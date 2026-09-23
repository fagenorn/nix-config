# Task 2: Stdin inputs and the builder verb's contract, intent and scope kinds

Decisions: D3, D4, D5, D6, D19, D21, D22, D23, D27. Spec §1 (the whole
"delivery builder" section) is this task's derivation contract; read it first.

**Files:**
- Create: `S/workflow_delivery_build.py`
- Modify: `S/delivery_model/_objects.py`, `S/delivery_model/__init__.py` (export `STAGE_ACTIONS`)
- Modify: `S/workflow_delivery.py` (load the builder; `build_delivery`)
- Modify: `S/workflow-state.py` (`read_input_bytes`, every input flag, `build-delivery` verb, resolver lookup)
- Modify: `home/common/agent-skills/default.nix` (install the build module)
- Modify: `CLAUDE.md` (one bullet, below)
- Test: `T/test_delivery_workflow.py`, `T/test_delivery_model.py` (facade pin), `T/test_workflow_state.py` only if a message pin moves

**Interfaces:**
- Consumes: Task 1's slot `pr_ref` grammar.
- Produces (later tasks rely on these exact names):
  - CLI `workflow-state build-delivery --repo-root <abs> --kind <contract|initial-intent|scope> --input <abs-path|->`
    (Task 3 adds `selected-output`, `observation`, `authority-observation` to the same closed choice set).
  - Outputs: `contract` → `{"contract": <delivery-contract/v1>, "initial_intent": <authorization-intent/v1>}`;
    `initial-intent` → the intent; `scope` → one `scope-tuple/v1`. Bytes are `model.canonical_bytes(value)`.
  - `S/workflow_delivery_build.py`: `WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION = 1`,
    `class DeliveryBuilder(model, *, notes_max_characters)` with
    `build(kind: str, value: object, *, policy: dict | None) -> object` (pure: no I/O,
    no clock, no imports beyond stdlib); private `_contract_facts(contract)` returning
    `(project, issue, branch, base, worktree)` and `_scope(contract, stage)` shared by
    every kind.
  - `DeliveryRuntime.build_delivery(kind, value, *, policy)` (validates every output
    with `validate_delivery_object` before returning).
  - Model facade: `STAGE_ACTIONS`, a `types.MappingProxyType` over `_STAGE_ACTIONS`
    (`kind -> (action, effect, observation_kind)`), added to `__all__`.
  - `workflow-state.py`: `read_input_bytes(value: str, label: str) -> bytes` and
    `resolve_project_argv() -> list[str]`.
  - Test harness in `T/test_delivery_workflow.py`: `WORKTREE_NAME`, `LATER`, and
    mixin `BuilderHarness` with `project(mutate=None) -> Path` (sets `self.root`,
    `self.home`, `self.worktree`), `cli(*args, stdin=None, ok=True)`,
    `build(kind, value, *, ok=True)`, `contract_input(**changes)` and
    `control_request(issues, *, now=NOW, contracts=None, intents=None, worktrees=(), forge=None, max_parallel=2)`.

**Invariants:**
- `read_input_bytes`: `-` returns all of `sys.stdin.buffer`; a non-absolute value
  raises `WorkflowError(f"{label} file path must be absolute")`; an unreadable path
  raises `WorkflowError(f"cannot read {label} file: …")`. It is the only reader of
  `--request-file` (labels `control request`, `direct owner request`),
  `--checkpoint-file` (`checkpoint`), `--summary-file` (`summary`), `--result-file`
  (`result`) and `--input` (`builder input`); report bytes reach artifact-budget
  through `artifact_budget_validate(..., input_bytes=...)` (per D23).
- `build-delivery` never calls `transact`, `workflow_paths` or a lock, reads no
  clock, and writes nothing. It refuses (exit 2, empty stdout) on any unknown,
  missing or mistyped input key, an unknown kind, or a failed validation.
- Only `contract` reads policy. `resolve_project_argv()` picks, in order:
  `[sys.executable, <script dir>/resolve-project.py]` when that sibling exists (source),
  else `Path(__file__).parent / "resolve-project"` (installed `~/.agents/bin`), else
  `~/.agents/bin/resolve-project`; a non-zero exit, timeout (60 s) or non-object
  stdout is a refusal (per D27).
- Every kind taking a `contract` first validates it and regenerates its initial
  intent; a different id or digest refuses. A hand-built contract is therefore
  refused by every builder kind.
- Identical inputs give identical bytes; declared scopes (in the intent) and actual
  scopes (kind `scope`) come from the one `_scope` function (per D5).

**Derivation (per D4–D6; exact values):**
1. Input `contract`: exactly `issue` (int ≥ 1), `worktree` (absolute and equal to
   `os.path.normpath(worktree)`), `source_kind` (`explicit_user` or
   `standing_repository`; `parent_handoff` refuses), `source_reference` (non-empty
   string), `now` (`YYYY-MM-DDTHH:MM:SSZ`).
2. Policy: `project.id`; `bindings.tracker.kind` (must be `github`),
   `.repo_slug`; `bindings.vcs.branch_pattern`, `.worktree.prefix`,
   `.integration_branch`, `.merge.delete_branch` (bool). Any missing member refuses.
3. Branch = `PurePosixPath(worktree).name`. Build the accepted regex by splitting
   the pattern on `(<num>|<slug>)`, `re.escape`-ing literal parts, substituting
   `str(issue)` and `[a-z0-9][a-z0-9-]*`, and allowing an optional escaped prefix:
   `^(?:<prefix>)?<pattern>$`. No full match refuses.
4. Project = `{project_id, provider: tracker.kind, repository_id: repo_slug,
   repository_slug: repo_slug}`. Base = integration branch.
5. Stages, ids equal to kinds, each `depends_on` = `[previous id]` (first `[]`),
   `retryable: true`, action/effect from `STAGE_ACTIONS`:
   `select_reviewed_output, publish_branch, open_pr, merge_pr` (slot target,
   `matching_required`), `close_tracker` (literal `str(issue)`, `not_required`),
   `delete_remote_branch` only when `delete_branch` (literal branch,
   `not_required`), `remove_worktree` (literal worktree, `cleanup_target`),
   `delete_local_branch` (literal branch, `cleanup_target`).
6. Slot target: `{"kind":"slot","slot_id":"reviewed","subject_kind":"commit",
   "constraints":{**project, "branch", "base", "deliverable_class":"source",
   "data_ref":{"kind":"selected_output_slot","slot_id":"reviewed",
   "classification":"source","audience": canonical_digest({"repository": slug})}}}`.
7. Deliverable: `{"id": f"issue-{issue}", "summary": f"Deliver {slug}#{issue}",
   "obligations": all four "required"}`.
8. Provenance: `{"kind": source_kind, "reference": source_reference, "digest":
   canonical_digest({"policy": {"project_id", "tracker_kind", "repository_slug",
   "branch_pattern", "worktree_prefix", "integration_branch", "delete_branch"},
   "issue", "worktree", "source": {"kind", "reference"}}), "created_at": now}`.
9. `_scope(contract, stage)`: principal `{"kind":"issue_owner","stable_id":
   f"{project_id}#{issue}"}`; action/effect of the stage; `risk` = effect;
   `spend {"kind":"none"}`; endpoint `none` except `remove_worktree` →
   `{"kind":"literal","value": worktree}`; target = project members + `issue`,
   `branch`, `base` + `output_ref` (slot stages `{"kind":"slot","slot_id":"reviewed"}`,
   literal stages `none`) + `pr_ref` (`open_pr`/`merge_pr` the slot form, else
   `none`); `data` = the slot `data_ref` for slot stages, else `none`; sealed `id`.
   `_contract_facts` reads branch/base from the first slot stage's constraints and
   the worktree from the `remove_worktree` literal.
10. Intent: `predecessor_intent_id: null`, `source {kind, reference,
    evidence_digest: provenance.digest}`, `issued_at: created_at`, `expires_at:
    null`, `revocation_key: f"{project_id}#{issue}@{created_at}"`, one scope per
    stage sorted by id, sealed `id`; the contract carries its id and
    `canonical_digest(intent)`.

- [ ] **Step 1: Write the failing tests**

Add to `T/test_delivery_workflow.py` imports: `from .test_resolve_project import
CODEX_HEADER, MANAGED_LINE, git, make_home, source_contract`, then these
module-level definitions and classes:

```python
WORKTREE_NAME = "worktree-issue-171-delivery-contract-source"
LATER = "2026-09-21T00:10:00Z"


class BuilderHarness:
    """One synthetic resolvable project and a CLI driver shared by builder-backed tests."""

    def project(self, mutate=None):
        self.home = make_home(); self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.addCleanup(shutil.rmtree, self.root, True)
        git(self.root, "init", "--quiet")
        for name in ("home/common/agent-skills/standards", ".out-of-scope",
                     ".worktrees", ".agents/instructions"):
            (self.root / name).mkdir(parents=True)
        source = b"# invariants\n"
        (self.root / ".agents/instructions/bootstrap.md").write_bytes(source)
        contract = source_contract()
        if mutate is not None:
            mutate(contract)
        (self.root / ".agents/project.json").write_text(json.dumps(contract), encoding="utf-8")
        (self.root / "AGENTS.md").write_bytes(CODEX_HEADER.encode() + b"\n\n" + source)
        (self.root / "CLAUDE.md").write_text(f"# authored body\n{MANAGED_LINE}\n", encoding="utf-8")
        self.worktree = str(self.root / ".worktrees" / WORKTREE_NAME)
        return self.root

    def cli(self, *args, stdin=None, ok=True):
        completed = subprocess.run(
            [sys.executable, str(WORKFLOW), *map(str, args)], input=stdin,
            capture_output=True, check=False,
            env={**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"})
        if ok:
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        return completed

    def build(self, kind, value, *, ok=True):
        completed = self.cli("build-delivery", "--repo-root", self.root, "--kind", kind,
                             "--input", "-", stdin=json.dumps(value).encode(), ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def contract_input(self, **changes):
        value = {"issue": 171, "worktree": self.worktree, "source_kind": "explicit_user",
                 "source_reference": "invocation:/from-issue 171 --auto", "now": NOW}
        value.update(changes)
        return value

    def control_request(self, issues, *, now=NOW, contracts=None, intents=None,
                        worktrees=(), forge=None, max_parallel=2):
        def keyed(value):
            return {str(issue): copy.deepcopy(value) for issue in issues}
        return {"interface_version": 2, "now": now, "max_parallel": max_parallel,
            "attempt_budget_minutes": 30, "human_directed": True, "issues": list(issues),
            "tracker": [{"issue": issue, "state": "open", "open_blockers": [],
                         "decision_blockers": []} for issue in issues],
            "owners": [], "worktrees": list(worktrees),
            "forge": forge or keyed({"state": "none", "url": None, "merge_sha": None}),
            "delivery_contracts": contracts or keyed(None),
            "authorization_intents": intents or keyed([]),
            "authority_observations": keyed([]), "reevaluation_evidence": keyed([]),
            "delivery_observations": keyed([]), "requested_scopes": keyed(None),
            "recoveries": keyed(None)}


class DeliveryBuilderTest(BuilderHarness, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load(MODEL, "delivery_model_builder", package=True)

    def validate(self, value, kind):
        return self.model.validate_delivery_object(
            value, expected_kind=kind, notes_max_characters=500)

    def test_contract_is_deterministic_policy_derived_and_valid(self):
        self.project()
        raw = json.dumps(self.contract_input()).encode()
        path = self.root / "contract-input.json"; path.write_bytes(raw)
        first = self.cli("build-delivery", "--repo-root", self.root, "--kind", "contract",
                         "--input", "-", stdin=raw)
        second = self.cli("build-delivery", "--repo-root", self.root, "--kind", "contract",
                          "--input", path)
        self.assertEqual(first.stdout, second.stdout)
        built = json.loads(first.stdout)
        self.assertEqual(first.stdout, self.model.canonical_bytes(built))
        self.assertEqual(set(built), {"contract", "initial_intent"})
        contract, initial = built["contract"], built["initial_intent"]
        self.validate(contract, "delivery-contract"); self.validate(initial, "authorization-intent")
        self.assertEqual(contract["initial_authorization_intent_id"], initial["id"])
        self.assertEqual(contract["initial_authorization_intent_digest"],
                         self.model.canonical_digest(initial))
        self.assertEqual([stage["id"] for stage in contract["stages"]], [
            "select_reviewed_output", "publish_branch", "open_pr", "merge_pr",
            "close_tracker", "delete_remote_branch", "remove_worktree",
            "delete_local_branch"])
        constraints = contract["stages"][0]["target_ref"]["constraints"]
        self.assertEqual((constraints["branch"], constraints["base"]), (WORKTREE_NAME, "main"))
        literals = {stage["id"]: stage["target_ref"].get("value") for stage in contract["stages"]}
        self.assertEqual((literals["close_tracker"], literals["remove_worktree"],
                          literals["delete_local_branch"]), ("171", self.worktree, WORKTREE_NAME))
        self.assertEqual(set(contract["deliverable"]["obligations"].values()), {"required"})
        self.assertEqual(len(initial["scopes"]), 8)
        self.assertEqual((initial["source"]["kind"], initial["revocation_key"]),
                         ("explicit_user", f"fagenorn/nix-config#171@{NOW}"))

        def keep_remote(contract_value):
            contract_value["bindings"]["vcs"]["merge"]["delete_branch"] = False
        self.project(keep_remote)
        stages = self.build("contract", self.contract_input())["contract"]["stages"]
        self.assertNotIn("delete_remote_branch", [stage["id"] for stage in stages])

    def test_contract_refusals_exit_two_with_empty_stdout(self):
        def gitlab(contract_value):
            contract_value["bindings"]["tracker"]["kind"] = "gitlab"
        cases = (("non-github tracker", gitlab, {}),
                 ("foreign issue branch", None, {"worktree": "/wt/issue-172-other"}),
                 ("unpatterned branch", None, {"worktree": "/wt/feature-171"}),
                 ("relative worktree", None, {"worktree": "wt/" + WORKTREE_NAME}),
                 ("parent handoff", None, {"source_kind": "parent_handoff"}),
                 ("unknown key", None, {"extra": True}))
        for label, mutate, changes in cases:
            with self.subTest(label=label):
                self.project(mutate)
                refused = self.build("contract", self.contract_input(**changes), ok=False)
                self.assertEqual((refused.returncode, refused.stdout), (2, b""))
        self.project()
        missing = self.contract_input(); missing.pop("now")
        for kind, value in (("contract", missing), ("nonsense", self.contract_input())):
            with self.subTest(kind=kind):
                refused = self.build(kind, value, ok=False)
                self.assertEqual((refused.returncode, refused.stdout), (2, b""))

    def test_scope_and_initial_intent_regenerate_from_the_contract(self):
        self.project()
        built = self.build("contract", self.contract_input())
        contract, initial = built["contract"], built["initial_intent"]
        self.assertEqual(self.build("initial-intent", {"contract": contract}), initial)
        declared = {item["id"]: item for item in initial["scopes"]}
        for stage in contract["stages"]:
            scope = self.build("scope", {"contract": contract, "stage_id": stage["id"]})
            with self.subTest(stage=stage["id"]):
                self.assertEqual(declared[scope["id"]], scope)
                self.assertEqual((scope["action"], scope["effect"], scope["risk"]),
                                 (stage["action"], stage["effect"], stage["effect"]))
                self.assertEqual(scope["principal"], {
                    "kind": "issue_owner", "stable_id": "fagenorn/nix-config#171"})
                self.assertEqual(scope["target"]["pr_ref"], (
                    {"kind": "slot", "slot_id": "reviewed"}
                    if stage["kind"] in {"open_pr", "merge_pr"} else {"kind": "none"}))
        tampered = copy.deepcopy(contract)
        tampered["provenance"]["created_at"] = "2026-09-22T00:00:00Z"
        for kind, value in (("initial-intent", {"contract": tampered}),
                            ("scope", {"contract": tampered, "stage_id": "merge_pr"}),
                            ("scope", {"contract": contract, "stage_id": "unknown"})):
            with self.subTest(kind=kind, stage=value.get("stage_id")):
                refused = self.build(kind, value, ok=False)
                self.assertEqual((refused.returncode, refused.stdout), (2, b""))


class HelperInputTest(BuilderHarness, unittest.TestCase):
    def pipe(self, boundary, raw):
        completed = subprocess.run(
            [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
             boundary, "--input", "-", "--policy", str(POLICY)],
            input=raw, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout

    def assert_parity(self, state, args, flag, raw, piped=None):
        """The path form and the stdin form leave identical stdout and ledger bytes."""
        before = state.read_bytes()
        path = self.root / f"{flag.strip('-')}.json"; path.write_bytes(raw)
        by_path = self.cli(*args, flag, path)
        after = state.read_bytes(); state.write_bytes(before)
        by_stdin = self.cli(*args, flag, "-", stdin=raw if piped is None else piped)
        self.assertEqual((by_stdin.stdout, state.read_bytes()), (by_path.stdout, after))
        return by_stdin.stdout

    def test_every_input_flag_reads_stdin_and_refuses_relative_paths(self):
        self.project()
        run = ("--repo-root", self.root, "--run-id", "inputs")
        for command in (("control", *run, "--request-file"),
                        ("direct-owner", "--repo-root", self.root, "--request-file"),
                        ("checkpoint-delivery", *run, "--now", NOW, "--checkpoint-file"),
                        ("finish", *run, "--now", NOW, "--summary-file"),
                        ("finish", *run, "--now", NOW, "--issue", 151, "--attempt", 1,
                         "--result-file"),
                        ("build-delivery", "--repo-root", self.root, "--kind", "contract",
                         "--input")):
            with self.subTest(command=command[0], flag=command[-1]):
                refused = self.cli(*command, "relative.json", ok=False)
                self.assertEqual(refused.returncode, 2)
                self.assertIn(b"file path must be absolute", refused.stderr)

        self.cli("init-run", *run, "--now", NOW)
        state = self.root / ".superpowers/workflows/inputs/state.json"
        candidate = {"issue": 151, "recorded": None, "candidate": {
            "path": str(self.root / ".worktrees/worktree-issue-151-inputs"), "state": "absent"}}
        stdout = self.assert_parity(state, ("control", *run), "--request-file", json.dumps(
            self.control_request([151], worktrees=[candidate])).encode())
        self.assertEqual(self.pipe("workflow-response", stdout), stdout)

        built = self.build("contract", self.contract_input())
        request = {"interface_version": 2, "issue": 171, "now": NOW,
            "attempt_budget_minutes": 30, "new_run": False, "owner_unavailable": False,
            "tracker": {"issue": 171, "state": "open", "open_blockers": [],
                        "decision_blockers": []},
            "worktree": {"issue": 171, "recorded": None,
                         "candidate": {"path": self.worktree, "state": "absent"}},
            "forge": {"state": "none", "url": None, "merge_sha": None},
            "delivery_contract": built["contract"],
            "authorization_intents": [built["initial_intent"]],
            "authority_observations": [], "reevaluation_evidence": [],
            "delivery_observations": [], "requested_scope": None, "recovery": None}
        owner = json.loads(self.cli("direct-owner", "--repo-root", self.root,
                                    "--request-file", "-",
                                    stdin=json.dumps(request).encode()).stdout)
        historical = {"issue": 171, "state": "failed", "pr_url": None, "merge_sha": None,
            "issue_closed": False, "discussion_items": [], "detail_state": "none",
            "report_path": None, "notes": "failed"}
        summary = json.dumps({"interface_version": 2, "issue": 171,
            "state": "terminal_failed", "custody": owner["custody"],
            "historical_owner_result": historical,
            "delivery_contract_digest": owner["contract_digest"],
            "delivery_observations": [], "authority_observations": [],
            "reevaluation_evidence": [], "detail_state": "none",
            "report_path": None, "notes": "failed"}).encode()
        direct_state = self.root / f".superpowers/workflows/{owner['run_id']}/state.json"
        self.assert_parity(direct_state, ("finish", "--repo-root", self.root, "--run-id",
                           owner["run_id"], "--now", LATER), "--summary-file", summary,
                           piped=self.pipe("ship-summary", summary))

        workflow = load(WORKFLOW, "workflow_state_inputs")
        legacy = workflow.new_run_state(run_id="legacy-inputs", now=NOW, issues={})
        legacy["schema_version"] = 2
        legacy["issues"]["151"] = {"issue": 151, "outcome": None, "attempts": [
            workflow.new_control_attempt(issue=151, attempt_number=1,
                worktree=str(self.root / "wt-151"), now=NOW,
                deadline_at="2026-09-21T01:00:00Z")]}
        legacy_state = self.root / ".superpowers/workflows/legacy-inputs/state.json"
        legacy_state.parent.mkdir(parents=True)
        legacy_state.write_text(json.dumps(legacy), encoding="utf-8")
        self.assert_parity(legacy_state, ("finish", "--repo-root", self.root, "--run-id",
                           "legacy-inputs", "--now", LATER, "--issue", 151, "--attempt", 1),
                           "--result-file", json.dumps({**historical, "issue": 151}).encode())
```

In `test_public_source_and_installed_admission_fail_closed`, copy
`SCRIPTS / "workflow_delivery_build.py"` into `store`, symlink it into `library`
in the installed layout, and add a fail-closed loop exactly like the projection
one: removing the build module, or replacing it with
`b"WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION = 2\nclass DeliveryBuilder: pass\n"`,
makes `rejects_dependency("builder")` hold with the repo tree unchanged. In
`T/test_delivery_model.py::test_import_is_pure_and_interface_is_exact` add
`"STAGE_ACTIONS"` to the pinned `__all__` set.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py 2>&1 | tail -5`
Expected: FAIL/ERROR — `build-delivery` is an invalid choice, `-` is read as a
missing file, relative report paths are accepted, and the fail-closed loop cannot
find `workflow_delivery_build.py`.

- [ ] **Step 3: Implement**

1. `_objects.py`: `STAGE_ACTIONS = MappingProxyType(_STAGE_ACTIONS)`; export it
   from `__init__.py` and `__all__`.
2. `workflow-state.py`: add `read_input_bytes`; make `load_json_request` decode
   its bytes (keeping the `invalid {label} JSON` message); route
   `command_checkpoint_delivery`, `command_finish_delivery` and `load_result_file`
   through `artifact_budget_validate(..., input_bytes=read_input_bytes(...))`.
   Add `resolve_project_argv()`, `command_build_delivery(args)` and a parser entry
   (`--repo-root` required and absolute, `--kind` with `choices=("contract",
   "initial-intent", "scope")`, `--input` required). The handler writes
   `runtime.model.canonical_bytes(result)` to `sys.stdout.buffer`.
3. `workflow_delivery.py`: `_load_builder(model, notes_max)` mirrors
   `_load_projection` (entry `Path(__file__).with_name("workflow_delivery_build.py")`,
   module name `_workflow_delivery_build`, `ValueError("workflow delivery builder is
   unavailable")`, version check → `"unsupported workflow delivery builder
   interface"`); `__init__` loads it after the model; `build_delivery` delegates and
   validates the output kinds.
4. `S/workflow_delivery_build.py`: the derivation above; every refusal raises
   `ValueError` with a short reason.
5. `default.nix`: beside the wire entry add
   `".agents/lib/python/workflow_delivery_build.py".source = ./scripts/workflow_delivery_build.py;`.
6. `CLAUDE.md`: add a bullet under "Claude Code is declaratively managed",
   directly after the bullet that ends "there is no Superpowers input, patch,
   marketplace or plugin in this repo.":
   `- Delivery objects are built, never hand-composed: \`workflow-state build-delivery --repo-root <ledger_repo_root> --kind <kind> --input <absolute-path|->\` derives the \`delivery-contract/v1\` and its initial authorization intent from \`resolve-project\` policy, and seals each stage's scope. It is read-only — no lock, ledger, clock or write — and refuses anything it cannot derive with exit 2 and empty stdout.`

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivery_model.py 2>&1 | tail -3` → `OK`.
Run: `just build 2>&1 | tail -3` → exit 0.
Run: `just agent-workflow-tests 2>&1 | tail -3` → `OK (skipped=1)`.
Run: `if grep -qE "open\(|subprocess|datetime" home/common/agent-skills/scripts/workflow_delivery_build.py; then exit 1; fi` → exit 0 (the module stays pure).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/{workflow_delivery_build.py,workflow_delivery.py,workflow-state.py} \
  home/common/agent-skills/scripts/delivery_model/{__init__.py,_objects.py} \
  home/common/agent-skills/default.nix CLAUDE.md \
  home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivery_model.py
git commit -m "feat(workflow-state): build delivery contracts, intents and scopes; read inputs from stdin"
```
