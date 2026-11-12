# ADR-console-012 — The page answers owner prompts through the runner's owner path

- **Status:** accepted
- **Decided in:** #836, #837, #863, #895

## Context

A held verification waits on the owner through an owner prompt, a live `owner-action` marker the runner posts on the issue (ADR-verification-009). The owner had to leave the console to tick it. #837 says such a hold is an inbox item only when it needs the owner, and #863 lets the page answer it, as #862 did for a decision prompt (ADR-console-010). #836 sets the bar for a costly answer: a release or a live or paid check is approved from the page "with the preview shown in full and a typed confirmation", and a free-text reply is always possible.

## Decision

1. **One route, one item.** The page answers a verification prompt with `POST /api/check-answer`, a page write under ADR-console-008, whose body names the project, one item key, the answer and the item's content version (a digest of the prompt's fields and text as the page showed it), plus the note for a note and the typed confirmation for an approval. The console answers through the single-prompt owner path of the verification area (`verify_answer`), which re-reads the live prompt as the owner, refuses it when its content no longer matches the version the page sent, and ticks, ends or comments exactly once; the console passes no token and copies nothing, so the tracker stays the record. This is the console's one new import edge.
2. **The answers by kind.** A manual check takes passed, failed or a note. A verdict takes "Accept as passed" or "Close as not verified". An approval takes approve. A stale check takes keep or drop. An act prompt has no box, so the page shows its detail and offers no answer.
3. **A note ticks nothing.** It is one plain owner comment on the issue, the note verbatim after a fixed first line naming the prompt; the check keeps waiting and the item stays open. A note that would carry a verify block is refused, because a trusted comment with one becomes the held block. The note field is a multi-line textarea.
4. **Keep and drop.** `drop` ticks the prompt's only box, "Accept without <host>". `keep` ends the stale prompt as `kept`: the check keeps waiting on its host and the runner never asks that stale identity again.
5. **A typed confirmation for every approval.** Every approval, live or paid, keeps its full detail and the line `Type <owner>/<repo>#<issue> to approve.` with a single-line field in one fold, "Review and approve", that the owner opens; Approve stays disabled until the field equals that text exactly, and the post carries it. A paid approval adds the line "This check costs money." The runner path refuses an approval without the confirmation, and refuses a paid one unless the console says it is paid. #863 names the confirmation only for paid checks; the stricter rule of #836 item 5 is the one kept.
6. **The console has no multi-item action.** The page and the console answer one item per request, so a live approval is never sent behind another item's confirmation and no preview goes unseen. The runner's `approve --all-live` stays the only bulk path, and it never ticks a paid prompt (ADR-verification-009).
7. **Need and trust.** A prompt is an item only from an owner or member comment, only while live within that trusted set, and only when it names its block and check. A prompt with both boxes ticked is not answered, so its item stays open and the answer is refused until one box is unticked. A held issue with no live prompt raises no item.
8. **The same undo and the keys.** Every answer goes through the five-second undo of ADR-console-010 and then the existing states: waiting, sending, answered, "Could not send: <reason>". A sent note returns the box to choosing with the field cleared and "Note sent.". Number keys and Enter keep acting on decision items only, and are ignored while an input, textarea, select or contenteditable element has focus; Escape still undoes.
9. **Typed text survives a frame.** The page keeps each field's unsent text and selection in a draft keyed by item and field, restores them and the focus after every streamed frame, and drops the draft when the item is no longer open (and not waiting or sending) or its answer is sent.

## Consequences

- The page now has two answer calls, each literal, and no other write answers an item.
- An old logged item lacks the new members, so the view reads them with defaults and the next tracker read rewrites it.
- An answer for a prompt that changed since the page showed it, in its text or fields as well as in its boxes, is refused with the tracker's reason and shown as "Could not send"; the version is taken when the owner chooses the answer, so a frame that revises the prompt during the undo does not rebind it.
- A page closed inside the undo sends nothing.
