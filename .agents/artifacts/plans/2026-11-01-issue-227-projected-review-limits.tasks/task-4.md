# Task 4: Skill callers adopt the forecast, the gates and the stop

**Files:**
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/from-issue/standards-review.md`
- Modify: `home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/delegated-owner.md`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: `review-feasibility gate --plan <root> --base <base> --head <HEAD> --completed-through 0` and `review-feasibility confirm --plan <root> --base <base> --input -` (Task 1, exits 0/3/2); the producer report shapes Task 2 validates (`projection` on `implementation-plan` reports only).
- Produces: the machine text below, which the execution half and Task 5's replay rely on; the `**Decomposition stop.**` paragraph in from-issue `SKILL.md`, the one home of the reconciliation rule (D6), which the Phase-6 route cites by that name.

- Consumes (execution half): `sdd-gate record PLAN_FILE --task N` and its ready object (Task 3); `sdd-gate next` refusals at `projection` and `validate-report` (Task 3); `review-feasibility confirm` (Task 1); the SDD `decompose_required` shape (Task 2); the planning half's `**Decomposition stop.**` paragraph and `PROJECTION_MACHINE_TEXT`.
- Produces (execution half): the sdd controller loop and the Phase-6 stop route below; no new names.


**Invariants — planning half:**
- writing-plans gains a compact `## Review feasibility forecast` section (D14 places it inside `SKILL.md`, hot because every plan carries one, D9): the two block headings; one fenced `json` line of canonical JSON each; the delivery fields (`schema_version: 3`, `kind`, `delivery_base`, `proposed_boundary`, `boundaries`, `process_records`, `actual_evidence` with `kind: git-range-ownership/v1`, head and tree of the delivery base and no `process_ranges` at planning time, `derived_from: null`); boundary fields (root holds every task; children partition parents; `depends_on` chains with `completed-tasks` prerequisites holding null `commit`/`tree`; each boundary's own `process_package`, `process_forecast_ids`, and one 64-byte entry in `process_commit_subject_bytes` per future process commit); a record per `Files:` path with one `authored-cumulative/v1` bound per containing boundary; conservative whole-record bounds that include fix rounds, recordings and the Phase-5 edit; and that field semantics are in nix-config's `python/README.md` § Review feasibility forecast (Task 1).
- writing-plans' `## Package budget` / `## Return control` run, after the final mutation (a mechanical-only self-grade's edits included): pin the base with `git merge-base HEAD origin/<integration-branch>`, commit, then the gate with `--save-dir "$(sdd-workspace <root>)"`, which keeps the full validated result (D20). Exit 0 → `complete` with the summary as `projection`; exit 3 → `decompose_required` whose artifact stays `within_budget`, plus `projection`; exit 2 → one forecast correction round, commit and rerun, then `failed` with the tool's reason in notes (D7). An artifact overage keeps today's over-budget report without `projection`.
- AUTO.md's plan subagent section gains `projection` in its exact `complete` report and an exact projected `decompose_required` report; both existing `"violations":["root_bytes"]` reports stay (the existing count test expects 2).
- standards-review's caller input gate: after the independent `artifact-budget check`, the caller computes the base itself by `git merge-base HEAD origin/<integration-branch>` (D13) and runs `review-feasibility confirm`; exit 0 is required before any reviewer dispatch. The Accepted-edit remeasurement reruns `review-feasibility gate` (same `--save-dir`) after accepted plan edits and stops on exit 3 or 2.
- REVIEW-CONTRACT grades the forecast: a `Files:` path with no record, a missing process artifact or recording subject, or a bound below the task's stated scope is Blocking (D12).
- from-issue `SKILL.md` § Artifact report boundary confirms an `implementation-plan` report's `projection` (exit must be 0 for `complete`, 3 for `decompose_required`; any other exit or a disagreement is `failed`); a confirmed `decompose_required` takes the Decomposition stop. That paragraph says: the attempt ends `stopped` through the terminal return procedure; notes lead with the class, gate head, ordinal and the recommendation's id and tasks or "new design required" (D13); worktree, branch, workspace, ledger and saved result are kept; nothing is acquired, filed, repinned or dispatched; each derived delivery needs a new issue, spec, plan, base, forecast, package and reviews; closing the stopped issue or its parent needs a reconciliation record mapping every original criterion and operational effect to an accepted child's immutable identities, actual package, review and operational evidence, and a closed checkbox is not evidence (D6).
- Instruction budget (D14): every edited instruction document ends no larger in bytes than at the delivery base. Fund additions by tightening prose in the same document; keep every machine-text pin, delete an existing English-phrase pin on text you cut in this commit (agent-helpers rule 6, D22), never edit `instruction-load.json`, never apply or name the user-only raise label.

**Invariants — execution half:**
- sdd Step 5: after a clean review (or everything parked at the cap), run `sdd-gate record PLAN_FILE --task N`, commit exactly its `paths` as one process-only commit with subject `plan: record task <N> evidence` (under a lifecycle identity through self-registration and `launch-commit`, as final-review.md's acceptance record; otherwise plain `git commit`), then `sdd-gate next --completed N` with `--task N+1` when one remains (D2). Forecast blocks change only through `record` after SDD entry (D12).
- sdd Step 1 refusal routing:
  - step `projection`, `gate: decompose_required` → `review-feasibility confirm --plan PLAN_FILE --base DELIVERY_BASE --input -` over the refusal's `report` must exit 3 → SDD `decompose_required` with `stop: {"kind":"projected_overflow","projection":<confirm stdout>}`;
  - step `validate-report`, `gate: decompose_required` → `artifact-budget check --kind review-package --root <report artifact path>` must agree on all four metrics and the violations → SDD `decompose_required` with `stop: {"kind":"actual_overage","artifact":<report artifact>}`;
  - `gate: failed`, a confirm exit other than 3, or any disagreement → SDD `failed`.
  No later dispatch follows a stop; the workspace, ledger and worktree are kept (D6). A plan without forecast blocks fails at the first projection (D9).
- sdd Finish: the exact SDD key list gains `stop` for `decompose_required` only, with `review_state: unknown`, both verdicts and `verification_state` `not_run`, `acceptance_state: not_applicable`, `detail_state: none`, `report_path: null`, and `base_sha`/`head_sha` the refused gate's range (the summary's for a projected overflow; `DELIVERY_BASE` and the gate head for an actual overage). The Review-package gate's exit-3 bullet points to this state.
- from-issue `SKILL.md` Phase 6: a validated SDD `decompose_required` is verified before any continuation — `projected_overflow` by `review-feasibility confirm --plan <root> --base <base> --input -` over `stop.projection` (exit 3, base computed by `git merge-base HEAD origin/<integration-branch>`, never copied from the report, D13), `actual_overage` by an independent `artifact-budget check --kind review-package` on `stop.artifact.path` agreeing with it — then takes the Decomposition stop; a disagreement is `failed`.
- delegated-owner.md: an SDD `decompose_required` takes that Phase-6 route in place of `progress` or `delegate`.
- Instruction budget (D14): `sdd/SKILL.md`, from-issue `SKILL.md` and `delegated-owner.md` each end no larger in bytes than at the delivery base. Fund additions by replacing the sdd "Cumulative delivery gate" and "Review-package gate" prose that `sdd-gate` now enforces with a pointer to its steps; machine-text pins stay, English-phrase pins on cut text go (D22).

- [ ] **Step 1: Write the failing tests** in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

```python
# Machine-consumed text only (agent-helpers rule 6, D22): helper argv, the block headings
# and kinds the forecast loader reads, and report JSON the validators read. No English phrase.
PROJECTION_MACHINE_TEXT = {
    WRITING_PLANS: (
        "## Review feasibility delivery", "## Review feasibility task", "git-range-ownership/v1",
        "authored-cumulative/v1", "git merge-base HEAD origin/<integration-branch>",
        "review-feasibility gate --plan <root> --base <base> --head <HEAD> --completed-through 0",
        '--save-dir "$(sdd-workspace <root>)"', "`projection`"),
    FROM_ISSUE_DIR / "AUTO.md": (
        '"budget_status":"within_budget"},"projection":',
        '{"state":"decompose_required","artifact":{"kind":"implementation-plan"'),
    FROM_ISSUE_DIR / "standards-review.md": (
        "review-feasibility confirm --plan <root> --base <base> --input -",
        "git merge-base HEAD origin/<integration-branch>"),
    FROM_ISSUE_DIR / "SKILL.md": ("review-feasibility confirm --plan <root> --base <base> --input -",),
}
BUDGET_BASE = "8d0bbc25383663fa3bc86623d0701e7d4bd4f9bc"


class ProjectionCallerContractsTest(unittest.TestCase):
    def test_projection_callers_carry_their_machine_text(self):
        for path, items in PROJECTION_MACHINE_TEXT.items():
            text = normalized(path.read_text(encoding="utf-8"))
            for item in items:
                with self.subTest(path=path.name, item=item):
                    self.assertIn(item, text)

    def test_the_planning_confirmation_precedes_reviewer_dispatch(self):
        gate = (FROM_ISSUE_DIR / "standards-review.md").read_text(encoding="utf-8")
        gate = normalized(gate.split("## Caller input gate", 1)[1].split("## Dispositioning findings", 1)[0])
        self.assertLess(gate.index("artifact-budget check --kind implementation-plan --root"),
                        gate.index("review-feasibility confirm"))
        self.assertLess(gate.index("review-feasibility confirm"), gate.index("capabilities.review.plan"))

    def test_edited_planning_documents_do_not_grow(self):
        for path in (WRITING_PLANS, FROM_ISSUE_DIR / "AUTO.md", FROM_ISSUE_DIR / "standards-review.md",
                     PHASE_5_REVIEW_CONTRACT, FROM_ISSUE_DIR / "SKILL.md"):
            relative = path.relative_to(REPO_ROOT).as_posix()
            shown = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-s", f"{BUDGET_BASE}:{relative}"],
                                   capture_output=True, text=True)
            if shown.returncode:
                self.skipTest("delivery base not in this clone")
            with self.subTest(path=relative):
                self.assertLessEqual(path.stat().st_size, int(shown.stdout))
```

Then, for the execution half:

```python
PROJECTION_MACHINE_TEXT[SDD] = (
    "sdd-gate record PLAN_FILE --task N", "sdd-gate next --completed N",
    "review-feasibility confirm --plan PLAN_FILE --base DELIVERY_BASE --input -",
    '"kind":"projected_overflow"', '"kind":"actual_overage"',
    "artifact-budget check --kind review-package")
PROJECTION_MACHINE_TEXT[FROM_ISSUE_DIR / "delegated-owner.md"] = ("decompose_required",)


class ExecutionCallerContractsTest(unittest.TestCase):
    def test_record_precedes_next_and_phase_6_confirms(self):
        sdd = normalized(SDD.read_text(encoding="utf-8"))
        self.assertLess(sdd.index("sdd-gate record PLAN_FILE --task N"), sdd.index("sdd-gate next --completed N"))
        phase6 = normalized((FROM_ISSUE_DIR / "SKILL.md").read_text(encoding="utf-8")
                            .split("## Phase 6", 1)[1].split("## Phase 7", 1)[0])
        self.assertIn("review-feasibility confirm --plan <root> --base <base> --input -", phase6)

    def test_edited_execution_documents_do_not_grow(self):
        for path in (SDD, FROM_ISSUE_DIR / "SKILL.md", FROM_ISSUE_DIR / "delegated-owner.md"):
            relative = path.relative_to(REPO_ROOT).as_posix()
            shown = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-s", f"{BUDGET_BASE}:{relative}"],
                                   capture_output=True, text=True)
            if shown.returncode:
                self.skipTest("delivery base not in this clone")
            with self.subTest(path=relative):
                self.assertLessEqual(path.stat().st_size, int(shown.stdout))
```

Place the two `PROJECTION_MACHINE_TEXT[...]` assignments directly after the dictionary above, so `ProjectionCallerContractsTest` checks them too.

- [ ] **Step 2: Run and watch it fail**

Run: `timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k CallerContracts 2>&1 | tail -3`
Expected: FAIL — the machine text is absent.

- [ ] **Step 3: Edit the eight documents** to both halves' Invariants, wording each new sentence from the live Task 1–3 behavior, then cut until each edited instruction document is no larger than at base. Add no English-phrase assertion; delete any existing phrase pin whose text you cut (D22).

- [ ] **Step 4: Verify**

Run: `timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3` — Expected: `OK`.
Run: `bash -c 'set -o pipefail; timeout 600 just agent-instruction-budget 2>&1 | tail -2'` — Expected: ends `check: pass`.
Run: `timeout 3600 just build 2>&1 | tail -2` — Expected: success.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(skills): gate plans and sdd tasks on projected limits"
```

Decisions: D2, D5–D9, D12–D14, D20, D22.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":4,"records":[{"bounds":[{"added_lines":140,"boundary":"all","deleted_lines":140,"record_bytes":20480,"support":{"covers":["r4a"],"kind":"authored-cumulative/v1"}},{"added_lines":140,"boundary":"c3","deleted_lines":140,"record_bytes":20480,"support":{"covers":["r4a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4a","last_task":4,"owner":4,"path":"home/common/agent-skills/skills/writing-plans/SKILL.md"},{"bounds":[{"added_lines":20,"boundary":"all","deleted_lines":20,"record_bytes":8192,"support":{"covers":["r4b"],"kind":"authored-cumulative/v1"}},{"added_lines":20,"boundary":"c3","deleted_lines":20,"record_bytes":8192,"support":{"covers":["r4b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4b","last_task":4,"owner":4,"path":"home/common/agent-skills/skills/from-issue/AUTO.md"},{"bounds":[{"added_lines":12,"boundary":"all","deleted_lines":12,"record_bytes":6144,"support":{"covers":["r4c"],"kind":"authored-cumulative/v1"}},{"added_lines":12,"boundary":"c3","deleted_lines":12,"record_bytes":6144,"support":{"covers":["r4c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4c","last_task":4,"owner":4,"path":"home/common/agent-skills/skills/from-issue/standards-review.md"},{"bounds":[{"added_lines":10,"boundary":"all","deleted_lines":10,"record_bytes":6144,"support":{"covers":["r4d"],"kind":"authored-cumulative/v1"}},{"added_lines":10,"boundary":"c3","deleted_lines":10,"record_bytes":6144,"support":{"covers":["r4d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4d","last_task":4,"owner":4,"path":"home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md"},{"bounds":[{"added_lines":40,"boundary":"all","deleted_lines":40,"record_bytes":28672,"support":{"covers":["r4e"],"kind":"authored-cumulative/v1"}},{"added_lines":40,"boundary":"c3","deleted_lines":40,"record_bytes":28672,"support":{"covers":["r4e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4e","last_task":4,"owner":4,"path":"home/common/agent-skills/skills/from-issue/SKILL.md"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":4,"record_bytes":8192,"support":{"covers":["r4f"],"kind":"authored-cumulative/v1"}},{"added_lines":4,"boundary":"c3","deleted_lines":4,"record_bytes":8192,"support":{"covers":["r4f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4f","last_task":4,"owner":4,"path":"home/common/agent-skills/skills/from-issue/delegated-owner.md"},{"bounds":[{"added_lines":70,"boundary":"all","deleted_lines":70,"record_bytes":18432,"support":{"covers":["r4g"],"kind":"authored-cumulative/v1"}},{"added_lines":70,"boundary":"c3","deleted_lines":70,"record_bytes":18432,"support":{"covers":["r4g"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4g","last_task":4,"owner":4,"path":"home/common/agent-skills/skills/sdd/SKILL.md"},{"bounds":[{"added_lines":100,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["r4h"],"kind":"authored-cumulative/v1"}},{"added_lines":100,"boundary":"c3","deleted_lines":0,"record_bytes":12288,"support":{"covers":["r4h"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4h","last_task":4,"owner":4,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"}]}}
```
