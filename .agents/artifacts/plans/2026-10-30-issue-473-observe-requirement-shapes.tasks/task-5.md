# Task 5: Skill text and README

Spec § Decisions (Which replies are workflow responses; Skill and doc text); § Test seams (Prose pins); per D5, D7 and D11. `acquire-direct.md` stops spelling out the five requirement shapes and points at `expects`. from-issue's lifecycle-call rule names both exemptions. The README records the contract. Both skill edits shrink their files, because the instruction budget's headroom is 18–45 bytes and a raise needs a human label (D7).

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/acquire-direct.md` (line 37, the `kind: observe` item)
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (line 41, its second sentence)
- Modify: `home/common/agent-skills/README.md` (new `### Direct-owner observations` under `## Lifecycle helpers`, placed after `### workflow-state build-delivery`)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`WorkflowSkillContractsTest.test_direct_auto_observe_owner_terminal_loop_is_closed`; a new test in `ResumePackContractsTest`)

**Interfaces:**
- Consumes: `module_constants(path, *names)`, defined in this test module, which reads tuple, set and string literals by AST. Task 1's `EXPECTS_MEMBERS` tuple literal in `python/agent_tools/attempt_observations.py`. The behavior Tasks 2–4 implemented, which the README describes.
- Produces: skill text and README prose only.

**Invariants:**
- `test_workflow_skill_contracts.py` still imports nothing from `agent_tools` and no sibling test module (D11).
- `acquire-direct.md` keeps the closed observe envelope (`interface_version`, `kind`, `issue`, nullable `run_id`, `requirements`). It also keeps line 38's observation rules (observe only what each asks, and how), the builder example block, the contract-to-slot mapping and the fail-loud rules.
- Each edited skill file is no larger than at the base `8212d8fb`, and `just agent-instruction-budget` passes with no ceiling changed.
- The kept pin `test_both_skills_exempt_the_pack_from_workflow_response_validation` stays green.

- [ ] **Step 1: Write the failing pins**

In `WorkflowSkillContractsTest.test_direct_auto_observe_owner_terminal_loop_is_closed`, delete the five literal requirement shapes from the `for shape in (...)` tuple. Keep the two envelope strings. Then add at the end of the method:

```python
        observe = text[text.index("**`kind: observe`**"):text.index("**`kind: owner`**")]
        expects = module_constants(REPO_ROOT / "python/agent_tools/attempt_observations.py",
                                   "EXPECTS_MEMBERS")["EXPECTS_MEMBERS"]
        for name in ("expects", *expects):
            self.assertIn(f"`{name}`", observe)
```

In `ResumePackContractsTest`, add:

```python
    def test_the_lifecycle_call_rule_exempts_build_delivery_and_the_pack(self):
        """Issue 473 D5: the only skill-named workflow-state stdout never piped through the
        workflow-response boundary."""
        text = FROM_ISSUE.read_text(encoding="utf-8")  # raw: the rule is one line
        section = text[text.index("## Lifecycle identity"):text.index("### Resume pack")]
        [rule] = [line for line in section.splitlines()
                  if "--boundary workflow-response" in line]
        for name in ("`build-delivery`", "`resume-pack`"):
            self.assertIn(name, rule)
```

- [ ] **Step 2: Run the pins and watch them fail**

Run (Unit run): `test_workflow_skill_contracts.py -k test_direct_auto_observe_owner_terminal_loop_is_closed -k test_the_lifecycle_call_rule_exempts_build_delivery_and_the_pack`
Expected: FAIL. `` `expects` `` is not in the observe item, and `` `build-delivery` `` is not in the rule line.

- [ ] **Step 3: Rewrite the two skill sentences**

`acquire-direct.md` line 37: replace this fragment

```text
, then accept only the five exact requirement shapes, in the returned order: `{"kind":"tracker"}`; `{"kind":"recorded_worktree", "path":"<absolute-path>"}`; `{"kind":"candidate_worktree"}`; `{"kind":"forge_pr", "path":"<issue-branch-prefix>"}`; or `{"kind":"delivery_contract", "subject_id":"<issue>", "reason_code":"delivery_contract_required", "detail_pointer":null}`.
```

with

```text
, then take the requirements in the returned order. Each carries `expects`: the request member its answer fills (`slot`), that answer's `members` with their meanings, an `example` answer, and, when non-null, the `build` command that produces it.
```

`SKILL.md` line 41: replace

```text
Pipe each `workflow-state` reply's raw bytes through `artifact-budget validate-report --boundary workflow-response --input -` before decoding it; `resume-pack` stdout is no workflow response, is never piped through `validate-report`, and stays untrusted until the resume pack's checks pass.
```

with

```text
Pipe each `workflow-state` reply's raw bytes through `artifact-budget validate-report --boundary workflow-response --input -` before decoding it, but never `build-delivery` or `resume-pack` stdout: neither is a workflow response, and a resume pack stays untrusted until its checks pass.
```

These measure −125 and −4 bytes.

- [ ] **Step 4: Record the contract in the README**

Add under `## Lifecycle helpers`, after the `### workflow-state build-delivery` subsection:

```markdown
### Direct-owner observations

Each requirement of a `workflow-state direct-owner` `observe` reply carries `expects`, a closed object that says how to answer it. `slot` is the request member the answer is sent in. `members` maps each member of that answer to a one-line meaning that lists any closed value set. `example` is one illustrative issue-73 answer with exactly those members. `build` is `null` for an observed answer. For `delivery_contract` it is the `workflow-state build-delivery` command line, with `<ledger_repo_root>` as its only placeholder, that turns an `example`-shaped input into the slot's value. Each kind's `expects` is a constant, so a tracker or worktree example pasted for another issue fails the request's issue check. The catalogue lives in `agent_tools.attempt_observations`, beside the tracker, forge and worktree observation sets that the request validators import. A requirement kind with no entry refuses the call with exit 2 and empty stdout. `direct-owner --help` names `expects` and its members.

At the `workflow-response` boundary, an observe reply's requirements are the five direct kinds, none twice, each with exactly that `expects` shape and its kind's `slot`. Control summaries and delivery blocks keep their bare requirement shape. The `register-worker`, `release-worker` and `mark-progress` replies are accepted by exact member set. Every `workflow-state` subcommand a skill names is a workflow response, except `build-delivery` (sealed delivery values, which the next request's own validation checks) and `resume-pack`. `tests/test_artifact_budget.py` derives that set from the skill text and drives one real reply of each through the boundary.
```

- [ ] **Step 5: Verify**

1. Unit run: `test_workflow_skill_contracts.py` [about 5 s]. Expected: `OK`.
2. Without the package path, as the installed tier runs it: `bash -c 'set -o pipefail; env -u PYTHONPATH python3 -m unittest -q home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3'`. Expected: `OK (skipped=1)`, with no `ModuleNotFoundError`.
3. Unit run: `home/common/agent-skills/tests/test_skill_lint.py` and `home/common/agent-skills/tests/test_instruction_load.py`. Expected: `OK`.
4. No skill file grew (exits 1 if one did): `bash -c 'for f in home/common/agent-skills/skills/from-issue/acquire-direct.md home/common/agent-skills/skills/from-issue/SKILL.md; do test "$(wc -c < "$f")" -le "$(git show 8212d8fb:"$f" | wc -c)" || exit 1; done'`.
5. Budget. Expected: `check: pass`.
6. Scope: `git diff --stat 8212d8fb -- home/common/agent-skills/skills home/common/claude-code/skills home/common/codex/skills` lists exactly the two from-issue files.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/acquire-direct.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/README.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit ... -- -m "docs(from-issue): observe requirements describe themselves; build-delivery is no workflow response (issue 473)"
```

After this commit, sdd's final gate runs `just build` and `just agent-workflow-tests` on the final head (AC4).
