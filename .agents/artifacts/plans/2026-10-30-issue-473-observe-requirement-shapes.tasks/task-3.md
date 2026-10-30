# Task 3: `direct-owner --help` names `expects`

Spec § Decisions (`direct-owner --help`); § Test seams (Help names `expects`); per D1. Give the `direct-owner` subparser a `description`. This follows the precedent of `build-delivery` and `owner-liveness` in the same `build_parser`.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`build_parser`, the `direct_owner = subparsers.add_parser("direct-owner")` line, about line 5624)
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (new class `DirectOwnerHelpTest`)

**Interfaces:**
- Consumes: Task 1's `attempt_observations.EXPECTS_MEMBERS`, Task 2's `expects` on observe replies, and `LifecycleHarness.run_cli(*args, ok=True)`. The in-process runner returns argparse's `--help` output with exit 0, as `test_public_cli_exposes_direct_owner_but_not_retired_commands` already relies on.
- Produces: help text only. No argument, default or handler changes.

**Invariants:**
- `workflow-state direct-owner --help` exits 0. Its stdout names `expects` and each of `slot`, `members`, `example` and `build` as whole words.
- The description is ASCII. It names only reply kinds `direct-owner` can print (`observe`, `owner`, `delivery_remainder`, `terminal`), and it says nothing about the request shape, which `acquire-direct.md` holds (spec § Out of scope).

- [ ] **Step 1: Write the failing test**

Add after `DirectObserveExpectsTest`:

```python
class DirectOwnerHelpTest(LifecycleHarness, unittest.TestCase):
    """Issue 473 AC2: `direct-owner --help` names where an observation's shape is described."""

    def test_direct_owner_help_names_expects_and_its_members(self):
        completed = self.run_cli("direct-owner", "--help")
        self.assertEqual(completed.returncode, 0)
        for name in ("expects", *attempt_observations.EXPECTS_MEMBERS):
            with self.subTest(name=name):
                self.assertRegex(completed.stdout, rf"\b{name}\b")
```

- [ ] **Step 2: Run the test and watch it fail**

Run (Unit run): `test_workflow_state.py -k DirectOwnerHelpTest`
Expected: FAIL in five subtests. The base help lists only `--repo-root` and `--request-file`.

- [ ] **Step 3: Add the description**

Replace the `add_parser("direct-owner")` call with:

```python
    direct_owner = subparsers.add_parser("direct-owner", description=(
        "Acquire, resume or replay one issue's direct owner from one interface-2 "
        "request read from --request-file, and print one observe, owner, "
        "delivery_remainder or terminal reply. Each requirement of an observe reply "
        "carries expects: slot names the request member its answer fills, members maps "
        "each member of that answer to its meaning, example is one illustrative answer, "
        "and build is null or the workflow-state command that builds the answer."))
```

- [ ] **Step 4: Verify**

Unit run: `test_workflow_state.py -k DirectOwnerHelpTest -k test_public_cli_exposes_direct_owner_but_not_retired_commands`
Expected: `OK`, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
launch-commit ... -- -m "docs(workflow-state): direct-owner --help names expects (issue 473)"
```
