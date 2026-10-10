# Task 3: The guard suite pins every fixture row

**Files:**
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `home/common/claude-code/README.md`
- Create: `.agents/artifacts/plans/2026-10-10-issue-351-guarded-command-shape.acceptance.md` (row AC1 only)
- Test: `tests/test_claude_permission_guard.py`

`home/common/claude-code/lifecycle_guard.py` is not edited. This task adds a
characterization test: the guard already gives every row its verdict, so the test passes
as soon as it is written, and a fixture mutation proves it can fail.

**Interfaces:**
- Consumes, from Task 1, `tests/fixtures/guarded-command-shapes.json`:
  - `values`: an object from placeholder (`<branch>`, `<pr-num>`, `<resolved-repository>`,
    `<rendered subject>`) to its concrete text;
  - `skill_forms`: a list of `{id, template, sites, label, bare, prefixed}`, where `bare` and
    `prefixed` are `{"exit": 0}` or `{"exit": 2, "reason": <fragment of the guard's message>}`
    and `label` is the word the guard prints after `lifecycle guard: unsafe `;
  - `refused_shapes`: a list of `{id, form, before, after, label, reason}`, whose command is
    `before` + the concrete command of the skill form with id `form` + `after`.
- Consumes, from the suite: `ClaudePermissionGuardTest.run_guard(command, cwd=None, env=None, guard_args=None)`,
  which wires in the fake `gh`, and `make_repo(origin, default_branch="main")`.
- Produces: `ClaudePermissionGuardTest.test_every_guarded_command_shape_gets_its_verdict`.

**Invariants:**
- Every skill form's concrete command gets its `bare` verdict, and the same command behind
  the literal `unset GITHUB_TOKEN && ` gets its `prefixed` verdict.
- Every refused shape exits 2 with `lifecycle guard: unsafe <label>:` and its `reason`
  fragment in stderr.
- The test stores no command of its own: every command is derived from the fixture (D6).
- No existing test, and nothing in the adversarial table, changes.

- [ ] **Step 1: Build the settings artifact**

Run: `just build` (timeout 3600 s).
Expected: exit 0 and a `./result` link.

Then check that the artifact resolves:
`nix-store --query --requisites ./result | grep -c -- '-claude-code-settings\.json$'`
Expected: `1`.

- [ ] **Step 2: Write the test**

In `tests/test_claude_permission_guard.py`, inside `class ClaudePermissionGuardTest`,
insert this block immediately before `    def test_tag_push_near_misses_are_refused(self):`
(it follows `test_every_adapter_spelling_is_an_allowed_row`, the other fixture-driven
table):

```python
    # Guarded command shapes (#351): the forms ship-issue spells and the dressed
    # shapes agents reach for, from the fixture the shell-example suite also reads.
    SHAPES = json.loads((Path(__file__).parent / "fixtures/guarded-command-shapes.json")
                        .read_text(encoding="utf-8"))
    TOKEN_PREFIX = "unset GITHUB_TOKEN && "

    def shape_command(self, template):
        for placeholder, value in self.SHAPES["values"].items():
            template = template.replace(placeholder, value)
        return template

    def assert_shape_verdict(self, command, repo, label, verdict):
        result = self.run_guard(command, cwd=repo)
        self.assertEqual(verdict["exit"], result.returncode, (command, result.stderr))
        if verdict["exit"] == 2:
            self.assertIn(f"lifecycle guard: unsafe {label}:", result.stderr)
            self.assertIn(verdict["reason"], result.stderr)

    def test_every_guarded_command_shape_gets_its_verdict(self):
        """#351 AC3, D6: the skill's literal forms and the refused dressed shapes."""
        slug = self.SHAPES["values"]["<resolved-repository>"]
        repo = self.make_repo(f"git@github.com:{slug}.git")
        forms = {form["id"]: form for form in self.SHAPES["skill_forms"]}
        for form in forms.values():
            command = self.shape_command(form["template"])
            for variant, text in (("bare", command), ("prefixed", self.TOKEN_PREFIX + command)):
                with self.subTest(form=form["id"], variant=variant):
                    self.assert_shape_verdict(text, repo, form["label"], form[variant])
        for shape in self.SHAPES["refused_shapes"]:
            command = (shape["before"] + self.shape_command(forms[shape["form"]]["template"])
                       + shape["after"])
            with self.subTest(shape=shape["id"]):
                self.assert_shape_verdict(
                    command, repo, shape["label"], {"exit": 2, "reason": shape["reason"]})

```

- [ ] **Step 3: Run it, then watch it fail on a mutated row**

Run: `env CLAUDE_SETTINGS_PATH="$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')" python3 -m unittest tests/test_claude_permission_guard.py -k test_every_guarded_command_shape_gets_its_verdict`
Expected: `Ran 1 test`, `OK`. Twelve skill-form verdicts (six forms, bare and prefixed) and
seven refused shapes are checked inside it.

Now the mutation. In `tests/fixtures/guarded-command-shapes.json`, change the `bare`
verdict of the form `branch.remote` from `{"exit": 2, "reason": "expected exactly git push [-u] origin <branch>"}`
to `{"exit": 0}` and run the same command.
Expected: FAIL in the subtest `(form='branch.remote', variant='bare')` with
`AssertionError: 0 != 2`, its message carrying
`lifecycle guard: unsafe push: expected exactly git push [-u] origin <branch>`.

Restore the fixture: `git checkout -- tests/fixtures/guarded-command-shapes.json`, and
confirm `git status --short tests/fixtures` prints nothing.

- [ ] **Step 4: Name the fixture in the guard README**

In `home/common/claude-code/README.md`, the paragraph that begins `The forge adapter's two
mutations are adjudicated too` ends with the sentence
`The spelling fixture `tests/fixtures/forge-adapter-spellings.json` drives both the adapter suite and the guard's allowed-row table; the guard never reads it at run time.`
Append this sentence to the same paragraph, on the same line, after one space:

````text
The shape fixture `tests/fixtures/guarded-command-shapes.json` (#351) lists the push, merge and branch-delete forms the `ship-issue` skill spells and the dressed shapes agents reach for, each with the guard's verdict; it drives the guard suite's shape table and the `ship-issue` check in `home/common/agent-skills/tests/test_shell_example_contracts.py`, and the guard never reads it either.
````

`CLAUDE.md` does not change.

- [ ] **Step 5: Record AC1 as pending**

AC1 is evidence from a later consumer-project run and cannot be measured in this change
(D10). Create `.agents/artifacts/plans/2026-10-10-issue-351-guarded-command-shape.acceptance.md`
with the heading `# Acceptance record — issue #351`, a blank line, the header row
`| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |`,
its separator row, and one row, AC1:

- Criterion: the issue's first acceptance line verbatim, without its checkbox. Read it
  with `gh issue view 351 --repo fagenorn/nix-config --json body`. Its `grep` pattern
  holds three `\|`, which a Markdown table reads as literal pipes, so the row keeps
  its eight cells.
- Kind: `evidence`.
- Check or command: `grep -c "lifecycle guard: unsafe \(push\|merge\|branch deletion\)"`
  over the run's subagent transcripts; threshold: 0 (baseline 15).
- Observed: `not measured — post-merge`.
- Commit: `—`.
- Conditions: `the next orchestrated run that ships at least 3 issues on nodocom, with the merged skill text installed on the orchestrating host`.
- Verdict: `unverified`.

The controller adds rows AC2 and AC3 at final review. If sdd has already created the
record, add or replace only row AC1 in it.

- [ ] **Step 6: Verify**

Run: `env CLAUDE_SETTINGS_PATH="$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')" python3 -m unittest tests/test_claude_permission_guard.py` (timeout 900 s)
Expected: `OK`, no failure or error: the new table and every existing guard test, the
adversarial table included.

Run: `grep -c "guarded-command-shapes.json" home/common/claude-code/README.md`
Expected: `1`.

Scope check: `git status --short` lists exactly the three files of this task, and
`git diff --stat -- home/common/claude-code/lifecycle_guard.py` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add tests/test_claude_permission_guard.py home/common/claude-code/README.md .agents/artifacts/plans/2026-10-10-issue-351-guarded-command-shape.acceptance.md
git commit -m "test(guard): pin ship-issue's guarded command shapes against the built guard (#351)"
```
