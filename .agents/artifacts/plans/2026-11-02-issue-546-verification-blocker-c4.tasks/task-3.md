# Task 3: Owner procedures, ceilings and the lifecycle README

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/final-review.md` (`## Final verification`, step 4)
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (the lifecycle-call rule; `## Suspension procedure`)
- Modify: `home/common/agent-skills/skills/from-issue/acquire-direct.md` (item 1, new item 5, the clearing rule)
- Modify: `home/common/agent-skills/instruction-load.json` (three profiles' `ceiling_bytes` and `note`, `corpus_ceiling_bytes`)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify: `home/common/agent-skills/tests/test_shell_example_contracts.py` (`COMMAND_VOCABULARY`)
- Modify: `home/common/agent-skills/README.md` (`### Verification blockers`)
- Modify: `python/README.md` (`## verification-observe`, its known-limitations sentence)

**Interfaces:**
- Consumes: Task 2's ready member `verification_refusals` and gathering (named in the README only); the landed `suspend --verification-input -` (issue 544 D8), the direct-owner `expects.build` (issue 545 D10) and the `suspended` envelope's members (issue 544 D7).
- Produces: instruction text only, no code interface. Skill-text test helpers `validate_workflow_response(value) -> subprocess.CompletedProcess` and `normalize_declaration(declaration) -> subprocess.CompletedProcess` in `test_workflow_skill_contracts.py` (D17).

**Invariants:**
- Instruction text grows only in `final-review.md`, `from-issue/SKILL.md` and `acquire-direct.md` (D8).
- from-issue keeps one home for the `suspend` verb: its first template line is byte-identical, a second literal template follows it for `verification` only, the cause list orders `verification` after sdd's `deadline` and before the reaper's parenthesis, and the lifecycle-call rule lists `--verification-input -` (D5).
- sdd classifies under a lifecycle identity, before the repair, only when every failing declared command qualifies, and declares the first in run order; the adapter runs before any worker release or reap; every other case (no lifecycle identity, a `record` exit 3 or helper exit 2 with no failing command, a change-caused failure, a refusal) repairs as written (D5, D14, D18).
- acquire-direct answers `verification` through `expects.build` without restating its command line, and item 5 names exactly the seven `suspended` members, after item 4 (D6).
- Each breached hot ceiling and the corpus ceiling equal their measure at this task's head; each raised profile's `note` gains one sentence; no other ceiling, conditional ceiling or `description_ceiling_bytes` moves (D8).
- `from-issue/SKILL.md` leaves the issue-227 growth pin, and every other document it lists keeps its pin (D16).
- Skill-text tests pin only rule-6 surfaces: `workflow-state` argv, the closed cause value, a JSON key set validated by the wire, and a vetted shell example; the behavioural pins run in children (D11, D17).

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

1. `INPUT_FLAG_RE` becomes `re.compile(r"(--request-file|--checkpoint-file|--summary-file|--verification-input|--input)\s+(\S+)")` (wrapped over two lines), so every lifecycle document's `--verification-input` value is checked to be `-`.
2. In `test_owner_has_executable_phase_gate_and_action_semantics`, the dict comprehension becomes a loop that keeps the first line per verb, so the canonical `suspend` template stays the pinned one:

   ```python
           templates = {}
           for line in self.from_issue.splitlines():
               if line.startswith(("workflow-state progress ", "workflow-state suspend ")):
                   templates.setdefault(line.split()[1], line.split(" | ")[0].split())
   ```
3. In `test_suspension_procedure_admits_agent_dispatch`, the ordered anchors become `"`human_gate`", "`external`", "`agent_dispatch`", "`deadline`", "`verification`", "(the reaper alone owns `unknown`)"`, and right after that test add:

   ```python
       def test_the_verification_cause_has_its_own_suspend_template(self):
           """Issue 546 D5: the second `suspend` template adds only the cause and its stdin flag,
           and the lifecycle-call rule lists that flag."""
           suspends = [line.split(" | ")[0].split() for line in self.from_issue.splitlines()
                       if line.startswith("workflow-state suspend ")]
           self.assertEqual([[word for word in words if word.startswith("--")]
                             for words in suspends],
                            [["--repo-root", "--run-id", "--action-id", "--blocked-on"],
                             ["--repo-root", "--run-id", "--action-id", "--blocked-on",
                              "--verification-input"]])
           second = suspends[1]
           self.assertEqual(second[second.index("--blocked-on"):],
                            ["--blocked-on", "verification", "--verification-input", "-", "<<'EOF'"])
           rule = next(block for block in self.from_issue.split("\n\n")
                       if block.startswith("Every lifecycle call is one command"))
           self.assertIn("`--verification-input -`", rule)
   ```
4. Before `def test_auto_names_the_dispatch_gap_fallback_and_relays_closed_lines(self):` add:

   ```python
       def test_final_verification_declares_a_blocker_the_adapter_accepts(self):
           """Issue 546 D5: final-review's declaration, each placeholder filled with a valid
           value, is one the source `normalize_declaration` accepts, and unclassified it is not."""
           review = (SDD_DIR / "final-review.md").read_text(encoding="utf-8")
           (line,) = [line.strip() for line in review.splitlines()
                      if line.strip().startswith('{"command_id": ')]
           for placeholder, value in (("<id>", "nix-build"), ("<class>", "dependency"),
                                      ("<absolute worktree>", "/tmp/wt"), ("<name>", "flake-lock"),
                                      ("<path>", "flake.lock")):
               line = line.replace(f'"{placeholder}"', json.dumps(value))
           declaration = json.loads(line)
           done = normalize_declaration(declaration)
           self.assertEqual(done.returncode, 0, done.stderr)
           unclassified = {key: value for key, value in declaration.items()
                           if key != "failure_class"}
           self.assertIn("unclassified", normalize_declaration(unclassified).stderr)
   ```
5. In `test_direct_auto_observe_owner_terminal_loop_is_closed`, the ordered anchors gain `"kind: suspended"` after `"kind: terminal"`. Before `def test_adjacent_from_issue_acquisition_modes_remain_unchanged(self):` add:

   ```python
       def test_direct_acquisition_relays_exactly_a_suspended_reply(self):
           """Issue 546 D6: item 5's members are a `suspended` reply's whole key set, as the
           source workflow-response validator admits it (issue 544 D16)."""
           text = normalized(ACQUIRE_DIRECT.read_text(encoding="utf-8"))
           item = text[text.index("**`kind: suspended`**"):]
           members = re.findall(r"`([a-z_]+)`", item[:item.index(";")])
           sample = {"interface_version": 2, "kind": "suspended", "run_id": "run-1", "issue": 151,
                     "custody": {"kind": "implementation", "attempt": 1, "launch": 1,
                                 "action_id": "151:1:1"},
                     "blocked_on": "verification", "reentry": "/from-issue 151 --auto"}
           reply = {name: sample.get(name) for name in members}
           done = validate_workflow_response(reply)
           self.assertEqual(done.returncode, 0, done.stderr)
           for name in members:
               with self.subTest(dropped=name):
                   less = {key: value for key, value in reply.items() if key != name}
                   self.assertEqual(validate_workflow_response(less).returncode, 2)
   ```
6. Before `def skill_sections(document, *sections):` add the two child-process helpers (D17):

   ```python
   def validate_workflow_response(value):
       """The source `artifact-budget validate-report --boundary workflow-response` over `value`, in
       a child with `PYTHONPATH` set to `python/` and a temporary `HOME` holding the source policy,
       because the installed-mode run has no package on its path (issue 505 D8, issue 546)."""
       with tempfile.TemporaryDirectory() as home:
           share = Path(home) / ".agents/share"
           share.mkdir(parents=True)
           (share / "artifact-budget-policy.json").symlink_to(
               REPO_ROOT / "home/common/agent-skills/artifact-budget-policy.json")
           return subprocess.run(
               [sys.executable, str(REPO_ROOT / "home/common/agent-skills/scripts/artifact_budget.py"),
                "validate-report", "--boundary", "workflow-response", "--input", "-"],
               input=json.dumps(value), capture_output=True, text=True, timeout=60, check=False,
               env={**os.environ, "HOME": home, "PYTHONPATH": str(REPO_ROOT / "python")})


   def normalize_declaration(declaration):
       """The source `verification_blocker.normalize_declaration` over `declaration` in a child with
       `PYTHONPATH` set to `python/` (issue 505 D8, issue 546): exit 0 when it accepts it."""
       return subprocess.run(
           [sys.executable, "-c", "import json, sys\n"
            "from agent_tools.verification_blocker import normalize_declaration\n"
            "normalize_declaration(json.load(sys.stdin))\n"],
           input=json.dumps(declaration), capture_output=True, text=True, timeout=60,
           check=False, env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "python")})
   ```
7. The issue-227 growth pin (D16): above `def assert_no_larger_than_base(test, paths):`, after the `BUDGET_BASE = …` line, add the comment `# from-issue/SKILL.md left these pins when issue 546 grew it under labelled instruction` / `# ceilings, the standing growth gate this base stood in for (issue 546 D16).`; remove `FROM_ISSUE_DIR / "SKILL.md"` from the tuples of `test_edited_planning_documents_do_not_grow` and `test_edited_execution_documents_do_not_grow`, keeping every other path.

In `home/common/agent-skills/tests/test_shell_example_contracts.py`, `COMMAND_VOCABULARY` gains `"verification-observe"` between `"uv"` and `"wc"`, so final-review's `text`-fence call is vetted as a sanctioned lifecycle call (whole-allowed, quoted heredoc; parent D18).

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k declares_a_blocker -k suspended_reply -k own_suspend_template -k admits_agent_dispatch -k terminal_loop_is_closed 2>&1 | grep -E '^(Ran|OK|FAILED)'`
Expected: `Ran 5 tests`, `FAILED (failures=3, errors=2)`: no second template, no `verification` cause, no item 5 and no declaration (two `ValueError` errors, from the missing item 5 and the missing declaration line, and three failures).

- [ ] **Step 3: Write the procedures, the ceilings and the docs**

`from-issue/SKILL.md` (D5):
- The lifecycle-call rule's `` `--summary-file -` or `--input -` `` becomes `` `--summary-file -`, `--verification-input -` or `--input -` ``.
- In `## Suspension procedure`, `` or sdd's `deadline` (the reaper alone owns `unknown`). A validated `kind: terminal` reply `` becomes:

  ````text
  or sdd's `deadline` or `verification` (the reaper alone owns `unknown`). For `verification` call instead, feeding the failure `verification-observe failure` printed:

  ```text
  workflow-state suspend --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> --blocked-on verification --verification-input - <<'EOF' | artifact-budget validate-report --boundary workflow-response --input -
  <the printed failure, unchanged>
  EOF
  ```

  A validated `kind: terminal` reply
  ````

`acquire-direct.md` (D6):
- Item 1: before `Build `delivery_contract` with one command.` insert `` Answer `verification` by running its `expects.build`, `<ledger_repo_root>` filled, on the requirement less `expects` through a quoted heredoc, and append the printed observation to `verification`. ``; `A builder refusal (exit 2, empty stdout)` becomes `A builder or adapter refusal (exit 2, empty stdout)`.
- After item 4 add: ``5. **`kind: suspended`**: require exactly `interface_version`, `kind`, `run_id`, `issue`, `custody`, `blocked_on` and `reentry`; print `Suspended (blocked_on=<blocked_on>). Resume: <reentry>` as the final output, stop before Phase 1, and install no waiter.``
- The clearing rule's `` `owner`, `delivery_remainder`, `terminal`, or any failure `` becomes `` `owner`, `delivery_remainder`, `suspended`, `terminal`, or any failure ``.

`sdd/final-review.md` step 4 (D5, D14): replace its third line's `Dispatch the final-review fixer above once, carrying the failing command and` with the block below (3-space list indentation kept), so the step reads on with `its log path, …` unchanged:

````text
   Under a lifecycle identity, first classify each failing command. It is a
   shared blocker only when its cause lies outside the change and
   integration-branch paths decide it: a pinned dependency (`dependency`), the
   declared environment (`environment`), an external service
   (`external_service`) or the command's declared input (`command_input`); a
   product, test or build failure of the change never is. When at least one
   command failed and every failing command qualifies, run for the first in
   run order, in the foreground and before any worker release or reap:

   ```text
   verification-observe failure --repo-root <ledger_repo_root> --input - <<'EOF'
   {"command_id": "<id>", "failure_class": "<class>", "worktree": "<absolute worktree>", "facts": [{"name": "<name>", "paths": ["<path>"]}]}
   EOF
   ```

   Exit 0: follow from-issue's suspension procedure with
   `blocked_on=verification` and the printed failure. Every other case
   repairs: no lifecycle identity, no failing command (a `record` exit 3 or
   a helper exit 2 alone), a change-caused failure, or a refusal. Dispatch
   the final-review fixer above once, carrying the failing command and
````

`instruction-load.json` (D8): run `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base 763d8d48570c747ad368d0849939328ad12b49ed`; it prints one `ceiling:` line per breached ceiling (the prototype measured `from-issue-controller` 72073 on both hosts, `implementation-owner` 133940 on both, `orchestrated-issue-owner` 138309 on `claude`, corpus 405818; use your own measures). Set each named `ceiling_bytes` host value and `corpus_ceiling_bytes` to exactly its printed measure; touch nothing it does not name. Append to the end of each raised profile's `note`, inside its string:
- `from-issue-controller`: `` Ceiling raised for #228 (issue 546): from-issue/SKILL.md's suspension procedure gained the `verification` cause and its `--verification-input -` template, and acquire-direct.md answers a `verification` requirement and relays a `suspended` reply (#155 D10).``
- `implementation-owner` and `orchestrated-issue-owner`: `` Ceiling raised for #228 (issue 546): from-issue/SKILL.md's suspension procedure gained the `verification` cause and its `--verification-input -` template, and sdd/final-review.md's Final verification declares a shared verification blocker before its repair (#155 D10).``

`home/common/agent-skills/README.md` § `### Verification blockers` (D9, D10): replace the second paragraph's tail `` `orchestrate-control step` gathers the observations (`python/README.md` § `orchestrate-control`). Known limitation: acquire-direct fails loudly on a `verification` requirement and on a `suspended` reply; that is issue 546.`` (with its leading space) by three new paragraphs:

```text
The callers close the loop (issue 546, [design](../../../.agents/artifacts/specs/2026-11-02-issue-546-verification-blocker-c4-design.md)). sdd's Final verification declares a blocker under a lifecycle identity: before its repair, when every failing declared command fails for a cause outside the change that integration-branch paths decide (`dependency`, `environment`, `external_service` or `command_input`, never a product, test or build failure of the change), it runs `verification-observe failure` for the first of them in run order, in the foreground and before any worker release or reap, because the suspension procedure's reap deletes the scratch root a refused declaration's repair still needs. Exit 0 follows from-issue's suspension procedure with `blocked_on=verification`, whose second literal template feeds the printed failure to `suspend --verification-input -`; a refusal, or a mix holding a change-caused failure, takes the repair as written, and a failure after the repair keeps the Residuals route. `orchestrate-control step` observes every requirement the bootstrap lists once per step, after at most one fetch, sends the observations on its first `control` call only (`[]` on a chained second), and reports each requirement it could not observe in its ready object's `verification_refusals`, leaving that attempt parked (`python/README.md` § `orchestrate-control`). acquire-direct answers a `verification` requirement by running its `expects.build` on the requirement less `expects`, and relays a `suspended` reply with `Suspended (blocked_on=<blocked_on>). Resume: <reentry>`, stopping before Phase 1. acquire-durable sends `verification: []` and keeps its one-dispatch rule, so a run parked on `verification` fails loudly there.

Known limitations: repository paths are the only fact kind, so an outage that no path decides stays a `transport` suspension; an orchestration observes once per step, so a run whose only remaining work is parked ends in `finalize`, and re-invoking the orchestration observes again; a resumed attempt's worktree does not take in the change that resolved its record, so if its command fails again the adapter's guard refuses (the worktree's `HEAD` differs from `origin`) and the owner repairs instead of parking again; and a contract whose `project.id` or integration branch changed while a record is open makes control refuse every observation of that record, so every later step refuses at `control`.

A ledger that a reviewed source helper migrated to schema 11 is refused by every older installed helper (`unknown_schema`, nothing written; issue 544). Until `just switch` installs that source, every call for that run comes from the same checkout: `workflow-state` runs as `PYTHONPATH=<checkout>/python python3 <checkout>/home/common/agent-skills/scripts/workflow-state.py`, a `workflow-state` shim for it is first on `PATH`, because `orchestrate-control`, `launch-scope`, `launch-commit`, `sdd-gate` and other `agent_tools` commands run it by name, and those commands, `verification-observe` included, run from that checkout's `python/`. No ledger marker records which helper wrote a run: an installed helper's `unknown_schema` refusal is the signal that a call came from the wrong place.
```

`python/README.md` § `verification-observe`, known limitations: ``; and nothing calls the command yet, because its callers arrive in later children of issue 228 (c2 to c4).`` becomes ``. Its callers are listed in `home/common/agent-skills/README.md` § Verification blockers.``

- [ ] **Step 4: Verify**

Run (timeout 600 s): `PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner --jobs 4 home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_skill_lint.py 2>&1 | tail -1`
Expected: `suite-runner: summary members=4 passed=4 failed=0`.
Run (timeout 300 s): `env -u PYTHONPATH python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k declares_a_blocker -k suspended_reply -k own_suspend_template 2>&1 | tail -1`
Expected: `OK` (the installed-tier shape: no package on the path, D17).
Run (timeout 3000 s), AC1's set: `PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner --jobs 6 home/common/agent-skills/tests/test_attempt_migration.py home/common/agent-skills/tests/test_verification_suspension.py home/common/agent-skills/tests/test_verification_control.py home/common/agent-skills/tests/test_verification_direct.py home/common/agent-skills/tests/test_control_cutover.py tests/test_verification_blocker.py tests/test_verification_observe.py tests/test_orchestrate_control.py 2>&1 | tail -1`
Expected: `suite-runner: summary members=8 passed=8 failed=0`.
Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base 763d8d48570c747ad368d0849939328ad12b49ed --raise-label; grep -c '"verification-observe"' home/common/agent-skills/tests/test_shell_example_contracts.py; grep -c 'Ceiling raised for #228 (issue 546)' home/common/agent-skills/instruction-load.json`
Expected: `check: pass`, `1`, `3`.
Run (timeout 600 s): `just agent-instruction-budget --raise-label`
Expected: `check: pass`. Without `--raise-label` it fails with `raise:` lines: CI's `Instruction Budget` stays red until the user applies the label, which no agent applies (D8).
Stage first, then run (timeout 3600 s): `just build`
Expected: exit 0.

AC2 is graded at the final review as the root's acceptance map says (D18): its final-head clause through the Declared verification line, its process clauses from this plan's SDD workspace `progress.md`; this task writes nothing for it.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/acquire-direct.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/README.md python/README.md
launch-commit … -- -m "feat(skills): route shared verification blockers" -m "Issue 546." -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":3,"records":[{"bounds":[{"added_lines":24,"boundary":"all","deleted_lines":3,"record_bytes":4096,"support":{"covers":["r3a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3a","last_task":3,"owner":3,"path":"home/common/agent-skills/skills/sdd/final-review.md"},{"bounds":[{"added_lines":13,"boundary":"all","deleted_lines":4,"record_bytes":8192,"support":{"covers":["r3b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3b","last_task":3,"owner":3,"path":"home/common/agent-skills/skills/from-issue/SKILL.md"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":5,"record_bytes":8192,"support":{"covers":["r3c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3c","last_task":3,"owner":3,"path":"home/common/agent-skills/skills/from-issue/acquire-direct.md"},{"bounds":[{"added_lines":10,"boundary":"all","deleted_lines":10,"record_bytes":40960,"support":{"covers":["r3d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3d","last_task":3,"owner":3,"path":"home/common/agent-skills/instruction-load.json"},{"bounds":[{"added_lines":110,"boundary":"all","deleted_lines":12,"record_bytes":21504,"support":{"covers":["r3e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3e","last_task":3,"owner":3,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":2560,"support":{"covers":["r3f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3f","last_task":3,"owner":3,"path":"home/common/agent-skills/tests/test_shell_example_contracts.py"},{"bounds":[{"added_lines":9,"boundary":"all","deleted_lines":3,"record_bytes":22528,"support":{"covers":["r2f","r3g"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3g","last_task":3,"owner":3,"path":"home/common/agent-skills/README.md"},{"bounds":[{"added_lines":10,"boundary":"all","deleted_lines":10,"record_bytes":59392,"support":{"covers":["r1c","r2d","r3h"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3h","last_task":3,"owner":3,"path":"python/README.md"}]}}
```
