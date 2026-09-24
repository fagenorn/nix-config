# Task 4: from-issue and ship-issue rewrites

Decisions: D5, D7, D9, D11, D15, D20, D23. Work from the worktree root; paths are
repo-relative (skill paths below are under `home/common/agent-skills/skills/`).
Lands recovered hunks — the commit carries the `Recovered-From` trailer (root
Global Constraints).

**Files:**
- Modify: `from-issue/SKILL.md` (Phase 0 pre-flight sentence)
- Modify: `ship-issue/SKILL.md` (Phase 4 PR creation, Phase 6 docs-only check)
- Modify: `ship-issue/HUMAN-GATE.md` (Gate 1)
- Modify: `ship-issue/CI-MERGE.md` (banned-polling evidence)
- Modify: `ship-issue/SYNC.md` (`.claude/settings.json` row)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (Gate 1 anchor)

**Interfaces:**
- Consumes (Task 2, `test_shell_example_contracts.py`): `refused_examples` as
  amended by Task 2's fix round (lifecycle helper calls sanctioned, fence
  bodies de-indented — D23, D24, D26). Before that round lands, the findings
  probe below also prints the lifecycle calls; do not start this task then.
- Produces: rewritten skill text only; no new names.

**Invariants:**
- Every rewrite keeps the example's meaning (D7).
- ship-issue's PR creation, in both places, is the lifecycle guard's exact
  five-flag form with a literal body free of `"`, `$`, backtick and backslash;
  no `--body-file` anywhere in `ship-issue/` (D11).
- The `unset GITHUB_TOKEN &&` gh-hygiene span in `ship-issue/SKILL.md` and the
  spans in `from-issue/bindings.md` and `from-issue/REVIEW-CONTRACT.md` are
  unchanged (D5).
- #171's lifecycle helper calls and their rule prose stay byte-identical: in
  `from-issue/SKILL.md` the lifecycle-call rule and the direct-owner,
  build-delivery and finish calls; in `ship-issue/SKILL.md` the delivery-loop
  rule and the checkpoint and finish calls (D23). No line this task adds or
  removes names `workflow-state` or `artifact-budget`.
- `test_workflow_skill_contracts.py`'s Phase 4 ordering assertion
  (`check-launch`, `git push -u origin <branch>`, `check-launch`,
  `gh pr create`, ending at the first `## Summary`) still holds unedited: the
  body's first line stays `## Summary`, after `gh pr create` on the same line.

**Findings probe** (used in Steps 1 and 4; prints one line per finding, nothing
when clean):

```bash
python3 -c "import pathlib, sys; sys.path.insert(0, 'home/common/agent-skills/tests'); from test_shell_example_contracts import refused_examples; [print(p, f.line, f.form) for p in sys.argv[1:] for f in refused_examples(pathlib.Path(p).read_text(encoding='utf-8'))]" home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md home/common/agent-skills/skills/ship-issue/CI-MERGE.md home/common/agent-skills/skills/ship-issue/SYNC.md
```

- [ ] **Step 1: Update the pinned anchor and see the reds**

In `test_workflow_skill_contracts.py`, inside the Gate 1 `assert_ordered(normalized(gate_1), …)`
call, replace `'gh pr create --base <integrationBranch> --title "<title>" --body'`
with `'gh pr create --repo <repoSlug> --base <integrationBranch> --head <branch> --title "<title>" --body'`.

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py`
Expected: FAIL — the Gate 1 ordering test only.

Run the findings probe. Expected: exactly six lines, at these lines at
`a311fda` (a later sync may move the numbers, never the documents or forms) —
`from-issue/SKILL.md 440 pipe` (pre-flight); `ship-issue/SKILL.md 210 heredoc`
(PR creation) and `273 pipe` (docs-only check); `HUMAN-GATE.md 40 heredoc`;
`CI-MERGE.md 26 pipe`; `SYNC.md 61 chain`. The gh-hygiene span is the bare
sanctioned literal and the lifecycle helper calls are sanctioned (D23), so
neither yields a line. Any other line is a classifier bug or a missed site —
stop and report it rather than editing around it.

- [ ] **Step 2: Rewrite the new-work sites**

1. `from-issue/SKILL.md`, the **Pre-flight** paragraph under `## Phase 0 — Investigate`: replace
   ``Then `git worktree list | grep <worktreePrefix>issue-<num>-`:`` with
   ``Then run `git worktree list` and keep the entries whose branch — the bracketed last field of each line — starts with `<worktreePrefix>issue-<num>-`:``
   (the none/one/several bullets that follow are unchanged).
2. `ship-issue/SKILL.md`, `## Phase 4 — Open PR`: replace the whole fence that
   follows "Run `check-launch` again, then:" (the `gh pr create … "$(cat <<'EOF'`
   block through `)"`) with:

   ````
   ```
   gh pr create --repo <repoSlug> --base <integrationBranch> --head <branch> --title "<title>" --body "## Summary
   <2-4 bullets of what shipped>

   ## Spec
   <spec-path>

   ## Plan
   <plan-path>

   Closes #<num>"
   ```
   ````

   and directly after the fence add the paragraph:

   > This is the one form the lifecycle guard accepts: one command, those five flags in that order, `repoSlug` from Phase 0, and the body a single double-quoted argument that may span lines but contains no `"`, `$`, backtick or backslash. A body written to a file, a heredoc or a command substitution is refused, so render the body in place.

3. `ship-issue/HUMAN-GATE.md`, `## Gate 1`: replace the second fence (the
   heredoc `gh pr create`) with the same fence as item 2, and in the sentence
   after it replace `Present the body fully rendered — the heredoc expanded, the resolved bindings`
   with `Present the body fully rendered — the resolved bindings` (rest of the
   sentence unchanged).

- [ ] **Step 3: Re-apply the recovered hunks**

Read them with `git diff 95b6caf 3c9709ca -- home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/CI-MERGE.md home/common/agent-skills/skills/ship-issue/SYNC.md`
and apply by hand, verbatim, only these hunks:
- `ship-issue/SKILL.md` Phase 6 docs-only check → ``**Docs-only changes never wait for CI.** `git diff --name-only <base>..HEAD` — every path ends in `.md` → skip straight to Phase 7 …`` (rest of the sentence unchanged).
- `ship-issue/CI-MERGE.md` → "ran a bare `gh pr checks <n>`, filtered for a single check, 244 times, plus …" (re-wrap the paragraph lines as the hunk does).
- `ship-issue/SYNC.md` settings.json row → ``git restore --staged .claude/settings.json`, then `git checkout HEAD -- .claude/settings.json` — never include in the merge``.

Do **not** apply the retained Phase 4 `--body-file` hunk (reversed by D11), its
`env -u GITHUB_TOKEN` gh-hygiene hunk (D5) or its `.claude/skills.config.json`
"if it exists" hunks (#100).

- [ ] **Step 4: Verify**

Run the findings probe. Expected: empty output.

Run (before committing): `git diff --name-only -G "workflow-state|artifact-budget" HEAD -- home/common/agent-skills/skills/from-issue home/common/agent-skills/skills/ship-issue`
Expected: no output — no added or removed line names a lifecycle helper (D23).

Run: `git grep -n -e "--body-file" -e "env -u GITHUB_TOKEN" -- home/common/agent-skills/skills/ship-issue`
Expected: no output, exit 1.

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: `OK`.

Run: `just agent-workflow-tests`
Expected: exit 0 (a failure confined to the root's HOME-note test: follow that note).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/ship-issue home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit
```

Message: `fix(agent-skills): teach from-issue and ship-issue shell forms the checker accepts`;
the body lists the recovered hunks (ship-issue docs-only check, CI-MERGE
polling evidence, SYNC settings.json row), names the Phase 4/Gate 1 PR
creation as new work in the guard's form (D11) and the pre-flight as new work,
then the trailer paragraph with
`Recovered-From: 3c9709ca470bd473d49b39a611ca6cab258973db`.
