# Task 2: Reconcile the conformance ladder and publish the Demo facts

After Task 1, the three conformance suites fail 58 tests. The reason is that
`check_contract_resolvable` never binds the platform, calls the pre-slice resolver
signatures, and runs under a `HOME` that has no platform installed. This task writes
the single reconciliation commit (D1). It rests on D4–D7, D9, D10 and D11. The spec
sections "Conformance ladder", "Facts on …" and "Suites" are the reference.

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance-checks.py`
- Modify: `home/common/agent-skills/tests/conformance_test_support.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance_registry.py`

**Interfaces:**
- Consumes, from Task 1 (`context.resolver` is `resolve-project.py` loaded in
  process):
  - `bootstrap_platform_library() -> bool`, `PLATFORM_LIBRARY_REPAIR_ID` and
    `require_platform_manifest() -> (manifest, path)`, which raises
    `ContractError("resolver_failure", repair_id, …)`;
  - `validate_schema_version(source, violations, supported)`,
    `validate_contract(source, manifest)`,
    `raise_for_platform_range(platform, platform_version)` and
    `declared_facts(source)`;
  - `ContractError.reason_code`;
  - from `tests/test_resolve_project.py`: `install_home`, `COMMITTED`, `MANIFEST`
    and `mutated_manifest`.
- Produces:
  - in `conformance-checks.py`:
    - `settle(context, error, facts: dict | None = None) -> bool`;
    - `compatibility_facts(resolver, manifest: dict, source) -> dict`;
    - `resolver_failed(context, stage: str, resolver_repair_id: str | None = None) -> Outcome`;
  - in `conformance_test_support.py`:
    - the re-exports `COMMITTED`, `MANIFEST`, `install_home` and
      `mutated_manifest`;
    - `platform_env(tmp: Path, manifest=COMMITTED, *, library=True) -> dict`;
    - the mixin `PlatformHome`, whose `setUp` pins `HOME`.

**Invariants:**
- The ladder runs in this order: platform, present, schema, valid, range,
  projection, capability. Each step's `stage` label is, in turn, `platform`,
  `present`, `schema_supported`, `valid`, `schema_supported`, `projection_fresh`
  and `capability_required` (D4).
- `schema_supported` is recorded as passed only after `raise_for_platform_range`
  (D4). A broken installation fails `resolvable` with facts exactly
  `{stage: "platform", resolver_repair_id}`, and every ladder stage is suppressed by
  `repository.contract.resolvable` (D5).
- The facts on `compatibility.contract.schema_supported` follow the spec's D6
  table: 5 keys when it passes, and at most 8 when it fails. A suppressed stage
  carries exactly `{suppressed_by}`.
- `conformance-registry.py` and `conformance.py` are not modified, so no closed set
  or schema changes.

- [ ] **Step 1: Write the test infrastructure and the failing tests**

(a) `tests/conformance_test_support.py`:
- Add `import os` (alphabetically, after `import json`) and
  `from unittest import mock` (after `from pathlib import Path`).
- Append this paragraph to the module docstring, after the sentence ending
  "…overrides PATH.":

```
HERMETIC_ENV's HOME also holds the platform installation the resolver ladder
binds first — the committed manifest and library, installed by the resolver
family's own `install_home` (#147 D7). A case that needs another manifest, or
no library, runs under `platform_env` instead.
```

Replace the line `_HERMETIC_HOME = tempfile.mkdtemp(prefix="conformance-home-")` with:

```python
# The resolver family's installer is the one home of the installed layout
# (#147 D7), so this module lends it to the conformance suites rather than
# copying it. Only the named helpers are imported, so no resolver TestCase
# enters a conformance suite's namespace. The directory has to be importable
# however this module was reached.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_resolve_project import (  # noqa: E402
    COMMITTED, MANIFEST, install_home, mutated_manifest,
)

_HERMETIC_HOME = str(install_home(
    Path(tempfile.mkdtemp(prefix="conformance-home-")).resolve()))
```

Append this at the end of the module:

```python
def platform_env(tmp: Path, manifest: object = COMMITTED, *,
                 library: bool = True) -> dict:
    """HERMETIC_ENV with `HOME` at a platform installation built under `tmp`.

    `manifest` and `library` are `install_home`'s override hook, unchanged:
    `COMMITTED` copies the repository's manifest, `None` installs none, any
    other value is written as the manifest, and `library=False` leaves the
    library uninstalled.
    """
    home = install_home(tmp / "home", manifest, library=library)
    return {**HERMETIC_ENV, "HOME": str(home)}


class PlatformHome:
    """S3 cases run the ladder in this process, so `HOME` is pinned (#147 D7).

    In process the ladder binds `agent_platform` from this process's own
    `$HOME/.agents/lib/python`. Pinned to the hermetic installation, a case's
    outcome no longer depends on whether the machine has switched to a
    generation that installs the platform. The library caches in
    `sys.modules` under its one name, and the resolver's origin guard refuses
    a copy imported from any other `HOME`, so the cached module is evicted on
    the way in and again on the way out.
    """

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"HOME": HERMETIC_ENV["HOME"]})
        patcher.start()
        self.addCleanup(patcher.stop)
        sys.modules.pop("agent_platform", None)
        self.addCleanup(sys.modules.pop, "agent_platform", None)
```

(b) `tests/test_conformance.py`:
- Change the support import to import `COMMITTED, REPO_ROOT, HERMETIC_ENV, SCRIPT,
  PlatformHome, ReportAssertions, Rebinding, doctor, fixture, load_module,
  make_root, make_stub_bin, mutated_manifest, platform_env, run`.
- Declare `class EvaluatorResolutionTest(PlatformHome, Rebinding, unittest.TestCase)`
  and `class EngineFailureTest(PlatformHome, Rebinding, unittest.TestCase)`. Leave
  their bodies alone, except for the assertion below.
- In `test_a_resolver_exception_is_a_check_finding_not_the_refusal`, replace the
  final `assertEqual` with:

```python
        # The stage fact pins *which* step broke: with the platform unbound
        # this case would fail at `platform` for a reason it does not test.
        self.assertEqual([check["status"], check["reason_code"], check["facts"]],
                         ["failed", "resolver_failure", {"stage": "present"}])
```

- Insert the following between `ContractParseFailureTest` and `NotOnboardedTest`.
  Keep two blank lines around each top-level definition.

```python
SCHEMA_CHECK_ID = "compatibility.contract.schema_supported"
LADDER_STAGE_IDS = (
    "repository.contract.present", SCHEMA_CHECK_ID, "repository.contract.valid",
    "repository.projection.fresh", "host.capability.required")
# The interval every platform case declares for itself, so no expectation
# below depends on what the committed contract happens to declare.
INTERVAL = {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"}


def with_contract(root: Path, **members) -> Path:
    """Replace top-level members of the fixture root's contract."""
    contract = root / ".agents/project.json"
    authored = json.loads(contract.read_text(encoding="utf-8"))
    authored.update(members)
    contract.write_text(json.dumps(authored, indent=2), encoding="utf-8")
    return root


class PlatformLadderTest(ReportAssertions, unittest.TestCase):
    """#147 D4-D6: the ladder binds the platform first and judges the interval
    on `compatibility.contract.schema_supported`, which carries the facts."""

    def entry_ids(self, root: Path, env: dict) -> list[str]:
        """The one root cause `workflow_entry` stops at, as check ids."""
        code, out, err = run("run", "--purpose", "workflow_entry",
                             "--repo-root", str(root), env=env)
        self.assertEqual(code, 2, err)
        report = json.loads(out)
        self.assert_validates(report)
        return [check["id"] for check in report["checks"]]

    def test_a_broken_installation_fails_resolvable_at_the_platform_stage(self):
        cases = (("library", COMMITTED, False, "platform.library.missing"),
                 ("manifest", None, True, "platform.manifest.missing"))
        for missing, manifest, library, repair_id in cases:
            with self.subTest(missing=missing), fixture() as tmp:
                root = make_root(tmp)
                env = platform_env(tmp, manifest, library=library)
                report, by_id = doctor(self, root, env=env)
                resolvable = by_id["repository.contract.resolvable"]
                self.assertEqual(
                    [resolvable["status"], resolvable["reason_code"],
                     resolvable["repair_id"], resolvable["facts"]],
                    ["failed", "resolver_failure", "conformance.internal",
                     {"stage": "platform", "resolver_repair_id": repair_id}])
                for check_id in LADDER_STAGE_IDS:
                    self.assertEqual(
                        [by_id[check_id]["status"], by_id[check_id]["facts"]],
                        ["suppressed",
                         {"suppressed_by": "repository.contract.resolvable"}])
                self.assertEqual(report["outcome"]["primary_check_id"],
                                 "repository.contract.resolvable")
                self.assert_validates(report)
                self.assertEqual(self.entry_ids(root, env),
                                 ["repository.contract.resolvable"])

    def test_an_incompatible_platform_or_schema_fails_schema_supported(self):
        cases = (
            ("platform_too_old", "0.9.0", 1, "/platform"),
            ("platform_too_new", "2.0.0", 1, "/platform"),
            ("project_schema_unsupported", "1.4.2", 2, "/schema_version"),
        )
        for reason_code, version, schema, pointer in cases:
            with self.subTest(reason_code=reason_code), fixture() as tmp:
                root = with_contract(make_root(tmp), schema_version=schema,
                                     platform=INTERVAL)
                env = platform_env(
                    tmp, mutated_manifest(platform_version=version))
                report, by_id = doctor(self, root, env=env)
                check = by_id[SCHEMA_CHECK_ID]
                self.assertEqual(
                    [check["status"], check["reason_code"], check["repair_id"]],
                    ["failed", "unsupported_schema",
                     "contract.schema.unsupported"])
                self.assertEqual(check["facts"], {
                    "platform_version": version,
                    "supported_project_schemas": ["1"],
                    "project_schema_version": schema,
                    "platform_min_inclusive": "1.0.0",
                    "platform_max_exclusive": "2.0.0",
                    "schema_reason_code": reason_code,
                    "violations": 1,
                    "first_pointer": pointer,
                })
                valid = by_id["repository.contract.valid"]
                self.assertEqual([valid["status"], valid["facts"]],
                                 ["suppressed", {"suppressed_by": SCHEMA_CHECK_ID}])
                self.assert_validates(report)
                self.assertEqual(self.entry_ids(root, env), [SCHEMA_CHECK_ID])

    def test_a_malformed_interval_fails_valid_and_suppresses_schema_supported(self):
        with fixture() as tmp:
            root = with_contract(make_root(tmp), platform={
                "min_inclusive": "1.0", "max_exclusive": "2.0.0"})
            report, by_id = doctor(self, root)
            valid = by_id["repository.contract.valid"]
            self.assertEqual(
                [valid["status"], valid["reason_code"],
                 valid["facts"]["first_pointer"]],
                ["failed", "invalid_contract", "/platform/min_inclusive"])
            schema = by_id[SCHEMA_CHECK_ID]
            self.assertEqual(
                [schema["status"], schema["facts"]],
                ["suppressed", {"suppressed_by": "repository.contract.valid"}])
            self.assert_validates(report)

    def test_a_shape_violation_outranks_an_out_of_range_platform(self):
        """The range check runs only once shape validation has passed, so the
        root cause is the one `resolve` would refuse with (#147 D4)."""
        with fixture() as tmp:
            root = with_contract(make_root(tmp), platform=INTERVAL,
                                 unexpected_member=True)
            env = platform_env(tmp, mutated_manifest(platform_version="2.0.0"))
            _, by_id = doctor(self, root, env=env)
            self.assertEqual(
                [by_id["repository.contract.valid"]["status"],
                 by_id[SCHEMA_CHECK_ID]["status"]], ["failed", "suppressed"])
            self.assertEqual(self.entry_ids(root, env),
                             ["repository.contract.valid"])

    def test_a_compatible_root_passes_schema_supported_with_the_platform_facts(self):
        with fixture() as tmp:
            root = with_contract(make_root(tmp), platform=INTERVAL)
            env = platform_env(tmp, mutated_manifest(platform_version="1.4.2"))
            report, by_id = doctor(self, root, env=env)
            check = by_id[SCHEMA_CHECK_ID]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"]],
                ["passed", None, None])
            self.assertEqual(check["facts"], {
                "platform_version": "1.4.2",
                "supported_project_schemas": ["1"],
                "project_schema_version": 1,
                "platform_min_inclusive": "1.0.0",
                "platform_max_exclusive": "2.0.0",
            })
            self.assert_validates(report)
```

(c) `tests/test_conformance_registry.py`: import `MANIFEST` as well, wrapping the
import as `MANIFEST, REPO_ROOT, ReportAssertions, doctor, fixture, load_module,` /
`make_root, run,`. In
`AcceptanceDemoTest.test_doctor_on_this_repository_reports_every_registered_check`,
insert this directly before its `for repair in report["repairs"]:` loop. It is the
in-suite form of the Demo (D7, D11):

```python
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        contract = json.loads(
            (REPO_ROOT / ".agents/project.json").read_text(encoding="utf-8"))
        schema = by_id["compatibility.contract.schema_supported"]
        self.assertEqual([schema["status"], schema["facts"]], ["passed", {
            "platform_version": manifest["platform_version"],
            "supported_project_schemas":
                [str(version) for version in manifest["project_schema_versions"]],
            "project_schema_version": contract["schema_version"],
            "platform_min_inclusive": contract["platform"]["min_inclusive"],
            "platform_max_exclusive": contract["platform"]["max_exclusive"],
        }])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_conformance.py -k PlatformLadderTest -k EngineFailureTest 2>&1 | tail -1; python3 -m unittest home/common/agent-skills/tests/test_conformance_registry.py -k AcceptanceDemoTest 2>&1 | tail -1`

Expected: `FAILED (failures=7, errors=1)`, then `FAILED (failures=1)`. The ladder
still calls the pre-slice signatures, so every subprocess run reports
`resolver_failure`. `EngineFailureTest` already passes at this point. Its new
`stage` assertion guards against a regression, not against today's code.

- [ ] **Step 3: Rewire the ladder**

In `scripts/conformance-checks.py`, replace everything from `def settle(` up to,
but not including, `def stage_result(` with the block below. Leave the rest of the
module unchanged. The block is written out in full because its order, its stage
labels and where the facts attach are the decisions D4–D6 record. It was validated
against a scratch replay: 85 conformance tests and 178 resolver tests pass.

```python
def settle(context: Context, error, facts: dict | None = None) -> bool:
    """Record one resolver refusal against the stage its code names (D33).

    `facts` are the stage's own facts; the refusal's `violations` and
    `first_pointer` are merged over them. The ladder passes the compatibility
    facts this way for an `unsupported_schema` refusal (#147 D6). Returns
    False for a code no stage owns, which the caller reports on
    `repository.contract.resolvable` itself.
    """
    stage = CODE_STAGES.get(error.code)
    if stage is None:
        return False
    check_id = STAGE_CHECKS[stage]
    # Overwrites a `passed` recording when the code names an earlier stage:
    # `validate_projections` refuses `invalid_contract` after `valid` passed.
    context.stages[stage] = Outcome(
        "failed", error.code, stage_repair_id(stage, error.code),
        {**(facts or {}),
         "violations": len(error.violations),
         "first_pointer": bound_fact(error.violations[0]["pointer"])})
    suppress_unset_stages(context, check_id)
    return True


def compatibility_facts(resolver, manifest: dict, source) -> dict:
    """What `compatibility.contract.schema_supported` reports (#147 D6).

    The installed platform's version and supported project schemas always;
    the contract's declared schema version and interval only as far as the
    resolver's defensive `declared_facts` reads them, so an absent or
    malformed member is left out rather than defaulted. At most five keys,
    which leaves a failed check room for `schema_reason_code`, `violations`
    and `first_pointer` within the eight-key cap (D9).
    """
    facts = {
        "platform_version": bound_fact(manifest["platform_version"]),
        "supported_project_schemas": bound_facts(
            str(version) for version in manifest["project_schema_versions"]),
    }
    declared = resolver.declared_facts(source)
    if declared["project_schema_version"] is not None:
        facts["project_schema_version"] = declared["project_schema_version"]
    interval = declared["platform_interval"]
    if interval is not None:
        facts["platform_min_inclusive"] = bound_fact(interval["min_inclusive"])
        facts["platform_max_exclusive"] = bound_fact(interval["max_exclusive"])
    return facts


def check_contract_resolvable(context: Context) -> Outcome:
    """Run the resolver ladder once and cache every stage it settles (D17).

    The steps follow `resolve`'s refusal precedence (#147 D4): bind the
    platform library and manifest, discover the root, check the declared
    schema version against the manifest's supported set, validate the
    contract's shape, and only then check the installed platform version
    against the declared interval. `schema_supported` is recorded as passed
    after that range check, so a passed compatibility check always means the
    interval was evaluated.

    This is the engine's one declared exception to the single boundary in
    `main`: a failure *of the resolver* is this check's finding — a broken
    platform installation among them, reported at the `platform` stage with
    the resolver's own repair id (#147 D5) — while a failure of anything else
    is the refusal (D29).
    """
    resolver = context.resolver
    stage = "platform"
    manifest = None
    try:
        if not resolver.bootstrap_platform_library():
            return resolver_failed(
                context, stage, resolver.PLATFORM_LIBRARY_REPAIR_ID)
        try:
            manifest, _ = resolver.require_platform_manifest()
        except resolver.ContractError as error:
            return resolver_failed(context, stage, error.repair_id)

        stage = "present"
        root = resolver.discover_root(context.root_arg)
        context.root = root
        context.stages["present"] = Outcome("passed")

        stage = "schema_supported"
        source = resolver.load_contract(root)
        context.contract = source
        violations: list[dict] = []
        resolver.validate_schema_version(
            source, violations, manifest["project_schema_versions"])

        stage = "valid"
        violations += resolver.validate_contract(source, manifest)
        resolver.raise_for_violations(dedup_violations(violations))
        context.stages["valid"] = Outcome("passed")

        stage = "schema_supported"
        resolver.raise_for_platform_range(
            source["platform"], manifest["platform_version"])
        context.stages["schema_supported"] = Outcome(
            "passed", facts=compatibility_facts(resolver, manifest, source))

        stage = "projection_fresh"
        context.bindings = resolver.normalize_bindings(source["bindings"], root)
        context.capabilities = resolver.compute_capabilities(
            context.bindings, root, source["capabilities"])
        resolver.validate_projections(root, source)
        context.stages["projection_fresh"] = Outcome("passed")

        stage = "capability_required"
        resolver.raise_for_unavailable(list(context.required), context.capabilities)
        context.stages["capability_required"] = Outcome("passed")
    except resolver.ContractError as error:
        facts = None
        if error.code == "unsupported_schema":
            # Both raise sites run after the manifest and the contract are
            # bound, so the refusal can say what it was measured against.
            facts = {**compatibility_facts(resolver, manifest, context.contract),
                     "schema_reason_code": error.reason_code}
        if not settle(context, error, facts):
            return resolver_failed(context, stage)
    except Exception:
        return resolver_failed(context, stage)
    return Outcome("passed")


def resolver_failed(context: Context, stage: str,
                    resolver_repair_id: str | None = None) -> Outcome:
    """The ladder itself broke: every unsettled stage suppresses under it.

    `stage` names the ladder step that broke. A broken platform installation
    also carries the resolver's own repair id, so the report names what to
    reinstall without a new repair in the closed set (#147 D5).
    """
    suppress_unset_stages(context, RESOLVABLE_CHECK_ID)
    facts = {"stage": stage}
    if resolver_repair_id is not None:
        facts["resolver_repair_id"] = bound_fact(resolver_repair_id)
    return Outcome("failed", "resolver_failure", "conformance.internal", facts)
```

The `dedup_violations` docstring stays true: `validate_contract` still re-runs
`validate_schema_version`.

- [ ] **Step 4: Verify the focused suites and the workflow suite**

Run: `T=home/common/agent-skills/tests; python3 -m unittest $T/test_resolve_project.py $T/test_resolve_platform.py $T/test_resolve_platform_status.py $T/test_conformance.py $T/test_conformance_checks.py $T/test_conformance_registry.py 2>&1 | tail -3`

Expected: `Ran 263 tests` and `OK`. That is 178 resolver tests plus 85 conformance
tests, the 80 existing ones and the 5 new ones. At the start of this task, the same
command reports `Ran 258 tests` and `FAILED (failures=50, errors=8)`.

Run: `git diff --quiet HEAD -- home/common/agent-skills/scripts/conformance-registry.py home/common/agent-skills/scripts/conformance.py && echo "closed sets untouched"`

Expected: `closed sets untouched`.

Run: `L="${TMPDIR:-/tmp}/t2-awt.log"; just agent-workflow-tests > "$L" 2>&1; grep -E '^(Ran [0-9]+ tests|OK|FAILED)' "$L"`

Expected: `Ran 999 tests` and `OK`, in about 3 minutes. 999 is the count at this
base, and any failure line is a stop.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/conformance-checks.py \
  home/common/agent-skills/tests/conformance_test_support.py \
  home/common/agent-skills/tests/test_conformance.py \
  home/common/agent-skills/tests/test_conformance_registry.py
git commit -F - <<'EOF'
fix(agent-skills): reconcile the conformance ladder with the platform resolver

Bind the platform before discovery, validate against the installed manifest,
run the interval check after shape validation, and report the platform version,
supported schemas and declared interval on
compatibility.contract.schema_supported. The conformance suites install the
platform into their hermetic HOME, and the in-process cases pin it (#147 D4-D7).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XJQu22Bg2fayzv7KNKKbaA
EOF
```

A signing failure is a stop. Report it, and never bypass it.

- [ ] **Step 6: Prove the Demo on the built generation (D9, D10)**

```bash
set -euo pipefail
just build
H=$(nix-store -qR ./result | grep -- '-home-manager-files$')
test "$(printf '%s\n' "$H" | wc -l | tr -d ' ')" = 1
WT=$(git rev-parse --show-toplevel); OUT="${TMPDIR:-/tmp}/t2-demo"; mkdir -p "$OUT"
HOME=$H "$H/.agents/bin/conformance" run --purpose doctor --repo-root "$WT" --offline > "$OUT/report.json"
HOME=$H "$H/.agents/bin/conformance" validate-report --input "$OUT/report.json"
HOME=$H "$H/.agents/bin/resolve-project" platform-status --repo-root "$WT" --fleet > "$OUT/status.json"
H="$H" WT="$WT" OUT="$OUT" python3 - <<'EOF'
import json, os
from pathlib import Path
H, WT, OUT = (Path(os.environ[name]) for name in ("H", "WT", "OUT"))
manifest = json.loads((WT / "home/common/agent-skills/platform-manifest.json").read_text())
contract = json.loads((WT / ".agents/project.json").read_text())
checks = {c["id"]: c for c in json.loads((OUT / "report.json").read_text())["checks"]}
schema = checks["compatibility.contract.schema_supported"]
assert schema["status"] == "passed", schema
assert schema["facts"] == {
    "platform_version": manifest["platform_version"],
    "supported_project_schemas": [str(v) for v in manifest["project_schema_versions"]],
    "project_schema_version": contract["schema_version"],
    "platform_min_inclusive": contract["platform"]["min_inclusive"],
    "platform_max_exclusive": contract["platform"]["max_exclusive"]}, schema["facts"]
status = json.loads((OUT / "status.json").read_text())
installed = str((H / ".agents/share/platform-manifest.json").resolve())
assert installed.startswith("/nix/store/") and status["platform"]["manifest_path"] == installed, status["platform"]
assert status["compatibility"]["compatible"] is True and status["fleet"] == [], status
print("demo ok", json.dumps(schema["facts"], sort_keys=True))
EOF
```

Expected: `{"valid":true}`, then `demo ok {…five facts…}`. Other checks in the doctor
report may be `not_run` (the offline tracker check, the release-profile checks). The
Demo asserts only the compatibility check. The build writes the git-ignored
`./result`. Never run `just switch` (D8).

- [ ] **Step 7: Verify the boundary**

```bash
BASE=$(git merge-base HEAD origin/main)
git diff --name-only "$BASE" HEAD -- . ':(exclude).claude/' | sort > "${TMPDIR:-/tmp}/t2-files.txt"
printf '%s\n' .agents/project.json home/common/agent-skills/default.nix \
  home/common/agent-skills/platform-manifest.json home/common/agent-skills/scripts/agent_platform.py \
  home/common/agent-skills/scripts/conformance-checks.py home/common/agent-skills/scripts/resolve-project.py \
  home/common/agent-skills/tests/conformance_test_support.py home/common/agent-skills/tests/test_conformance.py \
  home/common/agent-skills/tests/test_conformance_registry.py home/common/agent-skills/tests/test_resolve_platform.py \
  home/common/agent-skills/tests/test_resolve_platform_status.py \
  home/common/agent-skills/tests/test_resolve_project.py justfile | sort | diff - "${TMPDIR:-/tmp}/t2-files.txt" && echo "boundary ok"
```

Expected: `boundary ok`. The package-feasibility check is sdd's cumulative delivery
gate, which runs after this task (spec Verification 6). Do not run `review-package`
yourself, because a second publication of the same range collides with that gate.
