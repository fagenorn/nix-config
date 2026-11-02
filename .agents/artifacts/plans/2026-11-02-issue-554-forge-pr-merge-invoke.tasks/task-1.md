# Task 1: The candidate's `merge` binding

Per D2 and D15. Read the plan root's Global Constraints first. The forge descriptor is not touched here: Task 2 flips it, so this task's tests compile against a patched copy.

**Files:**
- Modify: `python/agent_tools/release_adapter.py` (`CANDIDATE_MEMBERS`)
- Modify: `python/agent_tools/release_profile.py` (`_candidate_problem` becomes `candidate_problem`; new `MERGE_MEMBER`, `MERGE_KEYS`, `_merge_problem`, `binds_merge`; `bind_candidate`)
- Modify: `tests/release_test_support.py` (new `MERGE`, `merge_profile()`, `merge_descriptors()`)
- Modify: `tests/release_driver_support.py` (new `forge_merge_profile()`)
- Modify: `tests/test_release_profile.py` (new `MergeBindingTest`)
- Modify: `python/README.md` (§ Release profiles: one sentence appended after the `bind_candidate(compiled, candidate)` sentence)

**Interfaces:**
- Consumes: `release_profile.compile_profile`, `bind_candidate` and `ResolvedReleaseProfile` as at base; `compiled["candidate_members"]` maps each node id to its operation's `candidate_members`.
- Produces:
  - `release_adapter.CANDIDATE_MEMBERS == ("merge", "notes", "title")` (sorted; the descriptor check requires a sorted unique subset).
  - `release_profile.MERGE_MEMBER = "merge"`, `release_profile.MERGE_KEYS = frozenset(("pr", "base_tip"))`.
  - `release_profile.candidate_problem(candidate: object) -> str | None`: the base `_candidate_problem`, renamed public, unchanged. It checks exactly the operator's four members (`CANDIDATE_KEYS` stays `version`, `commit`, `title`, `notes`). Task 4's driver calls it before observing `merge`.
  - `release_profile.binds_merge(compiled: ResolvedReleaseProfile) -> bool`: true when any node's `candidate_members` holds `"merge"`.
  - `bind_candidate(compiled, candidate)`: as at base, plus the `merge` rules below.
  - `release_test_support.MERGE == {"pr": 336, "base_tip": "5" * 40}` (the spelling fixture's canonical `pr` and `base_tip`).
  - `release_test_support.merge_profile() -> dict`: `forge_profile()` with a `merge` node (`mode: materialize`, `operation: pr_merge`, adapter `forge`, target `repository`, principal `maintainer`, credential `forge-keyring`, `effect: irreversible`, `deps: []`, `observation_deadline_ms: 600000`, `config: {}`, `config_schema_version: 1`) inserted first, `tag.deps == ["merge"]`, and a `recovery.units.merge` equal to the `tag` unit. This is the JarBird shape: `pr_merge` → `tag` → `github-release` on one target, branch `main`.
  - `release_test_support.merge_descriptors() -> dict`: `descriptors()` with `github-forge`'s `pr_merge` entry updated to `support: "supported"`, `reason: None`, `candidate_members: ["merge"]`. Task 2 deletes it once the real descriptor says the same.
  - `release_driver_support.forge_merge_profile() -> dict`: `fixture_profile()` with its `merge` node moved onto the forge (`adapter: "forge"`, `operation: "pr_merge"`, `target: "repository"`, `principal: "maintainer"`, `credential: "forge-keyring"`) and the `fixture-merge` alias removed (`requirements.adapters.merge`, `bindings.adapters.merge`, `bindings.targets.trunk`, `bindings.credentials["merge-token"]`). It keeps `fixture-deploy`'s `deploy` activation unit. Task 5's two-branch matrix uses it.

**Invariants:**
- A candidate carries `merge` exactly when `binds_merge(compiled)`. Otherwise `bind_candidate` raises `ValueError`: a merge profile without `merge`, or any other profile with it.
- `merge` is exactly `{pr, base_tip}`. `pr` has `type(pr) is int` and `pr >= 1`, so `True`, `0` and `"336"` are refused. `base_tip` matches `COMMIT_PATTERN` (40 lowercase hex).
- The operator's four members are checked first by `candidate_problem` on the candidate without `merge`, so a bad title is reported as before, whatever `merge` holds.
- With a merge, the subject's `candidate` is `{version, commit, merge}`, and so is the `candidate` of every proof and recovery unit whose node's adapter alias is the alias of a node that consumes `merge`. Units of any other alias keep `{version, commit}` (D15). `merge` is never a top-level unit parameter.
- `notes` and `title` bind as before. A single-branch profile's `bind_candidate` output is byte-identical to base.
- No descriptor, digest or adapter module other than `release_adapter.CANDIDATE_MEMBERS` changes.

- [ ] **Step 1: Write the failing test**

Add the three support helpers above. Then add to `tests/test_release_profile.py` (import `release_driver_support as rs` beside `release_test_support as support`):

```python
class MergeBindingTest(unittest.TestCase):
    """Issue 554 D2, D15: `merge` is an identity member bound beside version and commit."""

    IDENTITY = {"version": "v1.2.3", "commit": "1" * 40,
                "merge": {"pr": 336, "base_tip": "5" * 40}}

    def compiled(self, profile, profile_id="two-branch", extra=None):
        descriptors = {**support.merge_descriptors(), **(extra or {})}
        return release_profile.compile_profile(profile_id, profile, support.base_contract(),
                                               descriptors)

    def test_a_merge_profile_binds_merge_into_the_subject_and_every_forge_unit(self):
        compiled = self.compiled(support.merge_profile())
        self.assertTrue(release_profile.binds_merge(compiled))
        inputs = release_profile.bind_candidate(compiled, {**support.CANDIDATE, "merge": support.MERGE})
        self.assertEqual(inputs["subject"]["candidate"], self.IDENTITY)
        self.assertEqual([u["name"] for u in inputs["proof"]["units"]],
                         ["merge", "tag", "github-release"])
        for unit in (*inputs["proof"]["units"], *inputs["recovery"]["units"]):
            with self.subTest(unit=unit["name"]):
                self.assertEqual(unit["parameters"]["candidate"], self.IDENTITY)
                self.assertNotIn("merge", unit["parameters"])
        self.assertEqual(inputs["proof"]["units"][2]["parameters"]["title"], support.CANDIDATE["title"])

    def test_merge_reaches_only_the_units_of_the_consuming_alias(self):
        deploy = rs.FixtureDeploy().describe()
        compiled = self.compiled(rs.forge_merge_profile(), extra={"fixture-deploy": deploy})
        inputs = release_profile.bind_candidate(compiled, {**support.CANDIDATE, "merge": support.MERGE})
        candidates = {unit["name"]: unit["parameters"]["candidate"] for unit in inputs["proof"]["units"]}
        self.assertEqual(candidates["deploy"], {"version": "v1.2.3", "commit": "1" * 40})
        for name in ("merge", "tag", "github-release"):
            self.assertEqual(candidates[name], self.IDENTITY)

    def test_a_merge_profile_refuses_a_missing_or_malformed_merge(self):
        compiled = self.compiled(support.merge_profile())
        for merge in (None, {}, {"pr": 0, "base_tip": "5" * 40}, {"pr": True, "base_tip": "5" * 40},
                      {"pr": "336", "base_tip": "5" * 40}, {"pr": 336, "base_tip": "5" * 39},
                      {"pr": 336, "base_tip": "A" * 40}, {"pr": 336, "base_tip": "5" * 40, "x": 1}):
            with self.subTest(merge=merge):
                candidate = dict(support.CANDIDATE) if merge is None else {**support.CANDIDATE, "merge": merge}
                with self.assertRaises(ValueError):
                    release_profile.bind_candidate(compiled, candidate)
        with self.assertRaisesRegex(ValueError, "title"):
            release_profile.bind_candidate(compiled, {**support.CANDIDATE, "title": 'a "q"',
                                                      "merge": support.MERGE})

    def test_a_profile_without_a_merge_node_refuses_merge_and_binds_as_before(self):
        compiled = self.compiled(support.forge_profile(), "github-release")
        self.assertFalse(release_profile.binds_merge(compiled))
        with self.assertRaises(ValueError):
            release_profile.bind_candidate(compiled, {**support.CANDIDATE, "merge": support.MERGE})
        inputs = release_profile.bind_candidate(compiled, support.CANDIDATE)
        self.assertEqual(inputs["subject"]["candidate"], {"version": "v1.2.3", "commit": "1" * 40})

    def test_candidate_problem_checks_only_the_operator_members(self):
        self.assertIsNone(release_profile.candidate_problem(dict(support.CANDIDATE)))
        self.assertIsNotNone(release_profile.candidate_problem({**support.CANDIDATE, "merge": support.MERGE}))
        self.assertIsNotNone(release_profile.candidate_problem({**support.CANDIDATE, "version": "1.2.3"}))
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_profile.py -k MergeBinding 2>&1 | tail -4'`
Expected: FAIL. `compile_profile` raises on the patched descriptor, because `"merge"` is outside `CANDIDATE_MEMBERS`, and `binds_merge` and `candidate_problem` are not defined.

- [ ] **Step 3: Write the minimal implementation**

In `release_adapter.py`, set `CANDIDATE_MEMBERS = ("merge", "notes", "title")`.

In `release_profile.py`, rename `_candidate_problem` to `candidate_problem` (one caller) and add `MERGE_MEMBER`, `MERGE_KEYS`, `_merge_problem(merge) -> str | None` and `binds_merge(compiled)`. In `bind_candidate`, after the `TypeError` and publication checks, check the candidate in this order and raise `ValueError` with the first problem:

1. A non-dict candidate fails through `candidate_problem(candidate)`.
2. Next, `candidate_problem` runs on the candidate without its `merge` key.
3. A merge profile whose candidate lacks `merge` fails with "candidate must carry merge, which node `<id>` consumes".
4. A non-merge profile whose candidate has `merge` fails with "candidate carries merge, which no node of the profile consumes".
5. Last, `_merge_problem` runs on the member.

Build `identity = {version, commit}`, and `bound = {**identity, "merge": {"pr": …, "base_tip": …}}` when `binds_merge`, else `identity`. The aliases that consume `merge` are `{node["adapter"] for node in publication and activation if "merge" in compiled["candidate_members"][node["id"]]}`. Each unit's `candidate` is a fresh copy of `bound` when its node's adapter alias is in that set, else a copy of `identity`. The `for member in candidate_members` loop skips `"merge"`. The subject's `candidate` is `bound`. Update the `bind_candidate` docstring to state the `merge` rule, citing "issue 554 D2, D15".

In `python/README.md` § Release profiles, append this one sentence after the sentence that begins "`bind_candidate(compiled, candidate)` takes only":

"A profile with a node that consumes the `merge` candidate member (`release_profile.binds_merge`, issue 554 D2) needs the candidate to carry `merge: {pr, base_tip}`, a positive integer and 40 lowercase hex digits. It binds that member, beside `version` and `commit`, into the subject's `candidate` and into the `candidate` of every unit of the consuming node's adapter alias, and any other profile refuses a candidate that carries it (issue 554 D15)."

Change nothing else on that line.

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_profile.py tests/test_release_grammar.py tests/test_release_adapter_core.py tests/test_release_driver.py tests/test_forge_adapter.py 2>&1 | tail -4'`
Expected: PASS, `OK`. Base's counts plus 5. The base digest pins in `test_release_adapter_core.py` still hold, because no descriptor changed.

Run: `if git grep -n '_candidate_problem' -- python/agent_tools/release_profile.py; then exit 1; fi`
Expected: exit 0.

Run (timeout 3600 s): `just build`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release_adapter.py python/agent_tools/release_profile.py tests/release_test_support.py tests/release_driver_support.py tests/test_release_profile.py python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-554/T1): bind the candidate's merge member" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":2048,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1a","last_task":1,"owner":1,"path":"python/agent_tools/release_adapter.py"},{"bounds":[{"added_lines":60,"boundary":"all","deleted_lines":15,"record_bytes":10240,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":1,"owner":1,"path":"python/agent_tools/release_profile.py"},{"bounds":[{"added_lines":35,"boundary":"all","deleted_lines":0,"record_bytes":4096,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":2,"owner":1,"path":"tests/release_test_support.py"},{"bounds":[{"added_lines":20,"boundary":"all","deleted_lines":0,"record_bytes":3072,"support":{"covers":["r1d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1d","last_task":5,"owner":1,"path":"tests/release_driver_support.py"},{"bounds":[{"added_lines":70,"boundary":"all","deleted_lines":0,"record_bytes":8192,"support":{"covers":["r1e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1e","last_task":2,"owner":1,"path":"tests/test_release_profile.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":1,"record_bytes":20480,"support":{"covers":["r1f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1f","last_task":5,"owner":1,"path":"python/README.md"}]}}
```
