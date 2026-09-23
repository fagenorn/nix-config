# Task 3: Checker-contract guidance

Decisions: D5, D6, D11, D15, D16. Work from the worktree root; paths are
repo-relative. Lands an adapted retained hunk — the commit carries the
`Recovered-From` trailer (root Global Constraints).

**Files:**
- Modify: `home/common/agent-skills/skills/worktrees/SKILL.md`
- Modify: `home/common/agent-skills/tests/test_shell_example_contracts.py`

**Interfaces:**
- Consumes (Task 2, `test_shell_example_contracts.py`): `SANCTIONED_PREFIX`,
  `refused_examples`, `WorktreesGuidanceTest` with its `self.skill` (the live
  `worktrees/SKILL.md` text) and `section(heading)` helper,
  `RefusedFormFixtureTest.test_host_baseline_yields_nothing`.
- Produces: the `## Shell forms the isolation checker refuses` section; two new
  `WorktreesGuidanceTest` methods. Nothing later consumes them by name.

**Invariants:**
- The section sits after `## Already positioned? Skip the call` and before
  `## Detect existing isolation`.
- It names, in this order: the invariant, the four forms, the one-command-per-
  call alternative, the path-passing alternative, the per-invocation directory,
  the sanctioned prefix and "change the shell form, never the isolation" (D16).
- It names no `--body-file` example (D11) and no version-specific rule table (D6).
- `worktrees/SKILL.md` still yields no findings — it is the fixture host.

- [ ] **Step 1: Write the failing tests**

Add to `WorktreesGuidanceTest` in `test_shell_example_contracts.py`:

```python
    SECTION = "## Shell forms the isolation checker refuses"

    def test_section_sits_between_positioning_and_detection(self):
        self.assertLess(self.skill.index("## Already positioned? Skip the call"),
                        self.skill.index(self.SECTION))
        self.assertLess(self.skill.index(self.SECTION),
                        self.skill.index("## Detect existing isolation"))

    def test_section_names_contract_forms_and_alternatives_in_order(self):
        section = " ".join(self.section(self.SECTION).split())
        anchors = (
            "one plain command whose targets are literal arguments",
            "a multi-clause chain",
            "a pipe",
            "a redirect",
            "a heredoc fed to a command's stdin",
            "One command per call",
            "pass them by path",
            "`git -C <path>`",
            f"`{SANCTIONED_PREFIX}`",
            "change the shell form, never the isolation",
        )
        position = 0
        for anchor in anchors:
            found = section.find(anchor, position)
            self.assertNotEqual(found, -1, f"missing or out of order: {anchor!r}")
            position = found + len(anchor)
        self.assertNotIn("--body-file", section)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: FAIL — the two new methods (`ValueError: substring not found` for the
section heading); every Task-2 test still passes.

- [ ] **Step 3: Write the section (adapted from the retained hunk)**

The retained text is in `git diff 95b6caf 3c9709ca -- home/common/agent-skills/skills/worktrees/SKILL.md`
(the added `## Shell forms …` block). Insert this adaptation — pipes added,
`--body-file` dropped, the literal argument and the sanctioned prefix added —
directly before `## Detect existing isolation`, separated by blank lines:

```markdown
## Shell forms the isolation checker refuses

The same audit found the **shell form** of a command costs 197 error turns, roughly **four times** the redundant-entry class above — the largest single class. The checker runs a command only when it can verify the command stays inside the worktree, and it can do that for one plain command whose targets are literal arguments. Shell control flow and redirection hide the target, so it refuses them rather than guess. Four forms do this: a multi-clause chain (`&&`, `||`, `;`), a pipe, a redirect (including `2>/dev/null`), and a heredoc fed to a command's stdin.

What works instead:

- One command per call. A dependent step is the next call, decided by reading the previous call's exit status and output. Filter or count output by reading it, not by piping it.
- Create files with the file-writing tool and pass them by path where the CLI takes one (`--notes-file`, `-F <file>`), or pass a body as one literal quoted argument with no substitution inside it.
- Carry the directory inside the invocation: absolute paths under the worktree root, or the tool's own directory flag such as `git -C <path>`. A prelude that `cd`s in and chains onward is itself the refused chain.
- Treat a non-zero exit as information — read it and decide the next call — rather than suppressing stderr.
- One chain is sanctioned: the `unset GITHUB_TOKEN && ` prefix that `from-issue/bindings.md`'s tracker-cli hygiene prescribes, spelled exactly as there. The lifecycle guard accepts that literal and nothing looser.
- Refused → change the shell form, never the isolation. Rewriting the command to work outside the worktree defeats the call that put you in it.
```

The prefix span must equal the guard literal byte for byte, trailing space
included — the anchor test builds it from `SANCTIONED_PREFIX`.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: `OK` — including `test_host_baseline_yields_nothing`, which proves the
new prose teaches no refused form.

Run: `just agent-workflow-tests`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/worktrees/SKILL.md home/common/agent-skills/tests/test_shell_example_contracts.py
git commit
```

Message: `docs(worktrees): state the isolation checker's shell-form contract`;
the body names the adapted retained hunk (the `worktrees` "Shell forms the
isolation checker refuses" section: pipes added, `--body-file` dropped, literal
argument and sanctioned prefix added, per D5, D6, D11) and the guidance test
adapted from `test_worktrees_names_the_refused_shell_forms_and_the_alternative`
(D16), then the trailer paragraph with
`Recovered-From: 3c9709ca470bd473d49b39a611ca6cab258973db`.
