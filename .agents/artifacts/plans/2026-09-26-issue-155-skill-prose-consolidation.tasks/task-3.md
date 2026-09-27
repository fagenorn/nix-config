# Task 3: Point ship-release at the shell-form home (E4) and guard checker mentions

**Files:**
- Modify: `SK/ship-release/SKILL.md`
- Test: `T/test_shell_example_contracts.py`

**Interfaces:**
- Consumes (existing, in `T/test_shell_example_contracts.py`): `re`,
  `SOURCE_TREES`, `swept_documents()` (every living `*.md` of both source trees
  outside `evals/`, as `(tree key, posix path)` pairs) and the
  `GUIDANCE_POINTER` constant.
- Produces: the constants `GUIDANCE_HOME = "worktrees/SKILL.md"` and
  `CHECKER_MENTION = re.compile(r"isolation\s+checker", re.I)`, and
  `lacks_guidance_pointer(document_text) -> bool`. The function is true exactly
  when the text matches `CHECKER_MENTION` and does not contain `GUIDANCE_HOME`.
  It is exercised by the new `GuidancePointerTest`.

**Invariants:**
- `SK/worktrees/SKILL.md` is the one document exempt from the guard. It is the
  guidance home (D1).
- A paraphrase that avoids the words "isolation checker" is outside the guard.
  That limitation is named, per spec §Guards.
- E4 changes only the reason clause of ship-release Phase 2's first sentence. The
  `<release-body-path>` placeholder, "outside the working tree", "file-writing
  tool" and "passed by path" survive.
- The new text spells the home with its skill prefix, as `worktrees/SKILL.md`, so
  it adds no same-skill basename to ship-release. D18 closure is unaffected.

- [ ] **Step 1: Write the failing test**

In `T/test_shell_example_contracts.py`, directly below the existing
`GUIDANCE_POINTER = …` line, add:

```python
GUIDANCE_HOME = "worktrees/SKILL.md"
CHECKER_MENTION = re.compile(r"isolation\s+checker", re.I)


def lacks_guidance_pointer(document_text):
    """True when a document mentions the isolation checker without naming its
    guidance home. A paraphrase that avoids the term is outside this check."""
    return (CHECKER_MENTION.search(document_text) is not None
            and GUIDANCE_HOME not in document_text)


class GuidancePointerTest(unittest.TestCase):
    def test_every_checker_mention_names_the_guidance_home(self):
        for tree, relative in swept_documents():
            if (tree, relative) == ("shared", GUIDANCE_HOME):
                continue
            with self.subTest(document=f"{tree}:{relative}"):
                text = (SOURCE_TREES[tree] / relative).read_text(encoding="utf-8")
                self.assertFalse(
                    lacks_guidance_pointer(text),
                    f"{tree}:{relative} mentions the isolation checker without "
                    f"naming {GUIDANCE_HOME}",
                )

    def test_a_mention_without_the_pointer_is_reported(self):
        text = (SOURCE_TREES["shared"] / "ship-release/SKILL.md").read_text(encoding="utf-8")
        self.assertFalse(lacks_guidance_pointer(text))
        self.assertTrue(lacks_guidance_pointer(text.replace(GUIDANCE_HOME, "")))
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py -k GuidancePointerTest`
Expected: FAILED (failures=2). The live-sweep test fails naming
`shared:ship-release/SKILL.md`. The mutation test fails its first
`assertFalse`, because ship-release mentions the checker without the pointer.

- [ ] **Step 3: Make E4**

In `SK/ship-release/SKILL.md`, `## Phase 2 — Open PR`, replace

```text
passed by path, because a heredoc into `gh` is refused by the worktree isolation checker.
```

with

```text
passed by path — see `worktrees/SKILL.md`, `## Shell forms the isolation checker refuses`.
```

The pointer now names the section that owns the reason (the spec's homes table).

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_ship_release_contracts.py`
Expected: OK. That includes `GuidancePointerTest`, the source sweep and
`WorktreesGuidanceTest`.

Run: `git grep -n -F "heredoc into" -- home/common/agent-skills/skills/ship-release/SKILL.md`
Expected: no output and exit 1. At the start commit it prints the Phase 2
sentence.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-release/SKILL.md home/common/agent-skills/tests/test_shell_example_contracts.py
git commit -m "refactor(skills): point ship-release at the shell-form home and guard checker mentions (#155 E4)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Decision IDs: D1, D2, D13.
