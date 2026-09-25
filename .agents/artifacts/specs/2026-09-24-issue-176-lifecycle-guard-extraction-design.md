# Lifecycle guard extraction — issue 176

Design, 2026-09-24. Autonomous (`from-issue --auto`): every row below was
self-answered against the parent spec, `CLAUDE.md` and the standards. The
parent is `.claude/specs/2026-09-24-agent-tools-package-design.md`. Its rows
**parent D4** (standalone guard, store JSON, argument-free hook), **parent D9**
(three seams; seam 3 is the registered hook), **parent D10** (build-time check),
**parent D15** and **parent D16** (nothing locates code from `__file__`) bind
this spec. Parent D5 makes the extraction its own PR, one that needs no package.

## Problem

The Claude Code `PreToolUse` Bash lifecycle guard is the security boundary for
push, PR creation, branch deletion and merge. Its roughly 930 lines of Python
live inside a Nix `''` string in `home/common/claude-code/default.nix`, and six
Nix expressions are spliced into that text: the shebang interpreter, the
`git`/`gh`/`jq` store paths, the authorized-owner set and the integration-base
map. As a result:

- A linter cannot parse the source, because an interpolation such as
  `frozenset({${…}})` is not Python. The source is reachable only through a
  build.
- Adding an owner rewrites the guard's own source text. A reviewer cannot tell
  a configuration change from a code change by looking at which store paths
  moved.
- Syntax and import errors surface only at run time. A hook that exits with
  anything other than 2 is *non-blocking* in Claude Code, and the `__main__`
  catch-all cannot cover import time. Such a guard therefore fails open, and
  the allow list admits the four guarded verbs unexamined.

## Solution

Move the Python verbatim (dedented) into `home/common/claude-code/lifecycle_guard.py`.
That file uses only the standard library and imports nothing from
`agent_tools`. The only edits are the ones needed to read a policy. The Nix
module keeps owning the Nix values and writes them to a store JSON policy file.
The registered hook stays `${lifecycleGuard}/bin/claude-bash-lifecycle-guard`,
but that file becomes a short store wrapper. The wrapper clears the
`NIX_PYTHON*` variables and runs
`python3 -I <source store path> --policy <policy store path> "$@"`. The guard
loads and validates the policy on every invocation, and any policy defect
blocks. The wrapper's build runs it once on a harmless payload, so a source or
policy that cannot load fails `just build` instead of failing open at run time.

## Decisions

### Files

| File | Change |
|---|---|
| `home/common/claude-code/lifecycle_guard.py` | **New**, mode 0644 (not executable). The guard source. |
| `home/common/claude-code/default.nix` | The guard's Python is removed. The file gains `lifecycleGuardPolicy` and turns `lifecycleGuard` into the wrapper (below). `authorizedOwners`, `integrationBases`, their comments and the hook registration stay. |
| `tests/test_claude_permission_guard.py` | Gains one case (per D9). No existing line changes. |
| `CLAUDE.md` | Gains one sentence (per D10). |
| `docs/standards/README.md`, `docs/standards/agent-helpers.md` | Only if they exist on `main` at this PR's last sync before merge (per D11). |

The new `.py` file is not a Nix module. `scanPaths` goes only one level into
`home/common/`, so nothing else picks it up. A flake sees only
git-tracked files, so the file must be `git add`ed before the first
`just build`.

### The policy file (per D3)

`lifecycleGuardPolicy = pkgs.writeText "claude-bash-lifecycle-guard-policy.json" (builtins.toJSON { … })`
holds exactly five keys. `builtins.toJSON` sorts them and writes compact JSON:

```json
{"authorized_owners":["fagenorn","elevenyellow"],
 "gh_bin":"/nix/store/…-gh-…/bin/gh",
 "git_bin":"/nix/store/…-git-…/bin/git",
 "integration_bases":{"elevenyellow/nodocom":"dev","fagenorn/arcwave":"dev"},
 "jq_bin":"/nix/store/…-jq-…/bin/jq"}
```

The keys map to their Nix sources as follows:

- `authorized_owners` comes from `authorizedOwners`.
- `integration_bases` comes from `integrationBases`.
- `git_bin`, `gh_bin` and `jq_bin` are `"${pkgs.git}/bin/git"`,
  `"${pkgs.gh}/bin/gh"` and `"${pkgs.jq}/bin/jq"`, the values that are spliced
  into the source today.

Their string context keeps `git`, `gh` and `jq` in the closure. The file has no
version field. The guard accepts a document only when all of these hold:

- It is a JSON object whose key set is exactly those five keys.
- `authorized_owners` is a list of non-empty strings. A bare string must be
  refused, because `in` would then test for a substring.
- `integration_bases` is an object whose keys and values are non-empty strings.
- Each `*_bin` is a string and `os.path.isabs` holds for it.

### The registered executable (per D1, D2)

`lifecycleGuard` stays `pkgs.writeTextFile` with the same
`name = "claude-bash-lifecycle-guard"`, `executable = true` and
`destination = "/bin/claude-bash-lifecycle-guard"`. Its `text` becomes:

```sh
#!${pkgs.runtimeShell} -p
unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
exec ${pkgs.python3}/bin/python3 -I ${./lifecycle_guard.py} --policy ${lifecycleGuardPolicy} "$@"
```

`${./lifecycle_guard.py}` gives the source its own store path, which is
addressed only by the file's content. An owner change therefore produces a new
policy path and a new wrapper, but never a new source path. The path must be
interpolated. `builtins.toString ./lifecycle_guard.py` would instead name the
file inside the whole flake's `-source` store path, which moves with every
repository edit. Both behaviours were verified with Nix 2.31.5.

Arguments flow like this:

- The hook passes no arguments, so the guard sees `--policy P`.
- The suite passes override flags, so the guard sees
  `--policy P --gh-bin <fake> …`.

The `exec` is load-bearing. Without it, the hook's timeout kill would reach
bash and orphan the Python process.

The `-p` is load-bearing too (per D15). A non-interactive bash sources
`$BASH_ENV` and imports exported functions, and a function can override
`exec` or `unset`, so without it an inherited environment could end the wrapper
with exit 0 before Python starts. Privileged mode skips `BASH_ENV` and `ENV`,
imports no functions, and ignores `SHELLOPTS` and `BASHOPTS`. The base hook's
Python shebang ran no shell, so the flag keeps the wrapper from widening the
boundary.

The hook registration expression is untouched. The generated entry is still
matcher `Bash` with one `type = "command"` hook, `timeout = 30`, no `args`, and
a `command` equal to that one absolute path. Only the store hash inside the
command changes.

**Honest limit.** If the wrapper's `exec` itself fails (exit 126 or 127), the
hook fails open, exactly as a missing shebang interpreter does today. Store
references keep both targets in the closure, so this can happen only if the
store is damaged.

### Extracting the source (per D12)

The new file starts as the text of today's `''` string with 6 columns of
indentation removed. That matches the guard text Nix builds today everywhere
except the six interpolation sites, which E1 and E2 remove. The only edits to
it are these:

- **E1.** Delete the shebang line. Add a module docstring of at most 6 lines
  saying that the store wrapper runs this file under `python3 -I` with
  `--policy`, and that the file must stay standard-library-only (parent D4).
- **E2.** Delete the five spliced constants: `DEFAULT_GIT_BIN`,
  `DEFAULT_GH_BIN`, `DEFAULT_JQ_BIN`, `AUTHORIZED_OWNERS` and
  `INTEGRATION_BASES`. Add `POLICY_KEYS`, the frozenset of the five key names.
- **E3.** Add a `Policy` class written like `Context`. Its attributes are
  `authorized_owners` (a frozenset), `integration_bases` (a dict), `git_bin`,
  `gh_bin` and `jq_bin`. Add `load_policy(path)`, which returns
  `(Policy, None)` or `(None, reason)` in the style of the file's `*_problem`
  helpers. It turns `OSError`, `UnicodeDecodeError` and `json.JSONDecodeError`
  into a reason that names the path, and it applies the shape rules above.
- **E4.** `Context(args, policy, cwd)` also stores `authorized_owners` and
  `integration_bases` from the policy.
- **E5.** `ownership_problem(repository, authorized_owners)` and
  `authorized_bases(repository, base_branch, integration_bases)` take the
  collections as explicit parameters. Their callers pass the `context.`
  attributes, and `validate_merge`'s own integration-base lookup reads
  `context.integration_bases`. No module-level mutable state is introduced.
- **E6.** In `main()`, as set out in D4 and D5:
  - The parser is `argparse.ArgumentParser(prog="claude-bash-lifecycle-guard")`,
    so usage text keeps today's program name.
  - `--policy` is added and required.
  - `--git-bin`, `--gh-bin` and `--jq-bin` default to `None`.
  - `--child-timeout-seconds` keeps its default of 5.
  - After the existing hook-input checks, and before `guarded_operations`,
    `main()` loads the policy. On failure it returns
    `block(f"invalid policy: {reason}")`. On success it fills each bin that is
    still `None` from the policy and builds `Context` with the policy.

Nothing else changes. That covers comments, grammar, the order of checks,
messages, the `__main__` catch-all, and every line outside E1–E6.

### Behaviour on policy defects (per D4)

| Condition | Result |
|---|---|
| `--policy` missing (the source run by hand) | argparse error, exit 2 |
| Policy unreadable, not UTF-8, malformed JSON, or wrong shape | `lifecycle guard: invalid policy: <reason>`, exit 2, for **every** valid Bash payload, guarded or not |
| Malformed hook input | Unchanged: `invalid hook input:` wins, because input is checked first |
| Any other exception inside `main()` | Unchanged: the catch-all prints `unexpected failure:` and exits 2 |

The policy is read inside `main()`, never at import time. An import-time
failure would escape the catch-all and exit 1, which does not block.

### Build-time check (per D7)

The wrapper's `writeTextFile` gains a `checkPhase`. `writeTextFile` evaluates
it after writing and `chmod +x`-ing `$target`. It pipes
`{"tool_name":"Bash","tool_input":{"command":"true"}}` into `"$target"` and
fails the build unless the exit status is 0. Because the policy loads eagerly,
this one run proves several things:

- The source compiles.
- Its imports resolve under `-I`.
- `--policy` reaches the guard.
- The generated policy passes validation.
- An unguarded command is allowed.

It needs no git, network or cwd, because `true` yields no guarded operation.
CI's `Nix Eval` only evaluates, so this check runs under the local
`just build`, which `CLAUDE.md` names as the verification step.

### Living documents (per D10, D11)

**`CLAUDE.md`.** In the "Claude Code is declaratively managed" bullet, add one
sentence after "…hands four lifecycle verbs to a fail-closed `PreToolUse`
hook." It names three things:

- **The source.** The hook's Python is `home/common/claude-code/lifecycle_guard.py`,
  which is standard-library-only and imports nothing from `agent_tools`.
- **How it runs.** The registered command is a store wrapper. The wrapper clears
  `NIX_PYTHON*` and runs the source under `python3 -I`, with `--policy`
  naming a store JSON file of the Nix-owned values (`authorizedOwners`,
  `integrationBases` and the `git`/`gh`/`jq` paths).
- **The consequences.** An owner change never touches the source, `just build`
  fails if the source or policy cannot load, and an unreadable or malformed
  policy blocks every Bash call.

The existing clause naming `authorizedOwners` in `default.nix` as the
authoritative roster stays true and is kept.

**Standards shard.** If `docs/standards/` from #175 is on `main` at this PR's
last sync before merge, then:

- Append `home/common/claude-code/lifecycle_guard.py` to the `agent-helpers.md`
  row's `governs` cell in `docs/standards/README.md`.
- Add one sentence to `agent-helpers.md` stating that the lifecycle guard stays
  standalone and standard-library-only (parent D4) and that, of the shard's
  rules, only rule 3 binds it.

If #175 has not landed by then, this PR leaves `docs/` alone. Its PR body then
states that the guard glob passes back to #175, so that whichever of the two
merges second adds it.

## Test seams

There is one seam: **seam 3, the guard's registered hook** (parent D9). The
built settings reach `tests/test_claude_permission_guard.py` through
`CLAUDE_SETTINGS_PATH`, and the suite drives the registered command with its
override flags. This spec adds no seam.

- **Regression floor.** Every existing case passes with no change to any
  existing line of the test file. The suite already exercises every policy
  value through the built hook:
  - the owner set: `fagenorn` and `elevenyellow` repositories pass, and other
    owners get `outside standing authorization`;
  - the integration base: `elevenyellow/nodocom` targets `dev`;
  - the default `git` path: no case passes `--git-bin`;
  - the default `jq` path: acceptance cases do not pass `--jq-bin`.

  A guard that ignored or misread its policy would therefore turn those cases
  red.
- **New case (per D9).** `test_hostile_interpreter_environment_is_ignored` is
  a single case. It builds one fixture directory holding a `json/__init__.py`
  that calls `os._exit(0)`, a `.pth` file whose line is
  `import os; os._exit(0)`, and a `bash_env` file whose line is `exit 0`. It
  runs `invoke_command("git branch -d -f topic", env=…)` with `BASH_ENV`
  naming that file and `PYTHONPATH` and `NIX_PYTHONPATH` naming the directory,
  and asserts exit 2 with `lifecycle guard: unsafe branch deletion:` in stderr.
  At base the case is red, because the shadowed `json` forces exit 0.
  Dropping `-I`, the `unset` or `-p` turns it red again. Verified on 3.13.12:
  a `NIX_PYTHONPATH` `.pth` forces exit 0 even under `-I`. Verified on bash
  5.3: a `BASH_ENV` file forces exit 0 unless bash runs with `-p` (per D15).
- **Run.** `just show-claude-settings > "$TMPDIR/claude-settings.json" && CLAUDE_SETTINGS_PATH="$TMPDIR/claude-settings.json" python3 tests/test_claude_permission_guard.py -v`

Demonstrations are verification only and are not committed. Before the first
edit, capture the base settings and the base built guard text.

| Claim | Demonstration |
|---|---|
| Acceptance 1: the source is its own file | `lifecycle_guard.py` exists, and `grep -nE '^\s*(import\|from\|def\|class) ' home/common/claude-code/default.nix` prints nothing. Today it prints 33 lines, all inside the guard. |
| Acceptance 2: no interpolation | `grep -nE '\$\{\|/nix/store\|fagenorn\|elevenyellow\|nodocom\|arcwave' home/common/claude-code/lifecycle_guard.py` prints nothing. |
| Acceptance 2: an owner change touches only the policy | Temporarily add an owner, rerun `just show-claude-settings`, and `cat` both wrappers. The source store path is identical, the policy path differs, and diffing the two policies shows only the added owner. Revert. |
| Extraction fidelity | `diff -u <base built guard> home/common/claude-code/lifecycle_guard.py` shows only E1–E6 hunks. |
| Hook shape unchanged | For base and new, `jq -S '.hooks \| walk(if type=="string" then gsub("/nix/store/[0-9a-z]{32}-";"/nix/store/HASH-") else . end)'` gives identical output. |
| Byte-compiles | `PYTHONPYCACHEPREFIX="$TMPDIR/pyc" python3 -m py_compile home/common/claude-code/lifecycle_guard.py` exits 0. |
| Lints | `devenv -O packages:pkgs "ruff" shell -- ruff check --isolated home/common/claude-code/lifecycle_guard.py` prints `All checks passed!`. Today's text, with its constants stubbed, already passes ruff 0.14.6's default rules. |
| The build check can fail | Temporarily set `authorizedOwners` to a string. `just build` fails in the wrapper's `checkPhase` with `invalid policy`. Revert. |

## Out of scope

- Any change to the guard's grammar, validation, messages or order of checks.
- Changing the owner roster or the integration bases.
- The `agent_tools` package, its launchers and its recipes (#175, #177–#179).
- Codex, which never runs this hook.
- The allow list and `defaultMode`.
- Relocating the test file, or adding a `just` recipe for the guard suite.
- Adding a linter to the build, CI or `justfile`.
- Rejecting duplicate keys in the policy. Its only producer is
  `builtins.toJSON`.
- Renaming the hook, the derivation or the `--*-bin` flags.
- Creating `docs/standards/`, which belongs to #175.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The hook's path is a store wrapper that execs the interpreter on the source's own store path (an interpolated path, never `builtins.toString`) with `--policy <store JSON>` ahead of `"$@"` | parent D4; parent D16 and #175 shard rule 3 (nothing located from `__file__`); acceptance 2; the suite's registration assertions | Policy found beside the script via `__file__`/`argv[0]`: a path-derived lookup, and it forces one derivation, so the source path moves with owners. An env var: ambient, and inherited by every git/gh/jq child. A Nix-generated Python stub: Nix values in Python text again |
| D2 | The wrapper unsets `NIX_PYTHONPATH`/`NIX_PYTHONPREFIX`/`NIX_PYTHONEXECUTABLE` and runs `python3 -I` | Verified: without `-I`, a script's directory is `sys.path[0]`, which for a store file is `/nix/store`; a `NIX_PYTHONPATH` `.pth` forces exit 0 under `-I`; #175 launcher precedent; parent D2 | Keep today's bare interpreter: it would pass the suite, but `PYTHONPATH`, user-site and `.pth` code could force exit 0 on a security boundary |
| D3 | Flat policy with exactly five keys (`authorized_owners`, `integration_bases`, `git_bin`, `gh_bin`, `jq_bin`), no version field, strict type checks | The wrapper pins both store paths, so they cannot skew (parent D12's reasoning); a bare string owner turns `in` into a substring test | A version tag or handshake guards against skew that cannot happen. A nested `tools` object helps no reader |
| D4 | Load the policy on every invocation inside `main()`, after hook-input checks and before judging; any defect blocks every Bash call with `invalid policy:` | `CLAUDE.md` "every uncertainty blocks"; 2026-08-17 plan: no exception may exit non-blocking; stdin drained before refusal | Load at import time: escapes the catch-all, and exit 1 does not block. Load lazily for guarded verbs only: hides a broken policy until the first push, and D7 could not prove it |
| D5 | Override flags default to `None` and fall back to the policy; `--policy` is required plumbing that the suite never passes; `prog` stays `claude-bash-lifecycle-guard`; owners and bases travel on `Context` as explicit parameters | parent D4 (the existing overrides stay); #175 shard rule 2 `prog` precedent; the-bar Maintainability | Parse `--policy` first to use policy values as argparse defaults: a two-phase parse for no gain. Module globals set via `global`: hidden mutable state |
| D6 | Keep `authorizedOwners`/`integrationBases` and their comments in `default.nix`; the policy is derived from them | `CLAUDE.md` names `default.nix` the authoritative roster; the issue: Nix owns these values | A checked-in JSON or Python roster file: moves the documented home and adds a file for no consumer |
| D7 | The wrapper's `checkPhase` runs it on a harmless Bash payload and requires exit 0 | parent D10 (a build-time import check); the non-blocking exit-1 hazard; `CLAUDE.md`: `just build` is the verification step | `py_compile` only: misses import-time and policy errors. Running the suite in the build: rejected by parent D10 |
| D8 | Lint is verification-only, using `ruff check --isolated` (default rules) from an ad-hoc devenv | No linter configured in the repo; standards README "lint commands nowhere"; the-bar YAGNI | `writers.writePython3Bin` with flake8: the source goes back through a Nix string, and flake8's 79-column default would force reformatting |
| D9 | Add exactly one seam-3 case, a hostile interpreter environment, and change no existing line; add no `--policy` case | parent D9 seam 3; the-bar Tests that can fail; #175's hostile-`PYTHONPATH` launcher test | No new case: D2 would go untested. A `--policy` case would turn plumbing into a test override, and existing cases already exercise every policy value |
| D10 | One `CLAUDE.md` sentence naming the source file, the wrapper, `-I` and the policy | the-bar Moves keep their history (re-point living docs in the same PR) | Rewriting the guard paragraph: churn with no new fact |
| D11 | If #175's `docs/standards/` is on `main` at the last sync before merge, add the guard's glob and a sentence saying only rule 3 binds it; otherwise leave `docs/` alone and hand the glob back to #175 in the PR body | parent D6; #175 spec ("#176 adds the guard's glob") | Governing the guard by all five rules: rules 1, 2 and 4 contradict parent D4. Creating `docs/standards/` here: it is #175's |
| D12 | The new file is the base's built guard text, dedented, plus only E1–E6; it is not executable; history is followed with `git blame -w -C -C`, because there is no file to `git mv` | the-bar Moves keep their history; the issue's "behaviour identical" floor | Reformatting or tidying during the move: hides the named edits from review |
| D13 | The lint demonstration runs `ruff check --isolated --select E4,E7,E9,F` from a scratch `devenv.nix` under `$TMPDIR` (refines D8 and the Lints row) | Planning probe: devenv 2.0.2's `-O packages:pkgs "ruff"` fails to evaluate (`undefined variable 'config'`); its ruff 0.16.6 widened the defaults and flags seven findings (I001, ISC004, FURB188, BLE001) that are all in the base's built text, while the flake pins 0.14.6; D12 forbids tidying | Bare default rules: a verdict that moves with the ruff version and is red at base. Fixing the findings: rewrites moved text, against D12 |
| D14 | The shard sentence scopes rule 3 to its ban on import machinery and `__file__` lookups, and states that the guard runs `git`/`gh`/`jq` by the absolute paths its policy names rather than by name on `PATH` (refines D11) | Live rule 3 (#175) also says an executable outside the package "runs by its command name on `PATH`"; parent D4 (the tool paths reach the guard as policy); the-bar Defense in depth | "Only rule 3 binds it" unqualified: its `PATH` clause contradicts the pinned tool paths. Resolving the tools through `PATH`: a hostile `PATH` could stand in for `git` or `gh` on a security boundary |
| D15 | The wrapper's shebang runs bash with `-p`, and the hostile-environment case also plants `BASH_ENV` (extends D2 and D9) | Phase-5 standards review: a non-interactive bash sources `BASH_ENV` and imports exported functions, either of which can exit 0 before Python starts; reproduced on bash 5.3 (exit 0 without `-p`, 2 with it); D2's own threat model; the base hook's Python shebang ran no shell | `env -i` or `env -u` in the shebang: shebang argument splitting differs between darwin and Linux, and `env -i` drops the variables the guard's children need. An unprotected bash: the wrapper would open a fail-open path the base did not have |
| D16 | D9 stands: the policy shape checks are demonstrated (Task 1's defect table, Task 3's failing build) rather than regression-tested, and no `--policy` case is committed | Phase-5 review discussion; D5 (`--policy` is plumbing, not a test override); the policy's only producer is `builtins.toJSON` over typed Nix values, and the build's `checkPhase` loads every generated policy | Committing the defect table as seam-3 cases through a repeated `--policy`: turns plumbing into a test override and ties the suite to argparse keeping the last repeated value, which D5 and D9 rejected |
