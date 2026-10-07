# Issue #274 — Type and locate every acceptance criterion at authoring and planning

Slice S3 of the [acceptance-criteria gate design](2026-10-06-acceptance-criteria-gate-design.md)
(the parent). The parent's decisions D1–D11 bind this slice; D2 (inline closed
kinds) and D9 (the map is a grading input, not a prerequisite) bind it most
directly. Rows below are this issue's own (D1–D8 here); parent rows are cited as
"parent D<n>".

## Problem

A criterion's author knows whether it is a test, a measurement, or a human
judgment and where it is observed, but the issue template has no place to say
so, and the plan has no surface that maps criteria to the tasks and checks that
will satisfy them. A criterion nobody owns stays invisible until grading, which
is how #262 closed with two unmeasured criteria. The grading side (S1, #272)
needs both inputs to exist; this slice creates them.

## Solution

1. **Authoring.** The `to-issues` template's criterion lines take the shape
   `- [ ] [code|evidence|human] <outcome> — measured: <where>`. The skill states
   the three kinds as the parent defines them, the kind-preference rule (prefer
   `code`, then `evidence`; `human` only when no agent can produce the
   observation), the evidence clause (command, conditions, literal threshold),
   and extends the falsifiability rule to the `measured:` clause.
2. **Planning.** `writing-plans` adds a required root section,
   `## Acceptance map`, with one row per issue criterion and a matching
   self-review item.
3. **Plan review.** `REVIEW-CONTRACT.md` gains a blocking acceptance-map check,
   which reaches the native reviewer and the Codex plan-review route alike
   because both read the contract by path.
4. **Evals.** Fixture issue `001-well-specified` carries tagged criteria, and the
   two evals that plan from it (from-issue eval 1, writing-plans eval 1) grade a
   map row for each one.
5. **Guard.** The dispatch-marker inventory gains a pinned count, proving the
   slice adds no agent.

## Decisions

**Criterion line (per D1).** The literal shape is
`- [ ] [<kind>] <observable outcome> — measured: <where>`, with `<kind>` one of
`code`, `evidence`, `human` and `measured:` naming one place: for `code`, a
test, check or CI job; for `evidence`, the command, the conditions it runs
under and a literal threshold (`≤ 90 s per module, serial, idle mbp`); for
`human`, who judges and in what environment. The template shows the tag and the
clause on every placeholder line. The falsifiability paragraph gains one
sentence: the `measured:` clause must name an observation that fails at the
base commit, and an evidence threshold is a literal number or string, never
"faster" or "reasonable".

**Acceptance map (per D2, D3, D4).** A root-plan section placed directly after
`## Task index`. It is a pipe table, `| AC | Kind | Task | Check |`, with one
row per criterion in issue order, `AC1` to `AC<n>`:

- `Kind` copies the issue's tag. An untagged (legacy) criterion is classified by
  the planner and written `<kind> (classified)`; a tagged criterion is never
  reclassified.
- `Task` names exactly one owning task, `Task N`, from the index. When several
  tasks contribute, the owner is the task that adds or runs the check.
- `Check` names the test, check or CI job for `code`; the command, the
  conditions, the literal threshold and the acceptance-record row `AC<n>` the
  owning task's implementer fills in for `evidence`; the attesting judgment for
  `human`. The record file itself and its columns belong to S1 (parent D4).
- The criteria come from the issue the plan serves, or, with no issue, from the
  requirements document's acceptance criteria. With none, the section holds the
  single line `None — no acceptance criteria.`

The map is the plan's only acceptance surface (parent D9); it replaces nothing
in the task bodies, whose verification lines stay as they are.

**Plan-review check (per D5).** A new `## Acceptance map check` section in
`REVIEW-CONTRACT.md`, before the common-miss checklist, lists what is
**Blocking**: the section is missing; a criterion has no row or more than one;
rows are out of issue order; a kind is outside the closed set or contradicts the
issue's tag; an owning task is not in the index; an `evidence` row lacks its
command, conditions or threshold. A `(classified)` kind the reviewer disagrees
with is Should-fix, with the reviewer's proposed kind.

**Fixture and eval grading (per D6, D7).** Fixture 001's seven numbered criteria
become seven `- [ ] [code] … — measured: tests/test_cli.py` lines, same order and
meaning (criterion 6 by a `--help` output test the implementer adds there).
Fixtures 002 and 003 stay untagged, as the legacy shape the planner classifies.
The eval assert library gains one helper, `acceptance_map_covers <plan-root>
<issue-file>`: it counts the issue's top-level criterion items (`- [ ]` or `<n>.`) under
`## Acceptance criteria` and passes only when the plan root's
`## Acceptance map` holds rows `AC1`…`AC<n>`, each exactly once and in order,
whose kind matches the issue tag (or carries `(classified)` for an untagged
line). Both evals add a named assert calling it.

**Marker guard (per D8).** `test_dispatch_contracts.py` pins the total number of
`<!-- agent-dispatch:` markers across the source skill trees as a literal, the
count at the plan's base commit. S1 changes one marker's model, not the count,
so the two slices do not contend over the value. A later change that adds a
marker updates the literal in the same commit, which is the point of the pin.

## Test seams

All seams already exist; `just agent-workflow-tests` runs them.

1. **Skill-text contract tests** (`test_workflow_skill_contracts.py`), asserting
   phrases, not prose: the template's `[code|evidence|human]` tag and
   `— measured:` on every criterion line; the kind-preference rule and the
   extended falsifiability sentence; writing-plans' `## Acceptance map` section,
   its `| AC | Kind | Task | Check |` header and its self-review item;
   `REVIEW-CONTRACT.md`'s acceptance-map check naming a missing row as Blocking.
2. **The eval assert library**, executed from unittest by sourcing the real
   `assert-lib.sh` (prior art: `run_assertion_shell` already runs eval shells in
   that file). Cases: a conforming plan passes; a missing row, a duplicate row,
   an out-of-order row and a kind contradicting the issue tag each fail. The
   live-eval grading test additionally asserts both evals call the helper and
   that fixture 001 has seven tagged criterion lines.
3. **The dispatch-marker inventory** (`test_dispatch_contracts.py`), per D8.

The `artifact-budget` plan parser needs no change: the task index ends at the
next `## ` heading, and map rows start with `|`, never `Task `.

## Out of scope

- Grading criteria, the acceptance record's file and columns, `acceptance_state`,
  and ship's hold branch (S1 #272, S2 #273). No sdd file is touched.
- Retagging existing open issues or fixtures 002/003.
- A parser or validator of criterion lines or the map outside the eval helper;
  the plan reviewer judges the map.
- An evidence criterion in the tinytask fixture.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Criterion line is `- [ ] [<kind>] <outcome> — measured: <where>`; evidence `where` = command, conditions, literal threshold; preference code > evidence > human; falsifiability rule extends to the `measured:` clause. | Parent D2 and its Decisions; issue AC1; to-issues "the body is the contract". | A separate "Measured" sub-list per criterion: splits one contract line in two and drifts. |
| D2 | The map is a root section directly after `## Task index`, a pipe table with columns AC, Kind, Task, Check, rows `AC1..AC<n>` in issue order, exactly one owning `Task N` each (the task that adds or runs the check). | Parent S3 row shape; `artifact-budget` ends the index at the next `## ` and requires every `Task `-prefixed index line to be an index row. | Map rows inside task members: no single place to check coverage, and the reviewer must read every member to find a gap. |
| D3 | A tagged criterion's kind is copied, never reclassified; an untagged one is classified by the planner and written `<kind> (classified)`. | Parent D2 (planner classifies legacy criteria); the issue tag is the author's contract. | Unmarked classification: the reviewer and grader cannot tell an author's tag from a planner's guess. |
| D4 | Evidence rows name the record row `AC<n>` only; the record's file and columns are left to S1. With no criteria, the map holds `None — no acceptance criteria.`; with no issue, criteria come from the requirements document. | Parent D4 assigns the record to sdd (S1, #272 in flight); keep this slice off sdd. | Defining the record file here: two slices would own one format. |
| D5 | The review check is its own `REVIEW-CONTRACT.md` section; structural gaps are Blocking, a disputed `(classified)` kind is Should-fix. | Parent: "REVIEW-CONTRACT.md blocks a missing row"; codex PLAN-REVIEW reads the contract by path, so one edit covers both routes. | Blocking a disputed classification: a judgment call is not a structural gap, and the grader re-judges it anyway. |
| D6 | Fixture 001's seven criteria become `[code]` lines measured by `tests/test_cli.py`; 002/003 stay untagged. | Issue AC3; legacy untagged criteria must stay plannable (parent D2). | Adding an evidence criterion to tinytask: changes the fixture's meaning for no grading gain in this slice. |
| D7 | Eval grading is one assert-lib helper, `acceptance_map_covers`, used by from-issue eval 1 and writing-plans eval 1, and unit-tested by sourcing the real `assert-lib.sh`; it counts checkbox and numbered criterion items, so legacy issues grade too. | Both evals plan from fixture 001; existing helpers (`ledger_has_rows`) are the eval-grading home; DRY. | An inline awk in each evals.json: two copies of one rule; a string-presence-only test would never fail on a broken helper. |
| D8 | AC4 is measured by a new literal total-marker-count pin in `test_dispatch_contracts.py`, valued at the plan's base. | Issue AC4 names that file's marker count, which does not exist yet; S1 changes a marker's model, not the count. | Relying on the model-matrix registry alone: it catches an unregistered marker, not a registered new one. |
| D9 | The `measured:` clause is the one place an issue body may name a test, file or command; `to-issues`' "no file paths" rule gains that exception. | Parent D2 (`measured: <test, check or CI job>`); #274's own criteria name test files; a grader reruns what the clause names. | Keep "no file paths" absolute and describe checks in prose: a described check cannot be rerun. |
| D10 | `acceptance_map_covers` matches both headings case-insensitively, counts column-0 `- [ ]`/`- [x]` and `<n>.` items, requires an exact kind for a tagged item and `<kind> (classified)` for an untagged one, and with zero criteria passes only on the `None — no acceptance criteria.` line with no rows. Its unit tests and the other #274 contract tests are new `TestCase` classes appended to the named test files. | Spec D4, D7; `assert-lib.sh` heading-case precedent; #272 concurrently edits the shared test file's existing classes. | Vacuous pass on zero criteria: an unparsed criteria section would grade green. |
