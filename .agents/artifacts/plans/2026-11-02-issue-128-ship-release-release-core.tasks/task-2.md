# Task 2: Driver read side — selection, gates, store, tokens, status, preview

**Files:**
- Create: `python/agent_tools/release_driver.py`
- Create: `tests/release_driver_support.py`
- Create: `tests/test_release_driver.py`
- Modify: `justfile` (add `tests/test_release_driver.py` after `tests/test_release_command.py`)

**Interfaces:**
- Consumes:
  - Task 1's `release_verification.observe`, `VerificationRefused`, `evidence_id`.
  - `release_profile.compile_profile(profile_id, profile, contract, descriptors)`, which
    raises `ValueError` or `ProfileInadmissible`.
  - `release_profile.bind_candidate(compiled, candidate)`, which raises `ValueError`.
  - `release_adapter.REGISTRY`, `DESCRIPTORS` and `build_descriptors(registry)`.
  - `transaction_core.TransactionStore(root, clock=)`, with `.lookup`, `.load`,
    `.read_receipt` and `.hazard_markers`.
  - `transaction_history.TERMINALS`.
  - Test support: `tests/release_test_support.py` (`forge_profile`,
    `publication_free_profile`, `restorable_profile`, `missing_deadline_profile`,
    `base_contract`, `FIXTURE_STORE`) and `tests/forge_world.py` (`ForgeWorld`,
    `CANONICAL`, `verification_ready`).
- Produces (Tasks 3–6 extend or call these exact names):

```python
SCHEMA_VERSION = 1
KEY_SCHEMA = "release/v1"
EXECUTOR_ID = "release-driver"
AUTHORITY_CLASS = "release"
CUSTODY_TTL_MS = 900_000

class Refusal(Exception):
    def __init__(self, code: str, detail: str, repair_id: str | None = None) -> None: ...
    def as_object(self) -> dict[str, Any]: ...  # {"code", "repair_id", "detail"}

@dataclass(frozen=True)
class Project:
    project_id: str
    root: Path            # the main checkout, absolute
    common_dir: Path      # its git common dir, absolute
    integration_branch: str
    default_branch: str
    deploy_adapter: str   # bindings.deploy.adapter
    contract: Mapping[str, Any]   # the loaded source contract

def creation_key(project_id: str, profile_id: str, ordinal: int) -> str: ...
def token(plan_digest: str, action: str, attempt: int, acquisition: int) -> str: ...
def main_checkout(repo_root: Path) -> Path: ...          # the common dir, else Refusal
def require_cwd(repo_root: Path, cwd: Path) -> None: ... # Refusal cwd_mismatch

class Driver:
    def __init__(self, project: Project, *, profile_id: str | None = None,
                 registry: Mapping[str, Any] = release_adapter.REGISTRY,
                 clock: Callable[[], int] | None = None) -> None: ...
    project: Project; profile_id: str; compiled: ResolvedReleaseProfile
    registry: Mapping[str, Any]; clock: Callable[[], int] | None
    def shape_refusal(self) -> Refusal | None: ...
    def store(self, *, create: bool = False) -> TransactionStore | None: ...
    def transactions(self) -> list[tuple[int, Transaction]]: ...   # ordinals 1..n, probed
    def current(self) -> tuple[int, Transaction] | None: ...       # the last probed, or None
    def status(self) -> dict[str, Any]: ...
    def preview(self, candidate: Mapping[str, str] | None) -> dict[str, Any]: ...
```

**Invariants:**
- **Selection (D13, D18).**
  - With no `profile_id`, the driver picks the sole profile of
    `contract["release"]["profiles"]` whose `publication` is not `"none"`. With several,
    it refuses `profile_ambiguous`, whose detail lists the ids sorted. With none, it
    refuses `profile_unknown`.
  - An unknown `profile_id` refuses `profile_unknown`.
  - `compile_profile` raising `ValueError` or `ProfileInadmissible` refuses
    `profile_inadmissible`.
  - Descriptors are `release_adapter.build_descriptors(registry)`.
- **Shape gates (§1, D1, D26)** come from `shape_refusal()`, first failure wins:
  - `merge_not_declared` (repair `release.profile.merge_unsupported`) when
    `integration_branch != default_branch` and no compiled publication node has mode
    `materialize`;
  - `deploy_watch_unowned` (repair `release.profile.activation_unbound`) when
    `deploy_adapter != "none"`;
  - `anchors_unsupported` (repair `release.profile.anchor_unbound`) when any
    `compiled["recovery_declaration"]["units"]` posture is `restorable`.
- **Gate 1 helpers (D19)** read only the filesystem:
  - `main_checkout(root)` returns `root / ".git"` when that is a directory and not a
    symlink. Otherwise it refuses `not_main_checkout`.
  - `require_cwd(root, cwd)` finds the nearest ancestor of `cwd.resolve()`, itself
    included, that holds a `.git` entry. It refuses `cwd_mismatch` unless that ancestor
    equals `root.resolve()`.
- **Store (D4).** The root is `common_dir / "agent-release" / "store"`.
  - `store()` returns `None` when the root is not a directory, and so creates nothing.
  - `store(create=True)` makes both directories, `chmod`s each to `0o700` and returns
    `TransactionStore(root, clock=self.clock)`.
  - `transactions()` probes `lookup(creation_key(..., n))` for `n = 1, 2, …` until the first
    `None`, loading each.
- **Token (D6).** `token(...)` is `f"{action}:{h[:12]}"`, where `h` is
  `telemetry_digest([plan_digest, action, attempt, acquisition])` without its `sha256:`
  prefix.
  - The next attempt is the stored action view's `attempts + 1`, or 1 when the action is
    undeclared.
  - The next acquisition is the count of `lease_acquired` and `lease_reacquired` events
    plus 1, or 1 with no transaction.
- **Action order.** The order is `compiled["publication"] + compiled["activation"]`.
  - An action entry is `{name: node["id"], operation, mode, effect, target: node["target"],
    status}`. `status` is the stored view's status by name, else `None`.
  - A confirmation is listed for each entry with `effect == "irreversible"` and
    `status != "satisfied"`. It is
    `{action, effect, operation, version, commit, token}`, in action order.
- **`preview(candidate)`** writes nothing, takes no lock and calls no adapter (§4). It first
  raises `shape_refusal()`. Its mode follows `current()`:
  - **resume** when the current transaction is not in `TERMINALS`:
    - a non-None candidate raises `release_in_flight`, whose detail names the stored version;
    - `plan_digest = telemetry_digest({"transaction_id": id, "proof_plan_digest":
      events[0]["proof_plan_digest"]})`;
    - `verification` is `None`; `candidate` is the stored version, commit and title (D25);
    - `runnable` is `True` and `refusal` is `None`.
  - **new** otherwise:
    - a `None` candidate raises `candidate_required`;
    - `bind_candidate`'s `ValueError` raises `candidate_invalid`;
    - it calls `release_verification.observe` against the profile's repository: the
      `repository` of the first compiled proof unit whose `parameters["target"]["kind"]`
      is `github_repository`. When no unit has one, new mode raises `profile_inadmissible`
      at this point. The shape gates have already passed by then, so `GateTest`'s
      restorable case still reaches `anchors_unsupported`.
  - In new mode, `plan_digest` is `telemetry_digest` over `{"profile_digest",
    "ordinal": n + 1, "candidate": {version, commit, title, "notes_digest":
    telemetry_digest(notes)}, "verification": {"result", "checks": [{context,
    conclusion}]} or None, "actions": [{name, operation, mode, effect, target}]}`.
  - The first problem met becomes `refusal`, `runnable` is `False`, and confirmations are
    still listed (D18):
    - `VerificationRefused` gives its own code, and `verification` is `None`;
    - a `failed` result gives `verification_failed`;
    - a `pending` result gives `verification_pending`;
    - any transaction `1..n` that is not `abandoned` and holds this version gives
      `version_reserved`.
  - The document is exactly `{schema_version, mode, profile: {id, digest}, plan_digest,
    candidate: {version, commit, title}, verification, actions, confirmations, runnable,
    refusal}`.
- **`status()`** never raises a shape refusal. It returns
  `{schema_version, profile: {id, digest}, shape: None | refusal object, release}`.
  - `release` is `None` with no transaction. Otherwise, for the last one:
    - `{transaction_id, ordinal, state, parked_from, reason, version, commit, actions,
      grants, evidence_ids, terminal, receipt, hazard_markers}`;
    - `reason` is the latest `transitioned` event's `reason` while
      `state == "attention_required"`, else `None` (D25);
    - `actions` are `{name, operation, effect, status, attempts, reference}`, where
      `reference` is the latest `action_inspected` event's reference for that action id,
      else `None`;
    - `grants` are `{grant_id, authority_class, valid}`;
    - `terminal` is the snapshot's `terminal` as a dict, and `receipt` is
      `read_receipt(terminal["receipt_digest"])`, else `None`;
    - `hazard_markers` is `{key: list(store.hazard_markers(key))}` per concurrency key.

- [ ] **Step 1: Write the support module and the failing tests**

`tests/release_driver_support.py`:

```python
"""Shared fixtures for the release driver suites (#128 spec, Test seams 2 and 3)."""
import copy
import tempfile
from pathlib import Path

from agent_tools import release_driver, release_profile
from . import release_test_support as support
from .forge_world import CANONICAL

PROJECT_ID = "fagenorn/nix-config"
KEY = "release/fagenorn/nix-config"


class Clock:
    def __init__(self, now: int = 1_790_000_000_000) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


class FixtureStore:
    """`fixture-store` for registry injection: describes itself and is never driven."""

    def describe(self):
        return copy.deepcopy(support.FIXTURE_STORE)

    def inspect(self, request):
        raise AssertionError("fixture-store is never inspected")

    def invoke(self, request):
        raise AssertionError("fixture-store is never invoked")


def candidate(**overrides) -> dict:
    return {"version": CANONICAL["tag"], "commit": CANONICAL["commit"],
            "title": CANONICAL["title"], "notes": "notes body", **overrides}


def project(case, *, profiles=None, integration="main", default="main",
            deploy_adapter="none") -> release_driver.Project:
    scratch = tempfile.TemporaryDirectory()
    case.addCleanup(scratch.cleanup)
    root = Path(scratch.name).resolve() / "checkout"
    (root / ".git").mkdir(parents=True)
    profiles = {"github-release": support.forge_profile()} if profiles is None else profiles
    return release_driver.Project(
        project_id=PROJECT_ID, root=root, common_dir=root / ".git",
        integration_branch=integration, default_branch=default,
        deploy_adapter=deploy_adapter,
        contract={**support.base_contract(), "release": {"profiles": profiles}})


def seed(driver, ordinal=1, **overrides) -> str:
    """Create a transaction directly, as `run` would, and return its id."""
    store = driver.store(create=True)
    inputs = release_profile.bind_candidate(driver.compiled, candidate(**overrides))
    return store.create(
        release_driver.creation_key(PROJECT_ID, driver.profile_id, ordinal),
        inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
        proof=inputs["proof"], recovery=inputs["recovery"],
        authority_class=release_driver.AUTHORITY_CLASS).transaction_id
```

`tests/test_release_driver.py` (Tasks 3 and 5 append classes to it and to the support
module):

```python
"""The release driver library against the real TransactionStore (#128 spec §1, §2, §4, §7).

Run: just agent-workflow-tests"""
import os
import re
import unittest
from pathlib import Path

from agent_tools import forge_adapter, release_driver
from agent_tools.canonical import telemetry_digest
from . import release_driver_support as rs
from . import release_test_support as support
from .forge_world import ForgeWorld

TOKEN = re.compile(r"^(tag|github-release):[0-9a-f]{12}$")


class DriverCase(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        self.clock = rs.Clock()

    def driver(self, project=None, **kwargs):
        return release_driver.Driver(project or rs.project(self), clock=self.clock, **kwargs)

    def assertRefusal(self, code, call, *args, **kwargs):
        with self.assertRaises(release_driver.Refusal) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception


class SelectionTest(DriverCase):
    def test_the_sole_publication_profile_is_selected(self):
        project = rs.project(self, profiles={"github-release": support.forge_profile(),
                                             "forge-target": support.publication_free_profile()})
        self.assertEqual(self.driver(project).profile_id, "github-release")

    def test_ambiguous_unknown_and_inadmissible_refuse(self):
        two = rs.project(self, profiles={"a-release": support.forge_profile(),
                                         "b-release": support.forge_profile()})
        refusal = self.assertRefusal("profile_ambiguous", self.driver, two)
        self.assertIn("a-release, b-release", refusal.detail)
        self.assertEqual(self.driver(two, profile_id="b-release").profile_id, "b-release")
        self.assertRefusal("profile_unknown", self.driver, two, profile_id="nope")
        bad = rs.project(self, profiles={"github-release": support.missing_deadline_profile()})
        self.assertRefusal("profile_inadmissible", self.driver, bad)


class GateTest(DriverCase):
    def test_unrunnable_shapes_refuse_preview_and_show_in_status(self):
        restorable = rs.project(self, profiles={"restorable": support.restorable_profile()})
        registry = {"github-forge": forge_adapter, "fixture-store": rs.FixtureStore()}
        cases = (("merge_not_declared", "release.profile.merge_unsupported",
                  rs.project(self, integration="dev"), {}),
                 ("deploy_watch_unowned", "release.profile.activation_unbound",
                  rs.project(self, deploy_adapter="github-actions-health"), {}),
                 ("anchors_unsupported", "release.profile.anchor_unbound", restorable,
                  {"registry": registry}))
        for code, repair, project, kwargs in cases:
            with self.subTest(code=code):
                driver = self.driver(project, **kwargs)
                refusal = self.assertRefusal(code, driver.preview, rs.candidate())
                self.assertEqual(refusal.repair_id, repair)
                self.assertEqual(driver.status()["shape"]["code"], code)
        self.assertEqual(self.world.calls(), [])

    def test_main_checkout_and_cwd_read_the_filesystem(self):
        root = rs.project(self).root
        self.assertEqual(release_driver.main_checkout(root), root / ".git")
        (root / "sub").mkdir()
        release_driver.require_cwd(root, root / "sub")
        linked = root.parent / "linked"
        linked.mkdir()
        (linked / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        self.assertRefusal("not_main_checkout", release_driver.main_checkout, linked)
        self.assertRefusal("cwd_mismatch", release_driver.require_cwd, root, linked)


class PreviewTest(DriverCase):
    def test_new_preview_names_both_irreversible_actions_and_writes_nothing(self):
        self.world.verification_ready()
        driver = self.driver()
        document = driver.preview(rs.candidate())
        self.assertEqual((document["mode"], document["runnable"], document["refusal"]),
                         ("new", True, None))
        self.assertEqual([(a["name"], a["effect"], a["status"]) for a in document["actions"]],
                         [("tag", "irreversible", None), ("github-release", "irreversible", None)])
        names = [c["action"] for c in document["confirmations"]]
        self.assertEqual(names, ["tag", "github-release"])
        for confirmation in document["confirmations"]:
            self.assertRegex(confirmation["token"], TOKEN)
            self.assertEqual(confirmation["token"], release_driver.token(
                document["plan_digest"], confirmation["action"], 1, 1))
        self.assertFalse((driver.project.common_dir / "agent-release").exists())
        self.assertEqual({c["argv"][0] for c in self.world.calls()}, {"api"})

    def test_tokens_are_stable_and_follow_their_inputs(self):
        self.world.verification_ready()
        driver = self.driver()
        first, again = driver.preview(rs.candidate()), driver.preview(rs.candidate())
        self.assertEqual(first, again)
        retitled = driver.preview(rs.candidate(title="v1.2.3 — other"))
        self.assertNotEqual(retitled["plan_digest"], first["plan_digest"])
        self.assertNotEqual(retitled["confirmations"][0]["token"], first["confirmations"][0]["token"])

    def test_unready_ci_is_not_runnable_but_still_names_the_confirmations(self):
        cases = (("verification_pending", {"runs": []}),
                 ("candidate_stale", {"tip": "9" * 40}))
        for code, kwargs in cases:
            with self.subTest(code=code):
                self.world.reset()
                self.world.verification_ready(**kwargs)
                document = self.driver().preview(rs.candidate())
                self.assertEqual((document["runnable"], document["refusal"]["code"]), (False, code))
                self.assertEqual(len(document["confirmations"]), 2)

    def test_new_mode_needs_a_valid_candidate(self):
        self.assertRefusal("candidate_required", self.driver().preview, None)
        self.assertRefusal("candidate_invalid", self.driver().preview, rs.candidate(version="1.2.3"))

    def test_a_nonterminal_release_is_previewed_for_resume_only(self):
        driver = self.driver()
        tid = rs.seed(driver)
        refusal = self.assertRefusal("release_in_flight", driver.preview, rs.candidate())
        self.assertIn("v1.2.3", refusal.detail)
        document = driver.preview(None)
        digest = driver.store().load(tid).events[0]["proof_plan_digest"]
        self.assertEqual((document["mode"], document["verification"]), ("resume", None))
        self.assertEqual(document["plan_digest"], telemetry_digest(
            {"transaction_id": tid, "proof_plan_digest": digest}))
        self.assertEqual(document["candidate"]["title"], rs.candidate()["title"])
        self.assertEqual(self.world.calls(), [])

    def test_an_abandoned_release_frees_its_version(self):
        self.world.verification_ready()
        driver = self.driver()
        tid = rs.seed(driver)
        store = driver.store()
        custody = store.acquire(tid, executor_id="t", subject_path=str(driver.project.root),
                                ttl_ms=1000).custody
        store.advance(tid, "abandoned", reason="test", external_state="known", custody=custody)
        document = driver.preview(rs.candidate())
        self.assertEqual((document["mode"], document["runnable"]), ("new", True))


class StatusTest(DriverCase):
    def test_no_store_reads_as_no_release(self):
        driver = self.driver()
        self.assertEqual(driver.status()["release"], None)
        self.assertFalse((driver.project.common_dir / "agent-release").exists())

    def test_status_shows_a_nonterminal_release(self):
        driver = self.driver()
        tid = rs.seed(driver)
        store = driver.store()
        custody = store.acquire(tid, executor_id="t", subject_path=str(driver.project.root),
                                ttl_ms=1000).custody
        store.issue_grant(custody, grant_id="g", actor="operator", actor_kind="human",
                          authority_class="release-irreversible")
        release = driver.status()["release"]
        self.assertEqual((release["transaction_id"], release["ordinal"], release["state"],
                          release["version"], release["terminal"], release["receipt"]),
                         (tid, 1, "created", "v1.2.3", None, None))
        self.assertEqual(release["grants"], [{"grant_id": "g",
                                              "authority_class": "release-irreversible",
                                              "valid": True}])
        self.assertEqual([(a["name"], a["status"], a["attempts"]) for a in release["actions"]],
                         [("tag", None, 0), ("github-release", None, 0)])
        self.assertEqual(sorted(release["hazard_markers"]), [rs.KEY])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m agent_tools.suite_runner tests/test_release_driver.py 2>&1 | tail -4`
Expected: FAIL, `ModuleNotFoundError: No module named 'agent_tools.release_driver'`.

- [ ] **Step 3: Write `release_driver.py`**

Implement the Interfaces to the Invariants above. The module docstring names spec §1, §2,
§4 and §7 and D1, D4, D6, D13, D18, D19, D25 and D26. It says that `preview` and `status`
create nothing. Keep `Refusal` codes to exactly those this task uses:
`profile_ambiguous`, `profile_unknown`, `profile_inadmissible`, `not_main_checkout`,
`cwd_mismatch`, `merge_not_declared`, `deploy_watch_unowned`, `anchors_unsupported`,
`candidate_required`, `candidate_invalid` and `release_in_flight`. The in-document codes
are `candidate_stale`, `verification_unavailable`, `verification_pending`,
`verification_failed` and `version_reserved`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m agent_tools.suite_runner tests/test_release_driver.py tests/test_release_verification.py 2>&1 | tail -4`
Expected: `summary members=2 passed=2 failed=0`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release_driver.py tests/release_driver_support.py \
  tests/test_release_driver.py justfile
git commit -m "feat(issue-128/T2): release driver selection, gates, status and preview"
```
