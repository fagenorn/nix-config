# Task 4: Drop the ceiling raise and sync with `origin/main`

Spec section **Instruction budget**; rows D12 and D15.

**Files:**
- Modify (revert): `home/common/agent-skills/instruction-load.json`
- Merge: everything `origin/main` advanced by. Per a scratch probe, `CLAUDE.md`, `justfile`, `instruction-load.json` and `home/common/agent-skills/tests/test_workflow_skill_contracts.py` auto-merge cleanly.

**Interfaces:**
- Consumes: commit `ec089c67` ("chore(instruction-load): raise the corpus ceiling for #279's lane triage"), and the remote-tracking ref `origin/main`.
- Produces: a branch head that has `origin/main` as an ancestor, with `instruction-load.json` byte-identical to `origin/main`'s. Task 5 starts from this head.

**Invariants:**
- After this task, `git diff --quiet origin/main -- home/common/agent-skills/instruction-load.json` exits 0 (D15).
- No ceiling is edited by hand. The revert removes only the corpus raise; Task 1's commit `ffbc16e0` also raised three profile ceilings and appended their notes, so after the merge the whole file is restored from `origin/main` (`git checkout origin/main -- home/common/agent-skills/instruction-load.json`), never edited value by value (Phase-5 B-001).
- The revert and the merge are separate commits, both signed. Never pass `--no-gpg-sign`, and never rewrite history: no rebase, no reset of pushed commits.
- `instruction_load check` is expected to **fail** at this task's end, because the from-issue text is still the uncompressed version. That failure is Task 5's red. Do not fix it here.

- [ ] **Step 1: Confirm the base state the gate must change**

Run: `git fetch origin && git diff --quiet origin/main -- home/common/agent-skills/instruction-load.json; echo "diff=$?"; git merge-base --is-ancestor origin/main HEAD; echo "ancestor=$?"`
Expected: `diff=1` and `ancestor=1`. The branch still carries the raise and is behind main.

- [ ] **Step 2: Revert the raise**

Run `git revert --no-commit ec089c67`. Then commit it with the launch's commit wrapper when the harness registered one, otherwise with plain `git commit`, using the message `Revert "chore(instruction-load): raise the corpus ceiling for #279's lane triage"` and the body `No ceiling is raised (issue AC5, spec D15).` Add the session attribution trailers.

- [ ] **Step 3: Merge `origin/main`**

Run `git merge --no-ff --no-commit origin/main`. If any path conflicts, stop and report the conflicting paths: the probe predicts none, so a conflict means main moved in a way this plan did not anticipate. Otherwise commit with the message `Merge remote-tracking branch 'origin/main' into worktree-issue-279-orchestrated`, the same way as Step 2.

- [ ] **Step 3b: Restore the gate file from main**

Run `git checkout origin/main -- home/common/agent-skills/instruction-load.json`, then commit it, signed and with the session trailers, as `chore(instruction-load): restore main's ceilings and notes for #279` with the body `Drops the profile-ceiling raises ffbc16e0 made; no ceiling is raised (issue AC5, spec D15).` If the file is already identical, skip the commit.

- [ ] **Step 4: Verify**

Run: `git diff --quiet origin/main -- home/common/agent-skills/instruction-load.json && git merge-base --is-ancestor origin/main HEAD && echo ok`
Expected: `ok`.

Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base origin/main > "${TMPDIR:-/tmp}/il-279.txt" 2>&1; echo "exit=$?"; tail -5 "${TMPDIR:-/tmp}/il-279.txt"`
Expected: a non-zero exit naming breached from-issue profiles. This records Task 5's red, and nothing changes in this task.

Run, with a timeout of at least 600 s: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_lane_triage.py home/common/agent-skills/tests/test_resolve_project.py > "${TMPDIR:-/tmp}/ut-279.log" 2>&1; echo "exit=$?"; tail -3 "${TMPDIR:-/tmp}/ut-279.log"`
Expected: `exit=0` and `OK`. The merge did not disturb Tasks 1–2.
