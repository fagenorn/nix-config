---
name: writing-plans
description: Turns a spec into a task-by-task implementation plan. Use when multi-step work needs a plan before code.
---

# Writing Plans

Write for a skilled engineer with no context on this codebase, toolset or domain, who reads exactly one task and none of the others. Every task names the files it touches, the exact interfaces and invariants it must satisfy, and how to test and verify it. DRY, YAGNI, test-first, frequent commits.

**Resolve once at entry.** Run `resolve-project resolve --repo-root <the checkout you were called in>` and read the absolute `bindings.paths.artifacts.plans` from the snapshot it prints. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Never persist the snapshot or infer a policy value.

**Save the package root to** `<bindings.paths.artifacts.plans>/YYYY-MM-DD-<feature-name>.md` and its task members to the sibling `<stem>.tasks/` directory (`<stem>.tasks/task-1.md` first), committed in the worktree you were called in. The root path is the public plan path (D3, D6).

## Payload discipline

Sibling skills cite this section and plans embed it in tasks. Move information as cheaply as it arrives: targeted `rg` over whole-file reads; bounded reads around the lines that matter; test and build output summarized to the failing lines; long logs written to disk and passed as paths; artifacts (briefs, packages, reports) handed between agents as paths, never inlined. Verification commands produce small output by construction (quiet flags, filters, tails).

## Scope and file structure

A spec covering several independent subsystems gets one plan per subsystem, each yielding working, testable software; say so rather than fusing them.

Before defining tasks, map the files to create or modify and each one's responsibility: one clear responsibility per file, files that change together kept together, split by responsibility rather than layer, existing patterns followed. Split a file you are already modifying when it helps; never restructure unilaterally.

When the map depends on one bounded repository fact, keep the planning judgment here and delegate only the read-only lookup:

<!-- agent-dispatch: id=planning-bounded-fact-lookup role=explorer model=sonnet effort=medium -->
Agent(subagent_type="Explore", model="sonnet", effort="medium") performs one sharply bounded read-only repository lookup without choosing task boundaries.

If the lookup turns open-ended, ambiguous or judgment-bearing, stop the cheap-tier run and re-dispatch the `issue-owner` on Opus/high; record that escalation and the selected role in the plan phase's existing fixed-schema report.

## Task size

A task is the smallest unit with its own test cycle that is worth a fresh reviewer's gate: fold setup, configuration, scaffolding and documentation into the task that needs them, and split only where a reviewer could reject one task while approving its neighbour. Every task ends in an independently testable deliverable. Steps are one action each: write the failing test, watch it fail, write the minimal implementation, run the tests, commit.

## Plan root

The root holds the header below and no numbered task bodies or copied ledger rationale; numbered tasks live only in members (D3).

```markdown
# <Feature> Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** <one sentence>

**Architecture:** <2–3 sentences on the approach>

**Tech stack:** <key technologies and libraries>

## Global Constraints

<The spec's project-wide requirements (version floors, dependency limits, naming
and copy rules, platform requirements), one line each, values copied verbatim.
Every task implicitly includes this section.>

## Test seams

<The seams the spec agreed, one line each. Implementers test only at these; a
task needing a new seam is a plan bug.>

## Delivery estimate and boundaries

<Expected changed files, likely aggregate-growth risks, and independently
deliverable slices when the change may exceed a review-package boundary. Every
number is labelled an estimate.>

## Task index

<One line per task: ID, title, files touched, risk lane, and member link. Members
are numbered contiguously from 1, one row each, at most eight. Every row ends
exactly in `[task-N.md](<stem>.tasks/task-N.md)`. Lanes:
- `mechanical` — deletion/renaming with no behavioral, configuration, interface,
  generated-output, or semantic-documentation effect.
- `low-risk` — small semantic changes: bounded, locally-verifiable behavior
  changes — excluding anything touching concurrency, lifecycle, destructive
  operations, security, release, migration, or public contracts.
- `full` — everything else.

Example: `Task 3 — Wire settings loader — src/config.py, tests/test_config.py — low-risk — [task-3.md](2026-08-19-feature.tasks/task-3.md)`>

## Acceptance map

<One row per acceptance criterion of the issue this plan serves, in issue order
(with no issue, of the requirements document). With no criteria, this section
holds the single line `None — no acceptance criteria.` Otherwise:

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 3 | `tests/test_config.py::test_loader_rejects_unknown_key` |

- `AC` — `AC1` to `AC<n>` in issue order, each exactly once.
- `Kind` — the issue's `[code|evidence|human]` tag, copied and never
  reclassified; an untagged criterion gets your judgment, written
  `<kind> (classified)`.
- `Task` — exactly one owning `Task N`: the task that adds or runs the check.
- `Check` — `code`: the test, check or CI job; `evidence`: the command, its
  conditions, the literal threshold and the acceptance-record row `AC<n>` the
  owning implementer fills in; `human`: the judgment and who makes it.

This map is the plan's only acceptance surface.>

## Decisions

<Cite the spec's `## Decision ledger` rows by ID ("per D3"); never copy them. A
new non-obvious decision forced by planning (scope, interface, behavioral,
test-seam, irreversible, user-preference) is appended to the spec's ledger and
cited. Routine splits, commit boundaries and obvious verification get no row;
merge related decisions into one.>

---
```

## Task members

Write each task to exactly `<stem>.tasks/task-N.md`, self-contained for one implementer: exact interfaces, invariants, assertions, verification commands, and step-by-step decisions where an algorithm embodies one. Full implementation code appears only when it preserves a decision prose and interfaces cannot (a subtle algorithm, an exact wire format). Failing tests are always written out in full: they are the contract. Cite decision IDs instead of copying Global Constraints or rationale, and carry every task-specific value (D3).

````markdown
# Task N: <Component>

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py`
- Test: `tests/exact/path/to/test.py`

**Interfaces:**
- Consumes: <what this task uses from earlier tasks — exact signatures>
- Produces: <what later tasks rely on — exact names, parameter and return types>

**Invariants:**
- <properties this task preserves, one per line, phrased so a test can pin them>

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL — `function` is not defined

- [ ] **Step 3: Write the minimal implementation**

<The exact signature, the invariants and assertions it satisfies, and the
non-obvious decisions of its algorithm; full code only under the carve-out.>

```python
def function(input: InputType) -> Expected:
    """Contract: <the invariant this function pins>."""
```

- [ ] **Step 4: Verify**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS, 1 test, no warnings

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

**Every task has a verification line that can fail**: a command and the observation that would show the task incomplete, which must hold at the commit the implementer starts from. A shell gate needs care: `set -e` exempts a `!`-inverted command, so `! grep <forbidden> <file>` never aborts; write `if grep -q <forbidden> <file>; then exit 1; fi`. A terminal `grep -c` inverts the sense too: zero matches, the passing case, exits 1.

**Each task names its focused test commands**, red then green, plus the project's build check only when the task changes files that check evaluates (add it when unsure). No task runs the full declared verification as a per-task gate; sdd's final gate runs it once on the final head. Global Constraints may still name those commands with their timeouts.

**Scope every gate to the plan's files.** Give diffs a pathspec (`git diff --stat BASE..HEAD -- <the paths named in the plan's Files: blocks>`) or assert on file content; never expect a raw commit range ("exactly three files changed", "every commit is a `feat:`"), because plan and spec commits and a ship-time sync merge land in it too. Where commit shape is truly under test, restrict to the branch's own commits (`git log --no-merges BASE..HEAD ^origin/<integration-branch>`) and exempt the artifact and review-fixup subjects.

## No placeholders

Never write "TBD", "TODO", "implement later", "fill in details"; "add appropriate error handling", "add validation", "handle edge cases"; "write tests for the above" without the tests; "similar to Task N" (tasks are read alone, so restate the interfaces, invariants and assertions); a step that does not pin its exact interface, invariants and assertions; or a type, function or method no task defines.

## Package budget

Finish all content first, then run `artifact-budget check --kind implementation-plan --root <root-path> --format json`; the checker discovers the members and owns the thresholds. Never pass or report a member list (D5, D6, D8).

- Exit 0 with `within_budget`: measured.
- Exit 2: `failed`, with no prose fallback.
- First exit 3: compact repeated prose into root or spec references, keeping task-specific contracts, and check again. Still over: split only where both halves are independently testable, update the contiguous index and links, and check again. Any root, member, count or aggregate violation that persists returns `decompose_required`; `complete` is forbidden (D5).

Measure after the final mutation, and check the amended spec too when planning appended a ledger row. Any later writer, an accepted Phase-5 edit included, checks every artifact it changed before advancing (D5, D14).

## Self-review

Reread the finished plan against the spec yourself (no dispatch) and fix inline:

1. **Spec coverage**: every requirement maps to a task.
2. **Placeholders**: none of the patterns above.
3. **Type consistency**: later tasks use the names earlier tasks define (`clearLayers()` vs `clearFullLayers()` is a bug).
4. **Falsifiability and scope**: every task has a gate that can fail, and none asserts over an unscoped range.
5. **Task index**: one row per member, contiguous, each ending in its link, files and lane matching the body; a `mechanical` or `low-risk` lane for excluded work is a bug. The root holds no numbered task body.
6. **Members**: exact files, consumed and produced interfaces, invariants, complete failing tests, implementation actions, a scoped falsifiable gate, decision IDs and commit scope.
7. **Acceptance map**: one row per issue criterion in order, kinds copied or `<kind> (classified)`, owners in the index, `evidence` rows with command, conditions and threshold.
8. **Remeasure** the package after the last edit, and the spec if a ledger row was appended.

## Return control

Build one producer report `{state, artifact, notes}` (D11, D14). `complete`: `kind: "implementation-plan"`, the root `path`, the checker's four `metrics` and `budget_status: "within_budget"`. `decompose_required`: the same with `budget_status: "over_budget"` and the checker's `violations`. `failed`: a null artifact, or only the known root `kind` and `path`. Notes may point to the root or spec, within shared policy; never artifact contents or member paths.

Write it to a candidate from `mktemp "${TMPDIR:-/tmp}/producer-report-XXXXXX.json"`, run `artifact-budget validate-report --boundary producer --input <report-candidate>`, and remove the candidate in a cleanup that runs on every outcome (a `trap` on `EXIT HUP INT TERM`, or `finally`). Return only the validated stdout; validator exit 2 is `failed`, with no fallback. Do not offer or start execution: the caller owns standards review and execution.
