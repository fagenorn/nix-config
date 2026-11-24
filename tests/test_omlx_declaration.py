"""The eleven-m5 oMLX declaration: the pin, the memory guard and the restart wiring.

Reads the declaration through tests/host_readings.py, so it runs on any machine; new files
must be `git add`-ed first.
Run: just agent-workflow-tests
"""
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
