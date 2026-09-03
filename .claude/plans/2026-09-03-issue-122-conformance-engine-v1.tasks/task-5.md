# Task 5: Repository policy checks — path classification, ignore sentinel, command indirection

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`

**Interfaces:**
- Consumes from Task 2: `Check`, `Outcome`, `Context` (`context.root`, `context.contract`), `REGISTRY`, `REPAIRS`.
- Produces three evaluators — `check_paths_classified`, `check_ignore_runtime_sentinel`, `check_commands_no_shell_indirection` — plus `LIFECYCLE_CLASSES`, `CANONICAL_AGENTS_PREFIXES`, `OVERBROAD_IGNORE_PATTERNS`, `RUNTIME_IGNORE_PATTERNS`, `SHELL_ARGV0`, `SHELL_METACHARACTERS`, and three registry entries with three repairs.

**Invariants:**
- All three are pure filesystem and contract reads: no process, no write, no network.
- Path classification is a **closed** four-class rule (#72). A path matching none of the four is a finding, never a new implicit class.
- The ignore check reads the tracked ignore files only. `.git/info/exclude` is machine-local and is deliberately not consulted — a machine-local rule cannot be the repository's classification.
- `verification.commands.no_shell_indirection` validates command *policy*; the resolver already validated command *shape*. Neither re-implements the other.
- Facts carry repository-relative paths and command ids, never absolute paths and never a command's full argv.

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

**Subject set.** Every *file* under `<root>/.agents/` (recursive, `rglob("*")` filtered to `is_file()`, with any path containing a `.git` component skipped), expressed relative to `<root>/.agents/`; plus every declared projection `target`, expressed relative to `<root>`.

**Classification.**
- A `.agents/`-relative path is `canonical_tracked` when it equals `project.json` or starts with one of the remaining `CANONICAL_AGENTS_PREFIXES` directory prefixes. Under `artifacts/` require the second segment to be one of `specs`, `plans`, `evidence`, `handoffs`, `notes`; any other `artifacts/<x>/` segment is unclassified.
- A `.agents/`-relative path starting with `runtime/` is `ignored_runtime`.
- A repository-relative path equal to a declared projection `target` is `tracked_projection`.
- A path equal to a member of `BOOKKEEPING_ALLOWLIST` is `allowlisted_bookkeeping`.
- Anything else is unclassified.

**The finding.** No unclassified path → `Outcome("passed")`. Otherwise:

```python
Outcome("failed", "unclassified_path", "lifecycle.path.classify", {
    "paths": <up to 8 offending repository-relative paths, sorted>,
    "count": <total offending>,
})
```

Offending paths are reported repository-relative (`.agents/<x>` for the first set) so a reader can open them.

## `repository.ignore.runtime_sentinel`

```python
RUNTIME_IGNORE_PATTERNS = (".agents/runtime/", ".agents/runtime",
                           "/.agents/runtime/", "/.agents/runtime")
OVERBROAD_IGNORE_PATTERNS = (".agents/*", "/.agents/*", ".claude/*", "/.claude/*")
```

1. Read `<root>/.gitignore` as UTF-8 if it exists; strip each line, drop empties and lines starting with `#`. An unreadable or absent file yields an empty rule list, never an exception.
2. **Overbroad first** — an overbroad ignore conceals authored truth, so it outranks a missing sentinel. If any rule is in `OVERBROAD_IGNORE_PATTERNS`:
   `Outcome("failed", "overbroad_ignore", "lifecycle.ignore.repair", {"rules": <up to 8 offending rules, sorted>, "count": <total>})`.
3. **Then coverage.** `.agents/runtime/` is covered when either some root rule is in `RUNTIME_IGNORE_PATTERNS`, or `<root>/.agents/runtime/.gitignore` exists and its bytes are exactly `b"*\n"` (#72's sentinel). Neither → `Outcome("failed", "runtime_ignore_missing", "lifecycle.ignore.repair", {"root_gitignore": <bool: the file exists>, "sentinel": <bool: the sentinel file exists>})`.
4. Otherwise `Outcome("passed")`.

Accepting either spelling is deliberate: this repository covers the subtree from the root `.gitignore`, and #72's committed `.agents/runtime/.gitignore` sentinel is the other legitimate home. Demanding only one would fail a conformant repository.

## `verification.commands.no_shell_indirection`

```python
SHELL_ARGV0 = ("sh", "bash", "zsh", "dash", "ksh")
SHELL_METACHARACTERS = (";", "|", "&&", "`", "$(")
```

For each `command_id, entry` in `sorted(context.contract["bindings"]["commands"].items())`, the entry is offending when either:
- `Path(entry["argv"][0]).name` is in `SHELL_ARGV0` **and** `"-c"` appears in `entry["argv"][1:]`; or
- any element of `entry["argv"]` contains any member of `SHELL_METACHARACTERS`.

Read the *authored* contract, not the normalized bindings: normalization rewrites `cwd` but leaves `argv` alone, and reading the authored form keeps the reported ids and the authored text in one correspondence.

No offender → `Outcome("passed")`. Otherwise:

```python
Outcome("failed", "shell_indirection", "contract.commands.destructure", {
    "commands": <up to 8 offending command ids, sorted>,
    "count": <total offending>,
})
```

## Registry entries this task adds

Append after `repository.projection.fresh` — all three depend on `repository.contract.valid`, which precedes them in `REGISTRY`:

| Id | Domain | Subject kind | Req. | Depends on | Reason codes | Repair (module, class, operation) |
|---|---|---|---|---|---|---|
| `repository.paths.classified` | repository | path | required | `repository.contract.valid` | `unclassified_path` | `lifecycle.path.classify` (conformance, `user_action`, null) |
| `repository.ignore.runtime_sentinel` | repository | path | required | `repository.contract.valid` | `runtime_ignore_missing`, `overbroad_ignore` | `lifecycle.ignore.repair` (conformance, `worktree`, null) |
| `verification.commands.no_shell_indirection` | verification | command | required | `repository.contract.valid` | `shell_indirection` | `contract.commands.destructure` (resolve-project, `user_action`, null) |

`lifecycle.ignore.repair` is `worktree` — editing `.gitignore` changes the working tree — but carries `operation: None`, because no engine subcommand performs it (D25).

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_conformance.py`.

```python
class PathClassificationTest(ReportAssertions, unittest.TestCase):
    def test_a_conformant_agents_tree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, err = run("run", "--purpose", "doctor", "--repo-root", str(root))
            self.assertEqual(code, 0, err)
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "repository.paths.classified"]
            self.assertEqual(check["status"], "passed")
            self.assertEqual(check["facts"], {})

    def test_an_unclassified_agents_path_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            (root / ".agents/scratchpad").mkdir()
            (root / ".agents/scratchpad/notes.txt").write_text("x", encoding="utf-8")
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            report = json.loads(out)
            check = {c["id"]: c for c in report["checks"]}["repository.paths.classified"]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["reason_code"], "unclassified_path")
            self.assertEqual(check["facts"]["paths"], [".agents/scratchpad/notes.txt"])
            self.assertEqual(check["facts"]["count"], 1)
            self.assertEqual(check["repair_id"], "lifecycle.path.classify")
            self.assert_validates(report)

    def test_a_runtime_path_is_classified_and_does_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            (root / ".agents/runtime/state/run-1").mkdir(parents=True)
            (root / ".agents/runtime/state/run-1/state.json").write_text(
                "{}", encoding="utf-8")
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "repository.paths.classified"]
            self.assertEqual(check["status"], "passed")

    def test_an_unadmitted_artifacts_subdirectory_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            (root / ".agents/artifacts/scratch").mkdir(parents=True)
            (root / ".agents/artifacts/scratch/x.md").write_text("x", encoding="utf-8")
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "repository.paths.classified"]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["facts"]["paths"],
                             [".agents/artifacts/scratch/x.md"])

    def test_offending_paths_are_capped_at_eight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            (root / ".agents/scratchpad").mkdir()
            for i in range(12):
                (root / f".agents/scratchpad/n{i}.txt").write_text("x", encoding="utf-8")
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            report = json.loads(out)
            check = {c["id"]: c for c in report["checks"]}["repository.paths.classified"]
            self.assertEqual(len(check["facts"]["paths"]), 8)
            self.assertEqual(check["facts"]["count"], 12)
            self.assert_validates(report)


class IgnoreSentinelTest(ReportAssertions, unittest.TestCase):
    def test_root_gitignore_rule_satisfies_the_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            (root / ".gitignore").write_text(".agents/runtime/\n", encoding="utf-8")
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "repository.ignore.runtime_sentinel"]
            self.assertEqual(check["status"], "passed")

    def test_the_committed_runtime_sentinel_also_satisfies_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            (root / ".gitignore").write_text("result\n", encoding="utf-8")
            (root / ".agents/runtime").mkdir(parents=True)
            (root / ".agents/runtime/.gitignore").write_bytes(b"*\n")
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "repository.ignore.runtime_sentinel"]
            self.assertEqual(check["status"], "passed")

    def test_missing_coverage_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            (root / ".gitignore").write_text("result\n", encoding="utf-8")
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            report = json.loads(out)
            check = {c["id"]: c for c in report["checks"]}[
                "repository.ignore.runtime_sentinel"]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["reason_code"], "runtime_ignore_missing")
            self.assertEqual(check["repair_id"], "lifecycle.ignore.repair")
            self.assertEqual(
                {r["repair_id"]: r for r in report["repairs"]}[
                    "lifecycle.ignore.repair"]["safety_class"], "worktree")
            self.assert_validates(report)

    def test_an_overbroad_ignore_outranks_a_present_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            (root / ".gitignore").write_text(
                ".agents/runtime/\n.agents/*\n", encoding="utf-8")
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "repository.ignore.runtime_sentinel"]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["reason_code"], "overbroad_ignore")
            self.assertEqual(check["facts"]["rules"], [".agents/*"])


class ShellIndirectionTest(ReportAssertions, unittest.TestCase):
    def mutate_commands(self, root: Path, command_id: str, argv: list) -> None:
        path = root / ".agents/project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        contract["bindings"]["commands"][command_id]["argv"] = argv
        path.write_text(json.dumps(contract), encoding="utf-8")

    def test_declared_commands_without_indirection_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "verification.commands.no_shell_indirection"]
            self.assertEqual(check["status"], "passed")
            self.assertEqual(check["domain"], "verification")

    def test_a_shell_dash_c_command_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            self.mutate_commands(root, "nix-build", ["bash", "-c", "just build"])
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            report = json.loads(out)
            check = {c["id"]: c for c in report["checks"]}[
                "verification.commands.no_shell_indirection"]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["reason_code"], "shell_indirection")
            self.assertEqual(check["facts"]["commands"], ["nix-build"])
            self.assertEqual(check["repair_id"], "contract.commands.destructure")
            self.assert_validates(report)

    def test_a_metacharacter_in_any_argv_element_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            self.mutate_commands(root, "nix-build", ["just", "build && just switch"])
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "verification.commands.no_shell_indirection"]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["facts"]["commands"], ["nix-build"])

    def test_the_ci_purpose_includes_the_verification_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, _ = run("run", "--purpose", "ci", "--repo-root", str(root))
            self.assertIn("verification.commands.no_shell_indirection",
                          [c["id"] for c in json.loads(out)["checks"]])

    def test_the_fleet_purpose_excludes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, _ = run("run", "--purpose", "fleet", "--repo-root", str(root))
            self.assertNotIn("verification.commands.no_shell_indirection",
                             [c["id"] for c in json.loads(out)["checks"]])
```

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
