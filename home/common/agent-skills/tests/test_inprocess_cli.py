"""The in-process CLI runner against a real child process (issue 500 D2, D3, D6).

Run: just agent-workflow-tests
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ._inprocess_cli import run_script


# Reports its working directory, its stdin bytes and one environment variable, then
# writes raw bytes (non-UTF-8 only in bytes mode) and a stderr line, and exits as
# argv[1] says: a number, `raise`, or any other text as the `sys.exit` message.
PROBE = r'''import hashlib, os, sys
data = sys.stdin.buffer.read()
sys.stdout.write(f"cwd={os.getcwd()}\nstdin={len(data)}:{hashlib.sha256(data).hexdigest()}\n"
                 f"probe={os.environ.get('PROBE_VALUE')}\n")
sys.stdout.flush()
sys.stdout.buffer.write(b"raw:\xff\x00\n" if sys.argv[2] == "bytes" else "raw:é\n".encode())
sys.stderr.write("probe: stderr line\n")
outcome = sys.argv[1]
if outcome == "raise":
    raise RuntimeError("probe failure")
sys.exit(int(outcome) if outcome.isdigit() else outcome)
'''


class InProcessRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.probe = self.directory / "probe.py"
        self.probe.write_text(PROBE, encoding="utf-8")
        self.env = {**os.environ, "PROBE_VALUE": "issue-500"}

    def child(self, args, *, input, cwd, text):
        """The same call as a real child: `None` input is an empty stdin, as in-process."""
        stdin = {"stdin": subprocess.DEVNULL} if input is None else {"input": input}
        done = subprocess.run([sys.executable, str(self.probe), *args], cwd=cwd,
                              env=self.env, capture_output=True, text=text, check=False,
                              **stdin)
        return done.returncode, done.stdout, done.stderr

    def test_a_run_returns_exactly_what_a_child_process_returns(self):
        rows = (
            ("bytes stdin, bytes mode", ("0", "bytes"), b"\x00\xffstdin\n", None, False),
            ("text stdin, text mode", ("0", "text"), "héllo\n", None, True),
            ("cwd set, bytes mode", ("0", "bytes"), None, self.directory, False),
            ("cwd set, text mode", ("0", "text"), None, self.directory, True),
            ("exit 3", ("3", "bytes"), b"", None, False),
            ("sys.exit message", ("stopped by probe", "text"), None, None, True),
        )
        for name, args, input, cwd, text in rows:
            with self.subTest(name):
                done = run_script(self.probe, args, env=self.env, input=input, cwd=cwd,
                                  text=text)
                self.assertEqual((done.returncode, done.stdout, done.stderr),
                                 self.child(args, input=input, cwd=cwd, text=text))

    def test_the_process_is_restored_on_every_outcome(self):
        def state():
            return (os.getcwd(), dict(os.environ), list(sys.argv), sys.stdin, sys.stdout,
                    sys.stderr, sys.modules.get("__main__"))

        before = state()
        failed = run_script(self.probe, ("3", "bytes"), env=self.env, cwd=self.directory,
                            text=False)
        self.assertEqual(failed.returncode, 3)
        self.assertEqual(state(), before)
        raised = run_script(self.probe, ("raise", "text"), env=self.env, cwd=self.directory)
        self.assertEqual(raised.returncode, 1)
        self.assertEqual(raised.stderr.splitlines()[-1], "RuntimeError: probe failure")
        self.assertEqual(state(), before)
        missing = self.directory / "missing"
        with self.assertRaises(FileNotFoundError):
            run_script(self.probe, ("0", "bytes"), env=self.env, cwd=missing, text=False)
        self.assertEqual(state(), before)
        with self.assertRaises(FileNotFoundError):
            self.child(("0", "bytes"), input=None, cwd=missing, text=False)


if __name__ == "__main__":
    unittest.main()
