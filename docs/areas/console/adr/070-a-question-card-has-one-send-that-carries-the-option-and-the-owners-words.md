# ADR-console-070 — A question card has one send that carries the option and the owner's words

- **Status:** accepted
- **Decided in:** #1242

## Context

ADR-console-019 lets the owner answer a manager's question with an option or with their own words. The manager's look check offers three options: approve, approve with one fix, ask for changes. The card had two sends with two payloads: "Send answer" posted the picked option and dropped the words box, and "Send my words" posted the words and dropped the option. On 17 Nov an owner picked "Ask for changes", typed what to change, and sent: the words were lost and the manager received only the label, which tells it nothing to act on.

## Decision

**D1. One send.** The card has one send. It posts the picked option, the owner's words, or both in one answer. The separate "Send my words" button is gone.

**D2. The manager marks which option needs words.** A question carries `needs_words`, a list of the exact texts of the options whose answer needs the owner's words (one or more). The console exposes it to the page as `needs_words_index`, the list of those options' indices counted like `recommended_index` against the logged options (ADR-console-027). The page never guesses it from an option's label: an option the manager did not mark sends without words, as before.

**D3. The body and the rows.** The body of `POST /api/round-answer` carries `choice`, `text` or both. With both, the `question.answered` row gains `"words"`, the owner's words, beside `answer` and `chosen`; with one of them the row is the row it was. The `sprint inbox` entry of an answer always carries `words`: null for an option alone, the answer text for words alone, and the owner's words beside the option for both.

**D4. `differs` is unchanged.** `differs` stays `chosen != recommended`. Words do not make an answer differ, and the digest speaks the answer text only when `differs` is true, as before.

**D5. An option can be unpicked.** A manager question starts with its recommended option picked (ADR-console-019). Clicking the picked option unpicks it, so words alone stay possible while the recommendation is preselected.

**D6. Words are required where marked.** Picking the option that needs words with no words typed is refused by the card with "Say what to change." and by the service with "say what to change", and nothing is appended. Typed words leave the box only when the service answers 204; a refused or failed send keeps them.

## Consequences

- No schema bump: a round without `needs_words` and an answer without `"words"` are byte-identical to what they were (ADR-console-027), so every stored row reads as before.
- A manager on the older contract never marks `needs_words`, so its options send without words as before, and the owner can still add words, which the manager reads on the answer.
- The owner's words reach the manager in the same answer as the option, so the manager never has to ask again what to change.
- Related: ADR-console-019, ADR-console-027.
