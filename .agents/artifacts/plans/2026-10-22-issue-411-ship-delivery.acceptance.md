# Acceptance record — issue #411

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] Selection, effect observations, authority observations, checkpoint and terminal summary assembly use the existing canonical builders and validators through a complete documented helper interface — measured: new helper integration tests. | code | `python3 -m unittest home/common/agent-skills/tests/test_ship_delivery.py` within the focused run below | All 10 compiler scenarios passed. Real checkpoint/finish boundaries accepted close, hold, sync and a remainder takeover after merge. Prior references remain contract-bound; the final payload contains only current-custody authority. | `666574f6d69d373cde281d6043c943b55fac429d` | Focused run: 212 tests passed, 4 installed-view skips, 29.823 s; Nix Git 2.55, Nix Bash 5.3, Python 3.13, source policy surface. | met |
| AC2 | [code] Stale custody, malformed facts, failed builders and validator refusals fail closed without an external effect — measured: negative integration tests. | code | Same real-boundary compiler run; installed `AgentToolsLauncherTest.test_ship_delivery_uses_the_real_validator_with_hostile_python_channels` | Stale context, malformed facts, failed canonical builders, validator refusal, cross-contract prior evidence, ambiguous refs and reserved `kind`/`self` refused with exit 2 and no ledger change. Canonical-valid legacy handoff/prior reports refused without tracebacks. Installed validator refusal passed under hostile Python import channels. | `666574f6d69d373cde281d6043c943b55fac429d` | Focused run above plus 3 installed-launcher tests passed in 6.848 s against the built home-manager-files output. The compiler executes no external delivery effect. | met |
| AC3 | [code] Shipping instructions invoke the helper rather than requiring handwritten sealed delivery JSON, with no instruction-budget increase — measured: workflow contract tests and Instruction Budget CI. | code | Focused shipping/shell/dispatch contract tests; `just agent-instruction-budget` | Contract tests passed in the 212-test run; local Instruction Budget gate exited 0 with `check: pass`. Shipping, sync and remainder instructions use `ship-delivery`; its API is installed for other repositories. | `666574f6d69d373cde281d6043c943b55fac429d` | Local gate against origin/main; Instruction Budget CI remains a PR merge gate. No raise label was used. | met |
| AC4 | [code] The helper is packaged as an isolated agent_tools launcher and included in repository verification — measured: installed-launcher checks, workflow suite and host build. | code | `just build eleven-m5`; 3 installed-launcher checks; `just agent-workflow-tests` in final verification | Host build exited 0. All 3 installed checks passed, covering the command table, every launcher's hostile-import help path and the new helper's real-validator refusal/API reference. Full workflow suite is in final verification, explicitly pending. | `666574f6d69d373cde281d6043c943b55fac429d` | Build/installed evidence is complete. Final declared verification will run after integration sync and this record; no passing full-suite result is claimed here. | met |

Controller approved these four code verdicts after conformance review and the
clean scoped correctness re-review. COR-001 and COR-002 are addressed; the bounded
legacy-worktree fixture repair preserves exact propagation of the real Git error.

Focused command (Nix Git/Bash first on PATH, `WORKFLOW_POLICY_SURFACE=source`,
`PYTHONPATH=python`, timeout 180 s):

```text
python3 -m unittest home/common/agent-skills/tests/test_ship_delivery.py home.common.agent-skills.tests.test_delivery_workflow.LegacyWorktreeTest.test_a_slugless_worktree_without_a_patterned_live_branch_refuses home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py
```

Run logs: `/private/tmp/issue-411-review-fix-focused.log`,
`/private/tmp/issue-411-review-fix-build.log`,
`/private/tmp/issue-411-review-fix-launchers.log`, and
`/private/tmp/issue-411-instruction-budget-final.log`.

Final verification: **pending**. The controller will synchronize the integration
branch, then run the declared build and full workflow suite on the resulting
branch tree before delivery. Earlier interrupted or superseded full-suite runs
are not acceptance evidence.
