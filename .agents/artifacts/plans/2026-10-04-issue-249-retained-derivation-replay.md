# Issue 249 Retained Derivation and Replay Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill, one implementer per task and a review between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Publish `derive-review-feasibility-fixtures` and `replay-retained` on SOURCE's models: an acyclic witness and anchor, deterministic five-file derivation, Git-free replay with its exit contract, and the full-shape tier `agent-retained-tests <root>`.

**Architecture:** Three library modules join `agent_tools`: `review_witness` (the bundle contract and its one full validation), `review_derivation` and `review_replay`, with two thin command modules and two command-table rows. Task 1 first corrects three inherited SOURCE defects, so that the G2 source pin covers the corrected bytes. The [spec](../specs/2026-10-04-issue-249-retained-derivation-replay-design.md) owns every contract and the ledger RP1–RP18; it cites the parent design at `6e5224e` and the SOURCE spec for the rest.

**Tech stack:** Python standard library, Git plumbing, canonical JSON, unittest, Nix/Home Manager, just.

## Global Constraints

- Design identity `DP234-REPLAY`. The immutable `DELIVERY_BASE` is `218f5bc0bf3556fa05959e6ba24175685b58e2a9`. Every gate covers every later product and process commit.
- Agent-helper standards 1–5 (`docs/standards/agent-helpers.md`): thin command modules with `prog` set to the command name; no dynamic import, `sys.path` edit or `__file__` lookup in the package; digests via `telemetry_digest` or CORE's `canonical_bytes`; external commands by name on `PATH`.
- Both commands pass only the real pin constants and offer no pin option. Each library entry point takes its pins explicitly (parent D12).
- The closed error codes are the spec's (§ *Error codes*); neither command catches an unexpected exception (RP8). Payload encodings stay SOURCE's (RP13).
- Size bounds (RP14): every file stays within its task's forecast record, and no new record exceeds 20,480 B (36,864 B for the full-shape module). Every changed file stays one whole review record. No cap or generated-exemption change.
- No CLAUDE.md edit (parent D16). Tasks 5 and 6 change no `python/` byte; any later `python/` change repeats G2 and G0.
- Nothing writes the retained root, its object store, the issue-100 archive, parent evidence or lifecycle state, and no ref is added.
- Declined inherited findings stay declined: no SOURCE edit beyond Task 1's three.
- Commits are SSH-signed and end with the session's trailer lines. Every subject is at most 64 UTF-8 bytes, checked before committing. Code and docstrings describe verified behavior.
- Out of scope: the spec's § *Out of scope*.

## Test seams

- Suites run as `PYTHONPATH=python python3 -m unittest tests.<module>` and import modules normally; commands run as `python -m agent_tools.<module>`. Only `tests/test_agent_tools_launchers.py` touches built launchers.
- Temporary real Git repositories and ephemeral SSH keys through `tests/retained_review_test_support.py`, which gains `retained_fixture` and `tool_fixture` returning plain paths and pins (RP12). `source_budget_env` stages the source budget helper.
- Test-only trust injection is a direct call to `validate_bundle` with a rebuilt anchor (RP7). The replay command's two non-refusal exits are tested in process with its pin names patched (RP17).
- Portable suites `test_review_witness`, `test_review_derivation` and `test_review_replay` are listed in `agent-workflow-tests`. The full-shape classes run only under `just agent-retained-tests <root>`; a skip there fails the recipe (RP10).
- Verification command IDs: `agent-workflow-tests` and `nix-build` (`just build`), run in this worktree.

## Delivery estimate and boundaries

These are estimates (parent D15, RP14, RP18). Product: nineteen paths in six tasks, ten of them new, about 208 KB of forecast records; `justfile` carries four ordered cumulative contributions and the launcher module two. Process: the spec, this root and six members, about 145 KB. Growth risk sits in `review_witness.py`, the three portable suites and the full-shape module. An actual record above its bound needs a committed forecast revision and a renewed G0, never truncation or a lowered bound.

There is one boundary, `replay`: the decomposition already separated SOURCE, and the commands are not acceptable without their tier. Subject reserves are two 64-byte subjects per task (implementation plus one fix) and ten for process; a second fix round needs one ruling that adds one subject.

## Task index

Task 1 — Inherited SOURCE corrections — python/agent_tools/review_task7.py, python/agent_tools/review_issue100.py, python/agent_tools/review_issue121.py, tests/test_review_task7.py, tests/test_review_issue100.py, tests/test_review_issue121.py — full — [task-1.md](2026-10-04-issue-249-retained-derivation-replay.tasks/task-1.md)
Task 2 — Tool closure, witness, anchor and bundle validation — python/agent_tools/review_witness.py, tests/test_review_witness.py, tests/retained_review_test_support.py, justfile — full — [task-2.md](2026-10-04-issue-249-retained-derivation-replay.tasks/task-2.md)
Task 3 — Derivation and the derive command — python/agent_tools/review_derivation.py, python/agent_tools/derive_review_feasibility_fixtures.py, tests/test_review_derivation.py, justfile — full — [task-3.md](2026-10-04-issue-249-retained-derivation-replay.tasks/task-3.md)
Task 4 — Portable replay and the replay command — python/agent_tools/review_replay.py, python/agent_tools/replay_retained.py, tests/test_review_replay.py, justfile — full — [task-4.md](2026-10-04-issue-249-retained-derivation-replay.tasks/task-4.md)
Task 5 — Publish both commands and prove portable built parity — lib/agent-tools.nix, tests/test_agent_tools_launchers.py — full — [task-5.md](2026-10-04-issue-249-retained-derivation-replay.tasks/task-5.md)
Task 6 — Full-shape retained tier — justfile, tests/test_review_retained_full.py, tests/test_agent_tools_launchers.py — full — [task-6.md](2026-10-04-issue-249-retained-derivation-replay.tasks/task-6.md)

## Execution gates

Every gate runs in the matching gate environment: define `core_gate` exactly as the CORE plan's "Matching gate environment" section does (`.agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.md`) and use `source` mode with this worktree as `TREE` and the recipe's `python3` as `PYTHON`. Never use an ambient checker. Keep outputs and logs outside the worktree, in this child's SDD workspace.

**G0, projection, before any product commit and after every plan, spec or forecast change.** Pin the committed head `HEAD`.
1. `core_gate source TREE PYTHON python3 -m agent_tools.review_feasibility project --plan <this root> --base DELIVERY_BASE --head HEAD --completed-through N`; capture the exit and the canonical bytes.
2. `validate-result --input RESULT --producer-exit 0` in the same closure.
3. A second independent invocation must reproduce every byte.

`N` is 0 before Task 1 and, once task `N` is accepted and its ranges are recorded, `N` (RP14). Only exit 0 with `complete/within_budget` clears G0. Exit 2 or 3 stops with no bootstrap; exit 3 stops for decomposition.

Planning G0 at `--completed-through 0`: at the plan-review head `5769d40`, exit 0 and `complete/within_budget`: root 11,272 of 16,384 B, total 364,552 of 524,288 B, largest member 61,440 B, `file_count` 8 (seven of eight payload members under the initial sequential packing, with the first-fit strategies behind it), validated and reproduced byte for byte. The result for the final planning head is kept at `.superpowers/review-evidence/249/run-20261003-248-249/g0-result.json` under the primary checkout.

**G1, the complete fixed-base actual gate, after every task and fix and at the final head.** Pin `HEAD`; run `core_gate source ... python3 -m agent_tools.review_package <this root> DELIVERY_BASE HEAD`, validate it through `artifact-budget validate-report --boundary producer`, then independently run `artifact-budget check --kind review-package`. Both must show `complete/within_budget` with identical metrics. After each task, record its `actual_ranges` and refresh `actual_evidence` in a process-only commit, then renew G0.

**G2, the source pin, after Task 4** (spec § *Delivery gates*). An independent review of the complete `python/` source at one pinned commit, plus a fresh adversarial reviewer who repeats the graft and rehash reproduction in disposable alternates-backed clones against `contribution_edges`, `reconstruct_boundary` (selector `tasks-1`) and the source derive command. That commit is the `AGENT_RETAINED_TOOL_COMMIT` of every authoritative full-shape run. Evidence, with before/after root digests, goes to the SDD workspace.

**G3, final.** Focused tests, full `just agent-workflow-tests`, `just build`, `just agent-installed-skill-tests` and `AGENT_RETAINED_TOOL_COMMIT=<G2 pin> just agent-retained-tests /Users/anis/tmp/nix-config`, no skip counted as a pass; then separate authorship-independent conformance and correctness reviews over the complete fixed-base delivery. Required CI remains the merge gate. Nothing is activated. G2 and G3 retained runs are quiescent (RP11).

## Acceptance coverage

| Issue 249 criterion | Verified by |
|---|---|
| Derivation | Task 3 Step 4; Task 6 `test_two_derivations_are_byte_identical` |
| Anchor and witness | Task 2 Step 4 (`test_core_loader_accepts_a_committed_bundle`, the closure cases); Task 6 `test_dirty_or_mismatched_tool_tree_refuses` |
| Replay ordering and exits | Task 2 Step 4 (trust injection), Task 4 Step 4, Task 6 `test_replay_with_sources_unreachable` |
| Built parity | Task 5 Step 4; Task 6 `RetainedLauncherTest` |
| Full-shape tier | Task 6 Step 4 |
| Delivery gates | G0–G3 above; each task's Step 6 |

## Decisions

RP1 fixes the six tasks and Task 1's scope, with RP15 for its two consequences. RP2, RP3, RP7, RP8 and RP16 govern Task 2; RP4, RP5, RP6, RP9 and RP16 govern Task 3; RP2, RP8 and RP17 govern Task 4; parent D16 and RP12 govern Task 5; RP7, RP10 and RP11 govern Task 6; RP13 keeps the encodings; RP14 and RP18 govern the forecasts, reserves and G0 renewal.

## Standards review provenance

Reviewer Codex (`codex-plan-review`, gpt-6-astra, xhigh), isolated and read-only, base `218f5bc`, plan head `2dc6bc7`, no fallback. Four findings (2 Blocking, 2 Should fix), all verified against the live tree and accepted; none rejected or deferred: Task 5 runs the source side from a clean `cwd`; Task 6 maps the two digest-named adoption records to their placeholder rows and ignores punctuation-only policy lines; Task 3 adds a publication-failure cleanup case.

## Review feasibility delivery

```json
{"actual_evidence":{"head":"5f67003b83503fb56037c7a9720812cf611c79e8","kind":"git-range-ownership/v1","process_ranges":[{"base":"218f5bc0bf3556fa05959e6ba24175685b58e2a9","boundaries":["replay"],"head":"5d5a5d70a25bdbf15c234a60e10f891f7727d5d1"},{"base":"d5232acfe2494ef5ed415f75c72906807dc3f91f","boundaries":["replay"],"head":"8755b2f8ec9412242dab254f9ef318da1e78eb24"}],"tree":"92a214ffbfa700e0648ab098259d087aa43a0ca2"},"boundaries":[{"acceptance":"Complete REPLAY: the witness, anchor and tool closure, five-file derivation, Git-free replay, both published commands and the full-shape retained tier; G0-G3 gates and independent reviews.","depends_on":[],"id":"replay","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["p1","p2","p3","p4","p5","p6","p7","p8"],"process_package":{"plan":".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.md","spec":".agents/artifacts/specs/2026-10-04-issue-249-retained-derivation-replay-design.md","tasks":[".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-1.md",".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-2.md",".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-3.md",".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-4.md",".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-5.md",".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-6.md"]},"tasks":[1,2,3,4,5,6]}],"delivery_base":"218f5bc0bf3556fa05959e6ba24175685b58e2a9","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":540,"boundary":"replay","deleted_lines":0,"record_bytes":45056,"support":{"covers":["p1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p1","last_task":6,"owner":0,"path":".agents/artifacts/specs/2026-10-04-issue-249-retained-derivation-replay-design.md"},{"bounds":[{"added_lines":150,"boundary":"replay","deleted_lines":0,"record_bytes":17408,"support":{"covers":["p2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p2","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.md"},{"bounds":[{"added_lines":145,"boundary":"replay","deleted_lines":0,"record_bytes":11264,"support":{"covers":["p3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p3","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-1.md"},{"bounds":[{"added_lines":185,"boundary":"replay","deleted_lines":0,"record_bytes":17408,"support":{"covers":["p4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p4","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-2.md"},{"bounds":[{"added_lines":152,"boundary":"replay","deleted_lines":0,"record_bytes":15360,"support":{"covers":["p5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p5","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-3.md"},{"bounds":[{"added_lines":143,"boundary":"replay","deleted_lines":0,"record_bytes":13312,"support":{"covers":["p6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p6","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-4.md"},{"bounds":[{"added_lines":123,"boundary":"replay","deleted_lines":0,"record_bytes":10240,"support":{"covers":["p7"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p7","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-5.md"},{"bounds":[{"added_lines":147,"boundary":"replay","deleted_lines":0,"record_bytes":15360,"support":{"covers":["p8"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p8","last_task":6,"owner":0,"path":".agents/artifacts/plans/2026-10-04-issue-249-retained-derivation-replay.tasks/task-6.md"}],"proposed_boundary":"replay","schema_version":3}
```
