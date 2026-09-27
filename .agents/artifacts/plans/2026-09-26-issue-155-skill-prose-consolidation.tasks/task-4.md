# Task 4: Guard leaf clauses against copies outside enrolled regions

**Files:**
- Test: `T/test_dispatch_contracts.py`

**Interfaces:**
- Consumes (existing, in `T/test_dispatch_contracts.py`): `CONTRACTS`,
  `CARRIERS` (each `Carrier` has `relative`, `tree`, `kind`, `anchor`),
  `_rendered_region(carrier, text)`, which raises `RegionError` when a region is
  missing or ambiguous, and `_clause_pattern(clause)`, the wrapping-tolerant
  matcher. Also `SOURCE_TREES` and `REPO_ROOT` from `skill_tree_support`, where
  `REPO_ROOT` joins the existing import list.
- Produces: `AGENT_DEFINITIONS` (`REPO_ROOT / "home/common/claude-code/agents"`),
  `GLOBAL_GUIDANCE` (`REPO_ROOT / "home/common/agent-guidance/AGENTS.md"`), and
  two functions. `guarded_documents() -> dict[str, str]` maps label to text.
  `stray_copies(documents) -> list[str]` returns `"<label>: <contract id>"`
  strings. The new `StrayCopyGuardTest` exercises both.

**Invariants:**
- Labels: `<tree key>:<skill>/<file>` for source-tree documents, with tree key
  `shared` or `claude-only` exactly as in `SOURCE_TREES`. `agents/<name>.md` for
  agent definitions. `agent-guidance/AGENTS.md` for the global guidance file. A
  carrier's label is `f"{carrier.tree}:{carrier.relative}"`.
- `guarded_documents()` excludes every path with an `evals` component. It covers
  both source trees, every `*.md` in `AGENT_DEFINITIONS` and `GLOBAL_GUIDANCE`
  (D3, D21).
- A clause is stray when its wrapping-tolerant match count in the whole document
  exceeds its count inside the carrier's rendered region. For a non-carrier, the
  region is empty. A duplicate inside a region is not stray: the existing
  exactly-once check owns that.
- No carrier, region, clause text or `CONTRACTS` entry changes. The live guard
  passes at the start commit once the helpers exist. Its failing observation is
  the missing helpers (Step 2) and the mutation test's expectations.

- [ ] **Step 1: Write the failing test**

Add to `T/test_dispatch_contracts.py`, directly before
`class SourceTreeContractsTest`:

```python
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
```

The four mutations are a non-carrier, a fence carrier with the clause above its
fence, a section carrier with the clause after `## Notes` (outside its
`## Dispatch, phase-budget and attempt-budget rules` section), and the global
guidance.

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py -k StrayCopyGuardTest`
Expected: FAILED (errors=3), each `NameError: name 'guarded_documents' is not defined`.

- [ ] **Step 3: Write the guard**

Add `REPO_ROOT,` to the `from skill_tree_support import (…)` list,
alphabetically between `INSTALLED_VIEWS` and `SHARED_TREE`. Then add, directly
above `StrayCopyGuardTest`:

```python
AGENT_DEFINITIONS = REPO_ROOT / "home/common/claude-code/agents"
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
    carriers = {f"{carrier.tree}:{carrier.relative}": carrier for carrier in CARRIERS}
    found = []
    for label in sorted(documents):
        text = documents[label]
        carrier = carriers.get(label)
        region = _rendered_region(carrier, text) if carrier is not None else ""
        for contract_id, clause in CONTRACTS.items():
            pattern = _clause_pattern(clause)
            if len(pattern.findall(text)) > len(pattern.findall(region)):
                found.append(f"{label}: {contract_id}")
    return found
```

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py`
Expected: OK. Skips occur only in `InstalledTreeContractsTest`, whose installed
home is unset.

Mutation spot check. Temporarily change the `>` in `stray_copies` to `>=` and
rerun `-k StrayCopyGuardTest`. Expected: FAIL in
`test_no_clause_occurs_outside_an_enrolled_region`. Then restore `>`, rerun, and
expect OK.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_dispatch_contracts.py
git commit -m "test(skills): refuse leaf-clause copies outside enrolled carrier regions (#155)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Decision IDs: D3, D4, D21.
