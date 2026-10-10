# Test-harness prep for the attempt identity migration — design

Issue: https://github.com/fagenorn/nix-config/issues/346 (prepares https://github.com/fagenorn/nix-config/issues/337).

## Triage

Input: `{"signals": {"contract_change": {"value": "no", "evidence": "test-only: harness helpers inside two test files, no product interface changes"}, "concurrency_or_persistence": {"value": "no", "evidence": "no product code touched; tests keep today's ledger bytes and run ids"}, "open_design_questions": {"value": "no", "evidence": "issue fixes helper names, shapes and bodies from commit 6ae38b0c"}, "criteria_shape": {"value": "hit", "evidence": "five acceptance criteria, one verified only by diff review"}}, "paths": ["home/common/agent-skills/tests/test_workflow_state.py", "home/common/agent-skills/tests/test_delivery_workflow.py"]}`
Verdict: `{"hits":["criteria_shape"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

The #337 branch (`worktree-issue-337-orchestrated`, head `6ae38b0c`) is green but cannot be review-packaged: its `-U10` diffs of `test_workflow_state.py` (74203 B) and `test_delivery_workflow.py` (73665 B) exceed the D29 per-file target of 60000 B. Most of those bytes are one-per-test call-site rewrites, not lifecycle semantics. A reviewer of #337 should see only the helper bodies and assertions that really change.

## Solution

Land on `main`, in those two test files only, the behaviour-neutral half of `6ae38b0c`'s sweep: the shared harness helpers under the branch's names and signatures, with bodies that reproduce today's behaviour, and the existing tests routed through them. #337 then rebases and changes only helper bodies and the assertions whose expectations really move (schema 8, binding, minting).

## Decisions

**`LifecycleHarness` (`test_workflow_state.py`)**

| Helper | Body on main |
| --- | --- |
| `_as_legacy(state, version, *, keep_delivery=False, handle=None)` | as today; `handle` sets `run_id`; the `transaction_id` pop for `version < 8` lands (no-op today) |
| `store_root`, `tree_snapshot()` | verbatim from the branch |
| `install_legacy(state, handle, version=7)` | verbatim from the branch: run dir, workflows `.gitignore` `*\n`, empty `state.lock`, `self.run_id = handle`, `write_state(_as_legacy(..., handle=handle))` |
| `assert_bound(state)` | asserts `schema_version == 7` only |
| `init_run(*, now=DEFAULT_NOW)` | identity tuple `("--run-id", self.run_id)`; `now=None` omits `--now`; `self.run_id` read back from the reply (per D2) |
| `_legacy_finish_input(stored)` | `return self._as_legacy(stored, 2)`; used by `finish` and `concurrent_finish` |
| `direct_run_id(issue, sequence)` | `f"direct-{issue}-{sequence:06d}"` |
| `run_dirs()` | verbatim: sorted names of directories under `workflows` |
| `mint_direct_ledger(state, issue, sequence, prior_run)` | creates the dir and an empty `state.lock`, writes `{**state, "run_id": direct_run_id(...)}` as compact sorted JSON plus newline (today's hand-built bytes), returns the dir; `prior_run` unused (per D4) |

Call sites routed, as the issue lists them: literal `direct-<n>-00000k` replies and paths go through `direct_run_id`; `direct-73-*` glob/prefix listings go through `run_dirs()`; the two hand-built second direct ledgers go through `mint_direct_ledger`; the `write_state(_as_legacy(...))` legacy installs (prior-schema reconcile helper, schema 1/2/4/5/6 upgrade and hybrid tests, `ProgressMarkerTest`, `WorkerRegistryTest`, `LaneSchemaTest`) go through `install_legacy(state, "orchestrate-<issue>", version)` with the branch's added `assert_bound` calls; `run_id` is read back from `init-run` output in the stable-lock/state test, the reserved-ids test and `LedgerClockSeamTest.init_without_time(key)` (with the branch's `glob("*/state.json")` assertions); and the non-direct and zero-sequence phase-gate replies use `self.run_id`.

**`test_delivery_workflow.py`**

- `BuilderHarness.runs` (a dict), `run_of(label)` = `self.runs.get(label, label)`, `mint_run(key, *, now=NOW)` = `init-run --run-id key`, read back into `self.run_id` and `self.runs[key]`, returning the `--repo-root`/`--run-id` argument tuple.
- `ContractLifecycleTest.write_run(label, attempts, *, schema=7)` registers `self.runs[label] = label` and writes under that run id. `control`, `legacy_finish` and every `--run-id "<label>"` / `.superpowers/workflows/<label>` site (chain, orch, legacy, v2, forge-v2, forge-wait, orch-fail, `spawn_contracted`, `HelperInputTest` "inputs") go through `run_of` / `mint_run`.
- `direct_runs(issue)` scans `*/state.json` for ledgers holding `issue` (branch text).
- `DeliveryAdmissionTest`: each `init-run` (admission, legacy-contractless, orchestrated, refusal, recovery-control, dispatch-wire) reads the run id back and later calls use it; `remainder_sweeps(root, home, key)` returns `(control, checkpoint, run_id)` and its five callers unpack it; the transact-on-legacy test uses an `orchestrate-151` ledger.
- `LedgerClockTest`'s direct skew test asserts `self.run_dirs() == [self.run_id]`.

Text reuse: every routed line and helper signature is copied from `6ae38b0c` so #337's rebase is mechanical. A docstring is copied when it is true on main; where it describes core minting or binding, main gets a one-line docstring true today (per D1).

**Size discipline.** Each file's `git diff -U10 origin/main` must stay at or below 60000 B, and replaying `6ae38b0c`'s final contents of each file over this change's head must leave a `-U10` diff at or below 60000 B; both numbers are recorded in the PR (per D5).

## Test seams

The two existing test modules and their harness classes (`LifecycleHarness`, `BuilderHarness`, `ContractLifecycleTest`, `DeliveryAdmissionTest`) are the only seams; the tests keep driving `workflow-state` through its CLI and importable functions exactly as today. No new test file, fixture module or product hook. Verification is the full `just agent-workflow-tests` suite (both files plus their dependents) and the two byte measurements per file.

## Out of scope

- Everything on the issue's "Stays in #337" list: `agent_tools.attempt_identity` / `attempt_store` / `TransactionStore` imports, `ORCHESTRATED` / `TRANSACTION`, `--creation-key`, `init_run`'s dialect choice, `direct_state_path`'s index lookup, the store `copytree` in `copy_ledger_root`, schema 7 → 8 literals and `transaction_id` in expected ledgers, `identity=` / `schema_version=` arguments, `LedgerRefused`, the D14 bound-refusal assertions, `write_run`'s `orchestrate-<issue>-r<n>` mapping, the legacy-inputs/survive renames and `LedgerClockTest.run_cli`.
- Any product change under `scripts/`, `python/` or other tests; any `review-package` or D29 budget change.
- Rebasing or editing the #337 branch itself.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Helper names, signatures and routed call-site lines are copied from `6ae38b0c`; a docstring is copied only when it is true on main, otherwise main gets a one-line true docstring that #337 later rewrites with the body | Issue "reuse its text; keep its names so #337's rebase is mechanical"; the-bar: a test states what it really checks | Verbatim branch docstrings naming transactions and D12/D21 minting: they would describe behaviour main does not have |
| D2 | `init_run` lands without the `creation_key` parameter and always passes `--run-id self.run_id`, but already reads `self.run_id` back and honours `now=None` | Issue lists `--creation-key` and `init_run`'s dialect choice under "Stays in #337" | Landing `creation_key=None` as an inert parameter: an unused interface main cannot honour |
| D3 | AC2's "run ids unchanged" covers ids the product produces or derives (direct ids, `init-run` replies, phase-gate replies), which keep today's values. Test-chosen fixture names the issue explicitly routes (the `install_legacy` handles `orchestrate-<issue>`, `init_without_time` keys `clock-seam` / `empty-override`, the `orchestrate-151` transact-on-legacy ledger) take the branch's names; every such test reads the id back and no assertion pinned the old literal | Issue's routing list names these handles; "orchestrate-" has no meaning on main (only `^direct-N-NNNNNN$` is reserved) | Keeping `self.run_id` handles: #337 would then rewrite each site again, returning bytes to its diff and endangering AC5 |
| D4 | `mint_direct_ledger` and `direct_run_id` reproduce today's bytes and literals exactly; `prior_run` is accepted and ignored, and the state's own `prior_run` is kept as today's hand-built ledgers keep it | Issue's main-compatible bodies; AC2 "paths and bytes unchanged" | Writing `prior_run` into the ledger now: changes ledger bytes on main |
| D5 | If `test_workflow_state.py`'s own `-U10` diff exceeds 60000 B, the pure literal-to-`direct_run_id` replacements are left to #337 first (smallest value per byte), and each dropped site is named in the PR | Issue's explicit fallback; issue estimates ~56.8 KB for this file and ~20 KB headroom in #337's remainder | Splitting this issue further, or trimming helper definitions, which #337's mechanical rebase needs |
| D6 | A branch `assert_bound` call lands only where main's ledger is schema 7 at that point (an added check, never a loosened one); a call on a ledger main leaves below 7, and any expectation that `install_legacy`'s extra run directory would change, stays in #337 | AC2 "no assertion removed, loosened or skipped"; the-bar "Tests that can fail" | Landing every branch call and weakening `assert_bound` to fit: an assertion that cannot fail |
| D7 | AC2 gets a mechanical proxy per file beside the diff review: `def test_` and `skip` counts equal to base, `self.assert`/`.assert_called` line count not below base, and no forbidden #337 text added; any routed site whose branch form fails on main (a stricter `run_dirs()`/glob check, the branch `direct_runs` body) stays in #337 and is named in the PR | AC2 "no assertion removed, loosened or skipped" is the triage's review-only criterion; the-bar "Tests that can fail"; D6's rule for `assert_bound` generalised | Diff review alone: no falsifiable per-task gate; weakening a branch assertion to pass on main: loosens what #337 will check |
| D8 | Where a branch read-back would make an echo assertion compare the reply with itself, main keeps the read-back and adds one pin of today's literal (reserved-ids test: `assertEqual(zero_id, "direct-73-000000")`); #337 drops the pin when it changes minting | Task 2 review (plan-mandated finding); AC2 "no assertion loosened" governs over the plan's verbatim read-back | Land the read-back alone: makes the zero-sequence echo check tautological on main |
