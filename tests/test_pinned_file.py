"""lib/pinned-file.nix holds its pin against the file on disk (issue 1353).

builtins.path with a sha256 reuses an existing store path of that hash without reading the
file again, so a fixture edited after its store path existed still built against the old copy.
The helper hashes the file itself; these tests evaluate it on a tampered copy after the pinned
content has already been added to the store.
Run: just agent-workflow-tests
"""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "lib/pinned-file.nix"
CHECK = ROOT / "lib/omlx-check.nix"
FIXTURE = ROOT / "tests/fixtures/omlx/qwen3.8-flash-next-chat_template.jinja"


def evaluate(path: Path, pin: str):
    expr = f'import {HELPER} {{ path = {path}; name = "pinned.txt"; sha256 = "{pin}"; }}'
    return subprocess.run(
        ["nix", "--extra-experimental-features", "nix-command", "eval", "--raw", "--impure",
         "--expr", expr],
        capture_output=True, text=True,
    )


@unittest.skipUnless(shutil.which("nix"), "nix is not on PATH")
class PinnedFileTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.file = Path(scratch.name) / "fixture.txt"

    def test_a_file_that_matches_its_pin_is_copied_to_the_store(self):
        self.file.write_text("pinned content\n")
        done = evaluate(self.file, hashlib.sha256(b"pinned content\n").hexdigest())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(done.stdout, r"^/nix/store/[0-9a-z]{32}-pinned\.txt$")

    def test_an_edited_file_fails_even_when_the_pinned_store_path_exists(self):
        pin = hashlib.sha256(b"pinned content\n").hexdigest()
        self.file.write_text("pinned content\n")
        self.assertEqual(evaluate(self.file, pin).returncode, 0)  # the pinned path now exists
        self.file.write_text("edited content\n")
        done = evaluate(self.file, pin)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(hashlib.sha256(b"edited content\n").hexdigest(), done.stderr)

    def test_the_adapter_check_pins_the_fixture_through_the_helper(self):
        source = CHECK.read_text(encoding="utf-8")
        self.assertIn("import ./pinned-file.nix", source)
        digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        self.assertIn(f'sha256 = "{digest}";', source)


if __name__ == "__main__":
    unittest.main()
