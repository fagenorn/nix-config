# Task 2: Capability readiness, declaration/binding contradictions, and `--require`

**Files:**
- Modify: `home/common/agent-skills/scripts/resolve-project.py`
- Test: `home/common/agent-skills/tests/test_resolve_project.py`

**Interfaces:**
- Consumes, from Task 1: `SCHEMA_VERSION = 1`; the tuples `CAPABILITY_NAMES` (the eleven names), `BINDING_NAMESPACES`, `CAPABILITY_STATES`, `AUTHORED_SUPPORT`, `REASON_CODES`; `class ContractError(Exception)` with `code`, `repair_id`, `violations`; `discover_root(repo_root) -> Path`; `load_contract(root) -> dict`; `validate_contract(source) -> list[dict]`; `normalize_bindings(source_bindings, root) -> dict`; `emit_json(value) -> int`; `emit_error(code, repair_id, violations) -> int`; `main(argv=None) -> int` with the `resolve`, `check-projections` and `write-projections` subparsers. Task 1's `resolve` sets every `supported` capability to `available` without evaluating a prerequisite; this task replaces that branch.
- Produces, for Tasks 3–5: `validate_capability_bindings(source: dict) -> list[dict]` returning D6 contradiction violations; `compute_capabilities(bindings: dict, root: Path, declarations: dict) -> dict` mapping each of the eleven names to `{"state", "reason_code", "repair_id"}`; and `resolve` accepting `--require <capability>` repeatably.

**Invariants:**
- A capability declared `unsupported` yields `{"state": "unsupported", "reason_code": None, "repair_id": None}` and has no prerequisite evaluated and no binding requirement imposed.
- A capability declared `supported` with a structurally incomplete binding is `invalid_contract`, never `blocked` (D6).
- `blocked` carries the **first** failing prerequisite's `reason_code` from `REASON_CODES` and a `repair_id` of exactly `capability.<name>.<reason_code>`; `available` and `unsupported` carry `None` for both.
- No subprocess is executed to decide readiness — not `git`, not the tracker CLI, not a verification command. Only `shutil.which`, `Path.exists`, `os.access` and the executable bit are consulted.
- `--require` accepts only the eleven registry names, as a closed argparse `choices` set; an unknown name is an argparse usage error — exit 2 with empty stdout, no JSON (D16).
- `capability_unavailable` reports one violation per offending required name, pointer `/capabilities/<name>`, sorted by pointer; its `repair_id` is `capability.<first offending name in pointer order>.<that entry's reason_code, or "unsupported" when the entry is unsupported>`.

## Steps

- [ ] **Step 1: Write the failing tests**

Append to `home/common/agent-skills/tests/test_resolve_project.py`, above the `if __name__ == "__main__":` guard. It adds a PATH-stubbing subprocess helper, because readiness is decided from `PATH` alone:

```python
import stat


def run_with_path(path_value: str, *args: str) -> tuple[int, str, str]:
    """Run the resolver with `PATH` replaced by exactly `path_value`.

    The interpreter is `sys.executable`, an absolute path, because `PATH` here
    holds only the stub directory and no Python (B-002). `os`, `sys` and
    `subprocess` are already imported by Task 1's module header.
    """
    env = dict(os.environ, PATH=path_value)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=60, env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def make_stub_bin(names: tuple[str, ...]) -> Path:
    """A directory holding executable no-op stubs for the named binaries."""
    stub = Path(tempfile.mkdtemp())
    for name in names:
        target = stub / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return stub


class CapabilityStateTest(ResolverTestCase):
    def resolve_with_path(self, root: Path, stub: Path, *extra: str):
        code, out, err = run_with_path(
            str(stub), "resolve", "--repo-root", str(root), *extra)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, out, err

    def test_available_when_every_prerequisite_is_present(self):
        root = self.make_root()
        stub = make_stub_bin(("gh", "git", "just", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        for name in ("tracker", "worktrees", "knowledge.standards",
                     "knowledge.architecture", "verification",
                     "review.plan", "review.code"):
            with self.subTest(capability=name):
                entry = snap["capabilities"][name]
                self.assertEqual(entry["state"], "available")
                self.assertIsNone(entry["reason_code"])
                self.assertIsNone(entry["repair_id"])

    def test_tracker_is_blocked_when_its_cli_is_absent(self):
        root = self.make_root()
        stub = make_stub_bin(("git", "just", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        entry = snap["capabilities"]["tracker"]
        self.assertEqual(entry["state"], "blocked")
        self.assertEqual(entry["reason_code"], "tracker_cli_missing")
        self.assertEqual(entry["repair_id"], "capability.tracker.tracker_cli_missing")

    def test_worktrees_is_blocked_when_git_is_absent(self):
        root = self.make_root()
        stub = make_stub_bin(("gh", "just", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        entry = snap["capabilities"]["worktrees"]
        self.assertEqual(entry["state"], "blocked")
        self.assertEqual(entry["reason_code"], "vcs_worktree_unsupported")
        self.assertEqual(entry["repair_id"],
                         "capability.worktrees.vcs_worktree_unsupported")

    def test_verification_is_blocked_when_a_command_binary_is_absent(self):
        root = self.make_root()
        stub = make_stub_bin(("gh", "git", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        entry = snap["capabilities"]["verification"]
        self.assertEqual(entry["state"], "blocked")
        self.assertEqual(entry["reason_code"], "command_missing")
        self.assertEqual(entry["repair_id"], "capability.verification.command_missing")

    def test_knowledge_is_blocked_when_a_declared_path_is_absent(self):
        root = self.make_root()
        (root / "CLAUDE.md").unlink()
        stub = make_stub_bin(("gh", "git", "just", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        entry = snap["capabilities"]["knowledge.architecture"]
        self.assertEqual(entry["state"], "blocked")
        self.assertEqual(entry["reason_code"], "knowledge_path_missing")
        self.assertEqual(entry["repair_id"],
                         "capability.knowledge.architecture.knowledge_path_missing")

    def test_every_blocked_reason_code_is_from_the_closed_set(self):
        root = self.make_root()
        code, snap, _, err = self.resolve_with_path(root, make_stub_bin(()))
        self.assertEqual(code, 0, err)
        for name, entry in snap["capabilities"].items():
            with self.subTest(capability=name):
                if entry["state"] == "blocked":
                    self.assertIn(entry["reason_code"],
                                  ("tracker_cli_missing", "vcs_worktree_unsupported",
                                   "knowledge_path_missing", "command_missing"))
                    self.assertEqual(entry["repair_id"],
                                     f"capability.{name}.{entry['reason_code']}")
                else:
                    self.assertIsNone(entry["reason_code"])
                    self.assertIsNone(entry["repair_id"])

    def test_unsupported_capabilities_never_evaluate_prerequisites(self):
        root = self.make_root()
        code, snap, _, err = self.resolve_with_path(root, make_stub_bin(()))
        self.assertEqual(code, 0, err)
        for name in ("release", "deploy", "knowledge.context", "knowledge.hints"):
            with self.subTest(capability=name):
                self.assertEqual(snap["capabilities"][name]["state"], "unsupported")


class ContradictionTest(ResolverTestCase):
    def refuse(self, contract: dict) -> dict:
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        return payload["error"]

    def test_supported_tracker_with_kind_none_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["tracker"]["kind"] = "none"
        self.assertIn("/bindings/tracker/kind",
                      [v["pointer"] for v in self.refuse(contract)["violations"]])

    def test_supported_tracker_with_an_empty_cli_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["tracker"]["cli"] = ""
        self.refuse(contract)

    def test_supported_worktrees_with_a_non_git_vcs_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["vcs"]["kind"] = "hg"
        self.refuse(contract)

    def test_supported_knowledge_with_an_empty_path_list_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["paths"]["standards"] = []
        self.assertIn("/bindings/paths/standards",
                      [v["pointer"] for v in self.refuse(contract)["violations"]])

    def test_supported_verification_with_no_ids_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["workflow"]["verification"] = []
        self.refuse(contract)

    def test_supported_review_with_a_null_id_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["workflow"]["review"]["plan"] = None
        self.refuse(contract)

    def test_unsupported_capabilities_impose_no_binding_requirement(self):
        contract = source_contract()
        self.assertEqual(contract["capabilities"]["release"]["support"], "unsupported")
        self.assertIsNone(contract["bindings"]["workflow"]["release"])
        self.assertEqual(contract["bindings"]["deploy"]["adapter"], "none")
        code, _, err = self.resolve(self.make_root(contract))
        self.assertEqual(code, 0, err)

    def test_a_supported_deploy_needs_an_adapter_and_a_command(self):
        contract = source_contract()
        contract["capabilities"]["deploy"]["support"] = "supported"
        self.refuse(contract)


class RequireTest(ResolverTestCase):
    def test_requiring_an_unsupported_capability_refuses(self):
        root = self.make_root()
        code, out, _ = run_with_path(
            str(make_stub_bin(("gh", "git", "just", "codex"))),
            "resolve", "--repo-root", str(root), "--require", "release")
        payload = json.loads(out)
        self.assertEqual(code, 2)
        error = payload["error"]
        self.assertEqual(error["code"], "capability_unavailable")
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/capabilities/release"])
        self.assertEqual(error["repair_id"], "capability.release.unsupported")
        self.assertNotIn("schema_version", payload)

    def test_requiring_a_blocked_capability_names_its_reason_code(self):
        root = self.make_root()
        code, out, _ = run_with_path(
            str(make_stub_bin(("git", "just", "codex"))),
            "resolve", "--repo-root", str(root), "--require", "tracker")
        error = json.loads(out)["error"]
        self.assertEqual(code, 2)
        self.assertEqual(error["code"], "capability_unavailable")
        self.assertEqual(error["repair_id"], "capability.tracker.tracker_cli_missing")

    def test_several_offending_requirements_are_reported_in_pointer_order(self):
        root = self.make_root()
        code, out, _ = run_with_path(
            str(make_stub_bin(("gh", "git", "just", "codex"))),
            "resolve", "--repo-root", str(root),
            "--require", "release", "--require", "deploy")
        error = json.loads(out)["error"]
        self.assertEqual(code, 2)
        pointers = [v["pointer"] for v in error["violations"]]
        self.assertEqual(pointers, ["/capabilities/deploy", "/capabilities/release"])
        self.assertEqual(error["repair_id"], "capability.deploy.unsupported")

    def test_requiring_an_available_capability_returns_the_snapshot(self):
        root = self.make_root()
        code, out, err = run_with_path(
            str(make_stub_bin(("gh", "git", "just", "codex"))),
            "resolve", "--repo-root", str(root), "--require", "tracker")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["schema_version"], 1)

    def test_an_unknown_require_name_is_an_argparse_usage_error(self):
        root = self.make_root()
        code, out, err = run("resolve", "--repo-root", str(root),
                             "--require", "orchestration")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("orchestration", err)


class NoSubprocessTest(ResolverTestCase):
    def test_readiness_runs_no_child_process(self):
        """An empty PATH must still produce a snapshot, not an execution error."""
        root = self.make_root()
        code, out, err = run_with_path(
            str(make_stub_bin(())), "resolve", "--repo-root", str(root))
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out)["schema_version"], 1)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_resolve_project.py 2>&1 | tail -20`
Expected: FAIL — every `CapabilityStateTest` blocked-state case reports `available` (Task 1 derives state from the declaration alone), every `ContradictionTest` case exits 0 instead of refusing, and `RequireTest` errors because `resolve` has no `--require` option.

- [ ] **Step 3: Implement contradiction validation**

Add `validate_capability_bindings(source: dict) -> list[dict]`, called from the same one-pass validation as Task 1's `validate_contract` and merged into the same violation list before sorting. It runs only over capabilities declared `supported`, and only when the bindings it inspects are themselves structurally sound (a namespace already reported malformed contributes no second violation). Per D6:

| Declared `supported` | Requirement | Violation pointer |
|---|---|---|
| `tracker` | `bindings.tracker.kind != "none"` and `bindings.tracker.cli` is a non-empty string | `/bindings/tracker/kind`, `/bindings/tracker/cli` |
| `worktrees` | `bindings.vcs.kind == "git"` | `/bindings/vcs/kind` |
| `knowledge.context` | `bindings.paths.context` is non-empty | `/bindings/paths/context` |
| `knowledge.standards` | `bindings.paths.standards` is non-empty | `/bindings/paths/standards` |
| `knowledge.architecture` | `bindings.paths.architecture` is non-empty | `/bindings/paths/architecture` |
| `knowledge.hints` | `bindings.paths.hints` is non-empty | `/bindings/paths/hints` |
| `verification` | `bindings.workflow.verification` is non-empty | `/bindings/workflow/verification` |
| `review.plan` | `bindings.workflow.review.plan` is not `null` | `/bindings/workflow/review/plan` |
| `review.code` | `bindings.workflow.review.code` is not `null` | `/bindings/workflow/review/code` |
| `release` | `bindings.workflow.release` is not `null` | `/bindings/workflow/release` |
| `deploy` | `bindings.deploy.adapter != "none"` and `bindings.deploy.command` is not `null` | `/bindings/deploy/adapter`, `/bindings/deploy/command` |

A capability declared `unsupported` contributes no requirement at all. Each violation's internal repair id is `contract.capabilities.<name>.binding_incomplete`.

- [ ] **Step 4: Implement readiness computation**

Add:

```python
def resolves_on_path(argv0: str) -> bool:
    """True when argv0 names a runnable binary, without executing it.

    `cwd` is the base for a relative argv0 and is already absolute.
    """


def compute_capabilities(bindings: dict, root: Path, declarations: dict) -> dict:
    """Contract: eleven entries, each {"state", "reason_code", "repair_id"}."""
```

`resolves_on_path(argv0, cwd)`: when `argv0` contains no path separator, return `shutil.which(argv0) is not None`; otherwise resolve a relative `argv0` against `cwd` — the command entry's own already-normalized absolute working directory, not `project.root` — and return `path.is_file() and os.access(path, os.X_OK)`. Resolving against `cwd` is what actually happens when the command runs, so `{"cwd": "tools", "argv": ["./check"]}` is checked at `<root>/tools/check` (DISC-001). Every `command_missing` prerequisite passes the entry's `cwd`. It never runs the binary.

`compute_capabilities` walks `CAPABILITY_NAMES` in order. A declaration of `unsupported` yields `{"state": "unsupported", "reason_code": None, "repair_id": None}` immediately. A declaration of `supported` evaluates that capability's prerequisites in the fixed order of the spec's Capability computation table, returning `{"state": "available", "reason_code": None, "repair_id": None}` when all pass, and otherwise `{"state": "blocked", "reason_code": <first failure's code>, "repair_id": f"capability.{name}.{reason_code}"}`:

- `tracker` — `resolves_on_path(bindings["tracker"]["cli"], root)`, else `tracker_cli_missing`. The tracker CLI has no command entry, so its base is `root`.
- `worktrees` — `resolves_on_path("git", root)`, then the **parent directory** of `root / bindings["vcs"]["worktree"]["root"]` exists and `os.access(parent, os.W_OK)`; either failure gives `vcs_worktree_unsupported`.
- `knowledge.context` / `knowledge.standards` / `knowledge.architecture` / `knowledge.hints` — the matching `bindings["paths"][…]` list is non-empty and every entry, resolved under `root`, exists; else `knowledge_path_missing`.
- `verification` — for every id in `bindings["workflow"]["verification"]`, `resolves_on_path(entry["argv"][0], entry["cwd"])` where `entry = bindings["commands"][id]`; else `command_missing`.
- `review.plan`, `review.code`, `release` — the same single check over `bindings["workflow"]["review"]["plan"]`, `…["code"]`, and `bindings["workflow"]["release"]`; else `command_missing`.
- `deploy` — the same single check over `bindings["deploy"]["command"]`; else `command_missing`.

The dispatch over `CAPABILITY_NAMES` raises on its default branch rather than returning a fallback state.

Replace Task 1's declaration-only branch in `resolve` with this function and remove any comment or docstring that described the interim behavior.

**SF-002 — the readiness branches these rules create each need a falsifiable test.** Add to `CapabilityStateTest`:

```python
    def test_worktrees_is_blocked_when_the_worktree_parent_is_unwritable(self):
        root = self.make_root()
        stub = make_stub_bin(("gh", "git", "just", "codex"))
        parent = root / ".worktrees"
        original = parent.stat().st_mode
        parent.chmod(0o500)
        try:
            code, snap, _, err = self.resolve_with_path(root, stub)
        finally:
            parent.chmod(original)
        self.assertEqual(code, 0, err)
        entry = snap["capabilities"]["worktrees"]
        self.assertEqual(entry["state"], "blocked")
        self.assertEqual(entry["reason_code"], "vcs_worktree_unsupported")

    def test_worktrees_is_blocked_when_the_worktree_parent_is_absent(self):
        root = self.make_root()
        stub = make_stub_bin(("gh", "git", "just", "codex"))
        shutil.rmtree(root / ".worktrees")
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        self.assertEqual(
            snap["capabilities"]["worktrees"]["reason_code"],
            "vcs_worktree_unsupported")

    def test_a_relative_executable_resolves_against_its_command_cwd(self):
        """DISC-001: the base is the entry's `cwd`, not `project.root`."""
        source = source_contract()
        source["bindings"]["commands"]["local-check"] = {
            "argv": ["./check"], "cwd": "tools", "env": []}
        source["bindings"]["workflow"]["verification"] = ["local-check"]
        root = self.make_root(source)
        stub = make_stub_bin(("gh", "git", "just", "codex"))

        (root / "tools").mkdir()
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["capabilities"]["verification"]["state"], "blocked")

        target = root / "tools" / "check"
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["capabilities"]["verification"]["state"], "available")

    def test_a_relative_executable_at_the_root_does_not_satisfy_a_cwd_entry(self):
        source = source_contract()
        source["bindings"]["commands"]["local-check"] = {
            "argv": ["./check"], "cwd": "tools", "env": []}
        source["bindings"]["workflow"]["verification"] = ["local-check"]
        root = self.make_root(source)
        (root / "tools").mkdir()
        decoy = root / "check"
        decoy.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        decoy.chmod(decoy.stat().st_mode | stat.S_IXUSR)
        stub = make_stub_bin(("gh", "git", "just", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["capabilities"]["verification"]["state"], "blocked")
```

`shutil` joins the module imports. The unwritable-parent case is skipped under a
`root` euid, where mode bits do not deny access:
`@unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "mode bits do not bind root")`.

- [ ] **Step 5: Implement `--require`**

Add to the `resolve` subparser: `--require`, `action="append"`, `dest="require"`, `default=None`, `choices=list(CAPABILITY_NAMES)`, `metavar="CAPABILITY"` (D16 — argparse rejects an unknown name with its own usage error, exit 2 and no stdout). After computing capabilities and before emitting, collect every required name whose `state` is not `available` into violations of the shape `{"pointer": f"/capabilities/{name}", "message": …}`, sorted by pointer. When that list is non-empty, raise `ContractError("capability_unavailable", f"capability.{first}.{reason}", violations)`, where `first` is the first offending name in pointer order and `reason` is that entry's `reason_code` when it is `blocked`, or the literal `unsupported` when it is `unsupported`.

- [ ] **Step 6: Verify**

```sh
python3 -m unittest -v home/common/agent-skills/tests/test_resolve_project.py 2>&1 | tail -5
just agent-workflow-tests 2>&1 | tail -5
python3 home/common/agent-skills/scripts/resolve-project.py resolve --repo-root . \
  | python3 -c 'import json,sys; c=json.load(sys.stdin)["capabilities"]; print(sorted({e["state"] for e in c.values()}))'
git status --porcelain
```

Expected: both test runs report `OK`; the states line prints a subset of `['available', 'blocked', 'unsupported']` and, on a machine with `gh`, `git`, `just` and `codex` on `PATH`, exactly `['available', 'unsupported']`; `git status --porcelain` shows only this task's two files.

Falsifiable gate — at Task 1's commit, `--require release` exits 0 with a snapshot rather than refusing:

```sh
if python3 home/common/agent-skills/scripts/resolve-project.py resolve --repo-root . --require release >/dev/null 2>&1; then exit 1; fi
if grep -q "subprocess" home/common/agent-skills/scripts/resolve-project.py; then exit 1; fi
```

The second line pins the no-subprocess invariant: the resolver must not import or call `subprocess` at all.

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/scripts/resolve-project.py \
  home/common/agent-skills/tests/test_resolve_project.py
git commit -m "feat(resolver): compute capability readiness and enforce --require

Per D6, D9, D13, D16.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
