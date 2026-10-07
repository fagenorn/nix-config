---
name: retro
description: Review a coding session and propose fixes to the agent environment that ran it. Use for a retro or post-mortem.
disable-model-invocation: true
---

The user has asked for a **retrospective**. You are suggesting improvements to the coding agent's **environment** to improve future runs. The aim is to fix the environment, not to grade the session. You are not redoing the session's task.

## Steps

### 1. Read the session

If the user names a session, use that one. Otherwise use the current one. Read primary sources, not your memory of them:

- **Claude Code transcripts**: `~/.claude/projects/<cwd with / and . replaced by ->/<session-id>.jsonl`. Subagent transcripts are in the same directory.
- **Codex transcripts**: `~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-*.jsonl`.
- **Workflow evidence**, when the session ran this system's lifecycle: the run ledger and the attempt it records (`workflow-state`), the `sdd` task ledger and `progress.md`, review findings, and the issue and PR threads.

Transcripts are large, so extract from them instead of reading them whole. Use `jq`/`grep` to pull the user turns, tool calls with their sizes, tool errors, permission denials, and retries. Then read only the stretches around what you find. Each finding cites its evidence as a session plus a turn or tool call.

### 2. Find candidates

Look for candidates for improvement in these categories.

- **Navigation**: how easy was it for the agent to find the right files? Are there hidden dependencies between files? Would a **navigation pointer** make it easier? _Use when_ the session took a long time to find a piece of information.
- **Automated checks**: are there automated checks that could catch errors the agent made? Linting, typing, tests, filesystem linters? Read the repo's own check command first (its `justfile`, `package.json` or build-tool `lint`/`check` scripts, its CI workflow), so a check that already exists but sits unwired or silently broken is the finding, not a reinvention. A repo with no **guardrail** (no pre-commit hook and no CI job running its lint/typecheck/test command) is itself a finding. An un-linted repo is a standing missed opportunity, not a neutral default. _Use when_ the agent made a mistake an automated check could have caught, or the repo has no guardrail at all.
- **Coding standards**: should the **reviewer agent** be given a new rule to enforce? Should an existing rule be removed or clarified? Classify the violation first. A **mechanical** violation (a fixed syntactic pattern, a banned API, an import shape, a file-location rule) gets a deterministic check, full stop: a custom rule in the repo's own linter, a new pre-commit hook, or a new CI job, whichever the repo's language and existing guardrail make cheapest. Default to building the check over writing the rule. Reserve a written standard for genuine **judgement calls**: cross-file consistency, "matches the surrounding style," anything no guardrail could ever substitute for. _Use when_ the reviewer agent failed to catch a mistake.
- **Always-loaded guidance**: are there steering instructions that should be moved to standards, a skill, or automated checks instead? _Use when_ a `CLAUDE.md`/`AGENTS.md` is particularly large, in the repo or in the global scope.
- **Tool economy**: did the agent make expensive tool calls that could be streamlined? Is any custom tooling (CLIs, MCPs, `~/.agents/bin` helpers) particularly token-inefficient? _Use when_ the agent made an expensive tool call.
- **No-ops**: look for instructions in steering files and skills that don't modify the agent's behavior. _Use when_ the steering files are large and unwieldy.
- **Information access**: look for opportunities to increase the agent's access to information, such as teeing dev server logs or giving read-only access to third-party services. _Use when_ a crucial piece of information was not available to the agent.
- **Workflow friction**: did a skill's own procedure cost the session? Look for a phase repeated, a helper refused the agent's input, a stall or suspension, a handoff that lost state, or a permission prompt or guard block on a legitimate command. _Use when_ the session ran a skill or the lifecycle helpers and spent turns fighting them.

### 3. Route each candidate

Each candidate goes to exactly one home. Decide the home before you propose the change.

- **Project**: the fix belongs to the repository the session worked in. Its checks, its `docs/standards/` shards (Layer 2), its `CONTEXT.md`, ADRs, and its instruction source. When the repo has `.agents/instructions/bootstrap.md`, that file is the source. `AGENTS.md` and the import line in `CLAUDE.md` are generated from it by `resolve-project write-projections`, so propose edits to the source.
- **Global**: the fix belongs to the agent environment every project inherits. That is the skills, the global guidance, the agent definitions, the Layer 0/1 standards, the `~/.agents/bin` helpers, and Claude Code's settings and permission guard. All of it is generated from the nix-config repository (`fagenorn/nix-config`). Its paths are listed under Reference below. `~/.claude/` and `~/.agents/` are build output and reset on rebuild, so never propose an edit there.

A friction that would recur in any project is global, even when only one project showed it. A rule that names this repo's paths, tools, or domain is project-scoped. When the session ran outside nix-config, a global finding is a proposal against nix-config, not an edit you make in the current repo.

### 4. Present

Present the candidates in order of severity. Severity is the cost the issue imposes per future session multiplied by how often it recurs. For each candidate give:

- a one-line title and its category;
- the evidence (session plus turn or tool call);
- the home (**project** or **global**) and the exact file or check to change;
- the proposed change, in one or two sentences.

Write for a reader who did not watch the session. Be concrete. Don't pad: if the session went cleanly, say so and present only what you found, even if that is nothing.

Then stop. Change nothing until the user picks which candidates to act on. For each pick, the user decides between fixing it now and filing an issue (`to-issues`). A global pick filed from another project is filed on `fagenorn/nix-config`.

## Reference

### Implementation vs Review

Remember that all work goes through two stages: implementation and review. The implementation agent has the most **context pressure**. They are responsible for exploration, writing code, and debugging failures.

The review agent has the least context pressure. It receives a diff, so no exploration is needed, and it often does not need to write code or debug.

This means that the review agent should be responsible for imposing coding standards, not the implementation agent. Here the reviewer agents (`reviewer`, `reviewer-lite`) take their rubric from the dispatch brief. That brief pastes Layer 0 of the standards plus the shards whose globs match the change. So a reviewer gains a rule by gaining a standards shard, not by editing the agent definition.

### Files

- **Always-loaded guidance**: these files are pushed into the context window of every agent, so use them incredibly sparingly, usually only for **navigation pointers**. The project's `CLAUDE.md`/`AGENTS.md` come from `.agents/instructions/bootstrap.md` where it exists. The global `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` come from nix-config's `home/common/agent-guidance/AGENTS.md`.
- **Standards**: these are read during review, not implementation. Layer 0 (`the-bar.md`) and Layer 1 (`stacks/`) are global, sourced from nix-config's `home/common/agent-skills/standards/`. Layer 2 is the project's `docs/standards/`, which holds deltas only, behind an index of at most 40 lines. A rule true for every project on a stack belongs in Layer 1.
- **Docs**: use docs as reference files, pointed to by other files. Look for existing docs before writing new ones.
- **Skills**: use skills for docs, since their description goes into the agent's context window, or for user-invoked commands. Global skills come from nix-config's `home/common/agent-skills/skills/`. Claude-only skills come from `home/common/claude-code/skills/`.
- **Agents, settings and guard**: the agent definitions are in nix-config's `home/common/claude-code/agents/`. Settings and the permission allow surface are in `home/common/claude-code/default.nix`. The `PreToolUse` lifecycle guard is in `home/common/claude-code/lifecycle_guard.py`.
- **Helpers**: the `~/.agents/bin` commands are built from nix-config's `python/agent_tools/` package and `home/common/agent-skills/scripts/`.

_Adapted from Matt Pocock's `retro` skill; provenance and the upstream MIT notice are recorded in [LICENSE](LICENSE)._
