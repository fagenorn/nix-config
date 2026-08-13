# Durable Workflow Lifecycle Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make issue owners and dispatchers recover from lost notifications while mechanically enforcing one fresh retry, fixed wall deadlines, and pre-ceiling durable handoffs for [issue #14](https://github.com/fagenorn/nix-config/issues/14).

**Architecture:** A standard-library Python CLI is the single writer for versioned, atomic `.superpowers/workflows/<run-id>/state.json` ledgers. Workflow skills invoke that CLI at launch, phase, reconciliation, and finish boundaries; deterministic subprocess tests reopen the ledger and contract tests assert the required write-before-notify ordering in skill prose.

**Tech stack:** Python 3 standard library (`argparse`, `datetime`, `json`, `os`, `pathlib`, `tempfile`, `unittest`), Markdown skill contracts, Nix Home Manager, Just.

## Global Constraints

- Runtime state lives under the current repository's git-ignored `.superpowers/workflows/<run-id>/`; no runtime ledger or handoff is committed.
- `state.json` has `schema_version: 1`; every transaction holds `fcntl.flock` on per-run `state.lock` across read–validate–mutate–replace, then replaces the file atomically. Unknown versions, states, actions, identities, lock failures, and conflicting terminal writes exit non-zero without altering the previous file.
- Fresh attempts are numbered 1 and 2 only. Same issue + owner + normalized worktree resumes the current attempt without changing `started_at` or `deadline_at`; another fresh launch is refused and persists a failed issue outcome linked to attempts 1 and 2.
- Deadlines are fixed at fresh launch. `last_progress_at` changes do not extend them. Overdue active attempts become visible `stopped` outcomes and retain the worktree path.
- The compact terminal result fields are exactly `issue`, `state`, `pr_url`, `merge_sha`, `issue_closed`, `discussion_items`, and `notes`; `state` is `merged | stopped | failed`, and `notes` is at most 500 characters.
- Durable terminal state is written before the identical compact result is sent to the caller. Reconciliation happens before any retry; an older delayed notification never overrides a newer authoritative result.
- Phase actions are the closed set `continue | fresh_start | handoff | delegate`. At/over either reserved ceiling, `continue` is forbidden; missing usage data selects `handoff` unless `delegate` or artifact-sufficient `fresh_start` already applies.
- A durable handoff is `handed_off`, resumes the same attempt while its fixed deadline remains, and never consumes the fresh-retry allowance. `reconcile` never silently expires it; an explicit matching late resume records a visible stopped result with its worktree retained, then permits the one fresh retry.
- Every accepted launch persists the issue and an append-only `{kind, owner, worktree, at}` event; reconstruction never depends on command stdout.
- Use no dependency beyond Python's standard library and no real sleeps, network, GitHub calls, or agent processes in tests.
- Preserve unrelated worktree changes. Never bypass commit signing. Every implementation commit includes `Co-Authored-By: Codex <codex@openai.com>`.

## File structure

| File | Responsibility |
|---|---|
| `home/common/agent-skills/scripts/workflow-state.py` | New executable: schema validation, atomic mutation, attempt transitions, reconciliation, phase decisions, and JSON CLI. |
| `home/common/agent-skills/tests/test_workflow_state.py` | New subprocess/filesystem tests for lifecycle, retry, expiry, handoff, phase actions, and corruption/conflict rejection. |
| `home/common/agent-skills/tests/test_workflow_skill_contracts.py` | New static contract tests for invocation paths, lifecycle ordering, compact schema, and handoff integration in skill text. |
| `home/common/claude-code/skills/orchestrate-issues/SKILL.md` | Modify dispatcher protocol to initialize/reconcile durable runs, supply attempt identity, cap retries through the helper, and drain from durable outcomes. |
| `home/common/agent-skills/skills/from-issue/SKILL.md` | Modify orchestration phase boundaries and all returns to use durable lifecycle state. |
| `home/common/agent-skills/skills/from-issue/AUTO.md` | Modify autonomous rules so checkpoints persist executable decisions and terminal/handoff state. |
| `home/common/agent-skills/skills/handoff/SKILL.md` | Modify handoff contract to accept and atomically write a validated per-run durable destination while retaining the interactive temp default. |
| `home/common/agent-skills/default.nix` | Modify shared installation to expose the helper as executable `~/.agents/bin/workflow-state`. |
| `justfile` | Modify verification surface with `agent-workflow-tests`. |

## Test seams

- Invoke `home/common/agent-skills/scripts/workflow-state.py` as a subprocess with a temporary repository and injected ISO timestamps; assert stdout JSON, exit status, and reopened `state.json`.
- Reopen the ledger after each command with a fresh Python process; no test imports private helper functions.
- Read the four workflow skill files as text and assert stable operation names, exact result fields, and write/reconcile ordering.
- Run `just agent-workflow-tests`, then `just build`.

## Auto-resolved decisions

### Four task boundaries
- **Question:** How should lifecycle code, budget behavior, prose integration, and installation be divided for independent reviews?
- **Choice:** Use four tasks: durable attempt/result lifecycle; phase/handoff policy; skill integration/contracts; installation and repository gates.
- **Grounding:** `writing-plans` requires the smallest independently testable reviewer-worthy deliverable. Core recovery works without context policy; policy extends its state machine; skills consume the complete CLI; installation verifies the deployed path.
- **Alternative considered:** One helper task plus one prose task was rejected because retry/recovery and phase-budget behavior are independently rejectable contracts and would make one review too broad.

### Executable location and name
- **Question:** Where should the shared lifecycle helper be authored and how should skills invoke it?
- **Choice:** Author `home/common/agent-skills/scripts/workflow-state.py` and install it at `~/.agents/bin/workflow-state`.
- **Grounding:** `home/common/agent-skills/default.nix` already installs shared project-independent binaries in `~/.agents/bin`, which is visible to both Claude-only and shared skills.
- **Alternative considered:** Placing it under `orchestrate-issues/` was rejected because `from-issue` and `handoff` also consume it and Codex does not install the Claude-only skill tree.

### CLI-only test boundary
- **Question:** Should tests import lifecycle internals for speed or exercise only the CLI?
- **Choice:** Exercise only subprocess JSON and reopened filesystem state.
- **Grounding:** The design fixes the CLI/filesystem as the public seam, and the Bar requires observable behavior rather than private call assertions.
- **Alternative considered:** Unit-importing helpers was rejected because internal refactors could pass while argument parsing, exit behavior, or atomic persistence was broken.

### Phase action precedence
- **Question:** When multiple phase-boundary choices are possible, what deterministic precedence should the helper implement?
- **Choice:** `delegate` when the entire remainder is self-contained; otherwise `fresh_start` when artifacts fully reconstruct the next phase and it needs no current context; otherwise `handoff` when usage is missing/at threshold or non-artifact state must travel; otherwise `continue`.
- **Grounding:** This is the ordered strategy in `from-issue` expressed as a closed set, while preserving the design's “never continue without measured headroom” invariant.
- **Alternative considered:** Checking budget before delegation/fresh start was rejected because it would write unnecessary handoffs even when no conversation state needs to survive.

### Default headroom
- **Question:** What concrete reserve makes “before the ceiling” executable?
- **Choice:** Defaults are 2 assistant turns and 10,000 context tokens; a configured value may override either, and equality with `ceiling - headroom` is already too late to continue.
- **Grounding:** The design requires one orchestration turn plus the next dispatch/report boundary; two turns and 10k tokens conservatively represent that boundary without changing the documented 120/150k ceilings.
- **Alternative considered:** Zero reserve was rejected because deciding only at the exact ceiling cannot produce a handoff before crossing it.

### Result input channel
- **Question:** How should a skill pass structured terminal data without shell-quoting corrupting discussion items or notes?
- **Choice:** `finish` consumes a JSON file through `--result-file` and prints the normalized persisted object to stdout.
- **Grounding:** The result is structured and may contain arbitrary reviewer text; file input avoids command-line quoting and leaves the durable ledger as the sole authoritative stored result.
- **Alternative considered:** Seven separate flags were rejected because JSON-valued discussion items and nullable fields would be reassembled inconsistently by prompt authors.

### Contract-test strictness
- **Question:** Should static tests compare whole skill paragraphs byte-for-byte?
- **Choice:** Assert semantic anchors and their ordering, including helper operations, schema fields, and “finish before caller report”; do not snapshot entire prose.
- **Grounding:** Tests should fail for behavior contract drift, not harmless editorial wrapping.
- **Alternative considered:** Full snapshots were rejected as brittle and as duplicate authoritative copies of skill text.

### B1: Durable launch history
- **Question:** The fallback reviewer found that the original plan returned a resume marker but left persisted state looking like only a fresh launch. How should Task 1 change?
- **Choice:** Require an issue field and append-only launch events on every accepted fresh/resume launch, and assert them after reopening state.
- **Grounding:** Issue #14 requires reconstructable issue identity and resume-versus-fresh launch state; the amended spec records the corrected schema.
- **Alternative considered:** Output-only launch markers were rejected because they disappear with a lost notification.

### B2: Concurrent writer safety
- **Question:** The fallback reviewer found atomic replacement alone permits lost updates from the dispatcher's default two parallel owners. What must Task 1 add?
- **Choice:** Lock a stable per-run file with `fcntl.flock` across the entire transaction and add a concurrent subprocess test proving both issue updates survive.
- **Grounding:** Live `orchestrate-issues/SKILL.md` defaults `maxParallel` to 2; the amended spec and Bar require one authoritative durable ledger.
- **Alternative considered:** Optimistic unlocked replacement was rejected because it is crash-safe but not concurrency-safe.

### S1: Focused red command
- **Question:** The fallback reviewer found Task 2's dotted unittest name crosses the hyphenated `agent-skills` directory and is not importable. What command should replace it?
- **Choice:** Run the test file by filesystem path for the focused red step.
- **Grounding:** Existing repository test/eval commands use file paths, and the path form works without package import names.
- **Alternative considered:** Renaming the production directory into a Python package was rejected as unrelated scope.

### S2: One combined controller demo
- **Question:** The fallback reviewer found the plan covered six scenarios separately but did not prove the issue's combined final-ledger demo.
- **Choice:** Add one deterministic test containing delayed completion, silent expiry, near-ceiling handoff, outcome uniqueness, and retry-cap assertions.
- **Grounding:** The issue's Demo paragraph requests those conditions in one fixture; the amended spec now names the seam.
- **Alternative considered:** Separate tests alone were rejected because they cannot expose cross-issue reconciliation or uniqueness interactions.

## Standards review

- **Reviewer:** native Codex local contract fallback after three fresh read-only worker attempts produced no report.
- **Job IDs:** `issue14-plan-review`, `issue14-plan-review-retry`, `issue14-plan-review-final` (infrastructure timeouts; no findings returned).
- **Base SHA:** `c254feee264bf45b0c704b668ca8bbc7a56e25e4`
- **Plan reviewed:** `7497ff5`
- **Fallback used:** yes — local grade against `/nix/store/5npc5maarqgv7nkvmircdwpjx6z9nysy-hm_fromissue/REVIEW-CONTRACT.md`, live files, the Bar, and Python standards.
- **Disposition:** B1 and B2 verified and applied to spec/plan; S1 and S2 verified and applied; no Discussion findings. UI/common-miss checks do not apply to this CLI/Markdown change. Remaining plan is clean after amendment.

---

### Task 1: Durable attempt and terminal-result lifecycle

**Files:**
- Create: `home/common/agent-skills/scripts/workflow-state.py`
- Create: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: repository root, `run_id`, injected RFC3339 UTC `--now`, issue number, owner handle, absolute/normalizable worktree, budget minutes, and a compact JSON result file.
- Produces: CLI commands `init-run`, `launch`, `finish`, and `reconcile`; JSON stdout; atomic `.superpowers/workflows/<run-id>/state.json` with schema version 1.
- Command forms:
  - `workflow-state init-run --repo-root ROOT --run-id ID --now TIME`
  - `workflow-state launch --repo-root ROOT --run-id ID --issue N --owner OWNER --worktree PATH --now TIME --budget-minutes MINUTES [--resume-handoff PATH]`
  - `workflow-state finish --repo-root ROOT --run-id ID --issue N --attempt N --result-file PATH --now TIME`
  - `workflow-state reconcile --repo-root ROOT --run-id ID --now TIME`

- [ ] **Step 1: Write failing black-box lifecycle tests**

Create a `unittest.TestCase` whose `setUp` makes a temporary repository root and whose `run_cli(*args, ok=True)` runs `[sys.executable, SCRIPT, *args]` with captured text. Add tests that:

```python
def test_delayed_notification_recovers_durable_terminal_result(self):
    self.init_run()
    first = self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
    result = {"issue": 14, "state": "merged", "pr_url": "https://github.com/fagenorn/nix-config/pull/15", "merge_sha": "abc123", "issue_closed": True, "discussion_items": [], "notes": ""}
    persisted = self.finish(first["attempt"], result)
    recovered = self.reconcile(now="2026-08-13T20:10:00Z")
    self.assertEqual(persisted, result)
    self.assertEqual(recovered["issues"]["14"]["outcome"], result)

def test_same_owner_worktree_resume_keeps_attempt_and_deadline(self):
    self.init_run()
    first = self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
    resumed = self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a", now="2026-08-13T20:20:00Z")
    self.assertEqual((resumed["attempt"], resumed["launch_kind"]), (1, "resume"))
    self.assertEqual(resumed["deadline_at"], first["deadline_at"])

def test_only_one_fresh_retry_and_refusal_links_prior_attempts(self):
    self.init_run()
    self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
    second = self.launch(issue=14, owner="owner-b", worktree=self.root / "wt-b")
    refused = self.launch(issue=14, owner="owner-c", worktree=self.root / "wt-c", ok=False)
    state = self.read_state()
    self.assertEqual((second["attempt"], second["prior_attempt"]), (2, 1))
    self.assertEqual(state["issues"]["14"]["outcome"]["state"], "failed")
    self.assertEqual(refused.returncode, 3)
    self.assertIn("attempts 1 and 2", refused.stderr)
```

Also cover overdue active attempt → stopped with worktree path in notes, matching repeated `finish` idempotency, conflicting finish rejection with unchanged bytes, terminal resume returning the stored result rather than launching, invalid schema/action/state rejection, note length, nullable URL/SHA validation, and `.superpowers/workflows/.gitignore` containing `*`.

Assert every accepted attempt contains `issue` and a persisted `launches` list. A matching resume appends a `resume` event with owner/worktree/time while preserving `started_at` and `deadline_at`; reopening the file must prove the event without relying on stdout. Add one concurrency test that launches helper subprocesses against distinct issues in the same run and asserts the reopened ledger contains both updates; coordinate their start with a test-only process barrier, never production sleeps.

- [ ] **Step 2: Run the new test module and confirm the red state**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_state.py`

Expected: FAIL because `home/common/agent-skills/scripts/workflow-state.py` does not exist.

- [ ] **Step 3: Implement the minimal lifecycle CLI**

Implement a script with `main(argv: list[str] | None = None) -> int` and no import-time effects. Centralize:

```python
SCHEMA_VERSION = 1
ATTEMPT_STATES = frozenset({"active", "handed_off", "stopped", "failed", "merged"})
RESULT_STATES = frozenset({"merged", "stopped", "failed"})
RESULT_FIELDS = ("issue", "state", "pr_url", "merge_sha", "issue_closed", "discussion_items", "notes")
```

Use `datetime.fromisoformat(value.replace("Z", "+00:00"))`, reject non-UTC/naive time, normalize worktrees with `Path.resolve(strict=False)`, and resolve the run directory only beneath `Path(repo_root).resolve() / ".superpowers/workflows"`. Validate `run_id` against `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`.

For every transaction: open stable per-run `state.lock`, acquire `fcntl.LOCK_EX` before reading, read+validate existing JSON, mutate a fresh object, write JSON with sorted keys and a newline to `NamedTemporaryFile(dir=run_dir, delete=False)`, `flush`, `os.fsync`, close, `os.replace`, then fsync the directory when supported; release only after replacement completes. On failure unlink only the helper's temporary file. Never catch-and-ignore lock, validation, or filesystem errors. Read-only inspection takes `LOCK_SH`.

`launch` returns the attempt object. A fresh launch stores `issue`, a fixed deadline, `state: active`, `launch_kind: fresh`, one fresh launch event, `prior_attempt`, null terminal result/handoff, and phase fields. Same identity appends a resume launch event and stores `launch_kind: resume` without rewriting start/deadline. A third fresh request atomically stores the failed compact outcome and exits 3 after printing a precise refusal to stderr.

`finish` validates exact fields/types and issue match, persists the result on the named attempt and issue outcome, then prints the normalized object. `reconcile` expires every overdue active attempt and returns the full compact run view. Preserve worktree paths in every stopped/failed note without exceeding 500 characters.

- [ ] **Step 4: Run lifecycle tests and inspect atomic state**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_state.py`

Expected: PASS; test names explicitly include delayed recovery, owner death/expiry, resume, retry cap, and conflicting-write rejection. No test sleeps.

Run: `git diff --check -- home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py`

Expected: exit 0 and no output.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(agents): persist bounded workflow attempts (#14)" -m "Co-Authored-By: Codex <codex@openai.com>"
```

### Task 2: Executable phase-budget and durable-handoff transitions

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: Task 1's validated run/attempt lookup and atomic mutation functions.
- Produces: `progress` command and closed-set `phase_action` persistence.
- Command form: `workflow-state progress --repo-root ROOT --run-id ID --issue N --attempt N --phase N --now TIME [--turn-count N] [--context-tokens N] [--turn-ceiling 120] [--context-ceiling 150000] [--turn-headroom 2] [--context-headroom 10000] --next-needs-context true|false --artifacts-sufficient true|false --remainder-self-contained true|false [--handoff-path PATH]`.

- [ ] **Step 1: Add failing action and handoff tests**

Add table-driven subprocess cases:

```python
cases = [
    ({"remainder_self_contained": True, "turn_count": 119, "context_tokens": 149000}, "delegate"),
    ({"next_needs_context": False, "artifacts_sufficient": True, "turn_count": 119, "context_tokens": 149000}, "fresh_start"),
    ({"next_needs_context": True, "turn_count": 10, "context_tokens": 20000}, "continue"),
    ({"next_needs_context": True, "turn_count": 118, "context_tokens": 20000}, "handoff"),
    ({"next_needs_context": True, "turn_count": 10, "context_tokens": 140000}, "handoff"),
    ({"next_needs_context": True, "turn_count": None, "context_tokens": None}, "handoff"),
]
```

Assert each result's action and persisted `phase`, `last_progress_at`, measured counts/ceilings/headroom. Add a test that `handoff` without a path leaves the attempt active but prints `handoff`; after an atomically written file beneath this run's `handoffs/`, repeating with `--handoff-path` sets `state: handed_off`. Reject a nonexistent path, symlink escape, path outside this run, `continue` at threshold, progress on terminal state, and a phase number that moves backward. Resume `handed_off` with matching owner/worktree plus exact `--resume-handoff` before its deadline and assert attempt remains 1 and becomes active. Also assert an explicit matching resume at/after that deadline records a stopped outcome retaining the worktree, then a distinct owner can launch attempt 2.

Add `test_combined_controller_demo_has_one_authoritative_outcome_per_issue`: initialize one run with three issues; finish one before its simulated delayed notification, expire one silent owner through `reconcile`, and hand off one at its injected context threshold. Reconcile from a fresh process and assert exactly one authoritative outcome/state per issue, no attempt number above 2, the delayed notification cannot replace the durable result, and the handed-off issue carries an existing resumable path.

- [ ] **Step 2: Run the focused tests and confirm the red state**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_state.py`

Expected: FAIL because `progress` and handoff-resume validation do not exist.

- [ ] **Step 3: Implement the closed-set decision and handoff transition**

Add `PHASE_ACTIONS = frozenset({"continue", "fresh_start", "handoff", "delegate"})` and one pure selector with the precedence in the Auto-resolved decision above. Boolean CLI values accept only literal `true`/`false`. Counts and ceilings are nonnegative integers; headroom must be smaller than its ceiling. `continue` requires both counts and strict `< ceiling - headroom` comparisons.

Persist the action and complete input snapshot on the attempt on every successful `progress`. For handoff finalization, resolve the path without following an escape outside `<run-dir>/handoffs`, require an existing regular non-symlink file, and then set `state: handed_off` and `handoff_path`. A matching `launch --resume-handoff` requires the stored exact path and reactivates the same attempt; it does not alter deadline or retry count.

- [ ] **Step 4: Verify the complete CLI behavior**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_state.py`

Expected: PASS, including all six issue-requested scenarios: delayed notification, owner death, same-worktree resume, retry cap, wall expiry, and pre-ceiling handoff.

Run: `git diff --check -- home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py`

Expected: exit 0 and no output.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(agents): enforce workflow phase budgets (#14)" -m "Co-Authored-By: Codex <codex@openai.com>"
```

### Task 3: Wire durable lifecycle into dispatcher, owner, and handoff skills

**Files:**
- Create: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/handoff/SKILL.md`

**Interfaces:**
- Consumes: Tasks 1–2 command forms and JSON output; existing from-issue compact return and ship handoff.
- Produces: exact lifecycle command ordering for all top-level owners, durable-first dispatcher reconciliation, executable phase gates, and durable handoff destination contract.

- [ ] **Step 1: Write failing skill-contract tests**

Create `unittest` tests that read each file and use an `assert_ordered(text, *anchors)` helper. Assert:

```python
self.assert_ordered(orchestrate, "init-run", "reconcile", "launch", "from-issue", "reconcile")
self.assert_ordered(owner_return_section, "--result-file", "workflow-state finish", "send the exact JSON")
self.assert_ordered(retry_section, "workflow-state reconcile", "workflow-state launch")
for field in ("issue", "state", "pr_url", "merge_sha", "issue_closed", "discussion_items", "notes"):
    self.assertIn(field, from_issue)
self.assertIn("workflow-state progress", from_issue)
self.assertIn("continue | fresh_start | handoff | delegate", from_issue)
self.assertIn(".superpowers/workflows/<run-id>/handoffs/", handoff)
```

Also assert the dispatcher no longer says “never poll” in a way that forbids event-driven durable reconciliation, no retry can be described without the helper cap, `AUTO.md` requires persistence at every phase checkpoint, early Phase-0 stops finish when lifecycle identity exists, and default interactive handoff still names `mktemp`.

- [ ] **Step 2: Run contract tests and confirm the red state**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL because current skills rely on notifications/advisory budgets and do not name `workflow-state`.

- [ ] **Step 3: Update `orchestrate-issues` in lifecycle order**

Keep it dispatcher-only. Add a “Durable run ledger” section before dispatch that creates or resumes a `run_id`, calls `init-run`, then `reconcile`. Rewrite dispatch to call `launch` before spawning and pass only `run_id`, attempt, owner, worktree, and the existing literal `from-issue <num> --auto` invocation. Require the child to persist and return the normalized compact result.

Rewrite wait behavior as notification-driven plus mandatory durable reconciliation on dispatcher resume, notification receipt, before retry, and before final drain. The dispatcher must never poll continuously, but it must reconstruct after a delayed/missing notification. Document durable-result precedence and ignore a stale older-attempt notification. Make the wall budget executable via `reconcile`; its stopped outcome retains the worktree and is not automatically relaunched without checking failure policy and `launch` cap. Replace prose retry counting with helper refusal behavior.

- [ ] **Step 4: Update `from-issue`, `AUTO.md`, and `handoff`**

In `from-issue`, resolve an optional lifecycle envelope from the caller (`run_id`, attempt, owner, worktree). Standalone interactive runs may initialize their own run only when durable orchestration is requested; existing direct use otherwise remains compatible.

At every phase boundary, call `workflow-state progress` with observable usage values and obey its exact action. Define each action operationally: continue; start fresh from committed artifacts; invoke `handoff` to the per-run destination then finalize `handed_off` and stop; or delegate the remainder to a fresh agent. If usage is unavailable, do not fabricate it. Replace the current advisory turn/context paragraph with this executable gate while retaining the 120/150k defaults.

Add one terminal-return procedure used by Phase-0 content stops, budget stops, execution failures, and Phase-7 success: assemble the exact compact result in a temporary JSON file, call `workflow-state finish`, then send stdout unchanged to the caller. Explicitly state that failure to persist is a failure to finish and must be surfaced, never reported as merged/completed. Phase 7 still uses its fresh ship agent, but from-issue owns the final durable write after receiving the ship report.

In `AUTO.md`, state that auto-resolving a checkpoint never skips `progress`; a returned handoff must be durably written/finalized and stop; terminal results must be written before notification.

In `handoff`, accept an optional caller-provided destination only under the current run's `.superpowers/workflows/<run-id>/handoffs/`, reject symlink/path escape, read before write, and atomically replace it. Retain `mktemp` as the default. Do not duplicate lifecycle JSON in the handoff document.

- [ ] **Step 5: Verify skill contract and diff scope**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: PASS; anchors prove init/reconcile/launch ordering, finish-before-send, all compact fields, four phase actions, and durable handoff path.

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_state.py`

Expected: PASS; prose edits did not change the CLI contract.

Run: `git diff --check -- home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/skills/handoff/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: exit 0 and no output.

- [ ] **Step 6: Commit**

```bash
git add home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/skills/handoff/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(agents): reconcile durable workflow outcomes (#14)" -m "Co-Authored-By: Codex <codex@openai.com>"
```

### Task 4: Install and verify the workflow lifecycle gate

**Files:**
- Modify: `home/common/agent-skills/default.nix`
- Modify: `justfile`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: completed helper and test modules from Tasks 1–3.
- Produces: executable `~/.agents/bin/workflow-state` after Home Manager activation and `just agent-workflow-tests` as the deterministic repository gate.

- [ ] **Step 1: Add the failing repository gate expectation**

Run: `just agent-workflow-tests`

Expected: FAIL with “Justfile does not contain recipe `agent-workflow-tests`”.

- [ ] **Step 2: Wire installation and the test recipe**

In `home/common/agent-skills/default.nix`, add an executable home file beside `context-map-lint`:

```nix
".agents/bin/workflow-state" = {
  source = ./scripts/workflow-state.py;
  executable = true;
};
```

In `justfile`, add:

```just
# Verify durable workflow lifecycle and skill contracts without agent/network timing.
agent-workflow-tests:
  python3 -m unittest -v \
    home/common/agent-skills/tests/test_workflow_state.py \
    home/common/agent-skills/tests/test_workflow_skill_contracts.py
```

- [ ] **Step 3: Run deterministic acceptance tests**

Run: `just agent-workflow-tests`

Expected: PASS. Output names tests for delayed notification recovery, owner expiry, same-worktree resume, retry cap/refusal, phase-boundary handoff, and durable handoff resume; zero failures/errors.

Run: `rg -n 'sleep|api.github.com|gh ' home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: no matches and exit 1, proving tests are deterministic and offline.

- [ ] **Step 4: Run repository build and scoped change gate**

Run: `just build`

Expected: exit 0; Nix evaluates/builds `darwinConfigurations.mbp.system` (the existing renamed-system warning is allowed).

Run: `git diff --check origin/main...HEAD -- .claude/specs/2026-08-13-durable-workflow-lifecycle-design.md .claude/plans/2026-08-13-durable-workflow-lifecycle.md home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/skills/handoff/SKILL.md home/common/agent-skills/default.nix justfile`

Expected: exit 0 and no output.

Run: `git diff --name-only origin/main...HEAD -- home/common/agent-skills home/common/claude-code/skills/orchestrate-issues justfile`

Expected: exactly the nine implementation/test paths listed in this plan; no host modules, fixture application, unrelated skills, or generated files.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/default.nix justfile
git commit -m "test(agents): gate durable workflow lifecycle (#14)" -m "Co-Authored-By: Codex <codex@openai.com>"
```

## Acceptance coverage

| Issue acceptance criterion | Planned proof |
|---|---|
| Owner writes terminal result before sending; missing/delayed notification recovers without redispatch | Task 1 durable finish/reconcile test; Task 3 ordered skill contract |
| Reconstructable attempt fields and resume/fresh identity | Task 1 state assertions and exact attempt schema |
| Same owner/worktree resume is free; one fresh retry; next refused and linked | Task 1 resume/retry tests and exit-3 refusal |
| Fixed wall expiry visibly stops/fails and preserves worktree | Task 1 injected-deadline reconcile test |
| Every phase boundary selects before 120/150k ceiling; durable resumable handoff | Task 2 threshold/action and handoff-resume tests; Task 3 from-issue/AUTO contract |
| Automated evaluations cover six scenarios and build succeeds | Task 4 `just agent-workflow-tests` and `just build` |
