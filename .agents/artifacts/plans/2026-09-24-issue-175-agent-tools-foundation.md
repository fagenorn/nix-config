# Agent Tools Foundation Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Ship the `agent_tools` package with one shared canonical-JSON module,
move `agent-costs`, `agent-gate-bundle` and `agent-evidence` into it, and deploy
`agent-evidence` as an isolated launcher that ignores a hostile `agent_tools` on
every channel a caller controls
([#175](https://github.com/fagenorn/nix-config/issues/175)).

**Architecture:** A top-level `python/` holds `pyproject.toml` and the package
(Task 1). Each tool moves in with `git mv` and a handful of edits, importing
`agent_tools.canonical` (Tasks 2–4). `lib/agent-tools.nix` builds the package,
import-checks every module, and generates one `-I -m` launcher per command-table
row, and the agent-skills module installs it (Task 4). An installed-layout test
proves the isolation (Task 5). A project standards shard sends new helper code to
the package (Task 6).

**Tech stack:** Python 3 stdlib (`unittest`, subprocess round trips),
setuptools via nixpkgs `buildPythonPackage`, Nix/Home Manager, `just`, Markdown.

Spec (source of truth, read it whole):
`.claude/specs/2026-09-24-issue-175-agent-tools-foundation-design.md`, D1–D13.
It is a slice of `.claude/specs/2026-09-24-agent-tools-package-design.md`
(parent D1–D16), which binds as well.

## Global Constraints

- Standard library only. `pyproject.toml` declares `dependencies = []` and no
  `[project.scripts]` (parent D3, D13).
- Command names, `~/.agents/bin` paths and each moved tool's argv, stdin, stdout
  and exit contract stay unchanged (parent D15). The moved tools' existing
  assertions pass as they are. Test edits only change how code is located and
  rename the digest at its call sites (D7).
- Every move uses `git mv`, and its content edits are exactly D2's list, so git's
  rename detection pairs old and new (parent D14). Living documents naming a
  moved file are re-pointed in the move's own commit (the-bar, Moves keep their
  history). Point-in-time records under `.claude/specs` and `.claude/plans` keep
  their paths.
- Neither the package nor the moved tools' suites (`test_agent_costs`,
  `test_agent_gate_bundle`, `test_agent_evidence`) edit `sys.path` or load a
  module by file path. Other suites' loaders belong to their clusters, and the
  drift test support keeps its `agent-model-drift` loader for #179 (D7).
- Recipes assign `PYTHONPATH="{{agent_tools_path}}"` only on
  `agent-workflow-tests`, `agent-costs` and `agent-gate-bundle` (D6). There is no
  justfile-wide `export`, and `agent-model-matrix` and `agent-model-drift` are
  left untouched.
- Scope is exactly the spec's `## Out of scope`. There are no other cluster
  moves, no deletion of `~/.agents/lib/python` or of other loaders, no delivery
  rename, no function splits and no test relocation.
- #100 edits `justfile`, `home/common/agent-skills/default.nix` and the resolver
  suite concurrently. Keep edits to those files local, and never reflow
  neighbouring lines.
- Flakes see tracked files only, so `git add` a new file before `just build`.
  A `.nix` change runs `just build` in its task. Never run `just switch`.
- The helpers under `~/.agents/bin` are main's build. Gates run this worktree's
  source (with `PYTHONPATH=python`) or its build (`./result`).
- Every task ends with `just agent-workflow-tests` green. A planning run at
  8c3f6da, with Task 6's contract and fixture edits applied, gave 1042 tests
  with 1 skipped, and took 7–20 minutes depending on machine load. The planned
  counts are 1046 after Task 1, 1047 after Task 2, 1048 after Task 3, and 1050
  after Tasks 4–6. Summarize any failure to its failing test ids.
- Commits are conventional and SSH-signed. Never disable signing. Each commit
  ends with the harness's attribution trailer lines.

Path abbreviations used in members: `PK` = `python/agent_tools`,
`AS` = `home/common/agent-skills`, `CC` = `home/common/claude-code/skills/codex-collaboration`.

## Test seams

- **Seam 1, from source.** The existing suites run under the recipe's
  `PYTHONPATH`, and commands run as `[sys.executable, "-m", "agent_tools.<module>", …]`.
  This slice adds the golden canonical test, a `-m --help` run in the cost and
  gate suites, and evidence's two hook-composition pins (D7).
- **Seam 2, installed layout.** `tests/test_agent_tools_launchers.py` runs only
  from `just agent-installed-skill-tests`, under `AGENT_SKILLS_INSTALLED_HOME`
  (D8).
- Seam 3, the guard's registered hook, is untouched.
- **Shown once, not committed.** Three facts are demonstrated during
  verification: the build-time imports check (Task 4), the standards
  registration (Task 6) and the cost tool's process pool under `-m` (Task 2).

## Delivery estimate and boundaries

These figures are estimates. About 20 files change. The three renames carry about
3,650 lines with fewer than 30 edited. New code is about 40 lines of `canonical`,
50 of Nix, 60 and 150 lines of new tests, and 70 lines of docs. With rename
detection, the diff is about 35–55 KB, which fits one review package. The main
growth risk is a move whose edits outgrow D2's list and break rename pairing.
Tasks run in index order, and each depends on every earlier one.

## Task index

Task 1 — The package and its canonical module — `python/pyproject.toml` (create), `PK/__init__.py` (create), `PK/canonical.py` (create), `tests/test_agent_tools_canonical.py` (create), `justfile` — full — [task-1.md](2026-09-24-issue-175-agent-tools-foundation.tasks/task-1.md)

Task 2 — Move agent-costs into the package — `scripts/agent-costs.py` → `PK/agent_costs.py`, `tests/test_agent_costs.py`, `tests/agent_model_drift_test_support.py`, `justfile` — full — [task-2.md](2026-09-24-issue-175-agent-tools-foundation.tasks/task-2.md)

Task 3 — Move agent-gate-bundle into the package — `scripts/agent-gate-bundle.py` → `PK/agent_gate_bundle.py`, `tests/test_agent_gate_bundle.py`, `justfile` — full — [task-3.md](2026-09-24-issue-175-agent-tools-foundation.tasks/task-3.md)

Task 4 — agent-evidence ships as an isolated launcher — `AS/scripts/agent-evidence.py` → `PK/agent_evidence.py`, `lib/agent-tools.nix` (create), `AS/default.nix`, `AS/tests/test_agent_evidence.py`, `AS/tests/test_workflow_skill_contracts.py`, `CC/DIFF-REVIEW.md`, `CC/evals/evals.json` — full — [task-4.md](2026-09-24-issue-175-agent-tools-foundation.tasks/task-4.md)

Task 5 — Installed-layout launcher test — `tests/test_agent_tools_launchers.py` (create), `justfile` — full — [task-5.md](2026-09-24-issue-175-agent-tools-foundation.tasks/task-5.md)

Task 6 — Project standards shard and the architecture note — `docs/standards/README.md` (create), `docs/standards/agent-helpers.md` (create), `.agents/project.json`, `AS/tests/test_resolve_project.py`, `CLAUDE.md` — full — [task-6.md](2026-09-24-issue-175-agent-tools-foundation.tasks/task-6.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| AC1: `agent-evidence` is an isolated launcher; a fake `agent_tools` on `PYTHONPATH` is not imported | 4 (launcher), 5 (installed test) |
| AC2: no moved tool defines its own digest or duplicate-key hook | 1 (home), 2, 3, 4 |
| AC3: a package module that fails to import fails `just build` | 4 (imports check, shown once) |
| AC4: moved tools' tests use `python -m`; no file-path loads or `sys.path` edits | 2, 3, 4 |
| AC5: `resolve-project resolve` lists the project's standards shard | 6 |
| Regression floor: names, paths and contracts unchanged; existing assertions pass as-is; living docs re-pointed | 2, 3, 4 (help and usage byte identity), 4 (docs) |
| Demo: `just agent-installed-skill-tests` shows the real module answering | 5 |

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D11 from design,
and they cite the parent's rows as "parent D*n*". Planning added two rows:

- **D12** refines D9. The resolver suite's fixture root gains one
  `docs/standards` mkdir (Task 6).
- **D13** refines how D5's `lib.mkMerge` is written. It is inline, and
  `nixfmt` is not re-run (Task 4).

A planning probe in a scratch clone applied Tasks 1–6's code and ran their
gates. The darwin build passed, the installed test passed with its red proofs,
the help and usage byte identity held, the D5 conflict failed evaluation as
intended, and the full suite passed at 1050 tests.

## Standards review provenance

- Reviewer: Claude fallback (native `reviewer`, Opus). Codex `plan-review` was
  attempted first and failed with a usage-limit error (`CODEX_REVIEW_FAILURE`),
  so the one-time native fallback ran; Codex was not retried.
- Base SHA `5702dfb`, plan reviewed at `08b7c93`; isolated, read-only; no focus.
- Accepted 5, rejected 0, deferred 0. Should-fix: SF-1, single-channel controls
  (Task 5, spec D8 text, D14); SF-2, the golden-digest comment shows the
  escaped bytes (Task 1). Discussion, applied: D-1, the evaluation-time
  command-table assert (Task 4, D14); D-2, the pool check widens an empty window
  (Task 2); D-3, the recorded shell values are substituted literally (Task 4).

---
