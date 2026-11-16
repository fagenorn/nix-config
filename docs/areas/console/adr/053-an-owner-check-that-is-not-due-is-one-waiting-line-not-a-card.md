# ADR-console-053 — An owner check that is not due is one waiting line, not a card

- **Status:** accepted
- **Decided in:** #1129

## Context

A check held for the owner can be due by its block yet waiting by its wording. The case that started this is jarbird#619: its block carried only a `released_includes` member and the sentence "Two days after the release, read the hourly job rows". The runner posted the owner prompt as soon as the release included the merge, because the block has no `days_after` or `not_before` member, so the owner met a card for a check that was not yet theirs to do. The runner is right to prompt only a due check (`verify_run` returns before the owner form when the check is not due), which leaves a not-due owner check with no prompt and so no card: the console must read the held block itself to show that the check is waiting, and a wait must not look like a question (ADR-console-019: the inbox is for questions only).

## Decision

**D1. The reading.** The console reads a held owner check with the runner's own member readers and the forge's clock: `verify_facts.evaluate_wait` reads every member and dates a wait only when every unmet member is dated, by the latest date; `verify_wait.owner_waits` selects the owner checks. Owner checks only: the unattended rule is unchanged (ADR-verification-003).

**D2. A prompt means due.** The runner prompts only a due check and a met dated member stays met, so a check that has been prompted is never evaluated by the console.

**D3. No `when` field.** A block with no `not_before` and no `days_after` member states no date, so the check is never dated; its line reads the exact `no_when` text of the reading.

**D4. Due, not yet prompted.** An unprompted due check is a `Due now` line until the runner's next pass, every 900 seconds, posts its prompt; the prompt is the card. A live or paid `command` check is the exception: the runner prompts it only for a command the project's `workflow.verification` names, which the console never reads, so its line (`due_command`) says the pass asks unless it refuses the command.

**D5. The tracker read.** The read adds the `needs-verification` label to what it lists. Its forge reads are outside `inbox.MAX_CALLS`, and the stop is asked before each of them, so `close()` still waits for at most one `gh` call.

**D6. Where a wait lives.** Waits are inbox items, never counted. A wait sits under the sprint whose report names its issue, else under its project, which a wait keeps active and drawn. The digest rule follows: a wait is not a transition the digest announces.

Retention keeps the newest row of an outstanding wait (`event_log`): an idle project is polled only while it holds a wait and an unchanged wait appends no row, so ninety days of silence would otherwise drop the line and the polling with it, and the check would never become a card.

**D7. No clock ends a wait in the view.** The view's clock is the host's, never the forge's; only a tracker read, with the forge's clock, ends a wait.

**D8. The page line.** A wait is one quiet line: `Waiting until <day>: <text> #<issue>` for a dated wait, `<text> #<issue>` for an undated one, with the issue number linking to the tracker comment. The day is the new `day` form of a time element, drawn in local time (`Wed 18 Nov`). No border, no background, no button. Under a sprint the line sits in the same list as the sprint's check lines (ADR-console-051), so it is indented to the sprint head's text and has the check line's even gap above and below. The text is set as text.

**D9. The import edge.** `agent_tools.console.inbox` imports `agent_tools.verification.verify_wait`. This amends ADR-console-012's "one new import edge"; the layout table in `tests/test_agent_tools_layout.py` lists it.

**D10. Pictures.** The page change is held for the owner's before and after pictures at 1440 and 480 px, as ADR-console-045 D6.

## Consequences

- ADR-console-012 is amended: the console has a second import edge into the verification area.
- A check whose wording states a wait shows no card until its block is fixed to say so in a `when` member.
- A due check shows a `Due now` line, not a card, until the runner's next pass.
- The tracker read costs one clock read and the release or CI reads of unprompted owner checks.
- Related: ADR-console-012, ADR-console-019, ADR-console-045, ADR-verification-003.
