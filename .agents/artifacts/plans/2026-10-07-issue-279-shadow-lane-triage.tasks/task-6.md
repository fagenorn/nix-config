# Task 6: Re-sync, budget check against the current main, final gate and acceptance record

Spec section **Instruction budget**; rows D10, D12, D15 and D16.

**Files:**
- Modify: `.agents/artifacts/plans/2026-10-07-issue-279-shadow-lane-triage.acceptance.md`
- Merge (only if `origin/main` moved after Task 4): whatever main advanced by.

**Interfaces:**
- Consumes (Task 5): `home/common/agent-skills/tests/test_workflow_skill_contracts.py::LaneTriageRecordKeysTest`, and the from-issue corpus fitted under main's ceilings. Consumes (Task 4): a head that contains the `origin/main` of its time.
- Produces: the acceptance record with AC4's check renamed and an AC5 row added, all observed on the final head.

**Invariants:**
- No `--raise-label` is passed, and no `instruction-load.json` ceiling differs from the then-current `origin/main` (D15).
- `git diff --quiet origin/main -- home/common/agent-skills/instruction-load.json` exits 0 at the final head.
- A re-sync is a signed merge commit, never a rebase.

- [ ] **Step 1: Re-sync with the current main**

Run `git fetch origin`. If `git merge-base --is-ancestor origin/main HEAD` exits 1, merge `origin/main` as in Task 4 Step 3. On a conflict, stop and report the conflicting paths.

- [ ] **Step 2: Check the budget against that main**

Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base origin/main > "${TMPDIR:-/tmp}/il-279.txt" 2>&1; echo "exit=$?"; tail -3 "${TMPDIR:-/tmp}/il-279.txt"`
Expected: `exit=0`. If it fails because main's own growth ate the slack, re-run Task 5 Step 5's delta command. If the delta is still ≤ 0 against the new main, the breach is main's to fix: stop and report the failing profile. Never raise a ceiling (issue AC5).

Run: `git diff --quiet origin/main -- home/common/agent-skills/instruction-load.json && echo same`
Expected: `same`.

- [ ] **Step 3: Final gate**

Run each command in the foreground, with a timeout of at least 2400 s (3600 s recommended). Capture each command's own exit status before reading its log tail (no status through a pipe; the shell may be zsh, so never rely on `PIPESTATUS`), and record verification only when that status is 0 (Phase-5 SF-001):
- `L="${TMPDIR:-/tmp}/build-279.log"; just build > "$L" 2>&1; echo "exit=$?"; tail -5 "$L"`. Expected: `exit=0`.
- `L="${TMPDIR:-/tmp}/awt-279.log"; just agent-workflow-tests > "$L" 2>&1; echo "exit=$?"; tail -3 "$L"; grep -c LaneTriageRecordKeysTest "$L"`. Expected: `exit=0`, `OK`, and a count of 2.
- `L="${TMPDIR:-/tmp}/ais-279.log"; just agent-installed-skill-tests > "$L" 2>&1; echo "exit=$?"; tail -5 "$L"` (D10). Expected: `exit=0` and `OK`, which shows that the `ast`-based pin also runs without `PYTHONPATH` (D16).

- [ ] **Step 4: Update the acceptance record**

In the acceptance record:
- AC4: set the check to `home/common/agent-skills/tests/test_workflow_skill_contracts.py::LaneTriageRecordKeysTest` under `just agent-workflow-tests`.
- Append an AC5 row. Criterion: the issue's fifth criterion, copied. Kind: `code`. Check: the required `Instruction Budget` CI check on the PR, without the `instruction-budget-raise` label. Its local proxy is `instruction_load check --base origin/main`, which must exit 0 with no `--raise-label`. Observed: Step 2's exit and the `origin/main` SHA it ran against. Put the local result in Observed. Verdict: `unverified` (the closed vocabulary is `met`, `unmet`, `unverified`, `human_pending`), because only the PR's green `Instruction Budget` check establishes AC5; ship-issue's CI wait observes that check, and the record is updated to `met` only once it is green (Phase-5 SF-002).
- Fill Observed and Commit on every row from Step 3, using the final head SHA.

- [ ] **Step 5: Commit**

Commit the acceptance record with the message `docs(plans): record #279's acceptance under main's instruction ceilings`, signed and with the session trailers.
