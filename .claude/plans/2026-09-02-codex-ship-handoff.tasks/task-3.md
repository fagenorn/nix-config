# Task 3: Extend the `--auto` gate enumeration and verify the accommodation record

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Inspect only (never modify): `home/common/agent-skills/README.md`

**Interfaces:**
- Consumes: `HUMAN-GATE.md` from Task 1 (whose opener already defers to `from-issue/SKILL.md`'s suspension procedure with `blocked_on: human_gate`) and Task 2's `## Standing authorization` rows. This task adds no new suspension mechanism, no new `blocked_on` value, and no new re-entry line — it widens one enumeration so the existing mechanism covers the review-adjudicated host.
- Produces: nothing later tasks consume. This is the last task; it also runs the whole-repo verification for the branch.
- The test module attribute it reads, `self.auto`, and the constant `AUTO` (line 19) already exist. Do not add a constant.

**Invariants:**
- `AUTO.md`'s final paragraph keeps its existing routing verbatim — it still names `SKILL.md`'s suspension procedure, `blocked_on: human_gate`, and the canonical re-entry line. Only the parenthetical enumeration of *which* gates qualify grows by one case.
- No file under `home/common/agent-skills/README.md` is edited. Its `## Host adapter accommodations` section is already at the base commit (per D1), and per that row it is deliberately not pinned by a test — this task only proves it is present and intact.
- `home/common/agent-skills/skills/ship-release/SKILL.md` is not touched (per D9).

- [ ] **Step 1: Write the failing test**

Add this test method to `WorkflowSkillContractsTest` (the class beginning at line 185), placed next to the other `self.auto` assertions:

```python
    def test_auto_gate_enumeration_covers_an_unguarded_host(self):
        # AUTO.md's final paragraph is the one suspension route for shipping
        # gates. It gains the review-adjudicated host as a third qualifying
        # case, so the operator gate reuses the mechanism that already exists.
        self.assertIn(
            "At any Phase-6 or Phase-7 push, PR-open, or merge gate the "
            "lifecycle guard does not stand — a repository the guard does not "
            "cover, a merge it fails closed on, or a host that has no such "
            "guard at all and adjudicates intent by review instead — do not die "
            "at the prompt: follow `SKILL.md`'s suspension procedure, "
            "suspending `blocked_on: human_gate` and printing the canonical "
            "re-entry line, so a later human approval resumes the same attempt "
            "without penalty.",
            normalized(self.auto),
        )
        # No second pause shape is introduced.
        self.assertEqual(self.auto.count("blocked_on: human_gate"), 1)
```

`normalized` is the module-level helper already used by `test_ship_issue_guards_every_pre_merge_forge_write`; it collapses the paragraph's hard line wraps so the assertion is on the sentence, not on the wrap points.

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py WorkflowSkillContractsTest.test_auto_gate_enumeration_covers_an_unguarded_host -v`
Expected: `Ran 1 test` … `FAILED (failures=1)` — `AssertionError`, the expected sentence is not in the normalized text, because the file reads `…cover, or a merge it fails closed on —`.

Confirm independently:
```bash
grep -c 'a host that has no such guard at all' home/common/agent-skills/skills/from-issue/AUTO.md
```
Expected at base: `0`, exit status 1.

- [ ] **Step 3: Amend `AUTO.md`**

In the final paragraph (currently lines 351–355), rewrite only the em-dashed enumeration. The paragraph must read, once line wraps are collapsed:

```
At any Phase-6 or Phase-7 push, PR-open, or merge gate the lifecycle guard does not stand — a repository the guard does not cover, a merge it fails closed on, or a host that has no such guard at all and adjudicates intent by review instead — do not die at the prompt: follow `SKILL.md`'s suspension procedure, suspending `blocked_on: human_gate` and printing the canonical re-entry line, so a later human approval resumes the same attempt without penalty.
```

Keep the file's existing hard-wrap width (~78 columns) when re-wrapping the paragraph; the assertion normalizes whitespace, so wrap points are free but house style is not. Change nothing else in the file.

- [ ] **Step 4: Verify**

```bash
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py WorkflowSkillContractsTest.test_auto_gate_enumeration_covers_an_unguarded_host -v
```
Expected: `Ran 1 test` … `OK`.

**Acceptance criterion 4 — the accommodation record.** Verify it is present and intact, rather than recreating it (per D1). These clauses are matched fixed-string against the file's own hard wraps, so none of them spans a line break in the committed text:

```bash
for clause in \
  '## Host adapter accommodations' \
  '### Shipping authorization — `ship-issue`' \
  'shipping needs authorization for' \
  '129 times, peaking at 57 in a' \
  'irreducibility evidence is therefore not required' \
  'skills/ship-issue/HUMAN-GATE.md' ; do
  if ! grep -qF "$clause" home/common/agent-skills/README.md; then
    echo "AC4 missing: $clause"; exit 1
  fi
done
echo 'AC4 ok'
```
Expected: `AC4 ok`. (At the commit *before* the design commit this block exits 1 on the first clause; on this branch it passes, which is the point — the plan verifies rather than reproduces.)

**Acceptance criterion 3 — no bypass instruction anywhere on the handoff path.** The ship contract already bans rewriting the integration branch; prove the new path adds no counter-instruction:

```bash
if grep -nE 'git merge .*(main|<integrationBranch>)|git push origin (main|<integrationBranch>)|--admin|--force-with-lease' \
     home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md \
   | grep -qv 'must not'; then
  echo 'AC3 violated: an unqualified bypass instruction'; exit 1
fi
echo 'AC3 ok'
```
Expected: `AC3 ok` — every match sits inside the "must not" closed list.

**Whole-branch verification.**

```bash
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py
```
Expected: `Ran 128 tests` … `OK` — 0 failures, 0 errors.

```bash
just agent-workflow-tests
python3 home/common/agent-skills/tests/test_ship_release_contracts.py
```
Expected: both `OK`. The second proves `ship-release`'s own claim is deliberately unamended and its suite still passes (per D9).

```bash
just build
```
Expected: succeeds. This proves the new sidecar materializes without a Nix change, because `home/common/agent-skills/default.nix` links whole skill directories and carries no per-file manifest. Confirm that fact directly rather than assuming it:

```bash
if grep -q 'HUMAN-GATE\|CI-MERGE\|SYNC\.md' home/common/agent-skills/default.nix; then
  echo 'a per-file manifest exists — update it'; exit 1
fi
echo 'no manifest; whole-directory link confirmed'
```
Expected: `no manifest; whole-directory link confirmed`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/AUTO.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "$(cat <<'EOF'
fix(from-issue): cover an unguarded host in the --auto shipping gate route

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
EOF
)"
```
