from __future__ import annotations

import asyncio
import unittest

from civitai_publisher.approval import ApprovalManager, ApprovalPayload, DecisionState


class ApprovalManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_reject_is_single_use_and_clears_pending(self):
        manager = ApprovalManager(id_factory=lambda: "approval-1")
        notices = []
        task = asyncio.create_task(
            manager.wait_for_decision(
                ApprovalPayload(node_id="9", title="Title", prompt="Prompt"),
                timeout_seconds=2,
                notify=notices.append,
            )
        )
        await asyncio.sleep(0)

        self.assertEqual([item["request_id"] for item in manager.pending_public()], ["approval-1"])
        self.assertNotIn("token", notices[0])
        self.assertTrue(manager.decide("approval-1", approved=False, edits={}))
        self.assertFalse(manager.decide("approval-1", approved=True, edits={}))

        decision = await task
        self.assertEqual(decision.state, DecisionState.REJECTED)
        self.assertEqual(manager.pending_public(), [])

    async def test_approval_returns_only_validated_review_edits(self):
        manager = ApprovalManager(id_factory=lambda: "approval-2")
        task = asyncio.create_task(
            manager.wait_for_decision(
                ApprovalPayload(node_id="9", title="Before", prompt="Old", tags=("one",), nsfw=False),
                timeout_seconds=2,
                notify=lambda _payload: None,
            )
        )
        await asyncio.sleep(0)
        self.assertTrue(manager.decide(
            "approval-2",
            approved=True,
            edits={
                "title": "  After  ",
                "prompt": "  New prompt  ",
                "tags": [" one ", "two", "", 42],
                "nsfw": True,
                "token": "must-not-pass",
                "request_id": "another-run",
            },
        ))

        decision = await task
        self.assertEqual(decision.state, DecisionState.APPROVED)
        self.assertEqual(decision.title, "After")
        self.assertEqual(decision.prompt, "New prompt")
        self.assertEqual(decision.tags, ("one", "two"))
        self.assertTrue(decision.nsfw)

    async def test_timeout_fails_closed_and_removes_request(self):
        manager = ApprovalManager(id_factory=lambda: "approval-timeout")
        closed = []
        decision = await manager.wait_for_decision(
            ApprovalPayload(node_id="1", title="", prompt=""),
            timeout_seconds=0.01,
            notify=lambda _payload: None,
            notify_closed=closed.append,
        )
        self.assertEqual(decision.state, DecisionState.TIMED_OUT)
        self.assertEqual(manager.pending_public(), [])
        self.assertEqual(closed, ["approval-timeout"])


if __name__ == "__main__":
    unittest.main()
