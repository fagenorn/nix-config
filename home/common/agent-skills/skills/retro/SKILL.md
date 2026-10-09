---
name: retro
description: Reviews a coding session and proposes fixes to the agent environment behind it. Use for a retro or post-mortem.
disable-model-invocation: true
---

A **retrospective** proposes fixes to the coding agent's **environment** so future runs go better. It does not grade the session or redo its task.

## Steps

### 1. Read the session

Use the session the user names, else the current one. Read primary sources, not memory:

- **Claude Code transcripts**: `~/.claude/projects/<cwd with / and . replaced by ->/<session-id>.jsonl`, subagent transcripts beside them.
- **Codex transcripts**: `~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-*.jsonl`.
- **Workflow evidence**, when the session ran this system's lifecycle: the run ledger and its attempt (`workflow-state`), the `sdd` task ledger and `progress.md`, review findings, and the issue and PR threads.

Transcripts are large: extract with `jq`/`grep` (user turns, tool calls with their sizes, tool errors, permission denials, retries), then read only the stretches around what you find. Each finding cites a session plus a turn or tool call.

### 2. Find candidates

- **Navigation**: the agent took long to find information; would a **navigation pointer** or an explicit dependency between files help?
- **Automated checks**: the agent made a mistake a check could catch. Read the repo's own check command and CI first, so an unwired or broken existing check is the finding. A repo with no **guardrail** (no pre-commit hook and no CI job running lint/typecheck/test) is itself a finding.
- **Coding standards**: the reviewer missed a mistake. A **mechanical** violation (fixed syntactic pattern, banned API, import shape, file location) gets a deterministic check in the repo's linter, a pre-commit hook or CI, whichever is cheapest. Reserve a written standard for **judgement calls** no check could replace.
- **Always-loaded guidance**: a large `CLAUDE.md`/`AGENTS.md` (repo or global) holds steering that belongs in standards, a skill or a check.
- **Tool economy**: an expensive tool call, or token-inefficient custom tooling (CLIs, MCPs, `~/.agents/bin` helpers).
- **No-ops**: instructions in steering files and skills that change no behavior.
- **Information access**: crucial information was unavailable (dev server logs, read-only access to a third-party service).
- **Workflow friction**: a skill or lifecycle helper cost turns: a repeated phase, a refused input, a stall or suspension, a handoff that lost state, or a guard or permission block on a legitimate command.

### 3. Route each candidate

Each candidate goes to exactly one home, decided before you propose the change:

- **Project**: the session's repository: its checks, `docs/standards/` shards (Layer 2), `CONTEXT.md`, ADRs and instruction source. Where `.agents/instructions/bootstrap.md` exists it is the source; `AGENTS.md` and the `CLAUDE.md` import line are generated from it by `resolve-project write-projections`.
- **Global**: the environment every project inherits, generated from the nix-config repository (`fagenorn/nix-config`); paths under Reference. `~/.claude/` and `~/.agents/` are build output that resets on rebuild, so never propose an edit there.

A friction that would recur in any project is global, even if one project showed it. A rule naming this repo's paths, tools or domain is project-scoped. Outside nix-config, a global finding is a proposal against nix-config, not an edit in the current repo.

### 4. Present

Order candidates by severity: cost per future session times how often it recurs. For each give a one-line title and category, the evidence, the home and exact file or check, and the change in one or two sentences. Write for a reader who did not watch the session. If the session went cleanly, say so.

Then stop. Change nothing until the user picks candidates; for each pick they choose between fixing it now and filing an issue (`to-issues`). A global pick from another project is filed on `fagenorn/nix-config`.

## Reference

### Implementation vs review

The implementer carries the most context pressure (exploration, code, debugging); the reviewer receives a diff and carries the least. So standards are imposed at review. The reviewer agents (`reviewer`, `reviewer-lite`) take their rubric from the dispatch brief, which pastes Layer 0 plus the shards whose globs match the change: a reviewer gains a rule through a new standards shard, not an agent-definition edit.

### Files

- **Always-loaded guidance**: in every agent's context, so reserve it for **navigation pointers**. Project `CLAUDE.md`/`AGENTS.md` come from `.agents/instructions/bootstrap.md` where it exists; the global `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` come from nix-config's `home/common/agent-guidance/AGENTS.md`.
- **Standards**: read at review. Layer 0 (`the-bar.md`) and Layer 1 (`stacks/`) are global, in nix-config's `home/common/agent-skills/standards/`. Layer 2 is the project's `docs/standards/`: deltas only, behind an index of at most 40 lines. A rule true for every project on a stack belongs in Layer 1.
- **Docs**: reference files pointed to from elsewhere; look for an existing doc before writing one.
- **Skills**: for docs whose description earns its place in every context, or for user-invoked commands. Global skills live in nix-config's `home/common/agent-skills/skills/`, Claude-only ones in `home/common/claude-code/skills/`.
- **Agents, settings and guard**: agent definitions in `home/common/claude-code/agents/`; settings and the permission allow surface in `home/common/claude-code/default.nix`; the `PreToolUse` lifecycle guard in `home/common/claude-code/lifecycle_guard.py`.
- **Helpers**: the `~/.agents/bin` commands are built from nix-config's `python/agent_tools/` and `home/common/agent-skills/scripts/`.

_Adapted from Matt Pocock's `retro` skill; provenance and the upstream MIT notice are recorded in [LICENSE](LICENSE)._
