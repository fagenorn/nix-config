# Issue 254 Compact Retained Encodings Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill, one implementer per task and a review between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Give the retained `issue-121.json` and `issue-100-derived.json` payloads compact encodings that keep every fact, so that each of the five bundle files is one whole review record under CORE's unchanged caps.

**Architecture:** Each model module keeps SOURCE's Git derivation as `model_*` and gains a pure `compact_*`/`expand_*` pair; `derive_*` returns the payload and `validate_*` returns the model. The witness digests the models, and replay reads them. The [spec](../specs/2026-10-04-issue-254-compact-retained-encodings-design.md) owns every contract and the ledger CP1–CP20; it cites the SOURCE and REPLAY specs for the rest.

**Tech stack:** Python standard library, Git plumbing, canonical JSON, unittest, Nix, just.

## Global Constraints

- Design identity `DP234-COMPACT`. The immutable `DELIVERY_BASE` is `7e17c8196569b0a96950f07ff886884690ffa224`. Every gate covers every later product and process commit.
- Caps do not move: 65,536 B per member, eight members, 524,288 B in all. No cap, bound, packing-policy or generated-exemption change, no split file, no omitted or truncated fact (parent D3).
- No new module, command, option or bundle file under `python/`. `MEMBER_MAX_BYTES` and `ANCHOR_MAX_BYTES` stay decode bounds, and the Task-7 table, its validator and its bytes are untouched (CP10). Both command shells keep their options, exits and stderr lines.
- The closed error codes are the published ones; no code is added (CP8). Pin faults keep `invalid_pins` and `assignment_mismatch`.
- Agent-helper standards 1–5 (`docs/standards/agent-helpers.md`).
- No CLAUDE.md edit. Task 3 changes no `python/` byte; any later `python/` change repeats G2, its post and G0.
- Nothing writes the retained root, its object store, the issue-100 archive, parent evidence or lifecycle state, and no ref is added.
- Size bounds: every changed file stays one whole review record within its task's forecast. An actual record above its bound needs a committed forecast revision and a renewed G0, never truncation or a lowered bound.
- Commits are SSH-signed and end with the session's trailer lines. Every subject is at most 64 UTF-8 bytes, checked before committing. Code and docstrings describe verified behavior.
- Out of scope: the spec's § *Out of scope*.

## Test seams

- Suites run as `PYTHONPATH=python python3 -m unittest tests.<module>` and import modules normally; commands run as `python -m agent_tools.<module>`. Only `tests/test_agent_tools_launchers.py` touches built launchers, and it imports no `agent_tools` outside the retained recipe (CP18).
- Temporary real Git repositories through `tests/retained_review_test_support.py`, unchanged; `source_budget_env` stages the source budget helper.
- A forged case changes a model or a payload and, where it needs one, calls `compact_*`; no test reads a private name. Published forged-model cases reach validation through `compact_*` (CP14).
- Payload-level cases live in two new portable suites, `test_review_compact121` and `test_review_compact100`, listed in `agent-workflow-tests` (CP15). The full-shape classes run only under `just agent-retained-tests <root>`, where a skip fails the recipe (RP10).
- Test-only trust injection is a direct `validate_bundle` call with a rebuilt witness and anchor, or the replay command under the forger's own digest (RP7). New built replay parity runs are sealed: a scratch `HOME` and a `PATH` of one empty directory (CP19).
- Verification command IDs: `agent-workflow-tests` and `nix-build`, run in this worktree.

## Delivery estimate and boundaries

These are estimates (parent D15, RP14). Product: fourteen paths in three tasks, two of them new, about 249 KB of forecast records; five paths carry two ordered cumulative contributions. Process: the spec, this root and three members, about 157 KB. Growth risk sits in the two model modules.

There is one boundary, `compact`. If G0 returns exit 3, the split is by model: Task 1 alone, then Task 2 with Task 3 (CP12). Subject reserves are two 64-byte subjects per task and ten for process; a second fix round needs one ruling that adds one subject.

## Task index

Task 1 — Issue-121 payload, schema version 4 — python/agent_tools/review_issue121.py, python/agent_tools/review_witness.py, python/agent_tools/review_derivation.py, python/agent_tools/review_replay.py, tests/test_review_compact121.py, tests/test_review_issue121.py, tests/test_review_witness.py, tests/test_review_replay.py, justfile — full — [task-1.md](2026-10-04-issue-254-compact-retained-encodings.tasks/task-1.md)
Task 2 — Issue-100 payload, schema version 2 — python/agent_tools/review_issue100.py, python/agent_tools/review_witness.py, python/agent_tools/review_derivation.py, tests/test_review_compact100.py, tests/test_review_issue100.py, tests/test_review_witness.py, tests/test_review_replay.py, justfile — full — [task-2.md](2026-10-04-issue-254-compact-retained-encodings.tasks/task-2.md)
Task 3 — Built parity and the full-shape tier — tests/test_review_retained_full.py, tests/test_agent_tools_launchers.py — full — [task-3.md](2026-10-04-issue-254-compact-retained-encodings.tasks/task-3.md)

## Execution gates

Every gate runs in the matching gate environment: define `core_gate` exactly as the CORE plan's "Matching gate environment" section does (`.agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.md`) and use `source` mode with this worktree as `TREE` and the recipe's `python3` as `PYTHON`. Never use an ambient checker. Keep outputs and logs outside the worktree, in this child's SDD workspace.

**G0, projection, before any product commit and after every plan, spec or forecast change.** Pin the committed head `HEAD`.
1. `core_gate source TREE PYTHON python3 -m agent_tools.review_feasibility project --plan <this root> --base DELIVERY_BASE --head HEAD --completed-through N`; capture the exit and the canonical bytes.
2. `validate-result --input RESULT --producer-exit 0` in the same closure.
3. A second independent invocation must reproduce every byte.

`N` is 0 before Task 1 and, once task `N` is accepted and its ranges are recorded, `N` (RP14). Only exit 0 with `complete/within_budget` clears G0. Exit 2 or 3 stops with no bootstrap; exit 3 stops for decomposition.

Planning G0 at `--completed-through 0`: at head `c789543`, exit 0 and `complete/within_budget`: root 8,997 of 16,384 B, total 421,157 of 524,288 B, largest member 65,536 B, `file_count` 9 (eight of eight payload members, so a forecast revision has no spare member), validated and reproduced. The recording commit changes no forecast, and a re-run there also cleared.

**G1, the complete fixed-base actual gate, after every task and fix and at the final head.** Pin `HEAD`; run `core_gate source ... python3 -m agent_tools.review_package <this root> DELIVERY_BASE HEAD`, validate it through `artifact-budget validate-report --boundary producer`, then independently run `artifact-budget check --kind review-package`. Both must show `complete/within_budget` with identical metrics. After each task, record its `actual_ranges` and refresh `actual_evidence` in a process-only commit, then renew G0.

**G2, the source pin, after Task 2** (spec § *Delivery gates*; CP11, CP12). It has three parts, at one pinned commit:
1. An authorship-independent review of the complete `python/` source.
2. A fresh adversarial reviewer, working in disposable alternates-backed clones of the retained root. The reviewer repeats REPLAY's graft and rehash reproduction against `contribution_edges`, `reconstruct_boundary` (selector `tasks-1`) and the source derive command. The reviewer derives a scratch bundle at the pin and requires `expand_100` and `expand_121` of its members to equal, byte for byte, the payloads that the modules at `7e17c81` derive from the same objects, run from a detached checkout of that commit outside this worktree. The reviewer also tries non-canonical payloads against `validate_100` and `validate_121`.
3. The controller posts on https://github.com/fagenorn/nix-config/issues/235 the pin's full SHA, the five file sizes of that scratch bundle and the two schema versions (2 and 4), with full URLs.

That commit is the `AGENT_RETAINED_TOOL_COMMIT` of every authoritative full-shape run. Evidence, with before and after root digests, goes to the SDD workspace. The tier is not run before Task 3 rewrites its site tables.

**G3, final.** Focused suites, full `just agent-workflow-tests`, `just build`, `just agent-installed-skill-tests` and `AGENT_RETAINED_TOOL_COMMIT=<G2 pin> just agent-retained-tests /Users/anis/tmp/nix-config`, no skip counted as a pass; then separate authorship-independent conformance and correctness reviews over the complete fixed-base delivery. Required CI remains the merge gate. Nothing is activated. G2 and G3 retained runs are quiescent (RP11).

## Acceptance coverage

| Issue 254 criterion | Verified by |
|---|---|
| 1. Measured feasibility before product work | Spec § *Measured feasibility*, committed at `c410ae5` before any product commit; the reference packings in Tasks 1 and 2 reproduce its 48,917 B and 62,118 B |
| 2. Each payload at most 65,536 B; tier asserts all five | Task 3 `test_bundle_files_fit_the_whole_record_caps`, run at G3 |
| 3. Total and EVIDENCE headroom | Spec § *Measured feasibility*; the same case asserts the five-file sum at most 196,608 B |
| 4. Issue-100 facts and expansion | Task 3 `test_issue100_expansion_is_the_source_model_fact_for_fact`; Task 2 `test_payload_is_closed_and_expands_to_the_source_model` |
| 5. Issue-121 facts and expansion | Task 3 `test_issue121_expansion_is_the_source_model_fact_for_fact`; Task 1 `test_payload_is_closed_and_expands_to_the_source_model` and `test_every_fixture_shape_round_trips` |
| 6. Every refusal, from source and built; recomputed members | Tasks 1 and 2 Step 4: the compact suites' altered-input, non-canonical and malformed-member cases and the published suites through `compact_*`. Task 3 Step 4, built and from source with the sources unreachable (CP19): the stub's replacement-anchor, changed-member and partial-bundle cases, the derive command's `tool_closure`, and on the real bundle each rehashed `REHASHED_FORGERIES` row: a missing edge, a reordered edge and a duplicate record per payload (CP20) |
| 7. Determinism, unchanged root, no skip | Task 3 Step 4: the unchanged `test_two_derivations_are_byte_identical`, the root comparison around every test and the recipe's skip refusal |
| 8. New versions; old encodings refused | Tasks 1 and 2: `test_source_encoding_and_other_versions_are_refused` and the source-encoded cases of the witness and replay suites. Task 3: each member replaced in turn by its whole SOURCE encoding in the real bundle, coherently rehashed, is `invalid_payload` from the built launcher and from source (CP20) |
| 9. Swap disposition | CP9; the swap case of each compact suite; both published swap cases stay green |
| 10. G2 and the pin on issue 235 | G2 above; Task 2 Step 6 |
| 11. G0, G1, suites, build, installed tier | G0 before Task 1; each task's Step 6; G3 |

## Decisions

CP1, CP4, CP6–CP9 and CP13–CP15 govern both model tasks; CP3 governs Task 1; CP2, CP5 and CP16 govern Task 2; CP17 bounds what the refusal cases claim; CP10, CP11 and CP18–CP20 govern Task 3; CP12 governs the gates.

## Standards review provenance

Reviewer Codex (gpt-6-astra, xhigh), isolated and read-only, base `7e17c8196569b0a96950f07ff886884690ffa224`, no fallback. Accepted 3, rejected 0, deferred 0.
- B1, accepted: built parity for a missing edge, a reordered edge and a duplicate record (CP20).
- B2, accepted: sealed replay parity runs (CP19).
- S1, accepted: each old encoding refused separately (CP20).

## Review feasibility delivery

```json
{"actual_evidence":{"head":"82ba7ac1b4364f30c63b4d75aebcfb389693f987","kind":"git-range-ownership/v1","process_ranges":[{"base":"7e17c8196569b0a96950f07ff886884690ffa224","boundaries":["compact"],"head":"ca99033edc90ec95b195a06191a3d2542cec57ea"},{"base":"31ae90db116e3e9632afdc6846a5d7bd8d709a61","boundaries":["compact"],"head":"6083c6b5521a94063b69421b0917f24c6baa1aa0"},{"base":"01f0508968be676d0e2fa77df03bf19be0d6d157","boundaries":["compact"],"head":"1e800d8414e55d9515800cc097253c0dddc4599a"},{"base":"57135445b525d3d1cefcc540e7dae1f31809d4c1","boundaries":["compact"],"head":"3b5ca2bac91e3ed67729eea0da7964431d15352d"},{"base":"691d8f257615c5698965918b3cca036c2e9ccec9","boundaries":["compact"],"head":"f38a0f855b4347351221fa81d02adbaf6b42c88b"}],"tree":"03dc7595ade73851efe9d0a492889401f1137367"},"boundaries":[{"acceptance":"Complete COMPACT: both retained payloads in compact encodings that expand to SOURCE's models, the witness over the models, old encodings refused, built parity and the full-shape tier bounds; G0-G3 gates and independent reviews.","depends_on":[],"id":"compact","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["p1","p2","p3","p4","p5"],"process_package":{"plan":".agents/artifacts/plans/2026-10-04-issue-254-compact-retained-encodings.md","spec":".agents/artifacts/specs/2026-10-04-issue-254-compact-retained-encodings-design.md","tasks":[".agents/artifacts/plans/2026-10-04-issue-254-compact-retained-encodings.tasks/task-1.md",".agents/artifacts/plans/2026-10-04-issue-254-compact-retained-encodings.tasks/task-2.md",".agents/artifacts/plans/2026-10-04-issue-254-compact-retained-encodings.tasks/task-3.md"]},"tasks":[1,2,3]}],"delivery_base":"7e17c8196569b0a96950f07ff886884690ffa224","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":426,"boundary":"compact","deleted_lines":0,"record_bytes":36864,"support":{"covers":["p1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p1","last_task":3,"owner":0,"path":".agents/artifacts/specs/2026-10-04-issue-254-compact-retained-encodings-design.md"},{"bounds":[{"added_lines":150,"boundary":"compact","deleted_lines":0,"record_bytes":17408,"support":{"covers":["p2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p2","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-10-04-issue-254-compact-retained-encodings.md"},{"bounds":[{"added_lines":470,"boundary":"compact","deleted_lines":0,"record_bytes":39936,"support":{"covers":["p3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p3","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-10-04-issue-254-compact-retained-encodings.tasks/task-1.md"},{"bounds":[{"added_lines":437,"boundary":"compact","deleted_lines":0,"record_bytes":37888,"support":{"covers":["p4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p4","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-10-04-issue-254-compact-retained-encodings.tasks/task-2.md"},{"bounds":[{"added_lines":356,"boundary":"compact","deleted_lines":0,"record_bytes":30720,"support":{"covers":["p5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p5","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-10-04-issue-254-compact-retained-encodings.tasks/task-3.md"}],"proposed_boundary":"compact","schema_version":3}
```
