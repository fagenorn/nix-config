# Wayfind — why the disciplines are shaped this way

SKILL.md owns the rules; this file owns their rationale and the traps they
prevent. Read it when a rule feels skippable.

## Why gists are one line, ≤160 characters

Every line of the map body is a gist: enough to decide whether to open the
ticket, never enough to stand in for it. A Decisions-so-far gist holds the
operative values — the dates, amounts and choices a later session would
otherwise re-derive — with ticket links exempt from the cap. A research ticket's
gist is the conclusion the decision turned on, never a summary of the findings —
those stay in the linked file. A long gist buys nothing: it doesn't spare the
next session the ticket read, and every session pays for it again.

## Why compression is same-session and starts from a fresh read

A body pushed past its ~6k budget is compressed back under before the session
finishes — never deferred to a follow-up, because the follow-up pays the whole
context cost again to learn what to cut. Fold gists a later decision subsumed
into the one that superseded them; cut back to its link any entry that has grown
an explanation. Compression rewrites the index; it never deletes from it — every
closed ticket keeps its link. The whole-body rewrite starts from a fresh read
because rewriting from the copy already in context silently drops the lines a
concurrent session appended meanwhile.

## Why tickets never paste each other's resolutions

A `Note (from <ticket>) …` block is a second copy of a decision that already has
a home — it goes stale silently the moment that ticket is amended, and it
teaches the next session that tickets are stores, so it opens a dozen of them
looking for what else was pasted. The ticket is the store; everything else
points at it. Cite a sibling by link plus one line of what it settled, and open
the ticket itself when you need more.

## Why one sitting per ticket

A ticket is sized to one fresh-context session because a resumed one pays for
the whole context twice, and the second payment buys nothing. Take the ticket
you can finish now. If you must stop mid-resolution, park state in the ticket
before you go — what's settled, what's still open, what you were about to do
next — so the next sitting resumes from the ticket instead of from a transcript
it no longer has.

## Native blocking and the database-id trap

Blocking uses the tracker's native dependency relationship because it renders
the frontier *visually* in the tracker's own UI — a human sees what's takeable
without opening the map. Only a tracker without native blocking falls back to a
body convention. Same mechanism and same trap as documented in `to-issues`
(GitHub: `POST .../issues/<child>/dependencies/blocked_by -F
issue_id=<blocker-db-id>`, where `issue_id` is the blocker's **numeric database
id** from `--jq .id`, never the `#number`).
