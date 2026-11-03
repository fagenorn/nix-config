---
name: wayfind
description: Charts a foggy effort as a map issue of decision tickets and resolves one per session. Use for ideas too foggy to spec or slice.
---

# Wayfind

For a loose idea too big for one session whose **destination** isn't visible yet. Wayfind charts the way as a **shared map** on the tracker and works its **decision tickets** (questions resolved by decisions, not build slices) one at a time until nothing is left to decide. Then specs go to `to-issues` and builds to `from-issue`, whose slices cite **Decisions so far** in `## Decisions`.

This is **planning, not doing**: the pull to just do the work usually means the map is done. It replaces `prototype` when the open question isn't UI- or state-shaped. Read [DISCIPLINE.md](./DISCIPLINE.md) when a rule below feels skippable.

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Use `bindings.tracker` and `capabilities.tracker`; authored unsupported uses the local map route, while blocked stops. The local map is `map.md` with `state: open|complete` front-matter; tickets are `tickets/NNN-<slug>.md` with `type: wayfinder:<type>`, `state`, `assignee` and `blocked_by: [NNN, …]` above `## Question`; resolving appends `## Resolution` and flips `state`.

## The map

One issue labelled `wayfinder:map`, with the tickets as its children. The map is an **index, not a store**: a decision lives only in its ticket. Name tickets by title wrapping the link, never by bare number.

**Low-res** means title and body only (GitHub: `gh issue view <n> --json title,body`; `kind: none`: `map.md`). Ticket bodies open on demand, one at a time. The map body, loaded low-res once per session:

```markdown
## Destination
<the spec, decision, or change reaching the end produces. 1–2 lines; every session orients here first.>

## Notes
<domain; skills to consult; standing preferences — pointers only: facts live in the tickets. Entries past ~2 lines are a ticket or linked artifact, not a note.>

## Decisions so far
- [<closed ticket title>](link) — <the answer: ≤160 chars of operative values — dates, amounts, the choice>

## Not yet specified
<fog: questions not yet phrasable sharply — see Fog of war>

## Out of scope
<work consciously ruled beyond the destination — gist + why + closed-ticket link. Never graduates.>
```

Every body line is a **gist**: one line of at most 160 characters of operative values, links exempt. The body's budget is **~6k characters**; a session that pushes past it compresses back under before it finishes, folding subsumed gists into their superseder and cutting grown explanations back to links. Compression never deletes a closed ticket's link, and it rewrites from a fresh read of the body, the one exception to loading it once.

## Tickets

A ticket's body is its `## Question`, sized to one fresh-context session. Label it `wayfinder:<type>`; **HITL** types are worked with a human who speaks for themselves (the agent never answers the human's side), **AFK** types by the agent alone:

- **research** (AFK): a fact a decision waits on; dispatch the `research` skill and link its findings file.
- **prototype** (HITL): a cheap concrete artifact via the `prototype` skill, linked.
- **grilling** (HITL, the default): a conversation; invoke `grill-with-docs`.
- **task** (HITL or AFK): manual work needed before a decision can be made; the resolution records what was done and the facts later tickets need.

Link what a session makes from the ticket, never paste it. Cite a sibling ticket by link plus one line, never by pasting its resolution.

**Claim before work**: assign the ticket to yourself; open and unassigned means unclaimed. Blocking uses the tracker's native dependency relationship; on GitHub that is the same `blocked_by` call as `to-issues`, whose `issue_id` is the blocker's **numeric database id** (`--jq .id`), never its `#number`. **Frontier** = open, unblocked, unclaimed children.

## Fog of war

Chart only what you can see. A question you **can state precisely now** (not answer) becomes a ticket, even if blocked. One you can't phrase sharply yet is one loose entry in **Not yet specified**; never pre-slice fog. That section holds only fog: not decisions, live tickets or out-of-scope work.

Resolving a ticket clears fog: graduate newly phrasable entries into tickets and delete them. Work past the destination is not fog: rule it **Out of scope** (close mis-scoped tickets with one gist line); it returns only through a redrawn destination, as a fresh effort.

## Chart the map (first invocation, from a loose idea)

1. **Name the destination** in a `grill-with-docs` session; it fixes scope, so it comes first.
2. **Map the frontier**: grill again, breadth-first. No fog surfaced means the journey fits one session: no map; route to `design` or `to-issues`.
3. **Create the map** with Destination and Notes filled and fog under Not yet specified.
4. **Create the specifiable tickets** as children, then wire blocking edges in a second pass (issues need ids first).
5. **Fire the research tickets**: one `research` agent each, in parallel.
6. Stop. Charting resolves nothing by hand.

## Work the map (later invocations, with the map's URL or number)

**One sitting per ticket**: if you stop mid-resolution, park the state in the ticket first (settled, open, next action).

1. Load the map low-res. Under `kind: none` that is the session's only read (compression excepted): record into the loaded copy, anchored under its section heading so concurrent lines survive; on a shared tracker, re-read just before updating.
2. Choose the user's named ticket, else the first frontier ticket. **Claim it.**
3. Resolve it, opening related or closed tickets on demand and using the skills its type and the Notes name. Resolve at most one per session (research dispatches excepted).
4. Record: a resolution comment, close the ticket, and append its gist to Decisions so far. Over the ~6k budget, compress now.
5. Maintain, as part of resolving: graduate newly phrasable fog (create, then wire, then delete the entry), rule out-of-scope discoveries out, update or delete invalidated tickets. The one-per-session bound limits resolving, never this bookkeeping. Expect concurrent sessions.
6. **Complete the map** when the frontier and Not yet specified are both empty. Re-dispose anything still open explicitly: resolved, out of scope, or a named **standing verification hook** with its reopen condition. Close the map (`kind: none`: `state` → `complete`) with a closing note under Destination: what was reached, a link (the spec, or Decisions so far), and the next command, `/to-issues` (multi-slice spec) or `/from-issue` (single-session build). If existing authorization covers delivering this decision record, deliver it and report; stop on an actual permission denial. Never start a second decision, issue slicing or implementation without separate authorization.

## Inflow from the fog gate

`from-issue --auto`'s Phase-0 fog gate emits one decision ticket per unphrasable question. File each under the existing map that covers the area, else create a minimal map (destination: the aborted issue's intent). The aborted issue gets a comment linking the tickets and is natively blocked by them.
