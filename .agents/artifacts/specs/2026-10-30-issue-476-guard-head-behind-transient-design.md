# Lifecycle guard: refuse a wrong head SHA and a BEHIND merge, mark row-check timeouts transient, state the accepted verb form — issue 476

Issue: https://github.com/fagenorn/nix-config/issues/476. This was designed autonomously
(`from-issue --auto`), so every call made without the user is a row in the Decision ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "the lifecycle guard's merge adjudication contract gains two new refusals and the row-check refusal text changes"}, "concurrency_or_persistence": {"value": "no", "evidence": "stateless PreToolUse hook; no locking or persisted state touched"}, "open_design_questions": {"value": "doubt", "evidence": "whether the head/BEHIND checks also bind the release arm and how UNKNOWN merge state is treated need a defensible default"}, "criteria_shape": {"value": "hit", "evidence": "five acceptance criteria"}}, "paths": ["home/common/claude-code/lifecycle_guard.py", "tests/test_claude_permission_guard.py", "home/common/agent-guidance/AGENTS.md", "home/common/claude-code/README.md"]}
Verdict: {"hits":["contract_change","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

The Oct 21–30 retro counted four kinds of avoidable lifecycle-guard and forge refusals in
coordinator and one-off flows, where agents write lifecycle commands by hand instead of
copying them from `ship-issue`:

1. **Spelling.** 9 refusals in 4 sessions for a `>` or `&`, a `$` in a body, a missing
   `--repo` or an unparseable command. The always-loaded global guidance never says what
   form the guard accepts. `ship-issue`'s `## gh hygiene` says it, but only to an agent
   that loaded that skill.
2. **Row-check timeouts.** 2 refusals read `…the row check did not confirm its derived
   policy row: timed out; repair: run claude-guard-policy`, and both passed on a plain
   rerun. The named repair is wrong for a timeout: recompiling the policy re-derives every
   project and does nothing about a slow check.
3. **Guessed head SHAs.** 2 merges carried a full SHA guessed from a short one in
   `--match-head-commit`. The guard checks only the SHA's spelling (issue 402 D10), so the
   command reached GitHub, which refused it without saying what the head is.
4. **Behind merges.** 3 merges ran while the branch was behind a base that requires
   up-to-date heads. GitHub refused each with "head branch is not up to date", after the
   guard had already passed it.

## Solution

Three changes, one for each kind of refusal:

- One line in the global guidance states the accepted form of a guarded lifecycle verb.
- A row-check timeout refusal says it is transient and asks for a rerun. No other row-check
  refusal says that.
- The merge validator reads two more facts in its existing PR lookup, `headRefOid` and
  `mergeStateStatus`. It refuses a PR whose merge state is `BEHIND` and names the sync
  recovery. It refuses a `--match-head-commit` value that is not the PR's head and names
  the actual head. Both checks bind both merge arms.

GitHub stays the authority. It still compares `--match-head-commit` atomically with the
merge and still enforces its own up-to-date rule. The guard's new checks are the outer
checks of the-bar's *defense in depth*. They fail fast and say something useful, and
GitHub's checks keep correctness across the window between the guard's check and the merge.

## Decisions

### Merge validator: two PR facts

The PR lookup still runs once with the same argv shape. Only its `--json` field list grows,
to `state,baseRefName,headRefName,headRefOid,mergeStateStatus,url,statusCheckRollup`. The
two new names follow the order of the forge adapter's own field list. The lookup still
scrubs the credential variables, and the jq predicate (open, authorized base, URL prefix)
and the base read-back are unchanged.

The **mergeability check** is one function that both arms call. It takes the parsed PR
facts and the command's `--match-head-commit` value (or none) and returns the first
problem, or none. The order is:

1. **Merge state.** If `mergeStateStatus` is missing, is not a string or is empty, the
   result is `cannot read the PR merge state`. If it is exactly `BEHIND`, the result is
   `the PR is behind its base <base>; repair: sync the branch with <base>, push it and wait
   for its required checks before merging` (per D2, D4, D5). Any other value passes.
2. **Head commit.** This step runs only when the command carries `--match-head-commit`. If
   `headRefOid` is not 40 lowercase hexadecimal characters, the result is `cannot read the PR
   head commit`. If it differs from the command's value, the result is
   `--match-head-commit <given> is not the PR head commit <headRefOid>; merge only a head you
   reviewed` (per D3, D4, D5). Without the flag, `headRefOid` is neither read nor demanded.

Each arm runs this check after its own arm-shape judgment and before its first gate
(per D1):

- **Feature arm:** head-branch read, then the permanent-head refusal, then the mergeability
  check. After that come the integration-base exemption and the protection lookup.
- **Release arm:** the integration-into-default shape check, then the mergeability check,
  then the rollup predicate.

A PR merged onto a declared integration base therefore passes the new checks before the
exemption. The exemption only spares that base the protection demand.

Both new refusals are refusals of the forge state. They go through `refuse("merge", …)`
with no forms, so they name only their problem and print neither the `accepted:` clause nor
the prefix clause (issue 402 D3, per D5).

### Row check: the transient marker

The row check's `why` for a timeout stays `timed out`. Only the closing clause of a timeout
refusal changes, to `; transient: rerun the command` in place of
`; repair: run claude-guard-policy` (per D6). A refusal for any other reason keeps the
repair clause and never carries the marker. That covers a refused or unavailable report,
an unreadable report, a branch mismatch and a row check that could not start. The literal
conflict and `origin/HEAD` refusals keep their own texts. The 27-second invocation-deadline
refusal is not a row-check refusal and stays as it is. The marker applies the same way to
all four repository-bound verbs, because each of them gets the row check's problem from
the one place that builds it.

### Global guidance: the accepted form

The single global guidance source gets one paragraph of its own, placed just before the
`instruction-budget-raise` line, which is the other guard-related rule (per D7):

> Run `git push`, `git branch -d`, `gh pr create`, `gh pr merge` and `gh release create`
> each alone in its own Bash call: no chain, pipe or redirection beyond an
> `unset GITHUB_TOKEN && ` prefix, an explicit `--repo` on each `gh` verb, and no `"`,
> `$`, backtick or backslash in a title, subject or body.

The plan may change the wrapping but not the content. The line must pass
`just agent-instruction-budget` with no ceiling raised. The frame counts toward the corpus
ceiling, which has about 8.5 KB of headroom, and toward no profile total.

### Guard documentation

The Claude Code module README is the one home of guard semantics. It changes in the same
change as the code, so it never describes behaviour the branch lacks:

- `## Adjudicated verbs`: the merge sentence no longer says the guard checks only the
  spelling of `<sha>`. It names the head comparison, the `BEHIND` refusal, the arms they
  bind and their place after the arm-shape judgment, and says GitHub keeps the atomic
  head match.
- The refusal-classes paragraph adds the two new refusals and the two `cannot read`
  refusals to the forge-state class.
- `## Guard policy` row check: a refusal at step 3 for a timeout names the rerun, not
  `claude-guard-policy`.

There is nothing to write in context docs or ADRs, because `knowledge.context` is
unsupported and no ADR directory is bound.

## Test seams

There is one seam, the existing one: the built guard, run as registered through `run_guard`
against the fake `gh` and fake row check in `tests/test_claude_permission_guard.py`
(prior art: issues 116, 377 and 402) (per D8). No new seam is added.

- **Fake `gh`.** It matches the new field list exactly, so the lookup's shape is pinned.
  Its default PR payload gains `headRefOid` set to the fixture SHA that every merge fixture
  already uses (`d4d9acc0505c73305b3e0ced029db43100bc0e8a`), and `mergeStateStatus: CLEAN`.
  Every `FAKE_PR_JSON` override that reaches the mergeability check gains whichever of the
  two fields that check reads. `RELEASE_PR` gains both.
- **AC1: wrong head.** A merge whose `--match-head-commit` differs from the payload's
  `headRefOid` exits 2, and its refusal contains the actual SHA. Rows cover the feature arm
  into the default branch, the feature arm into an integration base with protection
  poisoned, and the release arm. The row asserts the refusal text, not just exit 2: on
  today's guard a field-list mismatch with the fake would also exit 2, and the row has to
  fail today for the right reason.
- **AC2: BEHIND.** Rows on the same three paths refuse with the `behind its base <base>`
  problem and its repair. One more row carries both a `BEHIND` state and a wrong head and is
  refused as `BEHIND` (per D1). Payloads with `UNKNOWN`, `BLOCKED`, `DIRTY` and `UNSTABLE`
  still reach acceptance (per D2). A wrong head on a PR whose head no arm admits gets the
  permanent-head refusal (per D1).
- **Unreadable facts.** A missing, null or numeric `mergeStateStatus` is refused as
  `cannot read the PR merge state`. With the flag, a missing or short `headRefOid` is
  refused as `cannot read the PR head commit`. Without the flag, a missing `headRefOid`
  passes (per D4).
- **State class.** `test_state_refusals_print_no_accepted_forms` gains the wrong-head and
  `BEHIND` refusals.
- **AC3: timeout marker.** The hanging-row-check test asserts that the refusal ends
  `timed out; transient: rerun the command` and does not contain `claude-guard-policy`.
  `assert_unconfirmed`, which every other row-check refusal goes through, asserts that the
  marker is absent.
- **AC4.** `just agent-instruction-budget` passes, and so does CI `Instruction Budget`.
- **AC5.** `just agent-workflow-tests` passes with the whole adversarial table green, and
  so does `just build` (the wrapper's build check loads the guard).

## Out of scope

- Skill changes. `ship-issue`'s `## gh hygiene`, its head-divergence stop and
  POST-SELECTION-SYNC's trigger already describe these recoveries. Teaching a skill to read
  the new refusals is separate work.
- Any other verb, refusal, timeout value or deadline: the 5 s child bound, the 15 s
  row-check bound and the 27 s invocation deadline.
- Refusing merge states other than `BEHIND`, requiring `--match-head-commit`, reading
  branch protection to predict the up-to-date rule, or working out "behind" from commit
  ancestry.
- Marking any row-check refusal other than the timeout as transient, `fetch_failed` lock
  loss included.
- Codex, which has no hook: it gets only the guidance line.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Both arms run the mergeability check, each after its own arm-shape judgment (feature: permanent-head refusal; release: integration-into-default shape) and before the integration-base exemption, the protection lookup and the rollup predicate. Inside it, `BEHIND` is judged before the head comparison | The release form also takes `[--match-head-commit <sha>]`, and a behind release PR is refused by GitHub too. README: the integration base is exempt from the protection demand only. README: an arm refusal is a text refusal, which no state recovery cures. The sync that clears `BEHIND` moves the head, so judging the head first would cost a round trip | Running the check once, right after the PR lookup and before the arm split: one call site, but it would ask for a sync on a PR no arm admits (`main` into `dev`). Running it on the feature arm only: leaves the release arm's wrong SHA to GitHub |
| D2 | Refuse exactly `mergeStateStatus == "BEHIND"`. Every other value (`UNKNOWN`, `BLOCKED`, `DIRTY`, `UNSTABLE`, `CLEAN`, `HAS_HOOKS`, `DRAFT`) passes to GitHub, and the guard reads no protection setting | The issue names only "behind its base". GitHub reports `BEHIND` only where the base requires up-to-date heads (third-party observations: s3ntin3l8/mullion-session-manager#2279, SmartTechBrewery/swarm#1113, kunchenguid/no-mistakes#1402), which matches POST-SELECTION-SYNC's "a head merely behind a base with no such rule merges as it is" and "`UNKNOWN` … is no trigger". `.agents/knowledge/rejections/ungated-agent-merges.md`: the forge gate is the protection | Refusing `UNKNOWN`: would refuse every merge made right after a push, while GitHub is still computing the state. Reading `strict` from protection or computing ancestry: a second copy of GitHub's rule, plus a lookup, and it can refuse merges GitHub admits. `BLOCKED` can hide a behind head, and GitHub still refuses that one |
| D3 | When the command carries `--match-head-commit`, compare it with the PR's `headRefOid` in the existing lookup. Without the flag, read nothing. Reverses issue 402 D10 | Issue 476 change 3 and the retro's 2 guessed SHAs. GitHub keeps the atomic match, so the check-to-use window stays closed (the-bar: defense in depth) | Keeping the spelling-only check (402 D10): the retro failure. Requiring the flag: it changes the accepted form, which 402 made optional and the release flow relies on |
| D4 | A fact the check needs and cannot read fails closed: a missing, non-string or empty `mergeStateStatus` is `cannot read the PR merge state`, and, only when the flag is present, a `headRefOid` that is not 40 lowercase hex is `cannot read the PR head commit` | README: "every uncertainty … blocks". #116 D5's `cannot read the PR head branch`. GitHub's GraphQL schema declares both fields non-null, so neither refusal fires against real gh | Passing an unreadable value through: a check the guard claims to make would be silently skipped. Demanding `headRefOid` without the flag: a refusal about a fact nothing compares |
| D5 | Both new refusals are forge-state refusals with no `accepted:` or prefix clause. The wording is `the PR is behind its base <base>; repair: sync the branch with <base>, push it and wait for its required checks before merging` and `--match-head-commit <given> is not the PR head commit <actual>; merge only a head you reviewed` | Issue 402 D3 (forge-state refusals name only their problem). The existing `; repair:` clause shape. ship-issue: a diverged head carries unreviewed commits and is never resolved by merging | Printing the accepted forms: the `<sha>` template cannot help. "Use `<actual>`": invites merging commits nobody reviewed |
| D6 | Only a row-check timeout ends `; transient: rerun the command`, and that clause replaces `; repair: run claude-guard-policy`. Every other row-check refusal keeps the repair and no marker. The deadline refusal is unchanged | AC3. The retro's two timeouts passed on a plain rerun. `claude-guard-policy` re-derives every project and cannot speed up a slow check | Appending the marker and keeping the repair: two remedies, one of them wrong. Also marking `fetch_failed` lock loss: AC3 bars the marker there, and the guard cannot tell a lost lock from an unreachable origin |
| D7 | The guidance line names all five verbs, the credential-scrub prefix as the only allowed chain, `--repo` on `gh` verbs, and every forbidden free-text character (`"`, `$`, backtick, backslash), as a paragraph of its own before the raise-label line | Issue change 1. The guard's free-text rule forbids all four characters. ship-issue spells the `unset GITHUB_TOKEN && ` prefix, so a bare "no `&&`" would contradict it. The corpus ceiling has room | `$` alone, as the issue summary wrote it: markdown bodies would then hit the backtick refusal. Restating the accepted forms: they are already in the form table, and the refusal prints them |
| D8 | Test only through the existing registered-guard seam. The fake `gh`'s default payload carries the shared fixture SHA as `headRefOid` and `CLEAN`, and the new rows assert refusal text rather than only exit 2 | Prior art: issues 116, 377 and 402. Every merge fixture and the `form_values` `<sha>` share one SHA, so filled forms keep passing. A field-list mismatch also exits 2, so exit 2 alone would let AC1's row pass today | A unit seam that imports the guard: the guard is a standalone file run as registered, and its tests drive the built wrapper. A fake that merges overrides into the default payload: it breaks the rows that test an absent field |
