# Task 1: The Claude-compatible wait clause in its constant and nine carriers

This task covers spec § The clause and § The contract test, per D1, D2, D4 and D7. The `no-wait-loops` clause changes in its one constant and in all nine carriers in the same commit, guarded by a new contract class. Task 2 adds the from-issue rule; nothing here touches the Suspension procedure.

**Files:**
- Modify: `home/common/agent-skills/tests/test_dispatch_contracts.py` (the `"no-wait-loops"` entry of `CONTRACTS` only)
- Modify: `home/common/agent-skills/skills/sdd/implementer-prompt.md`, `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`, `home/common/agent-skills/skills/sdd/re-review-prompt.md`, `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`, `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (append one class)

**Interfaces:**
- Consumes, from `test_workflow_skill_contracts.py` as it is at the base: `REPO_ROOT`, `SKILL_TREES` (the shared, Claude-only and Codex skill trees), `normalized(text)` (every whitespace run to one space), and the module imports `re` and `unittest`.
- Produces, for Task 2: the class `ClaudeCompatibleWaitContractsTest(unittest.TestCase)`, appended after `HandBuiltTimeContractsTest` and before `if __name__ == "__main__":`, with class attributes `QUOTE_MARKER`, `CHAINED_CHECK`, `CHAINED_SHELL`, `FORMER_SITES` and `WAIT_FORMS`, and class methods `unquoted(text) -> str` and `chained_waits(text) -> list[str]`.

**Invariants:**
- `CONTRACTS["no-wait-loops"]` equals, after Python string concatenation: ``Never loop `sleep` in the foreground or chain a check onto it: use Monitor with an until-condition, or one short bare `sleep N` call and check in the next.`` (155 bytes, D1).
- Each of the nine carriers holds that clause exactly once in its rendered region, wrapped as dictated in Step 3; the region, its anchor and the other three clauses are unchanged.
- No `*.md` under `SKILL_TREES` matches either chained shape, and ``bounded foreground `sleep N` `` occurs in none of the three skill trees.
- The agent definitions, `REMAINDER_PLACEHOLDER`, `AGENT_CLAUSES` and the `CARRIERS` tuple are unchanged.

- [ ] **Step 1: Write the failing tests**

Append this class to `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, after `HandBuiltTimeContractsTest` and before the blank lines that precede `if __name__ == "__main__":` (two blank lines on each side):

```python
class ClaudeCompatibleWaitContractsTest(unittest.TestCase):
    """#474: no skill document chains a check onto a foreground `sleep`, and
    each former no-wait-loops site names both Claude-compatible waits."""

    QUOTE_MARKER = re.compile(r"(?m)^[ \t]*>[ \t]?")
    # The retired "`sleep N`, then check once" family, read whitespace-normalized.
    CHAINED_CHECK = re.compile(r"`sleep [^`]*`, then check")
    # A `sleep <arg>` opening a command, at a line or code-span start, chained by && || ;
    CHAINED_SHELL = re.compile(r"(?:^[ \t]*|`)sleep[ \t]+[^\s`;&|]+[ \t]*(?:&&|\|\||;)", re.M)
    FORMER_SITES = (
        "home/common/agent-skills/skills/sdd/implementer-prompt.md",
        "home/common/agent-skills/skills/sdd/task-reviewer-prompt.md",
        "home/common/agent-skills/skills/sdd/re-review-prompt.md",
        "home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md",
        "home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md",
        "home/common/agent-skills/skills/from-issue/ship-handoff.md",
        "home/common/agent-skills/skills/from-issue/SKILL.md",
        "home/common/agent-skills/skills/sdd/SKILL.md",
        "home/common/claude-code/skills/orchestrate-issues/SKILL.md",
    )
    WAIT_FORMS = ("Monitor with an until-condition", "bare `sleep N` call")

    @classmethod
    def unquoted(cls, text):
        return cls.QUOTE_MARKER.sub("", text)

    @classmethod
    def chained_waits(cls, text):
        """The shapes `text` matches: "prose", "shell", both or neither."""
        body = cls.unquoted(text)
        found = []
        if cls.CHAINED_CHECK.search(normalized(body)):
            found.append("prose")
        if cls.CHAINED_SHELL.search(body):
            found.append("shell")
        return found

    def test_the_shapes_match_the_chained_forms_and_spare_the_rest(self):
        for text, shape in (
            ("    run one bounded foreground `sleep N`, then check\n    once.", ["prose"]),
            ("> run one bounded foreground `sleep N`, then\n> check once.", ["prose"]),
            ("`sleep 30 && gh pr checks 1`", ["shell"]),
            ("sleep 60; workflow-state status", ["shell"]),
            ("  > `sleep 5 || true`", ["shell"]),
        ):
            with self.subTest(hit=text):
                self.assertEqual(self.chained_waits(text), shape)
        for text in (
            "`sleep <wait_seconds>`",
            "background `sleep <wait_seconds>`; every wait",
            "`until <check>; do sleep 2; done`",
            "or one short bare `sleep N` call and check in the next.",
        ):
            with self.subTest(spare=text):
                self.assertEqual(self.chained_waits(text), [])

    def test_no_skill_document_chains_a_check_onto_a_foreground_sleep(self):
        checked = 0
        for tree in SKILL_TREES:
            self.assertTrue(tree.is_dir(), tree)
            for path in sorted(path for path in tree.rglob("*.md") if path.is_file()):
                checked += 1
                with self.subTest(document=str(path.relative_to(REPO_ROOT))):
                    self.assertEqual(self.chained_waits(path.read_text(encoding="utf-8")), [])
        self.assertGreater(checked, 20)

    def test_each_former_site_names_both_claude_compatible_waits(self):
        for relative in self.FORMER_SITES:
            text = normalized(self.unquoted((REPO_ROOT / relative).read_text(encoding="utf-8")))
            for form in self.WAIT_FORMS:
                with self.subTest(site=relative, form=form):
                    self.assertIn(form, text)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Wait-class tests command (timeout 600 s).
Expected: `Ran 3 tests`, `FAILED (failures=27)`: the ban fails once for each of the nine carriers (shape `['prose']`), and the site check fails twice per carrier, once per wait form. The pattern self-test passes at the base; it guards the shapes, not the carriers.

- [ ] **Step 3: Write the minimal implementation**

Make each replacement below exactly; every old text occurs once in its file. Fenced texts are whole lines, indentation included.

1. `home/common/agent-skills/tests/test_dispatch_contracts.py`, in `CONTRACTS`, replace

```text
        "Never write an `until` or `while` loop around `sleep` to wait for "
        "something: if a wait is truly needed, run one bounded foreground "
        "`sleep N`, then check once."
```

with

```text
        "Never loop `sleep` in the foreground or chain a check onto it: use "
        "Monitor with an until-condition, or one short bare `sleep N` call "
        "and check in the next."
```

2. In each of the five sdd prompt templates (`implementer-prompt.md`, `task-reviewer-prompt.md`, `re-review-prompt.md`, `correctness-reviewer-prompt.md`, `conformance-reviewer-prompt.md`), replace

```text
    Never write an `until` or `while` loop around `sleep` to wait for something:
    if a wait is truly needed, run one bounded foreground `sleep N`, then check
    once.
```

with

```text
    Never loop `sleep` in the foreground or chain a check onto it: use Monitor
    with an until-condition, or one short bare `sleep N` call and check in the
    next.
```

3. `home/common/agent-skills/skills/from-issue/ship-handoff.md`, replace

```text
Never write an `until` or `while` loop around `sleep` to wait for something: if a
wait is truly needed, run one bounded foreground `sleep N`, then check once.
```

with

```text
Never loop `sleep` in the foreground or chain a check onto it: use Monitor with
an until-condition, or one short bare `sleep N` call and check in the next.
```

4. `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, replace

```text
> Never write an `until` or `while` loop around `sleep` to wait for something: if
> a wait is truly needed, run one bounded foreground `sleep N`, then check once.
```

with

```text
> Never loop `sleep` in the foreground or chain a check onto it: use Monitor with
> an until-condition, or one short bare `sleep N` call and check in the next.
```

5. In `home/common/agent-skills/skills/from-issue/SKILL.md` (the **Leaf-agent clauses** quote) and `home/common/agent-skills/skills/sdd/SKILL.md` (the `## Agent tiers` quote), the clause is the end of one long `> ` line. In each file, replace the substring

```text
Never write an `until` or `while` loop around `sleep` to wait for something: if a wait is truly needed, run one bounded foreground `sleep N`, then check once.
```

with

```text
Never loop `sleep` in the foreground or chain a check onto it: use Monitor with an until-condition, or one short bare `sleep N` call and check in the next.
```

and leave the rest of the line and the file unchanged.

- [ ] **Step 4: Verify**

Run the Wait-class tests command (timeout 600 s). Expected: `Ran 3 tests`, `OK`.

Run the Skill contract tests command (timeout 900 s). Expected: `Ran 235 tests`, `OK (skipped=3)`.

Run (timeout 60 s):

```bash
set -euo pipefail
if git grep -n -F 'bounded foreground `sleep N`' -- home/common/agent-skills/skills home/common/claude-code/skills home/common/codex/skills; then exit 1; fi
n=$(git grep -l -F 'one short bare `sleep N` call and check in the' -- home/common/agent-skills/skills home/common/claude-code/skills | wc -l | tr -d ' ')
test "$n" -eq 9
echo clause-ok
```

Expected: `clause-ok`. At the starting commit the first `git grep` prints the nine old copies and the script exits 1. The scope leaves out the tests, whose self-test fixtures keep a retired fragment on purpose.

Run the Budget command (timeout 600 s). Expected: last line `check: pass`.

Run the Installed tier command (timeout 3600 s). Expected: `OK (skipped=1)` or `OK`; `InstalledTreeContractsTest.test_no_wait_loops` passes against the built home.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/skills/sdd/implementer-prompt.md home/common/agent-skills/skills/sdd/task-reviewer-prompt.md home/common/agent-skills/skills/sdd/re-review-prompt.md home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/sdd/SKILL.md home/common/claude-code/skills/orchestrate-issues/SKILL.md
launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- -m "feat(skills): name Claude-compatible waits in the no-wait-loops clause (issue 474)"
```

The message ends with the session's attribution trailer. Report DONE with the three test counts and the Budget line.
