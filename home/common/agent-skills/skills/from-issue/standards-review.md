# Phase 5 detail — standards review

Unless Phase 0 marked the issue `mechanical-only`:

## Caller input gate

In order; any failure stops before reviewer dispatch on both routes.

1. Pipe the planning producer's stdout bytes through `artifact-budget validate-report --boundary producer --input -`; decode only those.
2. Require `state: complete`, an implementation-plan artifact and `budget_status: within_budget`.
3. Run `artifact-budget check --kind implementation-plan --root <reported-root> --format json` and compare the root and all four metrics. Exit 2, exit 3, malformed metrics or a mismatch fails.
4. Compute `<base>`, never from the report: `git merge-base HEAD origin/<integration-branch>`. `review-feasibility confirm --plan <root> --base <base> --input -` over the report's `projection` must exit 0.
5. Read `capabilities.review.plan` from the retained snapshot, passing its explicit hint paths to the packet:
   - **Blocked** stops, surfacing its `reason_code` and `repair_id`; no fallback.
   - **Available and `codex-collaboration` available** → invoke its `plan-review` operation, which assembles the packet. The one native fallback follows only a completed non-capacity runtime/output failure, never a busy reviewer. Supply the issue number and criteria, the Phase-0 investigation and open questions, the worktree base SHA, the spec path, `bindings.tracker`, `bindings.paths`, the review capability, the plan root with its four checker metrics (no member list or contents), and the absolute path (never the contents) of `REVIEW-CONTRACT.md` beside `SKILL.md`.
   - **Authored unsupported, or that completed non-capacity failure** (including native Codex) →

<!-- agent-dispatch: id=from-issue-plan-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") launches one fresh plan reviewer with no inherited context, the same inputs, and the same `REVIEW-CONTRACT.md` path, told to read that file first.

**Mechanical-only:** replace the dispatch with a self-grade — read the issue, spec, plan, live files and `REVIEW-CONTRACT.md`, then grade into the same buckets. Any behavioral, configuration, interface, generated-output or semantic-documentation effect disqualifies it.

## Dispositioning findings

Verify every actionable finding against the live worktree; record stale or unsupported ones as rejected. Record provenance in the plan (reviewer, job id, base SHA, fallback used) plus each disposition; never copy a raw reviewer transcript into project artifacts.

Apply blocking fixes inline to the plan (standing local-commit authorization). Bring should-fix items to the user (`--auto`: apply them). Append one ledger row per applied **non-obvious** finding — Choice = the edit, Grounding = the reviewer's rationale plus any doc cite, Rejected alternative = what you weighed (or "reviewer's call accepted as-is"); a row reversing a decision names it.

## Accepted-edit remeasurement

After all accepted blocking and should-fix edits, the last plan or ledger write is final. Run `artifact-budget check --kind implementation-plan` over the full plan, and `artifact-budget check --kind design-spec` when the spec or its ledger changed. Apply the owning producer's compact/split remediation once, then recheck. Still over: return `decompose_required` to the decomposition checkpoint, no SDD. After a plan edit, commit and rerun `review-feasibility gate --plan <root> --base <base> --head <HEAD> --completed-through 0 --save-dir "$(sdd-workspace <root>)"`; exit 3 stops likewise, exit 2 is `failed`. Only `within_budget` with gate exit 0 advances.
