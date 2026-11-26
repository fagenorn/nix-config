"""The console's runtime copy of the owner glossary matches the docs table and flags what it should.

Run: just agent-workflow-tests
"""
import ast
import json
import re
import unittest
from pathlib import Path

from agent_tools.console import answer, deliveries, engine_runs, owner_words, sprints, view
from agent_tools.delivery import procedure_check
from agent_tools.delivery.engine_ledger import RunState
from agent_tools.delivery.routing import index_table

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES = REPO_ROOT / "tests/fixtures/console/owner-words-cases.json"
ORDINARY = REPO_ROOT / "tests/fixtures/console/owner-words-ordinary.txt"
PAGE = REPO_ROOT / "python/agent_tools/console/page.html"
PAGE_TEXT_MODULES = ("view", "sprints", "engine_runs", "guest", "capacity")
LITERAL_MODULES = ("answer", "approve", "contract_draft")
SPRINT_LITERAL_MODULES = ("answer", "card_entries")
OWNER_FACING = re.compile(r"(?:_TEXT|_LABEL|_SENTENCE|_LINE|_LEAD)$|^HEADLINE$")
STR = r'"((?:[^"\\\n]|\\.)*)"'
CLASS_POSITIONS = (
    r'\b(?:el|phrase)\(\s*"[^"]*"\s*,\s*' + STR,
    r"\bactionButton\(\s*" + STR,
    r"\.className\s*=\s*" + STR,
)
TEXT_POSITIONS = (
    r'\bel\(\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*' + STR,
    r'\bactionButton\(\s*"[^"]*"\s*,\s*' + STR,
    r"\.textContent\s*=\s*" + STR,
    r'setAttribute\(\s*"(?:title|aria-label|placeholder)"\s*,\s*' + STR,
)


def page_words(html):
    """The page's own words: markup text, visible attributes, and the script's phrases."""
    first, last = html.find("<script>"), html.rfind("</script>")
    script, markup = html[first + len("<script>"):last], html[:first] + html[last + len("</script>"):]
    markup = re.sub(r"<(style|template)\b[^>]*>.*?</\1>", "", markup, flags=re.S)
    words = [t.strip() for t in re.findall(r">([^<>]+)<", markup) if t.strip()]
    words += re.findall(r'\b(?:title|aria-label|placeholder|alt)="([^"]*)"', markup)
    starts = lambda patterns: {m.start(1) for p in patterns for m in re.finditer(p, script)}
    classes, texts = starts(CLASS_POSITIONS), starts(TEXT_POSITIONS)
    for m in re.finditer(STR, script):
        lit = m.group(1)
        if m.start(1) in classes:
            continue
        if m.start(1) in texts or re.search(r"\s", lit) or lit[:1].isupper():
            words.append(lit)
    return words


def text_constants(source):
    """The string values of the module's owner-facing names, never a dict key."""
    def values(node):
        if isinstance(node, ast.Dict):
            return [v for x in node.values for v in values(x)]
        if isinstance(node, ast.Constant):
            return [node.value] if isinstance(node.value, str) else []
        return [v for x in ast.iter_child_nodes(node) for v in values(x)]
    out = []
    for stmt in ast.parse(source).body:
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target] if isinstance(stmt, ast.AnnAssign) else []
        if targets and stmt.value is not None and any(isinstance(t, ast.Name) and OWNER_FACING.search(t.id) for t in targets):
            out += values(stmt.value)
    return out


def module_literals(source):
    """Every string literal of the module the owner may read: no docstring, no `raise` argument, no option flag.

    The refusals, headlines and notes of `answer` and `approve` are module constants under many names and
    f-strings inside functions, so these two modules are scanned by literal, not by name.
    """
    tree = ast.parse(source)
    skipped = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise):
            skipped |= {id(n) for n in ast.walk(node)}
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and body \
                and isinstance(body[0], ast.Expr):
            skipped.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skipped
            and not n.value.startswith("-")]


def console_text_words():
    root = REPO_ROOT / "python/agent_tools/console"
    read = lambda m: (root / (m + ".py")).read_text(encoding="utf-8")
    return ([w for m in PAGE_TEXT_MODULES for w in text_constants(read(m))]
            + [w for m in LITERAL_MODULES for w in module_literals(read(m))])


def blank_fields(text):
    """A format field reads as a number, so a text such as "issue #{issue}" is still found."""
    return re.sub(r"\$?\{[^{}]*\}", "1", text)


def prose(texts):
    return [t for t in texts if re.search(r"\s", t)]


def engine_state(stage):
    return RunState(run="r", project="o/p", issue=1, stage=stage, step=None, wait=None, stop=None, done=False,
                    last_event=None, process=None, alive=True, engine_alive=True)


def sprint_page_words():
    root = REPO_ROOT / "python/agent_tools/console"
    read = lambda m: (root / (m + ".py")).read_text(encoding="utf-8")
    stages = sprints.REPORT_STAGES + sprints.CLOSING_STAGES + deliveries.STAGES
    summary = deliveries.run_summary([deliveries.IssueStage(n, s) for n, s in enumerate(deliveries.STAGES, 1)],
                                     "moved just now")
    return (page_words(PAGE.read_text(encoding="utf-8"))
            + [w for m in PAGE_TEXT_MODULES for w in text_constants(read(m))]
            + [w for m in SPRINT_LITERAL_MODULES for w in prose(module_literals(read(m)))]
            + [sprints.closing_text(1, 1, 1), sprints.progress_text(1, 4, 1, 1, 1)]
            + [view.CLOSING_OUTCOME_TEXT.get(s, deliveries.stage_words(s)) for s in stages]
            + [summary]
            + [engine_runs.line_text(engine_state(s)) for s in procedure_check.STAGES]
            + [answer.LOOK_APPROVES.format(option="Approve this head", head="aaaaaaa", pr=12, issue=7),
               answer.LOOK_RECORDING.format(head="aaaaaaa", issue=7),
               answer.LOOK_MOVED.format(found="bbbbbbb", head="aaaaaaa")])


def words(text):
    return [f.word for f in owner_words.found(text)]


class ListTest(unittest.TestCase):
    def test_the_page_of_ordinary_sentences_raises_nothing(self):
        lines = [l for l in ORDINARY.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertGreaterEqual(len(lines), 24)
        for line in lines:
            with self.subTest(line=line):
                self.assertEqual(words(line), [])
        page = "\n".join(lines)
        for word in ("main", "head", "look", "held", "land", "claim", "issue", "profile", "guard", "brief",
                     "queued", "activate"):
            with self.subTest(word=word):
                self.assertIsNotNone(re.search(rf"(?<![0-9A-Za-z]){word}(?![0-9A-Za-z])", page, re.I))

    def test_the_list_copy_matches_the_docs_table(self):
        text = (REPO_ROOT / "docs/guides/owner-words.md").read_text(encoding="utf-8")
        rows = index_table(text)
        self.assertEqual(rows[0], ["Do not write", "Write instead"])
        self.assertEqual([tuple(r) for r in rows[1:]], [(a, b) for a, b, _ in owner_words.ROWS])
        self.assertEqual(len(owner_words.ROWS), 27)

    def test_the_shared_cases_find_what_the_case_file_says(self):
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 40)
        for case in cases:
            with self.subTest(text=case["text"]):
                self.assertEqual(words(case["text"]), case["found"])

    def test_the_cases_cover_every_row(self):
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        rows = {f.row for case in cases for f in owner_words.found(case["text"])}
        self.assertEqual(rows, set(range(len(owner_words.ROWS))))

    def test_an_explained_word_is_still_found(self):
        self.assertEqual(words("the land lock (its turn to merge)"), ["land lock"])

    def test_the_longest_match_wins_an_overlap(self):
        self.assertEqual(words("the guard refusal"), ["guard refusal"])
        self.assertEqual(words("verify-fix"), ["verify-fix"])

    def test_the_sentence_is_the_one_holding_the_word(self):
        (hit,) = owner_words.found("All good. Waiting on the land\nlock now. Next is tests.")
        self.assertEqual((hit.word, hit.sentence), ("land lock", "Waiting on the land lock now."))

    def test_found_in_counts_a_word_once_across_texts_in_list_order(self):
        hits = owner_words.found_in(["the guard said no", "rerun now", "rerun later"])
        self.assertEqual([f.word for f in hits], ["rerun", "the guard"])
        self.assertEqual(hits[0].sentence, "rerun now")
        self.assertEqual(owner_words.found_in([]), [])

    def test_no_replacement_uses_a_listed_word(self):
        for _, instead, _ in owner_words.ROWS:
            with self.subTest(instead=instead):
                self.assertEqual(owner_words.found(instead), [])


class NoGlossTest(unittest.TestCase):
    def test_a_status_with_a_listed_word_stays_plain_text(self):
        from .test_console_page import REPORTED, START, full, nodes, of_class, render, sprint_lines, with_sprints

        frame = {**view.derive_view([]), **with_sprints([{**REPORTED, "status": "waiting on the land lock"}])}
        (snap,) = render([START, {"frame": frame}, {"open": "sprint:" + REPORTED["sprint_id"]}, {"snapshot": True}])
        (line,) = sprint_lines(snap)
        (status,) = of_class(line, "p", "report-status")
        self.assertEqual(full(status), "waiting on the land lock")
        self.assertEqual([n for n in nodes(status) if n["tag"] == "button"], [])
        self.assertEqual([n["title"] for n in nodes(status) if n.get("title")], [])

    def test_the_view_sends_no_glossary(self):
        self.assertNotIn("glossary", view.derive_view([]))

    def test_no_gloss_module_or_picture_state_remains(self):
        self.assertEqual(sorted(p.name for p in (REPO_ROOT / "tests").glob("*gloss*.py")), [])
        for name in ("tests/console_screenshots.py", "justfile"):
            with self.subTest(file=name):
                text = (REPO_ROOT / name).read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"(?i)gloss", text))


class FixedWordsTest(unittest.TestCase):
    def test_the_look_and_adoption_refusals_are_among_the_scanned_words(self):
        from agent_tools.console import answer, approve
        words = console_text_words()
        for text in (answer.LOOK_MOVED, answer.LOOK_CLOSED, approve.FAILING, approve.NOT_READY_PULL,
                     approve.MERGING, "The proposed change of "):
            self.assertIn(text, words)

    def test_module_literals_reads_function_strings_and_skips_docstrings_raises_and_flags(self):
        source = ('"""held doc"""\nA = "guard"\ndef f(n):\n    """rerun doc"""\n'
                  '    if n:\n        raise ValueError("a claim")\n    run(["git", "--verify"])\n    return f"The look of {n} is held."\n')
        self.assertEqual(module_literals(source), ["guard", "The look of ", " is held.", "git"])

    def test_a_failing_adoptions_reason_names_the_link_the_card_shows(self):
        from agent_tools.console import approve
        label = "Open the proposed change on GitHub"
        self.assertIn(label, PAGE.read_text(encoding="utf-8"))
        self.assertIn(label, approve.FAILING_WHY)

    def test_page_words_reads_markup_text_and_visible_attributes(self):
        html = '<p title="Open the pull request">The land lock</p><style>.held{}</style><template id="x"><b>held</b></template><script>"use strict";</script>'
        words = page_words(html)
        self.assertIn("Open the pull request", words)
        self.assertIn("The land lock", words)
        self.assertFalse([w for w in words if "held" in w])

    def test_page_words_reads_script_phrases_and_capitalised_literals(self):
        words = page_words('<script>el("p", "x", w); f("the rerun waits"); const L = [["Held", "held"]];</script>')
        self.assertIn("the rerun waits", words)
        self.assertIn("Held", words)
        self.assertNotIn("held", words)

    def test_page_words_reads_a_lowercase_word_in_a_text_position(self):
        html = '<script>el("span", "", "guard"); actionButton("x btn-quiet", "rerun", f); n.textContent = "held"; b.setAttribute("title", "claim"); if (s === "look") {}</script>'
        self.assertEqual(page_words(html), ["guard", "rerun", "held", "claim"])

    def test_page_words_skips_class_arguments_and_code_tokens(self):
        html = '<script>el("p", "held why", w); phrase("span", "look card", x); actionButton("claim btn", "Go", f); n.className = "rerun now"; if (s === "held") {}</script>'
        self.assertEqual(page_words(html), ["Go"])

    def test_page_words_reads_hundreds_of_the_pages_words(self):
        self.assertGreater(len(page_words(PAGE.read_text(encoding="utf-8"))), 500)

    def test_text_constants_reads_the_values_of_owner_facing_names(self):
        source = 'A_TEXT = {"claim": "Claim", "look": ("your look", "x")}\nB = "rerun"\nC_LABEL = f"held {n}"\nD_SENTENCE = "a" "b"\nHEADLINE = "Top"\nE_LINE: str = "Line"\ndef f():\n    F_TEXT = "inner"\n'
        self.assertEqual(text_constants(source), ["Claim", "your look", "x", "held ", "ab", "Top", "Line"])

    def test_console_text_words_reads_the_modules_the_page_shows(self):
        from agent_tools.console import answer, approve, guest, sprints
        words = console_text_words()
        for text in (sprints.NOW_LOCK_TEXT, view.HEADLINE, guest.SHARING_OFF_TEXT, answer.LOOK_APPROVES,
                     approve.FAILING_WHY, approve.APPLIED_NOTE):
            self.assertIn(text, words)

    def test_the_sprint_and_page_words_use_no_listed_word(self):
        flagged = [t for t in sprint_page_words() if owner_words.found(blank_fields(t))]
        self.assertEqual(flagged, [])

    def test_the_completed_lines_are_among_the_scanned_words(self):
        scanned = sprint_page_words()
        for text in (sprints.closing_text(1, 1, 1), engine_runs.line_text(engine_state("verifying")),
                     answer.LOOK_RECORDING.format(head="aaaaaaa", issue=7),
                     deliveries.run_summary([deliveries.IssueStage(n, s) for n, s in enumerate(deliveries.STAGES, 1)],
                                            "moved just now")):
            self.assertIn(text, scanned)

    def test_each_shown_stage_word_uses_no_listed_word(self):
        for stage in sprints.REPORT_STAGES + sprints.CLOSING_STAGES + deliveries.STAGES:
            with self.subTest(stage=stage):
                self.assertEqual(owner_words.found(view.CLOSING_OUTCOME_TEXT.get(stage, deliveries.stage_words(stage))), [])
        self.assertEqual(deliveries.stage_words("verifying"), "testing")
        self.assertEqual(deliveries.stage_words("landing"), "going in")

    def test_a_run_line_and_a_delivery_summary_show_the_stage_in_plain_words(self):
        self.assertEqual(deliveries.run_summary([deliveries.IssueStage(1, "landing")], "quiet for 45 min"),
                         "1 issue in delivery: 1 going in, quiet for 45 min")
        self.assertEqual(engine_runs.line_text(engine_state("verifying")), "testing, moving")
        self.assertEqual(engine_runs.line_text(engine_state("landing")), "going in, moving")

    def test_the_stage_values_on_the_wire_are_unchanged(self):
        self.assertEqual((deliveries.VERIFYING, deliveries.LANDING, sprints.LANDED), ("verifying", "landing", "landed"))
        self.assertEqual(deliveries.stage_text(deliveries.IssueStage(12, "verifying")), "testing")
        entry = engine_runs.engine_entry(engine_state("verifying"), None)
        self.assertEqual((entry["stage"], entry["stage_text"]), ("verifying", "testing"))

    def test_blank_fields_puts_a_number_in_each_format_field(self):
        self.assertEqual(blank_fields("{commit} at ${tokens}"), "1 at 1")
        self.assertEqual(owner_words.found(blank_fields("{commit} at ${tokens}")), [])
        self.assertNotEqual(owner_words.found("{commit} at ${tokens}"), [])
        self.assertEqual(words(blank_fields("on issue #{issue}.")), ["issue #1"])

    def test_prose_keeps_only_texts_with_whitespace(self):
        self.assertEqual(prose(["commit", "the adoption commit", "adopt.commit.failed"]), ["the adoption commit"])
