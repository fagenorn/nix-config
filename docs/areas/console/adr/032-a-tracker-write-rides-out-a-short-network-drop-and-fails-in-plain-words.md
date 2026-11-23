# ADR-console-032 — A tracker write rides out a short network drop and fails in plain words

- **Status:** accepted
- **Decided in:** #1075

## Context

The page answers a decision prompt by ticking a box as the owner (ADR-console-010) and answers an owner prompt through the runner's owner path (ADR-console-012). Both are one write to the tracker through `gh`. A short network drop made that write fail, and the owner saw the raw transport error (a `gh` message, an HTTP status) on the card with no way forward but to choose the answer again. A drop of a few seconds is common, and the owner had already passed the undo once. #1075 makes the console ride it out and say what happened in words the owner can act on.

## Decision

**D1. Which writes.** The tick of ADR-console-010 and the owner path of ADR-console-012 (a check's passed, failed, approve, drop and keep answers). The console never retries a note (D6).

**D2. What is retried.** The transport class of `forge_api`: a `transient` failure, that is a timeout, a connection failure or an HTTP 5xx. The whole operation is read and written again, so each retry checks the tracker as it is now. A refusal or a 4xx is never retried, and neither is `gh` missing, an unreadable payload or any other exception.

**D3. The schedule and its deadline.** A retry waits 1, 2, 4, 8 and 10 seconds, all within 30 seconds of the first attempt.

- That deadline also bounds every `gh` call of every attempt: no call starts after it and none runs past it.
- The last wait is cut so that a last try keeps 5 seconds for its calls, and no retry is made when no time is left for one.
- Closing the console ends the retries.
- The card reads `Sending…` meanwhile.

**D4. An answer already landed.** An answer the prompt already carries is left alone: the decision's tick of exactly the same choices, and the owner path's tick of the same box or, for `keep`, its `kept` end. So a retry whose earlier attempt landed but lost its reply succeeds without a second write, while any other answer to that prompt is still refused as answered.

**D5. Plain words.** A failure the console could not mend is worded by `answer.tracker_words`, for example `Could not send: this computer could not reach GitHub. Check the network, then try again.` A reply with no reason reads `the console did not say why.` No status code, failure kind or exception type reaches the card. The raw error stays on the stderr lines: `console: answer_tick_failed` for the final failure and `console: answer_tick_retry` for each retried one (#1057, #1062).

**D6. A note.** A note posts a comment, so a repeat after a lost reply could post it twice. The console tries a note once, fails with the plain words, and leaves Try again to the owner.

**D7. Try again.** The page offers Try again on a failed answer when the console answered 5xx or did not answer at all, and never on a refusal, where a repeat cannot succeed. It sends the same answer at once, because the owner already passed the undo, and choosing another option drops it. It is a quiet action and not a second primary.

## Consequences

- A retried answer whose earlier attempt landed succeeds without a second write, while another answer is still refused.
- A note after a lost reply may need the owner's Try again, and may then post twice.
- One request may take up to thirty seconds, so the card shows `Sending…` for that long before it fails.
- The module docstrings of `answer.py`, `forge_api.py`, `verify_answer.py` and `service.py` stay the contract for the exact texts.
- Related: ADR-console-010, ADR-console-012.
