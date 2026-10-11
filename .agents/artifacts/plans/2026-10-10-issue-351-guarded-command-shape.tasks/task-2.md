# Task 2: The skill family states and cites the run-alone rule

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SYNC.md`
- Modify: `home/common/agent-skills/skills/ship-issue/POST-SELECTION-SYNC.md`
- Modify: `home/common/agent-skills/skills/ship-issue/CI-MERGE.md`
- Modify: `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`
- Modify: `home/common/agent-skills/tests/test_shell_example_contracts.py` (one new test class)
- Test: `home/common/agent-skills/tests/test_shell_example_contracts.py`

**Interfaces:**
- Consumes, from Task 1, in `test_shell_example_contracts.py`:
  `GUARDED_SHAPES: dict`, `ship_issue_documents() -> tuple[tuple[str, Path], ...]`,
  `guarded_command_findings(document_text: str, shapes: dict, document_name: str) -> tuple[GuardedFinding, ...]`
  and `guarded_findings_report(document: str, findings) -> str`; and the fixture
  `tests/fixtures/guarded-command-shapes.json`, whose anchor is the token
  ``` `## gh hygiene` ``` (the heading inside one pair of backticks).
- Produces: `ShipIssueGuardedCommandSweepTest`, and skill text in which every living
  example that begins with `git push`, `gh pr merge` or `git branch -d` is a fixture
  form whose block carries the anchor.

**Invariants:**
- `ship-issue/SKILL.md` keeps exactly one heading line `## gh hygiene`, unrenamed:
  `worktrees/SKILL.md` cites it for the sanctioned prefix, and the rule still spells
  that prefix as `unset GITHUB_TOKEN && `.
- The rule names the push, the merge and the branch delete in prose, with no code span
  around a guarded verb (D4, D5).
- Every command string, key and anchor that `test_workflow_skill_contracts.py` pins stays
  byte for byte: in particular `git push -u origin <branch>`, both merge spellings,
  `git push origin --delete <branch>` and `git branch -d <branch>`.
- No rule is removed: every cut below is an intro line, a restated parenthetical, a
  rationale clause or wording (D9, D13).
- The Instruction Budget gate passes with no ceiling raised and no gate file changed.
  `home/common/agent-skills/instruction-load.json` is not edited.
- `SKILL.md`'s body stays at or under 500 reflowed lines and
  `POST-SELECTION-SYNC.md` and `REVIEW.md` at or under 100 (skill-lint L2 and L3, which
  the gate reports as `lint:` lines; D13).
- Only the six documents named above change under `skills/`. The flow diagram's phase
  lines, the Phase 8 fence body and every other fence body are untouched.

What the new sentences claim was checked against the guard source at the base commit:
it accepts `git push -u origin <branch>` and `git push origin <branch>`, bare and behind
`unset GITHUB_TOKEN && `; it accepts the merge only as the whole command, bare or behind
exactly that prefix; it accepts `git branch -d <branch>` only as the whole command with
no prefix; it refuses every `--delete` push (D2); and it refuses a guarded verb written
as unquoted argument words while accepting one inside a single quoted token (D8).

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_shell_example_contracts.py`, insert this class
immediately before the line `ORCHESTRATE_SKILL = SOURCE_TREES["claude-only"] / "orchestrate-issues/SKILL.md"`
(so it follows Task 1's `GuardedCommandShapeTest`):

```python
class ShipIssueGuardedCommandSweepTest(unittest.TestCase):
    def test_every_guarded_command_is_a_cited_form(self):
        documents = ship_issue_documents()
        self.assertIn("SKILL.md", [name for name, _ in documents])
        for name, path in documents:
            with self.subTest(document=name):
                findings = guarded_command_findings(
                    path.read_text(encoding="utf-8"), GUARDED_SHAPES, name)
                self.assertEqual(
                    findings, (), guarded_findings_report(f"ship-issue/{name}", findings))
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py -k ShipIssueGuardedCommandSweepTest`
Expected: FAIL with six failing subtests, one each for `CI-MERGE.md`, `HUMAN-GATE.md`,
`POST-SELECTION-SYNC.md`, `REVIEW.md`, `SKILL.md` and `SYNC.md`. The reports name the
thirteen sites, among them `ship-issue/REVIEW.md:70: R1: git push` and
`ship-issue/SKILL.md:151: R2: git push -u origin <branch>`.

- [ ] **Step 3: Edit the skill text**

Apply the 28 edits below. Each `Old` text occurs exactly once in its file at the base
commit; replace it with its `New` text and change nothing else. A line break inside an
`Old` or `New` block is a real line break in the file. If an `Old` text is missing or
occurs twice (the file moved under a sync merge), stop and report instead of improvising.

### The edits

#### `home/common/agent-skills/skills/ship-issue/SKILL.md`

**E1.** Cut: the intro line restates the frontmatter description. Delete this line and the blank line after it:

````text
Merges a finished worktree branch into the integration branch, closes or holds its issue, cleans up.
````

**E2.** Rename: a command that is only named goes in prose (D4).

Old:

````text
`git worktree
remove` and `git branch -d` — fenced
````

New:

````text
`git worktree
remove` and the branch delete — fenced
````

**E3.** The rule (D5). It replaces the old prefix sentence; the `glab` sentence that starts at `When` stays as it is.

Old:

````text
Prefix a forge invocation only with the names in `bindings.tracker.credential_env.unset_before_invocation`; for example, an exhaustive list containing `GITHUB_TOKEN` yields `unset GITHUB_TOKEN && gh ...` when a harness token lacks access to the target org. When
````

New:

````text
Run the push, the merge and a branch delete each as its own Bash call, spelled exactly as shown: no `cd`, chain, pipe, redirection or wrapper. Read the result from that call's output or a follow-up call, never through a pipe or an appended `echo`. The only prefix unsets exactly the names in `bindings.tracker.credential_env.unset_before_invocation` (`GITHUB_TOKEN` yields `unset GITHUB_TOKEN && `) and goes only on a forge or `origin` call, never on the local branch delete. Text that only mentions one of these commands goes in one quoted argument. When
````

**E4.** Cut: wording only; all five items stay.

Old:

````text
Payload discipline: targeted `rg` over whole-file reads, bounded reads, summarized command output, logs on disk, artifacts handed over as paths.
````

New:

````text
Payload discipline: targeted `rg`, bounded reads, summarized output, logs on disk, artifacts as paths.
````

**E5.** Citation for the Phase 4 push fence. The match is the end of its paragraph.

Old:

````text
stop without pushing. Then:
````

New:

````text
stop without pushing. Then (`## gh hygiene`):
````

**E6.** Cut: wording only.

Old:

````text
A body written to a file, a heredoc or a command substitution is refused, so render the body in place.
````

New:

````text
A body from a file, a heredoc or a command substitution is refused: render it in place.
````

**E7.** Cut: the rationale is shortened.

Old:

````text
— GitHub resolves bare `#N` against the source repo context, which under cross-references lands on unrelated refs.
````

New:

````text
— a bare `#N` resolves against the source repo and can land on unrelated refs.
````

**E8.** Cut: a rationale parenthetical.

Old:

````text
skip straight to Phase 7 (a markdown-only diff cannot break a build); anything else
````

New:

````text
skip straight to Phase 7; anything else
````

**E9.** Citation for the Phase 7 merge fence. The match is the end of its paragraph.

Old:

````text
Never pass `--no-ff`.
````

New:

````text
Never pass `--no-ff`. Then (`## gh hygiene`):
````

**E10.** Citation for the remote branch delete (D2), paid for in the same paragraph.

Old:

````text
Then ask the REMOTE whether the branch still exists, `git ls-remote --heads origin <branch>`; PR metadata like `headRefName` proves nothing. Non-empty output → `git push origin --delete <branch>`.
````

New:

````text
Then ask the REMOTE whether the branch still exists, `git ls-remote --heads origin <branch>`; PR metadata proves nothing. Non-empty output → `git push origin --delete <branch>` (`## gh hygiene`).
````

**E11.** Citation for the Phase 8 local branch delete.

Old:

````text
2. Remove the worktree from the main repo root, never from inside the worktree:
````

New:

````text
2. Remove the worktree from the main repo root, never from inside the worktree (branch delete: `## gh hygiene`):
````

**E12.** Cut: wording only.

Old:

````text
with a baseline of the same project in a scratch worktree on
````

New:

````text
with a baseline run in a scratch worktree on
````

**E13.** Cut: the parenthetical restates Phase 4, which it still names.

Old:

````text
if `OPEN`, `gh issue close <num>` (the real close mechanism when retained integration and default branches differ — see Phase 4).
````

New:

````text
if `OPEN`, `gh issue close <num>` (see Phase 4).
````

**E14.** Cut: wording only.

Old:

````text
- If a phase reveals an earlier one was wrong (review surfaces a misaligned spec, say), back up to the appropriate `from-issue` phase. Don't paper over.
````

New:

````text
- If a phase shows an earlier one was wrong (a review finds a misaligned spec, say), back up to that `from-issue` phase. Don't paper over.
````

#### `home/common/agent-skills/skills/ship-issue/REVIEW.md`

**E15.** Cut: wording only.

Old:

````text
`apply` and `push` are separate steps. Follow this order:
````

New:

````text
`apply` and `push` are separate steps, in this order:
````

**E16.** The remote-less push becomes a listed form with its citation. The dropped words restate the no-write stop.

Old:

````text
on anything but `current: true`, stop without
   pushing and take the no-write stop. Then `git push`.
````

New:

````text
on anything but `current: true`, take the
   no-write stop. Then `git push origin <branch>` (`## gh hygiene`).
````

#### `home/common/agent-skills/skills/ship-issue/SYNC.md`

**E17.** Rename: the prohibited push goes in prose (D4).

Old:

````text
`git rebase`, `git push origin <integration-branch>` → **stop and surface**
````

New:

````text
`git rebase`, pushing the integration branch → **stop and surface**
````

#### `home/common/agent-skills/skills/ship-issue/POST-SELECTION-SYNC.md`

**E18.** Joins a wrapped line so the file stays at 100 reflowed lines (D13).

Old:

````text
mergeable`. The route runs
when:
````

New:

````text
mergeable`. The route runs when:
````

**E19.** Rename: a command that is only named goes in prose (D4).

Old:

````text
or `gh pr merge` was refused because
````

New:

````text
or the merge was refused because
````

**E20.** Cut: wording only.

Old:

````text
proceed to
the merge, and if the merge is then refused, the first case applies.
````

New:

````text
proceed to
the merge; if it is then refused, the first case applies.
````

**E21.** Citation for the post-selection push, wrapped so no line passes 100 characters.

Old:

````text
(SKILL.md's `## Launch guard`), then `git push origin <branch>`.
````

New:

````text
(SKILL.md's `## Launch guard`), then
   `git push origin <branch>` (`## gh hygiene`).
````

#### `home/common/agent-skills/skills/ship-issue/CI-MERGE.md`

**E22.** Rename: a command that is only named goes in prose (D4).

Old:

````text
`gh pr merge` runs local post-merge steps
````

New:

````text
The merge runs local post-merge steps
````

#### `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`

**E23.** Cut: wording only.

Old:

````text
There are up to two planned gate locations on the successful path
````

New:

````text
There are up to two gates on the successful path
````

**E24.** Rename: a command that is only named goes in prose (D4).

Old:

````text
Present Phase 4's `git push` and `gh pr create` commands
````

New:

````text
Present Phase 4's push and `gh pr create` commands
````

**E25.** Cut: wording only.

Old:

````text
Gate 1 also names that a second and final gate follows after CI and what it will
cover.
````

New:

````text
Gate 1 also names the second, final gate that follows CI and what it covers.
````

**E26.** Citation for Gate 2's remote delete. The command text the human-gate contract test pins is unchanged.

Old:

````text
- `git push origin --delete <branch>`, taken only when
````

New:

````text
- `git push origin --delete <branch>` (`## gh hygiene`), only when
````

**E27.** Citation for Gate 2's local delete. The pinned command text is unchanged.

Old:

````text
- `git branch -d <branch>`.
````

New:

````text
- `git branch -d <branch>` (`## gh hygiene`).
````

**E28.** Cut: wording only.

Old:

````text
retry only after
diagnosing the failure and re-validating
````

New:

````text
retry only after
diagnosing it and re-validating
````

- [ ] **Step 4: Verify the text**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: `Ran 33 tests`, `OK (skipped=1)`.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_eval_cases.py home/common/agent-skills/tests/test_instruction_load.py`
Expected: `OK` (skips allowed, no failure or error): the pinned machine text survived.

Run: `wc -c home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/REVIEW.md home/common/agent-skills/skills/ship-issue/SYNC.md home/common/agent-skills/skills/ship-issue/POST-SELECTION-SYNC.md home/common/agent-skills/skills/ship-issue/CI-MERGE.md home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`
Expected, when the six files started at their base-commit bytes:

| File | Base bytes | After |
|---|---|---|
| `SKILL.md` | 30838 | 30856 |
| `REVIEW.md` | 6587 | 6592 |
| `SYNC.md` | 3586 | 3578 |
| `POST-SELECTION-SYNC.md` | 6329 | 6335 |
| `CI-MERGE.md` | 1462 | 1458 |
| `HUMAN-GATE.md` | 4791 | 4778 |

- [ ] **Step 5: Run the Instruction Budget gate**

Run: `just agent-instruction-budget`
Expected: its last line is `check: pass`, with no `lint:`, `ceiling:`, `tightness:` or
`raise:` line. At the base commit the tightest ceiling leaves `SKILL.md` 28 bytes of
growth and this task uses 18.

If, and only if, the gate prints a `ceiling:` line (the base moved under a sync merge),
apply these reserve cuts to `SKILL.md`, in order, rerunning the gate after each:

1. `Throughout, follow` → `Follow` (the sentence about Payload discipline).
2. `— the "discarded N commits" wording is misleading; the content is on the integration branch.`
   → `— its "discarded N commits" wording misleads: the content is on the integration branch.`

If the gate still fails, or prints a `lint:` or `raise:` line, stop and report the
gate's output. Do not edit `instruction-load.json`, do not remove a rule, and do not ask
for the `instruction-budget-raise` label: only the user grants a raise (D9).

Scope check: `git status --short` lists exactly the seven files of this task.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/REVIEW.md home/common/agent-skills/skills/ship-issue/SYNC.md home/common/agent-skills/skills/ship-issue/POST-SELECTION-SYNC.md home/common/agent-skills/skills/ship-issue/CI-MERGE.md home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md home/common/agent-skills/tests/test_shell_example_contracts.py
git commit -m "docs(skills): ship-issue states the run-alone shape of its guarded commands (#351)"
```
