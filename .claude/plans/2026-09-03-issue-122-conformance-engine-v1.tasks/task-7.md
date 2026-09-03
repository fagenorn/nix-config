# Task 7: The release-profile lint trio and the end-to-end acceptance gate

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`

**Interfaces:**
- Consumes from Task 2: `Check`, `Outcome`, `Context`, `REGISTRY`, `REGISTRY_BY_ID`, `REPAIRS`, `repair_ids_for`, `select`, `bound_fact`.
- Produces `find_release_profile(context) -> tuple[str, str | None]`, three evaluators, three registry entries, three repairs, and the acceptance suite.

**Invariants:**
- The three checks are `repository`-domain, `optional`, and carry `subject_kind: "release_profile"` (D6, D25). Being optional is what keeps an absent subject out of `outcome.status`.
- Neither `not_run` reason can read as a pass, and neither can drive `incomplete`, because the checks are optional (D6).
- Nothing in this task compiles, parses or validates a release profile: this slice ships no compiler, and judging a profile it cannot read would be a fabricated finding (D27).
- After this task the registry is closed at **17** entries and every acceptance criterion in the issue has a test that fails at the base commit.
- The committed-root acceptance gate runs `--offline` (D35); the paragraph under the suite states what it then judges.

## The subject locator (D27)

```python
def find_release_profile(context: "Context") -> tuple[str, str | None]:
    """Contract: ("absent", None) when the contract declares no release command,
    else ("unsupported", <the declared command id>). This slice ships no profile
    compiler, so a declared release command is a subject it cannot read (D27)."""
```

Read `context.contract["bindings"]["workflow"]["release"]`. `None` → `("absent", None)`. A command id string → `("unsupported", <id>)`.

Each of the three evaluators is then the same two-branch body, differing only in its repair id:

```python
state, command_id = find_release_profile(context)
if state == "absent":
    return Outcome("not_run", "subject_absent", <repair_id>, {"declared": False})
if state == "unsupported":
    return Outcome("not_run", "profile_unsupported", <repair_id>,
                   {"declared": True, "release_command": bound_fact(command_id)})
raise ValueError(f"unknown release profile state: {state!r}")
```

The `raise` is the closed-set default the bar demands and the one shape D32 admits: the two authored conditions above return an `Outcome`, and only a locator state the closed set does not cover — reachable solely by extending the engine and forgetting this dispatch — raises. No external input reaches it, and the S3 in-process seam covers it.

Each evaluator carries a docstring naming the #86 item it will judge once a compiler exists, phrased as what it *will* check rather than what it does check today — for `rolled_back_reachable`: *"Will fail a publication unit that has activation and immutable publication but no residue-only compensate edge, which makes rolled_back structurally unreachable (#86). This slice ships no profile compiler, so it reports not_run."* Do not write a docstring claiming the check evaluates a profile.

## Registry entries this task adds

All three: domain `repository`, subject kind `release_profile`, requirement `optional`, `depends_on = ("repository.contract.valid",)`, `network = False`. Every repair is `{"module": "conformance", "safety_class": "user_action", "operation": None}`.

| Id | `findings`: reason code → repair id |
|---|---|
| `repository.release_profile.rolled_back_reachable` | `subject_absent`, `profile_unsupported`, `rolled_back_unreachable` → `release_profile.compensate.add` |
| `repository.release_profile.restore_anchor` | `subject_absent`, `profile_unsupported`, `restore_anchor_destroyed` → `release_profile.materialize.add` |
| `repository.release_profile.observation_deadline` | `subject_absent`, `profile_unsupported`, `observation_deadline_optional` → `release_profile.deadline.require` |

The third reason code in each row is declared now and emitted by the compiler slice; declaring it here is what makes the registry closed rather than growing later (D5). The Task 2 guard only constrains an *emitted* reason code, so an unemitted declared code is not a failure — and because `findings` is the single source (D31), declaring it here is also what puts its repair id inside `repair_ids_for`.

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_conformance.py`.

```python
RELEASE_PROFILE_IDS = (
    "repository.release_profile.observation_deadline",
    "repository.release_profile.restore_anchor",
    "repository.release_profile.rolled_back_reachable",
)


class ReleaseProfileLintTest(ReportAssertions, unittest.TestCase):
    """AC2: the three prototype lint items are registered with declared subjects."""

    def test_all_three_are_registered_with_a_declared_subject(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp))
            for check_id in RELEASE_PROFILE_IDS:
                with self.subTest(check=check_id):
                    check = by_id[check_id]
                    self.assertEqual(
                        [check["domain"], check["subject_kind"],
                         check["requirement"], check["status"],
                         check["reason_code"], check["facts"]],
                        ["repository", "release_profile", "optional", "not_run",
                         "subject_absent", {"declared": False}])
                    self.assertIsNotNone(check["repair_id"])
            self.assertEqual(report["outcome"],
                             {"status": "passed", "primary_check_id": None})
            repairs = {r["repair_id"]: r for r in report["repairs"]}
            for repair_id in ("release_profile.compensate.add",
                              "release_profile.materialize.add",
                              "release_profile.deadline.require"):
                self.assertEqual(repairs[repair_id]["safety_class"], "user_action")
                self.assertIsNone(repairs[repair_id]["operation"])
            self.assert_validates(report)

    def test_a_declared_release_command_is_unsupported_not_absent(self):
        with fixture() as tmp:
            root = make_root(tmp)
            path = root / ".agents/project.json"
            contract = json.loads(path.read_text(encoding="utf-8"))
            contract["bindings"]["workflow"]["release"] = "codex-review"
            contract["capabilities"]["release"] = {"support": "supported"}
            path.write_text(json.dumps(contract), encoding="utf-8")
            report, by_id = doctor(self, root)
            for check_id in RELEASE_PROFILE_IDS:
                check = by_id[check_id]
                self.assertEqual([check["status"], check["reason_code"]],
                                 ["not_run", "profile_unsupported"])
                self.assertEqual(check["facts"], {"declared": True,
                                                  "release_command": "codex-review"})
            self.assertEqual(report["outcome"]["status"], "passed")
            self.assert_validates(report)

    def test_an_unknown_locator_state_raises(self):
        """S3: the closed-set default branch (D32)."""
        module = load_module()
        original = module.find_release_profile
        module.find_release_profile = lambda _context: ("compiled", "x")
        self.addCleanup(setattr, module, "find_release_profile", original)
        with self.assertRaises(ValueError):
            module.check_release_profile_restore_anchor(object())


REGISTERED_CHECK_IDS = (
    "compatibility.contract.schema_supported",
    "host.capability.required",
    "host.executor.helper_on_path",
    "host.policy_path.no_follow_readable",
    "host.tracker.credential",
    "repository.contract.present",
    "repository.contract.resolvable",
    "repository.contract.valid",
    "repository.ignore.runtime_sentinel",
    "repository.paths.classified",
    "repository.projection.fresh",
    "repository.release_profile.observation_deadline",
    "repository.release_profile.restore_anchor",
    "repository.release_profile.rolled_back_reachable",
    "repository.residue.nested_ledger",
    "repository.residue.root_scratch",
    "verification.commands.no_shell_indirection",
)

ENTRY_LADDER_IDS = (
    "repository.contract.resolvable", "repository.contract.present",
    "compatibility.contract.schema_supported", "repository.contract.valid",
    "repository.projection.fresh", "host.capability.required")


def ids_with(*prefixes):
    return tuple(i for i in REGISTERED_CHECK_IDS if i.startswith(prefixes))


PURPOSE_SELECTION = {
    "workflow_entry": ENTRY_LADDER_IDS,
    "adoption": ids_with("repository.", "compatibility."),
    "fleet": ids_with("repository.", "compatibility."),
    "ci": ids_with("repository.", "compatibility.", "verification."),
    "local": tuple(dict.fromkeys(ENTRY_LADDER_IDS + ids_with("host."))),
    "doctor": REGISTERED_CHECK_IDS,
}


class RegistryClosureTest(unittest.TestCase):
    def test_the_registry_is_exactly_the_seventeen_declared_checks(self):
        module = load_module()
        self.assertEqual(sorted(c.id for c in module.REGISTRY),
                         sorted(REGISTERED_CHECK_IDS))

    def test_every_declared_repair_resolves_and_none_is_unreachable(self):
        """D31: repair_ids_for reads the registry's own findings declaration."""
        module = load_module()
        declared = set()
        for check in module.REGISTRY:
            for repair_id in module.repair_ids_for(check):
                self.assertIn(repair_id, module.REPAIRS, check.id)
                declared.add(repair_id)
        self.assertEqual(declared, set(module.REPAIRS))

    def test_registry_order_is_topological(self):
        module = load_module()
        seen = set()
        for check in module.REGISTRY:
            for dependency in check.depends_on:
                self.assertIn(dependency, seen, f"{check.id} precedes {dependency}")
            seen.add(check.id)

    def test_every_purpose_selects_exactly_the_declared_ids(self):
        """SF-002: one discriminating matrix over the closed registry."""
        module = load_module()
        for purpose, expected in PURPOSE_SELECTION.items():
            with self.subTest(purpose=purpose):
                ids = [c.id for c in module.select(purpose)]
                self.assertEqual(sorted(ids), sorted(expected))
                self.assertEqual(len(ids), len(set(ids)))


class AcceptanceDemoTest(ReportAssertions, unittest.TestCase):
    """D22: the demo the issue names, against this repository's committed root."""

    def test_doctor_on_this_repository_reports_every_registered_check(self):
        report, by_id = doctor(self, REPO_ROOT, "--offline")
        self.assertEqual([c["id"] for c in report["checks"]],
                         sorted(REGISTERED_CHECK_IDS))
        self.assertEqual(report["subject"]["project_id"], "fagenorn/nix-config")
        self.assertNotIn("failed", [c["status"] for c in report["checks"]])
        self.assertEqual(by_id["host.tracker.credential"]["reason_code"],
                         "offline_constraint")
        self.assertEqual(report["outcome"]["status"], "incomplete")
        for repair in report["repairs"]:
            self.assertNotEqual(repair["safety_class"], "destructive")
        self.assert_validates(report)

    def test_workflow_entry_on_a_broken_contract_stops_at_one_root_cause(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / ".agents/project.json").write_text("{ broken", encoding="utf-8")
            code, out, err = run("run", "--purpose", "workflow_entry",
                                 "--repo-root", str(root))
            self.assertEqual(code, 2, err)
            report = json.loads(out)
            self.assertEqual(len(report["checks"]), 1)
            self.assertEqual(len(report["repairs"]), 1)
            self.assertEqual(report["checks"][0]["id"], "repository.contract.valid")
            self.assertEqual(report["checks"][0]["reason_code"], "invalid_contract")
            self.assertEqual(report["outcome"]["primary_check_id"],
                             "repository.contract.valid")
            self.assert_validates(report)
```

The committed-root gate runs `--offline` through the hermetic runner (D35), so it asks a deterministic question — does the full registry appear, does the report validate, is any check `failed`, is any repair `destructive` — and never whether this machine holds a tracker credential. `host.tracker.credential` is therefore `not_run`/`offline_constraint` and, being required, makes the outcome exactly `incomplete`. That is asserted, not tolerated: a gate accepting either `passed` or `incomplete` would pass on a machine whose credential state it never controlled.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py`
Expected: `ReleaseProfileLintTest` fails with `KeyError` on each of the three ids; `RegistryClosureTest` fails showing 14 registered ids against 17 expected and `local`/`doctor` selections short of the matrix; `AcceptanceDemoTest.test_doctor_on_this_repository_reports_every_registered_check` fails on the same list mismatch.

- [ ] **Step 3: Write the minimal implementation**

Add `find_release_profile`, the three evaluators (`check_release_profile_rolled_back_reachable`, `check_release_profile_restore_anchor`, `check_release_profile_observation_deadline`), the three registry entries and the three repairs. Append the registry entries after `repository.residue.root_scratch`; they depend on `repository.contract.valid`, which precedes them.

- [ ] **Step 4: Verify**

```bash
python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py
just agent-workflow-tests
just build
python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root . --offline \
  > /tmp/conformance-demo.json
python3 -c 'import json; r=json.load(open("/tmp/conformance-demo.json")); print(len(r["checks"]), r["outcome"]["status"]); print([c["id"] for c in r["checks"] if c["subject_kind"]=="release_profile"])'
python3 home/common/agent-skills/scripts/conformance.py validate-report --input /tmp/conformance-demo.json
git diff --stat HEAD~6
```

Expected: unittest OK; `just agent-workflow-tests` and `just build` pass; the `python3 -c` line prints `17 incomplete` — `--offline` makes the required `host.tracker.credential` `not_run`, so the outcome never depends on this machine's credentials (D35) — then the three `repository.release_profile.*` ids; `validate-report` prints `{"valid":true}` and exits 0; the last command carries **no pathspec**, the only way a fifth file can show, and spans the plan's base commit to the working tree — the six landed task commits plus this task's change, which Step 5 commits — listing exactly the plan's four files and nothing else. (`HEAD~6` assumes one commit per landed task.)

Falsifiability at the base commit: the `python3 -c` line prints `14` and an empty list.

- [ ] **Step 5: Commit**

```bash
rm -f /tmp/conformance-demo.json
git add home/common/agent-skills/scripts/conformance.py \
        home/common/agent-skills/tests/test_conformance.py
git commit -m "$(cat <<'MSG'
feat(conformance): register the release-profile lint trio and close the registry

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
MSG
)"
```
