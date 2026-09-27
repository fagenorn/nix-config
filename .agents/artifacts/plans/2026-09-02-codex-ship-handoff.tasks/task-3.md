# Task 3: Extend the `--auto` gate enumeration and verify the accommodation record

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Inspect only (never modify): `home/common/agent-skills/README.md`

**Interfaces:**
- Consumes: `HUMAN-GATE.md` from Task 1 (whose opener already defers to `from-issue/SKILL.md`'s suspension procedure with `blocked_on: human_gate`, and whose `## Never route around a denial` section this task's AC3 gate reads) and Task 2's `## Standing authorization` rows. This task adds no new suspension mechanism, no new `blocked_on` value, and no new re-entry line — it widens one enumeration and carves one exemption out of the self-answer rule, both routing to the mechanism that already exists.
- Reads the `setUpClass` attribute `cls.ship_human_gate` created in Task 1. Adds no test constant of its own.
- Produces: nothing later tasks consume. This is the last task; it also runs the whole-repo verification for the branch.
- The test module attribute it reads, `self.auto`, and the constant `AUTO` (line 19) already exist. Do not add a constant.

**Invariants:**
- `AUTO.md`'s final paragraph keeps its existing routing verbatim — it still names `SKILL.md`'s suspension procedure, `blocked_on: human_gate`, and the canonical re-entry line. Only the parenthetical enumeration of *which* gates qualify grows by one case.
- `AUTO.md` gets exactly **two** amendments and no third (per D13): the enumeration in the final paragraph, and the self-answer sentence's irreversible-authorization exemption. Both route to the one existing suspension procedure; neither invents a `blocked_on` value.
- After the second amendment `AUTO.md` contains the string `blocked_on: human_gate` twice, and `human_gate` remains the only `blocked_on` value the file names.
- No file under `home/common/agent-skills/README.md` is edited. Its `## Host adapter accommodations` section is already at the base commit (per D1), and per that row it is deliberately not pinned by a test — this task only proves it is present and intact.
- `home/common/agent-skills/skills/ship-release/SKILL.md` is not touched (per D9).

- [ ] **Step 1: Write the failing test**

Add these three test methods to `WorkflowSkillContractsTest` (the class beginning at line 185), placed next to the other `self.auto` assertions:

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
        # No second pause shape is introduced: after Step 3b the file names
        # `blocked_on: human_gate` twice — the shipping-gate route here and
        # the self-answer exemption — and `human_gate` is still the only
        # `blocked_on` value in the file.
        self.assertEqual(self.auto.count("blocked_on: human_gate"), 2)
        self.assertEqual(
            sorted(set(re.findall(r"blocked_on[:=] ?(\w+)", normalized(self.auto)))),
            ["human_gate"],
        )

    def test_auto_never_self_answers_an_irreversible_authorization_gate(self):
        # D13: the general self-answer instruction cannot stand unqualified
        # once a gate exists that `--auto` must NOT answer for the operator.
        # Grounded in D2's #84 (a fresh, single-use confirmation, never
        # inherited) and #90 (one operator touchpoint; silence is never yes).
        self.assertIn(
            "One class of gate is exempt: a gate that asks a human to "
            "authorize an irreversible action is never self-answered. Its "
            "confirmation must be fresh and single-use, and silence never "
            "means yes — so present the gate's block and follow `SKILL.md`'s "
            "suspension procedure, suspending `blocked_on: human_gate` and "
            "printing the canonical re-entry line, rather than answering on "
            "the operator's behalf.",
            normalized(self.auto),
        )
        # The general rule itself is unchanged and still stands first.
        self.assert_ordered(
            normalized(self.auto),
            "when one tells you to ask or wait, run the self-answer pattern "
            "instead.",
            "One class of gate is exempt:",
        )

    def test_human_gate_carries_no_affirmative_bypass_instruction(self):
        # AC3 (per D14). The closed negative list under
        # `## Never route around a denial` is the file's ONLY home for these
        # spellings; anywhere else they would read as an instruction. A
        # line-local grep cannot see this, because the list's "must not:"
        # lead-in sits on the introduction line and each banned verb on its
        # own bullet.
        gate = self.ship_human_gate
        split = gate.index("## Never route around a denial")
        outside, ban = gate[:split], normalized(gate[split:])
        self.assertIn("On this path the session must not:", ban)
        for bypass in (
            "--admin",
            "--force",
            "--force-with-lease",
            "git merge",
            "git push origin <integrationBranch>",
            "git reset",
            "git rebase",
        ):
            with self.subTest(bypass=bypass):
                self.assertNotIn(bypass, outside)
```

`normalized` is the module-level helper already used by `test_ship_issue_guards_every_pre_merge_forge_write`; it collapses the paragraph's hard line wraps so the assertion is on the sentence, not on the wrap points. `re` is already imported at module scope (`normalized` itself uses `re.sub`).

- [ ] **Step 2: Run the test and watch it fail**

Run all three:

```bash
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  WorkflowSkillContractsTest.test_auto_gate_enumeration_covers_an_unguarded_host \
  WorkflowSkillContractsTest.test_auto_never_self_answers_an_irreversible_authorization_gate \
  WorkflowSkillContractsTest.test_human_gate_carries_no_affirmative_bypass_instruction -v
```

Expected before Step 3: `Ran 3 tests` … `FAILED (failures=2)`.
- `test_auto_gate_enumeration_covers_an_unguarded_host` — `AssertionError`, the expected sentence is not in the normalized text, because the file reads `…cover, or a merge it fails closed on —` and because `blocked_on: human_gate` still occurs once, not twice.
- `test_auto_never_self_answers_an_irreversible_authorization_gate` — `AssertionError`, the exemption sentence is absent; the file still says only "run the self-answer pattern instead."
- `test_human_gate_carries_no_affirmative_bypass_instruction` — passes already, because Tasks 1 and 2 have landed by the time this task runs. Its falsifiability is demonstrated in Step 4, not here.

Confirm the two `AUTO.md` gaps independently:
```bash
grep -c 'a host that has no such guard at all' home/common/agent-skills/skills/from-issue/AUTO.md
grep -c 'One class of gate is exempt' home/common/agent-skills/skills/from-issue/AUTO.md
```
Expected at base: `0` from each, exit status 1 from each.

- [ ] **Step 3: Amend `AUTO.md`**

**3a — the shipping-gate enumeration.** In the final paragraph (currently lines 351–355), rewrite only the em-dashed enumeration. The paragraph must read, once line wraps are collapsed:

```
At any Phase-6 or Phase-7 push, PR-open, or merge gate the lifecycle guard does not stand — a repository the guard does not cover, a merge it fails closed on, or a host that has no such guard at all and adjudicates intent by review instead — do not die at the prompt: follow `SKILL.md`'s suspension procedure, suspending `blocked_on: human_gate` and printing the canonical re-entry line, so a later human approval resumes the same attempt without penalty.
```

Keep the file's existing hard-wrap width (~78 columns) when re-wrapping the paragraph; the assertion normalizes whitespace, so wrap points are free but house style is not.

**3b — the self-answer exemption (per D13).** The general self-answer instruction currently tells the owner to answer for the human whenever a sub-skill asks or waits. Task 1's gate is precisely a gate `--auto` must **not** answer: it presents its block and suspends `blocked_on: human_gate`. Left as-is, `AUTO.md` would instruct the owner to self-answer an irreversible-authorization confirmation, contradicting D2's grounding (#84 — a fresh, single-use confirmation, never inherited and never silently retried; #90 — one operator touchpoint, and silence never means yes).

Replace lines 48–50, which currently read:

```
Sub-skills (`design`, `grill-with-docs`, `writing-plans`, `sdd`,
`ship-issue`) don't know about `--auto`. *You* carry the autonomous-mode context — when one tells you
to ask or wait, run the self-answer pattern instead.
```

with exactly (the paragraph is re-wrapped to the file's ~78-column house style; the assertion normalizes whitespace, so the wrap points are free but the words are not):

```
Sub-skills (`design`, `grill-with-docs`, `writing-plans`, `sdd`,
`ship-issue`) don't know about `--auto`. *You* carry the autonomous-mode
context — when one tells you to ask or wait, run the self-answer pattern
instead. One class of gate is exempt: a gate that asks a human to authorize an
irreversible action is never self-answered. Its confirmation must be fresh and
single-use, and silence never means yes — so present the gate's block and
follow `SKILL.md`'s suspension procedure, suspending `blocked_on: human_gate`
and printing the canonical re-entry line, rather than answering on the
operator's behalf.
```

The general rule is kept and still stands first; the exemption is appended to the same paragraph so a reader cannot meet one without the other.

Change nothing else in the file: 3a and 3b are the only two amendments, and no third is permitted.

- [ ] **Step 4: Verify**

```bash
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  WorkflowSkillContractsTest.test_auto_gate_enumeration_covers_an_unguarded_host \
  WorkflowSkillContractsTest.test_auto_never_self_answers_an_irreversible_authorization_gate \
  WorkflowSkillContractsTest.test_human_gate_carries_no_affirmative_bypass_instruction -v
```
Expected: `Ran 3 tests` … `OK` — the two that failed in Step 2 now pass.

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

**Acceptance criterion 3 — no bypass instruction anywhere on the handoff path.** The ship contract already bans rewriting the integration branch; prove the new path adds no counter-instruction. This is checked by `test_human_gate_carries_no_affirmative_bypass_instruction` (per D14), **not** by a line-local `grep`: the list's `must not:` lead-in sits on the introduction line while each banned verb sits on its own bullet, so a per-line "does this line also say `must not`?" filter rejects the very text Task 1 prescribes. The test instead splits the file at `## Never route around a denial` and asserts that every bypass spelling occurs only inside that closed list, in the prescribed order, and nowhere before it.

```bash
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  WorkflowSkillContractsTest.test_human_gate_carries_no_affirmative_bypass_instruction \
  WorkflowSkillContractsTest.test_ship_issue_human_gate_consolidates_and_forbids_bypass -v
```
Expected: `Ran 2 tests` … `OK`.

Prove the gate can actually fail — it must reject an *affirmative* bypass while accepting the prescribed negative list:

```bash
cp home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md /tmp/human-gate.bak
python3 - <<'EOF'
import pathlib
p = pathlib.Path("home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md")
t = p.read_text()
i = t.index("## Never route around a denial")
p.write_text(t[:i] + "If CI is stuck, pass `--admin` to land it.\n\n" + t[i:])
EOF
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  WorkflowSkillContractsTest.test_human_gate_carries_no_affirmative_bypass_instruction -v
cp /tmp/human-gate.bak home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md
rm /tmp/human-gate.bak
git diff --exit-code home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md
```
Expected: the middle run reports `FAILED (failures=1)` with `AssertionError: '--admin' unexpectedly found` under `[bypass='--admin']`; the final `git diff --exit-code` is silent and exits 0, proving the file was restored byte-for-byte. Re-run the two-test command above and confirm `OK` before continuing.

**Whole-branch verification.**

```bash
python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py
```
Expected: `Ran 130 tests` … `OK` — 0 failures, 0 errors (125 at the base commit, plus one from Task 1, one from Task 2 and three from this task).

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
