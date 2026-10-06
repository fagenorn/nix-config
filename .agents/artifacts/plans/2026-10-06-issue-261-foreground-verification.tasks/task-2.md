# Task 2: The `own-commands` leaf clause in every carrier and agent definition

**Files:**
- Test: `home/common/agent-skills/tests/test_dispatch_contracts.py`
- Modify (shared tree `home/common/agent-skills/skills/`): `sdd/implementer-prompt.md`, `sdd/task-reviewer-prompt.md`, `sdd/re-review-prompt.md`, `sdd/correctness-reviewer-prompt.md`, `sdd/conformance-reviewer-prompt.md`, `from-issue/ship-handoff.md`, `from-issue/SKILL.md`, `from-issue/AUTO.md`, `sdd/SKILL.md`
- Modify (Claude-only tree): `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/claude-code/agents/{implementer,mechanic,reviewer,reviewer-lite}.md`
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings only)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `CONTRACTS["own-commands"]` in `test_dispatch_contracts.py`; `Carrier.contracts` (tuple of clause ids) and `Carrier.label`; region kind `"body"`; `CARRIER_ROOTS`. Task 3 and Task 4 do not touch this file.

**Invariants:**
- The clause text is the Global Constraints string, held once in `CONTRACTS` and repeated verbatim (whitespace-normalized) in each carrier (per D3).
- Each of the nine skill carriers holds all three clauses exactly once in its rendered region; each agent definition holds only `own-commands`, exactly once, in its body (per D4, D11).
- A clause a carrier does not declare, anywhere in that document, is a stray copy (per D11).
- Agent carriers are skipped by the installed-tree test because `"agents"` is in no `INSTALLED_VIEWS` tree set (per D11).
- The clause never names a tool or the literal `run_in_background` (per D3).

- [ ] **Step 1: Write the failing tests**

Edit `test_dispatch_contracts.py` as follows.

1. Docstring first line: `"""Dispatch contracts: the leaf-agent clauses every carrier must hold.`
2. Add to `CONTRACTS`, after `read-before-write`:

```python
    "own-commands": (
        "Run each long command, every verification command included, in the "
        "foreground with an explicit timeout above its expected duration. If "
        "the host moves one to the background anyway, wait for it within the "
        "same turn: never end your turn while a command you started is still "
        "running."
    ),
```

3. Move `AGENT_DEFINITIONS = REPO_ROOT / "home/common/claude-code/agents"` above `Carrier`, then add `CARRIER_ROOTS = {**SOURCE_TREES, "agents": AGENT_DEFINITIONS}`. Replace `Carrier` with:

```python
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
```

4. Append to `CARRIERS`:

```python
    Carrier("implementer.md", "agents", "body", contracts=AGENT_CLAUSES),
    Carrier("mechanic.md", "agents", "body", contracts=AGENT_CLAUSES),
    Carrier("reviewer.md", "agents", "body", contracts=AGENT_CLAUSES),
    Carrier("reviewer-lite.md", "agents", "body", contracts=AGENT_CLAUSES),
```

5. Add the renderer and register it as `"body": _body_region` in `_RENDERERS`:

```python
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
```

6. `missing_contracts` checks only declared clauses:

```python
    return frozenset(
        contract_id
        for contract_id in carrier.contracts
        if region.count(CONTRACTS[contract_id]) != 1
    )
```

7. `_source_path` reads `CARRIER_ROOTS[carrier.tree] / carrier.relative`. In `stray_copies`, key carriers by `carrier.label`, and count a clause inside the region only when the carrier declares it:

```python
    carriers = {carrier.label: carrier for carrier in CARRIERS}
    ...
        for contract_id, clause in CONTRACTS.items():
            pattern = _clause_pattern(clause)
            held = region if carrier is not None and contract_id in carrier.contracts else ""
            if len(pattern.findall(text)) > len(pattern.findall(held)):
                found.append(f"{label}: {contract_id}")
```

8. Every loop over `CONTRACTS` per carrier becomes a loop over `carrier.contracts`: `CheckerMutationTest.cases`, `test_relocating_a_clause_into_the_dispatch_header_misses_exactly_that_contract`, `SourceTreeContractsTest.assert_contract_held` and `InstalledTreeContractsTest.assert_contract_installed` (skip a carrier whose `contracts` lacks the id).
9. Add a helper and a `"body"` entry to `REGION_BREAKERS`:

```python
def _without_frontmatter_close(carrier, text):
    lines = text.splitlines()
    close = [index for index, line in enumerate(lines) if line == "---"][1]
    return "\n".join(lines[:close] + lines[close + 1:])

# in REGION_BREAKERS
    "body": (
        ("the frontmatter's closing line removed", _without_frontmatter_close),
        ("no frontmatter at all",
         lambda carrier, text: "\n".join(
             line for line in text.splitlines() if line != "---")),
    ),
```

10. New tests:

```python
# in SourceTreeContractsTest
    def test_own_commands(self):
        self.assert_contract_held("own-commands")

# in InstalledTreeContractsTest
    def test_own_commands(self):
        self.assert_contract_installed("own-commands")

# in StrayCopyGuardTest
    def test_an_undeclared_clause_in_an_agent_definition_is_a_stray_copy(self):
        label = "agents/reviewer.md"
        documents = guarded_documents()
        documents[label] = documents[label] + "\n" + CONTRACTS["launch-by-type"] + "\n"
        self.assertEqual(stray_copies(documents), [f"{label}: launch-by-type"])


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
```

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -6`
Expected: FAIL — `test_own_commands` (source tree) reports every carrier, and the mutation tests fail to locate `own-commands` before mutating.

- [ ] **Step 3: Implement the carriers**

Insert the clause verbatim into each region, matching that document's wrapping and indentation (fence templates indent 4 spaces; blockquotes keep `> `):

- The five `sdd/*-prompt.md` templates and `from-issue/ship-handoff.md`: append the clause to the paragraph that already holds the two clauses, as its continuation.
- `orchestrate-issues/SKILL.md`: append it to the quoted paragraph holding the two clauses in the owner-launch blockquote; nothing else changes there.
- `from-issue/SKILL.md` and `sdd/SKILL.md`: in each **Leaf-agent clauses** paragraph replace `carries these two sentences verbatim` with `carries these three clauses verbatim` (the rest of the sentence is unchanged); append the clause to the `> ` quote line (per D10).
- `from-issue/AUTO.md`: `- the two sentences of `SKILL.md`'s **Leaf-agent clauses** rule, verbatim, as a paragraph of their own,` becomes `- the three clauses of `SKILL.md`'s **Leaf-agent clauses** rule, verbatim, as a paragraph of their own,` (per D10).
- Each agent definition: add the clause as its own paragraph in the body, immediately before the paragraph starting `The dispatch prompt owns`; frontmatter unchanged.

Then run `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E '^profile|exceed' | head -40` and, for each `profile <id> on <host>: hot <N> bytes exceed ceiling <M>` line, set that ceiling to `<N>` and append to that profile's `note` once: `Ceiling raised for #261: the leaf-agent clauses gained a third, own-commands, in their carriers and agent definitions (#155 D10).`

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -4`
Expected: `OK` (installed-tree tests skipped). Also `if grep -rn 'run_in_background' home/common/agent-skills/skills/from-issue home/common/agent-skills/skills/sdd; then exit 1; fi` prints nothing.

- [ ] **Step 5: Commit**

Stage exactly the files listed above, then
`launch-commit <Lifecycle worker values> -- -m "feat(agent-skills): add the own-commands leaf-agent clause (#261)" -m "<trailers>"`.
