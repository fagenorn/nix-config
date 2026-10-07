"""Dispatch contracts: the leaf-agent clauses every carrier must hold.

A carrier is skill-authored text that reaches a subagent's prompt. A clause
counts only inside the carrier's rendered region, the text the recipient
actually receives, and must occur there exactly once.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import unittest

import sys

# unittest loads suites by path, so the directory is not a package; the
# shared support module lives beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_tree_support import (  # noqa: E402
    INSTALLED_VIEWS,
    REPO_ROOT,
    SHARED_TREE,
    SOURCE_TREES,
    installed_home_or_skip,
    installed_root_error,
)

# The one authoritative home of each clause. Carriers repeat the text because a
# pasted template carries no link into the subagent's context; every copy is
# asserted against these constants, whitespace-normalized.
CONTRACTS = {
    "launch-by-type": (
        "Launch any subagent by type only, never by name: a subagent cannot "
        "spawn a named teammate, and a named launch returns an error instead "
        "of work."
    ),
    "read-before-write": (
        "Read an existing file before writing to it: overwriting content you "
        "have not read destroys work you cannot see."
    ),
    "own-commands": (
        "Run each long command, every verification command included, in the "
        "foreground with an explicit timeout above its expected duration. If "
        "the host moves one to the background anyway, wait for it within the "
        "same turn: never end your turn while a command you started is still "
        "running."
    ),
}


AGENT_DEFINITIONS = REPO_ROOT / "home/common/claude-code/agents"
CARRIER_ROOTS = {**SOURCE_TREES, "agents": AGENT_DEFINITIONS}


@dataclass(frozen=True)
class Carrier:
    relative: str  # "<skill>/<file>" in its skill tree, or "<name>.md" for an agent definition
    tree: str  # a CARRIER_ROOTS key
    kind: str  # a _RENDERERS key
    anchor: str = ""  # the line a non-fence region is located by
    contracts: tuple = tuple(CONTRACTS)  # the clause ids this carrier must hold

    @property
    def label(self):
        """The carrier's label in guarded_documents()."""
        if self.tree == "agents":
            return f"agents/{self.relative}"
        return f"{self.tree}:{self.relative}"


AGENT_CLAUSES = ("own-commands",)


CARRIERS = (
    Carrier("sdd/implementer-prompt.md", "shared", "fence"),
    Carrier("sdd/task-reviewer-prompt.md", "shared", "fence"),
    Carrier("sdd/re-review-prompt.md", "shared", "fence"),
    Carrier("sdd/correctness-reviewer-prompt.md", "shared", "fence"),
    Carrier("sdd/conformance-reviewer-prompt.md", "shared", "fence"),
    Carrier("from-issue/ship-handoff.md", "shared", "fence"),
    Carrier(
        "orchestrate-issues/SKILL.md", "claude-only", "blockquote",
        "launches the issue owner in a fresh context with this entire prompt:",
    ),
    Carrier(
        "from-issue/SKILL.md", "shared", "section",
        "## Dispatch, phase-budget and attempt-budget rules",
    ),
    Carrier("sdd/SKILL.md", "shared", "section", "## Agent tiers"),
    Carrier("implementer.md", "agents", "body", contracts=AGENT_CLAUSES),
    Carrier("mechanic.md", "agents", "body", contracts=AGENT_CLAUSES),
    Carrier("reviewer.md", "agents", "body", contracts=AGENT_CLAUSES),
    Carrier("reviewer-lite.md", "agents", "body", contracts=AGENT_CLAUSES),
)

# The remainder ship-owner prompt in ship-handoff.md forwards the leaf-agent
# clauses through a placeholder line rather than a copy (per D13).
REMAINDER_PLACEHOLDER = "<the three leaf-agent clauses of the ship-owner prompt above, verbatim>"
STALE_REMAINDER_WORDING = "two leaf-agent sentences"

# Documents under these skills whose body holds exactly one unlabeled fence are
# dispatch templates and must be enrolled as fence carriers, except the
# declared set: from-issue/SKILL.md's one fence is its `## The flow` diagram.
ENROLMENT_SKILLS = ("from-issue", "sdd")
NON_TEMPLATE_SINGLE_FENCE_DOCS = frozenset({"from-issue/SKILL.md"})


class RegionError(ValueError):
    """A carrier's rendered region is missing or ambiguous."""


def _normalized(text):
    return re.sub(r"\s+", " ", text)


def _unlabeled_fenced_blocks(text):
    blocks = []
    info = None
    body = []
    for line in text.splitlines():
        if line.startswith("```"):
            if info is None:
                info = line[3:].strip()
                body = []
            else:
                if info == "":
                    blocks.append("\n".join(body))
                info = None
            continue
        if info is not None:
            body.append(line)
    return blocks


def _fence_region(carrier, text):
    blocks = _unlabeled_fenced_blocks(text)
    if len(blocks) != 1:
        raise RegionError(
            f"{carrier.relative}: expected exactly one unlabeled fenced block, "
            f"found {len(blocks)}"
        )
    lines = blocks[0].split("\n")
    for index, line in enumerate(lines):
        # The lines above `prompt: |` are dispatch parameters, not prompt text.
        if line.strip() == "prompt: |":
            return "\n".join(lines[index + 1:])
    return blocks[0]


def _blockquote_region(carrier, text):
    lines = text.splitlines()
    anchors = [index for index, line in enumerate(lines) if carrier.anchor in line]
    if len(anchors) != 1:
        raise RegionError(
            f"{carrier.relative}: expected one anchor line, found {len(anchors)}"
        )
    index = anchors[0] + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    quoted = []
    while index < len(lines) and lines[index].startswith(">"):
        quoted.append(re.sub(r"^> ?", "", lines[index]))
        index += 1
    if not quoted:
        raise RegionError(
            f"{carrier.relative}: the anchor line is not followed by a quote block"
        )
    return "\n".join(quoted)


def _section_region(carrier, text):
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line == carrier.anchor]
    if len(starts) != 1:
        raise RegionError(
            f"{carrier.relative}: expected heading {carrier.anchor!r} once, "
            f"found {len(starts)}"
        )
    body = []
    for line in lines[starts[0] + 1:]:
        if re.match(r"#{1,2} ", line):
            break
        body.append(line)
    return "\n".join(body)


def _body_region(carrier, text):
    """An agent definition's body: everything after the frontmatter's closing
    line, the second line that is exactly `---`."""
    lines = text.splitlines()
    rules = [index for index, line in enumerate(lines) if line == "---"]
    if len(rules) < 2:
        raise RegionError(
            f"{carrier.relative}: expected a frontmatter block closed by a "
            f"second `---` line, found {len(rules)} `---` lines"
        )
    return "\n".join(lines[rules[1] + 1:])


_RENDERERS = {
    "fence": _fence_region,
    "blockquote": _blockquote_region,
    "section": _section_region,
    "body": _body_region,
}


def _rendered_region(carrier, text):
    renderer = _RENDERERS.get(carrier.kind)
    if renderer is None:
        raise RegionError(f"{carrier.relative}: unknown carrier kind {carrier.kind!r}")
    return renderer(carrier, text)


def missing_contracts(carrier, document_text):
    """Contract ids whose clause does not occur exactly once in the region."""
    region = _normalized(_rendered_region(carrier, document_text))
    return frozenset(
        contract_id
        for contract_id in carrier.contracts
        if region.count(CONTRACTS[contract_id]) != 1
    )


def _clause_pattern(clause):
    """Match a clause as a carrier wraps it: any line break, indentation or
    quote marker between two words."""
    words = (re.escape(word) for word in clause.split(" "))
    return re.compile(r"\s+(?:>\s*)?".join(words))


def _source_path(carrier):
    return CARRIER_ROOTS[carrier.tree] / carrier.relative


def _live(carrier):
    return _source_path(carrier).read_text(encoding="utf-8")


GLOBAL_GUIDANCE = REPO_ROOT / "home/common/agent-guidance/AGENTS.md"


def guarded_documents():
    """Label -> text of every document the stray-copy guard reads: each living
    `*.md` of both source trees outside `evals/` (labelled `<tree>:<skill>/<file>`),
    each Claude agent definition (`agents/<name>.md`) and the global guidance
    file (`agent-guidance/AGENTS.md`)."""
    documents = {}
    for tree, root in SOURCE_TREES.items():
        for path in sorted(root.rglob("*.md")):
            relative = path.relative_to(root)
            if "evals" not in relative.parts:
                documents[f"{tree}:{relative.as_posix()}"] = path.read_text(encoding="utf-8")
    for path in sorted(AGENT_DEFINITIONS.glob("*.md")):
        documents[f"agents/{path.name}"] = path.read_text(encoding="utf-8")
    documents["agent-guidance/AGENTS.md"] = GLOBAL_GUIDANCE.read_text(encoding="utf-8")
    return documents


def stray_copies(documents):
    """`<label>: <contract id>` for each clause that occurs in a document
    outside an enrolled carrier's rendered region, in label then contract order."""
    carriers = {carrier.label: carrier for carrier in CARRIERS}
    found = []
    for label in sorted(documents):
        text = documents[label]
        carrier = carriers.get(label)
        region = _rendered_region(carrier, text) if carrier is not None else ""
        for contract_id, clause in CONTRACTS.items():
            pattern = _clause_pattern(clause)
            held = region if carrier is not None and contract_id in carrier.contracts else ""
            if len(pattern.findall(text)) > len(pattern.findall(held)):
                found.append(f"{label}: {contract_id}")
    return found


class StrayCopyGuardTest(unittest.TestCase):
    def test_no_clause_occurs_outside_an_enrolled_region(self):
        self.assertEqual(stray_copies(guarded_documents()), [])

    def test_the_guard_reads_both_trees_the_agent_definitions_and_the_guidance(self):
        labels = set(guarded_documents())
        for label in ("shared:worktrees/SKILL.md", "claude-only:orchestrate-issues/SKILL.md",
                      "agents/reviewer.md", "agent-guidance/AGENTS.md"):
            self.assertIn(label, labels)
        self.assertFalse([label for label in labels if "/evals/" in label])

    def test_a_copy_outside_a_region_names_its_document(self):
        clause = CONTRACTS["launch-by-type"]
        for label, mutate in (
            ("shared:worktrees/SKILL.md", lambda text: text + "\n\n" + clause + "\n"),
            ("shared:sdd/implementer-prompt.md", lambda text: clause + "\n\n" + text),
            ("shared:from-issue/SKILL.md", lambda text: text + "\n\n" + clause + "\n"),
            ("agent-guidance/AGENTS.md", lambda text: text + "\n" + clause + "\n"),
        ):
            with self.subTest(document=label):
                documents = guarded_documents()
                documents[label] = mutate(documents[label])
                self.assertEqual(stray_copies(documents), [f"{label}: launch-by-type"])

    def test_an_undeclared_clause_in_an_agent_definition_is_a_stray_copy(self):
        label = "agents/reviewer.md"
        documents = guarded_documents()
        documents[label] = documents[label] + "\n" + CONTRACTS["launch-by-type"] + "\n"
        self.assertEqual(stray_copies(documents), [f"{label}: launch-by-type"])


class SourceTreeContractsTest(unittest.TestCase):
    def assert_contract_held(self, contract_id):
        for carrier in CARRIERS:
            if contract_id not in carrier.contracts:
                continue
            with self.subTest(carrier=carrier.relative):
                self.assertNotIn(
                    contract_id,
                    missing_contracts(carrier, _live(carrier)),
                    f"{carrier.relative}: the {contract_id} clause must occur "
                    "exactly once in the rendered region",
                )

    def test_launch_by_type(self):
        self.assert_contract_held("launch-by-type")

    def test_read_before_write(self):
        self.assert_contract_held("read-before-write")

    def test_own_commands(self):
        self.assert_contract_held("own-commands")


class InstalledTreeContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = installed_home_or_skip()

    def assert_contract_installed(self, contract_id):
        error = installed_root_error(self.root)
        self.assertIsNone(error, error)
        for view, skills_dir, trees in INSTALLED_VIEWS:
            base = self.root / skills_dir
            if not base.is_dir():
                with self.subTest(view=view):
                    self.fail(f"the {view} view is missing: {base}")
                continue
            for carrier in CARRIERS:
                if carrier.tree not in trees or contract_id not in carrier.contracts:
                    continue
                path = base / carrier.relative
                with self.subTest(view=view, carrier=carrier.relative):
                    self.assertTrue(path.is_file(), f"the {view} view lacks {path}")
                    self.assertNotIn(
                        contract_id,
                        missing_contracts(carrier, path.read_text(encoding="utf-8")),
                        f"{path}: the {contract_id} clause must occur exactly "
                        "once in the rendered region",
                    )

    def test_launch_by_type(self):
        self.assert_contract_installed("launch-by-type")

    def test_read_before_write(self):
        self.assert_contract_installed("read-before-write")

    def test_own_commands(self):
        self.assert_contract_installed("own-commands")


def _without_frontmatter_close(carrier, text):
    lines = text.splitlines()
    close = [index for index, line in enumerate(lines) if line == "---"][1]
    return "\n".join(lines[:close] + lines[close + 1:])


# Region breakages per carrier kind, each derived from the live text.
REGION_BREAKERS = {
    "fence": (
        ("a second unlabeled fence", lambda carrier, text: text + "\n```\nextra\n```\n"),
        (
            "no fence at all",
            lambda carrier, text: "\n".join(
                line for line in text.splitlines() if not line.startswith("```")
            ),
        ),
    ),
    "blockquote": (
        ("the anchor line removed", lambda carrier, text: text.replace(carrier.anchor, "")),
        ("the anchor line repeated", lambda carrier, text: text + "\n" + carrier.anchor + "\n"),
        ("the quote markers stripped", lambda carrier, text: re.sub(r"(?m)^> ?", "", text)),
    ),
    "section": (
        ("the heading removed", lambda carrier, text: text.replace(carrier.anchor + "\n", "", 1)),
        ("the heading repeated", lambda carrier, text: text + "\n" + carrier.anchor + "\n"),
    ),
    "body": (
        ("the frontmatter's closing line removed", _without_frontmatter_close),
        ("no frontmatter at all",
         lambda carrier, text: "\n".join(
             line for line in text.splitlines() if line != "---")),
    ),
}


class CheckerMutationTest(unittest.TestCase):
    def located(self, carrier, text, contract_id):
        matches = list(_clause_pattern(CONTRACTS[contract_id]).finditer(text))
        self.assertEqual(
            len(matches), 1,
            f"{carrier.relative}: expected the {contract_id} clause once in the "
            "document before mutating it",
        )
        return matches[0]

    def removed(self, carrier, text, contract_id):
        match = self.located(carrier, text, contract_id)
        return text[:match.start()] + text[match.end():]

    def cases(self):
        for carrier in CARRIERS:
            for contract_id in carrier.contracts:
                yield carrier, contract_id

    def test_unmodified_text_misses_nothing(self):
        for carrier in CARRIERS:
            with self.subTest(carrier=carrier.relative):
                self.assertEqual(missing_contracts(carrier, _live(carrier)), frozenset())

    def test_removing_a_clause_misses_exactly_that_contract(self):
        for carrier, contract_id in self.cases():
            with self.subTest(carrier=carrier.relative, contract=contract_id):
                mutated = self.removed(carrier, _live(carrier), contract_id)
                self.assertEqual(missing_contracts(carrier, mutated), {contract_id})

    def test_relocating_a_clause_outside_the_region_misses_exactly_that_contract(self):
        # The document's top precedes every region's fence, anchor or heading.
        for carrier, contract_id in self.cases():
            with self.subTest(carrier=carrier.relative, contract=contract_id):
                mutated = (CONTRACTS[contract_id] + "\n\n"
                           + self.removed(carrier, _live(carrier), contract_id))
                self.assertEqual(missing_contracts(carrier, mutated), {contract_id})

    def test_relocating_a_clause_into_the_dispatch_header_misses_exactly_that_contract(self):
        headed = [carrier for carrier in CARRIERS
                  if carrier.kind == "fence" and "prompt: |" in _live(carrier)]
        self.assertTrue(headed, "no fence carrier declares `prompt: |`")
        for carrier in headed:
            for contract_id in carrier.contracts:
                with self.subTest(carrier=carrier.relative, contract=contract_id):
                    text = self.removed(carrier, _live(carrier), contract_id)
                    line_start = text.rindex("\n", 0, text.index("prompt: |")) + 1
                    mutated = (text[:line_start] + "  " + CONTRACTS[contract_id]
                               + "\n" + text[line_start:])
                    self.assertEqual(missing_contracts(carrier, mutated), {contract_id})

    def test_duplicating_a_clause_inside_the_region_misses_exactly_that_contract(self):
        for carrier, contract_id in self.cases():
            with self.subTest(carrier=carrier.relative, contract=contract_id):
                text = _live(carrier)
                end = self.located(carrier, text, contract_id).end()
                mutated = text[:end] + " " + CONTRACTS[contract_id] + text[end:]
                self.assertEqual(missing_contracts(carrier, mutated), {contract_id})

    def test_a_missing_or_ambiguous_region_fails_loud(self):
        for carrier in CARRIERS:
            for label, breaker in REGION_BREAKERS[carrier.kind]:
                with self.subTest(carrier=carrier.relative, breakage=label):
                    with self.assertRaises(RegionError):
                        missing_contracts(carrier, breaker(carrier, _live(carrier)))


class CarrierDeclarationTest(unittest.TestCase):
    def test_every_agent_definition_is_an_own_commands_body_carrier(self):
        enrolled = {c.relative: c for c in CARRIERS if c.tree == "agents"}
        self.assertEqual(set(enrolled), {p.name for p in AGENT_DEFINITIONS.glob("*.md")})
        for carrier in enrolled.values():
            with self.subTest(carrier=carrier.relative):
                self.assertEqual((carrier.kind, carrier.contracts), ("body", AGENT_CLAUSES))

    def test_every_skill_carrier_holds_all_three_clauses(self):
        skill_carriers = [c for c in CARRIERS if c.tree != "agents"]
        self.assertEqual(len(skill_carriers), 9)
        for carrier in skill_carriers:
            with self.subTest(carrier=carrier.relative):
                self.assertEqual(carrier.contracts, tuple(CONTRACTS))
                self.assertEqual(len(carrier.contracts), 3)

    def test_the_remainder_prompt_placeholder_names_three_clauses(self):
        text = (SHARED_TREE / "from-issue/ship-handoff.md").read_text(encoding="utf-8")
        self.assertIn(REMAINDER_PLACEHOLDER, text)
        self.assertNotIn(STALE_REMAINDER_WORDING, text)


class EnrolmentGuardTest(unittest.TestCase):
    def test_every_single_fence_template_is_an_enrolled_fence_carrier(self):
        discovered = set()
        for skill in ENROLMENT_SKILLS:
            for path in sorted((SHARED_TREE / skill).glob("*.md")):
                relative = f"{skill}/{path.name}"
                if relative in NON_TEMPLATE_SINGLE_FENCE_DOCS:
                    continue
                if len(_unlabeled_fenced_blocks(path.read_text(encoding="utf-8"))) == 1:
                    discovered.add(relative)
        enrolled = {carrier.relative for carrier in CARRIERS if carrier.kind == "fence"}
        self.assertEqual(
            discovered, enrolled,
            "a single-unlabeled-fence document under from-issue/ or sdd/ is not "
            "an enrolled fence carrier, or an enrolled one stopped carrying "
            "exactly one unlabeled fence",
        )


# The dispatch-marker inventory across both skill source trees (#272 D12): a
# change that adds or retires a dispatch updates this count deliberately. #270
# added two (the Sonnet task-fix re-dispatch and the BLOCKED reasoning escalation).
MARKER_INVENTORY = 39
MARKER_LINE = re.compile(r"^<!-- agent-dispatch: id=([a-z0-9-]+) ", re.M)
CONFORMANCE_MARKER = ("<!-- agent-dispatch: id=sdd-final-conformance-review "
                      "role=conformance-reviewer model=opus effort=high -->")
CONFORMANCE_CALL = ('Agent(subagent_type="reviewer", model="opus", effort="high") '
                    "performs the first-pass whole-branch conformance review.")


class MarkerInventoryTest(unittest.TestCase):
    def markers(self):
        found = []
        for tree in SOURCE_TREES.values():
            for path in sorted(tree.rglob("*.md")):
                found += MARKER_LINE.findall(path.read_text(encoding="utf-8"))
        return found

    def test_the_marker_inventory_count_is_unchanged(self):
        markers = self.markers()
        self.assertEqual(len(markers), MARKER_INVENTORY)
        self.assertEqual(len(set(markers)), MARKER_INVENTORY)

    def test_the_final_conformance_marker_selects_opus_high(self):
        text = (SHARED_TREE / "sdd/conformance-reviewer-prompt.md").read_text(encoding="utf-8")
        markers = [line for line in text.splitlines()
                   if line.startswith("<!-- agent-dispatch:")]
        self.assertEqual(markers, [CONFORMANCE_MARKER])
        self.assertIn(CONFORMANCE_CALL, text)


if __name__ == "__main__":
    unittest.main()
