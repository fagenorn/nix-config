# Range-Scoped Verification Gates Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Land the two instruction-text edits approved in
`.claude/specs/2026-08-12-range-scoped-gates-design.md` into
`home/common/agent-skills/skills/writing-plans/SKILL.md`, so plan authors are told to scope every
verification gate to the files the plan owns, closing issue
[#11](https://github.com/fagenorn/nix-config/issues/11).

**Architecture:** One Markdown skill file is edited as two literal string replacements — a new rule
paragraph appended to the falsifiability paragraph that closes `## Task structure` (W1), and a
relabelled Self-review item 4 that makes the rule reachable from the file's own review pass (W2). No
mechanism change, no new file, no code, no script committed. `sdd/SKILL.md` was investigated and the
spec's recorded verdict is **no edit**; this plan gates that verdict rather than acting on it. Task 1
lands both edits — they are one deliverable, since W2 points at a rule only W1 states — and Task 2 is
a whole-change gate that produces evidence rather than a commit.

**Tech stack:** Markdown (skill instruction text); Nix flake — nix-darwin + home-manager, exercised
via `just build`; Python 3 stdlib (inline heredoc, nothing committed); `git`, `grep`, `wc`, `awk`.

## File structure

| File | Disposition |
|------|-------------|
| `home/common/agent-skills/skills/writing-plans/SKILL.md` | **Modified** — the only file this plan owns. 6,203 → 7,189 bytes, 150 → 152 lines. |
| `home/common/agent-skills/skills/sdd/SKILL.md` | **Not modified.** The spec's verdict section is the deliverable for this half of the issue and it is "no edit". Task 2 Step 2 gates it at zero changed lines. |
| `.claude/plans/2026-08-12-range-scoped-gates.md` | This plan. Committed by the phase that wrote it, and amended later by the caller's review phase. No gate in this plan reads it. |
| `.claude/specs/2026-08-12-range-scoped-gates-design.md` | Already committed at `a98fe6d`. Read-only input; it is the byte-source for both edits. |

Nothing else is created or modified. In particular: no check script, no change under
`home/common/agent-skills/skills/sdd/scripts/`, no eval asserts, no edit to `from-issue/SKILL.md` or
`ship-issue/SKILL.md`, and nothing under `~/.claude/skills` (those are Nix store symlinks regenerated
on rebuild — editing them is both futile and out of scope).

## Global Constraints

Copied from the spec and the issue; every task's requirements implicitly include this section.

- **Instruction text only.** No mechanism change: no new config key, no new file, no new script, no
  change to any skill's behaviour beyond what the two prose blocks say.
- **One file only.** Edits land in `home/common/agent-skills/skills/writing-plans/SKILL.md` and
  nowhere else. Spec requirement **R9**.
- **`sdd/SKILL.md` must show zero changed lines.** The spec's recorded verdict is that the lesson does
  not bind there — every range `sdd` uses is computed from live refs at the moment it is needed, never
  authored — so an edit to that file is a scope violation, not an improvement. Spec requirement **R8**.
- **Apply the spec's AFTER blocks byte-for-byte**, including their line breaks. Do not re-flow,
  re-wrap, re-punctuate or "tidy" them, and do not retype them from memory. The AFTER text is already
  written in the file's register (dense, imperative, rationale-bearing) with the file's layout
  conventions — body paragraphs as one unwrapped line, em dash U+2014, straight ASCII double quotes —
  so copying verbatim is what satisfies spec requirement **R6**. It is not a licence to rewrite.
- **Measured byte size is the acceptance figure:** `writing-plans/SKILL.md` goes **6,203 → 7,189
  bytes** (+986, +15.9%) and **150 → 152 lines**. Both figures were reproduced by dry-run while
  writing this plan, by applying the spec's fences as literal string replacements to a copy of the
  live file. A file landing off either figure means text was padded, dropped or re-flowed. Spec
  requirement **R7** caps the addition at 1,000 bytes; 986 is inside it.
- **Verification gates are scoped to the files this plan owns.** No gate in this plan asserts over a
  raw commit range — no "exactly N files changed in BASE..HEAD", no "every commit in the range matches
  X". This is not stylistic: it is the rule the change itself teaches, and this branch will take a
  ship-time sync merge with `main`, which is precisely the event that falsifies such a gate. Gates are
  content assertions against the file, or diffs carrying both a pathspec and the merge-base form
  `origin/main...HEAD`. Flow-artifact commits (`docs(plans):`, `docs(specs):`), review fixups, and the
  sync merge are **expected residents** of this branch's range; a gate that fires on them is a bug in
  this plan, not a finding.
- **Commits:** one per task where a task commits at all (Task 2 commits nothing), conventional-commits
  style, `fix(agents): …` subject with the `(#11)` reference, ending with exactly these two trailer
  lines in this order:

  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_012tJnHYhagKXWknC1KnFg8W
  ```

## Test seams

**None, by design.** The spec states it outright: "**No test seams** in the `design` skill's sense: an
instruction-text change has no public boundary to test." There is no test suite for skills, none is
added, and `just build` is this repo's one verification step per `CLAUDE.md`.

Implementers therefore verify at these four gates and nowhere else — a task wanting a fifth is a plan
bug, not an implementer's call:

1. **Verbatim presence** — both AFTER blocks appear exactly once in the target file and W2's BEFORE
   block appears zero times, checked by an inline Python heredoc that extracts the blocks *from the
   spec itself*, so nothing is transcribed and the check cannot drift from its source.
2. **Size** — `wc -c` = 7189 and line count = 152. Exact equality on both: under verbatim application
   there is no legitimate source of variance. Both figures are needed — re-wrapping a paragraph
   swaps a space for a newline and is byte-neutral, so the byte count alone cannot catch a re-flow.
3. **Scope** — path-scoped, merge-base-form diffs showing `sdd/SKILL.md` at zero changed lines and
   `writing-plans/SKILL.md` as the only skill file this branch touched.
4. **Build** — `just build`, once, in Task 2.

## Auto-resolved decisions

### Two tasks (edit, then whole-change gate) rather than one or three
- **Question:** The change is two literal string replacements in one file. Does it become one task, one
  task per edit, or an edit task plus a verification task?
- **Choice:** Two tasks. Task 1 lands **both** W1 and W2 and commits; Task 2 is a whole-change gate
  that produces evidence and no commit.
- **Grounding:** `writing-plans` says to split "only where a reviewer could meaningfully reject one
  task while approving its neighbor". W1 and W2 fail that test in both directions: spec requirement
  **R5** is "the rule is reachable from the file's Self-review checklist", so W1 without W2 leaves R5
  unmet, and W2 without W1 leaves a checklist item pointing at a rule the file never states. They are
  one deliverable. Task 2 passes the test: its own gates are the subject matter of this change, so a
  reviewer could reject a badly-scoped gate while accepting the prose edit, and vice versa. It also
  puts the whole-change properties — `sdd` untouched, `just build` green — in front of an agent that
  did not perform the edit. `.claude/plans/2026-08-10-wayfind-skill-hardening.md` Task 4 is the direct
  repo precedent for a final gate task that commits nothing ("This task is a gate; it produces
  evidence, not a commit"), and it passed review.
- **Alternative considered:** A single task folding the build in, on the grounds that two sdd review
  rounds for ~1 KB of Markdown is over-machinery. Rejected because `just build` takes minutes and the
  `sdd`-zero-lines scope gate is a property of the change as a whole, not of the edit; both want one
  home, and a fresh agent is what makes a gate worth having.

### Gates use `origin/main...HEAD` (merge-base form) plus a pathspec
- **Question:** W1's own AFTER text prints `git diff --stat BASE..HEAD -- <paths>` — the two-dot form
  with a pathspec. Should this plan's own diff gates use that same form for consistency with the text
  it is landing?
- **Choice:** No. Every diff gate here uses the three-dot form `git diff --stat origin/main...HEAD --
  <path>`, which diffs from `merge-base(origin/main, HEAD)` to `HEAD`.
- **Grounding:** Three-dot with a pathspec satisfies W1's rule and strengthens it rather than
  contradicting it — W1 requires a pathspec, and this has one. The extra property is the one the spec
  credits `sdd` with in its verdict section: "the final-review range is a merge-base, which
  self-corrects across a sync merge… merging the integration branch into the feature branch advances
  that merge-base to the merged tip, so the commits the merge brought in fall out of the range by
  construction". This branch is known to take that merge at ship time, so the stronger form is free
  insurance. It is also correct in the other direction: if `origin/main` advances *after* the sync
  merge, the merge-base stays at the merged tip and the new upstream commits are still excluded.
  Verified at the base commit — `git merge-base origin/main HEAD` resolves to `165a3b0`, `origin/main`'s
  tip.
- **Alternative considered:** Mirroring W1's two-dot form exactly, deriving `BASE` by `git log … |
  grep -m1 '<subject>'` as `.claude/plans/2026-08-10-wayfind-skill-hardening.md` Task 4 does. Rejected:
  that subject-grep is the exact mechanism the spec's Problem section blames for issue #1's mid-run
  failure ("reaches back past those commits"), and a plan teaching gate scope should demonstrate the
  strongest available form, not the minimum passing one.

### No byte-size gate on `sdd/SKILL.md`
- **Question:** The verdict is "no edit to `sdd/SKILL.md`". The cheapest possible check is `wc -c
  home/common/agent-skills/skills/sdd/SKILL.md` = 14748. Should the plan assert that?
- **Choice:** No. `sdd/SKILL.md` is gated **only** by the path-scoped merge-base diff showing zero
  changed lines.
- **Grounding:** A byte-size assertion on a file this plan does not own is the same failure mode this
  change exists to prevent, one level down. If another branch legitimately edits `sdd/SKILL.md` and
  merges to `main` before this one ships, the sync merge changes that file's size and a `wc -c` gate
  fires on work this branch neither authored nor should grade — D5's "a verification gate that reports
  false failures is worse than no gate". The path-scoped merge-base diff is immune: after the merge,
  `merge-base(origin/main, HEAD)` already contains the other branch's edit, so the diff stays empty and
  correctly reports that *this* branch changed nothing there.
- **Alternative considered:** Asserting the size anyway on the grounds that a concurrent `sdd` edit is
  unlikely. Rejected — "unlikely" is what issue #1's author believed about the range, twice.

### The byte gate on `writing-plans/SKILL.md` stays, because the plan owns that file
- **Question:** By the reasoning above, could an upstream edit to `writing-plans/SKILL.md` merging in
  before ship make the `wc -c` = 7189 gate fire falsely too?
- **Choice:** Keep the gate, and rank the content assertions above it. Task 2 Step 1 reports the two
  presence checks and the two size checks together, so a size mismatch is always read alongside
  evidence of whether the edits themselves are intact.
- **Grounding:** This is the one file the plan owns, and the spec makes 7,189 the acceptance figure
  ("Exact equality: under verbatim application there is no legitimate source of variance, and exactness
  catches a dropped blank line that a presence check would miss"). A gate firing on a change to an
  owned file is a **true** signal that wants a human, which is the opposite of the sdd case — there the
  gate would fire on a file the plan has no claim to. The presence checks are unaffected by upstream
  additions elsewhere in the file, so the pair distinguishes "our edits are wrong" from "the file moved
  underneath us".
- **Alternative considered:** Dropping to a presence-only check for symmetry with the sdd treatment.
  Rejected: it discards spec requirement R7's measurable form and the dropped-blank-line catch the spec
  explicitly calls out, in exchange for insuring against a collision on a file no other open issue
  touches.

### Edits applied with the Edit tool; scripted extraction is the recovery path
- **Question:** W1's AFTER block contains a 918-byte unwrapped single line. Does the implementer apply
  it by hand (Edit tool, copying the fence) or by script (read the spec, string-replace)?
- **Choice:** Edit tool as the primary method, with both fences reproduced verbatim in Task 1. A
  scripted extraction from the spec is given as the recovery path, to be run only if the size gate
  comes back off 7,189.
- **Grounding:** The Edit tool produces a reviewable diff and matches how
  `.claude/plans/2026-08-10-wayfind-skill-hardening.md` landed fourteen edits of this exact kind
  ("Copy the fenced block out of the spec"). Transcription risk is fully covered rather than avoided:
  a single altered byte fails both the presence check and the byte count, so the task cannot pass
  silently with drift, and the recovery path is deterministic when it does fail.
- **Alternative considered:** Making the scripted replacement primary, since it is byte-exact by
  construction. Rejected as the less idiomatic route for a two-string edit — and it would make the
  fences reproduced in Task 1 decorative, when the whole reason to reproduce them is that an
  implementer reads exactly one task without the others.

### Verification runs as an inline Python heredoc, not `grep -cF` alone
- **Question:** The spec says "`grep -cF` on the AFTER strings is the whole test". W1's AFTER block is
  three lines (paragraph, blank, paragraph). Does the gate use `grep`?
- **Choice:** An inline `python3 - <<'PY'` heredoc that extracts both fences from the spec by section
  anchor and asserts exact substring counts plus the two size figures. `grep -cF` on the new
  paragraph's opening clause is kept as the human-readable red/green signal in Task 1 Step 1.
- **Grounding:** `grep -F` cannot match a pattern spanning newlines, so `grep` alone cannot verify W1's
  AFTER block — it would silently check only one line of three and would miss a dropped blank line,
  which is exactly the defect the spec says exactness must catch. Extracting from the spec rather than
  from a string typed into this plan means the check has one source of truth and cannot drift from it.
  Nothing is committed: it is a heredoc in a step, not the `verify-edits.py` harness the spec rejected
  as over-machinery for two string checks.
- **Alternative considered:** `diff` against a pre-built expected file in the scratch directory.
  Rejected: it needs an artifact to exist before the check runs and outside the repo, so it cannot be
  re-run by a reviewer from a clean checkout.

### Line count gated alongside byte count
- **Question:** The spec names one size figure, `wc -c` = 7189. Is that sufficient?
- **Choice:** Gate both `wc -c` = 7189 and line count = 152.
- **Grounding:** Re-wrapping the new paragraph to the file's ~78-column fenced-template width swaps
  spaces for newlines, which is byte-neutral — a re-flowed file can hit 7,189 bytes exactly while
  violating spec requirement **R6**'s "body paragraphs as one unwrapped line". The line count catches
  it for free. Both figures were measured by dry-run against the live file while writing this plan
  (150 → 152 lines; W1 replaces one line with three, W2 replaces one line with one).
- **Alternative considered:** A dedicated register check — grep the file for em dash U+2014 and assert
  no straight-quote regressions. Rejected as redundant: the AFTER text is copied verbatim from the
  spec, so an exact substring match already proves every character of it, including its punctuation.

### The spec's earlier decision entry says `Falsifiability and scope`; the fence says `Falsifiability and gate scope`
- **Question:** The spec's Auto-resolved decision "Amend Self-review item 4 or add item 5?" records the
  choice as "relabelled `Falsifiability and scope`", but the W2 fence and the later grill decision
  "G2" both say `Falsifiability and gate scope`. Which does the plan carry?
- **Choice:** `Falsifiability and gate scope` — the fence. The discrepancy is logged here and neither
  document is edited to hide it.
- **Grounding:** The fence is the single source of truth for text the implementer copies, and this is a
  decisions-log ordering artifact rather than a real conflict: G2 explicitly supersedes the earlier
  entry ("Label it `Falsifiability and gate scope`"), and the spec's `## Solution` section and its
  Verification section both already use the qualified form. The spec's own instruction is that a later
  entry extends the log rather than rewriting it, so the stale phrase in the superseded entry is the
  format working as intended.
- **Alternative considered:** Amending the spec's earlier entry for tidiness. Rejected: the spec is
  committed at `a98fe6d` and its decisions log is deliberately append-only; rewriting history there to
  remove a superseded choice destroys the traceability the format exists for.

### `just build` runs once, in Task 2, and is not the falsifiable gate
- **Question:** `CLAUDE.md` makes `just build` the repo's definition of verified. Does every task run
  it, and does it count as the verification line that could fail?
- **Choice:** It runs exactly once, as Task 2 Step 3. Task 2's falsifiable-at-base gate is Step 1's
  content and size assertions, not the build.
- **Grounding:** `writing-plans` requires a verification line that "could fail… at the commit the
  implementer starts from", and `just build` is green at the base commit — a Markdown-only change
  cannot break Nix evaluation, so a passing build proves nothing about whether the edits landed. Step 1
  is red at base and green after, confirmed by dry-run: at `a98fe6d` the two AFTER blocks appear 0
  times, W2's BEFORE block appears once, and the file is 6,203 bytes / 150 lines. The build is run
  regardless because the issue asks for it and because
  `home/common/claude-code/default.nix` copies the whole skills tree into the store via
  `skillsDir = ../agent-skills/skills`, so the run does exercise the edited file.
- **Alternative considered:** Running `just build` in Task 1 as well, for a tighter feedback loop.
  Rejected: minutes of build per task to re-prove a property that cannot regress from a Markdown edit.

### No "Standards review provenance" section in this plan
- **Question:** `.claude/plans/2026-08-10-wayfind-skill-hardening.md` carries a `## Standards review
  provenance` section. Should this plan reserve one for the review phase that follows?
- **Choice:** No section, no placeholder. The reviewing phase adds it if it has something to record.
- **Grounding:** `writing-plans`' `## No placeholders` lists "TBD" and "fill in details" as plan
  failures, and a reserved-but-empty section is one. The review has not run, so there is nothing
  truthful to write. The amendment is safe to make after this plan is committed precisely because no
  gate in this plan reads the plan file — which is the same property the Global Constraints require of
  every gate here, applied to this plan's own artifact.
- **Alternative considered:** A stub section with the field names and empty values. Rejected by the
  no-placeholders rule, and because an unfilled stub reads as a review that happened and found nothing.

### B1: the plan's four edit fences held unsubstituted template tokens (Phase-5 review)
- **Question:** (fallback reviewer, Blocking, high confidence) The fences in Task 1 Steps 2–3 contained
  the literal strings `@@W1_BEFORE@@`, `@@W1_AFTER@@`, `@@W2_BEFORE@@`, `@@W2_AFTER@@` instead of the
  spec's text — the implementer's Edit calls would hard-fail (`old_string` absent from the target),
  contradicting the plan's own "reproduced verbatim" claims and the `## No placeholders` rule of the
  very file under edit.
- **Choice:** Substituted the spec's fence bodies verbatim into all four fences, then re-verified:
  every spec fence now occurs byte-identically in the plan, and a whole-file placeholder scan is clean
  (the one `TBD` hit is a decision entry quoting the rule).
- **Grounding:** Reviewer evidence at the committed plan's lines 310/317/330/336 (f0b17c2), confirmed
  by grep before fixing. Root cause: the Phase-4 author hit its session limit after writing the
  template pass and before substitution; the file ended structurally complete, so the gap was
  invisible to an outline check.
- **Alternative considered:** Reviewer's call accepted as-is.

### S1: recovery replay was not deterministic over a mistyped W1 (Phase-5 review)
- **Question:** (fallback reviewer, Should-fix, medium confidence) W1's AFTER restates its BEFORE
  unchanged, so replaying `text.replace(before, after)` over a mistyped W1 appends a second, correct
  paragraph while leaving the typo'd one in place — the plan called this path "deterministic".
- **Choice:** The recovery block now restores the pristine file first
  (`git checkout HEAD -- home/common/agent-skills/skills/writing-plans/SKILL.md` — nothing is
  committed until Step 5) before replaying from the spec; the prose states why.
- **Grounding:** Reviewer's failure scenario verified against the fence text: after a mistyped W1,
  `count(after) == 0` and `count(before) == 1` still hold, so the replay silently double-applies.
- **Alternative considered:** Reviewer's call accepted as-is.

### D1: the duplicated Python heredoc is intentional, not DRY debt (Phase-5 review)
- **Question:** (fallback reviewer, Discussion) The ~25-line fence-extraction heredoc appears in both
  Task 1 Step 4 and Task 2 Step 1; flag it so a later fixup doesn't "simplify" the duplication away.
- **Choice:** No edit; recorded here as the durable note the reviewer asked for.
- **Grounding:** `writing-plans/SKILL.md` makes "Similar to Task N" a plan failure — tasks are read in
  isolation, so each carries its own copy.
- **Alternative considered:** Extracting a shared script file — rejected; this plan already decided
  the verification script is never committed.

---

## Standards review provenance

- **Reviewer:** Claude fallback (`reviewer` agent, fresh context, read-only toolset) — not Codex.
- **Codex failure class:** silent runtime crash — the bridge agent idled twice with no output, no
  `codex-companion` process was alive, and no job-state directory was ever created for this worktree;
  no Codex job id exists. One-time native fallback per the codex-collaboration contract; no Codex retry.
- **Reviewed at:** plan commit `f0b17c2` on branch base `165a3b0` (= origin/main). Focus: none configured.
- **Dispositions:** B1 (Blocking) accepted and applied; S1 (Should-fix) accepted and applied (auto
  mode); D1 (Discussion) recorded, no edit. Rejected: none. The reviewer's own dry-run reproduced every
  figure in the plan (7,189 bytes / 152 lines / +3 −1) and confirmed no gate asserts over an unscoped
  commit range.

---

### Task 1: Land W1 and W2 in `writing-plans/SKILL.md`

**Files:**
- Create: none.
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md`
- Test: none — see **Test seams**. Verification is the content and size gates in Step 4.

**Interfaces:**
- Consumes: `.claude/specs/2026-08-12-range-scoped-gates-design.md`, section `## The edits`. The W1
  fences are at spec lines 129–131 (BEFORE) and 135–139 (AFTER); the W2 fences are at spec lines
  160–162 (BEFORE) and 166–168 (AFTER). Both fences are reproduced verbatim in the steps below; if the
  two ever disagree, **the spec's fence wins** — report the discrepancy rather than choosing.
- Produces: `home/common/agent-skills/skills/writing-plans/SKILL.md` at 7,189 bytes / 152 lines,
  containing both AFTER blocks exactly once. Task 2 gates on exactly this.

Run every command from the repository root
(`/Users/anis/tmp/nix-config/.claude/worktrees/issue-11-range-scoped-gates`).

- [ ] **Step 1: Confirm the gates are red before the edit**

Run:

```bash
F=home/common/agent-skills/skills/writing-plans/SKILL.md
wc -c "$F"
awk 'END{print NR" lines"}' "$F"
grep -cF '**Scope every gate to the files the plan owns.**' "$F"
grep -cF '4. **Falsifiability and gate scope**' "$F"
grep -cF '4. **Falsifiability** — every task has a verification line that can fail.' "$F"
```

Expected, at the commit this task starts from: `6203`, `150 lines`, then `0`, `0`, `1`. The two zeros
are the falsifiable observation — the rule is absent and the Self-review item still carries its old
label. A `1` on either of the first two greps means the edit already landed and this task has nothing
to do; stop and report rather than editing.

`grep -c` exits non-zero when it prints `0`. Run these as plain sequential commands; under `set -e`
the step aborts on a correct result.

- [ ] **Step 2: Apply W1 — the new rule paragraph at the end of `## Task structure`**

Use the Edit tool on `home/common/agent-skills/skills/writing-plans/SKILL.md`. This is one literal
string replacement: the AFTER block restates the BEFORE paragraph unchanged and appends a blank line
plus a second paragraph. The BEFORE string occurs exactly once in the file, at line 124, immediately
above the `## No placeholders` heading.

`old_string` — copy verbatim, one line:

```markdown
**Every task carries at least one verification line that could fail.** Name the command and the observation that would show the task incomplete, and confirm that observation holds at the commit the implementer starts from. A criterion already true at the base commit is how an implementer "completes" a no-op.
```

`new_string` — copy verbatim, three lines (paragraph, empty line, paragraph). The second paragraph is
a single unwrapped line; do not re-wrap it, and do not lose the empty line between the two:

```markdown
**Every task carries at least one verification line that could fail.** Name the command and the observation that would show the task incomplete, and confirm that observation holds at the commit the implementer starts from. A criterion already true at the base commit is how an implementer "completes" a no-op.

**Scope every gate to the files the plan owns.** Give diffs a pathspec (`git diff --stat BASE..HEAD -- <the paths named in the plan's Files: blocks>`) or assert against file content directly; never write a raw commit-range expectation — "exactly three files changed", "every commit in the range is a `feat:`". The range is not the plan's to grade: the plan and spec files land in it, so do the caller's `docs(plans):`/`docs(specs):` artifact commits, and a ship-time sync merge pulls in everything the integration branch advanced by — the gate then reads another issue's shipped work as scope creep and demands reverting it. Where commit shape genuinely is under test, restrict to the branch's own commits (`git log --no-merges BASE..HEAD ^origin/<integration-branch>`; the sync merge is unreachable from the integration branch, so `^` alone leaves it in) and name the artifact and review-fixup subjects as exempt.
```

- [ ] **Step 3: Apply W2 — Self-review item 4 gains the gate-scope check**

Use the Edit tool on the same file. The BEFORE string occurs exactly once, at line 144 (line 146 after
W1 has been applied), as the last item of the numbered `## Self-review` list. W1 and W2 are mutually
independent — neither BEFORE string appears inside the other's AFTER block — so this replacement is
unaffected by Step 2 having run.

`old_string` — copy verbatim:

```markdown
4. **Falsifiability** — every task has a verification line that can fail.
```

`new_string` — copy verbatim, still one line:

```markdown
4. **Falsifiability and gate scope** — every task has a verification line that can fail, and no gate asserts over an unscoped commit range.
```

- [ ] **Step 4: Verify both edits landed byte-for-byte**

Run:

```bash
python3 - <<'PY'
import pathlib, sys
SPEC = pathlib.Path('.claude/specs/2026-08-12-range-scoped-gates-design.md').read_text()
TARGET = pathlib.Path('home/common/agent-skills/skills/writing-plans/SKILL.md')

def fence(tag, kind):
    body = SPEC.split('### ' + tag + ' — ')[1]
    return body.split('**' + kind + '**\n\n```markdown\n')[1].split('\n```\n')[0]

text = TARGET.read_text()
checks = [
    ('W1 AFTER  present exactly once', text.count(fence('W1', 'AFTER')),  1),
    ('W2 AFTER  present exactly once', text.count(fence('W2', 'AFTER')),  1),
    ('W2 BEFORE gone',                 text.count(fence('W2', 'BEFORE')), 0),
    ('byte size',                      len(text.encode()),                7189),
    ('line count',                     text.count('\n'),                  152),
]
bad = 0
for name, got, want in checks:
    ok = got == want
    bad += 0 if ok else 1
    print(('PASS' if ok else 'FAIL'), name, '->', got, '(want', str(want) + ')')
print('FAILURES:', bad)
sys.exit(1 if bad else 0)
PY
rc=$?
echo "exit=$rc"
[ "$rc" -eq 0 ]
```

Expected: five `PASS` lines, `FAILURES: 0`, `exit=0`.

The heredoc reads both fences out of the committed spec by section anchor, so the check has the same
source of truth as the edit and cannot drift from it. If extraction itself breaks — a spec that no
longer has the expected fence layout — Python raises `IndexError` and the step exits non-zero rather
than passing vacuously.

**If `byte size` or `line count` fails but the presence checks pass**, the surrounding file changed,
not your edit. Report it; do not adjust the AFTER text to hit the number.

**If a presence check fails**, the block was transcribed rather than copied. Recover deterministically:
restore the pristine file first — nothing is committed until Step 5, and W1's AFTER restates its
BEFORE, so replaying over a mistyped edit would append a correct paragraph while leaving the bad one
in place — then replay the replacement from the spec and re-run the check above:

```bash
git checkout HEAD -- home/common/agent-skills/skills/writing-plans/SKILL.md
python3 - <<'PY'
import pathlib
SPEC = pathlib.Path('.claude/specs/2026-08-12-range-scoped-gates-design.md').read_text()
TARGET = pathlib.Path('home/common/agent-skills/skills/writing-plans/SKILL.md')

def fence(tag, kind):
    body = SPEC.split('### ' + tag + ' — ')[1]
    return body.split('**' + kind + '**\n\n```markdown\n')[1].split('\n```\n')[0]

text = TARGET.read_text()
for tag in ('W1', 'W2'):
    before, after = fence(tag, 'BEFORE'), fence(tag, 'AFTER')
    if text.count(after) == 1:
        print(tag, 'already applied')
        continue
    assert text.count(before) == 1, (tag + ' BEFORE occurs ' + str(text.count(before)) + ' times, expected 1 — stop and report')
    text = text.replace(before, after)
    print(tag, 'applied')
TARGET.write_text(text)
PY
```

- [ ] **Step 5: Commit**

Run:

```bash
git add home/common/agent-skills/skills/writing-plans/SKILL.md
git commit -m "$(cat <<'EOF'
fix(agents): writing-plans scopes verification gates to owned files (#11)

Adds a rule paragraph to the end of Task structure telling plan authors to
give every gate a pathspec or a direct content assertion, and never a raw
commit-range expectation. Names the three things that land in a range no
matter what the plan intends -- the plan and spec files, the caller's
docs(plans):/docs(specs): artifact commits, and the ship-time sync merge --
and gives the branch-filtered git log form for the case where commit shape
genuinely is under test.

Self-review item 4 becomes "Falsifiability and gate scope" so the rule is
caught at the file's own review pass rather than only stated.

Issue #1 hit the unscoped form twice on one branch: a mid-run BLOCKED task
when the Phase-5 provenance amendment landed inside the verification range,
and a ship-time round where the sync merge made three other issues' shipped
work read as scope creep.

Applied verbatim from .claude/specs/2026-08-12-range-scoped-gates-design.md;
6,203 -> 7,189 bytes as measured there.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012tJnHYhagKXWknC1KnFg8W
EOF
)"
```

Expected: one new commit touching one file. Confirm the trailers survived:

```bash
git log -1 --format='%s%n---%n%(trailers:key=Co-Authored-By,key=Claude-Session)'
git show --stat --format= HEAD
```

Expected: the subject line, then both trailer lines, then a stat naming
`home/common/agent-skills/skills/writing-plans/SKILL.md` and nothing else — `1 file changed, 3
insertions(+), 1 deletion(-)`.

---

### Task 2: Whole-change verification

**Files:**
- Create: none.
- Modify: none. This task is a gate: it produces evidence, not a commit. If a check fails, fix it in
  `home/common/agent-skills/skills/writing-plans/SKILL.md` and amend Task 1's commit rather than adding
  a new one.
- Test: none — see **Test seams**.

**Interfaces:**
- Consumes: `home/common/agent-skills/skills/writing-plans/SKILL.md` as Task 1 left it, and
  `.claude/specs/2026-08-12-range-scoped-gates-design.md` as the byte-source for the presence checks.
- Produces: the verification evidence quoted in the task report and in the PR body. Nothing downstream
  consumes it.

Run every command from the repository root
(`/Users/anis/tmp/nix-config/.claude/worktrees/issue-11-range-scoped-gates`).

- [ ] **Step 1: Both edits present verbatim, at the acceptance size**

Run:

```bash
python3 - <<'PY'
import pathlib, sys
SPEC = pathlib.Path('.claude/specs/2026-08-12-range-scoped-gates-design.md').read_text()
TARGET = pathlib.Path('home/common/agent-skills/skills/writing-plans/SKILL.md')

def fence(tag, kind):
    body = SPEC.split('### ' + tag + ' — ')[1]
    return body.split('**' + kind + '**\n\n```markdown\n')[1].split('\n```\n')[0]

text = TARGET.read_text()
checks = [
    ('W1 AFTER  present exactly once', text.count(fence('W1', 'AFTER')),  1),
    ('W2 AFTER  present exactly once', text.count(fence('W2', 'AFTER')),  1),
    ('W2 BEFORE gone',                 text.count(fence('W2', 'BEFORE')), 0),
    ('byte size',                      len(text.encode()),                7189),
    ('line count',                     text.count('\n'),                  152),
]
bad = 0
for name, got, want in checks:
    ok = got == want
    bad += 0 if ok else 1
    print(('PASS' if ok else 'FAIL'), name, '->', got, '(want', str(want) + ')')
print('FAILURES:', bad)
sys.exit(1 if bad else 0)
PY
rc=$?
echo "exit=$rc"
[ "$rc" -eq 0 ]
```

Expected: five `PASS` lines, `FAILURES: 0`, `exit=0`.

This is the task's falsifiable line. At the commit this plan was written against it reports
`FAIL W1 AFTER present exactly once -> 0`, `FAIL W2 AFTER present exactly once -> 0`,
`FAIL W2 BEFORE gone -> 1`, `FAIL byte size -> 6203`, `FAIL line count -> 150`, `FAILURES: 5`,
`exit=1`. It is deliberately a content assertion against the file rather than a diff: it is unaffected
by anything else on the branch or by what a sync merge brings in.

- [ ] **Step 2: Scope — `sdd/SKILL.md` untouched, one skill file changed**

Run:

```bash
echo "-- sdd/SKILL.md: the verdict is 'no edit', so this must be empty --"
git diff --stat origin/main...HEAD -- home/common/agent-skills/skills/sdd/SKILL.md
echo "-- writing-plans/SKILL.md: this branch's own change --"
git diff --stat origin/main...HEAD -- home/common/agent-skills/skills/writing-plans/SKILL.md
echo "-- anything changed outside the allowed set (must be empty) --"
git diff --name-only origin/main...HEAD -- ':(exclude)home/common/agent-skills/skills/writing-plans/SKILL.md' ':(exclude).claude/plans' ':(exclude).claude/specs'
echo "-- merge-base the three-dot form resolves to --"
git merge-base origin/main HEAD
```

Expected: the first command prints **nothing** — zero changed lines in `sdd/SKILL.md`, satisfying spec
requirement **R8**'s recorded verdict. The second prints `1 file changed, 3 insertions(+), 1
deletion(-)`. The third prints **nothing** — the excluded pathspecs are the allowed set (the one file
this plan owns, plus the flow's own plan and spec artifacts, which land in the range regardless of what
this plan does), and the three-dot form already keeps the sync merge's commits out of the range by
construction, so an empty result here means nothing else changed anywhere in the tree, satisfying **R9**
honestly rather than by restricting the search to a directory first. The fourth prints a SHA
(`165a3b0…` before any sync merge; the merged tip afterwards) — it is context for reading the three
diffs, not a value to assert.

Two properties of these gates are the point of this change and must not be "simplified" away in a
review fixup:

- **Every diff carries a pathspec.** Without one the diffstat also lists this plan, the design spec,
  and — after ship-issue's Phase-1 sync merge — every file `main` advanced by, and reports them as
  scope creep.
- **Every diff uses the three-dot form.** `origin/main...HEAD` diffs from `merge-base(origin/main,
  HEAD)` to `HEAD`. A sync merge advances that merge-base to the merged tip, so the commits the merge
  brought in fall out of the range by construction; if `origin/main` advances again afterwards, the
  merge-base stays put and the new upstream commits are excluded too.

`docs(plans):` and `docs(specs):` commits, review fixups, and the sync merge itself are **expected**
residents of this branch's history. No gate in this task inspects the commit list, so none of them can
make it fire. The `sdd` check is a non-regression guard rather than a falsifiable one — it is
correctly empty at the base commit too, and it is here to catch a scope violation, not to prove work
was done. Step 1 carries this task's falsifiability.

- [ ] **Step 3: The build**

Run:

```bash
just build
rc=$?
echo "exit=$rc"
[ "$rc" -eq 0 ]
```

Expected: `exit=0`. The run takes several minutes. One pre-existing evaluation warning is normal and is
**not** a regression — `evaluation warning: 'system' has been renamed to/replaced by
'stdenv.hostPlatform.system'` is present at the base commit too.
`home/common/claude-code/default.nix` copies the whole skills tree into the store via
`skillsDir = ../agent-skills/skills`, so this run does exercise the edited file. A Markdown-only change
cannot break Nix evaluation; the run is here because `CLAUDE.md` makes a green `just build` this
repo's definition of verified, and the issue asks for it.

- [ ] **Step 4: Requirements roll-call**

Read the landed text and confirm each of the spec's requirements maps to it. Report the mapping:

| Req | Where it landed |
|-----|-----------------|
| **R1** — forbids raw commit-range expectations, imperatively | W1, `never write a raw commit-range expectation` |
| **R2** — names the substitutes concretely | W1, the pathspec'd `git diff --stat` form and "assert against file content directly" |
| **R3** — names all three expected residents | W1, "the plan and spec files land in it", "the caller's `docs(plans):`/`docs(specs):` artifact commits", "a ship-time sync merge" |
| **R4** — gives the branch-scoped `git log` escape hatch including `--no-merges` | W1, `git log --no-merges BASE..HEAD ^origin/<integration-branch>` plus the parenthetical explaining why `^` alone is insufficient |
| **R5** — reachable from Self-review | W2, item 4 relabelled `Falsifiability and gate scope` |
| **R6** — register and layout preserved | Both blocks copied verbatim from the spec; proven by Step 1's exact substring match and the 152-line count |
| **R7** — addition ≤ 1,000 bytes | 986 (6,203 → 7,189), proven by Step 1's byte check |
| **R8** — recorded verdict on `sdd/SKILL.md` | The spec's verdict section; enforced by Step 2's empty diff |
| **R9** — no other file edited | Step 2's exclusion diff over `origin/main...HEAD` (everything outside the owned file plus the plan/spec artifacts), empty output |

Confirm the two claims that only reading can settle, and quote the evidence:

```bash
sed -n '124,128p' home/common/agent-skills/skills/writing-plans/SKILL.md
sed -n '137,147p' home/common/agent-skills/skills/writing-plans/SKILL.md
```

Expected: the first prints the falsifiability paragraph, an empty line, the new `**Scope every gate to
the files the plan owns.**` paragraph as **one unwrapped line**, an empty line, and the
`## No placeholders` heading itself on line 128 — confirming the rule sits at the end of `## Task
structure` and did not get re-flowed. The second prints the `## Self-review` block with four numbered
items, item 4 reading
`4. **Falsifiability and gate scope** — every task has a verification line that can fail, and no gate
asserts over an unscoped commit range.` — confirming the checklist still has four items, not five.

Report the roll-call, Step 1's five `PASS` lines, Step 2's three diff outputs, and the build's exit
code. This task commits nothing.
