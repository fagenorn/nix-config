import contextlib
import io
import os
import tempfile
import unittest

from tinytask.cli import main


def run(*argv):
    """Run the CLI, returning (exit_code, stdout_lines)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(argv))
    return code, buffer.getvalue().splitlines()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "tasks.json")

    def add(self, title):
        return run("--file", self.path, "add", title)

    def test_add_echoes_the_created_task(self):
        code, lines = self.add("write the spec")
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["1\topen\twrite the spec"])

    def test_list_hides_done_tasks_by_default(self):
        self.add("write the spec")
        self.add("write the plan")
        run("--file", self.path, "done", "1")
        _, lines = run("--file", self.path, "list")
        self.assertEqual(lines, ["2\topen\twrite the plan"])

    def test_list_all_includes_done_tasks(self):
        self.add("write the spec")
        run("--file", self.path, "done", "1")
        _, lines = run("--file", self.path, "list", "--all")
        self.assertEqual(lines, ["1\tdone\twrite the spec"])

    def test_done_on_unknown_id_exits_non_zero(self):
        code, lines = run("--file", self.path, "done", "99")
        self.assertEqual(code, 1)
        self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
