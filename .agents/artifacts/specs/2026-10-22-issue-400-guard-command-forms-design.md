# Lifecycle guard: verbs behind global options and wrappers — issue 400

Design for https://github.com/fagenorn/nix-config/issues/400, deliverable 1 of
the retro draft spec on branch `worktree-retro-guard` (commit `b0a18c26`,
`.agents/artifacts/specs/2026-10-21-guard-command-forms-design.md`, "retro Dn").
"#351" cites `.agents/artifacts/specs/2026-10-10-issue-351-guarded-command-shape-design.md`;
"issue 377 Dn" cites the guard-policy trust split; a bare "Dn" cites this
spec's ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "The guard's accepted command grammar (scrub prefix, git -C) and recognition rule change; README guard paragraph documents it."}, "concurrency_or_persistence": {"value": "no", "evidence": "Pure command parsing/validation; repo context lookups are read-only and unchanged in kind."}, "open_design_questions": {"value": "no", "evidence": "Issue body and retro spec b0a18c26 settle prefix set, -C rule and recognition rule."}, "criteria_shape": {"value": "hit", "evidence": "Five acceptance criteria (over four)."}}, "paths": ["home/common/claude-code/lifecycle_guard.py", "tests/test_claude_permission_guard.py", "tests/fixtures/guarded-command-shapes.json", "home/common/agent-skills/tests/test_shell_example_contracts.py", "home/common/claude-code/README.md"]}
Verdict: {"hits":["contract_change","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

An orchestrator finishing an authorized feature PR (nodocom, feature branch into
`dev`) was refused on the two invocation forms agents are told to use, and was
waved through, unadjudicated, on a form the guard never recognised:

| Command | Today | Root cause |
|---|---|---|
| `env -u GITHUB_TOKEN git push origin <feature>` | refused: not in a command position | The verb pass treats every wrapper option as a flag, so `GITHUB_TOKEN` (the argument of `-u`) becomes the command word and `git` lands in argument position. |
| `env -u GITHUB_TOKEN gh pr merge <n> --repo <slug> --merge …` | refused: not in a command position | Same. |
| `git -C <worktree> push origin <feature>` | not adjudicated | The verb is matched only as the contiguous tokens `git push`; a global option in between hides it. |

The same gap hides `git -c a=b push …`, `git --git-dir=… push …`,
`/usr/bin/git push …`, `gh --repo a/b pr merge 1`, `gh pr --repo a/b merge 1`,
`env -S "git push origin main"` and `env --split-string="gh pr merge 1"`: each
reaches only the permission classifier. The `worktrees` skill tells agents to
carry a directory as `git -C <path>` because `cd` chains are refused, and the
consumer repository's git guide prescribes `env -u GITHUB_TOKEN gh …`, so both
refusals break sanctioned flows while the third form runs on trust.

## Solution

1. **Recognise** a guarded verb wherever `git` or `gh` would run it: any word
   whose basename is `git` or `gh`, with git global options or gh flags between
   the words, and guarded-verb text in an `env -S` segment. Recognition only
   widens what is adjudicated; it allows nothing by itself.
2. **Find the command position behind wrappers**: the verb pass consumes wrapper
   option arguments as the detaching pass already does, so in
   `env -u NAME git push …` the command word is `git`.
3. **Accept exactly two harmless invocation forms**, a credential-scrub prefix
   and `git -C <dir>`, by stripping their exact spelling to the canonical
   command that today's grammars judge unchanged. Every other wrapper, global
   option, path-qualified program or spelling is refused.
4. **Judge the repository the command targets**: `git -C <dir>` builds the
   repository context from `<dir>`, not from the payload `cwd`.

Demo: a hook payload for `env -u GITHUB_TOKEN git push origin <feature>` exits 0;
one for `git -C <worktree> push origin main` exits 2 refusing the default-branch
push.

## Decisions

### Recognition

**git.** A word whose basename is `git` starts a git invocation that runs to the
end of its simple command (the next operator token or segment end). The words
after it that begin with `-` before the first other word are its global options.
With no global option, or exactly one `-C` followed by its directory word, the
next word is the subcommand, and the invocation is guarded when that is `push`,
or `branch` with `-d` as its next word. With any other global option the walk
does not try to know which options take a value: the invocation is guarded when
`push`, or `branch` followed by `-d`, occurs anywhere among its later words, and
it is always refused (D3). The guarded set does not grow.

**gh.** A word whose basename is `gh` starts a gh invocation. It is guarded when
its first two words are a guarded path (`pr merge`, `pr create`,
`release create`, `release new`), or, when a flag word comes before the path's
second word, when the path's two words occur in that order among its words (D4).
Flags after the path never matter, so `gh pr view 1 --json mergeable` stays
unguarded.

**Where.** Recognition runs at every word, as the contiguous match does today:
an invocation that starts at a command position is adjudicated, and one that
starts anywhere else keeps today's refusal ("not in a command position …; quote
it if you only mean to mention it"), so `xargs git -C x push …` and an unquoted
mention stay refused. The command-position pass consumes wrapper option
arguments from the detaching pass's existing per-wrapper option table
(`env -u NAME`, `sudo -u user`, attached and long forms included); keywords,
assignments and redirections keep their current treatment, so a leading
redirection still leaves the verb outside a command position.

**Text the guard cannot tokenise as a command.** At every site that refuses on
raw text (an unparseable command, an untokenisable segment, an evaluator
segment, and now a segment in which `env` takes `-S`/`--split-string`), a
guarded verb matches when its words occur in order among the text's words, the
first by basename, in either of two readings: words split at whitespace, quotes
and the shell-active characters; and words split the same way after quotes and
backslashes are deleted, since the shell glues quoted or escaped pieces into one
word (D5, D12, D16). A verb also matches, as at base `336d9e05`, when its words
joined by one space are a substring of the text or of the text with its quotes
and backslashes deleted, so a word that is not the verb's own word
(`${CMD:-git push …}`, `git branch -df x`) cannot hide it (D17). The verb pass finds an evaluator at a command position by
basename, as the detaching pass already does, so `/bin/sh -c 'git push …'`
(unadjudicated today) is an evaluator segment. An `env -S` segment is judged on
its whole text, like an evaluator segment (the raise-label mention included),
not only the payload, because env appends the remaining words to the split
payload. Its reason is `command text handed to env -S cannot be validated`; the
evaluator, unparseable and untokenisable reasons are unchanged.

The detaching-word pass and the raise-label pass are unchanged.

### Accepted invocation forms

A recognised invocation at a command position is accepted only as one of:

```
<verb…>
[<scrub>]<verb…>            push, PR creation, merge, release creation
git -C <dir> <git verb…>
[<scrub>]git -C <dir> push …
```

**Scrub prefix** (D1). `<scrub>` is exactly one of these spellings, single
spaces, nothing before it in the text being judged, `N` and `M` distinct
members of the guard's existing credential-name set (`GITHUB_TOKEN`,
`GH_TOKEN`):

- `unset N && ` or `unset N M && ` (today's literal, generalised; either order);
- `env -u N ` or `env -u N -u M `.

Nothing else may sit in the `env` invocation: an assignment, `-i`, `-S`,
`--chdir`, `--`, `--unset=`, an attached `-uN`, a clustered option, a repeated
name, a second `env` or a double space all leave the text unstripped, and the
verb's grammar then refuses it. Branch deletion takes no scrub prefix in either
spelling (D2): it is judged on its exact grammar, as #351 pinned.

**Directory option** (D7). `-C <dir>` is the only accepted git global option, at
most once, directly after `git`, before any verb `git` guards (push in either
arm, branch deletion). `<dir>` is one unquoted word, non-empty, with no
whitespace, no quote and no shell-active character (the release `--notes-file`
character rule, without its absolute-path demand). It composes with the scrub
prefix as `env -u N git -C <dir> push …`; the `unset` spelling needs no
composition rule because it is a separate segment for a push.

**Refusals judged at recognition** (D6). Before any repository lookup, a guarded
invocation is refused when its program word is path-qualified (`git`/`gh` named
by a path), when it carries a git global option other than one `-C`, when `-C`
repeats, or when the `-C` directory's value breaks the spelling rule. The
reason names the problem and then `run git and gh by name, and carry a
directory only as git -C <dir>`. A gh flag between the path words, and a `-C`
directory whose value passes but whose spelling is quoted or escaped, are left
to the verb's grammar, which refuses them with today's grammar message because
the exact strip below does not apply. No refusal lists accepted forms beyond
that one phrase (retro D7 is deliverable 2).

### Canonical command

Stripping is textual and exact, at the start of the judged text: the accepted
scrub prefix, then, at the new start, `git -C <dir> ` to `git `. Text that does
not match an accepted spelling is left whole, so the grammar refuses it;
nothing is normalised looser than the spelling.

| Verb | Judged on | Scrub prefix | `git -C` | Repository context |
|---|---|---|---|---|
| push (branch and tag arms) | its segment, leading whitespace dropped | `env -u` stripped; `unset … &&` is its own segment | stripped | `<dir>`, else `cwd` |
| PR creation | its segment | `env -u` stripped; `unset … &&` is its own segment | n/a | `cwd` |
| merge, release creation | whole command | either spelling stripped from the start | n/a | `cwd` |
| branch deletion | whole command | none | stripped | none |

Each grammar then judges the canonical text exactly as today: push and PR
creation per segment, so other segments may chain as today; merge, release
creation and branch deletion on the whole command, so nothing may chain after
the prefix. The single `UNSET_GITHUB_TOKEN_PREFIX` assignment stays as the
spelling the ship-issue skill check reads; the accepted spellings derive from
the credential-name set and include it (D9).

### Repository context

The repository context (origin slug, `origin/HEAD`, the derived-row lookup and
row check, the tag lookup's working directory) is built from the target
directory: `<dir>` joined to the payload `cwd` (an absolute `<dir>` stands
alone; no path normalisation, so git resolves it as the shell's `git -C`
would), or the payload `cwd` with no `-C`. A relative `<dir>` with no string
`cwd`, a missing directory or one outside a repository yields an unknown
repository and today's "outside standing authorization" refusal. Contexts are
built lazily, one per distinct target directory in an invocation, and all share
the 27-second invocation deadline (D8, issue 377 D12). Branch deletion still
builds none.

### Shape fixture

The #351 fixture changes in two places (D10):

- Each skill form gains an `env_prefixed` verdict for the form behind
  `env -u GITHUB_TOKEN `: accepted for the two push forms and the two merge
  forms, refused for the local branch delete (grammar: `expected exactly git
  branch -d <branch>`) and the remote delete (as bare). The `push.env-wrapper`
  and `merge.env-wrapper` refused shapes are removed: these verdicts are their
  accepted home.
- A new `invocation_shapes` section holds rows `{id, template, label, verdict}`
  with full templates over the fixture's `values` plus a `<repository-root>`
  placeholder the guard suite fills with its fixture repository: accepted
  `git -C <repository-root> push origin <branch>`, the same behind
  `env -u GITHUB_TOKEN ` with `-u`, and `git -C <repository-root> branch -d
  <branch>`; refused (reason fragment `git -C <dir>`) `git -c`, `git
  --git-dir=`, a second `-C`, and path-qualified `git` and `gh`; refused (merge
  grammar) `gh --repo <slug> pr merge …` and `gh pr --repo <slug> merge …`;
  refused (env -S reason) `env -S "git push origin <branch>"` and
  `env --split-string="gh pr merge …"`; refused (evaluator reason)
  `/bin/sh -c 'git push origin <branch>'`. Every refused row uses the feature
  branch, so exit 2 proves recognition rather than a default-branch refusal.

The shell-example suite reads neither new key and keeps its code; its refused
shapes are still all R1 findings of the ship-issue check.

### README

The claude-code README states the rules where they live today: the "wherever a
simple command starts" sentence gains the recognition rule (basenames, git
global options, gh flags, `env -S` text, wrapper option arguments); the
adjudicated-verbs paragraph replaces "the exact literal prefix `unset
GITHUB_TOKEN && `" with the scrub-prefix spellings, the verbs they apply to and
branch deletion's exclusion, adds the `-C` rule with its per-directory context,
and the release-creation sentence cites the same prefix set. No CLAUDE.md
change: it sends guard detail to the README.

## Test seams

One seam, the guard process boundary (hook JSON on stdin, exit status and
stderr out), run as registered against the built settings and base policy with
the fake `gh`, fixture compiled policy and stub row check, the way the #377 and
#385 plans run `tests/test_claude_permission_guard.py` after `just build` (D11).

- **Adversarial table** (`tests/test_claude_permission_guard.py`):
  1. AC1 rows: allowed `env -u GITHUB_TOKEN git push origin <feature>`,
     `unset GH_TOKEN && git push -u origin <feature>`, and
     `env -u GITHUB_TOKEN gh pr merge <n> --repo <slug> --merge --delete-branch`
     onto a protected default branch; refused `env -u PATH git push …`,
     `env FOO=1 git push …`, `env -i git push …`,
     `env -u GITHUB_TOKEN -i git push …`, `env --unset=GITHUB_TOKEN git push …`,
     `sudo -u x git push …` and the merge followed by `; echo x`.
  2. Prefix-grammar rows: `unset GITHUB_TOKEN GH_TOKEN && <merge>` and
     `env -u GITHUB_TOKEN -u GH_TOKEN <merge>` accepted (the first moves out of
     today's near-miss list, per D1); a repeated name, attached `-uGITHUB_TOKEN`,
     `--`, a second `env`, a double space, and either prefix before branch
     deletion refused.
  3. AC2 rows over two fixture repositories, the payload `cwd` in one and `-C`
     naming the other: a push of the target's default branch refused while
     that branch is not the `cwd` repository's default; a push of the `cwd`
     repository's default branch allowed because it is not the target's; a
     target outside standing authorization refused from an authorized `cwd`
     and the reverse allowed; a relative `<dir>` resolved against `cwd`; a
     relative `<dir>` with no `cwd` refused; a tag push whose annotated tag
     exists only in the target allowed.
  4. Recognition rows: the fixture's `invocation_shapes`, run by one table
     test, their single home.
  5. Wrapper-argument rows: `sudo -u root sh -c 'git push origin <feature>'`
     refused as an evaluator segment (passes today).
  Existing rows stay green, wrapper rows included (`env -i …`, `env FOO=bar
  …`, `sudo -u anis …` still exit 2, now by grammar).
- **Shape table** (same suite): every skill form in its bare, `unset`-prefixed
  and `env`-prefixed variants, the remaining refused shapes, and the
  invocation shapes, prior art #351 D6.
- **Shell-example suite** unchanged and green under `just agent-workflow-tests`.
- **Build check**: `just build` runs the guard as registered.

No in-process test imports the guard: it is a standalone file run under
`python3 -I`, and every behaviour here is observable at its exit status.

## Out of scope

- Retro deliverable 2: `--match-head-commit` in the merge grammar, refusals that
  list the accepted forms, and any ship-issue spelling change.
- Redirections, pipes, `cd … &&` and `; echo` suffixes on guarded verbs (#351
  stands); refspecs, `-q` and other push flags; `gh pr create --body-file`
  (#386).
- Removing the stray `GITHUB_TOKEN` export at its source.
- Allow-surface entries for the new forms: `git -C … push` and
  `env -u … git push` stay outside the allow list, so the permission
  classifier still decides them after the guard passes them.
- The ship-issue skill check's own recognition: it still finds a guarded verb
  only as consecutive words and keeps flagging any dressed form in ship-issue
  documents.
- git and gh aliases, configured or inline (`git -c alias.x=push x …`), and gh
  extensions: a cooperating-session residual, as today.
- A pre-existing gap noticed here: a push or PR creation after `cd <dir> &&` is
  still judged against the payload `cwd`, because those verbs tolerate other
  segments. A follow-up issue, not this change.
- The guarded verb set: `git branch -D`, `git branch --delete` and every
  other verb stay unguarded.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Scrub prefix = `unset N[ M] && ` or `env -u N[ -u M] `, N/M distinct members of `GITHUB_TOKEN`/`GH_TOKEN`, exact single-space spelling, stripped only from the start of the judged text; reverses #351's env-wrapper refusal and today's `unset GITHUB_TOKEN GH_TOKEN &&` near-miss refusal | Issue decisions 1–2 (retro D1, D2): the consumer guide's one-shot form; unsetting `HOME`/`GIT_DIR`/`PATH` could change what the command sees; the merge grammar already reads exact raw text | Any `env -u NAME` (verdict/command divergence); argv-level stripping for per-segment verbs (a second, looser normalisation path) |
| D2 | Branch deletion takes `git -C <dir>` (spelling check only) but no scrub prefix | #351: the credential prefix "goes only on a forge or origin call, so never on the local branch delete" (fixture pins it refused); branch deletion needs no repository context; worktrees skill sanctions `git -C` | Prefix on every verb (flips a pinned #351 verdict for no need); refuse `-C` before `branch -d` (recognition would newly refuse a sanctioned form that runs today) |
| D3 | git: no option or one `-C <dir>` → next word is the subcommand; any other global option → guarded when `push` or `branch -d` occurs among later words, always refused | the-bar Defense in depth; git exits on an unknown global option, so over-reading costs no working command | A table of value-taking global options (retro list): an option missing from it hides the verb |
| D4 | gh: guarded when its first words are a guarded path, or when a flag precedes the path's second word and both path words occur in order | Issue "whatever flags sit between them"; cobra takes an unknown flag's value from the next word, so dropping flag words alone misses `gh --repo a/b pr merge` | Drop flag words only (misses flag values); emulate cobra (needs gh's per-command flag table) |
| D5 | Raw-text sites (unparseable, untokenisable, evaluator, `env -S` segment) match a verb's words in order among the text's words, first by basename; an `env -S` segment is judged on its whole text; the verb pass finds an evaluator by basename | env appends the remaining words to the split payload; literal containment misses `sh -c 'git -C x push …'`; grill probe: `/bin/sh -c 'git push origin main'` exits 0 today, while the detaching pass already matches evaluators by basename | Literal containment (misses global options); payload-only check (misses `env -S git push origin main`); exact-name evaluator match (keeps the `/bin/sh` hole) |
| D6 | Path-qualified program, foreign git global option, repeated `-C` and a bad `-C` spelling are refused at recognition, before any lookup, with one reason naming `git -C <dir>`; gh flags between path words fall to the grammar's existing message | Issue directory-option bullet; retro D8 puts accepted-forms messages in deliverable 2 | Per-form messages listing accepted forms (deliverable 2); letting the grammar refuse them all (no hint toward the sanctioned form) |
| D7 | `<dir>`: one unquoted word, no whitespace, quote or shell-active character, relative allowed, joined to payload `cwd` without normalisation; unresolvable → unknown repository | Issue: "resolves `<dir>` against the hook payload's `cwd`"; release `--notes-file` character rule | Absolute-only (contradicts resolving against `cwd`); `normpath` (can differ from git's own `chdir` through symlinks) |
| D8 | One repository context per distinct target directory in an invocation, built lazily, sharing the 27-second deadline | Push is judged per segment, so one command may push from two directories; issue 377 D12 | One context per invocation (judges the wrong repository); refusing multi-directory commands (an unrequested rule) |
| D9 | The single `UNSET_GITHUB_TOKEN_PREFIX` assignment stays as the skill spelling; accepted spellings derive from the credential-name set and include it | #154 D5: the skill check reads exactly that one assignment and fails loud otherwise; the-bar DRY | Replace it with the generated set (breaks the skill check's source read); restate the set in a test |
| D10 | Fixture: skill forms gain an `env_prefixed` verdict (the env-wrapper rows' new home); a new guard-only `invocation_shapes` section with full templates and a `<repository-root>` placeholder | Issue fixture bullet; the skill check composes refused shapes as before+form+after and sees verbs only as consecutive words, so `git -c … push` cannot be a refused shape | Add them to `refused_shapes` (its R1 test fails on rows the skill check cannot see); widen the skill check (ship-issue spelling is out of scope) |
| D11 | Test only at the guard process boundary; AC rows in the adversarial table; recognition rows live once in the fixture and one table test runs them; two fixture repositories for `-C` | CLAUDE.md (adversarial table); #351 D6 (one fixture, two suites); the-bar Tests that can fail | In-process unit tests of recognition (the guard is a standalone `-I` file, not importable); the same rows in both homes |
| D12 | Raw-text sites split words at whitespace, quotes and the guard's shell-active set `UNSAFE_BRANCH_CHARS` (backslash and `$` included), and a word env's option table reads as a split-string option with attached text (`-Sgit`, `--split-string=git`) also yields that text as a word (plan) | D5's purpose; planning probe at `336d9e05`: `env -Sgit push origin main` exits 0, and `eval git\ push …` evades a whitespace split; `wrapper_option` already classifies attached payloads; the-bar Defense in depth, DRY | Split at whitespace, quotes and operator characters only (both forms stay unadjudicated); a new break set (a second home for "shell-active") |
| D13 | Canonical text has one home, `canonical_text`, called from `main`: push and PR creation drop leading whitespace, then the exact scrub prefix and then `git -C <dir> ` are stripped, each only when a non-whitespace character follows; validators strip nothing (plan) | § Canonical command ("nothing is normalised looser than the spelling"; a double space is refused); the-bar DRY (`validate_merge` and `validate_release` each strip the literal today) | A strip in each validator (copies of one rule); PR creation keeping its leading whitespace (`true && env -u N gh pr create …` would never strip while the same push would) |
| D14 | Redirection words between `git`/`gh` and the verb (`git 2>/dev/null push …`) and wrappers named by path (`/usr/bin/env sh -c '…'`) stay unrecognised, as at `336d9e05`; a follow-up issue (plan) | § Recognition keeps redirections' current treatment and matches wrappers as today; the issue's recognition list names neither; planning probe: both exit 0 before and after this change | Fold them in during planning (widens a reviewed recognition rule without a design pass) |
| D15 | Phase-5 review (R1, R2): a git invocation whose global-option run ends at a shell operator before any subcommand (`git -C $(pwd) push …`) is recognised from the segment's remaining words and refused; a `-C` value word is never itself recognised as a program, so a repository directory named `git` is judged once | Codex plan review R1/R2, traced against `tokenize_segment` (operators split runs) and the per-token recognition loop; the-bar fail-closed | Leave both: R1 leaves a push unadjudicated (the gap issue 400 closes), R2 refuses an authorized push for its directory's basename |
| D16 | Task-2 review: raw-text sites read a text twice, quotes and backslashes as word breaks and quotes and backslashes deleted, and refuse when either reading holds a guarded verb's words in order | Task-2 review traced `sh -c "g''it push …"`, `eval g\\it push …` and `env -S "gi\\t push …"` past the single reading; README: everything the tokeniser cannot vouch for is refused; `detaching_word`'s two-readings precedent | One reading at quote breaks: the shell glues quoted pieces into one word, so an evaluator payload runs a verb the guard never saw |
| D17 | Final review: raw-text sites also refuse when a guarded verb's words joined by one space are a substring of the text or of its glued reading; a git run that ends at an operator inside its global options (D15) reads on through the rest of the command, across segment boundaries, in both raw readings, and is refused with the D15 reason when `push` or `branch -d` occurs | final correctness review CR-001, CR-002; base `336d9e05` substring check: `eval "${CMD:-git push origin main}"` and `sh -c "git branch -df x"` exit 0 under the in-order readings alone, and `split_segments` cuts `git -C $(pwd \| cat) push …` at the `\|` inside the substitution | In-order readings only (a regression against base); tracking substitution depth across segments to bound the D15 read (a second model of `$(`, backtick and grouping nesting the tokeniser does not keep) |
| D18 | Ship review: the D15 read-on also runs when a git run carries a global option other than `-C` before the operator, and when a gh run carries a flag or ends before its third word; the gh refusal reads `the gh invocation continues past a shell substitution or grouping` | ship correctness review CR-001: `git -c core.hooksPath=$(printf /dev/null) push origin main`, `git -c k=${X} push …`, `gh pr --repo $(…) merge 1 --merge` and `gh --repo $(…) pr merge …` exit 0 at the final-review head, because `tokenize_segment` ends the run at the substitution inside the option value and neither D15 nor the gh path match reads past it | Read on only when the run ends inside the global options (D15 alone: a non `-C` option's value hides the verb); read on for every truncated run (refuses `gh pr view $(…) --json url` and `git log --format=$(…)`, whose verbs are already certain) |
