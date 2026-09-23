# Task 1: Fence carriers and the dispatch-contract module

Decisions: D2–D6, D9–D12, D14, D15. Work from the worktree root; every path
below is repo-relative. `SK` = `home/common/agent-skills/skills`.

**Files:**
- Create: `home/common/agent-skills/tests/test_dispatch_contracts.py`
- Modify: `justfile` (register the module in `agent-workflow-tests`)
- Modify: `SK/sdd/implementer-prompt.md`, `SK/sdd/task-reviewer-prompt.md`,
  `SK/sdd/re-review-prompt.md`, `SK/sdd/correctness-reviewer-prompt.md`,
  `SK/sdd/conformance-reviewer-prompt.md`, `SK/from-issue/ship-handoff.md`
- Test: `home/common/agent-skills/tests/test_dispatch_contracts.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (Tasks 2 and 3 extend these by exact name): `REPO_ROOT`,
  `SHARED_TREE`, `CLAUDE_ONLY_TREE`, `SOURCE_TREES: dict[str, Path]` (keys
  `"shared"`, `"claude-only"`), `CONTRACTS: dict[str, str]` (keys
  `"launch-by-type"`, `"read-before-write"`), frozen dataclass
  `Carrier(relative: str, tree: str, kind: str, anchor: str = "")`,
  `CARRIERS: tuple[Carrier, ...]`, `class RegionError(ValueError)`,
  `_RENDERERS: dict[str, Callable[[Carrier, str], str]]`,
  `missing_contracts(carrier, document_text) -> frozenset[str]`,
  `_clause_pattern(clause) -> re.Pattern`, `_source_path(carrier) -> Path`,
  `_live(carrier) -> str`, `REGION_BREAKERS: dict[str, tuple[(label, fn), ...]]`,
  test classes `SourceTreeContractsTest`, `CheckerMutationTest`,
  `EnrolmentGuardTest`.

**Invariants:**
- `missing_contracts` returns exactly the contract ids whose clause does not
  occur exactly once in the rendered region (D15); an unknown kind or a
  missing/ambiguous region raises `RegionError` (D6).
- A fence carrier's region is the single unlabeled fence body, narrowed to the
  lines after its first `prompt: |` line when it has one (D14).
- The single-unlabeled-fence documents under `SK/from-issue/` and `SK/sdd/`,
  minus `from-issue/SKILL.md`, equal the enrolled fence carriers (D11).
- Each template gains exactly one four-line paragraph and loses no line; the
  implementer's `Never deliver it via SendMessage` sentence keeps its words and
  place (D5).

- [ ] **Step 1: Write the failing test module**

Create `home/common/agent-skills/tests/test_dispatch_contracts.py` with exactly:

````python
"""Dispatch contracts: the two leaf-agent clauses every carrier must hold.

A carrier is skill-authored text that reaches a subagent's prompt. A clause
counts only inside the carrier's rendered region, the text the recipient
actually receives, and must occur there exactly once.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).parents[4]
SHARED_TREE = REPO_ROOT / "home/common/agent-skills/skills"
CLAUDE_ONLY_TREE = REPO_ROOT / "home/common/claude-code/skills"
SOURCE_TREES = {"shared": SHARED_TREE, "claude-only": CLAUDE_ONLY_TREE}

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


_RENDERERS = {"fence": _fence_region}


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
````

- [ ] **Step 2: Register the module**

In `justfile`'s `agent-workflow-tests` recipe, add the line
`    home/common/agent-skills/tests/test_dispatch_contracts.py \` directly after
`    home/common/agent-skills/tests/test_workflow_skill_contracts.py \`.

- [ ] **Step 3: Run the module and watch it fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -1`
Expected: `FAILED (failures=64)` — every source and mutation subtest for all six
carriers; `EnrolmentGuardTest` and `test_a_missing_or_ambiguous_region_fails_loud`
already pass (confirm with `-v 2>&1 | grep ' ok$'`: exactly those two).

- [ ] **Step 4: Recover the clause paragraphs (D12 — read-only source)**

Read the retained placements with
`git diff 95b6caf 3c9709ca -- home/common/agent-skills/skills/sdd home/common/agent-skills/skills/from-issue/ship-handoff.md`.
Do not reuse their position or the delivery/"Deliver … yourself" sentences (D5):
re-apply by hand as a separate paragraph. In each of the five sdd templates,
insert these four lines plus one blank line immediately before the line named,
so a blank line separates the paragraph from the text above and from the heading:

```
    Launch any subagent by type only, never by name: a subagent cannot spawn a
    named teammate, and a named launch returns an error instead of work. Read an
    existing file before writing to it: overwriting content you have not read
    destroys work you cannot see.
```

| File | Insert before (current line) |
|---|---|
| `SK/sdd/implementer-prompt.md` | `    ## Report Format` (l99) |
| `SK/sdd/task-reviewer-prompt.md` | `    ## Output Format` (l164) |
| `SK/sdd/re-review-prompt.md` | `    ## Output Format` (l84) |
| `SK/sdd/correctness-reviewer-prompt.md` | `    ## Output Format` (l89) |
| `SK/sdd/conformance-reviewer-prompt.md` | `    ## Output Format` (l84) |

In `SK/from-issue/ship-handoff.md` insert the same paragraph flush-left, plus
one blank line, before `Return exactly canonical JSON from …` (l49):

```
Launch any subagent by type only, never by name: a subagent cannot spawn a named
teammate, and a named launch returns an error instead of work. Read an existing
file before writing to it: overwriting content you have not read destroys work
you cannot see.
```

- [ ] **Step 5: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -3`
Expected: `Ran 9 tests` and `OK`.
Run: `just agent-workflow-tests 2>&1 | tail -3` — expected `OK` (a skip count is fine).
Run: `just agent-model-matrix 2>&1 | head -1` — expected `agent model matrix: valid`.
Run: `git diff --numstat -- home/common/agent-skills/skills` — expected six rows,
each `5	0`.

- [ ] **Step 6: Commit with provenance (D12)**

Stage exactly the eight Files above. Write the message to a
`mktemp "${TMPDIR:-/tmp}/commit-msg-XXXXXX"` file (never in the working tree),
commit with `git commit -F <file>`, then delete the file. Message:

```
fix(agent-skills): hold fenced dispatch templates to leaf-agent clauses

Add the launch-by-type and read-before-write clauses, as their own
paragraph before each output section, to the five sdd dispatch
templates and from-issue/ship-handoff.md, and hold them with the new
test_dispatch_contracts.py module, registered in agent-workflow-tests.

Recovered selectively from branch worktree-issue-99-skill-prose-fixes
(commit 3c9709ca, parent 95b6caf), re-applied by hand:
- LEAF_LAUNCH_CLAUSE text: verbatim, now CONTRACTS["launch-by-type"]
- READ_BEFORE_WRITE_CLAUSE text: "a file" became "an existing file",
  now CONTRACTS["read-before-write"]
- the clause paragraphs in the five sdd templates and ship-handoff.md:
  re-placed before the output section; the SendMessage delivery
  sentence and the reviewers' "Deliver ... yourself" sentence dropped
- DISPATCH_PROMPT_TEMPLATES, NON_TEMPLATE_SINGLE_FENCE_DOCS,
  unlabeled_fenced_blocks(), test_dispatch_prompt_templates_are_enrolled
  and test_dispatch_prompts_carry_the_leaf_agent_clauses: moved into
  test_dispatch_contracts.py, generalized over carriers, split per
  contract
Not recovered: LEAF_DELIVERY_CLAUSE, the bindings-config guards (#100),
the shell-form and worktrees hunks (#154), the ship-release and
GITHUB_TOKEN changes, and the retained spec and plan.

Recovered-From: 3c9709ca470bd473d49b39a611ca6cab258973db
```

The co-author and session trailer lines your harness prescribes follow
`Recovered-From:` directly, with no blank line, in that same final paragraph.

- [ ] **Step 7: Post-commit gates**

Run: `git log -1 --format='%(trailers:key=Recovered-From,valueonly)'`
Expected: `3c9709ca470bd473d49b39a611ca6cab258973db` (an empty line means the
trailer is not in the final trailer paragraph — amend the message).
Run the root's **AC4 exclusion gate** — expected `AC4 exclusion gate: pass`.
Run: `git status --porcelain` — expected empty.
