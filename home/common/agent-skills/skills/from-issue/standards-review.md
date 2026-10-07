# Phase 5 detail — standards review

Loaded from `SKILL.md` at Phase 5. Unless Phase 0 marked the issue `mechanical-only`:

## Caller input gate

In order; any failure stops before reviewer dispatch, on both routes.

1. Pipe the planning producer's received stdout bytes through `artifact-budget validate-report --boundary producer --input -`, then decode only the validated bytes.
2. Require `state: complete`, an implementation-plan artifact and `budget_status: within_budget`.
3. Run `artifact-budget check --kind implementation-plan --root <reported-root> --format json` and compare the root plus all four metrics. Exit 2, exit 3, malformed metrics or a claim mismatch fails.
4. Read `capabilities.review.plan` from the retained snapshot, passing its hint paths to the reviewer packet:
   - **Blocked** stops and surfaces its `reason_code` and `repair_id`; it never takes a fallback.
   - **Available and `codex-collaboration` available** → invoke its `plan-review` operation. It assembles the packet and falls back to the native reviewer once, only after a completed non-capacity runtime/output failure; a busy or concurrent reviewer is never a fallback condition. Supply the issue and acceptance criteria, the Phase-0 investigation and open questions, the worktree base SHA, the spec and plan paths, and the absolute path to `REVIEW-CONTRACT.md` beside `SKILL.md`.
   - **Authored unsupported, or the completed non-capacity runtime/output failure above** (including when this skill runs natively in Codex) →

<!-- agent-dispatch: id=from-issue-plan-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") launches one fresh plan reviewer with no inherited context, the same inputs, and the same `REVIEW-CONTRACT.md` path, told to read that file first.

Pass the contract by path; never inline it.

**Mechanical-only:** replace the dispatch with a self-grade — read the issue, spec, plan, live files, and `REVIEW-CONTRACT.md`, then grade against the same Blocking / Should-fix / Discussion buckets. Any behavioral, configuration, interface, generated-output, or semantic-documentation consequence disqualifies the shortcut.

## Dispositioning findings

Verify every actionable finding against the live worktree before touching the plan; stale or unsupported ones are recorded as rejected, not silently applied. Record provenance in the plan (reviewer, job id, base SHA, whether fallback was used) plus each disposition, and never copy a raw reviewer transcript into project artifacts.

Apply blocking fixes inline to the plan (standing local-commit authorization). Bring should-fix items to the user; in `--auto`, apply them too. Append one ledger row per applied **non-obvious** finding — Choice = the edit, Grounding = the reviewer's rationale plus any doc cite, Rejected alternative = what you weighed (or "reviewer's call accepted as-is") — and a row that reverses an earlier decision names it.

## Accepted-edit remeasurement

After every accepted blocking or should-fix edit, treat the last plan or ledger write as the final mutation. Run `artifact-budget check --kind implementation-plan` over the full plan package, then `artifact-budget check --kind design-spec` when the spec or its decision ledger changed. Compare each result with the previous report; a stale measurement never advances. Apply the owning producer's compact/split remediation once and recheck after its final mutation. If either final check remains over budget, return `decompose_required` to the decomposition checkpoint and do not dispatch SDD. Only a final `within_budget` advances.
