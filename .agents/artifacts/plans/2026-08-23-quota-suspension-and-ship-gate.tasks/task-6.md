# Task 6: Cost reporter `interrupted` outcome

**Files:**
- Modify: `scripts/agent-costs.py`
- Test: `tests/test_agent_costs.py`

**Interfaces:**
- Consumes (existing): `classify_outcome(final_text)` (~102–110), the regex constants `STRONG_DONE_RE`/`BLOCKED_RE`/`WEAK_DONE_RE` (~82–89), `group_outcome(g)` (~547–556). The reporter reads transcript text only — never ledgers (per D14).
- Produces:
  - `INTERRUPTED_RE = re.compile(r"suspended \(blocked_on=", re.IGNORECASE)` alongside the other constants.
  - `classify_outcome` order becomes: `STRONG_DONE_RE` → `"completed"`; `INTERRUPTED_RE` → `"interrupted"`; `BLOCKED_RE` → `"blocked"`; `WEAK_DONE_RE` → `"completed"`; else `"abandoned"`. The interrupted check MUST precede the blocked check: the canonical line contains `blocked_on`, whose substring `blocked` would otherwise match `BLOCKED_RE` first.
  - `group_outcome` precedence becomes: `completed` > `interrupted` > `blocked` > `abandoned` (empty → `"-"` unchanged).

**Invariants:**
- A final text containing the canonical stop line `Suspended (blocked_on=usage_limit). Resume: /from-issue 101 --auto` classifies as `interrupted`, never `abandoned` and never `blocked` (#101 acceptance criterion; per D14).
- Any final text that classified `completed` before this task still classifies `completed` (STRONG/WEAK done regexes untouched, STRONG still first).
- The outcome table renders the new label without special-casing (it prints whatever `group_outcome` returns).

- [ ] **Step 1: Write the failing tests** (extend `OutcomeTest`, which calls the functions directly):

```python
def test_canonical_suspension_line_classifies_interrupted(self):
    line = "Suspended (blocked_on=usage_limit). Resume: /from-issue 101 --auto"
    self.assertEqual(agent_costs.classify_outcome(line), "interrupted")

def test_interrupted_beats_blocked_regex_overlap(self):
    line = "Work paused. Suspended (blocked_on=human_gate). Resume: /from-issue 7 --auto"
    self.assertEqual(agent_costs.classify_outcome(line), "interrupted")

def test_group_outcome_precedence_with_interrupted(self):
    self.assertEqual(agent_costs.group_outcome({"outcomes": ["interrupted", "abandoned"]}), "interrupted")
    self.assertEqual(agent_costs.group_outcome({"outcomes": ["blocked", "interrupted"]}), "interrupted")
    self.assertEqual(agent_costs.group_outcome({"outcomes": ["completed", "interrupted"]}), "completed")
```

(Match `group_outcome`'s real parameter shape — read its current call convention first; if it takes the group dict `g` with a different key than `outcomes`, mirror the existing precedence tests' arrangement.)

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m unittest -v -k interrupted tests/test_agent_costs.py`
Expected: FAIL — `classify_outcome` returns `blocked` (the `blocked_on` substring) or `abandoned`.

- [ ] **Step 3: Implement** — one regex constant, one reordered function body, one precedence-list edit.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v tests/test_agent_costs.py`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/agent-costs.py tests/test_agent_costs.py
git commit -m "feat(scripts): classify canonical suspension stops as interrupted, not abandoned"
```

**Verification (falsifiable):** at base, `python3 -c "import importlib.util,sys; spec=importlib.util.spec_from_file_location('ac','scripts/agent-costs.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m.classify_outcome('Suspended (blocked_on=usage_limit). Resume: x'))"` prints `blocked` (or `abandoned`) — after, it prints `interrupted`. Cite: D14 and the spec's Outcome reporting decision.
