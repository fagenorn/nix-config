# Workflow Lifecycle Hardening Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Stop the durable workflow lifecycle from erasing real results, self-cloning
past its phase budget, narrating its attempt budget, and stranding retries away from
the work they must resume.

**Architecture:** Four changes, each at the layer that owns the fact. Two new attempt
fields (`finished_at`, `result_source`) make a reaper-synthesized terminal record
distinguishable from an owner's report, so `command_finish` can preserve a late result
and supersede a provisional expiry. `select_phase_action` reorders so the phase budget
is consulted before delegation. `.claude/skills.config.json` plus two new
`resolve-bindings` keys give the attempt budget one authoritative home. The retry
worktree fix is a two-sided prose contract with no helper change, pinned by one CLI
test.

**Tech stack:** Python 3 stdlib only (`argparse`, `json`, `pathlib`, `datetime`);
`unittest` for tests; Markdown SKILL contracts; Nix + `just` for the build gate.

**Spec:** `.claude/specs/2026-08-17-workflow-lifecycle-hardening-design.md` — read it
before any task. It owns the decision ledger (D1–D21); this plan cites rows by ID.

## Global Constraints

- **Terminology, in every line of prose and every docstring this plan dictates
  (per D16):** **attempt budget** = the wall clock (`agentBudgetMinutes` →
  `deadline_at`, enforced by `reconcile` and `launch`). **Phase budget** = the turn
  and context ceilings that `select_phase_action` evaluates. "Ceiling" only ever means
  a phase-budget limit; "deadline" and "wall clock" only ever mean the attempt budget.
  Never write bare "budget" where either could be meant.
- `SCHEMA_VERSION` stays `1`; no migration is written (per D7).
- `PHASE_INPUT_FIELDS`, `validate_phase_inputs`, `RESULT_FIELDS`, `validate_result`,
  `ATTEMPT_STATES`, `RESULT_STATES`, `PHASE_ACTIONS` and the compact terminal-result
  schema are **unchanged**. `select_phase_action`'s signature is unchanged.
- `workflow-state launch --budget-minutes` stays `required=True` (per D12).
- Python: stdlib only, no new imports beyond what each file already has, no third-party
  dependencies. Match the file's existing style (module-level frozensets/tuples for
  closed sets, `raise WorkflowError(...)` for every rejection).
- Tests never import `workflow-state.py`; they invoke it as a subprocess and reopen
  `state.json`. `resolve-bindings` likewise runs as a subprocess.
- `pytest` is **not installed**. Every test command in this plan is `python3 -m
  unittest`, run from `home/common/agent-skills/`.
- Commits are SSH-signed and carry `Co-Authored-By: Claude Fable 5
  <noreply@anthropic.com>`. **Never** pass `--no-gpg-sign` or `-c commit.gpgsign=false`;
  surface a signing failure instead of working around it.
- Base commit for every scoped diff gate:
  `bdc1ecf6cadee6ad9d77edcfce3ca9dcef03ffb6`.

## Test seams

- **Lifecycle CLI seam** — `home/common/agent-skills/tests/test_workflow_state.py`.
  Subprocess the helper against a temp ledger root with injected `--now`; assert exit
  code, stdout JSON, and the reopened `state.json`.
- **Skill contract seam** — `home/common/agent-skills/tests/test_workflow_skill_contracts.py`.
  Prose anchors and `assert_ordered` chains over the two SKILL.md files and the eval
  corpus.
- **Binding resolver seam (new)** — `home/common/agent-skills/tests/test_resolve_bindings.py`.
  Subprocess `scripts/resolve-bindings` against a temp repo root, parse `key=value`
  lines. Follows `test_diff_scope.py`'s shape.
- **Build seam** — `just agent-workflow-tests`, then `just build`.

No other seam exists. A task that appears to need one is a plan bug, not an
implementer's call.

## Task index

| ID | Title | Files touched | Lane |
| --- | --- | --- | --- |
| Task 1 | Attempt records carry `finished_at` and `result_source` | `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` | full |
| Task 2 | A late finish preserves the owner's result and supersedes a provisional expiry | `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` | full |
| Task 3 | The phase gate consults the phase budget before delegation | `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` | full |
| Task 4 | The attempt budget becomes a resolved binding | `.claude/skills.config.json` (new), `home/common/agent-skills/scripts/resolve-bindings`, `home/common/agent-skills/tests/test_resolve_bindings.py` (new), `justfile` | full |
| Task 5 | A fresh retry reaches the prior worktree — helper behaviour pinned | `home/common/agent-skills/tests/test_workflow_state.py` | full |
| Task 6 | The two-sided retry and budget-provenance contract in skill prose | `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` | full |
| Task 7 | Amend the 2026-08-13 design and run the whole-change gate | `.claude/specs/2026-08-13-durable-workflow-lifecycle-design.md` | full |

Every task is `full`. Nothing here is mechanical: Tasks 1–3 and 5 change lifecycle
semantics and the durable public record, Task 4 introduces a configuration surface,
Task 6 changes a public skill contract and its grader, and Task 7 rewrites the accepted
semantic record of an existing design. Assigning a lighter lane to any of them would be
a plan bug.

## Decisions

The spec owns the ledger. Cited here: **D1** (lateness derived, not stored), **D2** (two
fields, closed source set), **D3** (`progress` stays strict), **D4** (provisional expiry,
narrow supersession), **D5** (gate order), **D6** (`delegate` does not reset the wall
clock), **D7** (no schema bump), **D8** (from-issue routes a deadline rejection), **D9**
(config carries only `orchestration`), **D10** (`agentBudgetMinutes: 180`, default 90),
**D11** (resolver emits both, degrades gracefully), **D12** (`--budget-minutes` stays
required), **D13** (no helper change for item 4), **D14** (dispatcher checks worktree
liveness only), **D15** (markers applied at execute time), **D16** (attempt vs phase
budget), **D17** (evals move with the skill).

Planning added **D18–D21** to the spec's ledger: the task split at the
schema/behaviour boundary and its consequences, the exact error strings, the resolver's
non-clobbering emission, and the whole-change gate's placement.

---

### Task 1: Attempt records carry `finished_at` and `result_source`

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, for Tasks 2, 3 and 5:
  - Module constant `RESULT_SOURCES = frozenset({"owner", "expiry", "superseded", "refused"})`.
  - `ATTEMPT_FIELDS` additionally contains `"finished_at"` and `"result_source"`.
  - `stop_attempt(attempt: dict[str, Any], *, reason: str, now: str, source: str) -> dict[str, Any]`
    — `now` is an already-formatted RFC3339 UTC string (the caller's `now`, not a
    `datetime`); `source` is a member of `RESULT_SOURCES`. It stamps
    `attempt["state"] = "stopped"`, `attempt["result"]`, `attempt["finished_at"] = now`,
    `attempt["result_source"] = source` and returns the result.
  - Every attempt dict created by `command_launch` carries `"finished_at": None,
    "result_source": None`.

**Invariants:**
- For every attempt: `finished_at is None` ⟺ `result is None` ⟺ `result_source is None`.
- `result_source`, when set, is a member of `RESULT_SOURCES`.
- `finished_at`, when set, parses as RFC3339 UTC and satisfies `started_at <= finished_at`.
  It is **deliberately not bounded above** by `deadline_at` — that unbounded upper end is
  the whole point of item 1 (per D1).
- `result_source == "expiry"` ⟹ `finished_at >= deadline_at`. An expiry cannot exist
  before the deadline it reports.
- Exactly one producing site per source value: `owner` ← `command_finish`; `expiry` ←
  `command_reconcile` and `command_launch`'s two deadline checks; `superseded` ←
  `command_launch`'s stop of the prior attempt before appending a fresh one; `refused` ←
  `command_launch`'s third-attempt refusal (per D2).
- `SCHEMA_VERSION` stays `1` (per D7).
- The refusal path's existing overwrite of `attempts[-1]`'s terminal result is
  **preserved unchanged** — it is a separate defect, explicitly out of scope. This task
  only stamps the two new fields there.

**Error strings this task introduces** (exact, per D19 — later tasks and tests assert
these substrings):

| Condition | Message |
| --- | --- |
| the null-triple is broken | `attempt result, finish time and result source must all be null or all be set` |
| `result_source` not in `RESULT_SOURCES` | `invalid attempt result source` |
| `finished_at` unparseable | `invalid attempt finish time` (produced by `parse_utc(value["finished_at"], "attempt finish time")`) |
| `finished_at < started_at` | `invalid attempt finish time order` |
| `result_source == "expiry"` and `finished_at < deadline_at` | `expiry finish time must not precede the attempt deadline` |

- [ ] **Step 1: Write the failing tests**

Append to `home/common/agent-skills/tests/test_workflow_state.py`. Follow the file's
existing helper conventions (temp ledger root, `run_cli`-style subprocess invocation,
reopening `state.json`) — read a neighbouring test first and mirror it exactly rather
than inventing a new harness.

Two changes plus one addition:

1. **Extend** `test_owner_death_expiry_stops_active_attempt_with_worktree`: after the
   existing assertions, add

```python
        self.assertEqual(attempt["result_source"], "expiry")
        self.assertEqual(attempt["finished_at"], "2026-08-13T20:10:00Z")
        self.assertGreaterEqual(attempt["finished_at"], attempt["deadline_at"])
```

2. **Extend** `test_cross_field_lifecycle_corruption_is_rejected_without_changes` with
   five new rows, following that test's existing parametrized shape (each row mutates an
   otherwise-valid persisted `state.json`, then asserts the next CLI call exits non-zero,
   prints the message, and leaves the file bytes byte-identical):

   | Label | Mutation of the terminal attempt | Expected message substring |
   | --- | --- | --- |
   | `terminal-without-finished-at` | set `finished_at` to `None`, leave `result` and `result_source` set | `must all be null or all be set` |
   | `nonterminal-with-result-source` | on an `active` attempt set `result_source` to `"owner"`, leave `result` and `finished_at` `None` | `must all be null or all be set` |
   | `unknown-result-source` | set `result_source` to `"reaper"` | `invalid attempt result source` |
   | `finished-at-before-start` | set `finished_at` to one second before `started_at` | `invalid attempt finish time order` |
   | `expiry-finished-before-deadline` | on an `expiry` attempt set `finished_at` to one second before `deadline_at` | `expiry finish time must not precede the attempt deadline` |

3. **Add** `test_superseding_retry_and_refusal_stamp_their_result_source`:

```python
    def test_superseding_retry_and_refusal_stamp_their_result_source(self):
        root = self.make_run()
        self.launch(root, issue=7, owner="owner-a", worktree="/tmp/wt-a",
                    now="2026-08-13T10:00:00Z")
        self.launch(root, issue=7, owner="owner-b", worktree="/tmp/wt-b",
                    now="2026-08-13T10:30:00Z")
        attempts = self.read_state(root)["issues"]["7"]["attempts"]
        self.assertEqual(attempts[0]["state"], "stopped")
        self.assertEqual(attempts[0]["result_source"], "superseded")
        self.assertEqual(attempts[0]["finished_at"], "2026-08-13T10:30:00Z")
        self.assertIsNone(attempts[1]["finished_at"])
        self.assertIsNone(attempts[1]["result_source"])

        code, _, err = self.launch_raw(root, issue=7, owner="owner-c",
                                       worktree="/tmp/wt-c",
                                       now="2026-08-13T11:00:00Z")
        self.assertNotEqual(code, 0)
        self.assertIn("attempts 1 and 2 already consumed", err)
        attempts = self.read_state(root)["issues"]["7"]["attempts"]
        self.assertEqual(attempts[1]["state"], "failed")
        self.assertEqual(attempts[1]["result_source"], "refused")
        self.assertEqual(attempts[1]["finished_at"], "2026-08-13T11:00:00Z")
```

Adapt the helper names (`make_run`, `launch`, `launch_raw`, `read_state`) to whatever
the file actually defines; do **not** add new helpers if equivalents exist.

- [ ] **Step 2: Run the tests and watch them fail**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_workflow_state -v 2>&1 | tail -25
```

Expected: FAIL — `KeyError: 'result_source'` on the expiry and supersede assertions; the
corruption rows pass their mutation in but the CLI exits 0 (or rejects with `invalid
attempt schema` rather than the specific message), so the assertions on the message text
fail.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/scripts/workflow-state.py`:

1. Add the module constant beside `RESULT_STATES`:

```python
RESULT_SOURCES = frozenset({"owner", "expiry", "superseded", "refused"})
```

2. Add `"finished_at"` and `"result_source"` to the `ATTEMPT_FIELDS` frozenset.

3. Change `stop_attempt` to the signature in **Interfaces** above. Its docstring must
   name the attempt budget explicitly, e.g. `"""Stamp a terminal stopped record.
   ``source`` says who ended the attempt; ``now`` is when the record was written, which
   for an ``expiry`` is at or after the attempt budget's ``deadline_at``."""`

4. Update all `stop_attempt` call sites to pass `now=now, source=...`:
   - `command_launch`, handed-off deadline check → `source="expiry"`
   - `command_launch`, active same-identity deadline check → `source="expiry"`
   - `command_launch`, the stop of `attempts[-1]` before appending a fresh attempt →
     `source="superseded"`
   - `command_reconcile` → `source="expiry"`
   - `command_finish`'s deadline branch → `source="expiry"` (Task 2 deletes this branch;
     leave it correct here so this task is green on its own)

5. In `command_launch`'s third-attempt refusal path, alongside the existing
   `latest["state"] = "failed"` / `latest["result"] = failed`, add
   `latest["finished_at"] = now` and `latest["result_source"] = "refused"`. Change
   nothing else about that path.

6. In `command_launch`'s new-attempt dict literal, add `"finished_at": None,
   "result_source": None`.

7. In `validate_attempt`, after the existing `result` block, add the four clauses of the
   **Invariants** section using the exact messages from the table above. Derive nothing
   from a stored label — mirror the file's existing style of re-deriving (per D1). The
   null-triple check must run before the per-field checks so a broken triple reports the
   triple message, not a field message.

- [ ] **Step 4: Verify**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_workflow_state 2>&1 | tail -5
```

Expected: `OK`. Test count is ≥ 26 (25 at the base commit, plus the new
`test_superseding_retry_and_refusal_stamp_their_result_source`). At this task's commit
the base-commit test `test_late_merged_finish_persists_canonical_stopped_expiry` **still
passes unchanged** — Task 2 reverses it.

Then confirm the closed set is genuinely closed and the field really landed:

```sh
python3 - <<'PY'
import json, subprocess
print(subprocess.run(["grep","-c","RESULT_SOURCES","scripts/workflow-state.py"],
                     capture_output=True,text=True).stdout.strip())
PY
```

Expected: at least `3` (definition, membership check, and at least one docstring or
comment reference).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(workflow-state): record who wrote each terminal result and when

Adds finished_at and result_source to every attempt record, with the closed
source set owner|expiry|superseded|refused and cross-field validation. Per D1/D2
of the workflow-lifecycle-hardening spec.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: A late finish preserves the owner's result and supersedes a provisional expiry

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes from Task 1: `RESULT_SOURCES`; `attempt["finished_at"]` and
  `attempt["result_source"]` present on every attempt;
  `stop_attempt(attempt, *, reason, now, source)`.
- Produces: no new names. `command_finish`'s observable contract changes — a `finish` at
  or after `deadline_at` now records the reported result instead of a synthetic
  `stopped`, and a `finish` on a latest attempt whose `result_source` is `"expiry"`
  overwrites that provisional record.

**Invariants:**
- `command_finish`'s rule order, exactly (per D4). `attempt` is
  `issue_state["attempts"][args.attempt - 1]`; `existing` is `attempt["result"]`;
  `outcome` is `issue_state["outcome"]`:
  1. `now_value < parse_utc(attempt["last_progress_at"], ...)` → raise
     `finish time must not move backward`. **Deliberately before rule 2**: a
     byte-identical replay carrying a clock that moved backward is a lie about when the
     work ended, not an idempotent retry, and rule 2 compares only the result object,
     which cannot see it.
  2. **Idempotent** — `existing == result and outcome == result` → return `result`, no
     state change. `finished_at` keeps the first write's value.
  3. **Supersede a provisional expiry** — when *all* hold:
     `args.attempt == len(issue_state["attempts"])` (this attempt is the issue's
     **latest**); `attempt["result_source"] == "expiry"`; `outcome == existing` — then
     set `attempt["state"]`, `attempt["result"]`, `attempt["finished_at"] = now`,
     `attempt["result_source"] = "owner"` and `issue_state["outcome"]`, and return the
     reported result.
  4. `existing is not None or outcome is not None` → raise
     `conflicting terminal result for issue {issue} attempt {attempt}` *(unchanged)*.
  5. `attempt["state"] != "active"` → raise `finish requires an active attempt`
     *(unchanged — this is what rejects a `handed_off` finish)*.
  6. Record the reported result with `finished_at = now`, `result_source = "owner"`.
     **The `now_value >= deadline_at` branch is deleted.**
- A `superseded`, `refused` or `owner` record is **never** supersedable.
- An **older** attempt's expiry is never supersedable once a newer attempt exists — rule
  3's latest-attempt guard is what enforces this.
- `retain_worktree` still appends the worktree to `stopped`/`failed` notes only. A
  preserved late `merged` result's `notes`, `pr_url`, `merge_sha` and `issue_closed` are
  stored **byte-for-byte as reported**.
- `command_progress` is **not touched** — it keeps its hard error at or after the
  deadline (per D3). The deadline keeps its teeth; it merely stops destroying finished
  work.
- After rule 3 fires, a repeat of the same call matches rule 2, so `finished_at` records
  the supersession, not the retry.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_workflow_state.py`:

**Reverse and rename** `test_late_merged_finish_persists_canonical_stopped_expiry` to
`test_late_merged_finish_preserves_the_owner_result`. Keep its existing setup (launch,
then `finish` a merged result at `2026-08-13T20:10:00Z`, past the attempt's
`deadline_at`). Replace its assertions with:

```python
        state = self.read_state(root)
        attempt = state["issues"]["7"]["attempts"][0]
        outcome = state["issues"]["7"]["outcome"]
        self.assertEqual(attempt["state"], "merged")
        self.assertEqual(attempt["result"]["state"], "merged")
        self.assertEqual(attempt["result"]["pr_url"], reported["pr_url"])
        self.assertEqual(attempt["result"]["merge_sha"], reported["merge_sha"])
        self.assertIs(attempt["result"]["issue_closed"], True)
        self.assertEqual(attempt["result"]["notes"], "")
        self.assertEqual(attempt["finished_at"], "2026-08-13T20:10:00Z")
        self.assertGreaterEqual(attempt["finished_at"], attempt["deadline_at"])
        self.assertEqual(attempt["result_source"], "owner")
        self.assertEqual(outcome, attempt["result"])
        self.assertEqual(stdout_json, attempt["result"])
```

(`reported` is the result dict the test wrote to the `--result-file`; `stdout_json` is
the parsed CLI stdout. Bind both from the existing setup rather than re-deriving.)

**Add** four tests:

```python
    def test_expiry_result_is_provisional_until_the_owner_reports(self):
        root = self.make_run()
        self.launch(root, issue=7, owner="owner-a", worktree="/tmp/wt-a",
                    now="2026-08-13T10:00:00Z")
        self.reconcile(root, now="2026-08-13T20:10:00Z")
        attempt = self.read_state(root)["issues"]["7"]["attempts"][0]
        self.assertEqual(attempt["state"], "stopped")
        self.assertEqual(attempt["result_source"], "expiry")

        merged = self.result_file(issue=7, state="merged",
                                  pr_url="https://example.test/pr/1",
                                  merge_sha="abc123", issue_closed=True,
                                  notes="merged after the deadline")
        code, out, _ = self.finish_raw(root, issue=7, attempt=1,
                                       result_file=merged,
                                       now="2026-08-13T20:20:00Z")
        self.assertEqual(code, 0)
        state = self.read_state(root)
        attempt = state["issues"]["7"]["attempts"][0]
        self.assertEqual(attempt["state"], "merged")
        self.assertEqual(attempt["result_source"], "owner")
        self.assertEqual(attempt["finished_at"], "2026-08-13T20:20:00Z")
        self.assertEqual(attempt["result"]["notes"], "merged after the deadline")
        self.assertEqual(state["issues"]["7"]["outcome"], attempt["result"])
        self.assertEqual(json.loads(out), attempt["result"])

        before = self.state_bytes(root)
        other = self.result_file(issue=7, state="failed", notes="conflicting")
        code, _, err = self.finish_raw(root, issue=7, attempt=1, result_file=other,
                                       now="2026-08-13T20:30:00Z")
        self.assertNotEqual(code, 0)
        self.assertIn("conflicting terminal result", err)
        self.assertEqual(self.state_bytes(root), before)

    def test_expired_older_attempt_cannot_supersede_after_a_fresh_retry(self):
        root = self.make_run()
        self.launch(root, issue=7, owner="owner-a", worktree="/tmp/wt-a",
                    now="2026-08-13T10:00:00Z")
        self.reconcile(root, now="2026-08-13T20:10:00Z")
        self.launch(root, issue=7, owner="owner-b", worktree="/tmp/wt-a",
                    now="2026-08-13T20:15:00Z")
        before = self.state_bytes(root)
        merged = self.result_file(issue=7, state="merged",
                                  pr_url="https://example.test/pr/1",
                                  merge_sha="abc123", issue_closed=True, notes="")
        code, _, err = self.finish_raw(root, issue=7, attempt=1, result_file=merged,
                                       now="2026-08-13T20:20:00Z")
        self.assertNotEqual(code, 0)
        self.assertIn("conflicting terminal result", err)
        self.assertEqual(self.state_bytes(root), before)

    def test_refused_third_attempt_result_is_not_supersedable(self):
        root = self.make_run()
        self.launch(root, issue=7, owner="owner-a", worktree="/tmp/wt-a",
                    now="2026-08-13T10:00:00Z")
        self.launch(root, issue=7, owner="owner-b", worktree="/tmp/wt-b",
                    now="2026-08-13T10:30:00Z")
        self.launch_raw(root, issue=7, owner="owner-c", worktree="/tmp/wt-c",
                        now="2026-08-13T11:00:00Z")
        before = self.state_bytes(root)
        merged = self.result_file(issue=7, state="merged",
                                  pr_url="https://example.test/pr/1",
                                  merge_sha="abc123", issue_closed=True, notes="")
        code, _, err = self.finish_raw(root, issue=7, attempt=2, result_file=merged,
                                       now="2026-08-13T11:10:00Z")
        self.assertNotEqual(code, 0)
        self.assertIn("conflicting terminal result", err)
        self.assertEqual(self.state_bytes(root), before)

    def test_finish_rejects_time_before_last_progress(self):
        root = self.make_run()
        self.launch(root, issue=7, owner="owner-a", worktree="/tmp/wt-a",
                    now="2026-08-13T10:00:00Z")
        self.progress(root, issue=7, attempt=1, phase=3, now="2026-08-13T11:00:00Z")
        before = self.state_bytes(root)
        merged = self.result_file(issue=7, state="merged",
                                  pr_url="https://example.test/pr/1",
                                  merge_sha="abc123", issue_closed=True, notes="")
        code, _, err = self.finish_raw(root, issue=7, attempt=1, result_file=merged,
                                       now="2026-08-13T10:30:00Z")
        self.assertNotEqual(code, 0)
        self.assertIn("finish time must not move backward", err)
        self.assertEqual(self.state_bytes(root), before)
```

Adapt helper names (`make_run`, `launch`, `launch_raw`, `reconcile`, `progress`,
`finish_raw`, `result_file`, `read_state`, `state_bytes`) to the file's actual helpers.
If `state_bytes` does not exist, read the `state.json` path with
`Path(...).read_bytes()` inline; do not add a helper for one use.

For `test_finish_rejects_time_before_last_progress`, pass the `progress` call the
complete phase-budget input set (`--turn-count 10 --context-tokens 20000
--turn-ceiling 120 --context-ceiling 150000 --turn-headroom 2 --context-headroom 10000`
plus the three booleans) exactly as the file's other `progress` helpers do, choosing
booleans that yield `continue`.

- [ ] **Step 2: Run the tests and watch them fail**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_workflow_state -v 2>&1 | tail -30
```

Expected: FAIL —
`test_late_merged_finish_preserves_the_owner_result` sees `"stopped"` where it asserts
`"merged"`; `test_expiry_result_is_provisional_until_the_owner_reports` gets exit ≠ 0
with `conflicting terminal result` on the first `finish`;
`test_finish_rejects_time_before_last_progress` gets exit 0.

- [ ] **Step 3: Write the minimal implementation**

Rewrite `command_finish`'s conflict/deadline block in `workflow-state.py` to the exact
rule order in **Invariants**. Three concrete edits:

- Insert the backward-time guard immediately after `attempt` and the `retain_worktree`
  normalization are bound, before `existing`/`outcome` are consulted:

```python
        if now_value < parse_utc(attempt["last_progress_at"], "attempt progress time"):
            raise WorkflowError("finish time must not move backward")
```

- Between the idempotent-return branch and the `conflicting terminal result` raise,
  insert the supersession branch guarded by all three conditions of rule 3. On success it
  writes `attempt["state"] = result["state"]`,
  `attempt["result"] = copy.deepcopy(result)`, `attempt["finished_at"] = now`,
  `attempt["result_source"] = "owner"`,
  `issue_state["outcome"] = copy.deepcopy(result)`, `state["updated_at"] = now`, and
  returns `(result, True)`.
- Delete the `if now_value >= parse_utc(attempt["deadline_at"], ...)` branch entirely,
  including its `stop_attempt` call. In the final record path add
  `attempt["finished_at"] = now` and `attempt["result_source"] = "owner"`.

Add a docstring or comment on `command_finish` naming the semantics in the plan's
terminology: a finish at or after the **attempt budget's** deadline records the owner's
reported result, and the expiry record `reconcile` writes is provisional. Do **not**
mention the phase budget here — `command_finish` never sees it.

`command_progress` is not edited.

- [ ] **Step 4: Verify**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_workflow_state 2>&1 | tail -5
grep -c 'attempt deadline expired' scripts/workflow-state.py
```

Expected: `OK`. The `grep -c` must be **strictly lower** than at the base commit (base:
run `git show bdc1ecf6cadee6ad9d77edcfce3ca9dcef03ffb6:home/common/agent-skills/scripts/workflow-state.py | grep -c 'attempt deadline expired'`
to read it) — the deleted `finish` branch is one call site gone. Also confirm the name
is gone:

```sh
grep -c 'test_late_merged_finish_persists_canonical_stopped_expiry' tests/test_workflow_state.py
```

Expected: `0`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "fix(workflow-state): a late finish no longer erases the owner's result

command_finish records the reported terminal result at or after the attempt
budget's deadline, supersedes a provisional expiry on the latest attempt, and
rejects a finish time that moves backward. Per D1/D3/D4.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: The phase gate consults the phase budget before delegation

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–2 (independent of the attempt fields).
- Produces: no new names. `select_phase_action`'s signature, parameter names and return
  domain are all **unchanged**; only the rule order inside it changes.

**Invariants:**
- The new rule sequence, exactly (per D5):
  1. `artifacts_sufficient and not next_needs_context` → `"fresh_start"`
  2. `turn_count is None or context_tokens is None` → `"handoff"`
  3. `turn_count >= turn_ceiling - turn_headroom or context_tokens >= context_ceiling - context_headroom` → `"handoff"`
  4. `remainder_self_contained` → `"delegate"`
  5. `not next_needs_context` → `"handoff"`
  6. → `"continue"`
- **`delegate` implies measured phase-budget usage strictly below both ceilings.** This
  is the observability the issue asks for and it is re-derivable:
  `validate_attempt`'s existing `select_phase_action(**phase_inputs) != phase_action`
  check already refuses any persisted record that claims otherwise. No new phase input
  and no new stored field.
- **`delegate` does not reset the attempt wall clock** (per D6) — an explicit
  non-change. Nothing in this task reads `deadline_at` or any wall-clock value.
- `PHASE_INPUT_FIELDS` and `validate_phase_inputs` are unchanged.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_workflow_state.py`:

**Revise** `test_progress_action_precedence_and_complete_inputs_are_persisted`: its case
1 (`remainder_self_contained: True`, `turn_count: 119`, `context_tokens: 149000`) flips
its expected action from `"delegate"` to `"handoff"`. The other five cases are unchanged
— verified against the new order; do not touch them.

**Add**:

```python
    def test_delegate_requires_measured_usage_below_both_ceilings(self):
        root = self.make_run()
        self.launch(root, issue=7, owner="owner-a", worktree="/tmp/wt-a",
                    now="2026-08-13T10:00:00Z")
        out = self.progress_raw(root, issue=7, attempt=1, phase=3,
                                now="2026-08-13T10:05:00Z",
                                turn_count=10, context_tokens=20000,
                                next_needs_context=True, artifacts_sufficient=False,
                                remainder_self_contained=True)
        self.assertEqual(json.loads(out)["phase_action"], "delegate")

        out = self.progress_raw(root, issue=7, attempt=1, phase=4,
                                now="2026-08-13T10:10:00Z",
                                turn_count=None, context_tokens=None,
                                next_needs_context=True, artifacts_sufficient=False,
                                remainder_self_contained=True)
        self.assertEqual(json.loads(out)["phase_action"], "handoff")

        out = self.progress_raw(root, issue=7, attempt=1, phase=5,
                                now="2026-08-13T10:15:00Z",
                                turn_count=10, context_tokens=140000,
                                next_needs_context=True, artifacts_sufficient=False,
                                remainder_self_contained=True)
        self.assertEqual(json.loads(out)["phase_action"], "handoff")

        out = self.progress_raw(root, issue=7, attempt=1, phase=6,
                                now="2026-08-13T10:20:00Z",
                                turn_count=118, context_tokens=20000,
                                next_needs_context=True, artifacts_sufficient=False,
                                remainder_self_contained=True)
        self.assertEqual(json.loads(out)["phase_action"], "handoff")
```

Case 2 selects `handoff`, so the attempt would become `handed_off` only if a
`--handoff-path` is supplied; supply none, matching how the file's existing precedence
test drives `handoff` without finalizing. If the file's `progress` helper does not accept
`turn_count=None`/`context_tokens=None` as "omit the flag", extend it minimally to do so
rather than adding a second helper.

The ceiling arithmetic these cases pin, with the standard ceilings
(`--turn-ceiling 120 --context-ceiling 150000 --turn-headroom 2 --context-headroom
10000`): the turn threshold is `120 - 2 = 118` and the context threshold is
`150000 - 10000 = 140000`; both rules are `>=`, so `118` and `140000` are *at* the
ceiling and must yield `handoff`, while `10`/`20000` is below both and must yield
`delegate`.

- [ ] **Step 2: Run the tests and watch them fail**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_workflow_state -v 2>&1 | tail -25
```

Expected: FAIL — every case of `test_delegate_requires_measured_usage_below_both_ceilings`
that expects `handoff` returns `delegate`, and the revised case 1 of the precedence test
returns `delegate`.

- [ ] **Step 3: Write the minimal implementation**

In `select_phase_action`, move the `if remainder_self_contained: return "delegate"` block
from first position to sit **after** the unknown-usage check and the ceiling check,
producing exactly the six-rule order in **Invariants**. Add a docstring stating the
contract in the plan's terminology:

```python
    """Select the phase-boundary action from the phase budget and the three booleans.

    The phase budget is the turn and context ceilings with their headrooms; this
    function never sees the attempt budget's wall clock, and ``delegate`` does not
    reset it. ``fresh_start`` comes first because a disposable conversation with
    sufficient artifacts is the cheapest transition at any budget level. Unknown
    usage and at-ceiling usage both yield ``handoff`` before ``delegate`` is
    considered, so a persisted ``delegate`` implies measured usage strictly below
    both ceilings.
    """
```

Change nothing else in the function and nothing in `validate_phase_inputs`.

- [ ] **Step 4: Verify**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_workflow_state 2>&1 | tail -5
python3 - <<'PY'
import re
src = open("scripts/workflow-state.py").read()
body = src[src.index("def select_phase_action"):]
body = body[:body.index("\ndef ")]
order = re.findall(r'return "(\w+)"', body)
assert order == ["fresh_start", "handoff", "handoff", "delegate", "handoff", "continue"], order
print("gate order OK:", order)
PY
```

Expected: `OK` from unittest, and `gate order OK: ['fresh_start', 'handoff', 'handoff',
'delegate', 'handoff', 'continue']`. At the base commit that assertion fails, because
`delegate` is returned first.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "fix(workflow-state): check the phase budget before selecting delegate

select_phase_action now returns handoff for unknown or at-ceiling turn/context
usage before remainder_self_contained is consulted, so a persisted delegate
implies measured usage below both ceilings. Per D5/D6.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: The attempt budget becomes a resolved binding

**Files:**
- Create: `.claude/skills.config.json`
- Create: `home/common/agent-skills/tests/test_resolve_bindings.py`
- Modify: `home/common/agent-skills/scripts/resolve-bindings`
- Modify: `justfile`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, for Task 6's prose:
  - `resolve-bindings` emits two additional `key=value` lines in its existing sorted
    output: `agentBudgetMinutes=<int>` and `maxParallel=<int>`.
  - `DEFAULTS` gains `"agentBudgetMinutes": "90"` and `"maxParallel": "2"`.
  - Helper `positive_int_str(value: object, default: str, *, key: str) -> str`.
  - `.claude/skills.config.json` at the repository root with exactly one section.

**Invariants:**
- The committed config carries **only** the `orchestration` section (per D9). Nothing
  that `resolve-bindings` already auto-detects correctly from git is pinned — pinning a
  fact git owns creates a second home that drifts on a rename or a fork.
- The committed value is `agentBudgetMinutes: 180`; the *default* in `DEFAULTS` stays
  `90` (per D10). 180 is double the reaped default, sized against `just build` at 3–13
  minutes per task under nix-daemon contention across a 7-phase run.
- `positive_int_str` accepts only a plain `int` that is `> 0`. A `bool` is **not**
  accepted (`isinstance(True, int)` is `True` in Python — reject `bool` explicitly). A
  numeric **string** such as `"90"` is not accepted.
- A present-but-invalid value prints exactly one `resolve-bindings: ...` diagnostic to
  **stderr**, falls back to the documented default, and keeps **exit status 0** (per
  D11). Breaking every skill's binding resolution over one optional orchestration key is
  not an option.
- Absent keys fall through unchanged: adding this file must not alter any binding the
  resolver already emits (per D20). This is a gate, asserted in Step 1.
- Existing emitted keys, their values and the sorted output order are otherwise
  untouched.

- [ ] **Step 1: Write the failing test**

Create `home/common/agent-skills/tests/test_resolve_bindings.py`, following
`tests/test_diff_scope.py`'s subprocess-a-script shape (read it first for the
`SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / ...` idiom and its
`subprocess.run` conventions).

```python
"""Contract tests for scripts/resolve-bindings.

Runs the resolver as a subprocess against temporary repository roots and parses
its `key=value` lines. Covers the attempt budget (`agentBudgetMinutes`, the
wall-clock allowance for one attempt) and `maxParallel`.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resolve-bindings"
REPO_ROOT = Path(__file__).resolve().parents[3]


def run(root: Path) -> tuple[int, dict[str, str], str]:
    proc = subprocess.run(
        ["python3", str(SCRIPT), "--repo-root", str(root)],
        capture_output=True, text=True, timeout=30,
    )
    bindings = dict(
        line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line
    )
    return proc.returncode, bindings, proc.stderr


class ResolveBindingsTest(unittest.TestCase):
    def make_root(self, config: object | None) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / ".git").mkdir()
        if config is not None:
            (root / ".claude").mkdir()
            (root / ".claude" / "skills.config.json").write_text(
                json.dumps(config), encoding="utf-8"
            )
        return root

    def test_defaults_apply_without_a_config_file(self):
        code, bindings, err = run(self.make_root(None))
        self.assertEqual(code, 0)
        self.assertEqual(bindings["agentBudgetMinutes"], "90")
        self.assertEqual(bindings["maxParallel"], "2")
        self.assertEqual(err, "")

    def test_configured_orchestration_values_are_emitted(self):
        root = self.make_root(
            {"orchestration": {"agentBudgetMinutes": 240, "maxParallel": 5}}
        )
        code, bindings, err = run(root)
        self.assertEqual(code, 0)
        self.assertEqual(bindings["agentBudgetMinutes"], "240")
        self.assertEqual(bindings["maxParallel"], "5")
        self.assertEqual(err, "")

    def test_invalid_values_fall_back_with_a_diagnostic_and_exit_zero(self):
        for bad in (0, -5, "90", True, 1.5, None):
            with self.subTest(value=bad):
                root = self.make_root({"orchestration": {"agentBudgetMinutes": bad}})
                code, bindings, err = run(root)
                self.assertEqual(code, 0)
                self.assertEqual(bindings["agentBudgetMinutes"], "90")
                if bad is not None:
                    self.assertIn("resolve-bindings:", err)
                    self.assertIn("agentBudgetMinutes", err)

    def test_adding_the_config_does_not_disturb_the_other_bindings(self):
        plain = self.make_root(None)
        configured = self.make_root(
            {"orchestration": {"agentBudgetMinutes": 180, "maxParallel": 2}}
        )
        _, a, _ = run(plain)
        _, b, _ = run(configured)
        a.pop("repoRoot"), b.pop("repoRoot")
        a.pop("agentBudgetMinutes"), b.pop("agentBudgetMinutes")
        a.pop("maxParallel"), b.pop("maxParallel")
        self.assertEqual(a, b)

    def test_the_committed_repository_config_sets_the_attempt_budget(self):
        code, bindings, _ = run(REPO_ROOT)
        self.assertEqual(code, 0)
        self.assertEqual(bindings["agentBudgetMinutes"], "180")
        self.assertEqual(bindings["maxParallel"], "2")
        committed = json.loads(
            (REPO_ROOT / ".claude" / "skills.config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(list(committed), ["orchestration"])
        self.assertEqual(committed["orchestration"]["agentBudgetMinutes"], 180)


if __name__ == "__main__":
    unittest.main()
```

Note `None` in the invalid loop: a JSON `null` is a *present but empty* value that must
fall back silently like every other absent key, so the diagnostic is asserted only for
the non-`None` cases.

`REPO_ROOT` is `tests/` → `agent-skills/` → `common/` → `home/` … — verify the
`parents[N]` index resolves to the worktree root before writing the rest (print it once
and check), and correct N if the directory depth differs.

- [ ] **Step 2: Run the test and watch it fail**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_resolve_bindings -v 2>&1 | tail -20
```

Expected: FAIL — `KeyError: 'agentBudgetMinutes'` in every case; the committed-config
case additionally fails because `.claude/skills.config.json` does not exist.

- [ ] **Step 3: Write the minimal implementation**

1. Create `.claude/skills.config.json` at the worktree root, exactly:

```json
{
  "orchestration": {
    "agentBudgetMinutes": 180,
    "maxParallel": 2
  }
}
```

2. In `home/common/agent-skills/scripts/resolve-bindings`:
   - Add `"agentBudgetMinutes": "90"` and `"maxParallel": "2"` to `DEFAULTS`.
   - Add, beside `as_bool_str` and mirroring its shape:

```python
def positive_int_str(value: object, default: str, *, key: str) -> str:
    """Return a positive int as a string, else the default with one diagnostic.

    A present-but-invalid value degrades to the documented default and keeps exit
    status 0: one bad optional orchestration key must not break binding resolution
    for every skill.
    """
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        print(
            f"resolve-bindings: ignoring invalid orchestration.{key} "
            f"{value!r}; using {default}",
            file=sys.stderr,
        )
        return default
    return str(value)
```

   - Read the section once, `orchestration = config.get("orchestration") or {}`, beside
     the existing `naming`/`commit` reads.
   - Add two entries to the `bindings` dict:

```python
        "agentBudgetMinutes": positive_int_str(
            orchestration.get("agentBudgetMinutes"),
            DEFAULTS["agentBudgetMinutes"],
            key="agentBudgetMinutes",
        ),
        "maxParallel": positive_int_str(
            orchestration.get("maxParallel"),
            DEFAULTS["maxParallel"],
            key="maxParallel",
        ),
```

   - Extend the module docstring with one sentence naming the new keys and the
     terminology: `agentBudgetMinutes` is the **attempt budget** — the wall-clock
     allowance for one orchestrated attempt. Do not mention the phase budget; the
     resolver has nothing to do with it.

3. In `justfile`, add `home/common/agent-skills/tests/test_resolve_bindings.py` to the
   `agent-workflow-tests` recipe's file list, keeping the existing continuation-backslash
   style and the list's existing order convention.

- [ ] **Step 4: Verify**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_resolve_bindings 2>&1 | tail -3
python3 scripts/resolve-bindings --repo-root /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening | grep -E '^(agentBudgetMinutes|maxParallel)='
grep -c 'test_resolve_bindings' /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/justfile
```

Expected: `OK`; the resolver prints exactly `agentBudgetMinutes=180` and `maxParallel=2`;
the justfile grep prints `1`. At the base commit the resolver prints neither line.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills.config.json home/common/agent-skills/scripts/resolve-bindings home/common/agent-skills/tests/test_resolve_bindings.py justfile
git commit -m "feat(resolve-bindings): give the attempt budget one authoritative home

Adds agentBudgetMinutes and maxParallel to the resolved binding set with the
documented defaults (90, 2), a graceful-degradation guard for invalid values,
and a repository config pinning the attempt budget at 180 minutes. Per D9/D10/D11.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: A fresh retry reaches the prior worktree — helper behaviour pinned

**Files:**
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes from Task 1: `attempt["result_source"]` on every attempt record.
- Produces: no code. This task adds the CLI test that the Task-6 prose contract rests on.

**Invariants:**
- **No `workflow-state` code change** (per D13). If any assertion below fails, that is a
  finding to report — not a licence to edit the helper. The behaviour was verified
  against the live helper at the base commit; this task pins it so the prose contract in
  Task 6 cannot silently rot.
- `launch` with a **new owner handle** and the **prior attempt's recorded worktree**
  creates attempt 2 with that exact worktree, `prior_attempt: 1`, `state: "active"`.
  Neither `validate_attempt` nor `validate_state` constrains worktree uniqueness across
  attempts.
- `launch` with the **same owner** and the same worktree instead returns attempt 1's
  stored terminal outcome without appending an attempt — the resume-identity rule working
  as intended. **The identity that decides fresh-vs-resume is the owner handle, not the
  workspace.**

- [ ] **Step 1: Write the failing test**

```python
    def test_fresh_retry_may_reuse_the_prior_attempt_worktree(self):
        root = self.make_run()
        shared = "/tmp/wt-issue-7"
        self.launch(root, issue=7, owner="owner-a", worktree=shared,
                    now="2026-08-13T10:00:00Z")
        self.reconcile(root, now="2026-08-13T20:10:00Z")
        first = self.read_state(root)["issues"]["7"]["attempts"][0]
        self.assertEqual(first["state"], "stopped")
        self.assertEqual(first["result_source"], "expiry")
        self.assertEqual(first["worktree"], shared)

        out = self.launch_json(root, issue=7, owner="owner-b", worktree=shared,
                               now="2026-08-13T20:15:00Z")
        self.assertEqual(out["attempt"], 2)
        self.assertEqual(out["worktree"], shared)
        self.assertEqual(out["prior_attempt"], 1)
        self.assertEqual(out["state"], "active")
        attempts = self.read_state(root)["issues"]["7"]["attempts"]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[1]["worktree"], attempts[0]["worktree"])

        self.finish(root, issue=7, attempt=2,
                    result_file=self.result_file(
                        issue=7, state="stopped", notes="blocked"),
                    now="2026-08-13T20:30:00Z")
        before = self.state_bytes(root)
        out = self.launch_json(root, issue=7, owner="owner-b", worktree=shared,
                               now="2026-08-13T20:40:00Z")
        self.assertEqual(out["state"], "stopped")
        self.assertEqual(len(self.read_state(root)["issues"]["7"]["attempts"]), 2)
        self.assertEqual(self.state_bytes(root), before)
```

`launch_json` is whatever helper the file uses to parse `launch` stdout as JSON; reuse
it, do not add one. The final block pins the resume-identity half: the **same** owner
plus the same worktree returns the stored outcome and appends nothing.

- [ ] **Step 2: Run the test and watch it fail**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_workflow_state.WorkflowStateTest.test_fresh_retry_may_reuse_the_prior_attempt_worktree -v 2>&1 | tail -15
```

(Substitute the file's actual `TestCase` class name.)

Expected: FAIL — `AttributeError` / `NameError` for the not-yet-written test, and, once
written, it must **pass immediately** because no helper change is needed. That is the
point: the falsifiable observation here is not "it currently fails" but "the helper
already behaves this way, and this test will fail loudly the day someone adds a worktree
uniqueness constraint". Confirm falsifiability by temporarily changing `owner="owner-b"`
to `owner="owner-a"` in the second `launch_json` and watching the `attempt == 2`
assertion fail; then change it back.

- [ ] **Step 3: Write the minimal implementation**

None. Do not edit `scripts/workflow-state.py` in this task (per D13). If the test does
not pass as written, stop and report the discrepancy rather than adapting the helper —
the spec's item-4 solution assumes this behaviour, and a change here would invalidate the
prose contract in Task 6.

- [ ] **Step 4: Verify**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_workflow_state 2>&1 | tail -3
git diff --stat HEAD -- scripts/workflow-state.py
```

Expected: `OK`; and the `git diff --stat` prints **nothing** — this task touches no
helper code.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_workflow_state.py
git commit -m "test(workflow-state): pin fresh-retry reuse of the prior attempt worktree

A new owner handle with the prior attempt's recorded worktree records attempt 2
at that worktree; the same owner returns the stored outcome. Per D13.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: The two-sided retry and budget-provenance contract in skill prose

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes from Task 4: the resolver emits `agentBudgetMinutes` and `maxParallel`, so the
  prose can name `~/.agents/bin/resolve-bindings` as the source rather than "the config".
- Consumes from Task 5: the pinned helper behaviour the retry contract rests on.
- Produces: the prose anchors that the revised and added contract tests assert.

**Invariants:**
- The dispatcher's role boundary holds (per D14): it may run **one**
  `git worktree list --porcelain` scan — worktree *metadata*, not issue content. The
  four-signal resume inspection stays `from-issue` Phase 0's job and is not duplicated.
- `from-issue` Phase 1 keeps **"never choose another path"** and **"never remove unknown
  contents"**. The envelope identity stays bound to its exact path through shipping and
  cleanup.
- Every sentence uses the D16 terminology: `--budget-minutes` and `agentBudgetMinutes`
  are the **attempt budget**; the `--turn-ceiling`/`--context-ceiling` block is the
  **phase budget**. Do not write bare "budget" in any sentence this task touches.
- §3's first-attempt reservation wording ("reserve a collision-free exact absolute
  worktree path", "does not create the worktree", "configured worktree root") is
  **unchanged**.
- Eval 1's "reserve a collision-free absolute worktree path" sentence **stays** — it
  describes the first-attempt path, which is unchanged.
- The eval corpus must move in the same commit as the prose (per D17): an eval is the
  graded statement of correct behaviour, so a stale one actively fails a correct run.

**Prose to write.** These are the semantics the shipped code and the shipped contract
actually have as of Tasks 1–5; write them to say exactly that.

1. **`orchestrate-issues` §1**, replacing the `Read orchestration.maxParallel from the
   config (default 2)` sentence:

   > - Resolve `maxParallel` from `~/.agents/bin/resolve-bindings` (default **2**;
   >   `orchestration.maxParallel` in `.claude/skills.config.json` overrides). More
   >   parallelism mostly buys merge conflicts: every ship-issue merge serializes on the
   >   integration branch anyway.

2. **`orchestrate-issues` §3**, appended to the paragraph containing
   `--budget-minutes <budget>`:

   > `<budget>` is the **attempt budget** — the wall-clock allowance for one attempt —
   > and comes from `agentBudgetMinutes` in `~/.agents/bin/resolve-bindings`
   > (`orchestration.agentBudgetMinutes` in `.claude/skills.config.json`, default 90).
   > Do not restate a number here; read the resolver.

3. **`orchestrate-issues` §4 Budget guard**, replacing the
   `(default 90 min; orchestration.agentBudgetMinutes overrides)` parenthetical:

   > **Attempt-budget guard:** if an agent has been silent past its attempt budget (the
   > wall-clock allowance resolved as `agentBudgetMinutes`; see §3 — the resolver is the
   > single source, so no number is repeated here), `workflow-state reconcile` persists a
   > provisional `stopped` outcome that retains the worktree and carries
   > `result_source: "expiry"`. A later `finish` from that attempt's own owner supersedes
   > it, so a `stopped` outcome seen here may still be replaced by the owner's real
   > result. Surface it for inspection. It is not automatically relaunched: first apply
   > the failure policy, then let `workflow-state launch` enforce the fresh-attempt cap.

4. **`orchestrate-issues` §5 failure policy, bullet 3** (the fresh-retry bullet),
   replacing "a fresh owner/worktree":

   > 3. Only when resume is impossible — the attempt is terminal and the durable outcome
   >    still permits a retry — launch a fresh attempt with a **fresh owner identity**.
   >    The workspace does not decide fresh-vs-resume; the owner handle does. Choose the
   >    worktree like this:
   >    - Read the prior attempt's recorded `worktree` from the reconciled ledger
   >      (`reconcile`, which §5 already mandates before every retry, prints it).
   >    - Check whether that exact path is still a live git worktree checked out on this
   >      issue's branch — one `git worktree list --porcelain` scan. This is worktree
   >      metadata, not issue content, so the role boundary holds; the deeper
   >      resume-signal inspection stays the owner's Phase-0 job.
   >    - Live → pass that exact path as `--worktree`, so the retry owner reaches the
   >      existing work instead of an empty tree.
   >    - Not live (removed, or checked out on another branch) → reserve a fresh
   >      collision-free path exactly as §3 does for a first attempt.
   >    Either way, spawn only from the accepted attempt. The helper allows attempts 1
   >    and 2 only and refuses a third fresh attempt; record its durable failed outcome
   >    instead of counting in prose.

5. **`from-issue` Phase 1**, replacing the "If the path is occupied or mismatched…"
   sentence with a three-way decision on the envelope's exact absolute path:

   > When a lifecycle envelope exists, use its exact absolute `worktree`, and decide by
   > what is actually there:
   > - **Absent** from both the filesystem and `git worktree list` → create it from
   >   `origin/<integration-branch>`.
   > - **Already a git worktree checked out on this issue's branch** → **adopt it**:
   >   `cd` in and continue. Do not re-create it, do not move it, do not reset it. This
   >   is the normal shape of a retry, whose dispatcher hands back the prior attempt's
   >   worktree. Phase 0's resume-signal inspection governs what to do with its contents.
   > - **Anything else** — occupied by a non-worktree path, or a worktree checked out on
   >   a different branch → fail the attempt through the terminal return procedure,
   >   naming both the envelope path and what was found, so the dispatcher can correct
   >   the reservation.
   >
   > Never remove unknown contents and never choose another path. The envelope identity
   > stays bound to this path through shipping and cleanup.

6. **`from-issue` phase-gate section**, appended after "Obey the returned action
   exactly" (per D8):

   > If `workflow-state progress` is rejected because the attempt budget's deadline has
   > passed, that is not a harness fault and not a reason to retry it: go straight to the
   > terminal return procedure and record your truthful state with `workflow-state
   > finish`, which preserves a result reported at or after the deadline. Persistence
   > precedes notification.

7. **`evals/evals.json`**, two `expected_output` passages:
   - Eval 2, failure-policy case (c): replace "issues a fresh owner AND fresh worktree
     (attempt 2)" with wording that grades a **fresh owner identity**, plus the prior
     attempt's recorded worktree when it is still a live worktree on the issue's branch,
     else a freshly reserved path.
   - Eval 1's `orchestration.maxParallel` (default 2) "from config" and eval 2's
     "default 90 min, `orchestration.agentBudgetMinutes` overrides" both become
     "resolved through `~/.agents/bin/resolve-bindings`", keeping the same numbers.
   - Keep the JSON valid and its existing formatting/indentation style.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (read it first for
its `assert_ordered` helper and the constants naming the two SKILL.md paths — note
`orchestrate-issues` lives under `home/common/claude-code/skills/`, not under
`agent-skills/`):

**Revise** `test_lifecycle_phase_one_uses_exact_reserved_attempt_worktree` — replace the
`occupied or mismatched` anchor with the new wording, keeping `never choose another path`
and `fail the attempt`:

```python
        self.assert_ordered(
            FROM_ISSUE,
            [
                "use its exact absolute `worktree`",
                "Absent",
                "checked out on this issue's branch",
                "adopt it",
                "Do not re-create it, do not move it, do not reset it",
                "checked out on\n>   a different branch",
                "fail the attempt through the terminal return procedure",
                "never choose another path",
            ],
        )
```

(Anchor substrings must be copied from the prose actually written in Step 3 — adjust for
line wrapping; prefer short single-line fragments over any anchor that spans a newline.)

**Extend** `test_dispatcher_resumes_recorded_attempt_before_fresh_launch` through the
prior-worktree retry step:

```python
        self.assert_ordered(
            ORCHESTRATE,
            [
                "workflow-state reconcile",
                "resume before fresh",
                "--resume-handoff",
                "fresh owner identity",
                "prior attempt's recorded `worktree`",
                "git worktree list --porcelain",
                "reserve a fresh",
                "refuses a third fresh attempt",
            ],
        )
```

**Add** three tests:

```python
    def test_orchestrate_resolves_the_attempt_budget_from_the_resolver(self):
        self.assert_ordered(
            ORCHESTRATE,
            ["--budget-minutes <budget>", "attempt budget",
             "agentBudgetMinutes", "resolve-bindings"],
        )
        self.assertIn("resolve `maxParallel` from `~/.agents/bin/resolve-bindings`",
                      ORCHESTRATE.lower().replace("resolve `maxparallel`",
                                                  "resolve `maxParallel`".lower()))

    def test_from_issue_routes_a_deadline_rejected_progress_to_the_terminal_return(self):
        self.assert_ordered(
            FROM_ISSUE,
            ["Obey the returned action exactly",
             "attempt budget's deadline has passed",
             "terminal return procedure",
             "Persistence precedes notification"],
        )

    def test_orchestrate_eval_grades_the_prior_worktree_retry(self):
        raw = EVALS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        expected = " ".join(
            case["expected_output"] for case in iter_expected_output(data)
        )
        self.assertNotIn("fresh worktree", expected)
        self.assertIn("fresh owner identity", expected)
        self.assertIn("prior attempt's recorded worktree", expected)
        self.assertIn("resolve-bindings", expected)
        self.assertIn("reserve a collision-free absolute worktree path", expected)
```

Simplify the `maxParallel` assertion in the first test to a plain
`self.assertIn("resolve `maxParallel` from `~/.agents/bin/resolve-bindings`", ORCHESTRATE)`
— the case-folding above is over-clever; drop it. `iter_expected_output` is whatever
traversal `test_ship_issue_eval_restates_the_gate_boundary_it_grades` already uses over
the eval JSON; reuse that precedent rather than writing a new walker, and define
`EVALS_PATH` alongside the existing SKILL.md path constants.

- [ ] **Step 2: Run the tests and watch them fail**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_workflow_skill_contracts -v 2>&1 | tail -25
```

Expected: FAIL — every new anchor (`adopt it`, `prior attempt's recorded worktree`,
`attempt budget`, `resolve-bindings` in `orchestrate-issues`) is absent, and
`assertNotIn("fresh worktree", expected)` fails because eval 2 still grades it.

- [ ] **Step 3: Write the implementation**

Apply passages 1–7 above to the three files. Preserve each file's existing heading
structure, list markers, and line-wrapping width; do not reflow untouched paragraphs.
After editing the eval file, confirm it still parses:
`python3 -c "import json,sys; json.load(open(sys.argv[1]))" <evals path>`.

- [ ] **Step 4: Verify**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
python3 -m unittest tests.test_workflow_skill_contracts 2>&1 | tail -3
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening
grep -c 'fresh worktree' home/common/claude-code/skills/orchestrate-issues/evals/evals.json
grep -c 'occupied or mismatched' home/common/agent-skills/skills/from-issue/SKILL.md
```

Expected: `OK`; both greps print `0`. At the base commit both print ≥ `1`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/claude-code/skills/orchestrate-issues/evals/evals.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(skills): hand a retry the prior worktree and resolve the attempt budget

orchestrate-issues §5.3 passes the prior attempt's live worktree with a fresh
owner identity; from-issue Phase 1 adopts an envelope worktree already on the
issue's branch; §1/§3/§4 and the evals resolve the attempt budget through
resolve-bindings. Per D8/D11/D14/D17.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Amend the 2026-08-13 design and run the whole-change gate

**Files:**
- Modify: `.claude/specs/2026-08-13-durable-workflow-lifecycle-design.md`

**Interfaces:**
- Consumes: the shipped behaviour of Tasks 1–6. Each marker below asserts semantics that
  must be **true of the code at this commit**; before writing a marker, confirm the claim
  against the implementation, and correct the marker (and report it) if the code differs.
- Produces: the amended accepted record. Nothing consumes it programmatically.

**Invariants:**
- Markers are **appended inline** to the named sentences (per D15, following issue 32's
  D8/D9 convention). Nothing in the 2026-08-13 design is deleted, rewritten or
  reordered; no other clause changes.
- Each marker leads with the amending issue and spec name, exactly as dictated.
- This task lands **last** so the markers are atomic with the shipped field names — an
  abandoned branch must never leave the old spec asserting behaviour that does not exist.

**The four markers, verbatim:**

1. Under **"Attempt schema and identity"**, after the JSON block's paragraph:

   > (**amended by issue 33's workflow-lifecycle-hardening spec, D1/D2** — every attempt
   > also carries `finished_at` and `result_source`, and a fresh retry may reuse the
   > prior attempt's worktree path; the identity that distinguishes a resume from a fresh
   > retry is the owner handle, not the workspace.)

2. Under **"Lifecycle state machine"**, after "All terminal transitions preserve the
   worktree path":

   > (**amended by issue 33's workflow-lifecycle-hardening spec, D2/D4** — a `finish` at
   > or after the deadline records the owner's reported result rather than a synthetic
   > expiry; the expiry result written by `reconcile` is provisional and is superseded by
   > a later owner report on the same latest attempt.)

3. Under **"Notification reconciliation"**, on the bullet beginning "An active or
   handed-off attempt at/after its deadline becomes `stopped`":

   > (**amended by issue 33's workflow-lifecycle-hardening spec, D4** — this stopped
   > result is provisional: it carries `result_source: "expiry"` and a later `finish`
   > from that attempt's owner replaces it.)

4. Under **"Executable phase-boundary budget decision"**, on the numbered action list:

   > (**amended by issue 33's workflow-lifecycle-hardening spec, D5** — this list
   > originally evaluated `delegate` first; the ceiling and unknown-usage checks now
   > precede it, so `delegate` is selected only with measured usage below both ceilings.
   > The fixed wall deadline is unchanged: `delegate` does not reset it.)

- [ ] **Step 1: Confirm each marker matches the shipped code**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening/home/common/agent-skills
grep -n 'finished_at\|result_source' scripts/workflow-state.py | head -20
python3 - <<'PY'
import re
src = open("scripts/workflow-state.py").read()
body = src[src.index("def select_phase_action"):]
body = body[:body.index("\ndef ")]
print(re.findall(r'return "(\w+)"', body))
PY
```

Expected: both fields present in `ATTEMPT_FIELDS`, in `validate_attempt`, in
`stop_attempt` and in `command_finish`; the gate order prints `['fresh_start',
'handoff', 'handoff', 'delegate', 'handoff', 'continue']`. Any mismatch means a marker
would be false — fix the marker text (or report the code gap) before Step 2.

- [ ] **Step 2: Apply the four markers**

Locate each named heading with `grep -n` and append the marker to the sentence or list
item named, as a parenthetical paragraph immediately following it. Change nothing else in
the file.

- [ ] **Step 3: Verify the markers landed and nothing else moved**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening
grep -c "amended by issue 33's workflow-lifecycle-hardening spec" .claude/specs/2026-08-13-durable-workflow-lifecycle-design.md
git diff --numstat bdc1ecf6cadee6ad9d77edcfce3ca9dcef03ffb6..HEAD -- .claude/specs/2026-08-13-durable-workflow-lifecycle-design.md
```

Expected: exactly `4`; and the `--numstat` shows **0 deletions** (additions only) for
that file — the amendment convention forbids rewriting the accepted record.

- [ ] **Step 4: Whole-change gate**

```sh
cd /Users/anis/tmp/nix-config/.claude/worktrees/issue-33-workflow-lifecycle-hardening
just agent-workflow-tests 2>&1 | tail -5
```

Expected: `OK` with a test count **strictly greater than 53** (53 at the base commit;
this plan adds ≥ 11 tests across Tasks 1–6 and reverses one).

Then, **once** (it is slow — 3–13 minutes under nix-daemon contention from sibling
worktrees; do not run it per task):

```sh
just build 2>&1 | tail -20
```

Expected: the build succeeds. `home/common/agent-skills/default.nix` installs each script
individually (`.agents/bin/workflow-state` ← `scripts/workflow-state.py`,
`.agents/bin/resolve-bindings` ← `scripts/resolve-bindings`) and `tests/` is not
deployed, so the new test module needs no Nix change — only the `agent-workflow-tests`
recipe, already done in Task 4. Every test runs the **repo source**, not `~/.agents/bin`;
the deployed copies only change on `just switch`, which is not part of this
verification.

Finally, confirm the change touched exactly the files this plan owns:

```sh
git diff --stat bdc1ecf6cadee6ad9d77edcfce3ca9dcef03ffb6..HEAD -- \
  .claude/skills.config.json \
  home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/scripts/resolve-bindings \
  home/common/agent-skills/tests/test_workflow_state.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  home/common/agent-skills/tests/test_resolve_bindings.py \
  home/common/agent-skills/skills/from-issue/SKILL.md \
  home/common/claude-code/skills/orchestrate-issues/SKILL.md \
  home/common/claude-code/skills/orchestrate-issues/evals/evals.json \
  justfile \
  .claude/specs/2026-08-13-durable-workflow-lifecycle-design.md
```

Expected: all eleven paths appear. (This is a scoped pathspec, not a commit-range shape
assertion: the spec and plan artifact commits and any ship-time sync merge also land in
the range and are not this gate's business.)

- [ ] **Step 5: Commit**

```bash
git add .claude/specs/2026-08-13-durable-workflow-lifecycle-design.md
git commit -m "docs(specs): amend the 2026-08-13 lifecycle design for issue 33

Four inline markers: the two new attempt fields and worktree-reusing retries,
the preserved late finish, the provisional expiry, and the reordered phase gate.
Per D15.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
