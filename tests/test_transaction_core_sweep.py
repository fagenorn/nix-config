"""Asserted sweep of the transaction core across four unlike project shapes (#204 D6, D17).

The prototype's autopilot printed where each (shape, scenario) cell landed; this table
asserts it against persisted history. Only the success row exists in this slice.

Run: just agent-workflow-tests
"""

import ast
import inspect
import io
import re
import tempfile
import tokenize
import unittest
from pathlib import Path

from agent_tools import transaction_core
from agent_tools.transaction_core import TransactionStore

from .transaction_core_shapes import SHAPES
from .transaction_core_sweep_support import SCENARIOS, drive

WITH_ACTIVATION = ("created", "awaiting_verification", "ready", "publishing", "published",
                   "activating", "proving", "succeeded")
WITHOUT_ACTIVATION = tuple(s for s in WITH_ACTIVATION if s != "activating")

# (shape, scenario) -> (final state, every state the persisted history passes through)
SWEEP = {
    ("platform", "success"): ("succeeded", WITH_ACTIVATION),
    ("product", "success"): ("succeeded", WITH_ACTIVATION),
    ("daemon", "success"): ("succeeded", WITH_ACTIVATION),
    ("library", "success"): ("succeeded", WITHOUT_ACTIVATION),
}


def states_passed(transaction):
    return ("created",) + tuple(event["to"] for event in transaction.events[1:])


class SweepTableTest(unittest.TestCase):
    def test_the_table_covers_every_shape_for_every_ported_scenario(self):
        self.assertEqual(set(SWEEP), {(shape, scenario) for shape in SHAPES
                                      for scenario in SCENARIOS})

    def test_every_cell_lands_where_the_table_says(self):
        for (shape, scenario), (final, path) in SWEEP.items():
            with self.subTest(shape=shape, scenario=scenario), \
                    tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                transaction_id = drive(TransactionStore(root), shape, scenario)
                persisted = TransactionStore(root).load(transaction_id)
                self.assertEqual(persisted.creation_key, f"{shape}:{scenario}")
                self.assertEqual(persisted.state, final)
                self.assertEqual(states_passed(persisted), path)
                self.assertEqual({e["external_state"] for e in persisted.events[1:]},
                                 {"known"})

    def test_recreating_a_driven_cell_returns_its_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TransactionStore(Path(tmp))
            first = drive(store, "library", "success")
            subject = dict(store.load(first).subject)
            again = store.create("library:success", subject)
            self.assertEqual(again.transaction_id, first)
            self.assertEqual(len(again.events), len(store.load(first).events))


PROJECT_NAMES = frozenset({"nix", "nixos", "darwin", "fagenorn", "palmier", "nodo", "argus"})
PROVIDER_NAMES = frozenset({
    "github", "gitlab", "gh", "git", "ghcr", "docker", "oci", "railway", "launchd",
    "launchctl", "plist", "homebrew", "brew", "cachix", "sops", "anthropic", "claude",
    "codex"})
PROVIDER_VERBS = frozenset({
    "push", "merge", "tag", "deploy", "switch", "restart", "rebuild", "upload", "rebase",
    "checkout"})
FORBIDDEN_WORDS = PROJECT_NAMES | PROVIDER_NAMES | PROVIDER_VERBS
_NOT_CODE = frozenset({tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                       tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER})


def _docstring_starts(source):
    starts = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                starts.add((first.value.lineno, first.value.col_offset))
    return starts


def neutrality_findings(source):
    """Every forbidden whole word in `source`'s code, comments and docstrings excluded."""
    docstrings = _docstring_starts(source)
    findings = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in _NOT_CODE:
            continue
        if token.type == tokenize.STRING and token.start in docstrings:
            continue
        text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", token.string)
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        for word in re.split(r"[^0-9a-z]+", text.lower()):
            if word in FORBIDDEN_WORDS:
                findings.append((token.start[0], word))
    return findings


class NeutralityTest(unittest.TestCase):
    def setUp(self):
        self.source = inspect.getsource(transaction_core)

    def test_the_shipped_module_names_no_project_provider_or_provider_verb(self):
        self.assertEqual(neutrality_findings(self.source), [])

    def test_a_provider_verb_planted_in_code_is_found(self):
        planted = self.source + "\n\ndef deploy_everything():\n    return None\n"
        self.assertEqual([word for _, word in neutrality_findings(planted)], ["deploy"])

    def test_the_same_word_in_a_comment_or_docstring_is_not_code(self):
        for planted in ("\n# deploy the candidate\n",
                        '\n\ndef neutral():\n    """Deploy nothing."""\n    return None\n'):
            with self.subTest(planted=planted):
                self.assertEqual(neutrality_findings(self.source + planted), [])

    def test_matching_is_by_whole_word_and_covers_string_literals(self):
        self.assertEqual(neutrality_findings("associated = 'pushed'\n"), [])
        self.assertEqual(neutrality_findings("where = 'git-tag'\n"), [(1, "git"), (1, "tag")])

    def test_camel_case_identifiers_are_split_on_case_boundaries(self):
        planted = ("class DeployRefused(Exception):\n    pass\n\n"
                   "x = GitPush\ny = HTTPServerRebase\n")
        self.assertEqual(neutrality_findings(planted),
                         [(1, "deploy"), (4, "git"), (4, "push"), (5, "rebase")])
        self.assertEqual(neutrality_findings("Pushed = Associated\n"), [])


if __name__ == "__main__":
    unittest.main()
