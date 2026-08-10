# Wayfind skill hardening — gist caps, section reads, reply-by-exception

Design for issue [fagenorn/nix-config#1](https://github.com/fagenorn/nix-config/issues/1). Date 2026-08-10.
Ran `--auto`: every question below was self-answered and logged in `## Auto-resolved decisions`.

Grounding (per `doc-grounded-questions`): this repo has no `docs/`, no `CONTEXT-MAP.md`, and no ADR
directory — `CLAUDE.md` is the project doc and it is the authority on how the skills tree is managed
(`home/common/agent-skills/skills/` is the single source for both Claude and Codex). Sources read in
full: the three target `SKILL.md` files, `wayfind/evals/evals.json`, the eval fixture at
`home/common/agent-skills/evals/fixture-repo/.claude/wayfind/concurrent-shells/`, and the sibling
skills that mention wayfind (`to-issues`, `from-issue/AUTO.md`, `design`).

## Problem

Two real wayfind efforts (argus, 7 sessions / 13 decisions, GitHub tracker; nabeel-debiel, 16
sessions, `kind: none` markdown) were transcript-audited. Protocol adherence was excellent; the waste
is concentrated and measurable:

1. **Ticket fan-in re-reads (~54k tok)** — late tickets re-read 7–12 prior ticket bodies each, because
   tickets carry pasted `Note (from X resolution)` blocks (one ticket had four, 500–1,000 chars each).
   Nothing in the skill forbids this, so it is a store violation the skill permits.
2. **Multi-sitting re-tokenization** — one argus session paid the same ~85k context ~3× across three
   sittings (325k cache-creation against a 111k peak).
3. **Map bloat (~36k tok of re-reads)** — "Decisions so far" gists are 700–1,100-char paragraphs in
   *both* trackers despite the skill's existing "one-line gist" rule; map bodies reached 12.4k chars
   (argus #16) and ~18k (nabeel peak). The long gists did not prevent the fan-in re-reads, so the extra
   length bought nothing.
4. **Whole-file doc reads** — `doc-grounded-questions` step 4 prescribes the architecture doc with no
   size cap; argus charting read a 63k-char file whole.

Also observed: grill rounds of 5–14 recommendation-carrying questions answered ~90% "yes" — a
round-trip of pure assent.

The through-line: **the one-line rule already existed and was violated in both efforts because it
carried no checkable number.** Every edit below therefore lands a number an agent can check itself
against, or names a concrete artifact shape to refuse.

## Solution

Instruction text only, three files, no mechanism changes. Seven edit groups (P1–P5, P7, P8; P6 was the
batching escape hatch, reviewed and rejected — see Out of scope), landing as twelve string
replacements.

| ID | File | Change |
|----|------|--------|
| P1 | `wayfind/SKILL.md` | Gist = one line, ≤160 chars of operative values, links exempt; map body budget ~6k chars, compressed same session; research gists carry the conclusion, not the findings |
| P2 | `wayfind/SKILL.md` | Notes are pointers; an entry past ~2 lines is a ticket or a linked artifact |
| P3 | `wayfind/SKILL.md` | "Low-res" defined tracker-agnostically; `kind: none` skips the pre-update re-read |
| P4 | `doc-grounded-questions/SKILL.md` (+ 1 line in `grill-with-docs`) | Docs past ~400 lines read by governing section, headings grepped first; P4b removes the contradiction this creates in step 1's legacy fallback |
| P5 | `grill-with-docs/SKILL.md` | Reply-by-exception for fully-recommended rounds, with a three-way carve-out |
| P7 | `wayfind/SKILL.md` | Cross-ticket references are link + one line, never a pasted resolution |
| P8 | `wayfind/SKILL.md` | One sitting per ticket; park state in the ticket before pausing |

Cost of the fix, measured by dry-run (below): +4,312 bytes across the three files. A wayfind grilling
session can load all three, so worst case is ~1.1k extra tokens per session, against 90k+ tokens of
measured waste across two efforts. The trade is not close.

## The edits

Anchors are section names plus the exact string to match — line numbers rot. Every BEFORE below is
verbatim from the current file.

---

### P3a — `wayfind/SKILL.md`, section `## The map`: define low-res at first use

Anchor: the line immediately above the map-body code fence.

**BEFORE**

```markdown
Map body, loaded low-res once per session:
```

**AFTER**

```markdown
**Low-res** = title and body only, no ticket bodies (GitHub: `gh issue view <n> --json title,body`; `kind: none`: the `map.md` file itself); ticket bodies open on demand while resolving, one at a time, never as a set.

Map body, loaded low-res once per session:
```

Follows the file's own `The **frontier** = open, unblocked, unclaimed children.` definition shape.

---

### P2 — `wayfind/SKILL.md`, map template: Notes are pointers

Anchor: the `## Notes` placeholder inside the map-body code fence.

**BEFORE**

```markdown
## Notes
<domain; skills every session should consult; standing preferences>
```

**AFTER**

```markdown
## Notes
<domain; skills every session should consult; standing preferences — pointers only: the facts live in the tickets. Any entry running past ~2 lines is a ticket or a linked artifact, not a note.>
```

---

### P1a — `wayfind/SKILL.md`, map template: the gist line

Anchor: the `## Decisions so far` placeholder inside the map-body code fence.

**BEFORE**

```markdown
## Decisions so far
- [<closed ticket title>](link) — <one-line gist of the answer>
```

**AFTER**

```markdown
## Decisions so far
- [<closed ticket title>](link) — <the answer in one line: ≤160 chars of operative values — dates, amounts, the choice made>
```

---

### P1b — `wayfind/SKILL.md`, section `## The map`: gist discipline and body budget

Anchor: insert two paragraphs immediately after the map-body code fence closes, before `## Tickets`.

**BEFORE** — nothing between the closing fence and `## Tickets`.

**AFTER** — new text inserted there:

```markdown
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
Compression rewrites the index; it never deletes from it — every closed ticket keeps its line.
```

The "before you finish, never a follow-up" construction is lifted from `grill-with-docs`' existing
**Net-neutral writes** rule ("both are same-commit obligations, never follow-ups"), so the two skills
enforce budgets with one vocabulary.

---

### P7 — `wayfind/SKILL.md`, section `## Tickets`: cross-ticket references

Anchor: the paragraph beginning `Whatever a session makes while resolving`. Keep it; append a new
paragraph after it.

**BEFORE**

```markdown
Whatever a session makes while resolving — findings file, prototype, checklist — is **linked** from the ticket, never pasted into it.
```

**AFTER**

```markdown
Whatever a session makes while resolving — findings file, prototype, checklist — is **linked** from the ticket, never pasted into it.

The same holds between tickets: cite a sibling by **link plus one line** of what it settled, and open
the ticket itself when you need more. Never paste another ticket's resolution into this one. A
`Note (from <ticket>) …` block is a second copy of a decision that already has a home — it goes stale
silently the moment that ticket is amended, and it teaches the next session that tickets are stores,
so it opens a dozen of them looking for what else was pasted. The ticket is the store; everything
else points at it.
```

This is the edit that targets cost #1, and it is the existing index-not-store invariant extended one
level down — from map→ticket to ticket→ticket.

---

### P3b — `wayfind/SKILL.md`, section `## Work the map`, step 1

**BEFORE**

```markdown
1. Load the map low-res — not every ticket body.
```

**AFTER**

```markdown
1. Load the map low-res. Under `kind: none` that is the session's only read of it: record into the copy you already loaded rather than re-reading before you write, and anchor the edit under its section heading so a concurrent session's line survives yours. On a shared tracker, re-read the body just before updating it — other sessions do land there.
```

The `— not every ticket body` clause is dropped because P3a now defines the term where it is first
used; keeping both would be the duplication this issue is about.

---

### P1c — `wayfind/SKILL.md`, section `## Work the map`, step 4

**BEFORE**

```markdown
4. Record: answer as a resolution comment, close the ticket, append its one-line gist to Decisions so far.
```

**AFTER**

```markdown
4. Record: answer as a resolution comment, close the ticket, append its gist to Decisions so far — one line, ≤160 characters, links exempt. If that push takes the body over its ~6k budget, compress it back under now, before you finish.
```

---

### P8 — `wayfind/SKILL.md`, section `## Work the map`: sitting discipline

Anchor: insert as a new paragraph immediately after step 5 (`5. Maintain — part of resolving…`),
before `## Inflow from the fog gate`.

**BEFORE** — nothing between step 5 and the next heading.

**AFTER** — new text inserted there:

```markdown
**One sitting per ticket.** A ticket is sized to one fresh-context session because a resumed one pays
for the whole context twice, and the second payment buys nothing. Take the ticket you can finish now.
If you have to stop mid-resolution, park state in the ticket before you go — what's settled, what's
still open, what you were about to do next — so the next sitting resumes from the ticket instead of
from a transcript it no longer has.
```

Placed after the step list rather than inside it: it governs the whole of *resolving*, and a session
pauses during step 3, not at a step boundary. It reinforces one-decision-per-session (finish the one
you took) rather than competing with it.

---

### P5 — `grill-with-docs/SKILL.md`, `<what-to-do>`: reply-by-exception

Anchor: insert after the paragraph beginning `Ask the whole frontier as one numbered round`, before
`If a question can be answered by exploring the codebase or docs`.

**BEFORE** — nothing between those two paragraphs.

**AFTER** — new text inserted there:

```markdown
When every question in a round carries a ➡️ recommendation, say so once, at the first round: they may
reply with only the numbers they'd change, and anything they don't name adopts its recommendation and
is recorded as a decision exactly as if they had typed it. A well-defaulted round then costs one short
reply instead of a line of assent per question. The decisions stay theirs — the offer is made in the
open, and any number they name overrides.

Three kinds of question never ride on silence: anything that redraws the destination or the scope,
anything hard to reverse, and anything that spends money or hands out a credential. Mark those in the
round and wait for an answer in words, however many rounds it costs.
```

`redraws the destination` is wayfind's own phrase (`out-of-scope work returns only if the destination
is redrawn`); `hard to reverse` is criterion 1 of this file's own **Offer ADRs sparingly** test. The
carve-out reuses vocabulary the system already defines rather than inventing a third scale.

---

### P4a — `doc-grounded-questions/SKILL.md`, step 4: size discipline

**BEFORE**

```markdown
4. **Find and read the architecture doc** if the question touches more than one component. Use `docPaths.architecture`
   if configured; otherwise look for `ARCHITECTURE.md`, `docs/architecture.md`, or a "Architecture" README section.
   Read it for cross-tier invariants.
```

**AFTER**

```markdown
4. **Find and read the architecture doc** if the question touches more than one component. Use `docPaths.architecture`
   if configured; otherwise look for `ARCHITECTURE.md`, `docs/architecture.md`, or a "Architecture" README section.
   Read it for cross-tier invariants — and past ~400 lines, read it by governing section rather than whole: grep its
   headings first, then open only the sections covering the components in play. The same cap governs any other long
   doc this pass sends you to; the context map is the exception, and only because it is capped at 150 lines by design.
   A large architecture doc read end-to-end can cost more than every other step of this pass combined, and its two or
   three relevant sections answer the question just as well.
```

Deliberately does **not** restate the phase-cache re-read ban further down the file — that rule
already exists and covers a different failure (re-reading), where this covers over-reading once.

---

### P4b — `doc-grounded-questions/SKILL.md`, step 1 legacy fallback: remove the contradiction

Required by P4a: the generalized cap would otherwise contradict the legacy fallback's standing
instruction to read the glossary "in full". The map's own "read in full" instruction is untouched and
explicitly exempted in P4a.

**BEFORE**

```markdown
   **No map?** Fall back to the legacy layout: read whichever of `docPaths.context`, `CONTEXT.md`, `GLOSSARY.md`,
   `DOMAIN.md` or a top-of-`README` domain section exists, in full. Read it once, not per question.
```

**AFTER**

```markdown
   **No map?** Fall back to the legacy layout: read whichever of `docPaths.context`, `CONTEXT.md`, `GLOSSARY.md`,
   `DOMAIN.md` or a top-of-`README` domain section exists — whole when it is short, by governing section when it is
   not (step 4). Read it once, not per question.
```

---

### P4c — `grill-with-docs/SKILL.md`, `## Domain awareness`: one cross-reference line

**BEFORE**

```markdown
During codebase exploration, also look for existing documentation.
```

**AFTER**

```markdown
During codebase exploration, also look for existing documentation. Read a long one by section, not whole: past ~400 lines, grep its headings first and open only the sections that govern what you're grilling — `doc-grounded-questions` step 4 owns this rule.
```

Carries the operative threshold rather than being a bare pointer: an agent reading `grill-with-docs`
has no guarantee it will also load `doc-grounded-questions`, and a cross-reference it must chase to
act on is a cross-reference it will skip.

## Invariants — how each edit stands against them

| Invariant | Standing |
|-----------|----------|
| **index-not-store** | Strengthened. P7 extends it from map→ticket to ticket→ticket; P1b names the gist as an index entry ("never enough to stand in for it"); P2 does the same for Notes. |
| **one-decision-per-session** | Untouched and reinforced. P8 says *finish the one you took*, which is the same rule read from the other end. No edit adds a batching path. |
| **HITL decision ownership** | Preserved. P5 is the only edit near it, and it is a delegation the human is *offered once, in the open*, overridable by naming any number, with an explicit carve-out for the three question classes where silence must not stand. The agent still never answers the human's side — it records an answer the human chose to give by not objecting. |
| **fog discipline** | Untouched. No edit touches `## Fog of war`, the ticket/fog test, or step 5's graduate-and-clear obligation. P1b's compression menu deliberately avoids fog so it can't be read as a licence to delete Not-yet-specified entries. |

## Eval consistency

`wayfind/evals/evals.json` (3 pipeline evals) and its fixture were read in full. **No assert
contradicts any new rule, and none needs changing.**

- Eval 2's gist assert (`its gist landed under Decisions so far`) is an awk check for ≥1 `- ` bullet
  under the heading. A ≤160-char gist satisfies it identically.
- Eval 1's heading assert covers `Destination`, `Not yet specified`, `Out of scope`. P1a and P2 change
  only placeholder text *inside* the fence, never a heading. Notes is not asserted.
- No assert measures map body size, so the ~6k budget can only ever be satisfied.
- Eval 2 runs in `kind: none`, where P3b removes the pre-update re-read. Every assert reads final file
  state, never process, so the removed read is invisible to grading.
- P5, P7, P8 have no assert surface at all.

Fixture check: `concurrent-shells/map.md` has an empty `Decisions so far` (a comment reading `one line
per closed ticket: the gist, then the link for the detail` — already consistent with P1). Its Notes
block runs ~5 lines but is four distinct pointers, each under two lines and each citing a doc, so it
satisfies P2 as written (the cap is per *entry*, not per section). The fixture needs no edit.

## Cross-skill ripple check

Grepped `home/common/agent-skills/skills/` for every passage under edit. **No ripple; no sibling skill
needs a change.**

- `Decisions so far`, `low-res`, `Not yet specified` — zero occurrences outside `wayfind/SKILL.md` and
  its evals. The map's internal vocabulary is not cited anywhere else.
- `to-issues/SKILL.md` `## Decisions` asks for "Links to the decisions this slice depends on — ADRs,
  wayfind decision tickets, spec sections — **one line each with the answer's gist**." P1 makes wayfind
  *match* this downstream contract instead of feeding it paragraphs; it is the strongest evidence the
  cap is right. `to-issues` line 88 (rejected-alternatives log) links wayfind tickets, also unaffected.
- `from-issue/AUTO.md` emits a wayfind decision ticket per foggy question at the Phase-0 fog gate.
  Mechanism untouched; the ticket shape and the fog gate are both unchanged.
- `design/SKILL.md` uses the same `❓/➡️` round format and would benefit from P5, but the issue scopes
  the change to three files. See Out of scope.
- `grill-with-docs` line 89 contains the string "one-line gist" in an unrelated context (the context
  map's Areas table). Not affected.

## Verification

There is no test suite for skills, and none is added — the issue says so explicitly. Verification is by
review.

**Every edit above was dry-run against copies before this spec was committed.** All twelve BEFORE
anchors matched exactly once each in the live files, so the implementer can apply them as literal
string replacements without re-deriving anchors. Two facts came out of that run and are binding on
the plan:

1. **Measured sizes.** `wayfind/SKILL.md` 7,236 → 10,066 bytes (+2,830, +39%);
   `grill-with-docs/SKILL.md` 6,845 → 7,765 (+920, +13%); `doc-grounded-questions/SKILL.md`
   9,631 → 10,193 (+562, +6%). These are the numbers the `wc -c` sanity check should reproduce;
   a file materially past its figure means prose was padded beyond this spec.
2. **`4. Record:` is not bolded** in `wayfind`'s Work-the-map list, unlike step 2's `**Claim it.**`.
   The P1c edit preserves the unbolded form. Do not "fix" it.

The rest of the review checklist:

3. Every acceptance criterion in the issue maps to one named edit above, applied verbatim.
4. `grep -n` the four invariant phrases (`index, not a store`, `more than one ticket per session`,
   `never answers the human's side`, `Fog of war`) and confirm each is present and unweakened. The
   dry-run confirms all four survive the edits.
5. The three files are consumed as symlinks from the Nix store; `just build` must still evaluate. The
   files are copied verbatim by home-manager, so a text-only change cannot break evaluation, but the
   build is the repo's one verification step per `CLAUDE.md` and should run.

**No test seams** in the `design` skill's sense: this change has no public boundary to test. That
section is replaced by the review checklist above, which is what the issue's Verification section
asks for.

## Out of scope

- **P6 / batching escape hatch** — softening one-ticket-per-session was reviewed and rejected upstream.
  Observed context peaks make "still light, take another" rare, and loosening a crisp rule that agents
  demonstrably follow invites compliance decay. Not reintroduced anywhere in this design.
- **Compacting argus #16** — separate-repo housekeeping.
- **Extending P5 to `design/SKILL.md`** — the same rubber-stamp waste applies to its rounds, but the
  issue names three files and `design` already has an autonomous-mode clause covering the `--auto`
  half. Worth a follow-up issue; not this one.
- **New eval asserts** — a 160-char check on Decisions-so-far lines would be cheap, but the issue's
  Verification section rules the test surface out, and expanding it would make an instruction-only
  change a harness change.
- **Any mechanism change** — no new config key, no new file, no change to tracker bindings, ticket
  types, blocking, or the fog gate.

## Auto-resolved decisions

### Eval consistency: change `evals.json` or leave it?
- **Question:** Do the new rules (≤160-char gist, ~6k map budget) contradict anything `wayfind/evals/evals.json` asserts, and should eval coverage grow to cover them?
- **Choice:** Leave `evals.json` and the fixture untouched. Verified assert-by-assert that nothing conflicts; recorded the finding in `## Eval consistency` instead.
- **Grounding:** Eval 2's gist assert is `awk … i && /^[-*] / {n++} END {exit !(n>0)}` — a bullet-count, indifferent to length. No assert reads body size or read-counts. The issue's own Verification section: "No test suite exists for skills. Verify by review."
- **Alternative considered:** Adding a `≤160 chars` assert to eval 2. Rejected: it turns an instruction-text issue into a harness change, and the fixture's `Decisions so far` starts empty, so the assert would only grade the agent's one new line — thin signal for the scope it adds.

### P8 landing spot
- **Question:** Does sitting discipline belong in the `## Work the map` step list or the `## Tickets` section?
- **Choice:** A bolded paragraph after `Work the map`'s step 5, before `## Inflow from the fog gate`.
- **Grounding:** A session pauses mid-*resolution* — inside step 3 — not at a step boundary, so it isn't a step. `Work the map` is what a resuming session reads; `## Tickets` is read when *creating* one. The file already uses trailing bolded paragraphs for cross-cutting discipline (`**Claim before work**` in `## Tickets`).
- **Alternative considered:** A sixth numbered step. Rejected: it would read as "do this after maintaining", when it actually governs when you start.

### P1 placement — template comment, step 4, or both
- **Question:** Does the gist cap go in the map template's placeholder, in `Work the map` step 4, or both?
- **Choice:** Both, plus a rationale paragraph after the template. The template placeholder and step 4 carry the number; the paragraph carries the *why* and the budget rule once.
- **Grounding:** The two audiences are disjoint — a charting session copies the template and never reaches step 4; a work session executes step 4 and may never re-read the template. The rule was already violated in both efforts when it lived in one place with no number.
- **Alternative considered:** Template only (smaller). Rejected: the observed violations happened at *record* time, in step 4's slot, which is precisely where a template comment is out of sight.

### P4 threshold phrasing
- **Question:** Hard cap ("never read a doc over 400 lines whole") or advisory ("past ~400 lines")?
- **Choice:** Advisory `past ~400 lines`, paired with a concrete procedure (grep headings, then read the governing sections).
- **Grounding:** The file's own register is advisory-with-numbers — "capped at 150 lines", "the one or two area files that actually apply". A hard cap would also make a 401-line doc unreadable in full, which no evidence supports.
- **Alternative considered:** A hard prohibition. Rejected: over-constrains, and the file has no other absolute size prohibition to match.

### Where "low-res" gets defined
- **Question:** Define low-res at its first use in `## The map`, or at `Work the map` step 1 where the load happens?
- **Choice:** Define at first use in `## The map`; step 1 keeps only the operative re-read rule and drops its now-redundant `— not every ticket body` clause.
- **Grounding:** The term appears in `## The map` first and would otherwise be undefined on first read. The file's `The **frontier** = …` line is exact precedent for defining a term inline where it first appears.
- **Alternative considered:** Full definition in both places. Rejected — duplication is the failure mode this issue exists to fix.

### Safety of skipping the `kind: none` pre-update re-read
- **Question:** Does skipping the pre-update re-read risk clobbering a concurrent session, given the skill says "Expect concurrent sessions on other tickets"?
- **Choice:** Skip it, and add "anchor the edit under its section heading" so a targeted append coexists with another session's append. Keep the re-read on shared trackers.
- **Grounding:** `Work the map` step 5 already tells sessions to expect concurrency. A section-anchored append either applies cleanly alongside another session's line or fails loudly when its anchor is gone — it cannot silently overwrite, which a whole-body rewrite could.
- **Alternative considered:** A hedge ("skip unless a concurrent session is possible"). Rejected: a condition an agent cannot evaluate produces a rule it will not follow, which is exactly how the one-line gist rule failed.

### Where the research-gist rule lives
- **Question:** Put "research gists carry the conclusion, not the findings" in the `research` ticket-type bullet or in the gist paragraph?
- **Choice:** In the gist paragraph, beside the cap.
- **Grounding:** The rule is about what goes on the *map*, and the ticket-type bullet already carries the matching ticket-level rule ("findings file linked from the ticket"). Both statements in one paragraph keep gist policy in one place.
- **Alternative considered:** The `research` bullet. Rejected: it would split gist policy across two sections, and the bullet is read when *dispatching*, not when recording.

### P7 anchor
- **Question:** Where does the cross-ticket reference rule go?
- **Choice:** Immediately after `## Tickets`' existing "linked from the ticket, never pasted into it" paragraph.
- **Grounding:** It is the same rule at the next level down, and putting it beside its parent makes the generalization self-evident rather than asserted.
- **Alternative considered:** `## The map`, next to index-not-store. Rejected: this is ticket-to-ticket behavior; a reader looking for it is in `## Tickets`.

### P5 anchor and whether it weakens HITL ownership
- **Question:** Where does reply-by-exception go, and does letting silence stand as an answer violate "the agent never answers the human's side"?
- **Choice:** In `<what-to-do>`, right after the round-shape paragraph. It does not violate the invariant: the offer is explicit, made once, and any number the human names overrides.
- **Grounding:** The invariant lives in `wayfind` ("worked with a human who speaks for themselves — the agent never answers the human's side"). Under reply-by-exception the human *does* speak: they accept a batch of stated recommendations by declining to change them, having been told in advance that is what silence means. The carve-out removes the cases where that inference is unsafe.
- **Alternative considered:** Requiring an explicit "all yes". Rejected: that is the round-trip of pure assent the audit measured, and it buys no additional consent that the stated-in-advance offer doesn't already carry.

### Carve-out vocabulary
- **Question:** How to name the three question classes that always need a typed answer?
- **Choice:** "redraws the destination or the scope", "hard to reverse", "spends money or hands out a credential".
- **Grounding:** `redrawn` destination is wayfind's own term (`## Fog of war`); `hard to reverse` is criterion 1 of `grill-with-docs`' own ADR test. Reusing established terms means an agent already knows how to apply them.
- **Alternative considered:** A new severity scale. Rejected as a third vocabulary for a distinction two existing ones already draw.

### P4 cross-reference: pointer or pointer-with-threshold
- **Question:** Should `grill-with-docs`' cross-reference line name the ~400-line threshold or just point at `doc-grounded-questions`?
- **Choice:** Name the threshold and the procedure, then attribute the rule.
- **Grounding:** `grill-with-docs` may be invoked without `doc-grounded-questions` loading (its `<supporting-info>` never requires it), so a bare pointer is unactionable in exactly the session that needs it. The issue's AC asks for "one cross-reference line" — this is one line.
- **Alternative considered:** Bare pointer. Rejected: unactionable, and the phase-cache ban — the thing the AC forbids duplicating — is untouched either way.

### Amending step 1's legacy fallback (P4b)
- **Question:** Generalizing the size cap to "any other long doc" contradicts step 1's standing instruction to read the legacy glossary "in full". Restrict the cap to the architecture doc, or amend step 1?
- **Choice:** Amend step 1's legacy fallback to "whole when it is short, by governing section when it is not (step 4)". The map's separate "read in full" instruction is untouched and explicitly exempted in P4a.
- **Grounding:** A 63k-char legacy `CONTEXT.md` wastes exactly what a 63k-char `ARCHITECTURE.md` wastes; the issue's AC says "docs past ~400 lines", not "the architecture doc". Leaving a self-contradiction in a file whose job is to be followed literally is worse than a nine-word amendment.
- **Alternative considered:** Scoping the cap to step 4's doc only. Rejected: leaves the identical waste reachable one step earlier.

### Whether compression may delete
- **Question:** "Compress the map body" could be read as licence to drop old decisions. Constrain it?
- **Choice:** Yes — "Compression rewrites the index; it never deletes from it — every closed ticket keeps its line." Compression means folding subsumed gists and cutting grown explanations back to their links.
- **Grounding:** index-not-store: the map is the only place a closed ticket is discoverable from. A compression pass that dropped lines would convert a token problem into a correctness problem, and `to-issues` reads `Decisions so far` downstream to populate slice `## Decisions`.
- **Alternative considered:** Leaving "compress" undefined. Rejected: an unbounded instruction to shrink a file, given to an agent under budget pressure, is how indexes lose entries.

### Deliberately excluding fog from the compression menu
- **Question:** Should "drop fog that has graduated" be one of the compression moves?
- **Choice:** No. The compression menu names only gist-folding and explanation-cutting.
- **Grounding:** Graduating fog is already step 5's non-optional maintenance obligation. Listing it as a compression move would both duplicate it and reframe a correctness rule as a size optimization — a session under budget pressure might then "compress" fog it never graduated.
- **Alternative considered:** Including it for completeness. Rejected on both counts above.

### Extending P5 to `design/SKILL.md`
- **Question:** `design` uses the identical `❓/➡️` round format and suffers the same rubber-stamp waste. Include it?
- **Choice:** No. Recorded in Out of scope as a follow-up candidate.
- **Grounding:** The issue's Scope section names three files and says "Instruction-text only". `design` already carries an autonomous-mode clause, so the `--auto` half of the waste is covered there; only its interactive rounds are exposed.
- **Alternative considered:** A fourth file in this change. Rejected: scope creep on an issue that already survived a reviewer pass at three files.

### Accepting +39% on `wayfind/SKILL.md`
- **Question:** The dry-run puts `wayfind/SKILL.md` at 10,066 bytes, +39%. An issue about token waste that grows the file every session loads deserves an answer. Trim the prose to hit a smaller number?
- **Choice:** No. Ship the measured +2,830 bytes and publish the real figures rather than shaving rationale to reach a prettier percentage.
- **Grounding:** The rationale clauses are the mechanism: "the one-line rule already existed and was violated in BOTH field efforts because it lacked a checkable cap." An imperative with no reason attached is what already failed here twice. +2,830 bytes is ~710 tokens per session against ~36k (map bloat) plus ~54k (fan-in) measured in one effort. The file also lands at 10,066 bytes — within a byte of `doc-grounded-questions`' pre-existing 9,631, so it is not an outlier among these skills.
- **Alternative considered:** Cutting the four rationale sentences (~600 bytes, ~8 points of growth). Rejected: it saves a rounding error and removes the exact property that distinguishes these edits from the rule that already failed.

### No ADR
- **Question:** Do these decisions warrant an ADR?
- **Choice:** No. `adr_paths: []`.
- **Grounding:** The repo has no `docs/`, no ADR directory and no ADR convention. `grill-with-docs`' own three-part test fails at "hard to reverse" — every edit here is a text revert. The committed spec is the record.
- **Alternative considered:** Establishing an ADR convention here. Rejected: inventing a docs tree to record a prose edit inverts the cost.
