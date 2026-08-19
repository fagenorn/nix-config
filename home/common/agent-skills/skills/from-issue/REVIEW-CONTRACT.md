# Phase-5 plan review contract

Reviewer-facing text for `from-issue` Phase 5. The dispatcher hands this file's **path** to the
reviewer (or to `codex-collaboration`, which passes it by path in the review packet) and supplies concrete
values for every `<placeholder>` and binding named below — plan root path, its four
checker metrics, spec path, issue number,
`<tracker-cli>`, `unsetGithubToken`, `docPaths.*`, `projectHints`, and the optional review focus.
The orchestrator never inlines this text into its own context.

---

Review the implementation plan at `<plan-path>` against the project's coding bar.

Before Phase 5 reads state or advances, its caller must pipe the exact received
planning-report bytes through `artifact-budget validate-report --boundary
producer --input -` and use only validated stdout. It requires the exact D11
object in `state: complete`, with one `implementation-plan` artifact whose root
path and four metrics match the supplied values. Validator failure, any legacy
producer-specific list or summary field, or any other state stops Phase 5 as a
contract failure; there is no prose fallback (D11, D14).

Before reading plan content, run `artifact-budget check --kind
implementation-plan --root <plan-path> --format json`. Require exit 0,
`within_budget`, and the same `root_bytes`, `total_bytes`, `file_count`, and
`largest_member_bytes` supplied in the packet. Exit 2/3, missing metrics, stale
metrics, or an unreadable member is a blocking contract failure. Then read the
root and every indexed member in checker discovery order. The packet supplies
only the plan root and metrics, never contents or a member list (D3, D5, D6, D8).

First ground in the project's docs: invoke `doc-grounded-questions` if available, else ground
map-first — read the context map (`docPaths.contextMap`, else `docs/CONTEXT-MAP.md`, else legacy root `CONTEXT-MAP.md`) and open only
the area `CONTEXT.md` files whose `governs:` globs intersect the plan's touched paths or whose terms
appear in the issue; ADRs (the loaded areas' `adr/` dirs, plus `system`; `docPaths.adrDir` only in legacy
repos) only when cited; the standards layers that apply
(`~/.agents/standards/the-bar.md`, its `stacks/` shards matching the diff's file types, and the
project's `docs/standards/` shards whose globs intersect). Only when the project has no map, fall
back to reading `docPaths.{context,standards,architecture}` whole. Then
read the issue body (`<tracker-cli> issue view <num>` — prefix with `unset GITHUB_TOKEN &&` only if
`unsetGithubToken` is true), the spec at `<spec-path>`, and the validated plan
root plus every member.

When checking specific findings, **read the live file at HEAD** rather than relying on snapshot/diff
views — code may have been edited since the plan was written, and stale snapshots produce
false-positive should-fixes.

For each plan task, flag anything that violates the grounded constraints. Every
finding identifies its affected task member or root section. Explicitly report
any member that could not be read. Pay particular attention to:
framework-first (custom executors/state machines where a framework primitive already exists),
production-grade-by-default (half-finished branches, missing error paths at boundaries), DI rules, and
the test-fixture conventions in the project's standards shards (or legacy coding-standards doc).

If `projectHints` is configured and present (a directory → its `review.md`; a single file → itself), read it for project-specific review
hints/examples and fold those into this pass (e.g. recurring repo-specific plan bugs that have escaped
review before).

## Common-miss checklist

Scan against these categories — they have repeatedly slipped past plan review and surfaced only at PR
review.

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

  The checklist forces the *act* of checking; relying on the reviewer to mentally enumerate is how an
  Esc-key gap once leaked. Any **user-reachable** path the plan doesn't address is a Blocker. A path
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
  plan tells the implementer to write — does the wording match what the code will *actually* do? Drift
  here is a PR-review fix-up commit waiting to happen.
- **Stale prose audit.** Distinct from the bullet above: that one checks prose the plan *dictates the
  implementer write*; this one checks prose that *already exists* in files adjacent to the diff. For
  every context-doc sentence, ADR clause, docstring, or comment near the PR's footprint, re-read the
  live file. Terminology the PR retires (renamed concepts, deprecated class names, removed fields) must
  be purged in *all* adjacent comments and doc references — not just the diff's immediate footprint.
  One of the most common post-PR-review fix-up categories.
- **Dead branches after iteration.** If Phase 4 → Phase 5 revisions changed the design (e.g. "use the
  framework's collapsible primitive" replacing hand-rolled state, "switch from an explicit field to a
  derived value"), walk every code path the plan still describes and confirm each is reachable. Pivoted
  plans leave stranded `else` branches, unused props, and `if (legacyFlag)` arms that the implementer
  dutifully writes and the PR reviewer dutifully flags.
- **Test-assertion specificity, not just scenarios.** Where the plan says "add a test that returns 400"
  or "asserts the array shape", grade whether the named assertion will *pin the documented contract* —
  error-body shape and content-type, ordering with discriminating rows, specific error-message format,
  role/aria attributes for UI. Tests that pass under any 400 emitter, against any non-null array, or by
  matching a substring of a transformed value aren't pinning anything; flag as Should-fix.
- **Spec ↔ implementation message-format parity.** Operator-facing error messages, fallback strings,
  audit-trail formats, and UI status labels that the spec promises must match the implementation
  byte-for-byte (or the implementation must explain why its actual format is equivalent/better). A
  spec-promised exact string that falls through to a generic default is a real gap caught only at PR
  review when missed here.
- **DRY against existing helpers.** For any new helper, hook, or utility the plan introduces, grep for
  similar prior patterns. If a near-duplicate exists, the plan should either reuse it or justify why a
  new one is needed. Duplicate helpers fixed only at PR review are a recurring waste.

## Output

Output a structured review:

- **Blocking** — must fix before execution
- **Should-fix** — strong recommendation, justify if you skip
- **Discussion** — judgment calls worth raising with the user

Write `None.` under an empty section. Don't propose new features. Don't second-guess scope. Grade only
against the bar.

Accepted Phase-5 edits are not complete when the text is saved. After the last
write, the orchestrator re-runs the implementation-plan check and compares the
fresh package metrics; if it amended the spec or appended a decision-ledger row,
it also re-runs the design-spec check. Any invalid or over-budget result stops
the phase instead of advancing with stale measurement (D5, D14).
