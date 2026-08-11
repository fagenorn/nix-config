# Detached Reviewer Bridge Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Reviewer plan-reviews run as the runtime's own detached background workers (`codex-companion task --fresh --reviewer --background` enqueues instead of throwing), the `codex:codex-reviewer` bridge agent becomes a fixed sequence of bounded foreground calls (enqueue → at most two 540 s waits → verbatim collect), and the codex-collaboration skill states only the contract — delivered as a regenerated `patches/agent-plugins/codex-plugin-cc.patch` at `patchRevision = 5` plus three surgical edits to the skill text.

**Architecture:** The runtime diff is one predicate: `handleTask`'s reviewer guard drops its `options.background` arm, so reviewer jobs flow into the existing, issue-#2-hardened background path (`buildTaskJob` → `buildTaskRequest` → `enqueueBackgroundTask` → `spawnDetachedTaskWorker`) with zero changes to any of those functions. All plugin changes live in a scratch clone of `openai/codex-plugin-cc` at pinned revision `db52e28f4d9ded852ab3942cea316258ae4ef346` and land in this repo only as the regenerated zero-context patch. The bridge agent definition (`plugins/codex/agents/codex-reviewer.md`) is fully rewritten to the spec's binding body; the skill file `home/common/claude-code/skills/codex-collaboration/SKILL.md` is edited in the worktree directly. Design authority: `.claude/specs/2026-08-11-detached-reviewer-bridge-design.md` — this plan implements it, it does not redesign it.

**Tech stack:** Node.js ≥ 22 ESM (`.mjs`, stdlib only), `node --test` runner, git-generated unified diff patch, Nix (`just build` applies the patch via `patch -p1` inside `lib/agent-plugins.nix`).

## Global Constraints

- Pinned upstream revision: `db52e28f4d9ded852ab3942cea316258ae4ef346` (`openai/codex-plugin-cc`); the flake input never changes.
- The patch file `patches/agent-plugins/codex-plugin-cc.patch` is the only plugin-code artifact; never commit the scratch checkout; never edit anything under `/nix/store` (read-only).
- `patchRevision` in `lib/agent-plugins.nix` goes `4` → `5` exactly once (Task 1), never higher.
- The committed patch is zero-context; regenerate with `git diff -U0 <pinned-rev>` and apply with `git apply --unidiff-zero` (plain `git apply` fails on zero-context hunks; nix's `patch -p1` handles them by line number).
- New guard predicate, exact: `if (reviewer && (write || resumeLast))`. New guard message, exact: `Reviewer jobs must be fresh and read-only.` (trailing period included). The old message `Reviewer jobs must be fresh, foreground, and read-only.` must not survive anywhere in the patched tree.
- The runtime change is the guard predicate only. No changes to `enqueueBackgroundTask`, `spawnDetachedTaskWorker`, `handleTaskWorker`, `status`, `result`, `cancel`, the state/liveness machinery, `printUsage`, or the SessionEnd hook (session-end reap of this session's jobs stays — AC4 is a launcher/turn-end guarantee, a documented boundary in the spec).
- Foreground reviewer runs remain allowed; the p4 tests `reviewer tasks run foreground in a fresh read-only runtime and clean it up` and `parallel reviewers in one worktree receive distinct mutable runtimes` (`tests/runtime.test.mjs`) must stay green unchanged.
- The bridge agent definition body (Task 2) is the spec's binding text, copied byte-for-byte from this plan; the prescribed calls and bounds may not be altered. Frontmatter is unchanged (`model: sonnet`, `tools: Bash, Read`). The bridge omits `--timeout-ms` on the enqueue — the runtime's reviewer default (840 000 ms) rides the stored request.
- Canonical test command (from the scratch checkout root; the `env -u` scrub removes this repo's live Claude-session variables which otherwise fail 4 upstream tests spuriously):
  `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
  Baseline at patch p4 (verified 2026-08-11, node v22.22.2): `# tests 102 / # pass 98 / # fail 0 / # skipped 4`.
- `just build` (run in the worktree) is the repo verification step; it must end green in every task.
- Worktree: `/Users/anis/tmp/nix-config/.claude/worktrees/issue-3-detached-reviewer-bridge` (branch `worktree-issue-3-detached-reviewer-bridge`, base `cafcf6f`). Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- The AC8 live demo (a real plan-review through the skill against the activated build) is the ship phase's call — it requires `just switch`. This plan's gates stop at the suite, `just build`, and the patched-closure content checks. Evidence home fixed by this plan: `.claude/specs/2026-08-11-detached-reviewer-bridge-evidence.md` (see Ship-phase note).

## Scratch checkout workflow (used by Tasks 1–2)

The scratch checkout lives at a fixed path outside the repo and is rebuilt deterministically at the start of every task from the currently committed patch, so tasks are independent and a half-edited scratch tree can never leak between implementers:

```bash
WORKTREE=/Users/anis/tmp/nix-config/.claude/worktrees/issue-3-detached-reviewer-bridge
SCRATCH=/tmp/codex-plugin-cc-issue-3-scratch
PIN=db52e28f4d9ded852ab3942cea316258ae4ef346

if [ ! -d "$SCRATCH/.git" ]; then
  gh repo clone openai/codex-plugin-cc "$SCRATCH"
fi
git -C "$SCRATCH" reset --hard
git -C "$SCRATCH" checkout --force --detach "$PIN"
git -C "$SCRATCH" clean -ffd
test -z "$(git -C "$SCRATCH" status --porcelain)"   # must print nothing / exit 0
git -C "$SCRATCH" apply --unidiff-zero "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$SCRATCH" add -N .
```

Regeneration (end of Tasks 1–2, after tests are green — `add -N` first so files created since setup, e.g. `tests/reviewer-detach.test.mjs`, appear in the diff):

```bash
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" > "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
```

## File structure

Scratch checkout (all paths relative to `$SCRATCH`):

- `plugins/codex/scripts/codex-companion.mjs` — the reviewer guard in `handleTask` (currently lines 796–798) loses its `options.background` arm and gets the reworded message (Task 1). The only runtime edit in this issue.
- `plugins/codex/agents/codex-reviewer.md` — body below the frontmatter fully replaced with the bounded-foreground transport sequence (Task 2).
- `tests/reviewer-detach.test.mjs` — new behavior-named test file: detached survival + verbatim durable result, both surviving guard refusals, worker-internal timeout on the background path (Task 1).
- `tests/commands.test.mjs` — one new docs-contract test pinning the agent definition's prescribed calls and bounds (Task 2).

Repo worktree:

- `patches/agent-plugins/codex-plugin-cc.patch` — regenerated in Tasks 1–2.
- `lib/agent-plugins.nix` — `patchRevision = 4` → `5` (Task 1 only).
- `home/common/claude-code/skills/codex-collaboration/SKILL.md` — three spec'd edits: Launch ¶2 → contract, failure classes 4→3, diff-review paragraph drops its mechanics clause (Task 3).

## Test seams

Inherited from the spec — implementers test at these and nowhere else:

1. **CLI subprocess surface:** `node <SCRIPT> task|status|result … --json` run as child processes against a temp workspace with the fake codex on PATH (`installFakeCodex(binDir, <behavior>)`, `buildEnv(binDir)` from `tests/fake-codex-fixture.mjs`).
2. **On-disk state contract:** job record JSON, job logs, and reviewer runtime directories located via the exported resolvers (`resolveStateDir`/`resolveJobFile` from `lib/state.mjs`, `resolveReviewerRuntimeHome` from `lib/runtime-home.mjs`), plus the fake codex's own state file (`fake-codex-state.json`) for what the runtime told Codex (sandbox, `CODEX_HOME`).
3. **Narrow docs seam** (`tests/commands.test.mjs` precedent, e.g. `internal docs use task terminology for rescue runs`): text assertions over `plugins/codex/agents/codex-reviewer.md`, because AC3 is a claim about that file's contents.

No stopwatch assertions, no call-count assertions, no process-tree/`ppid` assertions: every assertion is a printed payload, an on-disk record, a directory's existence, or the doc file's text. Dead-worker fast-fail, `--wait` prompt termination, and flip-path runtime cleanup are already pinned by `tests/liveness.test.mjs` and are not re-tested.

## Auto-resolved decisions

### Task granularity: three tasks along artifact boundaries
- **Question:** One task for the whole change, or several — and along which boundary?
- **Choice:** Three tasks: (1) guard lift + `tests/reviewer-detach.test.mjs` + patchRevision bump, (2) bridge agent definition rewrite + its docs-contract test, (3) the three SKILL.md edits + final whole-issue verification. Each ends in a green suite (Tasks 1–2), a green `just build`, and one worktree commit.
- **Grounding:** writing-plans right-sizing — a reviewer can reject the agent-def text or the skill edits while approving the guard lift; the slices map to distinct acceptance criteria (AC1/AC2/AC7 · AC3/AC7 · AC6/AC8-prep). Precedent: the issue #2 plan (`.claude/plans/2026-08-11-truthful-job-terminal-states.md`) used the same per-artifact slicing against the same patch workflow.
- **Alternative considered:** One monolithic task — rejected: no intermediate reviewer gate, and the runtime/test change would ship in the same reviewable unit as pure prose rewrites. Folding Task 3 into Task 2 — rejected: different repos of record (patch vs worktree file) and different ACs; a skill-text objection should not roll back a green patch commit.

### Scratch checkout at a fixed /tmp path, rebuilt per task
- **Question:** Where does the scratch upstream checkout live, and does it persist between tasks?
- **Choice:** Fixed path `/tmp/codex-plugin-cc-issue-3-scratch`; every patch-touching task starts with `reset --hard` + `checkout --force --detach <pin>` + `clean -ffd` + apply the currently committed patch. Clone reuse is a network optimization only; correctness never depends on prior task state.
- **Grounding:** Dispatch brief names the `/tmp/codex-plugin-cc-issue-3-scratch` precedent and "rebuild deterministically from the committed patch at every task start"; the issue #2 plan proved this exact workflow across three tasks.
- **Alternative considered:** mktemp-fresh clone per task (network-dependent every task, no gain over reset); a git-ignored dir inside the worktree (risks accidental commit).

### patchRevision bumped in Task 1, not the final task
- **Question:** When does `patchRevision` go 4→5, given two patch-touching commits?
- **Choice:** Task 1 bumps it together with the first regenerated patch; Task 2 leaves it at 5. Task 3's final gate re-verifies `patchRevision = 5` and that the built closure carries a `.p5` plugin path.
- **Grounding:** `codexVersion` embeds `p${patchRevision}`; bumping at the first content change keeps every intermediate commit's version string truthful (the-bar "Truthful terminal states" applied to version metadata; same decision, same grounding as the issue #2 plan). AC8 requires one bump total, which this satisfies.
- **Alternative considered:** Bumping in the last patch task — rejected: Task 1 would ship a p4-labelled build containing p5 content.

### Test framing: four behavior tests in `tests/reviewer-detach.test.mjs`, one docs test in `tests/commands.test.mjs`
- **Question:** How do the spec's Test-strategy items 1–4 map onto test cases and files, and what are the resulting suite counts?
- **Choice:** Four tests in the new file — (1) survival + verbatim durable result, (2) reviewer+`--write` refusal, (3) reviewer+`--resume-last` refusal, (4) worker-internal timeout — plus one agent-definition docs test appended to `tests/commands.test.mjs` (its seam lives there, beside the existing doc pins). The two guard refusals are separate tests so each fails for exactly one reason. Expected counts: after Task 1 `# tests 106 / # pass 102 / # fail 0 / # skipped 4`; after Task 2 `# tests 107 / # pass 103 / # fail 0 / # skipped 4`.
- **Grounding:** Spec Test strategy items 1–4 verbatim; the-bar "Tests that can fail" (all four behavior tests fail at p4 — 1 and 4 die at enqueue on the old guard, 2 and 3 assert the reworded message the old guard doesn't print); `commands.test.mjs` is the established home for doc-contract pins.
- **Alternative considered:** One combined guard test with two `run` calls — rejected: a failure wouldn't name which invariant regressed. Putting the docs test in `reviewer-detach.test.mjs` — rejected: that file is the CLI/state seam; the docs seam's precedent and its `read()` helper live in `commands.test.mjs`.

### Agent-def docs test: pin the prohibition, forbid the enabling form
- **Question:** The spec's binding agent body itself contains the literal token `` `run_in_background` `` (inside the sentence "Never pass `run_in_background`, never sleep, never write a polling loop."), yet the spec's test sketch says the file must "not match `run_in_background`". A literal `doesNotMatch(/run_in_background/)` would fail against the spec's own binding text. Which gives?
- **Choice:** The binding body wins (the spec marks it binding; the test sketch is a sketch). The docs test asserts the prohibition sentence is present (`/Never pass `run_in_background`/`), the enabling form is absent (`doesNotMatch(/run_in_background:\s*true/)` — the exact regression observed at p4, `` (`run_in_background: true`) ``), completion-notification language is absent (`doesNotMatch(/completion notification/i)`), and the three prescribed markers are present (the `--background --json` enqueue, `--wait --timeout-ms 540000`, `CODEX_REVIEW_FAILURE:`). The test still fails at p4 for three independent reasons and fails on the twice-observed regression (harness backgrounding) in any form that re-prescribes it.
- **Grounding:** Spec Decisions: "This text is binding on the plan; incidental wording may be polished, the prescribed calls and bounds may not" — deleting the prohibition sentence to satisfy a test sketch would weaken the binding text; AC3's target is "no harness background execution and no unbounded wait", which the chosen assertions pin directly. p4 body verified: line 17 carries `` (`run_in_background: true`) ``, line 23 carries "wait for its completion notification".
- **Alternative considered:** Rewording the body to avoid the token ("never run Bash in the background") — rejected: the parameter name is exactly what the executing model must not pass; euphemism trades enforcement precision for test convenience. A plain `doesNotMatch(/run_in_background/)` — rejected: contradicts the binding body.

### Hermetic env pinned at the top of `tests/reviewer-detach.test.mjs`
- **Question:** How do the new tests stay correct when the suite runs inside a live Claude Code session (which exports `CLAUDE_PLUGIN_DATA` and `CODEX_COMPANION_SESSION_ID`)?
- **Choice:** Module-level setup at the top of the file: set `process.env.CLAUDE_PLUGIN_DATA` to a fresh temp dir, delete `CODEX_COMPANION_SESSION_ID`/`CODEX_COMPANION_TRANSCRIPT_PATH`. In-process resolvers (`resolveReviewerRuntimeHome`) and spawned CLI children (which inherit `process.env` via `buildEnv`) then agree on the state root, with no session filter interference.
- **Grounding:** node.md stack shard: process-per-file isolation — set the environment the module reads before the first import-time use; `resolveStateRoot()` reads the env at call time. Precedent: `tests/liveness.test.mjs` (issue #2) pins exactly these three variables at module top for the same reason.
- **Alternative considered:** Relying on the suite-level `env -u` scrub alone (what `runtime.test.mjs` does) — rejected: leaves the file wrong when run un-scrubbed, and the scrub is a runner convention, not a property of the file.

### Test prompts delivered via stdin, not positionals
- **Question:** The upstream background test passes the prompt as a positional; the bridge's production enqueue pipes it from a temp file into stdin. Which do the new tests use?
- **Choice:** stdin — the `run` helper's `input:` option (`spawnSync` pipes it; `readStdinIfPiped` in `lib/fs.mjs:35` reads fd 0 when stdin is not a TTY, verified at p4). The enqueue the tests exercise is then byte-identical in shape to the enqueue the agent definition prescribes.
- **Grounding:** Spec Auto-resolved "Enqueue prompt delivery": the stdin path is the production mechanism ("the forensic run's job was created through it"); testing the seam the bridge actually uses is what makes test 1 evidence for the agent-def sequence.
- **Alternative considered:** Positional prompt (upstream test's style) — works, but tests a sibling input path the bridge never takes.

### Timeout test seeds a canonical `CODEX_HOME` like the foreground reviewer tests
- **Question:** Does test 4 (worker-internal timeout) need the canonical-home fixture (`auth.json` + `config.toml`), which the runtime-dir assertion doesn't reference?
- **Choice:** Yes — both reviewer-runtime tests (1 and 4) set `CODEX_HOME` to a seeded canonical home, mirroring `reviewer tasks run foreground in a fresh read-only runtime and clean it up` exactly.
- **Grounding:** The reviewer runtime is seeded *from* the canonical home; every existing reviewer test provides one. Diverging from the proven fixture to save two lines risks testing an unseeded-degenerate path no production run takes.
- **Alternative considered:** Omitting it in test 4 — rejected as above; fixture parity beats minimalism here.

### `just build` gates every task, not only the final one
- **Question:** Is a green `just build` required per task or once at the end?
- **Choice:** Every task ends with a green `just build` (Tasks 1–2 because the patch feeds a nix derivation; Task 3 because SKILL.md is a home-manager-materialized file).
- **Grounding:** CLAUDE.md: "After editing any `.nix`, run `just build` before claiming success" — the patch is materially a nix input; same decision as the issue #2 plan. After the first build the marginal cost is seconds (only the cheap `runCommand` rebuilds).
- **Alternative considered:** Final-task-only — rejected: an intermediate commit with a nix-unappliable patch would be discovered two tasks late.

### Commit boundaries: one worktree commit per task
- **Question:** What lands in each worktree commit?
- **Choice:** Task 1: `patches/agent-plugins/codex-plugin-cc.patch` + `lib/agent-plugins.nix`. Task 2: the patch file only. Task 3: `home/common/claude-code/skills/codex-collaboration/SKILL.md` only. Nothing from `$SCRATCH` is ever committed; `result` (the `just build` symlink) stays untracked.
- **Grounding:** Dispatch brief's recorded workflow (patch is the only plugin artifact); writing-plans "frequent commits" with one reviewable deliverable each; issue #2 precedent.
- **Alternative considered:** A single squashed commit — rejected: loses the per-task review gates sdd depends on.

### Evidence home for the AC8 live demo: `.claude/specs/2026-08-11-detached-reviewer-bridge-evidence.md`
- **Question:** The spec fixes the evidence *format* (c4g2-evidence precedent) and delegates the exact home to the plan. Where does the ship phase record the live plan-review run?
- **Choice:** `.claude/specs/2026-08-11-detached-reviewer-bridge-evidence.md`, created by the ship phase (not by any task in this plan), following the `.claude/specs/2026-08-10-c4g2-evidence.md` precedent: what ran, what it printed. Required contents per the spec: the enqueue payload (jobId), the wait snapshot(s) showing `running` → `completed`, the returned review with `Blocking`/`Should fix`/`Discussion` sections, the job's terminal `completed` record, and the absence of any `CODEX_REVIEW_FAILURE` or Claude fallback.
- **Grounding:** Spec Verification loop ("Record it following the `c4g2-evidence.md` precedent in `.claude/specs/` (the plan phase fixes the exact home)"); sibling-file naming convention (`<date>-<slug>-evidence.md` beside `<date>-<slug>-design.md`).
- **Alternative considered:** Appending evidence to the design spec — rejected: the design doc is approved and frozen; c4g2 set the separate-file precedent.

---

### Task 1: Guard lift — reviewer jobs enqueue on the detached background path

**Files:**
- Modify (scratch): `plugins/codex/scripts/codex-companion.mjs`
- Create (scratch): `tests/reviewer-detach.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch` (regenerated)
- Modify (worktree): `lib/agent-plugins.nix` (`patchRevision` 4→5)

**Interfaces:**
- Consumes: existing runtime, unchanged — `handleTask`'s background branch (`buildTaskJob`/`buildTaskRequest`/`enqueueBackgroundTask`/`spawnDetachedTaskWorker`), the reviewer `timeoutMs` default (840 000 ms, computed before the branch and stored in the job request), issue #2's liveness reconciliation, `runTrackedJob`'s `result: execution.payload` persistence. Test infrastructure — `installFakeCodex(binDir, behavior)`/`buildEnv(binDir)` (`tests/fake-codex-fixture.mjs`), `makeTempDir`/`initGitRepo`/`run` (`tests/helpers.mjs`), `resolveReviewerRuntimeHome(workspaceRoot, jobId)` (`plugins/codex/scripts/lib/runtime-home.mjs`).
- Produces (later tasks rely on these):
  - CLI behavior: `codex-companion task --fresh --reviewer --background --json` (prompt on stdin) exits 0 and prints the queued payload `{jobId: "reviewer-…", status: "queued", title, summary, logFile}`; the detached worker completes the review and persists `storedJob.result.rawOutput` — the exact sequence Task 2's agent definition prescribes.
  - Guard message: `Reviewer jobs must be fresh and read-only.` for reviewer+`--write` and reviewer+`--resume`/`--resume-last` (with or without `--background`).
  - Test file `tests/reviewer-detach.test.mjs` (self-contained; no fixtures shared with other tasks).

- [ ] **Step 1: Rebuild the scratch checkout**

Run the *Scratch checkout workflow* setup block from the plan header verbatim. Verify:

Run: `git -C /tmp/codex-plugin-cc-issue-3-scratch rev-parse HEAD`
Expected: `db52e28f4d9ded852ab3942cea316258ae4ef346`

- [ ] **Step 2: Write the failing tests**

Create `$SCRATCH/tests/reviewer-detach.test.mjs`:

```js
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

import { buildEnv, installFakeCodex } from "./fake-codex-fixture.mjs";
import { initGitRepo, makeTempDir, run } from "./helpers.mjs";
import { resolveReviewerRuntimeHome } from "../plugins/codex/scripts/lib/runtime-home.mjs";

// State resolvers read these variables at call time, and spawned CLI children
// inherit process.env (via buildEnv), so pinning them here keeps every test in
// this file hermetic even when the suite runs inside a live Claude Code session.
// node --test runs each file in its own process; nothing leaks across files.
process.env.CLAUDE_PLUGIN_DATA = makeTempDir("codex-plugin-reviewer-detach-data-");
delete process.env.CODEX_COMPANION_SESSION_ID;
delete process.env.CODEX_COMPANION_TRANSCRIPT_PATH;

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCRIPT = path.join(ROOT, "plugins", "codex", "scripts", "codex-companion.mjs");
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
  const repo = makeTempDir();
  initGitRepo(repo);
  fs.writeFileSync(path.join(repo, "README.md"), "hello\n");
  run("git", ["add", "README.md"], { cwd: repo });
  run("git", ["commit", "-m", "init"], { cwd: repo });
  return repo;
}

function makeCanonicalHome() {
  const canonicalHome = makeTempDir();
  fs.writeFileSync(path.join(canonicalHome, "auth.json"), "{}\n");
  fs.writeFileSync(path.join(canonicalHome, "config.toml"), 'model = "canonical"\n');
  return canonicalHome;
}

test("a background reviewer run survives its launcher and lands a verbatim durable result", async () => {
  const repo = makeReviewRepo();
  const binDir = makeTempDir();
  const canonicalHome = makeCanonicalHome();
  installFakeCodex(binDir, "slow-task");
  const env = { ...buildEnv(binDir), CODEX_HOME: canonicalHome };

  // Synchronous spawn: by the time `run` returns, the launcher process has
  // fully exited. Everything asserted after this line therefore happened under
  // the detached worker alone — completion is itself the survival proof, and
  // the queued (not completed) payload proves the enqueue returned before the
  // review ran. No stopwatch, no process-tree assertions.
  const launched = run("node", [SCRIPT, "task", "--fresh", "--reviewer", "--background", "--json"], {
    cwd: repo,
    env,
    input: "review the plan"
  });

  assert.equal(launched.status, 0, launched.stderr);
  const launchPayload = JSON.parse(launched.stdout);
  assert.equal(launchPayload.status, "queued");
  assert.match(launchPayload.jobId, /^reviewer-/);

  const waited = run(
    "node",
    [SCRIPT, "status", launchPayload.jobId, "--wait", "--timeout-ms", "15000", "--json"],
    { cwd: repo, env }
  );
  assert.equal(waited.status, 0, waited.stderr);
  assert.equal(JSON.parse(waited.stdout).job.status, "completed");

  const resultPayload = await waitFor(() => {
    const collected = run("node", [SCRIPT, "result", launchPayload.jobId, "--json"], { cwd: repo, env });
    if (collected.status !== 0) {
      return null;
    }
    return JSON.parse(collected.stdout);
  });
  assert.equal(resultPayload.job.status, "completed");
  assert.equal(resultPayload.storedJob.kind, "plan-review");
  // Byte-for-byte: rawOutput is the reviewer's final message with no rendering,
  // no trailers — the field the bridge extracts and returns verbatim.
  assert.equal(resultPayload.storedJob.result.rawOutput, "Handled the requested task.\nTask prompt accepted.");

  // Isolation held on the background path: the worker ran Codex in the per-job
  // reviewer runtime, read-only, and removed it on completion; the canonical
  // home was never touched.
  const fakeState = JSON.parse(fs.readFileSync(path.join(binDir, "fake-codex-state.json"), "utf8"));
  assert.equal(fakeState.lastThreadStart.sandbox, "read-only");
  assert.equal(fakeState.lastCodexHome, resolveReviewerRuntimeHome(repo, launchPayload.jobId));
  assert.equal(fs.existsSync(fakeState.lastCodexHome), false);
  assert.equal(fs.readFileSync(path.join(canonicalHome, "config.toml"), "utf8"), 'model = "canonical"\n');
});

test("reviewer + write is still refused on the background path", () => {
  const repo = makeReviewRepo();
  const binDir = makeTempDir();
  installFakeCodex(binDir);

  const result = run("node", [SCRIPT, "task", "--reviewer", "--write", "--background", "--json"], {
    cwd: repo,
    env: buildEnv(binDir),
    input: "review the plan"
  });

  assert.notEqual(result.status, 0);
  assert.ok(result.stderr.includes(GUARD_MESSAGE), result.stderr);
});

test("reviewer + resume is still refused on the background path", () => {
  const repo = makeReviewRepo();
  const binDir = makeTempDir();
  installFakeCodex(binDir);

  const result = run("node", [SCRIPT, "task", "--reviewer", "--resume-last", "--background", "--json"], {
    cwd: repo,
    env: buildEnv(binDir),
    input: "review the plan"
  });

  assert.notEqual(result.status, 0);
  assert.ok(result.stderr.includes(GUARD_MESSAGE), result.stderr);
});

test("the worker's internal timeout fails a background reviewer job and cleans its runtime", async () => {
  const repo = makeReviewRepo();
  const binDir = makeTempDir();
  const canonicalHome = makeCanonicalHome();
  // 5 s turn against a 1 s budget: the worker's own Promise.race timeout must
  // fire, land the recorded error in the job file, and clean the runtime —
  // with no bridge watching. Defense-in-depth's inner bound, tested alone.
  installFakeCodex(binDir, "interruptible-slow-task");
  const env = { ...buildEnv(binDir), CODEX_HOME: canonicalHome };

  const launched = run(
    "node",
    [SCRIPT, "task", "--fresh", "--reviewer", "--background", "--timeout-ms", "1000", "--json"],
    { cwd: repo, env, input: "review the plan" }
  );
  assert.equal(launched.status, 0, launched.stderr);
  const launchPayload = JSON.parse(launched.stdout);
  assert.match(launchPayload.jobId, /^reviewer-/);

  const waited = run(
    "node",
    [SCRIPT, "status", launchPayload.jobId, "--wait", "--timeout-ms", "15000", "--json"],
    { cwd: repo, env }
  );
  assert.equal(waited.status, 0, waited.stderr);
  const waitedPayload = JSON.parse(waited.stdout);
  assert.equal(waitedPayload.job.status, "failed");
  assert.match(waitedPayload.job.errorMessage, /Codex job timed out after 1000ms\./);
  assert.equal(fs.existsSync(resolveReviewerRuntimeHome(repo, launchPayload.jobId)), false);
});
```

- [ ] **Step 3: Run the tests and watch all four fail**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/reviewer-detach.test.mjs`
Expected: FAIL — 4 tests, 4 fail. Tests 1 and 4 fail at the enqueue (`launched.status` is non-zero: the p4 guard throws `Reviewer jobs must be fresh, foreground, and read-only.` on reviewer+`--background`). Tests 2 and 3 fail on the message assertion (the p4 guard refuses, but with the old wording, which does not contain `Reviewer jobs must be fresh and read-only.`).

- [ ] **Step 4: Lift the background arm from the reviewer guard**

In `$SCRATCH/plugins/codex/scripts/codex-companion.mjs`, `handleTask` (currently lines 796–798), replace:

```js
  if (reviewer && (write || resumeLast || options.background)) {
    throw new Error("Reviewer jobs must be fresh, foreground, and read-only.");
  }
```

with:

```js
  if (reviewer && (write || resumeLast)) {
    throw new Error("Reviewer jobs must be fresh and read-only.");
  }
```

This is the entire runtime change. Reviewer + `--background` now flows into the existing `options.background` branch (`buildTaskJob` is already reviewer-aware: `reviewer-` id prefix, `kind: "plan-review"`, `jobClass: "review"`; `buildTaskRequest` already carries `reviewer` and the 840 000 ms reviewer-default `timeoutMs`). Touch nothing else — no change to `printUsage`, no change to any background/worker/state function.

- [ ] **Step 5: Verify — new tests pass, full suite green, foreground reviewer pins untouched**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/reviewer-detach.test.mjs`
Expected: PASS — 4 tests, 0 fail.

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
Expected: `# tests 106 / # pass 102 / # fail 0 / # skipped 4`. In particular `reviewer tasks run foreground in a fresh read-only runtime and clean it up` and `parallel reviewers in one worktree receive distinct mutable runtimes` (`tests/runtime.test.mjs`) must still pass — foreground reviewer runs remain allowed, and only the background arm was lifted.

- [ ] **Step 6: Regenerate the patch and bump `patchRevision`**

Run the *Regeneration* block from the plan header. Then in the worktree edit `lib/agent-plugins.nix`: `patchRevision = 4;` → `patchRevision = 5;`.

Run: `git -C "$WORKTREE" diff --stat -- patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix`
Expected: both files modified; the patch diff includes the new `tests/reviewer-detach.test.mjs` hunks and the one-predicate change in `plugins/codex/scripts/codex-companion.mjs`.

Run: `grep -c "Reviewer jobs must be fresh, foreground" "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: no matches (grep exits 1). The reviewer guard is patch-added — upstream at the pin has no reviewer guard at all, so the committed p4 patch carried the old message on a `+` line; after the edit and regeneration the old message vanishes from the patch (and thus from the patched tree) entirely.

Run: `grep -c "Reviewer jobs must be fresh and read-only." "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"`
Expected: `2` — one `+` line adding the reworded guard in `plugins/codex/scripts/codex-companion.mjs`, one `+` line adding the `GUARD_MESSAGE` constant in `tests/reviewer-detach.test.mjs`.

- [ ] **Step 7: `just build`**

Run (from `$WORKTREE`): `just build`
Expected: exits 0. Then `nix-store -qR ./result | grep codex-plugin-cc` lists a path containing `codex-plugin-cc-1.0.6-nix.db52e28f.p5` (the p5 marketplace built from the regenerated patch).

- [ ] **Step 8: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix
git commit -m "feat(agent-plugins): let reviewer jobs run detached on the background path

Drop the options.background arm from the codex-companion reviewer guard so
task --fresh --reviewer --background enqueues the runtime's own detached
worker (reviewer- job id, plan-review kind, 840 s stored budget) instead of
throwing. Write/resume combinations still refuse with the reworded message
'Reviewer jobs must be fresh and read-only.'; foreground reviewer runs stay
allowed. New tests/reviewer-detach.test.mjs pins launcher-survival with a
verbatim durable result, both surviving refusals, and the worker-internal
timeout on the background path. Patch p5 against codex-plugin-cc db52e28f.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Bridge agent definition — the bounded foreground transport sequence

**Files:**
- Modify (scratch): `plugins/codex/agents/codex-reviewer.md`
- Modify (scratch): `tests/commands.test.mjs`
- Modify (worktree): `patches/agent-plugins/codex-plugin-cc.patch` (regenerated)

**Interfaces:**
- Consumes: Task 1's CLI behavior — `task --fresh --reviewer --background --json` (prompt on stdin) prints `{jobId: "reviewer-…", status: "queued", …}`; `status <jobId> --wait --timeout-ms <n> --json` exits 0 and prints `{job: {status, errorMessage?, summary?, …}}` whether the job succeeded or failed; `result <jobId> --json` prints `{job, storedJob}` with `storedJob.result.rawOutput` holding the reviewer's final message byte-for-byte. Test seam: the `read(relativePath)` helper already defined at the top of `tests/commands.test.mjs` (resolves against `plugins/codex/`).
- Produces: the rewritten `plugins/codex/agents/codex-reviewer.md` — the single home for launch mechanics, which Task 3's skill text will point at ("Launch mechanics live solely in that agent's definition").

- [ ] **Step 1: Rebuild the scratch checkout**

Run the *Scratch checkout workflow* setup block from the plan header verbatim (it applies the Task 1 patch, so the lifted guard and `tests/reviewer-detach.test.mjs` are present). Verify:

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/reviewer-detach.test.mjs`
Expected: PASS — 4 tests, 0 fail.

- [ ] **Step 2: Write the failing docs-contract test**

Append to `$SCRATCH/tests/commands.test.mjs` (after `internal docs use task terminology for rescue runs`, using the file's existing `read` helper):

```js
test("the reviewer bridge agent prescribes only bounded foreground calls", () => {
  const agent = read("agents/codex-reviewer.md");

  // The fixed sequence: enqueue on the runtime's detached background path,
  // bounded waits, failure marker.
  assert.match(agent, /task --fresh --reviewer --background --json/);
  assert.match(agent, /--wait --timeout-ms 540000/);
  assert.match(agent, /CODEX_REVIEW_FAILURE:/);

  // The twice-observed regression, pinned in both directions: the definition
  // must state the prohibition and must never re-prescribe harness
  // backgrounding or a completion-notification wait.
  assert.match(agent, /Never pass `run_in_background`/);
  assert.doesNotMatch(agent, /run_in_background:\s*true/);
  assert.doesNotMatch(agent, /completion notification/i);
});
```

- [ ] **Step 3: Run the test and watch it fail**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/commands.test.mjs`
Expected: FAIL — the new test reports the first `assert.match` (no `--background` enqueue in the p4 body), and the p4 body also carries `` `run_in_background: true` `` and "wait for its completion notification", each independently failing its assertion.

- [ ] **Step 4: Replace the agent definition body**

Overwrite `$SCRATCH/plugins/codex/agents/codex-reviewer.md` with exactly this content (frontmatter unchanged from p4; the body below it is the spec's binding text — copy byte-for-byte, do not paraphrase; the prescribed calls and bounds may not be altered):

````markdown
---
name: codex-reviewer
description: Internal bridge for fresh, isolated, read-only Codex plan reviews requested by the codex-collaboration skill
model: sonnet
tools: Bash, Read
---

Act only as a transport for one Codex plan-review job.

- The dispatch message's first line is `WORKTREE_ROOT: <absolute path>`; everything
  after that line is the delegation prompt. If the line is absent, use the
  invocation directory as the root. Every Bash call below is foreground and
  bounded — the two wait calls set the Bash tool's `timeout` to 600000
  explicitly; every other call is sub-second and stays under the tool's default
  bound. Never pass `run_in_background`, never sleep, never write a polling loop.
- Pre-flight with one fast foreground Bash call: `command -v codex-companion`. If
  the command is missing, immediately return
  `CODEX_REVIEW_FAILURE: codex-companion not on PATH` without running anything else.
- Write the delegation prompt, unchanged, to a temporary file outside the repository.
- Enqueue exactly one review with one sub-second foreground call:
  `cd "<worktree-root>" && codex-companion task --fresh --reviewer --background --json < "<tmpfile>"`.
  The `cd` keys the runtime's job state to the reviewed worktree. Note the `jobId`
  from the printed JSON. From this moment a detached worker owns the review with
  its own 840 s budget; nothing that happens to you can stop it, and its result
  is durable in the job record.
- Wait with at most two foreground calls, run one after the other only while the
  job is still `queued` or `running`:
  `cd "<worktree-root>" && codex-companion status <jobId> --wait --timeout-ms 540000 --json`
  — each with the Bash tool's `timeout` parameter set to 600000. Read
  `job.status` from the printed JSON (the command exits 0 either way). Two
  540 s waits cover the worker's 840 s budget plus startup with margin.
- If `job.status` is `completed`, collect the result with one foreground call
  (temp paths beside the prompt file):
  `cd "<worktree-root>" && codex-companion result <jobId> --json > "<tmpdir>/result.json" && node -e 'const fs=require("node:fs");const o=JSON.parse(fs.readFileSync(process.argv[1],"utf8"))?.storedJob?.result?.rawOutput;if(typeof o!=="string"||!o)process.exit(3);fs.writeFileSync(process.argv[2],o)' "<tmpdir>/result.json" "<tmpdir>/review.md"`,
  then Read `<tmpdir>/review.md` and return its contents exactly. If the
  extraction exits non-zero, return
  `CODEX_REVIEW_FAILURE: job <jobId> completed without recorded reviewer output`.
- If `job.status` is `failed` or `cancelled`, return one line:
  `CODEX_REVIEW_FAILURE: ` followed by the job's `errorMessage`, else its
  `summary`, else `job <jobId> ended <status>`.
- If the job is still `queued` or `running` after the second wait, return one line:
  `CODEX_REVIEW_FAILURE: job <jobId> still <status> after 1080s of bounded waits
  (worker budget is 840s); check codex-companion status <jobId>`. Do not cancel
  the job — the worker's own timeout is the correctness bound.
- If any prescribed command itself fails, return a single line beginning
  `CODEX_REVIEW_FAILURE:` followed by its stderr or exit status.
- Run the whole sequence in this one turn without pausing; stopping early only
  delays the caller — it cannot harm the review, which is already detached with
  a durable result.
- Do not inspect the repository, interpret the request, edit files, run Git, retry,
  fall back to Claude analysis, or add commentary.
````

- [ ] **Step 5: Verify — docs test passes, full suite green**

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/commands.test.mjs`
Expected: PASS, including `the reviewer bridge agent prescribes only bounded foreground calls`.

Run (from `$SCRATCH`): `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`
Expected: `# tests 107 / # pass 103 / # fail 0 / # skipped 4`.

- [ ] **Step 6: Regenerate the patch, `just build`**

Run the *Regeneration* block from the plan header (`patchRevision` stays 5 — do not touch `lib/agent-plugins.nix`).

Run (from `$WORKTREE`): `just build`
Expected: exits 0; `nix-store -qR ./result | grep codex-plugin-cc` still lists the `.p5` path, and inside it `plugins/codex/agents/codex-reviewer.md` contains `task --fresh --reviewer --background --json` and does not contain `run_in_background: true`:

```bash
STORE=$(nix-store -qR ./result | grep codex-plugin-cc)
grep -c "task --fresh --reviewer --background --json" "$STORE/plugins/codex/agents/codex-reviewer.md"   # ≥ 1
grep -c "run_in_background: true" "$STORE/plugins/codex/agents/codex-reviewer.md" || true               # 0
```

- [ ] **Step 7: Commit**

```bash
cd "$WORKTREE"
git add patches/agent-plugins/codex-plugin-cc.patch
git commit -m "feat(agent-plugins): rewrite codex-reviewer bridge as bounded foreground transport

The bridge agent definition now prescribes the fixed sequence enqueue
(task --fresh --reviewer --background --json, prompt via stdin temp file) ->
at most two status --wait --timeout-ms 540000 calls (Bash tool timeout
600000) -> result --json with a node -e extraction of
storedJob.result.rawOutput returned verbatim. No harness backgrounding, no
sleeps, no polling loops, no completion-notification wait; on failed,
cancelled, or budget-expired jobs it returns one CODEX_REVIEW_FAILURE: line
carrying the job's recorded error and never cancels the worker. A docs test
in tests/commands.test.mjs pins the prescribed calls and forbids the
twice-observed backgrounding regression.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Skill text states the contract; final whole-issue verification

**Files:**
- Modify (worktree): `home/common/claude-code/skills/codex-collaboration/SKILL.md`

**Interfaces:**
- Consumes: Task 2's rewritten agent definition — the skill text's "Launch mechanics live solely in that agent's definition" must be true when this task lands, which is why this task runs last.
- Produces: the caller-facing contract for from-issue Phase 5 and sdd's diff-review consumer, unchanged in shape (three-section output, single `CODEX_REVIEW_FAILURE:` line on failure, capability fallback, one-time native fallback). Exactly three regions of SKILL.md change; everything else stays byte-stable.

- [ ] **Step 1: Edit `## Launch` — replace the plumbing narration with the contract**

In `$WORKTREE/home/common/claude-code/skills/codex-collaboration/SKILL.md`, replace the second paragraph of `## Launch` (currently lines 93–100), exactly:

Old text:

```markdown
Dispatch the plugin agent `codex:codex-reviewer` once with the complete packet.
Run it in the foreground, with the first line of the dispatch exactly
`WORKTREE_ROOT: <absolute worktree root>` so the bridge keys runtime job state
to the reviewed worktree. The bridge launches
`codex-companion task --fresh --reviewer --timeout-ms 840000` as a background
Bash task — the 840 s runtime budget exceeds the 600 s foreground Bash cap, so
expect up to ~15 minutes wall-clock — which guarantees a fresh isolated
`CODEX_HOME`, approval policy `never`, and sandbox `read-only`.
```

New text (the spec's contract paragraph, verbatim in substance — this is what the rebuilt bridge actually does):

```markdown
Dispatch the plugin agent `codex:codex-reviewer` once with the complete packet.
Run it in the foreground, with the first line of the dispatch exactly
`WORKTREE_ROOT: <absolute worktree root>` so the bridge keys runtime job state
to the reviewed worktree. Launch mechanics live solely in that agent's
definition. The contract: the review runs fresh in an isolated read-only
Codex runtime (fresh `CODEX_HOME`, approval policy `never`, sandbox
`read-only`), survives the bridge's own lifetime, and is bounded by the
runtime's internal ~14 min budget — expect up to ~15 minutes wall clock. The
bridge returns the reviewer's output verbatim, or a single
`CODEX_REVIEW_FAILURE:` line carrying the review job's recorded error.
```

- [ ] **Step 2: Edit `## Validate and fall back` — four failure classes become three**

In the same file, replace the four failure-class bullets (currently lines 113–116), exactly:

Old text:

```markdown
- the executable is missing or authentication is unavailable;
- the process crashes or reaches its hard timeout;
- the agent returns `CODEX_REVIEW_FAILURE:`;
- the result is empty or malformed after one completed fresh run.
```

New text (the process-level class becomes a job-record class — the skill can no longer observe a crash or hard timeout directly; it reaches the skill as the bridge's `CODEX_REVIEW_FAILURE:` line carrying the job record's error, and a crashed bridge agent shows up as the third class, empty or malformed output):

```markdown
- the executable is missing or authentication is unavailable;
- the agent returns `CODEX_REVIEW_FAILURE:` — the review job ended failed,
  cancelled, or timed out (including the runtime's hard timeout and
  dead-worker detection), with the job's recorded error on the line;
- the result is empty or malformed after one completed fresh run.
```

- [ ] **Step 3: Edit `## Operation: diff-review` — drop the mechanics clause**

In the same file's diff-review operation paragraph (currently lines 154–155), replace exactly:

Old text:

```markdown
dispatch with background launch inside the bridge, validation, one-time native
```

New text:

```markdown
dispatch, validation, one-time native
```

Touch nothing else in the file: the packet lists, reviewer contract, verify-and-disposition flow, "Parallel reviews are valid" paragraph, and both operations' output contracts stay byte-stable.

- [ ] **Step 4: Verify the edits are exactly the three regions**

Run: `grep -in "background" "$WORKTREE/home/common/claude-code/skills/codex-collaboration/SKILL.md"`
Expected: no output (exit 1). At this task's starting commit the same grep matches in the Launch paragraph ("as a background / Bash task") and the diff-review paragraph ("with background launch inside the bridge") — this gate fails until both edits land.

Run: `grep -n "the process crashes or reaches its hard timeout" "$WORKTREE/home/common/claude-code/skills/codex-collaboration/SKILL.md"`
Expected: no output (exit 1) — the process-level failure class is gone.

Run: `grep -c "Launch mechanics live solely" "$WORKTREE/home/common/claude-code/skills/codex-collaboration/SKILL.md"`
Expected: `1`.

Run: `git -C "$WORKTREE" diff --stat -- home/common/claude-code/skills/codex-collaboration/SKILL.md`
Expected: exactly one file changed; the hunks touch only the Launch paragraph, the failure-class bullets, and the diff-review paragraph.

- [ ] **Step 5: Final whole-issue verification — patch determinism, revision, closure**

Determinism check — a pristine re-apply of the committed patch reproduces itself byte-for-byte:

```bash
WORKTREE=/Users/anis/tmp/nix-config/.claude/worktrees/issue-3-detached-reviewer-bridge
SCRATCH=/tmp/codex-plugin-cc-issue-3-scratch
PIN=db52e28f4d9ded852ab3942cea316258ae4ef346
git -C "$SCRATCH" reset --hard && git -C "$SCRATCH" checkout --force --detach "$PIN" && git -C "$SCRATCH" clean -ffd
git -C "$SCRATCH" apply --unidiff-zero "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
git -C "$SCRATCH" add -N .
git -C "$SCRATCH" diff -U0 "$PIN" | diff - "$WORKTREE/patches/agent-plugins/codex-plugin-cc.patch"
```
Expected: `diff` prints nothing (exit 0).

Run: `grep -n 'patchRevision = ' "$WORKTREE/lib/agent-plugins.nix"`
Expected: `patchRevision = 5;` (bumped in Task 1; Tasks 2–3 must not have changed it).

Run (from `$WORKTREE`): `just build`
Expected: exits 0. Then:

```bash
STORE=$(nix-store -qR ./result | grep codex-plugin-cc)
echo "$STORE"                                                                    # ...codex-plugin-cc-1.0.6-nix.db52e28f.p5
grep -c "Reviewer jobs must be fresh and read-only." "$STORE/plugins/codex/scripts/codex-companion.mjs"   # 1
grep -c "task --fresh --reviewer --background --json" "$STORE/plugins/codex/agents/codex-reviewer.md"     # >= 1
```
Expected: the `.p5` path; the new guard message present in the shipped script; the new agent body present in the shipped definition — proof the patch applies under nix's `patch -p1` and ships the feature.

- [ ] **Step 6: Commit**

```bash
cd "$WORKTREE"
git add home/common/claude-code/skills/codex-collaboration/SKILL.md
git commit -m "feat(claude-code): codex-collaboration states the reviewer contract, not launch mechanics

The skill's Launch section now states only the contract — fresh isolated
read-only runtime, survives the bridge's lifetime, ~15 min ceiling, verbatim
output or one CODEX_REVIEW_FAILURE: line with the job's recorded error —
with launch mechanics living solely in the codex:codex-reviewer agent
definition. The validate-and-fall-back failure classes collapse 4 -> 3 (the
process-level class becomes a job-record class), and the diff-review
operation drops its background-launch mechanics clause. Caller-facing output
shape and fallback policy are unchanged.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Ship-phase note (AC8 live demo — not a task in this plan)

Activation (`just switch`) and the live end-to-end demo are the ship phase's call. After the merged change is active, run one real `plan-review` through the codex-collaboration skill against a real plan and record the evidence in `.claude/specs/2026-08-11-detached-reviewer-bridge-evidence.md` (c4g2-evidence precedent — what ran, what it printed): the enqueue payload (jobId), the wait snapshot(s) showing `running` → `completed`, the returned review with `Blocking`/`Should fix`/`Discussion` sections, the job's terminal `completed` record, and the absence of any `CODEX_REVIEW_FAILURE` or Claude fallback.

## Spec coverage

- R1/AC1 (reviewer background enqueue prints queued JSON with `jobId`, no waiting): Task 1 (guard lift; test 1's queued-payload assertion is the behavioral form of "sub-second").
- R2/AC2 (write/resume still refused; fresh + read-only invariants hold on the background path): Task 1 (tests 2–3 pin the refusals; test 1 pins sandbox `read-only`, per-job runtime home, runtime cleanup, canonical-home untouched).
- R3/AC3 (agent def: fixed bounded foreground sequence, no harness backgrounding, no unbounded wait): Task 2 (binding body + docs-contract test).
- R4/AC4 (launcher termination doesn't stop the review; result durable): Task 1 (test 1 — synchronous launcher provably exited before completion; result collected from the job record afterwards). SessionEnd boundary documented in the spec, no code change.
- R5/AC5 (failed/timed-out job → one `CODEX_REVIEW_FAILURE:` line with the recorded error, within the wait budget): error source pinned by Task 1 test 4 (`Codex job timed out after 1000ms.` in the job record via `status --wait`); the bridge's line format and budget prescribed by Task 2's binding body (failed/cancelled, expiry-without-cancel, and command-failure clauses).
- R6/AC6 (skill states contract only; no background tasks / completion notifications / launch command): Task 3 (three edits + greps).
- R7/AC7 (suite green env-scrubbed; reviewer-background coverage flips refused→enqueued as new tests failing at p4): Tasks 1–2 suite gates; final count `# tests 107 / # pass 103 / # fail 0 / # skipped 4`.
- R8/AC8 (patchRevision 4→5, `just build` green, live demo evidenced): Task 1 (bump + build), Task 3 Step 5 (determinism + `.p5` closure content checks); live demo deferred to ship phase with its evidence home fixed above.
