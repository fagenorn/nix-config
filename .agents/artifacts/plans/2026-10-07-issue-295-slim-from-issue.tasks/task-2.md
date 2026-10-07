# Task 2: Split the Phase-5 rollover out of AUTO.md and cut AUTO.md

**Files** (under `home/common/agent-skills/`):
- Create: `skills/from-issue/rollover.md`, `skills/from-issue/delegated-owner.md`
- Modify: `skills/from-issue/AUTO.md`, `skills/from-issue/SKILL.md` (index bullets and the four rollover pointers only)
- Modify: `instruction-load.json`, `skill-lint-debt.json`
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's tree. `bindings.md` and `grounding.md` are gone.
- Produces:
  - `rollover.md`, headed `# Phase-5 rollover (direct autonomous controller)`, with sections `## Mandatory transfer gate` and `## Earlier controller stop`. The continuation is one ```` ```json ```` fence whose `owner` has the 19 `V2_OWNER_KEYS`.
  - `delegated-owner.md`, headed `# Fresh delegated owner`, with one section `## Checks and Phases 6–7`.
  - `AUTO.md` with these `##` headings in this order: `The self-answer pattern`, `When *not* to auto-resolve`, `Phases 2–4 run as subagents` (with `### Design subagent — Phases 2 + 3` and `### Plan subagent — Phase 4 (+ mechanical Phase 5)`), `Interface_version 2 delivery relay`, `Other Phase 5–7 routes`. Task 3's `resume-pack.md` and Task 6's index name them.
  - Test constants `ROLLOVER` and `DELEGATED_OWNER`. `LIFECYCLE_DOCS` becomes a glob over `from-issue/*.md`.

**Invariants:**
- The `from-issue-design-grill` and `from-issue-planning` markers and their call lines stay in `AUTO.md`, byte for byte, each call on the line after its marker (per D3).
- Both report-shape blocks of each `AUTO.md` site keep their exact JSON text. `AUTO.md` must not end with exactly one unlabeled fence.
- `AUTO.md` keeps the fog-gate bullet's rule text and still names `REVIEW-CONTRACT.md`. Its last paragraph is the push/PR-open/merge human-gate paragraph that begins "At every Phase-6 or Phase-7 push, PR-open, or merge gate" (per D9).
- `AUTO.md`, `rollover.md` and `delegated-owner.md` name no sibling file. They refer to other content by phase or by a `SKILL.md` heading.
- The rollover's order and closed sets are unchanged:
  - Transfer gate: checks, then `progress`, then delegate.
  - Bookkeeper: release, then reap, then a dispatch running `check-launch` then `finish`.
  - Earlier controller: two byte-matched line exceptions, then validate-and-relay, then the six "does not" prohibitions.
- Byte targets (root Global Constraints): `AUTO.md` 8,500, `rollover.md` 3,800, `delegated-owner.md` 3,000.

- [ ] **Step 1: Re-point the machine-read tests (they fail until Step 3)**

In `tests/test_workflow_skill_contracts.py`, add the constants beside `AUTO`, and replace `LIFECYCLE_DOCS`:

```python
ROLLOVER = REPO_ROOT / "home/common/agent-skills/skills/from-issue/rollover.md"
DELEGATED_OWNER = REPO_ROOT / "home/common/agent-skills/skills/from-issue/delegated-owner.md"
```

```python
LIFECYCLE_DOCS = (*sorted((REPO_ROOT / "home/common/agent-skills/skills/from-issue").glob("*.md")),
                  SHIP_ISSUE, SHIP_ISSUE_REVIEW, SHIP_ISSUE_HUMAN_GATE, ORCHESTRATE)
```

(`FROM_ISSUE_DIR` is defined after `LIFECYCLE_DOCS`'s current line. Spell the path out, or move the assignment below `FROM_ISSUE_DIR`.)

In `test_lifecycle_calls_are_single_stdin_commands_on_interface_two`, change the `STDIN_CLAUSE` loop to `for path in (ORCHESTRATE, SHIP_ISSUE):`. That clause is prose on the scoped file (per D13).

Replace these two methods of `WorkflowSkillContractsTest`:

```python
    def test_capability_gap_line_is_spelled_identically_everywhere(self):
        # One closed line, compared byte for byte and never decoded (per D4).
        pattern = r"capability_gap[^`\n]*"
        self.assertIn(CAPABILITY_GAP_LINE, self.ship_issue)
        self.assertEqual(set(re.findall(pattern, self.ship_issue)), {CAPABILITY_GAP_LINE})
        carriers = set()
        for path in sorted(FROM_ISSUE_DIR.glob("*.md")):
            spellings = set(re.findall(pattern, path.read_text(encoding="utf-8")))
            with self.subTest(document=path.name):
                self.assertLessEqual(spellings, {CAPABILITY_GAP_LINE})
            if spellings:
                carriers.add(path.name)
        self.assertLessEqual({"ship-handoff.md", "delegated-owner.md"}, carriers)

    def test_auto_continuation_and_bookkeeper_are_interface_two(self):
        owner = json_block(ROLLOVER.read_text(encoding="utf-8"))["owner"]
        self.assertEqual((set(owner), owner["interface_version"]), (V2_OWNER_KEYS, 2))
        self.assert_ordered(normalized(DELEGATED_OWNER.read_text(encoding="utf-8")),
                            "workflow-state check-launch",
                            "workflow-state finish --summary-file -")
```

Replace `LaunchScopeWiringContractsTest.test_the_bookkeeper_route_reaps_before_dispatch`. It keeps the argv order and drops the English anchors:

```python
    def test_the_bookkeeper_route_reaps_before_dispatch(self):
        self.assert_ordered(self.read(DELEGATED_OWNER), self.REAP,
                            "workflow-state check-launch", "workflow-state finish")
```

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k capability_gap -k continuation_and_bookkeeper -k bookkeeper_route_reaps` (timeout 300 s)
Expected: ERROR, `FileNotFoundError` for `rollover.md` / `delegated-owner.md`.

- [ ] **Step 3: Move and cut**

1. `rollover.md` gets these parts of `AUTO.md`'s `### Mandatory direct implementation-owner rollover`, in order:
   - its opening paragraph, cut to one sentence;
   - `#### Mandatory transfer gate`, through the continuation JSON fence (relabelled ```` ```json ```` if needed), the "Pass the unchanged owner object…" constraint list, and the resume-pack-beside-the-continuation paragraph;
   - `#### Earlier controller stop`.

   Cut the sentence "The fresh owner resolves once at its own phase entry…", which restates `SKILL.md`'s resolve rule. Collapse the seven "no …" bullets into one sentence with the same seven exclusions.
2. `delegated-owner.md` gets `#### Fresh delegated owner` plus the mechanical-only paragraph that follows it. Rewrite "`SKILL.md`'s `### Resume pack` says" as "the resume pack's checks say". Rewrite "`SKILL.md`'s Phase-7 dispatch-gap fallback" as "Phase 7's dispatch-gap fallback". Name no file.
3. `AUTO.md`:
   - Delete the moved text.
   - Cut rationale: "The shift is *what you do*…" down to its last sentence, the audit-trail sentence of the self-answer step 3, "because brainstorm and grill transcripts…", "Splitting these into two dispatches would mean…", and "design quality is worth paying for here".
   - Replace each `decision-ledger.md` mention with "the C1 decision-ledger format (its file is in `SKILL.md`'s index)", and the `investigate.md` mention with "Phase 0's PR pre-flight".
   - Open `## Other Phase 5–7 routes` with one sentence: a direct autonomous controller hands Phases 6–7 to a fresh owner at the Phase-5 rollover, and every other route keeps the behaviour below.
   - Order the sections as in Interfaces, so the file ends on the human-gate paragraph.
   - Leave the opening "Under direct autonomous acquisition, a resume is not a takeover" paragraph in place. Task 3 moves it.
4. `SKILL.md`:
   - Add two bullets to `## Files beside this one`: "`rollover.md` — the direct autonomous controller's Phase-5 transfer and its stop afterwards" and "`delegated-owner.md` — the fresh owner delegated at that rollover; read it first, before any resume pack". Remove the `#### Fresh delegated owner` sentence from the `AUTO.md` bullet.
   - Rewrite the three remaining rollover pointers to name the new files: in `### Resume pack`, the `delegate` paragraph under `## Dispatch, phase-budget and attempt-budget rules`, and `## Terminal return procedure`'s earlier-controller paragraph.

- [ ] **Step 4: Delete the prose pins on the moved text**

Apply D11 and D13 to every method that reads `AUTO.md` or `SKILL.md`'s rollover pointers:
- `WorkflowSkillContractsTest`: `test_auto_names_the_dispatch_gap_fallback_and_relays_closed_lines`, `test_autonomous_reports_and_ship_handoff_are_root_plus_metrics`, `test_autonomous_over_budget_reports_include_required_violations`, `test_received_reports_cross_the_same_json_wire_seam`, `test_fixture_producer_states_supplement_behavioral_cli_cases`, `test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner`, `test_auto_gate_enumeration_covers_an_unguarded_host`, `test_direct_autonomous_bookkeeper_checks_before_the_terminal_finish`, `test_direct_auto_authorizations_are_explicit_and_never_inferred`, `test_auto_mode_never_skips_durable_checkpoints_or_terminal_writes`.
- The AUTO-reading parts of `LaunchFencedWorkerContractsTest.test_auto_subagents_commit_through_launch_commit_and_the_bookkeeper_is_unregistered`, `ResumePackContractsTest`, `InterimChildResultContractsTest.test_the_suspension_and_auto_pointers_route_to_the_paragraph` and `LaunchScopeWiringContractsTest.test_the_worker_sentence_follows_every_composed_worker_line`.

How to treat each assertion:
- Keep and re-point the JSON key-set assertions (`V2_OWNER_KEYS`, the report shapes in `AUTO.md`).
- Keep the argv and closed-line orderings. Drop their English anchors, and an ordering left with one anchor becomes `assertIn`.
- Delete every English-phrase assertion.

- [ ] **Step 5: Models**

- `instruction-load.json`:
  - `from-issue-controller`: add `from-issue/rollover.md` to `hot`, and add unread `"from-issue/delegated-owner.md": "the controller delegates Phases 6–7 at the rollover and never runs them as the fresh owner"`.
  - `orchestrated-issue-owner`: add unread `"from-issue/rollover.md": "a dispatcher-owned owner never takes the direct Phase-5 rollover"` and `"from-issue/delegated-owner.md": "only the owner delegated at the direct Phase-5 rollover reads it"`.
  - `implementation-owner`: add `from-issue/delegated-owner.md` to `hot`, and add unread `"from-issue/rollover.md": "the transfer gate and the earlier controller's stop run in the controller; this owner receives the continuation"`.
- `skill-lint-debt.json`: delete `L3 …/from-issue/AUTO.md`, `L4b …/from-issue/AUTO.md names decision-ledger.md` and `L4b …/from-issue/AUTO.md names investigate.md` (per D12).
- Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 6: Verify**

Run the focused suite (root Global Constraints). Expected: OK.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run:

```bash
set -euo pipefail
F=home/common/agent-skills/skills/from-issue
python3 - <<'EOF'
from pathlib import Path
F = Path("home/common/agent-skills/skills/from-issue")
caps = {"AUTO.md": 8500, "rollover.md": 3800, "delegated-owner.md": 3000}
for name, cap in caps.items():
    size = len((F / name).read_bytes())
    if size > cap:
        print(f"over target: {name} {size} > {cap} (name it in the commit body)")
auto = (F / "AUTO.md").read_text(encoding="utf-8").rstrip("\n")
assert auto.rsplit("\n\n", 1)[-1].startswith("At every Phase-6 or Phase-7 push, PR-open, or merge gate"), "AUTO.md does not end on the human-gate paragraph"
assert "REVIEW-CONTRACT.md" in auto
EOF
if grep -q 'Mandatory transfer gate' "$F/AUTO.md"; then exit 1; fi
```

Expected: exit 0, with any `over target` line named in the commit body. At the base this fails, because `rollover.md` is absent.

- [ ] **Step 7: Commit**

Commit as `refactor(from-issue): split the Phase-5 rollover into rollover.md and delegated-owner.md (#295)`.
