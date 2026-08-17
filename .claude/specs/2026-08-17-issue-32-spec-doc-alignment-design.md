# Align the shipped specs and skill docs with what merged in #21–#23

Issue: https://github.com/fagenorn/nix-config/issues/32

## Problem

Four passages written during issues #21–#23 describe behaviour that the same work later
changed. Each one is load-bearing for a *future* reader: three of them are the recorded
design and evidence a follow-on implementer seeds from, and the fourth is a live
instruction an agent executes every Phase 0. A reader who copies them today copies a
reversed decision, a false claim about an output format, a superseded measurement, and a
tool that the merged work retired.

Concretely:

1. The diff-scope design spec's **Test seams** section tells the reader to follow
   `test_agent_model_matrix.py`'s two-layer loader precedent **verbatim**. D20 of that
   same spec reversed exactly this — `load_module()` must register the module in
   `sys.modules` before `exec_module` — and the shipped `test_diff_scope.py` does. A new
   suite seeded from the unmarked sentence errors in `setUpClass` before asserting
   anything.
2. The same spec introduces `--format text` as "**the same content**" as the JSON form.
   It is not: the shipped `format_text` emits no `range:` line, and its own docstring says
   so. Prose and behaviour contradict each other, and the issue asks which one is wrong.
3. The degradation-gate evidence spec quotes `product: 64 lines, 3 files` /
   `excluded: … 2 artifact`, recorded at `224954b3`. Two further commits landed on that
   branch before it merged, so the shipped scope at the merged head `b83e618` is
   `76 lines, 3 files` / `3 artifact`. The document reads as a statement about what
   shipped while holding a number that never shipped.
4. `from-issue/investigate.md`'s C4 note still routes size accounting through
   `git diff --numstat`. Issues #21–#22 made `diff-scope` the accounting authority and
   ship-issue's Phase-5 gate now says "Measure, never hand-count". This is the **only**
   remaining `numstat` prose in the from-issue skill (verified by grep), and it was
   deliberately deferred: the degradation-gate design spec carries a section titled
   "`from-issue/investigate.md`'s C4 note stays verbatim" and lists it under **Out of
   scope** as a recorded residual, precisely because rewriting it "is a from-issue change
   with its own judgement call (what does an unwritten change's size gate call?)". Issue
   32 discharges that residual and answers that judgement call.

None of this is a bug in running software. The gate still decides correctly, the helper
still measures correctly. The defect is that the durable record disagrees with the
artefact, and nothing in the suite notices.

## Solution

Four prose corrections plus one contract test. Two governing rules decide *how* each
correction is made, and they are what keeps this from being a silent rewrite of history:

- **A spec is a record; amend it inline, never overwrite it.** The diff-scope spec
  already established the form — D19 carries
  `(**amended by D25** — this row originally read "…", which the correctness review found
  to be exactly the bug)`. Items 1 and 2 get the same treatment. Item 3's evidence
  snapshot is a recorded *observation*; it is preserved byte-for-byte and gains an
  addendum rather than a corrected figure.
- **A skill doc is a live instruction; rewrite it in place.** Item 4 gets no amendment
  marker. `investigate.md` is executed, not cited; an "originally read" clause in an
  operating instruction is noise the agent must read past on every run.

Per D3 below, issue 32 adds **no rows to the diff-scope spec's ledger**. That ledger runs
D1–D25 and belongs to issue 21; the amendment markers this work inserts cite either an
existing row of it (item 1 → its own D20, unqualified) or a row of *this* spec (item 2 →
D2 here, qualified by issue and spec name per D9, because that ledger has a D2 of its own).

### Item 1 — mark the reversed loader precedent

In `.claude/specs/2026-08-16-diff-scope-helper-design.md`, section `## Test seams`, the
sentence that today reads:

> It follows `test_agent_model_matrix.py`'s two-layer precedent verbatim:

becomes:

> It follows `test_agent_model_matrix.py`'s two-layer precedent (**amended by D20** — this
> sentence originally read "precedent verbatim", which D20 found to be exactly the bug:
> `load_module()` must additionally register the module in `sys.modules` before
> `spec.loader.exec_module`, or every classifier-layer test errors in `setUpClass`):

Nothing else in the section changes. The two sub-bullets describing the classifier layer
and the CLI layer are accurate and stay. Note the live sentence is wrapped mid-phrase
("…two-layer" / "precedent verbatim:"), so the edit spans two physical lines; `verbatim`
carries no emphasis in the source and none is added.

Why this shape: it matches D19's inline parenthetical exactly — bolded `**amended by
Dnn**`, an em-dash, the original wording quoted, then the reason. It cites the row that
already carries the full verified rationale (a `dataclasses` field resolving annotations
through `sys.modules[cls.__module__]` under `from __future__ import annotations`) instead
of restating it, which is the ledger contract.

### Item 2 — the text form deliberately omits the range identity (doc-only)

**Direction: doc-only.** `diff-scope.py` is not touched. Per D1.

In the same spec, the `**stdout, \`--format text\`.**` paragraph today reads:

> The same content for a human or an agent quoting it into prose: a `product:` line, an
> `excluded:` line, then one indented `<churn>  <path>` line per ranked file, binaries
> suffixed ` (binary)`.

becomes:

> The same *measurement* for a human or an agent quoting it into prose, minus the range
> identity: a `product:` line, an `excluded:` line, then one indented `<churn>  <path>`
> line per ranked file, binaries suffixed ` (binary)`. (**amended by issue 32's alignment
> spec, D2** — `.claude/specs/2026-08-17-issue-32-spec-doc-alignment-design.md`; this
> paragraph originally read "the same content", which was never true of the shipped
> helper.) The omission is deliberate: every line of the text form is a measured row, whereas the range
> is caller-supplied *input*, and a quoter carries it in the invocation printed above the
> output — the pattern `.claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md`
> already demonstrates. `--format json` echoes `range` because it is the machine record
> and must stay self-describing once detached from the command that produced it.

The grounding for choosing doc-only over adding a `range:` line is in D1; the short form
is that the range is already in the caller's hand at every documented call site, and the
alternative costs six tests, a second skill document, and a contract pin to buy a
value the quoting agent typed itself.

The marker leads with **issue 32's alignment spec** rather than a bare `D2` for a reason
that is not stylistic: the diff-scope spec's own ledger already contains a D2 (the row
that removed the stdin seam), so a bare "amended by D2" inside that document points at the
wrong row on a skim. Per D9. This is the only cross-spec citation in the slice; item 1's
marker cites the same spec's own D20 and needs no qualifier.

### Item 3 — preserve the snapshot, add a post-merge addendum

In `.claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md`:

- The fenced command, the fenced output (`product: 64 lines, 3 files` /
  `excluded: 0 lockfile, 0 generated, 2 artifact` and its three rows), the `Recorded
  2026-08-17 … at 224954b3…` line, and the `Re-run this command fresh at ship time`
  closing paragraph all stay **exactly as they are**. They are a true record of a real run
  at a named commit.
- Exactly one sentence is re-scoped so it cannot be read as a claim about what shipped.
  `Reading it the way the gate does: \`64\` product lines and \`3\` product files, both
  under ≤1,000 / ≤20, so this branch's own size prerequisite is satisfied.` becomes
  `Reading the snapshot the way the gate does: at \`224954b3\`, \`64\` product lines and
  \`3\` product files, both under ≤1,000 / ≤20, so this branch's own size prerequisite is
  satisfied — see the post-merge reading below for the figure at the merged tip.` The rest
  of that paragraph (the `2 artifact` explanation, the uncommitted-evidence-file note, the
  "one path per file throughout" closer) is unchanged and stays true of the snapshot.
- A new final section is appended, titled `## Post-merge reading (the figure that
  shipped)`, recording: PR #27 merged with head `b83e618e898ba80372756d0542f8872ded0e1672`
  (merge commit `5aa2834f10796c7c71ae7c6f377610d1e63f3f36`);
  `git merge-base b83e618e fc498cb7` is `fc498cb7…`, the same base the snapshot used, so
  the two runs are directly comparable; two commits landed after the snapshot — `6f0b4cf`
  (this evidence file) and `b83e618` (`test(ship-issue): pin the gate prerequisites'
  polarity`) — which is what moved 64 → 76 and 2 → 3 artifact; and the merged-head run,
  quoted verbatim from a real execution of the same command with `..b83e618e…`
  substituted:

  ```
  product: 76 lines, 3 files
  excluded: 0 lockfile, 0 generated, 3 artifact
    72  home/common/agent-skills/tests/test_workflow_skill_contracts.py
    2  home/common/agent-skills/skills/ship-issue/SKILL.md
    2  home/common/agent-skills/skills/ship-issue/evals/evals.json
  ```

  The section closes by stating the gate conclusion is unchanged — 76 ≤ 1,000 and 3 ≤ 20,
  the same verdict by the same margin — and that the third excluded artifact is this
  evidence file itself, now committed, exactly as the snapshot's own prose predicted
  ("it starts counting on any re-run made after this document is committed").

The addendum is not merely a correction: the document told itself to "re-run this command
fresh at ship time", and the addendum is that run. Per D4.

### Item 4 — name the shipped mechanism in the C4 note

In `home/common/agent-skills/skills/from-issue/investigate.md`, the final line becomes:

> **Size gates measure product changes (C4):** the Phase-0 number is an *estimate* — no
> range exists yet, so nothing can be measured; estimate the product change alone, leaving
> out the `specDir`/`planDir` artifacts this run will write, because they are process
> output. Once the branch has a range, `diff-scope` is the accounting authority
> (ship-issue's Phase-5 gate carries the invocation and the thresholds): measure, never
> hand-count, and exclude this run's own artifacts by passing one `--artifact-path` per
> file it wrote — never `<specDir>`/`<planDir>` themselves. Historical artifacts that are
> themselves the requested product still count.

Three properties this wording must keep, in priority order:

1. **Honest about both moments.** The line covers pre-worktree *estimating* (no range
   exists, no helper can run — it is an estimate and says so) and *later counting* (a range
   exists, `diff-scope` is authoritative). Collapsing them into "run diff-scope" would be
   the same class of defect this issue is fixing. This is the judgement call the
   degradation-gate spec deferred, answered.
2. **The directional carve-out survives.** This run's own artifacts are excluded by naming
   them one file at a time; `<specDir>`/`<planDir>` are never passed; a historical artifact
   that is itself the requested product still counts.
3. **It states policy and does not restate accounting.** Per the degradation-gate spec's
   established split — "the gate states a policy and calls the helper; the accounting
   itself lives in `diff-scope.py` and is not restated here" — this line names the helper
   and the carve-out but carries **no threshold numbers** and no runnable invocation. It
   names exactly one flag, `--artifact-path`, because that flag *is* how the carve-out is
   expressed and the policy is unstatable without it; the range arguments, the format flag
   and the two boundaries stay spelled once, in ship-issue's gate, which this line points
   at by name.

The word `numstat` disappears from the file entirely (per D5): the line tells the agent
what to do, and ship-issue's own phrasing for the same instruction is "Measure, never
hand-count", which this echoes without needing the retired tool's name. That also makes
the contract pin below unambiguous.

## Decisions

**Modules and interfaces touched.** `diff-scope.py`'s CLI contract is unchanged — no
flags, no output shape, no exit codes. The two `.claude/specs/` documents and the
`from-issue` skill's `investigate.md` change as prose. One new test method is added to
the existing `WorkflowSkillContractsTest` class.

**Behaviour.** The only executable behaviour change in the whole slice is the new
assertion. Every agent-visible behaviour — what the helper prints, what the gate decides,
what Phase 0 excludes from an estimate — is identical before and after; item 4 changes
*which tool the instruction names*, and the merged tooling already made that the true
answer.

**No Nix change.** `investigate.md` already exists inside a skill directory that is linked
wholesale, and the new test method lands in a file `just agent-workflow-tests` already
runs. No `default.nix` and no `justfile` edit. Under this repo's CLAUDE.md, `just build`
is the verification step *after editing any `.nix`*; no `.nix` is edited, so
`just agent-workflow-tests` is the load-bearing gate. Running `just build` anyway is cheap
and harmless, but it is not what proves this slice.

**Facts verified during design and grill, so the planner need not re-derive them.** The
implementer should still re-read the live text before editing, but these are settled:

- `just agent-workflow-tests` at base `de83938`: **175 tests, OK**.
- The merged-head measurement for item 3 was executed, not inferred; its stdout is quoted
  verbatim in the Item 3 section.
- PR #27 (`Retune the degradation gate to 1,000 product lines`) is `MERGED` with
  `headRefOid = b83e618e898ba80372756d0542f8872ded0e1672` and merge commit
  `5aa2834f10796c7c71ae7c6f377610d1e63f3f36`; `git merge-base b83e618e fc498cb7` is
  `fc498cb7…`, the base the snapshot used.
- The gate lives under `## Phase 5 — Review the PR` in `ship-issue/SKILL.md`, so item 4's
  "ship-issue's Phase-5 gate" cross-reference is correct.
- `"the same content"` at the `--format text` paragraph is the **only** text/JSON parity
  claim in the diff-scope spec; no sibling passage repeats it, so item 2's single-paragraph
  fix is complete.
- `investigate.md`'s line is the **only** restatement of the C4 artifact carve-out in any
  skill (`from-issue/SKILL.md`'s `specDir`/`planDir` mention governs worktree
  disposability, a different subject), so item 4's fix is complete and the new pin is
  correctly scoped to one file.

**No ADR, no context-map area, no glossary.** Settled twice already for this exact area —
D16 of the diff-scope design spec and the degradation-gate spec's "No ADR, no context-map
area" section: the ADR gate needs hard-to-reverse **and** surprising **and** a real
trade-off, and this repo has no `adr/` tree or context map outside an eval fixture, so one
record would invent a whole convention for itself. Re-checked during the grill pass: the
repo root has no `docs/`, no `CONTEXT.md`, no `GLOSSARY.md`, and no decision-record
directory; `CLAUDE.md` is the standing guidance doc. Every decision here is reversible by
editing a sentence, which is the opposite of the ADR gate's first condition. This spec is
the record.

**Canonical terms are unchanged.** The slice introduces no new domain vocabulary. It uses
the repo's established terms as-is — *product lines* / *product files* (spelled once in
`test_workflow_skill_contracts.py` as `GATE_LINE_BOUNDARY` / `GATE_FILE_BOUNDARY`),
*artifact* for a `specDir`/`planDir` file, and *range* for the two-dot `<base>..<head>`
argument. The one phrase that reads as new — `diff-scope` is "the accounting authority" —
is a compression of the degradation-gate spec's own sentence, "the gate states a policy
and calls the helper; the accounting itself lives in `diff-scope.py`", and introduces no
concept that spec does not already carry.

## Test seams

Existing seams only; no new harness, no new file.

**1. `just agent-workflow-tests`** — baseline verified at this branch's base:
**175 tests, OK**. One new method joins
`home/common/agent-skills/tests/test_workflow_skill_contracts.py`, the file that already
pins ship-issue's `diff-scope` invocation, and it is the seam for **item 4** (per D6).
Suggested name, matching the suite's "what the doc must guarantee" naming:
`test_phase0_size_note_delegates_counting_to_diff_scope`. It:

- Reads `from-issue/investigate.md` (the module already resolves `FROM_ISSUE_DIR`; add a
  sibling constant for the file and read it in `setUpClass`, matching how every other
  document in that suite is loaded).
- `assertNotIn("numstat", …)` — **fails at the base commit**, which is what makes item 4's
  acceptance criterion falsifiable rather than decorative.
- Pins the delegation as a whole affirmative clause, not a bare `diff-scope` token. The
  suite's own precedent for this is explicit
  (`test_ship_issue_eval_restates_the_gate_boundary_it_grades`: "a bare `diff-scope` token
  also matches a clause saying the boundary is *not* measured with the helper, which is
  the inversion this test guards"). Pin
  `` "`diff-scope` is the accounting authority" `` and `"measure, never hand-count"`.
- Pins the carve-out's polarity in both directions: `` "one `--artifact-path` per file" ``
  and `` "never `<specDir>`/`<planDir>` themselves" `` and
  `"still count"` for the historical-artifact clause.
- Pins the estimate/count split so a later editor cannot collapse it: assert both
  `"estimate"` and `"Once the branch has a range"` are present.
- `assertNotIn("1,000", …)` and `assertNotIn("≤20", …)` — guards the
  no-sibling-restatement rule, mirroring the gate test's own `assertNotIn("400")`. These
  pass at base; they are a ratchet, not an acceptance criterion.

The suite must end green with **176 tests**.

**2. The existing `test_diff_scope.py` text-format assertions** are the standing pin that
makes **item 2**'s corrected prose true, and no new test is needed. Six tests already fix
the text form's exact shape — `format_text` equality over a full payload,
`lines[0] == "product: 6 lines, 8 files"`, and
`assertEqual(len(text.splitlines()), 2 + 8)` ("two header lines plus one line per product
file, and nothing else"). A `range:` line cannot be added without breaking all of them,
and the corrected prose is checkable against them by reading. Note the shipped test's own
name — `test_text_format_reports_the_same_totals` — already frames the text form as
*totals*, which is what the amended paragraph now says.

**3. Item 3 is verified by re-execution, not by a test.** Run the evidence file's own
command with `..b83e618e898ba80372756d0542f8872ded0e1672` as the head and confirm the
output matches the addendum byte-for-byte. Executed during this design pass at base
`de83938`; the block quoted in the Item 3 section above is that run's verbatim stdout.

**4. Items 1–3 get no automated seam, deliberately** (per D7). No suite in this repo reads
`.claude/specs/**`, and adding one would invent a convention for a single record — the
same objection D16 of the diff-scope spec raised, and it applies with more force here
because a spec-prose linter would have to encode "which historical sentence is still
true", which is exactly the human judgement this issue is exercising. Verification is
reading the four passages, which is the issue's own stated demo.

## Out of scope

- **Any change to `diff-scope.py`, its CLI contract, or `test_diff_scope.py`.** Per D1.
  The helper is a merged contract twice reviewed (issues 21 and 31); this slice aligns
  prose to it, never the reverse.
- **Rewriting the diff-scope spec to reflect issue 31's later changes** — `--no-relative`,
  the streamed lockstep header scan, Unicode line-separator escaping. That spec's D19/D25
  region and its "How the range is read" section describe the issue-21 helper; issue 31
  has its own design spec (`2026-08-17-diff-scope-residuals-design.md`) and its own
  ledger. Reconciling the two is a separate concern with its own judgement calls.
- **Any spec drift not named by issue 32.** Four passages, listed by name above. A fifth
  one found while reading is recorded as a residual in the PR body, not fixed here.
- **Retuning any threshold.** ≤1,000 product lines and ≤20 product files are unchanged and
  are not restated anywhere new.
- **`patches/agent-plugins/**` and any `patchRevision` bump.** Nothing in this slice
  touches the plugin tree.
- **Adding an `adr/` tree or a context map.** Per the Decisions section.
- **Backfilling amendment markers into other historical specs.** The convention is applied
  to the two passages this issue names; a sweep is a different, much larger question.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Item 2 resolves **doc-only**: the spec prose is corrected to say the text form deliberately omits the range identity, and `diff-scope.py` is not touched | The issue's title ("Align the shipped specs and skill docs with what merged") and demo ("reading each of the four passages shows text consistent with the merged behavior") both point at the prose; the shipped `format_text` docstring already documents the omission as intentional ("the text form omits the range"), so behaviour and code-comment already agree and only the spec dissents. The gate-agent-quoting argument does not survive contact: at every documented call site the caller *constructs* the range (`$BASE_SHA..$HEAD_SHA`, computed two lines earlier in ship-issue's own snippet), so the helper would be echoing a value the quoter typed, and the repo's own evidence spec already shows the pattern of printing the invocation above the output. Cost asymmetry seals it: `test_diff_scope.py` fixes the text shape across six tests including `len(text.splitlines()) == 2 + 8`, ship-issue's gate prose says "its first line reads `product: …`", and `test_workflow_skill_contracts.py` pins that gate string — a `range:` line breaks all three layers. Smaller, more reversible, more idiomatic per the `--auto` tiebreak | Prepend a `range:` line to `format_text` — a behavioural change to a twice-merged contract, inside an issue whose four items are otherwise pure documentation, cascading into `diff-scope.py`, seven test assertions, `ship-issue/SKILL.md` and its contract pin, to supply a value the caller already holds |
| D2 | The `--format text` paragraph keeps an inline `(**amended by issue 32's alignment spec, D2** — …, this paragraph originally read "the same content", …)` marker (**amended by D9** — the citation originally led with a bare `D2`, which collides with the diff-scope spec's own D2) and states *why* the range is absent (text lines are measured rows; the range is caller-supplied input; the machine record is JSON) | Historical specs are the accepted record of past decisions and the repo's convention for correcting one is an inline amendment marker, not a silent rewrite (D19/D25 of the diff-scope spec). Recording the *reason* is what stops the next reader re-opening the same question and "fixing" the helper | Silently replace the sentence — erases that the spec ever misdescribed the format, and the next reviewer re-derives the whole question; state the correction with no reason — invites exactly the behavioural change D1 rejected |
| D3 | Issue 32 appends **no rows** to the diff-scope spec's D1–D25 ledger; item 1's marker cites that spec's existing D20, item 2's cites D2 of this spec by qualified path | The ledger contract is one issue-level table per spec, cited by later phases rather than duplicated; D20 already records item 1's decision in full, so a new row would restate it, and item 2's decision is being made *now*, by this issue, so it belongs to this issue's store. Qualifying the cross-spec citation keeps the two ledgers from blurring | Add D26/D27 to the diff-scope ledger — appends issue-32 decisions to issue-21's record and makes "per D26" ambiguous across two tables; add nothing anywhere and just edit prose — loses the trail entirely |
| D4 | Item 3 **preserves** the `224954b3` snapshot verbatim and appends a `## Post-merge reading (the figure that shipped)` section carrying the merged-head run (76/3, 3 artifact), the two intervening commits that explain the delta, the shared merge-base, and the unchanged verdict; only the one sentence that reads as a claim about what shipped is re-scoped to the snapshot | The file is *evidence* — a recorded observation at a named commit, with a stated `Re-run this command fresh at ship time` caveat. Overwriting the integers would falsify a real measurement and destroy the record of what was true when the branch was reviewed, against the same no-silent-rewrite convention as D2. The addendum satisfies both halves of the issue's acceptance criterion at once (the figure matches the merged tip **and** the measurement commit is named) and discharges the document's own caveat: the addendum *is* the fresh run at the branch's final commit | Overwrite 64→76 and 2→3 in place — falsifies a recorded observation and leaves the `224954b3` annotation attached to numbers never produced there; annotate only ("measured one commit early") — the doc still never states what shipped, and the issue's "figure matches the merged tip" branch stays unmet |
| D5 | Item 4's rewritten line **drops the word `numstat` entirely** rather than keeping it in a contrasting clause, and echoes ship-issue's own "measure, never hand-count" | The suite's existing precedent splits exactly this way: the ship-issue *skill section* is pinned `assertNotIn("--numstat")` while the *eval's* expected output carries the contrasting "rather than hand-counted numstat arithmetic" phrasing. `investigate.md` is a skill document, so it takes the skill-side treatment. It also makes the new pin a clean `assertNotIn("numstat", …)` with no escape hatch | Keep "never a hand-counted `git diff --numstat`" — the contrast is mildly informative but forces the pin to become a fragile whole-clause negative-context match, and leaves the retired tool's name in an instruction an agent reads every Phase 0 |
| D6 | Item 4 **does** get a contract-test pin in `test_workflow_skill_contracts.py` — a single new method with a fail-at-base `assertNotIn("numstat")`, whole-clause affirmative pins for the delegation, both directions of the carve-out, the estimate/count split, and `assertNotIn` guards on the thresholds | Load-bearing skill-doc wording is pinned in this suite by established precedent (it already pins ship-issue's whole `diff-scope` invocation, its two boundary strings, and the historical-artifact clause). This issue exists because doc/tool drift went unnoticed; leaving the fixed line unpinned reproduces the exact failure mode one file over. It is also the only item with a genuine automated seam available, and without it item 4's acceptance criterion is verified only by re-reading the file that was just edited | No pin, verify by reading — cheapest, but the drift recurs silently and the AC is unfalsifiable; a broader sweep pinning every from-issue phase note — ossifies wording nobody has seen drift, the YAGNI objection |
| D7 | Items 1–3 (the two `.claude/specs/` documents) get **no** automated seam; verification is reading, per the issue's own demo | No suite reads `.claude/specs/**`, and building one for three sentences invents a convention for itself — D16 of the diff-scope spec and the degradation-gate spec's "No ADR, no context-map area" both settled this shape of question the same way. A spec-prose linter would additionally have to encode which historical sentence is still true, which is the human judgement being exercised | Add a spec-linting suite — new harness, new convention, and it cannot express the actual invariant; assert the evidence figures from a test that shells out to git — pins a historical measurement to network-free repo state and breaks on any future rewrite of that range |
| D8 | Specs are amended inline; skill docs are rewritten in place with no marker (items 1–3 carry markers/addenda, item 4 does not) | A spec is a durable record whose value is that a reader can see what was decided and when — hence D19/D25's inline form. `investigate.md` is an operating instruction loaded into an agent's context every Phase 0; an "originally read" clause there is dead weight the agent must read past on every run, and git history already carries the provenance | Mark item 4 too, for uniformity — pays context cost on every from-issue run for provenance no executor needs; drop the markers everywhere for brevity — silently rewrites the record, the thing D19/D25 exists to prevent |
| D9 | Cross-spec amendment markers lead with the amending **issue and spec name** before the row ID (`**amended by issue 32's alignment spec, D2**`); same-spec markers keep D19/D25's bare `**amended by Dnn**` form | Grill pass, verified: the diff-scope spec's ledger already holds its own D2 (the row that removed the stdin seam), so a bare "amended by D2" written into that document resolves to the wrong row on a skim — the precise failure that the "qualify cross-ledger citations" rule exists to prevent, and it would land in the very document this issue is fixing for ambiguity | Bare `**amended by D2**` — points a reader of the diff-scope spec at that spec's own D2; cite the amending spec by bare file path only — accurate but forces a file-open to learn which decision applies, where the issue number alone is resolvable from the tracker |
