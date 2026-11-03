# Task 3: Move the conformance axis to Opus/high

Lane: full (model routing and its declared contract). Decisions: per D10 and
D12 of the spec's ledger, and parent D3. Read the spec's "Tier change ripple"
section first. This task also changes one site that list leaves out: sdd
`SKILL.md`'s `## Agent tiers` bullet still says the conformance axis runs "on
Sonnet/high".

**Files:**
- Modify: `home/common/agent-skills/model-matrix.json`
- Modify: `python/agent_tools/agent_model_matrix.py`
- Modify: `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/final-review.md`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Test: `home/common/agent-skills/tests/test_agent_model_matrix.py`
- Test: `home/common/agent-skills/tests/test_dispatch_contracts.py`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the existing role `conformance-reviewer`, which keeps its name,
  `eligible`, `prohibited` and its subagent type `reviewer`. Also the
  dispatch id `sdd-final-conformance-review`.
- Produces:
  - The marker
    `<!-- agent-dispatch: id=sdd-final-conformance-review role=conformance-reviewer model=opus effort=high -->`.
  - The call
    `Agent(subagent_type="reviewer", model="opus", effort="high") performs the first-pass whole-branch conformance review.`
  - The test class `AcceptanceGradingContractsTest` in
    `test_workflow_skill_contracts.py`, with `read(path)` and
    `assert_ordered(text, *anchors)` helpers. Tasks 4–6 add methods to it.

**Invariants:**
- The tier `("opus", "high")` is declared for `conformance-reviewer` in all
  of these places, and nowhere is it still `sonnet`: `model-matrix.json`'s
  role, its `sdd-final-conformance-review` dispatch site (`marker`, `call`,
  `model`) and the sdd scenario event for that dispatch;
  `EXPECTED_ROLE_TIERS`; `EXPECTED_TIERS` and `EXPECTED_SDD_SITES` in the
  matrix test; and the prompt's marker, call and subagent line.
- `sdd-final-conformance-rereview` stays `reviewer-lite`/`sonnet`/`medium`
  (per D4).
- Exactly 37 `<!-- agent-dispatch:` lines exist across both skill source
  trees, each id once (per D12).
- `agent_costs.py` and `tests/fixtures/` are not edited, because historical
  telemetry keeps the role spelling (per D10).
- No instruction-load profile exceeds its ceiling.

- [ ] **Step 1: Write the failing tests**

`home/common/agent-skills/tests/test_agent_model_matrix.py`: in
`EXPECTED_TIERS`, set `"conformance-reviewer": ("opus", "high")`. In
`EXPECTED_SDD_SITES["sdd-final-conformance-review"]`, set the model element
from `"sonnet"` to `"opus"`, so the tuple is
`(".../sdd/conformance-reviewer-prompt.md", "conformance-reviewer", "opus", "high", [])`.

`home/common/agent-skills/tests/test_dispatch_contracts.py`: append, before
the `if __name__ == "__main__":` block:

```python
# The dispatch-marker inventory across both skill source trees (#272 D12): a
# change that adds or retires a dispatch updates this count deliberately.
MARKER_INVENTORY = 37
MARKER_LINE = re.compile(r"^<!-- agent-dispatch: id=([a-z0-9-]+) ", re.M)
CONFORMANCE_MARKER = ("<!-- agent-dispatch: id=sdd-final-conformance-review "
                      "role=conformance-reviewer model=opus effort=high -->")
CONFORMANCE_CALL = ('Agent(subagent_type="reviewer", model="opus", effort="high") '
                    "performs the first-pass whole-branch conformance review.")


class MarkerInventoryTest(unittest.TestCase):
    def markers(self):
        found = []
        for tree in SOURCE_TREES.values():
            for path in sorted(tree.rglob("*.md")):
                found += MARKER_LINE.findall(path.read_text(encoding="utf-8"))
        return found

    def test_the_marker_inventory_count_is_unchanged(self):
        markers = self.markers()
        self.assertEqual(len(markers), MARKER_INVENTORY)
        self.assertEqual(len(set(markers)), MARKER_INVENTORY)

    def test_the_final_conformance_marker_selects_opus_high(self):
        text = (SHARED_TREE / "sdd/conformance-reviewer-prompt.md").read_text(encoding="utf-8")
        markers = [line for line in text.splitlines()
                   if line.startswith("<!-- agent-dispatch:")]
        self.assertEqual(markers, [CONFORMANCE_MARKER])
        self.assertIn(CONFORMANCE_CALL, text)
```

`home/common/agent-skills/tests/test_workflow_skill_contracts.py`: append,
before the `if __name__ == "__main__":` block:

```python
class AcceptanceGradingContractsTest(unittest.TestCase):
    """#272: the conformance axis grades every acceptance criterion on Opus/high."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_the_conformance_axis_runs_on_opus_high(self):
        final_review = self.read(SDD_DIR / "final-review.md")
        sdd = self.read(SDD)
        prompt = self.read(SDD_DIR / "conformance-reviewer-prompt.md")
        self.assertIn("Native `reviewer` on the Opus/high tier selected in "
                      "[conformance-reviewer-prompt.md](conformance-reviewer-prompt.md)",
                      final_review)
        self.assertIn("(parent D3)", final_review)
        self.assertNotIn("checklist-shaped work", final_review)
        self.assertIn("the conformance axis as `reviewer` on Opus/high;", sdd)
        self.assertIn("Subagent (reviewer, Opus/high as selected above):", prompt)
        for name, text in (("final review", final_review), ("sdd", sdd),
                           ("prompt", prompt)):
            with self.subTest(document=name):
                self.assertNotIn("Sonnet", text)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -5`
Expected: FAIL. The matrix test fails on the role tier and the site,
`test_the_final_conformance_marker_selects_opus_high` fails, and
`test_the_conformance_axis_runs_on_opus_high` fails.
`test_the_marker_inventory_count_is_unchanged` already passes at the base,
because it guards against drift.

- [ ] **Step 3: Write the minimal implementation**

1. `model-matrix.json`:
   - `roles.conformance-reviewer.model` → `"opus"`.
   - The `dispatch_sites` entry with id `sdd-final-conformance-review`:
     `marker` → the produced marker, `call` → the produced call (JSON-escaped
     as its neighbours are), `model` → `"opus"`.
   - The sdd scenario event with `"dispatch": "sdd-final-conformance-review"`:
     `model` → `"opus"`.
   - Keep the file's formatting.
2. `python/agent_tools/agent_model_matrix.py`: in `EXPECTED_ROLE_TIERS`, set
   `"conformance-reviewer": ("opus", "high")`.
3. `conformance-reviewer-prompt.md`: replace the marker line and the
   `Agent(...)` line under it with the produced marker and call. Replace the
   first fence line, `Subagent (reviewer, Sonnet/high as selected above):`,
   with `Subagent (reviewer, Opus/high as selected above):`.
4. `final-review.md`, in the **Conformance axis** bullet: replace its last
   sentence (it starts with the word `Native` and names the Sonnet/high tier
   and "checklist-shaped work"), through the end of the bullet, with exactly:

```text
Native `reviewer` on the Opus/high tier selected in [conformance-reviewer-prompt.md](conformance-reviewer-prompt.md): this axis also grades the issue's acceptance criteria, which gate delivery, and in the review study the cheaper tier missed real historical defects that Opus caught (parent D3).
```

5. sdd `SKILL.md`, `## Agent tiers`: in the final-review bullet, replace

```text
the conformance axis as `reviewer` on Sonnet/high;
```

   with

```text
the conformance axis as `reviewer` on Opus/high;
```

   Leave the rest of the bullet as it is.
6. Instruction-load ceilings. Measure with:

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
   `Ceiling raised for #272: the final conformance axis moved to Opus/high (#155 D10).`
   Re-run the script: it must print nothing. When it prints nothing on the
   first run, change nothing.

- [ ] **Step 4: Verify**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -3`
Expected: `OK`.

Run: `just agent-model-matrix`
Expected: exit 0, and the output includes the line
`agent model matrix: valid`.

Run: `if grep -q 'conformance-reviewer model=sonnet' home/common/agent-skills/model-matrix.json home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md; then exit 1; fi`
Expected: exit 0. At the base commit this exits 1.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/model-matrix.json python/agent_tools/agent_model_matrix.py home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(sdd): run the final conformance axis on Opus/high (#272)"
```
Under a `Lifecycle worker:` line, commit with
`launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "<message>"`
instead of `git commit`.
