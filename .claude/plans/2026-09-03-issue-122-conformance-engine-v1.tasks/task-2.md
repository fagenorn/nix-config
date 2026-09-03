# Task 2: The engine core — ladder, registry, purposes, and the two report shapes

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`

**Interfaces:**
- Consumes from Task 1: `SCHEMA_VERSION`, the closed vocabulary tuples, `validate_report`, `ReportError`, `emit_json`, `emit_error`, `build_parser`, `dispatch`, `main`.
- Produces, for Tasks 3–7:
  - `def load_resolver()` — returns the imported `resolve-project` module, memoised in a module global.
  - `class Check` — a `dataclasses.dataclass(frozen=True)` registry entry with fields `id: str`, `domain: str`, `subject_kind: str`, `requirement: str`, `depends_on: tuple[str, ...]`, `reason_codes: tuple[str, ...]`, `run: str`. `run` names the evaluator function on the module, looked up with `getattr`.
  - `REGISTRY: tuple[Check, ...]` — declared in dependency order; `REGISTRY_BY_ID: dict[str, Check]`.
  - `REPAIRS: dict[str, dict]` — `repair_id` → `{"module", "safety_class", "operation"}`.
  - `class Outcome` — a `dataclasses.dataclass` result an evaluator returns: `status: str`, `reason_code: str | None = None`, `repair_id: str | None = None`, `facts: dict | None = None`.
  - `class Context` — the per-run evaluation context, carrying `root: Path`, `offline: bool`, `required: tuple[str, ...]`, `resolver`, and `stages: dict[str, Outcome | None]` (the cached ladder results), plus `contract: dict | None`, `bindings: dict | None`, `capabilities: dict | None`.
  - `def evaluate(purpose: str, context: Context) -> list[dict]` — the emitted `checks` array.
  - `def build_report(purpose, context, checks) -> dict`.
  - `def select(purpose: str) -> tuple[Check, ...]` — the purpose's checks in dependency order.
  - `def bounded_run(argv: list[str], cwd, env=None) -> subprocess.CompletedProcess | None` — read-only child with `timeout=15`, `capture_output=True`, `text=True`; returns `None` on `OSError` or `subprocess.SubprocessError` instead of raising (D19).
- Later tasks extend `REGISTRY` and `REPAIRS` and add evaluator functions; they do not edit `select`, `evaluate` or `build_report`.

**Invariants:**
- The resolver ladder runs **at most once per process**. `repository.contract.resolvable` runs it inside one `except Exception` and caches every stage; every other structural check is a pure read of that cache (D17).
- `run` writes nothing under the subject root: no file opened for writing, no directory created.
- `checks` is emitted sorted by `id`; the *evaluation* order is `REGISTRY` order, which is topological (D24).
- Every emitted report satisfies `validate_report` — assert this inside `command_run` before printing, and let a `ReportError` become the `resolver_failure` refusal rather than a printed invalid report.
- `workflow_entry` emits exactly one check and at most one repair when the outcome is not `passed`, and exits 2. Every other purpose exits 0.
- No evaluator raises. An evaluator that cannot decide returns `Outcome("not_run", ...)`.

## The registry entries this task adds

Declared in this order (dependency order — `REGISTRY` order is *not* id order, D24):

| Order | Id | Domain | Subject kind | Req. | Depends on | Reason codes | Repair (module, class) |
|---|---|---|---|---|---|---|---|
| 1 | `repository.contract.resolvable` | repository | contract | required | — | `resolver_failure` | `conformance.internal` (conformance, `user_action`) |
| 2 | `repository.contract.present` | repository | contract | required | 1 | `not_onboarded` | `onboarding.contract.missing` (resolve-project, `user_action`) |
| 3 | `compatibility.contract.schema_supported` | compatibility | contract | required | 2 | `unsupported_schema` | `contract.schema.unsupported` (resolve-project, `user_action`) |
| 4 | `repository.contract.valid` | repository | contract | required | 3 | `invalid_contract` | `contract.invalid` (resolve-project, `user_action`) |
| 5 | `repository.projection.fresh` | repository | projection | required | 4 | `invalid_projection` | `projection.regenerate` (resolve-project, `worktree`, operation `{"subcommand": "write-projections", "args": []}`) |
| 6 | `host.capability.required` | host | capability | required | 4 | `capability_unavailable` | `capability.required.unavailable` (resolve-project, `user_action`) |

Every repair above carries `operation: None` except `projection.regenerate`.

## Purpose selection (D4, D5, D21)

```python
WORKFLOW_ENTRY_LADDER = (
    "repository.contract.resolvable",
    "repository.contract.present",
    "compatibility.contract.schema_supported",
    "repository.contract.valid",
    "repository.projection.fresh",
    "host.capability.required",
)
PURPOSE_DOMAINS = {
    "adoption": ("repository", "compatibility"),
    "ci":       ("repository", "compatibility", "verification"),
    "fleet":    ("repository", "compatibility"),
    "doctor":   DOMAINS,
}
```

`select(purpose)` returns, in `REGISTRY` order:
- `workflow_entry` → the entries named by `WORKFLOW_ENTRY_LADDER`;
- `local` → the `WORKFLOW_ENTRY_LADDER` entries **plus** every `host`-domain entry;
- a key of `PURPOSE_DOMAINS` → every entry whose `domain` is in that tuple;
- anything else → `raise ValueError(f"unknown purpose: {purpose!r}")`.

Selection is by domain, never by a hand-maintained id list, so Tasks 3–7 are additive (D21). `adoption` and `ci` must also pull in `compatibility.contract.schema_supported`, which their domain tuples already do.

## Evaluation

`evaluate(purpose, context)`:

1. Walk `select(purpose)` in order. Maintain `results: dict[str, Outcome]`.
2. For each entry, compute its `depends_on` closure over the *selected* set. If any ancestor's result status is `failed`, the entry's result is `Outcome("suppressed", facts={"suppressed_by": <the first such ancestor id in REGISTRY order>})` and no evaluator runs.
3. Otherwise call `getattr(module, entry.run)(context)` and take the returned `Outcome`.
4. **`workflow_entry` stops** at the first entry whose result status is `failed` or `not_run`, and `evaluate` returns exactly that one emitted check (D3). If every entry passes, it returns all six.
5. Assert each returned `Outcome.reason_code` is either `None` or a member of that entry's `reason_codes`; raise `ValueError` otherwise — a reason code outside the registry declaration is a bug in the evaluator, not a finding.
6. Return the emitted check objects sorted by `id`.

`build_report(purpose, context, checks)` assembles the six members. `subject.project_id` is `context.contract["project"]["id"]` when the contract parsed and carries it, else `None`; `subject.root` is `str(context.root)`; `subject.revision` comes from `bounded_run(["git", "-C", str(root), "rev-parse", "HEAD"])` — the 40-hex stdout when the child returns 0 and the output matches, otherwise `None` (D19, D23). `request.platform_target` is `f"{platform.system()}/{platform.machine()}"`, the same two values `subject.platform` carries (D14). `repairs` is built from the emitted checks' non-null `repair_id` values, deduplicated and sorted, each looked up in `REPAIRS` — a `repair_id` absent from `REPAIRS` raises `KeyError` rather than emitting a partial repair.

Outcome precedence and `primary_check_id` are computed exactly as the plan root states.

## The resolver ladder evaluator (D2, D17)

```python
RESOLVER_NAMES = ("resolve-project.py", "resolve_project.py", "resolve-project")


def load_resolver():
    """The sibling resolver module, loaded by path through SourceFileLoader.

    Tried in RESOLVER_NAMES order so an extensionless Nix-installed link loads
    identically to the repository file (D2). Its main() is __main__-guarded, so
    import defines functions and runs nothing.
    """
```

Implement with `importlib.util.spec_from_loader("conformance_resolve_project", SourceFileLoader(name, str(path)))` for the first sibling path that `is_file()`, then `module_from_spec` + `exec_module`. If none exists, raise `RuntimeError` naming the directory searched. Memoise in a module-level global.

`check_contract_resolvable(context)` is the **only** place the ladder runs:

```
try:
    root = resolver.discover_root(str(context.root))       -> stage "present"
    source = resolver.load_contract(root)
    context.contract = source
    violations = []
    resolver.validate_schema_version(source, violations)   -> stage "schema_supported"
    violations += resolver.validate_contract(source)
    resolver.raise_for_violations(dedup(violations))       -> stage "valid"
    context.bindings = resolver.normalize_bindings(source["bindings"], root)
    context.capabilities = resolver.compute_capabilities(
        context.bindings, root, source["capabilities"])
    resolver.validate_projections(root, source)            -> stage "projection_fresh"
    resolver.raise_for_unavailable(list(context.required), context.capabilities)
                                                           -> stage "capability_required"
except resolver.ContractError as err:
    record err against the stage its err.code names; every later stage stays None
except Exception:
    return Outcome("failed", "resolver_failure", "conformance.internal",
                   {"stage": <the last stage name attempted>})
```

Record each successfully completed stage as `Outcome("passed")` in `context.stages`; record the stage a `ContractError` names as `Outcome("failed", err.code, <that stage's repair id>, {"violations": <count>, "first_pointer": <err.violations[0]["pointer"]>})`. `first_pointer` is a contract JSON pointer, never a filesystem path, so the bounded-`facts` string limit is never in question. A stage that was never reached keeps `None`.

`validate_schema_version` appends to `violations` for a *malformed* version and raises only for an unsupported integer, so call it before `validate_contract` and pass the same list; `validate_contract` calls it again internally, so deduplicate the collected violations by `(pointer, message)` before `raise_for_violations` (the resolver publishes the first in pointer order, so duplicates would otherwise inflate the count fact).

On success `check_contract_resolvable` returns `Outcome("passed")`.

Each of the five dependent structural checks is a two-line evaluator reading `context.stages[<stage>]`: `Outcome("passed")` when the stage passed, the recorded failed `Outcome` when it failed, and `Outcome("not_run", "<stage>_not_reached")`— never reachable while suppression is in force, so instead raise `ValueError` on a `None` stage, since reaching a dependent whose ancestor did not run is a control-flow bug (the bar, *Fail loud*).

`host.capability.required` passes vacuously when `context.required` is empty — `raise_for_unavailable(None-or-[], …)` returns immediately.

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_conformance.py`. Add a fixture helper first: `make_root(tmp)` copies `REPO_ROOT/".agents/project.json"` into `<tmp>/.agents/project.json`, copies `.agents/instructions/bootstrap.md`, `AGENTS.md` and `CLAUDE.md`, and creates `home/common/agent-skills/standards/` and an empty `CLAUDE.md`-adjacent tree so the knowledge paths exist; it returns the root `Path`. `read_report(code, out)` asserts `code` then returns `json.loads(out)`.

```python
class RunReportShapeTest(ReportAssertions, unittest.TestCase):
    """AC1: both purposes emit a schema-valid report, differing in shape."""

    def test_doctor_on_a_clean_root_is_schema_valid_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, err = run("run", "--purpose", "doctor", "--repo-root", str(root))
            self.assertEqual(code, 0, err)
            report = json.loads(out)
            self.assertEqual(sorted(report), ["checks", "outcome", "repairs",
                                              "request", "schema_version", "subject"])
            self.assertEqual(report["schema_version"], 1)
            self.assertGreater(len(report["checks"]), 1)
            self.assertEqual([c["id"] for c in report["checks"]],
                             sorted(c["id"] for c in report["checks"]))
            self.assert_validates(report)

    def test_workflow_entry_on_a_broken_contract_is_one_root_cause(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            (root / "AGENTS.md").write_text("drifted\n", encoding="utf-8")
            code, out, err = run("run", "--purpose", "workflow_entry",
                                 "--repo-root", str(root))
            self.assertEqual(code, 2, err)
            report = json.loads(out)
            self.assertEqual(len(report["checks"]), 1)
            self.assertEqual(len(report["repairs"]), 1)
            check = report["checks"][0]
            self.assertEqual(check["id"], "repository.projection.fresh")
            self.assertEqual(check["reason_code"], "invalid_projection")
            self.assertEqual(check["repair_id"], "projection.regenerate")
            self.assertEqual(report["outcome"]["status"], "failed")
            self.assertEqual(report["outcome"]["primary_check_id"],
                             "repository.projection.fresh")
            self.assertEqual(report["repairs"][0]["safety_class"], "worktree")
            self.assertEqual(report["repairs"][0]["operation"],
                             {"subcommand": "write-projections", "args": []})
            self.assert_validates(report)

    def test_doctor_on_the_same_broken_contract_exits_zero_with_many_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            (root / "AGENTS.md").write_text("drifted\n", encoding="utf-8")
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root))
            self.assertEqual(code, 0)
            report = json.loads(out)
            self.assertGreater(len(report["checks"]), 1)
            self.assertEqual(report["outcome"]["status"], "failed")


class NotOnboardedTest(unittest.TestCase):
    """D23: identity is null rather than fabricated when the ladder cannot supply it."""

    def test_missing_contract_reports_not_onboarded_with_null_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = run("run", "--purpose", "workflow_entry", "--repo-root", tmp)
            self.assertEqual(code, 2)
            report = json.loads(out)
            self.assertEqual(report["checks"][0]["id"], "repository.contract.present")
            self.assertEqual(report["checks"][0]["reason_code"], "not_onboarded")
            self.assertIsNone(report["subject"]["project_id"])
            self.assertIsNone(report["subject"]["revision"])
            self.assertEqual(report["subject"]["root"], str(Path(tmp).resolve()))

    def test_doctor_suppresses_the_cascade_below_a_missing_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", tmp)
            self.assertEqual(code, 0)
            report = json.loads(out)
            by_id = {c["id"]: c for c in report["checks"]}
            self.assertEqual(by_id["repository.contract.present"]["status"], "failed")
            downstream = by_id["compatibility.contract.schema_supported"]
            self.assertEqual(downstream["status"], "suppressed")
            self.assertEqual(downstream["facts"],
                             {"suppressed_by": "repository.contract.present"})
            self.assertIsNone(downstream["repair_id"])
            self.assertEqual(report["outcome"]["primary_check_id"],
                             "repository.contract.present")


class RequiredCapabilityTest(unittest.TestCase):
    def test_requiring_an_unsupported_capability_fails_the_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, _ = run("run", "--purpose", "workflow_entry",
                               "--repo-root", str(root), "--require", "release")
            self.assertEqual(code, 2)
            report = json.loads(out)
            self.assertEqual(report["checks"][0]["id"], "host.capability.required")
            self.assertEqual(report["checks"][0]["reason_code"], "capability_unavailable")
            self.assertEqual(report["request"]["required_capabilities"], ["release"])

    def test_require_deduplicates_and_sorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, _ = run("run", "--purpose", "doctor", "--repo-root", str(root),
                               "--require", "worktrees", "--require", "tracker",
                               "--require", "worktrees")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["request"]["required_capabilities"],
                             ["tracker", "worktrees"])

    def test_unknown_require_name_is_an_argparse_error(self):
        code, out, err = run("run", "--purpose", "doctor", "--require", "teleport")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("usage:", err)


class ReadOnlyTest(unittest.TestCase):
    def test_run_writes_nothing_under_the_subject_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            before = sorted((str(p.relative_to(root)), p.is_dir(),
                             None if p.is_dir() else p.stat().st_mtime_ns)
                            for p in root.rglob("*"))
            self.assertEqual(run("run", "--purpose", "doctor",
                                 "--repo-root", str(root))[0], 0)
            after = sorted((str(p.relative_to(root)), p.is_dir(),
                            None if p.is_dir() else p.stat().st_mtime_ns)
                           for p in root.rglob("*"))
            self.assertEqual(before, after)
```

`assert_validates(report)` is a mixin method: it writes the report to a temp file and asserts `run("validate-report", "--input", path)` exits 0. Put it on a `ReportAssertions` base class both report suites inherit, so every task's report cases reuse it.

Also add the S3 case:

```python
class EngineFailureTest(unittest.TestCase):
    """S3: the top-level wrapper maps an unexpected exception to the closed code."""

    def test_unexpected_exception_becomes_resolver_failure(self):
        module = load_module()
        def boom(_root):
            raise RuntimeError("boom")
        module.load_resolver().discover_root = boom
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["run", "--purpose", "doctor", "--repo-root", "/"])
        self.assertEqual(code, 2)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["error"]["code"], "resolver_failure")
        self.assertEqual(payload["error"]["repair_id"], "conformance.internal")
```

Add `load_module()` mirroring `test_resolve_project.py:557`, and import `contextlib` and `io`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py`
Expected: the Task 1 cases still pass; every new case fails with argparse `invalid choice: 'run'` on stderr and exit 2 with empty stdout.

- [ ] **Step 3: Write the minimal implementation**

Add to `home/common/agent-skills/scripts/conformance.py`, in this order: `load_resolver`, `bounded_run`, the `Check`/`Outcome`/`Context` dataclasses, `REPAIRS`, the six evaluators, `REGISTRY`/`REGISTRY_BY_ID`, `WORKFLOW_ENTRY_LADDER`/`PURPOSE_DOMAINS`/`select`, `evaluate`, `build_report`, `command_run`.

`command_run(args)`:

```python
def command_run(args: argparse.Namespace) -> int:
    """Contract: prints one schema-valid report and returns 0, or 2 for a
    non-passing workflow_entry; any unexpected exception becomes the closed
    resolver_failure refusal with no report printed (D15)."""
```

Body: build the `Context` (root is `Path(args.repo_root or ".").resolve()`, D23); call `evaluate`; call `build_report`; call `validate_report` on the result; `emit_json`; return `2` if `args.purpose == "workflow_entry" and report["outcome"]["status"] != "passed"` else `0`. Wrap the whole body in `try/except Exception as err` returning `emit_error("resolver_failure", "conformance.internal", [{"pointer": "", "message": <the exception class name and str(err), truncated to 200 characters>}])` — the exception text may name a path, so truncate it, and never print a traceback to stdout.

Register the `run` subparser with `--purpose` (required, `choices=PURPOSES`), `--repo-root` (optional PATH), `--offline` (`action="store_true"`), and `--require` (`action="append"`, `default=[]`, `choices=load_resolver().CAPABILITY_NAMES`, `metavar="CAPABILITY"`). `--offline` is recorded verbatim into `request.offline` and consumed by no check in this task; the rule that reads it arrives with the first network-flagged check (D21).

- [ ] **Step 4: Verify**

```bash
python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py
just agent-workflow-tests
cd "$(mktemp -d)" && git init -q . >/dev/null && cd - >/dev/null
python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root . | python3 -m json.tool | head -20
python3 home/common/agent-skills/scripts/conformance.py run --purpose workflow_entry --repo-root .; echo "entry exit: $?"
```

Expected: unittest OK; `just agent-workflow-tests` passes; `doctor` on this repository prints a report whose `outcome.status` is `passed`; `workflow_entry` on this repository prints a six-check passing report and `entry exit: 0`.

Falsifiability at the base commit: `run --purpose doctor` exits 2 with argparse `invalid choice: 'run'`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/conformance.py \
        home/common/agent-skills/tests/test_conformance.py
git commit -m "$(cat <<'MSG'
feat(conformance): resolve the structural ladder into a purpose-selected report

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
MSG
)"
```
