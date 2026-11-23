"""The eleven-m5 oMLX restart marker (issue 1694).

Runs `hosts/darwin/eleven-m5/omlx-configure.py` against stub commands and a scratch state
directory: each restart reason lands in `.restart-needed` right after its mutation, a model
the declaration does not name is never rewritten, and an equal value is no change.
Run: just agent-workflow-tests
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TIER = "fast"

ROOT = Path(__file__).resolve().parents[1]
CONFIGURE = ROOT / "hosts/darwin/eleven-m5/omlx-configure.py"

PATCH_APPLIED = """#!/bin/sh
exit 0
"""

# Reads as not applied until the forward run (neither --reverse nor --dry-run) creates `applied`.
PATCH_APPLIES = """#!/bin/sh
here="$(dirname "$0")"
case " $* " in
  *" --reverse "*) [ -e "$here/applied" ]; exit $? ;;
  *" --dry-run "*) exit 0 ;;
esac
touch "$here/applied"
exit 0
"""

# Reads as not applied, its dry run passes, it applies, and its verify fails.
PATCH_NEVER_VERIFIES = """#!/bin/sh
case " $* " in
  *" --reverse "*) exit 1 ;;
esac
exit 0
"""


class ConfigureMarkerTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        (self.root / "site/omlx").mkdir(parents=True)
        self.stub = self.root / "patch"
        self.stub.write_text(PATCH_APPLIED)
        self.stub.chmod(0o755)
        (self.root / "noop.patch").write_text("")
        self.write_json(self.root / "declared-models.json", {
            "Declared": {"model_alias": "declared", "is_default": True, "is_pinned": False},
        })
        self.write_json(self.root / "declared-server.json", {
            "memory": {"memory_guard_tier": "custom", "memory_guard_custom_ceiling_gb": 192},
        })
        self.state = self.root / "state"
        self.state.mkdir()
        self.models = self.state / "model_settings.json"
        self.server = self.state / "settings.json"
        self.marker = self.state / ".restart-needed"
        self.write_json(self.models, {"version": 1, "models": {
            "Declared": {
                "model_alias": "declared", "is_default": True, "is_pinned": False, "temperature": 0.5,
            },
            "Admin-Model": {"is_default": False, "is_pinned": False},
        }})
        self.write_json(self.server, {
            "auth": {"api_key": "kept"},
            "memory": {"memory_guard_tier": "custom", "memory_guard_custom_ceiling_gb": 192.0},
        })
        self.extra = []

    def write_json(self, path, value):
        path.write_text(json.dumps(value))

    def read_json(self, path):
        return json.loads(path.read_text())

    def stub_with(self, script):
        self.stub.write_text(script)

    def run_configure(self):
        command = [
            sys.executable, str(CONFIGURE),
            "--state-dir", str(self.state),
            "--site-packages", str(self.root / "site"),
            "--patch-bin", str(self.stub),
            "--patch", str(self.root / "noop.patch"),
            "--model-settings", str(self.root / "declared-models.json"),
            "--server-settings", str(self.root / "declared-server.json"),
            *self.extra,
        ]
        return subprocess.run(command, text=True, capture_output=True, env={**os.environ})

    def marker_lines(self):
        return self.marker.read_text().splitlines() if self.marker.exists() else []

    def reasons_of(self, result):
        return json.loads(result.stdout)["restart_reasons"]

    def test_an_admin_change_to_an_undeclared_models_flags_marks_no_restart(self):
        # The file as oMLX's admin save writes it: set_settings clears every other model's
        # default when one is set (omlx/model_settings.py:998-1003).
        self.write_json(self.models, {"version": 1, "models": {
            "Declared": {
                "model_alias": "declared", "is_default": False, "is_pinned": False, "temperature": 0.5,
            },
            "Admin-Model": {"is_default": True, "is_pinned": True, "is_hidden": True},
        }})
        before = self.models.read_bytes()
        result = self.run_configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.models.read_bytes(), before)
        output = json.loads(result.stdout)
        self.assertEqual(output["restart_reasons"], [])
        self.assertIs(output["changed"], False)

    def test_a_declared_key_change_records_each_changed_key_once(self):
        self.write_json(self.server, {
            "auth": {"api_key": "kept"},
            "memory": {"memory_guard_tier": "balanced", "memory_guard_custom_ceiling_gb": 0.0},
        })
        both = [
            "settings.json memory/memory_guard_custom_ceiling_gb",
            "settings.json memory/memory_guard_tier",
        ]
        first = self.run_configure()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.marker_lines(), both)
        self.assertEqual(self.reasons_of(first), both)
        self.assertEqual(self.read_json(self.server)["auth"]["api_key"], "kept")
        second = self.run_configure()
        self.assertEqual(self.marker_lines(), both)
        self.assertEqual(self.reasons_of(second), [])
        settings = self.read_json(self.server)
        settings["memory"]["memory_guard_tier"] = "balanced"
        self.write_json(self.server, settings)
        third = self.run_configure()
        self.assertEqual(self.marker_lines(), both)
        self.assertEqual(self.reasons_of(third), ["settings.json memory/memory_guard_tier"])

    def test_a_reason_already_in_the_marker_is_kept(self):
        self.marker.write_text("model Downloaded added\n")
        settings = self.read_json(self.models)
        settings["models"]["Declared"]["is_pinned"] = True
        self.write_json(self.models, settings)
        result = self.run_configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.marker_lines(),
            ["model Downloaded added", "model_settings.json models/Declared/is_pinned"],
        )
        declared = self.read_json(self.models)["models"]["Declared"]
        self.assertIs(declared["is_pinned"], False)
        self.assertEqual(declared["temperature"], 0.5)

    def test_an_equal_number_written_as_a_float_is_no_change(self):
        before = (self.models.read_bytes(), self.server.read_bytes())
        result = self.run_configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertEqual((self.models.read_bytes(), self.server.read_bytes()), before)

    def test_an_applied_patch_and_a_created_file_are_reasons(self):
        self.stub_with(PATCH_APPLIES)
        self.server.unlink()
        result = self.run_configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = ["patch noop.patch applied", "settings.json created"]
        self.assertEqual(self.marker_lines(), expected)
        self.assertEqual(self.reasons_of(result), expected)

    def test_the_declared_default_returns_once_no_undeclared_model_is_default(self):
        settings = self.read_json(self.models)
        settings["models"]["Declared"]["is_default"] = False
        self.write_json(self.models, settings)
        result = self.run_configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIs(self.read_json(self.models)["models"]["Declared"]["is_default"], True)
        self.assertEqual(self.marker_lines(), ["model_settings.json models/Declared/is_default"])

    def test_two_defaults_leave_only_the_undeclared_one(self):
        settings = self.read_json(self.models)
        settings["models"]["Admin-Model"]["is_default"] = True
        self.write_json(self.models, settings)
        result = self.run_configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        models = self.read_json(self.models)["models"]
        self.assertEqual([name for name, entry in models.items() if entry["is_default"]], ["Admin-Model"])
        self.assertEqual(self.marker_lines(), ["model_settings.json models/Declared/is_default"])

    def test_a_patch_that_fails_its_verify_still_records_its_reason(self):
        self.stub_with(PATCH_NEVER_VERIFIES)
        result = self.run_configure()
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot verify applied noop.patch", result.stderr)
        self.assertEqual(self.marker_lines(), ["patch noop.patch applied"])

    def test_a_failure_after_a_settings_write_and_a_steering_change_keeps_both_reasons(self):
        settings = self.read_json(self.server)
        settings["memory"]["memory_guard_tier"] = "balanced"
        self.write_json(self.server, settings)
        self.write_json(self.root / "steering.json", {
            "P": {"base": "Base", "neurons": [{"layer": 1, "neuron": 2, "dose": 0.5}]},
        })
        self.extra = ["--steering", str(self.root / "steering.json")]
        base = self.state / "models/Base"
        base.mkdir(parents=True)
        (base / ".omlx-download-complete").touch()
        (base / "config.json").write_text("{}")
        preset = self.state / "models/P"
        preset.mkdir()
        (preset / ".omlx-steering-preset").touch()
        # A link the base does not want is unlinked first; the regular file then
        # collides with the wanted config.json link, so symlink_to raises.
        (preset / "old.json").symlink_to(base / "gone.json")
        (preset / "config.json").write_text("{}")
        result = self.run_configure()
        self.assertEqual(result.returncode, 1)
        self.assertIn("FileExistsError", result.stderr)
        self.assertFalse(os.path.lexists(preset / "old.json"))
        self.assertEqual(
            self.marker_lines(),
            ["settings.json memory/memory_guard_tier", "steering preset P changed"],
        )


if __name__ == "__main__":
    unittest.main()
