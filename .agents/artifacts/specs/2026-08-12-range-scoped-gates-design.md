# Range-scoped verification gates — scope gates to owned files

**Issue:** https://github.com/fagenorn/nix-config/issues/11
**Targets:** `home/common/agent-skills/skills/writing-plans/SKILL.md` (edited),
`home/common/agent-skills/skills/sdd/SKILL.md` (investigated, **not** edited — see the verdict below)

## Problem

A plan author writing a whole-change gate reaches for the obvious command: `git diff --stat
BASE..HEAD`, `git log BASE..HEAD`, then writes down what the answer should be — "exactly three files",
"every commit is a `fix(agents):`". That expectation is authored once, at plan time, against a range
that has not finished growing. Everything the surrounding workflow commits afterwards lands inside it.

Issue #1 hit this twice on one branch:

1. **Mid-run.** Task 4's Step 2 diffstat returned four files, the fourth being the plan file itself,
   and Step 5 found `73e955b` — the from-issue Phase-5 provenance amendment (`docs(plans):`), a commit
   the flow *mandates*. The implementer returned BLOCKED and the plan had to be amended mid-execution.
   Recorded as the plan's decision "Task-4 gate staleness: the Phase-5 provenance commit sits inside
   the verification range".
2. **At ship time.** ship-issue's Phase-1 sync merge with `main` pulled issues #2, #3 and #6's merged
   commits and files into `BASE..HEAD`. The same gates read another issue's shipped work as scope
   creep and said in so many words that it "must be reverted". Recorded as correctness finding C-3 /
   decision D5, fixed in PR #8 commit `48aeb16` by adding a pathspec to Step 2 and
   `--no-merges … ^origin/main` to Step 5.

D5's own framing is the general statement: *"a literal range expectation outliving the range it was
written against"*, and *"a verification gate that reports false failures is worse than no gate: the
next reader either reverts `main`'s files or learns to ignore the gate."*

Nothing in `writing-plans` warns about this. It tells the author every task needs a verification line
that could fail; it says nothing about what that line is allowed to range over. The failure is
non-obvious (the gate is *correct* when written and stays correct right up until the flow's own
machinery runs), general (it recurs on every branch a from-issue-style flow ships), and it costs a
BLOCKED task plus a ship-time review round each time.

## Solution

Two edits, both instruction text, both in `writing-plans/SKILL.md`, +986 bytes total:

1. **A new rule paragraph** appended to the falsifiability paragraph that closes `## Task structure` —
   the place where the file already defines what a verification line must do. It states the
   prohibition (no raw commit-range expectations), gives the two substitutes (pathspec'd diffs,
   direct content assertions), names the three expected residents of any range (the plan and spec
   files, the caller's `docs(plans):`/`docs(specs):` artifact commits, the ship-time sync merge), and
   gives the filtered command for the one case where commit shape genuinely is what is under test.
2. **Self-review item 4** is relabelled `Falsifiability and gate scope` and gains the matching check,
   so the rule is caught at the file's own review pass rather than only stated. (Decision G2 settled the
   qualified label; this summary was corrected to match it at ship-time review. The superseded decision
   entry that first proposed the bare `Falsifiability and scope` is left as logged — the decisions log
   is append-only, this Solution summary is not part of it.)

`sdd/SKILL.md` is **not** edited. The verdict and its reasoning are below.

## Requirements

- **R1** — `writing-plans` forbids raw commit-range expectations in verification gates, in imperative
  voice, as a rule and not a suggestion.
- **R2** — It names the substitutes concretely enough to act on: a pathspec'd diff, or an assertion
  against file content.
- **R3** — It names, as expected residents of any commit range, all three things that broke issue #1's
  gates: the plan/spec files themselves, the caller's `docs(plans):`/`docs(specs):` artifact commits,
  and the ship-time sync merge with the integration branch.
- **R4** — It gives the escape hatch for genuine commit-shape checks — a branch-scoped `git log`
  filter — including the non-obvious `--no-merges` half.
- **R5** — The rule is reachable from the file's Self-review checklist.
- **R6** — Both edits preserve the file's register (dense, imperative, rationale-bearing) and its
  layout conventions: body paragraphs as one unwrapped line, em dash U+2014, straight ASCII quotes.
- **R7** — Total addition ≤ 1,000 bytes.
- **R8** — A recorded verdict on whether the lesson binds in `sdd/SKILL.md`, either way.
- **R9** — No edit to any file other than `writing-plans/SKILL.md`.

## Does the lesson bind in `sdd/SKILL.md`? — verdict: **no**

**No edit to `sdd/SKILL.md`.** The lesson is about *authored* range expectations. sdd authors none;
every range it uses is computed from live refs at the moment it is needed, and the reviewers it
dispatches grade what is actually in the range rather than checking it against a number written
earlier. Four findings, each verified against the file and its scripts:

1. **Per-task ranges are recorded, not predicted.** The task loop's step 1 says "Record BASE (`git
   rev-parse HEAD`) first" — captured immediately before the dispatch. Every commit the caller made
   earlier, provenance amendments included, is an *ancestor* of BASE and therefore cannot be a
   resident of the range. Issue #1's mid-run failure came from the plan text deriving its own base by
   `git log … | grep -m1 '<subject>'`, which reaches back past those commits; sdd's recorded BASE
   cannot.
2. **The final-review range is a merge-base, which self-corrects across a sync merge.** `MERGE_BASE =
   git merge-base <integration-branch> HEAD`. Merging the integration branch into the feature branch
   advances that merge-base to the merged tip, so the commits the merge brought in fall out of the
   range by construction. This is precisely the condition C-3 broke under, and merge-base is immune to
   it.
3. **`scripts/review-package` asserts nothing.** It takes BASE and HEAD as arguments, validates them
   with `git rev-parse --verify`, and emits `git log --oneline`, `git diff --stat` and `git diff -U10`
   into a file. There is no expectation to go stale. The same holds for the four reviewer prompts:
   `task-reviewer-prompt.md`, `conformance-reviewer-prompt.md`, `correctness-reviewer-prompt.md` and
   `re-review-prompt.md` each tell the reviewer to read the supplied diff (or fetch the range
   themselves) and judge it — none carries a literal "exactly N files" or "every commit matches X".
4. **The symptom already has a route through sdd.** When a plan-authored gate fires falsely, the
   implementer's BLOCKED disposition covers it ("Plan wrong: escalate to the human") as does the fix
   loop's "Plan-mandated findings — anything conflicting with the plan's own text — are the human's
   call". Issue #1 took exactly that route and it worked: the implementer blocked, the controller
   adjudicated, the plan was amended. sdd behaved correctly; the plan was wrong.

Adding gate-design prose to sdd would restate `writing-plans`' rule at the wrong altitude — sdd
executes plans, it does not author gates — and would duplicate a rule in the larger of the two files
(14,748 bytes against 6,203) where a plan author is not reading.

**Residual, deliberately not fixed:** if a caller passes sdd a *local* integration ref that is behind
its remote, `git merge-base` lands at the old fork point and the final-review range does widen to
include commits already merged upstream. That is a stale-*ref* hazard, not the stale-*assertion*
hazard this issue is about; it has never fired here, the fix would be a different one-word change
(`main` → `origin/main`), and it is out of scope. Noted for whoever wants a follow-up issue.

## The edits

Both anchors were dry-run against a copy of the live file before this spec was committed: each BEFORE
string matches **exactly once**, and the two are mutually independent (neither appears inside the
other's replacement), so they can be applied in either order as literal string replacements.

Measured result: `writing-plans/SKILL.md` **6,203 → 7,189 bytes (+986, +15.9%)**. W1 contributes 920
bytes (including its leading blank line), W2 contributes 66.

---

### W1 — `writing-plans/SKILL.md`, section `## Task structure`: scope gates to owned files

Anchor: the falsifiability paragraph that closes `## Task structure`, immediately above the
`## No placeholders` heading. The AFTER re-states the BEFORE paragraph unchanged and appends a second
paragraph after a blank line — apply it as one literal replacement.

**BEFORE**

```markdown
**Every task carries at least one verification line that could fail.** Name the command and the observation that would show the task incomplete, and confirm that observation holds at the commit the implementer starts from. A criterion already true at the base commit is how an implementer "completes" a no-op.
```

**AFTER**

```markdown
**Every task carries at least one verification line that could fail.** Name the command and the observation that would show the task incomplete, and confirm that observation holds at the commit the implementer starts from. A criterion already true at the base commit is how an implementer "completes" a no-op.

**Scope every gate to the files the plan owns.** Give diffs a pathspec (`git diff --stat BASE..HEAD -- <the paths named in the plan's Files: blocks>`) or assert against file content directly; never write a raw commit-range expectation — "exactly three files changed", "every commit in the range is a `feat:`". The range is not the plan's to grade: the plan and spec files land in it, so do the caller's `docs(plans):`/`docs(specs):` artifact commits, and a ship-time sync merge pulls in everything the integration branch advanced by — the gate then reads another issue's shipped work as scope creep and demands reverting it. Where commit shape genuinely is under test, restrict to the branch's own commits (`git log --no-merges BASE..HEAD ^origin/<integration-branch>`; the sync merge is unreachable from the integration branch, so `^` alone leaves it in) and name the artifact and review-fixup subjects as exempt.
```

The new paragraph is one unwrapped line, matching every other body paragraph in the file. It opens
with a bolded imperative like its neighbour, and carries its rationale inline in the same way that
neighbour does ("A criterion already true at the base commit is how an implementer 'completes' a
no-op"). "Gate" is the file's own word — the plan-header template already speaks of "verification
gates" among the plan author's calls, and `## Task right-sizing` of "a fresh reviewer's gate". The
pathspec placeholder points at the `**Files:**` block that opens the task template directly above it,
so the author reads the owned paths off a structure this same file already requires rather than
inventing a list. The exclusion-ref form is not invented here either: `ship-issue` already runs
`git log <feature> ^origin/<integrationBranch> --oneline` as its foreign-commit check, against this
exact class of problem — other issues' commits riding into a branch's range.

---

### W2 — `writing-plans/SKILL.md`, section `## Self-review`: item 4 covers gate scope

Anchor: Self-review item 4, the last item in the numbered list.

**BEFORE**

```markdown
4. **Falsifiability** — every task has a verification line that can fail.
```

**AFTER**

```markdown
4. **Falsifiability and gate scope** — every task has a verification line that can fail, and no gate asserts over an unscoped commit range.
```

The label changes because the item now checks two distinct properties: a gate can be perfectly
falsifiable and still be scoped over a range the plan does not own. It reads "gate scope" rather than
bare "scope" because the file already has a `## Scope check` section about decomposing a spec into
independent subsystems — an unqualified "scope" in the checklist would point a reader at that. Item 2
sets the precedent for a checklist item pointing back at a rule stated earlier in the file ("search
for the patterns above").

## Verification

There is no test suite for skills and none is added; `just build` is this repo's one verification step
per `CLAUDE.md`. The three checks below are what the plan should gate on.

This change is its own first test case, so **none of these checks may be written as a raw commit-range
expectation** — a plan that teaches path-scoping and then ships an unscoped diffstat gate would be
falsified by its own subject matter, and would break for exactly the reasons W1 describes the moment
this branch takes a sync merge.

1. **Both edits present verbatim.** Assert against the file's content, not against a diff: the two
   AFTER strings above appear in `home/common/agent-skills/skills/writing-plans/SKILL.md` exactly once
   each, and the W2 BEFORE string appears zero times.
2. **Byte size.** `wc -c home/common/agent-skills/skills/writing-plans/SKILL.md` = **7189**. Exact
   equality: under verbatim application there is no legitimate source of variance, and exactness
   catches a dropped blank line that a presence check would miss.
3. **Scope.** Any diffstat carries a pathspec limited to this change's own paths —
   `home/common/agent-skills/skills/writing-plans/SKILL.md` plus this branch's own plan and spec files.
   `sdd/SKILL.md` in particular must show **zero** changed lines, since the verdict above is "no edit".
4. **The build.** `just build` exits 0. `home/common/claude-code/default.nix` copies the whole skills
   tree into the store via `skillsDir = ../agent-skills/skills`, so the run does exercise the edited
   file. A markdown-only change cannot break evaluation, but the issue asks for the run anyway. The
   pre-existing `evaluation warning: 'system' has been renamed to/replaced by
   'stdenv.hostPlatform.system'` is present at the base commit too and is not a regression.

**No test seams** in the `design` skill's sense: an instruction-text change has no public boundary to
test. This section replaces that one, following the precedent of
`.claude/specs/2026-08-10-wayfind-skill-hardening-design.md`.

## Out of scope

- **Any edit to `sdd/SKILL.md`.** The verdict section above is the deliverable for that half of the
  issue, and it is "no edit".
- **The stale-local-integration-ref residual in sdd's merge-base call.** A different hazard, never
  observed here; follow-up issue material at most.
- **The cosmetic minors parked in PR #8** — third-person voice in `grill-with-docs` P5, the
  Destination line-cap, the duplicated ~400 threshold. Consciously deferred there; folding them in
  would launder deferred work through an unrelated issue.
- **Script or tooling changes.** No new check script, no change to `sdd/scripts/*`, no eval asserts.
  The issue scopes this to instruction text.
- **Any edit to `from-issue/SKILL.md` or `ship-issue/SKILL.md`**, the two skills that actually produce
  the range's surprise residents (the Phase-5 provenance amendment and the Phase-1 sync merge). Neither
  authors a gate, so neither is where the rule belongs, and `ship-issue` already models the technique:
  its foreign-commit check at `git log <feature> ^origin/<integrationBranch> --oneline` is the same
  exclusion-ref form W1 prescribes. The repo knew the technique; `writing-plans` simply never told plan
  authors about it. The issue's scope names two files and neither of these is one of them.
- **Retrofitting the rule onto the existing plans** in `.claude/plans/`. Those are historical records
  of shipped work; `2026-08-10-wayfind-skill-hardening.md` already carries the fixed gates and the
  decisions explaining them.
- **Any file outside `home/common/agent-skills/skills/writing-plans/SKILL.md`**, and in particular the
  installed copies under `~/.claude/skills`, which are Nix store symlinks regenerated on rebuild.

## Auto-resolved decisions

### Does the lesson bind in `sdd/SKILL.md`?
- **Question:** The issue names `sdd/SKILL.md` as a conditional second target — "only if the
  investigation supports it". Its review-package and final-review ranges are computed by scripts using
  `merge-base`. Does the range-scoped-gate lesson bind there, and if so, at the final-review framing or
  in the reviewer instructions?
- **Choice:** It does not bind. No edit to `sdd/SKILL.md`. Full reasoning is recorded in the spec's
  verdict section so the plan phase and the PR reviewer inherit it.
- **Grounding:** Every sdd range is computed from live refs, never authored: per-task BASE is recorded
  as `git rev-parse HEAD` at dispatch (task loop step 1), so caller commits are ancestors and cannot be
  residents; the final review's `git merge-base <integration-branch> HEAD` advances past a sync merge by
  construction, which is exactly the C-3 condition; `scripts/review-package` merely validates its
  arguments and emits log/stat/diff; none of the four reviewer prompts carries a literal range
  expectation. sdd also already routes the symptom — BLOCKED's "Plan wrong: escalate to the human" and
  the fix loop's "Plan-mandated findings … are the human's call" — which is the route issue #1 actually
  took, successfully.
- **Alternative considered:** A short note in sdd's `## Final review — two axes` warning that the range
  may contain integration-branch commits. Rejected: after a sync merge the merge-base makes that
  false, so the note would teach a reviewer to discount commits that are not there; and it duplicates
  writing-plans' rule in the file whose readers are not authoring gates.

### Anchor and form of the writing-plans addition
- **Question:** Where does the rule land — extend the falsifiability paragraph, open a new `## Gate
  scope` section, or state it only as a Self-review item?
- **Choice:** A new sibling paragraph appended directly after the falsifiability paragraph at the end
  of `## Task structure`, plus an amended Self-review item. No new heading.
- **Grounding:** The falsifiability paragraph is where the file defines what a verification line must
  do; scope is a qualifier on that same object, and the two must be read together. `writing-plans`
  already carries the vocabulary — the plan-header template lists "verification gates" among the plan
  author's own calls, and `## Task right-sizing` speaks of "a fresh reviewer's gate" — so the rule
  needs no new term. A separate heading would add a sixth `##` to a five-heading, 6.2 KB file and
  separate the rule from the paragraph it qualifies.
- **Alternative considered:** A dedicated `## Gate scope` section, which would be more findable by
  someone grepping for "gate". Rejected as the larger and less reversible change: it restructures the
  file's outline to carry one paragraph, and the Self-review item already provides the second entry
  point.

### Absolute prohibition or stated preference?
- **Question:** Should the rule forbid raw commit-range expectations outright, or recommend
  path-scoping while permitting range assertions with care?
- **Choice:** Outright prohibition ("never write a raw commit-range expectation"), with one named
  escape hatch: when commit *shape* is genuinely the thing under test, use the branch-filtered `git
  log` form.
- **Grounding:** The issue's own fix destination says "never raw commit-range assertions". A softened
  rule would not have prevented either issue-#1 failure, since both gates were written by an author who
  believed the range was under control. The escape hatch is not a loophole — issue #1's Step 5 legitimately
  needed a commit-shape check, and `48aeb16` shows the correct filtered form rather than deleting the
  check.
- **Alternative considered:** "Prefer path-scoped diffs" as guidance. Rejected: `writing-plans` states
  its rules imperatively throughout ("These are plan failures — never write them"), and a preference
  is not falsifiable at the Self-review pass.

### Amend Self-review item 4 or add item 5?
- **Question:** The scope check is a distinct property from falsifiability. Does it become a fifth
  checklist item, or fold into item 4?
- **Choice:** Fold into item 4, relabelled `Falsifiability and scope`.
- **Grounding:** Both properties are checked by looking at the same object — each task's verification
  line — so one pass answers both, and keeping the checklist at four items preserves a list the file's
  own instruction calls "your own checklist, not a dispatch". The label changes because leaving it as
  "Falsifiability" while checking scope too would make the label lie.
- **Alternative considered:** A new item 5, `Gate scope`. Rejected as the larger change for no gain in
  what actually gets checked; it also grows a checklist whose brevity is part of its usability.

### Size budget for the addition
- **Question:** `writing-plans/SKILL.md` is only 6,203 bytes. How much may this rule add before it
  distorts the file?
- **Choice:** A budget of ≤1,000 bytes across both edits. Measured actual: 986 (+15.9%), giving 7,189.
- **Grounding:** Precedent from the same skill family — issue #1 grew `wayfind/SKILL.md` by +54% and
  `grill-with-docs/SKILL.md` by +13% and both were accepted through review, so +15.9% on the smallest
  file is well inside the band. The rule needs its rationale to be actionable: an author who is told
  only "don't do that" cannot tell a legitimately-failing gate from a false one, which is the judgment
  call that cost issue #1 a BLOCKED task.
- **Alternative considered:** A two-sentence, ~250-byte version stating the prohibition and the
  pathspec substitute only. Rejected: it drops the three named residents (R3), which are the part an
  author cannot derive, and drops the `--no-merges` subtlety that a correct commit-shape check needs.

### Concrete filtered command, or abstract advice?
- **Question:** For the commit-shape escape hatch, does the rule print the actual git invocation or
  describe it in prose?
- **Choice:** Print it: `git log --no-merges BASE..HEAD ^origin/<integration-branch>`, with a
  parenthetical explaining why `^origin/…` alone is insufficient.
- **Grounding:** This is the exact form `48aeb16` landed after the C-3 finding, so it is known-correct
  rather than invented here. The `--no-merges` half is the non-obvious part: the sync merge commit is
  not reachable from the integration branch, so the exclusion ref alone leaves it in the range — a
  plan author who reasons it out from prose will get this wrong, and the resulting gate fails on a
  commit no one authored. `writing-plans` prints concrete commands elsewhere (the Task-structure
  template's `pytest …` and `git commit -m …` lines).
- **Alternative considered:** "Restrict the log to the branch's own non-merge commits" without a
  command. Rejected: it is precisely the wording that leaves the `--no-merges` trap open.

### Vocabulary for the flow's own artifact commits
- **Question:** How does the rule refer to the commits the surrounding workflow makes — name
  `from-issue` and its Phase-5 amendment explicitly, or use a workflow-agnostic term?
- **Choice:** "the caller's `docs(plans):`/`docs(specs):` artifact commits" — agnostic term, concrete
  commit subjects.
- **Grounding:** `writing-plans` is invoked standalone as well as inside `from-issue`, and it already
  uses "the caller" for whatever workflow invoked it ("the caller owns standards review and
  execution"; the Auto-resolved-decisions block's "when the caller runs autonomously"). Naming
  `from-issue` would introduce a cross-skill dependency into a file that currently has none, and would
  read as inapplicable to a standalone author. The commit subjects stay concrete because those are what
  a gate actually matches against — `73e955b`, the commit that broke issue #1's gate, was a
  `docs(plans):`.
- **Alternative considered:** Naming from-issue's Phase-5 provenance amendment directly, which is more
  vivid and matches the evidence exactly. Rejected for the coupling, and because the sync-merge half of
  the same sentence is a `ship-issue` behaviour — naming one flow phase but not the other would be
  worse than naming neither.

### This change's own verification must model the rule
- **Question:** How does the plan verify *this* change — the usual whole-change diffstat gate, or
  something narrower?
- **Choice:** Content assertions against the file (both AFTER strings present exactly once, W2's BEFORE
  absent), an exact `wc -c` of 7189, and any diffstat carried with a pathspec limited to this change's
  own paths. Explicitly no raw commit-range expectation, stated as such in the Verification section.
- **Grounding:** The change teaches the rule; a plan that violated it while landing it would be
  falsified by its own subject matter, and would break for exactly the described reason the moment
  ship-issue's sync merge runs — this branch will take one. Issue #1's fixed Task 4 is the working
  template: pathspec'd diffstat plus per-file content checks.
- **Alternative considered:** The `verify-edits.py` harness issue #1 built for fourteen edits across
  three files. Rejected as over-machinery for two string checks in one file; `grep -cF` on the AFTER
  strings is the whole test.

### Commit trailers for this flow's commits
- **Question:** Which trailers do the commits on this branch carry, given repo history uses
  `Co-Authored-By: Claude Fable 5` while individual flows have used the executing model's trailer?
- **Choice:** Every commit in this flow ends with exactly `Co-Authored-By: Claude Fable 5
  <noreply@anthropic.com>` followed by `Claude-Session: https://claude.ai/code/session_012tJnHYhagKXWknC1KnFg8W`.
- **Grounding:** Flow-wide binding from the dispatching workflow, on the rationale "consistency within
  one PR chain". Precedent is issue #1's decision D1, which settled the same question the same way:
  "consistency within one PR chain outweighs continuity with pre-issue history."
- **Alternative considered:** Mixing trailers per phase according to which model executed each one.
  Rejected by the same reasoning D1 gave — it would put two trailers inside one PR and misattribute
  commits.

### G1 (grill): what the pathspec placeholder points at
- **Question:** The rule tells the author to give diffs a pathspec, but a placeholder like `<the paths
  this plan claims>` names no source for that list. Where does the author get it?
- **Choice:** `<the paths named in the plan's Files: blocks>` — a pointer at the `**Files:**` block
  that opens the task template a few lines above the rule.
- **Grounding:** Every task in `writing-plans` already opens with `**Files:** - Create: … - Modify: …
  - Test: …`, so the union of those blocks *is* the set of paths a plan owns; the rule needs no new
  bookkeeping, only a pointer at a structure the file already mandates. This also keeps the rule
  correct for whole-change gates like issue #1's Task 4, which spans every task's files rather than
  one task's.
- **Alternative considered:** Keeping the vaguer "the paths this plan claims". Rejected: it costs the
  same to read and leaves the author deriving a list they would then have to keep in sync by hand —
  the drift that produced the stale expectation in the first place.

### G2 (grill): "scope" in the Self-review label collides with `## Scope check`
- **Question:** Item 4's new label was `Falsifiability and scope`, but the file's `## Scope check`
  section means something else entirely — decomposing a spec into independent subsystems. Does the
  bare word mislead?
- **Choice:** Label it `Falsifiability and gate scope`. The clause keeps the unqualified "gate" since
  the label now supplies the qualifier.
- **Grounding:** `grep -i scope` over the live file returns exactly one hit, `## Scope check` at line
  12, so "scope" is already spoken for in this file's vocabulary and an unqualified second sense would
  be the file's only overloaded term. Five bytes buys the disambiguation.
- **Alternative considered:** Leaving the label as bare `Falsifiability` and letting the clause carry
  the new check. Rejected for the reason the label was changed at all — an item that checks two
  properties under a label naming one of them misdescribes its own checklist.

### G3 (grill): `origin/` prefix and placeholder spelling in the escape-hatch command
- **Question:** `sdd` writes the merge target as `<integration-branch>` and `ship-issue` as
  `<integrationBranch>`; issue #1's landed fix used the literal `^origin/main`. Which form does W1
  print, and does it keep the `origin/` prefix?
- **Choice:** `^origin/<integration-branch>` — sdd's kebab-case placeholder, with the `origin/` prefix
  retained.
- **Grounding:** The prefix is load-bearing, not decoration: `from-issue` bases worktrees on
  `origin/<integration-branch>` precisely because "the local branch may carry other agents' in-flight
  commits", and `ship-issue` notes that under parallel `--auto` runs a diverged local integration
  branch "is the expected steady state" — so a gate filtering on the local ref would exclude the wrong
  set. `ship-issue`'s own foreign-commit check uses the remote ref for the same reason. The kebab
  spelling follows `sdd`, which is the skill `writing-plans`' own header points readers at for
  execution; `ship-issue`'s camelCase form is the config-key spelling, used there inside literal
  commands.
- **Alternative considered:** Bare `^<integration-branch>` matching sdd's line 107 exactly. Rejected:
  it is the form that silently breaks under exactly the parallel-run conditions this repo runs in, and
  it would make the rule's own example a specimen of the bug the rule exists to prevent.
