"""Tests for the look-lint command and look_marker.near_misses (issue 1141)."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import look_marker as lm

REPO_ROOT = Path(__file__).resolve().parents[1]
LINE = "- [ ] [human] before merge: the settings page at 390 px — measured: the owner, on the console"
HEAD = "## Acceptance criteria\n\n"


def lint(body, argv=("--body-file", "-")):
    done = subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.look_lint", *argv],
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "python")},
        input=body,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.stderr == "", done.stderr
    lines = done.stdout.splitlines()
    assert len(lines) == 1, done.stdout
    return done.returncode, json.loads(lines[0])


def verdict(name, marked, covers, malformed):
    return {"command": "look-lint", "verdict": name, "marked": marked, "covers": covers, "malformed": malformed}


class LookLintCommandTest(unittest.TestCase):
    def test_the_exact_form_is_accepted(self):
        self.assertEqual(
            lint(HEAD + LINE + "\n"),
            (0, verdict("ok", True, ["the settings page at 390 px"], [])),
        )

    def test_each_malformed_attempt_is_refused(self):
        texts = [
            LINE.replace("before merge:", "before-merge:"),
            LINE.replace("[human]", "[Human]"),
            LINE.replace("before merge:", "Before merge:"),
            LINE.replace("before merge:", "before merge"),
            LINE.replace("—", "--"),
            "- [ ] [human] before merge: the settings page at 390 px",
            " " + LINE,
            LINE.replace("- [ ] ", "- [] "),
            "- [ ] before-merge: the owner must see the page first",
            "[ ] [human] Before merge: the owner looks at the page — measured: the owner",
            "- [ ] [human] the owner looks at `the page` before merging — measured: the owner, on the console",
            "- [ ] [human] the owner looks at the page before merging — measured: the owner, on the console",
        ]
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(
                    lint(HEAD + text + "\n"),
                    (1, verdict("malformed", False, [], [{"line": 3, "text": text}])),
                )

    def test_ordinary_criteria_pass_unmarked(self):
        for text in (
            "- [ ] [human] the owner likes the colours — measured: the owner, on the page",
            "- [ ] [code] CI is green before merge — measured: the CI run",
            "- [ ] [code] the cache lookup is warmed before merge — measured: CI",
        ):
            with self.subTest(text=text):
                self.assertEqual(lint(HEAD + text + "\n"), (0, verdict("ok", False, [], [])))

    def test_prose_and_code_spans_that_use_the_words_are_accepted(self):
        for text in (
            "- It returns the stage **awaiting look**, with the reason in plain words (`issue N needs the owner's look before merge`), "
            "the before and after pictures if its verify step wrote any, and a `cont` to resume from.",
            "- **`to-issues`**: write one criterion in the exact line form. A malformed attempt (for example "
            "`[human] before-merge` or a hold in prose) is caught by a lint.",
            "`- [ ] [human] before merge: <what the owner looks at> — measured: <who judges, where>`",
            "The `[human]` kind token followed by the literal words `before merge:` is the marker; a hold written in prose is not.",
            "Hold this for a look before merge: the owner must see the page first.",
            "A look before merge is held [human] by the owner.",
        ):
            with self.subTest(text=text):
                self.assertEqual(lint(HEAD + text + "\n"), (0, verdict("ok", False, [], [])))

    def test_a_marker_beside_a_near_miss_is_refused(self):
        code, out = lint(HEAD + LINE + "\n- [ ] [human] before-merge: the page\n")
        self.assertEqual(code, 1)
        self.assertIs(out["marked"], True)
        self.assertEqual(out["covers"], ["the settings page at 390 px"])
        self.assertEqual(out["malformed"], [{"line": 4, "text": "- [ ] [human] before-merge: the page"}])

    def test_a_near_miss_inside_a_fence_is_not_read(self):
        for body in ("```\n- [ ] [human] before-merge: x\n```\n", "~~~~\n- [ ] [human] before-merge: x\n"):
            with self.subTest(body=body):
                self.assertEqual(lint(body), (0, verdict("ok", False, [], [])))

    def test_the_body_file_is_read_and_a_bad_one_is_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.md"
            bad = Path(tmp) / "bad.md"
            good.write_bytes((HEAD + LINE).encode("utf-8"))
            bad.write_bytes(b"\xff\xfe- [ ] [human] before merge\n")
            code, out = lint("", ("--body-file", str(good)))
            self.assertEqual(code, 0)
            self.assertIs(out["marked"], True)
            for argv in ((), ("--bogus",), ("--body-file", str(Path(tmp) / "missing.md")), ("--body-file", str(bad))):
                with self.subTest(argv=argv):
                    code, out = lint("", argv)
                    self.assertEqual(code, 2)
                    self.assertEqual(list(out), ["command", "verdict", "error", "detail"])
                    self.assertEqual(
                        [out["command"], out["verdict"], out["error"]], ["look-lint", "error", "usage"]
                    )
                    self.assertIsInstance(out["detail"], str)
                    self.assertTrue(out["detail"])

    def test_the_command_table_runs_look_lint(self):
        from agent_tools.delivery import look_lint

        table = (REPO_ROOT / "lib/agent-tools.nix").read_text()
        self.assertIsNotNone(re.search(r'^\s*"look-lint" = "delivery\.look_lint";$', table, re.M))
        self.assertEqual(look_lint.build_parser().prog, "look-lint")


class NearMissTest(unittest.TestCase):
    def test_line_numbers_count_fence_lines(self):
        self.assertEqual(
            lm.near_misses("```\nx\n```\n- [ ] [human] before-merge: x\n"),
            (lm.NearMiss(4, "- [ ] [human] before-merge: x"),),
        )

    def test_body_lines_skip_fences_and_strip_the_end(self):
        self.assertEqual(list(lm.body_lines("a  \r\n```\nb\n```\nc")), [(1, "a"), (5, "c")])
        self.assertEqual(list(lm.body_lines(None)), [(1, "")])


class TemplateTest(unittest.TestCase):
    TO_ISSUES = REPO_ROOT / "home/common/agent-skills/skills/to-issues/SKILL.md"

    def test_the_to_issues_template_carries_the_look_line(self):
        text = self.TO_ISSUES.read_text(encoding="utf-8")
        template = text[text.index("<issue-template>") : text.index("</issue-template>")]
        look = lm.read_look(template)
        self.assertEqual(look.covers, ("<what the owner looks at>",))
        self.assertEqual(look.criteria[0].measured, "<who judges, where>")
        self.assertEqual(lm.near_misses(template), ())
        start = text.index("Before publishing, reread each body")
        sentence = text[start : text.index("\n", start)]
        self.assertIn("then run `look-lint --body-file <f>` on it and fix each refusal.", sentence)

    def test_the_skill_stays_within_its_budget(self):
        self.assertTrue(6075 <= len(self.TO_ISSUES.read_bytes()) <= 6378)


if __name__ == "__main__":
    unittest.main()
