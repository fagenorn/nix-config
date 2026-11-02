---
name: writing-plans
description: Turns a spec into a task-by-task implementation plan. Use when requirements for multi-step work need a plan before code.
---

# Writing Plans

Write for a skilled engineer with no context on this codebase, toolset or domain who reads one task and no other. DRY, YAGNI, test-first, frequent commits.

**Resolve once at entry.** Run `resolve-project resolve --repo-root <the checkout you were called in>` and read the absolute `bindings.paths.artifacts.plans` from the snapshot it prints. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Never persist the snapshot or infer a policy value.

**Save the package root to** `<bindings.paths.artifacts.plans>/YYYY-MM-DD-<feature-name>.md` and its task members to the sibling `<stem>.tasks/` directory (`<stem>.tasks/task-1.md` first), committed in your worktree.

## Payload discipline

Move information cheaply: targeted `rg` over whole-file reads; bounded reads; test and build output cut to failing lines; long logs on disk, passed as paths; artifacts (briefs, packages, reports) handed between agents as paths, never inlined. Verification commands print little (quiet flags, tails).

## Scope and file structure

A spec covering several independent subsystems gets a plan each.

Before mapping files, read the spec's **code map** if one exists: the path your caller named, else the spec's file name with `.code-map.md` for `.md` in the git directory (`git rev-parse --git-dir`). Its entries are leads: check every mapped path and symbol you write into a task against the current tree, and drop a wrong entry. Never cite or copy it into the plan: implementers and reviewers cannot see it.

Before defining tasks, map the files to create or modify and each one's responsibility: one per file, files that change together kept together, split by responsibility not layer, existing patterns followed. Never restructure alone.

When the file map depends on one bounded repository fact, keep the planning judgment here and delegate only the read-only lookup:

<!-- agent-dispatch: id=planning-bounded-fact-lookup role=explorer model=sonnet effort=medium -->
Agent(subagent_type="Explore", model="sonnet", effort="medium") performs one sharply bounded read-only repository lookup without choosing task boundaries.

If the lookup turns open-ended or judgment-bearing, stop the cheap-tier run and re-dispatch the `issue-owner` on Opus/high, recording the escalation in the plan phase's fixed-schema report.

## Task size

A task is the smallest unit with its own test cycle worth a reviewer's gate: fold setup, configuration, scaffolding and documentation into the task needing them, and split only where a reviewer could reject one task while approving its neighbour. Each ends independently testable.

## Plan root

The root holds the header below, no numbered task bodies, no copied ledger rationale.

```markdown
# <Feature> Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** <one sentence>

**Architecture:** <2–3 sentences on the approach>

**Tech stack:** <key technologies and libraries>

## Global Constraints

<The spec's project-wide requirements (version floors, dependency limits, naming
and copy rules, platform requirements), one line each, values verbatim.>

## Test seams

<The spec's agreed seams, one line each. Implementers test only at these; a new
seam is a plan bug.>

## Delivery estimate and boundaries

<Only the rationale for each boundary, one line each; the numbers live in the
committed forecast blocks.>

## Task index

<One line per task: ID, title, files touched, risk lane, member link. Members
are numbered from 1, at most eight. Every row ends exactly in
`[task-N.md](<stem>.tasks/task-N.md)`. Lanes:
- `mechanical` — deletion/renaming with no behavioral, configuration, interface,
  generated-output or semantic-documentation effect.
- `low-risk` — bounded, locally-verifiable behavior changes, excluding anything
  touching concurrency, lifecycle, destructive operations, security, release,
  migration or public contracts.
- `full` — everything else.>

## Acceptance map

<One row per acceptance criterion of the issue this plan serves, in issue order
(with no issue, of the requirements document). With no criteria, this section
holds the single line `None — no acceptance criteria.` Otherwise:

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 3 | `tests/test_config.py::test_loader_rejects_unknown_key` |

- `AC` — `AC1` to `AC<n>` in issue order, each once.
- `Kind` — the issue's `[code|evidence|human]` tag, never reclassified; an
  untagged criterion gets your judgment, written `<kind> (classified)`.
- `Task` — the one `Task N` that adds or runs the check.
- `Check` — `code`: the test, check or CI job; `evidence`: the command, its
  conditions, the literal threshold and the acceptance-record row `AC<n>` the
  owning implementer fills in; `human`: the judgment and who makes it.>

## Decisions

<Cite the spec's `## Decision ledger` rows by ID ("per D3"), never copied. A
new non-obvious decision forced by planning (scope, interface, behavioral,
test-seam, irreversible, user-preference) is appended to the ledger and cited;
routine choices get no row.>

---
```

## Task members

Write each task to exactly `<stem>.tasks/task-N.md`, self-contained for one implementer: exact interfaces, invariants, assertions, verification commands, and step-by-step decisions where an algorithm embodies one. Full implementation code appears only where prose and interfaces cannot preserve a decision (an exact wire format). Write failing tests out in full. Cite decision IDs instead of copying Global Constraints or rationale; carry every task-specific value.

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

- [ ] **Step 4: Verify**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS, 1 test, no warnings

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

**Every task has a verification line that can fail**: a command and the observation that would show the task incomplete, confirmed by hand at the commit the implementer starts from. `set -e` exempts a `!`-inverted command, so write `if grep -q <forbidden> <file>; then exit 1; fi`, not `! grep`; a terminal `grep -c` exits 1 on zero matches, the passing case.

**Each task names its focused test commands**, red then green, plus the project's build check only when the task changes files that check evaluates. No task runs the full declared verification; sdd's final gate runs it once on the final head.

**Scope every gate to the plan's files.** Give diffs a pathspec (`git diff --stat BASE..HEAD -- <the plan's Files: paths>`) or assert on file content; never expect a raw commit range, because plan and spec commits and a ship-time sync merge land in it too. Where commit shape is under test, restrict to the branch's own commits (`git log --no-merges BASE..HEAD ^origin/<integration-branch>`), exempting artifact and review-fixup subjects.

## No placeholders

Never write "TBD", "TODO", "implement later", "fill in details"; "add appropriate error handling", "add validation", "handle edge cases"; "write tests for the above" without the tests; "similar to Task N" (tasks are read alone); a step that does not pin its interface, invariants and assertions; or a type, function or method no task defines.

## Review feasibility forecast

The root carries one `## Review feasibility delivery` block and each member one `## Review feasibility task` block, each a heading and one fenced `json` line of canonical JSON. Field semantics: nix-config's `python/README.md` § Review feasibility forecast.

- Delivery: `schema_version` 3, `kind`, `delivery_base`, `proposed_boundary`, `boundaries`, `process_records`, `actual_evidence` (`kind: git-range-ownership/v1`, the base's head and tree, no `process_ranges`) and `derived_from: null`.
- Boundaries: the root holds every task, children partition their parents; `depends_on` chains carry `completed-tasks` prerequisites with null `commit` and `tree`; each has its own `process_package`, `process_forecast_ids` and one 64-byte `process_commit_subject_bytes` entry per future process commit.
- Task: a record per `Files:` path, one `authored-cumulative/v1` bound per containing boundary, conservative whole-record sizes including fix rounds, recordings and the Phase-5 edit.

## Package budget

Finish all content, then run `artifact-budget check --kind implementation-plan --root <root-path> --format json`; the checker discovers the members and owns the thresholds. Never pass a member list.

- Exit 0 with `within_budget`: measured.
- Exit 2: `failed`, with no prose fallback.
- First exit 3: compact repeated prose into root or spec references, keeping task-specific contracts, and recheck. Still over: split only where both halves are independently testable, update the contiguous index and links, and recheck. A persisting violation returns `decompose_required`; `complete` is forbidden.

Any later writer, an accepted Phase-5 edit included, first checks every artifact it changed.

**Projection gate.** After the final mutation (self-grade edits included) and a `within_budget` check, pin `<base>` with `git merge-base HEAD origin/<integration-branch>`, commit, then run `review-feasibility gate --plan <root> --base <base> --head <HEAD> --completed-through 0 --save-dir "$(sdd-workspace <root>)"` (`<HEAD>` is `git rev-parse HEAD`), which keeps the full validated result.

- Exit 0: `complete`, the printed summary as `projection`.
- Exit 3: `decompose_required`, its artifact still `within_budget`, plus `projection`.
- Exit 2: one forecast correction round (commit, rerun), then `failed` with the tool's reason in notes.

An artifact overage keeps the over-budget report below, without `projection`.

## Self-review

Reread the finished plan against the spec yourself, no dispatch, and fix inline:

1. **Spec coverage**: every requirement maps to a task.
2. **Type consistency**: later tasks use the names earlier tasks define.
3. **Members**: the whole member template, a scoped falsifiable gate, decision IDs, commit scope.
4. **The rules above**: no placeholders; an index row per member with matching files and lane (a `mechanical` or `low-risk` lane for excluded work is a bug); a complete acceptance map; no numbered task body in the root.
5. **Remeasure** the package after the last edit, and the spec after a ledger row.

## Return control

Build one producer report `{state, artifact, notes}`. `complete`: `kind: "implementation-plan"`, the root `path`, the checker's four `metrics`, `budget_status: "within_budget"` and `projection`. `decompose_required`: the same with `budget_status: "over_budget"` and the checker's `violations`, or `within_budget` plus `projection`. `failed`: a null artifact, or only the known root `kind` and `path`. Notes never carry artifact contents or member paths.

Write it to a candidate from `mktemp "${TMPDIR:-/tmp}/producer-report-XXXXXX.json"`, run `artifact-budget validate-report --boundary producer --input <report-candidate>`, and remove the candidate in a cleanup that runs on every outcome (a `trap` on `EXIT HUP INT TERM`, or `finally`). Return only the validated stdout; validator exit 2 is `failed`, with no fallback. Offer or start no execution: the caller owns review and execution.
