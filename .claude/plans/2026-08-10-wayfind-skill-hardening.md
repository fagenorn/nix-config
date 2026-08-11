# Wayfind Skill Hardening Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Land the fourteen instruction-text edits approved in the design spec across three
`SKILL.md` files, closing issue [#1](https://github.com/fagenorn/nix-config/issues/1)'s acceptance
criteria P1–P5, P7, P8 and P9.

**Architecture:** Three Markdown skill files under `home/common/agent-skills/skills/` are edited as
literal string replacements. No mechanism changes, no new files, no code. The replacement prose lives
in exactly one place — `.claude/specs/2026-08-10-wayfind-skill-hardening-design.md`, section
`## The edits` — and every task below points at the spec section that carries its strings rather than
restating them. Tasks are split one per target file because the three files share no anchor and can be
reviewed independently; a fourth task verifies the change as a whole.

**Tech stack:** Markdown (skill instruction text); Nix flake — nix-darwin + home-manager, exercised via
`just build`; Python 3 stdlib for the verification script; `git`, `grep`, `wc`.

## Global Constraints

Copied from the spec and the issue; every task's requirements implicitly include this section.

- **Instruction text only.** No mechanism change: no new config key, no new file, no change to tracker
  bindings, ticket types, blocking, or the fog gate.
- **Three files only:** `home/common/agent-skills/skills/{wayfind,grill-with-docs,doc-grounded-questions}/SKILL.md`.
  `wayfind/evals/evals.json` and the eval fixture under `home/common/agent-skills/evals/fixture-repo/`
  are deliberately **not** touched — the spec's `## Eval consistency` verified assert-by-assert that
  nothing conflicts.
- **Apply the spec's AFTER blocks byte-for-byte**, including their line breaks. Do not re-flow, re-wrap,
  re-punctuate or "tidy" them; do not retype them from memory. Copy the fenced block out of the spec.
- **Measured byte sizes are the acceptance figure**, reproduced by dry-run while writing this plan:

  | File | Before | After | Delta |
  |------|-------:|------:|------:|
  | `wayfind/SKILL.md` | 7,236 | **10,852** | +3,616 |
  | `grill-with-docs/SKILL.md` | 6,845 | **7,765** | +920 |
  | `doc-grounded-questions/SKILL.md` | 9,631 | **10,193** | +562 |

  A file landing off its figure means text was padded, dropped or re-flowed beyond the spec. The spec's
  wording: "a file materially past its figure means prose was padded beyond this spec."
- **Four invariants must survive unweakened**, per the issue: index-not-store, one-decision-per-session,
  HITL decision ownership, fog discipline. Grep probes: `index, not a store`,
  `more than one ticket per session`, `never answers the human's side`, `## Fog of war`. Each occurs
  exactly once before the change and must occur exactly once after.
- **Register:** "Each edit must read like the surrounding skill prose (dense, imperative,
  rationale-bearing)." This is already true of the spec's AFTER text — it is a reason to copy verbatim,
  not a licence to rewrite.
- **Commits:** one per task, conventional-commits style, `fix(agents): …`, ending with the trailer
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` (matching this flow's prior
  commits; repo history before this issue used a different model trailer — see D1 in Auto-resolved
  decisions).

## Test seams

**None, by design.** The spec states it outright: "**No test seams** in the `design` skill's sense:
this change has no public boundary to test." There is no test suite for skills and the issue's own
Verification section rules the test surface out ("No test suite exists for skills. Verify by review").

Implementers therefore verify at these four gates and nowhere else — a task wanting a fifth is a plan
bug, not an implementer's call:

1. **Verbatim presence** — `verify-edits.py` (Task 1, Step 1) parses the spec and asserts each AFTER
   block appears exactly once in its target file, and each superseded BEFORE block zero times. Nothing
   is transcribed, so the check cannot drift from the spec.
2. **Byte size** — `wc -c` against the table above.
3. **Position** — `grep`/`awk` ordering checks, because presence and size alone cannot catch a block
   inserted in the wrong place.
4. **Build** — `just build`, once, in Task 4.

## Standards review provenance

- **Reviewer:** Codex (`codex:codex-reviewer` bridge), fresh isolated `CODEX_HOME`, read-only sandbox.
- **Base SHA:** 8cee250; plan reviewed at commit 6cf672d.
- **Focus:** none configured.
- **Findings:** 0 blocking, 0 should-fix, 3 discussion — D1 applied (parenthetical reworded, trailer kept, logged), D2 reviewer-confirmation of an existing spec decision (no change), D3 no change (reviewer's own low-confidence assessment). 0 rejected, 0 deferred.
- **Independent reproduction by reviewer:** re-applied all 14 BEFORE→AFTER edits to fresh copies (byte counts land at exactly 10,852 / 7,765 / 10,193), ran the plan's verification script red at base (0/14) and green on edited copies (14/14), and reproduced the auxiliary grep/awk gates.
- **Fallback:** not used.

## Auto-resolved decisions

### Task granularity: one task per file
- **Question:** Should the fourteen replacements be one task, one task per acceptance criterion (P1…P9), or one task per file?
- **Choice:** One task per target file (three), plus a fourth whole-change verification task. Four tasks, three commits.
- **Grounding:** The spec's `## The edits` says "The fourteen anchors are mutually independent: none appears inside another edit's replacement text, so they can be applied in any order" — so no ordering constraint forces a finer split. Per-file is the split a reviewer can act on: `wc -c` and the invariant greps are both per-file, so a reviewer can reject `wayfind` while approving `doc-grounded-questions`. Ten of the fourteen edits land in `wayfind/SKILL.md` alone.
- **Alternative considered:** One task per acceptance criterion. Rejected: P4 spans two files and P1 spans three separate anchors in one file, so criterion-shaped tasks would produce commits that touch a file twice and a `wc -c` gate no single task could satisfy. Also rejected: a single fourteen-edit task — it collapses three independent review surfaces into one all-or-nothing gate.

### Task order: `doc-grounded-questions` before `grill-with-docs`
- **Question:** The tasks are independent — does order matter?
- **Choice:** Task 1 `wayfind`, Task 2 `doc-grounded-questions`, Task 3 `grill-with-docs`, Task 4 verification.
- **Grounding:** P4c adds a line to `grill-with-docs` that attributes the rule to "`doc-grounded-questions` step 4" (spec `### P4c`), and P4a is what puts that rule in step 4. Landing P4a first means no intermediate commit contains a cross-reference to a rule that does not exist yet. `wayfind` goes first because it is the largest surface and carries no cross-file dependency in either direction.
- **Alternative considered:** Any order, since all fourteen anchors are independent. Rejected as needlessly leaving a dangling reference in the branch history for a reader bisecting it; the constraint costs nothing.

### Verbatim application, including the spec's line wrapping
- **Question:** The spec hard-wraps the AFTER text for P1b, P7, P8 and P5 at ~95 characters, but `wayfind/SKILL.md` and `grill-with-docs/SKILL.md` write every paragraph as one long unwrapped line. Copy the spec's wrapping, or re-flow to each file's house style?
- **Choice:** Copy verbatim, wrapping included. Stated as a Global Constraint.
- **Grounding:** The spec's Verification section makes verbatim application the contract: "the implementer can apply them as literal string replacements without re-deriving anchors." The difference is invisible — a single newline inside a Markdown paragraph renders identically to a space, and it is byte-neutral (one newline replaces one space), so the measured byte figures hold either way; I confirmed this by re-running the dry-run and reproducing 10,852 / 7,765 / 10,193 exactly. The issue's "read like the surrounding skill prose" constraint is about register (dense, imperative, rationale-bearing), not line width.
- **Alternative considered:** Re-flowing the four inserted blocks to unwrapped single lines for house-style consistency. Rejected: it asks an implementer to transform text mid-copy, which is precisely where transcription drift enters, and it would break the `verify-edits.py` gate that makes this change checkable at all. If the mixed wrapping ever grates, it is a cosmetic follow-up on a file already committed.

### Gate design: derive checks from the spec, don't transcribe probes into the plan
- **Question:** How does a task prove its edits landed — hand-written `grep` probe strings in the plan, or a check derived from the spec?
- **Choice:** A ~30-line Python script that parses the spec's `## The edits` sections and asserts each AFTER block is present exactly once (and each superseded BEFORE block absent). Short hand-written probes are used only for the gotcha and invariant checks, where the target text is *pre-existing* and cannot drift.
- **Grounding:** This plan must not restate replacement prose — the spec is the single source. A transcribed probe is a second copy of that prose in a second file, which is the same store-not-index failure the issue is about. I tested the script both ways before committing this plan: it reports `0/14` against the current files and `14/14` against correctly-edited copies, so it is genuinely falsifiable. Multi-line probes also caught a real trap — P4b's AFTER text wraps mid-sentence, so a naive one-line `grep` for it returns 0 even when the edit is correct.
- **Alternative considered:** Fourteen hand-written `grep -F` probes. Rejected on drift risk and on the P4b wrapping trap above.

### The verification script is never committed
- **Question:** Where does `verify-edits.py` live — a committed `scripts/` entry, or outside the tree?
- **Choice:** Written to `"$(git rev-parse --git-dir)/verify-edits.py"`, outside the working tree, by the first task that needs it.
- **Grounding:** The spec's Out of scope forbids new files and any harness change ("no new config key, no new file"). The git-dir location is this repo's established pattern for exactly this: `doc-grounded-questions` writes its grounding cache to `"$(git rev-parse --git-dir)/GROUNDING.md"` — "per-worktree and outside the working tree, so it can never be committed." It also survives across all four tasks in one worktree.
- **Alternative considered:** An inline heredoc re-pasted in every task. Rejected: four copies of the same script is worse duplication than one uncommitted file, and it makes Task 4's re-run depend on a correct re-paste.

### Falsifiability: run each gate red before editing
- **Question:** With no test suite, how does a task avoid the no-op failure mode where its acceptance criteria were already true at the base commit?
- **Choice:** Every edit task runs its own gate *before* touching the file and records the failing output, then again after.
- **Grounding:** The `writing-plans` skill requires it: "confirm that observation holds at the commit the implementer starts from. A criterion already true at the base commit is how an implementer 'completes' a no-op." I verified the red state: `verify-edits.py` reports `0/10`, `0/2`, `0/2` per file at the base commit, and every AFTER block greps to zero occurrences there.
- **Alternative considered:** Post-edit verification only. Rejected: a gate that has never been observed failing is not evidence.

### `just build` runs once, in Task 4
- **Question:** Should every task run `just build`, or only the final one?
- **Choice:** Only Task 4.
- **Grounding:** `home/common/claude-code/default.nix:88` sets `skillsDir = ../agent-skills/skills`, so the whole tree is copied into the store and any of the three files reaching it is enough to exercise the path — three runs would exercise the same path three times. `CLAUDE.md` names `just build` "the verification step", not a per-edit check, and the spec agrees a text-only change "cannot break evaluation" while still asking that the build run. I confirmed it passes at the base commit (exit 0), so a Task 4 failure is attributable to this change.
- **Alternative considered:** A build gate per task. Rejected as several minutes of Nix evaluation each, buying no signal a single final run does not.

### Task 4 produces no commit
- **Question:** The commit-boundary rule is one commit per task, but Task 4 changes no file. Should it commit anything — a verification note, a plan checkbox update?
- **Choice:** No commit. Task 4 is a gate; its output is the evidence it reports back, which belongs in the task report and the PR body.
- **Grounding:** The change is scoped to three skill files (issue `## Scope`), and the spec's Out of scope forbids new files — a committed verification log would be both. Three commits for three files also keeps the branch bisectable per file.
- **Alternative considered:** An empty `--allow-empty` marker commit. Rejected as noise in the history of a five-thousand-byte prose change.

### Byte counts asserted as exact equality
- **Question:** Should the `wc -c` gate be exact (`= 10,852`) or a tolerance band?
- **Choice:** Exact equality, for all three files.
- **Grounding:** I reproduced all three figures to the byte by re-running the spec's dry-run from the spec's own fenced blocks (7,236→10,852, 6,845→7,765, 9,631→10,193, +5,098 total), so the exact number is known-reachable rather than an estimate. Under verbatim application there is no legitimate source of variance, and exactness makes the gate catch a dropped blank line — which the presence check alone would miss.
- **Alternative considered:** A ±2% band, per the spec's softer "materially past its figure" phrasing. Rejected: a band tolerates exactly the whitespace slippage this gate exists to catch, and the spec's phrasing is guidance to a human reviewer, not a looser contract for a machine check.

### Task-4 gate staleness: the Phase-5 provenance commit sits inside the verification range
- **Question:** (Task 4 implementer, BLOCKED) Step 2's diffstat found four files (the fourth being this plan) and Step 5 found one non-`fix(agents):` commit (`73e955b`, the Phase-5 review-provenance amendment) — both literal expectations written before Phase 5 ran. Exempt the flow's own process commit, or rewrite history?
- **Choice:** Amend both expectations to exempt flow-artifact commits (`docs(plans):`/`docs(specs):` touching only `.claude/plans/`/`.claude/specs/`, trailer still required); adjudicate Task 4 as passing on its already-recorded outputs, which satisfy the amended expectation (fourth file = this plan only; `73e955b` carries the trailer; the three task commits are well-formed).
- **Grounding:** from-issue Phase 5 mandates recording provenance in the plan as a commit ("standing local-commit authorization"), and spec/plan commits ship with the branch by design (Phase 1). The gate's intent — no scope creep into non-skill files, no malformed task commits — is fully satisfied; the evals files the check exists to protect are untouched.
- **Alternative considered:** Rewording/relocating `73e955b` via history rewrite — rejected: rewriting a legitimate process record to satisfy a stale literal expectation inverts the relationship between the gate and its intent.

### D1: commit-trailer precedent overstated
- **Question:** (Phase-5 reviewer) "(matching `git log`)" is true only of this issue's own three prior commits; repository history before this issue uses `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **Choice:** Keep the `Claude Opus 5 (1M context)` trailer; reword the parenthetical to say it matches this flow's prior commits rather than implying a repo-wide convention.
- **Grounding:** The executing session's harness mandates this exact trailer for commits it produces, and the issue's own commit chain (9f72280, f8f1789, 6cf672d) already carries it; consistency within one PR chain outweighs continuity with pre-issue history.
- **Alternative considered:** Reverting to the repo-wide `Claude Fable 5` trailer — rejected: it would misattribute the commits this flow actually produces and mix two trailers inside the same PR.

### D2: P4b scope addition — reviewer confirmation
- **Question:** (Phase-5 reviewer) Is P4b justified coherence work or scope creep beyond the issue's edit list?
- **Choice:** Accepted as part of P4, unchanged. This entry records the reviewer's independent confirmation of the spec's own "Amending step 1's legacy fallback (P4b)" decision.
- **Grounding:** Reviewer verified live `doc-grounded-questions/SKILL.md:51-52` says to read the legacy glossary fallback "in full", contradicting P4a's cap for the same document class; the amendment is nine words and preserves the map's exempted "read in full" instruction.
- **Alternative considered:** Treating P4b as out-of-band and deferring it — rejected by reviewer and author alike: landing P4a alone ships a self-contradicting file.

### D3: P9b step 6 leaves the GitHub close mechanism implicit
- **Question:** (Phase-5 reviewer, low confidence) Should step 6 spell out the GitHub-tracker close action rather than only disambiguating the `kind: none` case?
- **Choice:** No change.
- **Grounding:** The reviewer's own assessment: the file's existing register says "close the ticket" without spelling out `gh` invocations, and the tracker-bindings paragraph already establishes how generic actions map onto both tracker kinds.
- **Alternative considered:** Adding tracker-explicit close text — rejected: it would break the file's abstraction level to service a low-confidence nit, and the spec records the rationale for readers who need it.

---

### Task 1: `wayfind/SKILL.md` — ten edits (P1, P2, P3, P7, P8, P9)

**Files:**
- Modify: `home/common/agent-skills/skills/wayfind/SKILL.md`
- Create (outside the working tree, never committed): `$(git rev-parse --git-dir)/verify-edits.py`
- Test: none — see **Test seams**.

**Interfaces:**
- Consumes: nothing from another task. All replacement strings come from
  `.claude/specs/2026-08-10-wayfind-skill-hardening-design.md`, section `## The edits`.
- Produces: `verify-edits.py` at `$(git rev-parse --git-dir)/verify-edits.py`, used unchanged by Tasks
  2, 3 and 4 — invoked as `python3 "$(git rev-parse --git-dir)/verify-edits.py" [skill-name …]`, where
  each argument is a skill directory name (`wayfind`, `grill-with-docs`, `doc-grounded-questions`) and
  no argument means all three. Exit 0 = every checked edit present verbatim. Also produces
  `wayfind/SKILL.md` at exactly 10,852 bytes.

**The ten edits, and the spec section carrying each one.** Apply the BEFORE→AFTER blocks from these
sections verbatim; this plan does not reproduce them.

| Spec section | What it does | How to apply |
|---|---|---|
| `### P9a — wayfind/SKILL.md, tracker-bindings paragraph: map front-matter for kind: none` | map `state:` field | replace |
| `### P3a — wayfind/SKILL.md, section ## The map: define low-res at first use` | defines low-res | replace |
| `### P2 — wayfind/SKILL.md, map template: Notes are pointers` | Notes placeholder | replace |
| `### P1a — wayfind/SKILL.md, map template: the gist line` | gist placeholder | replace |
| `### P1b — wayfind/SKILL.md, section ## The map: gist discipline and body budget` | two new paragraphs | **insert** |
| `### P7 — wayfind/SKILL.md, section ## Tickets: cross-ticket references` | cross-ticket rule | replace (AFTER re-states the BEFORE sentence, then adds a paragraph) |
| `### P8 — wayfind/SKILL.md, section ## Work the map: sitting discipline` | lead-in paragraph | **insert** |
| `### P3b — wayfind/SKILL.md, section ## Work the map, step 1` | step 1 | replace |
| `### P1c — wayfind/SKILL.md, section ## Work the map, step 4` | step 4 | replace |
| `### P9b — wayfind/SKILL.md, section ## Work the map: step 6, complete the map` | new step 6 | **insert** |

The four **insert** edits give no BEFORE block, so their placement is stated here (placement only — the
text itself is in the spec):

- **P1b** — between the map-body code fence's closing ` ``` ` and the `## Tickets` heading, with one
  blank line on each side.
- **P8** — between the `## Work the map (later invocations, with the map's URL or number)` heading and
  step 1, with one blank line on each side.
- **P9b** — as the next list item immediately after step 5's line, with **no** blank line between them
  (the existing list has none), leaving `## Inflow from the fog gate` as the next heading.

**Gotchas — carried verbatim from the design handoff:**

> wayfind's "4. Record:" is unbolded — don't normalize.

> map state is open|complete, tickets open|closed — intentional.

Both are also in the spec's Verification section as points 2 and 3: the P1c edit preserves the unbolded
`4. Record:` form while step 2 above it is `**Claim it.**`, and after P9a the strings `state: open|complete`
(the map) and `state: open|closed` (tickets) sit one clause apart on purpose. **Do not "fix" either.**

- [ ] **Step 1: Install the verification script**

(Fenced with four backticks — the script's own regex contains a three-backtick literal.)

````bash
cat > "$(git rev-parse --git-dir)/verify-edits.py" <<'PY'
"""Assert every spec edit is present verbatim in its SKILL.md. Usage: verify-edits.py [skill ...]"""
import re, sys, pathlib
root = pathlib.Path.cwd()
spec = (root / ".claude/specs/2026-08-10-wayfind-skill-hardening-design.md").read_text()
skills = root / "home/common/agent-skills/skills"
target = {"P3a": "wayfind", "P2": "wayfind", "P1a": "wayfind", "P1b": "wayfind",
          "P7": "wayfind", "P3b": "wayfind", "P1c": "wayfind", "P8": "wayfind",
          "P9a": "wayfind", "P9b": "wayfind", "P5": "grill-with-docs",
          "P4c": "grill-with-docs", "P4a": "doc-grounded-questions",
          "P4b": "doc-grounded-questions"}
only = set(sys.argv[1:]) or set(target.values())
body = spec.split("## The edits", 1)[1].split("## Invariants", 1)[0]
cache, checked, bad = {}, 0, 0
for sec in re.split(r"^### ", body, flags=re.M)[1:]:
    sid = sec.split("\n", 1)[0].split(" ")[0].strip()
    if target.get(sid) not in only:
        continue
    fences = [f.rstrip("\n") for f in
              re.findall(r"^```markdown\n(.*?)^```$", sec, flags=re.M | re.S)]
    after, name = fences[-1], target[sid]
    txt = cache.setdefault(name, (skills / name / "SKILL.md").read_text())
    n = txt.count(after)
    ok, msg = n == 1, f"AFTER x{n}"
    if len(fences) == 2 and fences[0] not in after:
        m = txt.count(fences[0])
        ok, msg = ok and m == 0, msg + f", BEFORE x{m} (want 0)"
    checked += 1
    bad += not ok
    print(f"  {'PASS' if ok else 'FAIL'} {sid:4s} {name:24s} {msg}")
print(f"\n{checked - bad}/{checked} edits present verbatim."
      + ("" if not bad else f"  {bad} FAILED."))
sys.exit(1 if bad or not checked else 0)
PY
````

Run from the worktree root. The script resolves paths from `cwd`, so every invocation below must also
run from the worktree root.

- [ ] **Step 2: Run the gate and watch it fail**

Run: `python3 "$(git rev-parse --git-dir)/verify-edits.py" wayfind; echo "exit=$?"`

Expected: ten `FAIL` lines, `0/10 edits present verbatim.  10 FAILED.`, `exit=1`. If this reports
anything above `0/10`, stop — the file is not at the base commit this task assumes.

- [ ] **Step 3: Apply the ten replacements**

Open `.claude/specs/2026-08-10-wayfind-skill-hardening-design.md` and work the ten sections named in
the table above. For each, copy the fenced BEFORE block and the fenced AFTER block out of the spec and
apply the substitution literally — matching on the whole block, not a line of it. For the four insert
edits there is no BEFORE block; place the AFTER block as described above. Change nothing else in the
file: no reflowing, no typo fixes, no heading edits.

- [ ] **Step 4: Verify**

Run:

```bash
python3 "$(git rev-parse --git-dir)/verify-edits.py" wayfind
wc -c home/common/agent-skills/skills/wayfind/SKILL.md
W=home/common/agent-skills/skills/wayfind/SKILL.md
echo "-- invariants (each must print 1) --"
grep -cF 'index, not a store' $W
grep -cF 'more than one ticket per session' $W
grep -cF "never answers the human's side" $W
grep -cF '## Fog of war' $W
echo "-- gotchas --"
grep -c '^4\. Record:' $W          # want 1  (unbolded, preserved)
grep -cF '**4. Record' $W          # want 0  (never bolded)
grep -cF 'state: open|complete' $W # want 1  (map)
grep -cF 'state: open|closed' $W   # want 1  (tickets)
echo "-- Work-the-map order: lead-in, then steps 1..6 --"
awk '/^## Work the map/,/^## Inflow/' $W | grep -oE '^(\*\*One sitting per ticket\.\*\*|[0-9]\. )'
echo "-- P1b sits between the map fence and ## Tickets (want 2) --"
awk '/^## The map/,/^## Tickets/' $W | grep -cE '^(Every line of this body|The body.s budget)'
```

Expected, in order: `10/10 edits present verbatim.`; `10852` bytes; four `1`s for the invariants; then
`1`, `0`, `1`, `1` for the gotchas; then `**One sitting per ticket.**` followed by `1. ` through `6. `
in ascending order; then `2`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/wayfind/SKILL.md
git commit -m "$(cat <<'EOF'
fix(agents): wayfind gist caps, pointer notes, sitting and completion discipline (#1)

Lands the ten wayfind edits from the approved design: a checkable ≤160-char
cap on Decisions-so-far gists plus a ~6k map-body budget (P1), Notes and
cross-ticket references as pointers rather than pasted copies (P2, P7),
low-res defined tracker-agnostically with the kind:none pre-update re-read
dropped (P3), one-sitting-per-ticket discipline (P8), and an explicit map
completion state and step 6 (P9).

Applied verbatim from .claude/specs/2026-08-10-wayfind-skill-hardening-design.md;
7,236 -> 10,852 bytes as measured there. All four invariants unchanged.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `doc-grounded-questions/SKILL.md` — P4a and P4b

**Files:**
- Modify: `home/common/agent-skills/skills/doc-grounded-questions/SKILL.md`
- Test: none — see **Test seams**.

**Interfaces:**
- Consumes: `verify-edits.py` at `$(git rev-parse --git-dir)/verify-edits.py`, installed by Task 1
  Step 1. If it is absent, re-create it from that step verbatim.
- Produces: the ~400-line read-by-section rule in step 4 of this file, which Task 3's P4c edit
  attributes by name ("`doc-grounded-questions` step 4 owns this rule"). Also produces
  `doc-grounded-questions/SKILL.md` at exactly 10,193 bytes.

**The two edits, and the spec section carrying each one.** Both are straight BEFORE→AFTER replacements;
apply them verbatim from the spec, which this plan does not reproduce.

| Spec section | What it does |
|---|---|
| `### P4a — doc-grounded-questions/SKILL.md, step 4: size discipline` | adds the ~400-line read-by-governing-section rule to step 4 |
| `### P4b — doc-grounded-questions/SKILL.md, step 1 legacy fallback: remove the contradiction` | replaces step 1's "in full" legacy-glossary instruction |

**Gotcha — carried verbatim from the design handoff:**

> P4b is an edit the issue never listed — dgq step 1's legacy fallback says read the glossary "in full",
> contradicting P4a's cap; skipping it ships a self-contradicting file.

P4b is not optional and is not scope creep: the spec's `### P4b` opens "Required by P4a". Two further
consequences to respect: the **map's** separate "Always read the map in full" instruction in step 1 is
untouched and explicitly exempted inside P4a's own text, and P4a deliberately does **not** restate the
phase-cache re-read ban further down the file — that rule already exists and covers re-reading, where
this covers over-reading once. Do not add a cross-reference to it.

Note also that this file hard-wraps its paragraphs, and both AFTER blocks are wrapped and indented to
match. Preserve the leading indentation exactly — P4b's block is indented three spaces because it sits
inside a numbered list item.

- [ ] **Step 1: Run the gate and watch it fail**

Run: `python3 "$(git rev-parse --git-dir)/verify-edits.py" doc-grounded-questions; echo "exit=$?"`

Expected: two `FAIL` lines (`P4a`, `P4b`), `0/2 edits present verbatim.  2 FAILED.`, `exit=1`.

- [ ] **Step 2: Apply the two replacements**

Open `.claude/specs/2026-08-10-wayfind-skill-hardening-design.md`, and for each of the two sections
named above copy its fenced BEFORE and AFTER blocks and apply the substitution literally, matching on
the whole block. Change nothing else.

- [ ] **Step 3: Verify**

Run:

```bash
python3 "$(git rev-parse --git-dir)/verify-edits.py" doc-grounded-questions
wc -c home/common/agent-skills/skills/doc-grounded-questions/SKILL.md
D=home/common/agent-skills/skills/doc-grounded-questions/SKILL.md
echo "-- P4b: the contradiction is gone (want 0) --"
grep -cF 'domain section exists, in full' $D
echo "-- P4b: replacement present (want 1) --"
grep -cF 'whole when it is short, by governing section' $D
echo "-- the map's own read-in-full instruction survives (want 1) --"
grep -cF 'Always read the map in full' $D
echo "-- phase-cache ban untouched and not duplicated (want 1) --"
grep -cF 'do not re-read the map or an area file you have already cached in this phase' $D
```

Expected: `2/2 edits present verbatim.`; `10193` bytes; then `0`, `1`, `1`, `1`.

- [ ] **Step 4: Commit**

```bash
git add home/common/agent-skills/skills/doc-grounded-questions/SKILL.md
git commit -m "$(cat <<'EOF'
fix(agents): read long docs by governing section, not whole (#1)

Adds the ~400-line size cap to step 4 — grep headings first, then open only
the sections covering the components in play (P4a) — and amends step 1's
legacy fallback, whose standing "in full" instruction would otherwise
contradict it (P4b). The context map's own read-in-full rule is exempted,
and the existing phase-cache re-read ban is left alone rather than restated.

Applied verbatim from .claude/specs/2026-08-10-wayfind-skill-hardening-design.md;
9,631 -> 10,193 bytes as measured there.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `grill-with-docs/SKILL.md` — P4c and P5

**Files:**
- Modify: `home/common/agent-skills/skills/grill-with-docs/SKILL.md`
- Test: none — see **Test seams**.

**Interfaces:**
- Consumes: `verify-edits.py` at `$(git rev-parse --git-dir)/verify-edits.py`, installed by Task 1
  Step 1 (re-create it from that step if absent); and the step-4 rule landed by Task 2, which P4c's
  line attributes by name.
- Produces: `grill-with-docs/SKILL.md` at exactly 7,765 bytes. Nothing downstream consumes it.

**The two edits, and the spec section carrying each one.** Apply verbatim from the spec, which this
plan does not reproduce.

| Spec section | What it does | How to apply |
|---|---|---|
| `### P4c — grill-with-docs/SKILL.md, ## Domain awareness: one cross-reference line` | appends the cross-reference sentence | replace (AFTER re-states the BEFORE sentence, then appends) |
| `### P5 — grill-with-docs/SKILL.md, <what-to-do>: reply-by-exception` | two new paragraphs | **insert** |

P5 gives no BEFORE block. Placement: inside `<what-to-do>`, between the paragraph beginning
`Ask the whole frontier as one numbered round` and the paragraph beginning
`If a question can be answered by exploring the codebase or docs`, with one blank line on each side.
Both existing paragraphs stay exactly as they are.

P5 is the one edit in this change that touches HITL decision ownership, so its second paragraph — the
three-way carve-out for questions that redraw the destination or scope, are hard to reverse, or spend
money or a credential — is load-bearing, not decoration. Copy both paragraphs; shipping the first
without the second would weaken an invariant the issue names.

- [ ] **Step 1: Run the gate and watch it fail**

Run: `python3 "$(git rev-parse --git-dir)/verify-edits.py" grill-with-docs; echo "exit=$?"`

Expected: two `FAIL` lines (`P5`, `P4c`), `0/2 edits present verbatim.  2 FAILED.`, `exit=1`.

- [ ] **Step 2: Apply the two edits**

Open `.claude/specs/2026-08-10-wayfind-skill-hardening-design.md` and apply `### P4c` as a literal
BEFORE→AFTER replacement, then insert `### P5`'s AFTER block at the placement described above. Change
nothing else.

- [ ] **Step 3: Verify**

Run:

```bash
python3 "$(git rev-parse --git-dir)/verify-edits.py" grill-with-docs
wc -c home/common/agent-skills/skills/grill-with-docs/SKILL.md
G=home/common/agent-skills/skills/grill-with-docs/SKILL.md
echo "-- P5 order: round-shape, offer, carve-out, then explore-instead --"
grep -nE '^(Ask the whole frontier|When every question in a round|Three kinds of question|If a question can be answered)' $G
echo "-- the pre-existing 'one-line gist' string is untouched (want 1) --"
grep -cF 'one-line gist' $G
echo "-- net-neutral writes rule untouched (want 1) --"
grep -cF 'both are same-commit obligations, never follow-ups' $G
```

Expected: `2/2 edits present verbatim.`; `7765` bytes; then the four greps printing in exactly that
order — `Ask the whole frontier…`, `When every question in a round…`, `Three kinds of question…`,
`If a question can be answered…` (line numbers will differ; the **order** is what is being checked);
then `1` and `1`.

- [ ] **Step 4: Commit**

```bash
git add home/common/agent-skills/skills/grill-with-docs/SKILL.md
git commit -m "$(cat <<'EOF'
fix(agents): reply-by-exception for fully-recommended rounds (#1)

When every question in a round carries a recommendation, the user is told
once they may reply with only the numbers they would change (P5) — with a
carve-out for questions that redraw the destination or scope, are hard to
reverse, or spend money or a credential, which always need a typed answer.
Adds the ~400-line read-by-section cross-reference to Domain awareness,
carrying the threshold so it is actionable without loading
doc-grounded-questions (P4c).

Applied verbatim from .claude/specs/2026-08-10-wayfind-skill-hardening-design.md;
6,845 -> 7,765 bytes as measured there.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Whole-change verification

**Files:**
- Modify: none. This task is a gate; it produces evidence, not a commit (see **Auto-resolved
  decisions**). If a check fails, fix it in the owning file and amend that file's commit rather than
  adding a new one.
- Test: none — see **Test seams**.

**Interfaces:**
- Consumes: all three edited files, and `verify-edits.py` from Task 1 Step 1.
- Produces: the verification evidence quoted in the task report and the PR body. Nothing downstream.

- [ ] **Step 1: All fourteen edits, verbatim**

Run: `python3 "$(git rev-parse --git-dir)/verify-edits.py"; echo "exit=$?"`

Expected: fourteen `PASS` lines, `14/14 edits present verbatim.`, `exit=0`.

- [ ] **Step 2: Byte sizes and scope**

Run:

```bash
wc -c home/common/agent-skills/skills/wayfind/SKILL.md \
      home/common/agent-skills/skills/grill-with-docs/SKILL.md \
      home/common/agent-skills/skills/doc-grounded-questions/SKILL.md
BASE=$(git log --format='%H %s' \
       | grep -m1 'docs(plans): implementation plan for wayfind skill hardening' \
       | cut -d' ' -f1)
echo "base = $BASE"
git diff --stat "$BASE"..HEAD
```

Expected: `10852`, `7765`, `10193`, total `28810`. `$BASE` resolves to this plan's own commit (derived
by message rather than a fixed SHA, so review fixups between tasks cannot invalidate it). The diffstat
lists **exactly three files under `home/common/agent-skills/skills/`**, plus at most flow-artifact
paths under `.claude/plans/` or `.claude/specs/` from the from-issue flow's own process commits (the
Phase-5 provenance amendment lands in this range by construction). Any other file — in particular
`wayfind/evals/evals.json` or anything under `evals/fixture-repo/` — is out of scope and must be
reverted.

- [ ] **Step 3: Invariants survive**

Run:

```bash
W=home/common/agent-skills/skills/wayfind/SKILL.md
echo "-- the four named invariants (each must print 1) --"
grep -cF 'index, not a store' $W
grep -cF 'more than one ticket per session' $W
grep -cF "never answers the human's side" $W
grep -cF '## Fog of war' $W
echo "-- fog discipline lines, unedited (each must print 1) --"
grep -cF 'Chart only what you can see' $W
grep -cF "**Not yet specified** carries only fog" $W
grep -cF 'graduate what became phrasable into fresh tickets' $W
echo "-- one-at-a-time reading discipline (want 2: intro + new low-res definition) --"
grep -cF 'one at a time' $W
```

Expected: four `1`s, then three `1`s, then `2`. The last count is `1` before this change and `2` after
— the second occurrence is P3a's "one at a time, never as a set" for ticket bodies; a `1` here means
P3a did not land.

- [ ] **Step 4: The build**

Run: `just build`

Expected: exit 0. One pre-existing evaluation warning is normal and is **not** a regression —
`evaluation warning: 'system' has been renamed to/replaced by 'stdenv.hostPlatform.system'` is present
at the base commit too. `home/common/claude-code/default.nix:88` copies the whole skills tree into the
store via `skillsDir = ../agent-skills/skills`, so this run does exercise the three edited files.

- [ ] **Step 5: Acceptance criteria roll-call**

Confirm by reading the diff that each of the issue's criteria maps to landed text, and report the
mapping: P1 → P1a + P1b + P1c; P2 → P2; P3 → P3a + P3b; P4 → P4a + P4b + P4c; P5 → P5; P7 → P7;
P8 → P8; P9 → P9a + P9b. Then confirm the three commits are present and correctly shaped:

```bash
BASE=$(git log --format='%H %s' \
       | grep -m1 'docs(plans): implementation plan for wayfind skill hardening' \
       | cut -d' ' -f1)
git log --oneline "$BASE"..HEAD
git log "$BASE"..HEAD --format='%s%n%(trailers:key=Co-Authored-By)'
```

Expected: three `fix(agents): …` commits, one per target file (plus any review fixups from the
between-task gates), every one of them carrying
`Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. Flow-artifact commits
(`docs(plans):` / `docs(specs):` subjects touching only `.claude/plans/` or `.claude/specs/`) are
exempt from the `fix(agents):` subject rule but still require the trailer. Any other commit with no
trailer, or a subject outside these types, is a finding.
