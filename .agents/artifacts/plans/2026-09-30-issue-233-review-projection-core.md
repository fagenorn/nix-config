# Issue 233 Review Projection Core Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Publish actual packing and generic projection with authenticated Git history and source/built parity.

**Architecture:** Recover shared actual/generic operations, correct original-history authentication and preserve whole-path proof. Project the entire plan before new generic publication. The [spec](../specs/2026-09-30-issue-233-review-projection-core-design.md) owns D1–D9, R1–R4 and the behavioral contract.

**Tech stack:** Python standard library, Git plumbing, canonical JSON, unittest, Nix/Home Manager and just.

## Global Constraints

- Design identity `DP226-CORE`; immutable `DELIVERY_BASE=8836b641551b1ab6f2662379f0c0b83e38f5a0fb`. All gates include every later product/process commit; integration never moves this base.
- One shared original-history authority authenticates raw commit object identity, tree and ordered parent headers independently of traversal/evidence hashes.
- No changed caps, hidden costs, forecast fiction or generated-exemption expansion.
- Preserve U10 sequential whole-record packing. Only initial member-count or aggregate overflow permits U7/U5/U3/U1/U0 stable first-fit whole-file candidates, in that order. Select the first pass; if all fail, return the initial candidate's result.
- Success is `complete/within_budget` with exit 0; valid overflow is `decompose_required/over_budget` with exit 3. Invalid/unavailable input, provenance, support or reconstruction uses exit 2 and no success object.
- CORE's own plan has `derived_from: null`. Only complete CORE is declared; task reviews grant no delivery/bootstrap authority.
- New helpers use `python/agent_tools`, ordinary imports, canonical hooks/digests and the existing sibling helper. External commands run by name on PATH. No dynamic imports, path-derived module calls or private estimator.
- D2/D7 allow corrected shared source, necessary tests and only indispensable existing-actual-command relocation wiring. Generic publication and broader installed/docs work await the source gate.
- No retained adapters/models/fixtures/derivation/replay, caller adoption, lifecycle changes or host activation. Preserve the parent and other child scopes.
- Signed commits with `Co-Authored-By: Codex <noreply@openai.com>`. Code/docstrings/comments and living docs describe verified behavior; settle uncertain prose during implementation before committing it.

## Test seams

- Existing pure packing/source subprocess seams, temporary real Git repositories, real external policy and independent actual production/checking.
- `tests/test_agent_tools_launchers.py` via `just agent-installed-skill-tests`: actual built commands and private per-case layouts.
- Required verification command IDs: `agent-workflow-tests` → `just agent-workflow-tests`; `nix-build` → `just build`, in this worktree. Installed skips never accept deployment.

## Delivery estimate and boundaries

Estimate: two full-lane tasks, 26 product and four process paths. Members measure frozen U10 records and new-code/correction allowances. External review caps observed: root 16,384; payload 65,536; eight payloads; aggregate 524,288 bytes; manifest counts in root/aggregate/file count. Plan caps: 16,384/49,152/eight/131,072. Runtime policy remains authoritative. No fit claim or smaller CORE boundary; overflow stops. Unsupported proof is not overflow; 234/235 retain their D1 scopes.

Keep all supported bounds. Extra scope needs a supported committed revision and fresh gates, never truncation or lowered ceilings. Process full-record bounds use final UTF-8 bytes + line prefixes + 512 header bytes, then reserves: spec 2,048 bytes/24 lines; root 1,024/20; Task 1 3,072/48; Task 2 2,048/32. Retain prior bounds if compaction reduces text. Shared `lib/agent-tools.nix`, `CLAUDE.md`, `tests/test_agent_tools_launchers.py` have ordered cumulative Task-1/2 support and horizon 2; other product horizons equal their owner. All process horizons are 2. Forecast the move as delete+add; the generic loader cannot support a speculative rename proof.

Task 1 reserves four 120-byte subjects (implementation, optional move, two fixes), Task 2 three (publication, two fixes), process ten (artifact review fixes/checkpoints). Encoded-subject costs persist until actual substitution; exhausted reserves need revision. Charge every fixed-base effect; subranges clear nothing.

## Task index

Task 1 — Recover and authenticate the shared source closure — python/agent_tools/review_pack.py, python/agent_tools/review_actual.py, python/agent_tools/review_budget.py, python/agent_tools/review_publish.py, python/agent_tools/review_package.py, python/agent_tools/review_forecast.py, python/agent_tools/review_projection.py, python/agent_tools/review_feasibility.py, python/agent_tools/review_git.py, home/common/agent-skills/skills/sdd/scripts/review-package, home/common/agent-skills/scripts/artifact_budget.py, home/common/agent-skills/tests/test_artifact_budget.py, home/common/agent-skills/tests/test_review_package.py, home/common/agent-skills/tests/test_workflow_skill_contracts.py, tests/test_agent_tools_launchers.py, tests/test_review_pack.py, tests/test_review_feasibility.py, tests/test_review_projection_cases.py, tests/test_review_history.py, lib/agent-tools.nix, home/common/agent-skills/default.nix, justfile, CLAUDE.md, home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/skills/sdd/final-review.md, home/common/agent-skills/skills/sdd/fix-loop.md — full — [task-1.md](2026-09-30-issue-233-review-projection-core.tasks/task-1.md)
Task 2 — Publish and verify the generic managed command — lib/agent-tools.nix, CLAUDE.md, tests/test_agent_tools_launchers.py — full — [task-2.md](2026-09-30-issue-233-review-projection-core.tasks/task-2.md)

## Execution and complete-package gates

Admission is unavailable (D2). Commit/check this package and pass the actual gate before recovery. Baseline at the immutable base: `just agent-workflow-tests`, 1,747 tests, three installed-environment skips; evidence in the primary SDD workspace's `baseline.md`. No plan-only rerun; skips never accept installation.

**Complete actual gate (before implementation, every task/fix, final head):** pin exact full HEAD; run `review-package PLAN DELIVERY_BASE HEAD` (after relocation use `core_gate` below). Capture exit/stdout unchanged. Validate through `artifact-budget validate-report --boundary producer --input REPORT`, then independently run `artifact-budget check --kind review-package --root ROOT --format json`. Require exit 0/`complete/within_budget`, identical four integer metrics (not booleans), exact manifest base/head and complete records/changed lines. Use external reports/logs and fresh primary SDD package locations. Legacy production admits no source. Exit 2/3 stops; every task/fix gets independent full-lane review and focused/full/applicable build checks.

**Source gate:** at the earliest corrected independently reviewed source commit, pin commit/tree and the complete transitive closure: nine review modules, canonical/siblings/package metadata, selected external dependencies below and command mappings. Record sorted path→blob/raw-SHA256 entries and shared-canonical digest, Git/Python versions and packing/artifact-policy identities; extend for real imports. Independently compare committed/loaded bytes before and after each operation.

Refresh exact ownership/checkpoint metadata as below and commit the process-only update. In the matching environment below invoke `python3 -m agent_tools.review_feasibility project --plan PLAN --base DELIVERY_BASE --head HEAD --completed-through 1 --package-name NAME`, using the actual producer’s range basename NAME. Capture exit and canonical bytes; run the same closure's `validate-result --input RESULT --producer-exit 0`. An independent matching-closure invocation reloads/projects committed inputs and compares every closed v3 field: all identities/digests, basename, ordinal/boundary, counts, four metrics, status/violations and null recommendation. Bind root/member/spec hashes separately; require identical canonical results, exit 0/within-budget and complete actual acceptance. Shape alone clears nothing; all remaining publication/tests/process costs project. Exit 2 or 3 stops without Task 2 or an extended bootstrap. Source changes repeat review/closure/projection; plan/spec changes repeat committed budgets/projection. Never defer an available corrected-source gate behind extra work.

**Final gate:** completed-through 2, refreshed ownership; require actual-only candidate/name/four-metric parity with independent producer/checker. Run focused tests, full `agent-workflow-tests`, managed `nix-build`, installed checks without acceptance-by-skip and separate authorship-independent final conformance and correctness reviews over the complete fixed-base delivery. Required CI remains the merge gate. Controller owns lifecycle/ship; no activation.

## Forecast ownership and support

The delivery block pins design checkpoint/tree and owner-zero range. Artifact amendments are process-only tails; task actual ranges start empty. Classify every reachable base..checkpoint commit exactly once with disjoint topologically ordered product/task or process ranges, never path-filtered approximations. Preserve every original parent edge and authenticated endpoint. Before each product projection, refresh checkpoint head/tree and exact ranges, then commit only spec/root/members as metadata tail; no self-hashing commit ID or undeclared tail path.

Retain contribution IDs/ranges/horizons and all actual/tail/subject costs. Only spec/root/members are process paths; tests/wiring are product. Every correction repeats gates; v3 prefixes/larger-actual rules remain unchanged.

## Matching gate environment

D8/B2: every post-relocation producer/checker/project/validator uses `core_gate`, from the worktree; only pre-recovery actual production uses the legacy installation. `TREE` is its absolute root for `source`, or the unique built home-manager-files root obtained by the installed-test recipe for `built`. `PYTHON` is the resolved recipe interpreter for source, or the absolute store interpreter matched by `LAUNCHER` in the built `review-package` launcher. Fingerprint selections; never activate or modify host HOME. Calls clean their private layouts; retain outputs outside them.

```sh
core_gate() (
  gate_mode=$1; gate_tree=$2; gate_python=$3; shift 3
  gate_tmp=$(mktemp -d "${TMPDIR:-/tmp}/core233-gate-XXXXXX") || exit 2
  trap 'rm -rf -- "$gate_tmp"' EXIT HUP INT TERM
  mkdir -p "$gate_tmp/home" "$gate_tmp/bin" || exit 2
  case "$gate_mode" in
    source)
      gate_agents="$gate_tree/home/common/agent-skills"
      mkdir -p "$gate_tmp/home/.agents/lib/python" "$gate_tmp/home/.agents/share" || exit 2
      for gate_item in artifact_budget.py delivery_model; do
        ln -s "$gate_agents/scripts/$gate_item" "$gate_tmp/home/.agents/lib/python/$gate_item" || exit 2
      done
      ln -s "$gate_agents/artifact-budget-policy.json" "$gate_tmp/home/.agents/share/artifact-budget-policy.json" || exit 2
      gate_budget="$gate_agents/scripts/artifact-budget"
      gate_workspace="$gate_agents/skills/sdd/scripts/sdd-workspace"
      gate_modules="$gate_tree/python" ;;
    built)
      ln -s "$gate_tree/.agents" "$gate_tmp/home/.agents" || exit 2
      gate_budget="$gate_tree/.agents/bin/artifact-budget"
      gate_workspace="$gate_tree/.agents/bin/sdd-workspace"
      gate_modules= ;;
    *) exit 2 ;;
  esac
  ln -s "$gate_budget" "$gate_tmp/bin/artifact-budget" || exit 2
  ln -s "$gate_workspace" "$gate_tmp/bin/sdd-workspace" || exit 2
  ln -s "$gate_python" "$gate_tmp/bin/python3" || exit 2
  for gate_item in bash git basename dirname mkdir; do
    gate_exe=$(command -v "$gate_item") || exit 2
    ln -s "$gate_exe" "$gate_tmp/bin/$gate_item" || exit 2
  done
  env -u PYTHONHOME -u PYTHONSTARTUP -u PYTHONUSERBASE -u NIX_PYTHONPATH \
    -u NIX_PYTHONPREFIX -u NIX_PYTHONEXECUTABLE \
    HOME="$gate_tmp/home" PATH="$gate_tmp/bin:$PATH" \
    PYTHONPATH="$gate_modules" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 "$@"
)
```

Prefix source calls with `core_gate source TREE PYTHON`: `python3 -m agent_tools.review_package ...`, `python3 -m agent_tools.review_feasibility ...`, and `artifact-budget ...`. For built calls use `core_gate built TREE PYTHON` and absolute `TREE/.agents/bin/review-package` or `review-feasibility`; checkers still run by name. Pin resolved wrapper/module/policy/delivery-model/workspace targets, interpreters and helper executable paths/hashes in the closure inventory; compare against committed source or this exact build before/after every operation. Check `describe` matches the expected raw policy first. Preserve Git environment variables; authenticate effective ancestry. Identity/exit disagreement stops. Retain producer/checker outputs and failed exits externally; never use an ambient checker.

## Decisions

D2–D9/R1–R4 govern Task 1 source/compatibility; D1/D2/D5/D7/D8 govern Task 2 publication/parity. These map every acceptance row; the spec owns the ledger.

Phase 5 is clean (0/0/0): native Codex fallback reviewer/job `/root/review_core233_plan`, fix range `f5ece11655ea023edab7a32b1396357a65249f09..e348355530865f838e04446d8e95c34d6adc1d5f`; report `plan-review-r2.md` in primary SDD, preserving initial `plan-review.md`. B1/B2/S1 resolved per D8/D9. This review confers no source admission or fit.

## Review feasibility delivery

```json
{"actual_evidence":{"head":"6d19299ce9de81c32e60ad6b90a6092912825c37","kind":"git-range-ownership/v1","process_ranges":[{"base":"8836b641551b1ab6f2662379f0c0b83e38f5a0fb","boundaries":["core"],"head":"4e1211909f053bc1b0ab72f7f97ae4a33e0512b5"},{"base":"9bc9b2a2f713719b7e9f73ababf57cc125da7218","boundaries":["core"],"head":"6d19299ce9de81c32e60ad6b90a6092912825c37"}],"tree":"b3756f4adf131b519364347a5a209acb1c855a74"},"boundaries":[{"acceptance":"Complete CORE source and managed generic commands; corrected original ancestry; full-plan source gate; actual-only final parity, tests/build/installed checks and independent reviews.","depends_on":[],"id":"core","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[120,120,120,120,120,120,120,120,120,120],"process_forecast_ids":["p1","p2","p3","p4"],"process_package":{"plan":".agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.md","spec":".agents/artifacts/specs/2026-09-30-issue-233-review-projection-core-design.md","tasks":[".agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.tasks/task-1.md",".agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.tasks/task-2.md"]},"tasks":[1,2]}],"delivery_base":"8836b641551b1ab6f2662379f0c0b83e38f5a0fb","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":328,"boundary":"core","deleted_lines":0,"record_bytes":28955,"support":{"covers":["p1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p1","last_task":2,"owner":0,"path":".agents/artifacts/specs/2026-09-30-issue-233-review-projection-core-design.md"},{"bounds":[{"added_lines":135,"boundary":"core","deleted_lines":0,"record_bytes":19482,"support":{"covers":["p2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p2","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.md"},{"bounds":[{"added_lines":509,"boundary":"core","deleted_lines":0,"record_bytes":53465,"support":{"covers":["p3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p3","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.tasks/task-1.md"},{"bounds":[{"added_lines":215,"boundary":"core","deleted_lines":0,"record_bytes":20307,"support":{"covers":["p4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p4","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.tasks/task-2.md"}],"proposed_boundary":"core","schema_version":3}
```
