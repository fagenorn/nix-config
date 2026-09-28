# Resolver Family Move Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Move the resolver family (`resolve-project`, `conformance`,
`adopt-project`, their libraries, and `host_admission`) into `agent_tools`,
deploy the three commands as package launchers, and delete every bootstrap,
origin check, member tuple and file-path loader in the family
([#177](https://github.com/fagenorn/nix-config/issues/177)).

**Architecture:** A new `agent_tools.siblings.sibling_argv` helper lands first
with its own test (Task 1). One atomic task then `git mv`s the eleven files,
swaps the machinery for package imports, wires three command-table rows,
gives `workflow-state` its two transitional lookups, and re-points or deletes
every affected test. No smaller subset keeps the suites green (Task 2). The
installed-layout floor and a hostile top-level `agent_platform` follow
(Task 3). The living documents are re-pointed and the slice is verified end to
end (Task 4).

**Tech stack:** Python 3 stdlib (`unittest`, subprocess round trips),
nixpkgs `buildPythonPackage` via `lib/agent-tools.nix`, Home Manager, `just`,
Markdown.

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-28-issue-177-resolver-family-move-design.md`,
D1–D15. It is a slice of
`.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md`
(parent D1–D16), built on the #175 and #179 specs beside it. All of them bind.

## Global Constraints

- Command names, `~/.agents/bin` paths, argv, stdin, stdout and exit contracts,
  and the resolver's error shapes stay unchanged (parent D15). The only
  exceptions are D3's unreachable codes and D4's unset-`HOME` answer.
  Pre-existing assertions stay unedited apart from D7/D8's deletions,
  re-homings and location literals, and D14's corrections.
- Every move uses `git mv`. Its content edits are exactly the spec's D2–D4
  list for that file, plus D14: no reformatting, no reflow, no renamed helper,
  and no split function (parent D14). Unused imports go. The `__main__` block
  stays. The shebang goes, and each moved file ends with mode 100644.
- Living documents naming a moved file are re-pointed in the move's own commit
  (the-bar, Moves keep their history). Point-in-time records under
  `.agents/artifacts` keep their paths.
- Recipes assign `PYTHONPATH="{{agent_tools_path}}"` per line. There is no
  justfile-wide `export` (#175 D6). `agent_tools_path` is absolute.
- Scope is exactly the spec's `## Out of scope`. `workflow-state` changes only
  in its two D6 lookups. `promotion` keeps its `PATH` call, and the registry
  keeps its promotion literals.
- The shared wiring files are `justfile`, `lib/agent-tools.nix`,
  `home/common/agent-skills/default.nix`, `CLAUDE.md` and
  `tests/test_agent_tools_launchers.py`. Edits stay local. Never reflow a
  neighbouring line, and never run `nixfmt` (#175 D13).
- Flakes see tracked files only, and `git mv` stages. `git add` any other new
  file before `just build`. Never run `just switch`.
- `~/.agents/bin` is an older activation. Gates run this worktree's source with
  `PYTHONPATH="$PWD/python"`, or its build (`./result`).
- Run the full suite as `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests`,
  which is CI's mode. On this machine the activated `~/.agents/skills` predates
  the source. In this mode the base reports `Ran NBASE tests` and
  `OK (skipped=4)`, where `NBASE` is the count Task 1 Step 0 records (a planning run at
  `dc183ff` measured 1612). Expect
  `NBASE+3` after Task 1 and `NBASE-17` after Task 2 (21 tests deleted, 1
  added), unchanged after that. A run takes about 10–20 minutes. Write the log
  to a file and summarize any failure to its failing test ids.
- Commits are conventional and SSH-signed. Never disable signing. Each message
  ends with the harness's two trailer lines (`Co-Authored-By:` and
  `Claude-Session:`).

Path abbreviations used in members: `PK` = `python/agent_tools`,
`AS` = `home/common/agent-skills`, `T` = `home/common/agent-skills/tests`.

## Test seams

- **Seam 1, from source.** The family's suites run under the recipe's
  `PYTHONPATH`. They run commands as
  `[sys.executable, "-m", "agent_tools.<module>", …]`, import modules
  normally, and use relative sibling-suite imports. `HERMETIC_ENV` forwards an
  absolute `PYTHONPATH` (parent D8). There are three module-interface tests:
  `tests/test_agent_tools_siblings.py` (D9, D15), the re-homed
  ambiguous-forward-step case (D7), and the in-process wrapper cases.
- **Seam 2, installed layout.** `tests/test_agent_tools_launchers.py` runs only
  from `just agent-installed-skill-tests`. The `workflow-state` exemption lands
  in Task 2 (D13). The floor and the hostile `agent_platform` land in Task 3
  (D9).
- Seam 3, the guard's registered hook, is untouched.
- **Shown once, not committed.** Each task's `just build` covers the build-time
  import check of the moved modules. The `--help` byte identity and the demos
  run in Tasks 2 and 4.

## Delivery estimate and boundaries

These figures are estimates. About 30 product files change: 11 renames, 1 new
module, about 13 test files, 2 new or extended launcher tests,
`workflow-state.py`, `default.nix`, `lib/agent-tools.nix`, `justfile` and
`CLAUDE.md`. The PR therefore gets the full two-axis review. The renames carry
about 8,300 lines. Roughly 400 lines are deleted from them and about 60
edited. Test deletions come to about 450 lines, and new test code is about
60 lines. With rename detection the diff should be about 60–90 KB. That is the
main review-package risk: if it exceeds one package, split the review by
Task 2's production files versus its test files, never the commit. Rename
pairing is the other risk. `adopt_project` loses about 27% of its lines and
should pair at about 70%. The others should pair at 88% or more. Tasks run in
index order, and each depends on every earlier one (D12).

## Task index

Task 1 — Add the sibling-run helper — `PK/siblings.py` (create), `tests/test_agent_tools_siblings.py` (create), `justfile` — low-risk — [task-1.md](2026-09-28-issue-177-resolver-family-move.tasks/task-1.md)

Task 2 — Move the resolver family into the package — 11 × `git mv` `AS/scripts/{resolve-project,agent_platform,conformance,conformance-registry,conformance-checks,adopt-project,adopt_inspection,adopt_planning,adopt_apply,adopt_verify,host_admission}.py` → `PK/…`, `AS/scripts/workflow-state.py`, `lib/agent-tools.nix`, `AS/default.nix`, `T/{test_resolve_project,test_resolve_platform,test_resolve_platform_status,conformance_test_support,test_conformance,test_conformance_checks,test_conformance_registry,test_adopt_project,test_adopt_project_boundaries,test_adopt_apply,test_adopt_verify,test_delivery_workflow,test_workflow_skill_contracts,test_shell_example_contracts}.py`, `tests/test_agent_tools_launchers.py` — full — [task-2.md](2026-09-28-issue-177-resolver-family-move.tasks/task-2.md)

Task 3 — Pin the installed floor and the hostile platform import — `tests/test_agent_tools_launchers.py` — low-risk — [task-3.md](2026-09-28-issue-177-resolver-family-move.tasks/task-3.md)

Task 4 — Re-point the living documents and verify the slice — `CLAUDE.md` — low-risk — [task-4.md](2026-09-28-issue-177-resolver-family-move.tasks/task-4.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| AC1: the three commands are package launchers exercised by the installed-layout test | 2 (rows, launchers, hostile run), 3 (floor), 4 (final run) |
| AC2: no platform library under `~/.agents/lib/python` | 2 (wiring, built-tree check), 4 (final check) |
| AC3: no `sys.path` edit, origin check or file-path loader in the family's modules or tests | 2 (edits, greps), 4 (final greps) |
| AC4: no conformance library entries in `.agents/bin` | 2, 4 |
| Regression floor: contracts, `--help` bytes, suites green, living docs | 1–4 (suites), 2 (help identity, default.nix comments), 4 (`CLAUDE.md`, full run) |
| Demo | 4 |

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D12 from
design and the parent's rows as "parent D*n*". Planning added three rows:

- **D13** exempts `workflow-state` in the installed enumeration while it
  carries D6's lookups. It lands in Task 2.
- **D14** corrects the prose the move makes false. It lands in Task 2.
- **D15** points Task 1's real helper run at `diff_scope`.

## Standards review provenance

Reviewer: Claude fallback (isolated, read-only), base 488e95f. Codex ran, but its
event stream carried no runtime model-selection event, so the route could not be
established and the one native fallback reviewed the same packet. Accepted 3
(two Should-fix: orphaned test imports and the checker expectation; the
`agent_platform` banner still naming `resolve-project.py`; one Discussion: the
`install_home` span is six lines), rejected 0, deferred 0. The fake
`agent_platform.py` control stays as spec D9 decides.
