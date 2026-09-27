# Task 4: from-issue names the replies it reads, then the final gate

Per D6, D8, and #155 D10/D29. Abbreviations: `SK` =
`home/common/agent-skills/skills`, `T` = `home/common/agent-skills/tests`.

**Files:**
- Modify: `SK/from-issue/SKILL.md`, `home/common/agent-skills/instruction-load.json`
- Test: `T/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the wire from Tasks 2 and 3. `progress` prints a `phase_gate`
  whose `action` is the persisted action. `suspend` prints a `suspended` (with
  `blocked_on` and `reentry`) or, at the stall bound, a `kind: terminal` replay
  (with `reentry`).
- Consumes: `agent_tools.instruction_load.load_model(bytes) -> dict`,
  `measure(model, read) -> dict` and `tree_reader(root: Path)`, all under
  `PYTHONPATH=python`.
- Produces: nothing that a later task reads.

**Invariants:**
- `AUTO.md`, every other skill, and every architecture or standards document
  stay unchanged (D8).
- The existing pins stay green. They are `Obey the returned action exactly`,
  `continue | fresh_start | handoff | delegate`, the suspend command substring,
  `Suspended (blocked_on=<value>). Resume: <reentry from the envelope>`, the
  handoff/suspension distinction sentence, `no \`finish\` call`, and the
  ordered deadline-routing anchors.
- Only the profile-host pairs whose hot total now exceeds its ceiling change.
  Each is raised to its measured hot bytes, and each raised profile's `note`
  gains one sentence in the same commit (#155 D10). Ceilings are written by the
  scratch script below over `measure`, never by hand (#155 D29).

- [ ] **Step 1: Write the failing tests**

In `T/test_workflow_skill_contracts.py`, class `WorkflowSkillContractsTest`,
insert these methods immediately before `def test_terminal_replay_relays_reentry`:

```python
    def test_phase_gate_obeys_the_validated_phase_gate_action(self):
        """#191 D8: the obeyed action is the validated `phase_gate` reply's `action`."""
        self.assertIn(
            "Obey the returned action exactly: it is the `action` of the validated "
            "`phase_gate` reply, and the closed set is "
            "`continue | fresh_start | handoff | delegate`:",
            normalized(self.from_issue))

    def test_suspension_validates_its_reply_and_replays_a_stall_bound_terminal(self):
        """#191 D6, D8: suspend's reply is validated; a `terminal` reply is a replay."""
        suspension = self.section(
            self.from_issue, "## Suspension procedure", "## Phase 0"
        )
        self.assertIn(
            "workflow-state suspend --repo-root <ledger_repo_root> --run-id <run-id> "
            "--now <utc> --issue <n> --attempt <k> --blocked-on <value> "
            "| artifact-budget validate-report --boundary workflow-response --input -\n",
            suspension,
        )
        self.assert_ordered(
            normalized(suspension),
            "A validated `kind: terminal` reply means the anti-zombie bound ended "
            "the attempt instead: handle it as the terminal replay in the terminal "
            "return procedure — print its `reentry`, relay it, and write no "
            "`finish` — and stop.",
            "Otherwise the reply is `kind: suspended`; print the canonical line",
            "Suspended (blocked_on=<value>). Resume: <reentry from the envelope>",
        )
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k phase_gate_obeys -k stall_bound_terminal 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'`
Expected: `FAILED (failures=2)`.

- [ ] **Step 3: Edit `SK/from-issue/SKILL.md`**

1. In `**Executable phase gate.**`, replace
   `Obey the returned action exactly; the closed set is` + newline +
   `` `continue | fresh_start | handoff | delegate`: `` with exactly:
   ```text
   Obey the returned action exactly: it is the
   `action` of the validated `phase_gate` reply, and the closed set is
   `continue | fresh_start | handoff | delegate`:
   ```
   The text before `Obey` on that first line (`` --context-headroom 10000`. ``)
   stays as it is.
2. In `## Suspension procedure`, the fenced command line becomes exactly:
   ```text
   workflow-state suspend --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --issue <n> --attempt <k> --blocked-on <value> | artifact-budget validate-report --boundary workflow-response --input -
   ```
3. In the same section, replace
   `(the reaper alone owns \`unknown\`). Then print the canonical line as the final`
   + newline + `user-facing output:` with exactly:
   ```text
   (the reaper alone owns `unknown`). A validated `kind: terminal` reply means the
   anti-zombie bound ended the attempt instead: handle it as the terminal replay in
   the terminal return procedure — print its `reentry`, relay it, and write no
   `finish` — and stop. Otherwise the reply is `kind: suspended`; print the
   canonical line as the final user-facing output:
   ```

Nothing else in the file changes. The canonical `Suspended (…)` line, "That
line is the last thing you emit", and the handoff/suspension sentence stay
byte for byte.

- [ ] **Step 4: Raise the breached ceilings**

Run `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | grep -E '^(FAIL|ERROR):|exceed|^Ran |^OK|^FAILED'`
and watch `test_the_live_tree_breaches_no_ceiling` fail on the profiles that
hot-load `from-issue/SKILL.md`. Then run this scratch script once from the
worktree root. It is not committed.

```bash
PYTHONPATH=python python3 - <<'EOF'
import json
from pathlib import Path
from agent_tools import instruction_load
path = Path("home/common/agent-skills/instruction-load.json")
raw = path.read_bytes()
model = instruction_load.load_model(raw)
measurement = instruction_load.measure(model, instruction_load.tree_reader(Path(".")))
data = json.loads(raw)
sentence = (" Ceiling raised for #191's validated `progress` and `suspend` replies,"
            " which grew `from-issue/SKILL.md` (#155 D10).")
raised = []
for profile in data["profiles"]:
    breached = False
    for host in profile["hosts"]:
        hot = measurement["profiles"][profile["id"]][host]["hot"]["bytes"]
        if hot > profile["ceiling_bytes"][host]:
            profile["ceiling_bytes"][host] = hot
            breached = True
    if breached:
        profile["note"] += sentence
        raised.append((profile["id"], profile["ceiling_bytes"]))
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(raised)
EOF
```

Expected: it prints exactly `from-issue-controller`, `orchestrated-issue-owner`
and `implementation-owner`, five profile-host pairs in all. A planning probe of
these edits measured claude/codex 87836, claude 148223 and claude/codex 139348.
Those are estimates; the script's measured values are authoritative. The file
round-trips byte for byte through `json.dumps(indent=2, ensure_ascii=False)`, so
`git diff --stat -- home/common/agent-skills/instruction-load.json` shows
`8 insertions(+), 8 deletions(-)`.

- [ ] **Step 5: Verify, then run the final gate**

1. `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'` → `OK`, with the file's existing skips.
2. Scope gate, run before the commit. It fails on a stray skill or document edit, and it fails at the start:
   `test "$(git diff --name-only HEAD -- home/common/agent-skills/skills home/common/agent-skills/instruction-load.json docs CLAUDE.md | tr '\n' ' ')" = "home/common/agent-skills/instruction-load.json home/common/agent-skills/skills/from-issue/SKILL.md "`
3. Final gate, from the worktree root:
   - `just agent-workflow-tests 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED' | tail -5` → one `Ran N tests` line and `OK (skipped=…)`.
     The planning probe of Tasks 1–4 gave `Ran 1373 tests` and `OK (skipped=3)`:
     11 new tests over a derived base of 1362. The count is an estimate, and it
     moves with `main`. This takes about 25 minutes.
   - `just build`, run directly and unpiped so its own exit status is the gate → exit 0. Never `just switch`.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  home/common/agent-skills/instruction-load.json
git commit -m "docs(from-issue): read the validated phase_gate and suspend replies (#191)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
