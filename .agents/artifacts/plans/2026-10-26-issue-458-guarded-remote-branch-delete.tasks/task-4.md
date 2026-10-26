# Task 4: `orchestrate-control` spends direction on the first sweep

Spec § Direction is spent on the first sweep, § Acceptance evidence (AC3), § Test seams (orchestrate-control facts suite); per D4. After this task every `control` request `orchestrate-control step` builds carries `human_directed = session["human_directed"] and first_sweep`: an explicit-number session directs its first sweep, both calls of a chained first step included, and no later one; a label or milestone session never does. The session object, `start`'s output and the control request schema do not change. With Task 3 this closes AC3: a remainder or attempt that parks on a gated cause after the first sweep waits, and the session finalizes with its re-entry line.

**Files:**
- Modify: `python/agent_tools/orchestrate_control.py` (`control_request`, `control_rounds`)
- Modify: `tests/test_orchestrate_control.py` (`FactsTest`)
- Modify: `python/README.md` (the `orchestrate-control step` `control` paragraph)
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`_apply_one_issue_policy` docstring only)

**Interfaces:**
- Consumes: `StepInput(session, first_sweep, owners, contracts_due, refused_contracts)`; `control_rounds(args, bindings, request, facts, contracts)`, which builds the first request and, for a contract-only first reply, the chained second; `OrchestrateWorld.start(*argv)`, `.step(session, *, first_sweep=False, …)`, `.listing(flag, value, numbers)`, `.requests()` (every `workflow-state control` stdin, in call order).
- Produces: `control_request(b: Bindings, session: dict, tracker: list, forge: dict, worktrees: list, owners: list, pairs: Mapping[int, dict], *, human_directed: bool) -> dict`, whose `"human_directed"` member is that argument; `control_rounds` computes `directed = session["human_directed"] and request.first_sweep` once and passes `human_directed=directed` to both `control_request` calls.

**Invariants:**
- `human_directed` stays a required keyword with no default, so no caller sends the session value by accident.
- Every other request member, the call count and the chaining rule are unchanged; `test_the_request_carries_the_bound_policy_and_control_accepts_it` (an explicit session's `first_sweep=True` step, `human_directed` true) stays green unedited.
- No skill text changes (spec § Out of scope).

- [ ] **Step 1: Write the failing test**

`tests/test_orchestrate_control.py`, `FactsTest`, insert directly before `test_no_gh_child_sees_an_unset_variable`:

```python
    def test_direction_is_spent_on_the_first_sweep(self):
        """Issue 458 D4: an explicit session sends `human_directed` true only on its first
        sweep, both calls of a chained first step included; a label session never does."""
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        done, out = world.step(session, first_sweep=True)
        self.assertEqual((done.returncode, out["control_calls"]), (0, 2),
                         done.stdout + done.stderr)
        later, _ = world.step(session)
        self.assertEqual(later.returncode, 0, later.stdout + later.stderr)
        self.assertEqual([r["human_directed"] for r in world.requests()], [True, True, False])

        world = OrchestrateWorld(self)
        world.listing("--label", "agent:ready", [12, 14])
        session = world.start("--label", "agent:ready")["session"]
        for first_sweep in (True, False):
            done, _ = world.step(session, first_sweep=first_sweep)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual({r["human_directed"] for r in world.requests()}, {False})
```

- [ ] **Step 2: Run the test and watch it fail**

Run (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py -k test_direction_is_spent_on_the_first_sweep 2>&1 | tail -4'`
Expected: FAIL — `Lists differ: [True, True, True] != [True, True, False]`.

- [ ] **Step 3: Write the minimal implementation**

1. `python/agent_tools/orchestrate_control.py`: `control_request` takes the keyword-only `human_directed: bool` after `pairs` and returns it as `"human_directed"`; its docstring becomes `"""The interface-3 `control` request: the facts, the bound policy, the built pairs and `human_directed`, which only an explicit session's first sweep sets (issue 458 D4)."""`. In `control_rounds`, after `session, run_id = …`, add `directed = session["human_directed"] and request.first_sweep` and pass `human_directed=directed` to both `control_request(...)` calls.

2. `python/README.md`, the paragraph that begins `` `control` is called with `owners` as given. ``: insert after that first sentence, exactly:

   Each `control` request carries `human_directed` true only when the session's `human_directed` and `first_sweep` are both true, the chained second call of such a step included, and false otherwise, so an explicit session's direction is spent on its first sweep and a record that parks on a gated cause later in the session waits for the next invocation (issue 458 D4).

3. `home/common/agent-skills/scripts/workflow-state.py`, `_apply_one_issue_policy`'s docstring: replace

```
    owner always carries it, and an orchestrated sweep carries it exactly when
    the caller listed the issue numbers itself. A `--label`/`--milestone` sweep
    never does, so it leaves those parked and reports them.
```

with

```
    owner always carries it, and an orchestrated sweep carries it exactly when
    the caller listed the issue numbers itself, on the session's first sweep
    only (issue 458 D4). A `--label`/`--milestone` sweep never does, so it
    leaves those parked and reports them.
```

- [ ] **Step 4: Verify**

Run (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py 2>&1 | tail -4'`
Expected: `OK`.

Run (timeout 1800 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k test_an_undirected_sweep_parks_a_gated_remainder_until_a_directed_one 2>&1 | tail -4'`
Expected: `OK` (Task 3's half of AC3, re-run at this head).

Run: `bash -c 'test "$(git diff --numstat -- home/common/agent-skills/scripts/workflow-state.py | cut -f1,2)" = "$(printf "3\t2")"'`
Expected: exit 0 — the docstring's last two lines above became three (its first line is unchanged), and nothing else in `workflow-state.py` changed.

Run the Build.
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/orchestrate_control.py tests/test_orchestrate_control.py python/README.md home/common/agent-skills/scripts/workflow-state.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "fix(orchestrate-control): spend human direction on the first sweep (issue 458)" -m "<trailers>"
```
