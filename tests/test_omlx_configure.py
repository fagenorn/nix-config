"""Apply the host's real patches/settings to pinned upstream source in scratch."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class OmlxConfigureTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        root = Path(self.scratch.name)
        self.package = root / "site-packages"
        source = Path(os.environ["OMLX_TEST_SOURCE"]) / "omlx"
        for name in (
            "__init__.py", "_version.py", "server.py", "exceptions.py",
            "model_settings.py", "model_profiles.py",
            "patches/mlx_vlm_glm5_next_compat/__init__.py",
        ):
            destination = self.package / "omlx" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, destination)
        shutil.copytree(source / "api", self.package / "omlx/api")
        for path in (self.package / "omlx").rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        self.state = root / "state"
        self.state.mkdir()
        self.models = self.state / "model_settings.json"
        self.server = self.state / "settings.json"
        self.models.write_text(json.dumps({
            "version": 1, "future_root_key": "keep",
            "models": {
                "Qwen3.8-Flash-Next-oQ4e-mtp": {
                    "temperature": 0.42,
                    "chat_template_kwargs": {"preserve_thinking": False},
                },
                "unmanaged": {"is_default": True, "temperature": 0.27},
            },
        }))
        self.server.write_text(json.dumps({
            "auth": {"api_key": "test-secret-preserved"},
            "scheduler": {"max_num_seqs": 3},
            "server": {"port": 8123},
        }))
        self.command = [
            sys.executable, os.environ["OMLX_CONFIGURE_SOURCE"],
            "--state-dir", str(self.state),
            "--site-packages", str(self.package),
            "--patch-bin", shutil.which("patch"),
            "--model-settings", os.environ["OMLX_MODEL_SETTINGS"],
            "--server-settings", os.environ["OMLX_SERVER_SETTINGS"],
        ]
        for patch in json.loads(os.environ["OMLX_PATCHES"]):
            self.command.extend(["--patch", patch])

    def configure(self):
        return subprocess.run(self.command, text=True, capture_output=True)

    def test_real_adapter_schema_and_route(self):
        configured = self.configure()
        self.assertEqual(configured.returncode, 0, configured.stderr)
        env = dict(os.environ, PYTHONPATH=str(self.package))
        result = subprocess.run(
            [sys.executable, os.environ["OMLX_ADAPTER_PROBE"],
             "--server-source", str(self.package / "omlx/server.py"),
             "--model-settings", str(self.models),
             "--template", os.environ["OMLX_QWEN_TEMPLATE"]],
            env=env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK", result.stderr)

    def test_merges_actual_host_defaults_preserves_unowned_keys_and_is_idempotent(self):
        result = self.configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["changed"])
        actual = json.loads(self.models.read_text())
        for model in ("Qwen3.8-Flash-Next-oQ4e-mtp", "Qwen3.8-Flash-Next-UD-Q4_K_XL"):
            self.assertEqual(actual["models"][model]["thinking_budget_tokens"], 4096)
            self.assertTrue(actual["models"][model]["thinking_budget_enabled"])
            self.assertEqual(actual["models"][model]["chat_template_kwargs"]["reasoning_effort"], "medium")
        mlx = actual["models"]["Qwen3.8-Flash-Next-oQ4e-mtp"]
        self.assertEqual(mlx["temperature"], 0.42)
        self.assertFalse(mlx["chat_template_kwargs"]["preserve_thinking"])
        self.assertEqual(actual["future_root_key"], "keep")
        self.assertEqual(actual["models"]["unmanaged"], {"is_default": False, "temperature": 0.27})
        self.assertNotIn("thinking_budget_tokens", actual["models"]["GLM-5.3-Flash-MLX-oQ4-MTP"])
        server = json.loads(self.server.read_text())
        self.assertEqual(server["auth"]["api_key"], "test-secret-preserved")
        self.assertEqual(server["scheduler"]["max_num_seqs"], 3)
        self.assertTrue(server["scheduler"]["chunked_prefill"])
        self.assertEqual(server["server"]["port"], 8123)
        self.assertNotIn("test-secret-preserved", result.stdout + result.stderr)
        self.assertEqual(self.server.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        marker = self.state / ".restart-needed"
        self.assertTrue(marker.is_file())
        marker.unlink()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.models, self.server)}
        result = self.configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["changed"])
        self.assertFalse(marker.exists())
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})

    def test_incompatible_patch_fails_before_settings_or_source_mutation(self):
        # Break the second patch, so preflight must also prevent the first patch.
        target = self.package / "omlx/api/anthropic_models.py"
        target.write_text("incompatible upstream source\n")
        glm = self.package / "omlx/patches/mlx_vlm_glm5_next_compat/__init__.py"
        before = {p: p.read_bytes() for p in (self.models, self.server, glm)}
        result = self.configure()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("anthropic-effort.patch", result.stderr)
        self.assertIn("does not apply", result.stderr)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertFalse((self.state / ".restart-needed").exists())

    def test_malformed_settings_fail_without_applying_patches(self):
        self.server.write_text("invalid json")
        schema = self.package / "omlx/api/anthropic_models.py"
        before = schema.read_bytes()
        result = self.configure()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("settings.json", result.stderr)
        self.assertEqual(before, schema.read_bytes())

    def test_missing_installation_fails(self):
        shutil.rmtree(self.package / "omlx")
        result = self.configure()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("oMLX package", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
