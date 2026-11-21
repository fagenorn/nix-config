# ADR-console-100 — A manager's Bash permission prompt waits for the owner's answer on a card

- **Status:** accepted
- **Decided in:** #1424

## Context

ADR-console-021 refuses every permission prompt of a manager's session with one fixed sentence, because nobody watches a manager's terminal, and ADR-console-004 keeps a session waiting in its terminal out of the inbox. The console's own HTTP hook still marked such a prompt as waiting on 21 November: the refused request set the session's waiting state, a workflow agent's prompt did the same under the manager's session id, and nothing cleared it, so a manager that was working read as waiting on the owner for hours. The owner manages only through the console, so a prompt the owner could answer was never offered to them.

## Decision

**D1. A Bash prompt is held for the owner.** The manager's `PermissionRequest` hook runs `sprint permit --prompt`. It holds a prompt for a Bash command with a string command, asks the console, and polls it every two seconds for up to ten minutes. The owner allows the command once or refuses it on a permission card; every other prompt, the question tool included, is refused at once with ADR-console-021's sentence.

**D2. Allow once is a hook decision, never a rule.** The allow carries no permission update, and the manager's deny rules and every `PreToolUse` hook (the lifecycle guard, `sprint permit`) still run before a prompt exists, so allowing a prompt never bypasses them.

**D3. The answer route is an owner-only page write.** The card is answered on the page; the route is in the owner's page writes and in no guest or manager list.

**D4. A card is open only while its hook is held.** The hook's contact is the evidence that this prompt is still waiting, so a card whose hook stopped asking leaves, and a late answer is refused.

**D5. Prompts of one session are held side by side.** A manager's workflow agents carry its session id and can each hold a prompt; an ask never closes another.

**D6. The close and the answer are one decision.** The hook's final close is decided on the console together with the owner's answer, and the hook prints what the console decided, so an allow given between the last wait and the close is honored.

**D7. A crashed hook still refuses.** The settings command is `sprint permit --prompt || printf ...` with the fixed refusal, so a hook that fails to start or crashes refuses the prompt.

**D8. The view counts open cards only.** A session's waiting state counts nothing for the owner, and a waiting state clears when the session's own or its agents' transcripts hold a turn after it.

**D9. The hook proves the console before it sends the secret.** Another local account may own the loopback port while the console restarts. Before the ask and each wait or close the hook sends a nonce with no secret and sends the secret only when the reply is the HMAC of the nonce under the sprint's secret, so such a process gets no secret and has no decision honoured. A reply counts only for the prompt asked.

**D10. A request to leave the sandbox is refused, and a closure is told as the console's.** Allow once approves the whole tool input while the card shows only the command, so a prompt that asks to run outside the sandbox is refused at once. A prompt the console closed (a stopped sprint, an ended session) reaches the hook as `ended`, not as ten minutes unanswered.

## Consequences

- A manager's turn waits up to ten minutes on an unanswered card; unanswered, the prompt is refused with its own sentence and the manager goes on.
- After a console restart a card shows again only when its hook's next wait arrives.
- A session whose agents write while one prompt is held reads working.
- The lifecycle guard is unchanged.
- Related: ADR-console-004, ADR-console-021, ADR-console-094, ADR-console-097.
