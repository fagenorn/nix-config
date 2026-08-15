# Live bridge certification evidence

This file applies only when certifying that deployed bridge definitions are
current; it does not change the normal launch, read-only, timeout, output, or
fallback contracts in SKILL.md. Deploy the candidate collaboration skill, bridge
agent, and plugin first. Before any certification launch, the deployment/shipping
owner creates and seals an immutable deployment receipt. It names the
authoritative deployed paths, revisions, and `deployed_at` timestamps for all
three components, plus the assigned session ID; it cannot claim an actual start
time that has not happened yet.

At actual launch, the launcher creates an immutable session envelope and starts
the externally started fresh Claude session as one launch action. The envelope
records the same assigned session ID and the actual `started_at` timestamp. Give
both immutable objects to the fresh session as a read-only handoff. The fresh
session consumes both, verifies their session IDs match, independently resolves
the paths and revisions actually loaded, and verifies the loaded revisions match
the deployment receipt. An absent or mismatched receipt or envelope rejects
certification. These objects are external provenance only; do not add receipt or
envelope fields to the evidence schema. The session that performed deployment
can never certify its own deployment.

That fresh session creates one schema-version-1 JSON evidence artifact with
`schema_version` set to `1` and `kind` set to `bridge-smoke`, and must:

1. After the independent receipt comparison, record the authoritative revision
   and `deployed_at` timestamp for the loaded `skill`, `agent`, and `plugin`
   under `deployment`.
2. Record the assigned session ID and actual `started_at` timestamp from the
   session envelope under `session`, after verifying that ID against the
   deployment receipt. Reject stale evidence when the session began before any
   recorded deployment: **Reject stale sessions rather than treating them as
   current.**
3. Invoke exactly one `plan-review` and exactly one `diff-review` through this
   collaboration skill and its bridge agent. For each operation, record the
   bridge execution ID, job ID, observation time, terminal status, and matching
   result or failure under `agent_mediated`.
4. Record the corresponding direct transport probe under `direct`, with its own
   execution ID, observation time, terminal status, and result or failure. Keep
   `agent_mediated` distinct from `direct`: direct-only evidence cannot certify
   the bridge.
5. Preserve partial failures in the artifact. Record the bridge agent's own
   terminal failure before any allowed native fallback and never replace that
   failure with the fallback result.
6. Run `agent-evidence bridge <artifact.json>` (the helper at
   `~/.agents/bin/agent-evidence`; use the full path if the bare name does not
   resolve on PATH). Only after that exact command
   exits 0 may the session call the bridge current; a nonzero exit rejects
   certification and its diagnostics remain attached to the evidence record.
