# Agent tools foundation: package, isolated launchers, one canonical-JSON home

Design, 2026-09-24, for issue #175. This is the foundation slice of the accepted
parent design,
[One package for the agent workflow helpers](2026-09-24-agent-tools-package-design.md).
Every parent row binds. This spec cites them as "parent D*n*" and restates none.
It was written unattended, so each non-obvious call it makes is a row in the
Decision ledger below.

## Problem

The parent design is accepted, but none of it exists yet. There is no package
for helper code to live in, no build that turns a module into an isolated
`~/.agents/bin` command, and no project standard that sends new helper code to
the package. Every cluster move (#176–#179) needs that scaffolding, and without
a shared foundation each one would build its own.

Meanwhile three tools keep private copies of canonical-JSON knowledge. The
telemetry digest is copied into both `agent-costs` and `agent-gate-bundle`, and
the duplicate-key JSON hook into both `agent-gate-bundle` and `agent-evidence`.
The deployed `agent-evidence` is a raw script run by whatever `python3` its
shebang finds, so anything on that interpreter's import path can shadow it.

The user needs these moves to be invisible. Every command name, `~/.agents/bin`
path and argv/stdin/stdout/exit contract must stay as it is, and every existing
assertion in the moved tools' suites must keep asserting exactly what it
asserts today.

## Solution

One PR delivers the following:

- It creates `python/`, holding `pyproject.toml` and the `agent_tools` package:
  an `__init__`, the shared `canonical` module, and three tools moved in with
  `git mv`, each of which imports `canonical`.
- It adds `lib/agent-tools.nix`. The file builds the package and its one
  interpreter environment, checks that every module imports, and generates one
  isolated launcher per command-table row. The table has one row,
  `agent-evidence`.
- It changes the agent-skills Nix module to install the generated launcher in
  place of the raw `agent-evidence` script link.
- It points the test and tool recipes, and the moved tools' tests, at the
  source package through `PYTHONPATH`.
- It adds an installed-layout test to `just agent-installed-skill-tests`. The
  test proves that the built `agent-evidence` ignores a hostile `agent_tools` on
  `PYTHONPATH`.
- It adds the project standards shard `docs/standards/` and registers it in
  project policy.
- It re-points the living documents that name the moved files.

## Decisions

### What this slice moves (D1)

| Today | Module (parent D1 naming) | Launcher |
|---|---|---|
| `scripts/agent-costs.py` | `agent_tools.agent_costs` | none (repo-only; `just agent-costs`) |
| `scripts/agent-gate-bundle.py` | `agent_tools.agent_gate_bundle` | none (repo-only; `just agent-gate-bundle`) |
| `home/common/agent-skills/scripts/agent-evidence.py` | `agent_tools.agent_evidence` | `~/.agents/bin/agent-evidence` |

The command table therefore has exactly one row. The parent's rollout expected
two launchers in the foundation, but the issue was sliced after that spec was
written, and its slicing governs. One real launcher is enough for seam 2.

The other copies of the canonical knowledge stay where they are until #179:
the digests in the model-drift schema and scheduling modules, and the
duplicate-key hook in the model matrix. The model-drift schema's `_duplicates`
hook is not one of those copies: it raises a different error with different
text, so #179 decides how it adopts `canonical`. The delivery model's
`canonical_digest` is renamed with the delivery cluster (parent D11).

### How each file moves (D2)

Each tool moves with `git mv` to `python/agent_tools/<module>.py`. Its content
changes are limited to the following, which keeps them small enough for git's
rename pairing (parent D14):

- The shebang line and the executable bit go. A package module is imported or
  run with `-m`, never run by path. `agent-evidence` is already mode `100644`.
- The local digest or hook definitions are deleted, and one
  `from agent_tools.canonical import …` line is added. The package uses
  absolute imports throughout.
- The telemetry digest's call sites are renamed from `canonical_digest` to
  `telemetry_digest` (D3).
- Each command's `ArgumentParser` gets `prog="<command>"` (D5).
- The `agent-gate-bundle` docstring names `agent-costs.py`. It is re-pointed
  to `agent-costs`.

The `if __name__ == "__main__":` block stays, because it is what `-m` runs.
Nothing else changes: no split functions, no reformatting, no renamed
helpers.

### The canonical module (D3)

`agent_tools.canonical` uses only the standard library, does nothing at import
time, and has exactly three public names:

- **`telemetry_digest(body) -> str`** returns
  `"sha256:" + sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
  ensure_ascii=True).encode("utf-8")).hexdigest()`. That is byte-for-byte what
  today's copies compute (agent-cost-telemetry D9): no trailing newline, and
  `allow_nan` left at its default exactly as the copies leave it.
- **`reject_duplicate_keys(pairs) -> dict`** is an `object_pairs_hook`. It
  builds the object and raises `ValueError(f"duplicate JSON key {key!r}")` on
  the first repeated key.
- **`reject_nonfinite_literal(name)`** is a `parse_constant` hook. It always
  raises `ValueError(f"JSON constant {name} is not allowed")`. `json` calls it
  only for `NaN`, `Infinity` and `-Infinity`.

The module offers no composed loader: parent D11 rejected a parameterised load
function. Each caller composes its own hooks, exactly as it does today:

| Caller | Composition | Duplicate keys | NaN / Infinity |
|---|---|---|---|
| `agent_gate_bundle` (its local strict parse) | `json.loads(text, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal)` | rejected | rejected |
| `agent_evidence` (its artifact load) | `json.loads(text, object_pairs_hook=reject_duplicate_keys)` | rejected | accepted |
| `agent_costs` | no strict load; only the digest is shared | — | — |

**Why accepted input cannot change.** Each hook body is today's body, with the
same exception type and message. Each caller passes exactly the hooks it
passed before. Each caller's `except (json.JSONDecodeError, ValueError)` clause
is untouched. So the diagnostic codes (`JSON_INVALID`) and the `str(error)`
texts a caller emits are identical.

The shared digest is named `telemetry_digest`, the term the parent and the
shard use, and not `canonical_digest`. Until the delivery cluster renames the
delivery model's differently formatted `canonical_digest`, that name therefore
belongs to one function only. Callers import the name directly. They do not
alias it to their old local name.

### The package and its build (D4)

**`python/pyproject.toml`** declares:

- a setuptools build backend (`setuptools.build_meta`);
- a `[project]` table with `name = "agent-tools"`, a version, and
  `dependencies = []`, with no `[project.scripts]` (parent D3, D13);
- `[tool.setuptools.packages.find]` with `include = ["agent_tools*"]`.

**`python/agent_tools/__init__.py`** holds a docstring only: no re-exports and
no side effects.

**`lib/agent-tools.nix`** is a function of `{ pkgs }`, placed beside
`lib/agent-plugins.nix` (parent D7). It does five things:

- It reads `project.name` and `project.version` from the `pyproject.toml` with
  `lib.importTOML`, so the version has one home.
- It builds
  `package = python3.pkgs.buildPythonPackage { pyproject = true; src = ../python; build-system = [ setuptools ]; pythonImportsCheck = modules; }`.
  `modules` is derived by walking `python/agent_tools` recursively: every
  `.py` file becomes its dotted module name, and an `__init__.py` names its
  package. A module added later is checked without anyone editing a list
  (parent D10). nixpkgs runs the imports check as its own phase, whatever
  `doCheck` says. The package declares no check inputs, so no suite runs in
  the build.
- It builds `env = python3.withPackages (_: [ package ])`.
- It holds the command table, `commands = [ "agent-evidence" ]`: a list of
  command names. A module's name is its command name with each `-` replaced by
  `_`. That naming rule (parent D1) holds by construction and is written
  nowhere else.
- It builds the launchers. Each is
  `pkgs.writeShellScript "agent-tools-<name>"` with a two-line body:
  `unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE`, then the
  parent's `exec ${env}/bin/python3 -I -m agent_tools.<module> "$@"` (parent
  D2, D13; the `unset` line is D11). `writeShellScript` prepends the bash
  shebang, and its build runs `bash -n`.

The file returns `{ launchers }`, an attribute set from command name to
launcher store path. Nothing outside the file needs anything else from it.

**Isolation, channel by channel.** The environment's `python3` resolves its
own path and finds the environment's site-packages from that path. Under `-I`,
Python ignores every `PYTHON*` variable, never prepends the working directory,
and skips the user site.

`-I` does not stop nixpkgs' `sitecustomize`, which still runs. That module
reads three variables that are not `PYTHON*` variables:

- `NIX_PYTHONPATH`, whose directories it adds as site directories, running
  any `.pth` file it finds there. That is enough to put a fake package first on
  `sys.path`.
- `NIX_PYTHONPREFIX`, which rewrites `sys.prefix`.
- `NIX_PYTHONEXECUTABLE`, which rewrites `sys.executable`, the interpreter
  parent D16's sibling runs will reuse.

The environment's `python3` wrapper sets none of the three, so a value the
caller supplies would reach `sitecustomize` unchanged. The launcher unsets all
three before it execs (D11). With that line and `-I` together, the store copy
is the only `agent_tools` the launcher can import.

### Wiring into the home (D5)

The agent-skills module imports the file as
`import ../../../lib/agent-tools.nix { inherit pkgs; }`, the way the
claude-code module imports `agent-plugins.nix`. It maps each launcher to
`.agents/bin/<name>` with `source = <launcher>`.

The launcher entries enter `home.file` through `lib.mkMerge`, as a definition
separate from the existing literal attribute set, and the hand-written
`.agents/bin/agent-evidence` entry is deleted. A separate definition makes any
leftover hand-written entry for a table command a conflicting definition of
`source`, which fails evaluation. Joining the sets with `//` would let one
entry silently replace the other (the-bar, Fail loud).

`home.sessionPath` and `home.packages = [ pkgs.python3 ]` are unchanged, since
the raw scripts that have not moved yet still need a `python3` on `PATH`.

**The command keeps its name in its own output.** Under `-m`, argparse's
default `prog` is the module's file name: `agent_evidence.py` on Python 3.13,
and `python3 -m agent_tools.agent_evidence` on 3.14. Left alone, that would
change `agent-evidence --help` and every usage error. So each moved command
passes `prog="<command>"`, and the installed `agent-evidence` then prints
byte-for-byte what it prints today.

The two repo-only tools can print nothing byte-identical, because their usage
line named a script file that no longer exists. They now name the `just`
recipe instead (`agent-costs`, `agent-gate-bundle`), and no suite asserts that
line. The installed-layout test ties each launcher's name to its module's
`prog` (D8).

### Recipes run the source package (D6)

The justfile gains one variable,
`agent_tools_path := justfile_directory() / "python"`. The recipes that run
package code from source prefix their command with
`PYTHONPATH="{{agent_tools_path}}"`:

- `agent-workflow-tests`, because the suite imports `agent_tools`;
- `agent-costs`, which becomes `python3 -m agent_tools.agent_costs {{args}}`;
- `agent-gate-bundle`, which becomes
  `python3 -m agent_tools.agent_gate_bundle {{args}}`.

The prefix assigns `PYTHONPATH` rather than prepending to it, so an ambient
value never reaches the suite. Other recipes are left alone:

- `agent-installed-skill-tests` runs built launchers and tests that import
  nothing from source, so it gets no prefix.
- `agent-model-matrix` and `agent-model-drift` get their prefix with #179.
  That keeps the scheduling test's literal `python3 scripts/agent-model-drift.py
  {{args}}` assertion green.
- No justfile-wide `export` is used. It would leak into `switch`, `build` and
  `gc`, and it would touch lines #100 is editing.

### Test re-points (D7)

The only changes to existing test code are how it locates code and the
digest's name at its call sites. No expected value, fixture or assertion
predicate changes.

- **`tests/test_agent_costs.py`.** The `importlib` block becomes
  `from agent_tools import agent_costs` plus
  `from agent_tools.canonical import telemetry_digest`. Its
  `agent_costs.canonical_digest` calls become `telemetry_digest`, and its
  docstring's run line names `just agent-workflow-tests`.
- **`tests/test_agent_gate_bundle.py`.** Its loader becomes
  `from agent_tools import agent_gate_bundle as gate`, and its
  `gate.canonical_digest` calls become `telemetry_digest`, imported the same
  way. The docstring is re-pointed.
- **`home/common/agent-skills/tests/test_agent_evidence.py`.** `SCRIPT` goes.
  Both subprocess invocations run
  `[sys.executable, "-m", "agent_tools.agent_evidence", …]`, and the child
  inherits the recipe's `PYTHONPATH`.
- **`tests/agent_model_drift_test_support.py`** belongs to #179's cluster.
  Only its `agent-costs` load changes, to `from agent_tools import agent_costs`,
  because the old path no longer exists. Its file-path load of
  `agent-model-drift`, and the producer-integration test's `sys.path` insert of
  the tests directory, stay until #179 moves those tools.
  - The drift and cost tests now share one `agent_costs` module instance where
    they used to have two. Neither suite changes module state except through
    `mock.patch`, which restores it, so the sharing couples nothing.

Three small additions follow, all in seam 1. The first proves the recipes'
entry point runs `main`:

- **The cost and gate-bundle suites** each gain one run of
  `[sys.executable, "-m", "agent_tools.<module>", "--help"]`. Each run asserts
  exit 0 and stdout that starts with `usage: <command> `. Everything else in
  those suites calls `main()` in process, so without this run a lost
  `__main__` block would leave `just agent-costs` silently doing nothing while
  every suite stays green. The run also pins D5's `prog`.

The other two guard the one shared home:

- **`tests/test_agent_tools_canonical.py`**, added to `agent-workflow-tests`,
  pins:
  - a golden `telemetry_digest` as a literal hex string, over a body with
    unsorted keys, nesting, a non-ASCII string and a float;
  - each hook's exact exception text;
  - rejection of each of the three non-finite literals.

  Every existing digest assertion computes its expected value with the same
  function it checks. Today only the drift tools' independent copies would
  catch a format change in the shared home, and #179 removes those copies.
- **`test_agent_evidence`** gains two assertions that pin evidence's own hook
  composition: a duplicate key yields `JSON_INVALID`, and a `NaN` literal does
  not (the validator judges it, not the parser). The gate-bundle suite already
  pins both of its own behaviours.

### The installed-layout test (D8)

**Placement.** A new `tests/test_agent_tools_launchers.py` runs from
`just agent-installed-skill-tests`, after `test_dispatch_contracts.py` and with
the same `AGENT_SKILLS_INSTALLED_HOME`. It is not added to
`agent-workflow-tests`, because it has no source-side half. Its environment
handling follows #153 D8 and D16: an unset variable skips the test and names
the recipe, and a value that is not an absolute directory fails it.

**Enumeration.** The command table lives only in the Nix build, so the test
recognises what the build produced rather than reading a copy of the table. It
walks `<home>/.agents/bin`. Every entry whose bytes contain `agent_tools` must
fully match the launcher template: a `#!` line, the `unset` line, then
`exec <store-path>/bin/python3 -I -m agent_tools.<module> "$@"`. An entry that
does not match fails as a malformed launcher. The matching entries form the
launcher set.

The rule that anything naming the package must be a launcher is deliberate.
A raw script that imports `agent_tools` would be a loader, which shard rule 3
forbids, so the test failing on one is the test working.

**Assertions.**

1. The set contains `agent-evidence`. That is this issue's acceptance, and it
   stops the test passing vacuously if generation emits nothing. The full set
   is not pinned: the table owns it.
2. Each launcher's name equals its module name with `_` replaced by `-`.
3. **Hostile run.** A temporary root holds two things:
   - a fake `agent_tools/__init__.py` that writes a marker to stderr and exits
     97;
   - a `.pth` file whose `import` line puts that root first on `sys.path`.

   Each launcher runs as `<launcher> --help` with `PYTHONPATH` and
   `NIX_PYTHONPATH` both naming that root, and with that root as the working
   directory. The run must exit 0, its stdout must start with
   `usage: <name> `, and the marker must appear in neither stream.
4. **Controls.** These prove that each channel is live, so assertion 3 can
   fail. The launcher's own environment interpreter, taken from its `exec`
   line, runs `-m agent_tools.<module> --help` twice, and each run must exit
   97 with the marker:
   - (a) without `-I`, under the full hostile environment. This proves the
     `PYTHONPATH` and working-directory channels are live.
   - (b) with `-I`, with only `NIX_PYTHONPATH` set. This proves `-I` alone
     leaves that channel open, so the launcher's `unset` line is load-bearing.
     If nixpkgs ever stops honouring the variable, (b) fails, and the `unset`
     line and this control go together.

Each subprocess has a bounded timeout. The demo is this recipe's verbose
output, showing all four assertions passing for `agent-evidence`.

### Project standards shard (D9)

**`docs/standards/README.md`** is the index, at most 40 lines. It opens with
one paragraph saying this is Layer 2 of the three-layer contract, holds deltas
only, and that a shard loads when a touched path matches its globs. Then comes a
`| Shard | governs | Gist |` table with one row for `agent-helpers.md`. That
row governs `python/**`, `scripts/**`,
`home/common/agent-skills/scripts/**` and
`home/common/agent-skills/skills/*/scripts/**`.

Parent D6 also has the shard govern the lifecycle guard's file. #176 adds that
glob together with the file, because a glob that matches nothing is a
placeholder.

**`docs/standards/agent-helpers.md`** holds the five parent-D6 rules. Each is
written rule-first in at most two sentences, followed by one link to the parent
spec. Four rules are refined to fit this slice:

- **Rule 1** names where the command table lives (`lib/agent-tools.nix`). It
  says the rule binds new code and that each legacy script moves in its
  cluster's PR.
- **Rule 2** adds that a command's parser names its command (`prog`).
- **Rule 3** says a packaged sibling runs as
  `sys.executable [-I] -m agent_tools.<module>` through one shared helper
  (parent D16). It describes the helper's behaviour but not its name, because
  the first slice that needs the helper creates it.
- **Rule 4** names `agent_tools.canonical` and its composable hooks.

**Registration.** Project policy's `paths.standards` gains `docs/standards`
after the existing entry, so `resolve-project resolve` lists
`<root>/docs/standards`. The contract file is edited, and the result is checked
only through the resolver. The conformance suites copy the live contract into
their fixtures and create each declared directory, so the new entry must, and
will, exist as a real directory, not a symlink.

### Living documents (D10)

These are re-pointed in the same PR (the-bar, Moves keep their history; parent
D14):

- The codex-collaboration skill's `DIFF-REVIEW.md` names `agent-evidence.py`
  twice, and its `evals/evals.json` twice. All four become the command,
  `agent-evidence`.
- A comment in the workflow-skill-contracts test becomes `agent-evidence`.
- The moved tests' docstrings and the gate-bundle module's docstring are
  re-pointed.
- `CLAUDE.md` gains one short Architecture paragraph. It names
  `python/agent_tools`, the command table in `lib/agent-tools.nix`, the
  `-I -m` launchers, the recipes' `PYTHONPATH` and `docs/standards/`, and says
  the remaining flat scripts move in cluster by cluster. The half-migrated
  layout is a deliberate transition, and the-bar requires the architecture doc
  to name one.

Point-in-time records under `.claude/specs` and `.claude/plans` keep their
paths.

## Test seams

This slice uses two of the parent's three seams:

1. **Command contract and module interface, from source.** The existing suites
   run with the recipe's `PYTHONPATH`, and this slice adds the `-m` runs, the
   canonical test and the evidence pins (D7).
2. **Installed layout.** The new launcher test (D8).

Seam 3, the guard's registered hook, is untouched.

Three things are shown once during verification rather than by a committed
test:

- **The build-time imports check** (parent D10). Inject a failing import into
  a package module, watch `just build` fail in the imports-check phase, then
  revert. CI's `Nix Eval` evaluates but never builds, so this check runs only
  in a local `just build`.
- **The standards registration.** `resolve-project resolve` lists
  `<root>/docs/standards` among its standards paths.
- **The cost tool's process pool.** One real `just agent-costs` run finishes
  without the sequential-fallback notice. Under `-m`, the pool's spawned
  workers re-import the tool by module name, which they can only do through
  the recipe's `PYTHONPATH`.

## Out of scope

- The other slices:
  - #176 extracts the guard and adds the guard's glob to the shard.
  - #177, #178 and #179 move the remaining clusters, each deleting its own
    loaders, `sys.path` edits and `~/.agents/lib/python` entries.
  - The `artifact-budget` wrapper's replacement also belongs to its cluster.
- The copies of the digest and hook in the drift and matrix tools, and the
  `agent-model-matrix` and `agent-model-drift` recipes (#179).
- The delivery model's `canonical_digest` rename (delivery cluster).
- The parent-D16 sibling-run helper. None of the three moved tools runs another
  command, so the first slice whose modules do adds it.
- Splitting any oversized function, adding any third-party dependency,
  relocating test files, or switching the test recipe to discovery.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Move exactly `agent-costs`, `agent-gate-bundle`, `agent-evidence`; command table has one row (`agent-evidence`); drift/matrix copies wait for #179, the delivery rename for its cluster | Issue #175 slicing (written after the parent) governs; parent D5 strangler rollout | Also moving the model matrix to get the parent's second launcher — pulls #179's cluster into the foundation |
| D2 | Moves drop the shebang and exec bit, delete local copies, rename digest call sites, add `prog`; nothing else | Parent D14 rename pairing; parent D2/D8 (modules run only through `-m`) | Keep the shebang and exec bit — advertises a by-path run the shard forbids |
| D3 | `canonical` exports `telemetry_digest`, `reject_duplicate_keys`, `reject_nonfinite_literal`, with today's exact bodies and messages; each caller composes its hooks; call sites and tests use `telemetry_digest` directly | Parent D11 (per-caller composition, no parameterised loader); the-bar Name for intent; parent D15 | Import as `canonical_digest` alias — zero test edits, but keeps the name the parent retires because two formats share it |
| D4 | `lib/agent-tools.nix` takes `{ pkgs }` and returns only `{ launchers }`. Setuptools backend; name and version read from the pyproject. `pythonImportsCheck` derived by recursive walk of the package. The command table is a list of names, with the module derived by `-`→`_` | Parent D1, D2, D10, D13; `lib/agent-plugins.nix` precedent; the-bar DRY | Hand-listed import checks — a forgotten module escapes D10. Name→module attrset — restates the naming rule per row |
| D5 | Launcher `home.file` entries join via `lib.mkMerge` as a separate definition; each moved command pins `prog` to its command name | the-bar Fail loud; parent D15 (installed `--help`/usage unchanged) | `//` merge — a leftover entry silently wins. Default `prog` — installed usage becomes `agent_evidence.py` |
| D6 | One justfile variable; `PYTHONPATH` assigned (not prepended) only on `agent-workflow-tests`, `agent-costs`, `agent-gate-bundle`; no global export | Parent D8; #100 in flight on the justfile; the drift scheduling test's literal recipe assertion | Global `export PYTHONPATH` — leaks into `switch`/`build` and conflicts widely. Prepending — ambient values reach the suite |
| D7 | Test edits limited to locating code and the digest name; the drift test support re-points only its `agent-costs` load (its other loaders wait for #179). Add a `-m --help` run to the cost and gate suites, a golden canonical test, and two evidence composition pins | Regression floor "existing assertions pass as-is"; issue acceptance ("drive them as `python -m`"); the-bar Tests that can fail; parent seam 1 | In-process calls only — a lost `__main__` block passes every suite. Canonical format guarded only by self-recomputing assertions — drift passes silently |
| D8 | The installed test lives in `tests/` and runs only from `agent-installed-skill-tests`. It enumerates launchers by template match (anything naming `agent_tools` must be one) with an `agent-evidence` floor, then checks prog/name, a hostile `PYTHONPATH`+`NIX_PYTHONPATH`+`.pth`+cwd run, and two controls (non-isolated; `-I` with only `NIX_PYTHONPATH`) | Parent D9 seam 2, D13; #153 D8/D16 env handling; the-bar Tests that can fail | Emit the table as a JSON file into the home — a deployed artifact only a test reads. Pin the whole set — a second table |
| D9 | Shard index governs `python/**` and the three legacy script globs; the guard glob arrives with #176; rules refined (table home, `prog`, helper behaviour without a name); `docs/standards` appended to policy standards paths | Standards Layer-2 contract; parent D6; the-bar Production-grade (no placeholders) | Guard glob now — matches no file until #176. Test-directory globs — every test that locates package code changes alongside `python/**`, and skill-prose PRs would pay for the shard |
| D10 | Re-point skill prose, evals and comments to the `agent-evidence` command; add one CLAUDE.md Architecture paragraph naming the package, table, launchers and shard | the-bar Moves keep their history; parent D14; the-bar Production-grade (a transition is named in the architecture doc) | Leave CLAUDE.md silent — the architecture doc would not show the half-migrated layout |
| D11 | Refines parent D2/D13: each launcher unsets `NIX_PYTHONPATH`, `NIX_PYTHONPREFIX` and `NIX_PYTHONEXECUTABLE` before its unchanged `exec … -I -m` line | Grill finding in pinned nixpkgs, reproduced on the host interpreter: `sitecustomize` honours those variables under `-I` (site dirs with `.pth` execution, `sys.prefix`, `sys.executable`), and the env's `python3` wrapper does not set them; parent #151 fail-closed intent; the-bar Defense in depth | Rely on `-I` alone — a caller-supplied `NIX_PYTHONPATH` can still put a fake package first. `env -i` — strips `HOME`, `PATH` and tokens the helpers need |
| D12 | Refines D9: the registration also adds one `docs/standards` mkdir to the resolver suite's fixture root (`make_project_root`), beside its existing hard-coded standards mkdir; D9's claim that every fixture derives its directories holds only for the conformance roots | Planning probe: with the entry registered, `test_available_when_every_prerequisite_is_present` sees `knowledge.standards` blocked (`knowledge_path_missing`), because that root creates only the old directory; with the line, the resolver and conformance suites (186 tests) and the full workflow suite (1042 tests) pass; #100 is editing that suite | Derive every declared directory from the live contract, as conformance's `make_root` does — rewrites a helper #100 is changing, for no second caller |
| D13 | D5's `lib.mkMerge` wraps the existing literal set inline (`lib.mkMerge [ (localSkillFiles // {` … `}) agentToolFiles ]`), leaving the set's entries unindented; `nixfmt` is not re-run on `home/common/agent-skills/default.nix` | #100 edits the entries inside that set; `nixfmt` would re-indent all of them, about 110 lines; the repository does not enforce `nixfmt` (six tracked `.nix` files already fail `nixfmt --check`) | Re-run `nixfmt` — a whole-block conflict with #100 for layout only. An inline `imports` module holding the launchers — formats cleanly, but departs from D5's recorded mechanism |
