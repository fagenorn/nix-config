# Improve Codebase Architecture Skill Design

## Problem

The system has the architectural vocabulary for deep modules, but it does not have a repeatable
workflow that uses that vocabulary to inspect a real codebase, show the best deepening
opportunities visually, and carry a selected opportunity into the existing design pipeline.

The upstream `improve-codebase-architecture` skill is a useful starting point, but copying it
unchanged would leave broken workflow references, make its supporting vocabulary available to only
one of the two agents, and bypass this repository's grounding, dispatch, worktree, decision, and
testing contracts. It also leaves important operational behavior implicit: scan cost, report
failure behavior, when repository mutation begins, and how a selected candidate enters the local
pipeline.

The desired result is a repository-owned skill that preserves the upstream experience—focused
scan, visual candidates, top recommendation, then exploration of the selected candidate—while
behaving as a native member of this system.

## Solution

Add a shared, explicit-only `improve-codebase-architecture` skill and make the existing
`codebase-design` vocabulary a shared repository-managed skill. The architecture skill grounds in
the target project's context and decisions, infers a bounded scan scope, delegates one
judgment-bearing read-only scan, and renders zero to five evidence-backed deepening candidates as a
temporary HTML report. It never pads the report to meet a quota and never writes to the target
repository during discovery.

After the user selects a candidate, the skill applies a fog gate. A concrete candidate enters an
isolated worktree and proceeds through `design` and `grill-with-docs`. A destination that is still
too foggy to specify is handed to `wayfind`. After a concrete design has been grilled, the skill
stops and recommends `writing-plans` for one cohesive build or `to-issues` for several independently
shippable slices.

This is an attributed adaptation of Matt Pocock's
[`improve-codebase-architecture`](https://github.com/mattpocock/skills/tree/main/skills/engineering/improve-codebase-architecture)
at revision `9c9f36ccd3995266cd675468af71639c8dde1ec5`, inspected on 2026-08-17. The
upstream MIT copyright and license notice travel with the adapted skill.

## Decisions

### Shared modules and ownership

The repository owns two shared modules:

- **Codebase Design** is the single vocabulary and principle source for module, interface,
  implementation, depth, seam, adapter, leverage, locality, dependency categories, the deletion
  test, and interface-level testing. Its existing deepening and design-it-twice references become
  available to both agents.
- **Improve Codebase Architecture** owns discovery, candidate presentation, selection, and routing.
  It invokes the vocabulary module instead of copying its glossary, and invokes the existing
  grounding and design workflows instead of embedding substitutes.

The shared skill distributor continues to discover complete skill directories automatically. No
new plugin, marketplace, connector, or special-case installation path is introduced. Detailed HTML
guidance remains a lazily loaded reference, while the upstream license notice remains a packaged
resource that is not injected into model context.

The adaptation is maintained like the repository's other authored skills. Upstream changes never
flow into a deployed generation automatically; a future refresh is an intentional comparison and
port of useful changes.

### Invocation interface

Architecture review is explicit-only in both hosts because it is expensive, judgment-heavy, and can
open a browser. The Claude-facing control remains in skill frontmatter and the Codex-facing policy
is declared in the Codex skill metadata manifest. That metadata also supplies the human-facing name, short
description, and a default prompt that explicitly names `$improve-codebase-architecture`.

The user-facing input is an optional module, subsystem, path, or pain point. A supplied direction is
authoritative and bypasses hotspot inference. With no direction, the skill infers a bounded default
scope from repository history.

### Grounding and scan contract

Before proposing candidates, the skill loads `codebase-design` and invokes
`doc-grounded-questions`. Context terms become the domain names used in the report, existing ADRs
are constraints rather than suggestions to relitigate, and applicable standards are carried into
candidate grading.

With no user-named scope, the scan reads the last 50 non-merge commits, ranks repeatedly changed
paths, and follows the strongest concentration into code, tests, and relevant documentation. It
widens only when history is scattered or yields no meaningful concentration. History selects where
to look; it is not evidence by itself that a module should change.

One fresh architecture scan owner performs the organic code walk. This is design judgment, so the
model matrix assigns the `issue-owner` role at Opus/high rather than the bounded, non-judgmental
`explorer` role. The dispatch is read-only with respect to the repository and writes at most one
structured findings artifact in the OS temporary directory. If the host cannot dispatch a
sub-agent, the calling agent performs the same bounded scan inline and discloses the fallback.

For every suspected candidate, the scan must establish:

- the module and callers involved;
- the interface knowledge callers currently carry;
- where locality or leverage is lost;
- the result of the deletion test;
- the dependency category and whether a real seam has at least two justified adapters;
- the existing tests and the proposed interface-level test surface; and
- any context or ADR conflict, including why reopening it would be justified.

The report contains two to five candidates when that many survive this evidence bar. One is valid;
zero produces a truthful no-candidate report rather than speculation. Candidates use the upstream
strength vocabulary—`Strong`, `Worth exploring`, or `Speculative`—and never use a candidate quota as
a reason to include weak work.

### Visual report contract

The calling agent renders the findings to a fresh
`architecture-review-<timestamp>.html` file beneath the OS temporary directory, using `TMPDIR`, the
Windows temporary directory, or `/tmp` as appropriate. No report or scan artifact lands in the
target repository.

The report preserves the upstream lean editorial direction and uses Tailwind and Mermaid from
their CDNs. Mermaid is for graph-, call-, and sequence-shaped relationships; inline CSS and SVG are
for mass diagrams, cross-sections, and call-graph collapse. Each candidate card contains its title,
strength and dependency category, involved files/modules, before/after visualization, one-sentence
problem, one-sentence solution, short wins in the shared vocabulary, and an ADR warning when
needed. A final card names one top recommendation when at least one candidate exists.

The document remains useful without styling or script execution: semantic headings preserve the
reading order, every diagram has an adjacent text equivalent, color is never the only carrier of
meaning, and minimal inline base styles keep prose readable if a CDN is unavailable. Normal text
meets 4.5:1 contrast, cards reflow without duplicating content, and text is not clipped at narrow
widths or under user spacing overrides. The side-by-side layout collapses cleanly at phone width.

After generation, the skill best-effort opens the report with the platform's normal browser command
and always prints its absolute path. Report generation failure is a failed run. Browser-opening or
CDN failure is a disclosed warning, not a false report-generation failure, because the absolute
HTML artifact remains available.

### Selection, worktree, and downstream routing

After presenting the report, the skill asks which candidate the user wants to explore and proposes
the top recommendation. It does not propose a module interface before selection.

Selection is the first point at which repository mutation may begin:

1. **Fog gate.** If the destination or its current decision questions still cannot be stated
   precisely, invoke `wayfind` to chart the effort and then return control. Do not create a design
   worktree or automatically resume this skill after the map is charted.
2. **Concrete candidate.** Reuse the current workspace only when it is already an isolated linked
   worktree. Otherwise invoke `worktrees` and create a candidate-named worktree from the configured
   remote integration-branch ref before any spec or domain document is written.
3. **Design.** Invoke `design` to resolve module interface, seam placement, behavior, and test seams
   into a committed design spec. Preserve the scan evidence as grounding; do not re-ask decisions
   already made during candidate selection.
4. **Domain and decision review.** After the user approves the design, invoke `grill-with-docs` so
   domain language and qualifying ADRs are updated through the system's existing contracts.
5. **Scope gate and stop.** Recommend `writing-plans` when the grilled design is one cohesive build.
   Recommend `to-issues` when it contains independently shippable slices; each resulting issue can
   later enter `from-issue`. Do not invoke planning, create implementation issues, or execute code
   from this skill.

## Test seams

1. **Shared deployment seam.** Build the Nix/Home Manager configuration and inspect the produced
   user environment: both complete skill directories must be visible to Claude Code and Codex,
   including multi-file references and Codex metadata. This follows the existing automatic shared
   skill discovery and whole-directory-link behavior. `just build` is the repository's public
   verification command.
2. **Workflow contract seam.** Extend the existing Python contract suite and model-matrix validator
   to assert the explicit-only controls, upstream provenance, dependency references, 50-commit
   hotspot rule, zero-to-five unpadded candidate behavior, read-only discovery, temporary report path,
   selection routing, and the exact Opus/high `issue-owner` dispatch marker. Run `just
   agent-workflow-tests` and `just agent-model-matrix`.
3. **Deployed behavior seam.** Exercise the deployed skill against the TinyTask fixture. A scan-only
   case proves that no repository or worktree mutation occurs, returns an absolute temporary HTML
   path, and renders candidate cards plus a top recommendation when evidence supports one. A clear
   selection case reaches an isolated design worktree; a deliberately foggy selection routes to
   `wayfind` without creating that worktree. Visually inspect the generated report at phone and
   desktop widths, with Mermaid loaded and with scripts/styles disabled, to confirm the semantic
   fallback and diagram text equivalents. The existing deployed-skill eval harness is the prior
   art.

No implementer may add lower-level test seams for internal scan helpers or assert method calls. The
observable boundaries are installation, skill contract, and deployed workflow behavior.

## Out of scope

- Implementing any architecture candidate or automatically continuing into execution.
- Automatically publishing issues or invoking `writing-plans`, `to-issues`, `from-issue`, or `sdd`
  after the scope recommendation.
- Importing the upstream `grilling` or `domain-modeling` skills; the local design and documentation
  workflows own those responsibilities.
- Packaging these skills as a plugin or marketplace item.
- Automatic upstream synchronization, a Nix input for the upstream repository, or runtime fetching
  of skill instructions.
- Bundling Tailwind or Mermaid for offline rendering; CDN use is an accepted constraint.
- Creating a context map, glossary, or ADR merely because the scan ran. Those writes happen only
  after selection through the established design/documentation workflows.
- Changing existing workflow semantics beyond adding the new shared vocabulary dependency,
  dispatch registration, contract coverage, and eval cases required by this skill.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Maintain an attributed repository-owned adaptation and make both architecture skills shared across Claude Code and Codex | User Q1/Q5; shared-skill deployment contract; upstream MIT license at revision `9c9f36ccd3995266cd675468af71639c8dde1ec5` | Faithful or automatically updated upstream dependency: named workflows do not exist locally and future updates could silently undo native integration |
| D2 | Require explicit invocation in both hosts | User Q2; architecture scans are costly and browser-opening; OpenAI metadata supports an explicit-only policy | Implicit triggering: a matching refactor prompt could launch a repository-wide scan unexpectedly |
| D3 | Use a user-named scope or the last 50 non-merge commits, one Opus/high scan owner, and zero or 2–5 evidence-backed candidates without padding | User Q7/Q8; upstream hotspot and deletion-test guidance; model matrix reserves design judgment for `issue-owner` | Exhaustive scanning or cheap bounded explorer: unbounded cost in the first case and prohibited architectural judgment in the second |
| D4 | Render a temporary Tailwind/Mermaid CDN report with accessible semantic fallbacks and always return its absolute path | User Q3; upstream visual-report contract; UI guidance on contrast, reflow, semantic color, and text alternatives | Fully offline renderer: additional bundled assets and maintenance were not requested; Markdown-only output loses the core visual comparison |
| D5 | Keep discovery read-only; after selection route fog to `wayfind`, otherwise create/reuse a worktree for `design` then `grill-with-docs`, and stop before planning or issue creation | User Q4/Q6; `wayfind` declines clear one-session work; design artifacts must be committed off the integration branch | Always use wayfind or automatically continue to issues/planning: the former maps visible destinations and the latter erases required checkpoints |
| D6 | Verify at the deployment, workflow-contract, and deployed-behavior seams only | User Q9; existing Nix build, contract suite, model matrix, and eval harness | Internal implementation tests: they would test past the skill interface and couple verification to prompt structure |
