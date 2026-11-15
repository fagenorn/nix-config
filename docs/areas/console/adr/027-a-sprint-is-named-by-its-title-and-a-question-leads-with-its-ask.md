# ADR-console-027 — A sprint is named by its title and a question leads with its ask

- **Status:** accepted
- **Decided in:** #1031

## Context

On 2026-11-13 the console's first screen was read with a 1,400 character goal in play: the goal text named the sprint on every inbox item and in every digest sentence, and a manager's question ran to paragraphs inside the large display type, so the owner scrolled to find what was being asked. A goal is the owner's own words and can be as long as 2000 characters; nothing the manager wrote had a length.

## Decision

**Four limits, on the write path only.** A brief's title is at most 60 characters, a question's ask at most 140, its context at most 400 and each option at most 80. `checked_brief` and `checked_round` refuse an over-limit part with the limit named, before anything is logged, and the manager corrects it and sends again. The limits are checked right after each member's type check and before the older 1,000 and 500 character caps and the one-line check, so no over-limit input is answered with a generic "no valid" text.

**`title` is a required brief part.** The brief's parts are now `title`, `done`, `excluded`, `slices`, `risks` and `asks`: `title` is one line, non-empty after stripping. A sprint's title is its latest brief's title, whitespace collapsed and cut to 60; a sprint with no brief, or a logged brief without a title, falls back to the goal's first sentence (the first line up to the first `.`, `!` or `?` followed by whitespace or the end, else the whole line), cut to 60.

**A question's `question` is its ask, and `context` rides beside it.** `question` is the one thing the owner answers; the optional `context` member holds the why, may span lines, and is shown under the ask. A row of a round without a context is byte-identical to one logged before.

**Logged rows render cut, never refused.** The fold re-checks every logged `questions.asked` row without the limits, so a round logged over a limit folds into open questions with its full text; the view cuts text for display with one rule, `cut(text, limit)`: the text when it fits, else its first `limit - 1` characters, stripped, and an ellipsis. Options and the recommendation are cut for display only; the recommendation's identity is its index among the logged options.

**Only the sprint entry carries the goal.** On the wire the sprint entry (the sprint's detail) holds `goal`; every inbox item, `unstopped` entry and digest sentence names the sprint by its title. The brief card shows the title and keeps the full goal in a closed fold on every version.

## Consequences

- A manager on an older contract is refused with `the brief has no title` until it sends one, and with a limit named when a question runs long; the manager contract says both.
- Rows logged before this decision show an ellipsis where they exceed a limit, or a goal's first sentence where the brief has no title; nothing is rewritten in the log.
- The goal text still reaches the page, but only inside the sprint's own detail.
