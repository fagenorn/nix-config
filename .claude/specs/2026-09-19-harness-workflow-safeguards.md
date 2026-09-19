# Workflow safeguards after the month-one audit

Approved scope: immediate workflow-policy improvements from the September 19 retrospective. Related issues #150, #151 and #152 remain open for runtime contracts and quantitative replays. This slice changes skill guidance and behavioral evals, not lifecycle JSON or host scheduling machinery.

## Behavior

Carry the authorized deliverable, next authorized action, and actual permission boundary into handoff text. Reuse existing user approval within that scope; neither phase transitions nor a new session erase it. A changed target, new external effect or actual runtime denial remains a boundary. Preserve launch ownership, required CI and fixed-schema output contracts.

An already-merged implementation is evidence to reconcile against acceptance criteria and the live tracker, not an unconditional reason to abandon authorized closure. An existing open PR belonging to the requested work resumes shipping when authorized; unknown/competing work remains protected. Wayfind may finish delivery of its own authorized repository decision record while retaining the one-decision-per-session limit and the boundary before unrelated implementation.

SDD records a stable delivery merge base. Before its first implementer and between tasks, measure the actual cumulative committed review package with the existing producer/checker gate. Stop further dispatch on overflow or invalid reports, preserve completed work, and propose an independently reviewable split. A task-range pass does not prove whole-branch feasibility. Planning records expected changed files, growth risks and deliverable slices; estimates are labeled as estimates, never asserted as guaranteed final byte counts.

When known host capacity cannot support an issue owner and independent review, do not improvise competing owners or repeated spawn retries. Use an explicitly supported sequential/direct route, or report the missing capability. This policy does not claim to implement host reservation/notification scheduling; #150 owns that work.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|---|---|---|---|
| D1 | Preserve scoped user authorization without inventing --auto or ownership | Nodo/Arcwave/Argus corrections; current launch guard | Treat every checkpoint as new permission or silently acquire lifecycle identity |
| D2 | Use existing exact-range package generation incrementally | #121 late overflow after six tasks; existing bounded producer | Raise caps or add speculative size estimator presented as certainty |
| D3 | Keep scheduler and terminal schema work in #150–152 | Control interface owns capacity; strict result schema has no postcondition object | Add unvalidated fields or duplicate lifecycle policy in prose |

## Verification

Independent plan-only behavior probes: merged implementation/open issue; approved repository decision record; unchanged-scope experiment versus expanded authority; cumulative package failure after a task; capacity too small for two owners. Existing workflow contract tests and skill validation remain green. Eval outcomes are evidence of instruction following in these cases, not runtime lifecycle guarantees or measured token savings.
