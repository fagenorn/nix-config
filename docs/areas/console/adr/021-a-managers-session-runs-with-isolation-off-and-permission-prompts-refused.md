# ADR-console-021 — A manager's session runs with the background isolation guard off and permission prompts refused

- **Status:** accepted
- **Decided in:** #835, #973

## Context

ADR-console-015 starts a sprint's manager as a background Claude Code session (`claude --bg`) with a per-sprint settings file that holds only the sprint's id and secret as environment. The first sprint run end to end on a host stopped at its first delivery, for two reasons. The client blocks writes to the shared checkout from the subagents of a background session that has not moved into a worktree of its own, and a delivery keeps its plan files in the git directory of its worktree, which is part of the shared checkout: the plan step was refused. The manager then tried to enter the delivery's worktree, and the client asked for a permission in the session's terminal. Nobody watches a manager's session (ADR-console-004: a session waiting in its terminal is answered there), so the prompt stayed open for good, the sprint read quiet and the idle nudge of ADR-console-020 did not apply, because the session was blocked, not idle.

## Decision

**Two settings members.** The settings file the console writes for a manager's session (the sprint's `settings file` beside its secret) holds, besides the sprint's environment, `"worktree": {"bgIsolation": "none"}` and one `PermissionRequest` command hook without a matcher. The guard is off because a manager writes no code by contract (#835) and every delivery makes and works in its own worktree, so the guard's purpose is already met, and with it on a manager cannot run a delivery at all.

**Prompts are refused.** The hook is a plain shell command with no interpreter start that prints one JSON object: the client's deny decision for `PermissionRequest` with one fixed sentence, `Nobody watches this session, so the permission prompt was refused: do the step another way that needs no permission, or bring the choice to the owner with `sprint ask`.` It answers every prompt of the session and of its subagents, the question tool included, so a refused step returns to the manager as an ordinary failure it can act on. Both members were tried on a host before this decision.

**Written again.** The file is written before every launch and again before every wake of a stopped or removed session, whether the wake passes the session's name and settings (ADR-console-017's removed record) or is bare, so a sprint started before this decision gets both members the next time its manager is woken. A file that cannot be written fails the wake with `cannot write the manager's settings: <reason>` and the wake is not sent.

**The contract.** The manager's contract gains two sentences: a permission prompt in the session is refused automatically, so never wait for one; and never enter or create a worktree, because a delivery makes its own.

**Where the refusal lives.** The console's own hooks keep answering with an empty reply and decide nothing (ADR-console-004). The refusal is in the manager's settings file, not in a console route, so it holds while the console is down.

## Consequences

- A manager cannot be asked for a permission by the client at all: every tool call that needs one fails with the fixed sentence, so a manager that needs a permission-gated step reaches the owner only through `sprint ask`.
- A manager session no longer shows `waiting for a permission` in the console.
- A delivery run by a manager can write into the git directory of its own worktree.
- A settings file written before this decision keeps its old content until the sprint's manager is next launched or woken.
- A bare wake of a session whose saved options name the settings file picks up the refreshed content only if the client re-reads the file when it resumes; a wake with name and settings always does.
