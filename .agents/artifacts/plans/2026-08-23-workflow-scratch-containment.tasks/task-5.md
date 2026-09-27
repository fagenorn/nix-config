# Task 5: Tracked `.gitignore` backstop

**Files:**
- Modify: `.gitignore`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: nothing from earlier tasks; the test uses only `REPO_ROOT`, already defined at module level.
- Produces: the module-level constants `GITIGNORE`, `SCRATCH_IGNORE_PATTERNS`, `IGNORED_SHAPES`, `KEPT_SHAPES`.

**Invariants:**
- All six patterns are present as whole lines, so a reformatting that folds them into a comment fails the test.
- `.superpowers/` and `.worktrees/` carry no internal slash, so git matches them at every depth — including inside a linked worktree. Do not "tidy" them to `/.superpowers/`.
- The ignore behaviour is checked in a throwaway repository, never in this one: this repository's `.git/info/exclude` already ignores the same shapes, so an in-place `git check-ignore` would pass with an empty `.gitignore` (per D12).
- The throwaway repository is run with the user's global and system git config disabled, so a machine-local `core.excludesFile` cannot decide a keep shape for us.
- `handoff-*.md` is deliberately NOT a pattern: `handoff`'s durable destination is already inside `.superpowers/workflows/` and its nondurable candidate is in `$TMPDIR`, so the pattern would only risk masking a real document (per D6).
- `.git/info/exclude` is left exactly as it is. It becomes redundant, not wrong.

**Risk lane:** `full`. The diff is small but the blast radius is not: an over-broad pattern silently hides real files from every future `git add -A`, in this clone and every other, and neither `just build` nor the Nix evaluation would notice. Lane is set by what a wrong answer costs, not by how few lines it takes to write.

Cites D6, D12.

- [ ] **Step 1: Write the failing tests**

Add at module level:

```python
GITIGNORE = REPO_ROOT / ".gitignore"

SCRATCH_IGNORE_PATTERNS = (
    ".superpowers/",
    ".worktrees/",
    "**/.claude/worktrees/",
    "*.tmp.??????",
    "producer-report-*.json",
    "review-package-report-*.json",
)

# Every ephemeral shape a workflow run has produced or been told to produce.
IGNORED_SHAPES = (
    ".superpowers/sdd/primary/plan/progress.md",
    ".superpowers/workflows/run-1/state.json",
    "home/common/.superpowers/sdd/x",
    ".worktrees/issue-102/file.txt",
    ".claude/worktrees/worktree-issue-102/README.md",
    ".claude/worktrees/wt/.superpowers/sdd/primary/p/progress.md",
    "nested/.claude/worktrees/w/file",
    ".claude/plans/task-1-brief.md.tmp.aB3xY9",
    "producer-report-Ab12Cd.json",
    "review-package-report-xyz789.json",
    ".claude/specs/producer-report-XXXXXX.json",
)

# Real repository content that must stay visible to `git status`.
KEPT_SHAPES = (
    ".gitignore",
    "CLAUDE.md",
    "justfile",
    ".claude/settings.json",
    ".claude/specs/2026-08-23-workflow-scratch-containment-design.md",
    ".claude/plans/2026-08-23-workflow-scratch-containment.md",
    ".claude/plans/2026-08-23-workflow-scratch-containment.tasks/task-1.md",
    "home/common/agent-skills/skills/sdd/scripts/sdd-workspace",
    "home/common/agent-skills/tests/test_sdd_workspace.py",
    "handoff-notes.md",
)
```

Add these two tests to `WorkflowSkillContractsTest`:

```python
    def test_gitignore_is_tracked_and_carries_the_backstop(self):
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", ".gitignore"],
            check=True, capture_output=True,
        )
        lines = GITIGNORE.read_text(encoding="utf-8").splitlines()
        for pattern in SCRATCH_IGNORE_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, lines)

    def test_gitignore_ignores_leaked_shapes_in_an_isolated_repository(self):
        """Check the patterns in a throwaway repo, never in this one.

        This repository's .git/info/exclude already ignores the same shapes, so
        running `git check-ignore` here would pass even against an empty
        .gitignore — a vacuous pass. Global and system git config are disabled
        too, so a machine-local core.excludesFile cannot decide a keep shape
        for us (D12).
        """
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            home = Path(raw) / "home"
            home.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            (repo / ".gitignore").write_bytes(GITIGNORE.read_bytes())
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            })

            def status(candidate):
                return subprocess.run(
                    ["git", "-C", str(repo), "check-ignore", "-q", "--no-index",
                     candidate],
                    env=env, capture_output=True, check=False,
                ).returncode

            for shape in IGNORED_SHAPES:
                with self.subTest(ignored=shape):
                    self.assertEqual(status(shape), 0)
            for shape in KEPT_SHAPES:
                with self.subTest(kept=shape):
                    self.assertEqual(status(shape), 1)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k gitignore -v`

Expected: both FAIL. The tracked `.gitignore` holds only `result`, `__pycache__/` and `*.pyc` at the base commit, so every pattern assertion fails and every `IGNORED_SHAPES` entry comes back `1` (not ignored) in the isolated repository.

- [ ] **Step 3: Write the backstop**

Replace `.gitignore` in full with:

```gitignore
result
__pycache__/
*.pyc

# Ephemeral agent-workflow scratch. Their real homes are the primary checkout's
# .superpowers/ and $TMPDIR; these patterns are only the backstop, tracked here
# because .git/info/exclude is machine-local and invisible to every other clone.
.superpowers/
.worktrees/
**/.claude/worktrees/
*.tmp.??????
producer-report-*.json
review-package-report-*.json
```

`.superpowers/` and `.worktrees/` deliberately carry no leading slash so they match at every depth. `**/.claude/worktrees/` reproduces the `.git/info/exclude` rule this repository has run on for months. `*.tmp.??????` matches the six-`X` `mktemp` template `task-brief` uses for its atomic-replace sibling. The two `*-report-*.json` patterns match the report-candidate prefixes prescribed in Task 1 and already produced by `review-package`.

- [ ] **Step 4: Verify**

```bash
python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k gitignore -v 2>&1 | tail -5
```
Expected: `OK`, 2 tests.

```bash
git ls-files | grep -E '(^|/)\.superpowers/|(^|/)\.worktrees/|\.claude/worktrees/|\.tmp\.[A-Za-z0-9]{6}$|(^|/)(producer|review-package)-report-.*\.json$' > "${TMPDIR:-/tmp}/newly-ignored.txt" || true
if [ -s "${TMPDIR:-/tmp}/newly-ignored.txt" ]; then cat "${TMPDIR:-/tmp}/newly-ignored.txt"; exit 1; fi
echo "no tracked file is newly ignored"
```
Expected: `no tracked file is newly ignored` — adding these patterns must not shadow anything already under version control.

- [ ] **Step 5: Commit**

```bash
git add .gitignore home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "chore(git): track the agent-workflow scratch ignore backstop"
```
