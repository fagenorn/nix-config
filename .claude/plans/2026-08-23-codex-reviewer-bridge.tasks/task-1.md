# Task 1: Reviewer Operation Registry, Per-Operation Budget, Transport Wait Ceiling

**Files:**
- Modify: `patches/agent-plugins/codex-plugin-cc.patch` (regenerated once, not hand-edited)
- Modify: `lib/agent-plugins.nix` (`patchRevision` 10 → 11)
- Scratch source captured by the regenerated patch — Create: `plugins/codex/scripts/lib/review-operations.mjs`
- Scratch source captured by the regenerated patch — Modify: `plugins/codex/scripts/codex-companion.mjs`
- Scratch source captured by the regenerated patch — Modify: `plugins/codex/agents/codex-reviewer.md`
- Scratch tests captured by the regenerated patch — Modify: `tests/reviewer-detach.test.mjs`
- Scratch tests captured by the regenerated patch — Modify: `tests/worker-postmortem.test.mjs`
- Scratch tests captured by the regenerated patch — Modify: `tests/commands.test.mjs`

Six scratch files move inside the patch (per D12). Everything else this issue touches is repo-owned and belongs to Tasks 2 and 3.

**Interfaces:**
- Consumes (existing, unchanged): `handleTask`'s reviewer branch in `codex-companion.mjs` (`normalizeReviewOperation(options.reviewer)` at ~L850, the `timeoutMs` default at ~L854, `buildTaskRequest`/`enqueueBackgroundTask`); `resolveJobDeadline(createdAt, timeoutMs)` (~L710) and `MAX_ENFORCEABLE_TIMEOUT_MS` (~L76); `upsertJob` in `scripts/lib/state.mjs`, which merges `{...existing, ...patch}` so `request` and `deadlineAt` survive every later status write; test helpers `installFakeCodex(binDir, behavior)` / `buildEnv(binDir)` (`tests/fake-codex-fixture.mjs`), `makeTempDir` / `run` / `pinHermeticStateRoot` (`tests/helpers.mjs`), and `read(relativePath)` in `tests/commands.test.mjs`.
- Produces (new module `plugins/codex/scripts/lib/review-operations.mjs`):
  - `export const REVIEWER_BUDGETS_MS` — a `Map<string, number>` with exactly the entries `"plan-review" → 1680000` and `"diff-review" → 840000`.
  - `export const REVIEW_OPERATIONS` — `new Set(REVIEWER_BUDGETS_MS.keys())`, replacing the entrypoint's own `const REVIEW_OPERATIONS` (~L1112).
  - `export function reviewerBudgetMs(operation)` — returns the registered budget, throws `` `No reviewer budget is registered for ${operation}.` `` when the key is absent.
- Produces (behavioral): a background `--reviewer plan-review` enqueue stores `request.timeoutMs === 1680000` and `deadlineAt === createdAt + 1680000`; `--reviewer diff-review` stores `840000` and the matching deadline; `--timeout-ms` still overrides both; a non-reviewer task still stores `timeoutMs: null`.
- Produces (transport contract): `agents/codex-reviewer.md` states `Wait with at most four foreground calls` and reports exhaustion as `after 2160s of bounded waits`, with no worker-side budget claim anywhere in the file.

**Invariants:**
- `REVIEW_OPERATIONS` is derived from the registry's keys and never written independently: an operation cannot exist without a budget, and a budget cannot exist for an operation the runtime rejects (per D1). Existing `REVIEW_OPERATIONS.has(...)` call sites (~L577, ~L1120, ~L1128) keep working unchanged because the exported value is still a `Set`.
- A `Map` is used rather than a plain object so a lookup of an inherited property name (`"toString"`, `"constructor"`) cannot resolve to a non-`undefined` value and impersonate a registered operation.
- The transport's ceiling covers the largest registered budget: wait count × per-call bound (4 × 540 000 ms = 2 160 000 ms) strictly exceeds 1 680 000 ms. This relation is a test, not a remembered convention (per D3, D11).
- `540000` (the per-call wait bound) and `600000` (the Bash tool cap) are unchanged; only the number of wait calls changes (per D3).
- The agent definition's wait count stays one machine-readable phrase — `Wait with at most four foreground calls` — matching the closed word→number table the invariant test carries (per D13).
- No behavior change for `--timeout-ms`, for non-reviewer tasks, or for any job already enqueued: each record carries the budget it was enqueued with, so in-flight jobs terminate normally and there is no migration (per D1).
- The regenerated patch is a deterministic zero-context diff from the pinned revision, and `patchRevision` ends at `11`.

Cites: D1, D2, D3, D9, D10, D11, D12, D13.

- [ ] **Step 1: Re-check `patchRevision` against the integration branch before anything else** (per D10)

```bash
WORKTREE_ROOT="$PWD"
BASE_SHA=a3e13184274507e7c7f7623a3773df752af39678
git fetch origin main
git diff --stat "$BASE_SHA" origin/main -- patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix
```

Expected: **no output** — `main` has not advanced either file since this branch's base, so the bump 10→11 is uncontested. If either file shows, STOP and reconcile per D10: apply each side's patch to its own scratch clone, three-way merge the *source trees*, regenerate — never merge the patch text, and never rely on git to surface the collision (an identical revision bump on both sides hides it from the conflict list entirely).

- [ ] **Step 2: Create the one scratch clone and apply the patch**

```bash
PLUGIN_PIN=db52e28f4d9ded852ab3942cea316258ae4ef346
PLUGIN_SCRATCH=$(mktemp -d)
gh repo clone openai/codex-plugin-cc "$PLUGIN_SCRATCH"
git -C "$PLUGIN_SCRATCH" checkout "$PLUGIN_PIN"
git -C "$PLUGIN_SCRATCH" apply --unidiff-zero "$WORKTREE_ROOT/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$PLUGIN_SCRATCH" add -N .
```

Expected: `git apply` exits 0 silently. Plain `git apply` (without `--unidiff-zero`) would reject this patch — the patch is zero-context. Keep `$PLUGIN_SCRATCH` and `$WORKTREE_ROOT` in scope for every remaining step; this is the only scratch clone this task creates.

- [ ] **Step 3: Write the failing tests in the scratch clone**

In `tests/reviewer-detach.test.mjs`, add the registry import beside the existing `state.mjs` import (~L10):

```js
import { REVIEWER_BUDGETS_MS } from "../plugins/codex/scripts/lib/review-operations.mjs";
```

and inside the existing `for (const operation of ["plan-review", "diff-review"])` background-success loop, immediately after `assert.equal(result.storedJob.request.reviewOperation, operation);`:

```js
    // The budget the worker actually races against, read off the durable record
    // rather than off the constant: a registry the value never reaches is not a
    // budget. `upsertJob` merges, so the enqueued request survives to here.
    assert.equal(result.storedJob.request.timeoutMs, REVIEWER_BUDGETS_MS.get(operation));
```

In `tests/worker-postmortem.test.mjs`, add the same import beside the existing imports, then replace the flat literal inside the `for (const operation of ["plan-review", "diff-review"])` loop of the test `"a background enqueue stamps deadlineAt from the record's own createdAt"`:

```js
    // The reviewer default budget for this operation, exactly: enqueue time plus
    // the registered budget. Basing the deadline on the record's own createdAt is
    // what makes this an exact delta rather than a fuzzy window.
    assert.equal(
      Date.parse(reviewerRecord.deadlineAt) - Date.parse(reviewerRecord.createdAt),
      REVIEWER_BUDGETS_MS.get(operation)
    );
```

Leave that test's two non-reviewer cases (`--timeout-ms 60000` → 60000, untimed → `request.timeoutMs` null) exactly as they are.

In `tests/commands.test.mjs`, add at the top, after the existing imports:

```js
import { REVIEWER_BUDGETS_MS } from "../plugins/codex/scripts/lib/review-operations.mjs";

// The definition spells its wait count, like every other quantity in that
// Sonnet-facing file. A closed table keeps an unrecognised word a loud failure
// instead of a silently unparsed one (D13).
const WAIT_COUNT_WORDS = new Map([
  ["one", 1], ["two", 2], ["three", 3], ["four", 4], ["five", 5], ["six", 6]
]);
```

then, inside the existing test `"the reviewer bridge validates and forwards one explicit operation envelope"`, add after the `--wait --timeout-ms 540000` assertion:

```js
  // The transport's own numbers stay; the wait count and the ceiling it measures
  // are pinned here so the invariant test below has a stable subject.
  assert.match(agent, /Wait with at most four foreground calls/);
  assert.match(agent, /after 2160s of bounded waits/);
  // What the transport may never carry again is a worker-side budget claim or
  // the retired constant. This is precise about its subject: 540000, 600000 and
  // 2160 are the transport's own measurements and stay legal.
  assert.doesNotMatch(agent, /worker(?:'s)?[^.\n]*budget/i);
  assert.doesNotMatch(agent, /\b840\b/);
```

and add this as a new top-level test in the same file, directly after that one:

```js
test("the transport's bounded-wait ceiling still covers the slowest reviewer budget", () => {
  const agent = read("agents/codex-reviewer.md");
  const countWord = agent.match(/Wait with at most (\w+) foreground calls/)?.[1];
  assert.ok(WAIT_COUNT_WORDS.has(countWord), `unrecognised wait count: ${countWord}`);
  const perCallMs = Number(agent.match(/--wait --timeout-ms (\d+)/)?.[1]);
  assert.ok(Number.isFinite(perCallMs) && perCallMs > 0, "no per-call wait bound in the definition");
  const ceilingMs = WAIT_COUNT_WORDS.get(countWord) * perCallMs;
  const largestBudgetMs = Math.max(...REVIEWER_BUDGETS_MS.values());
  // The enforced half of `ceiling > startup + budget`: startup is measured in
  // seconds and is not a constant, so the test pins the part that is one.
  assert.ok(
    ceilingMs > largestBudgetMs,
    `bounded-wait ceiling ${ceilingMs}ms must exceed the largest reviewer budget ${largestBudgetMs}ms`
  );
});
```

- [ ] **Step 4: Run the suite in the scratch clone and watch it fail**

```bash
cd "$PLUGIN_SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID \
  -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs
```

Expected: FAIL. `tests/commands.test.mjs`, `tests/reviewer-detach.test.mjs` and `tests/worker-postmortem.test.mjs` all fail to load — `Cannot find module .../scripts/lib/review-operations.mjs`. Scrubbing those three variables is mandatory; with the live Claude-session environment intact, four unrelated upstream tests fail spuriously.

- [ ] **Step 5: Create the registry module**

Create `plugins/codex/scripts/lib/review-operations.mjs` in the scratch clone. Full code, because the derivation of the closed set from the keys is the decision this module exists to make structural (per D1, D11):

```js
// The reviewer operation registry: the single place that says which review
// operations exist and what each one may spend. The closed set below is derived
// from these keys, so an operation cannot exist without a budget and a budget
// cannot exist for an operation the runtime rejects.
//
// plan-review carries twice diff-review's wall. The evidence is asymmetric
// truncation, not a measured speed gap: across 83 surveyed reviewer jobs the
// shared 840 s wall killed ten plan-reviews against one diff-review, and
// plan-review's p90 sat at 730 s hard against that wall — the signature of a
// right-censored distribution whose observed median understates the honest one.
// A Map rather than an object so a
// lookup of an inherited property name cannot resolve to something non-undefined
// and impersonate a registered operation.
export const REVIEWER_BUDGETS_MS = new Map([
  ["plan-review", 1680000],
  ["diff-review", 840000]
]);

export const REVIEW_OPERATIONS = new Set(REVIEWER_BUDGETS_MS.keys());

export function reviewerBudgetMs(operation) {
  const budget = REVIEWER_BUDGETS_MS.get(operation);
  if (budget === undefined) {
    throw new Error(`No reviewer budget is registered for ${operation}.`);
  }
  return budget;
}
```

- [ ] **Step 6: Rewire the entrypoint to the registry**

In `plugins/codex/scripts/codex-companion.mjs`, three edits and nothing else:

1. Add to the import block, beside the other `./lib/*.mjs` imports:
   `import { REVIEW_OPERATIONS, reviewerBudgetMs } from "./lib/review-operations.mjs";`
2. Delete the local `const REVIEW_OPERATIONS = new Set(["plan-review", "diff-review"]);` (~L1112). Leave `STORED_REVIEW_OPERATION_ERROR`, `STORED_REVIEW_IDENTITY_ERROR` and `normalizeReviewOperation` where they are — the diagnostics are CLI-facing and belong to the entrypoint.
3. Replace the reviewer default at ~L854 so the budget comes from the registry:

```js
  const timeoutMs = options["timeout-ms"] == null
    ? (isReviewer ? reviewerBudgetMs(reviewOperation) : null)
    : Number(options["timeout-ms"]);
```

`reviewOperation` is non-null whenever `isReviewer` is true (both derive from the same `normalizeReviewOperation` call one line above), so `reviewerBudgetMs` never sees `null` on this path. Leave the `Number.isFinite(timeoutMs) && timeoutMs > 0` guard below it untouched.

- [ ] **Step 7: Rewrite the transport agent definition** (per D3, D13)

In `plugins/codex/agents/codex-reviewer.md`, four bullet-level edits. Keep every other line, the frontmatter (`model: sonnet`, `tools: Bash, Read`) and the per-call `--timeout-ms 540000` exactly as they are.

1. In the opening bullet, replace `the two wait calls set the Bash tool's` with `each wait call sets the Bash tool's` — the wait count then lives in exactly one place.
2. In the enqueue bullet, replace `a detached worker owns the review with its own 840 s budget; nothing` with `a detached worker owns the review; nothing`.
3. Replace the wait bullet's opening line and drop its closing sentence, so the bullet reads:

```markdown
- Wait with at most four foreground calls, run one after the other only while the
  job is still `queued` or `running`:
  `cd "<worktree-root>" && codex-companion status <jobId> --wait --timeout-ms 540000 --json`
  — each with the Bash tool's `timeout` parameter set to 600000. Read
  `job.status` from the printed JSON (the command exits 0 either way). Stop as
  soon as the status leaves `queued`/`running`: four is a ceiling, not a sequence
  to complete.
```

4. Replace the exhaustion bullet so it reports only what the transport itself measured:

```markdown
- If the job is still `queued` or `running` after the last wait, return one line:
  `CODEX_REVIEW_FAILURE: job <jobId> still <status> after 2160s of bounded waits;
  check codex-companion status <jobId>`. Do not cancel the job — the worker's own
  timeout is the correctness bound.
```

After these four edits the file contains no `840` and no worker-side budget claim, which is exactly what Step 3's negative assertions pin.

- [ ] **Step 8: Run the full suite in the scratch clone**

```bash
cd "$PLUGIN_SCRATCH" && env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID \
  -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs
```

Expected: PASS — every test file, no failures. A run that leaves `codex-plugin-test-*` directories under `~/.claude/plugins/data/codex-nix-codex/state/`, or a surviving `app-server-broker` / `codex app-server` process, means the scrubbing was skipped; re-run with the variables unset.

- [ ] **Step 9: Regenerate the patch and bump the revision — once**

```bash
git -C "$PLUGIN_SCRATCH" add -A
git -C "$PLUGIN_SCRATCH" diff -U0 "$PLUGIN_PIN" > "$WORKTREE_ROOT/patches/agent-plugins/codex-plugin-cc.patch"
```

Then edit `lib/agent-plugins.nix`: `patchRevision = 10;` → `patchRevision = 11;`. Confirm the regenerated patch still declares the file set the build expects — file-level metadata only, never per-line matching:

```bash
grep -c '^diff --git' patches/agent-plugins/codex-plugin-cc.patch
```

Expected: `33` — the 32 files the patch carried before, plus `plugins/codex/scripts/lib/review-operations.mjs`.

- [ ] **Step 10: Build and verify from the built store path** (never from the patch text)

```bash
just build
set -- $(nix-store --query --requisites ./result | grep -- '-codex-plugin-cc-.*\.p11$')
if [ "$#" -ne 1 ]; then echo "expected exactly one p11 plugin store path; found $#" >&2; exit 1; fi
PLUGIN_STORE="$1"
node -e 'import(process.argv[1]).then((m) => {
  const actual = JSON.stringify([...m.REVIEWER_BUDGETS_MS].sort());
  const expected = JSON.stringify([["diff-review", 840000], ["plan-review", 1680000]]);
  if (actual !== expected) {
    console.error(`built registry is ${actual}, expected ${expected}`);
    process.exit(1);
  }
  console.log(actual);
})' "$PLUGIN_STORE/plugins/codex/scripts/lib/review-operations.mjs"
grep -q 'Wait with at most four foreground calls' "$PLUGIN_STORE/plugins/codex/agents/codex-reviewer.md" || exit 1
if grep -q '840' "$PLUGIN_STORE/plugins/codex/agents/codex-reviewer.md"; then
  echo "the transport definition still names a retired budget constant" >&2; exit 1
fi
grep -q 'patchRevision = 11;' lib/agent-plugins.nix || exit 1
```

Expected: `just build` succeeds; the discovery finds exactly one `.p11` path; the `node -e` line prints exactly `[["plan-review",1680000],["diff-review",840000]]`; both `grep -q` presence checks pass and the prohibition check does not fire.

- [ ] **Step 11: Commit**

```bash
git add patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix
git commit -m "$(cat <<'MSG'
feat(agent-plugins): size the reviewer budget per operation and cover it from the transport

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Verification (falsifiable):** at this task's starting commit, `nix-store --query --requisites ./result | grep -c -- '-codex-plugin-cc-.*\.p11$'` finds zero paths (the closure carries `.p10`), and `grep -c 'at most two foreground calls' <p10-store>/plugins/codex/agents/codex-reviewer.md` is 1 while `at most four` is absent — so Step 10's discovery and both presence greps fail at base and can only pass after this task lands. Independently, Step 4's suite run fails at base on a missing module. Scope every diff inspection to this task's own files (`git diff --stat "$BASE_SHA"..HEAD -- patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix`); never grade the whole commit range, which also carries the spec and plan commits.
