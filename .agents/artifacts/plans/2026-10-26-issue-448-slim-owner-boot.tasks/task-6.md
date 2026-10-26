# Task 6: Cut 3 — support-file sections in the index

Spec § Cut 3; per D5, D8, D16, D20. The index's read rules for a verified pack stop three over-reads:
- **AUTO.md**: `When *not* to auto-resolve` governs Phases 0–5 only. Phases 6–7 read the opening, `The self-answer pattern`, `Other Phase 5–7 routes` (or the file named in its place) and `Interface_version 2 delivery relay`.
- **delegated-owner.md**: only the section the route selects is read, `## Checks and Phases 6–7` at the rollover and `## Generic delegate` for a generic delegate.
- **ship-handoff.md**: read only from `## Phase 7 — Ship` on, or for a generic delegate's handoff after Phase 6's gates.

The pack's JSON carries no section names (#265's facts-only pack).

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`: three lines of `## Files beside this one`, the `AUTO.md`, `delegated-owner.md` and `ship-handoff.md` bullets.
- Modify, for byte offsets only: `home/common/agent-skills/skills/from-issue/AUTO.md`, and other sentences of `SKILL.md`.
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`: `SlimBootContractsTest` gains two tests.
- Modify: `.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md`: the Built cell of cut row 3.

**Interfaces:**
- Consumes: Task 4's `SlimBootContractsTest` (`read`, `section`), and the module constants `FROM_ISSUE`, `AUTO`, `DELEGATED_OWNER`, `FROM_ISSUE_DIR` and `normalized`. If neither Task 4 nor Task 5 built anything, first create the class exactly as Task 4 Step 1 shows, minus its test method.
- Produces: the index structure D20 names. The `AUTO.md` bullet names `` `When *not* to auto-resolve` `` once, and ends in a clause starting `Phases 5–7:` (en dash).

**Invariants:**
- In the `AUTO.md`, `resume-pack.md`, `delegated-owner.md` and `ship-handoff.md` bullets, every backticked file name exists beside `SKILL.md`. Every other backticked span is a heading of the bullet's document (`AUTO.md`, `SKILL.md`, `delegated-owner.md`, `SKILL.md`), with a leading `## ` removed. The exceptions are spans starting with `-`, spans holding `<`, and the sub-skill names `sdd` and `ship-issue`.
- Within the `AUTO.md` bullet, the text from `Phases 5–7:` on names `` `Other Phase 5–7 routes` `` and `` `Interface_version 2 delivery relay` `` and not `` `When *not* to auto-resolve` ``. The direct-autonomous controller's `rollover.md` and the delegated owner's `delegated-owner.md` stay named as read in place of `Other Phase 5–7 routes`.
- The `delegated-owner.md` bullet names `` `## Checks and Phases 6–7` `` and `` `## Generic delegate` ``. The `ship-handoff.md` bullet names `` `## Phase 7 — Ship` ``, and no other of the four bullets names `` `ship-handoff.md` ``.
- The index's other bullets and the Task 5 identifiers are unchanged. Over `SKILL.md` and `AUTO.md`, bytes fall (D5), and no profile breaches its ceiling.

- [ ] **Step 0: Read the verdict**

Run `bash -c 'grep -qE "^\| 3 \| .*\| keep \| " .agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md'`. On a non-zero exit, change nothing, commit nothing, and report DONE with `cut 3 not built: Task 3 verdict` (D16).

- [ ] **Step 1: Write the failing tests**

Add to `SlimBootContractsTest`:

```python
    def bullet(self, name):
        index = self.section(self.read(FROM_ISSUE), "## Files beside this one",
                             "## Lifecycle identity")
        start = index.index(f"- **`{name}`**")
        end = index.find(" - **`", start + 1)
        return index[start:] if end < 0 else index[start:end]

    @staticmethod
    def headings(path):
        return {line.lstrip("#").strip()
                for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("#")}

    def test_every_section_and_file_the_verified_pack_reads_exists(self):
        for name, document in (("AUTO.md", AUTO), ("resume-pack.md", FROM_ISSUE),
                               ("delegated-owner.md", DELEGATED_OWNER),
                               ("ship-handoff.md", FROM_ISSUE)):
            for span in re.findall(r"`([^`]+)`", self.bullet(name)):
                with self.subTest(bullet=name, span=span):
                    if span.endswith(".md"):
                        self.assertTrue((FROM_ISSUE_DIR / span).is_file())
                    elif not (span.startswith("-") or "<" in span or span in ("sdd", "ship-issue")):
                        self.assertIn(span.removeprefix("## "), self.headings(document))
        for heading in ("`## Checks and Phases 6–7`", "`## Generic delegate`"):
            self.assertIn(heading, self.bullet("delegated-owner.md"))

    def test_phases_6_7_read_neither_the_stop_rules_nor_the_ship_handoff(self):
        auto = self.bullet("AUTO.md")
        self.assertEqual(auto.count("`When *not* to auto-resolve`"), 1)
        late = auto[auto.index("Phases 5–7:"):]
        for wanted in ("`Other Phase 5–7 routes`", "`Interface_version 2 delivery relay`"):
            self.assertIn(wanted, late)
        self.assertNotIn("`When *not* to auto-resolve`", late)
        self.assertIn("`## Phase 7 — Ship`", self.bullet("ship-handoff.md"))
        for name in ("AUTO.md", "resume-pack.md", "delegated-owner.md"):
            self.assertNotIn("`ship-handoff.md`", self.bullet(name))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k SlimBootContractsTest 2>&1 | tail -4'` (timeout 300 s).
Expected: FAIL and ERROR. The `delegated-owner.md` bullet names neither heading, and `Phases 5–7:` is not in the `AUTO.md` bullet (the base reads `for Phases 5–7,`).

- [ ] **Step 3: Edit the index**

Drafts with byte deltas measured at `cf7232c1`, about +26 B net. Fund the rest by shortening repeated wording elsewhere in `SKILL.md` or `AUTO.md`, the hot members every affected profile shares. Never drop a rule, a pinned identifier, a `## Contents` list (skill-lint L3) or a Task 4–5 identifier.

1. The `AUTO.md` bullet keeps `**`AUTO.md`** — autonomous-mode rules.`. Then (−74 B):

   ```
   Read it once, now, only with the literal token `--auto`; with a resume pack, after its checks pass. A failed pack reads it whole; a verified pack reads the opening and `The self-answer pattern`, then for Phases 0–5 `When *not* to auto-resolve`, for Phases 2–4 `Phases 2–4 run as subagents`, and for Phases 5–7: `Other Phase 5–7 routes` (the direct-autonomous controller at Phase 5 reads `rollover.md`, and the delegated owner `delegated-owner.md`, in its place) and `Interface_version 2 delivery relay`.
   ```

2. ``**`delegated-owner.md`** — every delegated owner, first: only `## Checks and Phases 6–7` or `## Generic delegate`, as its route selects.`` (+50 B)
3. ``**`ship-handoff.md`** — `## Phase 7 — Ship` on, or a generic delegate's handoff.`` (+50 B)

- [ ] **Step 4: Verify**

Run: the Step 2 command. Expected: PASS, every `SlimBootContractsTest` test (5 with cuts 1 and 2 built; fewer only when an earlier cut was not built).
Run: **Skill contract tests**. Expected: PASS.
Run: **Budget**. Expected: `check: pass`. On a `tightness:` line only, run `just agent-instruction-load tighten`, add `home/common/agent-skills/instruction-load.json` to the commit, and rerun.
Run the net-bytes check:

```bash
bash -c 'set -e; net=0; for f in home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md; do net=$((net + $(wc -c < "$f") - $(git show "HEAD:$f" | wc -c))); done; echo "net $net"; test "$net" -lt 0'
```

If the Budget or net-bytes check cannot pass without dropping a rule or an Invariants identifier, the cut fails D5's rule 2. Then revert every file but the record, set row 3's Verdict to `reject (instruction load)` and its Built to `not built`, and commit only the record.

- [ ] **Step 5: Record and commit**

Set cut row 3's Built cell to `built; net <n> bytes`. Then:

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  .agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md
git commit -m "feat(from-issue): a verified pack reads only its phase's support sections (issue 448)"
```
