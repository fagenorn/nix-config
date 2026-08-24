# Task 6: Pipe and redirect checks and every remaining rewrite

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/CI-MERGE.md`
- Modify: `home/common/agent-skills/skills/ship-release/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-release/CHANGELOG.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes from Task 2: `skill_documents()`. From Task 4: `shell_commands()`, `without_placeholders()`. From Task 5: `CHAIN` is not needed, but `||` must be removed from a command before the pipe scan so a chain operator cannot be reported as a pipe.
- Produces: `REDIRECT: re.Pattern` — `re.compile(r"[<>]")`, module-level. This is the last of the four forbidden-form checks; after this task the sweep contract is complete.

**Invariants:**
- No shell command shown in a discovered skill document contains a pipe into a command, or a `<` / `>` redirect, after placeholder stripping (per D4, D17).
- The pipe scan subtracts `||` occurrences first, so a chain operator is reported by the chain check and never double-reported here — one test, one reason.
- Two sites are rewritten for **meaning**, not stripped (per D10):
  - `ship-issue/CI-MERGE.md`'s `gh pr checks <n> | grep <check>` appears **inside a prohibition** as an anti-example. Its subject is the pipe. Name the filter in prose and keep the prohibition intact and readable; do not delete the sentence and do not turn it into an instruction to run that command.
  - `ship-release/CHANGELOG.md`'s `2>/dev/null` suppresses a failure the surrounding prose relies on (no tag yet → whole history). The replacement must state what a non-zero exit means rather than silently dropping the suppression.
- Every rewrite preserves the observation the reader is told to make. A command whose output was filtered by a pipe keeps its purpose in prose: which line to read, which field to check, what "non-empty" means.
- The PR-body and release-notes files are written with the file-writing tool and passed by path, matching Task 4's `--body-file` change and the `worktrees` guidance from Task 3.
- Command substitution stays untouched; `$(…)` is out of scope and no check added here may forbid it (per D8).

## The rewrites

Read each file before editing it.

**`from-issue/SKILL.md`** — the Phase 1 pre-flight. `git worktree list | grep <worktreePrefix>issue-<num>-`
becomes `git worktree list`, with the filter in prose: look for a
`<worktreePrefix>issue-<num>-` entry. The three-way "none / one / several" branching that
follows is unchanged.

**`ship-issue/SKILL.md`** — the Phase 6 docs-only skip.
`git diff --name-only <base>..HEAD | sed 's/.*\.//' | sort -u` becomes
`git diff --name-only <base>..HEAD`, and the condition becomes: every path ends in `.md` → skip
straight to Phase 7; anything else → the phase runs normally. Keep the parenthetical about a
markdown-only diff not being able to break a build.

**`ship-issue/CI-MERGE.md`** — the "Why improvised polling is banned" paragraph. Rewrite the
anti-example so the pipe is named rather than shown: one session ran a bare `gh pr checks <n>`,
filtered for a single check, 244 times. The rest of the paragraph — the `gh run view` re-runs,
the no-op keep-alive turns, and the three "never" clauses that close it — is unchanged.

**`ship-release/SKILL.md`** — four sites:

- Pre-flight step 3: `git log origin/<default>..origin/<integration> --first-parent --merges --pretty=oneline | wc -l` non-zero becomes the same command without the pipe, and the condition becomes "output non-empty"; "Zero → nothing to release" becomes "No output → nothing to release".
- Pre-flight step 6, local-ahead: `git log --oneline --left-right LOCAL...REMOTE | head -20` becomes `git log --oneline --left-right LOCAL...REMOTE`, with "surface its first 20 lines" in the prose.
- Section 4.5c, the `bash` fence: replace
  `PREV_TAG=$(git tag --list 'v[0-9]*' --merged "$MERGE_SHA" --sort=-v:refname | head -1)` with

```bash
git tag --list 'v[0-9]*' --merged "$MERGE_SHA" --sort=-v:refname
```

  and say in the prose that the **first line** is `PREV_TAG` and no output means the bootstrap
  case. The existing explanation of why `--merged "$MERGE_SHA"` matters, and the v0.1.0
  bootstrap rule, are unchanged; later prose keeps referring to `PREV_TAG`.
- Section 4.5f, the `bash` fence: replace the `echo … >` redirect with a written file passed by
  path, so the fence becomes

```bash
${GH_PREFIX}gh pr view <pr-num> --json body -q .body

${GH_PREFIX}gh release create "$NEXT_VERSION" \
  --target <default> \
  --title "$NEXT_VERSION — <one-line scope from PR title>" \
  --notes-file <release-notes-path>
```

  with one sentence between the two commands' description: write the PR body to
  `<release-notes-path>` with the file-writing tool, then pass it by path.
- The deploy-adapter contract fence: `railway deployment list --service <name> --json` keeps its
  first line and loses the `| jq …` continuation. Move the projection into prose: read the five
  most recent entries and check `.meta.commitHash` starts with `MERGE_SHA`, `.meta.branch`
  equals `<default>`, and `.status` is `SUCCESS`. The existing success-criteria comment line in
  that fence can carry the same three facts; keep the "list, not a status summary" reasoning in
  the paragraph above it.

**`ship-release/CHANGELOG.md`** — the single-branch paragraph. Drop `2>/dev/null` from
`PREV=$(git describe --tags --abbrev=0 origin/<default>)` and state what its failure means: no
tag yet → the command exits non-zero and the range is the whole history. The `--merges` note and
the field-separator explanation are unchanged.

- [ ] **Step 1: Write the failing tests**

Add `REDIRECT` at module level, then both tests as methods of `WorkflowSkillContractsTest`.

```python
REDIRECT = re.compile(r"[<>]")
```

```python
    def test_skill_shell_examples_pipe_into_no_command(self):
        for path, text in skill_documents():
            relative = path.relative_to(REPO_ROOT)
            for line_number, command in shell_commands(text):
                bare = without_placeholders(command).replace("||", "")
                with self.subTest(path=f"{relative}:{line_number}"):
                    self.assertNotIn(
                        "|",
                        bare,
                        f"pipe in shell example: {command} — keep the command and "
                        "put the filter in prose",
                    )

    def test_skill_shell_examples_use_no_redirect(self):
        for path, text in skill_documents():
            relative = path.relative_to(REPO_ROOT)
            for line_number, command in shell_commands(text):
                with self.subTest(path=f"{relative}:{line_number}"):
                    self.assertIsNone(
                        REDIRECT.search(without_placeholders(command)),
                        f"redirect in shell example: {command} — write files with "
                        "the file-writing tool and pass bodies by path",
                    )
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `just agent-workflow-tests`

Expected: FAIL.
- `test_skill_shell_examples_pipe_into_no_command` reports seven `subTest` failures: `from-issue/SKILL.md`, `ship-issue/SKILL.md`, `ship-issue/CI-MERGE.md`, and four in `ship-release/SKILL.md` (pre-flight step 3, pre-flight step 6, 4.5c, and the adapter fence).
- `test_skill_shell_examples_use_no_redirect` reports two: `ship-release/SKILL.md` section 4.5f and `ship-release/CHANGELOG.md`.

`ship-release/SKILL.md`'s tag-existence fence must **not** appear in the redirect failures — Task 5 removed its `>/dev/null 2>&1`. If it does, Task 5's rewrite did not land and must be finished before this one.

A failure at a site not listed above is a genuine find or an extraction imprecision — read it and judge. Rewrite a real shell example by the same rule; tighten `PLACEHOLDER`, `SHELL_COMMANDS` or `command_head` for a false positive. Never add a per-site exception (per D4).

- [ ] **Step 3: Apply the rewrites**

Make exactly the changes above.

- [ ] **Step 4: Verify**

Run: `just agent-workflow-tests`

Expected: PASS — both new tests green, and the whole suite green, which at this commit means all four forbidden-form checks, both dispatch-template tests, the presence-guard test, the worktrees-guidance test, and every pre-existing test.

Then confirm the sweep is complete rather than merely passing, by running the extractor over both skill trees and printing anything the four rules would reject:

Run: `python3 -c "import pathlib,sys; sys.path.insert(0,'home/common/agent-skills/tests'); import test_workflow_skill_contracts as t; bad=[(str(p),n,c) for p,x in t.skill_documents() for n,c in t.shell_commands(x) if t.CHAIN.search(t.without_placeholders(c)) or '|' in t.without_placeholders(c).replace('||','') or t.REDIRECT.search(t.without_placeholders(c)) or t.HEREDOC.search(t.without_placeholders(c))]; print(len(bad)); print(*bad, sep=chr(10))"`

Expected: `0` and no further lines. A non-zero count with the suite green would mean a check is not reaching the extractor's full output, which is a test bug, not a prose bug.

Finally, since no `.nix` file changed in this plan, run the Nix sanity check once at the end of the task:

Run: `just build`

Expected: success. A failure here is unrelated to this plan's edits and should be reported as such, not worked around.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/CI-MERGE.md home/common/agent-skills/skills/ship-release/SKILL.md home/common/agent-skills/skills/ship-release/CHANGELOG.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
```

```bash
git commit -m "fix(agent-skills): drop pipes and redirects from every shell example"
```
