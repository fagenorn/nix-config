# Task 1: Leaf-agent and read-before-write clauses in all six dispatch templates

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/implementer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/re-review-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Produces, for Tasks 2–6 and for any later suite work, these module-level names in
  `test_workflow_skill_contracts.py`:
  - `DISPATCH_PROMPT_TEMPLATES: tuple[Path, ...]` — the six enrolled template paths, in the order listed under **Files** above.
  - `NON_TEMPLATE_SINGLE_FENCE_DOCS: frozenset[Path]` — documents under the walked directories that carry exactly one unlabeled fence but are **not** dispatch templates, each excluded deliberately. Today its sole member is `FROM_ISSUE` (`skills/from-issue/SKILL.md`), whose `## The flow` section is an ASCII flow diagram in a bare fence; it is the orchestrator document, not a prompt (per D23).
  - `LEAF_LAUNCH_CLAUSE: str`, `LEAF_DELIVERY_CLAUSE: str`, `READ_BEFORE_WRITE_CLAUSE: str` — the three canonical clause strings, each a single-line string with single spaces.
  - `def unlabeled_fenced_blocks(text: str) -> list[str]` — every fenced block in `text` whose opening fence carries an **empty** info string, in document order, each returned as its raw body (fence lines excluded, inner indentation preserved).
  - `def normalized(text: str) -> str` — `" ".join(text.split())`.
- Consumes: nothing from earlier tasks — this is the first task.

**Invariants:**
- Each of the three clauses appears inside every enrolled template's single unlabeled fenced block, byte-identical after whitespace normalization (per D1, D2, D22).
- `implementer-prompt.md`'s existing delivery sentences are **not rewritten**: `LEAF_DELIVERY_CLAUSE` is their normalized form, reused verbatim (per D19).
- The clause set is the same three sentences in all six templates — no exception set, including the read-only reviewer templates where read-before-write is inert (per D13).
- The launch clause restricts *naming*, never launching: `implementer-prompt.md` and `ship-handoff.md` legitimately dispatch subagents, and `ship-handoff.md` states "Nested Agent calls are supported." That sentence stays (per D12).
- The enrolment predicate is "exactly one **unlabeled** fenced block", not "exactly one fenced block": `skills/from-issue/decision-ledger.md` has a single fence whose info string is `markdown` and is not a dispatch template (per D21).
- No project residue: the clauses name no repository, issue, or project (Global Constraints).

## The three canonical clause strings

Use these exact texts. Each is one sentence; a template may wrap it to its own line width and inherit its own indentation, because the assertion normalizes whitespace (per D22).

- `LEAF_LAUNCH_CLAUSE`:
  `Launch any subagent by type only, never by name: a subagent cannot spawn a named teammate, and a named launch returns an error instead of work.`
- `LEAF_DELIVERY_CLAUSE` — already present in `implementer-prompt.md`, copy it into the other five:
  `Never deliver it via SendMessage: you were not given a recipient name, and agent-type names like `general-purpose` are not addressable recipients.`
- `READ_BEFORE_WRITE_CLAUSE`:
  `Read a file before writing to it: overwriting content you have not read destroys work you cannot see.`

Note the backticks around `general-purpose` in the delivery clause: they are part of the string, exactly as the implementer template already writes it.

## Placement inside each fence

Place the clauses together, in launch → delivery → read-before-write order, in the part of the fenced prompt that already discusses reporting or delivery, so the subagent meets them alongside the rules they qualify.

- `implementer-prompt.md` — in the `## Report Format` paragraph that already begins "Then report back with ONLY". The delivery clause is already there; add the launch clause before it and the read-before-write clause after it.
- `task-reviewer-prompt.md` — immediately before the `### Strengths` report skeleton, as a short prose paragraph introducing how to report.
- `re-review-prompt.md` — immediately before the `### Verdict` section.
- `correctness-reviewer-prompt.md` — in the paragraph that begins "≤400 words total.", after the sentence about writing the verdict exactly as above.
- `conformance-reviewer-prompt.md` — immediately before the `### Coverage` section.
- `ship-handoff.md` — in the closing paragraph that already begins "Return exactly canonical JSON", after the sentence "Never inline detail."

Match each file's existing indentation inside the fence (four spaces in the five `sdd` templates, none in `ship-handoff.md`) and its existing wrap width.

- [ ] **Step 1: Write the failing tests**

Add these two module-level helpers beside the existing `nested_workflow_documents()` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, together with the constants, then the two tests as methods of `WorkflowSkillContractsTest`.

```python
DISPATCH_PROMPT_TEMPLATES = (
    SDD_DIR / "implementer-prompt.md",
    SDD_DIR / "task-reviewer-prompt.md",
    SDD_DIR / "re-review-prompt.md",
    SDD_DIR / "correctness-reviewer-prompt.md",
    SDD_DIR / "conformance-reviewer-prompt.md",
    FROM_ISSUE_DIR / "ship-handoff.md",
)

# One authoritative home for each clause pasted into all six dispatch prompts.
LEAF_LAUNCH_CLAUSE = (
    "Launch any subagent by type only, never by name: a subagent cannot spawn "
    "a named teammate, and a named launch returns an error instead of work."
)
LEAF_DELIVERY_CLAUSE = (
    "Never deliver it via SendMessage: you were not given a recipient name, "
    "and agent-type names like `general-purpose` are not addressable recipients."
)
READ_BEFORE_WRITE_CLAUSE = (
    "Read a file before writing to it: overwriting content you have not read "
    "destroys work you cannot see."
)


def normalized(text):
    return " ".join(text.split())


def unlabeled_fenced_blocks(text):
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
```

```python
    def test_dispatch_prompt_templates_are_enrolled(self):
        discovered = []
        for directory in (FROM_ISSUE_DIR, SDD_DIR):
            for path in sorted(directory.glob("*.md")):
                if path in NON_TEMPLATE_SINGLE_FENCE_DOCS:
                    continue
                text = path.read_text(encoding="utf-8")
                if len(unlabeled_fenced_blocks(text)) == 1:
                    discovered.append(path)
        self.assertEqual(
            sorted(discovered),
            sorted(DISPATCH_PROMPT_TEMPLATES),
            "a single-unlabeled-fence document under from-issue/ or sdd/ is not "
            "enrolled in DISPATCH_PROMPT_TEMPLATES (or an enrolled template "
            "stopped carrying exactly one unlabeled fence)",
        )

    def test_dispatch_prompts_carry_the_leaf_agent_clauses(self):
        for path in DISPATCH_PROMPT_TEMPLATES:
            blocks = unlabeled_fenced_blocks(path.read_text(encoding="utf-8"))
            self.assertEqual(len(blocks), 1, f"{path}: expected one unlabeled fence")
            prompt = normalized(blocks[0])
            for clause in (
                LEAF_LAUNCH_CLAUSE,
                LEAF_DELIVERY_CLAUSE,
                READ_BEFORE_WRITE_CLAUSE,
            ):
                with self.subTest(path=path.name, clause=clause[:40]):
                    self.assertIn(clause, prompt)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home.common.agent-skills.tests.test_workflow_skill_contracts` from the repo root — or, matching the project runner, `just agent-workflow-tests`.

Expected, at the commit this task starts from:
- `test_dispatch_prompt_templates_are_enrolled` — PASS, but only because `NON_TEMPLATE_SINGLE_FENCE_DOCS` excludes `FROM_ISSUE`. Seven documents under the two walked directories carry exactly one unlabeled fence at this commit: the six templates plus `skills/from-issue/SKILL.md`, whose `## The flow` ASCII diagram sits in a bare fence. Without the exclusion this test fails at the starting commit with `discovered` = 7 paths against a 6-path tuple. This half of the contract is a guard against future drift and must be green before the clause work, so a later failure is unambiguous (per D23).
- `test_dispatch_prompts_carry_the_leaf_agent_clauses` — FAIL. The first subTest failure names `task-reviewer-prompt.md` and the launch clause; five of the six templates carry none of the three clauses, and `implementer-prompt.md` carries only the delivery clause.

If `test_dispatch_prompt_templates_are_enrolled` fails at this commit, stop and report: the enrolment set has drifted from what the plan measured, and the tuple — not the walk — is the contract to fix. One exception is already known and handled: a bare-fenced document that is not a prompt belongs in `NON_TEMPLATE_SINGLE_FENCE_DOCS` with a one-line reason, never silently dropped from the walk. Adding a member there is a deliberate, reviewable act; widening the predicate to make the failure disappear is not.

- [ ] **Step 3: Insert the clauses**

Read each template before editing it. For each of the six files, insert the three clauses at the placement named above, in launch → delivery → read-before-write order, wrapped to that file's width and indented to match its fence body. In `implementer-prompt.md` the delivery clause already exists in place — add the launch clause before it and the read-before-write clause after it, and change nothing else in that paragraph, including the sentence naming the controller as the reader, which stays template-local (per D11).

Do not add the clauses outside any fence. Do not add a second fenced block to any template — that would break `test_dispatch_prompt_templates_are_enrolled`.

- [ ] **Step 4: Verify**

Run: `just agent-workflow-tests`

Expected: PASS. Both new tests green, and every pre-existing test in the suite still green — in particular `test_nested_dispatches_stay_unnamed_and_foreground`, which walks the same two directories and would fail if a clause introduced an `Agent(` line carrying `name=`.

Then confirm the clause reaches the prompt and not just the file, for one template:

Run: `python3 -c "import pathlib,sys; sys.path.insert(0,'home/common/agent-skills/tests'); import test_workflow_skill_contracts as t; print(len([b for b in t.unlabeled_fenced_blocks(pathlib.Path('home/common/agent-skills/skills/from-issue/ship-handoff.md').read_text()) if t.LEAF_LAUNCH_CLAUSE in t.normalized(b)]))"`

Expected: `1`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/implementer-prompt.md home/common/agent-skills/skills/sdd/task-reviewer-prompt.md home/common/agent-skills/skills/sdd/re-review-prompt.md home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
```

```bash
git commit -m "fix(agent-skills): pin leaf-agent and read-before-write clauses in every dispatch prompt"
```
