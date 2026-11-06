# Forge Markers and forge-claim Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** One race-safe way to write and read machine state on GitHub issues (`agent_tools.forge_markers`) and an issue-claim CLI on top of it (`forge-claim acquire|renew|release|status`) so two sessions or hosts can never both deliver one issue (issue 623).

**Architecture:** A marker is an issue comment whose first line is `<!-- agent:<kind> v1 key=value ... -->`. `forge_markers` parses, renders, lists, posts, edits and deletes markers through `gh api` (token variables removed), and settles contention by the smallest live comment id after a post and a re-read (D1, D2). `forge_claim` keeps claims as `claim` markers and the `in-progress` label as a filter; `status` judges staleness only from server timestamps (D4, D5) and reports a stale claim with one `owner-action` marker whose checkbox the owner ticks to release it (D6).

**Tech stack:** Python 3 standard library (`subprocess`, `json`, `re`, `datetime`, `email.utils`, `argparse`), `unittest`, the fake `gh` of `tests/forge_world.py`, Nix launcher table `lib/agent-tools.nix`.

Issue: https://github.com/fagenorn/nix-config/issues/623 (parent issue 572). No spec: the issue body and this plan's `## Decisions` are the decision record.

## Global Constraints

- Base `258dfac3`. Only the files in the Task index change.
- Standard library only; `python/agent_tools/forge_markers.py` and `python/agent_tools/forge_claim.py` import no other `agent_tools` module.
- No host clock: neither module calls `time.time`, `datetime.now`, `datetime.utcnow`, `date.today` or `time.localtime`; "now" is the server `Date` header (D5).
- Every `gh` child runs with `GITHUB_TOKEN` and `GH_TOKEN` removed from its environment (the fake `gh` exits 65 otherwise).
- No project-specific literal (this repository's slug, branch names, host names, recipe names) in either module: they run in other projects.
- Out of scope: migrating `deliver-direct`, `deliver-standard` or `orchestrate-issues` to `forge-claim` (later slices of issue 572).
- Tests run from the worktree root as `env PYTHONPATH="$PWD/python" python3 -m unittest <test file> 2>&1 | tail -5`, foreground, timeout 600 s.
- Commits: subject `feat(issue-623): …` or `test(issue-623): …`, say "issue 623", never a bare `#623`, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never `just switch`, never push.
- sdd's final gate runs `just build` and `just agent-workflow-tests` once on the final head (timeout 3600 s each).

## Test seams

1. `tests/forge_world.py` `ForgeWorld`: the fake `gh` keyed on argv, extended by Task 1 with `respond_sequence` (answers consumed in order, the last one repeating) so successive identical listings can differ.
2. `forge_markers` functions called in-process inside a `ForgeWorld`, asserting returned values and `world.argvs("gh")`.
3. `forge_claim.main(argv) -> int` called in-process with stdout captured, asserting the printed JSON object, the exit code and `world.argvs("gh")`.
4. `tests/test_agent_tools_launchers.py` `LAUNCHER_FLOOR` and `just build` for the installed `forge-claim` launcher.

## Task index

Task 1 — Marker grammar, forge reads and writes, race-settled write — `python/agent_tools/forge_markers.py`, `tests/forge_world.py`, `tests/test_forge_markers.py` — full — [task-1.md](2026-11-06-issue-623-forge-claim.tasks/task-1.md)

Task 2 — `forge-claim acquire`, `renew`, `release` — `python/agent_tools/forge_claim.py`, `tests/test_forge_claim.py` — full — [task-2.md](2026-11-06-issue-623-forge-claim.tasks/task-2.md)

Task 3 — `forge-claim status`, staleness by server time, owner-action release box — `python/agent_tools/forge_claim.py`, `tests/test_forge_claim.py` — full — [task-3.md](2026-11-06-issue-623-forge-claim.tasks/task-3.md)

Task 4 — Install the launcher, join the gating suite, document the contract — `lib/agent-tools.nix`, `tests/test_agent_tools_launchers.py`, `justfile`, `python/README.md` — full — [task-4.md](2026-11-06-issue-623-forge-claim.tasks/task-4.md)

All four are `full`: Task 1 is a concurrency protocol, Tasks 2–3 a public CLI contract that mutates a forge, Task 4 the installed command set and the gating suite.

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_forge_markers.py::RaceTest` (table of post/re-read interleavings: exactly one live claim, loser `lost_to` with its comment deleted) |
| AC2 | code | Task 3 | `tests/test_forge_claim.py::StatusTest` (stale by server time, one `stale-claim` marker across repeat calls, `held_by` for another holder until ticked, clock patched to a wrong value with the same verdict) |
| AC3 | code | Task 2 | `tests/test_forge_claim.py::ReleaseRenewTest` (release removes `in-progress` only with no other live claim; renew PATCHes the same comment, no POST) |
| AC4 | code | Task 4 | `Agent Workflow Tests` CI job and `just build` green at the PR head; `tests/test_agent_tools_launchers.py` floor names `forge-claim` |

## Decisions

- **D1 Marker grammar.** First line fullmatches `<!-- agent:(?P<kind>[a-z][a-z0-9-]*) v1(?P<fields>( [a-z][a-z0-9_]*=[A-Za-z0-9._:/@+-]+)*) -->`; a repeated key or any other first line is not a marker. Line 2 is one human sentence; further lines (`extra`) are free. A marker is live unless it carries a `released` or `resolved` field. Rejected: JSON in the comment (unreadable to humans, harder to keep one line).
- **D2 Winner and write.** Among live markers of one kind whose fields include a match set, the smallest comment `id` (REST `id`, the `databaseId`) wins. `write` posts, re-lists, takes the contest over the re-read plus its own id, and deletes its own comment when it is not the winner. Safety assumes a listing reflects every comment created before the listing started. Rejected: host timestamps; a lock comment (needs the same protocol anyway).
- **D3 Renewal changes the body.** `renew` rewrites the first line with `renewed=<n+1>` so the edit always changes the body and the server moves `updated_at`. Rejected: re-PATCHing an identical body (no guarantee the timestamp moves).
- **D4 Branch activity needs a branch.** `acquire` and `renew` take an optional `--branch` recorded as the claim's `branch` field. Staleness activity is the latest of the claim's `updated_at`, the branch's last push (`repos/<slug>/activity?ref=refs/heads/<branch>&activity_type=push&per_page=1`, `timestamp`) and the `updated_at` of pull requests whose head is that branch. A claim with no branch counts only its own renewals. Rejected: guessing a branch from a naming convention (project-specific).
- **D5 Server now.** "Now" is the `Date` header of `gh api --include rate_limit` (free of rate cost). Stale means `now - activity >= 24 h`.
- **D6 Owner-action marker.** Kind `owner-action`, fields `issue`, `reason=stale-claim`, `claim=<claim comment id>`, sentence naming the holder, extra line `- [ ] Release this claim`. Posted with `write` (match on all three fields) only when no live one exists for that claim; posting also ensures and adds the `owner-action` label. A live one whose body has a line `- [x] Release this claim` (x either case) is honoured by the next `status` or `acquire`: the claim gets `released=owner-action`, the marker `resolved=released`, then `in-progress` is removed if no live claim remains and `owner-action` if no live owner-action marker remains.
- **D7 Labels.** A label is ensured by `POST repos/<slug>/labels` (HTTP 422 means it exists) before it is added; colours `in-progress` `FBCA04`, `owner-action` `D93F0B`. A label removal's HTTP 404 is success.
- **D8 Exit codes.** 0 success (`acquired`, `already_held`, `renewed`, `released`, and every `status` verdict), 3 contention (`acquire` → `held_by`/`lost_to`, `renew`/`release` → `not_held`), 1 forge error (`verdict: "error"`), 2 usage (argparse, no JSON).

---
