# Agent-Lifecycle Permission Surface Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

Issue: https://github.com/fagenorn/nix-config/issues/30
Spec: `.claude/specs/2026-08-17-agent-lifecycle-permissions-design.md` — its `## Decision ledger`
(D1–D12) is the source of truth. This plan cites rows by ID and never restates them.

**Goal:** The Nix-declared global Claude Code settings ship the agent-lifecycle permission
surface — read-only git/tracker queries, worktree lifecycle, `git branch -d`, the `Agent` tool
and `gh pr merge` — so those commands resolve by rule instead of by a risk classifier that
stalls unattended `claude -p` runs, and the generated artifact is inspectable by a named command.

**Architecture:** Three product files change and no program logic does.
`home/common/claude-code/default.nix` gains sixteen strings in `permissions.allow` (fifteen
one-subcommand Bash prefixes plus a bare `Agent`) and loses the comment above `permissions`,
which asserts the list is deliberately empty and becomes false at the same commit. `justfile`
gains one ungated read-only recipe, `show-claude-settings`, that builds and then prints the
generated settings JSON out of the system closure (per D4/D5/D12), while both platform `build`
banners move to stderr so stdout is valid JSON from its first byte (per D11). This is the seam
both of the issue's inspection criteria are decided at. `CLAUDE.md` records the recipe and the
surface. Nothing else in the settings attrset moves: `defaultMode` stays `"auto"`, `ask` and
`deny` stay empty.

**Tech stack:** Nix (nix-darwin + home-manager module, `pkgs.formats.json`), `just` 1.43,
`nix-store`, `jq` 1.8, Markdown. No new flake input, no new test file, no new dependency.

## Global Constraints

- **Exactly three product paths change** across Tasks 1–3: `home/common/claude-code/default.nix`
  (modify), `justfile` (modify), `CLAUDE.md` (modify). No other `.nix` file, no file under
  `.github/`, or file under `home/common/agent-skills/` changes in Phase 6. Task 5's ship-time
  evidence companion is the only new file, and it is explicitly Phase 7.
- **The sixteen allow entries are a byte-exact contract**, in this order — the spec's tables and
  every gate below assume both the strings and the order:

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

  Do not add a seventeenth, do not reorder, do not "fix" a rule to a long flag form or a coarser
  prefix (per D2/D3), and do not spell the tool entry `Agent(...)` (per D1).
- **`defaultMode = "auto"` does not change, and `ask`/`deny` stay `[ ]`.** Both are explicitly out
  of scope in the spec; a `Bash(git config:*)` deny in particular would break `just evals`.
- **The negative criteria are properties of the shipped list**, not of a reviewer's attention: no
  entry may contain `config`, `.git`, `branch -D` or `push`, and none may be `Bash(*)` or a
  wildcarded interpreter such as `Bash(python*)`. Task 4 asserts this against the built artifact.
- **No new test file and no new entry in `just agent-workflow-tests`** (per D7).
- **`.claude/settings.local.json` is not touched** (per D6). It is untracked and globally ignored;
  it does not exist in this worktree at all.
- **Nothing about the CI gate or branch protection is touched**: not `.github/workflows/ci.yaml`,
  not `.github/branch-protection.json`, not the `protect-main` / `unprotect-main` /
  `show-protection` recipes. The applied protection is read at ship time (Task 5), never written.
- **Verification budget: exactly one cold `just build`, in Task 4.** Tasks 1–3 use source-level
  gates that run in under a second. `just build` takes several minutes on this host; do not run it
  per task. Never run `just switch` or any activation during Phase 6 — this repo switches only
  when asked, and the switch belongs to Task 5.
- **`./result` is gitignored** (`.gitignore` line 1) and a **stale** one from the design phase
  already exists in this worktree at the base commit, pointing at
  `/nix/store/…-darwin-system-25.11.ebec37a`. It is the live example of the hazard D5's `build`
  dependency exists for: never inspect it without building first, and never `git add` it.
- **Write scratch output outside the worktree** — `"${TMPDIR:-/tmp}/…"`, never a path under the
  repo, so `git status` stays clean.
- **Never disable commit signing.** No `-c commit.gpgsign=false`, no `--no-gpg-sign`; surface a
  signing failure rather than working around it. No `git config` writes, no edits under `.git/`,
  no `git branch -D`, no force push, no push at all during Phase 6.
- **Commit trailers**, on every commit, matching this branch's existing commits:

  ```
  Refs: https://github.com/fagenorn/nix-config/issues/30

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  ```
- **Payload discipline.** Summarise build output to the failing lines and the final status; never
  paste a whole `just build` run into a report. The settings artifact is captured to a file and
  queried with `jq`, not pasted.

## Test seams

The spec's three seams. A task that wants a fourth has found a plan bug.

1. **The generated settings artifact** — the store JSON, reached by `just show-claude-settings`
   (Task 2). This is where both inspection criteria are decided, positively (the sixteen entries,
   verbatim and in order) and negatively (no `config`, `.git`, `branch -D`, `push`, blanket or
   wildcarded-interpreter entry). Asserting on the built JSON rather than on the `.nix` source is
   the point: it is what Claude Code actually reads.
2. **`just build`, exit 0** — the repo's only verification step. Seam 1 depends on it, so both are
   satisfied by the one cold build in Task 4.
3. **The live demo, ship-time evidence and not a Phase-6 gate** — after a switch, a background
   subagent removes a scratch worktree and runs `gh pr view` with no permission denial. It is the
   only seam that can prove a rule *matches* rather than merely *exists*, and it needs
   `just switch` (sudo). Task 5.

**Per-task offline gates** (Tasks 1–3) are not seams; they are cheap falsifiable checks that the
edit landed as dictated, all verified runnable on this host at the base commit:

- `nix-instantiate --parse home/common/claude-code/default.nix` — parses without evaluating
  (0.1 s), catches a syntax error before the one build.
- `just --dry-run <recipe>` — prints a recipe's expanded commands, including its dependency's,
  and **executes nothing** (verified: a dependency `build` recipe printed but did not run).
- `just --list` — shows the recipe and the doc comment `just` extracts for it.
- `grep` over the three edited files.

Deliberately **not** a seam: any test that parses the `.nix` source for rule shape (per D7), and
`just switch` (Phase 6 never activates).

## Task index

| Task | Title | Files touched | Risk lane |
|------|-------|---------------|-----------|
| 1 | Declare the allow list and replace the false comment | `home/common/claude-code/default.nix` (modify) | **full** |
| 2 | Ship `just show-claude-settings` | `justfile` (modify) | **full** |
| 3 | Record the surface and the recipe in `CLAUDE.md` | `CLAUDE.md` (modify) | **low-risk** |
| 4 | The acceptance gate: one cold build + artifact inspection | no files; `just build`, `just show-claude-settings` | **full** |
| 5 | **SHIP-TIME ONLY — live evidence, NOT Phase 6** | `.claude/specs/2026-08-17-agent-lifecycle-permissions-evidence.md` (create, Phase 7) | **full** |

**Lane rationale.** Task 1 is **full** and is not mechanical whatever its line count suggests: it
changes generated output that a security decision engine reads, and it pre-authorizes destructive
commands (`git worktree remove --force`, `git branch -d`) and a release operation (`gh pr merge`,
whose `--admin` reachability is admissible only because of a live server-side gate, per D9). Task
2 is **full** because the recipe is the instrument both inspection criteria are decided by; a
stale `./result` would report superseded settings (D5), and a stdout banner would make its named
`jq` consumer unparsable (D11). Task 3 is **low-risk**: bounded documentation
whose content is fixed verbatim below, no behavioral or generated-output effect, and locally
verifiable by grep — but not `mechanical`, since it has semantic-documentation effect. Task 4 is
**full**: it edits nothing, and it is the only gate deciding whether a security-surface change is
correct. Task 5 is **full** and is not code — it activates a new permission policy on the live
machine and posts to the issue thread.

## Decisions

The spec owns the ledger. Rows this plan rests on: **D1** (`Agent` bare and knowingly inert;
`defaultMode` unchanged), **D2**/**D3** (one narrow rule per subcommand; `-d` only), **D4** (the
artifact-inspection route, and why the eval-then-realise route is broken), **D5** (the recipe,
ungated, depending on `build`), **D6** (`settings.local.json` untouched), **D7** (no new test),
**D8** (the comment rewrite and the two `CLAUDE.md` notes), **D9** (`gh pr merge` prefix-only),
**D10** (residuals named, not widened), **D11** (both `build` banners move to stderr), and
**D12** (the recipe intentionally keeps its `grep | xargs cat` body; artifact assertions fail
closed if it emits nothing). Planning requires no new issue-level decision beyond those rows.

---

### Task 1: Declare the allow list and replace the false comment

**Files:**
- Modify: `home/common/claude-code/default.nix` (the `settings` attrset, lines 43–51 at the base
  commit)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `settings.permissions.allow` — a Nix list of exactly the sixteen strings in the Global
  Constraints block, in that order. Tasks 4 and 5 read it only through the generated artifact,
  never through this file.

**Invariants:**
- `defaultMode` remains the string `"auto"`; `ask` and `deny` remain `[ ]`.
- Every Bash entry is a literal one-subcommand prefix terminated by `:*`; no entry contains a
  wildcard anywhere except as that trailing `*`.
- No entry contains `config`, `.git`, `branch -D` or `push`.
- The `settings` header comment at lines 19–21 is left exactly as it is; only the now-false
  comment directly above `permissions` is replaced (per D8).
- Every sentence in the new comment describes how the shipped configuration behaves at *this*
  commit. Nothing aspirational, nothing that a later change would silently falsify without also
  changing the line it sits next to.

- [ ] **Step 1: Confirm the criterion is false at the base commit**

```bash
grep -n 'allow = \[ \]' home/common/claude-code/default.nix
grep -n 'deliberately dropped' home/common/claude-code/default.nix
```

Expected: `48:      allow = [ ];` and `45:    # baseline, so it is deliberately dropped. Add durable global allows here if wanted.`
Both lines must be gone at the end of this task; if either grep finds nothing now, stop — the
worktree is not at the base commit this plan was written against.

- [ ] **Step 2: Replace lines 43–51 with the declared surface**

Replace the three-line comment and the four-line `permissions` attrset — everything from
`    # defaultMode = "auto" already auto-approves tool use; the large project-specific` through
`    };` — with exactly this. Indentation is four spaces for `permissions`, six for its keys,
eight for the list entries, matching the surrounding attrset.

```nix
    # `permissions.allow` is the agent-lifecycle surface: the commands the workflow skills run
    # unattended — read-only git/tracker queries, worktree lifecycle, `git branch -d`, `Agent`
    # dispatch and `gh pr merge`. It is declared here, at user scope, because project-scope
    # allow rules are never applied under `claude -p`, which is exactly where an unresolved
    # command stalls a background agent instead of prompting someone. It does not cover every
    # command those skills run; the residuals are named in the design.
    #
    # Two engine facts, both load-bearing for what is and is not in this list:
    #   * a Bash rule is a literal prefix, matched from position 0, case-sensitively, with no
    #     flag normalisation — so `-d` cannot reach `-D` — and a `*` matches across spaces,
    #     which is why there is no `git -C * <sub>` rule: it would also reach
    #     `git -C /repo push origin status`.
    #   * a malformed allow rule produces no warning; it silently never matches. Check a change
    #     to this list with `just show-claude-settings`, not by reading the diff.
    #
    # Rationale, residuals and rejected alternatives:
    # .claude/specs/2026-08-17-agent-lifecycle-permissions-design.md
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
        # command tolerates (a dirty tree), not what it destroys: the branch and its commits
        # survive. `git branch -d` refuses to delete an unmerged branch, and no rule here
        # reaches `-D`.
        "Bash(git worktree add:*)"
        "Bash(git worktree list:*)"
        "Bash(git worktree remove:*)"
        "Bash(git worktree prune:*)"
        "Bash(git branch -d:*)"

        # Prefix-only on purpose: ship-issue types `gh pr merge <n> --merge …`, argument before
        # flags, so a `--merge`-bearing prefix would never match — it would read safer and do
        # nothing. `--admin` is therefore reachable, and what refuses it is the server: while
        # `main`'s applied protection requires `Nix Eval` with enforce_admins on, GitHub rejects
        # the merge until that check is green (`just show-protection` prints what is applied).
        # REMOVE THIS ENTRY in the same change that removes that protection or turns
        # enforce_admins off.
        "Bash(gh pr merge:*)"

        # Inert as shipped: entering auto mode drops `Agent` allow rules — along with blanket
        # `Bash(*)` and wildcarded interpreters — and restores them on leaving, and
        # `defaultMode` above is `"auto"`. Kept because the rule is correct in plan and default
        # mode; written bare because how a plugin-namespaced type (`codex:codex-reviewer`) is
        # spelled inside `Agent(...)` is undocumented, and an unspellable rule silently never
        # matches.
        "Agent"
      ];
      ask = [ ];
      deny = [ ];
    };
```

- [ ] **Step 3: Verify at source level**

```bash
nix-instantiate --parse home/common/claude-code/default.nix > /dev/null && echo PARSE-OK
test "$(grep -c '^        "Bash(' home/common/claude-code/default.nix)" -eq 15 && echo BASH-COUNT-OK
test "$(grep -c '^        "Agent"$' home/common/claude-code/default.nix)" -eq 1 && echo AGENT-COUNT-OK
grep -n 'defaultMode = "auto";\|ask = \[ \];\|deny = \[ \];' home/common/claude-code/default.nix
test "$(grep -c 'defaultMode = "auto";\|ask = \[ \];\|deny = \[ \];' home/common/claude-code/default.nix)" -eq 3 && echo SHAPE-OK
grep -n 'deliberately dropped\|allow = \[ \]' home/common/claude-code/default.nix; stale_status=$?
test "$stale_status" -eq 1 && echo STALE-COMMENT-GONE
grep -nE '"(Bash|Agent)\([^)]*(config|\.git|branch -D|push)' home/common/claude-code/default.nix; forbidden_status=$?
test "$forbidden_status" -eq 1 && echo SOURCE-NEGATIVE-OK
```

Expected: all six `*-OK` markers, the three `permissions` key lines, and no output from either
negative grep. Each status assertion fails if its preceding grep errors as well as if it matches.

The `^        "Bash(` anchor is deliberate — it counts entries at list indentation only, so a
rule mentioned inside a comment cannot inflate the count. If a count is wrong, fix the list, not
the anchor.

- [ ] **Step 4: Commit**

```bash
git add home/common/claude-code/default.nix
git commit -m "$(cat <<'EOF'
feat(claude-code): declare the agent-lifecycle permission surface

permissions.allow was empty under defaultMode = "auto", which sent every
lifecycle command an unattended agent runs to the risk classifier and stalled
`claude -p` runs past auto mode's escalation threshold.

Sixteen entries: fifteen one-subcommand Bash prefixes over git and gh, plus a
bare Agent. Shapes are derived from the invocations the skills actually type,
so `gh pr merge` is prefix-only; its reachable --admin is refused by GitHub
while main's applied protection requires Nix Eval with enforce_admins on. The
issue's negative criteria hold by construction: matching is case-sensitive with
no flag normalisation, so `git branch -d` cannot reach `git branch -D`.

The comment above permissions claimed the allow list was deliberately dropped,
which this commit makes false; it is replaced with the two engine facts a future
editor needs and the per-entry conditions.

Refs: https://github.com/fagenorn/nix-config/issues/30

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Ship `just show-claude-settings`

**Files:**
- Modify: `justfile` (the two platform `build` banners, plus a new section between
  `agent-model-matrix` and `## branch protection`)

**Interfaces:**
- Consumes: nothing from Task 1 — the recipe is content-agnostic and works at any commit.
- Produces: the command `just show-claude-settings`, which prints the generated settings JSON on
  stdout and nothing else. Task 3 documents this name, Task 4 gates on it, Task 5 cites it.
- Produces: both `build` variants retain their human-facing progress banner on stderr, leaving
  stdout available to the recipe's JSON contract.

**Invariants:**
- The recipe depends on `build`, so it can never print a `./result` older than the current source
  (per D5). The stale `./result` already in this worktree is the case that proves this matters.
- The recipe is ungated — no `[macos]`/`[linux]` attribute, no username, no home-manager attribute
  path. `just` resolves the `build` dependency to whichever platform's recipe is enabled.
- stdout is the JSON alone: the `@` prefix suppresses command echo and both `build` banners move
  to stderr (per D11). No consumer strips or skips a line.
- The body remains the spec's `grep | xargs cat` shape (per D12). A zero-match invocation can
  print nothing and exit 0; Task 4's `jq -e` and explicit closure-count checks are the fail-closed
  acceptance gates. Do not invent a second guard in the recipe.

- [ ] **Step 1: Confirm the red state**

```bash
just --list | grep -c show-claude-settings   # 0
grep -c '^  @echo "Building .*\.\.\."$' justfile   # 2
```

Expected: `0` then `2`. The first grep exits 1 because the recipe is absent; the second proves
both banners still go to stdout. Both observations must be false after this task.

- [ ] **Step 2: Move both build banners to stderr**

Append `>&2` to the `@echo` line in each platform's `build` recipe and change nothing else:

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

The banner remains visible to a human; only its stream changes. This is D11's required
adaptation of the recipe to the live justfile.

- [ ] **Step 3: Insert the recipe**

After the `agent-model-matrix` recipe's last line (`  python3 home/common/agent-skills/scripts/agent-model-matrix.py trace representative`) and
before the `## branch protection` header, insert a blank line and then exactly:

```just
## claude code
# Print the Nix-generated ~/.claude/settings.json exactly as the next switch will write it.
show-claude-settings: build
  @nix-store --query --requisites ./result \
    | grep -- '-claude-code-settings\.json$' \
    | xargs cat
```

Three details are load-bearing and easy to lose:

- The recipe is ungated. Do not add `[macos]`/`[linux]` variants.
- It takes no parameters; `build` already defaults `target_host` from `hostname`.
- Keep the `grep | xargs cat` body verbatim per D12. The acceptance command, not this body,
  supplies the zero-output failure signal.

- [ ] **Step 4: Verify without building**

```bash
just --list | grep -A0 'show-claude-settings'
just --dry-run show-claude-settings; dry_run_status=$?
test "$dry_run_status" -eq 0 && echo DRY-RUN-OK
test "$(grep -c '^  @echo "Building .*\.\.\." >&2$' justfile)" -eq 2 && echo BANNERS-OK
test "$(grep -c '| xargs cat' justfile)" -eq 1 && echo BODY-OK
```

Expected: `--list` shows
`show-claude-settings                # Print the Nix-generated ~/.claude/settings.json exactly as the next switch will write it.`;
`--dry-run` prints the enabled platform's `build` commands followed by the three-stage
`nix-store | grep | xargs cat` pipeline, executes nothing, and all three `*-OK` markers print.

`--dry-run` executing nothing is verified behaviour on this host, not an assumption: it printed a
dependency recipe's command without running it. If the build actually starts, stop — the recipe
was written with a `!` shebang or otherwise diverges from the dictated form.

- [ ] **Step 5: Commit**

```bash
git add justfile
git commit -m "$(cat <<'EOF'
feat(justfile): add show-claude-settings and make build output pipeable

The Claude Code settings JSON is a let-bound store path, not a flake output, so
"inspect the generated artifact" needed a route. Evaluating the activation
script and realising the path it names is broken once the content changes --
nix eval registers no deriver -- so the recipe greps the settings file out of
the system closure `just build` already produces, and depends on `build` so a
stale ./result can never be reported as current.

Both platform build banners move to stderr so the recipe's stdout starts with
JSON and can be consumed directly by jq. The recipe retains the design's
grep-and-xargs body; its acceptance assertions fail closed on empty output.

Refs: https://github.com/fagenorn/nix-config/issues/30

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Record the surface and the recipe in `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (the `## Commands` fence, and the second bullet of the
  **Claude Code is declaratively managed** list)

**Interfaces:**
- Consumes: the command name `just show-claude-settings` (Task 2) and the fact that
  `permissions.allow` is populated (Task 1). Both must already be committed; this task documents
  behaviour that exists, it does not announce behaviour that is coming.
- Produces: nothing another task consumes.

**Invariants:**
- Both additions describe the repository as it stands at this commit. No forward-looking sentence.
- No other line of `CLAUDE.md` is touched — in particular the `Nix Eval` / `protect-main`
  paragraph, which the sibling issue wrote, is left exactly as it is.

- [ ] **Step 1: Confirm the notes are absent**

```bash
grep -c 'show-claude-settings' CLAUDE.md      # 0
grep -c 'permissions.allow' CLAUDE.md         # 0
```

Expected: `0` twice.

- [ ] **Step 2: Add the recipe to the Commands fence**

Append one line at the end of the ```sh fence in `## Commands`, after
`just install <IP>     # remote-provision a fresh NixOS box over SSH`:

```
just show-claude-settings # print the generated ~/.claude/settings.json (builds first)
```

The recipe name is 25 characters and the fence's comment column is 23, so this line's `#` sits two
columns right of the others. That is deliberate: re-aligning the block would rewrite eight lines
this plan does not own for a cosmetic gain. Leave the other lines alone.

- [ ] **Step 3: Add one sentence to the claude-code bullet list**

In the **Claude Code is declaratively managed** list, append to the end of the second bullet —
the one ending `**Edit settings in `default.nix`; do not edit `~/.claude/settings.json` directly (it resets on rebuild).**` —
a single space and then exactly:

```
The `permissions.allow` list in that attrset is the declared agent-lifecycle surface (read-only git/tracker queries, worktree lifecycle, `git branch -d`, `Agent`, `gh pr merge`), declared at user scope because project-scope allows are never applied under `claude -p`; `Bash(gh pr merge:*)` is admissible **only** while `main`'s applied protection requires `Nix Eval` with `enforce_admins` on (`just show-protection`), the bare `Agent` entry is dropped for as long as `defaultMode = "auto"`, and a malformed rule never warns and silently never matches — so check a change to the list with `just show-claude-settings`, which prints the built artifact, rather than by reading the diff.
```

- [ ] **Step 4: Verify**

```bash
test "$(grep -c 'show-claude-settings' CLAUDE.md)" -eq 2 && echo RECIPE-DOC-OK
test "$(grep -c 'agent-lifecycle surface' CLAUDE.md)" -eq 1 && echo SURFACE-DOC-OK
git diff --stat -- CLAUDE.md
```

Expected: both `*-OK` markers and a diffstat of `2 insertions(+), 1 deletion(-)` — one new fence
line, plus the bullet's single long line rewritten in place.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(claude): record the permission surface and its inspection recipe

Two notes in the places that already carry this kind of fact: the recipe in the
Commands block, and one sentence in the claude-code bullet list recording that
permissions.allow is the declared agent-lifecycle surface, that the gh pr merge
entry is coupled to main's applied protection, that the Agent entry is dropped
under auto mode, and that a malformed rule fails silently -- so a change is
checked with the recipe rather than by reading the diff.

Refs: https://github.com/fagenorn/nix-config/issues/30

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The acceptance gate — one cold build and the artifact inspection

**Files:**
- Modify: none. This task edits no file and makes no commit; its deliverable is the recorded
  evidence in the task report.

**Interfaces:**
- Consumes: `permissions.allow` from Task 1 and `just show-claude-settings` from Task 2, both
  already committed.
- Produces: the recorded outcome of the issue's acceptance criteria 1–3. Task 5 cites it.

**Invariants:**
- The build is cold and takes several minutes. Run it once. Do not run `just build` per task, and
  do not run `just switch`.
- The artifact is captured once to a file outside the worktree and every assertion is made against
  that file, so `git status` stays clean. The closure is queried once explicitly to prove it
  contains exactly one settings artifact, then once inside the named recipe that captures it.
- Every assertion below can fail at the base commit — the empty allow list fails the count, the
  diff and the `defaultMode`/`ask`/`deny` shape check alike.

- [ ] **Step 1: Build (acceptance criterion 3)**

```bash
just build; build_status=$?
echo "build-exit=$build_status"
test "$build_status" -eq 0
```

Expected: `build-exit=0`. Summarise: the last line of output plus the exit code. If it fails,
report the first Nix error line and stop — nothing below is meaningful.

- [ ] **Step 2: Capture the artifact once**

```bash
SETTINGS_PATHS="$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')"
printf '%s\n' "$SETTINGS_PATHS"
test "$(printf '%s\n' "$SETTINGS_PATHS" | grep -c .)" -eq 1 && echo ONE-SETTINGS-PATH
OUT="${TMPDIR:-/tmp}/claude-settings-issue30.json"
just show-claude-settings > "$OUT"
jq -e 'type == "object"' "$OUT" > /dev/null && echo CAPTURE-OK
```

Expected: one printed `/nix/store/…-claude-code-settings.json` path,
`ONE-SETTINGS-PATH`, and `CAPTURE-OK`. The capture has no `tail`/`sed` workaround: D11 requires
the build banner on stderr, so the first stdout byte is `{`. `jq -e` therefore catches both an
empty D12 pipeline and any stdout regression. This second `just` invocation re-runs `build`
against a now-warm store; it is an evaluation, not a rebuild.

- [ ] **Step 3: Assert the sixteen entries, verbatim and in order (acceptance criterion 1)**

```bash
jq -r '.permissions.allow[]' "${TMPDIR:-/tmp}/claude-settings-issue30.json" | wc -l   # 16
jq -r '.permissions.allow[]' "${TMPDIR:-/tmp}/claude-settings-issue30.json" | diff - <(cat <<'EOF'
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
EOF
); diff_status=$?
echo "diff-exit=$diff_status"
test "$diff_status" -eq 0
```

Expected: `16`, no diff output, `diff-exit=0`.

If only the *order* differs, do **not** reorder the Nix list to match. `builtins.toJSON` preserves
list order, so a reordering means the artifact is not what the module declares, and that is a
finding to report rather than a diff to silence.

- [ ] **Step 4: Assert the negative criteria (acceptance criterion 2)**

```bash
OUT="${TMPDIR:-/tmp}/claude-settings-issue30.json"
jq -r '.permissions.allow[]' "$OUT" | grep -nE 'config|\.git|branch -D|push'; forbidden_status=$?
test "$forbidden_status" -eq 1 && echo FORBIDDEN-ABSENT
jq -r '.permissions.allow[]' "$OUT" | grep -nE '^Bash\(\*\)$|^Bash\([A-Za-z0-9_.-]+\*'; blanket_status=$?
test "$blanket_status" -eq 1 && echo BLANKET-ABSENT
jq -e '.permissions.defaultMode == "auto" and (.permissions.ask | length == 0) and (.permissions.deny | length == 0)' "$OUT" > /dev/null && echo PERMISSION-SHAPE-OK
jq -e '[.permissions.allow[] | select(startswith("Bash(")) | select(endswith(":*)") | not)] | length == 0' "$OUT" > /dev/null && echo BASH-SHAPES-OK
```

Expected: both greps print nothing and all four `*-OK` / `*-ABSENT` markers print. A grep error
does not pass: only status 1 means the forbidden form was absent.

- [ ] **Step 5: Record and clean up**

```bash
rm -f "${TMPDIR:-/tmp}/claude-settings-issue30.json"
git status --short   # empty
```

Report, in the task report and not in a new file: `just build` exit code, the sixteen-line
`jq` output, the two forbidden-pattern greps' exit codes, and `$SETTINGS_PATHS`. Nothing is
committed by this task.

Seams 1 and 2 are now closed. Neither proves a rule *matches* — no offline check can, since there
is no rule linter and a malformed allow rule never warns. That is Task 5's job, and it is why the
issue is not finished when this task is green.

---

### Task 5: SHIP-TIME ONLY — live evidence and the discussion items (NOT Phase 6)

**Do not run this during plan execution.** It activates a new permission policy on the live
machine (`just switch`, sudo) and writes to the issue thread. It runs after this branch's PR has
merged, as part of shipping, and only when the operator has asked for the switch.

**Files:**
- Create (Phase 7): `.claude/specs/2026-08-17-agent-lifecycle-permissions-evidence.md`, following
  the repo's existing `*-evidence.md` companion convention.

**Interfaces:**
- Consumes: Task 4's recorded artifact inspection, and the merged branch.
- Produces: the ship-time evidence file and the issue-thread discussion record.

**Invariants:**
- The evidence file records what was run and what it printed. A step that was not run is recorded
  as not run, never as passed.
- `just show-protection` is read, never rewritten, and no `protect-main` / `unprotect-main` is run.

- [ ] **Step 1: Confirm the merge gate is still what `Bash(gh pr merge:*)` rests on**

```bash
PROTECTION_JSON="$(just show-protection)"; protection_status=$?
test "$protection_status" -eq 0
printf '%s\n' "$PROTECTION_JSON" | jq '{contexts: .required_status_checks.contexts, strict: .required_status_checks.strict, enforce_admins: .enforce_admins.enabled}'
printf '%s\n' "$PROTECTION_JSON" | jq -e '(.required_status_checks.contexts | index("Nix Eval") != null) and (.enforce_admins.enabled == true)' > /dev/null && echo MERGE-GATE-OK
```

Expected: the projection contains `Nix Eval`, `enforce_admins` is `true`, and `MERGE-GATE-OK`
prints. This is the condition
under which D9 admits a prefix-only `gh pr merge` rule with a reachable `--admin`. If it is not
true, the `Bash(gh pr merge:*)` entry must be removed in the same change that removed the
protection — that is what the module comment says, and this is the step that catches it.

If the endpoint answers HTTP 503 (it did, transiently, while the design was being written), that
is a GitHub-side failure, not a protection change: retry, and record the retry in the evidence
file. Do not change `show-protection` and do not add a fallback path to it — both are out of
scope for this issue.

- [ ] **Step 2: Activate, when the operator asks**

```bash
just switch
jq -e '.permissions.allow | length == 16' ~/.claude/settings.json > /dev/null && echo LIVE-SETTINGS-OK
```

Expected: `LIVE-SETTINGS-OK` — the activation script copies the store file over `~/.claude/settings.json`
unconditionally on every activation, so the live file is the artifact Task 4 inspected.

- [ ] **Step 3: The live demo (acceptance criterion 4)**

In a **new** Claude Code session (settings are read at startup), dispatch a background subagent
with the merged PR number and this exact job: choose a unique nonexistent path under
`${TMPDIR:-/tmp}`, run `git worktree add --detach <path> HEAD`, remove it with
`git worktree remove <path>`, then run
`gh pr view <merged-pr-number> --json number,state,url`. Tell it to return each command, exit
status, and any permission prompt or denial verbatim; it must not use `--force`, delete a branch,
or perform any other write. Record the result even if the `Agent` dispatch itself is denied.

This is the only observation that can distinguish a rule that matches from a rule that merely
exists, and it is the only check on residual R6 — whether the engine drops a Bash entry this
design believes it keeps.

- [ ] **Step 4: Post the two discussion items to the issue**

Comment on https://github.com/fagenorn/nix-config/issues/30 with, per the spec's
*Discussion items* section: (a) the `Agent` bullet is **not** satisfied by this change — `Agent`
allow rules are dropped under `defaultMode = "auto"`, so delegate dispatch stays
classifier-gated until `defaultMode` changes; and (b) R1 (`git -C <path> …`) is the largest
remaining source of classifier non-determinism and has no safe rule form, so the fix if it keeps
costing runs is to change the callers to `cd`, not to widen the rule.

- [ ] **Step 5: Write the evidence file and commit**

Record: the protection reading from Step 1, the `just switch` outcome and the live
`~/.claude/settings.json` entry count, the demo transcript excerpt from Step 3 (which commands
ran, whether any prompted), and the issue-comment URL or URLs for both discussion items.

```bash
git add .claude/specs/2026-08-17-agent-lifecycle-permissions-evidence.md
git commit -m "$(cat <<'EOF'
docs(specs): record ship-time evidence for the permission surface

Refs: https://github.com/fagenorn/nix-config/issues/30

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```
