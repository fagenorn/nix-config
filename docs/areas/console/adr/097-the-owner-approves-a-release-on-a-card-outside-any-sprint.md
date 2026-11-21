# ADR-console-097 — The owner approves a release on a card outside any sprint

- **Status:** accepted
- **Decided in:** #1401

## Context

ADR-console-094 removed the release from the manager permit because a permit that judges the text of a shell command cannot name every spelling that runs a release, and named issue 1401 as the enforcement. The owner then decided (D1) that the release command itself refuses a candidate, the pair of a commit and a version, that has no approved release card on record, whoever calls it and however it is spelled; no check of shell text decides it. The owner also decided (D2) that the lead posts the candidate to the console as a release card outside any sprint and the owner approves it on the console page, so every approval is a console record, and a release is refused when the console on that host cannot be read.

## Decision

**D1. A card outside any sprint.** The lead posts one release card for the pair (`commit`, `version`) with `release-card post`, which sends `POST /api/release-card` to the owner's port. The card belongs to no sprint, manager or project: it is one `release_card.posted` row with a null project, and the owner's answer is one `release_card.answered` row.

**D2. The owner approves it on the page.** `POST /api/release-answer` is an owner-only page write behind the guard of ADR-console-008, in neither `GUEST_WRITES` nor `MANAGER_WRITES`. The page lists each open card with an Approve release and a Decline button and picks neither. The first answer to an open card wins, and a card that is not open takes no answer. The lead's post is an owner-port route that is not a page write: it refuses any `Origin`, and it approves nothing.

**D3. The kinds are not kept.** The two kinds stay out of `KEPT_KINDS`, so the console's retention removes them with the other rows and the schema does not change.

**D4. The release command reads the store.** The release command reads the host console's store read-only at `release_card.host_store()`, the home the password database names for this user and never `$HOME`, and decides from the folded cards.

## Consequences

- Posting approves nothing: only the owner's answer on the page does.
- The approval is as strong as the page-write guard of ADR-console-008. A process of the owner's uid that holds the page token or writes the store could forge it, as it could any owner answer today.
- An approval older than 90 days lapses at read time, whether or not retention has run.
- The page lists only open cards, so a re-post of an approved pair offers nothing to click; the skill then asks in chat.
- Related: ADR-console-008, ADR-console-094.
