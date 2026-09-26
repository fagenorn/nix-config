# Task 2: Truthful remainder classification

Decisions: D1, D2, D5, D6, D9, D11. Spec "Remainder classification (D2)",
"Response contract (D5)" and "Test seams". Work from the worktree root. Every
shell block starts with `set -euo pipefail` (`set -uo pipefail` in the
watch-it-fail step) and these abbreviations, which the blocks below omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
```

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py`
  (`DeliveryRuntime.remainder_policy`: its nested `result` and two of its
  returns)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (one test in
  `DeliveryAdmissionTest`)

**Interfaces:**
- Consumes (Task 1): `DeliveryAdmissionTest.remainder_sweeps(self, root, home, run_id) -> (control, checkpoint)`,
  where `control(now, max_parallel=1, *, spawn=False) -> bytes` returns the raw
  response, and the static `DeliveryAdmissionTest.remainder_launch(response) -> dict`.
  Also the nested `admit` in `$S/workflow-state.py`.
- Produces: every result `remainder_policy` builds carries `desired`: `"idle"`
  for a live remainder, `"terminal"` for a stall-bound failure, and `"resume"`
  for everything else. The nested signature becomes
  `result(operation: str, *, changed: bool = False, desired: str = "resume", requirements: list[dict[str, Any]] | None = None) -> dict[str, Any]`.
  Only `command_control`'s lane selection reads `desired` (D1).

**Invariants:**
- `operation`, `changed`, `requirements`, `expired`, `custody_kind` and every
  ledger mutation `remainder_policy` makes stay as they are. Only `desired`
  changes, and only in the two returns named in Step 4 (D2).
- The `not dispatch_permitted` return, `result("idle", changed=reaped)`, keeps
  `desired: "resume"`. It covers a suspended remainder, one reaped to suspended,
  and an active one whose owner is unavailable, and the resume lane must still
  see each of them.
- `delivery_policy`'s first-remainder and historical-terminal results and
  `recovery_policy`'s results keep their own `desired` values.
- T1, T3, T4 and Task 1's three contract tests stay green.

- [ ] **Step 1: Confirm Task 1 landed**

```bash
set -euo pipefail
grep -c 'def admit(issue: int, result' $S/workflow-state.py
grep -c 'def remainder_sweeps' $T/test_delivery_workflow.py
```

Expected: `1`, then `1`. If either is `0`, stop, because Task 1 has not landed.

- [ ] **Step 2: Write the failing test**

In `class DeliveryAdmissionTest` of `$T/test_delivery_workflow.py`, insert this
directly after `test_a_suspended_remainder_with_a_free_slot_resumes` (Task 1's
last test) and before `test_control_allocates_only_one_proven_second_remainder`.
The declaration overwrite follows `test_admission_replay`'s `declare`.

```python
    def test_a_live_remainder_short_of_agent_slots_is_not_waiting(self):
        """T2: a live remainder is custody, not an issue queued for agent slots."""
        home = make_home(); self.addCleanup(shutil.rmtree, home, True)
        # The 4-slot floor: the controller plus the claimed r1:2 fill it.
        (home / ".agents/share/host-declaration.json").write_text(json.dumps(
            {"schema_version": 1, "routes": {
                "claude-code": {"support": "supported", "agent_slots": 4},
                "codex": {"support": "unsupported"}}}), encoding="utf-8")
        with tempfile.TemporaryDirectory() as raw:
            control, _ = self.remainder_sweeps(Path(raw), home, "short-slots")
            self.remainder_launch(control("2026-09-21T00:00:03Z"))
            response = json.loads(control("2026-09-21T00:00:04Z", max_parallel=2))
            self.assertEqual(response["admission"]["waiting"], [])
            self.assertFalse(any(item["kind"] == "delivery_remainder"
                                 for item in response["actions"]))
```

- [ ] **Step 3: Watch it fail**

```bash
set -uo pipefail
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py \
  -k short_of_agent_slots 2>&1 \
  | grep -E '^(FAIL|ERROR):|KeyError|AssertionError|^Ran|^OK|^FAILED'
```

Expected: `Ran 1 test` and `FAILED (failures=1)`, with
`AssertionError: Lists differ: [151] != []`. After Task 1 the live remainder
no longer crashes the sweep, but it still enters the resume lane and is
withheld for slots.

- [ ] **Step 4: Label the two custodies**

In `DeliveryRuntime.remainder_policy` of `$S/workflow_delivery.py`, make exactly
these edits and nothing else.

1. The nested `result`: add the keyword and use it.

   ```python
   # before
           def result(operation: str, *, changed: bool = False,
                      requirements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
   ...
                       "uses_candidate": False, "desired": "resume",
   # after
           def result(operation: str, *, changed: bool = False, desired: str = "resume",
                      requirements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
   ...
                       "uses_candidate": False, "desired": desired,
   ```

2. The stall-bound failure. The initial state filter returns `None` for a
   remainder that is already `failed`, so this branch is reached only when this
   sweep's reap crossed the stall bound:

   ```python
           if remainder["state"] == "failed":
               # Only this sweep's reap fails a remainder here, at the stall bound.
               # Its caller persists the changed result; control's lanes skip it (D2).
               if preview is None:
                   preview = {"next_stage_id": None}
               return result("terminal", changed=True, desired="terminal")
   ```

3. The live remainder. The reaper has already run, so an `active` remainder
   here is before its deadline:

   ```python
           if remainder["state"] == "active" and not owner_unavailable:
               # Live custody: control's lanes skip it, as they skip a live attempt (D2).
               return result("idle", desired="idle")
   ```

- [ ] **Step 5: Verify**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py \
  -k short_of_agent_slots -k live_remainder_with_a_free_slot \
  -k stall_bound_remainder -k suspended_remainder_with_a_free_slot 2>&1 \
  | grep -E '^(FAIL|ERROR):|KeyError|AssertionError|^Ran|^OK|^FAILED'
test "$(grep -c 'result("idle", desired="idle")' $S/workflow_delivery.py)" = 1
test "$(grep -c 'result("terminal", changed=True, desired="terminal")' $S/workflow_delivery.py)" = 1
test "$(grep -c 'result("idle", changed=reaped)' $S/workflow_delivery.py)" = 1
```

Expected: `Ran 4 tests`, `OK`, and each `test` exits 0.

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py \
  $T/test_host_admission.py $T/test_admission_replay.py \
  $T/test_delivery_workflow.py $T/test_workflow_delivery.py 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran|^OK|^FAILED'
```

Expected: `Ran 230 tests` and `OK`.

- [ ] **Step 6: Final gate**

```bash
set -euo pipefail
just agent-workflow-tests 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
just build 2>&1 | tail -n 3
```

Expected: `OK` with no `FAIL:` or `ERROR:` lines, and a `Ran` count four above
the base run's, which was 1305 at `2f2093f`. Then `just build` exits 0. No skill, `.nix` or installed file
changes, so the installed-surface test is unaffected. If only
`test_installed_policy_surface_matches_source_contract` fails, the installed
build is behind `main`. Rerun the first line as
`WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests`, as CI does, and
report both results.

- [ ] **Step 7: Commit**

```bash
set -euo pipefail
git add $S/workflow_delivery.py $T/test_delivery_workflow.py
git commit -m "fix(workflow-delivery): label live and stalled remainders truthfully (#190)" \
  -m "A live remainder is desired idle and a stall-bound failure desired terminal, so neither enters control's resume lane or its admission.waiting set." \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
