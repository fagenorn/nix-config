# Task 5: Lifecycle guard rewrite and allow surface

**Files:**
- Modify: `home/common/claude-code/default.nix` (the inline guard Python, lines ~19–314, and the `settings.permissions.allow` list, ~357–374)
- Modify: `CLAUDE.md` (the "16-entry allow surface" sentence in the claude-code section)
- Test: `tests/test_claude_permission_guard.py`

**Interfaces:**
- Consumes (existing): stdin JSON hook payload; `block(reason)` → stderr `lifecycle guard: <reason>`, exit 2; exit 0 = allow; `detect_repository(cwd)`; `parse_merge_raw`; `UNSAFE_BRANCH_CHARS`; `--git-bin/--gh-bin/--jq-bin/--child-timeout-seconds` test injection flags; the `fake-gh` fixture and `make_repo(origin)` in the test file; `CLAUDE_SETTINGS_PATH`-driven `setUpClass`.
- Produces:
  - **Dispatch** (replaces the substring dispatcher at ~166–175, per D10): `guarded_operations(command) -> list[str]` — segment the raw command and return the operations whose literal opens a command position. Algorithm (exact, the carve-out applies — this parsing IS the decision):
    1. Scan the string once, tracking single-quote and double-quote context.
    2. Outside quotes, `#` starts a comment (skip to end of line); `<<` or `<<-` followed by an optional quote and a delimiter word starts a heredoc — after the current line ends, skip whole lines until a line equal to the delimiter (ignoring leading tabs for `<<-`); `<<<` is a herestring, not a heredoc.
    3. Outside quotes/comments/heredocs, the characters `;`, `&`, `|`, and newline end a segment (runs like `&&`/`||` count once).
    4. A segment's command position: strip leading whitespace and leading `NAME=value` words; the remainder must START WITH one of the guarded literals — `gh pr merge`, `git branch -d`, `git push`, `gh pr create` — followed by end-of-segment or whitespace. Quoted interiors, heredoc bodies, and comments never contribute a command position.
    5. If the scan ends inside an unterminated quote or heredoc (unparseable), fail closed: if any guarded literal occurs anywhere as a substring, return that operation (blocking will follow when its grammar cannot match); otherwise return `[]`.
  - **Ownership rule** (per D10, D16): every guarded operation resolves `detect_repository(cwd)`; a repo whose owner is not `fagenorn` → `block("repository <slug or unknown> is outside standing authorization")`. The defer/exit-0 path for real guarded commands is REMOVED.
  - **`default_branch(cwd) -> str`**: `git -C <cwd> symbolic-ref --short refs/remotes/origin/HEAD` → strip the `origin/` prefix; any failure → block (fail closed).
  - **Push grammar**: `shlex.split` argv must be exactly `["git", "push", "-u", "origin", BRANCH]` or `["git", "push", "origin", BRANCH]`; BRANCH must not start with `-`, must not contain `:` or `+` (no refspecs/force), must pass `git check-ref-format --branch BRANCH`, and must differ from `default_branch(cwd)`. Anything else (force/delete/tags/mirror flags, extra remotes) → block.
  - **PR-create grammar**: argv exactly `["gh", "pr", "create", "--repo", REPO, "--base", BASE, "--head", HEAD, "--title", TITLE, "--body", BODY]` — REPO must equal the detected slug, BASE must equal `default_branch(cwd)`, HEAD validated like BRANCH above and ≠ BASE, TITLE/BODY must exclude `"`, backtick, `$`, backslash, and NUL (newlines allowed in BODY only). No `--fill`, no other flags.
  - **Merge generalization**: `REPOSITORY` constant is removed; the merge grammar and both `jq` predicates are templated on the detected slug (`.url | startswith("https://github.com/<slug>/pull/")`, base equals `default_branch(cwd)`), and the protection predicate becomes `(.required_status_checks.contexts | length) > 0 and .enforce_admins.enabled == true` against `gh api repos/<slug>/branches/<default-branch>/protection`.
  - **Allow surface**: exactly two new entries, inserted after `"Bash(git worktree prune:*)"` and before `"Bash(git branch -d:*)"`: `"Bash(git push:*)"`, `"Bash(gh pr create:*)"` — 18 entries total, order pinned.
  - **CLAUDE.md**: the sentence naming the 16-entry surface and the guard's checks is updated to 18 entries, naming push (non-default branch, no force/delete), PR-create (base = default branch), and the generalized fagenorn-owned + protection-checked merge, all fail-closed.

**Invariants:**
- Branch-delete guarding is unchanged and stays global (all repos).
- A command whose only mention of a guarded literal is inside a heredoc body, quoted string, or comment exits 0 in EVERY repo, including nix-config.
- The guard never exits 0 for a command whose command position opens with a guarded literal unless the full grammar AND live checks pass (per D16).
- All live checks keep the `--child-timeout-seconds` bound and fail closed on timeout/nonzero/invalid output.
- `just show-claude-settings` still finds exactly one settings artifact.

- [ ] **Step 1: Write the failing tests** (extend `ClaudePermissionGuardTest`; reuse `make_repo`, `run_guard`-style helpers and the `fake-gh` env contract; extend `fake-gh` to also answer `pr view`/`api ... protection` argv containing an arbitrary `--repo` slug and add a `FAKE_DEFAULT_BRANCH` env consumed by a new `fake-git`-less approach: instead set `refs/remotes/origin/HEAD` inside `make_repo` via `git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main` after creating a `main` remote-tracking ref):

```python
EXPECTED_ALLOW = [
    "Bash(git fetch:*)", "Bash(git status:*)", "Bash(git log:*)", "Bash(git diff:*)",
    "Bash(gh pr view:*)", "Bash(gh pr list:*)", "Bash(gh pr checks:*)",
    "Bash(gh issue view:*)", "Bash(gh issue list:*)",
    "Bash(git worktree add:*)", "Bash(git worktree list:*)", "Bash(git worktree remove:*)",
    "Bash(git worktree prune:*)",
    "Bash(git push:*)", "Bash(gh pr create:*)",
    "Bash(git branch -d:*)", "Bash(gh pr merge:*)", "Agent",
]

def test_heredoc_and_quoted_mentions_pass_in_own_repo(self):
    repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
    for command in (
        'cat > notes.md <<\'EOF\'\nrun gh pr merge 5 later\ngit push origin main\nEOF\n',
        'echo "docs say gh pr create --repo x"',
        'true # gh pr merge 9 --repo fagenorn/nix-config --merge --delete-branch',
    ):
        result = self.run_guard(command, cwd=repo)
        self.assertEqual(result.returncode, 0, (command, result.stderr))

def test_push_grammar_accepts_only_plain_nondefault_branch(self):
    repo = self.make_repo("git@github.com:fagenorn/nix-config.git")  # origin/HEAD -> main
    ok = self.run_guard("git push -u origin worktree-issue-101-quota", cwd=repo)
    self.assertEqual(ok.returncode, 0, ok.stderr)
    for bad in (
        "git push origin main",                       # default branch
        "git push --force origin topic",              # force
        "git push origin :topic",                     # delete refspec
        "git push origin +topic",                     # force refspec
        "git push upstream topic",                    # foreign remote
        "git push -u origin topic && rm -rf /",       # chained second command is fine BUT
    ):
        result = self.run_guard(bad, cwd=repo)
        if bad.endswith("rm -rf /"):
            self.assertEqual(result.returncode, 0, result.stderr)  # push segment itself is valid
        else:
            self.assertEqual(result.returncode, 2, bad)

def test_push_outside_fagenorn_blocks(self):
    repo = self.make_repo("git@github.com:someoneelse/tool.git")
    result = self.run_guard("git push -u origin topic", cwd=repo)
    self.assertEqual(result.returncode, 2)
    self.assertIn("outside standing authorization", result.stderr)

def test_pr_create_grammar_and_base_check(self):
    repo = self.make_repo("https://github.com/fagenorn/argus.git")
    ok = self.run_guard(
        'gh pr create --repo fagenorn/argus --base main --head issue-7-fix '
        '--title "fix: guard" --body "Closes #7"', cwd=repo)
    self.assertEqual(ok.returncode, 0, ok.stderr)
    for bad in (
        'gh pr create --repo fagenorn/nix-config --base main --head t --title "x" --body "y"',  # wrong repo
        'gh pr create --repo fagenorn/argus --base release --head t --title "x" --body "y"',    # wrong base
        'gh pr create --repo fagenorn/argus --base main --head t --title "$(pwn)" --body "y"',  # unsafe title
        'gh pr create --repo fagenorn/argus --base main --head t --fill',                        # wrong shape
    ):
        self.assertEqual(self.run_guard(bad, cwd=repo).returncode, 2, bad)

def test_merge_validates_in_every_fagenorn_repo_and_blocks_elsewhere(self):
    argus = self.make_repo("git@github.com:fagenorn/argus.git")
    merge = 'gh pr merge 107 --repo fagenorn/argus --merge --delete-branch'
    good = self.run_guard(merge, cwd=argus, fake_pr_repo="fagenorn/argus")
    self.assertEqual(good.returncode, 0, good.stderr)   # fake-gh serves matching PR+protection
    foreign = self.make_repo("git@github.com:someoneelse/tool.git")
    blocked = self.run_guard('gh pr merge 1 --repo someoneelse/tool --merge --delete-branch', cwd=foreign)
    self.assertEqual(blocked.returncode, 2)
```

Also UPDATE (not delete): `test_generated_allow_surface_is_exact_and_ordered` → new 18-entry list; `test_merge_guard_is_scoped_to_its_own_repository` → its argus merges now VALIDATE via fake-gh instead of deferring (rename to `test_merge_guard_validates_other_fagenorn_repos`), its prose-mention case moves under the heredoc/quoted test; `test_unsafe_merge_shapes_fail_before_network` keeps all 17 shapes (now against the detected repo). `fake-gh` gains dynamic-slug matching and `FAKE_PR_JSON` defaults derived from the requested slug + `main`.

- [ ] **Step 2: Run and watch them fail**

Run: `just show-claude-settings > "$TMPDIR/claude-settings.json" && CLAUDE_SETTINGS_PATH="$TMPDIR/claude-settings.json" python3 tests/test_claude_permission_guard.py -v`
Expected: FAIL — allow surface is 16 entries; heredoc mention blocks; push/pr-create unknown operations.

- [ ] **Step 3: Implement** in `default.nix` per Interfaces (one Python script, same derivation). Keep `parse_merge_raw`'s shape but template the slug; add `parse_push_argv`/`parse_pr_create_argv`; wire `guarded_operations` as the sole dispatcher; delete the early-exit defer added by 8108b18 (its job is subsumed by ownership + templated grammar). Update the allow list and the CLAUDE.md sentence.

- [ ] **Step 4: Verify**

Run: `just build && just show-claude-settings > "$TMPDIR/claude-settings.json" && CLAUDE_SETTINGS_PATH="$TMPDIR/claude-settings.json" python3 tests/test_claude_permission_guard.py -v`
Expected: PASS, all tests; `just build` succeeds (Nix eval green).

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/default.nix tests/test_claude_permission_guard.py CLAUDE.md
git commit -m "feat(claude-code): segment-scoped lifecycle guard with push and PR-create standing authorization"
```

**Verification (falsifiable):** at base, the heredoc command in Step 1 exits 2 inside a nix-config-remote repo (the exact misfire observed during design) and the allow list has 16 entries; after, it exits 0 and `jq -r '.permissions.allow | length' "$TMPDIR/claude-settings.json"` prints 18. Cite: D4, D10, D16.
