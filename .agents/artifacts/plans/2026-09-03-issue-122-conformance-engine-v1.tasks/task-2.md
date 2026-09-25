# Task 2: The engine core — ladder, registry, purposes, and the two report shapes

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`

**Interfaces:**
- Consumes from Task 1: the closed vocabulary tuples, `validate_report`, `ReportError`, `bound_fact`, `bound_facts`, `emit_json`, `emit_error`, `build_parser`, `dispatch`, `main`, and the test helpers `run`, `fixture`, `doctor`, `make_stub_bin`, `HERMETIC_ENV`.
- Produces, for Tasks 3–7:
  - `def load_resolver()` — the imported `resolve-project` module, memoised in a module global.
  - `class Check` — `dataclasses.dataclass(frozen=True)`: `id`, `domain`, `subject_kind`, `requirement`, `depends_on: tuple[str, ...]`, `findings: tuple[tuple[str, str], ...]`, `run: str`. `findings` is the declaration-ordered `(reason_code, repair_id)` mapping — the single source for what the check may emit (D31). `run` names the evaluator, looked up with `getattr`.
  - `Check.reason_codes` (property over `findings`) and `def repair_ids_for(check) -> tuple[str, ...]` (its sorted distinct repair ids).
  - `REGISTRY: tuple[Check, ...]` in dependency order; `REGISTRY_BY_ID: dict[str, Check]`.
  - `REPAIRS: dict[str, dict]` — `repair_id` → `{"module", "safety_class", "operation"}`.
  - `class Outcome` — `status`, `reason_code=None`, `repair_id=None`, `facts=None`.
  - `class Context` — `root: Path`, `root_arg: str | None`, `offline: bool`, `required: tuple[str, ...]`, `resolver`, `stages: dict[str, Outcome | None]`, `contract`, `bindings`, `capabilities`.
  - `evaluate(purpose, context) -> list[dict]`, `build_report(purpose, context, checks) -> dict`, `select(purpose) -> tuple[Check, ...]`.
  - `bounded_run(argv, cwd, env=None)` — read-only child, `timeout=15`, `capture_output=True`, `text=True`; returns `None` on `OSError`/`subprocess.SubprocessError` (D19).
  - `ENGINE_FAILURE_MESSAGE = "the conformance engine failed unexpectedly"`.
- Later tasks extend `REGISTRY` and `REPAIRS` and add evaluators; they do not edit `select` or `build_report`. **Task 4 alone extends `evaluate`**, with the offline rule D21 requires to arrive alongside the first network-flagged check rather than ahead of it.

**Invariants:**
- The ladder runs **at most once per process**, inside `repository.contract.resolvable`; every other structural check is a pure read of the cached stages (D17).
- After `check_contract_resolvable` returns, **no stage is `None`** (D33). A dependent evaluator that still finds one raises: that is a control-flow bug, not a finding.
- `checks` is emitted sorted by `id`; evaluation order is `REGISTRY` order, which is topological (D24).
- Every emitted report satisfies `validate_report` — asserted in `command_run` before printing.
- `workflow_entry` emits exactly one check and at most one repair when the outcome is not `passed`, and exits 2. Every other purpose exits 0.
- The root's evaluator-return rule (D32) and its one fact-bounding helper pair (D30) hold for every evaluator here.

## The registry entries this task adds

Dependency order — `REGISTRY` order is *not* id order (D24):

| # | Id | Domain | Subject kind | Depends on | `findings`: reason code → repair id | Repair module, class |
|---|---|---|---|---|---|---|
| 1 | `repository.contract.resolvable` | repository | contract | — | `resolver_failure` → `conformance.internal` | conformance, `user_action` |
| 2 | `repository.contract.present` | repository | contract | 1 | `not_onboarded` → `onboarding.contract.missing` | resolve-project, `user_action` |
| 3 | `compatibility.contract.schema_supported` | compatibility | contract | 2 | `unsupported_schema` → `contract.schema.unsupported` | resolve-project, `user_action` |
| 4 | `repository.contract.valid` | repository | contract | 3 | `invalid_contract` → `contract.invalid` | resolve-project, `user_action` |
| 5 | `repository.projection.fresh` | repository | projection | 4 | `invalid_projection` → `projection.regenerate` | resolve-project, `worktree`, operation `{"subcommand": "write-projections", "args": []}` |
| 6 | `host.capability.required` | host | capability | 4 | `capability_unavailable` → `capability.required.unavailable` | resolve-project, `user_action` |

All six are `required`. Every repair carries `operation: None` except `projection.regenerate`.

## The registry declares its own repairs (D31)

`findings` is the one authoritative mapping; three consumers derive from it and none restates it. The **evaluation guard** (`evaluate` step 5) requires `repair_id is None` when `reason_code is None`, and otherwise requires `(reason_code, repair_id)` to be a member of that entry's `findings`, raising `ValueError` on anything else — an evaluator emitting a code or repair its declaration does not name is a bug, not a finding. **`build_report`** looks the emitted `repair_id` up in `REPAIRS`, the guard having already proved it declared. **`repair_ids_for(check)`** answers the closure test from `findings`, never a second table.

## Purpose selection (D4, D5, D21)

```python
WORKFLOW_ENTRY_LADDER = (
    "repository.contract.resolvable", "repository.contract.present",
    "compatibility.contract.schema_supported", "repository.contract.valid",
    "repository.projection.fresh", "host.capability.required",
)
PURPOSE_DOMAINS = {
    "adoption": ("repository", "compatibility"),
    "ci":       ("repository", "compatibility", "verification"),
    "fleet":    ("repository", "compatibility"),
    "doctor":   DOMAINS,
}
```

`select(purpose)` returns, in `REGISTRY` order: for `workflow_entry`, the `WORKFLOW_ENTRY_LADDER` entries; for `local`, those **plus** every `host`-domain entry, deduplicated (`host.capability.required` is in both); for a `PURPOSE_DOMAINS` key, every entry whose `domain` is in that tuple; otherwise `raise ValueError(f"unknown purpose: {purpose!r}")`. Selection is by domain, never a hand-maintained id list, so Tasks 3–7 are additive (D21).

## Evaluation

`evaluate(purpose, context)`:

1. Walk `select(purpose)` in order, keeping `results: dict[str, Outcome]`.
2. If any ancestor in the entry's `depends_on` closure over the *selected* set is `failed`, the result is `Outcome("suppressed", facts={"suppressed_by": <first such ancestor in REGISTRY order>})` and no evaluator runs.
3. Otherwise call `getattr(module, entry.run)(context)`.
4. **`workflow_entry` stops** at the first result whose status is `failed` or `not_run`, and `evaluate` returns exactly that one check (D3). `suppressed` is **not** a stopping status: it reports something the ladder skipped, never the root cause. If every entry passes it returns all six.
5. Apply the `findings` guard above.
6. Return the check objects sorted by `id`.

`build_report(purpose, context, checks)` assembles the six members. `subject.project_id` is `context.contract["project"]["id"]` when the contract parsed, else `None`; `subject.root` is `str(context.root)` — the root the ladder discovered, which is why `build_report` runs after `evaluate` (D28); `subject.revision` is the 40-hex stdout of `bounded_run(["git", "-C", str(root), "rev-parse", "HEAD"])` when the child returns 0 and the output matches, else `None` (D19, D23). `request.platform_target` is `f"{platform.system()}/{platform.machine()}"`, the two values `subject.platform` carries (D14). `repairs` is the emitted checks' non-null `repair_id` values, deduplicated, sorted, each looked up in `REPAIRS`. Outcome precedence and `primary_check_id` are exactly as the plan root states.

## The resolver ladder evaluator (D2, D17, D28, D33)

`RESOLVER_NAMES = ("resolve-project.py", "resolve_project.py", "resolve-project")`. `load_resolver()` takes the first sibling path that `is_file()`, builds `importlib.util.spec_from_loader("conformance_resolve_project", SourceFileLoader(name, str(path)))`, then `module_from_spec` + `exec_module`, and memoises the result; with none present it raises `RuntimeError` naming the directory searched. Its docstring says the names are tried in that order so an extensionless Nix-installed link loads identically to the repository file (D2), and that the resolver's `main()` is `__main__`-guarded.

`check_contract_resolvable(context)` is the **only** place the ladder runs:

```
try:
    root = resolver.discover_root(context.root_arg)         -> stage "present"
    context.root = root
    source = resolver.load_contract(root)
    context.contract = source
    violations = []
    resolver.validate_schema_version(source, violations)    -> stage "schema_supported"
    violations += resolver.validate_contract(source)
    resolver.raise_for_violations(dedup(violations))        -> stage "valid"
    context.bindings = resolver.normalize_bindings(source["bindings"], root)
    context.capabilities = resolver.compute_capabilities(
        context.bindings, root, source["capabilities"])
    resolver.validate_projections(root, source)             -> stage "projection_fresh"
    resolver.raise_for_unavailable(list(context.required), context.capabilities)
                                                            -> stage "capability_required"
except resolver.ContractError as err:
    settle(err)
except Exception:
    suppress every stage still None under "repository.contract.resolvable"
    return Outcome("failed", "resolver_failure", "conformance.internal",
                   {"stage": <last stage attempted>})
```

**`context.root_arg` is `args.repo_root` verbatim, `None` when the flag was omitted.** The live resolver walks ancestors only for `None` and treats any given path as the root (D28, and the root constraint it amends). `context.root` starts at `Path(args.repo_root).resolve()` or `Path.cwd().resolve()` and is replaced by the discovered root as soon as `discover_root` returns, so `subject.root` names the project rather than the caller's directory.

**`settle(err)` is the complete stage state machine (D33).** The resolver raises codes from call sites the ladder order does not predict — `load_contract` raises `invalid_contract` before the schema stage has run at all, and `validate_projections` raises it for an unreadable projection source — so `settle` dispatches on `err.code`, never on which call raised:

| `err.code` | Stage recorded `failed` | Check that names it |
|---|---|---|
| `not_onboarded` | `present` | `repository.contract.present` |
| `unsupported_schema` | `schema_supported` | `compatibility.contract.schema_supported` |
| `invalid_contract` | `valid` | `repository.contract.valid` |
| `invalid_projection` | `projection_fresh` | `repository.projection.fresh` |
| `capability_unavailable` | `capability_required` | `host.capability.required` |
| anything else | — | the check itself fails `resolver_failure` |

`settle` records the named stage as `Outcome("failed", err.code, <that stage's repair id>, {"violations": <count>, "first_pointer": bound_fact(err.violations[0]["pointer"])})`, **overwriting a `passed` recording when the code names an earlier stage**, and sets *every stage still `None`* — those before it in ladder order as well as those after — to `Outcome("suppressed", facts={"suppressed_by": <the failing stage's check id>})`.

The "before it as well" clause is the whole fix for the parse hole: an unparseable contract fails `valid` while `schema_supported` never ran, so that stage becomes `suppressed` by `repository.contract.valid` instead of staying `None`, and `workflow_entry` — which does not stop on `suppressed` — walks on to the one true root cause.

Each of the five dependent structural checks is then a one-line evaluator returning `context.stages[<stage>]`, raising `ValueError` on a `None` (the bar, *Fail loud*).

`validate_schema_version` appends to `violations` for a *malformed* version and raises only for an unsupported integer, so call it before `validate_contract` with the same list; `validate_contract` calls it again internally, so deduplicate by `(pointer, message)` before `raise_for_violations` or the count fact inflates. On success the check returns `Outcome("passed")` with every stage `passed`. `host.capability.required` passes vacuously when `context.required` is empty.

## The one exception boundary (D15, D29)

Amend Task 1's `main` so resolver loading, parser construction and dispatch sit inside a single boundary:

```python
def main(argv: list[str] | None = None) -> int:
    try:
        return dispatch(build_parser().parse_args(argv))
    except SystemExit:
        raise                      # argparse usage: exit 2, no JSON
    except Exception:
        return emit_error("resolver_failure", "conformance.internal",
                          [{"pointer": "", "message": ENGINE_FAILURE_MESSAGE}])
```

`build_parser` is inside it because `--require`'s `choices` come from `load_resolver().CAPABILITY_NAMES`, so a resolver that will not load refuses in the D15 shape rather than tracebacking. The message is the **fixed sentence**, never `str(err)`, which can name a path (D29). `command_run` carries no `try/except Exception` of its own.

The single declared exception is the ladder's catch inside `check_contract_resolvable` (D17): a failure *of the resolver* is a check finding carrying `resolver_failure`; a failure of anything else in the engine is the refusal. `EngineFailureTest` pins both halves.

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_conformance.py`. Add `make_root(tmp)`: copy `REPO_ROOT/.agents/project.json` to `<tmp>/.agents/project.json`, copy `.agents/instructions/bootstrap.md`, `AGENTS.md` and `CLAUDE.md`, and create every knowledge and standards directory the contract declares, so a clean fixture genuinely passes. Return the root `Path`.

```python
class RunReportShapeTest(ReportAssertions, unittest.TestCase):
    """AC1: both purposes emit a schema-valid report, differing in shape."""

    def test_doctor_on_a_clean_root_is_schema_valid_and_exits_zero(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            self.assertEqual(sorted(report), ["checks", "outcome", "repairs",
                                              "request", "schema_version", "subject"])
            self.assertGreater(len(by_id), 1)
            self.assertEqual([c["id"] for c in report["checks"]], sorted(by_id))
            self.assert_validates(report)

    def test_workflow_entry_on_a_broken_projection_is_one_root_cause(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / "AGENTS.md").write_text("drifted\n", encoding="utf-8")
            code, out, err = run("run", "--purpose", "workflow_entry",
                                 "--repo-root", str(root))
            self.assertEqual(code, 2, err)
            report = json.loads(out)
            self.assertEqual([len(report["checks"]), len(report["repairs"])], [1, 1])
            check, repair = report["checks"][0], report["repairs"][0]
            self.assertEqual(
                [check["id"], check["subject_kind"], check["status"],
                 check["reason_code"], check["repair_id"]],
                ["repository.projection.fresh", "projection", "failed",
                 "invalid_projection", "projection.regenerate"])
            self.assertEqual(report["outcome"], {
                "status": "failed",
                "primary_check_id": "repository.projection.fresh"})
            self.assertEqual(repair["safety_class"], "worktree")
            self.assertEqual(repair["operation"],
                             {"subcommand": "write-projections", "args": []})
            self.assert_validates(report)


class ContractParseFailureTest(ReportAssertions, unittest.TestCase):
    """D33: a parse refusal fills every stage; no evaluator faces a None."""

    def broken(self, tmp):
        root = make_root(tmp)
        (root / ".agents/project.json").write_text("{ broken", encoding="utf-8")
        return root

    def test_doctor_fails_valid_and_suppresses_the_unreached_schema_stage(self):
        with fixture() as tmp:
            report, by_id = doctor(self, self.broken(tmp))
            self.assertEqual(by_id["repository.contract.valid"]["reason_code"],
                             "invalid_contract")
            schema = by_id["compatibility.contract.schema_supported"]
            self.assertEqual(
                [schema["status"], schema["facts"], schema["repair_id"]],
                ["suppressed", {"suppressed_by": "repository.contract.valid"}, None])
            self.assertEqual(report["outcome"]["primary_check_id"],
                             "repository.contract.valid")
            self.assert_validates(report)

    def test_workflow_entry_walks_past_the_suppressed_stage_to_the_root_cause(self):
        with fixture() as tmp:
            code, out, err = run("run", "--purpose", "workflow_entry",
                                 "--repo-root", str(self.broken(tmp)))
            self.assertEqual(code, 2, err)
            report = json.loads(out)
            self.assertEqual(len(report["checks"]), 1)
            self.assertEqual(report["checks"][0]["id"], "repository.contract.valid")
            self.assert_validates(report)


class NotOnboardedTest(unittest.TestCase):
    """D23, D28: identity is null rather than fabricated; the root is discovered."""

    def test_missing_contract_reports_not_onboarded_with_null_identity(self):
        with fixture() as tmp:
            code, out, _ = run("run", "--purpose", "workflow_entry",
                               "--repo-root", str(tmp))
            self.assertEqual(code, 2)
            report = json.loads(out)
            self.assertEqual(report["checks"][0]["reason_code"], "not_onboarded")
            self.assertEqual(
                [report["subject"]["project_id"], report["subject"]["revision"],
                 report["subject"]["root"]], [None, None, str(tmp.resolve())])

    def test_doctor_suppresses_the_cascade_below_a_missing_contract(self):
        with fixture() as tmp:
            report, by_id = doctor(self, tmp)
            self.assertEqual(by_id["repository.contract.present"]["status"], "failed")
            downstream = by_id["compatibility.contract.schema_supported"]
            self.assertEqual(
                [downstream["status"], downstream["facts"]],
                ["suppressed", {"suppressed_by": "repository.contract.present"}])
            self.assertEqual(report["outcome"]["primary_check_id"],
                             "repository.contract.present")

    def test_omitting_repo_root_discovers_the_root_from_a_nested_directory(self):
        """D28: no --repo-root means the resolver's ancestor walk, not the cwd."""
        with fixture() as tmp:
            root = make_root(tmp)
            code, out, err = run("run", "--purpose", "doctor",
                                 cwd=root / ".agents/instructions")
            self.assertEqual(code, 0, err)
            report = json.loads(out)
            self.assertEqual(
                [report["subject"]["root"], report["subject"]["project_id"]],
                [str(root.resolve()), "fagenorn/nix-config"])


class PurposeSelectionTest(unittest.TestCase):
    """SF-002: structural rules for all six purposes; Task 7 pins the exact ids."""

    def test_every_purpose_is_duplicate_free_and_dependency_closed(self):
        module = load_module()
        for purpose in module.PURPOSES:
            with self.subTest(purpose=purpose):
                ids = [check.id for check in module.select(purpose)]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(
                    ids, [c.id for c in module.REGISTRY if c.id in set(ids)])
                for check in module.select(purpose):
                    for dependency in check.depends_on:
                        self.assertIn(dependency, ids, f"{purpose}: {check.id}")

    def test_an_unknown_purpose_raises(self):
        with self.assertRaises(ValueError):
            load_module().select("teleport")
```

`RequiredCapabilityTest` covers the `--require` surface in three cases, all through the same helpers: requiring `release` on a clean fixture makes `workflow_entry` exit 2 with `host.capability.required` / `capability_unavailable` as its one check and `["release"]` in `request.required_capabilities`; `--require worktrees --require tracker --require worktrees` on `doctor` emits `["tracker", "worktrees"]`, deduplicated, sorted and a subset of `load_module().load_resolver().CAPABILITY_NAMES`; and `--require teleport` exits 2 with `usage:` on stderr and empty stdout, the argparse channel rather than a JSON refusal.

`ReadOnlyTest` (SF-003) adopts the resolver suite's three-witness pattern. It builds a fixture root, initialises a throwaway git repository in it (`git init -q`, `git add -A`, `git -c commit.gpgsign=false commit -q -m fixture`), records `git status --porcelain`, a `snapshot(root)` of `sorted((relative path, is_dir, st_mtime_ns))` over `root.rglob("*")` excluding `.git`, and `root.stat().st_mtime_ns`; runs `doctor`; and asserts all three are byte-identical afterwards.

Each witness catches what the others miss: `git status --porcelain` a tracked-content or index change, the recursive path/type set a created empty directory, and the mtimes — of **directories and of the root itself**, not only of files — a rewrite with identical bytes and a create-then-delete cycle that leaves the path set unchanged. Only the engine subprocess is hermetic; the fixture's own `git` calls use the caller's environment, and `commit.gpgsign=false` here is bookkeeping in a throwaway temp repository, never a plan commit.

`assert_validates(report)` is a mixin on a `ReportAssertions` base class both report suites inherit: it writes the report to a temp file and asserts `run("validate-report", "--input", path)` exits 0.

Also add the S3 cases, importing `contextlib` and `io`:

```python
class EngineFailureTest(unittest.TestCase):
    """S3: the boundary refuses; the ladder's declared catch does not (D17, D29).

    Both cases pass --offline, and every later S3 case calling main must: in
    process there is no hermetic runner, so evaluate's offline rule is what
    keeps Task 4's network check from spawning a child (D35).
    """

    def rebind(self, owner, name, value):
        original = getattr(owner, name)
        self.addCleanup(setattr, owner, name, original)
        setattr(owner, name, value)

    def test_an_unexpected_engine_exception_becomes_the_refusal(self):
        module = load_module()
        self.rebind(module, "build_report", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("sentinel-exception-detail")))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["run", "--purpose", "doctor", "--offline",
                                "--repo-root", str(REPO_ROOT)])
        self.assertEqual(code, 2)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["error"]["code"], "resolver_failure")
        self.assertEqual(payload["error"]["repair_id"], "conformance.internal")
        self.assertEqual([v["message"] for v in payload["error"]["violations"]],
                         [module.ENGINE_FAILURE_MESSAGE])
        self.assertNotIn("sentinel-exception-detail", buf.getvalue())

    def test_a_resolver_exception_is_a_check_finding_not_the_refusal(self):
        module = load_module()
        self.rebind(module.load_resolver(), "discover_root",
                    lambda _arg: (_ for _ in ()).throw(RuntimeError("boom")))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = module.main(["run", "--purpose", "doctor", "--offline",
                                "--repo-root", "/"])
        self.assertEqual(code, 0)
        check = {c["id"]: c for c in json.loads(buf.getvalue())["checks"]}[
            "repository.contract.resolvable"]
        self.assertEqual([check["status"], check["reason_code"]],
                         ["failed", "resolver_failure"])
```

Add `load_module()`. **It must register the module in `sys.modules` before `exec_module` (D36).** The engine uses postponed annotations, so dataclass construction resolves every field annotation through `sys.modules[cls.__module__].__dict__`; unregistered, that lookup returns `None` and the import dies with `AttributeError` before any test reaches its seam. Use **one** stable fullname for the `SourceFileLoader`, the spec and the registration; `exec_module` inside a `try` whose `except BaseException` pops the name again and re-raises, so a failed load leaves `sys.modules` clean:

```python
def load_module():
    """The engine as an imported module, loaded by path (its name is hyphenated).

    Registered under its spec name before exec_module: the module uses
    postponed annotations, and dataclass construction resolves them through
    sys.modules, so an unregistered module fails to import at all (D36).
    """
```

Every S3 case that rebinds a module attribute restores it through `addCleanup`, so no case leaks state into the next.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py`
Expected: the Task 1 cases still pass; every new case fails with argparse `invalid choice: 'run'` on stderr and exit 2 with empty stdout, or with an error from `load_module()`.

- [ ] **Step 3: Write the minimal implementation**

Add to `conformance.py`, in this order: `load_resolver`, `bounded_run`, the `Check`/`Outcome`/`Context` dataclasses, `repair_ids_for`, `REPAIRS`, the six evaluators, `REGISTRY`/`REGISTRY_BY_ID`, `WORKFLOW_ENTRY_LADDER`/`PURPOSE_DOMAINS`/`select`, `evaluate`, `build_report`, `command_run`, and the amended `main`.

```python
def command_run(args: argparse.Namespace) -> int:
    """Contract: prints one schema-valid report and returns 0, or 2 for a
    non-passing workflow_entry. It catches nothing: an unexpected exception
    reaches main's single boundary and becomes the D15 refusal (D29)."""
```

Body: build the `Context` (`root_arg = args.repo_root`; `root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd().resolve()`, D23, D28); `evaluate`; `build_report`; `validate_report`; `emit_json`; return `2` if `args.purpose == "workflow_entry" and report["outcome"]["status"] != "passed"` else `0`.

Register the `run` subparser with `--purpose` (required, `choices=PURPOSES`), `--repo-root` (optional PATH, **default `None`** so an omitted flag stays distinguishable from `"."`), `--offline` (`action="store_true"`), and `--require` (`action="append"`, `default=[]`, `choices=load_resolver().CAPABILITY_NAMES`, `metavar="CAPABILITY"`). `--offline` is recorded verbatim into `request.offline` and consumed by no check in this task; the rule that reads it arrives with the first network-flagged check (D21).

- [ ] **Step 4: Verify**

```bash
python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py
just agent-workflow-tests
python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root . | python3 -m json.tool | head -20
(cd .agents/instructions && python3 "$OLDPWD/home/common/agent-skills/scripts/conformance.py" run --purpose doctor \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["subject"]["root"])')
python3 home/common/agent-skills/scripts/conformance.py run --purpose workflow_entry --repo-root .; echo "entry exit: $?"
```

Expected: unittest OK; `just agent-workflow-tests` passes; `doctor` on this repository prints a report whose `outcome.status` is `passed`; the nested-directory run with no `--repo-root` prints this repository's root, not `.agents/instructions` (D28); `workflow_entry` prints a six-check passing report and `entry exit: 0`.

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
