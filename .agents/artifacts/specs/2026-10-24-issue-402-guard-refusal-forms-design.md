# Lifecycle guard: merge takes --match-head-commit, and every refusal names the accepted form — issue 402

Design for https://github.com/fagenorn/nix-config/issues/402, deliverable 2 of the
retro draft spec on branch `worktree-retro-guard` (commit `b0a18c26`). "Issue 400
Dn" cites `.agents/artifacts/specs/2026-10-22-issue-400-guard-command-forms-design.md`;
"#351" cites `.agents/artifacts/specs/2026-10-10-issue-351-guarded-command-shape-design.md`;
a bare "Dn" cites this spec's ledger. Base: `ca3e4423` (issue 400 merged as PR #409).

## Triage

Input: `{"signals": {"contract_change": {"value": "hit", "evidence": "Changes the guarded merge grammar (adds --match-head-commit) and the refusal-message contract of five guarded operations."}, "concurrency_or_persistence": {"value": "no", "evidence": "Guard is a stateless PreToolUse hook; no locking or persisted state touched."}, "open_design_questions": {"value": "no", "evidence": "Issue body records the four decisions and the exact message shape; remaining choices are implementation detail."}, "criteria_shape": {"value": "hit", "evidence": "Five acceptance criteria (over four)."}}, "paths": ["home/common/claude-code/lifecycle_guard.py", "tests/test_claude_permission_guard.py", "tests/fixtures/guarded-command-shapes.json", "home/common/agent-skills/skills/ship-issue/SKILL.md", "home/common/agent-skills/tests/test_shell_example_contracts.py", "home/common/claude-code/README.md"]}`
Verdict: `{"hits":["contract_change","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

An orchestrator with an authorized feature PR (nodocom #2342, feature branch into
`dev`) ran
`gh pr merge 2342 --repo elevenyellow/nodocom --merge --match-head-commit d4d9acc0505c73305b3e0ced029db43100bc0e8a`
and was told only `unsafe merge: command does not match the guarded merge grammar`.
Two things were wrong and the refusal named neither: `--match-head-commit` is not in
the grammar, and a feature PR must end in `--delete-branch` (without it the command
selects the release arm, reserved for integration into default). The agent could
not read the guard to learn the grammar (the auto-mode classifier treats that as a
bypass), so it handed the merge back to the user and the autonomous run stopped.
Earlier, `git push -q origin HEAD:<branch> 2>&1 | tail -2` was refused as `forbidden
raw command character`: the segment is cut at `&`, ends in `2>`, and `>` is the
forbidden character, with `-q` and the refspec waiting behind it. Nothing said
which character, or what form passes.

Meanwhile `ship-issue` checks that the PR head equals the reviewed `HEAD_SHA` in one
call and merges in another; the forge can make that check atomic, but the guard
refuses the flag that asks it to.

## Solution

1. **Merge grammar.** `gh pr merge <n> --repo <slug> --merge [--subject "<subject>"]
   [--match-head-commit <sha>] [--delete-branch]`, flags in that order, `<sha>`
   exactly 40 lowercase hex characters, optional in both arms; arm rules unchanged.
2. **One form table per operation**, written in a small template notation, compiled
   at the start of each invocation. The validators match the canonical command against it, and the
   refusals print it. Verdicts do not change except for the new merge flag.
3. **Refusals that name the problem and the cure**, shaped
   `lifecycle guard: unsafe <operation>: <specific problem>; accepted: <form>[; or <form>]; optional prefix: unset GITHUB_TOKEN && | env -u GITHUB_TOKEN`,
   printed for every refusal whose cure is a different spelling.
4. **Shipping flow.** `ship-issue`'s merge spells `--match-head-commit <reviewed HEAD_SHA>`.
5. **Docs.** The claude-code README states the merge grammar and the message shape.

Demo: a hook payload for the #2342 command, in a repository whose policy declares
`dev` as its integration branch and whose PR #2342 merges a feature branch into
`dev`, exits 2 with
`unsafe merge: missing --delete-branch: …; accepted: gh pr merge <n> --repo elevenyellow/nodocom --merge [--subject "<subject>"] [--match-head-commit <sha>] --delete-branch; optional prefix: unset GITHUB_TOKEN && | env -u GITHUB_TOKEN`;
that form, filled in, exits 0.

## Decisions

### Merge grammar

The merge's two arms keep their rules (#116 D5, the release arm's integration-into-
default shape and green rollup). Both gain one optional flag, `--match-head-commit
<sha>`, after `--subject` and before `--delete-branch`. `<sha>` is a separate word
of exactly 40 characters from `0-9a-f`; a short, uppercase, attached
(`--match-head-commit=<sha>`) or misplaced value is refused. The guard checks only
the spelling (D10): gh hands the SHA to GitHub, which refuses the merge if the PR
head differs, and checks that atomically with the merge. The PR lookup and the fake
`gh` it runs against are unchanged.

### The form table

One table, keyed by operation, is the single home of every accepted spelling (D1).
Each entry holds the operation's forms, in match and print order, and three
properties:

| Operation | Forms | Whole-text characters | Exact spelling | Scrub prefix |
|---|---|---|---|---|
| push | `git push origin refs/tags/<vX.Y.Z>`; `git push [-u] origin <branch>` | yes | no | yes |
| PR creation | `gh pr create --repo <slug> --base <base> --head <branch> --title "<title>" --body "<body>"` | no | no | yes |
| merge | feature: `gh pr merge <n> --repo <slug> --merge [--subject "<subject>"] [--match-head-commit <sha>] --delete-branch`; release: the same without `--delete-branch`, noted `only <integration> into <default>` | no | yes | yes |
| release creation | `gh release create <vX.Y.Z> --repo <slug> --verify-tag --title "<title>" --notes-file <path>` | no | yes | yes |
| branch deletion | `git branch -d <branch>` | yes | no | no |

**Notation.** Words are separated by single spaces. `<name>` is a slot that takes
one word; `"<name>"` is a quoted (free-text) slot, whose value may begin with `-`;
a slot may sit at the end of a literal word (`refs/tags/<vX.Y.Z>`); `[…]` is an
optional group (no nesting) whose first word is a literal flag. A form may carry a
note, printed after it in parentheses and never matched. The table compiles at the
start of every invocation, inside the guard's unexpected-failure handler, so a
template that does not compile refuses every Bash call (exit 2, never the
non-blocking exit 1 of an import-time crash) and fails `just build`, whose check runs
the guard on a harmless payload (D14).

**Slots** keep today's checks, run by the validators in today's order: `<n>` a
positive decimal PR number; `<slug>` the detected repository slug; `<base>` an
authorized base; `<branch>` the branch-name rules (`branch_name_problem` and `git
check-ref-format`); `<sha>` 40 lowercase hex; `<vX.Y.Z>` the SemVer tag pattern;
`<path>` absolute, no whitespace or shell-active character; `"<subject>"` and
`"<title>"` free text without newlines; `"<body>"` free text with newlines.

**Properties.** *Whole-text characters*: the operation refuses any shell-active
character (`UNSAFE_BRANCH_CHARS`) anywhere in its text, quoted or not, as push and
branch deletion do today. *Exact spelling*: the text must equal the matched form
rendered with its values (single spaces, quoted slots in double quotes), as the
merge and release grammars read raw text today. *Scrub prefix*: the operation takes
the issue 400 D1 prefix; `canonical_text` reads this property instead of naming
branch deletion, and the refusal's prefix clause reads it too.

### Matching

The validators keep their order: ownership first for the four repository-bound
verbs, then the form, then slots, then policy and forge state. The form step is one
shared matcher (D2):

1. For a whole-text-characters operation, the character rule as today.
2. Split the canonical text into words (`shlex`); an unbalanced quote refuses.
3. Try the forms in table order; an optional group is taken when the next word is
   its flag. The first form that consumes every word wins and yields the slot values.
4. For an exact-spelling operation, the rendered form must equal the canonical text.

This replaces `parse_merge_raw`, `parse_release_raw`, the merge and release argv
cross-checks, the push and branch-deletion argv patterns and `PR_CREATE_FLAGS`. The
tag form is tried before the branch form, as the push validator does today, so a
`refs/tags/` word still reaches the tag arm only when the command has no `-u`.

**Invariant.** Every command keeps base `ca3e4423`'s verdict except a merge
carrying `--match-head-commit <sha>` in its place. The adversarial table's exit
statuses stay as they are; only asserted reason substrings change, and only where
the new message names a more specific problem.

### Refusal message

A refusal whose cure is a different spelling reads (D3):

```
lifecycle guard: unsafe <operation>: <specific problem>; accepted: <form>[; or <form>…]; optional prefix: unset GITHUB_TOKEN && | env -u GITHUB_TOKEN
```

- **Which refusals.** Every refusal of one of the five operations that lies in the
  command's text: the recognition refusals (not a command position, evaluator,
  `env -S`, unparseable, untokenisable, invocation form, a run that continues past
  a substitution), each problem the matcher names, the slot problems, and a merge
  arm refusal while an arm remains. A refusal of the repository or the forge state
  names only its problem, as today: authorization and row problems, an unresolvable
  default branch, a default-branch push, head equal to base, a tag that is not an
  existing annotated tag, every PR, protection and rollup lookup or predicate
  failure, timeouts and the invocation deadline. No spelling would pass there, so
  no form is printed.
- **Forms.** The operation's forms that the refusal's known facts still admit, in
  table order, joined by `; or `. Before a lookup that is the whole table, except
  that the merge's release form is listed only where the context declares an
  integration branch and resolved its default branch, so a recognition refusal,
  which has no context, lists the feature form alone. After the PR lookup the merge
  lists only the arm the PR admits (D6).
- **Filling.** With a repository context, `<slug>` becomes the detected slug and,
  once the default branch resolved, `<base>` becomes one alternative per authorized
  base and the release note names the integration and default branches (`only dev
  into main`). Every other slot stays a placeholder (`<n>`, not the command's own
  number). A recognition refusal builds no context and fills nothing (D7).
- **Prefix clause.** Printed exactly as above for the four operations with the
  scrub-prefix property, derived from the one-name spellings of the first
  credential name in `SCRUB_PREFIXES`; omitted for branch deletion (issue 400 D2).
  The README lists the whole prefix set (D8).
- **Not a command position.** The message keeps its quoting advice as the problem
  and gains the clause, which adds the accepted prefixes.
- **Invocation form.** The recognition refusals keep `INVOCATION_FORM_HINT` (`run git
  and gh by name, and carry a directory only as git -C <dir>`) as part of the
  problem, then the clause. `-C` stays out of the forms (D9).

### Problems the guard names

Naming runs only after the form step has refused, so it never changes a verdict.
The first of these that applies is named (D4); steps 1 and 4 read the words before
the program word from the `shlex` split, and if none applies the problem reads
`does not match an accepted form`:

1. **Scrub-prefix attempt.** Words before the program word that begin with `unset`
   or `env`: an unaccepted credential-scrub prefix (a doubled space named as such),
   or for branch deletion `branch deletion takes no credential-scrub prefix`.
2. **Forbidden character**, shown itself (a control character by its escape): the
   first one anywhere in the text for push and branch deletion, the first one
   outside quotes for the other three. For `;`, `&`, `|`, `<`, `>` and a newline the
   problem adds `run the <operation> as its own Bash call and read its output with
   a follow-up call` (D5).
3. **Quoting**: an unbalanced quote, with today's `invalid command quoting` text.
4. **Wrapper**: any other words before the program word (a wrapper, keyword or
   assignment), named as an unaccepted wrapper.
5. **git global option** still in the canonical text, which means `-C` was not
   spelled exactly `git -C <dir> ` with one unquoted directory word.
6. **Unknown flag**: the first word beginning with `-` that is no flag of any of
   the operation's forms, values of quoted slots skipped.
7. **Structure**, at the furthest point any form matched to: a known flag out of
   place, a missing element (`missing --merge`), a wrong word (`expected create,
   found new`), or a word after the end. A required element absent from the rest of
   the command is named missing; otherwise the word found there is out of place.
8. **Exact spelling** (merge, release creation): spell it exactly as the form,
   single spaces and double-quoted free text.

Then the validator names its slot problems in today's order, now with the value:
a refspec (`refspec HEAD:<branch> is not accepted; name the branch alone`), a
force-push `+`, a namespaced ref, a dash-led or invalid branch name, `--repo <x> is
not the current repository <slug>`, a base outside the authorized ones, a free-text
value's forbidden character, a non-SemVer tag, a bad notes path, a short or
uppercase `--match-head-commit` value. Then the merge arms:

- **Missing `--delete-branch`.** The release form matched where no integration
  branch is declared, or the PR lookup shows a PR other than integration into
  default: the problem names `--delete-branch` as missing and keeps today's
  explanation (`it may be omitted only when merging dev into main; this PR merges
  <head> into <base>`); the clause lists the feature form. When the PR's head is
  itself a permanent branch no arm remains: today's text, no clause.
- **Permanent head.** The feature form matched and the head is a permanent branch:
  today's text; the clause lists the release form only when the PR merges the
  integration branch into the default branch.

### Shipping flow

`ship-issue`'s Phase 7 merge becomes
`gh pr merge <pr-num> --repo <resolved-repository> --merge --subject "<rendered subject>" --match-head-commit <reviewed HEAD_SHA> --delete-branch`,
and its flow-diagram line carries the same flag. `<reviewed HEAD_SHA>` is the full
`HEAD_SHA` Phase 6 compared (fixed in Phase 5, re-fixed after a review fix or a
post-selection sync). Two clauses go elsewhere (D11):

- `CI-MERGE.md`, read when Phase 7's merge exits non-zero, routes a merge that
  Phase 7's verify shows unmerged while `headRefOid` is no longer the reviewed
  `HEAD_SHA` to Phase 6's unreviewed-commits stop; the forge refused it because the
  head moved, and it is never retried without the flag.
- `REMAINDER.md` names the current selection's head as a remainder owner's
  `<reviewed HEAD_SHA>`: it reviews nothing, and the ledger merges that selection.

`SKILL.md` changes only the two spellings, each within its current reflowed line
count: the file sits at 498 of skill-lint L2's 500 reflowed lines, which
`just agent-instruction-budget` enforces (a probe adding 600 bytes failed L2; one
adding 280 bytes passed). The new clauses spell no guarded verb in code, which the
#351 check would read as a form.

### Shape fixture

The #351 shape fixture (issue 400 D10) changes (D12):

- `values` gains `<reviewed HEAD_SHA>` (40 lowercase hex), and the `merge.subject`
  and `merge.plain` templates carry `--match-head-commit <reviewed HEAD_SHA>` before
  `--delete-branch`, so the shape table runs the skill's spelling bare, behind
  `unset GITHUB_TOKEN && ` and behind `env -u GITHUB_TOKEN `.
- Reasons follow the named problems: `branch.local` prefixed and env-prefixed (scrub
  prefix on branch deletion), `branch.remote` (unknown flag `--delete`),
  `push.redirect-pipe` (forbidden `>`), `merge.after-cd` and `branch.after-cd`
  (forbidden `&`), `merge.then-echo` (forbidden `;`), and the two gh-flag invocation
  shapes (`--repo` out of place).
- A new guard-only `form_values` map gives one value per guard placeholder (`<n>`,
  `<slug>`, `<base>`, `<branch>`, `<sha>`, `<subject>`, `<title>`, `<body>`,
  `<vX.Y.Z>`, `<path>`). The shell-example suite reads none of it.

### README

The claude-code README's guard paragraphs state the merge grammar with
`[--match-head-commit <sha>]` and its 40-hex rule, the form table as the one home of
accepted spellings, the message shape, which refusals carry it and which print
only their problem, the fill rules and the release note, and the full scrub-prefix
set behind the clause's two spellings. The shape-fixture sentence names
`form_values`. No CLAUDE.md change: it sends guard detail to the README.

## Test seams

Guard behaviour is tested at one seam, the guard process boundary (hook JSON in,
exit status and stderr out), run against the built settings and base policy with the fake `gh`, the fixture
compiled policy and the stub row check (issue 400 D11).

- **Adversarial table** (`tests/test_claude_permission_guard.py`):
  1. AC1: allowed `gh pr merge <n> --repo <slug> --merge --match-head-commit
     <40-hex> --delete-branch`, with `--subject`, behind either scrub prefix, and on
     the release arm; refused a 39- and a 41-character value, an uppercase value,
     `--match-head-commit=<sha>`, the flag before `--subject`, after
     `--delete-branch`, and without a value.
  2. AC2: the #2342 command in a Nodo-row repository with the fake PR merging a
     feature branch into `dev`, asserting `missing --delete-branch` and `accepted:`;
     the segment `git push -q origin HEAD:<branch> 2>` (as the #2268 command splits)
     asserting the forbidden `>` and `accepted:`; one row per named problem class.
  3. A state refusal (an unauthorized repository, a default-branch push) prints no
     `accepted:`.
  4. Existing rows keep their exit statuses; reason substrings change only where
     the message became specific.
- **Forms are true** (same suite, AC3): for each operation the test provokes a
  refusal that prints its whole table in three contexts (the fixture repository with
  no integration branch, a Nodo-row repository, and a recognition refusal with no
  context, run in the fixture repository whose slug `form_values` names), plus the
  AC2 refusals. It parses each `accepted:` clause (alternatives at
  `; or `, the note in trailing parentheses dropped, every subset of `[…]` groups,
  `<…>` filled from `form_values`), and runs every variant bare and behind each
  printed prefix in that context, with PR facts matching the form's arm and an
  annotated tag for the tag form. Each exits 0. It asserts all five operations were
  covered (D13).
- **Shape table** (same suite): the fixture rows; every refused row also asserts
  `; accepted: `.
- **Shell-example suite** (`home/common/agent-skills/tests/test_shell_example_contracts.py`,
  under `just agent-workflow-tests`), code unchanged: R1 holds `ship-issue`'s new
  merge spelling to the fixture template (AC4).
- **Build** (`just build`, AC5): the guard runs as registered, so a template that
  does not compile fails the build.

The guard suite neither imports the guard nor reads its source: it is a standalone
`python3 -I` file, and every behaviour here is observable at its exit status and stderr.

## Out of scope

- Loosening any refusal: redirections, pipes, `cd … &&` chains and `; echo`
  suffixes stay refused (#351); a quoted `-C` directory, `--flag=value` spellings
  and gh flags before the path stay refused.
- A grammar-printing subcommand or any other second surface for the forms.
- Authorization, policy, row-check and forge-state semantics, and the texts of the
  refusals that print no form, including the lookup failures that carry no `unsafe
  <operation>:` label.
- Comparing `--match-head-commit` against the PR's head inside the guard.
- `ship-release`'s release-arm merge spelling and the forge adapter's spellings.
- Codex, which has no hook; the allow surface.
- A pre-existing gap the grill found: PR creation has no whole-text character rule,
  so an unquoted `--body a>b` passes as a redirect. Closing it changes verdicts; a
  follow-up issue.
- Filling slots from the command itself (`<n>`, `<branch>`).
- The ship-issue skill check's own recognition (consecutive words, as today).
- The raise-label and detaching-word refusals, which belong to no operation's table.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | One form table per operation, in a compiled template notation (`<slot>`, `"<slot>"`, `[group]`, a slot glued to a literal, a note), with three properties (whole-text characters, exact spelling, scrub prefix) that the validators, `canonical_text` and the messages all read | Issue decision 3 (forms from the table the validators use; a second surface drifts); the-bar DRY; issue 400 D13 (`canonical_text` single home) | A message-only table with the validators unchanged (drift in the accepting direction, contradicts decision 3); a grammar-printing subcommand (rejected by the issue) |
| D2 | One shared matcher replaces the per-verb parsers: words via `shlex`, forms in table order, first full match wins, exact operations re-render and compare with the text; verdicts unchanged except the new merge flag | Issue scope (explain, not loosen; #351 stands); base `ca3e4423` validators already pair a raw spelling with a `shlex` argv | Keep `parse_merge_raw`/`parse_release_raw` beside the table (two homes of the merge grammar); a looser argv-only merge (accepts single-quoted subjects) |
| D3 | The `accepted:` clause goes on every refusal that lies in the command's text, recognition refusals included; refusals of the repository or forge state keep only their problem | AC3: printed forms must pass in their context, and none passes in an unauthorized repository; issue title and the not-a-command-position bullet; extends issue 400 D6 ("no refusal lists accepted forms", deferred here) | A clause on every refusal (forms that cannot pass there, so AC3 fails); text refusals only from validators (leaves the evaluator and position refusals unexplained) |
| D4 | Problem precedence: scrub-prefix attempt, forbidden character, quoting, wrapper, leftover git option, unknown flag, structure, exact spelling, then slot values in today's order, then arms; ownership stays first for repository-bound verbs | Issue list of problems to name; open question "which message wins" (agent-choose); today's validator order (characters before argv for push and branch deletion) | Structure first (a `2>` push would read "unexpected word" instead of `>`); ownership last (prints forms for a repository where none passes) |
| D5 | A forbidden character is shown itself; `;`, `&`, `\|`, `<`, `>` and newline add "run the <operation> as its own Bash call and read its output with a follow-up call"; push and branch deletion scan the whole text, the others only outside quotes | Issue (`>`, `\|`, `&` advice); `ship-issue` `## gh hygiene` (each guarded verb its own call, output read by a follow-up call); `;`, `<` and newline join or redirect the same way | Only the issue's three (a `; echo exit=$?` suffix gets no cure); scanning quoted text for merge (would name a `$` the subject check names better) |
| D6 | Merge messages list the feature form always and the release form, noted `only <integration> into <default>`, only where the context declares an integration branch and resolved its default branch, so a recognition refusal lists the feature form alone; after the lookup only the arm the PR admits, none when its head is permanent and no arm fits | Open question on the release arm (agent-choose); issue demo prints only the feature form for #2342; arm rules unchanged (#116 D5); AC3 (a printed form must pass where it is printed) | Never list the release arm (a ship-release refusal would point at `--delete-branch`, which deletes `dev`); list both arms everywhere, recognition refusals included (offers a form that cannot pass in a repository without an integration branch) |
| D7 | Placeholders `<n> <slug> <base> <branch> <sha> <subject> <title> <body> <vX.Y.Z> <path>`; a context fills only `<slug>`, `<base>` (one alternative per authorized base) and the release note's branches; recognition refusals fill nothing; `"<subject>"` replaces the demo's `"…"` | Issue: fill slug and default/integration branches "when known"; the demo prints `<n>`; one placeholder syntax for the forms-are-true test | Fill `<n>` and `<branch>` from the command (repeats the agent's mistake back as accepted); build a context for recognition refusals (repository lookups only to word a message) |
| D8 | The clause prints exactly `optional prefix: unset GITHUB_TOKEN && \| env -u GITHUB_TOKEN`, derived from `SCRUB_PREFIXES`'s one-name spellings, omitted for branch deletion; the README lists the full set | Issue message shape; issue 400 D1, D2, D9 (`SCRUB_PREFIXES` and `UNSET_GITHUB_TOKEN_PREFIX` stay); the-bar Token economy | Print all eight spellings (noise); print the clause for branch deletion (a false form, refused by issue 400 D2) |
| D9 | `-C` stays out of the forms: recognition refusals keep `INVOCATION_FORM_HINT` in the problem, and a `-C` the exact strip missed is named as such | Issue 400 D6, D7, D13 (`-C` is stripped before the grammar); a quoted `-C` directory is refused today | `[-C <dir>]` in the git forms (the matcher would then accept `git -C "x" push`, a loosening, or need an element that never matches) |
| D10 | The guard checks only the SHA's spelling (40 lowercase hex, its own word, in place); the forge enforces the match | Issue decision 1 (the check becomes atomic at the forge); gh passes the SHA to GitHub, which refuses a moved head | Add `headRefOid` to the PR lookup and compare (a second, non-atomic copy of the forge's check that changes the lookup argv) |
| D11 | `ship-issue/SKILL.md` changes only its two merge spellings to carry `--match-head-commit <reviewed HEAD_SHA>`; `CI-MERGE.md` routes a merge left unmerged with a moved `headRefOid` to Phase 6's unreviewed-commits stop; `REMAINDER.md` names the current selection's head as a remainder owner's value | Issue shipping-flow bullet; SKILL.md Phase 6 (divergence is the genuinely-blocked stop); CI-MERGE.md is read when the merge exits non-zero; REMAINDER.md skips Phases 0–5; grill probe: SKILL.md sits at 498 of skill-lint L2's 500 reflowed lines | Both clauses in SKILL.md (breaks L2, so `just agent-instruction-budget` fails); spelling only (a head-mismatch refusal has no route, and a remainder owner has no reviewed head to spell) |
| D12 | Fixture: `values` gains `<reviewed HEAD_SHA>`, both merge skill forms carry the flag, refused reasons follow the named problems, and a guard-only `form_values` map holds the guard placeholders | #351 D6 (one fixture, two suites); issue 400 D10 (guard-only sections); AC3 "filled with the fixture's values" | Guard placeholders inside `values` (the same values under two names: `<n>`/`<pr-num>`, `<slug>`/`<resolved-repository>`) |
| D13 | The forms-are-true test reads the forms from refusals in three contexts, expands every `[…]` subset, fills from `form_values`, and runs each variant bare and behind each printed prefix; refused fixture rows assert the clause; state refusals assert its absence | AC3; issue 400 D11 (process boundary only); the-bar Tests that can fail | Read the table from the guard source (couples the test to a literal, outside the process seam); a test-only print flag (the second surface the issue rejects) |
| D14 | The form table compiles at the start of every invocation, inside the unexpected-failure handler: a template that does not compile refuses every Bash call with exit 2 and fails the build check | Grill: a PreToolUse hook blocks only on exit 2, so an import-time crash (exit 1) would let every call through; the build check runs the guard on a harmless payload; the-bar Fail loud, Defense in depth | Compile at import (fail-open at run time if a broken file were installed); compile on the first refusal (the build check's harmless payload never reaches it) |
