# Shell-form contracts: skill examples the worktree checker can verify — issue 154

Design for [#154](https://github.com/fagenorn/nix-config/issues/154), one slice of
[#99](https://github.com/fagenorn/nix-config/issues/99), 2026-09-23. Siblings:
[#153](https://github.com/fagenorn/nix-config/issues/153) (dispatch contracts,
merged at `a6ac80f`), [#155](https://github.com/fagenorn/nix-config/issues/155)
(prose consolidation), [#100](https://github.com/fagenorn/nix-config/issues/100)
(strict project resolver). Decisions D1–D18 bind the plan; planning added
D19–D21, plan review D22, the amendment after merging origin/main `185cc1a`
(#171's lifecycle calls) D23–D25, and the plan amendment D26.

## Problem

The #99 audit counted 417 recurring agent error turns across four classes. The
number is a count of error turns — not an HTTP status, not a provider or
transport failure. The largest class, 197 turns, is shell the harness's worktree
isolation checker refuses: 71 chained or piped commands, 68 redirects or
heredocs, 57 other. The shared skills teach those shapes: a pre-flight that pipes
`git worktree list` into `grep`, a PR body fed through `"$(cat <<'EOF' …)"`, a
release pre-flight guarded by `2>/dev/null || true`, and the `worktrees` skill's
own isolation probe, which chains, pipes and redirects in two lines. An agent
that copies an example faithfully produces an error turn.

The checker is harness code with no source in this repo. The installed binary
(Claude Code 2.1.280, read 2026-09-23) parses each command and refuses one it
cannot verify with "…is too complex to verify that it stays inside the
worktree", and its remedy text is "Split it into plain, separate commands and
run them from <worktree>." Its exact rules are version-bound (the same release
notes "certain nested shell expansions … are now refused"), so the fix states
the stable invariant and holds the skills to shapes every version accepts.

A prose fix alone rots, and a search that cannot see into `"$(…)"` or tell a
pipe from the `|` of a report shape (`clean | residuals | unknown`) cannot hold
it. The fix is guidance, rewritten examples, and a contract sweep with one
parser that source trees, installed trees and fixtures all go through.

## Solution

### The checker contract, as guidance (D6)

`worktrees/SKILL.md` gains `## Shell forms the isolation checker refuses`, a
sibling placed after `## Already positioned? Skip the call`, in that section's
shape: an evidence line (197 error turns, roughly four times the redundant-entry
class — the largest single class), then the contract and what works instead.

- **Contract.** The checker runs a command only when it can verify the command
  stays inside the worktree, and it can do that for one plain command whose
  targets are literal arguments. Shell control flow and redirection hide the
  target, so it refuses them rather than guess. The section names the four
  shapes that do this, in those words: a multi-clause chain (`&&`, `||`, `;`),
  a pipe, a redirect (including `2>/dev/null`), and a heredoc fed to a
  command's stdin.
- **What works instead.** One command per call; a dependent step is the next
  call, decided by reading the previous call's exit status and output. Filter or
  count output by reading it, not by piping it. Create files with the
  file-writing tool and pass them by path where the CLI takes one
  (`--notes-file`, `-F <file>`), or pass a body as one literal quoted argument
  with no substitution inside it. Carry the
  directory inside the invocation (`git -C <path>`, absolute paths under the
  worktree root), never a `cd … &&` prelude. Treat a non-zero exit as
  information rather than suppressing stderr. Refused → change the shell form,
  never the isolation.
- **The one sanctioned chain.** The `unset GITHUB_TOKEN && ` prefix that
  `from-issue/bindings.md`'s tracker-cli hygiene prescribes stays exactly as
  spelled there: the lifecycle guard accepts that literal and nothing looser
  (D5).
- **The one sanctioned pipeline.** A lifecycle helper call — one heredoc-fed
  `workflow-state` command, optionally piped into or out of `artifact-budget
  validate-report --input -` — stays exactly as `from-issue/SKILL.md`'s
  lifecycle-call rule spells it, since a request file would reverse #171's
  no-file rule. The shape belongs to those whole-allowed helpers alone: never
  copy a pipe or heredoc into another command on its strength. Should the
  checker refuse one, report the refusal rather than reshape the call: that
  rule owns its form (D23).

No rule table: the section names the invariant, the four forms and the remedy,
nothing version-specific (D6).

The existing `## Detect existing isolation` probe becomes one invocation,
`git rev-parse --path-format=absolute --git-dir --git-common-dir
--show-superproject-working-tree`, with prose: compare the first two lines —
different means a linked worktree (report the path and branch and stop),
identical means the default checkout; the superproject flag prints **no line at
all** outside a submodule, so a third line means a submodule, which is not
isolation. `--path-format=absolute` is load-bearing (D25): without it git prints
the common dir relative to the working directory, so a subdirectory of the
default checkout prints `/…/.git` over `../../.git` and reads as a linked
worktree. Verified on git 2.51.2, exit 0 each: the default checkout's root and a
subdirectory print two identical lines, a linked worktree's root and a
subdirectory two distinct lines.

### Where examples live, and how they are found (D1, D2)

A **living shared-skill example** is shell text shown in a `*.md` document under
either source skill tree — shared (`home/common/agent-skills/skills`) and
Claude-only (`home/common/claude-code/skills`) — outside any `evals/` directory.
Every skill is in, including `ship-release`, which never runs in a worktree: the
audit counts error turns, not sites, and a shape taught anywhere is copied
everywhere (retained D4). Excluded: eval fixtures, executable scripts under a
skill, agent definitions and global guidance (measured: zero offenders), and
`.claude/specs`/`.claude/plans` point-in-time records.

Three region kinds carry examples. Fences nest; the innermost opener's info
string decides, and a closer must be a bare run at least as long as its opener
(retained stack-based `FENCE`), so a `bash` fence inside a ````` ````markdown `````
plan template is still a shell fence. A fence body is read as CommonMark reads
fenced content: each body line loses up to as many leading spaces as its opener
is indented, so a fence inside a list item scans like a top-level one;
delimiters are still recognised at any indentation (D24). A line indented past
its fence keeps the excess, so a heredoc terminator indented relative to its
fence is not the exact line bash's `<<` needs: the example stays open and is
`unparseable`.

1. **Shell fences** — first word of the info string in
   `{bash, sh, shell, console, zsh}`: the whole body is shell.
2. **Ambiguous fences** — unlabeled or `text`: they also hold prompts, diagrams
   and JSON, so a line is an example only when its **command head** is in the
   closed command vocabulary; the example extends across `\` continuations and
   across any quote, substitution or heredoc it leaves open. This is what catches
   the bare-fence PR-body heredocs the retained extractor missed.
3. **Inline code spans** in prose, with the same command-head rule.

Other fences (`markdown`, `json`, `python`, …) are not shell. The command head is
the first word after repeatedly stripping leading `${VAR}` expansions and
`VAR=$(` openers (so `PR_BODY=$(${GH_PREFIX}gh …` heads `gh`); a basename is
compared, so a `~/.agents/bin/diff-scope` path matches `diff-scope`. A plain
`NAME=value` assignment has no head. The vocabulary is a closed constant of
command names the skills run; a guard keeps it honest (D14).

### The classifier (D3, D4)

One public function, `refused_examples(document_text)` → an ordered tuple of
findings `(line, form, example)`, one per refused form per example, `line` being
the line of the offending operator. It is the only entry point: the source
sweep, the installed sweep and every fixture call it on a document's text.

Inside it, a small scanner walks each example tracking single quotes, double
quotes, `$(…)` (also inside double quotes), `$((…))`, comments and heredoc
bodies. Operators count only in live shell context — top level or inside a
command substitution, including one nested in a `${…}` or `$((…))` expansion
(D22) — never inside quoted literal text, a comment or a heredoc
body. Angle-bracket placeholders (`<pr-num>`: `<`, a non-space, …, a non-space,
`>`) are removed first, so `cmd < in > out` still reds. The closed form set:

| Form | Matches |
|---|---|
| `chain` | `&&`, `\|\|`, `;`, a lone `&` |
| `pipe` | `\|`, `\|&` |
| `redirect` | `<`, `>`, `>>`, `N>`, `&>`, `>&`, `<(` |
| `heredoc` | `<<`, `<<-`, `<<<` (stdin fed from the document) |
| `unparseable` | an example the scanner cannot close (unterminated quote, substitution or heredoc) |

`unparseable` is fail-closed: an example the classifier cannot vouch for reds,
as the harness refuses what it cannot parse; a fence still open at the end of a
document is `unparseable` at its opener line, since its extent is unknowable.
Command substitution itself is not a refused form (D8). A newline inside a shell
fence separates successive calls, not a chain.

**Sanctioned prefix (D5).** An example that begins with exactly the lifecycle
guard's literal `unset GITHUB_TOKEN && ` is classified without it, and a
finished example that is only that literal (the inline mention in hygiene prose)
yields nothing. The exemption never ends a call: in a fence the literal's
trailing `&&` keeps the call open (D19), so a prefix line and the command after
it are one call, classified whole by this rule. The literal is not restated: the
test module reads it from the guard's single `UNSET_GITHUB_TOKEN_PREFIX = "…"`
assignment in `home/common/claude-code/default.nix` and fails loud unless
exactly one exists. `unset GITHUB_TOKEN; gh …` or any other spelling is still a
`chain`.

**Sanctioned lifecycle helper call (D23).** An example that is one pipeline — no
chain, no redirect, no command substitution — whose every segment's command head
is a whole-allowed helper, and whose every heredoc is `<<` with a quoted
delimiter, drops its `pipe` and `heredoc` findings; an `unparseable` still reds,
and an example that misses any condition is classified in full. The helpers are
not restated: the test module reads the basenames of `default.nix`'s single-word
`"Bash(<word>:*)"` allow entries — today `workflow-state` and `artifact-budget`,
bare and by `~/.agents/bin` path — and fails loud when there are none. This is
the shape #171 prescribes for every lifecycle call (its D22: one heredoc-fed
command, no request file), shaped so its D18 whole-helper allow rules match each
segment; a pipe or heredoc headed by any other command is still refused.

### Example rewrites (D7, D9–D11)

Measured on `a6ac80f` with a prototype of the classifier above: 24 offending
examples in 10 documents; 5 keep the sanctioned prefix, 19 are rewritten in 8
documents. Every rewrite keeps the example's meaning.

Re-measured at `a311fda` (origin/main `185cc1a` merged) with the committed
classifier: every rewrite site's text is unchanged — only line numbers moved —
and the `worktrees` probe is already rewritten, leaving 18 in 7 documents; the 5
prefix sites yield nothing. Main added 8 lifecycle helper calls in 3 documents
(13 `pipe`/`heredoc` findings, one of them `unparseable` from an indented
fence), which D23 and D24 keep rather than rewrite. A prototype applying
D23–D24 reports exactly the 18.

| Site (text unchanged at `a311fda`) | Forms | Disposition |
|---|---|---|
| `worktrees/SKILL.md` isolation probe | chain, pipe, redirect | single `git rev-parse --path-format=absolute` + three-line prose above (adapted, D25) |
| `from-issue/SKILL.md` direct-owner, build-delivery, finish; `ship-issue/SKILL.md` checkpoint, finish; `orchestrate-issues/SKILL.md` init-run, build-delivery, control (added by #171) | pipe, heredoc | kept — lifecycle helper call (D23); from-issue's build-delivery fence sits in a list item and is read de-indented (D24) |
| `from-issue/SKILL.md` pre-flight `git worktree list \| grep …` | pipe | `git worktree list`, then keep the entries whose branch starts `<worktreePrefix>issue-<num>-` (new) |
| `from-issue/bindings.md`, `from-issue/REVIEW-CONTRACT.md`, `ship-issue/SKILL.md` gh hygiene, `ship-release/SKILL.md` gh hygiene and Phase 4 | chain | kept — sanctioned prefix (D5) |
| `ship-issue/SKILL.md` Phase 4 and `HUMAN-GATE.md` Gate 1 PR creation | heredoc | the guard's exact form `gh pr create --repo <repoSlug> --base <integrationBranch> --head <branch> --title "<title>" --body "<body>"`, the body one literal double-quoted argument that may span lines and carries no `"`, `$`, backtick or backslash; Gate 1's "heredoc expanded" becomes "body fully rendered" (D11) |
| `ship-issue/SKILL.md` docs-only check | pipe | `git diff --name-only <base>..HEAD` — every path ends in `.md` → skip (recovered) |
| `ship-issue/CI-MERGE.md` banned-polling evidence | pipe | "a bare `gh pr checks <n>`, filtered for a single check, 244 times" (recovered, D9) |
| `ship-issue/SYNC.md` settings.json row | chain | `git restore --staged …`, then `git checkout HEAD -- …` (recovered) |
| `ship-release/CHANGELOG.md` single-branch `PREV` | redirect | drop `2>/dev/null`; with no tag the command exits non-zero and `PREV` is empty — the whole history (recovered, D10) |
| `ship-release/SKILL.md` no-forge local merge; Phase 0 local-behind | chain | check out, then — only if that succeeded — merge (recovered) |
| `ship-release/SKILL.md` Phase 0 ahead check | pipe | output non-empty, one merge per line (recovered) |
| `ship-release/SKILL.md` Phase 0 single-branch `PREV` | chain, redirect | plain `git describe --tags --abbrev=0 origin/<default>`; a non-zero exit there (no tag: first release) means an empty `PREV`, not a failed pre-flight (adapted, D10) |
| `ship-release/SKILL.md` Phase 0 local-ahead | pipe | "quoting its first 20 lines" (recovered) |
| `ship-release/SKILL.md` Phase 2 release PR | heredoc | body written with the file-writing tool to a path outside the working tree, passed as `--body-file <release-body-path>` (recovered, D11) |
| `ship-release/SKILL.md` Phase 4 "don't" sentence | chain | "don't check out `<default>` to merge it locally" (recovered, D9) |
| `ship-release/SKILL.md` 4.5b tag fetch | chain, redirect | `git remote get-url origin` and `git fetch --tags --quiet origin` as two calls; skip the fetch when the first exits non-zero (recovered) |
| `ship-release/SKILL.md` 4.5c previous tag | pipe | `git for-each-ref --count=1 --merged "$MERGE_SHA" --sort=-v:refname --format='%(refname:short)' 'refs/tags/v[0-9]*'` — its one line is `PREV_TAG`, no output is the bootstrap case (adapted, D12) |
| `ship-release/SKILL.md` 4.5f release notes | redirect | `gh pr view … -q .body`, write that body with the file-writing tool to `<release-notes-path>` outside the working tree, `gh release create … --notes-file <release-notes-path>`, then `rm <release-notes-path>` (recovered, adapted) |
| `ship-release/SKILL.md` 5d railway adapter | pipe | `railway deployment list --service <name> --json`, then read the five newest entries' fields in prose (recovered) |

`writing-plans`' `if grep -q …; then exit 1; fi` gate text (retained D18) no
longer exists in the tree; nothing to dispose.

### The installed skill tree (D13)

"Installed" keeps #153's meaning: the built `home-manager-files` output,
addressed by `AGENT_SKILLS_INSTALLED_HOME`, in a Claude view (`.claude/skills`:
shared and Claude-only documents) and a Codex view (`.agents/skills`: shared
documents). The installed sweep enumerates the documents from the source trees
and reads each one's installed copy by relative path, so a document the build
dropped is a failure, not a silent pass, and no walk of the installed links is
needed. Skills installed from elsewhere (UI/UX Pro Max) are
not source-authored and not swept. Unset variable → skip naming the recipe;
empty, relative, non-directory, or a missing view → fail (#153 D8, D16).

The tree and view layout becomes one support module both suites import, so the
variable name, recipe and view table have one home (D13).
`agent-installed-skill-tests` runs both modules with the variable set.

### Selective recovery (D15)

Retained branch `worktree-issue-99-skill-prose-fixes`, one WIP commit
`3c9709ca470bd473d49b39a611ca6cab258973db` (parent `95b6caf`), stays read-only:
hunks are read with `git show`/`git diff 95b6caf 3c9709ca`, re-applied by hand,
never checked out, cherry-picked, merged or rebased; the tip is confirmed
unchanged at the end.

| Retained hunk | Disposition |
|---|---|
| `worktrees` "Shell forms the isolation checker refuses" section | adapted: named alternatives kept; pipes added; `--body-file` dropped from the examples, the literal argument added; sanctioned-prefix sentence added (D5, D6, D11) |
| `worktrees` single `git rev-parse` probe and its prose | adapted: `--path-format=absolute` added, so a default-checkout subdirectory no longer reads as a linked worktree (D25) |
| `SHELL_FENCE_INFO`, stack-based `FENCE`, `command_head`, `PLACEHOLDER`, `SHELL_COMMANDS` | adapted into the classifier: `zsh` added, placeholder pattern tightened to non-space edges, heads compared by basename, vocabulary widened and guarded (D2, D14) |
| `HEREDOC`/`CHAIN`/`REDIRECT` regexes, `shell_commands`, `without_placeholders`, the four per-form tests and the whole-document heredoc test | replaced by the quote/substitution-aware scanner and fixture classes (D3, D4) — the regexes cannot see into `"$(…)"` or skip quoted text |
| `test_worktrees_names_the_refused_shell_forms_and_the_alternative` | adapted into the new module's guidance check (D16) |
| ship-issue docs-only check, CI-MERGE, SYNC; ship-release CHANGELOG, local merge, ahead check, local ahead/behind, "don't" sentence, tag fetch, release notes, railway | recovered (rewording noted in the table above) |
| ship-release Phase 0 `PREV` "capture its status" wording | adapted (D10) |
| ship-release 4.5c "first line is `PREV_TAG`" and its `test_ship_release_contracts.py` change | adapted: `for-each-ref --count=1` keeps an exact-equality assertion (D12) |
| ship-issue and ship-release PR-body `--body-file` rewrites | ship-release recovered; ship-issue reversed to the guard's literal form (D11) |
| `env -u GITHUB_TOKEN` rewording in four documents (retained D20) | excluded — breaks the lifecycle guard (D5) |
| leaf-agent clauses, enrolment guard; `.claude/skills.config.json` guards and `writing-plans` config wording; retained spec/plan/task files | excluded — #153 (landed), #100, superseded by this spec |

Each commit that lands a recovered or adapted hunk carries
`Recovered-From: 3c9709ca470bd473d49b39a611ca6cab258973db` in its trailer block
and lists those hunks in its body; new work carries no such trailer.

## Test seams

One new module, `home/common/agent-skills/tests/test_shell_example_contracts.py`,
registered in `agent-workflow-tests` and `agent-installed-skill-tests`. Its
public boundary is `refused_examples(document_text)` plus the closed form set,
the vocabulary, the guard-derived prefix and the config-derived helper set.
Classes:

1. **Source sweep** — one `subTest` per document across both source trees; any
   finding fails with document, line, form, example and a pointer to the
   `worktrees` section.
2. **Installed sweep** — the same assertion over each view's installed copies;
   skipped when the variable is unset (D13).
3. **Refused-form fixtures** (D18) — per form, one representative unsafe
   example, verbatim from the pre-rewrite text at `a6ac80f`, and its accepted
   replacement from the rewrite table. The host is the live `worktrees/SKILL.md`,
   first asserted to yield no findings. Each unsafe example appended to it
   yields exactly `{form}` on the appended operator's line in every region kind
   it can occupy (shell fence, ambiguous fence, inline span); each replacement
   yields nothing. Negative controls yield nothing: the unsafe text in single
   quotes, a heredoc body, a `#` comment, a `json` fence, and a prose line
   outside a span; `clean | residuals | unknown` in a span with a non-command
   head; the sanctioned prefix before `gh pr merge`, and the bare prefix
   mention. An unterminated `"$(` and an unclosed fence yield `unparseable`;
   `unset GITHUB_TOKEN; gh` yields `chain`, and so does a fence line
   `unset GITHUB_TOKEN &&` followed by a `gh pr merge` line. Lifecycle controls
   (D23): the `ship-issue/SKILL.md` checkpoint call verbatim (three segments, a
   quoted heredoc on the first) yields nothing in every fence kind; that call
   with a non-helper segment, a chain, a redirect, an unquoted delimiter or a
   `$(…)` argument reds in full; a config text with no single-word allow entry
   fails loud. Indentation (D24): a quoted heredoc in a list-item fence
   indented three spaces, terminator at the fence's indentation, yields
   `heredoc`; the terminator indented two further yields `unparseable`.
4. **Vocabulary guard** — every command head in a shell fence of either source
   tree is in the vocabulary, so ambiguous regions and spans recognise every
   command the skills actually run (D14).
5. **Guidance** — the `worktrees` section exists and names, in order, the
   invariant, the four forms, the one-command-per-call alternative, the
   path-passing alternative, the per-invocation directory, the sanctioned
   prefix, the lifecycle helper call and "change the shell form, never the
   isolation"; the probe is the single `git rev-parse --path-format=absolute`
   with the "no line at all" note (D16, D23, D25).

Existing suites that pin rewritten text are adjusted in the same change:
`test_workflow_skill_contracts.py`'s Gate 1 anchor follows the guard-form
`gh pr create`; `test_ship_release_contracts.py` locates the `for-each-ref`
line, still requires `--merged "$MERGE_SHA"`, executes it in its real repo and
asserts output equal to `v0.1.0`. The permission-guard suite is untouched and
stays green.

Prior art: #153's one-function boundary, live-text mutations and installed seam;
the permission guard's fail-closed tokeniser philosophy; the conformance suites'
shared support module.

## Acceptance criteria and verification

| #154 criterion | Satisfied by | Verified by |
|---|---|---|
| 1. Worktree guidance explains the checker contract for redirects, heredoc-to-stdin, pipes and multi-clause chains, naming an accepted alternative | the new `worktrees` section | guidance class |
| 2. Living shared-skill examples no longer teach refused shapes for worktree execution | 19 rewrites; 5 sanctioned-prefix sites; 8 lifecycle helper calls kept (D23) | source sweep green over both trees |
| 3. Fixtures cover each refused shape and one accepted replacement through the production parser/checker boundary | fixture class through `refused_examples` | fixture class green; each unsafe example reds exactly its form |
| 4. Source and installed trees pass the same sweep | one function, two sweep classes | `just agent-workflow-tests` green (installed skipped); `just agent-installed-skill-tests` green with both views run |
| 5. Selective recovery with provenance; unrelated #99 work excluded | recovery table | `Recovered-From` trailer on each recovering commit; retained tip still `3c9709ca`; the branch diff adds no `env -u GITHUB_TOKEN`, no `.claude/skills.config.json` guard, no leaf-agent clause |

`just build` passes (no `.nix` change; the installed recipe builds anyway).
`just agent-model-matrix` stays green: no dispatch marker moves.

## Out of scope

- The harness checker and the lifecycle guard; no guard grammar or permission
  allow-list change (D5, D11, D23).
- Rewriting #171's lifecycle calls (D23). Whether the harness checker accepts
  that shape inside an `EnterWorktree`-pinned session is unverified; #171's
  rule governs those calls and this issue keeps them as written. No follow-up
  issue is warranted yet: one is, once an audit records the checker refusing a
  lifecycle call, and its fix belongs to the helpers' input contract (#171's
  surface), not to this sweep.
- Command substitution as a refused form, and the sites that keep it
  (`BASE_SHA=$(…)`, `EXISTING=$(…)`, the Phase 0 `cd $(git -C …)`) — residual
  against the harness's version-bound nested-expansion rule (D8).
- `ship-release`'s release-PR creation not matching the guard's `gh pr create`
  grammar — true before and after this change; its body carries backticks the
  guard forbids (D11).
- Vocabulary coverage of a command shown only in spans or ambiguous fences (D14).
- Eval fixtures, skill scripts, agent definitions, global guidance, historical
  specs and plans (D1).
- #155 consolidation, #100 config-presence guards, #153 leaf-agent clauses.
- CI changes, `.nix` changes, `CLAUDE.md` edits, ADRs and any `docs/` tree (D17).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The sweep covers every `*.md` under both source skill trees outside `evals/`, including skills that never run in a worktree; scripts, agent definitions, global guidance and historical specs/plans are excluded | AC2 "living shared-skill examples"; audit counts error turns, not sites; retained D4/D15; excluded surfaces measured at zero offenders or are point-in-time records (the-bar Moves keep their history) | Worktree-resident skills only — needs a site allowlist that rots; include evals — graded fixtures, not examples an agent copies |
| D2 | Examples are shell-labeled fence bodies whole, plus lines of unlabeled/`text` fences and inline spans whose command head is in a closed vocabulary; fences nest and the innermost info decides | Phase-0: two PR-body heredocs sit in bare fences the retained extractor skipped; bare fences also hold prompts and diagrams where `\|` and `<` are prose | Only shell-labeled fences — misses both bare-fence heredocs; every bare-fence line as shell — false positives across prompts and diagrams |
| D3 | "Same parser/checker boundary as production" means one public `refused_examples(document_text)` that the source sweep, the installed sweep and every fixture call; its scanner is purpose-built and quote-, substitution- and heredoc-aware | #153's one-function boundary; the-bar Tests that can fail; the harness checker is not in the repo; stdlib `shlex` treats `"$(cat <<'EOF'` as one quoted word; the lifecycle guard's tokeniser lives in a Nix string, drops heredoc bodies and treats `\|` like `;` (the-bar Framework-first, checked) | Reuse the guard tokeniser — not importable without a build, and built to find verbs, not forms; regexes over raw lines (retained) — cannot tell quoted text from live shell |
| D4 | Closed form set `chain`, `pipe`, `redirect`, `heredoc`, plus fail-closed `unparseable`; placeholders stripped with non-space edges; findings carry the operator's line | AC1/AC3 name four shapes; the-bar Fail loud; the harness refuses what it cannot parse; `<[^<>]+>` would erase `< in >` | Four forms only — an example the scanner cannot close passes silently; the retained placeholder regex — hides real redirects |
| D5 | Keep `unset GITHUB_TOKEN && ` as the one sanctioned chain; the sweep derives the literal from the guard's single `UNSET_GITHUB_TOKEN_PREFIX` assignment and fails loud if it is not exactly one; the `worktrees` guidance points at `from-issue/bindings.md` as its prose home | CLAUDE.md: the guard accepts exactly that literal and its adversarial table refuses other spellings; under `env -u GITHUB_TOKEN gh …` the guard's tokeniser reads `GITHUB_TOKEN` as the command word, so `gh pr merge`/`gh pr create` sit in a non-command position and are blocked; the-bar DRY | Retained D20 `env -u GITHUB_TOKEN` — breaks the guarded merge and PR creation in `unsetGithubToken` repos; restate the literal in the test — a second home that can drift from the guard |
| D6 | The guidance states one invariant (a single plain command with literal targets is verifiable; control flow and redirection are refused), names the four forms and the remedies, and encodes no rule table | Retained D5; the harness's own remedy text "Split it into plain, separate commands"; its rules are version-bound (git-specific checks, nested-expansion change) | Mirror the observed rule table — stale at the next harness release and partly git-specific |
| D7 | Every rewrite keeps the example's meaning; 19 examples in 8 documents are rewritten, 5 prefix sites kept | the-bar Root causes; Phase-0 scan re-measured with the prototype classifier at `a6ac80f` | Strip operators mechanically — deletes a `set -e` rationale and turns a prohibition into nonsense |
| D8 | Command substitution is not a refused form; existing `$(…)` sites stay unless their site is rewritten anyway | Not among the audit's measured classes or the issue's four shapes; the harness refuses only "certain" nested expansions, version-bound (YAGNI) | Sweep `$(…)` too — rewrites a dozen sites against an unverified rule |
| D9 | Prose quoting an anti-pattern inside a code span is swept like any example and reworded to name the filter in words; no exemption mechanism | Retained D10; a quoted pipe is still a copyable shape; an exemption list is the allowlist D1 rejects | Exempt anti-pattern quotes — needs a per-site list and re-teaches the shape |
| D10 | `2>/dev/null` and `\|\| true` are replaced by prose that treats a non-zero exit as information (no tag → empty `PREV`); agents run one call at a time, so there is no `set -e` to survive | the-bar Root causes (no muting an error); the checker refuses the redirect and the chain | Keep `\|\| true` under an exemption — keeps a refused chain for a shell mode agents do not run |
| D11 | ship-issue's PR creation (Phase 4, Gate 1) becomes the lifecycle guard's exact `--repo/--base/--head/--title/--body` form with a literal body free of `"`, `$`, backtick and backslash; ship-release's release PR uses `--body-file`; the `worktrees` guidance names no `--body-file` example, so it never points a ship-issue agent at a guard-refused form | CLAUDE.md and `validate_pr_create`: exactly 13 argv, those chars forbidden, `--body-file` refused; shipped PR #166's body has zero backticks; ship-release runs from the default checkout and its body carries backticks, so no form satisfies the guard there | `--body-file` everywhere (retained) — the guard blocks ship-issue's standing-authorized PR creation; the literal form for releases — backticks in release bodies are refused |
| D12 | 4.5c uses `git for-each-ref --count=1 --merged "$MERGE_SHA" --sort=-v:refname … 'refs/tags/v[0-9]*'`, whose single line is `PREV_TAG` | Verified locally: returns `v0.10.0` over `v0.1.0`, excludes an unreachable `v9.9.9`, prints nothing with no match; keeps the executed test an exact-equality check | Retained "first line of `git tag --list`" — the executed test must parse output and the example depends on prose |
| D13 | The installed sweep reads each source-enumerated document's copy, by relative path, in the Claude and Codex views of `AGENT_SKILLS_INSTALLED_HOME`; the tree/view layout and the installed-root skip/fail rules move into one support module both contract suites import; `agent-installed-skill-tests` runs both | #153 D7/D8/D16; AC4 "same contract sweep"; the-bar DRY and Single responsibility (the second consumer arrives now); conformance suites' support-module precedent | Copy the constants into the new module — two homes that must change together; walk the installed views — a dropped document passes silently, and the Codex view's directory links need special traversal |
| D14 | The command vocabulary is a closed constant, and a guard test requires every command head in shell fences of both trees to be in it; a command shown only in spans or ambiguous fences is outside the guard's reach, a named residual | the-bar Fail loud; ambiguous regions and spans are only as good as the vocabulary; no prose parser can tell an unknown command from a word | An open heuristic — silently misses a new command; guard ambiguous fences too — their prompt and diagram lines would demand vocabulary entries for words |
| D15 | Recovery re-applies adapted hunks from `3c9709ca` by hand with a `Recovered-From` trailer and body inventory; the tip is verified unchanged | #153 D12; #154 AC5 | Cherry-pick — imports #100/#153 hunks and D20 |
| D16 | #154's guidance and sweep checks live in the new module, not in `test_workflow_skill_contracts.py` | the-bar Single responsibility; the installed recipe must run only these checks (#153 D9) | Extend the 3,500-line suite as the retained work did |
| D17 | No ADR, context doc, `CLAUDE.md` or `.nix` edit | #153 D13 re-decided: reversible prose held by tests; no ADR home; no `CLAUDE.md` sentence is falsified | Document the recipe in `CLAUDE.md` — growth #155 is chartered to consolidate |
| D18 | Fixtures use the historical offenders verbatim as constants, appended to the live `worktrees/SKILL.md` after a no-findings baseline, and assert the exact form on the appended operator's line; an unclosed fence is `unparseable` at its opener (refines D4) | the-bar Tests that can fail (fixtures shaped like production values); #153 D10/D15 live-host precedent; after the rewrite the offenders no longer exist in any live document | Minimal synthetic strings — pass while real offender shapes slip through; re-mutate each rewritten site back — needs a reverse mapping per site for no extra coverage |
| D19 | An example is one call: every non-blank, non-comment call start in a shell fence, a vocabulary-headed one in an ambiguous fence or span, extended while a quote, substitution, heredoc body, `\` or trailing `&&`/`\|\|`/`\|` leaves it open; a finding's line is that form's first operator in the call; the vocabulary is the closed set the plan fixes (every `~/.agents/bin` helper plus common tools) (refines D2, D4, D14) | Spec: "a newline inside a shell fence separates successive calls"; planning measurement 2026-09-23: the fixed set yields exactly the spec's 24 examples at `a6ac80f` | Whole-fence examples — one finding hides a second offending call in the same fence; a minimal vocabulary — misses a command later copied into a span |
| D20 | The source sweep lands with the last rewrite (plan Task 5); earlier rewrite tasks gate on `refused_examples` over the documents they touch, and no commit carries an expected-failure list | the-bar Production-grade (no half-wired path) and Tests that can fail; #153 plan: every task leaves `agent-workflow-tests` green | Land the sweep first with an allowlist of pending offenders — a shim the-bar forbids; land it red — every intermediate review grades a red suite |
| D21 | The fixture class adds one real-shaped command per remaining operator of the form table, and the "heredoc body" control asserts the opener's single `heredoc` finding with nothing from any body line (refines D18) | Spec form table lists `\|\|`, `;`, `&`, `\|&`, `>>`, `&>`, `>&`, `<`, `<(`, `<<-`, `<<<` that the four offenders never exercise; a heredoc opener is itself refused (D4), so its body cannot yield literally nothing | Offenders only — eleven operators untested; a body-only control — not a shell example the scanner could reach |
| D22 | Parameter (`${…}`) and arithmetic (`$((…))`) expansions are scanned contexts, not opaque skips: their own operator characters are not shell forms, but a `$(…)`/backtick substitution nested inside one is live and its operators count; fixtures pin `${REV:-$(… | …)}` and `$(( $(… | …) + 1 ))` as exactly `pipe` and `$(( 1 << 2 ))`/`${REV:-HEAD}` as clean | Phase-5 Codex plan review 154-B1: an opaque `${` or whole-skipped `$((` hides a live pipe, contradicting this spec's classifier contract; the-bar Tests that can fail | Opaque/whole skips — a refused form passes the sweep inside any expansion; fail closed as `unparseable` on any expansion — reds legitimate `${VAR:-default}` examples |
| D23 | A second sanctioned shape, the lifecycle helper call: one pipeline with no chain, redirect or command substitution, every segment headed by a whole-allowed helper (basenames of `default.nix`'s single-word `"Bash(<word>:*)"` allow entries, derived, empty → fail loud), every heredoc `<<` with a quoted delimiter, drops its `pipe`/`heredoc` findings; anything short of that is classified in full; the `worktrees` guidance names it beside the prefix, forbids generalizing it, and has a refused one reported, never reshaped (refines D5, D7) | #171 D22 (one heredoc-fed command, no request file) and D18 (helpers allowed whole so each segment matches), the `default.nix` allow-list comment, the lifecycle-call rule in `from-issue`, `ship-issue` and `orchestrate-issues`; measured at `a311fda`: 8 calls, 13 findings, none with a chain, redirect or substitution; the-bar DRY and Fail loud | Rewrite them to `--request-file <path>` — reverses #171's no-file rule and reintroduces the compound mktemp/cleanup it removed; a per-site or per-document exemption — the list D9/D20 reject; name the helpers in the test — a second home beside the allow list |
| D24 | A fence body line loses up to its opener's indentation in leading spaces before scanning; delimiters keep D2's stack rule at any indentation; a line indented past its fence keeps the excess, so an over-indented heredoc terminator is `unparseable` (refines D2, D4) | CommonMark fenced-content rule; from-issue's build-delivery fence sits in a list item with terminator `   EOF`, which the committed classifier reports `unparseable`; bash `<<` needs the exact delimiter line and `<<-` strips only tabs; measured: all 10 indented fence delimiters in both trees sit at ≤3 spaces | Strip all leading whitespace — passes a terminator bash would not match; CommonMark's 0–3-space delimiter limit — without list-container tracking it drops a deeper nested fence from the sweep or leaves it open, and no live fence needs it |
| D25 | The isolation probe is `git rev-parse --path-format=absolute --git-dir --git-common-dir --show-superproject-working-tree`; D15's disposition of that hunk becomes adapted | Task-2 review Important-2; verified on git 2.51.2: without the flag a default-checkout subdirectory prints `/…/.git` over `../../.git` (a false linked worktree); with it the default root and subdirectory print identical lines, a linked worktree's root and subdirectory distinct ones, through a symlinked path too; `ship-issue/SKILL.md`'s cleanup already uses `--path-format=absolute --git-dir` | The retained plain form — misreports every subdirectory of the default checkout; compare `--show-toplevel` with the common dir's parent — two calls or a substitution for the same answer |
| D26 | The D23 sanction is fail-closed at its edges: a heredoc counts as quoted only when its delimiter is written in single or double quotes (`<<\EOF` counts as unquoted), every pipe must be a plain `\|` (a `\|&` makes the call classified in full), and D5's bare-literal exemption is realized as "an inline span equal to the literal is not an example", so a fence body that ends on the bare literal is `unparseable` (refines D5, D19, D23) | #171's lifecycle-call rule spells `<<'EOF'` and a plain `\|`; `\|&` also pipes stderr, a redirect in effect; the-bar Fail loud; Task-2 review Important-1 (the bare literal must never end a call) | Mirror bash's quoting for `\EOF` and accept `\|&` — widens a sanction the helpers never use; exempt the bare literal wherever it stands alone — a dangling `&&` at a fence's end passes silently |
| D27 | The sanctioned prefix is stripped only when a command follows it on the same line, so a fence line holding the bare literal — trailing space or not — keeps its `&&` open (`chain`, or `unparseable` at the fence's end); fixtures pin the literal with its trailing space, `<<-'EOF'`, `<<<` and a backtick argument as outside the D23 sanction and a `<<"EOF"` delimiter as inside it (refines D26) | Phase-5 native review 154N-S1: the guard's literal ends in a space, so a line saved with it reduced to empty text and closed the call; 154N-S2: D26's heredoc and substitution edges had no fixture, and `<<<` has no delimiter branch to record it; the-bar Tests that can fail | Rstrip every fence body line — changes what a heredoc body is compared against; leave the edges to Step 9c's prose — an under-recording fix passes every existing test |
