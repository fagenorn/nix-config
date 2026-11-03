# Task 1: Readable PR body template and inline fallback

This task covers spec § Target text — `SKILL.md` Phase 4 and § Target text — from-issue's inline fallback. The PR body opens with Why, What changes, Evidence and Merge danger, then one collapsed Delivery record that holds the spec and plan links, the unchanged `## Acceptance` section and the notes. `Closes #<num>` stays last and outside the block (per D2, D3). The Phase-4 prose is compressed to pay for the template (per D10). Phase 2's and Phase 5's note sites, and `REVIEW.md`, are left for Task 2. Until Task 2, they still name the old Summary (per D11).

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (the `gh pr create` fence in `## Phase 4 — Open PR`, the paragraphs between that fence and `## Phase 5 — Review the PR`, and the **Hold** bullet of `## Phase 8 — Cleanup` step 1)
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md` (`## Inline fallback (no ship-issue skill)` only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes, from the module as it is at the base: `re`, `normalized(text)`, `SHIP_ISSUE_MACHINE_TEXT`, and in `WorkflowSkillContractsTest` the methods `assert_ordered(text, *anchors)` and `section(text, heading, next_heading)` and the class attributes `ship_issue` and `ship_handoff`.
- Produces, for Task 2: the module tuple `INLINE_FALLBACK_MARKUP`, which ends in the two lines `    "Delivery record",` and `)`, and is the last of five new constants placed directly after `SHIP_ISSUE_MACHINE_TEXT`. Also the method `test_inline_fallback_names_the_readable_body`, the last of two new methods placed directly after `test_ship_issue_documents_carry_their_machine_text`. Task 2 inserts its own code right after each.

**Invariants:**
- `SKILL.md` holds exactly one fenced `gh pr create … --body "…"` block. In its body, these appear in order: `## Why`, `## What changes`, `## Evidence`, `## Merge danger`, `<details><summary>Delivery record</summary>`, `Spec: `, `plan: `, `## Acceptance`, the two `Acceptance …:` lines, `<acceptance table>`, `<review and verification notes>`, `</details>`, `Closes #<num>`.
- The body has no `## Summary`. Each of `Acceptance state: <effective acceptance state>`, `Acceptance record: <record-path or none>`, `<acceptance table>` and `Closes #<num>` occurs exactly once, and the body has no `"`, `$`, backtick or backslash.
- from-issue's inline fallback names `` `## Why` ``, `` `## What changes` ``, `` `## Evidence` ``, `` `## Merge danger` ``, `` `<details>` `` and `Delivery record`, in that order.
- `SHIP_ISSUE_MACHINE_TEXT`, `HUMAN-GATE.md`, `REMAINDER.md` and `REVIEW.md` are byte-identical. Phase 2, Phase 5 and Phase 6 of `SKILL.md` are unchanged.
- The Budget command passes. `SKILL.md` ends at 500 reflowed lines, its L2 ceiling, so this task has no line to spare.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

1. Directly after the closing `}` of `SHIP_ISSUE_MACHINE_TEXT`, before the blank line and the `# "sibling <=2 words> candidate"` comment, insert one blank line and then:

````python
# The ship-issue PR body template (#494 D2, D3, D9): the one fenced
# `gh pr create` whose double-quoted body the agent renders verbatim. Its
# markup is pinned in reading order; no placeholder sentence is.
PR_BODY_TEMPLATE_RE = re.compile(r'```\ngh pr create [^\n]*--body "(.*?)"\n```', re.S)
PR_BODY_MARKUP = (
    "## Why", "## What changes", "## Evidence", "## Merge danger",
    "<details><summary>Delivery record</summary>", "Spec: ", "plan: ", "## Acceptance",
    "Acceptance state: <effective acceptance state>",
    "Acceptance record: <record-path or none>", "<acceptance table>",
    "<review and verification notes>", "</details>", "Closes #<num>",
)
PR_BODY_ONCE = (
    "Acceptance state: <effective acceptance state>",
    "Acceptance record: <record-path or none>", "<acceptance table>", "Closes #<num>",
)
# What the lifecycle guard refuses in a pr-create body.
PR_BODY_UNSAFE = ('"', "$", "`", "\\")
INLINE_FALLBACK_MARKUP = (
    "`## Why`", "`## What changes`", "`## Evidence`", "`## Merge danger`", "`<details>`",
    "Delivery record",
)
````

2. In `WorkflowSkillContractsTest`, directly after `test_ship_issue_documents_carry_their_machine_text`, add:

```python
    def test_ship_issue_pr_body_reads_first_then_records(self):
        bodies = PR_BODY_TEMPLATE_RE.findall(self.ship_issue)
        self.assertEqual(len(bodies), 1)
        body = bodies[0]
        self.assert_ordered(body, *PR_BODY_MARKUP)
        self.assertNotIn("## Summary", body)
        for line in PR_BODY_ONCE:
            with self.subTest(line=line):
                self.assertEqual(body.count(line), 1)
        for character in PR_BODY_UNSAFE:
            with self.subTest(character=character):
                self.assertNotIn(character, body)

    def test_inline_fallback_names_the_readable_body(self):
        fallback = self.section(self.ship_handoff, "## Inline fallback (no ship-issue skill)",
                                "## Remainder owner prompt")
        self.assert_ordered(normalized(fallback), *INLINE_FALLBACK_MARKUP)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the PR body cases command (timeout 600 s). Expected: `Ran 2 tests` and `FAILED (failures=2)`. The two failures are `AssertionError: -1 == -1 : missing anchor: '## Why'` in `test_ship_issue_pr_body_reads_first_then_records` and ``… missing anchor: '`## Why`'`` in `test_inline_fallback_names_the_readable_body`.

- [ ] **Step 3: Write the minimal implementation**

Make exactly these edits. Each `old` text occurs exactly once at the starting commit.

**(a) The Phase-4 template.** In `SKILL.md`, the fence after `Run `check-launch` again, then:` holds 17 lines, from `gh pr create --repo <resolved-repository> --base <integration> --head <branch> --title "<title>" --body "## Summary` through `Closes #<num>"`. Replace them so the whole fence reads:

````text
```
gh pr create --repo <resolved-repository> --base <integration> --head <branch> --title "<title>" --body "## Why
<1-3 sentences: what was wrong or missing and who notices, with the issue URL>
## What changes
<smallest sketch (diff, call tree or before/after) indented 4 spaces, then 2-4 plain bullets>
## Evidence
<before and after: the failing test that now passes, output or behaviour>
## Merge danger
<one- or two-way door; blast radius in a word; rollout and rollback>
<details><summary>Delivery record</summary>

Spec: <blob URL>, plan: <blob URL>
## Acceptance
Acceptance state: <effective acceptance state>

Acceptance record: <record-path or none>

<acceptance table>

<review and verification notes>
</details>

Closes #<num>"
```
````

The blank lines are exactly those shown: after the `<summary>` line, around the two `Acceptance` lines and the table, and after `</details>`. There are none between the four sections (per D2).

**(b) The paragraphs after the fence.** At the starting commit, five one-line paragraphs sit between the fence's closing line and `## Phase 5 — Review the PR`. They begin `This is the one form the lifecycle guard accepts`, `The `## Acceptance` section always appears.`, `Title: the issue title verbatim`, `GitHub auto-close on merge fires` and `**Use full URLs, not bare `#N`**`. Replace those five with exactly these three one-line paragraphs, keeping one blank line before each and one blank line before `## Phase 5`:

```text
This is the one form the lifecycle guard accepts: one command, those five flags in that order, `<resolved-repository>` the retained `bindings.tracker.repo_slug`, and the body a single double-quoted argument that may span lines but contains no `"`, `$`, backtick or backslash. A body from a file, a heredoc or a command substitution is refused: render it in place. Above `<details>`, explain or link each domain term on first use and name no internal ID (decision, finding, slice or `ACn`). Title: the issue title verbatim unless the implementation deviated meaningfully; under 70 chars.

The `## Acceptance` section always appears. `Acceptance state:` carries the effective value, and `Acceptance record:` carries the record's repository-relative path or `none`. With a record, `<acceptance table>` is a Markdown table with the columns `AC`, `Criterion`, `Kind` and `Verdict`, one row per record row, copying its closed tokens and its claim before `— measured:`; without one, drop that line. On a **hold** drop the `Closes #<num>` line too: a hold body carries no closing keyword (any form of close, fix or resolve before an issue reference), so the merge cannot close the issue. GitHub auto-closes only on a merge into the **default branch**; otherwise Phase 8's `gh issue close <num>` closes the issue, and the close branch keeps `Closes #<num>` for traceability.

**Use full URLs, not bare `#N`**, in PR bodies, comments, and commit-message references (`https://github.com/<resolved-repository>/issues/<n>`; spec and plan as blob URLs at the pushed head) — a bare `#N` resolves against the source repo. The `Closes #<num>` trailer is the one exception.
```

These carry D8's readability rule, D5's four-column table and D4's blob URLs. The title rule, auto-close and keyword list are shortened per D10.

**(c) The Phase-8 hold comment.** In the **Hold** bullet of `## Phase 8 — Cleanup` step 1, replace

```text
the PR body's three-column table and the record's link at the merge SHA (`https://github.com/<resolved-repository>/blob/<merge-sha>/<record-path>`).
```

with

```text
the PR body's acceptance table and the record's blob URL at the merge SHA.
```

The rest of the bullet, including `Held for verification: <PR URL>`, is unchanged (per D4, D5).

**(d) The inline fallback's body.** In `ship-handoff.md` § Inline fallback, replace

```text
The PR body carries `Closes #<num>` only when
```

with

```text
The PR body has `## Why`, `## What changes`, `## Evidence` and `## Merge danger`, then a collapsed `<details>` Delivery record; it carries `Closes #<num>` only when
```

**(e) The inline fallback's close clause.** Replace these two lines

```text
the issue when the sdd report's `acceptance_state` is `met` or `not_applicable`;
otherwise hold it with ship-issue Phase 8 step 1's hold sequence, in its order:
```

with this one line, without re-wrapping it or the lines around it (per D7):

```text
the issue on that condition; otherwise hold it with ship-issue Phase 8 step 1's hold sequence, in its order:
```

- [ ] **Step 4: Verify**

Run the PR body cases command (timeout 600 s). Expected: `Ran 2 tests`, `OK`.

Run the Skill contract tests command (timeout 900 s). Expected: `Ran 295 tests`, `OK (skipped=3)`. That run includes AC2's unchanged cases.

Run (timeout 60 s):

```bash
set -euo pipefail
if git grep -n -e 'three-column' -e '<merge-sha>/<record-path>' -e 'can land on unrelated refs' -- home/common/agent-skills/skills/ship-issue/SKILL.md; then exit 1; fi
test "$(grep -c -F 'the issue on that condition; otherwise hold it' home/common/agent-skills/skills/from-issue/ship-handoff.md)" -eq 1
git diff --quiet HEAD -- home/common/agent-skills/skills/ship-issue/REVIEW.md home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md home/common/agent-skills/skills/ship-issue/REMAINDER.md home/common/agent-skills/instruction-load.json
echo template-ok
```

Expected: `template-ok`. At the starting commit, the `git grep` prints two lines of `SKILL.md`, the full-URL paragraph and the **Hold** bullet, and the script exits 1.

Run the Budget command (timeout 600 s). Expected: the last line is `check: pass`. As measured on the prototype, ship-owner hot is 51949 of 52076 B, implementation-owner hot is 132682 of 132694 B, and `SKILL.md` is at 500 reflowed lines.

Run the Installed tier command (timeout 3600 s). Expected: the last line is `OK` or `OK (skipped=N)`, with no `FAIL` or `ERROR`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- -m "feat(ship-issue): open PRs with a readable body and a collapsed Delivery record (issue 494)"
```

The message ends with the session's attribution trailer. Report DONE with the two test counts and the Budget line.
