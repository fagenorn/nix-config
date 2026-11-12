# ADR-console-019 — A manager's questions arrive as inbox items and are answered on the page

- **Status:** accepted
- **Decided in:** #826, #836, #891

## Context

A third of what the owner typed was answers to a manager's questions, each in a separate terminal. ADR-console-013 and ADR-console-016 already carry a brief to the page and the owner's words back to the manager; a question had no route of its own, so it rode in the brief's asks or in a terminal prompt the owner had to find.

## Decision

**A round.** `sprint ask` sends one round of questions for a sprint, the manager's own write under ADR-console-013. Each question says what it blocks, offers two to four options and names the recommended one. A round is accepted only for a sprint whose brief is approved, and a malformed round is refused with the first bad member named.

**Kept only in the console's log.** A round and each answer are the kept kinds `questions.asked` and `question.answered` (schema 8, ADR-console-009), never written to the tracker. A round's id is the sequence number of its `questions.asked` row and a question is `(round, index)`. Each open question is an inbox item, and the sprint reads waiting on you (n) while any is open.

**One open round.** A sprint has one open round at a time: a second round is refused while any question is open unless it is a `blocker`, a round that stops all work until it is answered. The service enforces this under its ingest lock; the fold applies every well-formed row.

**An answer is a message.** The owner answers on the page with an option, the recommended one preselected, or in their own words. The answer is a message of kind `answer`, stored first and nudged to the manager like every message (ADR-console-016), and the manager reads it with `sprint inbox`, which names the question, the round and the option chosen. An answer other than the recommendation, own words included, is recorded as differing and said in the digest.

**Routes.** `POST /api/ask` is a manager write guarded by the sprint's secret (ADR-console-013): any `Origin` is refused, the body is at most 65536 bytes, and success is 200 with the round id and the question count. `POST /api/round-answer` is the eighth page write (ADR-console-008): the token and the console's own origin, a body of at most 16384 bytes, an empty `204` on success.

**The contract.** The manager decides reversible matters inside the approved brief, answers a delivery's may I proceed itself, and brings every real choice to the owner in one round. The contract is not in the instruction corpus, so there is no Instruction Budget raise (ADR-console-015).

## Consequences

- A round and its answers live only in the console's log, which the retention pass never prunes for these kinds: losing the log loses them, as no copy is on the tracker.
- A blocker lets a manager stack rounds, so the contract asks for one only when work cannot continue.
