# Task 5: Repository policy checks — path classification, ignore sentinel, command indirection

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`

**Interfaces:**
- Consumes from Task 2: `Check`, `Outcome`, `Context` (`context.root`, `context.contract`), `REGISTRY`, `REPAIRS`, `bound_facts`.
- Produces three evaluators — `check_paths_classified`, `check_ignore_runtime_sentinel`, `check_commands_no_shell_indirection` — plus `LIFECYCLE_CLASSES`, `CANONICAL_AGENTS_PREFIXES`, `OVERBROAD_IGNORE_PATTERNS`, `RUNTIME_IGNORE_PATTERNS`, `SHELL_ARGV0`, `SHELL_METACHARACTERS`, and three registry entries with three repairs.

**Invariants:**
- All three are pure filesystem and contract reads: no process, no write, no network.
- Path classification is a **closed** four-class rule (#72). A path matching none of the four is a finding, never a new implicit class.
- The ignore check reads the tracked ignore files only. `.git/info/exclude` is machine-local and is deliberately not consulted — a machine-local rule cannot be the repository's classification.
- `verification.commands.no_shell_indirection` validates command *policy*; the resolver already validated command *shape*. Neither re-implements the other.
- Facts carry repository-relative paths and command ids, never absolute paths and never a command's full argv. All of them go through `bound_facts` (D30): a path and an authored command id are both unbounded strings, and an unbounded one would make the report fail `validate_report`.

## The four closed lifecycle classes (#72)

```python
LIFECYCLE_CLASSES = ("canonical_tracked", "tracked_projection",
                     "ignored_runtime", "allowlisted_bookkeeping")
CANONICAL_AGENTS_PREFIXES = (
    "project.json", "instructions/", "skills/", "adapters/",
    "extensions/", "knowledge/", "artifacts/",
)
RUNTIME_PREFIX = "runtime/"
BOOKKEEPING_ALLOWLIST = ()   # closed and empty in v1: nothing outside .agents/
                             # is admitted as non-behavioral bookkeeping yet.
```

## `repository.paths.classified`

**Subject set.** Every *file* under `<root>/.agents/` (recursive `rglob("*")` filtered to `is_file()`, skipping any path with a `.git` component), expressed relative to `<root>/.agents/`; plus every declared projection `target`, expressed relative to `<root>`.

**Classification.**
- A `.agents/`-relative path is `canonical_tracked` when it equals `project.json` or starts with one of the remaining `CANONICAL_AGENTS_PREFIXES` directory prefixes. Under `artifacts/` require the second segment to be one of `specs`, `plans`, `evidence`, `handoffs`, `notes`; any other `artifacts/<x>/` segment is unclassified.
- A `.agents/`-relative path starting with `runtime/` is `ignored_runtime`.
- A repository-relative path equal to a declared projection `target` is `tracked_projection`.
- A path equal to a member of `BOOKKEEPING_ALLOWLIST` is `allowlisted_bookkeeping`.
- Anything else is unclassified.

**The finding.** No unclassified path → `Outcome("passed")`. Otherwise `Outcome("failed", "unclassified_path", "lifecycle.path.classify", {"paths": bound_facts(offending), "count": len(offending)})`, with offending paths reported repository-relative (`.agents/<x>` for the first set) so a reader can open them.

## `repository.ignore.runtime_sentinel`

```python
RUNTIME_IGNORE_PATTERNS = (".agents/runtime/", ".agents/runtime",
                           "/.agents/runtime/", "/.agents/runtime")
OVERBROAD_IGNORE_PATTERNS = (".agents/*", "/.agents/*", ".claude/*", "/.claude/*")
```

1. Read `<root>/.gitignore` as UTF-8 if it exists; strip each line, drop empties and lines starting with `#`. An unreadable or absent file yields an empty rule list, never an exception.
2. **Overbroad first** — an overbroad ignore conceals authored truth, so it outranks a missing sentinel. Any rule in `OVERBROAD_IGNORE_PATTERNS` → `Outcome("failed", "overbroad_ignore", "lifecycle.ignore.repair", {"rules": bound_facts(offending), "count": len(offending)})`.
3. **Then coverage.** `.agents/runtime/` is covered when either some root rule is in `RUNTIME_IGNORE_PATTERNS`, or `<root>/.agents/runtime/.gitignore` exists and its bytes are exactly `b"*\n"` (#72's sentinel). Neither → `Outcome("failed", "runtime_ignore_missing", "lifecycle.ignore.repair", {"root_gitignore": <bool: the file exists>, "sentinel": <bool: the sentinel file exists>})`.
4. Otherwise `Outcome("passed")`.

Accepting either spelling is deliberate: this repository covers the subtree from the root `.gitignore`, and #72's committed `.agents/runtime/.gitignore` sentinel is the other legitimate home. Demanding only one would fail a conformant repository.

## `verification.commands.no_shell_indirection`

```python
SHELL_ARGV0 = ("sh", "bash", "zsh", "dash", "ksh")
SHELL_METACHARACTERS = (";", "|", "&&", "`", "$(")
```

For each `command_id, entry` in `sorted(context.contract["bindings"]["commands"].items())`, the entry is offending when either `Path(entry["argv"][0]).name` is in `SHELL_ARGV0` **and** `"-c"` appears in `entry["argv"][1:]`, or any element of `entry["argv"]` contains any member of `SHELL_METACHARACTERS`.

Read the *authored* contract, not the normalized bindings: normalization rewrites `cwd` but leaves `argv` alone, and reading the authored form keeps the reported ids and the authored text in one correspondence.

No offender → `Outcome("passed")`. Otherwise `Outcome("failed", "shell_indirection", "contract.commands.destructure", {"commands": bound_facts(offending_ids), "count": len(offending_ids)})`.

## Registry entries this task adds

Append after `repository.projection.fresh` — all three depend on `repository.contract.valid`, which precedes them in `REGISTRY`. All three are `required`, `network = False`.

| Id | Domain | Subject kind | `findings`: reason code → repair id | Repair module, class, operation |
|---|---|---|---|---|
| `repository.paths.classified` | repository | path | `unclassified_path` → `lifecycle.path.classify` | conformance, `user_action`, null |
| `repository.ignore.runtime_sentinel` | repository | path | `runtime_ignore_missing` → `lifecycle.ignore.repair`; `overbroad_ignore` → `lifecycle.ignore.repair` | conformance, `worktree`, null |
| `verification.commands.no_shell_indirection` | verification | command | `shell_indirection` → `contract.commands.destructure` | resolve-project, `user_action`, null |

`lifecycle.ignore.repair` is `worktree` — editing `.gitignore` changes the working tree — but carries `operation: None`, because no engine subcommand performs it (D25).

- [ ] **Step 1: Write the failing test**

Append three classes to `home/common/agent-skills/tests/test_conformance.py`. Each inherits `ReportAssertions`, builds its root with `make_root(tmp)` inside `with fixture() as tmp:`, reads the report through Task 1's `doctor(self, root)` helper, and calls `assert_validates(report)` on every failing case. Homogeneous rows go in one method over `self.subTest`.

**`PathClassificationTest`** — the check is `repository.paths.classified`; on a finding assert `reason_code == "unclassified_path"` and `repair_id == "lifecycle.path.classify"`.

| Case | Fixture mutation | Expected |
|---|---|---|
| conformant tree | none | `passed`, `facts == {}` |
| unclassified path | write `.agents/scratchpad/notes.txt` | `failed`, `facts == {"paths": [".agents/scratchpad/notes.txt"], "count": 1}` |
| runtime state | write `.agents/runtime/state/run-1/state.json` | `passed` — `runtime/` is a class, not an escape |
| unadmitted artifacts dir | write `.agents/artifacts/scratch/x.md` | `failed`, `facts["paths"] == [".agents/artifacts/scratch/x.md"]` |
| cap and bound (D30) | 12 files under `.agents/scratchpad/` + six path segments of 40 `d`s each | `len(facts["paths"]) == 8`, `facts["count"] == 12`, and every emitted path is exactly 200 characters |

The last row is the one that fails without the bounding helper: a repository-relative path has no length ceiling, so an unbounded fact makes the engine's own report fail `validate_report` and turn a repository finding into `resolver_failure`.

**`IgnoreSentinelTest`** — the check is `repository.ignore.runtime_sentinel`. A shared `build(tmp, gitignore, sentinel=False)` helper writes `<root>/.gitignore` and, when asked, `<root>/.agents/runtime/.gitignore` holding exactly `b"*\n"`.

| Case | `.gitignore` | Sentinel | Expected |
|---|---|---|---|
| root rule | `.agents/runtime/` | no | `passed` |
| committed sentinel | `result` | yes | `passed` |
| no coverage | `result` | no | `failed` / `runtime_ignore_missing` / `lifecycle.ignore.repair`, and that repair's `safety_class` is `worktree` |
| overbroad outranks | `.agents/runtime/` then `.agents/*` | no | `failed` / `overbroad_ignore`, `facts["rules"] == [".agents/*"]` |

**`ShellIndirectionTest`** — the check is `verification.commands.no_shell_indirection`. A `with_argv(root, command_id, argv)` helper rewrites one command's `argv` in `<root>/.agents/project.json`.

| Case | `nix-build` argv | Expected |
|---|---|---|
| plain argv | unchanged | `passed`, `domain == "verification"` |
| shell `-c` | `["bash", "-c", "just build"]` | `failed` / `shell_indirection` / `contract.commands.destructure`, `facts["commands"] == ["nix-build"]` |
| metacharacter | `["just", "build && just switch"]` | same finding |

One further case runs `run("run", "--purpose", purpose, "--repo-root", str(root))` for `ci` and `fleet` and asserts the check id is present for the first and absent for the second — the purpose table's own claim, proved rather than assumed.

`make_root` must write a `.gitignore` covering `.agents/runtime/` from this task on, so the clean-root cases in every earlier class keep passing.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py`
Expected: the three new classes fail with `KeyError` on each of the three ids; every earlier class still passes.

- [ ] **Step 3: Write the minimal implementation**

```python
def check_paths_classified(context: "Context") -> "Outcome":
    """Contract: failed when a file under .agents/ or a declared projection
    target matches none of the four closed lifecycle classes (#72)."""


def check_ignore_runtime_sentinel(context: "Context") -> "Outcome":
    """Contract: failed for a broad .agents/* or .claude/* ignore rule, or when
    .agents/runtime/ is covered by neither a root rule nor the committed
    sentinel; the overbroad finding outranks the missing one."""


def check_commands_no_shell_indirection(context: "Context") -> "Outcome":
    """Contract: failed when a declared command's argv[0] is a shell invoked
    with -c, or any argv element carries a shell metacharacter."""
```

Add the three registry entries and three repairs.

- [ ] **Step 4: Verify**

```bash
python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py
just agent-workflow-tests
python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root . \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); b={c["id"]:c["status"] for c in r["checks"]}; print(b["repository.paths.classified"], b["repository.ignore.runtime_sentinel"], b["verification.commands.no_shell_indirection"])'
```

Expected: unittest OK; `just agent-workflow-tests` passes; the third command prints `passed passed passed` for this repository, whose `.agents/` tree holds only `project.json` and `instructions/bootstrap.md`, whose root `.gitignore` carries `.agents/runtime/` with no broad ladder, and whose three declared commands are plain argv.

Falsifiability at the base commit: the third command fails with `KeyError: 'repository.paths.classified'`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/conformance.py \
        home/common/agent-skills/tests/test_conformance.py
git commit -m "$(cat <<'MSG'
feat(conformance): register the repository lifecycle and command policy checks

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
MSG
)"
```
