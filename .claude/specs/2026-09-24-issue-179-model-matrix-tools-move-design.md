# Model-matrix tools and standalone commands move into agent_tools

Design, 2026-09-24, for issue #179. This is a cluster slice of the accepted
parent design,
[One package for the agent workflow helpers](2026-09-24-agent-tools-package-design.md),
built on the foundation slice
[#175](2026-09-24-issue-175-agent-tools-foundation-design.md). Every parent row
and every #175 row binds. This spec cites them as "parent D*n*" and "#175 D*n*"
and restates neither. It was written unattended, so each non-obvious call it
makes is a row in the Decision ledger below.

## Problem

Seven agent tools are still flat scripts outside the package:

- the model-matrix validator, deployed as `agent-model-matrix`;
- the model-drift reporter, a repo-only tool, and its three sibling modules
  (routing, scheduling, schema);
- `diff-scope`, which ship-issue's size gate calls by bare name;
- `context-map-lint`, whose `~/.agents/bin` path is promised to other
  projects' CIs.

Each deployed one runs on whatever `python3` its shebang finds, so anything on
that interpreter's import path can shadow it. The drift reporter reaches its
siblings through three `SourceFileLoader` blocks derived from `__file__`. Its
schema module executes the model-matrix validator from a file path under the
matrix root. The scheduling module leans on that loader's `sys.modules`
registration for a bare sibling import. The drift suites insert the tests
directory into `sys.path` and load the reporter by file path. The matrix and
diff-scope suites load their modules by file path as well.

The last copies of the canonical-JSON knowledge also live here. The drift
schema and the drift scheduling module each copy the telemetry digest, and the
model matrix copies the duplicate-key hook. The drift schema also has a
duplicate-key variant of its own, which #175 left for this slice to decide.

The user needs the move to be invisible. Command names, `~/.agents/bin` paths
and argv/stdin/stdout/exit contracts must not change, and existing assertions
must keep asserting what they assert today.

## Solution

One PR delivers the following:

- It moves the seven files into `python/agent_tools/` with `git mv`. Each gets
  only the small edits listed below.
- It adds three command-table rows to `lib/agent-tools.nix`, `agent-model-matrix`,
  `context-map-lint` and `diff-scope`, and deletes their hand-written `home.file`
  links.
- It replaces every loader in the drift family with a package import. That
  covers the reporter's three `SourceFileLoader` blocks, the schema's
  file-path load of the validator, and the scheduling module's bare import.
- It switches the matrix's hook and the two drift digests to
  `agent_tools.canonical`. The drift schema adopts `reject_duplicate_keys`
  too (D4).
- It runs the `agent-model-matrix` and `agent-model-drift` recipes as
  `python3 -m` under the recipe `PYTHONPATH`.
- It re-points the moved tools' tests to import normally and run `-m`, and
  deletes every `sys.path` insert and file-path loader they hold.
- It extends the installed-layout test to the three new launchers.
- It re-points the living documents.

After it, the top-level `scripts/` directory holds no tracked file.

## Decisions

### What moves (D1)

| Today | Module | Launcher |
|---|---|---|
| `home/common/agent-skills/scripts/agent-model-matrix.py` | `agent_tools.agent_model_matrix` | `~/.agents/bin/agent-model-matrix` |
| `home/common/agent-skills/scripts/diff-scope.py` | `agent_tools.diff_scope` | `~/.agents/bin/diff-scope` |
| `scripts/context-map-lint.py` | `agent_tools.context_map_lint` | `~/.agents/bin/context-map-lint` |
| `scripts/agent-model-drift.py` | `agent_tools.agent_model_drift` | none (repo-only; `just agent-model-drift`) |
| `scripts/agent-model-drift-routing.py` | `agent_tools.agent_model_drift_routing` | none (sibling module) |
| `scripts/agent-model-drift-scheduling.py` | `agent_tools.agent_model_drift_scheduling` | none (sibling module) |
| `scripts/agent-model-drift-schema.py` | `agent_tools.agent_model_drift_schema` | none (sibling module) |

Module names follow parent D1, the command name with underscores. The drift
siblings have no command, so each takes its file name with underscores. Those
are the names the reporter's loaders register them under today. No name
collides with the package's current modules (`agent_costs`, `agent_evidence`,
`agent_gate_bundle`, `canonical`). The drift family stays four flat modules,
per parent D1 and the parent's refinement of #98 D13 (siblings import each
other as package modules).

### How each file changes (D2–D5)

Every move follows #175 D2. Four of the seven files have a shebang, and each
of those goes. All seven are already mode `100644`. Absolute `agent_tools` imports replace the loaders, and imports
left unused are removed. The `if __name__ == "__main__":` block stays. Nothing
else changes: no split functions, no reformatting, and no renamed helpers
beyond those listed here.

- **`agent_model_matrix`.** The local `_reject_duplicate_keys` is deleted, and
  `load_matrix` passes `reject_duplicate_keys` from `agent_tools.canonical`.
  The parser becomes `ArgumentParser(prog="agent-model-matrix", description=__doc__)`.
  The installed command's usage already reads `agent-model-matrix`, taken from
  its link name, so `--help` stays byte-identical (#175 D5). The module
  docstring is that `--help` description, so it is not edited.
- **`diff_scope`.** Only the shebang is removed. It already pins
  `prog="diff-scope"`, and its docstring is its `--help` description.
- **`context_map_lint`.** Only the shebang is removed. It has no argparse
  parser: `main(sys.argv)` checks a fixed argv shape, and on misuse it prints
  the module docstring to stderr and exits 2. That docstring is observable
  output, so it stays byte-identical. Under `-m`, `sys.argv[0]` is the module
  path, and `main` never reads it. Shard rule 2 asks for a parser whose `prog`
  is the command name. The linter keeps its hand-written check anyway,
  because parent D15 promises its CLI unchanged and an argparse parser would
  change its misuse output. Its usage text and each status line already name
  the command (D8).
- **`agent_model_drift_routing`.** This is a pure rename: it imports no
  sibling.
- **`agent_model_drift_scheduling`.** The bare
  `from agent_model_drift_schema import SCHEDULING_METRICS` becomes
  `from agent_tools.agent_model_drift_schema import SCHEDULING_METRICS`. The
  local `_digest` is deleted, and its two call sites call `telemetry_digest`,
  imported from `agent_tools.canonical` (D3). `hashlib` and `json` go, because
  only `_digest` used them.
- **`agent_model_drift_schema`.** Three changes:
  - `canonical_digest` is deleted, and its two call sites (the record digest
    and the baseline digest) call `telemetry_digest` (D3).
  - `_duplicates` is deleted. `load_json` passes `reject_duplicate_keys` (D4).
  - `load_validated_matrix` imports the packaged validator (D5).

  `hashlib`, `importlib.machinery` and `sys` go.
- **`agent_model_drift`** (the reporter). The three `SourceFileLoader` blocks
  become
  `from agent_tools import agent_model_drift_routing as routing_logic`, the
  same for `agent_model_drift_scheduling as scheduling_logic` and
  `agent_model_drift_schema as schema`, and
  `from agent_tools.canonical import telemetry_digest`. The local names stay
  (D2), so no call site in `evaluate` changes, and the producer-integration
  test's `agent_model_drift.schema` access keeps working. `main` computes
  `matrix_digest = telemetry_digest(matrix)`, and its parser becomes
  `ArgumentParser(prog="agent-model-drift")`. The usage line used to name a
  script file that no longer exists, so it now names the `just` recipe, as
  #175 D5 did for the other repo-only tools. `importlib` and `Path` go.

**Canonical composition, per caller (D3, D4).** Each caller passes exactly the
hooks it applied before (parent D11):

| Caller | Composition | Duplicate keys | NaN / Infinity |
|---|---|---|---|
| `agent_model_matrix.load_matrix` | `json.loads(text, object_pairs_hook=reject_duplicate_keys)`, with the `except (OSError, json.JSONDecodeError, ValueError)` clause untouched | rejected: `cannot load <path>: duplicate JSON key '<k>'`, text unchanged | accepted, as today |
| `agent_model_drift_schema.load_json` | `json.loads(text, object_pairs_hook=reject_duplicate_keys)`, with the clause widened to `except (OSError, ValueError)` | rejected: `cannot load JSON input`, exit 2, unchanged | accepted at parse; field validators judge the values, as today |
| `agent_model_drift_scheduling` | no load; `telemetry_digest` only | — | — |
| `agent_model_drift` | no load; `telemetry_digest` of the validated matrix | — | — |

`diff_scope` and `context_map_lint` hold no digest and no strict load, so they
need nothing from `canonical`.

**Why the drift schema's clause widens (D4).** The canonical hook raises a
plain `ValueError`. Under the old tuple
`(OSError, UnicodeError, json.JSONDecodeError, InputError)`, a duplicate key
would escape `load_json` unwrapped, and stderr would change. Every member of
that tuple except `OSError` is a `ValueError`, so `(OSError, ValueError)`
catches everything it caught before, plus the hook. The new clause catches one
more case. A JSON integer literal longer than the interpreter's
integer-conversion limit (4,300 digits by default) raises a plain `ValueError`
inside `json.loads`. Today that error escapes to `main`, which prints the
interpreter's own message and exits 2; this was reproduced on the base. After
the change the same input prints `cannot load JSON input` and still exits 2.
Accepted input, stdout and exit codes are unchanged. #98's contract for
malformed documents is exit 2 with empty stdout, and no suite pins that
message. That edge's stderr text is the only observable delta in this slice.
One other plain `ValueError` can arise in that block: a path with an embedded
NUL byte. It cannot arrive through argv, so the command never sees it.

**The packaged validator (D5).** The body of `load_validated_matrix(root)`
becomes: `errors = agent_model_matrix.validate(root)`; if there are any, raise
`InputError("matrix validation failed")`; otherwise return
`agent_model_matrix.load_matrix(root)`. All of it stays inside today's
`except Exception` wrapper, which re-raises
`InputError("matrix validation failed")`. The `sys.modules` save and restore
goes with the loader. The matrix root now supplies data only: the matrix JSON,
the dispatch-site files and the agent manifests. The validator code is the
package's. For the recipe's normal use (`--matrix-root .` from source) nothing
changes, because the running checkout is the root. Two inputs used to fail
with `matrix validation failed` and are now judged on their data:

- a root that holds no validator script under
  `home/common/agent-skills/scripts/`, which after this move includes this
  repository itself;
- a subdirectory of a repository. The validator's own upward root search
  already governed the validation; only the file-path load required the exact
  root.

This is #98's stated intent: the reporter "loads the existing matrix through
its validator module rather than reimplementing" it. Once `matrix_fixture`
stops copying the script (D6), every drift CLI test runs against a root that
holds no validator script. The existing suites therefore exercise D5 without
a new test.

### Wiring (D1, D6)

- **Command table.** In `lib/agent-tools.nix`, `commands` becomes
  `[ "agent-evidence" "agent-model-matrix" "context-map-lint" "diff-scope" ]`,
  one per line. Below the existing naming comment, a comment carries the
  promise the deleted link's comment made: `# context-map-lint is a stable path other projects'
  CIs call without vendoring it (parent D15).` The per-row evaluation
  assertion (#175 D14) checks the three new modules. The imports check covers
  all seven modules by the existing recursive walk, so `lib/agent-tools.nix`
  gains no list.
- **Home.** In `home/common/agent-skills/default.nix`, three entries are
  deleted from the literal `home.file` set, `.agents/bin/context-map-lint`
  with its "Stable path" comment, `.agents/bin/agent-model-matrix` and
  `.agents/bin/diff-scope`. The launchers arrive through the existing
  `agentToolFiles` definition. Under #175 D5, a leftover entry would be a
  conflicting definition and fail evaluation. `home.packages = [ pkgs.python3 ]`
  and the session `PATH` stay, because other flat scripts still need them.
- **Isolation.** The three deployed commands now run under the environment's
  `python3 -I` (parent D2). `PYTHON*` variables, the working directory and the
  user site no longer reach them, and none of them reads any of those.
- **Recipes.** These follow #175 D6: `PYTHONPATH` is assigned, not prepended,
  and there is no global export.
  - `agent-model-matrix` runs
    `PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_matrix validate`,
    then the same prefix with `trace representative`. The validator still
    finds the repository root from the recipe's working directory.
  - `agent-model-drift *args` runs
    `PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_drift {{args}}`.
  - `agent-workflow-tests` gains `tests/test_context_map_lint.py`, inserted
    before `tests/test_branch_protection.py` (D6).

### Test re-points (D6, D7)

Test edits change only how code is located, as in #175 D7. No expected value
or assertion predicate changes, with three exceptions: D7's two location
literals, D8's installed-layout test, and one added drift run (D6). The only
fixture change is that `matrix_fixture` stops copying the one file that only
the deleted loader read.

- **`home/common/agent-skills/tests/test_agent_model_matrix.py`.**
  `import importlib.util`, `SCRIPT` and `load_module` go. The file imports
  `from agent_tools import agent_model_matrix`, and each
  `module = load_module()` becomes `module = agent_model_matrix`. No test
  mutates module state, so one shared instance couples nothing. The CLI test
  runs
  `[sys.executable, "-m", "agent_tools.agent_model_matrix", "validate", "--root", str(root)]`.
- **`home/common/agent-skills/tests/test_diff_scope.py`.** `import
  importlib.util`, `REPO_ROOT`, `SCRIPT` and `load_module` (with its
  docstring) go. The file imports `from agent_tools import diff_scope`, and
  its three `load_module()` calls become `diff_scope`. The package import
  registers the module in `sys.modules`, which is what its dataclasses need.
  `run_helper` and the outside-work-tree test run
  `[sys.executable, "-m", "agent_tools.diff_scope", …]`. `git_env()` copies
  `os.environ`, so the recipe's absolute `PYTHONPATH` reaches the child even
  when its working directory is a scratch repository. The module docstring's
  "imports scripts/diff-scope.py directly" and "runs the script as a
  subprocess" become "imports `agent_tools.diff_scope`" and "runs the module
  with `python -m` as a subprocess".
- **`tests/test_context_map_lint.py`.** Its runs become
  `[sys.executable, "-m", "agent_tools.context_map_lint", …]`, replacing
  `"python3", str(LINTER)`. `LINTER` becomes
  `REPO_ROOT / "python/agent_tools/context_map_lint.py"`, used only by the
  source-text scan. The suite joins `agent-workflow-tests`. No recipe runs it
  today, and after the move it cannot run without the recipe's `PYTHONPATH`.
- **`tests/agent_model_drift_test_support.py`.** `importlib.util`, `SCRIPT`
  and the file-path load go. It imports
  `from agent_tools import agent_costs, agent_model_drift`. `matrix_fixture`
  drops the validator script from its copy list, because its only reader was
  the deleted loader (D5). The local `digest` stays. It is the fixtures'
  independent expected-value oracle: sealed records and baselines are checked
  against `telemetry_digest` inside the schema, so the check keeps comparing
  two independent implementations (D6, D9).
- **The four drift suites** (`test_agent_model_drift_{schema,routing,scheduling,producer_integration}.py`).
  Each deletes its `sys.path.insert` and the `sys`/`Path` imports that served
  only that insert. Each then imports
  `from .agent_model_drift_test_support import (…)` with its name list
  unchanged. The producer-integration suite also imports
  `from .test_agent_costs import (…)`. The recipe loads these files as
  `tests.<module>`, so relative imports resolve. This is the precedent
  `from ._delivery_model_fixtures import …` in the agent-skills suites. The
  producer test's `mock.patch.object(agent_model_drift.schema, …)` is
  unchanged (D2).
- **`tests/test_agent_model_drift_scheduling.py`** gets two more changes. It
  keeps `import sys` and adds `import subprocess` for the second one.
  - `RepositoryWiringTest`'s required literal
    `"python3 scripts/agent-model-drift.py {{args}}"` becomes
    `'PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_drift {{args}}'`
    (D7).
  - The same class gains one test, which runs
    `[sys.executable, "-m", "agent_tools.agent_model_drift", "--help"]` with a
    bounded timeout and asserts exit 0 and stdout starting with
    `usage: agent-model-drift `. Every other drift test calls `main()` in
    process, so without this run a lost `__main__` block would leave
    `just agent-model-drift` silent while every suite stayed green. This is
    #175 D7's reason for the matching runs in the cost and gate suites, and
    the run also pins D2's `prog`.
- **`home/common/agent-skills/tests/test_workflow_skill_contracts.py`**
  changes three things (D7):
  - `test_living_source_has_no_legacy_policy_surface` passes the pathspec
    `python` instead of `scripts/context-map-lint.py`.
  - `_install_policy_surface_fixture` copies
    `python/agent_tools/context_map_lint.py` into the fixture home's
    `.agents/bin/context-map-lint`.
  - The degradation-gate comment's "lives in diff-scope.py" becomes "lives in
    `agent_tools.diff_scope`".

  Its real-home check (`test_installed_policy_surface_matches_source_contract`)
  is unchanged. After a switch, the installed linter is the launcher: a
  regular executable file with no legacy token, so the check still holds.
  The check reads the file and never runs it, so shard rule 5 still holds.
  CI skips it with `WORKFLOW_POLICY_SURFACE=source`.

No suite here builds a child environment from scratch, so no `PYTHONPATH`
forwarding is needed (parent D8).

### The installed-layout test (D8)

`tests/test_agent_tools_launchers.py` keeps its enumeration, name, hostile-run
and control structure. It changes in two places:

1. **Floor.** `test_the_command_table_generates_agent_evidence` becomes
   `test_the_command_table_generates_each_deployed_command`. It asserts, one
   subtest per name, that the launcher set contains every member of
   `LAUNCHER_FLOOR = ("agent-evidence", "agent-model-matrix", "context-map-lint", "diff-scope")`.
   A comment says this is the set #175 and #179 accepted as launchers: a
   floor, not the full set, which the command table owns (#175 D8).
2. **Misuse-answering commands.** A constant
   `MISUSE_USAGE = {"context-map-lint": "Usage: context-map-lint --repo-root "}`
   has this comment: "Commands without an argparse parser answer `--help` as
   misuse, with the module docstring on stderr and exit 2. Their CLI is
   promised unchanged (parent D15), so the probe pins that answer by a line
   only the module's own docstring prints." The hostile run keeps today's
   assertions for every launcher outside the map: exit 0, and stdout
   starting with `usage: <name> `. For a mapped launcher it asserts exit 2,
   empty stdout, and stderr containing the mapped line. Every launcher still
   asserts that the marker appears in neither stream. An import failure prints
   a traceback, never that docstring line, so the assertion still proves the
   module's own argument handling ran (parent D9 seam 2).

The controls need no change. The fake package's `__init__` exits 97 before
any command code runs, so they hold for every launcher. The module docstring
cites #179 D8 beside #175 D8.

### Living documents (D10)

- **`CLAUDE.md`.** In the "Agent helper package" paragraph, the sentence "The
  other helpers are still flat scripts under `scripts/` and
  `home/common/agent-skills/scripts/` and move in cluster by cluster, …"
  becomes "The remaining Python helpers are still flat scripts under
  `home/common/agent-skills/scripts/`, plus the sdd skill's `review-package`,
  and move in cluster by cluster, …". The rest of the sentence is unchanged.
  After this PR `scripts/` holds no tracked file.
- **`docs/standards/`** is unchanged. The index keeps `scripts/**` among the
  shard's globs. Parent D6 put it there so that a new flat script in that
  directory still loads the rule forbidding it. A glob that catches new files
  is not a placeholder for a missing one.
- **Skill prose, the agent-skills README and the codex-collaboration
  documents** name the commands and their `~/.agents/bin` paths, which do not
  change. They need no edit.
- The test docstrings and comments are re-pointed as listed in D6 and D7.
  Point-in-time records under `.claude/specs` and `.claude/plans` keep their
  paths.

### In-flight overlap (D11)

This was checked on 2026-09-24, against every worktree branch and the open PRs.
No branch edits the seven moved files, their suites, `python/`,
`lib/agent-tools.nix` or `docs/standards/`, so parent D5's gate holds for this
cluster. Branches for #150 (open PR #184), #121, #152, #154 and #117 edit the
shared wiring files: the justfile's test list and installed recipe,
`home/common/agent-skills/default.nix`, `CLAUDE.md`, and the contracts test.
They touch other hunks than this slice does. Edits to those files stay local
and never reflow neighbouring lines. `nixfmt` is not re-run on the agent-skills
module (#175 D13). #176, in flight in the same run, touches none of these
files.

### Acceptance criteria and how each is verified (D9)

- **AC1: the three commands are package launchers exercised by the
  installed-layout test.** `just agent-installed-skill-tests` passes, and its
  verbose output shows the floor subtests, the hostile runs and the controls
  for `agent-model-matrix`, `context-map-lint` and `diff-scope`. The Nix
  evaluation assertion refuses a table row without a module.
- **AC2: the drift family reaches the matrix and its siblings through package
  imports, and no file-path loader remains in these modules or their tests.**
  `git grep -nE "importlib|SourceFileLoader|spec_from_file_location|sys\.path|__file__" -- python/agent_tools`
  returns nothing (it is clean at base, too). The same pattern without
  `__file__` returns nothing over `tests/agent_model_drift_test_support.py`,
  `tests/test_agent_model_drift_*.py`, `tests/test_context_map_lint.py` and
  the matrix and diff-scope suites. Their `REPO_ROOT` constants locate
  repository data files, not code.
- **AC3: across the repository, the telemetry digest and the duplicate-key
  hook are each defined only in `agent_tools.canonical`.** The criterion is
  read as follows:
  - "The telemetry digest" is the agent-cost-telemetry D9 function.
  - "The duplicate-key hook" is the `ValueError(f"duplicate JSON key {key!r}")`
    `object_pairs_hook`. #175 D1 established that a hook raising its own error
    type and text is a variant, not a copy.
  - "The repository" means product code: tracked files outside the test
    directories and `.claude/`. Test-side expected-value oracles are the
    independent half of a check, not a definition.

  Two greps verify it after the PR:
  - `git grep -n hashlib -- python` lists only `python/agent_tools/canonical.py`.
  - `git grep -nE "object_pairs_hook=" -- . ':!.claude' ':!tests' ':!**/tests/**'`
    lists four package lines, each passing `reject_duplicate_keys`
    (`agent_evidence`, `agent_gate_bundle`, `agent_model_matrix`,
    `agent_model_drift_schema`). It also lists
    `artifact_budget.py`'s `_pairs_no_duplicates`, which raises the budget
    validator's own error and is #178's to adopt when it moves that module.

  Two other formats remain elsewhere, and both are variants too: the adoption
  plan digest, which refuses NaN (#177), and the delivery format (#178).
- **Regression floor.**
  - `just agent-workflow-tests` passes with every pre-existing assertion
    unedited, apart from D7's two location literals.
  - `just build` passes, import-checking the seven modules.
  - The built launchers' `--help` output for `agent-model-matrix`,
    `diff-scope` and `context-map-lint` (for the linter, its misuse answer)
    is byte-identical to the base source run the way the base home ran it:
    through a link named for the command. The machine's current
    `~/.agents/bin` is not the reference, because it may be an older
    activation.
- **Demo.**
  - `just agent-model-matrix` prints `agent model matrix: valid` and the
    representative trace from the package.
  - `just agent-model-drift --help` prints `usage: agent-model-drift …`.
  - `just agent-installed-skill-tests` shows the three new launchers passing.

A design probe, run on a scratch export of the base, applied this section's
module, recipe and test edits. The edited suites and the contracts suite
passed: 288 tests, 1 skipped. Both demos ran. An oversized integer literal and
a duplicate key each printed `cannot load JSON input` and exited 2 (D4). Staged
with `git mv`, all seven moves paired as renames, with similarity between 79%
and 100%. The Nix build and the installed-layout test were not probed.

## Test seams

This slice uses the parent's first two seams and adds no other:

1. **Command contract and module interface, from source.** The existing
   suites run under the recipe's `PYTHONPATH`, with commands as
   `[sys.executable, "-m", "agent_tools.<module>", …]` and modules imported
   normally. This slice adds the context-map-lint suite to the recipe and one
   `-m --help` run for the drift reporter (D6).
2. **Installed layout.** `tests/test_agent_tools_launchers.py` gets the
   extended floor and the misuse-answer expectation (D8).

Seam 3, the guard's registered hook, is untouched. The build-time imports check
and the demo are shown once during verification, not committed (#175
precedent).

## Out of scope

- Every other cluster:
  - #176, the guard;
  - #177, the resolver family and the adoption modules with their plan
    digest;
  - #178, the delivery family, `artifact-budget` with its
    `_pairs_no_duplicates` variant, review packaging, and the delivery
    format's rename.
- The parent-D16 sibling-run helper. No moved module runs another packaged
  command. `diff-scope` runs `git` by name.
- Splitting `agent-model-matrix`'s or any other oversized function (parent
  out of scope).
- Converting `context-map-lint` to argparse, or changing any command's argv,
  help or misuse output.
- Replacing test-side digest oracles with `telemetry_digest`.
- Relocating test files, switching the test recipe to discovery, or adding a
  committed lint that scans for canonical copies.
- `resolve-bindings`, the shell scripts and unrelated Python (parent out of
  scope).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Move exactly the seven files via `git mv` to flat modules named by parent D1 (`agent_model_matrix`, `diff_scope`, `context_map_lint`, `agent_model_drift`, `agent_model_drift_{routing,scheduling,schema}`); the three deployed commands become command-table rows and lose their hand-written links; the drift family stays repo-only | Parent D1, D13; parent refinement of #98 D13; #175 D1, D4, D5; issue #179 scope | A drift subpackage — needs a `__main__` module and breaks the command = module naming rule for structure nobody asked for |
| D2 | Edits per move are #175 D2's list plus: the reporter keeps `schema`/`routing_logic`/`scheduling_logic` as `import … as` aliases; `prog` pinned for `agent-model-matrix` and `agent-model-drift`; docstrings that are `--help` or misuse output stay byte-identical | Parent D14 rename pairing; #175 D2, D5; parent D15 | Import siblings under their module names — rewrites every call site in `evaluate` and the producer test's `agent_model_drift.schema` access |
| D3 | The matrix passes canonical's `reject_duplicate_keys`; the drift schema's `canonical_digest` and the scheduling module's `_digest` are deleted and their call sites (and the reporter's matrix digest) call `telemetry_digest` imported directly | Parent D11; #175 D3 (callers import the name directly); shard rule 4; #178's criterion that the delivery and telemetry digests stop sharing a name | Keep `canonical_digest` as a local alias — two formats keep sharing one name |
| D4 | The drift schema's variant hook is replaced by canonical's `reject_duplicate_keys`, and `load_json`'s clause widens to `except (OSError, ValueError)`: duplicates still yield `cannot load JSON input`/exit 2, accepted input is unchanged, and the only delta is that an integer literal over the interpreter's digit limit now reports `cannot load JSON input` (exit 2 either way) | #175 D1 (#179 decides the variant); shard rule 4; #98 design (malformed input: exit 2, empty stdout); reproduction on base | A local adapter re-raising `InputError` — still a local hook (rule 4, AC3). A typed `DuplicateKeyError` in `canonical` — widens #175 D3's closed surface to preserve a corrupted-input message (YAGNI) |
| D5 | `load_validated_matrix` imports the packaged validator; the matrix root supplies data only; roots lacking the old script path (now including this repo) or below the repo root are judged by data instead of failing; the fixture stops copying the script | #98 design ("through its validator module"); parent D12, D16; AC2 | Keep executing `<root>/…/agent-model-matrix.py` by path — a file-path loader AC2 removes, at a path that no longer exists here |
| D6 | Tests import modules normally and run `[sys.executable, "-m", …]`; the drift suites use relative sibling imports (the `_delivery_model_fixtures` precedent) and drop every `sys.path` insert; the context-map-lint suite joins `agent-workflow-tests`; the drift reporter gains one `-m --help` run; the drift fixtures keep their own `digest` oracle | Parent D8; shard rule 5; #175 D7; the-bar Tests that can fail | Absolute `from tests.… import` — a second convention beside the existing relative one. Lint suite left outside every recipe — its `-m` runs have no `PYTHONPATH`. Oracle → `telemetry_digest` — canonical checked against itself |
| D7 | Two existing assertions change only a location literal: the drift recipe literal becomes the `-m` recipe line, and the legacy-surface scan's pathspec `scripts/context-map-lint.py` becomes `python` (the policy-surface fixture copies the linter from its new path) | Issue #179 mandates the recipe switch, and #175 D6 deferred this literal; the scan must keep covering the moved helpers' source, and every `python/` file is clean today | A justfile comment carrying the old literal — a fake green. Re-pointing the scan to the linter file alone — the matrix and diff-scope sources silently leave it |
| D8 | The installed test's floor becomes the four deployed commands; the hostile `--help` run keeps its argparse expectation except for a one-entry `MISUSE_USAGE` map pinning `context-map-lint`'s docstring-on-stderr, exit-2 answer; the linter keeps its hand-written argv check, so shard rule 2's parser clause yields to D15 | Parent D15 (the linter's promised CLI outranks the shard's parser clause); parent D9 seam 2; #175 D8 | Converting the linter to argparse — changes a CLI other projects call. A no-argument probe — a future command without required arguments would do real work. Any-exit, any-stream assertions — weakens every argparse launcher's check |
| D9 | AC3 reads "the telemetry digest" and "the duplicate-key hook" as the exact canonical functions, over product code (test oracles excluded), verified by two greps; `artifact_budget`'s own-error variant, adoption's NaN-refusing digest and the delivery format are variants owned by #178/#177 | #175 D1 (a hook with its own error is a variant); issue #179's parenthetical names only the drift schema, drift scheduling and matrix; parent D12 (a flat script cannot import the package without a loader) | Adopting `artifact_budget`'s hook here — edits a #178 module that cannot import `agent_tools` until it moves |
| D10 | Re-point `CLAUDE.md`'s transition sentence (no `scripts/` left; names `review-package`); keep the standards index's `scripts/**` glob; carry the linter's stable-path promise to a comment on the command table; skill prose unchanged | the-bar Moves keep their history, Production-grade; parent D6 (legacy globs catch new flat scripts), D14, D15 | Dropping `scripts/**` — reverses parent D6's deterrence without grounding. Leaving `CLAUDE.md` as is — it names a directory with no tracked files |
| D11 | Take the cluster now: no in-flight branch touches its files; edits to the shared wiring files (#150's PR #184, #121, #152, #154, #117) stay local, with no reflow and no `nixfmt` | Parent D5; #175 D13 | Waiting for those branches — none touches this cluster's files, which is parent D5's gate |
| D12 | Plan order: drift family, then matrix, `diff-scope`, linter, floor. The drift family moves first with `load_validated_matrix` byte-identical for one commit (it still loads the flat validator by path, and `matrix_fixture` still copies it); the matrix move replaces both (D5). D8's misuse map lands with the linter's row and its floor after the last row, so every commit keeps `just build`, `just agent-workflow-tests` and `just agent-installed-skill-tests` green | Parent D14; #175 plan precedent (one task per move, each green); the-bar Tests that can fail | Matrix first — the flat drift schema would have to load a package module by path, which the recipe cannot import without `PYTHONPATH`. One matrix-and-drift task — a reviewer could reject either half alone. The floor with the first row — it fails until the last row lands |
