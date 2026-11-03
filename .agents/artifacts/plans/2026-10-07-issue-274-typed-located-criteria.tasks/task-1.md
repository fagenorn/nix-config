# Task 1: Type and locate the to-issues criterion line

Per D1, D9. Measures issue #274 AC1.

**Files:**
- Modify: `home/common/agent-skills/skills/to-issues/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (append one new class)

**Interfaces:**
- Consumes: the test module's existing `REPO_ROOT` and `normalized(text)` (collapses every whitespace run to one space).
- Produces: the criterion-line shape `- [ ] [<kind>] <observable outcome> — measured: <where>`, `<kind>` ∈ {`code`, `evidence`, `human`}, which Task 3's fixture and helper follow.

**Invariants:**
- Every `- ` line inside the `<issue-template>`'s `## Acceptance criteria` section matches `^- \[ \] \[(code|evidence|human)\] \S.* — measured: \S.*$`, and the three lines together show all three kinds.
- The falsifiability rule stays one paragraph starting `**Every acceptance criterion must be falsifiable.**`; the new sentence is appended to it.
- No other section of `to-issues/SKILL.md` changes.

- [ ] **Step 1: Write the failing test**

Append immediately before `if __name__ == "__main__":` in `test_workflow_skill_contracts.py`:

```python
class ToIssuesCriterionLineContractsTest(unittest.TestCase):
    """#274 AC1: every to-issues criterion line is typed and located (D1, D9)."""

    TO_ISSUES = REPO_ROOT / "home/common/agent-skills/skills/to-issues/SKILL.md"
    LINE_RE = re.compile(
        r"^- \[ \] \[(code|evidence|human)\] \S.* — measured: \S.*$")

    @classmethod
    def setUpClass(cls):
        cls.text = cls.TO_ISSUES.read_text(encoding="utf-8")
        template = cls.text[cls.text.index("<issue-template>"):
                            cls.text.index("</issue-template>")]
        section = template[template.index("## Acceptance criteria\n"):]
        section = section[:section.index("\n## ", 1)]
        cls.criterion_lines = [
            line for line in section.splitlines() if line.startswith("- ")]

    def test_every_template_criterion_line_carries_a_kind_and_a_measured_clause(self):
        self.assertGreaterEqual(len(self.criterion_lines), 3)
        for line in self.criterion_lines:
            with self.subTest(line=line):
                self.assertRegex(line, self.LINE_RE)
        kinds = {match.group(1) for match in map(self.LINE_RE.match, self.criterion_lines)
                 if match}
        self.assertEqual(kinds, {"code", "evidence", "human"})

    def test_the_shape_kinds_and_preference_rule_are_stated(self):
        text = normalized(self.text)
        for phrase in (
            "`- [ ] [code|evidence|human] <observable outcome> — measured: <where>`",
            "`code` — a check any reviewer reproduces at the head",
            "`evidence` — a measurement taken outside the gating suite",
            "`human` — needs a person's judgment or an environment the agent cannot control",
            "Prefer `code`, then `evidence`; use `human` only when no agent can "
            "produce the observation.",
            "no file paths outside a `measured:` clause",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_the_falsifiability_rule_extends_to_the_measured_clause(self):
        paragraph = next(
            line for line in self.text.splitlines()
            if line.startswith("**Every acceptance criterion must be falsifiable.**"))
        self.assertIn(
            "The `measured:` clause must name an observation that fails at the base "
            "commit, and an evidence threshold is a literal number or string, never "
            "\"faster\" or \"reasonable\".",
            paragraph,
        )
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ToIssuesCriterionLine 2>&1 | tail -5`
Expected: FAILED (failures=3) — the template lines read `- [ ] Criterion 1`, and none of the phrases exist yet.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/skills/to-issues/SKILL.md`:

1. Inside `<issue-template>`, replace the three `- [ ] Criterion N` lines under `## Acceptance criteria` with exactly:

```markdown
- [ ] [code] <observable outcome> — measured: <the test, check or CI job that observes it>
- [ ] [evidence] <observable outcome> — measured: <command>, <conditions it runs under>, <literal threshold>
- [ ] [human] <observable outcome> — measured: <who judges, in what environment>
```

2. Directly after `</issue-template>` and its following blank line, before the `**The body is the contract; the discussion is context.**` paragraph, insert this block (hard-wrap prose at ~100 columns like its neighbours; the tests read whitespace-normalized text):

```markdown
**Every acceptance criterion is typed and located.** Write each one as
`- [ ] [code|evidence|human] <observable outcome> — measured: <where>`, with exactly one kind from
that closed set:

- `code` — a check any reviewer reproduces at the head: a test, the build or a CI job. `measured:`
  names that test, check or CI job.
- `evidence` — a measurement taken outside the gating suite. `measured:` names the command, the
  conditions it runs under and a literal threshold, such as `≤ 90 s per module, serial, idle mbp`.
- `human` — needs a person's judgment or an environment the agent cannot control. `measured:` names
  who judges and in what environment.

Prefer `code`, then `evidence`; use `human` only when no agent can produce the observation. The
`measured:` clause is the one place the body names a test, file or command, because that name is
what a grader reruns.
```

3. In the `**The body is the contract; the discussion is context.**` paragraph, change ``no file paths, no line numbers`` to ``no file paths outside a `measured:` clause, no line numbers`` (per D9), re-wrapping the paragraph if needed.

4. Append to the end of the `**Every acceptance criterion must be falsifiable.**` paragraph (same physical line, after `…instead of deriving from the artifact.`), separated by one space, this exact sentence:

```markdown
The `measured:` clause must name an observation that fails at the base commit, and an evidence threshold is a literal number or string, never "faster" or "reasonable".
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ToIssuesCriterionLine 2>&1 | tail -3`
Expected: `Ran 3 tests` … `OK`

Run: `git diff --stat HEAD -- home/common/agent-skills/skills/to-issues home/common/agent-skills/tests/test_workflow_skill_contracts.py`
Expected: exactly those two files changed.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/to-issues/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(to-issues): type and locate every acceptance criterion (#274)"
```
