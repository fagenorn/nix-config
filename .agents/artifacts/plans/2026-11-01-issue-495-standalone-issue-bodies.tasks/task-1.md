# Task 1: Problem-first, self-explaining to-issues bodies

This task covers the whole spec: § The template, § The rules, § Budget and § Test seams, per D1 to D7. It is the plan's only task, so it also runs the full verification set.

**Files:**
- Modify: `home/common/agent-skills/skills/to-issues/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (insert one class)

**Interfaces:**
- Consumes, from `test_workflow_skill_contracts.py` as it is at the base: `normalized(text)` (every whitespace run to one space), the class attribute `ToIssuesCriterionLineContractsTest.TO_ISSUES` (the `Path` of `to-issues/SKILL.md`), and the module import `unittest`.
- Produces: the class `ToIssuesStandaloneBodyContractsTest(unittest.TestCase)`, inserted directly after `ToIssuesCriterionLineContractsTest` and before `AcceptanceMapContractsTest`, with the class attribute `TEMPLATE_HEADINGS` and the tests `test_the_template_sections_put_the_problem_before_what_to_build` and `test_the_first_use_and_stranger_read_rules_are_stated`. No later task consumes it.

**Invariants:**
- The `## ` headings between `<issue-template>` and `</issue-template>` are, in order, `Parent`, `Problem`, `What to build`, `Decisions`, `Acceptance criteria`, `Blocked by` (D3).
- The whitespace-normalized skill text contains `at first use` and `reread each body` (D4, D6).
- `to-issues/SKILL.md` is exactly the dictated text: 6483 bytes, sha256 `ec9d3d44abb17235f93c35b9f6ddbfb6f8dcfc0bcc1af19e30915e172686b811` (D1, D2).
- `ToIssuesCriterionLineContractsTest`, `RESOLUTION_SENTENCE`, `REFUSAL_REPORTING_SENTENCE` and `SHARED_POLICY_ENTRIES` are unchanged and their tests still pass.
- `home/common/agent-skills/instruction-load.json` and `to-issues/WIDE-REFACTORS.md` are unchanged (D1).

- [ ] **Step 1: Write the failing tests**

First confirm the starting text: `shasum -a 256 home/common/agent-skills/skills/to-issues/SKILL.md` prints `2a5fc7ac635a1351b8d50fe49173d0ff6468a97015b28adbf1b99ae695cfef63` (6494 bytes). Any other hash means the base moved: stop and report BLOCKED, because the dictated replacements and the byte count were measured against this text.

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, insert this class after `ToIssuesCriterionLineContractsTest` (whose last line is `            normalized(self.text))`) and before `class AcceptanceMapContractsTest`, with two blank lines on each side:

```python
class ToIssuesStandaloneBodyContractsTest(unittest.TestCase):
    """#495 AC1: the to-issues template puts Problem before What to build, and
    the skill states the first-use and stranger-read rules (D3, D4, D6)."""

    TEMPLATE_HEADINGS = ["Parent", "Problem", "What to build", "Decisions",
                         "Acceptance criteria", "Blocked by"]

    @classmethod
    def setUpClass(cls):
        cls.text = ToIssuesCriterionLineContractsTest.TO_ISSUES.read_text(encoding="utf-8")

    def test_the_template_sections_put_the_problem_before_what_to_build(self):
        template = self.text[self.text.index("<issue-template>"):
                             self.text.index("</issue-template>")]
        headings = [line[3:] for line in template.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, self.TEMPLATE_HEADINGS)

    def test_the_first_use_and_stranger_read_rules_are_stated(self):
        text = normalized(self.text)
        for token in ("at first use", "reread each body"):
            with self.subTest(token=token):
                self.assertIn(token, text)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the To-issues classes command (timeout 600 s).
Expected: `Ran 4 tests`, `FAILED (failures=3)`. The three `FAIL:` lines are `test_the_template_sections_put_the_problem_before_what_to_build` (the list lacks `Problem`) and `test_the_first_use_and_stranger_read_rules_are_stated` once with `token='at first use'` and once with `token='reread each body'`. The two `ToIssuesCriterionLineContractsTest` tests pass.

- [ ] **Step 3: Write the minimal implementation**

Make each replacement below in `home/common/agent-skills/skills/to-issues/SKILL.md`, exactly. Every old text occurs once in the file and is one or more whole lines; every paragraph in this file is a single line, so never hard-wrap a new one. Nothing else in the file changes.

1. The tracker sentence (§ Project bindings) counts the no-tracker route as publishing and drops the restated blocked-tracker stop (D7, D2). Replace

```text
`bindings.tracker.{kind,cli,repo_slug,credential_env.unset_before_invocation}` say where and how issues are filed. An authored unsupported tracker, or `kind: none`, means no publishing: emit the slices as a Markdown list, one template block each, for the user to file. A blocked tracker stops the forge operation.
```

with

```text
`bindings.tracker.{kind,cli,repo_slug,credential_env.unset_before_invocation}` say where and how issues are filed. An authored unsupported tracker, or `kind: none`, means no filing: publish the slices as a Markdown list, one template block each, for the user to file.
```

2. Step 1's comment-thread sentence, tightened with no rule dropped (D2). Replace

```text
Work from the conversation. Given an issue reference, fetch and read its full body; load the comment thread only when the body points to a discussion, shows review activity, or leaves a question open.
```

with

```text
Work from the conversation. Given an issue reference, read its full body, and its comments only when the body points to a discussion, shows review activity or leaves a question open.
```

3. Step 2 gains the title rule right after its vocabulary sentence and drops the restated prefactoring rule (D4, D5, D2). Replace

```text
Explore if you haven't. Titles and descriptions use the terms of the retained `bindings.paths.context` and the knowledge capability's passed records (an authored unsupported knowledge capability takes its no-knowledge route). Look for prefactoring that makes the change easy; it is its own leading slice.
```

with

```text
Explore if you haven't. Titles and descriptions use the terms of the retained `bindings.paths.context` and the knowledge capability's passed records (an authored unsupported knowledge capability takes its no-knowledge route). A title states the outcome in plain words, never plan shorthand. Look for prefactoring that makes the change easy.
```

4. Step 3 drops the tracer-bullet gloss that the first slice rule restates (D2). Replace

```text
Each issue is a **tracer bullet**: a thin vertical slice through every integration layer, never a horizontal slice of one layer. Mark each slice human-required (needs a person's decision, review, credential or approval) or autonomous, preferring autonomous.
```

with

```text
Each issue is a **tracer bullet**, never a horizontal slice of one layer. Mark each slice human-required (needs a person's decision, review, credential or approval) or autonomous, preferring autonomous.
```

5. The wide-refactor sentence, tightened; its subject already limits it to a wide refactor, and it still names `WIDE-REFACTORS.md` (D2). Replace

```text
A wide refactor (one mechanical change with codebase-wide blast radius) cannot land green as a tracer bullet: sequence it per [WIDE-REFACTORS.md](./WIDE-REFACTORS.md) when such a candidate appears.
```

with

```text
A wide refactor (one mechanical change with codebase-wide blast radius) cannot land green as a tracer bullet: sequence it per [WIDE-REFACTORS.md](./WIDE-REFACTORS.md).
```

6. Step 4's approval sentence, tightened with no rule dropped (D2). Replace

```text
Present the breakdown as a numbered list with each slice's **title**, **type** (human-required / autonomous), **blocked by**, and **user stories covered** when the source has them. Ask whether the granularity, dependencies, merges or splits, and human/autonomous marks are right. Iterate until the user approves.
```

with

```text
Present the breakdown as a numbered list with each slice's **title**, **type** (human-required / autonomous), **blocked by**, and **user stories covered** when the source has them. Iterate on granularity, dependencies, merges, splits and marks until the user approves.
```

7. The GitLab bullet drops its copy of the record rule (D2). Replace

```text
- **GitLab**: `glab issue note <child> --message "/blocked_by #<blocker>"`; the free tier lacks native links, so the body section is the record.
```

with

```text
- **GitLab**: `glab issue note <child> --message "/blocked_by #<blocker>"`; the free tier lacks native links.
```

8. The record sentence after the bullets, tightened (D2). Replace

```text
Without a native relationship the template's "Blocked by" section is the record. A slice is unblocked when all its blockers are closed.
```

with

```text
Without native links, "Blocked by" is the record. A slice is unblocked when all its blockers are closed.
```

9. The template gains `## Problem` between Parent and What to build (D3). Replace

```text
A reference to the parent issue (omit when the source was not an issue).

## What to build
```

with

```text
A reference to the parent issue (omit when the source was not an issue).

## Problem

What happens today, who it affects and why it matters now.

## What to build
```

10. What to build's placeholder drops the file-path clause that the `measured:` sentence owns (D3, D2). Replace

```text
The slice's end-to-end behavior, not layer-by-layer steps. No file paths or code, except a prototype snippet that pins a decision better than prose (state machine, reducer, schema), trimmed to its decision and marked as from a prototype.
```

with

```text
The slice's end-to-end behavior, not layer-by-layer steps. No code, except a prototype snippet that pins a decision better than prose (state machine, reducer, schema), trimmed to its decision and marked as from a prototype.
```

11. The "body is the contract" paragraph names its reader and holds the first-use rule and the stranger read; the publishing agent rereads, and no subagent is dispatched (D4, D2). Replace

```text
The body is the contract, read weeks later in a fresh context: behavior and outcomes, no file paths outside `measured:`, no line numbers, no "as discussed above"; what an implementer needs lives in the body or a linked artifact, never only in a comment.
```

with

```text
The body is the contract, read weeks later by a stranger holding only that page: behavior and outcomes, no line numbers, nothing an implementer needs left only to a comment. Explain each glossary term, decision ID or slice label in a few words, or link it, at first use. Before publishing, reread each body as that stranger and rewrite or link any sentence that needs the spec, the plan or the conversation.
```

- [ ] **Step 4: Verify**

Run (timeout 60 s):

```bash
set -euo pipefail
f=home/common/agent-skills/skills/to-issues/SKILL.md
test "$(wc -c < "$f" | tr -d ' ')" -eq 6483
test "$(shasum -a 256 "$f" | cut -d' ' -f1)" = ec9d3d44abb17235f93c35b9f6ddbfb6f8dcfc0bcc1af19e30915e172686b811
if ! git diff --quiet 8d0bbc25383663fa3bc86623d0701e7d4bd4f9bc -- home/common/agent-skills/instruction-load.json home/common/agent-skills/skills/to-issues/WIDE-REFACTORS.md; then exit 1; fi
echo text-ok
```

Expected: `text-ok`. At the starting commit the file is 6494 bytes, so the first `test` exits 1.

Run the To-issues classes command (timeout 600 s). Expected: `Ran 4 tests`, `OK`.

Run the Skill-text suites command (timeout 900 s). Expected: `Ran 334 tests`, `OK (skipped=3)`.

Run the Budget command (timeout 600 s). Expected: last line `check: pass`. A `tightness` or over-ceiling failure means the text deviates from the dictation: report it, never edit `instruction-load.json` (D1).

- [ ] **Step 5: Run the full verification set**

This is the plan's final task, so run the full verification set from the Global Constraints (timeout 3600 s each), with the Step 3 edits in the working tree.

- `just build`. Expected: exit 0. A planning trial on this text took about 25 s with a warm store.
- `just agent-workflow-tests`. Expected: exit 0 and a last summary line `suite-runner: summary members=107 passed=107 failed=0`. The planning trial took about 16 min.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/to-issues/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- -m "feat(skills): make to-issues bodies read on their own (issue 495)"
```

The message ends with the session's attribution trailer. Report DONE with the To-issues classes and Skill-text suites counts, the Budget line and the two full-verification results.
