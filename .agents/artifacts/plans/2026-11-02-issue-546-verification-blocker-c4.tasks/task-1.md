# Task 1: Batched observing in the adapter

**Files:**
- Modify: `python/agent_tools/verification_observe.py` (`observe`, new `observe_all`, module docstring)
- Modify: `tests/test_verification_observe.py` (new `ObserveAllTest`)
- Modify: `python/README.md` (`## verification-observe`, second paragraph)

**Interfaces:**
- Consumes: `agent_tools.verification_blocker.validate_requirement`, `validate_observation`, `BlockerRefused`; this module's private `_resolve`, `_fetch`, `_read_facts`, `_repository` and `ObserveRefused`, all unchanged.
- Produces: `observe_all(repo_root: str, requirements: object) -> tuple[list[dict], list[tuple[str, str]]]`, the `(observations, refused)` pair Task 2's `orchestrate-control step` imports (D2). `observe(repo_root, requirement) -> dict` keeps its signature, its CLI output and its `ObserveRefused`.

**Invariants:**
- `requirements` that is not a list raises `BlockerRefused("requirements: must be a list")`; an element `validate_requirement` refuses raises `BlockerRefused("requirements[<i>]: <that refusal>")`; both before any process starts, so the tracking ref is unmoved (D2).
- `[]` returns `([], [])` and resolves, fetches and reads nothing.
- Otherwise one resolution (no capability required), one branch-name check, one fetch and one `rev-parse` of the tracking ref serve every requirement; each requirement's paths are then read at that one commit, each by its own `ls-tree` (issue 543 D11, D12, D14).
- A refusal of the resolution, the branch name or the fetch refuses every requirement with that one reason; an `ls-tree` or `validate_observation` refusal refuses only its own requirement.
- Every requirement lands in exactly one list, both in input order. A refusal is `(blocker_id, reason)`, `reason` being `" ".join(str(error).split())`, exactly what the command prints after `verification-observe: `. A refused requirement never yields an observation, a `null` or a stale ref's value (issue 543 D6).
- `observe` and `observe_all` share one path; the CLI keeps exactly `failure` and `observe` (no `observe-all` mode).

- [ ] **Step 1: Write the failing tests**

In `tests/test_verification_observe.py`, after `import unittest` add `from unittest import mock`, and after `from agent_tools import verification_blocker as vb` add `from agent_tools import verification_observe as vo`. Then insert before `if __name__ == "__main__":`:

```python
class ObserveAllTest(ObserveCase):
    """`observe_all` by import, under this case's HOME, Git and PATH (issue 546 D2, D11)."""

    LOCK = {"kind": "verification", "blocker_id": "sha256:" + "1" * 64,
            "sources": [{"name": "flake-lock", "paths": ["flake.lock"]}]}
    NESTED = {"kind": "verification", "blocker_id": "sha256:" + "2" * 64,
              "sources": [{"name": "packages", "paths": ["pkgs/nested"]}]}

    def setUp(self):
        super().setUp()
        self.patch_environment(self.env)

    def patch_environment(self, env):
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def test_an_empty_list_observes_nothing_and_fetches_nothing(self):
        self.publish({"flake.lock": "lock 2\n"})
        before = self.tracking()
        self.assertEqual(vo.observe_all(str(self.root), []), ([], []))
        self.assertEqual(self.tracking(), before)

    def test_each_requirement_is_observed_as_observe_prints_it_after_one_fetch(self):
        self.publish({"flake.lock": "lock 2\n"})
        observations, refused = vo.observe_all(str(self.root), [self.NESTED, self.LOCK])
        self.assertEqual(refused, [])
        self.assertEqual(observations,
                         [self.ok(self.call("observe", requirement))
                          for requirement in (self.NESTED, self.LOCK)])
        self.assertEqual(self.tracking(), self.git(self.origin, "rev-parse", "main"))

    def test_an_unreachable_origin_refuses_every_requirement(self):
        before = self.tracking()
        self.git(self.root, "remote", "set-url", "origin", str(self.scratch / "missing.git"))
        observations, refused = vo.observe_all(str(self.root), [self.LOCK, self.NESTED])
        self.assertEqual(observations, [])
        self.assertEqual([blocker for blocker, _ in refused],
                         [self.LOCK["blocker_id"], self.NESTED["blocker_id"]])
        for _, reason in refused:
            self.assertTrue(reason.startswith("git fetch: "), reason)
            self.assertNotIn("\n", reason)
        self.assertEqual(refused[0][1], refused[1][1])
        self.assertEqual(self.tracking(), before)

    def test_a_failed_read_refuses_only_its_own_requirement(self):
        real = shutil.which("git", path=self.env.get("PATH"))
        shim = self.scratch / "shim"
        shim.mkdir()
        (shim / "git").write_text(
            '#!/bin/sh\nfor a in "$@"; do [ "$a" = pkgs/nested ] && '
            '{ echo "fatal: bad tree" >&2; exit 128; }; done\nexec '
            + shlex.quote(real) + ' "$@"\n', encoding="utf-8")
        (shim / "git").chmod(0o755)
        self.patch_environment({**self.env, "PATH": f"{shim}{os.pathsep}{self.env['PATH']}"})
        observations, refused = vo.observe_all(str(self.root), [self.NESTED, self.LOCK])
        self.assertEqual(refused, [(self.NESTED["blocker_id"], "git ls-tree: fatal: bad tree")])
        self.assertEqual([item["blocker_id"] for item in observations],
                         [self.LOCK["blocker_id"]])

    def test_a_malformed_list_raises_before_any_fetch(self):
        self.publish({"flake.lock": "lock 2\n"})
        before = self.tracking()
        for value, fragment in (
                ({"kind": "verification"}, "requirements: must be a list"),
                ([self.LOCK, {**self.NESTED, "kind": "probe"}],
                 "requirements[1]: requirement.kind: must be verification"),
                ([{**self.LOCK, "schema_version": 1}], "requirements[0]: requirement: ")):
            with self.subTest(value=value):
                with self.assertRaises(vb.BlockerRefused) as caught:
                    vo.observe_all(str(self.root), value)
                self.assertTrue(str(caught.exception).startswith(fragment), caught.exception)
        self.assertEqual(self.tracking(), before)
```

The patch uses `clear=True`, so `os.environ` is exactly the case's scrubbed `env` (temporary `HOME`, hermetic Git) while the function runs in process, as `actions_world` and `host_world` patch theirs.

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `PYTHONPATH="$PWD/python" python3 -m unittest tests.test_verification_observe.ObserveAllTest 2>&1 | tail -3`
Expected: `Ran 5 tests`, `FAILED (errors=5)`, each `AttributeError: module 'agent_tools.verification_observe' has no attribute 'observe_all'`.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/verification_observe.py`, replacing `observe` (D2):

- `_reason(error: Exception) -> str` returns `" ".join(str(error).split())`, the line `main` prints after its prefix.
- `_observations(repo_root: str, requirements: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]` takes requirements already validated. `[]` returns `([], [])` before anything else. Then, in one `try`, `snapshot = _resolve(repo_root)` and `commit = _fetch(snapshot)`; an `ObserveRefused` there returns `([], [(r["blocker_id"], _reason(error)) for r in requirements])`. Then, for each requirement in order, in its own `try`: `facts = _read_facts(snapshot["project"]["root"], commit, requirement["sources"])` and `validate_observation({"kind": OBSERVATION_KIND, "schema_version": SCHEMA_VERSION, "blocker_id": requirement["blocker_id"], "repository": _repository(snapshot), "facts": facts})` appended to the observations; `except (ObserveRefused, BlockerRefused) as error:` appends `(requirement["blocker_id"], _reason(error))` to the refusals. Docstring: `Observe valid requirements at one fetched commit (issue 546 D2): a resolution or fetch refusal refuses every requirement, a read or build refusal only its own.`
- `observe_all(repo_root: str, requirements: object)` checks `isinstance(requirements, list)` (else `raise BlockerRefused("requirements: must be a list")`), then each element with `validate_requirement`, re-raising `BlockerRefused(f"requirements[{index}]: {refusal}") from None`, then returns `_observations(repo_root, requirements)`. Docstring:

  ```text
  The observations of every requirement, after one resolution and at most one fetch
  (issue 546 D2): `(observations, refused)`, each in input order, every requirement in
  exactly one of them; a refusal is `(blocker_id, reason)`, never an observation.

  A non-list, or an element that is not a valid requirement, raises `BlockerRefused`
  naming `requirements[<i>]` before any process starts; an empty list does no I/O.
  ```
- `observe` keeps its docstring and becomes: `validate_requirement(requirement)` inside `try`, a `BlockerRefused` re-raised as `ObserveRefused(str(error)) from error` (its CLI wording is unchanged: no `requirements[0]` prefix); then `observations, refused = _observations(repo_root, [requirement])`; `if refused: raise ObserveRefused(refused[0][1])`; `return observations[0]`.
- Module docstring: after the line ending `` `verification-observe: invalid invocation` and exits 2; `--help` exits 0. `` add the two lines `The importable `observe_all` observes a list of requirements after one fetch` / `(issue 546 D2); no command mode runs it.`

`python/README.md` § `verification-observe`, second paragraph: after the sentence ending ``…return the same objects or raise `ObserveRefused`.`` insert:

```text
The importable `observe_all(repo_root, requirements)` is the batched form, which no command mode runs (issue 546): it raises `BlockerRefused` naming `requirements[<i>]`, or `requirements: must be a list`, before any process starts; an empty list returns `([], [])` and does no I/O; otherwise it resolves the project once, fetches once and reads the tracking ref once, then reads each requirement's paths at that commit and builds each observation as `observe` does. It returns `(observations, refused)`, each in input order and every requirement in exactly one, a refusal being `(blocker_id, reason)` with `reason` the line the command would print after its prefix: a resolution, branch-name or fetch refusal refuses every requirement, and a read or build refusal only its own. `observe` is its one-requirement form over the same path.
```

- [ ] **Step 4: Verify**

Run (timeout 900 s): `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_verification_observe.py tests/test_verification_blocker.py 2>&1 | tail -3`
Expected: `OK`, with 22 tests from `test_verification_observe.py` (17 existing, `ObserveTest`'s CLI wording unchanged) plus `test_verification_blocker.py`'s.
Run: `grep -c '^def observe_all(' python/agent_tools/verification_observe.py; grep -c 'observe_all(repo_root, requirements)' python/README.md; PYTHONPATH="$PWD/python" python3 -m agent_tools.verification_observe --help | grep -c observe-all`
Expected: `1`, `1`, then `0` (no command mode; that last `grep -c` exits 1, the passing case).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/verification_observe.py tests/test_verification_observe.py python/README.md
launch-commit … -- -m "feat(verification-observe): observe_all after one fetch" -m "Issue 546." -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"a4f46fc34ccdc135c64404d28ec538b84729d1b6","head":"28341d621a05338d3cf8ce5c253c296401232418"}],"commit_subject_bytes":[64,64,64],"id":1,"records":[{"bounds":[{"added_lines":65,"boundary":"all","deleted_lines":10,"record_bytes":7680,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1a","last_task":1,"owner":1,"path":"python/agent_tools/verification_observe.py"},{"bounds":[{"added_lines":95,"boundary":"all","deleted_lines":2,"record_bytes":7680,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":1,"owner":1,"path":"tests/test_verification_observe.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":18432,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":3,"owner":1,"path":"python/README.md"}]}}
```
