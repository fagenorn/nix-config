# Task 1: Brief-driven agents omit CLAUDE.md, paid for in place

Spec § Brief-driven agents run without CLAUDE.md, per D3 and D5. `mechanic` and `reviewer-lite` gain the frontmatter line `omitClaudeMd: true` (Claude Code then starts them, as subagents, without the user, project and local `CLAUDE.md` files); `implementer` and `reviewer` do not. Each file pays for its 19-byte line by rewording its own non-pinned prose shorter, without dropping an instruction, so no Instruction Budget measure grows.

**Files:**
- Modify: `home/common/claude-code/agents/mechanic.md`
- Modify: `home/common/claude-code/agents/reviewer-lite.md`
- Test: `home/common/agent-skills/tests/test_agent_model_matrix.py` (class `AgentModelMatrixTest`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: the frontmatter key `omitClaudeMd` with the value `true` in exactly `mechanic.md` and `reviewer-lite.md`, which Task 4 copies into its after-run sandbox.

**Invariants:**
- `mechanic.md` is at most 759 bytes and `reviewer-lite.md` at most 1,561 bytes (their sizes at base; `wc -c`), so the profiles at 760 and 1,562 bytes and the corpus ceiling hold without a raise (D5).
- The existing frontmatter lines (`name`, `description`, `effort`, `model`, `tools`) and their order are byte-identical; `omitClaudeMd: true` is the last frontmatter line, directly above the closing `---`.
- The own-commands clause ("Run each long command, every verification command included, …") is byte-identical in both files, and `reviewer-lite.md`'s mode names `**Scoped re-review**` and `**Lane verification**` are unchanged.
- `implementer.md` and `reviewer.md` are not modified.

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_agent_model_matrix.py`, add this method to `AgentModelMatrixTest`, directly after `test_every_custom_agent_explicitly_matches_its_matrix_role`:

```python
    def test_only_the_brief_driven_agents_omit_claude_md(self):
        found = {
            path.stem: frontmatter(path).get("omitClaudeMd")
            for path in sorted(AGENTS.glob("*.md"))
        }
        self.assertEqual(
            found,
            {"implementer": None, "mechanic": "true", "reviewer": None, "reviewer-lite": "true"},
        )
```

- [ ] **Step 2: Run the test and watch it fail**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_agent_model_matrix.py -k test_only_the_brief_driven_agents_omit_claude_md 2>&1 | tail -6'`
Expected: FAIL — `AssertionError: {'implementer': None, 'mechanic': None, 'reviewer': None, 'reviewer-lite': None} != {…}`.

- [ ] **Step 3: Write the minimal implementation**

Apply exactly these replacements (old text → new text; line breaks as shown).

`home/common/claude-code/agents/mechanic.md`:

1. Frontmatter: after the line `model: sonnet`, insert the line `omitClaudeMd: true`.
2. ```text
   If a step
   needs a judgment call the brief doesn't cover, stop and report the question
   instead of deciding.
   ```
   →
   ```text
   If a step
   needs a judgment the brief doesn't cover, stop and report the question instead
   of deciding.
   ```
3. ```text
   Follow the dispatch prompt's status vocabulary and report shape exactly.
   Keep the report to counts, paths and short notes.
   ```
   →
   ```text
   Follow the brief's status vocabulary and report shape exactly. Report only
   counts, paths and short notes.
   ```

`home/common/claude-code/agents/reviewer-lite.md`:

1. Frontmatter: after the line `tools: Read, Glob, Grep, Bash`, insert the line `omitClaudeMd: true`.
2. ```text
   2. **Lane verification**: a first-pass check of one task whose declared risk
      lane is mechanical or low-risk, judged only against its bounded diff.
   ```
   →
   ```text
   2. **Lane verification**: a first-pass check of one task whose declared lane
      is mechanical or low-risk, judged only against its bounded diff.
   ```
3. ```text
     branch: report the escalation to the `reviewer` role instead.
   ```
   →
   ```text
     branch: report the escalation to the `reviewer` role.
   ```
4. ```text
   Follow the dispatch prompt's verdict vocabulary, report shape and length
   budget exactly.
   ```
   →
   ```text
   Follow the brief's verdict vocabulary, report shape and length budget
   exactly.
   ```

The results measure 756 and 1,557 bytes. "The brief" is the name both files already use for the dispatch prompt, so no instruction changes meaning.

- [ ] **Step 4: Verify**

Run (timeout 600 s), from the worktree root:

```bash
set -e
test "$(wc -c < home/common/claude-code/agents/mechanic.md)" -le 759
test "$(wc -c < home/common/claude-code/agents/reviewer-lite.md)" -le 1561
git diff --quiet 04a396606d69fe6b720596c20846934b040abaa6 -- home/common/claude-code/agents/implementer.md home/common/claude-code/agents/reviewer.md
```

Expected: every command exits 0.

Run the **Matrix tests** (Global Constraints). Expected: `OK`, no failure; the new test passes and `test_dispatch_contracts` still finds the own-commands clause in all four agent files.

Run the **Budget gate** (Global Constraints). Expected: the last line is `check: pass`. With the texts above every touched ceiling stays within 1 % of its measure (760 over 756, 1,562 over 1,557), so neither an exceeded ceiling nor a `tightness` line can appear; either one means the files deviate from Step 3, and the task stops as BLOCKED with the gate's output.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/agents/mechanic.md home/common/claude-code/agents/reviewer-lite.md home/common/agent-skills/tests/test_agent_model_matrix.py
launch-commit … -- -m "feat(agents): mechanic and reviewer-lite start without CLAUDE.md (issue 425)" -m "<session trailers>"
```

Verify: `git status --short -- home` prints nothing.
