# ADR-console-066 — An answer reads in the main column, formatted, with the owner's choices as buttons

- **Status:** accepted
- **Decided in:** #1226

## Context

The owner's first real answer from a project's question session was raw text in the narrow Work column: the question showed twice, once on the thread's line and once on its row, the session's question back sat above the answer in grey, and the main column stayed empty (#1226). ADR-console-002 put the thread's questions and answers inside the Work column's "Questions (n)" fold and ADR-console-065 D8 fixed the answer's plain-words shape; this ADR moves the reading to where it can be read and gives the answer a form the page can draw.

## Decision

**D1.** A reading panel in the main column. One thread is read at a time, in one panel in the main column after the capacity warning and before the inbox. A thread's line in the Questions fold is a button that opens the thread in the panel and, pressed again, closes it; the panel's own Close does the same and returns focus to the line. Opening moves focus to the panel's heading. A sent question opens its thread in the panel once, when the view first carries it, without moving focus. A thread that leaves the view closes the panel.

**D2.** Each question once. The thread's first question is the panel's heading, so its row does not repeat it; each follow-up's question shows once on its own row. A thread's line in the fold shows the first question, its age and "and n follow-ups", and nothing of the answer.

**D3.** The answer is formatted from DOM nodes only. The page draws a fenced code block (a line starting with three backticks opens it, the next such line or the end closes it, its lines verbatim), bullet lists (`-`, `*` or `+`, then a space), numbered lists (one to three digits, then `.` or `)`, then a space), paragraphs, **bold** (a non-empty pair of double asterisks outside code) and `inline code` (a backtick pair, verbatim). Every node is built with the page's `el()` helper, so view text is never parsed as HTML; every other markup, an unmatched marker included, shows as text.

**D4.** The answer shape. The prompt names that subset and forbids headings, tables, links and HTML. The Question for you part is a question, then two to `MAX_CHOICES` (5) list lines each starting `- `, or none. `answer_parts` splits it: the view's `back_text` is the question alone and `back_choices` the list lines' texts in order; one list line, more than `MAX_CHOICES` or no question text leaves `back_text` the whole part and `back_choices` empty. This amends ADR-console-065 D8, which left the part free text.

**D5.** The call-out is last. The question for the owner sits in a bordered call-out after the answer, its sources and Make it a goal. Its choices show as quiet buttons only on the thread's last answered question while no follow-up is outstanding; a choice posts the choice's text as a follow-up in the thread, with the body, refusals and pending rules of ADR-console-062, and a refusal's reason shows in the call-out. A question for the owner is information: never peach, never counted.

**D6.** Sources are folded and the look is judged on a real answer. Read and Ran sit in a closed "What it read and ran" fold under the answer; Could not find out and the production line stay quiet lines under the answer. The look is judged on the owner's own long answer, shot at 1440 and 480 px, with the impeccable skill and the control kinds of #1137; the fold and the buttons use those kinds and the panel adds no colour.

## Considered Options

- Rendering in the Work column: too narrow for a long answer, the reported fault.
- A markdown library: a dependency, and an HTML-producing parser on view text.
- Raw HTML from the session: never; view text is not HTML.

## Consequences

- A session that uses other markup, such as a heading, a table or a link, shows it as text.
- A back part with one list line or more than five has no buttons; the owner answers in the follow-up box.
- Choices disappear once a follow-up is outstanding or the thread moves on, so an older call-out is text only.
- Related: ADR-console-002, ADR-console-058, ADR-console-062, ADR-console-065.
