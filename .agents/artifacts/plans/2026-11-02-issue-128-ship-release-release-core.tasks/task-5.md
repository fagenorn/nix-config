# Task 5: Crash and retry matrix, P2 feasibility

**Files:**
- Modify: `tests/release_driver_support.py` (fixture merge and deploy adapters, the two-branch
  fixture profile, the crash wrapper)
- Create: `tests/test_release_crash_matrix.py`
- Modify: `python/agent_tools/release_driver.py` (only when a matrix case exposes a driver
  defect; each fix stays inside Task 3's Invariants)
- Modify: `justfile` (add `tests/test_release_crash_matrix.py` after `tests/test_release_driver.py`)

**Interfaces:**
- Consumes: Tasks 1–3's `Driver`, `CUSTODY_TTL_MS`, `verification_ready` and the support
  module; `release_test_support`'s `forge_profile()` and `FIXTURE_STORE` (descriptor
  template); `tests/test_release_grammar.py`'s activation-unit example (profile template).
- Produces, in `tests/release_driver_support.py`:

```python
BASE_TIP = "5" * 40          # the default branch tip the merge CAS expects
MERGED_TIP = "3" * 40

class Crash(Exception): ...  # a simulated process death

class FixtureMerge:          # registry key "fixture-merge"; operation "merge", mode materialize
    default_tip: str; mutations: list[str]
    def describe(self) -> dict: ...
    def inspect(self, request) -> dict: ...
    def invoke(self, request) -> dict: ...

class FixtureDeploy:         # registry key "fixture-deploy"; activation operation "deploy"
    mutations: list[str]
    def describe(self) -> dict: ...
    def inspect(self, request) -> dict: ...
    def invoke(self, request) -> dict: ...

class CrashAt:
    """Wraps a registry entry: the first invoke of `operation` delegates (after=True) or not
    (after=False), then raises Crash; describe, inspect and later invokes pass through."""
    def __init__(self, inner, operation: str, *, after: bool = True) -> None: ...

def fixture_profile() -> dict: ...   # merge -> tag -> github-release, then activation deploy
```

**Invariants** (§5, Test seams, D2, D12, D20, D21):
- **The fixture descriptors** copy `FIXTURE_STORE`'s member set and values, except:
  - `name`;
  - `operations`, one each:
    - `merge`: `mode` `materialize`, `mutability` `pointer_cas`, `effects`
      `["irreversible"]`, `candidate_members` `[]`;
    - `deploy`: `mode` `provider_deploy`, `effects`
      `["reversible_no_incremental_spend"]`, `candidate_members` `[]`;
  - `predicates`: `publication_visible` supported for merge, `running_subject_identity`
    supported for deploy, the other unsupported with a reason;
  - `target_kinds`: `fixture_branch: ["branch"]` and `fixture_service: ["service"]`;
  - `executables`: one fixture name each.

  `release_adapter.descriptor_problems` must be `[]` for both.
- **Observations** follow `release_adapter`'s closed shapes:
  - an effect observation is `{outcome, reason, observed_subject: {}, references: [],
    observed_at: <int>, facts: {}}`;
  - a predicate observation is `{outcome, reason, references: [], observed_at: <int>}`;
  - an invoke result is `{result, error_class, reference}`.

  A non-`satisfied` derived predicate uses a reason from
  `transaction_plan.DERIVED_REASONS` for its class: `ref_absent` for merge and
  `subject_absent` for deploy.
- **FixtureMerge** is CAS-atomic in the fake:
  - `invoke` applies the merge only when `default_tip == BASE_TIP`. It sets
    `default_tip = MERGED_TIP`, appends `"merge"` to `mutations` and returns `accepted`.
    Otherwise it returns `rejected` / `precondition_failed` and changes nothing.
  - Effect inspection reads `satisfied` when `default_tip == MERGED_TIP`, `absent` when it
    is `BASE_TIP`, and `diverged` otherwise.
  - `publication_visible` reads `satisfied` exactly when merged.
- **FixtureDeploy:**
  - `invoke` appends `"deploy"` and marks the unit deployed.
  - Effect inspection reads `satisfied` once deployed, else `absent`.
  - `running_subject_identity` reads `satisfied` once deployed.
- **`fixture_profile()`** extends `forge_profile()`:
  - adapter aliases `merge` (`fixture-merge`) and `deploy` (`fixture-deploy`), with
    requirement ranges, targets, a principal and credentials of class `fixture_token`;
  - publication `merge` (`irreversible`, no deps), then `tag` (deps `["merge"]`), then
    `github-release`;
  - activation unit `deploy` (`reversible_no_incremental_spend`), with every
    `observation_deadline_ms` at 600000;
  - recovery units all `supersedable_only` with null anchors.

  It compiles with `build_descriptors({"github-forge": forge_adapter, "fixture-merge":
  FixtureMerge(), "fixture-deploy": FixtureDeploy()})`.
- **The matrix project** is `project(case, profiles={"two-branch": fixture_profile()},
  integration="dev")`. Gate 3 passes because `merge` is `materialize` (D1). Its
  verification reads are `verification_ready(integration="dev", default="main")`.
- **A crash** is `CrashAt` raising out of `Driver.run`. The test then advances the clock by
  `CUSTODY_TTL_MS + 1` and re-previews; custody was never released (D21).
- **Assertions** read the worlds' mutation logs and the core snapshot:
  - one effect per action: `FixtureMerge.mutations`, the fake `git push` of the tag, the
    fake `gh release create` and `FixtureDeploy.mutations`;
  - every postcondition inspected before the next action;
  - a retry only with a fresh token.

- [ ] **Step 1: Write the fixtures and the failing matrix**

Add the fixtures above to `tests/release_driver_support.py`. Then create
`tests/test_release_crash_matrix.py`:

```python
"""Crash and retry matrix over merge, tag, Release and deploy (#128 AC3, AC8; spec Test seams)."""
import unittest

from agent_tools import release_adapter, release_driver
from . import release_driver_support as rs
from .forge_world import ROWS, ForgeWorld

ORDER = ["merge", "tag", "github-release", "deploy"]


class MatrixCase(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        self.world.verification_ready(integration="dev", default="main")
        self.clock = rs.Clock()
        self.forge, self.merge, self.deploy = (rs.StatefulForge(self.world), rs.FixtureMerge(),
                                               rs.FixtureDeploy())

    def driver(self, crash=None):
        registry = {"github-forge": self.forge, "fixture-merge": self.merge,
                    "fixture-deploy": self.deploy}
        if crash is not None:
            key, operation, after = crash
            registry[key] = rs.CrashAt(registry[key], operation, after=after)
        project = rs.project(self, profiles={"two-branch": rs.fixture_profile()}, integration="dev")
        return release_driver.Driver(project, registry=registry, clock=self.clock)

    def counts(self):
        pushes = sum(c["argv"] == ROWS["tag.push"]["argv"][1:] for c in self.world.calls())
        creates = sum(c["argv"][:2] == ["release", "create"] for c in self.world.calls())
        return {"merge": len(self.merge.mutations), "tag": pushes, "github-release": creates,
                "deploy": len(self.deploy.mutations)}

    def crash_then_resume(self, crash):
        driver = self.driver(crash)
        shown = driver.preview(rs.candidate())
        with self.assertRaises(rs.Crash):
            driver.run(rs.candidate(), [c["token"] for c in shown["confirmations"]])
        self.clock.advance(release_driver.CUSTODY_TTL_MS + 1)
        resumed = driver.preview(None)
        self.assertEqual(resumed["mode"], "resume")
        stale = [c["token"] for c in shown["confirmations"]]
        fresh = [c["token"] for c in resumed["confirmations"]]
        if fresh:
            with self.assertRaises(release_driver.Refusal) as caught:
                driver.run(None, stale)
            self.assertIn(caught.exception.code, ("confirmation_stale", "confirmation_required"))
        result = driver.run(None, fresh)
        return driver, result


class FixtureShapeTest(MatrixCase):
    def test_the_fixture_profile_compiles_in_order(self):
        compiled = self.driver().compiled
        self.assertEqual([n["id"] for n in (*compiled["publication"], *compiled["activation"])],
                         ORDER)
        for adapter in (self.merge, self.deploy):
            self.assertEqual(release_adapter.descriptor_problems(adapter.describe()), [])

    def test_a_moved_default_tip_never_merges(self):
        self.merge.default_tip = "9" * 40
        _, result = rs.release(self.driver(), rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
        self.assertEqual(self.counts(), {"merge": 0, "tag": 0, "github-release": 0, "deploy": 0})


class CrashMatrixTest(MatrixCase):
    def test_merge_done_tag_interrupted_resumes_without_remerge_or_retag(self):
        driver, result = self.crash_then_resume(("github-forge", "tag", True))
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(self.counts(), {"merge": 1, "tag": 1, "github-release": 1, "deploy": 1})

    def test_each_arm_resumes_after_a_crash_past_its_mutation(self):
        arms = {"merge": ("fixture-merge", "merge"), "tag": ("github-forge", "tag"),
                "github-release": ("github-forge", "release"),
                "deploy": ("fixture-deploy", "deploy")}
        for arm, (key, operation) in arms.items():
            with self.subTest(arm=arm):
                self.setUp()
                _, result = self.crash_then_resume((key, operation, True))
                self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
                self.assertEqual(self.counts(), dict.fromkeys(ORDER, 1))

    def test_a_crash_before_the_mutation_retries_only_with_a_fresh_token(self):
        driver, result = self.crash_then_resume(("github-forge", "tag", False))
        self.assertEqual(result["next"], "done")
        self.assertEqual(self.counts()["tag"], 1)
        tag = next(a for a in driver.status()["release"]["actions"] if a["name"] == "tag")
        self.assertEqual(tag["attempts"], 2)

    def test_each_postcondition_is_inspected_before_the_next_action(self):
        driver = self.driver()
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual(result["next"], "done")
        events = driver.store().load(result["transaction_id"]).events
        names = {e["action_id"]: e["name"] for e in events if e["type"] == "action_declared"}
        firsts = {}
        lasts = {}
        for event in events:
            name = names.get(event.get("action_id"))
            if name is None:
                continue
            firsts.setdefault(name, event["seq"])
            if event["type"] == "action_inspected" and event["outcome"] == "satisfied":
                lasts[name] = event["seq"]
        for before, after in zip(ORDER, ORDER[1:]):
            self.assertLess(lasts[before], firsts[after], (before, after))


if __name__ == "__main__":
    unittest.main()
```

`self.setUp()` inside the subtest loop deliberately rebuilds the worlds per arm. Its
cleanups stack harmlessly.

- [ ] **Step 2: Run the matrix and watch it fail**

Run the root's suite form on `tests/test_release_crash_matrix.py`.
Expected: FAIL, `AttributeError: module 'tests.release_driver_support' has no attribute
'FixtureMerge'` until the fixtures exist. After that, any remaining failure is a driver
defect or a fixture-shape error.

- [ ] **Step 3: Make it pass**

Finish the fixtures until `FixtureShapeTest` passes. Change them only to satisfy the grammar
or the descriptor validator, never an assertion. When a `CrashMatrixTest` case still fails,
fix `release_driver.py` inside Task 3's Invariants. Typical defects are re-reading the fold
after a re-acquisition, or computing the acquisition ordinal before `acquire`. Name each fix
in the commit body. If a case can pass only by violating a Task 3 invariant, or by
re-invoking a satisfied action, stop and report: that is a design defect, not a test fix.

- [ ] **Step 4: Verify**

Run the root's suite form on `tests/test_release_crash_matrix.py tests/test_release_driver.py tests/test_release_command.py`.
Expected: `summary members=3 passed=3 failed=0`.

- [ ] **Step 5: Commit** exactly the Files paths, subject `feat(issue-128/T5): release crash and retry matrix`.

- [ ] **Step 6: P2 feasibility (P2 = Task 5, D23)**

Run the root's package check with `<first>` = `T5`.

Expected: exit 0. This step has nothing to commit.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":5,"records":[{"bounds":[{"added_lines":520,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["r2b","r3b","r5a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5a","last_task":5,"owner":5,"path":"tests/release_driver_support.py"},{"bounds":[{"added_lines":380,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["r5b"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r5b","last_task":5,"owner":5,"path":"tests/test_release_crash_matrix.py"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":0,"record_bytes":4096,"support":{"covers":["r1d","r2d","r5c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5c","last_task":5,"owner":5,"path":"justfile"}]}}
```
