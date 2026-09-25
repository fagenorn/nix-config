# ship-issue Degradation Gate Retune Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

Issue: https://github.com/fagenorn/nix-config/issues/22
Spec: `.claude/specs/2026-08-16-ship-issue-degradation-gate-design.md` (the decision ledger
there is the source of truth; this plan cites rows by ID — D1–D12 — and never restates them)

**Goal:** Retune `ship-issue`'s Phase-5 degradation gate to ≤1,000 product lines AND ≤20
product files, delegate all counting to the `diff-scope` helper, and pin both numbers plus
the delegation with deterministic tests so the skill and its eval cannot separate again.

**Architecture:** Three markdown/JSON/Python surfaces change and nothing executable does.
`ship-issue/SKILL.md` line 134 becomes a policy statement plus a helper call (per D1/D2/D3);
eval 1's `expected_output` gains the retuned boundary in one clause (per D5); and
`test_workflow_skill_contracts.py` gains two module-level boundary constants (per D7) that are
asserted against *both* documents, so the boundary is spelled once in the enforcement layer.
Each document edit ships in the same task as its pin (per D12).

**Tech stack:** Markdown, JSON, Python 3 stdlib `unittest` (`pathlib`, `json`), `just`, Nix /
home-manager. No new dependency, no new file under `home/`, no script change.

**This slice ships prose and its enforcement — no executable behaviour changes.**
`diff-scope.py`, its tests and its Nix wiring are untouched (spec: Out of scope).

## Global Constraints

- **`diff-scope.py` is out of bounds.** No edit to
  `home/common/agent-skills/scripts/diff-scope.py`, `tests/test_diff_scope.py`, or
  `home/common/agent-skills/default.nix`. The helper is a merged contract; this is its first
  consumer.
- **Exactly three product files change** across the whole plan:
  `home/common/agent-skills/skills/ship-issue/SKILL.md`,
  `home/common/agent-skills/skills/ship-issue/evals/evals.json`,
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py`. Plus one new
  `.claude/specs/*-evidence.md` process artifact in Task 3 (per D11).
- **Do not touch `ship-issue/REVIEW.md`.** It contains `≤400 words` twice — verdict word
  budgets for reviewers, not the gate's line cap. They are not restatements of this boundary
  and "fixing" them is out of scope. (The spec's Out-of-scope line calls REVIEW.md free of
  `400`; that is imprecise — it is free of the *boundary*, which is what matters.)
- **Do not touch `from-issue/investigate.md`'s C4 note** — residual, per D10.
- **One physical line per bullet.** `SKILL.md` bullets and `evals.json` records are single
  long lines in this repo; keep them that way so each document edit is a one-line replacement
  (`git diff --numstat` reads `1	1	<path>`). Do not reflow or hard-wrap.
- **Never disable GPG signing.** No `-c commit.gpgsign=false`, no `--no-gpg-sign`. Surface a
  signing failure rather than working around it.
- **Commit trailer**, on every commit:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- **Never run `just switch`** or any activation. `just build` is this repo's documented sole
  build gate (CLAUDE.md); switching happens only when the user asks.
- **Payload discipline.** Summarise test and build output to the failing lines and the final
  `Ran N tests` line; never paste a whole run into a report.

### The activation lag (an execution constraint, not a bug)

`~/.agents/bin/diff-scope` **does not exist on this host** — issue 21 merged the `home.file`
entry, but the machine has not been switched since (verified: `~/.agents/bin/` holds
`agent-evidence`, `agent-model-matrix`, `context-map-lint`, `resolve-bindings`,
`workflow-state`, and nothing else). This is precisely the day-one case D4 exists for.

Consequences every task must respect:

- **No task may invoke `diff-scope` by bare name or from `~/.agents/bin/`.** It will not
  resolve, and "fixing" that by switching is out of scope.
- The one real helper run this plan needs (Task 3, A10 evidence) invokes the script directly
  from the worktree. Verified working during planning:

  ```
  $ python3 home/common/agent-skills/scripts/diff-scope.py fc498cb..HEAD --format text \
      --artifact-path .claude/specs/2026-08-16-ship-issue-degradation-gate-design.md
  product: 0 lines, 0 files
  excluded: 0 lockfile, 0 generated, 1 artifact
  ```
  (exit 0; `--help` confirms `--artifact-path PATH  ... repeatable` and
  `--format {json,text}  (default: json)`.)
- The prose the plan writes into `SKILL.md` still names the bare name with the
  `~/.agents/bin/diff-scope` anchor (per D2) — that is the correct instruction for a *switched*
  host, and it is what `test_helper_binaries_resolve_from_bare_names` enforces. The absence
  today is what the no-measurement clause (D4) covers.

## Test seams

Existing seams only. A task that wants a new one has found a plan bug, not a licence.

1. **`just agent-workflow-tests`** — the deterministic gate
   (`python3 -m unittest -v` over seven suites, run from the worktree root). Baseline verified
   at this branch's tip: **156 tests, OK**. This plan adds two tests → **158** at the end.
2. **`just evals ship-issue 1`** — plan-only. `run-eval.sh` prints the prompt and
   `expected_output` for manual grading; it can never be green or red, so no task treats its
   exit status as a verdict. Its usable mechanical form is `| grep -c '<boundary>'` over the
   printed expected output.
3. **`just build`** — `SKILL.md` and `evals.json` are copied into the home-manager generation,
   so the build must still evaluate. Verified green at this branch's tip; it costs **≈3 min
   warm, ≈10 min cold** on this host, which is why it appears once per task and not per step.

Deliberately **not** a seam: `test_diff_scope.py` (per D8 and the spec's Test seams section) —
the helper is untouched, and a gate-flavoured test there asserts the caller's policy inside the
callee's suite.

## Task index

| Task | Title | Files touched | Risk lane |
|------|-------|---------------|-----------|
| 1 | Delegate the gate's accounting and pin the retuned boundary | `home/common/agent-skills/skills/ship-issue/SKILL.md` (modify), `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (modify) | **full** |
| 2 | Retune the eval that grades the gate, and pin SKILL↔eval agreement | `home/common/agent-skills/skills/ship-issue/evals/evals.json` (modify), `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (modify) | **low-risk** |
| 3 | Record the A10 helper evidence and sweep every gate | `.claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md` (create) | **low-risk** |

**Lane rationale.** Task 1 is **full**: it rewrites the sentence that decides how thoroughly
every future branch is reviewed — a semantic documentation change to a workflow contract that
other skills and a live pipeline read, not a wording tidy. Its blast radius is every subsequent
`ship-issue` run, which is exactly the "public contract" the low-risk lane excludes. Task 2 is
**low-risk**: the boundary is already settled by Task 1, so this is a bounded propagation into
one eval clause plus its pin; it changes what a *grader* accepts, is locally verifiable by the
test it ships with, and touches no concurrency, lifecycle, destructive operation, security,
release, or migration surface. Task 3 is **low-risk**: it adds one evidence document and runs
existing gates; it changes no instruction any agent follows. Nothing here is **mechanical** —
that lane is deletion/renaming with no semantic-documentation effect, and every task in this
plan changes meaning.

## Decisions

The spec owns the single decision ledger; read it before starting any task. This plan appended
two rows to it during planning and adds no others:

- **D11** — A10's recorded run is persisted as
  `.claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md`, produced by invoking the
  script directly, and instructs the ship phase to re-run fresh rather than quoting stale
  integers.
- **D12** — each document edit ships in the same task as the test that pins it, tests written
  first, so `just agent-workflow-tests` is green at every commit boundary.

Tasks cite rows inline (per D2, per D7, …). Rows are never restated here.

### Verified facts every task may rely on

Probed in this worktree during planning (git 2.51.2, Python 3.13.12, base `fc498cb`). No task
needs to re-derive them.

1. `section("**Pick the path first.**", "**Merge-delta check (degraded path).**")` over today's
   `SKILL.md` yields a **1,108-character** section containing, in order:
   `` `review_state` is `clean` `` (126), `manual conflict escalation` (301), the size clause,
   `` `risky` label `` (892), `` `review.criticalPaths` glob `` (1086) — and containing both
   `400` and `--numstat`. After the Task 1 rewrite the same section is **1,557 characters**,
   the order is unchanged, and both `400` and `--numstat` are gone. The full Task 1 assertion
   set was executed against a spliced copy: every assertion fails before the rewrite and passes
   after.
2. The gate boundary is restated in exactly **two** places repo-wide: `SKILL.md:134` and
   `evals/evals.json:10` (eval id 1). Other `400`s in the repo are unrelated —
   `REVIEW.md`'s `≤400 words`, `doc-grounded-questions`' ~400-line reading rule,
   `REVIEW-CONTRACT.md`'s HTTP-400 example, `test_workflow_state.py`'s `140000`.
3. `test_workflow_skill_contracts.py` currently imports only `pathlib.Path` and `unittest`;
   Task 2 needs `import json`. Precedent for reading an eval file in a contracts suite:
   `test_ship_release_contracts.py:22,68` (`EVALS = ...evals.json`, `json.loads(...)`).
4. `setUpClass` does **not** read `ship-issue/SKILL.md` today; Task 1 adds it.
5. `just build` runs `nix build ".#darwinConfigurations.mbp.system"` against the flake in the
   dirty worktree. Nix reads the **git index** for a dirty tree, so a *new* file under `home/`
   would have to be `git add`ed to be visible. No task creates one — but do not let an
   untracked file mislead a build result.
6. `result/` is gitignored (`.gitignore:1`), so `just build` leaves `git status --porcelain`
   clean.

---

### Task 1: Delegate the gate's accounting and pin the retuned boundary

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (line 134, the third bullet of
  the `**Pick the path first.**` list — exactly one line replaced)
- Modify/Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the first).
- Produces, for Task 2 to reuse verbatim:
  - `SHIP_ISSUE` — module-level `Path` to `ship-issue/SKILL.md`
  - `GATE_LINE_BOUNDARY = "≤1,000 product lines"` — module-level `str`
  - `GATE_FILE_BOUNDARY = "≤20 product files"` — module-level `str`
  - `cls.ship_issue` — the file text, read in `setUpClass`
  - `self.section(text, heading, next_heading)` and `self.assert_ordered(text, *anchors)` —
    existing helpers on `WorkflowSkillContractsTest`, unchanged.

**Invariants:**
- The two boundary numbers appear **exactly once each** in the test module, as the two constants
  above (per D7). No test may re-spell `1,000` or `20 product files` inline.
- Only the size bullet changes in `SKILL.md`. The other three degradation prerequisites keep
  their text *and their order* (`review_state` → conflict-free sync → size → `risky` /
  `criticalPaths`) — this is what makes A5 a check rather than a promise.
- The gate section names no counting arithmetic: no `--numstat`, no "additions + deletions", no
  `<auto-generated>` / `// Code generated by` markers, no lockfile-allowlist rule (per D1 — each
  now lives in `diff-scope.py`).
- `~/.agents/bin/diff-scope` is asserted in exactly one test —
  `test_helper_binaries_resolve_from_bare_names`, its existing home. The gate-contract test does
  **not** assert it (per the spec: no fragment asserted twice).

- [ ] **Step 1: Write the failing test**

Add at module level, next to the existing path constants (after `FROM_ISSUE_DIR`):

```python
SHIP_ISSUE = REPO_ROOT / "home/common/agent-skills/skills/ship-issue/SKILL.md"

# The Phase-5 degradation boundary, spelled once for the whole module: the skill
# and its eval are both checked against these two strings so they cannot drift.
GATE_LINE_BOUNDARY = "≤1,000 product lines"
GATE_FILE_BOUNDARY = "≤20 product files"
```

Add one line to `setUpClass`, alongside the other reads:

```python
        cls.ship_issue = SHIP_ISSUE.read_text(encoding="utf-8")
```

Add the new test method (place it immediately before
`test_helper_binaries_resolve_from_bare_names`):

```python
    def test_degradation_gate_delegates_counting_and_carries_the_retuned_boundary(self):
        # The gate states a policy and calls the helper; the accounting itself
        # lives in diff-scope.py and is not restated here.
        gate = self.section(
            self.ship_issue,
            "**Pick the path first.**",
            "**Merge-delta check (degraded path).**",
        )
        for fragment in (
            GATE_LINE_BOUNDARY,
            GATE_FILE_BOUNDARY,
            # the whole invocation, not its pieces: a gate that named only
            # <spec_path> would satisfy a bare "--artifact-path" check while
            # under-naming this run's artifacts and inflating the count (D3).
            "diff-scope $BASE_SHA..$HEAD_SHA --format text"
            " --artifact-path <spec_path> --artifact-path <plan_path>",
            "No measurement",
            "is not a small diff",
            "a historical artifact that is itself the requested product still counts",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, gate)
        for absent in ("--numstat", "400", "--root"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, gate)
        self.assert_ordered(
            gate,
            "`review_state` is `clean`",
            "manual conflict escalation",
            GATE_LINE_BOUNDARY,
            "`risky` label",
            "`review.criticalPaths` glob",
        )
```

Extend `test_helper_binaries_resolve_from_bare_names` with the `ship-issue` row, appended after
the existing `agent-evidence` loop:

```python
        with self.subTest(skill="ship-issue"):
            self.assertIn("~/.agents/bin/diff-scope", self.ship_issue)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `just agent-workflow-tests 2>&1 | tail -30`

Expected: **FAIL**, 157 tests run, and the failures come from exactly two test methods —
`test_degradation_gate_delegates_counting_and_carries_the_retuned_boundary` and
`test_helper_binaries_resolve_from_bare_names` (`skill='ship-issue'`). `unittest` reports one
block per failing `subTest`, so expect many blocks from the first method: all six `fragment=`
subTests, and the `absent=` subTests for `--numstat` and `400` (both are in today's section —
that is the point; `--root` is already absent and its subTest passes from the start), and the
un-subTested `assert_ordered` raising on the missing
`≤1,000 product lines` anchor. What must hold: **no ERROR** anywhere, and no other test method
in the failure list. An error means the constants or the `setUpClass` line went in wrong — fix
that before touching `SKILL.md`.

- [ ] **Step 3: Replace the gate bullet**

Replace `SKILL.md` line 134 — the whole line, one line in and one line out — with the following
**single physical line** (shown wrapped here; join it into one line, and keep the surrounding
bullets untouched):

```markdown
- The branch diff is small: **≤1,000 product lines AND ≤20 product files**. Measure, never hand-count: `diff-scope $BASE_SHA..$HEAD_SHA --format text --artifact-path <spec_path> --artifact-path <plan_path>` (executable `~/.agents/bin/diff-scope`; use the full path if the bare name does not resolve) — its first line reads `product: <lines> lines, <files> files`, after the helper drops lockfiles, generated-header files, and the artifact paths you named. The gate measures PRODUCT changes, not process artifacts, so pass one `--artifact-path` per **file this run wrote** — `<spec_path>`, `<plan_path>`, plus anything else it put there (a `research` findings file) — and never `<specDir>`/`<planDir>` themselves, which hold every artifact this repo has ever accepted; a historical artifact that is itself the requested product still counts. No measurement — helper missing, or a non-zero exit — is not a small diff: run the full two-axis review.
```

Every clause is load-bearing and each was checked against the live helper during planning:

- `$BASE_SHA..$HEAD_SHA` — both are already defined at the top of Phase 5; the two-dot range with
  both sides resolved is what `diff-scope` requires (per D2).
- `--format text` with no `--root` and no `jq` (per D2). The first output line really is
  `product: <n> lines, <m> files` and the second really is
  `excluded: <n> lockfile, <n> generated, <n> artifact` — verified. The quoted line is a reading
  aid, not a parser contract (per D8).
- one `--artifact-path` **per file**, never a directory (per D3); the carve-out sentence is the
  instruction that justifies the flag values, not a description of helper behaviour.
- the no-measurement clause (per D4) — live on day one, since the binary is not on PATH yet.

You may adjust connective wording for flow; you may not drop or weaken a clause, add counting
arithmetic back, or split the bullet across lines.

- [ ] **Step 4: Verify**

```bash
set -o pipefail   # without it a pipeline returns tail's status and a failing gate reads as 0
just agent-workflow-tests 2>&1 | tail -5
git diff --numstat "$(git merge-base HEAD origin/main)" -- home/common/agent-skills/skills/ship-issue/SKILL.md
grep -c "1,000" home/common/agent-skills/tests/test_workflow_skill_contracts.py
just build 2>&1 | tail -3
```

Expected, in order:
- `Ran 157 tests` … `OK` (156 baseline + 1 new method; the bare-names row is a subTest and adds
  no count), **and the pipeline exits 0** — with `pipefail` set, that status is the test run's.
- `1	1	home/common/agent-skills/skills/ship-issue/SKILL.md` — one line out, one line in. Any
  other numbers mean the bullet was reflowed or a neighbouring bullet was edited (A5).
  The range is deliberately `<base>` with **no `..HEAD`**: this step runs before Step 5's commit,
  so the edit is still in the working tree and a `base..HEAD` comparison would print nothing.
- `1` — the boundary is spelled once in the test module (A9). `2` or more means a test
  re-spelled it inline instead of using the constant.
- `just build` exits 0 (A8) — again a real status only because `pipefail` is set. Warm ≈3 min.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "$(cat <<'EOF'
feat(ship-issue): retune the degradation gate and delegate its counting

Closes part of https://github.com/fagenorn/nix-config/issues/22

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

**Criteria covered:** A1, A2, A3, A4, A5, A7, A8, and A9's first half.

---

### Task 2: Retune the eval that grades the gate, and pin SKILL↔eval agreement

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/evals/evals.json` (eval id 1's
  `expected_output`, one clause — exactly one line replaced)
- Modify/Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes, from Task 1 (already in the module — do not redefine):
  `GATE_LINE_BOUNDARY = "≤1,000 product lines"`, `GATE_FILE_BOUNDARY = "≤20 product files"`,
  `SHIP_ISSUE`, `cls.ship_issue`, `self.section`, `self.assert_ordered`.
- Produces: `SHIP_ISSUE_EVALS` (module-level `Path`) and `cls.ship_issue_evals` (parsed dict).

**Invariants:**
- The eval edit is **one clause long** (per the spec): it carries the two numbers and the
  delegation, and nothing about `--format`, `--root`, or which paths get named. Those belong to
  the skill, which is where an agent reads them, and to Task 1's contract test.
- The boundary constants stay spelled once in the module (per D7) — this task adds a *consumer*
  of them, never a second copy.
- The eval file is parsed as JSON and eval **id 1** is located by its `id` field, not by list
  position and not by substring search over the raw file: a boundary that migrated into another
  eval must not satisfy this test.
- No other eval record changes; evals 2 and 3 are untouched.

- [ ] **Step 1: Write the failing test**

Add `import json` to the module's imports (currently `from pathlib import Path` / `import
unittest`), and the path constant next to `SHIP_ISSUE`:

```python
SHIP_ISSUE_EVALS = (
    REPO_ROOT / "home/common/agent-skills/skills/ship-issue/evals/evals.json"
)
```

Add one line to `setUpClass`:

```python
        cls.ship_issue_evals = json.loads(SHIP_ISSUE_EVALS.read_text(encoding="utf-8"))
```

Add the new test method immediately after
`test_degradation_gate_delegates_counting_and_carries_the_retuned_boundary`:

```python
    def test_ship_issue_eval_restates_the_gate_boundary_it_grades(self):
        # Eval 1 grades a whole phase walk; its one degradation clause must
        # quote the same boundary the skill states, or a graded walk can be
        # "correct" against a number the skill no longer carries.
        expected = next(
            case for case in self.ship_issue_evals["evals"] if case["id"] == 1
        )["expected_output"]
        for fragment in (GATE_LINE_BOUNDARY, GATE_FILE_BOUNDARY, "diff-scope"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, expected)
        self.assertNotIn("≤400", expected)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `just agent-workflow-tests 2>&1 | tail -30`

Expected: **FAIL**, 158 tests run, failures from exactly one test method —
`test_ship_issue_eval_restates_the_gate_boundary_it_grades`: all three `fragment=` subTests fail
(today's eval names neither number nor the helper) and the final `assertNotIn("≤400", …)` fails.
**No ERROR** — a `KeyError`/`StopIteration` means the `id == 1` lookup or the `json.loads` line
went in wrong. Task 1's tests stay green; any failure from another method means Task 1 was
disturbed.

- [ ] **Step 3: Retune eval 1's clause**

In `evals.json`, inside eval id 1's `expected_output`, replace the fragment

```
the diff is small (≤400 lines/20 files)
```

with

```
the diff is small (≤1,000 product lines / ≤20 product files, measured with `diff-scope` rather than hand-counted numstat arithmetic)
```

Nothing else in that string changes, and the record stays one physical line. The clause is
accurate about the rewritten skill: a walk that recites numstat arithmetic now grades as a
failure rather than as a stylistic difference (per D5), and "product" is the same word the
helper prints and the skill now uses (per D9).

- [ ] **Step 4: Verify**

```bash
set -o pipefail   # without it a pipeline returns tail's status and a failing gate reads as 0
just agent-workflow-tests 2>&1 | tail -5
git diff --numstat "$(git merge-base HEAD origin/main)" -- home/common/agent-skills/skills/ship-issue/evals/evals.json
python3 -c "import json;print(len(json.load(open('home/common/agent-skills/skills/ship-issue/evals/evals.json'))['evals']))"
grep -c "1,000" home/common/agent-skills/tests/test_workflow_skill_contracts.py
grep -c "20 product files" home/common/agent-skills/tests/test_workflow_skill_contracts.py
just evals ship-issue 1 | grep -c "≤1,000 product lines"
just build 2>&1 | tail -3
```

As in Task 1, the numstat range carries **no `..HEAD`** — this step runs before the commit, so the
edit is still in the working tree.

Expected, in order: `Ran 158 tests` … `OK`; `1	1	…/evals.json`; `3` (the JSON still parses and
still holds three evals); `1`; `1` (A9 — the boundary is spelled exactly once in the test
module); `1` (A6's manual-grade leg — the printed expected output states the retuned boundary;
`just evals` cannot pass or fail, so this grep is the observation, not its exit status);
`just build` exits 0.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/evals/evals.json \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "$(cat <<'EOF'
test(ship-issue): grade the retuned boundary in eval 1 and pin skill/eval agreement

Closes part of https://github.com/fagenorn/nix-config/issues/22

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

**Criteria covered:** A6, A9, A8.

---

### Task 3: Record the A10 helper evidence and sweep every gate

**Files:**
- Create: `.claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md`

**Interfaces:**
- Consumes: the finished state of Tasks 1 and 2 (all three product files at their final
  content).
- Produces: the evidence document the ship phase quotes for the PR body (per D11 and A10).

**Invariants:**
- The recorded command invokes the script **directly from the worktree**
  (`python3 home/common/agent-skills/scripts/diff-scope.py …`), never `~/.agents/bin/diff-scope`
  and never a bare `diff-scope` — the symlink does not exist until a `just switch` that is out
  of scope.
- The recorded run names one `--artifact-path` per file this run wrote (per D3): the spec, the
  plan, and this evidence file itself. Naming the evidence file is free even though it is not
  yet committed — an unmatched value is deliberately not an error (per D3).
- The document records **the exact SHAs it measured** and states that the integers are a
  snapshot, not the PR's final numbers: review fixups and the Phase-1 sync merge move the range,
  so the ship phase re-runs the same command fresh (per D11).
- No product file changes in this task. `git diff --numstat <base>..HEAD -- home/` must be
  identical to what Tasks 1 and 2 produced.

- [ ] **Step 1: Run the helper over the branch's own range**

```bash
BASE_SHA=$(git merge-base HEAD origin/main)
HEAD_SHA=$(git rev-parse HEAD)
python3 home/common/agent-skills/scripts/diff-scope.py "$BASE_SHA".."$HEAD_SHA" --format text \
  --artifact-path .claude/specs/2026-08-16-ship-issue-degradation-gate-design.md \
  --artifact-path .claude/plans/2026-08-16-ship-issue-degradation-gate.md \
  --artifact-path .claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md
echo "exit=$?"
```

Expected shape (the integers are whatever the branch actually is — paste the real stdout, never
a number from this plan):
- exit 0, first line `product: <lines> lines, <files> files`, second line
  `excluded: 0 lockfile, 0 generated, <n> artifact` with `<n>` ≥ 2 (the spec and plan are
  committed by now).
- The per-file churn list under those two lines contains **only** the three product files this
  plan owns. **If any `.claude/` path appears in the product list, an `--artifact-path` is
  missing** — fix the invocation before recording it; that is the D3 failure mode this evidence
  exists to demonstrate the correct side of.
- `<files>` should be 3 (`SKILL.md`, `evals.json`, `test_workflow_skill_contracts.py`); a
  larger number means something outside the plan's file list was edited.

- [ ] **Step 2: Write the evidence document**

Create `.claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md` with this structure —
prose as written, the command reproduced as typed, and beneath it the **verbatim stdout** of
Step 1 rather than any transcription. Stdout does not echo the command, so write the two as
separate blocks (or one block with the command on a `$`-prefixed line) and never claim the
copied command is part of the captured output:

```markdown
# Degradation gate retune — A10 evidence

Issue: https://github.com/fagenorn/nix-config/issues/22
Spec: `.claude/specs/2026-08-16-ship-issue-degradation-gate-design.md` (A10)

A10 asks for the prescribed invocation to produce its two integers on a real range. It is
evidence, not a gate: the retuned gate cannot be observed deciding a live ship yet, because a
skill is read through the activated generation's `~/.claude/skills` link and
`~/.agents/bin/diff-scope` does not exist until the next `just switch` (out of scope here, per
the spec). This run therefore invokes the script directly from the worktree; the flags,
the range and the reading are identical to what the gate prescribes.

Recorded <date>, on `<branch>` at `<HEAD_SHA>` with `BASE_SHA=<BASE_SHA>`
(`git merge-base HEAD origin/main`).

<the command as typed, then the verbatim stdout from Step 1>

Reading it the way the gate does: `<lines>` product lines and `<files>` product files, both
under ≤1,000 / ≤20, so this branch's own size prerequisite is satisfied. The `excluded: …
<n> artifact` count is the spec and the plan — the two artifact files this run had committed when
the range was measured. The invocation also names this evidence file, which is still uncommitted
at that moment and so matches no row and contributes nothing; naming it costs nothing (an
unmatched `--artifact-path` is deliberately not an error, per D3) and it starts counting on any
re-run made after this document is committed. One path per file throughout, never
`<specDir>`/`<planDir>`.

**Re-run this command fresh at ship time.** These integers are a snapshot at the SHA above;
review fixups and the Phase-1 sync merge both move the range, so the PR body must quote a run
made after the branch's final commit, not this one.
```

- [ ] **Step 3: Sweep every gate**

```bash
set -o pipefail   # without it a pipeline returns tail's status and a failing gate reads as 0
just agent-workflow-tests 2>&1 | tail -5
git diff --numstat "$(git merge-base HEAD origin/main)"..HEAD -- home/
just evals ship-issue 1 | grep -c "≤1,000 product lines"
grep -rn "≤400\|--numstat" home/common/agent-skills/skills/ship-issue/SKILL.md | wc -l
grep -c "product: " .claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md
just build 2>&1 | tail -3
```

Expected, in order: `Ran 158 tests` … `OK`; exactly three rows, each `1	1	…` for `SKILL.md` and
`evals.json` and a larger pair for the test module, and nothing else under `home/`; `1`; `0`
(the retired boundary and the retired command are gone from the skill); `1` (the evidence file
really carries a helper reading); `just build` exits 0.

- [ ] **Step 4: Commit**

```bash
git add .claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md
git commit -m "$(cat <<'EOF'
docs(issue-22): record the A10 diff-scope run for the retuned gate

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Route the evidence to the ship phase**

The ship handoff carries `spec_path`, `plan_path` and a free-form summary — it has no field for
this document, so nothing delivers it automatically. This task is not complete until its report
back to the executing skill names, in that summary, **the evidence file's path and the obligation
to re-run its command fresh after the branch's final commit**. Without that line the ship owner
quotes stale integers or omits the A10 evidence entirely.

**Criteria covered:** A10, and a final re-check of A1–A9.

---

## Acceptance criteria → task map

Criteria IDs are the spec's (`## Acceptance criteria`, A1–A10).

| # | Task | Gate that observes it |
|---|------|-----------------------|
| A1 | 1 | `just agent-workflow-tests` — the whole prescribed invocation present as one span in the gate section, `--numstat` and `--root` absent |
| A2 | 1 | same test — `GATE_LINE_BOUNDARY` / `GATE_FILE_BOUNDARY` present, `400` absent |
| A3 | 1 | same test — the carve-out sentence present, and the asserted span carries `--artifact-path <spec_path> --artifact-path <plan_path>` in full, so a gate naming only one path fails; demonstrated in Task 3's recorded run |
| A4 | 1 | same test — `No measurement` / `is not a small diff` present |
| A5 | 1 | same test — `assert_ordered` over the four prerequisites; plus `git diff --numstat … -- SKILL.md` = `1	1` |
| A6 | 2 | `just agent-workflow-tests` (SKILL↔eval agreement test) **and** `just evals ship-issue 1 \| grep -c "≤1,000 product lines"` = 1 (manual-grade leg; plan-only, so the grep is the observation) |
| A7 | 1 | `just agent-workflow-tests` — `test_helper_binaries_resolve_from_bare_names`, `skill='ship-issue'` subTest |
| A8 | 1, 2, 3 | `just build` exits 0 |
| A9 | 1, 2 | `grep -c "1,000"` and `grep -c "20 product files"` over the test module both = 1 |
| A10 | 3 | the recorded direct-script run, committed as the evidence document (evidence, not a gate — per D11) |

**Not gated, by design:** the issue's behavioural criteria (a 900-line branch degrades, a
1,100-line branch does not). The gate is prose an agent follows, so no unittest over markdown
can execute them (per D6); eval 1 grades them by hand and Task 3's run demonstrates the
measurement they rest on.

## Standards review provenance

- Reviewer: **Codex** (`codex-collaboration` `plan-review`, isolated fresh runtime, approval
  policy `never`, sandbox `read-only`). No fallback used.
- Base SHA reviewed: `fc498cb732ce8378711739c62463e5285e36133c`; plan at commit `1f07435`.
- Focus: none configured (`codex.planReview.focus` unset).
- Findings: **3 Blocking, 2 Should-fix, 0 Discussion — 5 accepted and applied, 0 rejected,
  0 deferred.** All five were re-verified against the live plan and worktree before being applied.
  - Blocking: pre-commit numstat checks compared `base..HEAD` and so could not see the working-tree
    edit they gate (Tasks 1, 2); piped `tail` discarded the producer's exit status, so the
    "`just build` exits 0" gate was unobserved (all tasks); Task 3's evidence prose asserted an
    artifact count that is impossible at the moment it is measured.
  - Should-fix: the gate-contract test asserted fragments the acceptance map claimed as a whole
    invocation (per D13); the evidence document had no route to the ship owner (per D14).
- Raw reviewer transcript is deliberately not stored in this repository.

## Residuals carried out of this plan

- `from-issue/investigate.md`'s C4 note still restates the artifact exclusion in numstat terms
  (per D10) — recorded, not resolved.
- The retuned gate governs no live run until the next `just switch`; until then a `ship-issue`
  run reads the activated generation's older gate. Out of scope, and the reason A10 is evidence
  rather than a demonstration of degradation.
