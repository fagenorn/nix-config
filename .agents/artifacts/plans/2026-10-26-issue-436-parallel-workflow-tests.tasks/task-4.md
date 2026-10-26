# Task 4: Adoption fixtures resolve the same on every host

Spec § CI truthfulness prerequisites, per D8 as refined by D13. The adoption fixtures take this repository's own contract. Its plan and code review commands run `codex-companion`, which the hosted runner does not have, so there `resolve-project` derives `review.plan` and `review.code` as `blocked` (`command_missing`). Eight `test_adopt_verify` cases then read `adopted_with_blockers` where they demand `adopted`, or extra blockers.

The three fixture sites that already opt out of release for the same reason will share one helper. It keeps that opt-out and also rebinds both review commands to `true`, which every host resolves, as `test_adopt_apply.apply_repo` already does. Test semantics do not change: a case that expects `adopted` still demands `adopted`.

**Files:**
- Modify: `home/common/agent-skills/tests/test_adopt_project.py` (new `host_independent` helper before `scaffold`; `adopted_repo`)
- Modify: `home/common/agent-skills/tests/test_adopt_verify.py` (import; `verifiable_repo`; `RemoteRegistrationTest.test_a_diverged_local_branch_registers_from_the_remote`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `host_independent(contract: dict) -> dict` in `test_adopt_project.py`. It changes the contract in place and returns it.

**Invariants:**
- `host_independent` sets `contract["release"] = "unsupported"`. For each role in `("plan", "code")` it sets the `argv` of `contract["bindings"]["commands"][contract["bindings"]["workflow"]["review"][role]]` to `["true"]`. It reads the command ids from `workflow.review` rather than naming them, so the fixture follows the source contract.
- `fixture_contract`, `scaffold`, `test_adopt_apply.py` and `test_adopt_project_boundaries.py` are unchanged (D13).
- No assertion in any adoption test module changes.
- Under a `PATH` without `codex-companion`, all four adoption modules pass. Under the host's normal `PATH` they also pass.

- [ ] **Step 1: Reproduce the failure the hosted runner sees**

The failing tests already exist. They fail only where `codex-companion` does not resolve, so build that `PATH` under the scratch root. Steps 1, 2 and 4 use the shell variables `S` and `PY`: run them in one shell, or set both again first.

```bash
S=$(launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>)
mkdir -p "$S/no-review-path"
for tool in git gh just true; do ln -sf "$(type -P "$tool")" "$S/no-review-path/$tool"; done
PY=$(type -P python3)
PATH="$S/no-review-path:/usr/bin:/bin" bash -c 'type -P codex-companion || echo "codex-companion: not on PATH"'
```

Expected: the last line prints `codex-companion: not on PATH`. A path printed instead means the gate below proves nothing: report BLOCKED with that path.

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 900 s):

```bash
launch-scope exec … -- bash -c "set -o pipefail; PATH='$S/no-review-path:/usr/bin:/bin' PYTHONPATH='$PWD/python' '$PY' -m unittest home/common/agent-skills/tests/test_adopt_verify.py home/common/agent-skills/tests/test_adopt_project.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'"
```

Expected: `FAILED (failures=8)`. The failures are `VerifyReadOnlyTest.test_a_conformant_checkout_is_adopted_and_writes_nothing` and `.test_a_blocked_capability_is_adopted_with_blockers`; `RemoteRegistrationTest.test_registration_follows_the_contracts_integration_branch`, `.test_a_diverged_local_branch_registers_from_the_remote` and `.test_an_unpushed_adoption_refuses_not_integrated`; `IntegrationBranchOperandTest.test_the_operand_registers_against_the_integration_branch` and `.test_a_default_branch_without_a_contract_takes_the_operand_too`; and `IntegrationBranchOperandLifecycleTest.test_nothing_is_read_from_the_checkout`. These are the same eight as CI run 40263175321.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/tests/test_adopt_project.py`, add this function directly before `def scaffold(`:

```python
def host_independent(contract: dict) -> dict:
    """`contract`, changed in place so that no capability depends on the host.

    This repository's GitHub release profile derives a `blocked` release
    capability on any host without the forge adapter's executables on `PATH`,
    and its plan and code review commands run `codex-companion`, which the
    hosted CI runner lacks. No fixture built on this is about release or
    review, so release is opted out and both review commands become `true`,
    which every host resolves: the verdicts are the same everywhere.
    """
    contract["release"] = "unsupported"
    review = contract["bindings"]["workflow"]["review"]
    for role in ("plan", "code"):
        contract["bindings"]["commands"][review[role]]["argv"] = ["true"]
    return contract
```

In `adopted_repo`, delete the four comment lines that begin `# This repository's GitHub release profile derives a \`blocked\` release`. Replace `scaffold(root, fixture_contract(release="unsupported"), home)` with `scaffold(root, host_independent(fixture_contract()), home)`.

In `home/common/agent-skills/tests/test_adopt_verify.py`, make three edits:
1. In the `from .test_adopt_project import (` list, add `host_independent,` after `git,`.
2. In `verifiable_repo`, replace `contract = fixture_contract()` with `contract = host_independent(fixture_contract())`. Delete the four comment lines that begin `# This repository's GitHub release profile derives`, and the line `contract["release"] = "unsupported"` after them. The docstring and every other line stay.
3. In `RemoteRegistrationTest.test_a_diverged_local_branch_registers_from_the_remote`, replace the three lines `contract = fixture_contract()`, `# Opt out of the host-dependent release profile, as \`verifiable_repo\` does.` and `contract["release"] = "unsupported"` with the one line `contract = host_independent(fixture_contract())`.

- [ ] **Step 4: Verify**

Run the Step 2 command again, this time over all four adoption modules: `test_adopt_verify.py`, `test_adopt_project.py`, `test_adopt_apply.py` and `test_adopt_project_boundaries.py`, each under `home/common/agent-skills/tests/`.
Expected: `OK`, with no `FAIL` or `ERROR` line (287 tests at base).

Run the focused form (Global Constraints) on the same four modules, under the normal `PATH`.
Expected: `OK`.

Run `bash -c 'grep -n "release\"\] = \"unsupported\"\|release=\"unsupported\"" home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_verify.py'`.
Expected: one line only, the one inside `host_independent`. At base there are three.

Run `git diff --stat 9d2abb3f..HEAD -- home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_project_boundaries.py`.
Expected: nothing.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_verify.py
launch-commit … -- -m "test(issue-436): adoption fixtures resolve review on every host" -m "<session trailers>"
```

Verify: `git status --short` prints nothing.
