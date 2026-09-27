---
name: orchestrate-issues
description: Codex answer for "orchestrate issues X, Y, Z" — reports that multi-owner orchestration is unsupported on Codex and names the sequential /from-issue route. Never launches owners.
---

# orchestrate-issues — unsupported on Codex

Codex has no orchestration adapter: native Codex collaboration exposes no
pre-launch slot claim and no owner-completion event that `workflow-state` could
bind. Answer with the host's typed result instead of improvising a scheduler.

1. Run this once (if the bare `workflow-state` name does not resolve on PATH,
   use `~/.agents/bin/workflow-state`):

   ```text
   workflow-state host-route --route codex | artifact-budget validate-report --boundary workflow-response --input -
   ```

2. Return the validated result verbatim.
3. Name the supported sequential route: run `/from-issue <n> --auto` for each
   requested issue, one at a time, in the caller's order.

Never spawn owners, count threads, archive sessions, start an app-server, or
retry this answer.
