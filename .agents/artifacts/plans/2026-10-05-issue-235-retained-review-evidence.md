# Issue 235 Retained Review Evidence Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill, one implementer per task and a review between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Commit the five-file retained review evidence bundle with a trust pin outside it, prove the committed copy by replay, tamper and reproduction tests, and audit parent https://github.com/fagenorn/nix-config/issues/226.

**Architecture:** One derivation at the reviewed tool commit supplies the committed bytes and a second, independent one must reproduce them. A hand-written literal holds the anchor digest every test trusts. Three tiers read the committed copy: a portable suite in CI, built-launcher cases, and one case that derives the bundle again from the real objects. The [spec](../specs/2026-10-05-issue-235-retained-review-evidence-design.md) owns every contract and the ledger EV1–EV13; it cites the CORE, REPLAY and COMPACT specs for the rest.

**Tech stack:** Python standard library, unittest, Git plumbing, canonical JSON, Nix, just.

## Global Constraints

- Design identity `DP226-EVIDENCE`. The immutable `DELIVERY_BASE` is `8971e41802fd2ee4de8d1c85626ea1cdcf2d384d`. Every gate covers every later product and process commit.
- The reviewed tool commit (G2 pin) is `691d8f257615c5698965918b3cca036c2e9ccec9`; its `python` tree is `6ce6afdda7b95e749184fcd8e132fc0a38de915e`. The trusted anchor digest is `sha256:d0968f6a9ca20160bd027bb3ce12b5231efa603057a054a76fe37e5f4870a8a5`. A derivation that prints another digest stops the delivery; the value is never adopted (EV5).
- No path under `python/` changes, and no module, command, option or recipe is added (EV10). A source defect stops the delivery and goes to the issue that owns the module.
- The five committed files come only from Task 1's derivation A. They are never edited, reformatted or re-encoded.
- Caps do not move: 65,536 B per member, eight members, 524,288 B in all. The bundle files are ordinary whole records with no generated-evidence exemption (EV8).
- The retained root is `/Users/anis/tmp/nix-config`. No task writes its working tree, archive, parent evidence or lifecycle state. Every worktree shares its refs and objects, so a retained run is quiescent: no commit, fetch or gc in any worktree while it runs (RP11).
- Every long command carries an explicit `timeout`; no step waits without a bound.
- Commits are SSH-signed and end with the session's trailer lines. Every subject is at most 64 UTF-8 bytes. Code and docstrings describe verified behavior.
- Parent 226 stays open: no commit message, pull request text or file holds a closing keyword for it. Tracker references are full URLs.
- Size bounds: every changed file stays one whole review record within its task's forecast. An actual record above its bound needs a committed forecast revision and a renewed G0, never truncation or a lowered bound.
- Out of scope: the spec's § *Out of scope*.

## Test seams

- Suites run as `PYTHONPATH=python python3 -m unittest tests/<module>.py`; commands run as `python -m agent_tools.<module>`.
- Only `tests/test_agent_tools_launchers.py` touches built launchers, and it imports no `agent_tools` outside the retained recipe (CP18). Built replay runs are sealed (CP19).
- `tests/retained_evidence_test_support.py` is support, not a suite: three names and no `agent_tools` import.
- The portable suite runs the tier's own site and forgery tables over a scratch copy of the committed bundle (EV6). Trust injection is a direct `validate_bundle` call on a rebuilt bundle, or replay under the forger's own digest (RP7).
- The full-shape tier runs only under `just agent-retained-tests <root>`, where a skip fails the recipe (RP10). `source_budget_env` gains an optional source root, the only seam change (EV10).
- No test reads a private name. Verification command IDs: `agent-workflow-tests` and `nix-build`.

## Delivery estimate and boundaries

These are estimates, except the five bundle records, which are measurements (EV8). Product: fourteen paths in four tasks, eight of them new, about 272 KB of forecast records, of which the bundle is 186,167 B. Process: the spec, this root and four members, about 119 KB. The growth risks are the audit's row count and the member count.

There is one boundary, `evidence`: publication is not acceptable without the tests that prove it. If G0 returns exit 3, stop and return to design. Subject reserves are two 64-byte subjects per task and ten for process.

Planning repeated the spec's measurement: a scratch derivation at the pin and a trial of derivation B's route both reproduced the five sizes and the digest, and every test body in Tasks 2 and 3 ran green against that bundle. It was discarded (EV5).

## Task index

Task 1 — Publish the bundle and its trust pin — tests/fixtures/retained-review-evidence/ (five files), tests/retained_evidence_test_support.py, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-1.md](2026-10-05-issue-235-retained-review-evidence.tasks/task-1.md)
Task 2 — The portable evidence suite — tests/test_review_evidence.py, justfile — full — [task-2.md](2026-10-05-issue-235-retained-review-evidence.tasks/task-2.md)
Task 3 — Built parity and reproduction from the retained objects — tests/retained_review_test_support.py, tests/test_review_retained_full.py, tests/test_agent_tools_launchers.py — full — [task-3.md](2026-10-05-issue-235-retained-review-evidence.tasks/task-3.md)
Task 4 — The architecture sentence and the parent audit — CLAUDE.md, .agents/artifacts/specs/2026-10-05-issue-226-parent-audit.md — full — [task-4.md](2026-10-05-issue-235-retained-review-evidence.tasks/task-4.md)

## Execution gates

Every gate runs in the matching gate environment: define `core_gate` exactly as the CORE plan's "Matching gate environment" section does (`.agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.md`) and use `source` mode with this worktree as `TREE` and the recipe's `python3` as `PYTHON`. Never use an ambient checker. Keep outputs and logs outside the worktree, in this child's SDD workspace (`EV` below). There is no G2: this child changes no source (EV8).

```sh
TREE=$(git rev-parse --show-toplevel); PY=$(command -v python3); HEAD_SHA=$(git rev-parse HEAD)
BASE=8971e41802fd2ee4de8d1c85626ea1cdcf2d384d
PLAN=$TREE/.agents/artifacts/plans/2026-10-05-issue-235-retained-review-evidence.md
```

**Closure check, before every gate.** Through Task 1 the second line must hold too.

```sh
test "$(git log --format=%H --no-merges "$BASE"..HEAD ^origin/main -- python | wc -l)" -eq 0
test "$(git rev-parse HEAD:python)" = 6ce6afdda7b95e749184fcd8e132fc0a38de915e
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

Only exit 0 with `complete/within_budget`, validated and reproduced, clears G0. Exit 2 or 3 stops with no bootstrap. Task 1 starts only after G0 has cleared at 0, and that result file predates the publication commit.

Planning G0 at `--completed-through 0`: at head `c77f2be`, exit 0 and `complete/within_budget`: root 9,208 of 16,384 B, total 399,663 of 524,288 B, largest member 62,467 B, `file_count` 9 (eight of eight payload members, so a forecast revision has no spare member), validated and reproduced. The recording commit changes no forecast.

**G1, the complete fixed-base actual gate, after every task and fix and at the final head.**

```sh
core_gate source "$TREE" "$PY" timeout 900 python3 -m agent_tools.review_package "$PLAN" "$BASE" "$HEAD_SHA" > "$EV/g1-$HEAD_SHA.json"
core_gate source "$TREE" "$PY" artifact-budget validate-report --boundary producer --input "$EV/g1-$HEAD_SHA.json" | cmp - "$EV/g1-$HEAD_SHA.json"
core_gate source "$TREE" "$PY" artifact-budget check --kind review-package --format json \
  --root "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact"]["path"])' "$EV/g1-$HEAD_SHA.json")"
```

Both must show `complete/within_budget` with identical metrics; G1 overrides every forecast. After each task, record its `actual_ranges` and refresh `actual_evidence` in a process-only commit, then renew G0.

**Actual-only equality.** At the final head, with every range recorded, G0 at `--completed-through 4` reports the four metrics G1 reports there.

**G3, final.** In this order, each bounded, with no skip counted as a pass:

```sh
PYTHONPATH=python timeout 600 python3 -m unittest tests/test_review_evidence.py
timeout 7200 just agent-workflow-tests
timeout 3600 just build
timeout 3600 just agent-installed-skill-tests > "$EV/installed.log" 2>&1
grep -A1 '^test_committed_evidence_replays_alike_from_source_and_built ' "$EV/installed.log" | grep -q '\.\.\. ok$'
timeout 14400 just agent-retained-tests /Users/anis/tmp/nix-config > "$EV/retained.log" 2>&1
grep -A1 '^test_committed_evidence_reproduces_with_the_reviewed_tool ' "$EV/retained.log" | grep -q '\.\.\. ok$'
```

The retained run is quiescent (RP11); a changed root voids it and it is repeated. Then separate authorship-independent conformance and correctness reviews read the complete fixed-base delivery, the audit included. Required CI remains the merge gate. Nothing is activated. The pull request closes issue 235 only; after the merge the controller posts the audit's verdict on issue 226 with a link to the document at the merge commit (EV7).

## Acceptance coverage

| Issue 235 criterion | Verified by |
|---|---|
| 1. Exact committed bytes; independent anchor; two derivations; absent at base | Task 1 Steps 1, 3, 7 and 8; Task 2's authentic case; Task 3's reproduction case |
| 2. Issue-121 facts | Task 2 `test_issue121_facts` |
| 3. Task-7 table; Task 8 unexecuted | Task 2 `test_task7_facts` |
| 4. Issue-100 facts; distinct domains | Task 2 `test_issue100_facts` |
| 5. Source and built replay agree; tamper refusals; no leaks | Task 2's authentic, changed-copy, trusted-site, rehashed-change and leak cases; Task 3's built case |
| 6. Forecast, projection and actual gates | G0 at 0 before Task 1; each task's controller step; the equality above |
| 7. Verification runs; independent reviews; parent audit | G3; Task 4 |

## Decisions

EV1, EV2, EV5 and EV13 govern Task 1; EV3, EV6 and EV11 govern Task 2; EV3, EV4, EV10 and EV14 govern Task 3; EV7, EV9 and EV12 govern Task 4; EV8 governs the gates.

## Standards review provenance

Reviewer: Codex (`plan-review`, isolated, read-only, no fallback), plan head `e56bf56`, base `8971e41802fd2ee4de8d1c85626ea1cdcf2d384d`. Blocking 0. Should fix 1, accepted with a narrower correction (EV14): Task 3's claim about `AGENT_RETAINED_TOOL_COMMIT` now matches the class setup. Rejected 0, deferred 0.

## Review feasibility delivery

```json
{"actual_evidence":{"head":"5c740510554fa53403f29004678ddbf1a1a4d4e3","kind":"git-range-ownership/v1","process_ranges":[{"base":"8971e41802fd2ee4de8d1c85626ea1cdcf2d384d","boundaries":["evidence"],"head":"5175e66344b1f740a99ffbeb8117bafca1f4f52a"},{"base":"cea9765ef12398af971d40583ce6fe27476f34f5","boundaries":["evidence"],"head":"c255be69d77b30adb2b75e02cadd762446a4f984"},{"base":"3b485c9c38c79a862cc57fd3d5e4a0f9d743605f","boundaries":["evidence"],"head":"d0dd665546c84f561a47218ebf7d7a96260b4d8b"},{"base":"9b68dd396e6035c715abd347c1a5a11e5e4c87ab","boundaries":["evidence"],"head":"229b33fc209e8bc27a387ece8625a8fae41ef5ad"}],"tree":"0bf3bf37c74f4246759d69e9039baa8ea4975548"},"boundaries":[{"acceptance":"Complete EVIDENCE: the retained bundle committed as derived at the reviewed tool commit, its trust pin, the tests of the committed copy, the architecture sentence and the parent audit; G0, G1 and G3 gates and independent reviews.","depends_on":[],"id":"evidence","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["p1","p2","p3","p4","p5","p6"],"process_package":{"plan":".agents/artifacts/plans/2026-10-05-issue-235-retained-review-evidence.md","spec":".agents/artifacts/specs/2026-10-05-issue-235-retained-review-evidence-design.md","tasks":[".agents/artifacts/plans/2026-10-05-issue-235-retained-review-evidence.tasks/task-1.md",".agents/artifacts/plans/2026-10-05-issue-235-retained-review-evidence.tasks/task-2.md",".agents/artifacts/plans/2026-10-05-issue-235-retained-review-evidence.tasks/task-3.md",".agents/artifacts/plans/2026-10-05-issue-235-retained-review-evidence.tasks/task-4.md"]},"tasks":[1,2,3,4]}],"delivery_base":"8971e41802fd2ee4de8d1c85626ea1cdcf2d384d","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":415,"boundary":"evidence","deleted_lines":0,"record_bytes":33792,"support":{"covers":["p1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p1","last_task":4,"owner":0,"path":".agents/artifacts/specs/2026-10-05-issue-235-retained-review-evidence-design.md"},{"bounds":[{"added_lines":190,"boundary":"evidence","deleted_lines":0,"record_bytes":17408,"support":{"covers":["p2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p2","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-10-05-issue-235-retained-review-evidence.md"},{"bounds":[{"added_lines":201,"boundary":"evidence","deleted_lines":0,"record_bytes":16384,"support":{"covers":["p3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p3","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-10-05-issue-235-retained-review-evidence.tasks/task-1.md"},{"bounds":[{"added_lines":334,"boundary":"evidence","deleted_lines":0,"record_bytes":25088,"support":{"covers":["p4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p4","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-10-05-issue-235-retained-review-evidence.tasks/task-2.md"},{"bounds":[{"added_lines":146,"boundary":"evidence","deleted_lines":0,"record_bytes":13312,"support":{"covers":["p5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p5","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-10-05-issue-235-retained-review-evidence.tasks/task-3.md"},{"bounds":[{"added_lines":111,"boundary":"evidence","deleted_lines":0,"record_bytes":12800,"support":{"covers":["p6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p6","last_task":4,"owner":0,"path":".agents/artifacts/plans/2026-10-05-issue-235-retained-review-evidence.tasks/task-4.md"}],"proposed_boundary":"evidence","schema_version":3}
```
