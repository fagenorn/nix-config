# Constant-Size Tool Closure Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The retained bundle's `tool` group binds the whole `agent_tools` package by one digest, so a fresh derivation fits the retained tier's five-file bound again (166,257 B against 196,608 B) with no cap raised, and the committed evidence is re-derived in the new shape.

**Architecture:** Task 1 changes the encoding and its one validator: `derive_bundle` writes `files_sha256 = telemetry_digest(rows)` where it spread the rows, and `validate_bundle` accepts only the closed five-member group (D1–D3). Its reviewed head is the tool commit `T`. Task 2 derives the committed bundle again at `T` on a private quiescent root, re-pins `ANCHOR_SHA256` and `TOOL_COMMIT`, and runs the retained tier in full (D4, D5, D8).

**Tech stack:** Python 3 standard library, `unittest`, Git plumbing, canonical JSON, Nix, just.

Spec: `.agents/artifacts/specs/2026-11-02-issue-556-constant-size-tool-closure-design.md`; a bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/556.

## Global Constraints

- Base `e692c9685c3e4b08f55c327c5f2b8c699fc95bc4` (tree `587dbde15f26f7d6f05713cb7d6848f20041b2e2`, `python` tree `c20fb0aa5cc1641f0366524b01bf44967bbd465a`), the immutable delivery base. Spec commits `7321b37b` and `28299126`, then this plan's commit.
- Standard library only. No new module, command, option, recipe or test seam (spec § *Test seams*); no public name added to `review_witness` or `review_derivation` (D3).
- No cap, bound or decode limit moves: `MEMBER_MAX_BYTES`, `ANCHOR_MAX_BYTES` (32,768), the tier's `MEMBER_CAP` and `BUNDLE_CAP`, CORE's policy (D1, D7). No test asserts an exact file size (CP10, CP11).
- Not edited: point-in-time records (earlier specs and plans, the 226 audit, issue 235's recorded digest) (D6); the three fixture payloads, which must come out of Task 2 byte for byte unchanged; `home/common/agent-skills/tests/test_workflow_skill_contracts.py`.
- Comments, docstrings and README sentences describe the code as it behaves at the task's commit. No `TODO` or `FIXME`. Code prose cites the issue as "issue 556" or "#556", never a bare `Dn`.
- After Task 2, a fix that changes the bundle's encoding, its derivation or validation code, or the review-package policy digest repeats Task 2 at the new `T`; a change that only moves the package, a merge from `main` included, leaves the evidence bound to `T` (D8).
- Every retained run reads a private quiescent root built by `make_root` (Task 1 Step 6, Task 2 Step 2) under the runner's `launch-scope scratch` (D10), never the shared checkout; a changed root voids the run (RP11).
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit` with the same three values; commits are SSH-signed, subjects at most 64 bytes, ending with the session's trailer lines. Scratch goes under the root `launch-scope scratch` prints. No gate command or commit message pairs `git` with `push`. Never run `just switch`, and never push.
- Final gate (sdd runs it once, on the final head, by an actor that did not run Task 2's derivation A): `just build` and `just agent-workflow-tests`, timeout 3600 s each; then, on a fresh root from Task 2's `make_root`, Task 2's `basis` and `just agent-retained-tests <root>` with timeout 14400 s, checked as Task 2 Step 7 checks it. That last run is derivation B (D5 step 4). A skip, a void or a failure is not acceptance.

## Test seams

- `tests/test_review_witness.py` (portable): the closed tool shape, `files` rows refused beside or in place of the digest, a missing or malformed digest, all `component_mismatch`; `tool_closure` rows and `verify_running_closure` unchanged.
- `tests/test_review_derivation.py` (portable, real package via `tool_fixture`): a derived anchor's tool group is exactly the five members and its digest is `telemetry_digest` of `tool_closure`'s rows.
- `tests/test_review_evidence.py` (portable, committed copy): unchanged cases over the re-issued copy.
- `tests/test_review_retained_full.py` and `tests/test_agent_tools_launchers.py` (tier, under `just agent-retained-tests <root>`): the cap case, two byte-identical derivations, reproduction at `T`, built-and-source parity; no new case (D7).
- Suites run as `PYTHONPATH=python python3 -m unittest <path>`; commands as `python -m agent_tools.<module>`. Verification command IDs: `nix-build`, `agent-workflow-tests`.

## Delivery estimate and boundaries

Figures come from a scratch prototype of both tasks at the base, on a private root built as D10 says. The cap case failed there at 203,078 B before Task 1. Task 1's tests failed as Step 2 lists before its source change, and its three focused suites then passed (52 tests); the committed-copy suite failed as D9 expects. Derivation A at the prototype's `T` took 2 min 13 s, left the root unchanged, reproduced the three payloads byte for byte and wrote 166,257 B (anchor 4,671 B, witness 6,794 B). With those bytes and literals, the committed-copy suite, the legacy-surface scan and the sealed replay passed, and on the same root the tier's cap, twin-derivation and reproduction-at-`T` cases passed (3 tests, 10 min). Task 1 is 57 lines added and 22 deleted over six paths, about 30 KB of records; Task 2's records are about 43 KB, nearly all the two one-line JSON replacements. Forecasts add 20–80 % for fix rounds.

One boundary, `all`. Task 2 needs `T` from Task 1's reviewed head (D5). Neither task meets acceptance alone, and between them the committed-copy suites are red by construction (D9).

## Task index

Task 1 — The tool group binds the closure by one digest — `python/agent_tools/review_witness.py`, `python/agent_tools/review_derivation.py`, `python/README.md`, `tests/test_review_witness.py`, `tests/test_review_derivation.py`, `tests/test_review_retained_full.py` — full — [task-1.md](2026-11-02-issue-556-constant-size-tool-closure.tasks/task-1.md)

Task 2 — Re-issue the committed evidence at `T` — `tests/fixtures/retained-review-evidence/derivation-anchor.json`, `tests/fixtures/retained-review-evidence/derivation-witness.json`, `tests/retained_evidence_test_support.py` — full — [task-2.md](2026-11-02-issue-556-constant-size-tool-closure.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence (classified) | Task 2 | Command: `just agent-retained-tests "$ROOT"` (timeout 14400 s) in Task 2 Step 7. Conditions: `$ROOT` built fresh by `make_root` (D10), `basis` clean, root digest unchanged, at Task 2's head; repeated by the final gate at the final head as derivation B (D5 step 4). Threshold: exit 0 under the recipe's no-skip rule, last log line `OK`, and `test_bundle_files_fit_the_whole_record_caps`, `test_committed_evidence_reproduces_with_the_reviewed_tool` and `test_committed_evidence_replays_alike_from_source_and_built` each `... ok`. The implementer fills acceptance-record row `AC1`. |
| AC2 | code (classified) | Task 1 | Task 1 Step 4's bound checks: `git diff --quiet` of `python/agent_tools/review_expansion.py` and `home/common/agent-skills/artifact-budget-policy.json` against the base, and the `MEMBER_CAP, BUNDLE_CAP = 65536, 3 * 65536` and `ANCHOR_MAX_BYTES = 32768` lines. `tests/test_review_witness.py` `test_authenticated_bundle_is_the_anchor_and_its_four_raw_members` pins `ANCHOR_MAX_BYTES` and `MEMBER_MAX_BYTES`. No ledger row raises a cap (D1, D7). |
| AC3 | code (classified) | Task 2 | Task 2 Step 7's recipe runs `just build` first; sdd's final gate runs `just build` and `just agent-workflow-tests` at the final head, each exit 0. |

## Decisions

The plan rests on the spec's D1–D8. Planning appends D9 (two tasks, the red window at `T` and each task's retained gate) and D10 (the private retained root).

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, gpt-6-astra, xhigh), fresh isolated read-only thread, no focus, no fallback. Base `e692c9685c3e4b08f55c327c5f2b8c699fc95bc4`, plan head `a638d4aa`. Accepted 0, rejected 1, deferred 0.

- B1 (acceptance record absent from the forecast): rejected. The forecast's `process_package` is a closed `{spec, plan, tasks}` object (`python/agent_tools/review_forecast.py:83`, `:94`), so the current schema has no slot for `<plan stem>.acceptance.md`. sdd writes and commits that record after the last `sdd-gate next`, beside the plan, as the issue-544 and issue-547 deliveries did with forecasts of this same shape.

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"e692c9685c3e4b08f55c327c5f2b8c699fc95bc4","kind":"git-range-ownership/v1","process_ranges":[],"tree":"587dbde15f26f7d6f05713cb7d6848f20041b2e2"},"boundaries":[{"acceptance":"Issue 556 complete: AC1-AC3 green under the focused suites, the retained tier on a private quiescent root, just agent-workflow-tests and just build","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2"],"process_package":{"plan":".agents/artifacts/plans/2026-11-02-issue-556-constant-size-tool-closure.md","spec":".agents/artifacts/specs/2026-11-02-issue-556-constant-size-tool-closure-design.md","tasks":[".agents/artifacts/plans/2026-11-02-issue-556-constant-size-tool-closure.tasks/task-1.md",".agents/artifacts/plans/2026-11-02-issue-556-constant-size-tool-closure.tasks/task-2.md"]},"tasks":[1,2]}],"delivery_base":"e692c9685c3e4b08f55c327c5f2b8c699fc95bc4","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":320,"boundary":"all","deleted_lines":0,"record_bytes":30720,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":2,"owner":0,"path":".agents/artifacts/specs/2026-11-02-issue-556-constant-size-tool-closure-design.md"},{"bounds":[{"added_lines":110,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-556-constant-size-tool-closure.md"},{"bounds":[{"added_lines":220,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-556-constant-size-tool-closure.tasks/task-1.md"},{"bounds":[{"added_lines":230,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-556-constant-size-tool-closure.tasks/task-2.md"}],"proposed_boundary":"all","schema_version":3}
```
