# Task 6: Handoff templates carry `acceptance_state`

Lane: full (it changes the instructions that build a public report). Decisions:
per D8 and D9 of the spec's ledger, and parent D6. The handoff copies the sdd
report's value unchanged. ship-issue validates the field and carries it, and
its close stage does not read it (spec, Out of scope).

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Tasks 1–2): the `ship-handoff` boundary requires
  `acceptance_state` in both shapes, and pairs `clean` → {`met`,
  `human_pending`, `not_applicable`}, `residuals` → any, and `unknown` →
  {`not_applicable`}. Consumes (Task 5): sdd's Finish reports
  `acceptance_state`.
- Consumes (Task 3): `AcceptanceGradingContractsTest`, with `read(path)` and
  `assert_ordered(text, *anchors)`. Also the module constants `FROM_ISSUE`,
  `FROM_ISSUE_DIR`, `SHIP_ISSUE` and `SHIP_HANDOFF_V2_KEYS`.
- Produces: both template lines carry
  `"acceptance_state":"met|unmet|human_pending|not_applicable"` directly
  after `"review_state":"clean|residuals",`.

**Invariants:**
- `ship-handoff.md` still has exactly one line starting
  `{"interface_version":2` and exactly one starting `{"state":"complete"`.
- Two existing phrases stay byte-identical. One is ship-handoff.md's
  sentence that begins "In both handoff shapes, `head_sha` is the validated
  sdd report's `head_sha`". The other is from-issue's clause "ship-issue's
  Phase-5 range selection reads them, taking `head_sha` as the final-review
  head only when `review_state` is `clean`".
- ship-issue's Phase 8 close behavior is unchanged. No sentence says that
  ship holds or closes on `acceptance_state`.
- No instruction-load profile exceeds its ceiling.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

1. Add `"acceptance_state"` to the `SHIP_HANDOFF_V2_KEYS` set, after
   `"review_state"`.
2. Add this test to `AcceptanceGradingContractsTest`:

```python
    def test_both_handoff_templates_carry_acceptance_state(self):
        raw = (FROM_ISSUE_DIR / "ship-handoff.md").read_text(encoding="utf-8")
        templates = [line for line in raw.splitlines()
                     if line.startswith('{"interface_version":2')
                     or line.startswith('{"state":"complete"')]
        self.assertEqual(len(templates), 2)
        for line in templates:
            with self.subTest(template=line[:30]):
                self.assertIn('"review_state":"clean|residuals",'
                              '"acceptance_state":"met|unmet|human_pending|not_applicable",',
                              line)
        handoff = normalized(raw)
        self.assert_ordered(
            handoff,
            "In both handoff shapes, `head_sha` is the validated sdd report's `head_sha`",
            "In both handoff shapes, `acceptance_state` is the validated sdd report's "
            "`acceptance_state`, copied unchanged.",
            "(`review_state: unknown`) carries `not_applicable`",
            "its close stage does not read it")
        self.assertIn("`head_sha`, `acceptance_state` and `report_path` may be used to "
                      "construct the Phase-7 handoff", self.read(FROM_ISSUE))
        self.assertIn("`head_sha`, `review_state`, `acceptance_state`, `auto`",
                      self.read(SHIP_ISSUE))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -5`
Expected: FAIL in `test_both_handoff_templates_carry_acceptance_state`, and in
`test_ship_handoff_v2_ship_summary_v2_and_remainder_prompt`. The second one
fails because `SHIP_HANDOFF_V2_KEYS` now names a key that the v2 template
line lacks.

- [ ] **Step 3: Edit the three skill documents**

1. `from-issue/ship-handoff.md`: in both template lines, the one starting
   `{"interface_version":2` and the one starting `{"state":"complete"`,
   replace `"review_state":"clean|residuals",` with
   `"review_state":"clean|residuals","acceptance_state":"met|unmet|human_pending|not_applicable",`.
   Each template stays a single line.
2. `from-issue/ship-handoff.md`: directly after the paragraph that ends
   `ship-issue's Phase 5 reviews from.`, insert this paragraph:

```text
In both handoff shapes, `acceptance_state` is the validated sdd report's `acceptance_state`, copied unchanged. A `state: failed` handoff built without an sdd report (`review_state: unknown`) carries `not_applicable`. ship-issue validates the field and carries it; its close stage does not read it.
```

3. `from-issue/SKILL.md`: in the sentence that begins "After these gates,
   sdd's", replace `` `head_sha` and `report_path` may be used `` with
   `` `head_sha`, `acceptance_state` and `report_path` may be used ``. Keep
   the rest of the sentence byte-identical.
4. `ship-issue/SKILL.md`, **Invocation paths**: in the field list, replace
   `` `head_sha`, `review_state`, `auto`, one `` with
   `` `head_sha`, `review_state`, `acceptance_state`, `auto`, one ``.
5. Instruction-load ceilings. Measure with:

```bash
PYTHONPATH="$PWD/python" python3 - <<'PY'
from pathlib import Path
from agent_tools import instruction_load as il
root = Path(".").resolve()
model = il.load_model((root / il.MODEL_PATH).read_bytes())
measured = il.measure(model, il.tree_reader(root))
for profile in model["profiles"]:
    for host in profile["hosts"]:
        used = measured["profiles"][profile["id"]][host]["hot"]["bytes"]
        if used > profile["ceiling_bytes"][host]:
            print(profile["id"], host, profile["ceiling_bytes"][host], "->", used)
PY
```

   For every `(profile, host)` line it prints, set that profile's
   `ceiling_bytes.<host>` in `home/common/agent-skills/instruction-load.json`
   to the printed measured value, with no slack. Append this sentence to that
   profile's `note`:
   `Ceiling raised for #272: both ship-handoff shapes carry acceptance_state from the sdd report (#155 D10).`
   Re-run the script: it must print nothing.

- [ ] **Step 4: Verify**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -3`
Expected: `OK`.

Run: `if [ "$(grep -c '"acceptance_state":"met|unmet|human_pending|not_applicable"' home/common/agent-skills/skills/from-issue/ship-handoff.md)" != 2 ]; then exit 1; fi`
Expected: exit 0. At the base commit the count is 0.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(from-issue): carry acceptance_state in both ship-handoff shapes (#272)"
```
Under a `Lifecycle worker:` line, commit with
`launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "<message>"`
instead of `git commit`.
