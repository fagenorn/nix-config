# Scoped Codex Dispatch (Layer 2) Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Before dispatching `diff-review`, the caller measures the range with the shared
`diff-scope` helper; over 20 product files it dispatches a bounded, deterministic subset and
discloses that bound in the packet, in the axis verdict, and in both calling controllers'
provenance.

**Architecture:** Everything in this change is executable prose — the skill files an agent reads
as its contract — plus two test files that pin that prose. `DIFF-REVIEW.md` owns the size
pre-flight, the scoped packet, the scoped verdict format, and the degrade path;
`codex-collaboration/SKILL.md` is narrowed so its shared pre-flight sentence no longer claims to
be the only one; `sdd/correctness-reviewer-prompt.md` gains two packet-conditional clauses — a
coverage clause in `## Output Format` and a scoped-fetch clause in `## Diff Under Review`;
`sdd/final-review.md` and ship-issue's `REVIEW.md` + `SKILL.md` record the returned scope. A scoped
packet also *drops* the full-range diff-package path from item 4 and leaves `[DIFF_FILE]`
unsupplied, so the reviewer's input is bounded and not merely its grading (D16); the shared
`sdd/scripts/review-package` is not touched, so the conformance axis keeps its full input. No
`.nix`, `lib/`, or `patches/` file changes, and no `patchRevision` bump.

**Tech stack:** Markdown skill contracts under `home/common/`; Python 3 `unittest` contract tests
run by `just agent-workflow-tests`; the `codex-collaboration` plan-only eval suite
(`just evals`); Nix / home-manager as the deployment layer (`just build`).

**Spec:** `.claude/specs/2026-08-16-issue-23-scoped-codex-dispatch-design.md` — binding. Its
`## Decision ledger` is the single ledger for this issue; rows are cited here by ID.

**Base commit:** `fc498cb` (`origin/main`). Every "fails at base" claim below was checked at
`e0e3697`, the spec commit on this branch, where both test modules are green.

## Global Constraints

- Budget is **20 product files**, and the comparison is strict: `changed_files > 20` scopes,
  `changed_files == 20` does not. A range measuring zero product files is under budget.
- The scope is exactly one of three fixed values, spelled identically everywhere, always with
  pipe separators: `full` | `scoped: <N> of <M> product files` | `unmeasured`.
- Exactly three JSON fields are read from the helper: `product.changed_files`, `files[].path`,
  `files[].changed_lines`. `product.changed_lines` and `excluded` are never read (per D3's
  boundary against the degradation gate — issue #22 owns that gate).
- The subset is `files[]` verbatim — first 20 entries, no filtering, no re-ranking, binary rows
  included (per D2).
- The packet never embeds per-file diffs. It stays a paths packet.
- An unscoped packet is **exactly** the six numbered items that exist today; item 7 exists only
  when scoped (per D7). A scoped packet differs in exactly three places, not two (per D16): item 2,
  item 4 (the diff-package path is dropped, the plan path stays, and item 3 correspondingly leaves
  `[DIFF_FILE]` unsupplied), and the added item 7.
- Item 7 is a **collection instruction**, not only a disclosure: it directs the reviewer to fetch
  `git diff <base>..<head> -- <path>` for exactly the listed paths and to treat that set as the
  whole of the range under review (per D16).
- `home/common/agent-skills/skills/sdd/scripts/review-package` is **not modified** by any task, and
  neither is the package it produces: both axes share it and the conformance axis must keep full
  input. Layer 2 changes only what the correctness packet points at.
- The coverage disclosure opens the verdict's em-dash assessment clause and never sits between
  the verdict word and the dash (per D6).
- Codex failure classes stay a closed list of three. An oversized diff is not one, adds no
  fourth, never spends the one-time native fallback, and never triggers a retry (per D5).
- The helper is invoked by bare name `diff-scope`, with `~/.agents/bin/diff-scope` named as the
  anchored fallback — the phrasing every other `~/.agents/bin` helper contract uses.
- No `.nix` file, nothing under `lib/` or `patches/`, no `patchRevision` bump.
- Commits carry `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Never disable GPG
  signing (no `-c commit.gpgsign=false`, no `--no-gpg-sign`); surface signing failures instead.
  `%G?` reporting `N` in this repo is a local `allowedSignersFile` gap, not a signing failure.

## Test seams

Existing seams only; no new harness and no new test file.

- **`python3 -m unittest -v -k <name> home/common/agent-skills/tests/test_workflow_skill_contracts.py`**
  — the per-task gate. `-k` with a file path works and exits non-zero with `NO TESTS RAN` when
  the pattern matches nothing, so a missing test method fails the gate.
- **`python3 -m unittest -v home/common/agent-skills/tests/test_agent_evidence.py`** — the live
  `agent-evidence.py` validator, exercised through its CLI seam over the JSON fixtures.
- **`just agent-workflow-tests`** — the whole suite; run at the end of every task.
- **`just evals codex-collaboration <id>`** — **not a grader.** For `mode: plan-only`,
  `run-eval.sh` prints the prompt and the expected output, appends a `PRINTED` line to
  `results/results.jsonl`, and exits 0; it exits 2 (`no eval with id N`) when the id is absent.
  Exit 0 therefore means *the eval exists, is well-formed, and renders* — never *the eval passes*.
  The grade is a human reading a rendered transcript against `expected_output` (per D17); its
  owner and its record are the final step of this plan.
- **`just build`** — the Nix/home-manager integration gate. Slow. Runs once, in Task 4 only.

Deliberately not a seam: a live end-to-end Codex review (non-deterministic, ~15 min, and a
passing live run does not generalise across diff sizes).

## Task index

- **Task 1 — Size pre-flight, scoped packet, and scoped verdict in the `diff-review` contract** —
  `home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md`,
  `home/common/claude-code/skills/codex-collaboration/SKILL.md`,
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py`,
  `home/common/agent-skills/tests/test_agent_evidence.py` — **full**
- **Task 2 — Packet-conditional coverage and collection clauses in the correctness rubric** —
  `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`,
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — **full**
- **Task 3 — Both calling controllers record the scope** —
  `home/common/agent-skills/skills/sdd/final-review.md`,
  `home/common/agent-skills/skills/ship-issue/REVIEW.md`,
  `home/common/agent-skills/skills/ship-issue/SKILL.md`,
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — **full**
- **Task 4 — Eval coverage for the over-budget contract** —
  `home/common/claude-code/skills/codex-collaboration/evals/evals.json` — **low-risk**
- **Final step (not a task) — manually grade eval 3 and record the grade** — no file in
  `home/`; appends to this plan's `## Execution log`. Owner: the controller executing this plan.

Tasks 1–3 are **full** lane: each changes a dispatch contract, a reviewer input or output
contract, or a controller's provenance obligation. Task 2 is full lane for both reasons after
D16 — its `## Diff Under Review` clause changes what the reviewer is told to *collect*, not only
how it reports. Task 4 touches only a graded test asset — no shipped contract — so it is
**low-risk**; it carries the one `just build` integration gate. The final step ships no code and
is not dispatched to an implementer.

## Decisions

The spec owns the ledger. Tasks cite rows by ID (D1–D17). Planning appended D14 and D15, both
about where the prose is pinned mechanically; the Phase-5 standards review appended D16 (a scoped
packet bounds input, not only grading — narrows D7) and D17 (`plan-only` evals are manually
graded, and the grade needs a named owner). Nothing else in this plan required a new decision.

## Standards review provenance (Phase 5)

- **Reviewer:** Codex, through `codex-collaboration`'s `plan-review` (isolated read-only runtime).
  Job id `reviewer-mswdesml-gezw7j`. **No fallback consumed** — the review returned a valid result
  on its first dispatch, so the one-time native fallback was not used and Codex was not retried.
- **Base SHA reviewed:** `fc498cb` (`origin/main`), against the spec and plan as committed on this
  branch. Focus: none configured; standard review bar.
- **Dispositions:** 5 findings, **5 applied, 0 rejected, 0 deferred** — 3 blocking, 2 should-fix.
  No raw reviewer transcript is stored in the repo.

| Finding | Disposition |
|---|---|
| **B-01** — scoping bounded grading but not input: the scoped packet still carried item 4's full-range review package, and the rubric still told the reviewer to fetch the whole range | **Applied.** New ledger row **D16** (narrows D7): a scoped packet drops the diff-package path from item 4, leaves `[DIFF_FILE]` unsupplied, and makes item 7 a bounded per-file collection instruction; the rubric's "no diff file was supplied" branch gains the matching packet-conditional clause. Task 1 Step 4 and Task 2 Step 3 rewritten; their contract-test assertions extended. `sdd/scripts/review-package` is explicitly out of scope, so the conformance axis keeps full input. |
| **B-02** — Task 3's sdd provenance sentence was unconditional, but `final-review.md`'s capability-fallback path dispatches the native reviewer directly and returns no scope | **Applied.** Task 3 Step 3's sentence is now conditioned on the axis having come through `diff-review`, matching ship-issue's wording in Step 4; the native path records reviewer identity as today and no scope. Neither `full` nor `unmeasured` is stretched to cover it. Invariants and the contract-test assertion updated. |
| **B-03** — acceptance criterion 9 ("the eval suite asserts … and passes") had no owner: `run-eval.sh` records `PRINTED` and exits 0 for `mode: plan-only` | **Applied.** New ledger row **D17**. The plan now states plainly that plan-only evals are manually graded, that `just evals` verifies existence/well-formedness/rendering only, and that the automated pin is `test_workflow_skill_contracts.py`. A final plan step, owned by the plan's controller, runs and hand-grades eval 3 and records the verdict in `## Execution log` and the PR body. |
| **S-01** — Task 1's test pinned "no filtering, no re-ranking" but neither the subset cardinality nor the churn-descending order, so criteria 3 and 4 had no automated pin | **Applied.** Task 1 Step 1 gains four fragments: "taken as the first 20 entries in the emitted order", "ranks churn descending with a raw-path-bytes tie-break", "the same range always yields the same 20 paths", and "selected as the highest-churn files". |
| **S-02** — Task 4's two `grep -q` guards for eval 2 were vacuous: most of eval 2 could be rewritten with both still green | **Applied.** Step 4 now compares eval 2's **full** base `expected_output` (`git show fc498cb:<path> \| jq -r`) against the post-edit value minus the one inserted sentence, asserting byte equality and a single verbatim occurrence. |

---

### Task 1: Size pre-flight, scoped packet, and scoped verdict in the `diff-review` contract

**Files:**
- Modify: `home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md`
- Modify: `home/common/claude-code/skills/codex-collaboration/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Test: `home/common/agent-skills/tests/test_agent_evidence.py`

**Interfaces:**
- Consumes: the deployed helper `~/.agents/bin/diff-scope` (source
  `home/common/agent-skills/scripts/diff-scope.py`, wired to `~/.agents/bin` by
  `home/common/agent-skills/default.nix`; issue #21, already on `origin/main`). Its `--format
  json` payload has exactly these keys: `range`, `product.changed_lines`,
  `product.changed_files`, `files[].path`, `files[].changed_lines`, `files[].binary`,
  `excluded.{lockfile,generated,artifact}`. Its flags are `<range>`, `--root`,
  `--artifact-path` (repeatable, repository-relative, rejects absolute values), `--format`.
  Do not invent any other field or flag.
- Produces: the **scope** value returned by `diff-review`'s disposition — exactly one of
  `full`, `scoped: <N> of <M> product files`, `unmeasured`. Task 3's controller sentences quote
  those three spellings verbatim; Task 2's rubric clause quotes `scoped to <N> of <M> product
  files;`. Also produces the section headings `## Size pre-flight` and
  `### When the range is over budget` in `DIFF-REVIEW.md`, which Task 1's own test anchors on, and
  the scoped packet's collection instruction (item 7's listed paths as the whole of the range),
  which Task 2 mirrors in the rubric's "no diff file was supplied" branch.

**Invariants:**
- The capability pre-flight (`command -v codex-companion`, owned by `SKILL.md`) always runs
  before the size pre-flight; no path measures a range it will never dispatch (per D12).
- Under budget, unmeasured, or measured at exactly 20 files, the dispatched packet is
  byte-identical in structure to today's: six numbered items including item 4's diff-package path,
  no coverage sentence, no item 7, today's verdict format (acceptance criterion 2).
- Over budget the packet differs in exactly three places — item 2, item 4 (diff-package path
  dropped, plan path kept, `[DIFF_FILE]` left unsupplied on item 3's rubric), and the added item 7,
  which is a bounded per-file collection instruction (per D16). No task regenerates a smaller diff
  package, and `sdd/scripts/review-package` is not edited.
- The three scope spellings appear identically in `DIFF-REVIEW.md` and in Task 3's controllers.
- No sentence in either file converts a measurement problem into a Codex failure, a fallback, or
  a retry (per D5).
- The scoped verdict's first line satisfies
  `\*\*Correctness:\*\* (?:Clean(?:\s+[—-]\s+.+)?|Findings\s+[—-]\s+.+)` under `re.fullmatch` —
  the live check in `home/common/agent-skills/scripts/agent-evidence.py` (per D6).

- [ ] **Step 1: Write the failing contract test**

Add these module constants beside the existing ones at the top of
`home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

```python
DIFF_REVIEW = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md"
)
```

and in `setUpClass`, beside `cls.collaboration`:

```python
cls.diff_review = DIFF_REVIEW.read_text(encoding="utf-8")
```

Then add this test method to `WorkflowSkillContractsTest`:

```python
    def test_diff_review_scopes_oversized_ranges_and_discloses_coverage(self):
        # Whitespace-normalized: these are wrapped prose contracts, so line
        # breaks must not be part of what is pinned. The blockquote markers go
        # first — without that, a naive split() leaves a stray ">" inside the
        # coverage sentence and no fragment spanning its line wrap can match.
        contract = " ".join(self.diff_review.replace("\n> ", "\n").split())
        for fragment in (
            "resolve policy, capability pre-flight, packet by paths",
            "the size pre-flight below",
            "`~/.agents/bin/diff-scope`",
            "--artifact-path <specDir> --artifact-path <planDir>",
            "--format json",
            "`.claude/specs` and `.claude/plans`",
            "`product.changed_files`",
            "`files[].path`",
            "`files[].changed_lines`",
            "`product.changed_lines` and `excluded` are deliberately not read",
            "`changed_files > 20` scopes the packet, `changed_files == 20` does not",
            "no filtering, no re-ranking",
            # Cardinality and selection order — acceptance criteria 3 and 4 rest
            # on these two, and "no filtering, no re-ranking" pins neither.
            "taken as the first 20 entries in the emitted order",
            "ranks churn descending with a raw-path-bytes tie-break",
            "the same range always yields the same 20 paths",
            "selected as the highest-churn files",
            "yields no measurement — never a failure",
            "adds no fourth failure class",
            "never spends the one-time native fallback and never triggers a retry",
            "receives the same packet, item 7 and coverage sentence intact",
            "`full` | `scoped: <N> of <M> product files` | `unmeasured`",
            "This is a scoped review:",
            "do not treat their absence from the list as evidence they are clean",
            # The bound is on input, not only on grading (D16): item 4's
            # full-range package leaves a scoped packet, and item 7 is the
            # collection instruction that replaces it.
            "Under budget — or unmeasured — the packet is exactly the six items above",
            "Over budget it differs in exactly three places and nowhere else",
            "Item 4 drops the diff-package path",
            "`[DIFF_FILE]` has no value on a scoped dispatch",
            "do not change `scripts/review-package`: the conformance axis reads that "
            "same package whole",
            "Item 7 exists only when scoped",
            "one bounded read per listed path",
            "treat that set as the whole of the range under review",
            "one focused check per named risk",
            "it never embeds per-file diffs",
            "scoped to <N> of <M> product files;",
            "A scoped review may not use the bare",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, contract)

        # The capability check is named as running first, and the size
        # pre-flight is defined before the packet it changes.
        self.assertIn(
            "capability pre-flight and runs first", contract
        )
        self.assert_ordered(
            contract,
            "## Size pre-flight",
            "## Packet",
            "### When the range is over budget",
            "## Reviewer output contract",
            "## Disposition",
        )
        # The header no longer claims the shared file owns *the* pre-flight.
        self.assertNotIn("resolve policy, pre-flight, packet by paths", contract)

        # SKILL.md is narrowed in the same breath, or the two contracts
        # contradict each other (D12).
        self.assertIn(
            "Capability pre-flight first, one sub-second call", self.collaboration
        )
        self.assertNotIn(
            "Pre-flight first, one sub-second call", self.collaboration
        )
        self.assertIn("skip the capability pre-flight", self.collaboration)
        self.assertIn(
            "an additional pre-flight of its own in its reference file",
            self.collaboration,
        )
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest -v -k diff_review_scopes home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL. At the base commit `DIFF-REVIEW.md` contains no `## Size pre-flight` heading and
no occurrence of `diff-scope`, and `SKILL.md` still reads `Pre-flight first, one sub-second
call` — so the first `subTest` fragment already fails and `assertNotIn` on the SKILL.md sentence
fails too.

- [ ] **Step 3: Narrow the `DIFF-REVIEW.md` header and add the size pre-flight**

Replace the opening paragraph of `DIFF-REVIEW.md` (currently ending `The axis is never
skipped.`) with this text — one word narrowed, one sentence added:

~~~markdown
Read this when running `diff-review` — the correctness axis of the two-axis diff
review (the sdd skill defines the axes and owns dispatching the parallel native
conformance axis — that axis never comes through this skill). SKILL.md owns the
shared runtime contract: resolve policy, capability pre-flight, packet by paths,
`WORKTREE_ROOT:` first line, one foreground `codex:codex-reviewer` dispatch,
validation, one-time native `reviewer` fallback on a real Codex failure, never a
retry, concurrency never a fallback reason. The axis is never skipped. This
operation adds one pre-flight of its own — the size pre-flight below — which runs
after that capability check.
~~~

Then insert a new `## Size pre-flight` section between that paragraph and `## Packet`:

~~~markdown
## Size pre-flight

SKILL.md's `command -v codex-companion` check is the capability pre-flight and runs
first; this size pre-flight runs after it, never before. A missing capability takes
the native flow and never dispatches, so measuring first would be wasted work, and
the native path is unscoped by construction. The separate capability fallback — this
skill or the bridge agent unavailable, so the controller dispatches the native
correctness reviewer itself — never reaches this pre-flight and is never scoped.

Measure the range in product terms before building the packet. Run it from the
worktree root (the helper is `~/.agents/bin/diff-scope`; use the full path if the
bare name does not resolve on PATH):

```
diff-scope <base-sha>..<head-sha> \
  --root <absolute worktree root> \
  --artifact-path <specDir> --artifact-path <planDir> \
  --format json
```

`<specDir>` and `<planDir>` are the caller's already-resolved bindings, passed
repository-relative. A dispatcher that has none passes the documented defaults
`.claude/specs` and `.claude/plans` rather than omitting the flags, so the run's own
spec and plan never consume review budget.

Read exactly three fields from the JSON:

- `product.changed_files` — the budget comparison, and `M` in every disclosure.
- `files[].path` — the subset, taken as the first 20 entries in the emitted order.
- `files[].changed_lines` — the per-file churn printed beside each path in item 7.

`product.changed_lines` and `excluded` are deliberately not read here: they are the
degradation gate's thresholds, not this pre-flight's, and must not be wired into the
scoping decision.

The budget is 20 product files and the comparison is strict — `changed_files > 20`
scopes the packet, `changed_files == 20` does not. A range measuring zero product
files is under budget and dispatches whole.

Take the subset from `files[]` verbatim: no filtering, no re-ranking. The helper
already ranks churn descending with a raw-path-bytes tie-break, a total order, so the
same range always yields the same 20 paths. Binary rows carry a churn of zero and
sort after every text row, so one enters the subset only once every text product file
is already in it.

**No measurement.** A helper that is absent, exits non-zero, or emits output this
operation cannot parse yields no measurement — never a failure. Dispatch exactly as
an under-budget range does, six items and today's verdict format, and report
`unmeasured` to the calling controller. `diff-scope` reaches `~/.agents/bin` only
after a rebuild, so absence is a real state on a machine that has this skill.

An oversized diff is not a Codex failure and scoping adds no fourth failure class —
SKILL.md's closed list of three stands unchanged. Scoping never spends the one-time
native fallback and never triggers a retry. When Codex does fail on a scoped
dispatch, that one-time native fallback receives the same packet, item 7 and coverage
sentence intact.

The value this operation hands the calling controller is the **scope**, exactly one
of: `full` | `scoped: <N> of <M> product files` | `unmeasured`.
~~~

Grounding: the pre-flight ordering and both narrowings are D12; the flags and the binding
fallback are D3; the verbatim `files[]` subset including binary rows is D2; the no-measurement
degrade and the failure-class rule are D5; the fallback inheriting the scoped packet is D8.

- [ ] **Step 4: Make item 4 conditional and add the over-budget packet variant**

Two edits inside `## Packet`, and nothing else in that section.

First, item 4 gains a pointer to its conditional half. Replace the numbered item 4:

~~~markdown
4. The diff-package path when the caller built one, and the plan path (routing
   context for what the tasks were). The diff-package path is dropped when the
   range is scoped — see *When the range is over budget*.
~~~

Leave items 1–3, 5 and 6 and the `Nothing else rides along` paragraph exactly as they are. Then
append this subsection to the end of `## Packet`:

~~~markdown
### When the range is over budget

Under budget — or unmeasured — the packet is exactly the six items above. Over budget
it differs in exactly three places and nowhere else.

**Item 2 changes subject and gains a coverage sentence.** It becomes: review the
listed product files in the worktree, as changed across `<base-sha>..<head-sha>`, for
the same correctness subject matter, with the same instruction not to grade
conformance. Then, in substance:

> This is a scoped review: `<N>` of `<M>` changed product files, selected as the
> highest-churn files. Files outside the list are not under review in this pass — do
> not report on them, and do not treat their absence from the list as evidence they
> are clean.

Scoping bounds what is supplied and what is graded, not what may be consulted. The
rubric's carve-out for inspecting code outside the diff to evaluate a concrete named
risk stands untouched — one focused check per named risk — so a cross-file finding
that reaches into an unlisted file is legal and reportable. Silently grading an
unlisted file, or implying it was covered, is not.

**Item 4 drops the diff-package path.** That package is sdd's `scripts/review-package`
output: an unconditional full-range `git diff -U10 <base>..<head>`, which the rubric
tells the reviewer to read once. Carrying it in a scoped packet would hand over the
entire range this packet just bounded, so a scoped item 4 carries the plan path alone
— routing context is not a diff. Item 3 travels as always, with one placeholder
unsupplied: `[DIFF_FILE]` has no value on a scoped dispatch, which is exactly what
routes the reviewer into the rubric's "no diff file was supplied" branch. Do not
regenerate a smaller package and do not change `scripts/review-package`: the
conformance axis reads that same package whole.

**Item 7 exists only when scoped**, and it is the reviewer's collection instruction,
not only a disclosure: the selected paths, worktree-root-relative, one per line, in
the helper's emitted order, each with its `files[].changed_lines` count. Direct the
reviewer to collect the diff for exactly those paths, one bounded read per listed
path (`git diff <base>..<head> -- <path>`), and to treat that set as the whole of the
range under review. An unscoped packet has no item 7.

The packet stays a paths packet either way: it never embeds per-file diffs.
~~~

Grounding: item 2 keeps its name and meaning and item 7 is conditional per D7; item 4's
conditionality, the unsupplied `[DIFF_FILE]`, and item 7 as a collection instruction are D16,
which narrows D7's "exactly two places" to three; the consult-vs-grade boundary is D13; the
paths-only rule is D2. Task 2 writes the matching branch into the rubric — without it this item 7
is advisory and the reviewer still fetches the whole range.

- [ ] **Step 5: Add the scoped verdict format and the scope return**

Append to `## Reviewer output contract`, after the existing paragraph:

~~~markdown
When the packet is scoped, the coverage opens that first line's assessment clause,
after the em dash — never between the verdict word and the dash:

```
**Correctness:** Clean — scoped to <N> of <M> product files; <1–2 sentence assessment>.
**Correctness:** Findings — scoped to <N> of <M> product files; <1–2 sentence assessment>.
```

`agent-evidence.py` `re.fullmatch`es this line, so the position is a contract rather
than a style: `**Correctness:** Clean (scoped: 20 of 44) — …` fails validation. A
scoped review may not use the bare `**Correctness:** Clean` form, because that form
has nowhere to put the coverage. An unscoped or unmeasured review keeps today's
format exactly, bare form included.
~~~

Replace the `## Disposition` paragraph with:

~~~markdown
Verify-and-disposition stays with the calling controller and its own fix-flow rules:
return the validated three-section result (or the fallback reviewer's) unmodified,
plus the reviewer identity (`Codex` | `Claude fallback` + failure class) and the scope
(`full` | `scoped: <N> of <M> product files` | `unmeasured`) for the caller's ledger.
That return is the single hand-off point — the controller records what it is given and
never re-derives the measurement.
~~~

Grounding: verdict position is D6; the scope riding beside the reviewer identity as the single
hand-off point is D1. The reviewer-identity spelling stays `Codex | Claude fallback` here — the
spec's out-of-scope list forbids reconciling it with sdd's `Codex | native | fallback`.

- [ ] **Step 6: Narrow `codex-collaboration/SKILL.md`**

Three edits in the `## Launch` section, and nothing else in the file:

1. `Pre-flight first, one sub-second call: `command -v codex-companion`.` →
   `Capability pre-flight first, one sub-second call: `command -v codex-companion`.`
2. Append to that same paragraph, after `Never convert a missing runtime into a timed-out Codex
   attempt.`:
   `An operation may define an additional pre-flight of its own in its reference file —
   `diff-review` defines a size pre-flight in DIFF-REVIEW.md — and that one always runs after
   this capability check.`
3. In the next paragraph, `is not a reason to skip the pre-flight or go straight to native` →
   `is not a reason to skip the capability pre-flight or go straight to native`.

Failure classes, the fallback rule, the no-retry rule, the transport dispatch, and the
`agent-dispatch` comments are untouched.

When wrapping these sentences, keep each asserted fragment on a single line: Step 1's `DIFF-REVIEW.md`
assertions run against whitespace-normalized text, but its `SKILL.md` assertions run against the raw
file, so a line break inside `an additional pre-flight of its own in its reference file` would fail
the gate for a formatting reason rather than a contract one.

- [ ] **Step 7: Run the contract test and watch it pass**

Run: `python3 -m unittest -v -k diff_review_scopes home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: PASS, 1 test, no warnings.

- [ ] **Step 8: Lock the verdict regex against future edits**

Add this test method to `AgentEvidenceTest` in
`home/common/agent-skills/tests/test_agent_evidence.py`:

```python
    def test_scoped_correctness_verdict_passes_and_misplaced_scope_does_not(self):
        # DIFF-REVIEW.md puts the coverage inside the em-dash assessment clause
        # because this validator fullmatches the first line (D6). Both halves
        # already hold at the base commit; this is a regression lock, so a later
        # edit to the verdict regex cannot break the disclosure silently.
        original = self.fixture("bridge-fresh-end-to-end.json")
        sections = "\n\n## Critical\nNone.\n\n## Important\nNone.\n\n## Minor\nNone."

        accepted = deepcopy(original)
        accepted["operations"][1]["agent_mediated"]["result"] = (
            "**Correctness:** Clean — scoped to 20 of 44 product files; "
            "no defects in the reviewed subset." + sections
        )
        completed = self.run_document("bridge", accepted)
        self.assertEqual(completed.returncode, 0, completed.stderr)

        rejected = deepcopy(original)
        rejected["operations"][1]["agent_mediated"]["result"] = (
            "**Correctness:** Clean (scoped: 20 of 44) — "
            "no defects in the reviewed subset." + sections
        )
        self.assert_diagnostic(
            self.run_document("bridge", rejected), "BRIDGE_MEDIATED_RESULT_INVALID"
        )
```

`deepcopy`, `self.fixture`, `self.run_document` and `self.assert_diagnostic` already exist in
that module; `operations[1]` is the `diff-review` operation in that fixture. Per D15 this test
is green at the base commit by construction — it is a lock, not this task's failing gate.

- [ ] **Step 9: Verify**

Run: `python3 -m unittest -v -k diff_review_scopes home/common/agent-skills/tests/test_workflow_skill_contracts.py && python3 -m unittest -v -k scoped_correctness_verdict home/common/agent-skills/tests/test_agent_evidence.py && just agent-workflow-tests`

Expected: the two `-k` runs each report `Ran 1 test … OK`; `just agent-workflow-tests` reports
`OK` with two more tests than the base commit's count. Any `NO TESTS RAN` line means a test
method name does not match its gate and the task is incomplete.

- [ ] **Step 10: Commit**

```bash
git add home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md \
        home/common/claude-code/skills/codex-collaboration/SKILL.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py \
        home/common/agent-skills/tests/test_agent_evidence.py
git commit -m "feat(issue-23): scope oversized diff-review dispatches and disclose the coverage"
```

---

### Task 2: Packet-conditional coverage and collection clauses in the correctness rubric

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the scoped verdict format Task 1 wrote into `DIFF-REVIEW.md` —
  `**Correctness:** Clean — scoped to <N> of <M> product files; <1–2 sentence assessment>.`
  The output clause added here must quote the same token, `scoped to <N> of <M> product files;`.
  Also consumes Task 1's scoped packet shape: item 7 lists the paths under review and item 4 no
  longer carries a diff-package path, so `[DIFF_FILE]` is unsupplied on a scoped dispatch and the
  reviewer lands in this file's "no diff file was supplied" branch (per D16).
- Produces: nothing other tasks consume. This file is carried into the Codex packet by absolute
  path (`DIFF-REVIEW.md` item 3) and is also the native correctness reviewer's own prompt.

**Invariants:**
- **Two clauses, both conditional on what the packet says**, never on who is reading (per D11):
  a coverage clause in `## Output Format`, and a scoped-fetch clause in the `## Diff Under Review`
  paragraph's "no diff file was supplied" branch. Without the second, a scoped packet still meets
  a rubric that says `git diff base..head` the whole range, and the bound is advisory only.
- The body stays reviewer-agnostic: neither `## Diff Under Review` nor anything after
  `## Output Format` may name Codex, Claude, or any model.
- The named-risk carve-out (`Inspect code outside the diff only to evaluate a concrete risk you
  can name … one focused check per named risk, named in your report.`) survives **verbatim as
  text** (per D13). Inserting the scoped clause ahead of it re-wraps the paragraph, so its line
  breaks may move; not one word of it may change.
- The unconditional branch is preserved: an unscoped dispatch still reads the supplied diff file
  once, or fetches the whole range when none was supplied. Nothing here is made unconditional.
- On the native path no packet ever states a scope, so both clauses are inert there.
- `sdd/scripts/review-package` is not touched, and no placeholder is added to the
  `**Placeholders:**` list — `[DIFF_FILE]` being unsupplied is a state that list already covers.

- [ ] **Step 1: Write the failing test**

Add this test method to `WorkflowSkillContractsTest` in
`home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

```python
    def test_correctness_rubric_discloses_scope_only_when_the_packet_says_so(self):
        rubric = (SDD_DIR / "correctness-reviewer-prompt.md").read_text(
            encoding="utf-8"
        )
        # Stop at the Placeholders paragraph: it sits outside the fenced prompt
        # and legitimately names Codex, so including it would make the
        # reviewer-agnostic assertion below unfalsifiable.
        output_format = rubric[
            rubric.index("## Output Format") : rubric.index("**Placeholders:**")
        ]
        # The collection branch sits earlier, in its own section.
        diff_under_review = rubric[
            rubric.index("## Diff Under Review") : rubric.index("## What to Check")
        ]
        for fragment in (
            "When the packet supplied to you states the review is scoped",
            "scoped to <N> of <M> product files;",
            "never between the verdict word and the dash",
            "When the packet says nothing about scoping, write the verdict exactly",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, " ".join(output_format.split()))
        # The scoped packet bounds what is fetched, not only what is graded
        # (D16) — and the unconditional branch survives beside it.
        for fragment in (
            "Read the diff file once",
            "If no diff file was supplied, fetch the range yourself",
            "unless the packet states the review is scoped and lists the paths "
            "under review",
            "those listed paths are the whole of the range to fetch",
            "`git diff [MERGE_BASE_SHA]..[HEAD_SHA] -- <path>` once per listed path "
            "and fetch nothing wider",
            # The named-risk carve-out survives scoping untouched (D13). Pinned
            # whitespace-normalized: inserting the clause above re-wraps this
            # paragraph, and the wrap is not the contract — the words are.
            "one focused check per named risk, named in your report.",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, " ".join(diff_under_review.split()))
        # Reviewer-agnostic: both clauses key off the packet, not the reader (D11).
        for reader in ("Codex", "Claude", "native"):
            with self.subTest(reader=reader):
                self.assertNotIn(reader, output_format)
                self.assertNotIn(reader, diff_under_review)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest -v -k correctness_rubric_discloses home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL — at the base commit the `## Output Format` section says nothing about scoping,
so the first `subTest` fragment is absent.

- [ ] **Step 3: Add both clauses**

Two edits, both inside the fenced prompt template.

**3a — the output clause.** In the `## Output Format` section, insert immediately after the two
lines that end with `` `**Correctness:** Clean | Findings — 1–2 sentence assessment.` `` and
before `Then exactly three top-level sections`, keeping the template's 4-space indentation:

~~~
    When the packet supplied to you states the review is scoped, that assessment
    clause opens with `scoped to <N> of <M> product files;` — after the em dash,
    never between the verdict word and the dash. When the packet says nothing about
    scoping, write the verdict exactly as above.
~~~

**3b — the collection clause (per D16).** In the `## Diff Under Review` section, replace the
paragraph that currently begins `Read the diff file once;` with this text, re-wrapped as shown so
the two `git diff` code spans each stay on one line. Only the branch clause is new — every other
word, including the named-risk carve-out and the read-only rules, is carried over unchanged:

~~~
    Read the diff file once; when checking a finding, read the live file at HEAD,
    not a snapshot. If no diff file was supplied, fetch the range yourself:
    `git diff --stat [MERGE_BASE_SHA]..[HEAD_SHA]` then
    `git diff [MERGE_BASE_SHA]..[HEAD_SHA]` — unless the packet states the review
    is scoped and lists the paths under review, in which case those listed paths
    are the whole of the range to fetch: run
    `git diff [MERGE_BASE_SHA]..[HEAD_SHA] -- <path>` once per listed path and
    fetch nothing wider. Inspect code outside the diff only to evaluate a concrete
    risk you can name — cross-task contract drift, changed lock ordering, shared
    mutable state — one focused check per named risk, named in your report. Your
    review is read-only on this checkout: do not mutate the working tree, the
    index, HEAD, or branch state in any way. Do not re-run the full test suite —
    the implementers' reported runs are the evidence; run at most one focused test
    to resolve a specific doubt reading the code raised.
~~~

The clause hangs off the "no diff file was supplied" branch on purpose: Task 1's scoped packet
leaves `[DIFF_FILE]` unsupplied precisely so the reviewer lands here. It is conditional on what
the packet declares, so an unscoped dispatch — and every native dispatch, where no packet declares
anything — reaches the unchanged `git diff [MERGE_BASE_SHA]..[HEAD_SHA]` (per D11).

Change nothing else in the file: not the preamble, not the `agent-dispatch` comment, not the
`## What to Check` list, and not the `**Placeholders:**` list — both clauses are
packet-conditional, so neither introduces a new placeholder, and `[DIFF_FILE]` being unsupplied is
a state that list already contemplates.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v -k correctness_rubric_discloses home/common/agent-skills/tests/test_workflow_skill_contracts.py && just agent-workflow-tests`

Expected: `Ran 1 test … OK`, then the full suite `OK`. If the carve-out assertion fails, a word of
the named-risk sentence was changed while re-wrapping the paragraph — restore its wording verbatim
rather than relaxing the assertion. (The assertion is whitespace-normalized, so a moved line break
alone cannot be the cause.)

Also confirm the shared review package was not touched:

```bash
git diff fc498cb..HEAD --name-only -- home/common/agent-skills/skills/sdd/scripts/
```

Expected: prints nothing. `scripts/review-package` is the conformance axis's input too, and D16
bounds the correctness packet without shrinking it.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-23): bound and disclose a scoped packet in the correctness rubric"
```

---

### Task 3: Both calling controllers record the scope

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/final-review.md`
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the scope value `diff-review` returns per Task 1's `## Disposition` — exactly
  `full` | `scoped: <N> of <M> product files` | `unmeasured`. Both controllers record what they
  are given; neither re-derives the measurement and neither calls `diff-scope` itself.
- Produces: nothing later tasks consume.

**Invariants:**
- sdd records the scope in its ledger as a fourth value beside both verdicts and the correctness
  axis's reviewer identity (per D1). sdd's report contract to its caller is unchanged — the
  coverage already rides inside the correctness verdict's own first line.
- **The sdd sentence is conditional**, worded the same way ship-issue's is: it records a scope only
  when the correctness axis came through `diff-review`. `final-review.md`'s other correctness path
  is the capability fallback, which dispatches the native reviewer directly, never enters
  `diff-review`, never measures, and returns no scope; it keeps recording reviewer identity exactly
  as today and records no scope. Neither `full` nor `unmeasured` may be stretched to cover it —
  `full` would assert an unverified coverage, and `unmeasured` names a `diff-review` pre-flight that
  produced nothing, not a path that runs no pre-flight. An implementer must never have to invent a
  value here.
- ship-issue records the scope in the **PR body**, beside the correctness verdict — the same
  surface REVIEW.md already uses for `merge-delta empty, nothing to review` (per D9).
- ship-issue gains **no** reviewer-identity recording; it has none today and this change does not
  add one (per D9).
- Nothing here changes dispatch selection, so no `agent-dispatch` HTML comment is added, removed,
  or edited in either ship-issue file.
- The two existing spellings of reviewer identity stay as they are: `Codex | native | fallback`
  in sdd's ledger sentence, `Codex | Claude fallback` in the skill's disposition contract. The
  scope uses its own three values in both places, so the spellings need no reconciliation.

- [ ] **Step 1: Write the failing test**

Add these module constants at the top of
`home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

```python
SHIP_ISSUE = REPO_ROOT / "home/common/agent-skills/skills/ship-issue/SKILL.md"
SHIP_ISSUE_REVIEW = REPO_ROOT / "home/common/agent-skills/skills/ship-issue/REVIEW.md"
```

Do **not** add the ship-issue directory to `nested_workflow_documents()` — that generator feeds
unrelated blanket assertions over `from-issue` and `sdd` only, and widening it is out of scope.

Add this test method to `WorkflowSkillContractsTest`:

```python
    def test_calling_controllers_record_the_correctness_scope(self):
        final_review = " ".join(
            (SDD_DIR / "final-review.md").read_text(encoding="utf-8").split()
        )
        ship_review = " ".join(
            SHIP_ISSUE_REVIEW.read_text(encoding="utf-8").split()
        )
        ship_skill = " ".join(SHIP_ISSUE.read_text(encoding="utf-8").split())

        # sdd: the scope is a fourth recorded value beside both verdicts and the
        # correctness axis's reviewer identity (D1) — but only on the diff-review
        # path. The capability fallback dispatches the native reviewer directly
        # and returns no scope, so the sentence must not demand one there.
        self.assertIn(
            "When that axis came through `codex-collaboration`'s `diff-review`, "
            "record the scope it returned as well (`full` | `scoped: <N> of <M> "
            "product files` | `unmeasured`)",
            final_review,
        )
        self.assertIn(
            "the native reviewer dispatched directly returns no scope, so record "
            "none there",
            final_review,
        )
        self.assertIn("Never merge the two reports", final_review)
        self.assertIn("`Codex` | `native` | `fallback` + failure class", final_review)

        # ship-issue: the PR body is the provenance surface, and no reviewer
        # identity is added there (D9).
        self.assertIn(
            "Record that scope in the PR body beside the correctness verdict",
            ship_review,
        )
        self.assertIn(
            "ship-issue records no reviewer identity; this records the scope only.",
            ship_review,
        )
        self.assertIn(
            "the correctness axis's scope is recorded in the PR body per REVIEW.md",
            ship_skill,
        )
        # Dispatch selection is untouched: the Phase 5 dispatch ids stay as they are.
        for dispatch_id in (
            "ship-issue-full-conformance-review",
            "ship-issue-full-correctness-fallback",
            "ship-issue-scoped-fix-rereview",
        ):
            with self.subTest(dispatch_id=dispatch_id):
                self.assertIn(dispatch_id, ship_skill)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest -v -k controllers_record_the_correctness_scope home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL — at the base commit `final-review.md` records only `both verdicts plus the
correctness axis's reviewer identity`, and neither ship-issue file mentions a scope.

- [ ] **Step 3: Record the scope in sdd's ledger sentence**

In `home/common/agent-skills/skills/sdd/final-review.md`, in the paragraph beginning `Point the
conformance dispatch at the ledger's deferred-minor`, replace

> and record both verdicts plus the correctness axis's reviewer identity (`Codex` | `native` |
> `fallback` + failure class) in the ledger.

with

> and record both verdicts plus the correctness axis's reviewer identity (`Codex` | `native` |
> `fallback` + failure class) in the ledger. When that axis came through `codex-collaboration`'s
> `diff-review`, record the scope it returned as well (`full` | `scoped: <N> of <M> product files`
> | `unmeasured`); the native reviewer dispatched directly returns no scope, so record none there.

The base sentence is left intact and the scope arrives as a **conditional** second sentence, worded
the same way ship-issue's is in Step 4. This file's own capability-fallback path — "Unavailable →
use the Opus/high native reviewer" — never enters `diff-review` and never measures, so an
unconditional "record the scope" would force an implementer to invent a fourth value for it.

Nothing else in the file changes — the `Never merge the two reports` rule, the axis definitions,
the `scripts/review-package` invocation, and every `agent-dispatch` comment stay exactly as they
are. In particular, "review the branch on two axes … over that same package" stands: the package is
still built once and still read whole by the conformance axis; a scoped correctness dispatch simply
does not carry its path (per D16).

- [ ] **Step 4: Record the scope in ship-issue's PR body**

In `home/common/agent-skills/skills/ship-issue/REVIEW.md`, append this paragraph to the end of
the `## Full two-axis review — templates` section (immediately before `## Severity mapping (full
path)`):

~~~markdown
When the correctness axis came through `codex-collaboration`'s `diff-review`, it returns
a scope alongside its verdict: `full` | `scoped: <N> of <M> product files` |
`unmeasured`. Record that scope in the PR body beside the correctness verdict — the
same surface a degraded run uses for "merge-delta empty, nothing to review". A scoped
Clean that reaches the PR body without its scope reads as full coverage, which is
exactly what this record prevents. ship-issue records no reviewer identity; this records
the scope only.
~~~

Then in `home/common/agent-skills/skills/ship-issue/SKILL.md`, Phase 5, replace

> Axis reports are never merged.

with

> Axis reports are never merged, and the correctness axis's scope is recorded in the PR body per
> REVIEW.md.

That sentence opens the paragraph beginning `Axis reports are never merged. Apply findings
through REVIEW.md's severity mapping`; leave the rest of that paragraph and every
`agent-dispatch` comment untouched.

- [ ] **Step 5: Verify**

Run: `python3 -m unittest -v -k controllers_record_the_correctness_scope home/common/agent-skills/tests/test_workflow_skill_contracts.py && just agent-workflow-tests`

Expected: `Ran 1 test … OK`, then the full suite `OK`.

Also confirm no dispatch selection moved, over exactly the paths this plan owns:

```bash
git diff fc498cb..HEAD -- \
  home/common/agent-skills/skills/ship-issue/ \
  home/common/agent-skills/skills/sdd/ | grep -c '^[-+].*agent-dispatch'
```

Expected: prints `0` (and `grep -c` exits 1 on a zero count — that non-zero exit *is* the
passing case here, so do not chain this command with `&&`).

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/sdd/final-review.md \
        home/common/agent-skills/skills/ship-issue/REVIEW.md \
        home/common/agent-skills/skills/ship-issue/SKILL.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-23): record the correctness scope in both calling controllers"
```

---

### Task 4: Eval coverage for the over-budget contract

**Files:**
- Modify: `home/common/claude-code/skills/codex-collaboration/evals/evals.json`

**Interfaces:**
- Consumes: every contract Tasks 1–3 wrote — the pre-flight order and invocation, the three scoped
  packet differences (item 2, item 4's dropped diff-package path with `[DIFF_FILE]` unsupplied, and
  item 7 as a collection instruction, per D16), the scoped verdict format, the three scope values,
  the no-measurement degrade, and the fallback-preservation rule. The eval's `expected_output`
  grades exactly those and must not invent a field, flag, or value none of them defines.
- Produces: eval id `3` in this suite. The file's existing `skill_name` and `notes` keys and
  evals 1 and 2 keep their shape; `mode` stays `plan-only` (the sandbox has no `codex-companion`
  runtime, no Codex auth, and no ~15 minutes of external wall clock).

**Invariants:**
- Eval 2 keeps grading the under-budget packet's in/out boundaries **unchanged** — its `IN:`,
  `OUT —`, output-shape, disposition and `Failures:` clauses are edited in no way other than the
  one added permissive clause (acceptance criterion 2, per D4).
- Eval 3 grades the over-budget contract only; it does not restate eval 2's boundaries.
- The file stays valid JSON that `jq` and `run-eval.sh` can read.
- This task's gate proves the eval **exists, is well-formed, and renders**, and that eval 2 was
  extended rather than rewritten. It does not and cannot prove the eval passes: `run-eval.sh`
  records `PRINTED` and exits 0 for `mode: plan-only` (per D17). The grade is the plan's final
  step; the automated pin for the disclosure obligation's substance is Tasks 1–3's contract tests.

- [ ] **Step 1: Write the failing gate**

There is no unittest seam for this file; the gate is the runner plus `jq`. Run it first and watch
it fail:

Run: `just evals codex-collaboration 3`

Expected: FAIL — `run-eval: no eval with id 3 in …/evals.json`, exit status 2.

- [ ] **Step 2: Add the permissive clause to eval 2**

In eval 2's `expected_output`, insert exactly this sentence — **plus the single trailing space that
separates it from what follows** — immediately before the existing `Failures:` sentence, i.e.
between `…the same one-time native fallback and never-retry rules apply. ` and `Failures: reusing
the plan-review packet…`. Change nothing else in the string:

```
Naming the size pre-flight is correct here, not a deviation: measuring the range with `diff-scope` after the capability pre-flight and finding it at or under 20 product files means the packet is dispatched exactly as described above — six items, no coverage sentence, no file list.
```

Step 4 asserts that deleting this exact string (with its trailing space) from the post-edit value
reproduces the base value byte-for-byte, so it must be inserted verbatim and exactly once.

Per D4 this exists so a plan-only grader does not read a correct pre-flight mention as a
deviation from the under-budget contract eval 2 is there to grade. Eval 2 still grades the
**under-budget** packet, where item 4 carries the diff-package path exactly as today — D16 changes
nothing eval 2 asserts.

- [ ] **Step 3: Add eval 3**

Append this object to `.evals`, after eval 2:

```json
{
  "id": 3,
  "name": "diff-review-oversized-range-scoped-packet",
  "mode": "plan-only",
  "prompt": "sdd's final review is dispatching you for the correctness axis: operation diff-review over `aaa1111..bbb2222` in this worktree, a branch that changes 44 product files. **Plan-only: launch nothing.** Tell me: which pre-flights you run and in what order, with the exact command for any helper you call; what this packet contains that an under-budget packet would not, and what it no longer contains; how the reviewer is told to obtain the diff it reviews; what the reviewer's first line must look like; what you hand back to the calling controller; and what you do in each of these situations: (a) `diff-scope` is not installed on this machine; (b) Codex comes back `CODEX_REVIEW_FAILURE: job timed out` on this dispatch.",
  "expected_output": "Pre-flights, in this order: first the shared capability pre-flight `command -v codex-companion`; then diff-review's own size pre-flight, run from the worktree root as `diff-scope <base>..<head> --root <absolute worktree root> --artifact-path <specDir> --artifact-path <planDir> --format json` (helper at `~/.agents/bin/diff-scope`; defaults `.claude/specs` / `.claude/plans` when the dispatcher has no bindings, never omitting the flags). Exactly three fields are read — `product.changed_files`, `files[].path`, `files[].changed_lines`; `product.changed_lines` and `excluded` are deliberately not read, they belong to the degradation gate. 44 > 20, so the packet is scoped to the first 20 entries of `files[]` taken verbatim — no filtering and no re-ranking, the helper's churn-descending, path-tie-broken order is already a total order, so the same range always yields the same 20 paths, and binary rows (churn zero) sort last so they never displace a text file. The scoped packet differs from the six-item packet in exactly three places: item 2 changes subject to the listed product files as changed across the range and gains a coverage sentence in substance — this is a scoped review, 20 of 44 changed product files, selected as the highest-churn files, files outside the list are not under review in this pass, do not report on them and do not treat their absence from the list as evidence they are clean; item 4 DROPS the diff-package path and carries the plan path alone, because that package is `scripts/review-package`'s unconditional full-range `git diff -U10 base..head` and handing it over would leave the entire range to be read — item 3's rubric therefore travels with `[DIFF_FILE]` unsupplied, which is what routes the reviewer into the rubric's 'no diff file was supplied' branch; and a new item 7 lists the 20 paths, worktree-root-relative, one per line, in the helper's order, each with its changed-line count, as a collection instruction: fetch `git diff <base>..<head> -- <path>` once per listed path and treat that set as the whole of the range under review. Nothing else changes; no per-file diffs are embedded, the packet stays a paths packet, and `scripts/review-package` itself is not touched or regenerated — the conformance axis reads that same package whole. Scoping bounds what is supplied and what is graded, not what may be consulted: the rubric's carve-out for one focused check per concrete named risk survives, so a cross-file finding reaching into an unlisted file is legal and reportable. First line: `**Correctness:** Clean — scoped to 20 of 44 product files; <assessment>` or `**Correctness:** Findings — scoped to 20 of 44 product files; <assessment>` — the coverage opens the em-dash assessment clause, never sitting between the verdict word and the dash (agent-evidence.py fullmatches that line), and a scoped review never uses the bare `**Correctness:** Clean` form. Hand-off: the validated three-section result unmodified, plus the reviewer identity and the scope `scoped: 20 of 44 product files`, for the calling controller's ledger — the controller records what it is given and never re-derives the measurement. Case (a): a missing, non-zero-exiting or unparsable helper is no measurement, never a failure — dispatch exactly as today (six items including item 4's diff-package path, today's verdict format) and report `unmeasured`; it never spends the one-time native fallback and never triggers a retry. Case (b): that IS a real Codex failure — exactly one fresh native reviewer gets the SAME scoped packet, item 7 and coverage sentence intact, the failure class is recorded, Codex is not retried. Failures: treating the oversized diff as a Codex failure or spending the one-time fallback on it; leaving the full-range diff-package path in item 4, or supplying `[DIFF_FILE]`, on a scoped dispatch — the reviewer is then handed the whole range and only the grading was bounded; regenerating a pathspec-limited diff package or editing `scripts/review-package`, whose output the conformance axis shares; embedding per-file diffs; putting the coverage between `Clean` and the dash; filtering binary rows or re-ranking the helper's output; reading `product.changed_lines` or `excluded` into the scoping decision; scoping a range that measures exactly 20 product files; measuring before the capability pre-flight.",
  "files": []
}
```

- [ ] **Step 4: Verify the eval file**

```bash
EVALS=home/common/claude-code/skills/codex-collaboration/evals/evals.json
just evals codex-collaboration 3
jq -e '[.evals[].id] == [1,2,3]' "$EVALS"
jq -e '.evals[] | select(.id==3) | .mode == "plan-only" and (.files | length == 0)' "$EVALS"
```

Then the acceptance-criterion-2 guard. Substring greps cannot carry it — most of eval 2 could be
rewritten with any two of them still green — so compare the **whole** base value against the
post-edit value with the one inserted sentence removed:

```bash
EVALS=home/common/claude-code/skills/codex-collaboration/evals/evals.json
git show fc498cb:"$EVALS" | jq -r '.evals[] | select(.id==2) | .expected_output' \
  > "${TMPDIR:-/tmp}/eval2-base.txt"
jq -r '.evals[] | select(.id==2) | .expected_output' "$EVALS" \
  > "${TMPDIR:-/tmp}/eval2-now.txt"
python3 - <<'PY'
import os, pathlib
tmp = pathlib.Path(os.environ.get("TMPDIR", "/tmp"))
INSERTED = (
    "Naming the size pre-flight is correct here, not a deviation: measuring the "
    "range with `diff-scope` after the capability pre-flight and finding it at or "
    "under 20 product files means the packet is dispatched exactly as described "
    "above — six items, no coverage sentence, no file list. "
)
base = (tmp / "eval2-base.txt").read_text(encoding="utf-8")
now = (tmp / "eval2-now.txt").read_text(encoding="utf-8")
assert now.count(INSERTED) == 1, "the inserted sentence must appear exactly once, verbatim"
assert now.replace(INSERTED, "", 1) == base, "eval 2 was rewritten, not extended"
print("eval 2 extended, not rewritten: OK")
PY
```

Expected: every `jq -e` exits 0; the Python block prints `eval 2 extended, not rewritten: OK` and
exits 0. Any other difference in eval 2 — a reworded `IN:`/`OUT —` boundary, a changed
output-shape or disposition clause, a touched `Failures:` list — fails the second assert with the
full string mismatch, which is exactly what criterion 2 needs pinned.

`just evals codex-collaboration 3` here means: the eval exists, is well-formed, and renders its
prompt and expected output; the runner records `PRINTED` and exits 0. **This is not a grade** (per
D17) — do not report criterion 9 as satisfied from this exit code. The grade is the plan's final
step, below.

- [ ] **Step 5: Integration gate**

Run once, from the worktree root, after committing: `just build`

Expected: the build succeeds. It is slow (several minutes). No `.nix` file changed in this issue
and no file was created or deleted, so this is a regression check that the skill trees still
evaluate and deploy — `nix build` reads the worktree's committed git tree, so commit before
running it. A `result` symlink appears in the worktree root; it is gitignored.

- [ ] **Step 6: Commit**

```bash
git add home/common/claude-code/skills/codex-collaboration/evals/evals.json
git commit -m "test(issue-23): eval the over-budget diff-review contract"
```

---

### Final step (not a task): grade eval 3 by hand and record the grade

**Owner:** the controller executing this plan — not a task implementer, and not the `sdd` per-task
loop. Run it after Task 4 is committed and before the branch is reported complete.

`mode: plan-only` evals in this suite are manually graded (D17). Running the eval renders it;
grading it is a person reading a transcript. Both existing evals in this suite work the same way,
so this is the suite's normal close-out, not extra machinery.

- [ ] **Step 1: Render the eval and produce a transcript**

Run `just evals codex-collaboration 3` to print the prompt and the expected output. Paste the
printed prompt into a fresh session on a repo matching this skill's assumptions (a worktree where
`codex-collaboration` is installed), exactly as the runner's own closing instruction says, and keep
the response.

- [ ] **Step 2: Grade the transcript against `expected_output` by hand**

Grade the response against eval 3's `expected_output`, item by item: pre-flight order and exact
invocation; the three fields read and the two deliberately not read; the strict `> 20` comparison;
the three scoped-packet differences (item 2's coverage sentence, item 4's dropped diff-package
path with `[DIFF_FILE]` unsupplied, item 7 as the bounded per-file collection instruction); the
verdict's em-dash placement; the hand-off value; case (a) `unmeasured`; case (b) same scoped packet
to the one-time native fallback. Every clause of the `Failures:` list is a fail condition.

Verdict is one of `PASS` / `PARTIAL` / `FAIL`, with the missed clauses named.

- [ ] **Step 3: Record the grade**

Append the verdict, the model and date, and the missed clauses (if any) to `## Execution log`
below, and repeat the one-line verdict in the PR body beside the review outcome. A recorded
`PARTIAL` or `FAIL` is a legitimate outcome to surface — it grades the prose, and the automated
pins for the same contracts are Tasks 1–3's contract tests, which must be green regardless.

---

## Execution log

Filled in as the plan executes. The eval-3 grade is required (D17); the rest is optional context.

| What | Result |
|---|---|
| Eval 3 manual grade (`just evals codex-collaboration 3`, plan-only) | **PASS** — 2026-08-17. Graded against `expected_output` at `5bb2c2d`. Subject: a fresh Opus agent given only the eval `prompt` plus the repo, barred from opening any `evals/` file, so it never saw the answer key; grader: a separate Opus reviewer. 13 of 13 load-bearing clauses HIT, 0 MISS, 0 PARTIAL, and nothing contradicting `DIFF-REVIEW.md`/`SKILL.md` at HEAD. No eval defects found. Caveat: subject and grader are both agents, not humans — D17 asks for a human read, so this records an agent-performed grade, not a human one. |

---

## Acceptance criteria → task map

| Issue acceptance criterion | Task |
|---|---|
| Pre-flight obtains product diff size from the shared helper before dispatching | 1 |
| At or under 20 product files the packet is unchanged | 1 (contract), 4 (eval 2's permissive clause keeps this gradeable; Step 4's whole-string comparison pins that eval 2 was extended, not rewritten) |
| Above 20, the packet carries exactly the 20 highest-churn files plus a scope line | 1 (contract test pins the cardinality — "taken as the first 20 entries in the emitted order" — and the highest-churn selection) |
| The subset is deterministic | 1 (inherited from the helper's total order; pinned as "no filtering, no re-ranking", "ranks churn descending with a raw-path-bytes tie-break", and "the same range always yields the same 20 paths") |
| Excluded classes never consume budget | 1 (the `--artifact-path` invocation; the helper already drops lockfiles and generated files) |
| The axis verdict states the coverage achieved | 1 (`DIFF-REVIEW.md` format + the regex lock), 2 (the rubric clause the reviewer actually reads) |
| The correctness review is bounded in what it *reads*, not only in what it grades (D16) | 1 (item 4 conditional, item 7 as collection instruction), 2 (the rubric's scoped-fetch branch) |
| The calling controller records the scope | 3 (conditional on the axis having come through `diff-review`; the capability-fallback path records none) |
| An oversized diff does not consume the one-time native fallback | 1 |
| The eval suite asserts the scoped-packet contract and its disclosure obligation | 4 for the eval's existence, well-formedness, and rendering; 1–3 for the automated pin on the contracts' substance; the final step for the manual grade, which is the only thing that produces a pass or fail for the eval itself (per D17 — `run-eval.sh` records `PRINTED` and exits 0 without grading) |
