# to-issues issues that read on their own: problem first, terms explained — issue 495

Issue: https://github.com/fagenorn/nix-config/issues/495. This was designed autonomously
(`from-issue --auto`), so every call made without the user is a row in the Decision ledger.

## Triage

input signals: `contract_change`: doubt — the template is a test-pinned output contract. `concurrency_or_persistence`: no. `open_design_questions`: doubt — the ceiling question. `criteria_shape`: no — three deterministic criteria. Predicted paths: `home/common/agent-skills/skills/to-issues/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json`. Verdict `{"hits":["contract_change","open_design_questions"],"lane":"full","mode":"shadow"}`, `ran: full (shadow)`.

## Problem

The to-issues skill files the implementation tickets for a plan, both in this repo and in
`elevenyellow/nodocom`, which loads the same global skill. Its issue template opens at
**What to build**. The problem a ticket solves shows up only when the agent happens to add
background, as https://github.com/fagenorn/nix-config/issues/487 does inside What to build.

The skill tells the agent to write titles and descriptions in the project glossary's terms.
Nothing tells it to explain them. So
https://github.com/elevenyellow/nodocom/issues/2551 opens with "Tier evidence proves that a model
works in Nodo's harness before the remap gate binds it to a tier", and other titles and bodies
cite plan shorthand such as "S2 Part A" or "D31". A reader who has only the issue page cannot
tell what is wrong today, why it matters or what the labels mean. That reader may be the
implementer weeks later, a reviewer, or the owner.

The skill already states the reader: "The body is the contract, read weeks later in a fresh
context". But it names only some failures (file paths, line numbers, "as discussed above"), and
nothing makes the agent check a body before it publishes.

## Solution

1. Add a `## Problem` section to the issue template, between Parent and What to build.
2. State three rules in to-issues: titles name the outcome in plain words; a glossary term,
   decision ID or slice label is explained or linked at first use; before publishing, the agent
   rereads each body as a stranger and fixes any sentence that leans on the spec, the plan or the
   conversation.
3. Pay for the new text inside the same file, so its size does not grow and no instruction
   ceiling rises.
4. Add one contract class beside `ToIssuesCriterionLineContractsTest`. It fails today and pins
   the template's sections and the two new rules.

## Decisions

### The template (AC 1)

The template's sections become, in order: Parent, **Problem**, What to build (with its Demo
line), Decisions, Acceptance criteria, Blocked by. The new section is always present, and its
placeholder reads:

> What happens today, who it affects and why it matters now.

Parent keeps its place and its "omit when" rule. Demo, Decisions, the three criterion lines and
Blocked by do not change. What to build keeps its wording except one duplicate: "No file paths or
code, except" becomes "No code, except", because the `measured:` sentence already makes that
clause the only place a body names a file. Per D3 and D2.

### The rules (AC 1)

- **Titles.** Step 2's sentence about the terms titles and descriptions use gains: "A title
  states the outcome in plain words, never plan shorthand." Glossary terms stay allowed in a
  title, and the body explains them. Per D4 and D5.
- **First use and the stranger read.** The "body is the contract" paragraph is rewritten to name
  its reader and to hold both rules:

  > The body is the contract, read weeks later by a stranger holding only that page: behavior and
  > outcomes, no line numbers, nothing an implementer needs left only to a comment. Explain each
  > glossary term, decision ID or slice label in a few words, or link it, at first use. Before
  > publishing, reread each body as that stranger and rewrite or link any sentence that needs the
  > spec, the plan or the conversation.

  The paragraph drops "no file paths outside `measured:`", a copy of the sentence above it, and
  `no "as discussed above"`, which the stranger read now covers. The publishing agent rereads
  each body itself, and no subagent is dispatched. Per D4.

The falsifiable-criterion paragraph, the criterion-kind list and the `measured:` sentence do not
change.

### Budget (CI gate)

`to-issues/SKILL.md` measures 6494 B against a hot ceiling of 6494 B on both hosts, so it has no
headroom. The new text is paid for by removing duplicated or redundant text in the same file
(per D2):

- "A blocked tracker stops the forge operation." The resolver paragraph already says that
  required blocked capabilities stop.
- "; it is its own leading slice". The slice rule "Any prefactoring is its own slice, and comes
  first" already says it.
- The tracer-bullet gloss "a thin vertical slice through every integration layer". The first
  slice rule says the same thing.
- The two file-path copies and "as discussed above", described above.
- Tighter wording, with no rule dropped, in: step 1's comment-thread sentence, step 4's
  approval sentence, the GitLab bullet with the "Blocked by is the record" sentence after it, and
  the wide-refactor sentence.

These edits were prototyped on 8d0bbc25. They measure 6484 B, a change of −10 B. Both the gate
(`instruction_load check --base origin/main`) and the full `test_workflow_skill_contracts` module
pass. The result stays within 5% of the ceiling, so `instruction-load.json` is not edited. If the
final wording falls more than 5% below the ceiling, the plan runs
`just agent-instruction-load tighten`, which only lowers a ceiling and needs no label. The gate
decides. Per D1.

## Test seams

- **New class `ToIssuesStandaloneBodyContractsTest`** in `test_workflow_skill_contracts.py`,
  directly after `ToIssuesCriterionLineContractsTest` and reusing its `TO_ISSUES` path. Its
  docstring cites #495 AC1. It has two cases:
  1. The `## ` headings inside `<issue-template>` equal, in order, `Parent`, `Problem`,
     `What to build`, `Decisions`, `Acceptance criteria`, `Blocked by`.
  2. The whitespace-normalized skill text contains the tokens `at first use` and
     `reread each body`.

  Both cases fail at 8d0bbc25, where Problem and both tokens are absent, and both pass on the
  prototype. The class follows #274's `ToIssuesCriterionLineContractsTest`, which slices the
  template the same way, and #474's short-token pins. Per D6.
- **`ToIssuesCriterionLineContractsTest` (existing, unchanged)** measures AC 2.
- **The instruction-budget gate and the verification bindings** measure AC 3:
  `just agent-workflow-tests` and `just build`. The plan also runs
  `just agent-instruction-budget`.

## Out of scope

- Other skills that file tickets (wayfind, from-issue), `WIDE-REFACTORS.md`, and any to-issues
  eval. The repo has no to-issues eval today.
- Rewording or re-filing existing issues in either repo.
- A fresh-context reviewer subagent or a lint that checks published bodies.
- Changes to Demo, Decisions, the criterion lines or kinds, Blocked by, the falsifiable-criterion
  rules, the resolver paragraph or the GitHub `issue_id` instruction.
- Raising any instruction ceiling. The corpus ceiling also stays as it is.
- Deleting the existing `test_the_criterion_line_shape_is_stated` phrase pin. AC 2 keeps that
  class green as it stands.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The growth is offset inside `to-issues/SKILL.md`, so the net change is ≤ 0 B and no ceiling rises. `instruction-load.json` changes only if the gate reports the file more than 5% under its ceiling, and then only through `tighten`. | CLAUDE.md: only the user applies `instruction-budget-raise`, and Instruction Budget is a required check. #474 D5 is the precedent. The prototype measured −10 B and the gate passed. | Raising the 6494 B ceiling: the autonomous delivery would wait on a label only the user can apply, for a wording change. |
| D2 | The offset removes only duplicated or redundant text, and tightens wording without dropping a rule. The removals are the restated blocked-capability stop, the restated prefactoring rule, the tracer-bullet gloss, two file-path copies and "as discussed above". The pinned resolver sentences, the criterion lines and kinds, the falsifiable paragraph, the Demo, Decisions and Blocked by placeholders, and the GitHub `issue_id` instruction stay. | The bar: DRY. The issue: "The rest of the template … and the existing rules about falsifiable criteria stay as they are". The `RESOLUTION_SENTENCE`/`REFUSAL_REPORTING_SENTENCE` pins. | Cutting the GitHub `issue_id` instruction or the falsifiable paragraph: one prevents a known bug that silently links the wrong issue, and the issue keeps the other. Moving rules into a conditional reference file: each run would need an extra read for text every run uses. |
| D3 | `## Problem` sits between Parent and What to build, is always present, and its placeholder is "What happens today, who it affects and why it matters now." | The issue: "a Problem section before What to build: what happens today, who it affects and why it matters now". #487 shows the background a body needs. | Problem above Parent: moves a section the issue keeps, and Parent is a one-line link. An optional Problem: a prefactoring slice also has a problem, namely what makes the change hard today, and leaving the section out is the failure being fixed. |
| D4 | The title rule joins step 2's sentence that sets the vocabulary of titles and descriptions. The first-use rule and the stranger read join the "body is the contract" paragraph, which now names a stranger holding only that page as its reader. The publishing agent rereads each body itself. | The issue's diagnosis: step 2's use-the-glossary rule has no rule to explain the terms. The brief's recommended fold into that paragraph. The bar: Token economy. | A new readability subsection: a new heading, and the rules it would hold are already spread over two places. A fresh-context reviewer subagent per issue: a new dispatch site with a model-matrix row and pins, run for every issue, where the issue asks the agent to reread. |
| D5 | A title bans plan shorthand (slice labels, part numbers, decision IDs) but may use a glossary term. The first-use rule applies to the body, where a term can be explained. | Step 2 already has titles use the glossary's terms. The issue: a title "doesn't depend on plan shorthand". | Banning glossary terms from titles: contradicts step 2 and the project's consistent vocabulary. Applying the first-use rule to the title itself: a title has no room for an explanation. |
| D6 | AC 1's test is one new class. It pins the exact template heading list and two short tokens, `at first use` and `reread each body`. The title rule is not pinned. | AC 1, written by the user, names the file and the assertions. The standards README: a user instruction outranks Layer 2. Rule 6 allows text a subagent consumes, and sdd's final review reads the `## Acceptance criteria` heading. #474 D4 is the precedent for short tokens. | Full-sentence pins: rule 6 forbids them, and they fail on rewording. A headings-only test: it leaves AC 1's rule clause unmeasured. Pinning the title rule: no criterion asks for it, and rule 6 forbids a new phrase pin. |
