# ADR-console-052 — The owner posts and withdraws a notice to every manager of a project

- **Status:** accepted
- **Decided in:** #1120

## Context

ADR-console-044 let a manager post a notice for its project and ADR-console-046 put the open notices in front of every manager, but only a manager could post one. When the owner has something every sprint of a project should know, such as a frozen route or a file nobody should touch, they tell each manager by hand with "Tell the manager", one sprint at a time, and a sprint started later never hears it. The owner needs the same short, bounded, informational notice, posted once from the page and read by every manager of the project, now and at launch. It stays information: the console still refuses nothing because of it.

## Decision

**D1. Rows and payloads.** The owner's notice reuses the two kept rows of ADR-console-044, with the project in the project column and no `sprint_id` member, so the sprint fold never sees it: `notice.posted {"poster": "owner", "notice": {"kind": "heads-up", "text"}}` and `notice.withdrawn {"poster": "owner", "notice": <id>}`, where the id is the sequence number of the posting row. A row is the owner's only when it has `"poster": "owner"`, no `sprint_id` and a non-empty project; any other row of that shape changes nothing.

**D2. Bounds.** The text is one line of at most 280 characters, the bound of ADR-console-044 D2, and a project has at most 5 open notices of the owner's; a sixth is refused with the reason and nothing is appended. The kind is always a heads-up: the owner posts no claim and no hand-off.

**D3. Who may post, and when it ends.** The owner posts for a registered project with a running sprint, one that is open and not stopping, and the refusal says which of the two is missing. It needs no approved brief. It ends only when it is withdrawn: it belongs to the project, not to a sprint, so a sprint closing, stopping or dropping does not end it. Only the owner withdraws it: a manager's `sprint withdraw-notice` of it is refused, and the owner's withdrawal of a manager's notice is refused with the reason.

**D4. The two routes.** `POST /api/owner-notice` takes `{"project_id", "text"}` and `POST /api/owner-notice-withdraw` takes `{"project_id", "notice"}`, each of at most 4096 bytes. Both are page writes (ADR-console-008): the origin and the token are checked before any body is read, and a refused one appends nothing. A body the parser does not accept is 400 `bad owner notice` or `bad owner notice withdrawal`; a refusal of the rules in D2 and D3 is 409 with its reason; any other failure is 500 `owner notice failed` or `owner notice withdrawal failed`; success is an empty 204. Nothing logged names the text or the token.

**D5. What the managers read.** The owner's open notices join the project's list: a manager reads them in its first prompt, with `sprint inbox`, with `sprint status` and in `sprint notices`, in the block ADR-console-046 D4 defined, one line each: `- heads-up from the owner, <age>: <text>`. Every manager reads it, whoever it is for.

**D6. The nudge.** A running manager that is reachable learns of a new owner notice without being asked: the console sends the one fixed sentence of ADR-console-016, which tells it to run `sprint inbox`, never the owner's words, by the same routing a message takes, and records one `notice.nudged` row for the project with the route and its outcome. That row is an observation, not a kept kind, and nothing folds it. A notice nudge is not retried, counts as no failed nudge and delivers no message; one that cannot be started is the same row with no route and the reason, and the post still answers 204. A nudge already under way covers a notice posted before it started, so one relay carries a message and a notice together.

**D7. The view.** Every notice entry carries `owner`, true for the owner's, with the poster shown as "You" and no sprint id, and every project entry carries `notice_post`, true when the project has an open sprint that takes notices, so the page offers the post. The notice is information and changes no count, statement or inbox (ADR-console-046).

**D8. The page.** A project with a running sprint shows its "Notices" fold even with no notice, and holds a quiet "Post a notice" control: a one-line field with Send and Cancel, the draft and its focus surviving every frame and a refusal's reason beside it. The owner's notice reads "Heads-up, from You" with a quiet Withdraw (ADR-console-002).

**D9. Never approval.** The owner's notice is information and never approval of a brief, a merge or anything else; a manager's contract says so, and a manager answers it by reading it, not by waiting for it.

## Consequences

- No schema step: both kinds were already kept, so the owner's rows survive retention and the event log stays at its schema. An older build skips a row with no `sprint_id`, so it shows no owner notice and breaks nothing.
- The owner's notice is held per project, so a sprint launched later reads it in its first prompt.
- ADR-console-044 D9 and ADR-console-046 D1, "only a manager posts", no longer hold: the owner posts too. Their other rules are unchanged.
- The manager contract is outside the instruction corpus, so no Instruction Budget raise follows.
- Related: ADR-console-002, ADR-console-008, ADR-console-016, ADR-console-044, ADR-console-046.
