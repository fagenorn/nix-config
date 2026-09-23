# Task 7: Lifecycle skills on interface 2

Decisions: D6, D9, D10, D14, D15, D16, D17, D21, D22, D25, D26. Spec §6 and §7
(the skill rewrite map is this task's checklist). The shapes the prose names are
the live ones: read `S/delivery_model/_wire.py` (`_owner_action`, `_remainder`,
`_ship_handoff`, `_ship_summary`) and Tasks 2–6's CLI rather than paraphrasing.

**Files:**
- Modify: `OI/SKILL.md`, `OI/evals/evals.json`
- Modify: `SK/from-issue/SKILL.md`, `SK/from-issue/AUTO.md`, `SK/from-issue/ship-handoff.md`
- Modify: `SK/ship-issue/SKILL.md`, `SK/ship-issue/REVIEW.md`, `SK/ship-issue/HUMAN-GATE.md`
- Modify: `CLAUDE.md` (one sentence)
- Test: `T/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the helper surface of Tasks 2–6 (`build-delivery` kinds, `-` inputs,
  `contract_digest` in bootstrap, the `delivery_contract` requirement, the
  `delivery_remainder` action/response, `ship-handoff/v2`, `ship-summary/v2`).
- Produces: skill text only; no `agent-dispatch` marker is added or changed (D26).

**Content each document must carry (prose, pinned by the tests below):**
- `OI/SKILL.md`, `SK/from-issue/SKILL.md` and `SK/ship-issue/SKILL.md` each state
  "Every lifecycle call is one command that reads its input from stdin through a
  quoted heredoc" and apply it everywhere: `--request-file -`, `--checkpoint-file
  -`, `--summary-file -`, `--input -`, optionally piped into or out of
  `artifact-budget validate-report --input -`, with the helper named bare or as
  `~/.agents/bin/…` (D22). No temporary request or summary file remains.
- `OI/SKILL.md`: §2 consumes `workflow_bootstrap` requirements with `custody`,
  `recorded_worktree` and `contract_digest`, and observes each issue's forge at the
  `forge_pr` issue-branch prefix; it reports a recorded worktree's state and never
  a candidate for it, and reserves candidates only for issues without a bootstrap
  requirement (D25). §3 shows the exact 17-key request as a `json` block and the
  per-issue contract rule: build with `workflow-state build-delivery --kind
  contract` (source `explicit_user`, reference `invocation:/orchestrate-issues
  <numbers>`, or `standing_repository` with `sweep:<label|milestone>:<value>` per
  D6) for every issue without a bootstrap requirement and every requirement whose
  `contract_digest` is null (using its `recorded_worktree`), send it with its
  initial intent until a summary shows its digest, then null; on a builder refusal
  send null and report the refusal. §4: the closed set `spawn`, `resume`, `retry`,
  `delivery_remainder`, `wait`, `finalize`; project a dispatch action into the
  owner object (rename `id` to `action_id` and `kind` to `launch_kind`, add
  `kind: owner`, `interface_version: 2`, `ledger_repo_root`, `run_id`) and pass it,
  or the `delivery_remainder` object verbatim, as canonical JSON in the one
  existing owner prompt, which validates it with `--boundary workflow-response`
  before use. §5 renders from v2 summaries (custody, `contract_digest`,
  `pending_stage_ids`). The trailing "Interface_version 2 control adapter"
  appendix is folded into §2–§5 and removed.
- `SK/from-issue/SKILL.md`: the dispatcher route adopts the validated owner object
  (or hands a `delivery_remainder` object to the remainder launch); the direct
  section shows the 16-key interface-2 request as a `json` block and the loop:
  observe accepts `tracker`, `recorded_worktree`, `candidate_worktree`, `forge_pr`
  and `delivery_contract`; on `delivery_contract` build the contract with
  `workflow-state build-delivery --repo-root <ledger_repo_root> --kind contract`
  from the recorded worktree when one exists, else the reserved candidate, add its
  initial intent as `authorization_intents`, and resend with every retained fact;
  `kind: delivery_remainder` launches ship-issue remainder mode through the
  existing `from-issue-ship-owner` site with `ship-handoff.md`'s remainder prompt
  (D26). Durable interactive control uses the interface-2 control request. The
  terminal procedure consumes the ship owner's `ship-summary/v2`, runs
  `check-launch`, then `workflow-state finish --summary-file -`; its legacy
  sentence becomes "The legacy `--issue/--attempt/--result-file` transport is
  historical input only: it records a v1 owner's result for an attempt launched
  before interface 2 and is never used by a new run." The "Delivery interface
  version 2" appendix is folded in and removed.
- `SK/from-issue/AUTO.md`: the Phase-5 continuation `owner` is the validated
  interface-2 owner object (19 keys); the ledger-only bookkeeper runs
  `check-launch` and then `workflow-state finish --summary-file -` with the ship
  owner's validated summary.
- `SK/from-issue/ship-handoff.md`: the fenced ship-owner prompt carries a
  `ship-handoff/v2` candidate (one `{"interface_version":2,…}` line naming all 27
  keys: `authorization_intents` is the builder-regenerated initial intent from
  `build-delivery --kind initial-intent`, the id arrays and `selected_outputs` are
  the ones the author holds, `requested_scope` is null) and asks for a
  `ship-summary/v2` return naming its 12 keys; a new `## Remainder owner prompt`
  section carries the `delivery_remainder` object verbatim (D17, D26). The
  "Delivery handoff v2" appendix is folded in and removed.
- `SK/ship-issue/SKILL.md`: a `## Delivery loop` section (D15): pre-selection
  publication stays under the guard and `check-launch`; at the pre-merge
  selection gate on the final CI-green head, build the selection
  (`--kind selected-output`, refs: spec root, durable review report path or review
  state, `checks`) and the now-true `selected_output`, `branch_published` and
  `pr_opened` observations and checkpoint them with the built `merge_pr` scope;
  each post-selection effect runs checkpoint → require the echo to equal the scope
  → `current-launch` → effect → `current-launch` → next checkpoint with its
  observation, one `authority-observation` and the next scope; already-true stages
  are observation-only; a denial is checkpointed as the reducer's `human_gate`
  suspension. The completing observations ride the `ship-summary/v2`
  (`delivery_complete`, legacy `merged` row as `historical_owner_result`). Then a
  `## Remainder mode` section (entered with the `delivery_remainder` object; runs
  the loop from the ledger's ready stage; selection from the PR head when pending;
  writes its own `finish --summary-file -`). The writer rule replaces "A fresh
  ship owner never writes workflow-state itself…" with the exact sentence in
  `WRITER_RULE` below (D16). REVIEW.md and HUMAN-GATE.md appendices point at
  `## Delivery loop` instead of restating it.
- `OI/evals/evals.json`: evals 1 and 2 expect the `interface_version 2`
  bootstrap with `contract_digest`, the request, the per-issue `build-delivery`
  contract rule and the action set with `delivery_remainder`, keeping every anchor
  `test_orchestrate_evals_grade_control_and_reject_retired_policy` pins; no
  "version-1" wording remains.
- `CLAUDE.md`: replace "Producer-report candidates and `workflow-state`'s request
  *and* terminal result files are not written into a working tree at all — they
  are `mktemp` files under `$TMPDIR`, removed by an unconditional cleanup." with
  "Producer-report candidates are not written into a working tree at all — they
  are `mktemp` files under `$TMPDIR`, removed by an unconditional cleanup — and no
  lifecycle call writes an input file: each one feeds its request, checkpoint,
  summary or builder input to `workflow-state` on stdin (`-`) through a quoted
  heredoc, optionally piped through `artifact-budget validate-report --input -`."

- [ ] **Step 1: Write the failing tests**

In `T/test_workflow_skill_contracts.py`, delete `REQUEST_FILE_HOME`,
`REQUEST_FILE_INVOCATION`, `RESULT_FILE_HOME`, `RESULT_FILE_INVOCATION` and the four
tests that use them, and delete `test_ship_owner_reads_the_ledger_but_never_writes_it`.
Add at module level:

```python
LIFECYCLE_DOCS = (FROM_ISSUE, AUTO, FROM_ISSUE_DIR / "ship-handoff.md", SHIP_ISSUE,
                  SHIP_ISSUE_REVIEW, SHIP_ISSUE_HUMAN_GATE, ORCHESTRATE)
STDIN_CLAUSE = ("lifecycle call is one command that reads its input from stdin "
                "through a quoted heredoc")
WRITER_RULE = ("Under implementation custody a ship owner writes only "
               "`checkpoint-delivery`, never `finish`; a remainder owner writes its "
               "own `finish --summary-file -`.")
INPUT_FLAG_RE = re.compile(r"(--request-file|--checkpoint-file|--summary-file|--input)\s+(\S+)")
V2_DIRECT_REQUEST_KEYS = {"interface_version", "issue", "now", "attempt_budget_minutes",
    "new_run", "owner_unavailable", "tracker", "worktree", "forge", "delivery_contract",
    "authorization_intents", "authority_observations", "reevaluation_evidence",
    "delivery_observations", "requested_scope", "recovery"}
V2_CONTROL_REQUEST_KEYS = {"interface_version", "now", "max_parallel",
    "attempt_budget_minutes", "human_directed", "issues", "tracker", "owners",
    "worktrees", "forge", "delivery_contracts", "authorization_intents",
    "authority_observations", "reevaluation_evidence", "delivery_observations",
    "requested_scopes", "recoveries"}
V2_OWNER_KEYS = {"interface_version", "kind", "ledger_repo_root", "run_id", "issue",
    "attempt", "owner", "action_id", "launch_kind", "worktree", "handoff_path",
    "deadline_at", "custody", "contract", "contract_digest", "pending_stage_ids",
    "requirements", "authority_evaluation", "requested_scope"}
SHIP_HANDOFF_V2_KEYS = {"interface_version", "state", "ledger_repo_root", "run_id",
    "owner", "owner_worktree", "custody", "issue_number", "branch", "worktree_path",
    "spec_artifact", "plan_artifact", "head_sha", "review_state", "auto", "report_path",
    "notes", "delivery_contract", "delivery_contract_digest", "authorization_intents",
    "authorization_chain_digest", "authority_observation_ids", "reevaluation_evidence_ids",
    "authority_evaluation_consumption_ids", "pending_stage_ids", "selected_outputs",
    "requested_scope"}
SHIP_SUMMARY_V2_KEYS = {"interface_version", "issue", "state", "custody",
    "historical_owner_result", "delivery_contract_digest", "delivery_observations",
    "authority_observations", "reevaluation_evidence", "detail_state", "report_path",
    "notes"}


def json_block(text):
    match = re.search(r"```json\n(\{.*?\})\n```", text, re.DOTALL)
    if match is None:
        raise AssertionError("missing json block")
    return json.loads(match.group(1))
```

Add to `WorkflowSkillContractsTest`:

```python
    def test_direct_and_control_requests_are_interface_two(self):
        direct = self.section(self.from_issue, "### Direct autonomous acquisition",
                              "### Interactive direct acquisition")
        request = json_block(direct)
        self.assertEqual((set(request), request["interface_version"]),
                         (V2_DIRECT_REQUEST_KEYS, 2))
        for anchor in ("`delivery_contract`", "--kind contract", "`authorization_intents`",
                       "kind: delivery_remainder", "--request-file -"):
            self.assertIn(anchor, normalized(direct))
        decide = self.section(self.orchestrate, "## 3. Decide", "## 4. Execute control actions")
        self.assertEqual(set(json_block(decide)), V2_CONTROL_REQUEST_KEYS)
        for anchor in ("workflow-state build-delivery", "until a summary shows its digest",
                       "report the refusal", "--request-file -"):
            self.assertIn(anchor, normalized(decide))

    def test_orchestrate_bootstrap_actions_and_projected_owner(self):
        observe = normalized(self.section(self.orchestrate, "## 2. Bootstrap and observe",
                                          "## 3. Decide"))
        for anchor in ("workflow_bootstrap", "`contract_digest`", "`forge_pr`",
                       "never a candidate for it"):
            self.assertIn(anchor, observe)
        execute = normalized(self.section(self.orchestrate, "## 4. Execute control actions",
                                          "## 5. Final report"))
        for anchor in ("`spawn`, `resume`, `retry`, `delivery_remainder`, `wait`, or `finalize`",
                       "rename `id` to `action_id` and `kind` to `launch_kind`",
                       "`kind: owner`", "`interface_version: 2`", "canonical JSON",
                       "--boundary workflow-response"):
            self.assertIn(anchor, execute)
        self.assertNotIn("Interface_version 2 control adapter", self.orchestrate)

    def test_ship_handoff_v2_ship_summary_v2_and_remainder_prompt(self):
        line = next(item for item in self.ship_handoff.splitlines()
                    if item.startswith('{"interface_version":2'))
        self.assertLessEqual(SHIP_HANDOFF_V2_KEYS, set(re.findall(r'"([a-z_]+)":', line)))
        for key in SHIP_SUMMARY_V2_KEYS:
            self.assertIn(f"`{key}`", self.ship_handoff)
        for anchor in ("--kind initial-intent", "--boundary ship-summary",
                       "## Remainder owner prompt"):
            self.assertIn(anchor, self.ship_handoff)
        self.assertNotIn("## Delivery handoff v2", self.ship_handoff)

    def test_ship_issue_writer_rule_delivery_loop_and_remainder_mode(self):
        self.assertIn(WRITER_RULE, normalized(self.ship_issue))
        self.assertNotIn("never writes workflow-state itself", normalized(self.ship_issue))
        loop = normalized(self.section(self.ship_issue, "## Delivery loop", "## Remainder mode"))
        self.assert_ordered(loop, "pre-merge selection gate", "--kind selected-output",
            "`selected_output`, `branch_published` and `pr_opened`", "checkpoint-delivery",
            "equal the scope", "current-launch", "current-launch", "authority-observation",
            "observation-only", "`human_gate`", "`delivery_complete`")
        remainder = normalized(self.ship_issue.split("## Remainder mode", 1)[1])
        for anchor in ("`delivery_remainder`", "ready stage", "finish --summary-file -"):
            self.assertIn(anchor, remainder)
        for appendix in (self.ship_review, self.ship_human_gate):
            self.assertIn("## Delivery loop", appendix)

    def test_auto_continuation_and_bookkeeper_are_interface_two(self):
        transfer = self.section(self.auto, "#### Mandatory transfer gate",
                                "#### Fresh delegated owner")
        owner = json_block(transfer)["owner"]
        self.assertEqual((set(owner), owner["interface_version"]), (V2_OWNER_KEYS, 2))
        self.assert_ordered(normalized(self.auto), "workflow-state check-launch",
                            "workflow-state finish --summary-file -")

    def test_lifecycle_calls_are_single_stdin_commands_on_interface_two(self):
        for path in LIFECYCLE_DOCS:
            text = normalized(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                for forbidden in ('"interface_version": 1', "version-1",
                                  "temporary request file", "temporary `ship-summary/v2` file"):
                    self.assertNotIn(forbidden, text)
                for flag, value in INPUT_FLAG_RE.findall(text):
                    self.assertEqual(value.strip("`").rstrip(".,;"), "-", flag)
                self.assertLessEqual(text.count("--result-file"), 1)
        for path in (FROM_ISSUE, ORCHESTRATE, SHIP_ISSUE):
            with self.subTest(clause=path.name):
                self.assertIn(STDIN_CLAUSE, normalized(path.read_text(encoding="utf-8")))
        expected = " ".join(case["expected_output"] for case in self.orchestrate_evals["evals"])
        for anchor in ("interface_version 2", "delivery_remainder", "contract_digest",
                       "build-delivery"):
            self.assertIn(anchor, expected)
        self.assertNotIn("version-1", expected)
```

Re-pin, in the same step, only anchors that name retired interface-1 text:
`test_dispatcher_is_a_control_adapter_not_a_policy_owner` and
`test_direct_auto_acquires_only_through_direct_owner` (`--request-file
<absolute-json-path>` → `--request-file -`);
`test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner` (owner keys →
`V2_OWNER_KEYS`). Keep every other anchor; if a kept anchor's sentence moves, keep
its words.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -5`
Expected: FAIL in the six new tests — the direct `json` block is interface 1, the
orchestrate request has no `json` block, `version-1` and the temporary-file
prescriptions remain.

- [ ] **Step 3: Rewrite the documents** as "Content each document must carry"
lists, keeping every section heading the existing tests slice on and the two
dispatch clauses inside the orchestrate owner blockquote and the ship-handoff
fence.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -3` → `OK (skipped=1)`.
Run: `just agent-model-matrix` → exit 0 and `agent model matrix: valid`.
Run: `for skill in home/common/agent-skills/skills/from-issue home/common/agent-skills/skills/ship-issue home/common/claude-code/skills/orchestrate-issues; do nix shell --impure --expr 'let p = (builtins.getFlake "nixpkgs").legacyPackages.${builtins.currentSystem}; in p.python3.withPackages (ps: [ ps.pyyaml ])' -c python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py "$skill" || exit 1; done` → `Skill is valid!` three times.
Run: `just agent-workflow-tests 2>&1 | tail -3` → `OK (skipped=1)`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/orchestrate-issues home/common/agent-skills/skills/from-issue \
  home/common/agent-skills/skills/ship-issue CLAUDE.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(skills): drive the lifecycle skills through interface 2 and one delivery loop"
```
