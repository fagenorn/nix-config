# ADR-console-029 — The owner answers the adoption's questions on the page

- **Status:** accepted; amended by ADR-console-030
- **Decided in:** #1053, #1066

## Context

ADR-console-028 shows a repository's adoption plan on the page, but the plan's open questions were answered only by `adopt-project plan --answer QUESTION SUBJECT VALUE` in a terminal. #1053 puts them on the page: the owner answers each question with a click, and the plan stays the judge of every answer (ADR-project-contract-004).

## Decision

**D1. The questions.** A `registration.ended` row of a `bootstrap` or `reconcile` plan carries `plan_id`, `state`, `questions` and `answered` beside the eight members of ADR-console-028 D7. Every other row carries null, null, `[]` and `[]`, and a row of the eight members alone (written before #1053) is read with those values. `questions` has one entry per member of the plan's `decisions.open`, in its order, `{"id", "subject", "ask", "options", "recommended", "why"}`. `options` is a list of `{"value", "label"}` with exactly the values the plan offers, in its order. `recommended` is the plan's recommended value or null. `why` is null exactly when `options` is not empty. `answered` is the plan's `decisions.answered` as returned.

**D2. The wording.**

- `candidate-class`: the ask is `What should happen to <path>? No rule covers this agent file.` The options are `Archive it under .agents/knowledge/archive/adopted/` (`archive-history`) and `Keep it where it is` (`retain-product`).
- `path-reference`: the ask is `<file> line <line> names <literal>, which this plan moves. Should it follow the move?` The options are `Also name <additions joined by " and ">` (`extend`), `Change it to <replacement>` (`rewrite`) and `Leave it as it is` (`retain`), in the order the plan offers them.
- `reference-policy`: the ask is `The <class> files under <tree> name paths this plan moves. Should they follow the move?`, with `The files with no extension under <tree> ...` for the class `-`. The options are `Change every path that can follow the move` (`rewrite`) and `Leave these files as they are` (`retain`). The label of the recommended value ends in ` (recommended)`.
- `project-id`: the ask is `Which project is this repository?`; see D7.

**D3. The write.** `POST /api/plan-answer` is a member of `PAGE_WRITES` under ADR-console-008. Its body is one `application/json` object of at most 4096 bytes, exactly `{"plan_id", "id", "subject", "value"}`, each a non-empty string with no character below 0x20 and no 0x7F. Any other body is `400` `bad plan answer`. Refusals on the merits are `409`, append nothing and run nothing, and come in this order:

1. `answering the adoption's questions is not available on this host`;
2. `a registration is already running for <name>` (a registration or an answer run is under way);
3. `that plan is no longer the one shown; answer the plan shown now` (the latest row has no plan id, or another one).

Success is an empty `204` once the run is dispatched.

**D4. The run.** `adopt-project plan --repo-root <root> --format json` runs with one `--answer ID SUBJECT VALUE` per entry of the shown row's `answered`, then the new answer. It runs under ADR-console-028 D3's bounds (no shell, its own process group, `stdin` from the null device, 300 seconds, cancelled when the console closes), on a thread of its own. The console judges no answer: the plan accepts or refuses it. While it runs, the view's `registration` is `running` with the headline `Planning the adoption of <name> again with your answer…`.

**D5. The result.** A plan appends one new `registration.ended` row (D1), and the page shows its change lines and what is still open. A ready plan's note is `The plan is ready.`, with no command and no plan id (#1065), which amends ADR-console-028 D4 for every ready row; the page needs no terminal, and the Approve button of ADR-console-030 is the page's way to apply it. A question with exactly one offered answer ends its ask with `This is the only thing the adoption can do with this file.` on its own line, and the page sets Close apart from the questions (#1065). A missing agent platform headlines a plan `The adoption plan for <name> could not start: the agent platform's files are not installed on this host.` (#1065). An answer can leave nothing to adopt: a plan whose outcome is `no_change` appends a `not_registered` row whose headline is `<name> needs no adoption change and is not registered yet: run <the plan's handoff.next_command>`, and the answer run never registers the repository.

**D6. A refusal.**

- A plan error whose repair id is `adopt.decisions.invalid_answer` or `adopt.decisions.unmatched_answer` reads `The plan refused that answer: <its first message>`.
- Any other error reads `The plan was not made again: <its first message>` (`The plan was not made again.` without one). A run that fails reads `The plan was not made again: <words>`, the words of ADR-console-028 D5's `RUN_WORDS` for its failure kind (`it stopped unexpectedly` for an unknown kind or any other exception). Neither shows a repair id, an error code, a failure kind or an exception's type (#1057).

Neither appends a row, so the shown plan, its questions and the stored plan documents stay as they were. While that plan is shown, the text is the view's `registration.refusal`, and `registration.refused` names the question it answered (D10). It is kept in memory only: a restart forgets it, and the next answer run clears it. Before either text is made, the console writes the original to its stderr log as one `console: plan_answer_error <json>` line (the plan's error object, or the failure kind and its cause, or the exception's type and message followed by its traceback), so the reason outlives a restart.

**D7. No offered answer.** Such a question has `options` `[]` and one `why` line:

- a secret-shaped `candidate-class` path: `<path> looks like a secret, so it cannot be answered here: remove it from the repository in its own commit, then register the repository again.`
- any other `candidate-class` with no value: `<path> points outside the repository, so it cannot be answered here: remove it from the repository in its own commit, then register the repository again.`
- `project-id` with a null value: `The plan cannot tell which project this is, so it cannot be answered here: give the repository exactly one git remote, or write its project id in .agents/project.json, then register it again.`
- `project-id` with a value: `<value> is already registered for another checkout, so it cannot be answered here: write the intended project id in .agents/project.json, then register the repository again.`
- any other question, or one whose plan offers no answer: `This question cannot be answered here: answer it with adopt-project plan --answer in a terminal.`

**D8. The page.** This amends ADR-console-028 D8. The page draws each item of D10 as the question card of ADR-console-002: kind `Question`, title `Register <name>`, numbered options, Enter with the five-second undo, no words of the owner's own and no tracker link. Its send posts the D3 body with the item's plan id. An item with no offered answer shows its why line; the item's refusal and a refused write show on its card; a sent answer reads `Answered, planning again`. The Work column shows the registration's one line and its change lines only (D10). The words are the view's.

**D9. Authentication.** Answers pass only through the plan. The page names the plan id it shows. The console re-sends only the answers that plan returned plus the new one, and the new plan id covers them all (ADR-project-contract-004), so `adopt-project apply --plan-id` re-applies exactly what was answered.

**D10. Each question is an inbox item (#1066).** Each open question of a done registration's plan is one item of the view's `inbox.open`, titled `Register <name>`, and counts in `statement.inbox_items` and the headline. The items sit after the manager's questions and before the tracker's items, in the plan's order. An item's key is `register/<plan id>/<index>`, so an answer that makes a new plan replaces them. A question that offers answers shows them as the labels of one question card, with the values they send beside it, and nothing is preselected. A question with no offered answer shows its why line and still counts. The refusal (D6) shows on the item of the question `registration.refused` names, on no other. A running registration, one with no question and none at all add no item. The sentence of the statement is `Choose an option with its number and press Enter.` while any plan question offers an answer (after the manager's question sentence, before the tracker decision's), and `Each one says what to do next.` when only plan questions with no offered answer are open.

## Consequences

- The owner takes a plan from `draft` to `ready` with no terminal; applying and migrating stay terminal commands.
- Tests sandbox HOME (one per case) and every repository.
- No host check is added: an answer run only adds plan documents, which the ADR-console-028 check removes by repository root.
- Every answer run stores one more plan document; the console deletes none.
- Related: ADR-console-002, ADR-console-008, ADR-console-028, ADR-project-contract-004.
