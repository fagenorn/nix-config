"""The eleven-m5 oMLX restart marker.

Runs `hosts/darwin/eleven-m5/omlx-configure.py` against stub commands and a scratch state
directory: each restart reason lands in `.restart-needed` right after its mutation, a model
the declaration does not name is never rewritten, and an equal value is no change.
Runs `hosts/darwin/eleven-m5/omlx-restart.py` against a stub restart command and a local
`/health` server: the restart waits while the server holds a model or cannot be read.
Run: just agent-workflow-tests
"""

import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

TIER = "fast"

ROOT = Path(__file__).resolve().parents[1]
CONFIGURE = ROOT / "hosts/darwin/eleven-m5/omlx-configure.py"
RESTART = ROOT / "hosts/darwin/eleven-m5/omlx-restart.py"

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

    def legacy_directory(self, name, *entries):
        directory = self.state / "models" / name
        directory.mkdir(parents=True)
        (directory / ".omlx-old-preset").touch()
        for entry in entries:
            (directory / entry).write_text("{}")
        return directory

    def test_a_legacy_preset_directory_is_removed_and_reported(self):
        models = self.state / "models"
        target = self.root / "weights.safetensors"
        target.write_text("weights")
        old = self.legacy_directory("Old-preset", "spec.json")
        (old / "model.safetensors").symlink_to(target)
        kept = models / "Kept"
        kept.mkdir()
        (kept / "config.json").write_text("{}")
        result = self.run_configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["removed_presets"], ["Old-preset"])
        self.assertFalse(old.exists())
        self.assertTrue((kept / "config.json").is_file())
        self.assertTrue(target.exists())
        self.assertEqual(self.reasons_of(result), [])
        self.assertEqual(self.marker_lines(), [])

    def test_a_legacy_preset_directory_holding_a_real_file_is_refused(self):
        settings = self.read_json(self.server)
        settings["memory"]["memory_guard_tier"] = "balanced"
        self.write_json(self.server, settings)
        before = self.server.read_bytes()
        old = self.legacy_directory("Old-preset", "weights.safetensors")
        result = self.run_configure()
        self.assertEqual(result.returncode, 1)
        self.assertIn("legacy preset", result.stderr)
        self.assertIn("holds weights.safetensors", result.stderr)
        self.assertTrue((old / "weights.safetensors").is_file())
        self.assertEqual(self.server.read_bytes(), before)
        self.assertEqual(self.marker_lines(), [])

    def test_a_legacy_preset_directory_holding_a_subdirectory_is_refused(self):
        old = self.legacy_directory("Old-preset")
        (old / "nested.json").mkdir()
        (old / "nested.json" / "weights.safetensors").write_text("weights")
        result = self.run_configure()
        self.assertEqual(result.returncode, 1)
        self.assertIn("holds nested.json", result.stderr)
        self.assertTrue((old / "nested.json" / "weights.safetensors").exists())

    def test_a_failure_after_a_settings_write_keeps_its_reason(self):
        settings = self.read_json(self.server)
        settings["memory"]["memory_guard_tier"] = "balanced"
        self.write_json(self.server, settings)
        old = self.legacy_directory("Old-preset")
        (old / "config.json").symlink_to(self.root / "anywhere")
        old.chmod(0o500)
        self.addCleanup(old.chmod, 0o700)
        result = self.run_configure()
        self.assertEqual(result.returncode, 1)
        self.assertIn("PermissionError", result.stderr)
        self.assertEqual(self.marker_lines(), ["settings.json memory/memory_guard_tier"])
        self.assertEqual(self.read_json(self.server)["memory"]["memory_guard_tier"], "custom")


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests += 1
        body = self.server.body.encode()
        self.send_response(self.server.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


IDLE = {"status": "healthy", "engine_pool": {"loaded_count": 0, "model_count": 9}}


def serving(count):
    return {"status": "healthy", "engine_pool": {"loaded_count": count, "model_count": 9}}


class RestartGateTest(unittest.TestCase):
    REASONS = "settings.json memory/memory_guard_tier\nmodel GLM-New added\n"

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.marker = self.state / ".restart-needed"
        self.marker.write_text(self.REASONS)
        self.calls = self.root / "calls"
        self.rc = self.root / "rc"
        self.stub = self.root / "restart"
        self.stub.write_text(
            '#!/bin/sh\nhere="$(dirname "$0")"\necho run >> "$here/calls"\n'
            '[ -e "$here/rc" ] && exit "$(cat "$here/rc")"\nexit 0\n'
        )
        self.stub.chmod(0o755)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
        self.server.requests = 0
        self.server.status = 200
        self.server.body = json.dumps(IDLE)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/health"
        self.extra = []
        self.env = {}

    def answer(self, status, body):
        self.server.status = status
        self.server.body = body if isinstance(body, str) else json.dumps(body)

    def run_gate(self, url=None):
        command = [
            sys.executable, str(RESTART),
            "--state-dir", str(self.state),
            "--restart-bin", str(self.stub),
            "--health-url", url or self.url,
            *self.extra,
        ]
        return subprocess.run(command, text=True, capture_output=True, env={**os.environ, **self.env})

    def raw_server(self, reply):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        self.addCleanup(listener.close)

        def answer_once():
            connection, _ = listener.accept()
            with connection:
                connection.recv(4096)
                connection.sendall(reply)

        threading.Thread(target=answer_once, daemon=True).start()
        return f"http://127.0.0.1:{listener.getsockname()[1]}/health"

    def stub_calls(self):
        return len(self.calls.read_text().splitlines()) if self.calls.exists() else 0

    def marker_bytes(self):
        return self.marker.read_bytes()

    def deferral_lines(self, result):
        return [line for line in result.stderr.splitlines() if line.startswith("oMLX: restart deferred (")]

    def test_a_loaded_model_defers_the_restart_and_reports_it(self):
        self.answer(200, serving(1))
        before = self.marker_bytes()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_calls(), 0)
        self.assertEqual(self.marker_bytes(), before)
        self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
        (line,) = self.deferral_lines(result)
        for text in (
            "1 model loaded",
            "settings.json memory/memory_guard_tier",
            "model GLM-New added",
            "omlx-restart --now",
        ):
            self.assertIn(text, line)

    def test_an_idle_server_is_restarted_and_the_marker_cleared(self):
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_calls(), 1)
        self.assertFalse(self.marker.exists())
        self.assertIn(
            "oMLX: restarted for: settings.json memory/memory_guard_tier; model GLM-New added",
            result.stderr,
        )

    def test_a_server_still_loading_its_pinned_models_defers(self):
        self.answer(503, {"status": "loading", "engine_pool": {"loaded_count": 0}})
        before = self.marker_bytes()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_calls(), 0)
        self.assertEqual(self.marker_bytes(), before)
        (line,) = self.deferral_lines(result)
        self.assertIn("pinned models still loading", line)

    def test_a_server_that_is_down_is_restarted(self):
        with socket.socket() as closed:
            closed.bind(("127.0.0.1", 0))
            port = closed.getsockname()[1]
        result = self.run_gate(url=f"http://127.0.0.1:{port}/health")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_calls(), 1)
        self.assertFalse(self.marker.exists())

    def test_an_unreadable_health_answer_defers(self):
        self.answer(200, "not json")
        before = self.marker_bytes()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_calls(), 0)
        self.assertEqual(self.marker_bytes(), before)
        (line,) = self.deferral_lines(result)
        self.assertIn("server state unknown", line)

    def test_a_proxy_in_the_environment_never_stands_in_for_the_server(self):
        self.answer(200, serving(1))
        self.env = {
            "http_proxy": "http://127.0.0.1:9",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "no_proxy": "",
            "NO_PROXY": "",
        }
        before = self.marker_bytes()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_calls(), 0)
        self.assertEqual(self.marker_bytes(), before)
        (line,) = self.deferral_lines(result)
        self.assertIn("1 model loaded", line)

    def test_an_answer_cut_off_mid_body_defers(self):
        url = self.raw_server(b"HTTP/1.1 200 OK\r\nContent-Length: 500\r\n\r\n" + b"x" * 53)
        before = self.marker_bytes()
        result = self.run_gate(url=url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_calls(), 0)
        self.assertEqual(self.marker_bytes(), before)
        (line,) = self.deferral_lines(result)
        self.assertIn("server state unknown", line)

    def test_a_port_that_does_not_speak_http_defers(self):
        url = self.raw_server(b"SSH-2.0-OpenSSH_9.9\r\n")
        before = self.marker_bytes()
        result = self.run_gate(url=url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_calls(), 0)
        self.assertEqual(self.marker_bytes(), before)
        (line,) = self.deferral_lines(result)
        self.assertIn("server state unknown", line)

    def test_now_restarts_a_serving_server(self):
        self.answer(200, serving(1))
        self.extra = ["--now"]
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_calls(), 1)
        self.assertFalse(self.marker.exists())

    def test_a_failed_restart_keeps_the_marker_and_fails(self):
        self.rc.write_text("3")
        before = self.marker_bytes()
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.marker_bytes(), before)
        self.assertIn("restart failed (exit 3)", result.stderr)

    def test_no_marker_means_nothing_to_restart(self):
        self.marker.unlink()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_calls(), 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.server.requests, 0)

    def test_an_empty_marker_is_reported_as_an_unrecorded_change(self):
        self.marker.write_text("")
        self.answer(200, serving(2))
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        (line,) = self.deferral_lines(result)
        self.assertIn("2 models loaded", line)
        self.assertIn("pending: unrecorded change.", line)


if __name__ == "__main__":
    unittest.main()
