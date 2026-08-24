# Task 4: Workspace documentation and the `.superpowers/` allowlist

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/scripts/task-brief`
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/worktrees/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: `sdd-workspace`'s post-Task-3 output shape — `<primary>/.superpowers/sdd/{primary|wt-<worktree-name>}/<plan-basename>` — and `normalized(text)` / `corpus_documents()` from Task 1. **Task 3 must land first**: this task's prose asserts behaviour Task 3 implements, and dictating it earlier would put a false sentence in the corpus.
- Produces: the module-level constants `SDD_SCRIPTS`, `REPO_ROOT_WORKSPACE_LITERAL`, `SUPERPOWERS_SEGMENTS`, `SUPERPOWERS_SEGMENT_RE`, `SHIP_REVIEW_EXCEPTION`, `WORKTREE_BUCKET_LITERAL`, `CLEAN_SCRATCH_CLAUSE`.

**Invariants:**
- No skill document and no file under `sdd/scripts/` claims a repo-root-relative workspace. The literal `<repo-root>/.superpowers/sdd` sits in exactly two files today (`sdd/SKILL.md`, `sdd/scripts/task-brief`) and must sit in none afterwards.
- The `.superpowers/` segment set is closed *and* exact: `{workflows, issue-delivery, sdd, ship-review}`. Asserting equality rather than containment means a new home fails the test and a vanished home fails it too, so the assertion cannot go vacuous.
- `.superpowers/ship-review` appears in exactly one corpus file, and that file says why it is allowed to be worktree-local (per D7).
- `task-brief`'s and `review-package`'s calls into `sdd-workspace` are not touched — only `task-brief`'s header comment changes.
- The per-checkout bucket introduced by Task 3 is the one piece of workflow scratch nothing reclaims: `sdd/SKILL.md` deletes a plan workspace only on the **Clean** terminal state and deliberately keeps it on **Residuals**, and worktree names are deterministic (`worktreePrefix` + issue number) while the ledger's identity line is only `# SDD ledger — plan: <plan file path>`. So a recreated worktree of the same name, running the same plan basename, resolves to the same bucket and the same ledger. `ship-issue` — the one flow that removes a feature worktree — is where that bucket gets pruned; nowhere else may delete a bucket.
- Only the removed worktree's own bucket is pruned. `primary/` and every other `wt-*` bucket are untouched (per D8).

Cites D3, D5, D7, D8, D10.

- [ ] **Step 1: Write the failing tests**

Add at module level, beside the Task 1 constants:

```python
SDD_SCRIPTS = REPO_ROOT / "home/common/agent-skills/skills/sdd/scripts"

# The superseded claim: the workspace has not been repo-root-relative since the
# primary-checkout move (D3).
REPO_ROOT_WORKSPACE_LITERAL = "<repo-root>/.superpowers/sdd"

# Every `.superpowers/` home the corpus is allowed to name, spelled once (D10).
SUPERPOWERS_SEGMENTS = {"workflows", "issue-delivery", "sdd", "ship-review"}
SUPERPOWERS_SEGMENT_RE = re.compile(r"\.superpowers/([A-Za-z0-9_.-]+)")

SHIP_REVIEW_EXCEPTION = (
    "the one exception to the rule that workflow scratch never lives in a "
    "working tree"
)

# The orphaned-bucket prune, spelled once (D5, D8).
WORKTREE_BUCKET_LITERAL = "`<primary-checkout>/.superpowers/sdd/wt-<worktree-name>/`"

# What `git clean -fdx` actually destroys after Task 3 moved the ledger out of
# the feature worktree.
CLEAN_SCRATCH_CLAUSE = (
    "in a feature worktree that is `ship-issue`'s retained Minor/Discussion "
    "detail, and in the primary checkout it is every plan's SDD workspace"
)
```

Add these six tests to `WorkflowSkillContractsTest`:

```python
    def test_sdd_documents_the_primary_rooted_bucketed_workspace(self):
        text = normalized(self.sdd)
        self.assertIn(
            "`<primary-checkout>/.superpowers/sdd/<checkout-bucket>/<plan-basename>/`",
            text,
        )
        self.assertIn(
            "`primary` for the primary checkout itself and `wt-<worktree-name>` "
            "for a linked worktree",
            text,
        )
        self.assertIn(
            "`git clean -fdx` in the primary checkout destroys the workspace",
            text,
        )

    def test_no_document_or_script_claims_a_repo_root_workspace(self):
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path, text in corpus_documents()
            if REPO_ROOT_WORKSPACE_LITERAL in text
        ]
        offenders += [
            str(path.relative_to(REPO_ROOT))
            for path in sorted(SDD_SCRIPTS.iterdir())
            if path.is_file()
            and REPO_ROOT_WORKSPACE_LITERAL in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_superpowers_homes_are_a_closed_allowlist(self):
        found: dict[str, set[str]] = {}
        for path, text in corpus_documents():
            for match in SUPERPOWERS_SEGMENT_RE.finditer(text):
                found.setdefault(match.group(1), set()).add(
                    str(path.relative_to(REPO_ROOT))
                )
        self.assertEqual(set(found), SUPERPOWERS_SEGMENTS, found)

    def test_ship_review_is_the_single_documented_exception(self):
        carriers = [
            str(path.relative_to(REPO_ROOT))
            for path, text in corpus_documents()
            if ".superpowers/ship-review" in text
        ]
        self.assertEqual(
            carriers, ["home/common/agent-skills/skills/ship-issue/REVIEW.md"]
        )
        self.assertIn(SHIP_REVIEW_EXCEPTION, normalized(self.ship_review))

    def test_ship_issue_prunes_the_removed_worktrees_sdd_bucket(self):
        text = normalized(self.ship_issue)
        self.assertIn(WORKTREE_BUCKET_LITERAL, text)
        self.assertIn("Remove only that one worktree's bucket", text)

    def test_worktrees_names_the_scratch_git_clean_destroys(self):
        text = normalized(self.worktrees)
        self.assertIn(CLEAN_SCRATCH_CLAUSE, text)
        self.assertNotIn("(ledgers, review packages)", text)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k primary_rooted -k repo_root_workspace -k closed_allowlist -k single_documented_exception -k sdd_bucket -k git_clean_destroys -v`

Expected: five FAIL, one pass. `test_ship_issue_prunes_the_removed_worktrees_sdd_bucket` fails because no prune is documented anywhere, and `test_worktrees_names_the_scratch_git_clean_destroys` fails on the stale parenthetical still present at `worktrees/SKILL.md:14`. `test_sdd_documents_the_primary_rooted_bucketed_workspace`, `test_no_document_or_script_claims_a_repo_root_workspace` (offenders: `sdd/SKILL.md` and `sdd/scripts/task-brief`) and `test_ship_review_is_the_single_documented_exception` (the rationale sentence is absent) all fail. `test_superpowers_homes_are_a_closed_allowlist` passes at the base commit — verified: the corpus names exactly those four segments today — and is the pin that stops a fifth home being introduced without review. Do not weaken it to make it "fail first".

- [ ] **Step 3: Rewrite the five documents**

In `home/common/agent-skills/skills/sdd/SKILL.md`, replace the workspace bullet (around line 26) with, exactly:

```markdown
- Each plan owns a workspace: `scripts/sdd-workspace PLAN_FILE` prints the plan's git-ignored directory beneath the **primary checkout** — `<primary-checkout>/.superpowers/sdd/<checkout-bucket>/<plan-basename>/`, where `<checkout-bucket>` is `primary` for the primary checkout itself and `wt-<worktree-name>` for a linked worktree — home to every artifact for THIS plan: ledger, briefs, reports, review packages. It is never rooted at your cwd, so running from a linked worktree leaves no nested ledger inside it. Another plan's directory, and another checkout's bucket, is never yours to read or write.
```

In the same file, replace the parenthetical in the compaction bullet (around line 29) so it names the checkout that actually holds the workspace:

```markdown
- After compaction, trust the ledger and `git log` over recollection. (`git clean -fdx` in the primary checkout destroys the workspace; recover from `git log`.)
```

In `home/common/agent-skills/skills/sdd/scripts/task-brief`, replace the header lines 5–8 with:

```bash
# Usage: task-brief PLAN_FILE TASK_NUMBER [OUTFILE]
# Default OUTFILE: <workspace>/task-<N>-brief.md, where <workspace> is whatever
# sdd-workspace prints for PLAN_FILE — the primary checkout's
# .superpowers/sdd/<checkout-bucket>/<plan-basename>/, never a directory under
# the process cwd. Concurrent runs of the SAME plan from the SAME checkout
# share it.
```

Change no executable line of `task-brief`. The `sdd-workspace` invocation at line 47, the `mktemp`/`trap`/`cp`/`mv` sequence and the budget check all stay exactly as they are.

In `home/common/agent-skills/skills/ship-issue/REVIEW.md`, under "## Durable Minor/Discussion detail", insert this sentence immediately after "First, write the retained candidate at `.superpowers/ship-review/<issue>/retained-detail.json` in the feature worktree." and before "Run `artifact-budget validate-detail-input` …":

```markdown
That worktree-local path is deliberate and is the one exception to the rule that workflow scratch never lives in a working tree: on publication failure this flow re-reads the retained candidate and keeps the worktree, so the candidate's lifetime is meant to be the worktree's. Do not relocate it to `$TMPDIR` or the primary checkout.
```

Re-wrap to the file's ~80-column width; the tests normalize whitespace.

In `home/common/agent-skills/skills/ship-issue/SKILL.md`, in the numbered cleanup
step "Remove the worktree from the main repo root, never from inside the
worktree" (around line 227), append this paragraph immediately after that step's
fenced command block, at the step's three-space list indentation:

```markdown
   After the worktree is gone, remove that worktree's now-orphaned SDD bucket at
   `<primary-checkout>/.superpowers/sdd/wt-<worktree-name>/`. Nothing else prunes it:
   the bucket lives in the primary checkout and outlives the worktree that named it,
   so a later worktree recreated under the same name would resolve to this attempt's
   ledger and read its `Task <N>: complete` lines as its own. Remove only that one
   worktree's bucket — never `primary/`, and never another worktree's.
```

Do not touch the fenced command block itself, the `git worktree remove` /
`git worktree prune` / `git branch -d` sequence, or the numbered items around it.

In `home/common/agent-skills/skills/worktrees/SKILL.md`, replace the last sentence
of the paragraph at line 14 — currently

> `git clean -fdx` also deletes git-ignored scratch (ledgers, review packages) that a run in progress depends on.

with

> `git clean -fdx` also deletes git-ignored scratch a run in progress depends on: in a feature worktree that is `ship-issue`'s retained Minor/Discussion detail, and in the primary checkout it is every plan's SDD workspace.

After Task 3 the `sdd` ledger and its review packages no longer sit in the
feature worktree, so the old parenthetical names the wrong files for the wrong
checkout — the same correction this task makes to `sdd/SKILL.md`. Leave the rest
of that paragraph, and the whole "Destructive-ops carve-out" section around it,
untouched.

- [ ] **Step 4: Verify**

```bash
python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -v 2>&1 | tail -5
```
Expected: `OK` — all six new tests pass and nothing regresses.

```bash
python3 -m unittest home/common/agent-skills/tests/test_task_brief.py -v 2>&1 | tail -5
```
Expected: `OK`, 3 tests — proof the header edit did not disturb `task-brief`'s behaviour.

```bash
if git diff HEAD -- home/common/agent-skills/skills/sdd/scripts/task-brief \
   | grep -E '^[+-]' | grep -vE '^(\+\+\+|---)' | grep -qvE '^[+-]#'; then
  echo "a non-comment line of task-brief changed"; exit 1
fi
echo comment-only
```
Expected: `comment-only` — every changed line in `task-brief` is a comment line. Any executable change fails the gate.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/SKILL.md \
        home/common/agent-skills/skills/sdd/scripts/task-brief \
        home/common/agent-skills/skills/ship-issue/REVIEW.md \
        home/common/agent-skills/skills/ship-issue/SKILL.md \
        home/common/agent-skills/skills/worktrees/SKILL.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(agent-skills): describe the primary-rooted workspace, its exception, and bucket cleanup"
```
