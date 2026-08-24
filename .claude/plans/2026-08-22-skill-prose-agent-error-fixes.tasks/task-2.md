# Task 2: Presence guard on every bindings-config mention

**Files:**
- Modify: `home/common/agent-skills/skills/research/SKILL.md`
- Modify: `home/common/agent-skills/skills/design/SKILL.md`
- Modify: `home/common/agent-skills/skills/doc-grounded-questions/SKILL.md`
- Modify: `home/common/agent-skills/skills/wayfind/SKILL.md`
- Modify: `home/common/agent-skills/skills/to-issues/SKILL.md`
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/CONSOLIDATE.md`
- Modify: `home/common/agent-skills/skills/ship-release/SKILL.md`
- Modify: `home/common/agent-skills/skills/grill-with-docs/CONTEXT-FORMAT.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes from Task 1: nothing — this task is independent of the clause constants.
- Produces, for Tasks 4–6, these module-level names in `test_workflow_skill_contracts.py`:
  - `SKILL_TREES: tuple[Path, ...]` — `(REPO_ROOT / "home/common/agent-skills/skills", REPO_ROOT / "home/common/claude-code/skills")`.
  - `def skill_documents() -> Iterator[tuple[Path, str]]` — every `*.md` under `SKILL_TREES`, recursively, **excluding** any path with an `evals` component, yielded in sorted order as `(path, text)`.
  - `BINDINGS_CONFIG: str` — `".claude/skills.config.json"`.
  - `GUARD_PHRASES: tuple[str, ...]` — `("if it exists", "when present")`.

**Invariants:**
- Every occurrence of the literal `.claude/skills.config.json` in a discovered skill document sits in a blank-line-delimited paragraph that also contains `if it exists` or `when present` (per D3, D14).
- Only those two phrasings count. `when set`, `if configured`, `where available` and similar do not — the register is closed so the assertion stays one rule with no exception list (per D3).
- The guard is on the **file**, not on the resolver helper. A sentence whose only condition is "helper missing" leaves the read unconditional on the config's existence and does not satisfy this task (per D3).
- Descriptive mentions gain the phrase too, even where no read is instructed (per D3).
- Nothing about how bindings actually resolve changes: `scripts/resolve-bindings` is untouched, and no default value, key name, or precedence is edited (Global Constraints, Out of scope).
- `evals/` is excluded from discovery: eval prompts state the fixture's config as a given and are out of scope (Global Constraints).

## The sites and what each needs

Two occurrences already satisfy the rule and must be left alone:
`skills/from-issue/bindings.md` ("Read `.claude/skills.config.json` at the project root if it exists.") and
`skills/grill-with-docs/SKILL.md` ("prefer those when present"). Two more already satisfy it in
`home/common/claude-code/skills/codex-collaboration/{SKILL.md,PLAN-REVIEW.md}` — leave both.

The eleven files above each need one minimal insertion. Read each file before editing it, locate the occurrence, and add the phrase in the same sentence:

| File | Current shape of the mention | Required change |
|---|---|---|
| `research/SKILL.md` | "helper missing → `.claude/skills.config.json`, default `.claude/specs`" | insert `if it exists` after the path |
| `design/SKILL.md` | "helper missing → `.claude/skills.config.json`, default `.claude/specs`" | insert `if it exists` after the path |
| `writing-plans/SKILL.md` | "helper missing → `.claude/skills.config.json`, default `.claude/plans`" | insert `if it exists` after the path |
| `doc-grounded-questions/SKILL.md` | "prints the standard binding set from `.claude/skills.config.json` plus …; helper missing → read the config and apply the same defaults" | make the second clause read "read the config **if it exists**" |
| `to-issues/SKILL.md` | same shape as `doc-grounded-questions/SKILL.md` | same change |
| `ship-issue/SKILL.md` | "prints the standard binding set (…) from `.claude/skills.config.json` plus …. Helper missing → read the config and apply the defaults it documents." | make it "read the config **if it exists**" |
| `wayfind/SKILL.md` | "Resolve tracker bindings from `.claude/skills.config.json` (`issueTracker{kind,cli}`, default GitHub/`gh`)." | insert `when present` after the path |
| `ship-release/SKILL.md` | "Read `.claude/skills.config.json` at the project root." | insert `if it exists` before the full stop |
| `ship-issue/CONSOLIDATE.md` | "destination paths come from `.claude/skills.config.json` (`docPaths.*`, `specDir`, `planDir`) as resolved by the parent skill" | insert `when present` after the closing parenthesis |
| `grill-with-docs/CONTEXT-FORMAT.md` | "Prefer `.claude/skills.config.json`'s `docPaths.contextMap` / `docPaths.context` **when set**." | replace `when set` with `when present` — `when set` is not in the closed register |
| `orchestrate-issues/SKILL.md` | "The tracker CLI and `unsetGithubToken` come from `.claude/skills.config.json`, through the same bindings used by `from-issue`." | insert `when present` after the path |

Do not rewrap a line merely to fit the insertion unless the line then exceeds the file's prevailing width; the assertion's window is the paragraph, not the line, precisely so no rewrap is forced (per D14).

- [ ] **Step 1: Write the failing test**

Add the module-level names beside `nested_workflow_documents()`, then the test as a method of `WorkflowSkillContractsTest`.

```python
SKILL_TREES = (
    REPO_ROOT / "home/common/agent-skills/skills",
    REPO_ROOT / "home/common/claude-code/skills",
)
BINDINGS_CONFIG = ".claude/skills.config.json"
GUARD_PHRASES = ("if it exists", "when present")


def skill_documents():
    for tree in SKILL_TREES:
        for path in sorted(tree.rglob("*.md")):
            if "evals" in path.parts:
                continue
            yield path, path.read_text(encoding="utf-8")
```

```python
    def test_bindings_config_mentions_are_guarded_on_presence(self):
        for path, text in skill_documents():
            for paragraph in text.split("\n\n"):
                if BINDINGS_CONFIG not in paragraph:
                    continue
                with self.subTest(path=str(path.relative_to(REPO_ROOT))):
                    self.assertTrue(
                        any(phrase in paragraph for phrase in GUARD_PHRASES),
                        f"{path}: a paragraph naming {BINDINGS_CONFIG} carries no "
                        f"presence guard; use one of {GUARD_PHRASES}",
                    )
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `just agent-workflow-tests`

Expected: FAIL, with eleven `subTest` failures — one per file in the table above, each naming the repository-relative path in its `subTest` label. `from-issue/bindings.md`, `grill-with-docs/SKILL.md` and the two `codex-collaboration` documents must **not** appear among the failures; if one does, the paragraph split has landed differently than measured and the discovery or windowing needs re-reading before any prose is changed.

- [ ] **Step 3: Apply the eleven insertions**

Make exactly the changes in the table. Nothing else in these files changes — no reordering of keys, no default values touched, no additional sentences.

- [ ] **Step 4: Verify**

Run: `just agent-workflow-tests`

Expected: PASS — the new test green and every pre-existing test still green.

Then confirm the guard is on the file and not the helper, by checking that no remaining mention is helper-conditional only:

Run: `grep -rn "helper missing" home/common/agent-skills/skills --include=*.md`

Expected: every printed line that also names `.claude/skills.config.json` contains `if it exists`. A line naming the config with no `if it exists` on it is this task incomplete.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/research/SKILL.md home/common/agent-skills/skills/design/SKILL.md home/common/agent-skills/skills/doc-grounded-questions/SKILL.md home/common/agent-skills/skills/wayfind/SKILL.md home/common/agent-skills/skills/to-issues/SKILL.md home/common/agent-skills/skills/writing-plans/SKILL.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/CONSOLIDATE.md home/common/agent-skills/skills/ship-release/SKILL.md home/common/agent-skills/skills/grill-with-docs/CONTEXT-FORMAT.md home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
```

```bash
git commit -m "fix(agent-skills): guard every bindings-config mention on the file being present"
```
