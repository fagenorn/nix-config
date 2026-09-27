# Budgeted Reviewer Self-Collection Guidance Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

Issue: https://github.com/fagenorn/nix-config/issues/24
Spec: `.claude/specs/2026-08-16-codex-collection-budget-design.md` (owns the single decision ledger)

**Goal:** When the Codex companion cannot inline a diff, replace its one unbounded "inspect the diff yourself" sentence with five prescriptive lines that state an 8-file collection budget, order a stat-level survey before per-file diffs, forbid the access patterns that kill the app-server, and require the model to disclose what it did not read.

**Architecture:** The whole behavioural change is the over-cap branch of one module-private function, `buildAdversarialCollectionGuidance` in the patched plugin's `plugins/codex/scripts/lib/git.mjs`. The plugin is vendored into this repo as a zero-context patch against a pinned upstream rev, so the source edit is made in a scratch clone of that rev and the repo receives only the regenerated patch plus a `patchRevision` bump. Coverage is one new test plus one additive assertion in the plugin's existing `tests/git.test.mjs`; the Nix layer is verified by building the plugin derivation and reading the patched source out of the resulting store path.

**Tech stack:** Node.js 22 with `node --test` (no runtime dependencies), git (`git apply --unidiff-zero` / `git diff -U0`), Nix flakes + `just`, GNU patch (`patch -p1`, applied by the Nix builder).

## Global Constraints

- Pinned upstream rev: `db52e28f4d9ded852ab3942cea316258ae4ef346` (`flake.nix:58`). Read-only copy of that exact tree is also available at `/nix/store/7mwnkfz4wk96ibg8si2bnq5idgj2hzq8-source`.
- The patch `patches/agent-plugins/codex-plugin-cc.patch` is **zero-context**. Apply it only with `git apply --unidiff-zero`; plain `git apply` rejects it.
- **Never hand-edit the patch file.** It is produced only by `git diff -U0 <pin>` (acceptance criterion 7).
- **Never `grep` the patch text to assert anything about patched source.** A zero-context patch carries no per-line file attribution, so a patch-wide match cannot tell you which file it sits in. Assertions read the scratch clone or the built store path.
- `patchRevision` in `lib/agent-plugins.nix:6` advances 8 → 9 in the same commit as the regenerated patch. A regenerated patch with an unchanged revision makes the version string (`…-nix.db52e28f.p8`) lie about the tree it names.
- The plugin suite is run **env-scrubbed**: `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`. With the live Claude-session env unscrubbed, 4 upstream tests fail spuriously.
- Nix verification is `just build`, run from the worktree. **Do not run `just switch`.**
- Frozen, not to be touched: `DEFAULT_INLINE_DIFF_MAX_FILES = 2` and `DEFAULT_INLINE_DIFF_MAX_BYTES = 256 * 1024` (`git.mjs:8-9`, acceptance criterion 3), the under-cap guidance string (acceptance criterion 2), `inputMode` semantics, `plugins/codex/prompts/adversarial-review.md`, and every other field of the review context.
- No existing assertion in `tests/git.test.mjs` is modified or removed (per D3 the two asserted phrases survive the rewrite verbatim).
- **Process-snapshot rule:** the patched plugin is only picked up by a `claude` process launched after a switch. Nothing in this plan validates live end-to-end behaviour, and no task may claim it.
- Work only in `/Users/anis/tmp/nix-config/.claude/worktrees/issue-24-a2` on branch `worktree-issue-24-collection-budget`. Never touch `/Users/anis/tmp/nix-config` or the sibling worktrees `codex-review-input-bound` / `issue-21-a2`.
- Scratch work goes in `/private/tmp/claude-502/-Users-anis-tmp-nix-config/80e5143d-5473-4a76-85a4-7ebcb5490145/scratchpad`, never `/tmp`.
- Every commit references the issue as `https://github.com/fagenorn/nix-config/issues/24` (never bare `#24`) and ends with:

  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MqCijYLSasGzMK58HDMWdy
  ```

- Commits are SSH-signed by default. **Never** pass `-c commit.gpgsign=false` or `--no-gpg-sign`; surface a signing failure instead of working around it.
- Do not push.

## Test seams

- **The patched plugin's own `node --test` suite**, run env-scrubbed from the scratch clone root. This is the only behavioural seam; both existing branch tests live in `tests/git.test.mjs`.
- **Hygiene observation around that suite run**: `codex-plugin-test-*` directories under `~/.claude/plugins/data/codex-nix-codex/state/` and surviving `app-server-broker` / `codex app-server` processes. The `pinHermeticStateRoot` machinery in the patched `tests/helpers.mjs` already guarantees cleanliness — this plan *verifies* it, it does not rebuild it.
- **Patch reproducibility**: re-apply the committed patch to a fresh clone of the pin and diff the resulting tree against the scratch clone (per D8).
- **`just build`**, plus a direct build of the `agent-plugins.codex` derivation whose store path is then read (per D9). This is the seam for the Nix layer and the `patchRevision` bump.
- **Not a seam:** a live Codex review against a large branch. Slow, non-deterministic, and gated behind the process-snapshot rule. The spec records it as evidence to collect later, never a gate.

## Task index

- **Task 1 — Budget the over-cap collection guidance and cover it** — scratch clone `plugins/codex/scripts/lib/git.mjs`, scratch clone `tests/git.test.mjs`, repo `patches/agent-plugins/codex-plugin-cc.patch`, repo `lib/agent-plugins.nix` — **full**
- **Task 2 — Verify the Nix layer ships the budgeted guidance** — no file edits; verification gate over `lib/agent-plugins.nix` + `patches/agent-plugins/codex-plugin-cc.patch` as committed by Task 1 — **full**

Task 1 is `full`, not `low-risk`: it changes the instruction text handed to a review model on every over-cap run and it regenerates a release artifact consumed by a Nix build. Task 2 is `full` because its subject is that same release artifact — a green build is not by itself evidence the hunks landed correctly (see D9).

## Decisions

The spec at `.claude/specs/2026-08-16-codex-collection-budget-design.md` owns the single issue-level decision ledger. Rows are cited by ID here and never restated.

- The 8-file budget as an inline literal — **D1**.
- The static (non-parameterised) guidance string — **D2**.
- Preserving *lightweight summary* and *read-only git commands* verbatim, so no existing assertion changes — **D3**.
- The survey step reading the packet's own stat sections rather than instructing a fresh `git diff --stat` — **D4**.
- One new dedicated over-cap test with a behavioural regex set, plus one additive `doesNotMatch` on the existing inline test — **D5**.
- The context-width prohibition and the disclosure clause — **D6**.
- The very-large-single-file prohibition — **D7**.

Planning added three rows to that ledger:

- Verifying the regenerated patch by re-applying it to a fresh clone and diffing trees, never by reading the patch text — **D8**.
- Asserting the shipped guidance by reading the built store path rather than trusting a green `just build` — **D9**.
- Making the AC5 hygiene check a before/after delta rather than an absolute zero — **D10**.

---

### Task 1: Budget the over-cap collection guidance and cover it

**Files:**
- Modify (scratch clone): `$SCRATCH/codex-plugin-cc-p9/plugins/codex/scripts/lib/git.mjs`
- Test (scratch clone): `$SCRATCH/codex-plugin-cc-p9/tests/git.test.mjs`
- Modify (repo): `patches/agent-plugins/codex-plugin-cc.patch` — regenerated, never hand-edited
- Modify (repo): `lib/agent-plugins.nix` — `patchRevision` 8 → 9

where `SCRATCH=/private/tmp/claude-502/-Users-anis-tmp-nix-config/80e5143d-5473-4a76-85a4-7ebcb5490145/scratchpad`.

**Interfaces:**
- Consumes: `buildAdversarialCollectionGuidance(options?: { includeDiff?: boolean }): string` — module-private, declared at `plugins/codex/scripts/lib/git.mjs:292`, called once at `git.mjs:344` as `buildAdversarialCollectionGuidance({ includeDiff })`. Its signature does not change.
- Consumes: `collectReviewContext(cwd: string, target: ReviewTarget, options?): { cwd, repoRoot, branch, target, fileCount, diffBytes, inputMode, collectionGuidance, content, changedFiles, comparison? }` and `resolveReviewTarget(cwd: string, options): ReviewTarget`, both exported from the same module and both already imported at `tests/git.test.mjs:6`.
- Consumes: `makeTempDir(): string`, `initGitRepo(cwd: string): void`, `run(cmd: string, args: string[], opts: { cwd: string }): void` from `tests/helpers.mjs`, already imported at `tests/git.test.mjs:7`.
- Produces: no new export and no new symbol. `context.collectionGuidance` stays a `string`; on the `self-collect` branch it becomes five `"\n"`-joined lines instead of one.

**Invariants:**
- `buildAdversarialCollectionGuidance({ includeDiff: true })` returns exactly `"Use the repository context below as primary evidence."` — byte-identical to p8.
- The `self-collect` return contains the substrings `lightweight summary` and `read-only git commands` verbatim (per D3), so the existing assertions at `tests/git.test.mjs:168-169` pass unedited.
- `DEFAULT_INLINE_DIFF_MAX_FILES` and `DEFAULT_INLINE_DIFF_MAX_BYTES` at `git.mjs:8-9` are unchanged, and so is every threshold decision in `collectReviewContext`.
- Exactly two files change in the plugin tree: `plugins/codex/scripts/lib/git.mjs` and `tests/git.test.mjs`. Both are byte-identical to the pinned upstream at p8, so p9 adds the first hunks against them and there is nothing to reconcile.
- The committed patch, re-applied with `git apply --unidiff-zero` to a fresh clone of the pin, reproduces the scratch clone's tree exactly (per D8).
- No existing test assertion is modified or removed; every edit to `tests/git.test.mjs` is additive.

- [ ] **Step 1: Create the scratch clone at the pinned rev and apply the current patch**

```bash
SCRATCH=/private/tmp/claude-502/-Users-anis-tmp-nix-config/80e5143d-5473-4a76-85a4-7ebcb5490145/scratchpad
REPO=/Users/anis/tmp/nix-config/.claude/worktrees/issue-24-a2
PIN=db52e28f4d9ded852ab3942cea316258ae4ef346

rm -rf "$SCRATCH/codex-plugin-cc-p9"
git clone --quiet https://github.com/openai/codex-plugin-cc.git "$SCRATCH/codex-plugin-cc-p9"
git -C "$SCRATCH/codex-plugin-cc-p9" checkout --quiet "$PIN"
git -C "$SCRATCH/codex-plugin-cc-p9" apply --unidiff-zero "$REPO/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$SCRATCH/codex-plugin-cc-p9" status --short | wc -l
```

Expected: the clone succeeds, `git apply --unidiff-zero` prints nothing and exits 0, and the final count is `29` — the number of files the p8 patch touches.

If the network is unavailable, build the same base offline from the pinned tree instead — it is byte-identical to the rev, and `git diff -U0` output depends only on content, so the regenerated patch is unaffected:

```bash
rm -rf "$SCRATCH/codex-plugin-cc-p9"
mkdir -p "$SCRATCH/codex-plugin-cc-p9"
cp -R /nix/store/7mwnkfz4wk96ibg8si2bnq5idgj2hzq8-source/. "$SCRATCH/codex-plugin-cc-p9/"
chmod -R u+w "$SCRATCH/codex-plugin-cc-p9"
git -C "$SCRATCH/codex-plugin-cc-p9" init --quiet
git -C "$SCRATCH/codex-plugin-cc-p9" add -A
git -C "$SCRATCH/codex-plugin-cc-p9" commit --quiet --no-gpg-sign -m "pinned upstream db52e28f"
git -C "$SCRATCH/codex-plugin-cc-p9" apply --unidiff-zero "$REPO/patches/agent-plugins/codex-plugin-cc.patch"
```

The `--no-gpg-sign` here is on a throwaway scratch repo that is never pushed and never becomes a repo commit; the signing prohibition in Global Constraints applies to commits in the worktree and is not relaxed.
Record which base you used — Step 8's `git diff -U0 <base>` needs the matching base ref (`$PIN` for the clone path, `HEAD` before your edits for the offline path).

- [ ] **Step 2: Confirm the two target files are untouched by p8**

```bash
cd "$SCRATCH/codex-plugin-cc-p9"
git status --short -- plugins/codex/scripts/lib/git.mjs tests/git.test.mjs
grep -n "DEFAULT_INLINE_DIFF_MAX" plugins/codex/scripts/lib/git.mjs
```

Expected: the `git status` line is empty (p8 modifies neither file), and the thresholds read `const DEFAULT_INLINE_DIFF_MAX_FILES = 2;` on line 8 and `const DEFAULT_INLINE_DIFF_MAX_BYTES = 256 * 1024;` on line 9. If either file shows as modified, stop — the assumption this plan rests on is wrong and the hunks would need reconciling.

- [ ] **Step 3: Record the p8 baseline — suite green and hygiene clean**

Snapshot the hygiene state *before* the run (per D10 the criterion is a delta, because sibling agents on this machine may run the same suite concurrently):

```bash
cd "$SCRATCH/codex-plugin-cc-p9"
STATE=~/.claude/plugins/data/codex-nix-codex/state
ls -d "$STATE"/codex-plugin-test-* 2>/dev/null | wc -l   # → before-count
pgrep -fl app-server-broker; pgrep -fl 'codex app-server'  # → before-set

env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
  node --test tests/*.test.mjs 2>&1 | tail -20
```

Expected: the tail shows `# fail 0` with a non-zero `# pass` count. Save the summary lines (`# tests`, `# pass`, `# fail`) — this is the p8 baseline acceptance criterion 4 measures against. Re-run the two hygiene commands afterwards and confirm the count and the process set are unchanged from before-count / before-set.

If `# fail` is non-zero here, the baseline is broken before any edit: check that the `env -u` prefix was actually applied (unscrubbed, 4 upstream tests fail spuriously) before suspecting the patch.

- [ ] **Step 4: Write the failing test**

Insert this new test into `tests/git.test.mjs` immediately after the existing self-collect test, which closes with `});` on line 172 — i.e. in the blank-line gap before `test("collectReviewContext falls back to lightweight context for oversized single-file diffs", …)` on line 174. It reuses that test's fixture shape (three files, one commit, three edits, working-tree mode; per D5 one target mode is sufficient because the guidance does not branch on mode).

```js
test("collectReviewContext budgets self-collection guidance for over-cap adversarial reviews", () => {
  const cwd = makeTempDir();
  initGitRepo(cwd);
  for (const name of ["a.js", "b.js", "c.js"]) {
    fs.writeFileSync(path.join(cwd, name), `export const value = "${name}-v1";\n`);
  }
  run("git", ["add", "a.js", "b.js", "c.js"], { cwd });
  run("git", ["commit", "-m", "init"], { cwd });
  for (const name of ["a.js", "b.js", "c.js"]) {
    fs.writeFileSync(path.join(cwd, name), `export const value = "${name}-v2";\n`);
  }

  const target = resolveReviewTarget(cwd, {});
  const context = collectReviewContext(cwd, target);

  assert.equal(context.inputMode, "self-collect");
  assert.match(context.collectionGuidance, /at most 8 files/i);
  assert.match(context.collectionGuidance, /survey/i);
  assert.match(context.collectionGuidance, /stat/i);
  assert.match(context.collectionGuidance, /never fan out/i);
});
```

In the same edit, add exactly one line to the existing inline-diff test, immediately after `assert.match(context.collectionGuidance, /primary evidence/i);` on line 114. This encodes acceptance criterion 2 — under-cap guidance carries none of the budget language:

```js
  assert.doesNotMatch(context.collectionGuidance, /at most 8 files/i);
```

Change nothing else in the file. Lines 114, 168 and 169 keep their existing assertions verbatim (per D3).

- [ ] **Step 5: Run the test and watch it fail**

```bash
cd "$SCRATCH/codex-plugin-cc-p9"
env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
  node --test --test-name-pattern 'budgets self-collection guidance' tests/git.test.mjs 2>&1 | tail -25
```

Expected: FAIL — `# fail 1`, with an `AssertionError` on `assert.match(context.collectionGuidance, /at most 8 files/i)`; the actual value is the p8 one-sentence string `"The repository context below is a lightweight summary. Inspect the target diff yourself with read-only git commands before finalizing findings."`. The `assert.equal(context.inputMode, "self-collect")` guard above it must pass — if *that* is what fails, the fixture is not landing over the inline cap and the test proves nothing.

This red run **is** the acceptance-criterion-4 proof: the new coverage fails when the budget language is absent from the over-cap branch. Record the failure output.

- [ ] **Step 6: Write the minimal implementation**

In `plugins/codex/scripts/lib/git.mjs`, replace the single `return` statement on line 297 — the over-cap branch of `buildAdversarialCollectionGuidance` — with the array-of-lines form below. The under-cap `return` on line 294 and the `if (options.includeDiff !== false)` guard on line 293 are untouched.

The five strings are dictated verbatim by the spec's *The guidance string, verbatim* section. Copy them exactly: the dash in the third line is an em dash (U+2014), the apostrophe in `user's` is a plain ASCII `'`, and there is no trailing punctuation change anywhere. This code block is reproduced in full because the exact wording is the deliverable — it is what the review model reads.

```js
  return [
    "The repository context below is a lightweight summary, so collect the rest of the evidence yourself with read-only git commands, on a budget.",
    "Survey first: the changed-file list and diff stat included below show what changed; if they do not break the sizes down per file, get that with a single stat-level command before you read any file's diff.",
    "Then take targeted per-file diffs, at default context, for at most 8 files — the largest changes and anything the user's focus area names.",
    "Never take the full diff in one command, never widen the diff context, never fan out across every changed file, and never pull one very large file's diff whole.",
    "If the change is bigger than that budget covers, review what it does cover properly and state in your summary which parts of the change you did not read."
  ].join("\n");
```

Contract this pins: for `inputMode: "self-collect"`, `collectionGuidance` states a numeric file budget, prescribes a stat-level survey before per-file diffs, and forbids a whole-range fan-out; for `inputMode: "inline-diff"` it is byte-identical to p8. `8` stays an inline literal — do **not** introduce a module constant (per D1, a constant beside the two frozen inline thresholds invites conflating three different file counts). Do **not** interpolate `fileCount` or `diffBytes` (per D2).

Add no comment above the return. The strings say what the code does; a comment restating them would be a second copy of prose that has one authoritative source in the spec.

- [ ] **Step 7: Run the full suite and re-check hygiene**

```bash
cd "$SCRATCH/codex-plugin-cc-p9"
env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH \
  node --test tests/*.test.mjs 2>&1 | tail -20
```

Expected: PASS — `# fail 0`, and `# pass` exactly one higher than the Step 3 baseline (the one new test; the added `doesNotMatch` lives inside an existing test and adds no count).

Then, per D10 and acceptance criterion 5:

```bash
STATE=~/.claude/plugins/data/codex-nix-codex/state
ls -d "$STATE"/codex-plugin-test-* 2>/dev/null | wc -l
pgrep -fl app-server-broker; pgrep -fl 'codex app-server'
```

Expected: the count equals Step 3's before-count (ideally `0`), and the process list is unchanged from Step 3's before-set (ideally both `pgrep` calls exit 1 with no output). A *new* `codex-plugin-test-*` directory or a *new* broker/app-server process attributable to this run fails the task — the `pinHermeticStateRoot` machinery in `tests/helpers.mjs` is supposed to prevent exactly that.

- [ ] **Step 8: Regenerate the patch**

```bash
cd "$SCRATCH/codex-plugin-cc-p9"
git diff -U0 db52e28f4d9ded852ab3942cea316258ae4ef346 \
  > /Users/anis/tmp/nix-config/.claude/worktrees/issue-24-a2/patches/agent-plugins/codex-plugin-cc.patch
```

(Offline path from Step 1: use the synthetic base commit's SHA in place of the pin.)

Then confirm the regenerated artifact grew by exactly the two intended files — read the `diff --git` **headers**, which is file attribution, not a content grep of hunk lines:

```bash
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-24-a2
grep '^diff --git' patches/agent-plugins/codex-plugin-cc.patch | wc -l
git diff --stat -- patches/agent-plugins/codex-plugin-cc.patch
```

Expected: `31` header lines (29 at p8 plus `plugins/codex/scripts/lib/git.mjs` and `tests/git.test.mjs`), and a non-empty `git diff --stat` for the patch file. Do not open the patch to check the guidance text — that assertion belongs to Step 9 and Task 2.

- [ ] **Step 9: Prove the committed patch reproduces the scratch tree**

Per D8, the patch's integrity is verified by applying it, not by reading it:

```bash
SCRATCH=/private/tmp/claude-502/-Users-anis-tmp-nix-config/80e5143d-5473-4a76-85a4-7ebcb5490145/scratchpad
REPO=/Users/anis/tmp/nix-config/.claude/worktrees/issue-24-a2

rm -rf "$SCRATCH/codex-plugin-cc-verify"
git clone --quiet https://github.com/openai/codex-plugin-cc.git "$SCRATCH/codex-plugin-cc-verify"
git -C "$SCRATCH/codex-plugin-cc-verify" checkout --quiet db52e28f4d9ded852ab3942cea316258ae4ef346
git -C "$SCRATCH/codex-plugin-cc-verify" apply --unidiff-zero "$REPO/patches/agent-plugins/codex-plugin-cc.patch"

diff -r -x .git "$SCRATCH/codex-plugin-cc-verify" "$SCRATCH/codex-plugin-cc-p9"
```

(Offline path: `cp -R` the pinned store tree into `codex-plugin-cc-verify`, `chmod -R u+w`, `git init && git add -A && git commit --no-gpg-sign`, then apply.)

Expected: `git apply --unidiff-zero` exits 0 silently, and `diff -r` prints nothing and exits 0. Any output means the committed patch does not reconstruct the tree the suite was green against.

- [ ] **Step 10: Bump the patch revision**

In `lib/agent-plugins.nix`, line 6, change `patchRevision = 8;` to `patchRevision = 9;`. Nothing else in that file changes.

```bash
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-24-a2
git diff -- lib/agent-plugins.nix
```

Expected: exactly one changed line, `-  patchRevision = 8;` / `+  patchRevision = 9;`.

- [ ] **Step 11: Commit**

```bash
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-24-a2
git add patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix
git commit -m "$(cat <<'EOF'
fix(codex): budget the reviewer self-collection guidance

The over-cap collection guidance stated no bound of any kind, and the
model obeyed it literally: per-file diffs at widened context fanned out
across the whole range, inside the app-server process that upstream
openai/codex#24048 documents growing unbounded on large tool output
until the OS kills it. The over-cap branch now states an 8-file budget,
orders a stat-level survey before per-file diffs, forbids whole-range
diffs, widened context, fan-out and whole very-large-file diffs, and
requires the model to disclose what the budget left unread.

The under-cap guidance and both inline-diff thresholds are unchanged.
Ships as patch revision p9.

Refs: https://github.com/fagenorn/nix-config/issues/24

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MqCijYLSasGzMK58HDMWdy
EOF
)"
git log --show-signature -1 --format='%h %G? %s' | head -3
```

Expected: the commit succeeds and `%G?` reports a good signature (`G`). If signing fails, stop and surface the failure — do not retry with signing disabled.

**Acceptance criteria for Task 1:**
1. The over-cap branch of `buildAdversarialCollectionGuidance` returns the five spec lines joined with `"\n"`, byte-for-byte as written in Step 6 (acceptance criterion 1).
2. The under-cap branch returns `"Use the repository context below as primary evidence."` unchanged, and the new inline-test `doesNotMatch` proves the budget language is absent there (acceptance criterion 2).
3. `git.mjs:8-9` thresholds unchanged (acceptance criterion 3).
4. The env-scrubbed suite is green with `# pass` exactly one above the recorded p8 baseline, and the Step 5 red run is recorded as proof the new coverage fails without the budget language (acceptance criterion 4).
5. Hygiene delta is zero on both dimensions (acceptance criterion 5).
6. `patchRevision` reads `9` (part of acceptance criterion 6; the build itself is Task 2).
7. The patch was produced solely by `git diff -U0` and reproduces the scratch tree when re-applied (acceptance criterion 7).

---

### Task 2: Verify the Nix layer ships the budgeted guidance

**Files:**
- No file edits. This task is a verification gate over `lib/agent-plugins.nix` and `patches/agent-plugins/codex-plugin-cc.patch` as committed by Task 1. It produces a commit only if a gate fails and a fix is required.

**Interfaces:**
- Consumes: `import ./lib/agent-plugins.nix { inherit inputs; inherit pkgs; }` → an attrset whose `codex` attribute is the patched-plugin derivation, named `codex-plugin-cc-${codexUpstreamVersion}-nix.${shortRevision}.p${patchRevision}`. `home/common/claude-code/default.nix:9` is its only consumer in the repo.
- Produces: nothing consumed by a later task. This is the terminal gate.

**Invariants:**
- The Nix builder applies the patch with GNU `patch -p1`, not `git apply`. `patch -p1` accepts a zero-context patch at lenient offsets **without error**, so a successful build is not by itself evidence that the hunks landed in the right place — the shipped source must be read (per D9).
- The built store path's name ends in `.p9`.
- `plugins/codex/scripts/lib/git.mjs` inside the store path contains the budget line; `tests/git.test.mjs` inside it contains the new test.
- No `just switch`, no live Codex review, no claim that a running `claude` process picked the change up (process-snapshot rule).

- [ ] **Step 1: Build the patched plugin derivation directly and read its source**

```bash
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-24-a2
STORE=$(nix --extra-experimental-features 'nix-command flakes' build --no-link --print-out-paths --impure \
  --expr 'let f = builtins.getFlake (toString ./.);
              pkgs = f.inputs.nixpkgs-darwin.legacyPackages.aarch64-darwin;
          in (import ./lib/agent-plugins.nix { inherit (f) inputs; inherit pkgs; }).codex')
echo "$STORE"
grep -c "at most 8 files" "$STORE/plugins/codex/scripts/lib/git.mjs"
grep -c "never fan out" "$STORE/plugins/codex/scripts/lib/git.mjs"
grep -c "budgets self-collection guidance" "$STORE/tests/git.test.mjs"
grep -n "DEFAULT_INLINE_DIFF_MAX" "$STORE/plugins/codex/scripts/lib/git.mjs"
```

Expected: `$STORE` ends in `-codex-plugin-cc-1.0.6-nix.db52e28f.p9`; the three `grep -c` calls print `1`, `1`, `1`; and the thresholds still read `= 2;` and `= 256 * 1024;`. These greps read the **built store path**, which is the sanctioned way to assert about patched source — never grep the patch file for this.

A store path still ending in `.p8` means the `patchRevision` bump did not land. A build failure with `Hunk #N FAILED` means the regenerated patch does not apply under `patch -p1`; re-do Task 1 Steps 8–9 rather than editing the patch by hand.

- [ ] **Step 2: Run the repo's own build gate**

```bash
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-24-a2
just build 2>&1 | tail -15
```

Expected: the build completes without error. Do **not** run `just switch`.

- [ ] **Step 3: Confirm the branch touched only what the plan owns**

```bash
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-24-a2
git diff --stat origin/main..HEAD -- lib/agent-plugins.nix patches/agent-plugins/codex-plugin-cc.patch
git diff --stat origin/main..HEAD -- plugins/ home/ hosts/ flake.nix flake.lock
```

Expected: the first command lists both files with non-zero changes; the second prints nothing. In particular `flake.lock` must be untouched — the pin does not move for this change.

**Acceptance criteria for Task 2:**
1. The built store path is named `…p9` and its `plugins/codex/scripts/lib/git.mjs` carries the budgeted guidance while its `git.mjs:8-9` thresholds are unchanged (acceptance criteria 1, 3, 6).
2. Its `tests/git.test.mjs` carries the new over-cap test (acceptance criterion 4 shipped, not just present in the scratch clone).
3. `just build` succeeds (acceptance criterion 6).
4. The branch changes only `lib/agent-plugins.nix`, `patches/agent-plugins/codex-plugin-cc.patch`, and the plan/spec artifacts; `flake.lock` is untouched.
5. No `just switch` was run and no live-behaviour claim is made — the change is inert until a `claude` process is launched after a switch.

## Standards review corrections (binding on execution)

The Codex plan review found the gates below under-specified. These corrections override the
command blocks written above wherever they conflict; apply them as part of the task they name.

- **Every gate asserts its producing command's exit status (per D11).** The blocks above pipe
  `node --test` and `just build` into `tail`, which in zsh discards the producer's status. Run each
  success gate under `set -o pipefail`, or capture `${PIPESTATUS[1]}` / `$pipestatus[1]`, and fail
  the step on non-zero. For the expected-red run in Task 1 Step 5, assert the status is **non-zero**
  and that the failure is the new assertion — a red for any other reason is not the gate passing.
  Turn the store-path, `diff --git` header-count, threshold, and `patchRevision` expectations into
  commands that exit non-zero on mismatch rather than printing a number for a human to compare.
- **Assert the under-cap string by equality (per D12).** In addition to the planned
  `assert.doesNotMatch(..., /at most 8 files/i)`, add
  `assert.strictEqual(context.collectionGuidance, "Use the repository context below as primary evidence.");`
  to the existing inline-diff test. Both additions are additive; line 114's existing
  `/primary evidence/i` assertion and lines 168-169 stay verbatim (per D3).
- **Hygiene and scope compare identity sets, not counts (per D13).** Snapshot the exact
  `codex-plugin-test-*` directory names and the broker / `codex app-server` PID sets immediately
  before *and* immediately after each full-suite run — including the final one, which must not be
  compared against the stale p8-baseline snapshot — and diff the sets. Any delta this run cannot be
  shown to have caused is investigated, not averaged away. For the terminal branch audit, enumerate
  **all** changed paths against the fixed base SHA `969f357bf019ba0eeab6bb9fd4a2c00beba9c744` (not
  the mutable `origin/main`, which sibling agents may advance) and compare them against an explicit
  whitelist: `plugins/codex/scripts/lib/git.mjs`, `tests/git.test.mjs`,
  `patches/agent-plugins/codex-plugin-cc.patch`, `lib/agent-plugins.nix`, and this branch's spec and
  plan files. Also confirm no uncommitted files remain.

## Standards review provenance

- **Reviewer:** Codex, isolated read-only runtime (fresh `CODEX_HOME`, approval policy `never`,
  sandbox `read-only`), via the `codex-collaboration` `plan-review` operation. No native fallback.
- **Base SHA:** `969f357bf019ba0eeab6bb9fd4a2c00beba9c744`; plan reviewed at HEAD `3a0f8fa`.
- **Configured focus:** none.
- **Dispositions:** 5 findings, 5 accepted, 0 rejected, 0 deferred. Blocking B-01 (guidance claimed
  per-file sizes the working-tree packet does not carry) and B-02 (piped gates masked failing exit
  status); should-fix S-01 (under-cap equality), S-02 (hygiene snapshot bracketing), S-03 (scope
  audit breadth). Each was re-verified against live source before being applied: B-01 against
  `git.mjs:242-249` versus `:264`, the rest against the plan text cited. Logged as spec ledger rows
  D11-D13, with D4 revised to match the corrected guidance.
- The reviewer could not refresh the live issue (`gh` had no network); the supplied issue body was
  used. That affects no finding — the acceptance criteria were supplied verbatim in the packet.
