---
name: wayfind
description: Chart a big fuzzy effort as a map issue with decision tickets, then resolve one decision per session until the way is clear. Use for ideas too foggy to spec or slice.
---

# Wayfind

A loose idea has arrived — too big for one session and wrapped in fog: the way to the **destination** isn't visible yet. Wayfinding charts the way as a **shared map** on the issue tracker and works its **decision tickets** — questions whose resolution is a decision, not slices of a build — one at a time until nothing is left to decide. Then the effort leaves this skill: specs go to `to-issues`, builds go to `from-issue` — **Decisions so far** is what their slices cite in `## Decisions`, so an implementing agent inherits the answers instead of re-deriving them.

This is **planning, not doing**. The pull to just do the work is usually the signal the map is done and it's time to hand off. Sits between `prototype` and `to-issues`; replaces `prototype` as the entry point when the open question isn't UI- or state-shaped.

Resolve tracker bindings from `.claude/skills.config.json` (`issueTracker{kind,cli}`, default GitHub/`gh`). `kind: none` → the same structure as markdown under `.claude/wayfind/<effort>/`: the map at `map.md` carrying `state: open|complete` in its front-matter, each ticket a `tickets/NNN-<slug>.md` whose front-matter carries `type: wayfinder:<type>`, `state: open|closed`, `assignee` and `blocked_by: [NNN, …]` above its `## Question`; resolving appends `## Resolution` and flips `state`.

## The map

One issue labelled `wayfinder:map`; tickets are its child issues. The map is an **index, not a store** — a decision lives in exactly one place (its ticket); the map gists and links. Refer to tickets by **name** (title wrapping the link), never bare numbers — a wall of `#42, #43` is illegible.

**Low-res** = title and body only, no ticket bodies (GitHub: `gh issue view <n> --json title,body`; `kind: none`: the `map.md` file itself); ticket bodies open on demand while resolving, one at a time, never as a set.

Map body, loaded low-res once per session:

```markdown
## Destination
<what reaching the end looks like — the spec, decision, or change. 1–2 lines; every session orients here first.>

## Notes
<domain; skills every session should consult; standing preferences — pointers only: the facts live in the tickets. Any entry running past ~2 lines is a ticket or a linked artifact, not a note.>

## Decisions so far
- [<closed ticket title>](link) — <the answer in one line: ≤160 chars of operative values — dates, amounts, the choice made>

## Not yet specified
<fog: suspected questions not yet phrasable sharply — see Fog of war>

## Out of scope
<work consciously ruled beyond the destination — gist + why + closed-ticket link. Never graduates.>
```

Every line of this body is a **gist**: enough to decide whether to open the ticket, never enough to
stand in for it. A Decisions-so-far gist is one line of prose — no sub-bullets, no paragraph — holding
≤160 characters of operative values: the dates, amounts and choices a later session would otherwise
re-derive. The ticket links it carries don't count against the cap. A research ticket's gist is the
conclusion the decision turned on, never a summary of the findings — those stay in the linked file. A
long gist buys nothing: it doesn't spare the next session the ticket read, and every session pays for
it again.

The body's budget is **~6k characters**. A session that pushes it past that compresses back under
before it finishes — same session, never a follow-up: fold gists a later decision subsumed into the
one that superseded them, and cut back to its link any entry that has grown an explanation.
Compression rewrites the index; it never deletes from it — every closed ticket keeps its line. It is
also the one exception to the once-per-session low-res load: a whole-body rewrite starts from a fresh
read, because rewriting from the copy already in context silently drops the lines a concurrent
session appended meanwhile.

## Tickets

A ticket's body is its `## Question`, sized to one fresh-context session. Label `wayfinder:<type>`; each type is **HITL** (worked with a human who speaks for themselves — the agent never answers the human's side) or **AFK** (agent alone):

- **research** (AFK) — a fact a decision waits on, from docs/APIs/knowledge bases. Resolved by dispatching the `research` skill's background agent; findings file linked from the ticket.
- **prototype** (HITL) — raise the discussion's fidelity with a cheap concrete artifact via the `prototype` skill; link the artifact.
- **grilling** (HITL) — conversation; the default. Invoke `grill-with-docs`.
- **task** (HITL or AFK) — manual work that must happen before a decision *can* be made (provision access, move data so its shape is visible). The one type that does rather than decides; earns its place by unblocking a decision. Resolution records what was done and the facts later tickets depend on.

Whatever a session makes while resolving — findings file, prototype, checklist — is **linked** from the ticket, never pasted into it.

The same holds between tickets: cite a sibling by **link plus one line** of what it settled, and open
the ticket itself when you need more. Never paste another ticket's resolution into this one. A
`Note (from <ticket>) …` block is a second copy of a decision that already has a home — it goes stale
silently the moment that ticket is amended, and it teaches the next session that tickets are stores,
so it opens a dozen of them looking for what else was pasted. The ticket is the store; everything
else points at it.

**Claim before work**: assign the ticket to yourself first; an open unassigned ticket is unclaimed. Blocking uses the tracker's **native** dependency relationship, because that renders the frontier *visually* in the tracker's own UI — a human sees what's takeable without opening the map. Only a tracker without native blocking falls back to a body convention. Same mechanism and same database-id trap as documented in `to-issues` (GitHub: `POST .../issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `issue_id` is the blocker's **numeric database id** from `--jq .id`, never the `#number`). The **frontier** = open, unblocked, unclaimed children.

## Fog of war

Chart only what you can see. The test between ticket and fog: **can you state the question precisely now** (not: answer it now)?

- Sharp question → ticket, even if blocked.
- Can't phrase it sharply yet → one loose entry in **Not yet specified**; don't pre-slice fog into ticket-sized pieces — a patch may graduate into several tickets, or none.

**Not yet specified** carries only fog: not what's already decided (Decisions so far), not what's already a live ticket, not what's out of scope.

Resolving a ticket clears fog: graduate what became phrasable into fresh tickets and delete it from Not yet specified. Work past the destination is not fog — rule it **Out of scope** (close any mis-scoped ticket, one gist line on the map). The frontier stops at the destination, so out-of-scope work returns only if the destination is redrawn, and then as a fresh effort, never a resumption of this one.

## Chart the map (first invocation, from a loose idea)

1. **Name the destination** — a `grill-with-docs` session pins what this effort is finding its way to. Destination fixes scope, so it's settled first.
2. **Map the frontier** — grill again, breadth-first across the whole space. **No fog surfaced?** The journey fits one session — no map; say so and route to `design`/`to-issues` instead.
3. **Create the map** (Destination + Notes filled, fog sketched into Not yet specified).
4. **Create the specifiable tickets** as children, then wire blocking edges in a second pass (issues need ids before they can reference each other).
5. **Fire the research tickets** — dispatch a `research` agent per ticket, in parallel.
6. Stop. Charting is one session's work; it resolves nothing by hand.

## Work the map (later invocations, with the map's URL or number)

**One sitting per ticket.** A ticket is sized to one fresh-context session because a resumed one pays
for the whole context twice, and the second payment buys nothing. Take the ticket you can finish now.
If you have to stop mid-resolution, park state in the ticket before you go — what's settled, what's
still open, what you were about to do next — so the next sitting resumes from the ticket instead of
from a transcript it no longer has.

1. Load the map low-res. Under `kind: none` that is the session's only read of it (compression excepted — a whole-body rewrite starts from a fresh read, per the body's ~6k budget): record into the copy you already loaded rather than re-reading before you write, and anchor the edit under its section heading so a concurrent session's line survives yours. On a shared tracker, re-read the body just before updating it — other sessions do land there.
2. Choose: the user's named ticket, else the first frontier ticket. **Claim it.**
3. Resolve it, zooming into related/closed ticket bodies on demand; use the skills the ticket type and the map's Notes name. Never resolve more than one ticket per session (research dispatches excepted).
4. Record: answer as a resolution comment, close the ticket, append its gist to Decisions so far — one line, ≤160 characters, links exempt. If that push takes the body over its ~6k budget, compress it back under now, before you finish.
5. Maintain — part of resolving, not optional cleanup: graduate the fog this answer made phrasable (create-then-wire the fresh tickets, delete the graduated entry), rule out-of-scope discoveries out, update or delete tickets the decision invalidated. One-ticket-per-session bounds what you *resolve*, never this bookkeeping — closing a ticket without clearing the fog it lifted leaves the map worse than you found it. Expect concurrent sessions on other tickets.
6. **Complete the map** when the decision frontier is empty — no open ticket whose resolution is a decision — and **Not yet specified** is empty. Anything still open is re-dispositioned explicitly: resolved, ruled out of scope, or named a **standing verification hook** that outlives the effort, its reopen condition written down. Then close the map (`kind: none`: front-matter `state: open` → `complete`) with a closing note under **Destination** — what was reached, a link to the spec it produced or to Decisions so far when there is none, and the next command by name: `/to-issues` for a multi-slice spec, `/from-issue` for a build that fits one session. Announce it, run nothing: the spec and the handoff are the human's.

## Inflow from the fog gate

`from-issue --auto`'s Phase-0 fog gate emits one decision ticket per unphrasable question. File each under the effort's existing map when one covers the area; otherwise create a minimal map (destination = the aborted issue's intent) and attach them. The aborted issue gets a comment linking the tickets and is blocked by them via the native relationship.
