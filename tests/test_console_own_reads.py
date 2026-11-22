"""The own-read rule: which plain reads a manager's session may run without a permission card (#1620, ADR-console-103).

`own_reads.allowed` is pure over a command, the hook's working directory, session id, trusted root and
transcript stores, so every case here builds a real directory tree in a temporary directory and asks it
directly. The table of Case 1 holds every admitted form and every refused one; the later cases pin the
process-relative links, the case alias of the root, `GREP_OPTIONS`, the malformed inputs, the operand
grammar and the question hook's genuine-directory rule (`session_results`).

Run: just agent-workflow-tests
"""

from __future__ import annotations

import errno
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import own_reads, project_question_hook

TIER = "fast"  # source tree and standard library only


class OwnReadsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.T = T = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, T, ignore_errors=True)
        self.root = root = T / "proj"
        (root / "sub").mkdir(parents=True)
        (root / "README.md").write_text("readme\n")
        (root / "sub" / "a.txt").write_text("a\n")
        self.store = store = T / "home" / ".claude" / "projects"
        self.profile = profile = T / "accounts" / "profiles" / "work"
        store.mkdir(parents=True)
        profile.mkdir(parents=True)
        (profile / "projects").symlink_to(store)
        self.results = results = store / "-srv-proj" / "sess-1" / "tool-results"
        results.mkdir(parents=True)
        (results / "b1.txt").write_text("saved\n")
        (store / "-srv-proj" / "sess-2" / "tool-results").mkdir(parents=True)
        (store / "-srv-proj" / "sess-2" / "tool-results" / "b1.txt").write_text("other\n")
        (store / "-srv-proj" / "sess-1.jsonl").write_text("{}\n")
        (T / "out-slug" / "sess-1" / "tool-results").mkdir(parents=True)
        (T / "out-slug" / "sess-1" / "tool-results" / "x.txt").write_text("x\n")
        (store / "-linked").symlink_to(T / "out-slug")
        (T / "out-session" / "tool-results").mkdir(parents=True)
        (T / "out-session" / "tool-results" / "x.txt").write_text("x\n")
        (store / "-srv-two").mkdir()
        (store / "-srv-two" / "sess-1").symlink_to(T / "out-session")
        (T / "out-results").mkdir()
        (T / "out-results" / "x.txt").write_text("x\n")
        (store / "-srv-three" / "sess-1").mkdir(parents=True)
        (store / "-srv-three" / "sess-1" / "tool-results").symlink_to(T / "out-results")
        (T / "secret").mkdir()
        self.secret = secret = T / "secret" / "id"
        secret.write_text("secret\n")
        (root / "link").symlink_to(secret)
        (root / "loop").symlink_to("loop")
        (T / "secret" / "hard-target").write_text("hard\n")
        os.link(T / "secret" / "hard-target", root / "hard")
        self.stores = project_question_hook.transcript_dirs(
            {"HOME": str(T / "home"), "CLAUDE_ACCOUNTS_DIR": str(T / "accounts"),
             "CLAUDE_CONFIG_DIR": str(profile)})

    def check(self, command, cwd=None, session="sess-1", root="default", environ=None) -> bool:
        cwd = self.root if cwd is None else cwd
        root = self.root if root == "default" else root
        return own_reads.allowed(command, str(cwd), session, root if root is None else str(root),
                                 self.stores, environ or {})

    def test_reads_of_own_output_and_worktree_pass_and_every_other_form_prompts(self):
        results, store, secret, profile = self.results, self.store, self.secret, self.profile
        admitted = [
            f"sed -n 1,5p {results}/b1.txt",
            f"sed -n 1,5p {profile}/projects/-srv-proj/sess-1/tool-results/b1.txt",
            "sed -n '$p' README.md",
            "head -n 20 README.md",
            f"head -5 {results}/b1.txt",
            "tail -n +3 README.md",
            "tail -c 100 README.md",
            "cat -n README.md sub/a.txt",
            "cat 'README.md'",
            "cat sub/../README.md",
            "cat absent.txt",
            f"grep -n foo README.md {results}/b1.txt",
            "grep -e foo -e bar sub/a.txt",
            "grep -i -A 3 foo README.md",
            "wc -l README.md",
        ]
        refused = [
            "less README.md", "/bin/cat README.md", "env cat README.md", "FOO=1 cat README.md",
            "sed -i '' 1p README.md", "sed -n 1p README.md -i", "sed -n '1w out' README.md",
            "sed -n -e 1p README.md", "sed -E -n 1p README.md",
            "cat README.md > out", "cat README.md >> out", "cat README.md | head",
            "cat README.md; rm x", "cat README.md && curl x", "cat $(echo README.md)",
            "cat `echo x`", 'cat "$HOME/x"', "cat *.md", "cat ~/.ssh/id_ed25519",
            "grep foo README.md | wc -l", "cat README.md | tee x", "tee x", "python3 -c 1",
            "cat README.md -n", "head README.md -n 3", f"grep -e foo README.md -e {secret}",
            "grep foo README.md -r",
            "head -- README.md", "cat -", "wc --files0-from=x", "tail -f README.md",
            f"grep -f {secret} README.md",
            "cat -n", "grep foo", "sed -n 1p",
            "cat ../secret/id", "cat link", "cat loop", "cat nothere/../README.md",
            "cat README.md/../README.md", "cat /etc/passwd",
            f"cat {store}/-srv-proj/sess-2/tool-results/b1.txt", f"cat {store}/-srv-proj/sess-1.jsonl",
            f"cat {store}/-linked/sess-1/tool-results/x.txt",
            f"cat {store}/-srv-two/sess-1/tool-results/x.txt",
            f"cat {store}/-srv-three/sess-1/tool-results/x.txt",
            f"cat README.md {secret}", f"cat {secret} README.md",
            f"grep foo README.md {secret}", f"grep foo {secret} README.md",
            f"cat {results}/b1.txt {secret}", f"cat {secret} {results}/b1.txt",
            f"cat {secret}", "cat hard",
        ]
        for command in admitted:
            with self.subTest(command=command):
                self.assertTrue(self.check(command))
        for command in refused:
            with self.subTest(command=command):
                self.assertFalse(self.check(command))

    @unittest.skipUnless(os.path.isdir("/proc/self/fd"), "needs /proc")
    def test_a_process_relative_link_prompts(self):
        previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)
        self.assertFalse(self.check("cat /proc/self/cwd/README.md", cwd=self.T))
        (self.root / "here").symlink_to("/proc/self/cwd")
        self.assertFalse(self.check("cat here/README.md"))
        fd = os.open(self.root / "README.md", os.O_RDONLY)
        self.addCleanup(os.close, fd)
        self.assertFalse(self.check(f"cat /dev/fd/{fd}"))
        self.assertFalse(self.check(f"cat /proc/self/fd/{fd}"))

    def test_a_case_alias_of_the_root_is_the_root(self):
        alias = str(self.root).swapcase()
        if os.path.exists(alias):
            self.assertTrue(self.check("cat README.md", cwd=alias))
            self.assertTrue(self.check(f"cat {alias}/README.md"))
            self.assertFalse(self.check(f"cat {str(self.secret).swapcase()}"))
        elif sys.platform == "darwin":
            self.fail("expected a case-insensitive temporary volume on macOS")
        else:
            self.skipTest("the temporary volume is case-sensitive")

    def test_grep_prompts_when_grep_options_are_set(self):
        self.assertFalse(self.check("grep foo README.md", environ={"GREP_OPTIONS": f"-f {self.secret}"}))
        self.assertTrue(self.check("grep foo README.md", environ={}))
        self.assertTrue(self.check("cat README.md", environ={"GREP_OPTIONS": "x"}))

    def test_the_session_cwd_and_root_must_be_well_formed(self):
        own = f"cat {self.results}/b1.txt"
        self.assertTrue(self.check(own))
        self.assertFalse(self.check(own, session="sess-2"))
        self.assertFalse(self.check(own, session="../sess-1"))
        self.assertFalse(self.check(own, session=3))
        self.assertFalse(self.check("cat README.md", cwd="proj"))
        self.assertFalse(self.check("cat README.md", root=None))
        self.assertTrue(self.check(own, root=None))
        self.assertFalse(self.check("cat README.md", root="proj"))
        with mock.patch.object(own_reads.os, "lstat", side_effect=PermissionError(errno.EACCES, "denied")):
            self.assertFalse(self.check("cat README.md"))

    def test_operands_name_only_the_paths(self):
        self.assertEqual(["foo", "a", "b"], own_reads.operands("grep -e x -n foo a b"))
        self.assertEqual(["a", "b"], own_reads.operands("grep -n foo a b"))
        self.assertEqual(["a"], own_reads.operands("sed -n 2,4p a"))
        self.assertEqual(["a"], own_reads.operands("head -n 3 a"))
        self.assertEqual(["a"], own_reads.operands("tail -n +3 a"))
        self.assertIsNone(own_reads.operands("cat -n"))
        self.assertIsNone(own_reads.operands("cat a -n"))
        self.assertIsNone(own_reads.operands("grep -e x a -e b"))

    def test_session_results_is_the_question_hooks_rule(self):
        rule = project_question_hook.session_results
        self.assertTrue(rule(str(self.results / "b1.txt"), "sess-1", self.stores))
        self.assertFalse(rule(str(self.results / "b1.txt"), "sess-2", self.stores))
        self.assertFalse(rule(str(self.store / "-srv-proj" / "sess-1.jsonl"), "sess-1", self.stores))
        for linked in (self.T / "out-slug" / "sess-1" / "tool-results" / "x.txt",
                       self.T / "out-session" / "tool-results" / "x.txt",
                       self.T / "out-results" / "x.txt"):
            with self.subTest(linked=str(linked)):
                self.assertFalse(rule(str(linked), "sess-1", self.stores))
        self.assertFalse(rule(str(self.results / "b1.txt"), "sess-1", (str(self.T / "missing"),)))


if __name__ == "__main__":
    unittest.main()
