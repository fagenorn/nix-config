# Keepalive End-Turn Ping Cap Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A subagent conversation whose last reply was `end_turn` ends `end_turn_cap` at the first due time at which its idle period already holds `END_TURN_PINGS` (2) pings, while a conversation pending a tool, or with any other last reply or none, keeps the full window.

**Architecture:** One new per-conversation field, `_Conversation.last_reply`, is cleared by `Keepalive.observe` for every thread request and set by `Keepalive._done` under the guard that already marks a tool pending (D1). `Keepalive.tick` checks the cap after `ceiling` and `session_idle` and before building a ping, and ends the conversation through `_end` with the new reason `end_turn_cap` (D3, D4). `python/README.md` § `cache-proxy` and `home/common/claude-code/README.md` § Cache proxy describe the cap.

**Tech stack:** Python 3 standard library (`threading`, `dataclasses`, `unittest`), Just, Nix.

Spec: `.agents/artifacts/specs/2026-11-02-issue-502-keepalive-end-turn-ping-cap-design.md`. A bare "Dn" cites its `## Decision ledger`, and "#423 Dn" cites `2026-10-25-issue-423-cache-keepalive-design.md`. Issue: https://github.com/fagenorn/nix-config/issues/502.

## Global Constraints

- Base `4e944cb4` (`origin/main` at planning). Spec commits `ebfc6903` and `9477ad62`, plus the planning commit that appends D8.
- Not edited (spec § Out of scope): `python/agent_tools/cache_proxy.py`, every `.nix` file, the `justfile`, `CLAUDE.md`, `AGENTS.md`, `docs/spikes/cache-proxy-keepalive.md` and the #423 spec. `OUTCOMES`, `DUE_AFTER`, `TICK_INTERVAL`, `WINDOW`, `MAX_CANDIDATES`, `PING_TIMEOUT`, `classify`, the log events and their fields stay as they are (D4).
- Every existing test in `tests/test_cache_keepalive.py` keeps passing. The only existing lines that change are case 2's one line (D6) and the move of `pinged` (D8). No test reads a `_Conversation` field (D6).
- Comments, docstrings and README sentences describe the code as it behaves at the task's commit. No `TODO` or `FIXME`. The module's bare `(Dn)` citations name #423's ledger, so code prose cites this spec as "issue 502 D2" and never as a bare D-number. Commit messages say "issue 502", never a bare `#502`.
- The live lifecycle guard reads a command's raw text, so no gate command or commit message pairs `git` with `push`.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit … -- <git commit args>`. Commits are SSH-signed and end with the session's trailer lines. Scratch files go under the root that `launch-scope scratch` prints. Never run `just switch`, and never push.
- **Keepalive tests** (timeout 300 s, about 25 s). Append `-k <pattern>` to focus. At base the command ends `Ran 56 tests` and `OK`:

  ```bash
  bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_cache_keepalive.py 2>&1 | tail -4'
  ```

- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each).

## Test seams

- `Keepalive` driven directly through `KeepaliveCase` in `tests/test_cache_keepalive.py`: its `FakeClock`, `exchange`, `busy_main`, `due`, `pinged`, `events` and `ends`, with `send` against #422's `FakeUpstream` (D6, D8).
- Assertions read the pings built and sent, the `keepalive_end` lines and the upstream's request count. No proxy round-trip or command test is added (D6).

## Delivery estimate and boundaries

All figures are estimates from a scratch prototype run while planning. Four changed files plus the new acceptance record: `cache_keepalive.py` about +23/−5, `tests/test_cache_keepalive.py` about +82/−8 (one new class, the moved helper, one changed line), `python/README.md` one line rewritten in place (about +0.6 KB), `home/common/claude-code/README.md` one line rewritten in place (about +0.2 KB). One review package and one slice.

## Task index

Task 1 — Cap pings after an end_turn reply — `python/agent_tools/cache_keepalive.py`, `tests/test_cache_keepalive.py`, `python/README.md`, `home/common/claude-code/README.md`, `.agents/artifacts/plans/2026-11-02-issue-502-keepalive-end-turn-ping-cap.acceptance.md` — full — [task-1.md](2026-11-02-issue-502-keepalive-end-turn-ping-cap.tasks/task-1.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_cache_keepalive.py::EndTurnCapTest::test_an_end_turn_reply_gets_two_pings_then_ends_end_turn_cap` (the issue's demo), `::test_each_idle_period_after_an_end_turn_reply_gets_its_own_two_pings`, `::test_a_side_request_never_lifts_the_cap` and `::test_pings_sent_while_the_reply_streams_count_toward_the_cap`, each failing at base `4e944cb4` in Task 1 Step 2, which the acceptance record quotes. The `tool_use` half is `tests/test_cache_keepalive.py::KeepaliveTest::test_pings_repeat_while_the_session_is_active_and_stop_at_the_ceiling` (13 pings, then `ceiling`). `just agent-workflow-tests` runs them, all green, at the final gate. |
| AC2 | evidence | Task 1 | Command: D7's reading of `~/Library/Logs/claude-cache-proxy.log` on mbp. Condition (D7): the 7 days from the first `listening` line written after the first `just switch` on mbp that includes the merge. Threshold: every idle period whose last reply is `end_turn` has at most 2 (`END_TURN_PINGS`) pings. Task 1 writes acceptance-record row `AC2` as `not measured — post-merge (D7)`. The delivery never claims AC2: it stays evidence pending, and ship holds the issue for it. |

## Decisions

The plan rests on D1 (the last reply and where it is set and cleared), D2 (`END_TURN_PINGS = 2` and its comment), D3 (the check order and the per-period count), D4 (`end_turn_cap`), D5 (the cap over #423 D22's children rule), D6 (the AC1 seams and cases) and D7 (AC2 is post-merge). Planning appends D8 (an eighth AC1 case pinning `observe`'s clear, and `pinged` moved into `KeepaliveCase`).

---
