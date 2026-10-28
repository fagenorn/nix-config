# One agent_tools Build per Generation Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Every agent_tools consumer of one home-manager generation execs one agent_tools build, an installed-tier check over the built system closure pins it, and a source-level test pins that `guard-policy derive` derives a JarBird-shaped project.

**Architecture:** One new common home module applies `lib/agent-tools.nix` once and publishes the result as the `agentTools` module argument. The agent-skills and claude-code modules take it as an argument instead of applying the builder themselves, which leaves every store path unchanged (D2). `tests/test_agent_tools_launchers.py` reads the built system's closure through a variable both installed recipes pass (D3, D4, D8). `tests/test_guard_policy.py` gains two JarBird-shape derive cases (D5, D9).

**Tech stack:** Nix (home-manager module arguments, `just build`), Just, Python 3 standard library (`unittest`, `tomllib`, `subprocess`, `re`), the `agent_tools` package.

Spec: `.agents/artifacts/specs/2026-10-27-issue-467-single-agent-tools-build-design.md` (spec commit `3045ba50`). A bare "Dn" cites the spec's `## Decision ledger`. This plan appends D8–D10. Issue: https://github.com/fagenorn/nix-config/issues/467.

## Global Constraints

- Base `00ec4e65` (`origin/main`, the merge of issue 465's PR). Tasks land in index order, each on top of the one before.
- These stay unchanged (spec § Out of scope; D6, D7): `home/common/claude-code/lifecycle_guard.py`; the text of `lifecycleGuardBasePolicy`, `lifecycleGuard`, `lifecycleGuardRowCheck`, `claudeGuardPolicy` and the registered hook command in `home/common/claude-code/default.nix`; `lib/agent-tools.nix`; every command's interface; `home/common/agent-skills/scripts/artifact-budget`; `.github/`; `.agents/project.json`.
- The builder's value keeps its shape `{ launchers; scriptLauncher; }`, its interpreter environment stays private, and no configuration option is added (D2).
- The installed tier joins neither CI nor `bindings.workflow.verification` (D4).
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit. Where the implemented code differs from a clause this plan dictates, rewrite the clause from the code. Write "issue 467", never a bare `#467`. No `TODO` or `FIXME`.
- Stage each new file with `git add` before any `just build`, because the flake sees tracked files only.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. `$SCRATCH` below is the directory `launch-scope scratch` prints for your launch.
- Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. Commits are SSH-signed (never disable signing) and end with the session's trailer lines. Never run `just switch`, and never push.
- **Build** (timeout 1800 s; about 15 s when cached): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`.
- **Unit run** (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest -v <test file> [-k <pattern>]... 2>&1 | tail -12'`.
- **Installed tier** (timeout 3600 s; 238 tests in about 12 s at base): `bash -c 'set -o pipefail; just agent-installed-skill-tests 2>&1 | tail -4'`.
- Darwin: run the Build on `mbp` or `eleven-m5` where one is at hand. A darwin configuration cannot be evaluated on Linux (its catppuccin import needs a darwin build), so otherwise the task report says the darwin Build was not run.
- Final gate (sdd, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each), plus the Installed tier for AC2, which sits outside the declared verification line (D4).

## Test seams

Per the spec's § Test seams:

- **Installed layout.** `just agent-installed-skill-tests` and `just agent-retained-tests <root>` run `tests/test_agent_tools_launchers.py`, which holds the closure check (D3, D8).
- **Source.** `just agent-workflow-tests` runs `tests/test_guard_policy.py` over `tests/guard_policy_world.py`; the JarBird-shape derive cases live in its `DeriveTest` (D5, D9).
- **Build.** `just build` on anis-desktop, and on a darwin host where one is at hand. The single application evaluates and builds, with the package and launcher store paths of the base (D2).

## Delivery estimate and boundaries

All figures are estimates: 8 changed files (one new) plus this package and the spec ledger, about +190/−15 lines.

- `home/common/agent-tools/default.nix`: about +7 (new).
- The agent-skills and claude-code modules: +1/−1 each.
- `tests/test_agent_tools_launchers.py`: about +75/−12.
- `justfile`: +4/−2.
- `tests/test_guard_policy.py`: about +45.
- `python/README.md`: one paragraph. `home/common/claude-code/README.md`: one sentence and one paragraph.

The change fits one review package. Task 1 can ship alone, since it changes no store path. Task 3 can ship alone, since it only adds tests. Task 2 ships with Task 1, because its documentation describes the single application.

## Task index

Task 1 — One application of the agent-tools builder — `home/common/agent-tools/default.nix`, `home/common/agent-skills/default.nix`, `home/common/claude-code/default.nix`, `home/common/claude-code/README.md` — full — [task-1.md](2026-10-27-issue-467-single-agent-tools-build.tasks/task-1.md)
Task 2 — The closure pin in the installed tier — `tests/test_agent_tools_launchers.py`, `justfile`, `python/README.md`, `home/common/claude-code/README.md` — full — [task-2.md](2026-10-27-issue-467-single-agent-tools-build.tasks/task-2.md)
Task 3 — JarBird-shape derive cases — `tests/test_guard_policy.py` — full — [task-3.md](2026-10-27-issue-467-single-agent-tools-build.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | human (classified) | Task 3 | The reporter judges it on their host: after switching to a generation that contains this change, `claude-guard-row-check --repository elevenyellow/jarbird` prints `outcome` `derived` (D5, D10). The hermetic equivalent proved here is `tests/test_guard_policy.py::DeriveTest::test_a_jarbird_shaped_project_derives_while_its_adapter_waits_on_dev` and `::test_a_jarbird_shaped_project_derives_once_its_adapter_reaches_main`, run by `just agent-workflow-tests` |
| AC2 | code (classified) | Task 2 | `tests/test_agent_tools_launchers.py::AgentToolsLauncherTest::test_the_system_closure_holds_one_agent_tools_build`, `::test_every_launcher_in_the_system_closure_execs_one_environment` and `::test_each_system_closure_environment_imports_agent_tools_from_the_closure_build`, run by `just agent-installed-skill-tests` on anis-desktop at HEAD, which is outside the declared verification line (D4) |
| AC3 | human (classified) | Task 3 | The reporter judges it on their host: from a Claude Code session started after that switch, `gh pr create --repo elevenyellow/jarbird --base main --head dev …` passes the lifecycle guard (D5, D10). The hermetic equivalent is AC1's two derive cases plus the unchanged guard's `tests/test_claude_permission_guard.py::ClaudePermissionGuardTest::test_pr_create_grammar_and_base_check` and `::test_an_arcwave_shaped_project_is_judged_by_its_compiled_row` |

## Decisions

- Task 1 follows D1 and D2. Task 2 follows D3, D4, D6 and D8, with D10's README scope. Task 3 follows D5 and D9. D7 keeps `artifact-budget` out of every task.
- Planning appended D8–D10 to the spec's ledger. All tasks use the full lane because they touch lifecycle tooling and its acceptance checks.
- Planning trials on 2026-10-27, from scratch copies that were never committed, measured what the members claim:
  - the base build holds 27 `-agent-tools-` store paths;
  - Task 2's three tests are green on the base closure. They fail rather than skip without the variable. On a closure that also holds a Python 3.12 build, the first two fail and name both builds and both environments;
  - Task 3's two fixtures derive `main`/`dev` from source. Under `5ae1b9dc`'s source they refuse `branch_unresolved` and `contract_unresolved`;
  - the Installed tier passes at base.

---
