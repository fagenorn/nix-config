# ADR-console-103 — A manager reads its own saved output and worktree without a card

- **Status:** accepted
- **Decided in:** #1620

## Context

Two of the three permission cards raised in one hour on 22 Nov were the manager reading its own saved tool output with `sed -n`. ADR-console-100 D1 sends every Bash prompt the client would show to the owner's card, so the owner was asked to approve a read of the session's own files. This record amends that decision: an own read needs no card.

## Decision

The owner bound the first three: the rule fails closed, the lifecycle guard is untouched and the page does not change.

**D1. The rule sits in the `PermissionRequest` hook and fails closed.** `sprint permit --prompt` applies `own_reads.allowed` after it parses the input and before it resolves the sprint or asks the console. The hook fires only where the client would show a prompt, after the deny rules and every `PreToolUse` hook (the lifecycle guard, `sprint permit`), so the allow removes exactly the card and bypasses neither. The allow is the client's allow with no permission update (ADR-console-100 D2). The programs are exactly `sed -n` (never `-i` or another in-place flag), `head`, `tail`, `cat`, `grep` and `wc`. Any command the rule cannot fully parse, any path outside the two places, any write, redirection, pipe or substitution goes to the card as before. The `PreToolUse` path (`run_permit`) is unchanged.

**D2. The session's own folder is its `tool-results` directory, reached through genuine directories.** It is `<store>/<slug>/<session_id>/tool-results` for a transcript store `project_question_hook.transcript_dirs` names, checked by `session_results`, shared with the question hook. The slug, session and `tool-results` components must each be a directory and not a symlink; the session id is the hook input's `session_id` and must fullmatch `SESSION_NAME`. The question hook gains the same tightening.

**D3. The manager's own worktree is its project root, carried in the settings env.** The session runs in the project root with isolation off. The console writes the root as `CONSOLE_SPRINT_ROOT` (`manager.ROOT_ENV`) into the settings `env` at launch and at every wake (`_refresh_settings`); the hook never takes the input's `cwd` as the root, because the session can `cd`. A value inherited from the console's environment is dropped before the launch. With no absolute root only the session's own output is admitted. Containment is `project_question_hook._inside` against the root's real path.

**D4. The grammar is an allowlist over literal words, options first.** Words come from `permit.words`, which refuses any operator, redirection, expansion, glob, tilde or comment. Every option precedes the first positional word, because GNU tools permute arguments but stop at the first operand under `POSIXLY_CORRECT`. Each option is on its program's list; `--`, a lone `-` and every long option refuse. `sed` is only `sed -n <script> <path>...` with the script one line range ending in `p`. Every command names a path, and `grep` goes to the card when `GREP_OPTIONS` is set.

**D5. Relative paths resolve against the input's `cwd`**, which must be absolute. A quoted `~` is literal.

**D6. A hard-linked regular file goes to the card**, since a second name could be a file outside both places.

**D7. The hook input is parsed once and a request to leave the sandbox is refused before the rule runs.** `prompt_hook` returns the session, command, description and cwd. Its sandbox check is identity-strict: only an absent flag, `null` or `false` proceeds, so `0` is refused with `SANDBOX_TEXT` like `1`, and nothing is sent.

**D8. Resolution is physical and refuses process-relative links.** Each operand is walked component by component (`lstat`, `readlink`, `..` after links, at most 40 links); a missing or non-directory middle component goes to the card, as does any component on the filesystem of `/proc`, because `/proc/self/cwd`, `/proc/self/fd/N` and `/dev/fd/N` (a link into `/proc` on Linux) name the hook's own objects in the hook and the utility's in the read. `/dev` itself is not barred, so a scratch directory under `/dev/shm` still resolves; a device node outside the root refuses as a non-file.

## Consequences

- Residuals, not fixed here: a file swapped for a symlink between the check and the run (a check-then-run race every hook shares), and the Bash tool's shell state the hook cannot see (the owner's startup files, aliases and variables in the client's shell snapshot).
- A settings file gains `CONSOLE_SPRINT_ROOT` at the next launch or wake; until then a worktree read goes to the card and the session's own output is already admitted.
- The lifecycle guard, `permit.py`, the page and `run_permit` are untouched.
- Related: ADR-console-021, ADR-console-089, ADR-console-100, ADR-console-102.
