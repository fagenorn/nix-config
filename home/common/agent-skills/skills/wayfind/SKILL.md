---
name: wayfind
description: Chart a big fuzzy effort as a map issue with decision tickets, then resolve one decision per session until the way is clear. Use for ideas too foggy to spec or slice.
---

# Wayfind

A loose idea too big for one session, wrapped in fog: the **destination** isn't visible yet. Wayfind charts the way as a **shared map** on the tracker and works its **decision tickets** — questions resolved by decisions, not build slices — one at a time until nothing is left to decide. Then the effort leaves this skill: specs go to `to-issues`, builds to `from-issue`; their slices cite **Decisions so far** in `## Decisions`, so implementing agents inherit the answers.

This is **planning, not doing** — the pull to just do the work usually signals the map is done. Sits between `prototype` and `to-issues`; replaces `prototype` when the open question isn't UI- or state-shaped.

Each discipline's rationale — and the trap it prevents — is in [DISCIPLINE.md](./DISCIPLINE.md); read it when a rule feels skippable.

Resolve tracker bindings from `.claude/skills.config.json` (`issueTracker{kind,cli}`, default GitHub/`gh`). `kind: none` → markdown under `.claude/wayfind/<effort>/`: `map.md` with `state: open|complete` front-matter; tickets `tickets/NNN-<slug>.md` with `type: wayfinder:<type>`, `state`, `assignee`, `blocked_by: [NNN, …]` above `## Question`; resolving appends `## Resolution` and flips `state`.

## The map

One issue labelled `wayfinder:map`; tickets are its children. The map is an **index, not a store** — a decision lives only in its ticket; the map gists and links. Refer to tickets by **name** (title wrapping the link), never bare numbers.

**Low-res** = title and body only (GitHub: `gh issue view <n> --json title,body`; `kind: none`: the `map.md` file); ticket bodies open on demand, one at a time, never as a set.

Map body, loaded low-res once per session:

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

Every line of the body is a **gist**: one line, ≤160 characters of operative values, links exempt — enough to decide whether to open the ticket, never enough to stand in for it (why: DISCIPLINE.md).

The body's budget is **~6k characters**. A session that pushes past it compresses back under before finishing — same session, never a follow-up: fold subsumed gists into their superseder, cut grown explanations back to links. Compression rewrites the index, never deletes from it — every closed ticket keeps its link. It is also an exception to the once-per-session low-res load: the whole-body rewrite starts from a fresh read (why: DISCIPLINE.md).

## Tickets

A ticket's body is its `## Question`, sized to one fresh-context session. Label `wayfinder:<type>`; each type is **HITL** (worked with a human who speaks for themselves — the agent never answers the human's side) or **AFK** (agent alone):

- **research** (AFK) — a fact a decision waits on; dispatch the `research` skill's background agent, findings file linked from the ticket.
- **prototype** (HITL) — raise the discussion's fidelity with a cheap concrete artifact via the `prototype` skill; link the artifact.
- **grilling** (HITL) — conversation; the default. Invoke `grill-with-docs`.
- **task** (HITL or AFK) — manual work needed before a decision *can* be made (provision access, move data so its shape is visible); the one type that does rather than decides. Resolution records what was done and the facts later tickets depend on.

Whatever a session makes — findings file, prototype, checklist — is **linked** from the ticket, never pasted; likewise between tickets: cite a sibling by **link plus one line**, never paste its resolution (why: DISCIPLINE.md).

**Claim before work**: assign the ticket to yourself; open unassigned = unclaimed. Blocking uses the tracker's **native** dependency relationship (mechanism + database-id trap: DISCIPLINE.md). **Frontier** = open, unblocked, unclaimed children.

## Fog of war

Chart only what you can see. The ticket-vs-fog test: **can you state the question precisely now** (not: answer it now)?

- Sharp question → ticket, even if blocked.
- Can't phrase it sharply yet → one loose entry in **Not yet specified**; don't pre-slice fog — a patch may graduate into several tickets, or none.

**Not yet specified** carries only fog: not the decided, not live tickets, not out-of-scope.

Resolving a ticket clears fog: graduate the newly-phrasable into fresh tickets, delete the graduated entries. Work past the destination is not fog — rule it **Out of scope** (close mis-scoped tickets, one gist line); it returns only via a redrawn destination, as a fresh effort.

## Chart the map (first invocation, from a loose idea)

1. **Name the destination** — a `grill-with-docs` session pins it; destination fixes scope, so it's settled first.
2. **Map the frontier** — grill again, breadth-first. **No fog surfaced?** The journey fits one session — no map; route to `design`/`to-issues` instead.
3. **Create the map** (Destination + Notes filled, fog into Not yet specified).
4. **Create the specifiable tickets** as children, then wire blocking edges in a second pass (issues need ids first).
5. **Fire the research tickets** — one `research` agent per ticket, in parallel.
6. Stop. Charting is one session's work; it resolves nothing by hand.

## Work the map (later invocations, with the map's URL or number)

**One sitting per ticket**; stopping mid-resolution parks state in the ticket first — settled, open, next action (why: DISCIPLINE.md).

1. Load the map low-res. Under `kind: none`, that is the session's only read (compression's rewrite excepted): record into the loaded copy, anchored under its section heading so concurrent lines survive; on a shared tracker, re-read just before updating.
2. Choose: the user's named ticket, else the first frontier ticket. **Claim it.**
3. Resolve it, zooming into related/closed tickets on demand; use the skills the ticket type and Notes name. Never resolve more than one per session (research dispatches excepted).
4. Record: resolution comment, close the ticket, append its gist to Decisions so far — one line, ≤160 characters, links exempt. Over the ~6k budget → compress back under now, before finishing.
5. Maintain — part of resolving, not optional cleanup: graduate newly-phrasable fog (create-then-wire, delete the entry), rule out-of-scope discoveries out, update or delete invalidated tickets. One-per-session bounds what you *resolve*, never this bookkeeping. Expect concurrent sessions.
6. **Complete the map** when the decision frontier and **Not yet specified** are both empty. Anything still open gets an explicit re-disposition: resolved, out of scope, or a named **standing verification hook** with its reopen condition written down. Then close the map (`kind: none`: `state` → `complete`) with a closing note under **Destination**: what was reached, a link (the spec, or Decisions so far), and the next command — `/to-issues` (multi-slice spec) or `/from-issue` (single-session build). Announce it, run nothing: the handoff is the human's.

## Inflow from the fog gate

`from-issue --auto`'s Phase-0 fog gate emits one decision ticket per unphrasable question. File each under the effort's existing map when one covers the area; otherwise create a minimal map (destination = the aborted issue's intent). The aborted issue gets a comment linking the tickets and is blocked by them natively.
