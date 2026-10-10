"""Rendering contract of `agent_tools.sdd_brief` (issue 353, spec D5).

The rendering functions are imported (agent-helpers rule 5). The shipped
templates are rendered and compared with a body this file derives on its own;
no test holds a copy of their prose (rule 6).
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from agent_tools import sdd_brief
from agent_tools.sdd_brief import BriefError

REPO_ROOT = Path(__file__).resolve().parents[1]
SDD = REPO_ROOT / "home/common/agent-skills/skills/sdd"
TOKENS = frozenset({"[BRIEF_FILE]", "[CONTEXT]", "[REPORT_FILE]"})
VALUES = {"[BRIEF_FILE]": "/w/brief.md", "[REPORT_FILE]": "/w/report.md", "[CONTEXT]": "ctx"}
HEADER = ("Subagent:", '  description: "x"', "  prompt: |")
BODY = ("    Read [BRIEF_FILE] then [REPORT_FILE].", "", "    [CONTEXT]", "   ",
        "    Verdict: [Approved | Needs fixes]", "      indented")
RENDERED = ("Read /w/brief.md then /w/report.md.\n\nctx\n\n"
            "Verdict: [Approved | Needs fixes]\n  indented\n")


def template(*body, header=HEADER):
    return "\n".join(["# Fixture", "", "Outside [NOT_A_SLOT].", "", "```", *header, *body,
                      "```", "", "After.", ""])


def independent_body(text):
    """The fence lines after `prompt: |`, their first four characters removed (spec seam 2)."""
    lines = text.split("\n")
    opening, closing = [i for i, line in enumerate(lines) if line.startswith("```")]
    start = next(i for i in range(opening, closing) if lines[i].strip() == "prompt: |")
    return "\n".join(line[4:] for line in lines[start + 1:closing]) + "\n"


class RenderTest(unittest.TestCase):
    def test_the_body_is_dedented_and_filled(self):
        self.assertEqual(sdd_brief.render(template(*BODY), TOKENS, VALUES), RENDERED)

    def test_prompt_body_keeps_the_tokens(self):
        self.assertEqual(
            sdd_brief.prompt_body(template(*BODY)),
            "Read [BRIEF_FILE] then [REPORT_FILE].\n\n[CONTEXT]\n\n"
            "Verdict: [Approved | Needs fixes]\n  indented\n")

    def test_a_value_is_inserted_verbatim_and_never_rescanned(self):
        values = {**VALUES, "[BRIEF_FILE]": "[REPORT_FILE] \\1 $x", "[CONTEXT]": "a\n[BRIEF_FILE]"}
        self.assertEqual(
            sdd_brief.render(template(*BODY), TOKENS, values),
            "Read [REPORT_FILE] \\1 $x then /w/report.md.\n\na\n[BRIEF_FILE]\n\n"
            "Verdict: [Approved | Needs fixes]\n  indented\n")

    def test_an_empty_optional_value_removes_its_line_and_the_empty_line_after(self):
        self.assertEqual(
            sdd_brief.render(template(*BODY), TOKENS, {**VALUES, "[CONTEXT]": ""}),
            "Read /w/brief.md then /w/report.md.\n\nVerdict: [Approved | Needs fixes]\n  indented\n")

    def test_an_empty_optional_value_keeps_a_following_text_line(self):
        body = ("    [CONTEXT]", "    Read [BRIEF_FILE] then [REPORT_FILE].")
        self.assertEqual(
            sdd_brief.render(template(*body), TOKENS, {**VALUES, "[CONTEXT]": ""}),
            "Read /w/brief.md then /w/report.md.\n")

    def test_a_labeled_fence_is_not_the_prompt(self):
        text = template(*BODY) + "\n```python\nprint('[ZED]')\n```\n"
        self.assertEqual(sdd_brief.render(text, TOKENS, VALUES), RENDERED)

    def test_every_other_shape_is_refused(self):
        good = template(*BODY)
        cases = {
            "no fence": ("# T\n\nno fence\n", TOKENS, VALUES),
            "two unlabeled fences": (good + "\n```\nmore\n```\n", TOKENS, VALUES),
            "unclosed fence": (good.replace("```\n\nAfter.\n", "\nAfter.\n"), TOKENS, VALUES),
            "no prompt line": (template(*BODY, header=("Subagent:",)), TOKENS, VALUES),
            "two prompt lines": (template("    prompt: |", *BODY), TOKENS, VALUES),
            "under-indented line": (template(*BODY, "  short"), TOKENS, VALUES),
            "last body line empty": (template(*BODY, ""), TOKENS, VALUES),
            "unknown token": (template(*BODY, "    [ZED]"), TOKENS, VALUES),
            "token missing from the template": (
                good, TOKENS | {"[BASE_SHA]"}, {**VALUES, "[BASE_SHA]": "x"}),
            "value missing": (good, TOKENS, {"[BRIEF_FILE]": "b", "[CONTEXT]": "c"}),
            "extra value": (good, TOKENS, {**VALUES, "[ZED]": "z"}),
            "empty required value": (good, TOKENS, {**VALUES, "[BRIEF_FILE]": ""}),
            "optional token sharing its line": (
                template("    Read [BRIEF_FILE] then [REPORT_FILE].", "    Context: [CONTEXT]"),
                TOKENS, VALUES),
        }
        for name, (text, tokens, values) in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(BriefError):
                    sdd_brief.render(text, tokens, values)


class ShippedTemplateTest(unittest.TestCase):
    def test_the_token_sets_are_the_spec_table(self):
        plan = {"[PLAN_ROOT]", "[PLAN_ROOT_BYTES]", "[PLAN_TOTAL_BYTES]", "[PLAN_FILE_COUNT]",
                "[PLAN_LARGEST_MEMBER_BYTES]"}
        both = plan | {"[BRIEF_FILE]", "[REPORT_FILE]", "[GLOBAL_CONSTRAINTS]", "[STANDARDS]",
                       "[STACKS_DIR]"}
        self.assertEqual(sdd_brief.IMPLEMENTER_TOKENS, both | {
            "[TASK_NUMBER]", "[TASK_NAME]", "[CONTEXT]", "[TEST_SEAMS]", "[LIFECYCLE_WORKER]"})
        self.assertEqual(sdd_brief.REVIEWER_TOKENS, both | {
            "[BASE_SHA]", "[HEAD_SHA]", "[MANIFEST_ROOT]", "[ROOT_BYTES]", "[TOTAL_BYTES]",
            "[FILE_COUNT]", "[LARGEST_MEMBER_BYTES]"})
        self.assertEqual(sdd_brief.OPTIONAL_TOKENS, {"[CONTEXT]", "[LIFECYCLE_WORKER]"})

    def test_filling_each_token_with_itself_reproduces_the_prompt_body(self):
        for name, tokens in ((sdd_brief.IMPLEMENTER_TEMPLATE, sdd_brief.IMPLEMENTER_TOKENS),
                             (sdd_brief.REVIEWER_TEMPLATE, sdd_brief.REVIEWER_TOKENS)):
            with self.subTest(template=name):
                text = (SDD / name).read_text(encoding="utf-8")
                self.assertEqual(sdd_brief.render(text, tokens, {token: token for token in tokens}),
                                 independent_body(text))


PLAN = "\n".join([
    "# P", "", "**Goal:** g", "",
    "## Global Constraints", "", "- one", "", "- two", "", "",
    "## Test seams", "- seam", "",
    "## Task index", "",
    "Task 1 — First thing — `a/b.py`, `docs/x.md` — full — [task-1.md](plan.tasks/task-1.md)",
    "Task 2 — Second — with a dash — `c.py` — low-risk — [task-2.md](plan.tasks/task-2.md)",
    "Task 4 — Too — short",
    "", "## Decisions", "",
    "Task 3 — Outside — `z.py` — full — [task-3.md](plan.tasks/task-3.md)", ""])


class PlanHeaderTest(unittest.TestCase):
    def test_a_section_body_drops_its_outer_empty_lines(self):
        self.assertEqual(sdd_brief.plan_section(PLAN, "## Global Constraints"), "- one\n\n- two")
        self.assertEqual(sdd_brief.plan_section(PLAN, "## Test seams"), "- seam")

    def test_a_missing_or_repeated_heading_is_refused(self):
        with self.assertRaises(BriefError):
            sdd_brief.plan_section(PLAN, "## Nope")
        with self.assertRaises(BriefError):
            sdd_brief.plan_section(PLAN + "\n## Test seams\n\n- again\n", "## Test seams")

    def test_the_index_row_gives_the_title_and_the_backticked_paths(self):
        self.assertEqual(sdd_brief.task_row(PLAN, 1),
                         sdd_brief.TaskRow("First thing", ("a/b.py", "docs/x.md")))
        self.assertEqual(sdd_brief.task_row(PLAN, 2),
                         sdd_brief.TaskRow("Second — with a dash", ("c.py",)))

    def test_a_missing_repeated_or_malformed_row_is_refused(self):
        repeated = PLAN.replace("Task 4 — Too — short",
                                "Task 1 — Again — `q.py` — full — [task-1.md](plan.tasks/task-1.md)")
        cases = {"row only outside the index": (PLAN, 3), "no such row": (PLAN, 9),
                 "too few fields": (PLAN, 4), "repeated row": (repeated, 1),
                 "no Task index": (PLAN.replace("## Task index", "## Tasks"), 1),
                 "two Task indexes": (PLAN + "\n## Task index\n", 1)}
        for name, (text, number) in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(BriefError):
                    sdd_brief.task_row(text, number)


class StandardsTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        self.layer0 = self.root / "global"
        self.layer0.mkdir()
        self.bar = self.layer0 / "the-bar.md"
        self.bar.write_text("# Bar\n\nDeep modules.\n\n\n", encoding="utf-8")
        self.project = self.root / "project"
        self.project.mkdir()
        self.readme = self.project / "README.md"
        self.readme.write_text(
            "# Project standards\n\nIntro.\n\n"
            "| Shard | governs | Gist |\n|---|---|---|\n"
            "| [py.md](py.md) | `python/**`, `scripts/*.py` | Python rules. |\n"
            "| [docs.md](docs.md) | `docs/**` | Doc rules. |\n\nAfter the table.\n",
            encoding="utf-8")
        self.py = self.project / "py.md"
        self.py.write_text("# Py\n", encoding="utf-8")
        self.docs = self.project / "docs.md"
        self.docs.write_text("# Docs\n", encoding="utf-8")
        self.single = self.root / "single.md"
        self.single.write_text("# Single\n\nOne file.\n", encoding="utf-8")
        self.plain = self.root / "plain"
        self.plain.mkdir()
        (self.plain / "README.md").write_text(
            "| Layer | Where |\n|---|---|\n| 0 | [the-bar.md](the-bar.md) |\n", encoding="utf-8")

    def select(self, *touched, entries=None):
        entries = [self.project, self.single, self.plain] if entries is None else entries
        return sdd_brief.select_standards(self.layer0, entries, list(touched))

    def test_layer_zero_is_first_and_a_row_is_selected_by_its_globs(self):
        self.assertEqual(self.select("python/agent_tools/x.py"), [self.bar, self.py, self.single])
        self.assertEqual(self.select("docs/a/b.md", "scripts/run.py"),
                         [self.bar, self.py, self.docs, self.single])
        self.assertEqual(self.select("notes.txt"), [self.bar, self.single])
        self.assertEqual(self.select("Python/x.py"), [self.bar, self.single])
        self.assertEqual(self.select(), [self.bar, self.single])

    def test_entries_are_taken_in_the_order_given_and_listed_once(self):
        self.assertEqual(self.select("python/x.py", entries=[self.single, self.project]),
                         [self.bar, self.single, self.py])
        self.assertEqual(self.select("python/x.py", entries=[self.project, self.project]),
                         [self.bar, self.py])

    def test_a_layer_that_cannot_be_read_as_declared_is_refused(self):
        table = "| Shard | governs | Gist |\n|---|---|---|\n"

        def missing_bar():
            self.bar.unlink()

        def dangling_row():
            self.docs.unlink()

        def escaping_row():
            self.readme.write_text(table + "| [up](../single.md) | `docs/**` | Up. |\n",
                                   encoding="utf-8")

        def row_without_a_link():
            self.readme.write_text(table + "| py.md | `python/**` | No link. |\n", encoding="utf-8")

        def short_row():
            self.readme.write_text(table + "| [py.md](py.md) |\n", encoding="utf-8")

        for arrange in (missing_bar, dangling_row, escaping_row, row_without_a_link, short_row):
            with self.subTest(case=arrange.__name__):
                self.setUp()
                arrange()
                with self.assertRaises(BriefError):
                    self.select("python/x.py")
        with self.subTest(case="an entry that does not exist"):
            self.setUp()
            with self.assertRaises(BriefError):
                self.select("python/x.py", entries=[self.root / "absent"])

    def test_the_value_pastes_each_document_under_its_source_line(self):
        self.assertEqual(sdd_brief.standards_value([self.bar, self.py]),
                         f"Source: {self.bar}\n\n# Bar\n\nDeep modules.\n\nSource: {self.py}\n\n# Py")

    def test_a_document_that_is_not_utf8_is_refused(self):
        self.py.write_bytes(b"\xff\xfe")
        with self.assertRaises(BriefError):
            sdd_brief.standards_value([self.bar, self.py])


class WorkerBlockTest(unittest.TestCase):
    def test_the_block_is_the_worker_line_and_the_two_launch_scope_sentences(self):
        flags = "--repo-root /r --run-id run-1 --worker-id 14:1:1:w1"
        self.assertEqual(sdd_brief.worker_block("/r", "run-1", "14:1:1:w1"), "\n".join([
            f"Lifecycle worker: {flags}",
            "Run each long command, every verification command included, as "
            f"`launch-scope exec {flags} -- <argv>`, still in the foreground.",
            "Create every scratch directory or scratch worktree under the path that "
            f"`launch-scope scratch {flags}` prints."]))


if __name__ == "__main__":
    unittest.main()
