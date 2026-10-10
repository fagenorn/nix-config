# Task 4: Regression floor — the existing suites on minted and legacy-dialect runs

**Files:**
- Modify: `home/common/agent-skills/tests/test_workflow_state.py`
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py`
- Modify: `home/common/agent-skills/tests/test_host_admission.py`
- Modify: `home/common/agent-skills/tests/test_delivered_control.py`
- Modify: `home/common/agent-skills/tests/test_admission_replay.py`
- Modify: `tests/test_launch_scope.py`
- Modify: `tests/test_launch_commit.py`

No product file changes in this task. If a suite can only pass by changing `workflow-state.py`, `workflow_delivery.py` or a package module, stop and report it as a plan bug (BLOCKED) with the failing test name: that is a behaviour regression of Tasks 2–3, not sweep work.

**Interfaces:**
- Consumes: harness `init_run(creation_key=...)`, `install_legacy(state, handle, version=7)`, `_as_legacy(..., handle=)`, `direct_run_id(issue, sequence)`, `store_root`, `tree_snapshot()` (Tasks 2–3); `attempt_identity.RunIdentity`; `workflow-state`'s `validate_state(value, *, run_id, identity, schema_version=8)`, `SCHEMA_VERSION == 8`.
- Produces: nothing new. Every pre-existing test keeps its name and its lifecycle assertion.

**Invariants (the only permitted edits, D12, D19):**
1. **Run ids.** A free-form run id (`issue-14-test`, `replay`, `admission`, `run`, any other non-dialect literal) becomes either a `init-run --creation-key <key>` run whose minted handle the test reads back (from `self.run_id` after `init_run`, or the reply's `run_id`), or — where the test is about a pre-existing ledger (migration from schemas 1–6, legacy shapes, hand-written states) — a legacy-dialect handle installed with `install_legacy` / `_as_legacy(..., handle=...)`. Use `orchestrate-14` for the harness's issue-14 shapes and `orchestrate-<issue>` generally; use `direct-<issue>-<seq6>` only where the test is about a direct run.
2. **Ordering consequences of (1).** A value computed from `self.run_id` before `init_run` (e.g. `test_launch_scope`'s `self.registry`, any `state_path` captured early) is computed after it.
3. **Minted direct handles.** An expected `direct-<issue>-<seq6>` for a run that `direct-owner` creates becomes `self.direct_run_id(issue, seq)`; a path built from it follows. Expected `prior_run` values become the predecessor's handle the same way.
4. **Schema number.** An assertion of the current schema (`7`) becomes `8`; a hand-built current-schema state gains `"transaction_id"`: for a ledger on disk, the transaction id that the run's own binding requires (build such states by reading an `init_run` ledger and editing it, never by inventing an id); for a pure `validate_state` call that never touches the store, any `rel_` UUIDv7 literal, e.g. `"rel_0190f0e0-0000-7000-8000-000000000000"`.
5. **Validator arguments.** `workflow.validate_state(x, run_id=r)` becomes `workflow.validate_state(x, run_id=r, identity=ai.RunIdentity("orchestrated", None, None))` (or the direct identity where the state is a direct run's); a `select_phase_action(run_id=...)` call becomes `select_phase_action(direct=...)` with the boolean the run id used to imply.
6. **Legacy-migration tests** (schemas 1–6 → current) assert the migrated document is schema 8 with `transaction_id` equal to `TransactionStore(self.store_root).lookup(<the handle's key>)` (`from agent_tools.transaction_core import TransactionStore`); the rest of each assertion is unchanged.
7. `test_admission_replay` keeps its committed baseline byte-for-byte: `git diff --quiet eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7..HEAD -- home/common/agent-skills/tests/fixtures/admission-replay/baseline.json` exits 0. Only its run id lines change.
8. Nothing is skipped, deleted or weakened: no `skipTest`, no removed assertion, no loosened equality. A test that asserted a refusal of a free-form id at `init-run` (e.g. the reserved-direct cases near the existing `init-run` refusals) keeps its refusal: if the refusal reason changed from "reserved" to "not initialized", that test is about `--run-id` on a missing run and its expected message is updated, which is a D12 change — name it in the commit body.

- [ ] **Step 1: Run the suites and record the red set**

Run (each with a ≥ 900 s timeout):
`PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_admission_replay.py tests/test_launch_scope.py tests/test_launch_commit.py > "$SCRATCH/floor-red.log" 2>&1; tail -5 "$SCRATCH/floor-red.log"`
(`$SCRATCH` is the directory `launch-scope scratch` printed.) Expected: `FAILED (...)` — the red window Tasks 2–3 opened. Extract the failing test ids with `grep -E '^(FAIL|ERROR):' "$SCRATCH/floor-red.log" | sort -u > "$SCRATCH/floor-red.txt"`; that list is this task's worklist.

- [ ] **Step 2: Sweep file by file**

Apply invariants 1–8, one file at a time, re-running only that file's suite after each (`-k` to the class you edited for speed). Prefer fixing a shared helper (harness fixture builders, `setUp`) over editing each test; the harness edits in Tasks 2–3 already cover `init_run` and `acquire_direct`.

- [ ] **Step 3: Verify**

Run the Step 1 command again, writing `floor-green.log`.
Expected: `OK` on the last line; `grep -cE '^(FAIL|ERROR):' "$SCRATCH/floor-green.log"` prints `0` (exit 1 is the passing case for `grep -c`; check the printed number). Then:
`PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_migration.py tests/test_attempt_identity.py` — OK.
`git diff --stat HEAD~1..HEAD -- home/common/agent-skills/scripts python` after the commit prints nothing (no product change).
`git diff --quiet eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7..HEAD -- home/common/agent-skills/tests/fixtures/admission-replay/baseline.json` exits 0.
`git grep -n 'skipTest\|@unittest.skip' -- <the seven files>` shows no line that `git diff <task-start>..HEAD` added (`git diff <task-start>..HEAD -- <the seven files> | grep -c '^+.*skip'` prints `0`).

- [ ] **Step 4: Commit**

Stage only the seven files, then `launch-commit … -- -m "test: run the lifecycle suites on minted and legacy-dialect runs (#337)"`, listing in the body each test whose expected message changed under invariant 8, with the session trailers.
