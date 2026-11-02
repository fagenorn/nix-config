# Task 3: The Interim child results owner rule

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (dispatch rules section and suspension procedure)
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md` (`## Phases 2–4 run as subagents`)
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md` (`### 2. Handle the report`)
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (`## Phase 5 — Review the PR`)
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 2 may already have edited the from-issue, sdd and AUTO.md leaf-clause lines; leave those lines alone.
- Produces: the bold lead `**Interim child results.**`, which Task 4's dispatcher text does not cite but reviewers will search for.

**Invariants:**
- The paragraph below appears exactly once in each of the three skills and the copies are identical after whitespace normalization (per D5).
- The worker stays registered under its existing id; only an undeliverable message leads to the Writing-workers stop-and-release route (per D5, D8).
- The pointers restate nothing: each names the paragraph and adds no rule of its own.
- Suspension semantics for usage limits, transport, human gates and deadlines are unchanged.
- No `from-issue/` or `sdd/` document gains the literal `run_in_background`.

- [ ] **Step 1: Write the failing tests**

Append to `test_workflow_skill_contracts.py`, after `ProgressMarkerContractsTest`:

```python
class InterimChildResultContractsTest(unittest.TestCase):
    """#261: an owner treats a child's interim return as still running."""

    HEAD = "**Interim child results.**"
    OWNERS = (FROM_ISSUE, SDD, SHIP_ISSUE)

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    @classmethod
    def paragraph(cls, path):
        text = path.read_text(encoding="utf-8")
        start = text.index(cls.HEAD)
        end = text.find("\n\n", start)
        return normalized(text[start:] if end < 0 else text[start:end]).strip()

    def test_each_owner_skill_carries_the_paragraph_once(self):
        for path in self.OWNERS:
            with self.subTest(path=path.parent.name):
                self.assertEqual(path.read_text(encoding="utf-8").count(self.HEAD), 1)

    def test_the_paragraph_copies_stay_identical(self):
        canonical = self.paragraph(FROM_ISSUE)
        for path in (SDD, SHIP_ISSUE):
            with self.subTest(path=path.parent.name):
                self.assertEqual(self.paragraph(path), canonical)

    def test_the_paragraph_states_the_rule_in_order(self):
        self.assert_ordered(
            self.paragraph(FROM_ISSUE), self.HEAD,
            "is not a completion: the child is still running.",
            "Re-engage that same child by its recorded agent identity",
            "and wait for that report.",
            "You may end your own turn while the re-engaged child is live",
            "Never answer an interim result with a text-only reply",
            "never suspend for it (it is not an `external` wait)",
            "never dispatch a replacement or stop the child.",
            "stays registered under its existing worker id",
            "so it registers nothing new.",
            "If the message cannot be delivered",
            "release `--event stopped`",
            "the one case that may lead to a fresh dispatch.",
            "Only the child's final hand-back counts as its result.")

    def test_each_copy_sits_in_its_owner_section(self):
        for path, start, end in (
            (FROM_ISSUE, "**Writing workers.**", "## Terminal return procedure"),
            (SDD, "### 2. Handle the report", "### 3. Review the task"),
            (SHIP_ISSUE, "## Phase 5 — Review the PR", "## Phase 6 — Wait for CI"),
        ):
            with self.subTest(path=path.parent.name):
                self.assert_ordered(self.read(path), start, self.HEAD, end)

    def test_the_suspension_and_auto_pointers_route_to_the_paragraph(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Suspension procedure",
            "an external wait (never a child's interim result; see "
            "**Interim child results**)",
            "A suspension parks the attempt")
        self.assert_ordered(
            self.read(AUTO), "## Phases 2–4 run as subagents", "**Skill exception.**",
            "A Phase 2–4 subagent's interim result follows `SKILL.md`'s "
            "**Interim child results** rule.",
            "### Design subagent — Phases 2 + 3")
```

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k Interim 2>&1 | tail -6`
Expected: FAIL — `substring not found` / count `0 != 1` for `**Interim child results.**`.

- [ ] **Step 3: Implement**

Insert this paragraph, hard-wrapped to the host document's width, as a paragraph of its own (per D5, D8):

> **Interim child results.** A child's return that the host marks interim — it stopped with background work of its own still running, or its result may be interim — is not a completion: the child is still running. Re-engage that same child by its recorded agent identity: message it to wait for its own job inside its turn and then return its final report, and wait for that report. You may end your own turn while the re-engaged child is live, because the host wakes you with its next notification; that is a child's work, not a command you started. Never answer an interim result with a text-only reply, never suspend for it (it is not an `external` wait), and never dispatch a replacement or stop the child. A registered lifecycle worker stays registered under its existing worker id: an interim result is not its `returned` event, and re-engagement is not a resume, so it registers nothing new. If the message cannot be delivered, the child is one you cannot wait for: follow from-issue's **Writing workers** route (task-stop, then release `--event stopped`), then this skill's ordinary handling of a lost child; that is the one case that may lead to a fresh dispatch. Only the child's final hand-back counts as its result.

Placement:
- `from-issue/SKILL.md`: directly after the **Writing workers** paragraph (which ends `leave recovery to the dispatcher.`), before **Artifact report boundary**.
- `sdd/SKILL.md`: in `### 2. Handle the report`, directly after the status bullet list (after the **BLOCKED** bullet), before `If the implementer asks questions`.
- `ship-issue/SKILL.md`: the last paragraph of `## Phase 5 — Review the PR`, after the paragraph starting `If the fix changes unrelated behavior`.

Pointers:
- `from-issue/SKILL.md` `## Suspension procedure`: `an external wait,` becomes `an external wait (never a child's interim result; see **Interim child results**),`.
- `from-issue/AUTO.md`: a new paragraph of its own after the **Skill exception.** paragraph, before `### Design subagent — Phases 2 + 3`: `A Phase 2–4 subagent's interim result follows `SKILL.md`'s **Interim child results** rule.`

Then run `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E '^profile|exceed' | head -40`; for each `profile <id> on <host>: hot <N> bytes exceed ceiling <M>` line set that ceiling to `<N>` and append once to that profile's `note`: `Ceiling raised for #261: from-issue, sdd and ship-issue carry the Interim child results rule (#155 D10).`

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_ship_release_contracts.py 2>&1 | tail -4`
Expected: `OK` (installed-tree tests skipped), including the five new tests that failed in Step 2.

- [ ] **Step 5: Commit**

Stage exactly the files listed above, then
`launch-commit <Lifecycle worker values> -- -m "feat(agent-skills): treat an interim child result as still running (#261)" -m "<trailers>"`.
