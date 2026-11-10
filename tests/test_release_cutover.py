"""Legacy ship-release state at cutover (#128 AC6, spec §6, D8)."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_tools.release import release_cutover as cutover
from agent_tools.release import release_driver
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
        finished = {**STATE, "tag": "v1.0.0", "deployState": "none"}
        for key, wrong in (("releaseUrl", False), ("tag", 1), ("prUrl", []), ("pr", "3"),
                           ("pr", True), ("mergeSha", {}), ("headSha", None),
                           ("deployState", None)):
            with self.subTest(key=key, wrong=wrong):
                self.assertEqual(self.classify({**finished, key: wrong}), "unreadable")
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
