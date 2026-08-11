# Detached-Reviewer Plan Sync Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Amend the four drifted passages of the executed plan
`.claude/plans/2026-08-11-detached-reviewer-bridge.md` so its embedded test snippet and its
verification gates read true against the artifacts that shipped in merged PR #5.

**Architecture:** This is a documentation-accuracy change to one Markdown file. There is no code,
no build, no runtime. The "implementation" is four surgical in-place edits (Tasks 1–4) to
`.claude/plans/2026-08-11-detached-reviewer-bridge.md`; the "tests" are the amended document's own
commands, run against the live shipped artifacts, with the expectations the amended text states
observed to hold. Tasks 1–3 edit without committing; Task 4 makes the single commit that carries all
four edits, because acceptance criterion AC5 scopes to one commit's diff.

**Tech stack:** Markdown; `grep`, `diff`, `awk`, `sed`, `git` (`show`, `diff`, `log`). No Nix, no
Node, no test runner.

---

## Global Constraints

- **Exactly one file may change:** `.claude/plans/2026-08-11-detached-reviewer-bridge.md`. AC5. Never
  `git add` anything else in Task 4's commit.
- **Exactly one commit** carries the amendment, subject
  `docs(plans): sync detached-reviewer plan snippets and gates with what shipped`, ending with the
  trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. Precedent:
  `8cee250` (+33/−2) and `59f3303` (+14/−9), the repo's two existing single-file `docs(plans):` plan-sync
  commits, both subject-line + trailer with no body.
- **Never pass `--no-gpg-sign` or `-c commit.gpgsign=false`.** `git log --format=%G?` reports `N` for
  every commit in this repo because `gpg.ssh.allowedSignersFile` is unset — a local verification-only
  limitation, not a signing failure. Do not "fix" it.
- **`just build` is NOT a gate for any task in this plan, and must not be run as one.** The repo's only
  build gate is `just build`, but this issue changes no `.nix` file — nothing the Nix evaluation reads
  is touched, so a green build would be evidence of nothing. Recorded deliberately so a reviewer does
  not read its absence as an omission.
- **Attestations are byte-stable.** `## Auto-resolved decisions`, `## Standards review (Phase 5)`, D1
  (line 732 at base) and D2 (line 733 at base) in the amended file are out of scope and must not
  change. D1 in particular becomes the *provenance* of Task 1's synced snippet, not a stale note.
- **Out of scope entirely** — do not touch: `.claude/specs/2026-08-11-detached-reviewer-bridge-evidence.md`,
  `patches/agent-plugins/codex-plugin-cc.patch`, `lib/agent-plugins.nix`,
  `home/common/claude-code/skills/codex-collaboration/SKILL.md`, and Task 2 Step 6's cosmetic
  `grep -c … || true  # 0` in the amended plan.
- **`$WORKTREE` inside the amended plan's text is dictated content, not a variable to expand.** It
  refers to `/Users/anis/tmp/nix-config/.claude/worktrees/issue-3-detached-reviewer-bridge`, the
  worktree in which PR #5 was built, which no longer exists. Every `Run:` line you write into the file
  keeps the literal `"$WORKTREE/…"` form the file already uses. When you *rehearse* a gate to confirm it
  holds, substitute this worktree's root — see "Verification provenance" below.
- **Line numbers in this plan are stated at base `f99d7b9`** (the amended file is byte-identical to base
  at HEAD `72f7f88`). Task 1 removes 14 lines, so every line number after 341 shifts by −14 once Task 1
  lands. Use the quoted anchor text, never a line number, to locate an edit.
- **Em dashes are U+2014** (`e2 80 94`). The landed test comment Task 1 inserts contains one; copy the
  block verbatim rather than retyping it.

### Verification provenance (state it precisely — this is the defect the issue exists to remove)

Two of the amended gates prescribe `git diff -- <SKILL.md>` because Task 3 Step 4 of the amended plan
runs *before* Task 3's commit. At `f99d7b9` that change is already committed as `13b0006`, so those two
gates are rehearsed with `git show [-U0] 13b0006 -- <SKILL.md>`. Same change, same hunks, different
command. When you record that a gate holds, say which form you ran. Claiming the prescribed command was
run when a different one was is the exact species of defect S2 documents.

---

## Test seams

A documentation amendment is tested at the seam the amended document itself uses: **every command the
amended text names, run against the shipped artifacts, with its stated expectation observed.** No new
seam is invented. Three seams, all runnable from this worktree at HEAD:

1. **Snippet-equals-artifact** (Task 1). Extract the fenced block from the amended Task 1 Step 2;
   extract the added lines of the `tests/reviewer-detach.test.mjs` hunk from
   `patches/agent-plugins/codex-plugin-cc.patch`; `diff` them; expect empty output, exit 0. This is the
   amended plan's own idiom — its Task 3 Step 5 already gates patch determinism with a
   `git diff -U0 "$PIN" | diff - "…patch"` diff-to-empty check.
2. **Gate rehearsal** (Tasks 2–4). Every `Run:` line the amendment adds or rewords is executed against
   the live artifact and its printed output compared to the `Expected:` line written beside it.
3. **Single-file commit** (Task 4). `git show --stat --format= HEAD` names exactly
   `.claude/plans/2026-08-11-detached-reviewer-bridge.md` and nothing else. AC5 scopes to the amendment
   commit; this run's own from-issue artifacts (the design spec at `72f7f88`, and this plan file) are
   separate commits and are not part of that diff.

Shell prelude used by every gate in this plan. Set it once per shell; every `Run:` block below assumes
`$WT`, `$PLAN`, `$PATCH` and `$SKILL` are already exported, and the blocks that begin a task re-set them
so a task can be executed in a fresh shell on its own:

```bash
WT=/Users/anis/tmp/nix-config/.claude/worktrees/issue-6-plan-doc-sync
PLAN="$WT/.claude/plans/2026-08-11-detached-reviewer-bridge.md"
PATCH="$WT/patches/agent-plugins/codex-plugin-cc.patch"
SKILL="$WT/home/common/claude-code/skills/codex-collaboration/SKILL.md"
```

Note that `$PLAN` is the **file being amended**, not this file.

---

## Auto-resolved decisions

### Task granularity: one task per drifted passage

- **Question:** Four passages in one file — one task, two tasks (S1 / gates), or four?
- **Choice:** Four tasks, one per passage: S1 snippet (Task 1), Task 1 Step 6 gate (Task 2), Task 3
  Step 4 gate list (Task 3), the R6 coverage line plus the commit (Task 4).
- **Grounding:** `writing-plans`: "split only where a reviewer could meaningfully reject one task while
  approving its neighbor." Each passage has its own distinct falsifiable gate against a different live
  artifact — Task 1 against the patch's test hunk, Task 2 against the patch's hunk headers, Task 3
  against the live SKILL.md, Task 4 against the amended file's internal consistency. A reviewer can
  reject the Task 3 gate list (semantic wording of seven checks) while approving the Task 1 byte-diff,
  which is precisely the split that earns separate gates. The issue itself enumerates four passages and
  five acceptance criteria that map 1:1 onto them.
- **Alternative considered:** One task containing all four edits — it would have exactly one gate for
  four independent claims, and a reviewer disagreeing with one gate's wording would have to reject the
  byte-exact snippet resync along with it.

### Tasks 1–3 do not commit; Task 4 makes the single commit

- **Question:** `writing-plans` prescribes "frequent commits" and a commit step per task, but AC5 scopes
  to one commit's diff and the spec fixed one commit. Which wins?
- **Choice:** Tasks 1–3 end with verification and explicitly no commit; Task 4 stages the accumulated
  four-passage diff and commits once. Every task still ends with an independently testable deliverable —
  the deliverable is the amended passage in the working tree, verified by that task's gate.
- **Grounding:** Issue AC5 as bound in Phase 0: "AC5 requires the amendment commit's diff to touch
  exactly one file"; spec `## Auto-resolved decisions` → "One commit, `docs(plans):` subject … AC5
  requires the final diff to touch exactly one file, which a single commit makes trivially checkable via
  `git show --stat`." Both precedent commits (`8cee250`, `59f3303`) are single commits for a whole
  round of plan amendments. All four tasks edit the same file in the same working tree, so uncommitted
  state carries across `sdd` task boundaries without conflict.
- **Alternative considered:** A commit per task plus a final squash — four commits then a rebase, more
  moving parts and more ways to lose the single-file property, for no reviewer benefit on ~60 lines of
  Markdown.

### Gate design: content anchors and section extraction, never line numbers

- **Question:** Task 1 shortens the file by 14 lines, shifting every later line number. How should
  Tasks 2–4's gates locate their passages?
- **Choice:** Extract the enclosing step with `awk` between its `- [ ] **Step N: …**` heading and the
  next `- [ ] **Step …` heading, then grep inside the extract; and locate edits by unique quoted anchor
  text. No gate in this plan asserts a line number in the amended file.
- **Grounding:** Measured in this worktree: `awk '/^- \[ \] \*\*Step 4: Verify the edits are exactly the
  three regions\*\*/{f=1} f&&/^- \[ \] \*\*Step 5:/{exit} f' "$PLAN"` returns exactly that step's 13
  lines. Every anchor this plan quotes was confirmed to occur exactly once in the file (`grep -c`:
  `const GUARD_MESSAGE = …` → 1, `const resultPayload = await waitFor` → 1, the Step 4 heading → 1, the
  R6 line → 1). Scoping matters: bare `grep -c "codex-companion task" "$PLAN"` returns **4** and
  `grep -ic "completion notification" "$PLAN"` returns **5** at base, from unrelated passages — an
  unscoped count gate on either string would be meaningless.
- **Alternative considered:** Line-number gates recomputed per task — brittle, and they would silently
  pass against the wrong passage if an earlier task's line delta were mis-stated.

### Each task opens by observing its own gate fail

- **Question:** A docs change has no failing test to write first. How is test-first honoured?
- **Choice:** Every task's Step 1 runs that task's verification command at the task's starting state and
  records the failing observation, before any edit.
- **Grounding:** `writing-plans`: "Name the command and the observation that would show the task
  incomplete, and confirm that observation holds at the commit the implementer starts from. A criterion
  already true at the base commit is how an implementer 'completes' a no-op." All four were confirmed
  false at base while writing this plan (issue: "all confirmed false at base").
- **Alternative considered:** Verify-only at the end — for a change whose entire subject is documents
  that assert unverified things, shipping a gate nobody watched fail would repeat the defect.

### Gates rehearse against live artifacts, and say which command form was rehearsed

- **Question:** The amended gates prescribe `git diff` against an uncommitted working tree in a worktree
  that no longer exists. Assert "the gate was run" anyway?
- **Choice:** No. Each task rehearses with the equivalent committed-form command (`git show 13b0006`,
  `git show 377241e`) against this worktree, and this plan names both forms explicitly at every such
  gate.
- **Grounding:** `~/.agents/standards/the-bar.md`: "Run it and show the behaviour. Absence of an error
  is not evidence of success, and neither is a plausible diff. State what you ran and what it printed,
  or say plainly that you did not verify." Spec § "Verification provenance (stated precisely, because
  that is the point of this issue)".
- **Alternative considered:** Reconstructing an uncommitted working-tree state so the literal `git diff`
  form could run — ceremony producing an identical result on a docs change.

### The `@@ -0,0 +1,150 @@` pin is a cross-check, and Task 2's gate depends on Task 1 having landed

- **Question:** Task 2 writes a gate expecting the hunk header `@@ -0,0 +1,150 @@`, whose 150 must equal
  the length of the block Task 1 produces. Order the tasks, or pin the number independently?
- **Choice:** Task 1 first, and Task 2's Step 1 re-measures the amended block's length (must be 150)
  before writing the pin. The two amended passages cross-check each other.
- **Grounding:** Measured in this worktree: the base block is 164 lines (`awk` extract of Task 1 Step 2);
  the landed test inside the patch is 150 lines; their `diff` is exactly two hunks. 164 − 12 (helper +
  its trailing blank) − 2 (7-line wrapper → 5-line body) = 150, and `grep -c "^@@ -0,0 +1,150 @@"
  "$PATCH"` = 1.
- **Alternative considered:** A `@@ -0,0 +1,<n> @@` placeholder — the spec rejected it as weaker, and the
  plan's house style pins exact expected values (`Expected: 2`, `# tests 107 / # pass 103`).

### Diff-shape gates pin measured hunk headers, not guessed counts

- **Question:** Tasks 1, 3 and 4 gate on "the diff touched only what it should". State a hunk *count*,
  a *stat*, or the literal hunk headers?
- **Choice:** All three, and every number obtained by **simulating the four edits against the base file
  and measuring**, never by reasoning about them.
- **Grounding:** The first draft of this plan reasoned that Task 3's contiguous body replacement would
  produce one `-U0` hunk and that the whole amendment would produce five. Simulation showed Task 3
  produces **three** (the untouched gates it leaves in place sit between the changed regions, and `-U0`
  splits at every unchanged line) and the amendment produces **seven**, at `27 insertions(+), 22
  deletions(-)`. Those wrong numbers were corrected before this plan was committed. Dictating an
  unverified count into a plan whose entire purpose is removing unverified claims would have reproduced
  the defect at one remove — `~/.agents/standards/the-bar.md`: "Absence of an error is not evidence of
  success, and neither is a plausible diff."
- **Alternative considered:** Softening to "no unexpected hunks" — unfalsifiable, and it would let the
  exact class of stray edit these gates exist to catch through.

### Acceptance-criterion mapping lives in the plan, not only in the issue

- **Question:** Where does the AC→task map go?
- **Choice:** A `## Acceptance-criteria map` section at the end of this plan, plus an `**Acceptance
  criterion:**` line in each task header.
- **Grounding:** The amended plan itself carries a `## Spec coverage` section mapping R1–R8 onto tasks;
  matching that shape keeps the two documents legible side by side. The dispatch requires ACs mapped
  explicitly.
- **Alternative considered:** Leaving the map implicit in task titles — a fresh implementer reading one
  task in isolation would not know which criterion it discharges.

---

### Task 1: Resync Task 1 Step 2's embedded test block with the landed test

**Acceptance criterion:** AC1 — "Task 1 Step 2 contains no `waitFor` definition or call; the `result`
collection appears as a single call whose assertion carries stderr, matching the landed
`tests/reviewer-detach.test.mjs` inside `patches/agent-plugins/codex-plugin-cc.patch`."

**Files:**
- Modify: `.claude/plans/2026-08-11-detached-reviewer-bridge.md` (the `- [ ] **Step 2: Write the failing
  tests**` fenced `js` block, lines 178–341 at base)
- Read only (never modify): `patches/agent-plugins/codex-plugin-cc.patch`

**Interfaces:**
- Consumes: nothing from earlier tasks; this is the first task.
- Produces: the amended fenced block is exactly **150** lines and byte-identical to the landed
  `tests/reviewer-detach.test.mjs`. Task 2 writes a gate pinning the patch hunk header
  `@@ -0,0 +1,150 @@`, which is only true because this task produced a 150-line block.

- [ ] **Step 1: Watch the gate fail**

````bash
WT=/Users/anis/tmp/nix-config/.claude/worktrees/issue-6-plan-doc-sync
PLAN="$WT/.claude/plans/2026-08-11-detached-reviewer-bridge.md"
PATCH="$WT/patches/agent-plugins/codex-plugin-cc.patch"

awk '/^- \[ \] \*\*Step 2: Write the failing tests\*\*/{f=1} f&&/^```js$/{c=1;next} c&&/^```$/{exit} c' "$PLAN" > /tmp/plan-snippet.js
awk '/^@@ -0,0 \+1,150 @@$/{c=1;next} c&&!/^\+/{exit} c{sub(/^\+/,"");print}' "$PATCH" > /tmp/landed-test.js
wc -l /tmp/plan-snippet.js /tmp/landed-test.js
diff /tmp/plan-snippet.js /tmp/landed-test.js
````

Expected: FAIL — `164 /tmp/plan-snippet.js`, `150 /tmp/landed-test.js`, and `diff` exits 1 printing
exactly two hunks: `23,34d22` (the `waitFor` helper and its trailing blank line) and `82,88c70,74`
(the retry wrapper against the landed direct call). Nothing else differs.

- [ ] **Step 2: Delete the `waitFor` helper**

In `.claude/plans/2026-08-11-detached-reviewer-bridge.md`, replace exactly (this anchor occurs once in
the file):

````markdown
const GUARD_MESSAGE = "Reviewer jobs must be fresh and read-only.";

async function waitFor(predicate, { timeoutMs = 5000, intervalMs = 50 } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const value = await predicate();
    if (value) {
      return value;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("Timed out waiting for condition.");
}

function makeReviewRepo() {
````

with:

````markdown
const GUARD_MESSAGE = "Reviewer jobs must be fresh and read-only.";

function makeReviewRepo() {
````

That is a 12-line deletion: the 11-line helper plus the blank line that followed it. The blank line
after `GUARD_MESSAGE` survives, so `function makeReviewRepo() {` is preceded by exactly one blank line.

- [ ] **Step 3: Replace the retry wrapper with the landed direct call**

In the same fenced block, inside test 1, replace exactly (this anchor occurs once in the file):

````markdown
  const resultPayload = await waitFor(() => {
    const collected = run("node", [SCRIPT, "result", launchPayload.jobId, "--json"], { cwd: repo, env });
    if (collected.status !== 0) {
      return null;
    }
    return JSON.parse(collected.stdout);
  });
````

with:

````markdown
  // status --wait reported `completed`, so the record is terminal: one direct
  // `result` call must succeed — no retry loop.
  const collected = run("node", [SCRIPT, "result", launchPayload.jobId, "--json"], { cwd: repo, env });
  assert.equal(collected.status, 0, collected.stderr);
  const resultPayload = JSON.parse(collected.stdout);
````

Seven lines become five. The comment is part of the shipped file and states why the retry is
unnecessary — keep it, including its U+2014 em dash in `— no retry loop.`. Indentation is two spaces on
every line.

**Do not touch anything else in the block.** In particular, test 1's signature stays
`test("a background reviewer run survives its launcher and lands a verbatim durable result", async () => {`
even though no `await` survives in its body — that is how the file shipped, and the block exists to be
copied byte-for-byte. Dropping `async` would make the plan false in a new way.

- [ ] **Step 4: Verify — the block is byte-identical to the landed test**

````bash
WT=/Users/anis/tmp/nix-config/.claude/worktrees/issue-6-plan-doc-sync
PLAN="$WT/.claude/plans/2026-08-11-detached-reviewer-bridge.md"
PATCH="$WT/patches/agent-plugins/codex-plugin-cc.patch"

awk '/^- \[ \] \*\*Step 2: Write the failing tests\*\*/{f=1} f&&/^```js$/{c=1;next} c&&/^```$/{exit} c' "$PLAN" > /tmp/plan-snippet.js
awk '/^@@ -0,0 \+1,150 @@$/{c=1;next} c&&!/^\+/{exit} c{sub(/^\+/,"");print}' "$PATCH" > /tmp/landed-test.js
wc -l < /tmp/plan-snippet.js
diff /tmp/plan-snippet.js /tmp/landed-test.js && echo "IDENTICAL"
````

Expected: PASS — `150`, then `diff` prints nothing and `IDENTICAL` appears (exit 0).

- [ ] **Step 5: Verify — `waitFor` survives only in the D1 attestation**

```bash
grep -n "waitFor" "$PLAN"
```

Expected: exactly one line, the D1 disposition in `## Standards review (Phase 5)`:
`- **D1 (dead \`waitFor\` retry around \`result\` in Task 1 test 1):** disposition — accepted; …`.
D1 is an attestation and must be byte-stable: it now reads as the provenance of the synced snippet.

- [ ] **Step 6: Verify — only the intended 14 lines moved, and nothing else in the file did**

```bash
git -C "$WT" diff --stat -- .claude/plans/2026-08-11-detached-reviewer-bridge.md
git -C "$WT" diff -U0 -- .claude/plans/2026-08-11-detached-reviewer-bridge.md | grep '^@@'
```

Expected: one file changed, `5 insertions(+), 19 deletions(-)`; and exactly two hunk headers —

```
@@ -200,12 +199,0 @@ const GUARD_MESSAGE = "Reviewer jobs must be fresh and read-only.";
@@ -259,7 +247,5 @@ test("a background reviewer run survives its launcher and lands a verbatim durab
```

(measured by simulating this task's two edits against the base file). A third header means a stray edit
landed — revert it.

- [ ] **Step 7: Do not commit**

Leave the change staged-or-unstaged in the working tree. Task 4 makes the single commit that carries all
four passages (AC5). Running `git commit` here would split the amendment across commits and break the
AC5 check.

---

### Task 2: Task 1 Step 6 — demote `--stat` to a summary, add the patch-content hunk grep

**Acceptance criterion:** AC2 (first half) — "Task 1 Step 6 … no longer claim[s] `--stat` verifies
patch/hunk contents; each gate names a content-level check, with `--stat` retained only as a summary
line."

**Files:**
- Modify: `.claude/plans/2026-08-11-detached-reviewer-bridge.md` (the two lines at the head of
  `- [ ] **Step 6: Regenerate the patch and bump \`patchRevision\`**`, lines 381–382 at base)
- Read only (never modify): `patches/agent-plugins/codex-plugin-cc.patch`

**Interfaces:**
- Consumes: Task 1's amended block, now exactly 150 lines — that is what makes the `@@ -0,0 +1,150 @@`
  pin written below true of both the patch and the plan.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Watch the gate fail, and re-measure the 150 the new gate will pin**

````bash
WT=/Users/anis/tmp/nix-config/.claude/worktrees/issue-6-plan-doc-sync
PLAN="$WT/.claude/plans/2026-08-11-detached-reviewer-bridge.md"
PATCH="$WT/patches/agent-plugins/codex-plugin-cc.patch"

grep -n "the patch diff includes the new" "$PLAN"
awk '/^- \[ \] \*\*Step 2: Write the failing tests\*\*/{f=1} f&&/^```js$/{c=1;next} c&&/^```$/{exit} c' "$PLAN" | wc -l
grep -c "^@@ -0,0 +1,150 @@" "$PATCH"
````

Expected: FAIL on the first command — it prints one match, the `--stat` `Expected:` line claiming the
diff "includes the new `tests/reviewer-detach.test.mjs` hunks and the one-predicate change". The second
prints `150` (Task 1 landed) and the third prints `1`. If the second does not print `150`, stop: Task 1
is incomplete and the pin this task writes would be wrong.

- [ ] **Step 2: Rehearse the replacement gate against the live patch**

```bash
grep -A5 "^diff --git a/tests/reviewer-detach\.test\.mjs" "$PATCH"; echo "exit=$?"
grep -c "^new file mode" "$PATCH"
git -C "$WT" show --stat --format= 377241e
```

Expected — this is the printed output that licenses the wording written in Step 3:

```
diff --git a/tests/reviewer-detach.test.mjs b/tests/reviewer-detach.test.mjs
new file mode 100644
index 0000000..e29047b
--- /dev/null
+++ b/tests/reviewer-detach.test.mjs
@@ -0,0 +1,150 @@
exit=0
```

then `5` (the patch has five `new file mode` hunks, so the added-file header and the hunk header must be
seen *adjacent* to prove they belong to the same file — which is why this gate uses `-A5` rather than two
independent counts), then `377241e`'s stat: 2 files changed, 160 insertions(+), 4 deletions(-), with 162
of those changed lines in the patch and 2 in `lib/agent-plugins.nix`.

- [ ] **Step 3: Replace the two lines at the head of the step's gate block**

In `.claude/plans/2026-08-11-detached-reviewer-bridge.md`, replace exactly:

````markdown
Run: `git -C "$WORKTREE" diff --stat -- patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix`
Expected: both files modified; the patch diff includes the new `tests/reviewer-detach.test.mjs` hunks and the one-predicate change in `plugins/codex/scripts/codex-companion.mjs`.
````

with:

````markdown
Run: `git -C "$WORKTREE" diff --stat -- patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix`
Expected: a summary line only — exactly these two files modified, with nearly all the changed lines landing in the patch. `--stat` counts changed lines; it cannot show which hunks the regenerated patch gained or what they contain, so the three content checks below carry those claims.

Run: `grep -A5 "^diff --git a/tests/reviewer-detach\.test\.mjs" "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: one match, showing `new file mode 100644` and, five lines below the `diff --git` line, the whole-file hunk header `@@ -0,0 +1,150 @@` — the new test enters the patch as a single added-file hunk of exactly the 150-line block Step 2 dictates. `-A5` rather than two separate counts because the patch carries five `new file mode` hunks: the claim is that *these two lines belong to the same file*, which only adjacency shows.

The one-predicate change in `plugins/codex/scripts/codex-companion.mjs` is what the next two greps prove — the old guard message gone from the patch entirely, the new one present exactly twice:
````

Keep the literal `$WORKTREE` in both `Run:` lines; it is the file's own idiom for the issue-3 worktree.

**The two guard-message greps that follow are unchanged** — `Reviewer jobs must be fresh, foreground`
(expects no matches, exit 1) and `Reviewer jobs must be fresh and read-only.` (expects `2`). They were
always the real content-level proof of the predicate change; this amendment only stops `--stat` from
claiming their work. Do not reword or reorder them.

- [ ] **Step 4: Verify — the false claim is gone and the step reads as three content checks**

```bash
grep -c "the patch diff includes the new" "$PLAN"; echo "exit=$?"
awk '/^- \[ \] \*\*Step 6: Regenerate the patch and bump/{f=1} f&&/^- \[ \] \*\*Step 7:/{exit} f' "$PLAN" > /tmp/step6.txt
grep -c '^Run: ' /tmp/step6.txt
grep -c 'grep -A5 "\^diff --git a/tests/reviewer-detach' /tmp/step6.txt
cat /tmp/step6.txt
```

Expected: `0` and `exit=1` from the first command — the false claim is gone. Then `4` (the step now
carries four `Run:` gates: `--stat`, the new `grep -A5`, and the two unchanged guard-message greps —
it carried three before), then `1`. The `cat` then shows the whole amended Step 6, which must read, in
order: the `--stat` gate whose `Expected:` line explicitly disclaims hunk-level knowledge; the
`grep -A5` gate pinning `@@ -0,0 +1,150 @@`; the lead-in sentence; and the two unchanged guard-message
greps.

- [ ] **Step 5: Verify — the two unchanged guard greps still hold against the live patch**

```bash
grep -c "Reviewer jobs must be fresh, foreground" "$PATCH"; echo "exit=$?"
grep -c "Reviewer jobs must be fresh and read-only." "$PATCH"
```

Expected: `0` with `exit=1`, then `2`. (Rehearsed here because the amended lead-in sentence now names
these two greps as what carries the one-predicate claim — the plan must not name a gate without the
gate holding.)

- [ ] **Step 6: Do not commit**

Task 4 makes the single commit. See Task 1 Step 7.

---

### Task 3: Task 3 Step 4 — add the two missing R6 prohibition greps and replace the `--stat` claim

**Acceptance criterion:** AC2 (second half) and AC3 — "Task 3 Step 4 no longer claim[s] `--stat` verifies
patch/hunk contents", and "Task 3 Step 4's gate list includes case-insensitive negative greps for
`completion notification` and for `codex-companion task` against
`home/common/claude-code/skills/codex-collaboration/SKILL.md`, recorded as passing (exit 1) against the
live file."

**Files:**
- Modify: `.claude/plans/2026-08-11-detached-reviewer-bridge.md` (the body of
  `- [ ] **Step 4: Verify the edits are exactly the three regions**`, lines 646–658 at base, 632–644
  after Task 1)
- Read only (never modify): `home/common/claude-code/skills/codex-collaboration/SKILL.md`

**Interfaces:**
- Consumes: nothing from Tasks 1–2.
- Produces: a gate list of exactly seven `Run:`/`Expected:` pairs — the three R6 prohibition greps
  (`background`, `codex-companion task`, `completion notification`), the process-failure-class negative,
  the `Launch mechanics live solely` positive, the `--stat` summary, and the two diff-shape checks. Task
  4's amended R6 coverage line names three of these by string and must match them exactly.

- [ ] **Step 1: Watch the gate fail**

```bash
WT=/Users/anis/tmp/nix-config/.claude/worktrees/issue-6-plan-doc-sync
PLAN="$WT/.claude/plans/2026-08-11-detached-reviewer-bridge.md"
SKILL="$WT/home/common/claude-code/skills/codex-collaboration/SKILL.md"

awk '/^- \[ \] \*\*Step 4: Verify the edits are exactly the three regions\*\*/{f=1} f&&/^- \[ \] \*\*Step 5:/{exit} f' "$PLAN" > /tmp/step4.txt
cat /tmp/step4.txt
grep -c 'codex-companion task' /tmp/step4.txt; grep -ci 'completion notification' /tmp/step4.txt
```

Expected: FAIL — the extract is 13 lines carrying only **three** gates (`background`, the
process-failure-class negative, `Launch mechanics live solely`) plus a `--stat` gate whose `Expected:`
line reads "exactly one file changed; the hunks touch only the Launch paragraph, the failure-class
bullets, and the diff-review paragraph". Both counts print `0`: the two R6 prohibition greps are absent.
(Count inside the *extract*, not the whole file — file-wide, `codex-companion task` occurs 4 times and
`completion notification` 5 times at base, all in unrelated passages.)

- [ ] **Step 2: Rehearse all seven replacement gates against the live artifacts**

```bash
grep -in "background" "$SKILL"; echo "exit=$?"
grep -in "codex-companion task" "$SKILL"; echo "exit=$?"
grep -in "completion notification" "$SKILL"; echo "exit=$?"
grep -in "codex-companion" "$SKILL"; echo "exit=$?"
grep -n "the process crashes or reaches its hard timeout" "$SKILL"; echo "exit=$?"
grep -c "Launch mechanics live solely" "$SKILL"
git -C "$WT" show --stat --format= 13b0006 -- home/common/claude-code/skills/codex-collaboration/SKILL.md
git -C "$WT" show -U0 13b0006 -- home/common/claude-code/skills/codex-collaboration/SKILL.md | grep '^@@'
git -C "$WT" show 13b0006 -- home/common/claude-code/skills/codex-collaboration/SKILL.md | grep -c '^@@'
```

Expected: the first three print nothing with `exit=1` (all three R6 prohibitions clear on the live file);
the fourth prints **one** line — `88:Pre-flight first, one sub-second call: \`command -v codex-companion\`. If the`
with `exit=0`, which is exactly why the launch-command gate must be the two-word form and never the bare
word; the fifth prints nothing with `exit=1`; the sixth prints `1`. Then `13b0006` shows 1 file changed,
11 insertions(+), 8 deletions(-); its `-U0` hunk headers are exactly three —

```
@@ -96,5 +96,7 @@ Run it in the foreground, with the first line of the dispatch exactly
@@ -114,2 +116,3 @@ confidence, and unknowns. Treat only these as Codex failures:
@@ -155 +158 @@ packet by paths, `WORKTREE_ROOT:` first line, one foreground `codex:codex-review
```

— and the default-context hunk count is also `3`. **Provenance:** the amended gates prescribe
`git diff [-U0] -- <SKILL.md>` because in the amended plan Step 4 runs before Task 3's commit; at this
worktree's HEAD that change is committed as `13b0006`, so the rehearsal uses `git show [-U0] 13b0006`.
Same change, same hunks, different command.

- [ ] **Step 3: Replace the step's body in full**

In `.claude/plans/2026-08-11-detached-reviewer-bridge.md`, replace everything from the line
`- [ ] **Step 4: Verify the edits are exactly the three regions**` up to (but not including) the line
`- [ ] **Step 5: Final whole-issue verification — patch determinism, revision, closure**` with:

````markdown
- [ ] **Step 4: Verify the edits are exactly the three regions**

R6's three prohibitions, one case-insensitive grep each — match on exit status, not on printed output:

Run: `grep -in "background" "$WORKTREE/home/common/claude-code/skills/codex-collaboration/SKILL.md"`
Expected: no output (exit 1). At this task's starting commit the same grep matches in the Launch paragraph ("as a background / Bash task") and the diff-review paragraph ("with background launch inside the bridge") — this gate fails until both edits land.

Run: `grep -in "codex-companion task" "$WORKTREE/home/common/claude-code/skills/codex-collaboration/SKILL.md"`
Expected: no output (exit 1). This gate also fails until Step 1's edit lands: at the starting commit the old Launch paragraph names the launch command itself, `codex-companion task --fresh --reviewer --timeout-ms 840000`. Matched on the two-word form deliberately — the bare word must survive in the pre-flight `command -v codex-companion`, which this task does not touch.

Run: `grep -in "completion notification" "$WORKTREE/home/common/claude-code/skills/codex-collaboration/SKILL.md"`
Expected: no output (exit 1). Unlike the other two this one already passes at the starting commit — the wording has never been in this file, and the gate is here so the rewrite cannot introduce it. The bridge reports by returning its output, never by notifying.

Run: `grep -n "the process crashes or reaches its hard timeout" "$WORKTREE/home/common/claude-code/skills/codex-collaboration/SKILL.md"`
Expected: no output (exit 1) — the process-level failure class is gone.

Run: `grep -c "Launch mechanics live solely" "$WORKTREE/home/common/claude-code/skills/codex-collaboration/SKILL.md"`
Expected: `1`.

Run: `git -C "$WORKTREE" diff --stat -- home/common/claude-code/skills/codex-collaboration/SKILL.md`
Expected: a summary line only — one file changed, a handful of lines (11 insertions, 8 deletions). `--stat` cannot show *which* regions moved; the two checks below carry that claim.

Run: `git -C "$WORKTREE" diff -U0 -- home/common/claude-code/skills/codex-collaboration/SKILL.md | grep '^@@'`
Expected: exactly three hunk headers — one in the `## Launch` second paragraph (old line 96), one in the `## Validate and fall back` bullet list (old line 114), one in the diff-review mechanics clause (old line 155). `-U0` so the ranges point at the changed lines themselves and `^@@` provably matches headers only. A fourth header means a stray edit landed: revert it.

Run: `git -C "$WORKTREE" diff -- home/common/claude-code/skills/codex-collaboration/SKILL.md`
Expected: read all three hunks. Each removes exactly the Old text and adds exactly the New text dictated in Steps 1–3; no other line in the file differs.
````

Every pre-existing gate keeps its relative order and its wording; the two new prohibition greps are
inserted directly after their sibling `background` gate, under the new lead-in line, so the R6 sweep
reads as one unit. The step's title is unchanged — it already carried prohibition greps before this
amendment, so it was never a literal table of contents.

- [ ] **Step 4: Verify — the amended step contains all seven gates and no `--stat` content claim**

```bash
awk '/^- \[ \] \*\*Step 4: Verify the edits are exactly the three regions\*\*/{f=1} f&&/^- \[ \] \*\*Step 5:/{exit} f' "$PLAN" > /tmp/step4.txt
grep -c '^Run: ' /tmp/step4.txt
grep -c 'grep -in "codex-companion task"' /tmp/step4.txt
grep -c 'grep -in "completion notification"' /tmp/step4.txt
grep -c 'the hunks touch only the Launch paragraph' /tmp/step4.txt; echo "exit=$?"
grep -c 'diff -U0' /tmp/step4.txt
```

Expected: `8`, `1`, `1`, then `0` with `exit=1` (the false `--stat` claim is gone), then `1`. The `Run:`
count is 8 and not 7 because the `diff -U0 … | grep '^@@'` and the full `git diff` read are two separate
`Run:` lines alongside the six single-command gates.

- [ ] **Step 5: Verify — the diff touched only this step**

```bash
git -C "$WT" diff -U0 -- .claude/plans/2026-08-11-detached-reviewer-bridge.md | grep '^@@'
```

Expected: **six** hunk headers total across Tasks 1–3 — two from Task 1 (helper site, `result` call
site), one from Task 2 (Step 6's gate head), and **three** from this task. This task's replacement
produces three `-U0` hunks rather than one because the gates it leaves untouched (the `background`
grep, the process-failure-class grep, the `Launch mechanics live solely` pin) sit *between* the regions
it changes, and `-U0` splits a hunk at every unchanged line: one hunk inserts the lead-in line, one
inserts the two new prohibition greps after the `background` gate, one rewrites the `--stat`
`Expected:` line and appends the two diff-shape gates. Measured by simulating all four tasks' edits
against the base file. A seventh header at this point means a stray edit landed: revert it.

- [ ] **Step 6: Do not commit**

Task 4 makes the single commit. See Task 1 Step 7.

---

### Task 4: Restate the Spec-coverage R6 line, sweep the whole amendment, and commit

**Acceptance criterion:** AC4 — "The Spec-coverage R6 line's verification claim matches the amended gate
list" — and AC5 — "The change touches only
`.claude/plans/2026-08-11-detached-reviewer-bridge.md` (docs-only; no patch, nix, or skill files)."

**Files:**
- Modify: `.claude/plans/2026-08-11-detached-reviewer-bridge.md` (the `- R6/AC6 …` bullet in
  `## Spec coverage`, line 721 at base, 707 after Task 1)

**Interfaces:**
- Consumes: Task 3's amended gate list — the three grep names and the positive pin quoted in the new R6
  line must be exactly the strings that appear there.
- Produces: the single amendment commit at `HEAD`.

- [ ] **Step 1: Watch the gate fail**

```bash
WT=/Users/anis/tmp/nix-config/.claude/worktrees/issue-6-plan-doc-sync
PLAN="$WT/.claude/plans/2026-08-11-detached-reviewer-bridge.md"

grep -n "three edits + greps" "$PLAN"
```

Expected: FAIL — one match, the R6 coverage bullet reading `Task 3 (three edits + greps).`, which reads
as if all three R6 prohibitions were grep-verified when only `background` was written down.

- [ ] **Step 2: Replace the R6 coverage line**

In `.claude/plans/2026-08-11-detached-reviewer-bridge.md`, replace exactly:

````markdown
- R6/AC6 (skill states contract only; no background tasks / completion notifications / launch command): Task 3 (three edits + greps).
````

with:

````markdown
- R6/AC6 (skill states contract only; no background tasks / completion notifications / launch command): Task 3 — the three edits, plus Step 4's one case-insensitive negative grep per prohibition (`background`, `codex-companion task`, `completion notification`, each exiting 1 against the edited file) and the positive `Launch mechanics live solely` pin.
````

The three quoted grep patterns come from the design spec's R6 requirement — "…no longer mentions harness
background tasks, completion notifications, or the launch command" — and map 1:1 onto the three gates
Task 3 wrote. Do not touch any other bullet in `## Spec coverage`.

- [ ] **Step 3: Verify — the R6 line names exactly the gates that exist**

```bash
grep -c "three edits + greps" "$PLAN"; echo "exit=$?"
awk '/^- \[ \] \*\*Step 4: Verify the edits are exactly the three regions\*\*/{f=1} f&&/^- \[ \] \*\*Step 5:/{exit} f' "$PLAN" > /tmp/step4.txt
for pat in 'grep -in "background"' 'grep -in "codex-companion task"' 'grep -in "completion notification"' 'grep -c "Launch mechanics live solely"'; do
  printf '%-42s %s\n' "$pat" "$(grep -c -- "$pat" /tmp/step4.txt)"
done
grep -n '^- R6/AC6' "$PLAN"
```

Expected: `0` with `exit=1`; then each of the four patterns prints `1` — every gate the new R6 line
names is present in Task 3 Step 4, and nothing it names is missing; then the amended R6 bullet prints.

- [ ] **Step 4: Sweep — every amended gate holds against the live artifacts**

````bash
WT=/Users/anis/tmp/nix-config/.claude/worktrees/issue-6-plan-doc-sync
PLAN="$WT/.claude/plans/2026-08-11-detached-reviewer-bridge.md"
PATCH="$WT/patches/agent-plugins/codex-plugin-cc.patch"
SKILL="$WT/home/common/claude-code/skills/codex-collaboration/SKILL.md"

# AC1 — snippet equals the landed test, byte for byte
awk '/^- \[ \] \*\*Step 2: Write the failing tests\*\*/{f=1} f&&/^```js$/{c=1;next} c&&/^```$/{exit} c' "$PLAN" > /tmp/plan-snippet.js
awk '/^@@ -0,0 \+1,150 @@$/{c=1;next} c&&!/^\+/{exit} c{sub(/^\+/,"");print}' "$PATCH" > /tmp/landed-test.js
diff /tmp/plan-snippet.js /tmp/landed-test.js && echo "AC1 ok ($(wc -l < /tmp/plan-snippet.js) lines)"

# AC2a — Task 1 Step 6's new patch-content gate
grep -A5 "^diff --git a/tests/reviewer-detach\.test\.mjs" "$PATCH" | tail -1

# AC2b/AC3 — Task 3 Step 4's gates, against the live SKILL.md and 13b0006
for pat in "background" "codex-companion task" "completion notification"; do
  grep -qin "$pat" "$SKILL"; echo "$pat -> exit $?"
done
grep -c "Launch mechanics live solely" "$SKILL"
git -C "$WT" show -U0 13b0006 -- home/common/claude-code/skills/codex-collaboration/SKILL.md | grep -c '^@@'
````

Expected: `AC1 ok (150 lines)`; `@@ -0,0 +1,150 @@`; `background -> exit 1`,
`codex-companion task -> exit 1`, `completion notification -> exit 1`; `1`; `3`.

- [ ] **Step 5: Verify — attestations and out-of-scope files are untouched**

```bash
git -C "$WT" status --porcelain
git -C "$WT" diff --stat -- .claude/plans/2026-08-11-detached-reviewer-bridge.md | tail -1
git -C "$WT" diff -U0 -- .claude/plans/2026-08-11-detached-reviewer-bridge.md | grep '^@@'
git -C "$WT" diff -- .claude/plans/2026-08-11-detached-reviewer-bridge.md | grep -E '^[-+].*(D1 \(dead|D2 \(`grep -c`|## Standards review|## Auto-resolved decisions)'; echo "exit=$?"
```

Expected: `status --porcelain` lists **only** ` M .claude/plans/2026-08-11-detached-reviewer-bridge.md`
(plus this plan file if it is not yet committed — if so, commit it separately first, or ensure Step 6
stages only the amended plan). Then `1 file changed, 27 insertions(+), 22 deletions(-)`. Then exactly
**seven** hunk headers — two from Task 1, one from Task 2, three from Task 3 (see that task's Step 5 for
why three), one from Task 4:

```
@@ -200,12 +199,0 @@ const GUARD_MESSAGE = "Reviewer jobs must be fresh and read-only.";
@@ -259,7 +247,5 @@ test("a background reviewer run survives its launcher and lands a verbatim durab
@@ -382 +368,6 @@ Run: `git -C "$WORKTREE" diff --stat -- patches/agent-plugins/codex-plugin-cc.pa
@@ -647,0 +639,2 @@ Touch nothing else in the file: the packet lists, reviewer contract, verify-and-
@@ -650,0 +644,6 @@ Expected: no output (exit 1). At this task's starting commit the same grep match
@@ -658 +657,7 @@ Run: `git -C "$WORKTREE" diff --stat -- home/common/claude-code/skills/codex-col
@@ -721 +726 @@ Activation (`just switch`) and the live end-to-end demo are the ship phase's cal
```

Finally the fourth command prints nothing with `exit=1` — no line touching D1, D2,
`## Standards review (Phase 5)`, or `## Auto-resolved decisions` appears in the diff.

> The stat and the seven headers above were measured by applying all four tasks' edits to a scratch copy
> of the base file and diffing it against the original. If your numbers differ, an edit deviated from the
> dictated text — diff your file against the base and reconcile before committing.

- [ ] **Step 6: Commit — one commit, one file**

```bash
cd "$WT"
git add .claude/plans/2026-08-11-detached-reviewer-bridge.md
git commit -m "docs(plans): sync detached-reviewer plan snippets and gates with what shipped

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

Never pass `--no-gpg-sign` or `-c commit.gpgsign=false`. Stage the one path explicitly — no `git add -A`,
no `git commit -a`.

- [ ] **Step 7: Verify — the commit touches exactly one file (AC5)**

```bash
git -C "$WT" show --stat --format= HEAD
git -C "$WT" show --stat --format= HEAD | grep -c '|'
git -C "$WT" log -1 --format='%s%n%b'
```

Expected: exactly one stat line, naming
`.claude/plans/2026-08-11-detached-reviewer-bridge.md`; the count prints `1`; the log shows the
`docs(plans): sync detached-reviewer plan snippets and gates with what shipped` subject and the
`Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` trailer. Do **not** push and do
**not** open a PR.

> `git log --format=%G?` prints `N` for this commit, as it does for every commit in this repo including
> `f99d7b9`, because `gpg.ssh.allowedSignersFile` is unset locally. That is a verification-only
> limitation, not a signing failure. Do not "fix" it.

---

## Acceptance-criteria map

| AC | Criterion (abridged) | Task | Gate that proves it |
| --- | --- | --- | --- |
| AC1 | Task 1 Step 2 has no `waitFor` def/call; `result` is one call whose assertion carries stderr, matching the landed test | Task 1 | Task 1 Step 4 — extracted block `diff`s empty against the patch's `tests/reviewer-detach.test.mjs` hunk (150 lines, exit 0); Step 5 — `grep -n waitFor` returns only the D1 attestation |
| AC2 | Task 1 Step 6 and Task 3 Step 4 no longer claim `--stat` verifies contents; each names a content-level check, `--stat` kept as summary | Tasks 2 and 3 | Task 2 Step 4 — `grep -c "the patch diff includes the new"` → `0`/exit 1, amended step shows the `grep -A5` gate; Task 3 Step 4 — `grep -c 'the hunks touch only the Launch paragraph'` → `0`/exit 1, `grep -c 'diff -U0'` → `1` |
| AC3 | Task 3 Step 4 includes case-insensitive negative greps for `completion notification` and `codex-companion task` against SKILL.md, recorded as passing (exit 1) against the live file | Task 3 | Task 3 Step 4 — both greps present in the step extract (`1` each); Task 3 Step 2 and Task 4 Step 4 — both exit 1 against the live SKILL.md |
| AC4 | The Spec-coverage R6 line's verification claim matches the amended gate list | Task 4 | Task 4 Step 3 — `grep -c "three edits + greps"` → `0`/exit 1, and each of the four gate strings the new line names is found exactly once inside the Task 3 Step 4 extract |
| AC5 | The change touches only `.claude/plans/2026-08-11-detached-reviewer-bridge.md` | Task 4 | Task 4 Step 7 — `git show --stat --format= HEAD \| grep -c '\|'` → `1`, naming that path; Task 4 Step 5 — `git status --porcelain` shows no other modified file |

## Spec coverage

- **S1 (embedded test drifted from the landed test)** → Task 1. Spec D-1: the whole-block resync and the
  `waitFor` removal are the same edit — measured, exactly two differing hunks, 164 → 150 lines.
- **S2a (Task 1 Step 6's `--stat` claims hunk contents)** → Task 2. Spec D-2: `--stat` demoted to a
  labelled file-level summary; a `grep -A5` hunk-header check carries the "new test is in the patch"
  claim; the two guard-message greps already in the step are named as what carries the one-predicate
  claim.
- **S2b (Task 3 Step 4's `--stat` claims which regions changed)** → Task 3. Spec D-3: `--stat` demoted;
  a `-U0` hunk-header listing plus a full-diff read carry the "exactly three regions" claim.
- **S3a (two R6 prohibition greps missing)** → Task 3. Spec D-3: both inserted directly after the sibling
  `background` gate, phrased as exit-status expectations per the plan's own D2 disposition, scoped to the
  two-word `codex-companion task` because the bare word legitimately survives in the pre-flight
  `command -v codex-companion`.
- **S3b (R6 coverage line over-claims)** → Task 4. Spec D-4: the line restated to name exactly the four
  gates that now exist.
- **Spec D-5 (what does not change)** → Global Constraints, plus Task 4 Step 5's explicit gate that no
  diff line touches D1, D2, `## Standards review (Phase 5)`, or `## Auto-resolved decisions`.
