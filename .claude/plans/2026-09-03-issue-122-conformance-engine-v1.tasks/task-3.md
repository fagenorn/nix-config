# Task 3: Host installation checks — store-symlinked policy path and missing helper

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`

**Interfaces:**
- Consumes from Task 2: `Check`, `Outcome`, `Context`, `REGISTRY`, `REGISTRY_BY_ID`, `REPAIRS`, `select`, and `context.bindings` / `context.capabilities` (both populated by `check_contract_resolvable` when the contract validated, both `None` otherwise — unreachable here, because these checks depend on `repository.contract.valid`).
- Produces: two evaluators, `check_policy_path_no_follow_readable(context)` and `check_executor_helper_on_path(context)`, and the two registry entries and two repairs below.

**Invariants:**
- The symlink walk is **bounded at the project root**: it inspects the declared path's own components under the root and never a component at or above the root (D18). On macOS `/tmp` is a symlink to `private/tmp`; an unbounded walk would fail every fixture and every checkout beneath it.
- Neither evaluator performs a `PATH` search of its own. `host.executor.helper_on_path` projects the resolver's already-computed capability states (DRY with `resolves_on_path`).
- Neither evaluator opens a file, follows a link to read its target's contents, or starts a process.
- `facts` values are repository-relative paths and small integers, never absolute paths — an absolute path can exceed the 200-character bound and leaks the caller's home directory.

## Registry entries this task adds

Append to `REGISTRY` after `host.capability.required` (dependency order is preserved because both depend on `repository.contract.valid`, which precedes them):

| Id | Domain | Subject kind | Req. | Depends on | Reason codes | Repair |
|---|---|---|---|---|---|---|
| `host.policy_path.no_follow_readable` | host | path | required | `repository.contract.valid` | `policy_path_symlinked` | `host.policy_path.materialize` |
| `host.executor.helper_on_path` | host | host_tool | required | `repository.contract.valid` | `helper_missing` | `host.helper.install` |

Both repairs: `{"module": "conformance", "safety_class": "user_action", "operation": None}` — no command materialises a store-linked policy file or installs a helper, so the operation is null (D25).

## `host.policy_path.no_follow_readable`

**Subject set.** Every repository-relative path the contract declares as a knowledge or projection source, read from the *authored* contract (`context.contract["bindings"]["paths"]` and `context.contract["projections"]`), not from `context.bindings` — the normalized bindings are already absolute and the check needs the relative form for its facts. Collect, deduplicated and sorted:
- every entry of `paths.context`, `paths.standards`, `paths.architecture`, `paths.operations`, `paths.hints`, `paths.rejections`;
- every projection entry's `source`.

Projection *targets* are excluded: they are generated files the project owns and rewrites, not policy a reader opens with `O_NOFOLLOW`.

**The walk.** For each relative path, walk its components from the root downwards, accumulating `current = root`, then `current = current / part` for each `Path(relative).parts`. At each accumulated `current`, test `current.is_symlink()` (an `lstat`, which does not follow). Stop at the first component that is a symlink, or when the whole path is consumed. Never test `root` itself and never any of its parents (D18). A component that does not exist at all is **not** this check's finding — a missing knowledge path is the resolver's `knowledge_path_missing`, surfaced by `host.executor.helper_on_path` — so skip a path whose walk hits a non-existent component with no symlink found.

**The finding.** With no symlinked component, `Outcome("passed")`. Otherwise:

```python
Outcome("failed", "policy_path_symlinked", "host.policy_path.materialize", {
    "paths": <up to 8 offending repository-relative path strings, sorted>,
    "count": <total offending paths>,
    "link_depth": <component index of the first symlink in the first offender, 1-based>,
    "in_nix_store": <bool: os.readlink of that component, resolved against its parent,
                     starts with "/nix/store/">,
})
```

`in_nix_store` records *where the link points* as a boolean only — never the store path itself, which would be an absolute path in the facts.

## `host.executor.helper_on_path`

Reads `context.capabilities` and reports the capabilities the resolver already computed as `blocked` for a tool-shaped reason:

```python
TOOL_REASON_CODES = ("command_missing", "tracker_cli_missing")
```

Collect `[name for name, entry in sorted(context.capabilities.items())
          if entry["state"] == "blocked" and entry["reason_code"] in TOOL_REASON_CODES]`.

Empty → `Outcome("passed")`. Otherwise:

```python
Outcome("failed", "helper_missing", "host.helper.install", {
    "capabilities": <up to 8 offending capability names, sorted>,
    "count": <total>,
    "reason_codes": <the distinct reason codes among them, sorted>,
})
```

A capability blocked for `knowledge_path_missing` or `vcs_worktree_unsupported` is deliberately **not** this check's finding: neither is a helper missing from `PATH`, and misreporting them here would send a reader to the wrong repair.

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_conformance.py`.

```python
class PolicyPathSymlinkTest(ReportAssertions, unittest.TestCase):
    """AC3, first half: a policy path reached through a symlink is a host finding."""

    def test_symlinked_standards_directory_fails_with_a_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            standards = root / "home/common/agent-skills/standards"
            real = root / "materialized-standards"
            real.mkdir()
            (real / "the-bar.md").write_text("bar\n", encoding="utf-8")
            shutil.rmtree(standards)
            standards.symlink_to(real, target_is_directory=True)
            code, out, err = run("run", "--purpose", "doctor", "--repo-root", str(root))
            self.assertEqual(code, 0, err)
            report = json.loads(out)
            check = {c["id"]: c for c in report["checks"]}[
                "host.policy_path.no_follow_readable"]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["domain"], "host")
            self.assertEqual(check["subject_kind"], "path")
            self.assertEqual(check["reason_code"], "policy_path_symlinked")
            self.assertEqual(check["repair_id"], "host.policy_path.materialize")
            self.assertEqual(check["facts"]["paths"],
                             ["home/common/agent-skills/standards"])
            self.assertEqual(check["facts"]["count"], 1)
            self.assertEqual(check["facts"]["link_depth"], 4)
            self.assertFalse(check["facts"]["in_nix_store"])
            repair = {r["repair_id"]: r for r in report["repairs"]}[
                "host.policy_path.materialize"]
            self.assertEqual(repair["safety_class"], "user_action")
            self.assertIn(repair["safety_class"], ["read_only", "worktree",
                                                   "user_action", "destructive"])
            self.assertIsNone(repair["operation"])
            self.assert_validates(report)

    def test_symlinked_projection_source_is_also_a_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            source = root / ".agents/instructions/bootstrap.md"
            real = root / "bootstrap-real.md"
            real.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            source.unlink()
            source.symlink_to(real)
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "host.policy_path.no_follow_readable"]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["facts"]["paths"],
                             [".agents/instructions/bootstrap.md"])

    def test_a_clean_root_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "host.policy_path.no_follow_readable"]
            self.assertEqual(check["status"], "passed")
            self.assertIsNone(check["repair_id"])
            self.assertEqual(check["facts"], {})

    def test_a_symlinked_ancestor_above_the_root_is_not_a_finding(self):
        """D18: the walk is bounded at the project root."""
        with tempfile.TemporaryDirectory() as tmp:
            real_parent = Path(tmp) / "real"
            real_parent.mkdir()
            root = make_root(real_parent / "repo")
            linked_parent = Path(tmp) / "linked"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            code, out, _ = run("run", "--purpose", "doctor",
                               "--repo-root", str(linked_parent / "repo"))
            self.assertEqual(code, 0)
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "host.policy_path.no_follow_readable"]
            self.assertEqual(check["status"], "passed")


class HelperOnPathTest(ReportAssertions, unittest.TestCase):
    """AC3, second half: a helper missing from PATH is a host finding."""

    def test_empty_path_reports_the_blocked_tool_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            env = dict(os.environ, PATH="")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "run", "--purpose", "doctor",
                 "--repo-root", str(root)],
                capture_output=True, text=True, timeout=60, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            check = {c["id"]: c for c in report["checks"]}[
                "host.executor.helper_on_path"]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["subject_kind"], "host_tool")
            self.assertEqual(check["reason_code"], "helper_missing")
            self.assertEqual(check["repair_id"], "host.helper.install")
            self.assertIn("tracker", check["facts"]["capabilities"])
            self.assertEqual(check["facts"]["reason_codes"],
                             sorted(set(check["facts"]["reason_codes"])))
            self.assertLessEqual(len(check["facts"]["capabilities"]), 8)
            repair = {r["repair_id"]: r for r in report["repairs"]}[
                "host.helper.install"]
            self.assertEqual(repair["safety_class"], "user_action")
            self.assertIsNone(repair["operation"])
            self.assert_validates(report)

    def test_a_populated_path_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "host.executor.helper_on_path"]
            self.assertEqual(check["status"], "passed")
```

`make_root` must, from this task on, create the fixture's knowledge paths and place executable `gh`, `git`, `just` and `codex` stubs on a fixture `PATH` so the clean-root cases genuinely pass; extend it once here and reuse it. Import `os`, `shutil` at the top if not already imported.

`test_symlinked_standards_directory_fails_with_a_repair` asserts `link_depth == 4` because `home/common/agent-skills/standards` has four components and the fourth is the link.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py -k PolicyPath -k Helper`
(or run the module and read the new classes' results)
Expected: `KeyError: 'host.policy_path.no_follow_readable'` and `KeyError: 'host.executor.helper_on_path'` — the ids are not in the registry, so no check by that id appears in the report.

- [ ] **Step 3: Write the minimal implementation**

Add the two evaluators and their registry entries and repairs exactly as specified above. Signatures:

```python
def check_policy_path_no_follow_readable(context: "Context") -> "Outcome":
    """Contract: failed when any declared policy path reaches its target through
    a symlink at or below the project root, never above it (D18)."""


def check_executor_helper_on_path(context: "Context") -> "Outcome":
    """Contract: failed when the resolver computed a capability as blocked for a
    tool-shaped reason; performs no PATH search of its own."""
```

- [ ] **Step 4: Verify**

```bash
python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py
just agent-workflow-tests
python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root . \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); print(sorted(c["id"] for c in r["checks"] if c["domain"]=="host"))'
```

Expected: unittest OK; `just agent-workflow-tests` passes; the last command prints exactly
`['host.capability.required', 'host.executor.helper_on_path', 'host.policy_path.no_follow_readable']`.

Falsifiability at the base commit: that last command prints `['host.capability.required']`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/conformance.py \
        home/common/agent-skills/tests/test_conformance.py
git commit -m "$(cat <<'MSG'
feat(conformance): register the two host installation checks

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
MSG
)"
```
