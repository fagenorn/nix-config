# Task 6: Legacy cutover

**Files:**
- Create: `python/agent_tools/release_cutover.py`
- Modify: `python/agent_tools/release_driver.py` (gate 2, `status.legacy`, `run`'s deletion)
- Create: `tests/test_release_cutover.py`
- Modify: `tests/test_release_command.py` (add `LegacyCommandTest`)
- Modify: `python/README.md` (`## Release driver`: replace Task 4's closing legacy line)
- Modify: `justfile` (add `tests/test_release_cutover.py` after `tests/test_release_crash_matrix.py`)

**Interfaces:**
- Consumes:
  - Tasks 2–3's `Driver.preview`, `Driver.run`, `Driver.status` and `Refusal`;
  - Task 4's `TransactionCommandTest` helpers (`candidate()`, `run_with`, `store_exists`)
    and `run_release(..., cwd=)`;
  - `tests/release_driver_support` (`project`, `candidate`, `release`, `StatefulForge`).
- Produces:

```python
# python/agent_tools/release_cutover.py
LEGACY_PATH = ".superpowers/workflows/ship-release/state.json"
LEGACY_KEYS = frozenset(("headSha", "pr", "prUrl", "mergeSha", "tag", "releaseUrl",
                         "deployState"))
CLASSES = ("absent", "completed", "in_flight", "unreadable")
MAX_BYTES = 65536

def classify(repo_root: Path) -> dict[str, str]: ...   # {"class": <CLASSES>, "path": <abs str>}
def retire(repo_root: Path) -> None: ...               # unlink a `completed` file, else ValueError
```

- `Driver.status()` gains the member `legacy` (the `classify` dict). `Driver.run`'s
  document gains `legacy`: `"deleted"` when this run retired a completed file, else `None`.

**Invariants** (§6, D8):
- **`classify`** never follows a symlink and never imports a field:
  - `absent`: `lstat` raises `FileNotFoundError` (a missing parent included).
  - `unreadable`: any of these:
    - a symlink, or not a regular file;
    - larger than `MAX_BYTES`;
    - an `OSError` on read, invalid UTF-8 or invalid JSON;
    - not an object, or a key set other than exactly `LEGACY_KEYS`.
  - `completed`: `releaseUrl is not None`, or `tag is not None` with `pr is None`; and
    `deployState in ("done", "none")`.
  - `in_flight`: every other object with exactly `LEGACY_KEYS`.
- **`retire`** re-classifies and unlinks only a `completed` file. Any other class raises
  `ValueError` and touches nothing.
- **Gate 2:**
  - `preview` and `run` refuse `legacy_release_in_flight` (repair `release.legacy.finish`)
    for `in_flight` or `unreadable`. The detail names the class and the path, and says to
    finish the release with the previous generation's ship-release, or to remove the file
    once the user confirms the release is abandoned. Gate order is gate 2, then the shape
    gates (§1).
  - `status` reports and never refuses. `abandon` does not apply gate 2.
- **Deletion.** In new mode only, `run` calls `retire` after the confirmation checks and
  immediately before `create`. It never retires in resume mode, and nothing from the file
  reaches the store.

- [ ] **Step 1: Write the failing tests**

`tests/test_release_cutover.py`:

```python
"""Legacy ship-release state at cutover (#128 AC6, spec §6, D8).

Run: just agent-workflow-tests"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_tools import release_cutover as cutover
from agent_tools import release_driver
from . import release_driver_support as rs
from .forge_world import ForgeWorld

STATE = {"headSha": "1" * 40, "pr": None, "prUrl": None, "mergeSha": None, "tag": None,
         "releaseUrl": None, "deployState": "pending"}


def write(root, value):
    path = root / cutover.LEGACY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    return path


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()

    def classify(self, value):
        write(self.root, value)
        return cutover.classify(self.root)["class"]

    def test_absent(self):
        self.assertEqual(cutover.classify(self.root),
                         {"class": "absent", "path": str(self.root / cutover.LEGACY_PATH)})

    def test_completed(self):
        for state in ({**STATE, "releaseUrl": "https://x/r", "tag": "v1.0.0", "pr": 3,
                       "deployState": "done"},
                      {**STATE, "tag": "v1.0.0", "deployState": "none"}):
            with self.subTest(state=state):
                self.assertEqual(self.classify(state), "completed")

    def test_in_flight(self):
        for state in (STATE, {**STATE, "pr": 3, "tag": "v1.0.0", "deployState": "none"},
                      {**STATE, "releaseUrl": "https://x/r", "deployState": "watching"}):
            with self.subTest(state=state):
                self.assertEqual(self.classify(state), "in_flight")

    def test_unreadable(self):
        extra = {**STATE, "extra": 1}
        missing = {k: v for k, v in STATE.items() if k != "pr"}
        for value in ("{", "[]", json.dumps(extra), json.dumps(missing), "x" * 70000):
            with self.subTest(value=value[:20]):
                self.assertEqual(self.classify(value), "unreadable")
        path = self.root / cutover.LEGACY_PATH
        path.unlink()
        target = self.root / "elsewhere.json"
        target.write_text(json.dumps({**STATE, "tag": "v1.0.0", "deployState": "none"}),
                          encoding="utf-8")
        os.symlink(target, path)
        self.assertEqual(cutover.classify(self.root)["class"], "unreadable")

    def test_retire_removes_only_a_completed_file(self):
        path = write(self.root, STATE)
        with self.assertRaises(ValueError):
            cutover.retire(self.root)
        self.assertTrue(path.exists())
        write(self.root, {**STATE, "tag": "v1.0.0", "deployState": "none"})
        cutover.retire(self.root)
        self.assertFalse(path.exists())


class DriverLegacyTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        self.world.verification_ready()
        self.clock = rs.Clock()

    def driver(self):
        project = rs.project(self)
        return release_driver.Driver(project, registry={"github-forge": rs.StatefulForge(self.world)},
                                     clock=self.clock)

    def test_in_flight_blocks_preview_and_run_but_not_status(self):
        driver = self.driver()
        before = write(driver.project.root, STATE).read_bytes()
        for call in (lambda: driver.preview(rs.candidate()), lambda: driver.run(rs.candidate(), [])):
            with self.assertRaises(release_driver.Refusal) as caught:
                call()
            self.assertEqual((caught.exception.code, caught.exception.repair_id),
                             ("legacy_release_in_flight", "release.legacy.finish"))
        self.assertEqual(driver.status()["legacy"]["class"], "in_flight")
        self.assertEqual((driver.project.root / cutover.LEGACY_PATH).read_bytes(), before)
        self.assertFalse((driver.project.common_dir / "agent-release").exists())

    def test_a_completed_file_is_deleted_by_run_and_never_imported(self):
        driver = self.driver()
        path = write(driver.project.root, {**STATE, "tag": "v0.9.0", "deployState": "none"})
        self.assertTrue(driver.preview(rs.candidate())["runnable"])
        self.assertTrue(path.exists())
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["legacy"], result["next"]), ("deleted", "done"))
        self.assertFalse(path.exists())
        store = driver.project.common_dir / "agent-release"
        for file in store.rglob("*"):
            if file.is_file():
                self.assertNotIn(b"headSha", file.read_bytes())


if __name__ == "__main__":
    unittest.main()
```

Add to `tests/test_release_command.py` (it reuses `TransactionCommandTest`'s helpers by
subclassing):

```python
class LegacyCommandTest(TransactionCommandTest):
    """Cutover refuses while a legacy release is in flight (#128 AC6)."""

    def legacy(self, text):
        path = self.root / ".superpowers/workflows/ship-release/state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_in_flight_and_unreadable_refuse_and_touch_nothing(self):
        in_flight = json.dumps({"headSha": "1" * 40, "pr": 7, "prUrl": "u", "mergeSha": None,
                                "tag": None, "releaseUrl": None, "deployState": "pending"})
        for text in (in_flight, "not json"):
            with self.subTest(text=text[:10]):
                path = self.legacy(text)
                for argv, cwd in ((["preview", *self.candidate()], None),
                                  (["run", *self.candidate()], self.root)):
                    code, document, err = self.run_release("transaction", *argv, cwd=cwd)
                    self.assertEqual((code, document["error"]["code"]),
                                     (3, "legacy_release_in_flight"), err)
                self.assertEqual(path.read_text(encoding="utf-8"), text)
                code, status, _ = self.run_release("transaction", "status")
                self.assertEqual(code, 0)
                self.assertIn(status["legacy"]["class"], ("in_flight", "unreadable"))
        self.assertFalse(self.store_exists())
```

`LegacyCommandTest` subclasses `TransactionCommandTest`, so it inherits and re-runs that
class's tests. Keep that: they double as the proof that an `absent` legacy file changes
nothing.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m agent_tools.suite_runner tests/test_release_cutover.py 2>&1 | tail -4`
Expected: FAIL, `ModuleNotFoundError: No module named 'agent_tools.release_cutover'`.

- [ ] **Step 3: Implement**

Write `release_cutover.py` to the Invariants. Its docstring cites spec §6 and D8 and says
that removing an in-flight or unreadable file is a human action, never the driver's. Wire
gate 2, `status.legacy` and `run`'s deletion into `release_driver.py`. In `python/README.md`,
replace Task 4's closing legacy line in `## Release driver` with the four classes, the gate
and the deletion point, written from the code.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m agent_tools.suite_runner tests/test_release_cutover.py tests/test_release_command.py tests/test_release_driver.py tests/test_release_crash_matrix.py 2>&1 | tail -4`
Expected: `summary members=4 passed=4 failed=0`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release_cutover.py python/agent_tools/release_driver.py \
  tests/test_release_cutover.py tests/test_release_command.py python/README.md justfile
git commit -m "feat(issue-128/T6): legacy release state cutover"
```
