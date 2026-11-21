"""The switch recipes run the fleet preflight between the build and the activation (issue 1451).

Reads the repository `justfile` and runs `just` against a single-platform copy of
it: a recipe gated by the other platform is absent on a host, so the copy drops
every recipe gated by the platform not under test, and one test run can then judge
both switch recipes whatever host runs it.

The cases spawn `just` as a child, with `nix`, `nixos-rebuild` and `sudo` replaced
by stubs placed first on `PATH`. Each stub appends its own name, `PYTHONPATH` and
arguments to a log and exits; no stub runs a real program, so nothing is built and
nothing is activated. The copy's directory holds no flake and no `result/`, so a stub
that failed to intercept could not activate anything either.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JUST = shutil.which("just")

PREFLIGHT = "-m agent_tools.project_contract.fleet_preflight"
BUILD_MARKERS = {"macos": '.system"', "linux": "nixos-rebuild build "}
ACTIVATION_MARKERS = {
    "macos": "darwin-rebuild switch ",
    "linux": "nixos-rebuild switch ",
}
OTHER_PLATFORM = {"macos": "linux", "linux": "macos"}
HOST = "fixture-host"
STUB_NAMES = ("nix", "nixos-rebuild", "sudo")

STUB_SCRIPT = """#!/bin/sh
printf '%s\\n' "{name}" >> "$STUB_LOG"
printf 'PYTHONPATH=%s\\n' "$PYTHONPATH" >> "$STUB_LOG"
printf '%s\\n' "$*" >> "$STUB_LOG"
{tail}
"""
NIX_TAIL = """for arg in "$@"; do
  if [ "$arg" = shell ]; then exit "$PREFLIGHT_EXIT"; fi
done
exit 0"""


def stub_script(name: str) -> str:
    tail = NIX_TAIL if name == "nix" else "exit 0"
    return STUB_SCRIPT.format(name=name, tail=tail)


class FleetPreflightRecipeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(JUST, "just is not on PATH")

    def scratch(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="fleet-preflight-recipes-"))
        self.addCleanup(shutil.rmtree, path, True)
        return path

    def platform_justfile(self, platform: str) -> Path:
        other = f"[{OTHER_PLATFORM[platform]}]"
        mine = f"[{platform}]"
        kept: list[str] = []
        lines = (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            if line == other:
                index += 2
                while index < len(lines) and (
                    lines[index] == "" or lines[index][0].isspace()
                ):
                    index += 1
                continue
            if line != mine:
                kept.append(line)
            index += 1
        copy = self.scratch() / "justfile"
        copy.write_text("\n".join(kept) + "\n", encoding="utf-8")
        headers = [
            line for line in kept if line.startswith("switch target_host=hostname:")
        ]
        self.assertEqual(len(headers), 1, headers)
        return copy

    def dry_run(self, platform: str, *args: str) -> list[str]:
        path = self.platform_justfile(platform)
        proc = subprocess.run(
            [
                JUST,
                "--justfile",
                str(path),
                "--working-directory",
                str(path.parent),
                "--dry-run",
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stderr.splitlines()

    def dump(self, platform: str) -> dict:
        path = self.platform_justfile(platform)
        proc = subprocess.run(
            [JUST, "--justfile", str(path), "--dump", "--dump-format", "json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def stubbed_run(
        self,
        platform: str,
        *just_args: str,
        preflight_exit: int,
        extra_env: dict | None = None,
        working_directory: Path | None = None,
    ) -> tuple[int, list[str], Path]:
        path = self.platform_justfile(platform)
        work = self.scratch()
        bin_dir = work / "bin"
        bin_dir.mkdir()
        log = work / "stub.log"
        for name in STUB_NAMES:
            stub = bin_dir / name
            stub.write_text(stub_script(name), encoding="utf-8")
            stub.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STUB_LOG": str(log),
            "PREFLIGHT_EXIT": str(preflight_exit),
            **(extra_env or {}),
        }
        for name in STUB_NAMES:
            found = shutil.which(name, path=env["PATH"])
            self.assertIsNotNone(found)
            self.assertEqual(Path(found).parent, bin_dir, name)
        proc = subprocess.run(
            [
                JUST,
                "--justfile",
                str(path),
                "--working-directory",
                str(working_directory or path.parent),
                *just_args,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return proc.returncode, lines, (working_directory or path.parent)

    @staticmethod
    def calls(lines: list[str]) -> list[tuple[str, str, str]]:
        """Group the stub log into (name, PYTHONPATH value, arguments) triples."""
        return [
            (lines[i], lines[i + 1].removeprefix("PYTHONPATH="), lines[i + 2])
            for i in range(0, len(lines), 3)
        ]

    def assert_preflight_call(self, call: tuple[str, str, str], directory: Path) -> None:
        directory = directory.resolve()
        name, python_path, args = call
        self.assertEqual(name, "nix", call)
        self.assertEqual(python_path, f"{directory}/python", call)
        expected = [
            "shell",
            f"--inputs-from {directory}",
            "nixpkgs#python3",
            "--command python3 -B -m agent_tools.project_contract.fleet_preflight "
            f"--manifest {directory}/home/common/agent-skills/platform-manifest.json",
        ]
        position = 0
        for part in expected:
            found = args.find(part, position)
            self.assertNotEqual(found, -1, (part, args))
            position = found + len(part)

    def test_each_switch_recipe_runs_the_preflight_after_the_build_and_before_activation(
        self,
    ) -> None:
        for platform in ("macos", "linux"):
            with self.subTest(platform=platform):
                lines = self.dry_run(platform, "switch", HOST)
                builds = [i for i, l in enumerate(lines) if BUILD_MARKERS[platform] in l]
                preflights = [i for i, l in enumerate(lines) if PREFLIGHT in l]
                activations = [
                    i for i, l in enumerate(lines) if ACTIVATION_MARKERS[platform] in l
                ]
                self.assertEqual(len(builds), 1, lines)
                self.assertEqual(len(preflights), 1, lines)
                self.assertEqual(len(activations), 1, lines)
                self.assertLess(builds[0], preflights[0])
                self.assertLess(preflights[0], activations[0])
                line = lines[preflights[0]]
                self.assertIn("nixpkgs#python3", line)
                self.assertIn("--manifest", line)
                self.assertIn("python3 -B -m", line)
                self.assertNotIn("sudo", line.split())

    def test_no_switch_recipe_takes_a_skip_option(self) -> None:
        for platform in ("macos", "linux"):
            with self.subTest(platform=platform):
                switch = self.dump(platform)["recipes"]["switch"]
                self.assertEqual(
                    [p["name"] for p in switch["parameters"]], ["target_host"]
                )
                self.assertEqual(
                    [d["recipe"] for d in switch["dependencies"]], ["build"]
                )

    def test_a_failing_preflight_stops_the_switch_even_without_dependencies(
        self,
    ) -> None:
        for platform in ("macos", "linux"):
            with self.subTest(platform=platform, case="with dependencies"):
                code, lines, directory = self.stubbed_run(
                    platform, "switch", HOST, preflight_exit=1
                )
                self.assertNotEqual(code, 0)
                calls = self.calls(lines)
                self.assertEqual(len(lines), 6, lines)
                build_name, _, build_args = calls[0]
                if platform == "macos":
                    self.assertEqual(build_name, "nix")
                    self.assertIn("build", build_args.split())
                    self.assertNotIn("shell", build_args.split())
                else:
                    self.assertEqual(build_name, "nixos-rebuild")
                    self.assertEqual(build_args.split()[0], "build")
                self.assert_preflight_call(calls[1], directory)
                self.assertFalse([l for l in lines if l == "sudo"], lines)
            with self.subTest(platform=platform, case="--no-deps"):
                code, lines, directory = self.stubbed_run(
                    platform, "--no-deps", "switch", HOST, preflight_exit=1
                )
                self.assertNotEqual(code, 0)
                self.assertEqual(len(lines), 3, lines)
                self.assert_preflight_call(self.calls(lines)[0], directory)
                self.assertFalse([l for l in lines if l == "sudo"], lines)
            with self.subTest(platform=platform, case="JUST_NO_DEPS"):
                code, lines, directory = self.stubbed_run(
                    platform,
                    "switch",
                    HOST,
                    preflight_exit=1,
                    extra_env={"JUST_NO_DEPS": "true"},
                )
                self.assertNotEqual(code, 0)
                self.assertEqual(len(lines), 3, lines)
                self.assert_preflight_call(self.calls(lines)[0], directory)
                self.assertFalse([l for l in lines if l == "sudo"], lines)
            with self.subTest(platform=platform, case="positive control"):
                code, lines, directory = self.stubbed_run(
                    platform, "--no-deps", "switch", HOST, preflight_exit=0
                )
                self.assertEqual(code, 0)
                self.assertEqual(len(lines), 6, lines)
                calls = self.calls(lines)
                self.assert_preflight_call(calls[0], directory)
                self.assertEqual(calls[1][0], "sudo")
                self.assertIn(ACTIVATION_MARKERS[platform], calls[1][2] + " ")

    def test_the_preflight_judges_the_tree_the_switch_activates(self) -> None:
        for platform in ("macos", "linux"):
            with self.subTest(platform=platform):
                activated = self.scratch().resolve()
                code, lines, directory = self.stubbed_run(
                    platform,
                    "--no-deps",
                    "switch",
                    HOST,
                    preflight_exit=0,
                    working_directory=activated,
                )
                self.assertEqual(code, 0)
                self.assertEqual(directory, activated)
                calls = self.calls(lines)
                self.assert_preflight_call(calls[0], activated)
                self.assertEqual(len(lines), 6, lines)

    def test_the_build_recipe_runs_no_preflight(self) -> None:
        for platform in ("macos", "linux"):
            with self.subTest(platform=platform):
                lines = self.dry_run(platform, "build", HOST)
                self.assertFalse([l for l in lines if PREFLIGHT in l], lines)
                self.assertEqual(
                    len([l for l in lines if BUILD_MARKERS[platform] in l]), 1, lines
                )


if __name__ == "__main__":
    unittest.main()
