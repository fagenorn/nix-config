"""The eleven-m5 oMLX declaration: the pin, the memory guard and the restart wiring.

Reads the declaration through tests/host_readings.py, so it runs on any machine; new files
must be `git add`-ed first.
Run: just agent-workflow-tests
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from . import host_readings

TIER = "integration"

JARBIRD = "GLM-5.3-Flash-Abliterated-MLX-4bit"


class OmlxDeclarationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = host_readings.read("eleven-m5", "omlx")

    def test_the_jarbird_model_is_pinned_and_the_memory_guard_is_custom_at_192(self):
        self.assertEqual(self.got["models"][JARBIRD], {"is_pinned": True})
        self.assertEqual(
            self.got["server"]["memory"],
            {"memory_guard_tier": "custom", "memory_guard_custom_ceiling_gb": 192},
        )

    def test_only_the_jarbird_model_is_pinned(self):
        pinned = {name for name, entry in self.got["models"].items() if entry.get("is_pinned")}
        self.assertEqual(pinned, {JARBIRD})
        self.assertFalse(self.got["models"]["GLM-5.3-Flash-MLX-oQ4-MTP"]["is_pinned"])

    def test_activation_and_the_downloader_restart_only_through_the_gate(self):
        for name in ("activation", "fetch"):
            text = self.got[name]
            with self.subTest(text=name):
                self.assertIn("/bin/omlx-restart", text)
                for forbidden in ("--now", "pkill", "kickstart -k"):
                    self.assertNotIn(forbidden, text)
        self.assertIn("kickstart system/org.nixos.omlx-models", self.got["activation"])
        self.assertIn(' added" >> ', self.got["fetch"])
        self.assertIn(".restart-needed", self.got["fetch"])

    def test_the_declared_models_are_the_served_set(self):
        self.assertEqual(
            set(self.got["models"]),
            {
                "GLM-5.3-Flash-MLX-oQ4-MTP",
                "Qwen3.8-Flash-Next-oQ4e-mtp",
                "Qwen3.8-Flash-Next-UD-Q4_K_XL",
                "Qwen3.8-Flash-Next-DFlash2",
                JARBIRD,
            },
        )

    def test_the_downloader_restarts_without_reconfiguring(self):
        self.assertNotIn("/bin/omlx-configure", self.got["fetch"])
        self.assertIn("/bin/omlx-restart", self.got["fetch"])

    def test_the_serve_script_gates_the_start_on_the_floor(self):
        serve = self.got["serve"]
        gate = next(line for line in serve.splitlines() if " gate " in line)
        self.assertRegex(gate, r"^/nix/store/[0-9a-z]{32}-agent-platform/bin/memory-floor gate ")
        self.assertIn("--floor-gib 10 ", gate + " ")
        self.assertIn("--interval-seconds 2", gate)
        self.assertLess(serve.index(" gate "), serve.index("sops"))
        self.assertLess(serve.index(" gate "), serve.index("exec /opt/homebrew/bin/omlx serve"))
        for forbidden in ("pkill", "kill", "launchctl", "kickstart"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, gate)

    def test_a_restart_reloads_the_omlx_job_as_root_only_through_the_wrapper(self):
        self.assertEqual(
            self.got["reload"].splitlines(),
            [
                "/usr/bin/sudo -n /bin/launchctl unload /Library/LaunchDaemons/org.nixos.omlx.plist || true",
                "/usr/bin/sudo -n /bin/launchctl load -w /Library/LaunchDaemons/org.nixos.omlx.plist || exit",
                "exec /usr/bin/sudo -n /bin/rm -f /nix/var/nix/gcroots/omlx-held-serve",
            ],
        )
        for forbidden in ("pkill", "kickstart"):
            self.assertNotIn(forbidden, self.got["reload"])
        self.assertRegex(self.got["restart"], r"--reload-bin /nix/store/[0-9a-z]{32}-omlx-reload")
        self.assertIn("--restart-bin /nix/store/", self.got["restart"])

    def test_the_reactive_branch_pipes_the_key_from_sops_and_takes_no_caller_arguments(self):
        text = self.got["restart"]
        start = text.index('if [ "$#" -eq 1 ] && [ "$1" = --reactive ]; then')
        branch = text[start : text.index("\nfi\n", start)]
        for needle in (
            "-d --extract '[\"omlx_api_key\"]'",
            "SOPS_AGE_KEY_FILE=/Users/",
            "--status-url http://127.0.0.1:8000/api/status",
            f"--pinned-model {JARBIRD}",
            "--reactive",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, branch)
        self.assertLess(branch.index("sops"), branch.index("|"))
        self.assertLess(branch.index("|"), branch.index("omlx-restart.py"))
        self.assertNotIn('"$@"', branch)
        self.assertNotIn("OMLX_API_KEY", text)
        self.assertNotIn("export", text)
        self.assertTrue(text.rstrip().splitlines()[-1].endswith('"$@"'))

    def test_the_reactive_kill_keeps_pkills_no_match_status(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        stub = root / "pkill"
        stub.write_text('#!/bin/sh\nexit "$(cat "$(dirname "$0")/rc")"\n')
        stub.chmod(0o755)
        text = self.got["killReactive"]
        self.assertIn("/usr/bin/pkill", text)
        script = root / "kill"
        script.write_text(text.replace("/usr/bin/pkill", str(stub)))
        for code in (0, 1, 2):
            with self.subTest(code=code):
                (root / "rc").write_text(str(code))
                self.assertEqual(subprocess.run(["sh", str(script)]).returncode, code)
        restart = self.got["restart"]
        self.assertRegex(restart, r"--restart-bin /nix/store/[0-9a-z]{32}-omlx-kill-reactive")
        reactive = restart[: restart.index("\nfi\n")]
        self.assertNotRegex(reactive, r"-omlx-kill ")
        exec_line = next(line for line in restart.splitlines() if "omlx-restart.py" in line and "exec" in line)
        self.assertEqual(exec_line.count("-omlx-kill-reactive"), 0)
        self.assertRegex(restart.split("\nfi\n", 1)[1], r"--restart-bin /nix/store/[0-9a-z]{32}-omlx-kill \\")

    def test_the_kill_signals_the_uid_it_is_given_and_keeps_pkills_status(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        stub = root / "pkill"
        stub.write_text('#!/bin/sh\nhere="$(dirname "$0")"\necho "$*" > "$here/args"\nexit "$(cat "$here/rc")"\n')
        stub.chmod(0o755)
        text = self.got["kill"]
        self.assertIn("/usr/bin/pkill", text)
        self.assertNotIn("id -u", text)
        script = root / "kill"
        script.write_text(text.replace("/usr/bin/pkill", str(stub)))
        for code in (0, 1, 2):
            with self.subTest(code=code):
                (root / "rc").write_text(str(code))
                self.assertEqual(subprocess.run(["sh", str(script), "4242"]).returncode, code)
                self.assertEqual((root / "args").read_text().split(), ["-U", "4242", "-x", "omlx-server"])
        gated = self.got["restart"].split("\nfi\n", 1)[1]
        self.assertIn(f"--server-user {self.got['serverUser']} \\", gated)
        self.assertNotEqual(self.got["serverUser"], "root")

    def test_the_host_guide_says_a_restart_after_a_formula_upgrade_must_not_stay_pending(self):
        guide = (Path(__file__).resolve().parents[1] / "hosts/darwin/eleven-m5/README.md").read_text()
        text = " ".join(guide.split())
        self.assertIn("After a formula upgrade the restart must not stay pending", text)
        self.assertIn("the old process runs deleted code", text)
        self.assertIn("nothing was restarted", text)
