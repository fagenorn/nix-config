# One package for the agent workflow helpers

Design, 2026-09-24. Interactive `/design` session; every ledger row below was
either answered by the user or recommended and accepted by the user. No
tracker issue yet — `to-issues` slices this spec.

## Problem

The agent workflow helpers (`workflow-state`, `resolve-project`,
`conformance`, `artifact-budget`, `review-package`, the cost and drift tools,
and the rest) are some two dozen loose Python files. Nix links each one into
`~/.agents/bin` and drops the importable ones into `~/.agents/lib/python`.
Because they are not a package, they cannot import each other. As a result:

- **Every spec invents a loader.** Four mechanisms coexist: file-location
  specs with module version handshakes, `SourceFileLoader` helpers, `sys.path`
  insertion guarded by an origin check, and bare `sys.path` insertion. The
  #151 rule — never search `sys.path`, never fall back, refuse a foreign or
  missing module before any mutation — is re-implemented per module. It is
  already broken in `review-package`. Several suites build fake
  `$HOME/.agents/lib/python` trees just to exercise that machinery.
- **Knowledge is copied.** The D9 canonical digest is copied word for word
  into three tools, and the duplicate-key JSON hook into three more. A second,
  *different* canonical format in the delivery model shares the name
  `canonical_digest`, so the same value yields different digests depending on
  which function you call.
- **The security boundary is untestable source.** The Bash lifecycle guard is
  roughly 930 lines of Python pasted into a Nix string, with Nix values spliced
  into its text. It can be neither linted nor imported, and it is reachable
  only through a build.
- **It compounds.** In-flight #121 adds five more flat modules, and #152 one
  more, each needing its own route to its siblings.

The oversized functions (`workflow-state`'s 300–420-line policy and control
functions, `agent-costs`' 230–250-line scanners) are the visible symptom. They
are not this spec's target: splitting them is only affordable once modules can
import each other normally.

## Solution

Ship all agent-workflow Python as one package, `agent_tools`, with a
`pyproject.toml`, built by nixpkgs' Python builders into one interpreter
environment. Each `~/.agents/bin/<name>` becomes a generated launcher that runs
`python3 -I -m agent_tools.<module>` from that environment. Isolated mode makes
the Nix store copy the only importable one, so the #151 guarantee holds by
construction, and every loader, origin check, module handshake and the
`~/.agents/lib/python` tree are deleted. The shared D9 format gets one home. The
guard moves out of the Nix string into a real, self-contained file that reads
its Nix-owned values from a JSON file. A project standards shard makes the
package the only place new helper code can go.

It rolls out cluster by cluster: a foundation PR, then one move per group of
related modules, each taken when no in-flight branch touches it.

## Decisions

### External contract — unchanged (D15)

Every command keeps its name and its `~/.agents/bin/<name>` path. Skills call
helpers by bare name through the session `PATH`, the Claude allow surface names
`workflow-state` and `artifact-budget` bare and by path, and `context-map-lint`
is documented as a stable path for other projects. Each command keeps its
argv, stdin, stdout, stderr and exit codes; the existing suites are the
regression floor. The `~/.agents/share` data files (budget policy, platform
manifest) keep their paths — `task-brief` reads the policy there directly.

### The package (D1, D2, D3, D7, D13)

- **Members.** Every deployed helper (the agent-skills scripts plus
  `review-package`) and every repo-only agent tool (`agent-costs`,
  `agent-gate-bundle`, the `agent-model-drift` family, `context-map-lint`).
  Module names are the command names with underscores. Repo-only tools are
  modules without a launcher.
- **Shape.** A top-level `python/` directory holds `pyproject.toml` and the
  `agent_tools` package. The Nix build lives beside `lib/agent-plugins.nix` as
  `lib/agent-tools.nix`, and the agent-skills module imports it for the
  launchers.
- **Build.** `buildPythonPackage` from the `pyproject.toml`, wrapped into one
  `python3.withPackages` environment. The `pyproject.toml` declares no
  dependencies (the standard-library-only rule stands) and no
  `[project.scripts]`.
- **Command table.** The command-to-module mapping has exactly one home: the
  Nix build. It generates each launcher as
  `exec <env>/bin/python3 -I -m agent_tools.<module> "$@"`. Isolated mode
  also ignores the other `PYTHON*` variables; no helper reads any of them.

### What gets deleted (D12)

Each item is removed in the PR that migrates the module it serves: the lexical
file-location loaders, the `SourceFileLoader` helpers, every `sys.path` edit,
the origin checks, the module-load `*_INTERFACE_VERSION` constants and the
checks against them, the `~/.agents/lib/python` tree, the `artifact-budget`
shell wrapper (replaced by a launcher), and the tests that exist only to
exercise those. Versioned *data* formats — `schema_version`, manifest
`interface_version`, wire `kind` tags — are data contracts and stay.

### Canonical JSON (D11)

A shared `canonical` module owns the D9 format (sorted keys, compact
separators, ASCII-escaped, no trailing newline, `sha256:` prefix) and the
strict JSON load that rejects duplicate keys. The three D9 copies and the
three duplicate-key hooks import it. The delivery model keeps its own format
(non-ASCII preserved, NaN refused, trailing newline), because its digests are
already sealed into stored ledgers. It is renamed so that its name says it is
the delivery format, and two different formats no longer share one name.

### The lifecycle guard (D4)

The guard becomes a standalone Python file owned by the claude-code module.
It uses only the standard library and imports nothing from `agent_tools`, so no
helper refactor can change its behaviour. The values Nix owns — the
authorized-owner set, the integration-base map, and the `git`/`gh`/`jq` store
paths — reach it as a JSON file in the store, never as spliced source
text. The registered hook command stays one argument-free path. The existing
`--git-bin`/`--gh-bin`/`--jq-bin`/`--child-timeout-seconds` test overrides
stay, and the adversarial table stays green unchanged.

### Tests reach the source (D8)

The `just` recipes that run Python set `PYTHONPATH` to the `python/`
directory. Tests invoke commands as `[sys.executable, "-m",
"agent_tools.<module>", …]` and import modules normally. The recipes that run a
script by path (`agent-costs`, `agent-gate-bundle`, `agent-model-drift`,
`agent-model-matrix`) switch to `python3 -m`. Nothing in Python, tests
included, edits `sys.path`. A test file run outside a recipe fails with
`ImportError`. Test files stay where they are.

### Build-time check (D10)

The Nix build imports every module in the package (`pythonImportsCheck`), so a
broken import fails `just build`. It does not run the suite; that stays in
`just agent-workflow-tests` and the advisory CI job.

### Project standards shard (D6)

The repository gains `docs/standards/` — a README index and one
`agent-helpers.md` shard governing `python/**` and the guard file — and it is
added to the project policy's standards paths. The shard holds deltas only:

1. Agent-workflow Python lives in `agent_tools`. A new helper is a module there
   plus a command-table row, never a new top-level script.
2. A command module is a thin shell: parse argv, read input, call importable
   functions, write output, map errors to exit codes. Policy lives in functions
   that other modules and tests import.
3. No import machinery: no `sys.path` edits, no `importlib` loaders, no module
   version handshakes.
4. Digests use the shared D9 format or the delivery format, never a local
   copy.
5. Tests drive commands from source through `-m`. Only the installed-layout
   seam touches the built launchers.

### Rollout (D5, D14)

1. **Foundation PR:** the `pyproject.toml`, `lib/agent-tools.nix`, the launcher
   generation, the installed-layout test, the `canonical` module with the
   modules that copy D9 or the duplicate-key hook moved in (two of which have
   launchers, so seam 2 has real commands to run), and the standards shard.
   From this merge on, the shard routes all new helper code into the package.
2. **One PR per cluster** (e.g. delivery, conformance, resolver/platform,
   standalone commands, repo tools, review packaging, adoption), each taken
   when no in-flight branch touches its files. The guard extraction is its own
   PR and needs no package. The plan phase owns the order.
3. **Moves keep their history.** Every relocation goes through `git mv`. A
   cluster PR keeps its content edits small enough for git's rename pairing,
   so the review package shows renames plus edited hunks rather than whole-file
   additions. Living documents (`CLAUDE.md`, the agent-skills README, skill
   prose naming script paths) are re-pointed in the same PR. Point-in-time
   specs and plans keep their paths.

## Test seams

Three seams, each following an existing pattern; no implementer may add
others.

1. **Command contract from source.** The argv/stdin → stdout/exit contract of
   each command, run as `python -m agent_tools.<module>` with the recipe's
   `PYTHONPATH`. These are the existing suites; only how they locate the
   command changes.
2. **Installed layout.** A new test inside `just agent-installed-skill-tests`,
   which already builds first and passes the built `home-manager-files` as
   `AGENT_SKILLS_INSTALLED_HOME`. It runs every launcher under that tree's
   `.agents/bin`, proves each one reaches its module's own argument handling
   rather than an import failure, and proves that a hostile `PYTHONPATH` holding a fake
   `agent_tools` package is ignored. This replaces the fake-`HOME` loader tests
   spread across the suites.
3. **The guard's registered hook.** Unchanged: the built settings reach the
   test through `CLAUDE_SETTINGS_PATH`, and the test drives the registered
   command with its override flags.

## Out of scope

- Splitting `workflow-state`'s policy and control functions: #117 decides the
  engine's adoption shape and #125 re-platforms it. The post-migration module
  structure belongs to #117's decision scope.
- Splitting the other oversized functions (`agent-costs`, `agent-model-matrix`,
  `agent-evidence`, `review-package`): later slices, once their cluster lives
  in the package.
- `resolve-bindings`, which #100 deletes.
- Rewriting validators, and any third-party dependency (D3).
- The shell scripts (`task-brief`, `sdd-workspace`, `resolve-bindings`) and
  their inline Python heredocs.
- Relocating test files, or switching the test recipe from its explicit file
  list to discovery.
- Pinning rename detection in `review-package`, which relies on git's default
  `diff.renames`. #152 owns `review-package`. D14's rename-pairing constraint
  assumes that default holds.
- Unrelated Python: darktable, spotx, `anthropic-shim`.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Package members: every deployed helper plus the repo-only agent tools; the guard is handled by D4 | D9 digest copies live in the repo-only tools; user, round 1 | Deployed helpers only — leaves the duplication in place |
| D2 | `buildPythonPackage` + one `python3.withPackages` env; launchers run `python3 -I -m agent_tools.<module>` | #151 fail-closed import rule; the-bar Framework-first; Python stack shard (`pyproject.toml`) | `buildPythonApplication` wrappers — no isolation, `PYTHONPATH` shadows; flat dir on `PYTHONPATH` — same hole |
| D3 | Standard-library only; `pyproject.toml` declares no dependencies; a future one is a per-issue decision | the-bar YAGNI; behaviour-preserving scope | Adopt `jsonschema` now — changes error text and exit behaviour |
| D4 | Guard becomes a standalone, standard-library-only file owned by the claude-code module; Nix values arrive as a store JSON file; the hook stays one argument-free path with its existing test overrides | the-bar Defense in depth; guard test's registration assertions | Guard inside `agent_tools` — couples the security boundary to helper releases; Codex never runs it |
| D5 | Strangler rollout: foundation PR, then one PR per cluster taken when no in-flight branch touches it | #100, #121 and #152 edit the same files | Big-bang move — conflicts with three live branches; waiting — the pile grows |
| D6 | Add `docs/standards/` (index + `agent-helpers.md`) to the project's standards paths | Standards README Layer-2 contract | Python stack shard — Layer 1 may not name a repo; `CLAUDE.md` — not loaded into briefs by glob |
| D7 | Top-level `python/` holding `pyproject.toml` + `agent_tools`; Nix build in `lib/agent-tools.nix`; tests stay in place | `lib/agent-plugins.nix` precedent | Under `agent-skills/` — repo-only tools would look deployed |
| D8 | Recipes set `PYTHONPATH`; tests run `sys.executable -m agent_tools.<module>`; repo-tool recipes use `-m` | the-bar Root causes; Python stack shard (environment declared once) | A test-side `sys.path` helper — a loader again; always testing the built package — a build per test loop |
| D9 | Three seams: command contract from source, installed layout (with hostile `PYTHONPATH`), the guard's registered hook | `agent-installed-skill-tests` and `CLAUDE_SETTINGS_PATH` precedents; the-bar Tests that can fail | Keeping the fake-`HOME` loader tests — they test deleted machinery |
| D10 | `pythonImportsCheck` over every module; no suite in the build | `CLAUDE.md` names `just build` as the local verification | Running the suite in the build — every build becomes as slow as the suite |
| D11 | Shared `canonical` module owns D9 + strict JSON load; the delivery format stays in the delivery model under a distinguishing name | the-bar DRY (dedupe only what must change together); sealed ledger digests | One parametrized function — an option set nobody needs; merging formats — changes sealed digests |
| D12 | Delete loaders, `sys.path` edits, origin checks, module-load version handshakes, `~/.agents/lib/python` and the `artifact-budget` wrapper, each in its migrating PR; data-format versions stay | D2 makes cross-module version skew impossible | Keep handshakes as defense in depth — nothing can vary across them |
| D13 | Command-to-module table lives only in the Nix build; `pyproject.toml` declares no scripts | the-bar DRY | `[project.scripts]` — generates a second, non-isolated command set |
| D14 | Moves via `git mv`, edits small enough for rename pairing, living docs re-pointed in the same PR, point-in-time records untouched | the-bar Moves keep their history; review-package member budget (#122 D40) | Move and rewrite together — whole-file diffs overflow review packages |
| D15 | Command names, `~/.agents/bin` paths, CLI contracts and `~/.agents/share` data paths unchanged | Session `PATH` bare-name calls; the Claude allow surface; `context-map-lint`'s stable-path promise | Renaming commands while moving — breaks skills, allow rules and other repos |
