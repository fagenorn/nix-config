# Issue 256 Bounded Expansion Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill, one implementer per task and a review between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Bound what `expand_100` and `expand_121` build from a forged member, so that a maximal forged member under the 1,048,576 B decode bound gets the existing `invalid_payload` refusal within 5 s and a 32 MiB traced peak, while the real retained payloads expand byte for byte as before.

**Architecture:** A new package module, `review_expansion`, holds `MEMBER_MAX_BYTES` and a per-call `Budget` of that many canonical bytes. Each expander charges every row it materialises to its budget. `_refs` (issue 100) becomes one rename-component grouping and `_lineage` (issue 121) an incremental pass, each serving derivation and expansion alike. The [spec](../specs/2026-10-06-issue-256-bounded-expansion-design.md) owns every contract and the ledger D1–D8.

**Tech stack:** Python standard library (`signal`, `tracemalloc`), canonical JSON, unittest, Nix, just.

## Global Constraints

- The immutable `DELIVERY_BASE` is `31be7292b40159c5a3f49cc24f21b3292ba4ce89`. Every gate covers every later product and process commit.
- No cap, decode bound or schema moves: `MEMBER_MAX_BYTES` stays `1048576`, issue 100 stays at payload schema 2 and model schema 1, and issue 121 at payload schema 4 and model schema 3. No refusal code is added or renamed, and `validate_bundle` keeps its order (D1, D2).
- The one new module is `python/agent_tools/review_expansion.py`. No command, option, recipe or bundle file is added; the only `justfile` edit lists the new suite (D2).
- The committed evidence bundle under `tests/fixtures/retained-review-evidence/` and `tests/retained_evidence_test_support.py` are not touched.
- The real payloads expand to the same canonical bytes as at `DELIVERY_BASE`: issue 100 to 341,492 B, issue 121 to 211,097 B (spec § *Solution*).
- Agent-helper standards 1–5 (`docs/standards/agent-helpers.md`). No CLAUDE.md edit.
- Nothing writes the retained root's working tree, objects, archive or lifecycle state, and no ref is added. Every long command carries an explicit `timeout`.
- Commits are SSH-signed, made through `launch-commit`, and end with the session's trailer lines. Every subject is at most 64 UTF-8 bytes. Code and docstrings describe verified behavior.
- Size bounds: every changed file stays one whole review record within its task's forecast. An actual record above its bound needs a committed forecast revision and a renewed G0, never truncation or a lowered bound.
- Out of scope: the spec's § *Out of scope*.

## Test seams

- Suites run as `PYTHONPATH=python python3 -m unittest tests.<module>`; modules are imported normally and no test reads a private `agent_tools` name (D5).
- Forged payloads are the committed retained payloads with rows appended, built by `tests/retained_review_test_support.py`; that module also holds the bounded-call helper `measured` (D5, D6, D8).
- The budget boundary is tested by patching the public `agent_tools.review_expansion.MEMBER_MAX_BYTES` (D5).
- Replay under trust injection uses the replay suite's own `rebound` method over its portable bundle (D5, RP7).
- The committed-evidence suite and the full-shape tier run unchanged; the tier runs only under `just agent-retained-tests <root>`, where a skip fails the recipe.
- Verification command IDs: `agent-workflow-tests` and `nix-build`, run in this worktree.

## Delivery estimate and boundaries

These are estimates. Product: ten paths in two tasks, two of them new, about 109 KB of forecast records; two paths carry two ordered cumulative contributions. Process: the spec, this root and two members, about 104 KB. The growth risk sits in the two model modules, each forecast at 26,624 B against #254's measured 27,774 B record for a 315-line expander diff.

There is one boundary, `bounded`: neither expander alone meets issue criterion 2. If G0 returns exit 3, stop and return to design. Subject reserves are two 64-byte subjects per task and ten for process.

## Task index

Task 1 — Expansion budget and the issue-100 expander — python/agent_tools/review_expansion.py, python/agent_tools/review_witness.py, python/agent_tools/review_issue100.py, tests/test_review_expansion.py, tests/retained_review_test_support.py, tests/test_review_compact100.py, tests/test_review_replay.py, justfile — full — [task-1.md](2026-10-06-issue-256-bounded-expansion.tasks/task-1.md)
Task 2 — The issue-121 expander — python/agent_tools/review_issue121.py, tests/retained_review_test_support.py, tests/test_review_compact121.py, tests/test_review_replay.py — full — [task-2.md](2026-10-06-issue-256-bounded-expansion.tasks/task-2.md)

## Execution gates

Every gate runs in the matching gate environment: define `core_gate` exactly as the CORE plan's "Matching gate environment" section does (`.agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.md`) and use `source` mode with this worktree as `TREE` and the recipe's `python3` as `PYTHON`. Never use an ambient checker. Keep outputs and logs outside the worktree, in this child's SDD workspace (`EV` below).

```sh
TREE=$(git rev-parse --show-toplevel); PY=$(command -v python3); HEAD_SHA=$(git rev-parse HEAD)
BASE=31be7292b40159c5a3f49cc24f21b3292ba4ce89
PLAN=$TREE/.agents/artifacts/plans/2026-10-06-issue-256-bounded-expansion.md
```

**G0, projection, before Task 1 and after every accepted task and every plan, spec or forecast change.** `N` is 0 before Task 1 and, once task `N` is accepted and its ranges are recorded, `N` (RP14).

```sh
core_gate source "$TREE" "$PY" timeout 900 python3 -m agent_tools.review_feasibility project \
  --plan "$PLAN" --base "$BASE" --head "$HEAD_SHA" --completed-through "$N" > "$EV/g0-$N.json"; echo "exit=$?"
core_gate source "$TREE" "$PY" python3 -m agent_tools.review_feasibility validate-result \
  --input "$EV/g0-$N.json" --producer-exit 0 | cmp - "$EV/g0-$N.json"
core_gate source "$TREE" "$PY" timeout 900 python3 -m agent_tools.review_feasibility project \
  --plan "$PLAN" --base "$BASE" --head "$HEAD_SHA" --completed-through "$N" | cmp - "$EV/g0-$N.json"
```

Only exit 0 with `complete/within_budget`, validated and reproduced, clears G0. Exit 2 or 3 stops with no bootstrap. Task 1 starts only after G0 has cleared at 0 (CP12 precedent).

Planning G0 at `--completed-through 0`: at head `db027ea`, exit 0 and `complete/within_budget`: root 7,141 of 16,384 B, total 218,085 of 524,288 B, largest member 57,344 B, `file_count` 5 (four of eight payload members), validated and reproduced. The recording commit changes no forecast.

**G1, the complete fixed-base actual gate, after every task and fix and at the final head.**

```sh
core_gate source "$TREE" "$PY" timeout 900 python3 -m agent_tools.review_package "$PLAN" "$BASE" "$HEAD_SHA" > "$EV/g1-$HEAD_SHA.json"
core_gate source "$TREE" "$PY" artifact-budget validate-report --boundary producer --input "$EV/g1-$HEAD_SHA.json" | cmp - "$EV/g1-$HEAD_SHA.json"
core_gate source "$TREE" "$PY" artifact-budget check --kind review-package --format json \
  --root "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact"]["path"])' "$EV/g1-$HEAD_SHA.json")"
```

Both must show `complete/within_budget` with identical metrics; G1 overrides every forecast. After each task, record its `actual_ranges` and refresh `actual_evidence` in a process-only commit, then renew G0. At the final head, with every range recorded, G0 at `--completed-through 2` reports the four metrics G1 reports there.

**G3, final.** In this order, each bounded, with no skip counted as a pass:

```sh
set -o pipefail  # each line's status is its first failing stage, never `tail`'s (Codex S2)
PYTHONPATH=python timeout 1800 python3 -m unittest tests.test_review_expansion tests.test_review_compact100 \
  tests.test_review_compact121 tests.test_review_replay tests.test_review_evidence 2>&1 | tail -3
timeout 7200 just agent-workflow-tests 2>&1 | tail -3
timeout 3600 just build 2>&1 | tail -3
timeout 3600 just agent-installed-skill-tests > "$EV/installed.log" 2>&1; echo "exit=$?"
timeout 14400 just agent-retained-tests /Users/anis/tmp/nix-config > "$EV/retained.log" 2>&1; echo "exit=$?"
```

Every line must exit 0 (`exit=0` for the last two). `AGENT_RETAINED_TOOL_COMMIT` is left unset (the final head). The retained run is quiescent (RP11). Then separate authorship-independent conformance and correctness reviews read the complete fixed-base delivery; the correctness review repeats #254's I1 probe (a ≈975 kB issue-100 member) and the M1 probe against the final head with `measured` and records each time and traced peak (spec § *Delivery gates*). Required CI remains the merge gate. Nothing is activated.

## Acceptance coverage

| Issue 256 criterion | Verified by |
|---|---|
| 1. Maximal forged member refused in a stated bound; fails on the #257 tree | Task 1 `test_maximal_rename_chain_is_refused_within_the_bound`, Task 2 `test_maximal_edges_by_rows_is_refused_within_the_bound`, and `test_maximal_forged_member_is_refused_within_the_bound` in the replay suite (both members after Task 2) |
| 2. Both expanders linear or explicitly bounded | Tasks 1 and 2: the budget, the linear `_refs` and `_lineage`, and `test_each_amplified_site_is_refused` per expander |
| 3. Real payloads byte-identical; second derivation identical | `tests.test_review_evidence` and the compact suites' round trips, unchanged; the retained tier's determinism case at G3 |
| 4. No cap raised, no code added | Task 1 `test_the_bound_is_the_decode_bound_with_one_home`; the witness suite's constant assertion and the code-set assertions, unchanged |
| 5. Suites, tier, build | G3 |

## Decisions

D1–D4 govern both tasks' product code; D2 also governs Task 1's module move; D5, D6 and D8 govern the tests of both tasks; D7 bounds what both tasks leave unchanged.

## Review feasibility delivery

```json
{"actual_evidence":{"head":"0235fd99c03447da59cabde615498880d214b147","kind":"git-range-ownership/v1","process_ranges":[{"base":"31be7292b40159c5a3f49cc24f21b3292ba4ce89","boundaries":["bounded"],"head":"21814aa4722e7f03cd7fe0633391a254592e2fe0"},{"base":"d32d6359c553af8705eb58884588e6c6a60ab78d","boundaries":["bounded"],"head":"a02b8e20b3ca4544a2e7edd21b64645f47e0d9ff"},{"base":"396c96ba3b7c3350cd6d3e434b252b2f1b78c5ac","boundaries":["bounded"],"head":"2b716a50cf84748583adb9a69399480cdec535cf"}],"tree":"33e2819775e7b3dc3f10850728a73c2ba5f51c39"},"boundaries":[{"acceptance":"Complete BOUNDED: both retained expanders charge what they build to one per-call budget of MEMBER_MAX_BYTES, with linear _refs and _lineage, so a maximal forged member is refused invalid_payload within 5 s and 32 MiB; real payloads expand byte-identically; G0, G1 and G3 gates and independent reviews.","depends_on":[],"id":"bounded","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["p1","p2","p3","p4"],"process_package":{"plan":".agents/artifacts/plans/2026-10-06-issue-256-bounded-expansion.md","spec":".agents/artifacts/specs/2026-10-06-issue-256-bounded-expansion-design.md","tasks":[".agents/artifacts/plans/2026-10-06-issue-256-bounded-expansion.tasks/task-1.md",".agents/artifacts/plans/2026-10-06-issue-256-bounded-expansion.tasks/task-2.md"]},"tasks":[1,2]}],"delivery_base":"31be7292b40159c5a3f49cc24f21b3292ba4ce89","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":260,"boundary":"bounded","deleted_lines":0,"record_bytes":26624,"support":{"covers":["p1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p1","last_task":2,"owner":0,"path":".agents/artifacts/specs/2026-10-06-issue-256-bounded-expansion-design.md"},{"bounds":[{"added_lines":200,"boundary":"bounded","deleted_lines":0,"record_bytes":20480,"support":{"covers":["p2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p2","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-10-06-issue-256-bounded-expansion.md"},{"bounds":[{"added_lines":460,"boundary":"bounded","deleted_lines":0,"record_bytes":32768,"support":{"covers":["p3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p3","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-10-06-issue-256-bounded-expansion.tasks/task-1.md"},{"bounds":[{"added_lines":280,"boundary":"bounded","deleted_lines":0,"record_bytes":22528,"support":{"covers":["p4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p4","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-10-06-issue-256-bounded-expansion.tasks/task-2.md"}],"proposed_boundary":"bounded","schema_version":3}
```

## Standards review provenance

- Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra/xhigh), isolated and read-only, no fallback; base `31be7292b40159c5a3f49cc24f21b3292ba4ce89`; no focus.
- Findings: 0 Blocking, 2 Should fix, both verified against the live worktree and accepted (S1 into Task 2 Step 1 per D9; S2 into G3); 0 rejected, 0 deferred.
