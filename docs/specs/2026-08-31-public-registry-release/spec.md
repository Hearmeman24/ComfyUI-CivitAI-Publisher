# Public CivitAI Publisher release with NSFW-safe links

- **Status:** accepted
- **Work type:** feature
- **Authority:** implementation requested

## Review surface

### Outcome

The publisher continues to use `civitai.com` for API calls, but returns and reports a
`civitai.red/posts/<id>` link when the final reviewed NSFW value is true. The standalone node is
available from a public `Hearmeman24/ComfyUI-CivitAI-Publisher` repository and as the immutable
`0.1.0` release of `comfyui-civitai-publisher` under the active `hearmeman24` Comfy Registry
publisher. The same verified source is staged on the named RTX PRO 6000 pod without restarting
ComfyUI.

### Assumptions and hypotheses

- **Assumption:** the existing project id `comfyui-civitai-publisher` is the intended permanent
  Registry identity. **Impact if wrong:** Registry releases are immutable, so a different id must
  be chosen before the first publish rather than renamed afterward.
- **Assumption:** an authorized Comfy Registry API key can be supplied or created for the active
  `hearmeman24` publisher. **Impact if wrong:** the GitHub release and pod staging can complete, but
  Registry publication stops before any Registry write.

### Done when

- [ ] An approved NSFW post returns `https://civitai.red/posts/<id>`, while a non-NSFW post returns
  `https://civitai.com/posts/<id>` and every API request still targets `civitai.com` — source: user
  outcome and existing transport boundary
- [ ] A partial-post recovery error uses the same reviewed NSFW domain without leaking credentials
  — source: resiliency invariant
- [ ] The exact verified commit is public at `Hearmeman24/ComfyUI-CivitAI-Publisher` — source: user
  outcome
- [ ] Comfy Registry serves version `0.1.0` for publisher `hearmeman24` and node id
  `comfyui-civitai-publisher`, and the downloadable package contains the runtime but excludes test,
  script, and internal spec files — source: user outcome and Registry package contract
- [ ] The exact verified commit is staged on the RTX PRO 6000 box and ComfyUI is not restarted —
  source: user deployment request and operator boundary

## Execution contract

### Problem and evidence

The current client derives its returned post URL directly from the API origin. Consequently, an
NSFW publication returns `civitai.com` even though the requested public viewing domain is
`civitai.red`. The package already declares a public repository URL and semantic version, but it
does not declare the required Comfy Registry publisher metadata and has no Git remote.

- **Verified:** successful post URLs are currently formatted from `self._origin` regardless of
  NSFW state — evidence: `civitai_publisher/client.py:CivitAIClient.publish_post`
- **Verified:** partial-post recovery URLs are currently formatted from the API origin — evidence:
  `civitai_publisher/client.py:PartialPostError`
- **Verified:** the final reviewed NSFW value is passed into `publish_post` after the approval
  decision — evidence: `node.py:CivitAIPublisher._execute`
- **Verified:** package identity and version are already `comfyui-civitai-publisher` and `0.1.0`,
  while `[tool.comfy]` is absent — evidence: `pyproject.toml`

### Scope and non-goals

- **In scope:** user-facing success and recovery URL selection; regression coverage; Registry
  metadata and install/release documentation; package inspection; public repository creation and
  push; initial Registry publication and read-back; staging the release on the named pod.
- **Non-goals:** changing the CivitAI API host, changing NSFW levels or moderation behavior,
  publishing a CivitAI post during release verification, adding automatic GitHub-based Registry
  publishing, changing the node id after release, or restarting the remote ComfyUI process.

### Engineering envelope

- **Touched dimensions:** public interface=returned URL; security=Registry and CivitAI credentials;
  resiliency=partial-post recovery; deployment=GitHub, Registry, and one live RunPod checkout.
- **Effect on this contract:** API and public-view origins remain separate, credentials stay out of
  source/logs/package metadata, the immutable Registry release is verified before being claimed,
  and the pod update is staged with a rollback copy and no process restart.

### Owners, invariants, and approach

- **Authoritative owner:** the final `nsfw` argument to `CivitAIClient.publish_post` owns public-link
  domain selection; `_origin` continues to own API transport — evidence:
  `civitai_publisher/client.py:CivitAIClient.publish_post`
- **Must preserve:** injected non-production origins keep their own returned URLs; CivitAI API calls
  stay on the configured API origin; non-NSFW behavior stays on `civitai.com`; partial failures stay
  sanitized; Registry contents come only from tracked files allowed by `.comfyignore`; the remote
  process remains untouched.
- **Approach:** centralize post URL construction, map only the production API origin to
  `civitai.red` when NSFW is true, use that constructor on success and partial failure, then add the
  minimum current Registry metadata and release the already-versioned package.

### Verification

- **Regression seam:** client behavior tests prove the returned domain independently from API-call
  destinations and cover the partial-post recovery path.
- **Focused check:** `./scripts/verify fast`
- **Wider check:** `./scripts/verify full`
- **User boundary:** inspect a clean `comfy node pack`, read the pushed GitHub commit, read the
  Registry node/version API, and compile/test the staged pod tree without restarting ComfyUI.

### Rollout and recovery

- **Rollout:** land the tested URL change and release metadata in small local commits; create the
  public repository and push the exact commit to `main`; publish `0.1.0`; read back the Registry
  record/package; stage that commit on the pod with a dated backup.
- **Recovery:** GitHub can be corrected by a follow-up commit. Registry version `0.1.0` cannot be
  overwritten; any post-publication correction uses `0.1.1`. The pod backup remains available for
  an operator-approved rollback, and activation waits for a separate restart authorization.
