# Task 3: Isolation-checker shell guidance and a single-invocation isolation probe

**Files:**
- Modify: `home/common/agent-skills/skills/worktrees/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the existing module-level `WORKTREES` `Path` constant and the existing
  `self.assert_ordered(text, *anchors)` and `self.section(text, heading, next_heading)`
  helpers on `WorkflowSkillContractsTest`. Nothing from Tasks 1 or 2.
- Produces: nothing later tasks import. Tasks 4–6 will assert over `worktrees/SKILL.md`
  through their own blanket checks; this task must leave that file free of chain
  operators, pipes, redirects and heredocs in its shell examples so those checks pass
  when they arrive.

**Invariants:**
- The new section is a structural sibling of `## Already positioned? Skip the call`: a heading, one bolded measured-telemetry finding, then rules as bullets. Same shape, same register.
- The guidance is derived from **one stated invariant** — a static checker can confirm a command stays inside the worktree only when the target is a literal argument of a single invocation — and never from a guessed accept/reject rule table. The checker is harness-level with no source in this repository (per D5, Out of scope).
- The section names all three refused forms (multi-clause chain, redirect, heredoc fed to a command's stdin) **and** the alternative that works (issue criterion 4).
- The isolation probe becomes a **single `git rev-parse` invocation** with no chain, pipe or redirect. Its accompanying prose describes what that invocation actually prints: two lines normally, a third only inside a submodule. Verified locally — the superproject flag prints no line at all outside a submodule, so the prose must not imply three fixed lines.
- No project residue: the evidence line cites measured telemetry without naming a project, matching the existing `43%` note in the same file (Global Constraints).
- The section's own inline code spans must not themselves demonstrate a refused form. Write chain operators as bare spans (`&&`, `||`, `;`) and never as a command-leading span such as a `cd`-plus-chain prelude.

## The prose to write

Insert this section immediately after `## Already positioned? Skip the call` and immediately before `## Detect existing isolation`.

```markdown
## Shell forms the isolation checker refuses

The same audit found the **shell form** of a command costs roughly **four times** as many errors as the redundant-entry class above — the largest single class. The checker is static: it can confirm a command stays inside the worktree only when the target is a literal argument of a single invocation. Shell control flow and redirection hide the target, so they are refused. The three refused forms are a multi-clause chain, a redirect, and a heredoc fed to a command's stdin.

What works instead:

- One command per call. A dependent step is a second call, never a chain — no `&&`, no `||`, no `;`.
- Create and truncate files with the file-writing tool, never a redirect or a heredoc. The tool takes an explicit path the checker can read.
- Hand a long body to a CLI by path — `--body-file`, `--notes-file`, `-F <file>`, `@<file>` — after the file-writing tool has written it.
- Carry paths inside the single invocation: absolute paths under the worktree root, or the tool's own directory flag such as `git -C <path>`. A prelude that `cd`s in and chains with `&&` is itself the refused chain.
- Refused → change the shell form, never the isolation. Rewriting the command to work outside the worktree defeats the call that put you in it.
```

Then replace the whole body of `## Detect existing isolation` with:

````markdown
## Detect existing isolation

```bash
git rev-parse --git-dir --git-common-dir --show-superproject-working-tree
```

Compare the first two lines: different → you are already in a linked worktree; report the path and branch and stop. Identical → this is the default checkout. The superproject flag prints **no line at all** outside a submodule, so two lines is the normal case and a third line means a submodule — which also has a distinct git-dir and is *not* isolation.
````

- [ ] **Step 1: Write the failing test**

Add as a method of `WorkflowSkillContractsTest`.

```python
    def test_worktrees_names_the_refused_shell_forms_and_the_alternative(self):
        guidance = self.section(
            self.worktrees,
            "## Shell forms the isolation checker refuses",
            "## Detect existing isolation",
        )
        self.assert_ordered(
            guidance,
            "roughly **four times**",
            "literal argument of a single invocation",
            "a multi-clause chain, a redirect, and a heredoc fed to a command's stdin",
            "One command per call",
            "never a redirect or a heredoc",
            "--body-file",
            "git -C <path>",
            "change the shell form, never the isolation",
        )
```

`self.worktrees` must be the text of `WORKTREES`. The class already reads several skill
documents in `setUpClass`; if `cls.worktrees` is not among them, add
`cls.worktrees = WORKTREES.read_text(encoding="utf-8")` there in the same style as its
neighbours.

Also add, in the same test method, the probe assertion — one reason, one section:

```python
        probe = self.section(
            self.worktrees,
            "## Detect existing isolation",
            "## Branch and prefix contract",
        )
        self.assertIn(
            "git rev-parse --git-dir --git-common-dir "
            "--show-superproject-working-tree",
            probe,
        )
        self.assertIn("no line at all", probe)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `just agent-workflow-tests`

Expected: FAIL — `test_worktrees_names_the_refused_shell_forms_and_the_alternative` raises
`ValueError: substring not found` from `self.section`, because
`## Shell forms the isolation checker refuses` does not exist in the file yet. That is the
correct first failure: the section, not the wording, is what is missing.

- [ ] **Step 3: Write the section and replace the probe**

Read `home/common/agent-skills/skills/worktrees/SKILL.md` in full, then apply both edits
above verbatim. Leave `## Already positioned? Skip the call`, `## Destructive-ops
carve-out`, `## Branch and prefix contract`, `## refs/stash is shared` and `## Setup and
baseline` untouched.

- [ ] **Step 4: Verify**

Run: `just agent-workflow-tests`

Expected: PASS. In particular `test_worktrees_isolation_failure_reports_blocked_not_in_place`
— a pre-existing test over this same file — must still pass; if it fails, the probe
replacement removed prose it asserts on and the removal must be undone.

Then confirm the probe's documented behaviour against the live repository:

Run: `git rev-parse --git-dir --git-common-dir --show-superproject-working-tree`

Expected: exactly two lines, the first ending in a `worktrees/<name>` path and the second
being the common git dir — i.e. the "already in a linked worktree" reading the new prose
describes, with no third line.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/worktrees/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
```

```bash
git commit -m "docs(worktrees): state the isolation checker's shell rule and probe in one invocation"
```
