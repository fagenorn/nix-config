# Forge Markers and forge-claim Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** One race-safe way to write and read machine state on GitHub issues (`agent_tools.forge_markers`) and an issue-claim CLI on top of it (`forge-claim acquire|renew|release|status`) so two sessions or hosts can never both deliver one issue (issue 623).

**Architecture:** A marker is an issue comment whose first line is `<!-- agent:<kind> v1 key=value ... -->`. `forge_markers` parses, renders, lists, posts, edits and deletes markers through `gh api` (token variables removed), settles contention by the smallest live comment id after a post and a re-read (D1, D2), and ends a marker only by posting an append-only `end` marker that no later edit can undo (D9). `forge_claim` keeps claims as `claim` markers and the `in-progress` label as a filter; `status` judges staleness only from server timestamps (D4, D5) and reports a stale claim with one `owner-action` marker whose checkbox the owner ticks to release it, honoured only while the claim is still stale (D6, D10).

**Tech stack:** Python 3 standard library (`subprocess`, `json`, `re`, `datetime`, `email.utils`, `argparse`, `fcntl` in the test fake), `unittest`, the fake `gh` of `tests/forge_world.py`, Nix launcher table `lib/agent-tools.nix`.

Issue: https://github.com/fagenorn/nix-config/issues/623 (parent issue 572). No spec: the issue body and this plan's `## Decisions` are the decision record.

## Global Constraints

- Base `258dfac3`. Only the files in the Task index change.
- Standard library only. `python/agent_tools/forge_markers.py` imports no `agent_tools` module; `python/agent_tools/forge_claim.py` imports `agent_tools.forge_markers` and no other `agent_tools` module.
- No host clock: neither module calls `time.time`, `datetime.now`, `datetime.utcnow`, `date.today` or `time.localtime`; "now" is the server `Date` header (D5). Both modules bind the `datetime` class at module level by `from datetime import datetime, ...` (each adds `timedelta`/`timezone` as it needs) and never import the `datetime` module under another name, so `host_clock` (Test seams 5) reaches every spelling.
- Every `gh` child runs with `GITHUB_TOKEN` and `GH_TOKEN` removed from its environment (the fake `gh` exits 65 otherwise).
- No project-specific literal (this repository's slug, branch names, host names, recipe names) in either module: they run in other projects.
- Out of scope: migrating `deliver-direct`, `deliver-standard` or `orchestrate-issues` to `forge-claim` (later slices of issue 572).
- Tests run from the worktree root, foreground, timeout 600 s, with the test's own status preserved through the pipe: `bash -o pipefail -c 'env PYTHONPATH="$PWD/python" python3 -m unittest <test files> 2>&1 | tail -5'`. A failing or erroring test makes the command exit non-zero.
- Commits: subject `feat(issue-623): …` or `test(issue-623): …`, say "issue 623", never a bare `#623`, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never `just switch`, never push.
- sdd's final gate runs `just build` and `just agent-workflow-tests` once on the final head (timeout 3600 s each), unpiped or under `bash -o pipefail`.

## Test seams

1. `tests/forge_world.py` `ForgeWorld`: the fake `gh` keyed on argv, extended by Task 1 with a stateful comment store (`comment_store`, `stored`, `wait_cursor`): list, post, PATCH and DELETE of one issue's comments act on shared state, and an optional schedule forces the order of named store operations across concurrent callers.
2. `forge_markers` functions called in-process inside a `ForgeWorld`, asserting returned values, `world.stored()` and `world.argvs("gh")`.
3. `forge_claim.main(argv) -> int` called in-process with stdout captured for policy and clock rows; `python -m agent_tools.forge_claim` run as a child process (`subprocess`, the test's `PYTHONPATH`) for exit codes, the one-line JSON contract, usage errors and multi-process races (docs/standards/agent-helpers.md rule 5).
4. `tests/test_agent_tools_launchers.py` `LAUNCHER_FLOOR` and `just build` for the installed `forge-claim` launcher.
5. `tests/forge_world.py` `host_clock(instant, *modules)`: replaces each module's `datetime` name with a subclass whose `now`, `utcnow` and `today` return `instant`, and patches `time.time`, so a wrong host clock reaches every spelling the modules could use.

## Task index

Task 1 — Marker grammar, end markers, forge reads and writes, race-settled write, stateful fake — `python/agent_tools/forge_markers.py`, `tests/forge_world.py`, `tests/test_forge_markers.py` — full — [task-1.md](2026-11-06-issue-623-forge-claim.tasks/task-1.md)

Task 2 — `forge-claim acquire`, `renew`, `release`, JSON usage errors, owner-action retirement — `python/agent_tools/forge_claim.py`, `tests/test_forge_claim.py` — full — [task-2.md](2026-11-06-issue-623-forge-claim.tasks/task-2.md)

Task 3 — `forge-claim status`, staleness by server time, owner-action release box — `python/agent_tools/forge_claim.py`, `tests/test_forge_claim.py` — full — [task-3.md](2026-11-06-issue-623-forge-claim.tasks/task-3.md)

Task 4 — Install the launcher, join the gating suite, document the contract — `lib/agent-tools.nix`, `tests/test_agent_tools_launchers.py`, `justfile`, `python/README.md` — full — [task-4.md](2026-11-06-issue-623-forge-claim.tasks/task-4.md)

All four are `full`: Task 1 is a concurrency protocol, Tasks 2–3 a public CLI contract that mutates a forge, Task 4 the installed command set and the gating suite.

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_forge_markers.py::RaceTest` (two concurrent writers against the stateful fake under each post/re-read schedule: exactly one live claim in the final store, the loser's comment deleted and its result naming the winner; a read-before-post writer under the same harness leaves two live claims). The CLI `lost_to` verdict and exit 3 are pinned by Task 2's `CliTest::test_racing_acquires_leave_one_claim`. |
| AC2 | code | Task 3 | `tests/test_forge_claim.py::StatusTest` (stale by server time, one `stale-claim` marker across repeat calls, `held_by` for another holder until ticked, every verdict row repeated under `host_clock` at 1970 and 2100 with the same result) |
| AC3 | code | Task 2 | `tests/test_forge_claim.py::ReleaseRenewTest` (release removes `in-progress` only with no other live claim; renew PATCHes the same comment, no POST) |
| AC4 | code | Task 4 | `Agent Workflow Tests` CI job and `just build` green at the PR head; `tests/test_agent_tools_launchers.py` floor names `forge-claim` |

## Decisions

- **D1 Marker grammar.** First line fullmatches `<!-- agent:(?P<kind>[a-z][a-z0-9-]*) v1(?P<fields>( [a-z][a-z0-9_]*=[A-Za-z0-9._:/@+-]+)*) -->`; a repeated key or any other first line is not a marker. Line 2 is one human sentence; further lines (`extra`) are free. Liveness is D9. Rejected: JSON in the comment (unreadable to humans, harder to keep one line).
- **D2 Winner and write.** Among live markers of one kind whose fields include a match set, the smallest comment `id` (REST `id`, the `databaseId`) wins. `write` posts, re-lists, takes the contest over the re-read plus its own id, and deletes its own comment when it is not the winner. Safety assumes a listing reflects every comment created before the listing started. Rejected: host timestamps; a lock comment (needs the same protocol anyway).
- **D3 Renewal changes the body.** `renew` rewrites the first line with `renewed=<n+1>` so the edit always changes the body and the server moves `updated_at`, then re-lists and reports `not_held` when its claim has been ended meanwhile (D9). Rejected: re-PATCHing an identical body (no guarantee the timestamp moves).
- **D4 Branch activity needs a branch.** `acquire` and `renew` take an optional `--branch` recorded as the claim's `branch` field. Staleness activity is the latest of the claim's `updated_at`, the branch's last push (`repos/<slug>/activity?ref=refs/heads/<branch>&activity_type=push&per_page=1`, `timestamp`) and the `updated_at` of pull requests whose head is that branch. A claim with no branch counts only its own renewals. Rejected: guessing a branch from a naming convention (project-specific).
- **D5 Server now.** "Now" is the `Date` header of `gh api --include rate_limit` (free of rate cost). Stale means `now - activity >= 24 h`.
- **D6 Owner-action marker.** Kind `owner-action`, fields `issue`, `reason=stale-claim`, `claim=<claim comment id>`, sentence naming the holder, extra line `- [ ] Release this claim`. Posted with `write` (match on all three fields) only when no live one exists for that claim. Every `status` call whose verdict is `stale` ensures and adds the `owner-action` label (both idempotent), so a label call that failed after the post is repaired by the next call. A live one whose body has a line `- [x] Release this claim` (x either case) is honoured by the next `status` or `acquire` only when the claim it names is live and still stale by D4/D5 at that moment: the claim is ended (D9, reason `owner-action`) and edited to `released=owner-action`, the marker is ended (reason `released`). A ticked box on a claim that is no longer stale is ended (reason `renewed`) without releasing anything; on a claim already ended, it is ended (reason `released`).
- **D7 Labels.** A label is ensured by `POST repos/<slug>/labels` (HTTP 422 means it exists) before it is added; colours `in-progress` `FBCA04`, `owner-action` `D93F0B`. A label removal's HTTP 404 is success.
- **D8 Exit codes and output.** Every call, a usage error included, prints exactly one JSON object on one stdout line. 0 success (`acquired`, `already_held`, `renewed`, `released`, and every `status` verdict), 3 contention (`acquire` → `held_by`/`lost_to`, `renew`/`release` → `not_held`), 1 forge error (`verdict: "error"`, `error` = the `ForgeError` code), 2 usage (`verdict: "error"`, `error: "usage"`, `detail` = the parser's message). `-h`/`--help` alone prints argparse help text and exits 0.
- **D9 Ending is append-only.** A marker is ended by posting an `end` marker, `render("end", {"of": "<id>", "reason": "<reason>"}, "Ends marker comment <id> (<reason>).")`; nothing edits or deletes an `end` marker. A marker is live when it is not itself an `end` marker, carries no `released` field, and no `end` marker in the same listing names its id. `release` posts the `end` first and then edits the claim to `released=<reason>` (the issue's readable field); a delayed `renew` PATCH that rewrites the body from an older read can drop that field but never the `end`, so a released claim cannot come back. Rejected: a body-only `released` field (a concurrent PATCH erases it — GitHub comment edits have no compare-and-swap); deleting the claim (loses the record).
- **D10 Owner-action retirement.** `renew` and `release` end every live `owner-action` naming their claim (reasons `renewed`, `released`); a `status` whose verdict is `free` or `held_by` ends every live `owner-action` of the issue (reason `renewed` when its claim is live, else `released`). A call that ends one and leaves no live `owner-action` on the issue removes the `owner-action` label. Residual window, accepted: an honour that read a ticked box just before the holder's renewal can still end the claim; the holder's `renew` then reports `not_held` (D3), so holders run `renew` before each irreversible step and stop on `not_held`.

---
