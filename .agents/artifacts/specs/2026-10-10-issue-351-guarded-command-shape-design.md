# Issue #351 — ship-issue states the command shape the lifecycle guard accepts

Issue: https://github.com/fagenorn/nix-config/issues/351. Prior art: the #154 shell-form
contracts (`2026-09-23-issue-154-shell-form-contracts-design.md`), whose living-example
scanner this work extends, and the #124 forge-adapter spelling fixture, whose
one-fixture-two-suites shape it copies.

## Triage

Input: `{"signals":{"contract_change":{"value":"doubt","evidence":"skill-lint gains a new rule (a new failure class of a gate command); the guard grammar itself is not changed"},"concurrency_or_persistence":{"value":"no","evidence":"skill prose, a lint rule and guard unit tests only; no locking or persisted state"},"open_design_questions":{"value":"hit","evidence":"the issue asks for a run-alone shape for remote branch deletion, but the guard refuses every push with a delete flag; where the lint rule matches is also open"},"criteria_shape":{"value":"hit","evidence":"three criteria, but the first is transcript evidence from a future consumer-project run that no deterministic code check verifies"}},"paths":["home/common/agent-skills/skills/ship-issue/SKILL.md","home/common/agent-skills/skills/ship-issue/REVIEW.md","home/common/agent-skills/skills/ship-issue/POST-SELECTION-SYNC.md","home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md","home/common/agent-skills/skills/ship-issue/CI-MERGE.md","python/agent_tools/skill_lint.py","home/common/agent-skills/tests/test_skill_lint.py","tests/test_claude_permission_guard.py"]}`
Verdict: `{"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

The triage input predates the design: per D3 the check does not touch `skill_lint.py`
or its test.

## Problem

A ship agent dresses the guarded commands the way it dresses every other command: a
`2>&1 | tail` on the push, an `env -u GITHUB_TOKEN` wrapper, a `cd <worktree> &&`
before the merge, a `; echo exit=$?` after it, a guarded verb written unquoted into a
notes argument. The `PreToolUse` lifecycle guard refuses each of these, the agent
retries plainer, and every refusal costs one or two turns: 15 refusals over 9 ship
phases in one day (10 pushes, 4 merges, 1 branch deletion). The skill shows the bare
commands but never says they must run alone, and one of its own instructions (the
review fix push, written as a remote-less push) is a form the guard always refuses.

## Solution

Three parts, no guard change:

1. **Skill text.** `ship-issue/SKILL.md`'s existing `## gh hygiene` section becomes the
   one home of the run-alone rule, and every guarded-command site in
   `skills/ship-issue/*.md` spells an accepted literal form and cites that heading.
2. **A fixture of forms.** One JSON fixture lists the skill's literal forms and the
   refused dressed shapes, each with the guard's expected verdict.
3. **Two checks driven by that fixture.** The shell-example contract suite fails when a
   guarded command in the skill family is not a listed form, lacks the citation, or is
   missing from a site that must carry it. The guard suite runs every row through the
   built guard.

## What the guard accepts (verified at base `02d2f378`)

Probed by running the source guard under `python3 -I` with a scratch policy and a
scratch repository whose `origin` is an authorized owner, and read against
`validate_push`, `validate_merge`, `validate_branch_delete` and `guarded_operations`.

| Command | Judged on | Accepted | Refused |
|---|---|---|---|
| push | its own shell segment | `git push -u origin <branch>`, `git push origin <branch>`, each also behind `unset GITHUB_TOKEN && ` | any redirection on the segment (`2>&1`); `env -u GITHUB_TOKEN` wrapper; a remote-less `git push`; every `--delete`, `:branch`, force, tag-list or extra-refspec form |
| merge | the whole command | `gh pr merge <pr-num> --repo <slug> --merge [--subject "<subject>"] --delete-branch`, also behind exactly `unset GITHUB_TOKEN && ` | anything before, after or attached: `cd … &&`, `; echo exit=$?`, a pipe, a redirect, a wrapper |
| local branch delete | the whole command | `git branch -d <branch>` and nothing else | every other character on the command, the `unset GITHUB_TOKEN && ` prefix included |
| a mention | token position | a guarded verb inside one quoted token, a heredoc body or a comment | a guarded verb as unquoted words in an argument position (`… --notes refused git push origin x`) |

Two facts differ from the issue's summary. A push tolerates a leading `cd … &&`, a
trailing `; …` and a pipe with no redirection, because it is judged per segment; the
skill still prescribes the run-alone shape for it (D7). A heredoc body that mentions a
guarded verb passes today; the mention the guard refuses is the unquoted one (D8).

## Decisions

### The rule and its home

`## gh hygiene` in `ship-issue/SKILL.md` states, once, in prose that names the commands
without code spans:

- the push, the merge and a branch delete each run as their own Bash call, spelled
  exactly as the skill shows them: no `cd`, chain, pipe, redirection or wrapper;
- the result is read from that call's own output or from a follow-up call (the phases
  already name the head check after a fix push and the PR view after the merge), never
  through a pipe or an appended `echo`;
- the only prefix is the existing credential prefix, built only from
  `bindings.tracker.credential_env.unset_before_invocation`, and it goes only on a
  forge or `origin` call, so never on the local branch delete;
- text that only mentions a guarded verb (notes, evidence, a commit message) goes in
  one quoted argument.

The heading keeps its name: `worktrees/SKILL.md` already cites it for the sanctioned
prefix. Each site cites the rule with the anchor token `` `## gh hygiene` `` in the
site's own block (D5).

### Guarded-command sites (the thirteen living examples at base)

"Living example" is the #154 scanner's definition: a shell-fence call, a
vocabulary-headed line of an unlabeled fence, or an inline code span. The scanner finds
thirteen whose command is a guarded verb. The flow diagram's phase lines are not
examples and stay as they are.

| Site | At base | After |
|---|---|---|
| SKILL.md Phase 4 push (fence) | `git push -u origin <branch>` | same form; lead-in cites the anchor |
| SKILL.md Phase 7 merge (fence) | the `--subject` merge form | same form on its own line; lead-in cites the anchor |
| SKILL.md Phase 7 remote delete (span) | `git push origin --delete <branch>` | same form; cites the anchor (D2) |
| SKILL.md Phase 8 step 2 (fence) | `git branch -d <branch>` | same form; the step's lead-in cites the anchor |
| REVIEW.md fix step 4 (span) | remote-less `git push` | `git push origin <branch>`; cites the anchor |
| POST-SELECTION-SYNC.md step 4 (span) | `git push origin <branch>` | same form; cites the anchor |
| HUMAN-GATE.md Gate 2 chain (two spans) | remote delete and local delete forms | same forms (pinned by the human-gate contract test); each item cites the anchor |
| HUMAN-GATE.md Gate 1, CI-MERGE.md merge exit code, POST-SELECTION-SYNC.md trigger, SKILL.md launch-guard list (four bare-verb spans) | a guarded verb named in a code span | the command named in prose, no code span |
| SYNC.md integration-branch prohibition (span) | a push form the skill forbids | the prohibition in prose, no code span |

### The fixture

`tests/fixtures/guarded-command-shapes.json`, read by both suites and by nothing at run
time. It carries the three guarded verbs, the anchor token, and rows of two kinds:

- **skill forms**: an id, the `template` exactly as the skill spells it, the
  placeholder values that turn it into a concrete command, the documents that must carry
  it (`sites`), whether it takes the credential prefix, and the expected verdict.
  Rows: first push and later push (accepted, prefix accepted), merge with subject and
  merge without (accepted, prefix accepted; the subject-less row has no site), local
  branch delete (accepted bare, refused prefixed), remote branch delete (refused bare
  and prefixed, reason `expected exactly git push [-u] origin <branch>`).
- **refused shapes**: the dressed forms from the issue, each with the reason fragment
  the guard prints: push with `2>&1 | tail -3` (`forbidden raw command character`);
  push and merge behind `env -u GITHUB_TOKEN` (`not in a command position`); merge
  after `cd <dir> &&` and merge followed by `; echo exit=$?` (`does not match the
  guarded merge grammar`); a guarded verb as unquoted argument words (`not in a
  command position`); local branch delete after `cd <dir> &&` (`forbidden raw command
  character`).

A concrete command is always derived from `template` plus values, never stored beside
it, so the skill's spelling and the tested command cannot drift (D6).

### The skill check

It lives in the shell-example contract suite and reuses its example extractor behind
one new boundary function that takes a document's text, the fixture and the document's
name and returns findings. The credential prefix it strips is the literal that suite
already reads from the guard source. Over every `skills/ship-issue/*.md` (the suite's existing
sweep already skips `evals/`):

- **R1 form.** Every living example that holds a guarded verb as consecutive unquoted
  words, anywhere in it (D15), equals a skill-form `template` after the guard's own
  prefix literal. A bare verb, a remote-less push, a dressed or wrapped form, an
  unquoted mention and a forbidden push all fail.
- **R2 citation.** The block holding that example contains the anchor token. The block
  of a span is its paragraph or list item; the block of a fenced example is the prose
  paragraph or list-item text that introduces the fence.
- **R3 coverage.** Each skill form appears, satisfying R1 and R2, in every document its
  row lists, and `SKILL.md` has exactly one heading line equal to the anchor.

No rule has an exemption. A finding names the document, line, rule and example.

### The guard check

One new table test in `tests/test_claude_permission_guard.py`, next to the adapter
spelling table: for each skill-form row, the derived command and its prefixed variant
(the `unset GITHUB_TOKEN && ` literal that suite's merge tests already use) get the
row's two verdicts; for each refused-shape
row, exit 2 with `lifecycle guard: unsafe <label>:` and the row's reason fragment. It
uses the suite's fake `gh` and a scratch repository with an authorized `origin`.
No guard source changes, so the adversarial table is untouched.

### Instruction budget

The gate leaves this work almost no growth and no way to buy more: raising a ceiling or
editing a gate file needs the `instruction-budget-raise` label, which only the user
applies. Headroom at base, in bytes: `ship-issue/SKILL.md` alone +28;
SKILL + DELIVERY-LOOP + SYNC + REVIEW +27; those plus CONSOLIDATE +26;
CI-MERGE + POST-SELECTION-SYNC + HUMAN-GATE + REMAINDER 0; whole corpus +526.

Estimated additions: the rule about +250 and four citations about +72 in `SKILL.md`;
about +34 in `REVIEW.md`; about +54 across the conditional references. So the change
is byte-neutral by construction (D9):

- every added byte is offset in the same ceiling set, first by the prose renames above
  and by folding the old prefix sentence into the rule, then by wording-only tightening
  of the same files;
- a cut removes no rule, command, key or anchor that a test or another skill reads, and
  the plan names each cut before any text is added;
- `home/common/agent-skills/instruction-load.json` is not edited, except that
  `tighten` may lower a ceiling;
- if `SKILL.md` cannot reach its +28 without removing a rule, the work stops and
  returns to the user, who alone can grant a raise.

### Documentation

`home/common/claude-code/README.md` gains one sentence naming the new fixture beside
the adapter spelling fixture. It is not part of the measured instruction corpus.
`CLAUDE.md` does not change. No ADR or glossary entry is written: the project binds no
context path, and no decision here is hard to reverse.

## Acceptance criteria

- **AC1 [evidence]** Guard refusals of push, merge and branch deletion drop to zero.
  Measured: `grep -c "lifecycle guard: unsafe \(push\|merge\|branch deletion\)"` over
  the subagent transcripts of the next orchestrated run that ships at least 3 issues on
  nodocom, with the merged skill text installed on the orchestrating host; threshold 0,
  baseline 15 across 9 ship phases. Pending at merge (D10).
- **AC2 [code]** `just agent-workflow-tests` fails when a guarded command in
  `skills/ship-issue/*.md` breaks R1, R2 or R3. Falsified if any of these fixture
  documents yields no finding: a push example with no citation in its block; a merge
  example with no citation; a remote-less push; a push carrying `2>&1`; a document
  listed as a site with its form removed; a document named `REVIEW.md` whose only push
  is the base text's remote-less one. Also falsified if the swept tree yields a finding.
- **AC3 [code]** The guard suite, run against the built settings artifact, gives every
  fixture row its verdict: the five accepted skill forms and their accepted prefixed
  variants exit 0; the remote delete, the prefixed local delete and every refused shape
  exit 2 with the stated reason. Falsified by any row whose exit code or reason differs.
- **AC4 [code]** `just agent-instruction-budget` passes on the branch with no ceiling
  raised and no gate file changed. Falsified by any `ceiling:`, `tightness:` or
  `raise:` line.

## Test seams

- **The skill documents as text**, through the new boundary function in the
  shell-example contract suite, the same seam shape as `refused_examples`: fixture
  documents for each failure class, then the source-tree sweep. Prior art: #154.
- **The built guard as a process**, through `run_guard` in the guard suite, driven by
  the fixture. Prior art: `test_every_adapter_spelling_is_an_allowed_row`. It runs only
  after `just build`, with `CLAUDE_SETTINGS_PATH` naming the built settings JSON.
- **The budget gate**, `just agent-instruction-budget`, unchanged.

No other seam is added. `skill_lint` and its tests are not touched.

## Out of scope

- Any change to the guard grammar, including an arm for the remote branch delete, a
  tolerated `2>&1` or a tolerated leading `cd`.
- `ship-release`, `worktrees`, `from-issue` and every skill outside `skills/ship-issue/`
  (D1). `gh pr create` and `gh release create` shapes.
- Producing AC1's evidence, which needs a later consumer-project run.
- Three guard gaps seen while probing, left for separate issues: `git -C <dir> push`
  and `git -C <dir> branch -d` are not adjudicated, and neither is `git branch -D`. The
  skill prescribes none of them, and R1 keeps them out of the skill family.
- Where Phase 8's local delete runs when the shell's directory was the removed
  worktree. The block is unchanged apart from its citation.
- A model-run skill eval for the rule.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The "ship-issue skill family" is exactly `skills/ship-issue/*.md`; `ship-release` and `worktrees` are untouched. | AC2 names that glob; all 15 baseline refusals were ship phases; `ship-release` already tells the agent to spell its merge exactly and has 40 bytes of headroom. | Extending the rule to `ship-release`: no observed refusal there, and it would need its own budget offsets. |
| D2 | The guard adjudicates two deletions: local `git branch -d <branch>` (whole command, no prefix) is accepted, and every delete-flag push is refused. The skill runs the local delete alone and unprefixed, relies on the merge's `--delete-branch` for the remote, and keeps the fallback remote delete as a run-alone instruction that the fixture pins as refused. A refusal there is a denial under the existing denial rule, taken once and never reshaped. | `validate_push` and `validate_branch_delete`; the existing push table refuses `git push origin --delete topic`; DELIVERY-LOOP's denial step; zero delete-push refusals in the baseline. | A guard arm for the remote delete: it widens a fail-closed grammar for a refusal class the baseline never showed. Dropping the fallback: it changes the delivery contract's `delete_remote_branch` stage and removes a command that hook-less hosts can run. |
| D3 | The check lives in the shell-example contract suite, run by `just agent-workflow-tests`, and not in `skill_lint.py` or a skill eval. AC2 is reworded to match. | `instruction_load.GATE_FILES` lists `skill_lint.py`: any diff to it fails the required Instruction Budget check without the user-only label. Standards rule 6 allows shell examples vetted by that suite. | A `skill-lint` rule: needs a raise this run cannot get. A skill eval: model-run and non-deterministic, so it cannot "fail when the rule is missing". |
| D4 | The check has no mention exemption: every guarded-verb living example is a listed form with a citation, and a command that is only named is written in prose. Coverage is declared per form in the fixture. | `skill_lint`'s "no rule has an exemption"; REVIEW.md's remote-less push is a bare-verb span that is in fact an instruction, so a bare-verb exemption would have missed the one site the guard always refuses. | Exempting bare-verb spans as names: smaller diff, but it leaves that hole open. |
| D5 | The rule is stated once under the existing `## gh hygiene` heading, and each site carries only the anchor token in its own block. | The bar's one-home rule and token economy; `worktrees/SKILL.md` cites that heading; reference files already cite `SKILL.md` headings this way; the issue asks for the shape next to each command. | A new section heading: more bytes and a second home for the prefix rule. Restating the rule at each site: about six times the text against 28 bytes of headroom. |
| D6 | One fixture drives both the skill check and the guard table, and concrete commands are derived from the skill's template. | The #124 adapter spelling fixture, which drives two suites the same way; AC3's "the skill's literal forms". | Literals hand-copied into each suite: the skill and the tested command could drift apart unnoticed. |
| D7 | The skill prescribes the run-alone shape for the push too, although the guard judges a push per segment and tolerates a chain around it. The tests pin the skill forms and the refused shapes, and pin no chained push as accepted. | One rule for three commands costs the fewest bytes; the merge and the local delete are whole-command; 9 of 10 push refusals carried a redirection, which run-alone removes. | A per-command rule that allows `cd … &&` before a push: more text, and it leans on a laxness the guard may close. |
| D8 | The fourth refused shape is pinned as a guarded verb in unquoted argument words. The skill says to quote a mention. Heredoc bodies stay accepted and are not pinned as refused. | Probe at base; the existing `test_heredoc_and_quoted_mentions_pass_in_own_repo`; the guard README. | Pinning a heredoc mention as refused: it contradicts the guard's documented behaviour. |
| D9 | The change is byte-neutral per ceiling set with no raise, offsets come only from prose renames, the folded prefix sentence and wording-only tightening, and the work stops if `SKILL.md` cannot fit. | Headroom measured at base; the raise label is the user's alone. | Asking for a raise: outside this run's authority. Shrinking the rule until it fits unaided: it would drop one of the issue's four statements. |
| D10 | AC1 stays pending at merge. The plan's acceptance record carries its row unmeasured, so ship holds the issue open as `needs-verification`; the row is filled from the next qualifying nodocom run, after the merged skills are installed on that host. A refusal of the remote-delete form in that run counts against the threshold and is the issue's "refusal class survives" case, answered by a follow-up guard issue. | ship-issue's hold route for an evidence criterion without a measured row; the issue's own threshold and its last paragraph. | Closing on the code criteria alone: it would report an unmeasured criterion as met. |
| D11 | (plan) The plan's Acceptance map and the acceptance record carry the issue's three criteria, AC1 to AC3, which are this spec's AC1 to AC3. This spec's AC4, the budget gate, is a task gate and a final-verification command, not a record row. | writing-plans' Acceptance map is one row per issue criterion in issue order; the plan review's map check blocks a row with no issue line; the record's `Criterion` is the issue line verbatim. | A fourth map row: it has no issue criterion to copy, so the map check and the record schema would both reject it. |
| D12 | (plan) Check semantics the spec left open. R1 compares the example with its whitespace squeezed and the guard's prefix literal removed. R2's block for a fence call is the last prose block since the previous fence closed, so one lead-in never covers a run of fences, and the anchor is matched in the block's squeezed text. An R3 finding carries line 0. The sweep reads the source tree only. A refused shape is stored as a skill-form id plus the text before and after it (extends D6). | Prototyped at base in a scratch worktree: the base text yields findings at exactly the thirteen sites and the edited text none; the fence's `_OpenFence` already records its opener. Every fixture row was run through the source guard under `python3 -I` and got its verdict. | The nearest earlier prose block whatever lies between: a citation above one fence would vouch for every later fence. An installed-tree sweep: the installed files are the source files, and the refused-form sweep already proves the copy. |
| D13 | (plan) The cut list that pays for D9 is fixed in the plan's Task 2 and was measured at base: `SKILL.md` +18 bytes, `REVIEW.md` +5, `SYNC.md` −8, `POST-SELECTION-SYNC.md` +6, `CI-MERGE.md` −4, `HUMAN-GATE.md` −13, and the gate prints `check: pass`. Two limits this spec did not measure also bind: `SKILL.md`'s body is at 499 of skill-lint L2's 500 reflowed lines (498 after the edit), and `POST-SELECTION-SYNC.md` and `REVIEW.md` are at exactly 100 of L3's 100, so the first joins one wrapped line to pay for its citation. Cuts are an intro line that restates the frontmatter description, a parenthetical that restates Phase 4, rationale clauses and wording. | The gate and `skill_lint.reflowed_lines` run on the prototype; the six skill contract suites pass on it. | Per-file byte neutrality: stricter than any ceiling, and it would force more cuts in `SKILL.md`. Dropping the payload-discipline summary whole: the ship owner does not load `writing-plans`, so the summary is the rule it reads. |
| D14 | (review) R1 lists a prefixed example only when its form's `prefixed` and `bare` exits agree in the fixture, so `unset GITHUB_TOKEN && git branch -d <branch>` is an R1 finding and cannot satisfy R3. | Codex plan review PR-351-01; `validate_branch_delete` refuses the `&` of the prefix as a forbidden raw character. | Stripping the prefix from every example before the comparison: the check would then pass a spelling the guard refuses. |
| D15 | (final review) R1 reads a guarded verb anywhere in a living example as consecutive unquoted words, not only at its start; a verb inside one quoted argument stays a mention. Every fixture `refused_shapes` row is run through the document check. | Codex diff review CR-351-01: wrapped and chained shapes the guard refuses passed the sweep unseen; the issue names exactly those shapes. | Keeping the begins-with rule of the first draft: the check would let a ship-issue document teach a refused wrapper beside the listed form. |
