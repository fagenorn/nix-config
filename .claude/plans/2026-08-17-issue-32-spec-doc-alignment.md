# Spec/Doc Alignment (issue 32) Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Bring four passages written during issues #21–#23 back into agreement with what
actually merged — three by amending the durable record in place, one by rewriting a live
agent instruction and pinning it with a contract test.

**Architecture:** Four prose corrections in three files plus one new test method. Specs are
*records*: they are amended with an inline marker and never silently overwritten (items 1–3).
A skill doc is a *live instruction*: it is rewritten clean with no marker (item 4). The only
executable change in the whole slice is one new assertion method in the existing
`WorkflowSkillContractsTest`. `diff-scope.py`, its CLI contract, and `test_diff_scope.py` are
not touched (per D1).

**Tech stack:** Markdown (`.claude/specs/**`, `home/common/agent-skills/skills/**`), Python 3
stdlib `unittest`, `just` recipes. No Nix change, no new dependency, no new file.

Spec: `.claude/specs/2026-08-17-issue-32-spec-doc-alignment-design.md` — **the authority**.
Issue: https://github.com/fagenorn/nix-config/issues/32

## Global Constraints

- **No `.nix` file is edited**, so `just build` is not the load-bearing gate;
  `just agent-workflow-tests` is. Baseline at this branch's base `de83938`: **175 tests, OK**
  (re-verified during planning). The suite must end green at **176 tests**.
- **`diff-scope.py`, its CLI contract, and `test_diff_scope.py` are out of bounds** (per D1).
  No flags, no output shape, no exit codes change. Item 2 is doc-only.
- **Issue 32 appends no rows to the diff-scope spec's D1–D25 ledger** (per D3). Item 1's
  marker cites that spec's own `D20`; item 2's cites `D2` of *this* issue's spec, qualified by
  issue and spec name (per D9).
- **Thresholds are never restated anywhere new.** `≤1,000 product lines` / `≤20 product files`
  stay spelled where they already live (ship-issue's Phase-5 gate and the two module constants
  `GATE_LINE_BOUNDARY` / `GATE_FILE_BOUNDARY`).
- **The `224954b3` snapshot in the evidence file is preserved byte-for-byte** — the fenced
  command, the fenced output, the `Recorded 2026-08-17 …` line, and the `Re-run this command
  fresh at ship time` closing paragraph (per D4).
- **Amendment-marker form.** Same-spec: `(**amended by Dnn** — …)`, matching D19/D25's existing
  inline parenthetical. Cross-spec: lead with the amending issue and spec name before the row
  ID (per D9). Item 4 gets **no** marker (per D8).
- **Wrapping conventions differ per file and must be respected.** The two `.claude/specs/`
  documents wrap prose at ~90 columns; `investigate.md` writes one unwrapped physical line per
  paragraph. Item 4's replacement is a **single line**.
- **Never disable commit signing** (no `-c commit.gpgsign=false`, no `--no-gpg-sign`). Surface
  signing failures rather than working around them.
- Every commit ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Test seams

Existing seams only; no new harness, no new file (spec `## Test seams`).

1. **`just agent-workflow-tests`** — the load-bearing suite. One new method joins
   `home/common/agent-skills/tests/test_workflow_skill_contracts.py`; it is the seam for
   **item 4** and the only automated seam in the slice (per D6). 175 → 176 tests.
2. **`test_diff_scope.py`'s existing text-format assertions** are the standing pin that makes
   **item 2**'s corrected prose true — six tests already fix the text form's exact shape,
   including `assertEqual(len(text.splitlines()), 2 + 8)`. No new test; do not edit that file.
3. **Item 3 is verified by re-execution, not by a test** — run the evidence file's own command
   with the merged head substituted and compare byte-for-byte. Task 2 carries that command.
4. **Items 1–3 get no automated seam, deliberately** (per D7). No suite reads `.claude/specs/**`
   and building one would invent a convention for three sentences. Their gates below are
   therefore concrete, runnable content assertions over the edited files — not "read it and see".

**Why the prose gates normalize whitespace.** Each prose gate reads the file and collapses runs
of whitespace with `" ".join(text.split())` before asserting, so a re-wrap at a different column
cannot break the gate and a gate cannot be satisfied by an accidental line break inside a pinned
clause. This mirrors the suite's own precedent (`test_workflow_skill_contracts.py` already does
`" ".join(SHIP_ISSUE.read_text(...).split())`). Note the consequence: expected fragments must
not themselves contain doubled spaces, which is why no gate below quotes the
`` `<churn>  <path>` `` token.

## Task index

- **Task 1 — Amend the diff-scope spec's two drifted passages** — `.claude/specs/2026-08-16-diff-scope-helper-design.md` — **low-risk**
- **Task 2 — Append the post-merge reading to the degradation-gate evidence** — `.claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md` — **low-risk**
- **Task 3 — Rewrite the C4 size-gate note and pin it** — `home/common/agent-skills/skills/from-issue/investigate.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — **full**

Lane rationale, since two of three tasks are prose: none of these is `mechanical` — every one
changes what a document asserts or instructs, which is a semantic-documentation effect by
definition. Tasks 1 and 2 are bounded, locally verifiable amendments to historical records that
no agent executes, hence `low-risk`. Task 3 is `full`: it rewrites a live instruction loaded
into an agent's context on **every** Phase 0 run, its wording is a contract pinned by the
repo's contract suite, and getting the carve-out's polarity or the estimate/count split wrong
would change what future runs actually count — the exact class of defect this issue exists to
correct.

## Decisions

The spec owns the single ledger (D1–D9). Tasks below cite rows by ID. Planning surfaced **no
new non-obvious decision** — the spec fixes the direction (D1), the marker form (D2, D8, D9),
the ledger boundary (D3), the addendum shape (D4), the `numstat` drop (D5), the test pin (D6),
and the absence of a seam for items 1–3 (D7). Task grouping, constant placement, and the
verification commands below are routine plan mechanics and are deliberately **not** logged as
ledger rows.

Task grouping note: items 1 and 2 are one task because they are two markers of the same
convention inside one file, committed together; item 4's doc rewrite and its contract pin are
one task because the test's pinned fragments *are* the rewritten sentence — a reviewer cannot
meaningfully accept one without the other.

---

### Task 1: Amend the diff-scope spec's two drifted passages (items 1 and 2)

**Files:**
- Modify: `.claude/specs/2026-08-16-diff-scope-helper-design.md` (two passages: the
  `**stdout, \`--format text\`.**` paragraph at ~line 99, and the `## Test seams` sentence at
  ~lines 231–233)
- Test: none — per D7 this task's gate is the content assertion in Step 4, not a suite.

**Interfaces:**
- Consumes: nothing from earlier tasks. This task is independent and may run first.
- Produces: nothing later tasks import. Task 3 does **not** depend on this file.

**Invariants:**
- Every other line of the file is byte-identical afterwards — including the whole `D1`–`D25`
  ledger table, which gains **no** row (per D3).
- Item 1's marker cites the same spec's own `D20` with the bare `**amended by Dnn**` form; item
  2's marker leads with the amending issue and spec name (per D9) because that spec's ledger
  already holds a `D2` of its own.
- Neither marker restates D20's rationale beyond the one clause quoted below — the ledger row
  carries the full grounding and is cited, not duplicated.
- Both amendments quote the *original* wording so a reader can see what changed.

- [ ] **Step 1: Read the two live passages before editing**

```bash
sed -n '99,101p' .claude/specs/2026-08-16-diff-scope-helper-design.md
sed -n '231,233p' .claude/specs/2026-08-16-diff-scope-helper-design.md
```

Expected, exactly (line numbers may have shifted; match on content):

```
**stdout, `--format text`.** The same content for a human or an agent quoting it into
prose: a `product:` line, an `excluded:` line, then one indented `<churn>  <path>` line
per ranked file, binaries suffixed ` (binary)`.
```

```
**1. `home/common/agent-skills/tests/test_diff_scope.py`**, stdlib `unittest`, registered
in `just agent-workflow-tests`. It follows `test_agent_model_matrix.py`'s two-layer
precedent verbatim:
```

Note the item-1 sentence wraps mid-phrase (`…two-layer` / `precedent verbatim:`), so the edit
spans two physical lines. `verbatim` carries **no** emphasis in the source and none is added.

- [ ] **Step 2: Apply item 1 — mark the reversed loader precedent**

**Apply verbatim.** Replace the two lines ending `…two-layer` / `precedent verbatim:` with:

```
in `just agent-workflow-tests`. It follows `test_agent_model_matrix.py`'s two-layer
precedent (**amended by D20** — this sentence originally read "precedent verbatim", which
D20 found to be exactly the bug: `load_module()` must additionally register the module in
`sys.modules` before `spec.loader.exec_module`, or every classifier-layer test errors in
`setUpClass`):
```

Nothing else in `## Test seams` changes — the two sub-bullets describing the classifier layer
and the CLI layer are accurate and stay exactly as they are.

- [ ] **Step 3: Apply item 2 — the text form deliberately omits the range identity**

**Apply verbatim.** Replace the whole three-line `**stdout, \`--format text\`.**` paragraph
with (per D1, doc-only — `diff-scope.py` is not touched):

```
**stdout, `--format text`.** The same *measurement* for a human or an agent quoting it
into prose, minus the range identity: a `product:` line, an `excluded:` line, then one
indented `<churn>  <path>` line per ranked file, binaries suffixed ` (binary)`.
(**amended by issue 32's alignment spec, D2** —
`.claude/specs/2026-08-17-issue-32-spec-doc-alignment-design.md`; this paragraph
originally read "the same content", which was never true of the shipped helper.) The
omission is deliberate: every line of the text form is measured output, whereas the range
is caller-supplied *input*, and a quoter carries it in the invocation printed above the
output — the pattern `.claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md`
already demonstrates. `--format json` echoes `range` because it is the machine record and
must stay self-describing once detached from the command that produced it.
```

Preserve the doubled space inside `` `<churn>  <path>` `` exactly as the original has it.

- [ ] **Step 4: Verify**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
p = Path(".claude/specs/2026-08-16-diff-scope-helper-design.md")
t = " ".join(p.read_text(encoding="utf-8").split())
present = [
    # item 1
    "two-layer precedent (**amended by D20** — this sentence originally read"
    ' "precedent verbatim", which D20 found to be exactly the bug: `load_module()`'
    " must additionally register the module in `sys.modules` before"
    " `spec.loader.exec_module`, or every classifier-layer test errors in"
    " `setUpClass`):",
    # item 2
    "The same *measurement* for a human or an agent quoting it into prose, minus the"
    " range identity:",
    "(**amended by issue 32's alignment spec, D2** —"
    " `.claude/specs/2026-08-17-issue-32-spec-doc-alignment-design.md`; this paragraph"
    ' originally read "the same content", which was never true of the shipped helper.)',
    "The omission is deliberate: every line of the text form is measured output,"
    " whereas the range is caller-supplied *input*",
    "`--format json` echoes `range` because it is the machine record",
]
absent = [
    "precedent verbatim:",
    "The same content for a human",
    "| D26 |",
]
bad = [f for f in present if f not in t] + [f"UNEXPECTED: {f}" for f in absent if f in t]
print("\n".join(bad) if bad else "OK: both amendments applied, both originals gone")
raise SystemExit(1 if bad else 0)
PY
```

Expected: `OK: both amendments applied, both originals gone`, exit 0. This gate fails at the
base commit — `precedent verbatim:` and `The same content for a human` are both present there,
and the two markers are both absent.

Then confirm nothing else in the file moved:

```bash
git diff --stat -- .claude/specs/2026-08-16-diff-scope-helper-design.md
```

Expected: exactly one file, and the insertions/deletions confined to the two passages (roughly
`+15 -4` — item 1 replaces one line with four, item 2 replaces three with eleven; the two
sub-bullets and the ledger table must not appear in `git diff -U0` output).

- [ ] **Step 5: Commit**

```bash
git add .claude/specs/2026-08-16-diff-scope-helper-design.md
git commit -m "docs(issue-32): amend the diff-scope spec's loader and text-format passages

Item 1 marks the reversed two-layer precedent against D20; item 2 corrects the
--format text parity claim to say the range identity is deliberately omitted, per
D1 and D9. No ledger rows added, per D3.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Append the post-merge reading to the degradation-gate evidence (item 3)

**Files:**
- Modify: `.claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md` (one sentence
  re-scoped at ~line 32; one new section appended at end of file)
- Test: none — per D7. The gate is re-execution of the evidence file's own command, Step 4.

**Interfaces:**
- Consumes: nothing from earlier tasks. Independent of Tasks 1 and 3.
- Produces: nothing later tasks rely on.

**Invariants:**
- The `224954b3` snapshot is preserved **byte-for-byte** (per D4): the fenced `$ python3 …`
  command, the fenced `product: 64 lines, 3 files` / `excluded: … 2 artifact` output and its
  three rows, the `Recorded 2026-08-17, on …` paragraph, and the closing
  `**Re-run this command fresh at ship time.**` paragraph all stay exactly as they are.
- Exactly **one** sentence changes: the one that reads as a claim about what shipped. The rest
  of that paragraph — the `2 artifact` explanation, the uncommitted-evidence-file note, the
  "One path per file throughout" closer — is unchanged and stays true of the snapshot.
- The appended section is additive and lands **after** the `Re-run this command fresh at ship
  time` paragraph, as the file's new final section.
- Every SHA, subject line and integer in the appended section is a verified fact (all
  re-verified during planning against this worktree's object store); none is inferred.

- [ ] **Step 1: Re-scope the one sentence that reads as a claim about what shipped**

The paragraph currently opens (wrapped across lines 32–33):

```
Reading it the way the gate does: `64` product lines and `3` product files, both
under ≤1,000 / ≤20, so this branch's own size prerequisite is satisfied. The `excluded: …
```

**Apply verbatim** — replace the whole paragraph (its eight original lines, 32–39). Only the
first sentence changes wording; every later word is preserved exactly, but the paragraph is
re-flowed at the file's ~90-column width, so every one of its lines moves:

```
Reading the snapshot the way the gate does: at `224954b3`, `64` product lines and `3`
product files, both under ≤1,000 / ≤20, so this branch's own size prerequisite is
satisfied — see the post-merge reading below for the figure at the merged tip. The
`excluded: … 2 artifact` count is the spec and the plan — the two artifact files this run
had committed when the range was measured. The invocation also names this evidence file,
which is still uncommitted at that moment and so matches no row and contributes nothing;
naming it costs nothing (an unmatched `--artifact-path` is deliberately not an error, per
D3) and it starts counting on any re-run made after this document is committed. One path
per file throughout, never `<specDir>`/`<planDir>`.
```

- [ ] **Step 2: Append the post-merge section**

**Apply verbatim** as the new final section of the file (after the
`**Re-run this command fresh at ship time.**` paragraph, separated by one blank line):

````markdown
## Post-merge reading (the figure that shipped)

The snapshot above is a real run at `224954b3`, not the figure that shipped. PR #27 merged
with head `b83e618e898ba80372756d0542f8872ded0e1672` (merge commit
`5aa2834f10796c7c71ae7c6f377610d1e63f3f36`). `git merge-base b83e618e fc498cb7` is
`fc498cb732ce8378711739c62463e5285e36133c` — the same base the snapshot used, so the two runs
are directly comparable. Two commits landed on the branch after the snapshot: `6f0b4cf`
(`docs(issue-22): record the A10 diff-scope run for the retuned gate`, this evidence file) and
`b83e618` (`test(ship-issue): pin the gate prerequisites' polarity`). Those two are what moved
64 → 76 product lines and 2 → 3 excluded artifacts.

The same command, with `..b83e618e898ba80372756d0542f8872ded0e1672` substituted as the head:

```
product: 76 lines, 3 files
excluded: 0 lockfile, 0 generated, 3 artifact
  72  home/common/agent-skills/tests/test_workflow_skill_contracts.py
  2  home/common/agent-skills/skills/ship-issue/SKILL.md
  2  home/common/agent-skills/skills/ship-issue/evals/evals.json
```

The gate's conclusion is unchanged: `76` ≤ 1,000 and `3` ≤ 20 — the same verdict by the same
margin. The third excluded artifact is this evidence file itself, now committed, exactly as the
snapshot's own prose predicted ("it starts counting on any re-run made after this document is
committed"). This addendum is also the fresh run the paragraph above asks for, made at the
branch's final commit.
````

Copy the fenced output block exactly, including the two-space indent before each ranked row and
the single-space gap after `2` in the two `2  home/...` rows.

- [ ] **Step 3: Confirm the snapshot survived untouched**

Run:

```bash
git diff -U0 -- .claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md \
  | grep '^-' | grep -v '^---'
```

Expected: **only** lines belonging to the `Reading it the way the gate does: …` paragraph —
all eight of them, because re-scoping its first sentence re-flows the whole paragraph. If any
line of the fenced command, the fenced `64 lines` output, or the `Recorded 2026-08-17` /
`Re-run this command fresh at ship time` paragraphs appears as a `-` line, the D4 invariant is
broken — restore it before continuing.

- [ ] **Step 4: Verify by re-execution**

Re-run the evidence file's own command against the merged head and diff it against what the new
section claims:

```bash
python3 home/common/agent-skills/scripts/diff-scope.py \
  fc498cb732ce8378711739c62463e5285e36133c..b83e618e898ba80372756d0542f8872ded0e1672 \
  --format text \
  --artifact-path .claude/specs/2026-08-16-ship-issue-degradation-gate-design.md \
  --artifact-path .claude/plans/2026-08-16-ship-issue-degradation-gate.md \
  --artifact-path .claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md
```

Expected, byte-for-byte identical to the block written in Step 2:

```
product: 76 lines, 3 files
excluded: 0 lockfile, 0 generated, 3 artifact
  72  home/common/agent-skills/tests/test_workflow_skill_contracts.py
  2  home/common/agent-skills/skills/ship-issue/SKILL.md
  2  home/common/agent-skills/skills/ship-issue/evals/evals.json
```

Then assert the prose landed and the old claim is gone:

```bash
python3 - <<'PY'
from pathlib import Path
p = Path(".claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md")
raw = p.read_text(encoding="utf-8")
t = " ".join(raw.split())
present = [
    "Reading the snapshot the way the gate does: at `224954b3`, `64` product lines and"
    " `3` product files, both under ≤1,000 / ≤20, so this branch's own size prerequisite"
    " is satisfied — see the post-merge reading below for the figure at the merged tip.",
    "## Post-merge reading (the figure that shipped)",
    "product: 76 lines, 3 files",
    "excluded: 0 lockfile, 0 generated, 3 artifact",
    "b83e618e898ba80372756d0542f8872ded0e1672",
    "5aa2834f10796c7c71ae7c6f377610d1e63f3f36",
    # the snapshot, preserved
    "product: 64 lines, 3 files",
    "excluded: 0 lockfile, 0 generated, 2 artifact",
    "**Re-run this command fresh at ship time.**",
]
absent = ["Reading it the way the gate does"]
bad = [f for f in present if f not in t] + [f"UNEXPECTED: {f}" for f in absent if f in t]
print("\n".join(bad) if bad else "OK: addendum added, snapshot intact, claim re-scoped")
raise SystemExit(1 if bad else 0)
PY
```

Expected: `OK: addendum added, snapshot intact, claim re-scoped`, exit 0. This gate fails at the
base commit — `Reading it the way the gate does` is present there and the whole
`## Post-merge reading` section is absent.

- [ ] **Step 5: Commit**

```bash
git add .claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md
git commit -m "docs(issue-32): record the merged-head figure for the degradation gate

Preserves the 224954b3 snapshot verbatim and appends the post-merge reading
(76 lines / 3 files, 3 artifact at b83e618) with the two intervening commits and
the shared merge-base, per D4. The verdict is unchanged.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Rewrite the C4 size-gate note and pin it (item 4)

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/investigate.md` (the file's final line,
  line 20)
- Modify/Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (one new
  module constant, one new `setUpClass` line, one new test method)

**Interfaces:**
- Consumes: nothing from Tasks 1 or 2 — this task is independent of both.
- Produces: module constant
  `INVESTIGATE = REPO_ROOT / "home/common/agent-skills/skills/from-issue/investigate.md"` and
  class attribute `cls.investigate: str` on `WorkflowSkillContractsTest`, plus the method
  `test_phase0_size_note_delegates_counting_to_diff_scope(self)` — no return annotation,
  matching every other method in that file. No later task
  consumes them.

**Invariants:**
- The rewritten line is **honest about both moments**: Phase 0 *estimates* (no range exists, so
  nothing can be measured) and later runs *count* (a range exists, `diff-scope` is
  authoritative). Collapsing them into "run diff-scope" reproduces the exact defect this issue
  fixes.
- The **directional carve-out survives**: this run's own artifacts are excluded by naming them
  one file at a time via `--artifact-path`; `<specDir>`/`<planDir>` are **never** passed
  themselves; a historical artifact that is itself the requested product **still counts**.
- The line **states policy and does not restate accounting**: it names exactly one flag
  (`--artifact-path`, because the carve-out is unstatable without it), carries **no** threshold
  numbers and **no** runnable invocation, and points at ship-issue's Phase-5 gate by name for
  both. (Verified during design: the gate does live under `## Phase 5 — Review the PR` in
  `ship-issue/SKILL.md`.)
- The word `numstat` disappears from the file entirely (per D5) — no contrasting clause keeps
  it. This is what makes the new pin a clean `assertNotIn`.
- **No amendment marker** (per D8): `investigate.md` is executed, not cited.
- `investigate.md` writes one unwrapped physical line per paragraph — the replacement is a
  **single line**, matching the line it replaces.

- [ ] **Step 1: Write the failing test**

Add the module constant immediately after `AUTO` (currently line 11), keeping the neighbours'
spelling style — full path from `REPO_ROOT`, not composed from `FROM_ISSUE_DIR`:

```python
INVESTIGATE = REPO_ROOT / "home/common/agent-skills/skills/from-issue/investigate.md"
```

Add the read to `setUpClass`, immediately after `cls.auto = AUTO.read_text(encoding="utf-8")`,
so assignment order matches constant order:

```python
        cls.investigate = INVESTIGATE.read_text(encoding="utf-8")
```

Add the method immediately after `test_ship_issue_eval_restates_the_gate_boundary_it_grades`
and before `test_helper_binaries_resolve_from_bare_names`, grouping it with the other
degradation-gate contracts:

```python
    def test_phase0_size_note_delegates_counting_to_diff_scope(self):
        # Issues #21-#22 made diff-scope the accounting authority and retired the
        # hand-counted numstat arithmetic; this note is the only restatement of
        # the C4 artifact carve-out in any skill, so it is where that drift hid.
        note = " ".join(self.investigate.split())
        for fragment in (
            # Whole affirmative clauses, not a bare "diff-scope" token: a bare
            # token also matches a clause saying the counting is *not* delegated
            # to the helper, which is the inversion this test guards.
            "`diff-scope` is the accounting authority",
            "measure, never hand-count",
            # Both directions of the carve-out: this run's artifacts are named
            # one file at a time, and the directories themselves never are.
            "one `--artifact-path` per file",
            "never `<specDir>`/`<planDir>` themselves",
            "still count",
            # The estimate/count split: Phase 0 has no range, so its number is an
            # estimate; the helper is authoritative only once a range exists.
            # Collapsing these two moments is the defect issue 32 fixed.
            "the Phase-0 number is an *estimate*",
            "Once the branch has a range",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, note)
        # The retired tool must not survive anywhere in the file, and the gate's
        # two boundaries stay spelled once, in ship-issue's Phase-5 gate: this
        # line states the policy and points there rather than restating numbers.
        for absent in ("numstat", "1,000", "≤20"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, note)
```

- [ ] **Step 2: Run the test and watch it fail**

Run:

```bash
python3 -m unittest -v \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  -k test_phase0_size_note_delegates_counting_to_diff_scope
```

Expected: **FAIL**, on exactly seven subtests (verified at `de83938`) — six `assertIn`
fragments, which is every one of them except `"still count"`, a clause the base line already
carries verbatim; plus the `assertNotIn` subtest for `numstat`, because the base line reads
`when estimating or later counting scope via \`git diff --numstat\`, …`. The `1,000` and `≤20`
absence subtests pass at base and must keep passing after the rewrite. Fewer failures than that
means the doc edit was applied out of order; revert it and re-run before continuing.

- [ ] **Step 3: Rewrite the C4 note**

**Apply verbatim.** Replace the whole of `investigate.md`'s final line (line 20) with this
single line:

```
**Size gates measure product changes (C4):** the Phase-0 number is an *estimate* — no range exists yet, so nothing can be measured; estimate the product change alone, leaving out the `specDir`/`planDir` artifacts this run will write, because they are process output. Once the branch has a range, `diff-scope` is the accounting authority (ship-issue's Phase-5 gate carries the invocation and the thresholds): measure, never hand-count, and exclude this run's own artifacts by passing one `--artifact-path` per file it wrote — never `<specDir>`/`<planDir>` themselves. Historical artifacts that are themselves the requested product still count.
```

Nothing else in the file changes — the PR pre-flight queries and the five investigate steps stay
exactly as they are.

- [ ] **Step 4: Verify**

Run the targeted test first:

```bash
python3 -m unittest -v \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  -k test_phase0_size_note_delegates_counting_to_diff_scope
```

Expected: **OK**, 1 test, no warnings.

Then the load-bearing suite:

```bash
just agent-workflow-tests 2>&1 | tail -5
```

Expected: `Ran 176 tests` and `OK`. Baseline at this branch's base was 175, so any other count
means a method was added or lost elsewhere. A failure in
`test_degradation_gate_delegates_counting_and_carries_the_retuned_boundary` or in the
`nested_workflow_documents()` sweeps (which already glob `from-issue/*.md`, `investigate.md`
included) means the rewritten line broke a neighbouring contract — fix the line, not the test.

Finally confirm the retired tool is gone from the whole from-issue skill:

```bash
grep -rn "numstat" home/common/agent-skills/skills/from-issue/ ; echo "exit=$?"
```

Expected: no output, `exit=1`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/investigate.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "fix(from-issue): name diff-scope as the C4 accounting authority

Rewrites the Phase-0 size-gate note in place (no amendment marker, per D8):
Phase 0 estimates because no range exists, and diff-scope is authoritative once
one does. Drops numstat entirely per D5 and pins the whole clause, both
directions of the artifact carve-out, and the estimate/count split in the
contract suite per D6. 175 -> 176 tests.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Done when

- All three tasks committed on `worktree-issue-32-spec-doc-alignment`.
- `just agent-workflow-tests` reports **176 tests, OK**.
- The four passages named by issue 32 each read consistently with the merged behaviour, which
  is the issue's own stated demo: the diff-scope spec's loader precedent carries its D20
  amendment, its `--format text` paragraph says the range identity is deliberately omitted, the
  evidence file carries both the preserved snapshot and the shipped 76/3 figure, and
  `investigate.md` routes size accounting through `diff-scope`.
- `git diff --stat de83938..HEAD -- .claude/specs/2026-08-16-diff-scope-helper-design.md
  .claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md
  home/common/agent-skills/skills/from-issue/investigate.md
  home/common/agent-skills/tests/test_workflow_skill_contracts.py` shows exactly those four
  files changed. (The spec and plan artifacts land in the range too and are expected there;
  this pathspec is scoped to the files the plan owns.)
- No `.nix` file, no `diff-scope.py`, no `test_diff_scope.py`, and no `patches/` file appears in
  the branch's diff.

---

## Standards review (Phase 5)

**Provenance.** One fresh `reviewer` pass on Opus/high with no inherited context, run against
worktree HEAD `6a8c636` on base `de83938`, grading the plan alone (read-only) against
`from-issue`'s `REVIEW-CONTRACT.md`. The native reviewer was used in place of the Codex
`plan-review` path as a deliberate timebox fallback, per D10 — not a Codex failure. Verdict:
findings, **zero blocking**.

**Dispositions.** Every finding was re-verified against the live worktree before the plan was
touched; none was applied on the reviewer's word alone.

| Finding | Disposition |
|---------|-------------|
| Should-fix: Task 3 Step 1's `assertIn("estimate")` is vacuous — `investigate.md` step 5 already reads `**Scope-size estimate**` | **Applied.** Confirmed by executing the fragment list against the base file. Pin widened to the whole clause; per D11 |
| Should-fix: Task 3 Step 2 mis-states the fail-at-base expectation as three subtests | **Applied.** Executed the amended fragment list at `de83938`: seven subtests fail (six `assertIn`, all but `"still count"`, plus `assertNotIn("numstat")`); `1,000` and `≤20` pass at base. Step 2 now states that count |
| Should-fix: Task 2 Step 1's dictated block leaves a ~112-column line and silently deletes original line 34, contradicting Step 3's expectation | **Applied.** Block re-flowed so every line clears ~90 columns; Step 1 now says all eight original lines are replaced, and Step 3's expectation widened to the whole paragraph; per D12 |
| Discussion: Task 1's dictated "every line of the text form is a measured row" is inaccurate — the `product:` and `excluded:` lines are not rows | **Applied.** This slice exists to stop specs asserting false things, so the same bar applies to the prose it writes. Changed to "is measured output" in both the dictated block and the gate's assertion string |
| Discussion: Task 1 Step 4's `git diff --stat` expectation of `+13 -4` is off | **Applied.** Corrected to `+15 -4` (item 1 one line to four, item 2 three to eleven) |
| Discussion: Task 3's Interfaces block annotates the new method `-> None`, unlike every other method in that file | **Applied.** Annotation dropped so the implementer copies the file's style |
