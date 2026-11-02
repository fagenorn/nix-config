# Phase-5 plan review contract

Use only the binding values and capability states the caller supplies; never resolve or infer policy. You receive the plan root path and its four checker metrics, the spec path, the issue number, `bindings.tracker`, `bindings.paths` and the review capability. Never inline this file.

## Reviewer instructions

Review the implementation plan at `<plan-path>` against the project's coding bar.
Before reviewing, read the root and every indexed member in checker discovery
order. Explicitly report an unreadable member as a blocking contract failure;
never fall back to monolithic task parsing.

First ground with the retained `bindings.paths.context`, `bindings.paths.standards`,
and `bindings.paths.architecture` lists plus `capabilities.knowledge.*`: the caller
passes the selected map (if any), its selected areas and ADR paths, and the
standards paths that apply. With no selected map, use only those passed context
paths. Read the issue body through `bindings.tracker.cli` after unsetting only
names in `bindings.tracker.credential_env.unset_before_invocation`, then read the
spec at `<spec-path>` and the validated plan root plus every member.

When checking specific findings, **read the live file at HEAD**, not a snapshot or diff view.

For each plan task, flag anything that violates the grounded constraints. Every
finding identifies its affected task member or root section. Explicitly report
any member that could not be read. Pay particular attention to:
framework-first (custom executors/state machines where a framework primitive already exists),
production-grade-by-default (half-finished branches, missing error paths at boundaries), DI rules, and
the test-fixture conventions in the project's standards shards (or legacy coding-standards doc).

If the caller passes applicable `bindings.paths.hints` paths, read them for
project-specific review hints and fold those into this pass.

## Acceptance map check

Read the issue's acceptance criteria (or, with no issue, the requirements
document's) and the plan root's `## Acceptance map`. Each of these is **Blocking**:

- the `## Acceptance map` section is missing;
- a criterion has no row, or more than one;
- rows are out of issue order (`AC1` to `AC<n>`);
- a kind is outside `code`, `evidence`, `human`, or contradicts the issue's tag;
- an owning task is not a `Task N` in the Task index;
- an `evidence` row lacks its command, its conditions or its literal threshold.

A `(classified)` kind you disagree with is **Should-fix**: give the kind you would
assign and why.

## Common-miss checklist

Scan against these categories.

- **UX alternate-dismiss paths.** Modal/dialog/typed-confirmation/destructive-action surfaces must
  specify state-reset behavior for every *user-reachable* dismiss path. Your finding for this category
  must include an itemized checklist — one line per path, marked with what the plan says (or "not
  specified") for each:

  ```
  - [ ] X button: <plan's behavior or "not specified">
  - [ ] Cancel button: <…>
  - [ ] Esc key: <…>
  - [ ] Overlay click: <…>
  - [ ] Browser back / navigation away: <…>
  - [ ] Programmatic close (e.g. on success): <…>
  ```

  Any **user-reachable** path the plan doesn't address is a Blocker. A path
  that's not user-reachable on this surface (e.g. no programmatic close because there's no success
  state) is fine — say so explicitly in the checklist, don't omit the row.
- **Boundary-error fallbacks at unfamiliar-principal / missing-entity points.** Auth user that doesn't
  exist, admin not yet seeded, feature flag missing, downstream table empty. Does the plan name the
  failure mode and the graceful path, or does it assume the happy path? "Production-grade by default"
  fires here.
- **Defensive guards against future refactor.** When the plan introduces a `switch` on an enum, a
  polymorphic dispatch, a base-class extension, or a new arm of an exception hierarchy — does it
  specify what *fails loudly* when the type/enum/hierarchy is extended later, so the next contributor
  doesn't silently fall into a default branch?
- **Plan-prose / live-code parity.** Any docstring, comment, context-doc sentence, or ADR clause the
  plan tells the implementer to write — does the wording match what the code will *actually* do?
- **Stale prose audit.** Distinct from the bullet above: that one checks prose the plan *dictates the
  implementer write*; this one checks prose that *already exists* in files adjacent to the diff. For
  every context-doc sentence, ADR clause, docstring, or comment near the PR's footprint, re-read the
  live file. Terminology the PR retires (renamed concepts, deprecated class names, removed fields) must
  be purged in *all* adjacent comments and doc references — not just the diff's immediate footprint.
- **Dead branches after iteration.** If Phase 4 → Phase 5 revisions changed the design (e.g. "use the
  framework's collapsible primitive" replacing hand-rolled state, "switch from an explicit field to a
  derived value"), walk every code path the plan still describes and confirm each is reachable.
- **Test-assertion specificity, not just scenarios.** Where the plan says "add a test that returns 400"
  or "asserts the array shape", grade whether the named assertion will *pin the documented contract* —
  error-body shape and content-type, ordering with discriminating rows, specific error-message format,
  role/aria attributes for UI. Tests that pass under any 400 emitter, against any non-null array, or by
  matching a substring of a transformed value aren't pinning anything; flag as Should-fix.
- **Spec ↔ implementation message-format parity.** Operator-facing error messages, fallback strings,
  audit-trail formats, and UI status labels that the spec promises must match the implementation
  byte-for-byte (or the implementation must explain why its actual format is equivalent/better).
- **DRY against existing helpers.** For any new helper, hook, or utility the plan introduces, grep for
  similar prior patterns. If a near-duplicate exists, the plan should either reuse it or justify why a
  new one is needed.

## Output

Output a structured review:

- **Blocking** — must fix before execution
- **Should-fix** — strong recommendation, justify if you skip
- **Discussion** — judgment calls worth raising with the user

Write `None.` under an empty section. Don't propose new features. Don't second-guess scope. Grade only
against the bar.
