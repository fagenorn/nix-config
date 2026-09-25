# Task 4: State the root and the verbatim relay in living docs and skills

Decisions: D3, D6, D7. Spec §5 "Where the root is stated" and test seam 4.
Work from the worktree root. Every shell block starts with `set -euo pipefail` (`set -uo pipefail` in a
watch-it-fail step)
and these abbreviations, which the blocks below omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
FI=home/common/agent-skills/skills/from-issue/SKILL.md
OI=home/common/claude-code/skills/orchestrate-issues/SKILL.md
```

**Files:**
- Modify: `CLAUDE.md` (the "Delivery objects are built" sentence in the "Claude
  Code is declaratively managed" list)
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (the
  `delivery_contract` paragraph of "### Direct autonomous acquisition")
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (two
  bullets under "**Per-issue contract rule.**" in "## 3. Decide")
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (two
  constants and one `WorkflowSkillContractsTest` method)

**Interfaces:**
- Consumes (Tasks 1–3): the committed behaviour. That is the refusal line
  `workflow-state: resolve-project refused at <repo-root|worktree>: <document>`,
  the worktree veto `build-delivery refused: worktree policy differs from
  repo-root policy: …`, and the `build-delivery --help` description.
- Produces: two module constants, `BUILD_ROOT_CLAUSE` and `BUILD_REFUSAL_RELAY`,
  whose exact text appears in both contract-building skills.

**Invariants:**
- Every sentence added here describes Tasks 1–3's code as committed. Step 1
  checks each claim before any prose is written (plan-prose ≠ code-prose).
- The pinned sanctioned-exception sentence
  (`only sanctioned exception is `workflow-state build-delivery`, which performs its own sealed, read-only resolution`),
  `SK/ship-issue/SKILL.md`, `SK/from-issue/ship-handoff.md`, from-issue's
  "### Explicit durable interactive acquisition" and the `OI/evals/evals.json`
  expectations are unchanged (D7).
- Existing pinned anchors keep matching. In orchestrate's "## 3. Decide" those
  are `workflow-state build-delivery`, `report the refusal`,
  `while its latest summary carries `delivery_contract_required`` and
  `only when this invocation created the run`. In from-issue's direct section
  they are `--kind contract` and `` `delivery_contract` ``.
- `CLAUDE.md` keeps its `@.agents/instructions/bootstrap.md` import line, and
  only the one sentence changes.
- Hard-wrap each skill edit to match its surrounding lines. from-issue's
  paragraph is indented three spaces inside its list item, and orchestrate's
  bullets continue at two spaces.

- [ ] **Step 1: Confirm the claims against the code**

```bash
COLUMNS=400 python3 $S/workflow-state.py build-delivery --help | tr -s ' \n' ' ' | grep -c 'resolves project policy with resolve-project at --repo-root, the ledger repository root, and seals only that policy'
grep -c 'resolve-project refused at {label}: ' $S/workflow-state.py
grep -c 'resolve_project_policy(worktree, "worktree")' $S/workflow-state.py
grep -c 'worktree policy differs from repo-root policy: ' $S/workflow_delivery_build.py
```

Expected: `1`, `1`, `1` and `1`. If any line prints `0` or the block aborts,
stop: the prose below would then be false. `COLUMNS=400` keeps argparse from
wrapping, and so from breaking `--repo-root` at its hyphen.

- [ ] **Step 2: Write the failing skill pin**

In `T/test_workflow_skill_contracts.py`, add these constants directly after
`STDIN_CLAUSE`:

```python
BUILD_ROOT_CLAUSE = ("The builder seals the policy `resolve-project` resolves at "
                     "`--repo-root`, the ledger repository root; when `worktree` already "
                     "exists, it also resolves there and refuses if any sealed policy "
                     "member differs.")
BUILD_REFUSAL_RELAY = ("report the builder's stderr line verbatim: for a resolver refusal "
                       "it carries the resolver's `error.code`, `repair_id` and ordered "
                       "`violations` exactly.")
```

In `class WorkflowSkillContractsTest`, add this method directly after
`test_direct_and_control_requests_are_interface_two`:

```python
    def test_contract_builders_state_the_resolution_root_and_relay_refusals(self):
        direct = normalized(self.section(self.from_issue, "### Direct autonomous acquisition",
                                         "### Interactive direct acquisition"))
        decide = normalized(self.section(self.orchestrate, "## 3. Decide",
                                         "## 4. Execute control actions"))
        for skill, text in (("from-issue", direct), ("orchestrate-issues", decide)):
            with self.subTest(skill=skill):
                self.assertIn(BUILD_ROOT_CLAUSE, text)
                self.assertIn(BUILD_REFUSAL_RELAY, text)
```

Run: `PYTHONPATH=python python3 -m unittest $T/test_workflow_skill_contracts.py -k test_contract_builders_state 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'`
Expected: `Ran 1 test` and `FAILED (failures=2)`, one failure per skill subtest.

- [ ] **Step 3: Edit the two skills**

In `$FI`, the paragraph after the `--kind contract` code block contains, as
consecutive text,
`helper refuses a contract naming any other. Put the printed `contract` in`
and later
`` `authorization_intents`. A builder refusal (exit 2, empty stdout) fails ``
`loudly. For the duration of this acquisition,`. Make two insertions and leave
the rest of the paragraph unchanged.

1. Between `naming any other.` and ` Put the printed`, insert
   ` The builder seals the policy `resolve-project` resolves at `--repo-root`, the ledger repository root; when `worktree` already exists, it also resolves there and refuses if any sealed policy member differs.`
2. Replace `fails loudly. For the duration` with
   `fails loudly; report the builder's stderr line verbatim: for a resolver refusal it carries the resolver's `error.code`, `repair_id` and ordered `violations` exactly. For the duration`.

In `$OI`, under "**Per-issue contract rule.**":

1. The `worktree` bullet ends
   `contract whose worktree differs from the recorded path.` Append
   ` The builder seals the policy `resolve-project` resolves at `--repo-root`, the ledger repository root; when `worktree` already exists, it also resolves there and refuses if any sealed policy member differs.`
2. Replace the refusal bullet, which begins
   `- On a builder refusal (exit 2, empty stdout, the rule named on stderr), send`
   and ends `issue stays lifecycle-only.`, with:

```markdown
- On a builder refusal (exit 2, empty stdout, the rule named on stderr), send
  null and `[]` for that issue and report the refusal in the final report; that
  issue stays lifecycle-only. For the refusal, report the builder's stderr line
  verbatim: for a resolver refusal it carries the resolver's `error.code`,
  `repair_id` and ordered `violations` exactly.
```

Re-wrap only the lines you touched, to the width of their neighbours.

- [ ] **Step 4: Edit the `CLAUDE.md` sentence**

The line beginning `  - Delivery objects are built, never hand-composed:`
occurs exactly once. Within it, make two replacements.

1. Replace
   `derives the `delivery-contract/v1` and its initial authorization intent from `resolve-project` policy, and seals`
   with
   `derives the `delivery-contract/v1` and its initial authorization intent from the `resolve-project` policy at `--repo-root` (the ledger repository root, the only policy it seals; when the input worktree already exists it resolves there too and refuses if any sealed member differs), and seals`.
2. Replace
   `refuses anything it cannot derive with exit 2 and empty stdout.`
   with
   `refuses anything it cannot derive with exit 2 and empty stdout; when `resolve-project` refuses, the one stderr line carries the resolver's error document unchanged.`

- [ ] **Step 5: Verify the text**

```bash
PYTHONPATH=python python3 -m unittest $T/test_workflow_skill_contracts.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
grep -c 'policy at `--repo-root` (the ledger repository root, the only policy it seals;' CLAUDE.md
grep -c "the one stderr line carries the resolver's error document unchanged\." CLAUDE.md
grep -cx '@.agents/instructions/bootstrap.md' CLAUDE.md
git diff --numstat -- CLAUDE.md
if grep -n 'fails loudly\. For the duration' $FI; then exit 1; fi
```

Expected: `OK` for the whole skill-contract file. Then `1`, `1` and `1`, then
`1	1	CLAUDE.md`, and the `if grep` finds nothing. Summarize any failure to its
test ids.

- [ ] **Step 6: Final gate**

```bash
LOG="${TMPDIR:-/tmp}"; LOG="${LOG%/}/issue-181-build.log"
WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
if just build > "$LOG" 2>&1; then echo build-ok; else grep -E 'error:' "$LOG" | head -20; exit 1; fi
git status --short
```

Expected: `Ran 1240 tests …` and `OK (skipped=2)`. That is the base count of 1228
at `2e78e5e` plus this plan's 12 tests, and it grows only if a sync merge adds
tests. `WORKFLOW_POLICY_SURFACE=source` is the spelling CI uses. Without it,
`test_installed_policy_surface_matches_source_contract` reads this machine's
activated `~/.agents/skills`, which predates the branch. The suite takes about 6
minutes. The build prints `build-ok`, and `git status --short` shows only this
task's four files before the commit.
Summarize any failure to its test ids or `error:` lines. Never run `just switch`.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md $FI $OI $T/test_workflow_skill_contracts.py
git commit -m "docs: state build-delivery's resolution root and verbatim refusal relay" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
