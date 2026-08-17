# Agent-Lifecycle Permission Surface Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

Issue: https://github.com/fagenorn/nix-config/issues/30
Spec: `.claude/specs/2026-08-17-agent-lifecycle-permissions-design.md` — its
`## Decision ledger` (D1–D12) is the source of truth. This plan cites rows by ID and never
restates them. D11 and D12 were appended by this plan and are summarised under `## Decisions`.

**Goal:** The lifecycle commands this repo's agents actually run — read-only `git`/`gh`
queries, worktree add/list/remove/prune, `git branch -d`, and `gh pr merge` — resolve against
declared allow rules instead of a probabilistic classifier, and the resulting artifact is
inspectable with one named command.

**Architecture:** Three product files change and no new file is created. `justfile` gains an
ungated `show-claude-settings` recipe that depends on `build` and prints the settings JSON out
of the freshly built system closure (per D4/D5), plus a two-line adaptation that moves the
`build` recipes' progress banner to stderr so that output is pipeable (per D11).
`home/common/claude-code/default.nix` gets the sixteen-entry `permissions.allow` list and a
replacement comment carrying the two per-entry conditions (per D2/D3/D8/D9). `CLAUDE.md` gains
the recipe in its Commands block and one sentence in the claude-code bullet list (per D8). The
recipe lands **first**, because it is the gate the allow-list task is verified with.

**Tech stack:** Nix (`home-manager` module attrset → `(pkgs.formats.json {}).generate`), `just`
1.43, `nix-store --query --requisites`, `jq` 1.8, Markdown. No new flake input, no new test
file, no new runner (per D7).

## Global Constraints

- **Exactly three product paths change** across Tasks 1–2: `justfile` (modify),
  `home/common/claude-code/default.nix` (modify), `CLAUDE.md` (modify). No new file. No
  file under `home/common/agent-skills/` or `tests/` is touched (per D7).
- **The sixteen allow entries are a byte-exact contract.** They are written out in full in
  Task 2 and must land verbatim, in that order. Their exact spelling — `:*` rather than ` *`,
  `-d` rather than `-D` or `--delete`, prefix-only `gh pr merge` — is what makes the issue's
  negative criteria hold by construction (per D2/D3/D9). Do not "tidy" them.
- **`ask` and `deny` stay `[ ]`.** Adding a `deny` is out of scope and actively harmful (spec
  `## Out of scope`); a deny at any scope beats an allow at any other.
- **Do not change `defaultMode`.** It stays `"auto"` (per D1). The `Agent` entry is inert as
  shipped and the comment must say so; nothing in this plan may present it as working.
- **`.claude/settings.local.json` is not touched** (per D6). It is untracked and outside git.
- **Never run `just switch`** or any activation during plan execution. Task 3 is ship-time.
- **Phase 6 never touches the live repository.** No `gh api`, no `gh pr`, no `gh issue
  comment`, no `just protect-main` / `unprotect-main`, no `git push`. Other agents have open
  PRs in this session's orchestration run.
- **Never disable commit signing.** No `-c commit.gpgsign=false`, no `--no-gpg-sign`. Surface
  a signing failure rather than working around it.
- **Commit trailers**, on every commit:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_011BW621YtNATjTJfsJSJXnB`
  Each task's `git commit` spells both out; they are part of the message, not garnish.
- **Payload discipline.** `just show-claude-settings` prints ~40 lines of JSON; always pipe it
  through `jq` with the specific query the gate names, never paste a whole run into a report.
  Summarise a failed build to its error lines.
- **Budget.** `just build` (and therefore the recipe) took **26 s wall** in this worktree with
  a warm store on 2026-08-17, and minutes on a cold one. It is named in exactly two gates.

## Test seams

The spec's three seams (`## Test seams`). No new seam; a task that wants one has found a plan bug.

1. **The generated settings artifact** — the store JSON reached by `just show-claude-settings`,
   asserted with `jq`. Both of the issue's inspection criteria are decided here, positively
   (sixteen entries verbatim) and negatively (no `config` / `.git` / `branch -D` / `push` /
   blanket / wildcarded-interpreter entry).
2. **`just build`, exit 0** — the repo's only local verification step. Seam 1 subsumes it: the
   recipe depends on `build`, and `just` aborts the recipe if the dependency fails, so a
   successful `just show-claude-settings` is a successful `just build`.
3. **The live demo — ship-time evidence, not a plan gate.** After a `just switch`, a background
   subagent removes a scratch worktree and runs `gh pr view` with no permission denial. It is
   the only seam that can prove a rule *matches* rather than merely *exists*, and it needs sudo.
   It is Task 3.

## Task index

| ID | Title | Files touched | Risk lane |
|----|-------|---------------|-----------|
| 1 | Inspection route: `show-claude-settings` + pipeable build banner | `justfile` (modify), `CLAUDE.md` (modify) | **low-risk** |
| 2 | Declare the sixteen-entry allow list and replace the comment | `home/common/claude-code/default.nix` (modify), `CLAUDE.md` (modify) | **full** |
| 3 | **SHIP-TIME ONLY, NOT PHASE 6** — live demo, protection re-confirmation, issue thread | `.claude/specs/2026-08-17-agent-lifecycle-permissions-evidence.md` (create, at ship time) | **full** |

**Lane rationale.** Task 2 is **full** and is not mechanical, whatever a list of sixteen
strings looks like in a diff: it is the permission policy every unattended agent run on this
machine is decided by, it pre-authorizes a destructive command (`git worktree remove --force`)
and a release-surface one (`gh pr merge`, reachable with `--admin`), and its characteristic bug
is silent — a malformed allow rule produces no warning and simply never matches, so a reviewer
who reads the diff and not the built artifact cannot tell a working list from a dead one. Task
1 is **low-risk**: it adds one read-only recipe and redirects an informational `echo` from
stdout to stderr, bounded, locally verified on this host, changing no configuration Claude Code
or Nix reads. Task 3 is **full** and is not code: it activates a generation and posts to the
live issue thread.

## Decisions

The spec's ledger is authoritative; this plan rests on D1–D10 and appends two rows, D11 and
D12, in the same commit as this file:

- **D11** — the two `build` recipes' progress banners move to stderr, because they are on
  **stdout** in the real justfile and would corrupt the spec's own acceptance command
  (`just show-claude-settings | jq …`). This is the one adaptation of the spec's recipe snippet
  to the real file; the recipe body itself lands verbatim.
- **D12** — the recipe body keeps the spec's `grep | xargs cat` shape without a fail-loud guard,
  because the assertions that consume it (`jq -e`) fail closed on empty input.

Everything else — the task split, the commit boundaries, where in `justfile` and `CLAUDE.md`
the new lines sit — is routine and deliberately not logged.

---

### Task 1: Inspection route — `show-claude-settings`, with a pipeable build banner

**Files:**
- Modify: `justfile`
- Modify: `CLAUDE.md`
- Test: none (no test runner covers the justfile; the gate is the recipe's own output, per D7)

**Interfaces:**
- Produces: `just show-claude-settings` — an ungated recipe that depends on `build` and writes
  the generated Claude Code settings JSON, and nothing else, to **stdout**. Task 2 is verified
  entirely through it.
- Produces: `just build` (both platform variants) keeps its progress banner but writes it to
  **stderr**; its stdout stays empty on success.

**Invariants:**
- `just show-claude-settings` prints the *current* settings: it never reports a stale
  `./result` as current, which is why it depends on `build` (per D5).
- Its stdout is valid JSON with no preamble — `just show-claude-settings | jq …` must work with
  no filtering (per D11).
- The banner is still shown to a human running `just build`; it moves streams, it is not deleted.
- One ungated recipe serves both hosts: no `[macos]`/`[linux]` pair, no username in any
  attribute path (per D4/D5).

- [ ] **Step 1: Observe the red**

Run, from the worktree root:

```bash
just show-claude-settings
```

Expected: exit 1 with `error: Justfile does not contain recipe `show-claude-settings``.
Confirmed at this branch's base on 2026-08-17. If it already prints JSON, this task is done or
the wrong worktree is checked out — stop and report rather than editing.

- [ ] **Step 2: Move both build banners to stderr**

In `justfile`, in the `[macos]` `build` recipe and the `[linux]` `build` recipe, append `>&2`
to the `@echo` line and change nothing else:

```just
[macos]
build target_host=hostname flags="":
  @echo "Building nix-darwin config..." >&2
```

```just
[linux]
build target_host=hostname flags="":
  @echo "Building NixOS config for {{target_host}}..." >&2
```

Rationale for the change, which belongs in the commit message and not in the file: `echo`
writes to stdout, so the banner would otherwise be the first line of `show-claude-settings`'
output and would break `jq` (per D11). Nothing parses `just build`'s stdout today; `trace` and
`switch` depend on `build` and are unaffected.

- [ ] **Step 3: Add the recipe**

Insert at the end of the `## branch protection` block — after `show-protection`'s body and
before the `## remote nix vm installation` header — this exact text, keeping the file's
two-space body indent and four-space continuation indent:

```just
## claude code
# Print the Nix-generated ~/.claude/settings.json exactly as the next switch will write it.
show-claude-settings: build
  @nix-store --query --requisites ./result \
    | grep -- '-claude-code-settings\.json$' \
    | xargs cat
```

Three details are load-bearing:
- The recipe is **ungated**. `just`'s platform attributes resolve the `build` dependency to the
  enabled variant; verified on this host that `just --dry-run show-claude-settings` expands the
  darwin `build` (per D5). Do not add `[macos]`/`[linux]` variants.
- It takes **no parameters**. `build`'s `target_host` already defaults to `hostname`.
- Exactly one comment line sits immediately above the recipe, because `just --list` shows only
  the last comment line of a block — the convention the file states in its branch-protection
  section.

- [ ] **Step 4: Document it in the Commands block**

In `CLAUDE.md`, inside the ```sh``` block under `## Commands`, insert directly after the
`just build mbp` line:

```
just show-claude-settings  # build, then print the ~/.claude/settings.json Nix will install
```

The command is longer than the block's comment alignment column; leave the other lines alone
rather than re-aligning the block.

- [ ] **Step 5: Verify**

Run each; all four must hold.

```bash
just show-claude-settings 2>/dev/null | jq -e '.permissions | has("allow")' >/dev/null && echo RECIPE_OK
```
Expected: `RECIPE_OK`. (Proves the recipe exists, the build succeeded, exactly one settings
path was found, and its content parses as the settings JSON.)

```bash
just show-claude-settings 2>/dev/null | head -c 1
```
Expected: `{` — the first byte of stdout is JSON, not the banner. This is the check that fails
if Step 2 was skipped; it printed `Building nix-darwin config...` before the fix.

```bash
just build 2>&1 >/dev/null | grep -c 'Building nix-darwin config'
```
Expected: `1` — the banner still reaches the terminal, on stderr. (`2>&1 >/dev/null` keeps
stderr only; the argument order matters.)

```bash
just --list | grep 'show-claude-settings'
```
Expected: one line showing the recipe and its one-line summary.

```bash
just show-claude-settings 2>/dev/null | jq -r '.permissions.allow | length'
```
Expected: `0`. The list is still empty at this task — this is the number Task 2 flips to `16`,
and recording it here is what makes Task 2's gate falsifiable.

- [ ] **Step 6: Commit**

```bash
git add justfile CLAUDE.md
git commit -m "feat(justfile): add show-claude-settings and make build output pipeable

The recipe depends on build so it can never print a stale ./result as
current, and prints the settings file out of the freshly built system
closure. The build recipes' progress banner moves to stderr because it
was on stdout and would otherwise be the first line of the recipe's
output, breaking any jq consumer.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011BW621YtNATjTJfsJSJXnB"
```

---

### Task 2: Declare the sixteen-entry allow list and replace the comment

**Files:**
- Modify: `home/common/claude-code/default.nix` (the `permissions` attrset and the comment
  above it, at lines 43–51 of the base commit)
- Modify: `CLAUDE.md` (the claude-code bullet list)
- Test: none (per D7 — no offline test can check the property that matters, that a rule
  *matches*; the seams are the built artifact and the ship-time demo)

**Interfaces:**
- Consumes: `just show-claude-settings` from Task 1. Every gate below runs through it.
- Produces: `permissions.allow` in the generated `~/.claude/settings.json` — a sixteen-element
  array of strings, in the order written below.

**Invariants:**
- Exactly sixteen entries: fifteen `Bash(<prefix>:*)` rules and the bare `Agent` entry.
- No entry contains the substring `config`, `.git`, `branch -D`, or `push`; no entry is
  `Bash(*)` or a wildcarded interpreter such as `Bash(python*)`.
- Every Bash entry carries the trailing wildcard (without it a rule is an exact match and would
  never reach a command with arguments) and is a one-subcommand prefix (per D2).
- `permissions.defaultMode` stays `"auto"`; `ask` and `deny` stay `[ ]`.
- The comment above `permissions` makes no claim the shipped file does not support — in
  particular it must not present the `Agent` entry as effective under `defaultMode = "auto"`.

- [ ] **Step 1: Observe the red**

```bash
just show-claude-settings 2>/dev/null | jq -e '.permissions.allow | length == 16'
```
Expected: prints `false`, exit 1. (At the base commit the array is empty — verified in this
worktree on 2026-08-17: `{"allow":[],"ask":[],"defaultMode":"auto","deny":[]}`.)

- [ ] **Step 2: Replace the comment and populate the list**

In `home/common/claude-code/default.nix`, replace the three-line comment at lines 43–45 and the
`permissions` attrset at lines 46–51 with exactly this. The strings are a contract (see Global
Constraints); the comment prose is fixed here because each sentence is a condition a future
editor must not have to rediscover (per D8), and every claim in it is established in the spec:

```nix
    # The agent-lifecycle permission surface: the commands this repo's agents run to fetch,
    # inspect, manage worktrees, and land a PR. One narrow rule per subcommand, so that
    # adding a sibling subcommand stays a deliberate edit. Two engine facts drive the shapes:
    # a Bash prefix is matched literally from position 0 and is case-sensitive with no flag
    # normalisation (which is why `git branch -d` cannot reach `git branch -D`), and a
    # malformed allow rule produces no warning — it silently never matches. So check an edit
    # here with `just show-claude-settings`, not by reading the diff. `ask` and `deny` stay
    # empty on purpose: a deny at any scope beats an allow at any other.
    permissions = {
      defaultMode = "auto";
      allow = [
        # Read-only git and tracker queries.
        "Bash(git fetch:*)"
        "Bash(git status:*)"
        "Bash(git log:*)"
        "Bash(git diff:*)"
        "Bash(gh pr view:*)"
        "Bash(gh pr list:*)"
        "Bash(gh pr checks:*)"
        "Bash(gh issue view:*)"
        "Bash(gh issue list:*)"

        # Worktree lifecycle. `git worktree remove` reaches `--force`, which widens what the
        # command tolerates (a dirty tree), not what it destroys: it deletes the working copy
        # and the admin entry, never a branch and never a commit. Branch deletion is the
        # separate `-d`-only rule, which git refuses on an unmerged branch.
        "Bash(git worktree add:*)"
        "Bash(git worktree list:*)"
        "Bash(git worktree remove:*)"
        "Bash(git worktree prune:*)"
        "Bash(git branch -d:*)"

        # Prefix-only, because ship-issue types the PR number before every flag, so a
        # `--merge`-bearing prefix would never match. That leaves `--admin` reachable, and it
        # is admissible only because the merge is gated on the server: with `main`'s applied
        # protection making `Nix Eval` a required check and `enforce_admins` on, GitHub
        # refuses the merge — `--admin` included — until the check is green. Confirm with
        # `just show-protection`. If that protection is removed or `enforce_admins` is turned
        # off, remove this entry in the same change.
        "Bash(gh pr merge:*)"

        # Inert as shipped: Claude Code drops `Agent` allow rules on entering auto mode and
        # restores them on leaving, and `defaultMode` above is `"auto"`. Kept because it is
        # correct in plan and default mode; delegate dispatch stays classifier-gated until
        # `defaultMode` changes, which is a separate decision.
        "Agent"
      ];
      ask = [ ];
      deny = [ ];
    };
```

- [ ] **Step 3: Add the sentence to `CLAUDE.md`**

In `CLAUDE.md`, in the **Claude Code is declaratively managed** bullet list, append to the
bullet that ends `**Edit settings in `default.nix`; do not edit `~/.claude/settings.json`
directly (it resets on rebuild).**`:

```
`permissions.allow` in that attrset is the declared agent-lifecycle surface — read-only `git`/`gh` queries, worktree lifecycle, `git branch -d`, `gh pr merge`, and `Agent` — one narrow rule per subcommand; `Bash(gh pr merge:*)` is admissible only while `main`'s applied protection keeps `Nix Eval` required with `enforce_admins` on (`just show-protection`), and a malformed allow rule never warns and never matches, so check a change with `just show-claude-settings` rather than by reading the diff.
```

Keep it in the same bullet, one sentence, no new bullet and no new sub-list.

- [ ] **Step 4: Verify — positive**

```bash
just show-claude-settings 2>/dev/null | jq -e '.permissions.allow | length == 16' >/dev/null && echo COUNT_OK
```
Expected: `COUNT_OK`. Note `jq -e` fails closed both ways — exit 1 on `false`, exit 4 if the
recipe produced no output at all (verified on this host), so an empty or missing artifact
cannot pass this line.

```bash
just show-claude-settings 2>/dev/null | jq -r '.permissions.allow[]'
```
Expected, in this exact order:

```
Bash(git fetch:*)
Bash(git status:*)
Bash(git log:*)
Bash(git diff:*)
Bash(gh pr view:*)
Bash(gh pr list:*)
Bash(gh pr checks:*)
Bash(gh issue view:*)
Bash(gh issue list:*)
Bash(git worktree add:*)
Bash(git worktree list:*)
Bash(git worktree remove:*)
Bash(git worktree prune:*)
Bash(git branch -d:*)
Bash(gh pr merge:*)
Agent
```

Compare byte for byte, not by eye-skimming: `:*` vs ` *`, `-d` vs `-D`, and a missing trailing
wildcard are all invisible at a glance and all change what the rule reaches.

```bash
just show-claude-settings 2>/dev/null | jq -e '.permissions.defaultMode == "auto" and (.permissions.ask | length == 0) and (.permissions.deny | length == 0)' >/dev/null && echo UNCHANGED_OK
```
Expected: `UNCHANGED_OK`.

- [ ] **Step 5: Verify — negative (the issue's second criterion)**

```bash
just show-claude-settings 2>/dev/null | jq -r '.permissions.allow[]' \
  | grep -nE 'config|\.git|branch -D|push|^Bash\(\*\)$|^Bash\([A-Za-z0-9_.-]+\*'
```
Expected: **no output, exit 1**. Any printed line is a rule that violates a negative criterion
(a `git config` reach, a `.git` path, `branch -D`, a `push`, a blanket rule, or a wildcarded
interpreter such as `Bash(python*)`) — fix the entry, do not relax the pattern. Verified that
the pattern's last alternative does not false-positive on the shipped entries, because every
one of them has a space before its wildcard.

- [ ] **Step 6: Verify — the build itself (AC3)**

```bash
just build >/dev/null && echo BUILD_OK
```
Expected: `BUILD_OK`, exit 0. Cached to a few seconds right after Step 4, since the recipe
already built this closure.

- [ ] **Step 7: Commit**

```bash
git add home/common/claude-code/default.nix CLAUDE.md
git commit -m "feat(claude-code): declare the agent-lifecycle permission allow list

Sixteen entries — fifteen one-subcommand Bash prefixes over git and gh,
plus the bare Agent tool entry — so lifecycle commands resolve by rule
instead of by the risk classifier, which has no prompt to fall back on
in a background `claude -p` run. gh pr merge is prefix-only and is
admissible only behind main's required Nix Eval check with
enforce_admins on; the Agent entry is inert under defaultMode = auto and
the comment says so.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011BW621YtNATjTJfsJSJXnB"
```

**Phase 6 ends here.** Do not proceed to Task 3 during plan execution.

---

### Task 3: SHIP-TIME ONLY — live demo, protection re-confirmation, issue thread

**This is not a Phase-6 task.** It requires `just switch` (sudo, and this repo switches only
when asked) and it posts to the live issue. Run it at ship time, after the branch's PR has
merged, as the `ship-issue` evidence step — per the spec's seam 3 and its
`## Discussion items for the issue thread`.

**Files:**
- Create (at ship time): `.claude/specs/2026-08-17-agent-lifecycle-permissions-evidence.md`,
  following the repo's existing `*-evidence.md` companion convention.

**Why it cannot be a plan gate:** seams 1 and 2 prove the rules are *present and well-formed*.
Neither can prove they *match*: there is no rule linter, a malformed allow rule produces no
warning, and R6 leaves open whether the engine drops a Bash rule this design believes it keeps.
Only an activated generation can settle it.

- [ ] **Step 1: Activate**

```bash
just switch
```

- [ ] **Step 2: Re-confirm the condition `Bash(gh pr merge:*)` depends on**

```bash
just show-protection | jq '{contexts: .required_status_checks.contexts, enforce_admins: .enforce_admins.enabled}'
```
Expected: `Nix Eval` among the contexts and `enforce_admins: true`. This is the live applied
protection, not `.github/branch-protection.json`, and the two can legitimately disagree (per
D9). **If it does not hold, the `Bash(gh pr merge:*)` entry must be removed in a follow-up
change** — that is the coupling the module comment states. GitHub answered 503 to this call
while the spec was being written; retry rather than recording an outcome from a failed call.

- [ ] **Step 3: Run the issue's demo**

Dispatch a background subagent that (a) creates a scratch worktree, (b) removes it with
`git worktree remove`, and (c) runs `gh pr view` — and record whether any permission denial
occurred. Also record whether the subagent's own `Agent` dispatch was classifier-gated, which
is the observation that confirms or refutes D1's expectation that the entry is inert.

- [ ] **Step 4: Record the evidence**

Write `.claude/specs/2026-08-17-agent-lifecycle-permissions-evidence.md` with the date, the
branch and commit it was run at, the exact commands, and their unedited outcomes — including a
negative outcome. An entry that turns out not to match is a finding to record, not a result to
round up.

- [ ] **Step 5: Post the two discussion items to the issue**

Per D1 and the spec's `## Discussion items for the issue thread`, and only after the evidence
is written:

1. The `Agent` bullet in the issue is **not** satisfied by this change — `Agent` allow rules
   are dropped in auto mode, so delegate dispatch stays classifier-gated until `defaultMode`
   changes. Raising this is part of shipping the issue.
2. R1 (`git -C <path> …`) is the largest remaining source of classifier non-determinism, it has
   no safe rule form (`*` matches across spaces, so `Bash(git -C * status:*)` would also reach
   `git -C /repo push origin status`), and the fix if it keeps costing runs is to change the
   *callers* to `cd`, not to widen the rule.
