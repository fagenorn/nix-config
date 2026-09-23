"""Dispatch contracts: the two leaf-agent clauses every carrier must hold.

A carrier is skill-authored text that reaches a subagent's prompt. A clause
counts only inside the carrier's rendered region, the text the recipient
actually receives, and must occur there exactly once.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).parents[4]
SHARED_TREE = REPO_ROOT / "home/common/agent-skills/skills"
CLAUDE_ONLY_TREE = REPO_ROOT / "home/common/claude-code/skills"
SOURCE_TREES = {"shared": SHARED_TREE, "claude-only": CLAUDE_ONLY_TREE}

# Any directory laid out like the home home-manager populates: the built
# home-manager-files output, or $HOME after a switch.
INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"
INSTALLED_RECIPE = "just agent-installed-skill-tests"
# (view, skill directory under the installed home, source trees it publishes)
INSTALLED_VIEWS = (
    ("claude", ".claude/skills", frozenset({"shared", "claude-only"})),
    ("codex", ".agents/skills", frozenset({"shared"})),
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
}


@dataclass(frozen=True)
class Carrier:
    relative: str  # "<skill>/<file>" inside its skill tree
    tree: str  # a SOURCE_TREES key
    kind: str  # a _RENDERERS key
    anchor: str = ""  # the line a non-fence region is located by


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
)

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


_RENDERERS = {
    "fence": _fence_region,
    "blockquote": _blockquote_region,
    "section": _section_region,
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
        for contract_id, clause in CONTRACTS.items()
        if region.count(clause) != 1
    )


def _clause_pattern(clause):
    """Match a clause as a carrier wraps it: any line break, indentation or
    quote marker between two words."""
    words = (re.escape(word) for word in clause.split(" "))
    return re.compile(r"\s+(?:>\s*)?".join(words))


def _source_path(carrier):
    return SOURCE_TREES[carrier.tree] / carrier.relative


def _live(carrier):
    return _source_path(carrier).read_text(encoding="utf-8")


class SourceTreeContractsTest(unittest.TestCase):
    def assert_contract_held(self, contract_id):
        for carrier in CARRIERS:
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


class InstalledTreeContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get(INSTALLED_HOME_ENV)
        if root is None:
            raise unittest.SkipTest(
                f"{INSTALLED_HOME_ENV} is unset; run `{INSTALLED_RECIPE}` to "
                "check the skill trees the Nix build installs"
            )
        cls.root = Path(root)

    def assert_contract_installed(self, contract_id):
        self.assertTrue(
            self.root.is_absolute() and self.root.is_dir(),
            f"{INSTALLED_HOME_ENV}={str(self.root)!r} is not an absolute directory",
        )
        for view, skills_dir, trees in INSTALLED_VIEWS:
            base = self.root / skills_dir
            if not base.is_dir():
                with self.subTest(view=view):
                    self.fail(f"the {view} view is missing: {base}")
                continue
            for carrier in CARRIERS:
                if carrier.tree not in trees:
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
            for contract_id in CONTRACTS:
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
            for contract_id in CONTRACTS:
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


if __name__ == "__main__":
    unittest.main()
