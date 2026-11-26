"""The console's runtime copy of the owner glossary matches the docs table and flags what it should.

Run: just agent-workflow-tests
"""
import ast
import json
import re
import unittest
from pathlib import Path

from agent_tools.console import owner_words, view
from agent_tools.delivery.routing import index_table

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES = REPO_ROOT / "tests/fixtures/console/owner-words-cases.json"
PAGE = REPO_ROOT / "python/agent_tools/console/page.html"
PAGE_TEXT_MODULES = ("view", "sprints", "engine_runs", "guest", "capacity")
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


def console_text_words():
    root = REPO_ROOT / "python/agent_tools/console"
    return [w for m in PAGE_TEXT_MODULES for w in text_constants((root / (m + ".py")).read_text(encoding="utf-8"))]


def G(word):
    return dict(owner_words.GLOSSARY)[word]


class GlossaryTest(unittest.TestCase):
    def test_a_word_used_without_its_gloss_is_flagged_with_its_gloss(self):
        self.assertEqual(owner_words.unglossed("waiting on the land lock"), [("land lock", G("land lock"))])

    def test_the_glossary_copy_matches_the_docs_table(self):
        text = (REPO_ROOT / "docs/guides/owner-words.md").read_text(encoding="utf-8")
        rows = index_table(text)[1:]
        self.assertEqual([tuple(r) for r in rows], list(owner_words.GLOSSARY))
        self.assertEqual(len(owner_words.GLOSSARY), 12)

    def test_text_with_no_glossary_word_flags_nothing(self):
        self.assertEqual(owner_words.unglossed("two parts of the job are being built"), [])

    def test_a_word_matches_in_any_case(self):
        self.assertEqual(owner_words.unglossed("Waiting on the Land Lock"), [("land lock", G("land lock"))])
        self.assertEqual(owner_words.unglossed("the ci failed"), [("CI", G("CI"))])

    def test_a_word_inside_a_longer_word_is_not_flagged(self):
        self.assertEqual(owner_words.unglossed("a guardrail, a reclaim, decide, looked, held2"), [])

    def test_a_non_ascii_letter_or_space_never_folds_or_separates(self):
        self.assertEqual(owner_words.unglossed("İguard refused it"), [("guard", G("guard"))])
        self.assertEqual(owner_words.unglossed("looK at it"), [])
        self.assertEqual(owner_words.unglossed("the land lock"), [])

    def test_a_two_word_entry_matches_across_any_whitespace(self):
        self.assertEqual(owner_words.unglossed("the land \t\n lock"), [("land lock", G("land lock"))])

    def test_an_inflected_form_is_not_flagged(self):
        self.assertEqual(owner_words.unglossed("two slices, three pull requests, it looks fine, verified"), [])

    def test_a_word_glossed_in_the_same_text_is_not_flagged(self):
        text = "the land lock (" + G("land lock").upper().replace(" ", " \t ") + ")"
        self.assertEqual(owner_words.unglossed(text), [])
        self.assertEqual(
            owner_words.unglossed("the land lock and the rerun (" + G("land lock") + ")"),
            [("rerun", G("rerun"))],
        )

    def test_flags_come_in_glossary_order_once_each(self):
        self.assertEqual(
            owner_words.unglossed("rerun it, the pull request is held, rerun again"),
            [("held", G("held")), ("rerun", G("rerun")), ("pull request", G("pull request"))],
        )

    def test_unglossed_in_counts_a_word_once_across_texts(self):
        self.assertEqual(
            owner_words.unglossed_in(["rerun now", "the guard said no", "rerun later"]),
            [("guard", G("guard")), ("rerun", G("rerun"))],
        )
        self.assertEqual(owner_words.unglossed_in([]), [])

    def test_entries_is_the_wire_form_in_glossary_order(self):
        self.assertEqual(owner_words.entries(), [{"word": w, "gloss": g} for w, g in owner_words.GLOSSARY])

    def test_the_shared_cases_flag_what_the_case_file_says(self):
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 9)
        for case in cases:
            with self.subTest(text=case["text"]):
                self.assertEqual([w for w, _ in owner_words.unglossed(case["text"])], case["flagged"])

class ViewGlossaryTest(unittest.TestCase):
    def test_the_view_carries_the_glossary_in_order(self):
        self.assertEqual(view.derive_view([])["glossary"], owner_words.entries())


class FixedWordsTest(unittest.TestCase):
    def test_the_pages_fixed_words_use_no_unglossed_glossary_word(self):
        flagged = [t for t in page_words(PAGE.read_text(encoding="utf-8")) + console_text_words() if owner_words.unglossed(t)]
        self.assertEqual(flagged, [])

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
        from agent_tools.console import guest, sprints
        words = console_text_words()
        for text in (sprints.NOW_LOCK_TEXT, view.HEADLINE, guest.SHARING_OFF_TEXT):
            self.assertIn(text, words)
