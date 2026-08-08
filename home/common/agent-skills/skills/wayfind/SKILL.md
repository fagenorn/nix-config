---
name: wayfind
description: Chart a big fuzzy effort as a map issue with decision tickets, then resolve one decision per session until the way is clear. Use for ideas too foggy to spec or slice.
---

# Wayfind

A loose idea has arrived — too big for one session and wrapped in fog: the way to the **destination** isn't visible yet. Wayfinding charts the way as a **shared map** on the issue tracker and works its **decision tickets** — questions whose resolution is a decision, not slices of a build — one at a time until nothing is left to decide. Then the effort leaves this skill: specs go to `to-issues`, builds go to `from-issue` — **Decisions so far** is what their slices cite in `## Decisions`, so an implementing agent inherits the answers instead of re-deriving them.

This is **planning, not doing**. The pull to just do the work is usually the signal the map is done and it's time to hand off. Sits between `prototype` and `to-issues`; replaces `prototype` as the entry point when the open question isn't UI- or state-shaped.

Resolve tracker bindings from `.claude/skills.config.json` (`issueTracker{kind,cli}`, default GitHub/`gh`). `kind: none` → the same structure as markdown under `.claude/wayfind/<effort>/`: the map at `map.md`, each ticket a `tickets/NNN-<slug>.md` whose front-matter carries `type: wayfinder:<type>`, `state: open|closed`, `assignee` and `blocked_by: [NNN, …]` above its `## Question`; resolving appends `## Resolution` and flips `state`.

## The map

One issue labelled `wayfinder:map`; tickets are its child issues. The map is an **index, not a store** — a decision lives in exactly one place (its ticket); the map gists and links. Refer to tickets by **name** (title wrapping the link), never bare numbers — a wall of `#42, #43` is illegible.

Map body, loaded low-res once per session:

```markdown
## Destination
<what reaching the end looks like — the spec, decision, or change. 1–2 lines; every session orients here first.>

## Notes
<domain; skills every session should consult; standing preferences>

## Decisions so far
- [<closed ticket title>](link) — <one-line gist of the answer>

## Not yet specified
<fog: suspected questions not yet phrasable sharply — see Fog of war>

## Out of scope
<work consciously ruled beyond the destination — gist + why + closed-ticket link. Never graduates.>
```

## Tickets

A ticket's body is its `## Question`, sized to one fresh-context session. Label `wayfinder:<type>`; each type is **HITL** (worked with a human who speaks for themselves — the agent never answers the human's side) or **AFK** (agent alone):

- **research** (AFK) — a fact a decision waits on, from docs/APIs/knowledge bases. Resolved by dispatching the `research` skill's background agent; findings file linked from the ticket.
- **prototype** (HITL) — raise the discussion's fidelity with a cheap concrete artifact via the `prototype` skill; link the artifact.
- **grilling** (HITL) — conversation; the default. Invoke `grill-with-docs`.
- **task** (HITL or AFK) — manual work that must happen before a decision *can* be made (provision access, move data so its shape is visible). The one type that does rather than decides; earns its place by unblocking a decision. Resolution records what was done and the facts later tickets depend on.

Whatever a session makes while resolving — findings file, prototype, checklist — is **linked** from the ticket, never pasted into it.

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

1. Load the map low-res — not every ticket body.
2. Choose: the user's named ticket, else the first frontier ticket. **Claim it.**
3. Resolve it, zooming into related/closed ticket bodies on demand; use the skills the ticket type and the map's Notes name. Never resolve more than one ticket per session (research dispatches excepted).
4. Record: answer as a resolution comment, close the ticket, append its one-line gist to Decisions so far.
5. Maintain — part of resolving, not optional cleanup: graduate the fog this answer made phrasable (create-then-wire the fresh tickets, delete the graduated entry), rule out-of-scope discoveries out, update or delete tickets the decision invalidated. One-ticket-per-session bounds what you *resolve*, never this bookkeeping — closing a ticket without clearing the fog it lifted leaves the map worse than you found it. Expect concurrent sessions on other tickets.

## Inflow from the fog gate

`from-issue --auto`'s Phase-0 fog gate emits one decision ticket per unphrasable question. File each under the effort's existing map when one covers the area; otherwise create a minimal map (destination = the aborted issue's intent) and attach them. The aborted issue gets a comment linking the tickets and is blocked by them via the native relationship.
