# Keepalive Side Requests Leave a Pending Tool Alone Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A `no_tail_mark` request in a subagent conversation counts only as session activity while it is in flight, so a pending tool survives it and the conversation keeps being pinged until its own next request arrives.

**Architecture:** `Keepalive.observe` alone decides that a `no_tail_mark` request is a side request: it registers the side track's flight and gives it the sequence `None`, and leaves `last_request`, `epoch`, `pending_since` and the idle period alone (D2, D3). `_done`, `_apply`, `_settle`, `tick` and `_prune` do not change. A `None` sequence never equals the record's `epoch`, so a side track never marks a tool pending, and a ping built before a side request still applies its result. The `--keepalive` paragraph of `python/README.md` defines side and thread requests and says "request" of thread requests only.

**Tech stack:** Python 3 standard library (`threading`, `dataclasses`, `unittest`), Just, Nix.

Spec: `.agents/artifacts/specs/2026-11-02-issue-501-keepalive-unmarked-side-requests-design.md`. A bare "Dn" cites its `## Decision ledger`, and "#423 Dn" cites `2026-10-25-issue-423-cache-keepalive-design.md`. Issue: https://github.com/fagenorn/nix-config/issues/501.

## Global Constraints

- Base `a40b1270` (`origin/main` at planning). Spec commit `a00993dc`.
- Not edited (spec § Out of scope): `python/agent_tools/cache_proxy.py`, every `.nix` file, the `justfile`, `CLAUDE.md`, `AGENTS.md`, `home/common/claude-code/README.md`. `OUTCOMES`, `END_REASONS`, `DUE_AFTER`, `TICK_INTERVAL`, `WINDOW`, `MAX_CANDIDATES`, `PING_TIMEOUT`, `classify`, the log events and their fields stay as they are.
- Every existing test in `tests/test_cache_keepalive.py` stays byte-for-byte as it is and keeps passing (spec § Test seams). No test reads a `_Conversation` field (D4).
- Comments, docstrings and README sentences describe the code as it behaves at the task's commit. No `TODO` or `FIXME`. The module's `(Dn)` citations name #423's ledger, so code prose never cites this spec's D-numbers. Write "issue 501" there and in commit messages, never a bare `#501`.
- The live lifecycle guard reads a command's raw text, so no gate command or commit message pairs `git` with `push`.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit … -- <git commit args>`. Commits are SSH-signed and end with the session's trailer lines. Scratch files go under the root that `launch-scope scratch` prints. Never run `just switch`, and never push.
- **Keepalive tests** (timeout 300 s, about 20 s). Append `-k <pattern>` to focus. At base the command ends `Ran 50 tests` and `OK`:

  ```bash
  bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_cache_keepalive.py 2>&1 | tail -4'
  ```

- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each).

## Test seams

- `Keepalive` driven directly through `KeepaliveCase` in `tests/test_cache_keepalive.py`: its `FakeClock`, `exchange`, `due`, `events` and `ends`, with `send` against #422's `FakeUpstream` (D4).
- A side request is `document(tail_mark=False, …)` from the conversation's own agent id, placed 9 s after a `tool_use` completes or while the thread's response still streams (D4).
- Assertions read the pings returned and sent, the `keepalive_end` lines and, in one case, the public `Track.log_fields()` (D6). No proxy round-trip or command test is added.

## Delivery estimate and boundaries

All figures are estimates, from a scratch prototype run while planning. Four changed files plus this package and one spec ledger row: `cache_keepalive.py` about +18/−7 (the `observe` branch, the `Track` signature and three docstrings), `tests/test_cache_keepalive.py` about +82/−0 (one new class), `python/README.md` one line rewritten in place (about +0.6 KB), and the new acceptance record. One review package and one slice.

## Task index

Task 1 — Side requests leave a conversation's turn alone — `python/agent_tools/cache_keepalive.py`, `tests/test_cache_keepalive.py`, `python/README.md`, `.agents/artifacts/plans/2026-11-02-issue-501-keepalive-unmarked-side-requests.acceptance.md` — full — [task-1.md](2026-11-02-issue-501-keepalive-unmarked-side-requests.tasks/task-1.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_cache_keepalive.py::SideRequestTest::test_a_side_request_after_a_tool_use_keeps_the_tool_pending_until_its_result` (the pending state, and pings past the due where base ends the conversation `session_idle`), with `::test_a_side_request_while_the_tool_use_still_streams_leaves_it_pending` and `::test_a_side_request_while_a_ping_is_in_flight_does_not_supersede_it` (the request counter: a `tool_use` completion that stays current, a ping that is not superseded). Each fails at base `a40b1270` in Task 1 Step 2, which the acceptance record quotes. `just agent-workflow-tests` runs them, all green, at the final gate. |
| AC2 | evidence | Task 1 | Command: `just agent-costs --days 7 --report cache` on mbp. Condition (D5): run no sooner than 7 days after the first `just switch` on mbp that includes the merge, so the whole window follows it. Threshold: issue-owner "long foreground command" cache deaths ≤ 30 (127 in the 7 days to 2026-11-01). Task 1 writes acceptance-record row `AC2` as `not measured — post-merge (D5)`. The delivery never claims AC2: it stays evidence pending, and ship holds the issue for it. |

## Decisions

The plan rests on D1 (`no_tail_mark` is the only side outcome), D2 (`observe` registers only the side request's flight), D3 (the side sequence is `None`, set by `observe` alone, and `_done` and `_settle` stay unchanged), D4 (the seams and the failing-first cases) and D5 (AC2 is post-merge). Planning appends D6 (case 5 asserts the side track's `log_fields()`, and case 1 asserts the `resumed` line's `idle_s`).

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, `gpt-6-astra`, effort `xhigh`, thread `01a19af5-0378-7482-ab6e-b8cd3b0f12ed`), fresh isolated read-only mode, base `a40b1270`, plan at `d335703b`. Focus: whether the change reopens the overlapping-request races of #423 D27. No fallback. Findings: 0 Blocking, 0 Should fix; the Discussion section found no D27 regression and left only the planned test runs and AC2's post-switch measurement unverified, which Task 1 and the acceptance record already own. Accepted 0, rejected 0, deferred 0.

---
