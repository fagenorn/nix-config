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
be the only one; `sdd/correctness-reviewer-prompt.md` gains a packet-conditional output clause;
`sdd/final-review.md` and ship-issue's `REVIEW.md` + `SKILL.md` record the returned scope. No
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
  when scoped (per D7).
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
- **`just evals codex-collaboration <id>`** — plan-only: prints the prompt and expected output
  and exits 0; exits 2 (`no eval with id N`) when the id is absent. Grading itself is manual.
- **`just build`** — the Nix/home-manager integration gate. Slow. Runs once, in Task 4 only.

Deliberately not a seam: a live end-to-end Codex review (non-deterministic, ~15 min, and a
passing live run does not generalise across diff sizes).

## Task index

- **Task 1 — Size pre-flight, scoped packet, and scoped verdict in the `diff-review` contract** —
  `home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md`,
  `home/common/claude-code/skills/codex-collaboration/SKILL.md`,
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py`,
  `home/common/agent-skills/tests/test_agent_evidence.py` — **full**
- **Task 2 — Packet-conditional coverage clause in the correctness rubric** —
  `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`,
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — **full**
- **Task 3 — Both calling controllers record the scope** —
  `home/common/agent-skills/skills/sdd/final-review.md`,
  `home/common/agent-skills/skills/ship-issue/REVIEW.md`,
  `home/common/agent-skills/skills/ship-issue/SKILL.md`,
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — **full**
- **Task 4 — Eval coverage for the over-budget contract** —
  `home/common/claude-code/skills/codex-collaboration/evals/evals.json` — **low-risk**

Tasks 1–3 are **full** lane: each changes a dispatch contract, a reviewer output contract, or a
controller's provenance obligation. Task 4 touches only a graded test asset — no shipped contract
— so it is **low-risk**; it carries the one `just build` integration gate.

## Decisions

The spec owns the ledger. Tasks cite rows by ID (D1–D15). Planning appended two rows, D14 and
D15, both about where the prose is pinned mechanically; nothing else in this plan required a new
decision.

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
  `### When the range is over budget` in `DIFF-REVIEW.md`, which Task 1's own test anchors on.

**Invariants:**
- The capability pre-flight (`command -v codex-companion`, owned by `SKILL.md`) always runs
  before the size pre-flight; no path measures a range it will never dispatch (per D12).
- Under budget, unmeasured, or measured at exactly 20 files, the dispatched packet is
  byte-identical in structure to today's: six numbered items, no coverage sentence, no item 7,
  today's verdict format (acceptance criterion 2).
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
            "yields no measurement — never a failure",
            "adds no fourth failure class",
            "never spends the one-time native fallback and never triggers a retry",
            "receives the same packet, item 7 and coverage sentence intact",
            "`full` | `scoped: <N> of <M> product files` | `unmeasured`",
            "This is a scoped review:",
            "do not treat their absence from the list as evidence they are clean",
            "Item 7 exists only when scoped",
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

- [ ] **Step 4: Add the over-budget packet variant**

Leave items 1–6 and the `Nothing else rides along` paragraph exactly as they are. Append this
subsection to the end of `## Packet`:

~~~markdown
### When the range is over budget

Under budget — or unmeasured — the packet is exactly the six items above. Over budget
it differs in exactly two places and nowhere else.

**Item 2 changes subject and gains a coverage sentence.** It becomes: review the
listed product files in the worktree, as changed across `<base-sha>..<head-sha>`, for
the same correctness subject matter, with the same instruction not to grade
conformance. Then, in substance:

> This is a scoped review: `<N>` of `<M>` changed product files, selected as the
> highest-churn files. Files outside the list are not under review in this pass — do
> not report on them, and do not treat their absence from the list as evidence they
> are clean.

Scoping bounds what is graded, not what may be consulted. The rubric's carve-out for
inspecting code outside the diff to evaluate a concrete named risk stands untouched —
one focused check per named risk — so a cross-file finding that reaches into an
unlisted file is legal and reportable. Silently grading an unlisted file, or implying
it was covered, is not.

**Item 7 exists only when scoped:** the selected paths, worktree-root-relative, one
per line, in the helper's emitted order, each with its `files[].changed_lines` count.
An unscoped packet has no item 7.

The packet stays a paths packet either way: it never embeds per-file diffs.
~~~

Grounding: item 2 keeps its name and meaning and item 7 is conditional per D7; the
consult-vs-grade boundary is D13; the paths-only rule is D2.

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

### Task 2: Packet-conditional coverage clause in the correctness rubric

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the scoped verdict format Task 1 wrote into `DIFF-REVIEW.md` —
  `**Correctness:** Clean — scoped to <N> of <M> product files; <1–2 sentence assessment>.`
  The clause added here must quote the same token, `scoped to <N> of <M> product files;`.
- Produces: nothing other tasks consume. This file is carried into the Codex packet by absolute
  path (`DIFF-REVIEW.md` item 3) and is also the native correctness reviewer's own prompt.

**Invariants:**
- The clause is conditional on **what the packet says**, never on who is reading (per D11). The
  body stays reviewer-agnostic: nothing after `## Output Format` may name Codex, Claude, or any
  model.
- The named-risk carve-out (`Inspect code outside the diff only to evaluate a concrete risk you
  can name … one focused check per named risk, named in your report.`) is left byte-identical
  (per D13).
- On the native path no packet ever states a scope, so the clause is inert there.

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
        for fragment in (
            "When the packet supplied to you states the review is scoped",
            "scoped to <N> of <M> product files;",
            "never between the verdict word and the dash",
            "When the packet says nothing about scoping, write the verdict exactly",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, " ".join(output_format.split()))
        # Reviewer-agnostic: the clause keys off the packet, not the reader (D11).
        for reader in ("Codex", "Claude", "native"):
            with self.subTest(reader=reader):
                self.assertNotIn(reader, output_format)
        # The named-risk carve-out survives scoping untouched (D13).
        self.assertIn(
            "one focused check per named risk, named in your\n    report.", rubric
        )
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest -v -k correctness_rubric_discloses home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL — at the base commit the `## Output Format` section says nothing about scoping,
so the first `subTest` fragment is absent.

- [ ] **Step 3: Add the clause**

Inside the fenced prompt template, in the `## Output Format` section, insert immediately after
the two lines that end with `` `**Correctness:** Clean | Findings — 1–2 sentence assessment.` ``
and before `Then exactly three top-level sections`, keeping the template's 4-space indentation:

~~~
    When the packet supplied to you states the review is scoped, that assessment
    clause opens with `scoped to <N> of <M> product files;` — after the em dash,
    never between the verdict word and the dash. When the packet says nothing about
    scoping, write the verdict exactly as above.
~~~

Change nothing else in the file: not the preamble, not the `agent-dispatch` comment, not the
`## Diff Under Review` paragraph that carries the named-risk carve-out, and not the
`**Placeholders:**` list — the clause is packet-conditional, so it introduces no new placeholder
(per D11).

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v -k correctness_rubric_discloses home/common/agent-skills/tests/test_workflow_skill_contracts.py && just agent-workflow-tests`

Expected: `Ran 1 test … OK`, then the full suite `OK`. If the carve-out assertion fails, the
`## Diff Under Review` paragraph was rewrapped — restore it verbatim rather than relaxing the
assertion.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-23): teach the correctness rubric to disclose a scoped packet"
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
        # correctness axis's reviewer identity (D1).
        self.assertIn(
            "the scope that axis returned (`full` | `scoped: <N> of <M> product "
            "files` | `unmeasured`)",
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

> and record both verdicts, the correctness axis's reviewer identity (`Codex` | `native` |
> `fallback` + failure class), and the scope that axis returned (`full` | `scoped: <N> of <M>
> product files` | `unmeasured`) in the ledger.

Nothing else in the file changes — the `Never merge the two reports` rule, the axis definitions,
and every `agent-dispatch` comment stay exactly as they are.

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
- Consumes: every contract Tasks 1–3 wrote — the pre-flight order and invocation, the two scoped
  packet differences, the scoped verdict format, the three scope values, the no-measurement
  degrade, and the fallback-preservation rule. The eval's `expected_output` grades exactly those
  and must not invent a field, flag, or value none of them defines.
- Produces: eval id `3` in this suite. The file's existing `skill_name` and `notes` keys and
  evals 1 and 2 keep their shape; `mode` stays `plan-only` (the sandbox has no `codex-companion`
  runtime, no Codex auth, and no ~15 minutes of external wall clock).

**Invariants:**
- Eval 2 keeps grading the under-budget packet's in/out boundaries **unchanged** — its `IN:`,
  `OUT —`, output-shape, disposition and `Failures:` clauses are edited in no way other than the
  one added permissive clause (acceptance criterion 2, per D4).
- Eval 3 grades the over-budget contract only; it does not restate eval 2's boundaries.
- The file stays valid JSON that `jq` and `run-eval.sh` can read.

- [ ] **Step 1: Write the failing gate**

There is no unittest seam for this file; the gate is the runner plus `jq`. Run it first and watch
it fail:

Run: `just evals codex-collaboration 3`

Expected: FAIL — `run-eval: no eval with id 3 in …/evals.json`, exit status 2.

- [ ] **Step 2: Add the permissive clause to eval 2**

In eval 2's `expected_output`, insert this sentence immediately before the existing
`Failures:` sentence, changing nothing else in the string:

> Naming the size pre-flight is correct here, not a deviation: measuring the range with
> `diff-scope` after the capability pre-flight and finding it at or under 20 product files means
> the packet is dispatched exactly as described above — six items, no coverage sentence, no file
> list.

Per D4 this exists so a plan-only grader does not read a correct pre-flight mention as a
deviation from the under-budget contract eval 2 is there to grade.

- [ ] **Step 3: Add eval 3**

Append this object to `.evals`, after eval 2:

```json
{
  "id": 3,
  "name": "diff-review-oversized-range-scoped-packet",
  "mode": "plan-only",
  "prompt": "sdd's final review is dispatching you for the correctness axis: operation diff-review over `aaa1111..bbb2222` in this worktree, a branch that changes 44 product files. **Plan-only: launch nothing.** Tell me: which pre-flights you run and in what order, with the exact command for any helper you call; what this packet contains that an under-budget packet would not; what the reviewer's first line must look like; what you hand back to the calling controller; and what you do in each of these situations: (a) `diff-scope` is not installed on this machine; (b) Codex comes back `CODEX_REVIEW_FAILURE: job timed out` on this dispatch.",
  "expected_output": "Pre-flights, in this order: first the shared capability pre-flight `command -v codex-companion`; then diff-review's own size pre-flight, run from the worktree root as `diff-scope <base>..<head> --root <absolute worktree root> --artifact-path <specDir> --artifact-path <planDir> --format json` (helper at `~/.agents/bin/diff-scope`; defaults `.claude/specs` / `.claude/plans` when the dispatcher has no bindings, never omitting the flags). Exactly three fields are read — `product.changed_files`, `files[].path`, `files[].changed_lines`; `product.changed_lines` and `excluded` are deliberately not read, they belong to the degradation gate. 44 > 20, so the packet is scoped to the first 20 entries of `files[]` taken verbatim — no filtering and no re-ranking, the helper's churn-descending, path-tie-broken order is already a total order, so the same range always yields the same 20 paths, and binary rows (churn zero) sort last so they never displace a text file. The scoped packet differs from the six-item packet in exactly two places: item 2 changes subject to the listed product files as changed across the range and gains a coverage sentence in substance — this is a scoped review, 20 of 44 changed product files, selected as the highest-churn files, files outside the list are not under review in this pass, do not report on them and do not treat their absence from the list as evidence they are clean — and a new item 7 lists the 20 paths, worktree-root-relative, one per line, in the helper's order, each with its changed-line count. Nothing else changes; no per-file diffs are embedded, the packet stays a paths packet. Scoping bounds what is graded, not what may be consulted: the rubric's carve-out for one focused check per concrete named risk survives, so a cross-file finding reaching into an unlisted file is legal and reportable. First line: `**Correctness:** Clean — scoped to 20 of 44 product files; <assessment>` or `**Correctness:** Findings — scoped to 20 of 44 product files; <assessment>` — the coverage opens the em-dash assessment clause, never sitting between the verdict word and the dash (agent-evidence.py fullmatches that line), and a scoped review never uses the bare `**Correctness:** Clean` form. Hand-off: the validated three-section result unmodified, plus the reviewer identity and the scope `scoped: 20 of 44 product files`, for the calling controller's ledger — the controller records what it is given and never re-derives the measurement. Case (a): a missing, non-zero-exiting or unparsable helper is no measurement, never a failure — dispatch exactly as today (six items, today's verdict format) and report `unmeasured`; it never spends the one-time native fallback and never triggers a retry. Case (b): that IS a real Codex failure — exactly one fresh native reviewer gets the SAME scoped packet, item 7 and coverage sentence intact, the failure class is recorded, Codex is not retried. Failures: treating the oversized diff as a Codex failure or spending the one-time fallback on it; embedding per-file diffs; putting the coverage between `Clean` and the dash; filtering binary rows or re-ranking the helper's output; reading `product.changed_lines` or `excluded` into the scoping decision; scoping a range that measures exactly 20 product files; measuring before the capability pre-flight.",
  "files": []
}
```

- [ ] **Step 4: Verify the eval file**

```bash
EVALS=home/common/claude-code/skills/codex-collaboration/evals/evals.json
just evals codex-collaboration 3
jq -e '[.evals[].id] == [1,2,3]' "$EVALS"
jq -e '.evals[] | select(.id==3) | .mode == "plan-only" and (.files | length == 0)' "$EVALS"
jq -er '.evals[] | select(.id==2) | .expected_output' "$EVALS" | grep -q 'size pre-flight'
jq -er '.evals[] | select(.id==2) | .expected_output' "$EVALS" | grep -q 'OUT — named as deliberate exclusions, not omissions'
jq -er '.evals[] | select(.id==2) | .expected_output' "$EVALS" | grep -q "Failures: reusing the plan-review packet"
```

Expected: the runner prints eval 3's prompt and expected output and exits 0; every `jq -e` and
`grep -q` exits 0. The last two greps are the acceptance-criterion-2 guard — they fail if eval
2's in/out boundary text was rewritten rather than extended.

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

## Acceptance criteria → task map

| Issue acceptance criterion | Task |
|---|---|
| Pre-flight obtains product diff size from the shared helper before dispatching | 1 |
| At or under 20 product files the packet is unchanged | 1 (contract), 4 (eval 2's permissive clause keeps this gradeable) |
| Above 20, the packet carries exactly the 20 highest-churn files plus a scope line | 1 |
| The subset is deterministic | 1 (inherited from the helper's total order; asserted as "no filtering, no re-ranking") |
| Excluded classes never consume budget | 1 (the `--artifact-path` invocation; the helper already drops lockfiles and generated files) |
| The axis verdict states the coverage achieved | 1 (`DIFF-REVIEW.md` format + the regex lock), 2 (the rubric clause the reviewer actually reads) |
| The calling controller records the scope | 3 |
| An oversized diff does not consume the one-time native fallback | 1 |
| The eval suite asserts the scoped-packet contract and its disclosure obligation | 4 |
