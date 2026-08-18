# Agent-Lifecycle Permission Surface Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

Issue: https://github.com/fagenorn/nix-config/issues/30
Spec: `.claude/specs/2026-08-17-agent-lifecycle-permissions-design.md`

**Goal:** Declare exactly the issue's lifecycle permission surface in Nix while a fail-closed
`PreToolUse` guard narrows the two argument-sensitive Bash rules to the safe branch-delete and
repository-bound, protected-`main` merge shapes.

**Architecture:** `home/common/claude-code/default.nix` builds one Python policy executable and
registers it as the sole Bash `PreToolUse` command before declaring the sixteen allow entries. The
generated settings JSON is the discovery seam: `show-claude-settings` selects exactly one closure
artifact, and a stdlib test resolves and invokes the guard command from that artifact. `ship-issue`
emits the one merge shape the guard admits, with the resolved `repoSlug` explicit.

**Tech stack:** Nix/home-manager, Nix-built Python 3 stdlib, store-pinned `git`/`gh`/`jq`, `just`,
Python `unittest`, Markdown.

## Global Constraints

- Integration and default branch are `main`; tracker is `gh`; `repoSlug` is
  `fagenorn/nix-config`; `unsetGithubToken=false`; `coAuthoredBy=true`.
- Phase 6 may touch only `home/common/claude-code/default.nix`, `justfile`,
  `tests/test_claude_permission_guard.py`,
  `home/common/agent-skills/skills/ship-issue/SKILL.md`,
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `CLAUDE.md`, and the approved
  spec/plan artifacts. No `.github/**`, `.git/**`, local settings, git configuration, CI gate,
  protection, `defaultMode`, `ask`, or `deny` change.
- `permissions.allow` contains exactly these sixteen entries, in order: `Bash(git fetch:*)`,
  `Bash(git status:*)`, `Bash(git log:*)`, `Bash(git diff:*)`, `Bash(gh pr view:*)`,
  `Bash(gh pr list:*)`, `Bash(gh pr checks:*)`, `Bash(gh issue view:*)`,
  `Bash(gh issue list:*)`, `Bash(git worktree add:*)`, `Bash(git worktree list:*)`,
  `Bash(git worktree remove:*)`, `Bash(git worktree prune:*)`,
  `Bash(git branch -d:*)`, `Bash(gh pr merge:*)`, and bare `Agent`.
- Bare `Agent` remains inert while `defaultMode = "auto"`; comments and docs must say so. Do not
  change the mode to make it live.
- The guard is the safety boundary for `git branch -d` and `gh pr merge`; the broad allow strings
  are never described as safe on their own. No force branch deletion, push, broad unguarded merge,
  git config, `.git` edit, `gh pr create`, or `gh issue close` is added.
- The applied sibling gate is read-only evidence: `main` requires `Nix Eval` and has
  `enforce_admins=true`. Phase 6 must not call `protect-main`, `unprotect-main`, `just switch`,
  `sudo`, `git push`, `gh pr create`, or `gh pr merge`.
- Run exactly one cold `just build`, in Task 2. Later `show-claude-settings` calls may reuse that
  closure. Never disable signing. Every implementation commit includes:

  ```text
  Refs: https://github.com/fagenorn/nix-config/issues/30

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  ```

## Test seams

1. `just show-claude-settings` emits one JSON document and fails unless the closure has exactly one
   `-claude-code-settings.json` requisite (D4, D5, D15).
2. `tests/test_claude_permission_guard.py` reads that JSON, resolves the sole Bash `PreToolUse`
   command, and invokes the built executable with table-driven stdin/exit fixtures (D14, D16).
3. `just build` is the repository's local Nix evaluation/build gate. The one Task-2 build supplies
   the artifact used by seams 1 and 2.
4. Live PR metadata, applied protection, activation, and no-prompt behavior are Phase-7 evidence,
   never Phase-6 gates.

## Task index

| ID | Title | Files | Risk lane |
|----|-------|-------|-----------|
| P6-1 | Make generated-settings selection fail closed | `justfile` | full |
| P6-2 | Build, register, and contract-test the lifecycle guard and allow surface | `home/common/claude-code/default.nix`, `tests/test_claude_permission_guard.py` | full |
| P6-3 | Emit the repository-bound merge shape from `ship-issue` | `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` | full |
| P6-4 | Document the installed policy truthfully | `CLAUDE.md` | low-risk |
| P6-5 | Run the bounded Phase-6 acceptance gate | no files | full |
| P7-1 | Activate and record live evidence during shipping | no repository files; GitHub issue comment | full |

## Decisions

The spec owns the issue ledger. This plan implements D1–D2, D4–D6, D8, D10–D16; D13 reverses the
unsafe rationales in D3/D9, D14 reverses D7's no-test choice, and D15 reverses D11/D12's
zero-match behavior. Planning added D16 for the guard implementation and built-test interface.

## Reviewer provenance and disposition

- Reviewer: fresh native standards reviewer; review base
  `b344aaf527920dce8a47c2b9a11244234f2383d0`; no fallback reviewer.
- Blocking finding: `Bash(git branch -d:*)` admitted `-f`/`--force`, and
  `Bash(gh pr merge:*)` admitted other repositories and non-`main` PRs. Disposition: fully applied
  through D13 and Tasks P6-2/P6-3; one pre-allow guard accepts only exact shapes and verifies live
  repo/base/protection state.
- Should-fix finding: zero settings-artifact matches exited 0. Disposition: fully applied through
  D15 and Task P6-1; zero and multiple matches now fail before `cat`.
- Test-policy consequence: D14 and Task P6-2 add table-driven contract tests against the built
  executable named by generated settings.

---

## Phase 6 — implementation and local verification

### Task P6-1: Make generated-settings selection fail closed

**Files:**
- Modify: `justfile`

**Interfaces:**
- Produces: `just show-claude-settings`, whose stdout is exactly one generated settings JSON
  document and whose exit status is nonzero for zero or multiple matching closure paths.

**Invariants:**
- The recipe depends on `build`; both platform build banners move to stderr.
- Candidate selection is exactly D15's positional-parameter count; no `xargs`, `pipefail`, username,
  platform duplicate, or home-manager attribute path is introduced.

- [ ] **Step 1: Confirm the stale behavior**

  Run: `rg -n 'show-claude-settings|xargs cat|Building .*\.\.\.' justfile`

  Expected at the starting commit: no `show-claude-settings`; two build banners without `>&2`.

- [ ] **Step 2: Implement the exact-one recipe**

  Move both `build` recipe banners to stderr. Add this ungated recipe before branch-protection
  recipes:

  ```just
  ## claude code
  # Print the Nix-generated ~/.claude/settings.json exactly as the next switch will write it.
  show-claude-settings: build
    @set -- $$(nix-store --query --requisites ./result \
      | grep -- '-claude-code-settings\.json$' || true); \
      if [ "$$#" -ne 1 ]; then \
        echo "expected exactly one generated Claude settings artifact; found $$#" >&2; \
        exit 1; \
      fi; \
      cat "$$1"
  ```

- [ ] **Step 3: Verify without building**

  Run: `just --dry-run show-claude-settings`

  Expected: exit 0; the enabled `build` commands and exact-one body print without executing.

  Run: `test "$(rg -c '^  @echo "Building .*\.\.\." >&2$' justfile)" -eq 2 && ! rg -n 'xargs cat' justfile`

  Expected: exit 0. Either old stdout banner or stale `xargs` makes the gate fail.

- [ ] **Step 4: Commit**

  ```bash
  git add justfile
  git commit -m "feat(justfile): fail closed when selecting Claude settings

  Refs: https://github.com/fagenorn/nix-config/issues/30

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

### Task P6-2: Build, register, and contract-test the lifecycle guard and allow surface

**Files:**
- Modify: `home/common/claude-code/default.nix`
- Create: `tests/test_claude_permission_guard.py`

**Interfaces:**
- Produces: `lifecycleGuard`, one Nix-store executable referenced by the sole
  `settings.hooks.PreToolUse` entry whose matcher is `Bash`.
- Consumes: one JSON object on stdin. Requires `tool_name == "Bash"` and string
  `tool_input.command`; exits 2 with an actionable stderr reason on every malformed or rejected
  guarded call, otherwise exits 0 without emitting a permission decision.
- Produces: the sixteen-entry `settings.permissions.allow` contract from Global Constraints.
- Test consumes: `CLAUDE_SETTINGS_PATH=/absolute/generated/settings.json`; it discovers the guard
  from that JSON and invokes the built executable, never Nix source.

**Invariants:**
- If the raw command contains neither `git branch -d` nor `gh pr merge`, the guard returns 0 and
  remains outside permission classification.
- If either literal occurs, reject any raw `;`, `&`, `|`, `<`, `>`, `$`, backtick, backslash,
  newline, carriage return, `*`, `?`, `[`, `]`, `{`, `}`, `(`, `)`, `#`, or `~` before
  tokenisation; these cover control, expansion, redirection, globbing, comments, and second
  commands. Reject wrappers and malformed quoting after tokenisation. Tokenise with `shlex.split`;
  never execute raw command text or use `shell=True`.
- Branch deletion accepts only `['git', 'branch', '-d', branch]`, rejects a branch beginning `-`,
  and validates it by argv with absolute `${pkgs.git}/bin/git check-ref-format --branch`.
- Merge accepts only `gh pr merge <positive-decimal> --repo fagenorn/nix-config --merge
  --delete-branch`, optionally inserting `--subject <one-token-literal>` immediately before
  `--delete-branch`. Every other target, flag, order, repository, or strategy exits 2.
- For an accepted merge shape, invoke absolute `${pkgs.gh}/bin/gh` by argv to read that numbered PR
  with explicit `--repo fagenorn/nix-config`; use absolute `${pkgs.jq}/bin/jq` by argv to require an
  open PR with `baseRefName == "main"`. Then read
  `repos/fagenorn/nix-config/branches/main/protection` and require `Nix Eval` in contexts plus
  `.enforce_admins.enabled == true`. Child failure, invalid JSON, or false predicate exits 2 with
  the failing boundary named.
- Rejection reasons start with `lifecycle guard: invalid hook input:`, `lifecycle guard: unsafe
  branch deletion:`, or `lifecycle guard: unsafe merge:` as applicable. API/dependency reasons name
  `PR lookup`, `PR predicate`, `protection lookup`, or `protection predicate`; syntactic tests can
  therefore prove they rejected before the network boundary.
- `defaultMode = "auto"`, `ask = [ ]`, and `deny = [ ]` remain unchanged. The adjacent comment says
  the two broad entries are usable only through the guard and bare `Agent` is inert in auto mode.

- [ ] **Step 1: Write the failing built-contract test**

  Create `tests/test_claude_permission_guard.py` with this complete contract:

  ```python
  import json
  import os
  from pathlib import Path
  import subprocess
  import unittest


  SETTINGS_PATH = Path(os.environ["CLAUDE_SETTINGS_PATH"])


  class ClaudePermissionGuardTest(unittest.TestCase):
      @classmethod
      def setUpClass(cls):
          settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
          matches = [
              entry
              for entry in settings.get("hooks", {}).get("PreToolUse", [])
              if entry.get("matcher") == "Bash"
          ]
          if len(matches) != 1:
              raise AssertionError(f"expected one Bash PreToolUse matcher, found {len(matches)}")
          commands = [
              hook.get("command")
              for hook in matches[0].get("hooks", [])
              if hook.get("type") == "command"
          ]
          if len(commands) != 1 or not isinstance(commands[0], str):
              raise AssertionError(f"expected one command hook, found {commands!r}")
          cls.guard = Path(commands[0])
          if not cls.guard.is_absolute() or not os.access(cls.guard, os.X_OK):
              raise AssertionError(f"guard is not an executable absolute path: {cls.guard}")

      def invoke_raw(self, raw):
          return subprocess.run(
              [self.guard], input=raw, text=True, capture_output=True, timeout=5, check=False
          )

      def invoke_command(self, command):
          return self.invoke_raw(json.dumps({
              "tool_name": "Bash", "tool_input": {"command": command}
          }))

      def test_unrelated_bash_and_exact_branch_delete_pass(self):
          for command in ("git status --short", "git branch -d issue-30-safe"):
              with self.subTest(command=command):
                  result = self.invoke_command(command)
                  self.assertEqual(0, result.returncode, result.stderr)

      def test_malformed_hook_input_fails_closed(self):
          cases = (
              "not-json", "[]", "{}",
              json.dumps({"tool_name": "Read", "tool_input": {"command": "git branch -d x"}}),
              json.dumps({"tool_name": "Bash", "tool_input": {"command": 3}}),
          )
          for raw in cases:
              with self.subTest(raw=raw):
                  result = self.invoke_raw(raw)
                  self.assertEqual(2, result.returncode)
                  self.assertIn("lifecycle guard: invalid hook input:", result.stderr)

      def test_unsafe_branch_delete_shapes_fail_closed(self):
          cases = (
              "git branch -d -f topic", "git branch -d --force topic",
              "git branch -d one two", "git branch -d -bad",
              "git branch -d topic && true", "git branch -d topic; true",
              "git branch -d $(printf topic)", "git branch -d topic*",
              "command git branch -d topic", "git branch -d topic\ntrue",
          )
          for command in cases:
              with self.subTest(command=command):
                  result = self.invoke_command(command)
                  self.assertEqual(2, result.returncode)
                  self.assertIn("lifecycle guard: unsafe branch deletion:", result.stderr)

      def test_unsafe_merge_shapes_fail_before_network(self):
          cases = (
              "gh pr merge --repo fagenorn/nix-config --merge --delete-branch",
              "gh pr merge topic --repo fagenorn/nix-config --merge --delete-branch",
              "gh pr merge https://github.com/fagenorn/nix-config/pull/1 --repo fagenorn/nix-config --merge --delete-branch",
              "gh pr merge 1 --repo someone/else --merge --delete-branch",
              "gh pr merge 1 -R fagenorn/nix-config --merge --delete-branch",
              "gh pr merge 1 --repo fagenorn/nix-config --admin --merge --delete-branch",
              "gh pr merge 1 --repo fagenorn/nix-config --squash --delete-branch",
              "gh pr merge 1 --repo fagenorn/nix-config --rebase --delete-branch",
              "gh pr merge 1 --repo fagenorn/nix-config --merge",
              "gh pr merge 1 --merge --repo fagenorn/nix-config --delete-branch",
              "gh pr merge $PR --repo fagenorn/nix-config --merge --delete-branch",
              "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch | true",
          )
          for command in cases:
              with self.subTest(command=command):
                  result = self.invoke_command(command)
                  self.assertEqual(2, result.returncode)
                  self.assertIn("lifecycle guard: unsafe merge:", result.stderr)


  if __name__ == "__main__":
      unittest.main()
  ```

- [ ] **Step 2: Run the red test without a build**

  Run:

  ```bash
  RED_SETTINGS="${TMPDIR:-/tmp}/issue30-red-settings.json"
  printf '%s\n' '{"hooks":{"PreToolUse":[]}}' > "$RED_SETTINGS"
  CLAUDE_SETTINGS_PATH="$RED_SETTINGS" python3 tests/test_claude_permission_guard.py
  ```

  Expected: nonzero with `expected one Bash PreToolUse matcher, found 0`. Remove the scratch file.

- [ ] **Step 3: Implement the guard and settings registration**

  Before `settings`, define `lifecycleGuard` with `pkgs.writeTextFile`, `executable = true`,
  `destination = "/bin/claude-bash-lifecycle-guard"`, and a shebang fixed to
  `${pkgs.python3}/bin/python3`. The program uses only stdlib `json`, `shlex`, `subprocess`, and
  `sys`; define absolute constants for `${pkgs.git}/bin/git`, `${pkgs.gh}/bin/gh`, and
  `${pkgs.jq}/bin/jq`. Implement the ordered validation algorithm in Interfaces/Invariants, with
  one `block(reason)` path that prints `lifecycle guard: <reason>` to stderr and returns 2.

  Register exactly:

  ```nix
  hooks.PreToolUse = [
    {
      matcher = "Bash";
      hooks = [
        {
          type = "command";
          command = "${lifecycleGuard}/bin/claude-bash-lifecycle-guard";
        }
      ];
    }
  ];
  ```

  Populate `permissions.allow` with the exact sixteen-entry Global Constraints list. Replace the
  stale empty-list comment with truthful guard/allow and inert-`Agent` facts; do not preserve the
  old claims that case sensitivity or server protection alone makes either broad rule safe.

- [ ] **Step 4: Parse, build once, and capture the generated artifact**

  Run: `python3 -m py_compile tests/test_claude_permission_guard.py && nix-instantiate --parse home/common/claude-code/default.nix >/dev/null`

  Expected: exit 0.

  Run exactly once: `just build`

  Expected: exit 0. This is the plan's one cold build; summarize only the final status or first
  failing Nix line.

  Run:

  ```bash
  SETTINGS_JSON="${TMPDIR:-/tmp}/issue30-claude-settings.json"
  just show-claude-settings > "$SETTINGS_JSON"
  jq -e '(.permissions.allow | length) == 16 and
    .permissions.defaultMode == "auto" and
    (.permissions.ask | length) == 0 and
    (.permissions.deny | length) == 0 and
    ([.hooks.PreToolUse[] | select(.matcher == "Bash")] | length) == 1' "$SETTINGS_JSON"
  ```

  Expected: both commands exit 0 and stdout captured by the recipe parses as one JSON object.

- [ ] **Step 5: Run the built guard contract and artifact negative gates**

  Run: `CLAUDE_SETTINGS_PATH="$SETTINGS_JSON" python3 tests/test_claude_permission_guard.py -v`

  Expected: four tests pass; every rejection case returns 2 with nonempty stderr and no test needs
  network access.

  Run:

  ```bash
  jq -r '.permissions.allow[]' "$SETTINGS_JSON" > "${TMPDIR:-/tmp}/issue30-allows.txt"
  test "$(wc -l < "${TMPDIR:-/tmp}/issue30-allows.txt")" -eq 16
  ! rg -n 'config|\.git|branch -D|push|^Bash\(\*\)$|^Bash\([^)]*\*[^)]*:\*\)$' "${TMPDIR:-/tmp}/issue30-allows.txt"
  ```

  Expected: exit 0; no forbidden allow is printed. Remove both scratch files.

- [ ] **Step 6: Commit**

  ```bash
  git add home/common/claude-code/default.nix tests/test_claude_permission_guard.py
  git commit -m "feat(claude-code): guard lifecycle permissions before allow

  Refs: https://github.com/fagenorn/nix-config/issues/30

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

### Task P6-3: Emit the repository-bound merge shape from `ship-issue`

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the already-resolved `repoSlug` binding.
- Produces: exactly `gh pr merge <pr-num> --repo <repoSlug> --merge [--subject
  "<rendered mergeSubjectTemplate>"] --delete-branch`, in that order.

**Invariants:**
- The null-subject branch omits only `--subject` and its value; `--repo`, `--merge`, and
  `--delete-branch` remain.
- No `-R`, implicit current repository, alternate strategy, `--admin`, or other merge shape is
  documented or emitted. The existing post-merge state verification remains unchanged.

- [ ] **Step 1: Add the failing contract test**

  Add this method to `WorkflowSkillContractsTest`:

  ```python
  def test_ship_issue_merge_is_bound_to_the_resolved_repository(self):
      phase = self.section(self.ship_issue, "## Phase 7 — Merge", "## Phase 8 — Cleanup")
      expected = (
          'gh pr merge <pr-num> --repo <repoSlug> --merge '
          '--subject "<rendered mergeSubjectTemplate>" --delete-branch'
      )
      self.assertIn(expected, phase)
      self.assertNotIn("gh pr merge <pr-num> --merge", phase)
      self.assertIn("if it's null, omit `--subject` and its value", phase)
  ```

- [ ] **Step 2: Watch it fail**

  Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py`

  Expected: FAIL because the current command omits `--repo <repoSlug>`.

- [ ] **Step 3: Update the skill's one emitted merge shape**

  In Phase 7, say the command uses the binding resolved in Phase 0, update the null-subject sentence
  to “omit `--subject` and its value,” and replace the command block with the exact Produces shape.
  Do not change ship-release or add another merge authority.

- [ ] **Step 4: Verify and commit**

  Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py`

  Expected: the full file passes, including `test_ship_issue_merge_is_bound_to_the_resolved_repository`.

  ```bash
  git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
  git commit -m "fix(ship-issue): bind merges to the configured repository

  Refs: https://github.com/fagenorn/nix-config/issues/30

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

### Task P6-4: Document the installed policy truthfully

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Documents: `just show-claude-settings`; guarded branch/merge subsets; the live repo/base/gate
  checks; bare `Agent` remaining inert under auto; built-artifact/guard-test verification.

**Invariants:**
- Product prose describes behavior that exists by this commit. It does not repeat the superseded
  “`-d` cannot reach force” or “server protection alone makes the broad merge allow safe” claims.
- The CI-gate paragraph remains unchanged.

- [ ] **Step 1: Confirm the documentation is absent**

  Run: `rg -n 'show-claude-settings|lifecycle permission|PreToolUse' CLAUDE.md`

  Expected: no matches at the starting commit.

- [ ] **Step 2: Add bounded operator documentation**

  Add `just show-claude-settings # print the generated settings JSON (builds first)` to the Commands
  fence. In the existing declarative-Claude bullet, add one concise sentence stating all facts in
  Interfaces. Mention the contract test by path; keep rationale and residuals in the spec.

- [ ] **Step 3: Verify and commit**

  Run: `test "$(rg -c 'show-claude-settings' CLAUDE.md)" -eq 2 && test "$(rg -c 'tests/test_claude_permission_guard.py' CLAUDE.md)" -eq 1 && rg -n 'inert.*auto|auto.*inert' CLAUDE.md`

  Expected: exit 0 and one truthful inert-`Agent` sentence.

  ```bash
  git add CLAUDE.md
  git commit -m "docs(claude): explain the guarded lifecycle surface

  Refs: https://github.com/fagenorn/nix-config/issues/30

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
  ```

### Task P6-5: Run the bounded Phase-6 acceptance gate

**Files:**
- Modify: none.

**Invariants:**
- No second cold build, activation, tracker write, push, PR operation, protection query/mutation, or
  live merge occurs here.

- [ ] **Step 1: Re-run the fast repository contract suite**

  Run: `just agent-workflow-tests`

  Expected: exit 0; all existing workflow tests plus the repository-bound merge test pass.

- [ ] **Step 2: Re-run the built policy contract without rebuilding**

  Run:

  ```bash
  SETTINGS_JSON="${TMPDIR:-/tmp}/issue30-final-settings.json"
  just show-claude-settings > "$SETTINGS_JSON"
  CLAUDE_SETTINGS_PATH="$SETTINGS_JSON" python3 tests/test_claude_permission_guard.py -v
  ```

  Expected: recipe and all four tests exit 0. Remove the scratch file.

- [ ] **Step 3: Audit owned scope and terminal state**

  Run: `git diff --check b344aaf527920dce8a47c2b9a11244234f2383d0..HEAD -- home/common/claude-code/default.nix justfile tests/test_claude_permission_guard.py home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py CLAUDE.md`

  Expected: exit 0 with no output.

  Run: `git status --short && git log -4 --format='%h %s%n%b'`

  Expected: clean worktree; four implementation commits are signed under the repository's normal
  policy and each contains the issue reference and Co-Authored-By trailer.

---

## Phase 7 — live activation and tracker evidence

### Task P7-1: Activate and record live evidence during shipping

**Files:**
- Modify: no repository file.
- External write: one evidence/discussion comment on issue 30.

**Interfaces:**
- Consumes: the open issue-30 PR number before merge, the built settings artifact, and the merged
  branch after normal `ship-issue` delivery.
- Produces: issue-comment evidence that distinguishes local contract proof from live external-state
  proof.

**Invariants:**
- This task is not part of `sdd`/Phase 6. Do not run it until the user has authorized Phase 7.
- Protection is read, never changed. The guard is invoked directly; the evidence step does not run
  `gh pr merge`. `just switch` runs only when the operator explicitly authorizes activation.
- A skipped or failed observation is recorded as skipped/failed, never passed.

- [ ] **Step 1: Before merge, verify the external predicates and the positive guarded shape**

  Run:

  ```bash
  gh api repos/fagenorn/nix-config/branches/main/protection \
    --jq '[.required_status_checks.contexts, .enforce_admins.enabled]'
  PR_NUMBER="$(gh pr view --repo fagenorn/nix-config --json number --jq .number)"
  SETTINGS_JSON="${TMPDIR:-/tmp}/issue30-live-settings.json"
  just show-claude-settings > "$SETTINGS_JSON"
  GUARD="$(jq -er '[.hooks.PreToolUse[] | select(.matcher == "Bash") | .hooks[] | select(.type == "command") | .command] | if length == 1 then .[0] else error("expected one guard") end' "$SETTINGS_JSON")"
  printf '%s\n' "$(jq -nc --arg command "gh pr merge $PR_NUMBER --repo fagenorn/nix-config --merge --delete-branch" '{tool_name:"Bash",tool_input:{command:$command}}')" | "$GUARD"
  ```

  Expected: protection prints `[["Nix Eval"],true]`; direct guard invocation exits 0 and performs
  no merge. Any API, repo, base, state, or protection mismatch exits 2 and blocks shipping.

- [ ] **Step 2: Deliver through the normal ship workflow**

  Continue `ship-issue`. Its Phase-7 merge command must include
  `--repo fagenorn/nix-config`; required `Nix Eval` remains the server enforcement. Record the PR URL
  and merge SHA. Do not substitute an unguarded manual merge shape.

- [ ] **Step 3: Activate only on explicit operator request, then use a fresh session**

  Run `just switch` only after authorization. Verify the live settings carry sixteen allow entries
  and one Bash guard. Start a fresh Claude Code background session and have it create and remove one
  detached scratch worktree under `${TMPDIR:-/tmp}`, then run
  `gh pr view <merged-pr-number> --repo fagenorn/nix-config --json number,state,url`. Record commands,
  statuses, and any permission denial verbatim. Bare `Agent` may itself remain classifier-gated; that
  is expected, not a reason to claim the demo passed.

- [ ] **Step 4: Post the evidence and two residual discussion items**

  Comment on issue 30 with: protection projection; direct-guard exit; PR/merge identifiers;
  activation and no-prompt demo outcomes or explicit “not run”; the fact that bare `Agent` is inert
  under auto; and R1 (`git -C <path> …`) remains classifier-dependent with caller `cd` as the safe
  future direction. Remove the scratch JSON. Do not alter local settings or close the issue by a
  separate command when the merged `main` PR already closed it.
