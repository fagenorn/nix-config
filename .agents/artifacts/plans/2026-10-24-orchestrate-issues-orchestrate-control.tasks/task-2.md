# Task 2: Drive the skill through `start` and `step`

Spec § Solution, § Adapter state and the step protocol, § Reading `start` and `step`, § Executing a ready report, § What the skill keeps byte-identical, § Skill-text pins, § Living documents and the instruction budget; per D1–D4, D7, D8, D12, D13, D14. The Claude `orchestrate-issues` skill stops building requests, contracts and owner objects: §1 becomes one `orchestrate-control start`, §3 one `orchestrate-control step` per event, and §4 launches the report's `dispatches[]`. Its pins follow the new argv, the three living documents that cite removed text are re-pointed, and the one ceiling the shrink leaves loose is lowered, all in one commit: `test_instruction_load.LiveBudgetTest` runs the budget gate inside `just agent-workflow-tests`, so a loose ceiling fails the suite at any commit that leaves it (D13).

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/acquire-durable.md`
- Modify: `home/common/agent-skills/README.md` (§ Lifecycle helpers, the resume-pack sentence)
- Modify: `python/README.md` (§ `orchestrate-control`, the closing D11 sentence)
- Modify: `home/common/agent-skills/instruction-load.json` (profile `orchestration-dispatcher`)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 1): `orchestrate-control` whole-allowed in `home/common/claude-code/default.nix` and in `COMMAND_VOCABULARY`; without them the `step` heredoc example below is refused by `SourceTreeSweepTest`.
- Consumes (#403, unchanged): `orchestrate-control start --repo-root R <numbers>|--label L|--milestone M [--run-id I]` printing `{command, outcome: ready|unsupported|refused, session|route, …}`; `orchestrate-control step --repo-root R --input -` reading exactly `{session, first_sweep, owners, contracts_due, refused_contracts}` and printing a ready object `{command, outcome, run_id, control_calls, response, dispatches, contracts_due, refused_contracts, contract_refusals, ends_run}` or a refusal `{command, outcome: "refused", step, detail, completed_steps, response}`; each `dispatches[]` entry is `{action_id, launch_kind, issue, attempt, owner, worktree, handoff_path, owner_object, resume_pack}` (`python/README.md` § `orchestrate-control`).
- Produces: the skill text Task 4's evals grade.

**Invariants:**
- The skill holds none of `workflow-state launch`, `workflow-state reconcile`, `workflow-state host-route`, `workflow-state init-run`, `workflow-state control`, `workflow-state build-delivery`, `workflow-state resume-pack`, `--request-file`, `"interface_version": 3` (D4, D14).
- These regions stay byte-identical to the base (D7), each named by its first and last text: the owner dispatch from "<!-- agent-dispatch: id=orchestration-issue-owner" through "Never inline issue bodies or any content artifact in that prompt."; the envelope fence from "--repo-root <ledger_repo_root>" through "from-issue <num> --auto"; the wait rules from "For \`wait\`, adapter state consists only of" through "Never poll or repeat short sleeps.". Step 4's check compares them.
- The skill has exactly one `resolve-project resolve`, its policy entry names only `bindings.workflow.orchestration.stall_minutes`, and it never mentions `build-delivery` (D1, D4).
- `acquire-durable.md` names no `orchestrate-issues` and does not grow (1994 bytes at the base; D8).
- No instruction ceiling rises; only ceilings the gate reports on a `tightness:` line are lowered (D13).

- [ ] **Step 1: Write the failing pins**

Edit `home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

1. Delete the two constants `V2_CONTROL_REQUEST_KEYS = {…}` (five lines) and `V3_CONTROL_REQUEST_KEYS = V2_CONTROL_REQUEST_KEYS | {"host_route"}`; nothing else reads them once item 5 lands.
2. Replace the comment above `ORCHESTRATE_MACHINE_TEXT` and the whole `ORCHESTRATE: (…),` member (up to, not including, `    CODEX_ORCHESTRATE: (`) with:

```python
# Machine-consumed text each orchestrate-issues tree must carry (#291 D6):
# lifecycle helper argv, the `orchestrate-control` step input and the
# ready-report members the adapter reads (#404 D4), and the observation values
# the dispatcher sends. No guidance sentence is pinned.
ORCHESTRATE_MACHINE_TEXT = {
    ORCHESTRATE: (
        "orchestrate-control start --repo-root <ledger_repo_root>",
        "orchestrate-control step --repo-root <ledger_repo_root> --input -",
        "`session`", "`first_sweep`", "`owners`", "`contracts_due`", "`refused_contracts`",
        "`dispatches`", "`owner_object`", "`resume_pack`", "`contract_refusals`", "`ends_run`",
        "--boundary workflow-response", "`worktree_fact`",
        "`recorded_worktree_absent`", "`recorded_worktree_mismatch`",
        "workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> "
        "--action-id <action_id>",
        "launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --sweep",
        "run_in_background=true", "`launch_refused`", "`unavailable`",
        "workflow-state owner-liveness --repo-root <ledger_repo_root> --run-id <run-id> "
        "--action-id <action_id> --stall-minutes <stall_minutes> "
        "| artifact-budget validate-report --boundary workflow-response --input -",
        "workflow-state owner-liveness --repo-root <ledger_repo_root> --run-id <run-id> "
        "--action-id <action_id> --stall-minutes <stall_minutes> --since <liveness_since>",
        "`wait_seconds`", "`liveness_since`", "`stalled`", "`past_deadline`",
        "`not_current`",
    ),
```

3. In `CLAUDE_POLICY_ENTRIES`, replace the five-line `"orchestrate-issues/SKILL.md": (…),` member with `    "orchestrate-issues/SKILL.md": ("bindings.workflow.orchestration.stall_minutes",),`.
4. In `test_build_delivery_callers_name_the_sanctioned_resolution_exception`, delete the list line `            "home/common/claude-code/skills/orchestrate-issues/SKILL.md",`.
5. In `test_direct_and_control_requests_are_interface_two`, delete the six lines from `        decide = self.section(self.orchestrate, "## 3. Decide", "## 4. Execute control actions")` through `            self.assertIn(argv, normalized(decide))`; the `ACQUIRE_DIRECT` half and the closing `host_route: "direct"` assertion stay.
6. Replace the body of `test_dispatcher_calls_no_retired_lifecycle_command` with:

```python
    def test_dispatcher_calls_no_retired_lifecycle_command(self):
        # #404 AC1: every control round goes through orchestrate-control, so the
        # dispatcher spells no lifecycle call that helper makes, and no request.
        for retired in ("workflow-state launch", "workflow-state reconcile",
                        "workflow-state host-route", "workflow-state init-run",
                        "workflow-state control", "workflow-state build-delivery",
                        "workflow-state resume-pack", "--request-file",
                        '"interface_version": 3'):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, self.orchestrate)
```

- [ ] **Step 2: Run the pins and watch them fail**

Run (timeout 900 s): `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py`
Expected: FAIL — `test_orchestrate_documents_carry_their_machine_text` (12 subtests: both `orchestrate-control` argv and the ten backticked members), `test_dispatcher_calls_no_retired_lifecycle_command` (7 subtests, every new absence pin) and `test_build_delivery_callers_name_the_sanctioned_resolution_exception`; nothing else.

- [ ] **Step 3: Rewrite the skill**

Apply these edits to `home/common/claude-code/skills/orchestrate-issues/SKILL.md` in order. Each old text occurs exactly once; blocks are copied verbatim, the content between the four-backtick fence lines.

**E1.** Replace everything from the line that begins with the text below (the first body line, after the `# orchestrate-issues — a control adapter, not a manager` heading and its blank line) through the line `none of these cases and keeps its wait-ID handling below:` and the one blank line after it with Block A, which ends with that same line and one blank line:

```text
You are an external adapter around `workflow-state`. You resolve bindings, normalize tracker,
```


````markdown
You are an external adapter around `orchestrate-control`, which reads the tracker, the forge, git
and the ledger, builds delivery contracts, runs every control round and projects its owner
dispatches. You keep the duties that need host task handles: owner launches, notification
classification, liveness, the stop pass, wait observers and the final report. You never read issue
content, code, specs, plans, diffs, review findings, the tracker, the forge, git or the ledger, and
never build a request or a contract. Do not retain a second task ledger or reconstruct lifecycle
policy.

Lifecycle commands run the helpers at `~/.agents/bin/orchestrate-control` and
`~/.agents/bin/workflow-state`; if a bare name does not resolve on PATH, use its full path.

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain
the returned `ResolvedProject` in memory, and treat every resolver error as fatal
before mutation or external effects. On refusal, preserve and report the
resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never
translate it into a partial snapshot or fallback. Take only
`bindings.workflow.orchestration.stall_minutes` from it: when present and non-null it is
`stall_minutes`, the owner stall bound of §2 rules (a) and (d), passed only to `owner-liveness`;
absent or null, those rules arm no liveness check. Nested issue owners independently resolve at
their own phase entries. Do not read raw policy, invoke another resolver, infer from Git, or supply
defaults; `orchestrate-control` resolves the project itself on every call, and this dispatcher
never resolves again.

Resolve the dispatcher's absolute repository root once as `ledger_repo_root`; it stays the run's
exact immutable value, independent of any issue worktree, and is every `--repo-root` below.

## 1. Start the run

Open the run with one `start` call carrying exactly one issue selector: the caller's numbers in
the caller's order, `--label <label>` or `--milestone <milestone>`. A run minted with a creation key
is re-entered by adding `--run-id <run-id>`:

```text
orchestrate-control start --repo-root <ledger_repo_root> <numbers>
orchestrate-control start --repo-root <ledger_repo_root> --label <label>
orchestrate-control start --repo-root <ledger_repo_root> --milestone <milestone>
orchestrate-control start --repo-root <ledger_repo_root> <numbers> --run-id <run-id>
```

Read its one stdout object by `outcome`:

- `ready`: keep its `session` verbatim for the rest of the run; its `run_id` is `<run-id>` below.
- `unsupported`: the host route is unsupported. Render the `route` it carries, with its
  `alternative`, as the final report and stop, dispatching nothing.
- `refused`, or `orchestrate-control: invalid invocation` on stderr: report its `step` and `detail`
  (or that line) and stop; nothing is armed yet.

The helper validates every `workflow-state` reply it reads, so `start` and `step` output is never
piped through `validate-report`. `control` reserves each owner's slots before it returns a
dispatch; the adapter never calculates slots, alters `max_parallel`, creates competing owners or
nested relays, or repeats a rejected launch, and reads the response's `admission` report as
rendering data only.

## 2. Observe

Correlate a current host owner notification only with the `action_id` and `custody` recorded beside
its handle (§4), and normalize it as the bounded owner event for that exact issue, attempt and
launch identity; its `state` is `unavailable` for an owner that died and `launch_refused` for an
owner launch the host refused. Ignore unrelated or stale host notifications.
Classify every other host notification by its task handle,
against the handles recorded beside owner launches; a wake of the current wait handle is
none of these cases and keeps its wait-ID handling below:

````

**E2.** In rule (b), replace

```text
  custody in the next control call. On `current: false`, send nothing. Either way, refresh and
  continue the normal sweep.
```

with

```text
  custody in the next `step`. On `current: false`, send nothing. Either way, continue the
  normal sweep.
```

**E3.** In rule (d), replace the line

```text
  in the next control call, refreshing and making that call at once and executing its response. A
```

with

```text
  in the next `step`, making that call at once and executing its report. A
```

**E4.** Delete the paragraph (two lines and the blank line after it):

```text
At start/resume and after each current owner notification, tracker change or wait-ID wake, refresh
the facts the next request needs.
```

**E5.** Replace everything from the line `## 3. Decide` through the line `remainder mode). The owner dispatch envelope is:` and the one blank line after it with Block B (which ends with `The owner dispatch envelope is:` and one blank line, so the envelope fence follows unchanged):

````markdown
## 3. Step

Make exactly one `step` call at start or resume, and on each current owner notification, tracker
change or current wait-ID wake. Feed it this object on stdin through a quoted heredoc; no input
file is written:

```text
orchestrate-control step --repo-root <ledger_repo_root> --input - <<'EOF'
{"session": <session>, "first_sweep": <first_sweep>, "owners": <owners>, "contracts_due": <contracts_due>, "refused_contracts": <refused_contracts>}
EOF
```

- `session` is the object `start` printed, unchanged.
- `first_sweep` is `true` on the first `step` after `start` in this adapter process, `false` after.
- `owners` holds this event's observations: one `unavailable` from §2 rule (b) or (d), or the
  `launch_refused` observations of §4. Each rides exactly one call and is cleared after it.
- `contracts_due` and `refused_contracts` are the previous ready report's members of those names,
  passed back verbatim; both are `[]` on the first `step`.

`step` gathers the facts, builds the delivery contracts and runs the control round itself; the
adapter never builds a contract, assembles a request or calls `control`. Read its one stdout object
by `outcome`:

- `ready`: execute it as §4 says. Its `response` is the validated control response; its
  `dispatches` are the owner launches; keep its `contract_refusals` only for §5.
- `refused`, `orchestrate-control: invalid invocation`, or any other exit or stdout: end the run as
  `finalize` does, executing no action of the `response` it carries, and report its `step` and
  `detail` verbatim (or that stderr line) with the `action_id` of every owner handle still running,
  so the report never reads as a finished run. A re-invocation re-enters the run.

## 4. Execute control actions

Validate each action of a ready report's `response` as one of the closed kinds `spawn`, `resume`,
`retry`, `delivery_remainder`, `delivery_contract`, `wait`, or `finalize`, and execute actions in
returned order. Any other kind is a contract error: stop without executing it and surface the
unknown kind; fail loudly. The response is the only source of action order, kind and lifecycle
identity: never infer, reorder, omit or add an action.

**Stop pass.** Before executing the first action of a report whose `dispatches` is non-empty,
stop the superseded owners. The candidates are every owner
handle this adapter process recorded beside an owner launch's `action_id` that has produced no final
return. An interim notification under §2 rule (a) is not a final return. The current wait handle and
non-owner handles are never candidates; a handle this response dispatches becomes one only once
dispatched. For each candidate, run
`workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
with the `action_id` recorded beside it. On `current: false`, stop that handle through the host's
task-stop and mark it stopped; a missing or already exited handle counts as stopped. On
`current: true`, leave it running. A `check-launch` that exits non-zero, or whose output cannot be
parsed, is unknown, never `current: false`: leave the handle a candidate; so is a failed stop, and
the next pass tries both again. A stop failure never blocks dispatch; keep it a candidate for §5.
The pass sends no observation, makes no `step` and writes nothing to the ledger, so
a later notification from a stopped handle still falls under §2 rule (b). The pass ends by running
`launch-scope reap --repo-root <ledger_repo_root> --run-id <run-id> --sweep` once. A sweep that
exits non-zero never blocks dispatch: keep its exit code and, when it printed a report, its
`skipped` launches for §5.

Each `spawn`, `resume`, `retry` and `delivery_remainder` action arrives as one `dispatches[]`
entry, in the same order. Fill the envelope from the entry's members of the same names
(`action_id`, `issue`, `attempt`, `owner`, `worktree`, and `handoff_path` only when non-null), with
this adapter's `ledger_repo_root` and the `session`'s `run_id`. Put the entry's `owner_object`
verbatim in the prompt as its canonical JSON, and, when its `resume_pack` is non-null, that text
verbatim as the `Resume pack` paragraph; never decode either. Dispatch the owner in the background
with these values; pass the helper-issued action ID and owner token unchanged and never substitute
a host task ID. Both object kinds use this one dispatch (a `delivery_remainder` owner is
`from-issue` launching ship-issue remainder mode). The owner dispatch envelope is:

````

**E6.** Replace these seven lines (the two paragraphs after the envelope fence):

```text
For `resume`, include the returned `handoff_path` when present. For a `delivery_remainder`,
`attempt` is its `source_attempt`, `action_id` is its custody's `action_id`, and there is no
`handoff_path`. Record the host task handle beside the action ID only for notification correlation
and the stop pass; it is never an owner token or action identity.

If the host refuses an owner launch, never retry it: make exactly one control call carrying a
`launch_refused` owner observation for that action's `custody`, and execute that response.
```

with Block C:

````markdown
Record the host task handle beside the entry's `action_id` and the `custody` of the
`response.actions` entry whose `custody.action_id` equals it, only for notification correlation and
the stop pass; it is never an owner token or action identity.

If the host refuses an owner launch, never retry it, and keep launching the report's later
dispatches and executing its later actions. Once the report has executed, make one `step` carrying
a `launch_refused` owner observation for each refused launch's `custody`, and execute its report.
````

**E7.** In the `finalize` paragraph, replace

```text
further control call to prepare the report.
```

with

```text
further `step` to prepare the report.
```

**E8.** Replace the whole `delivery_contract` paragraph (the eight lines below) with Block D:

```text
For `delivery_contract`, a missing delivery contract is all that stops each issue in its `issues`
list, and control armed no deadline, so nothing else will wake the run.
This is the one rule for such an issue. Send each listed issue's contract as §3 describes (the pair
built for it earlier in this invocation, else build it now) and make the next control call at once;
that response takes over from this one. Never rebuild an issue whose build this invocation refused:
send null and `[]` for it. When the builder has refused every listed issue in this invocation, the
action ends the run as `finalize` does: run the stop pass, clear the wait state as for `finalize`
and render §5 from this response.
```

Block D:

````markdown
For `delivery_contract`, a missing delivery contract is all that stops each issue in its `issues`
list, and control armed no deadline, so nothing else will wake the run. When the report's
`ends_run` is true, every listed issue's build was refused: the action ends the run as `finalize`
does, and §5 renders from this response. Otherwise make the next `step` at once; it passes this
report's `contracts_due` back, `step` builds those contracts, and its report takes over from this
one.
````

**E9.** In §5, replace

```text
Render a `finalize` action, or a `delivery_contract` action that ends the run because every listed
build was refused, from the bounded summaries in the same interface_version 3 control response.
```

with

```text
Render a `finalize` action, or a `delivery_contract` action whose report's `ends_run` is true,
from the bounded summaries in the same interface_version 3 control response.
```

**E10.** In §5, replace

```text
the builder refusal from §3 when there was one
```

with

```text
that issue's retained `contract_refusals` `detail` when there was one
```

Then re-point the living documents (D8). Each old text below occurs once, and each new text replaces it exactly.

`home/common/agent-skills/skills/from-issue/acquire-durable.md`, four replacements, old then new:

```text
(source `explicit_user`, reference `invocation:/from-issue <num>`) under orchestrate-issues' per-issue contract rule: from
(source `explicit_user`, reference `invocation:/from-issue <num>`): from
```

```text
call `workflow-state control` again, as orchestrate-issues §4 describes. Only
call `workflow-state control` again. Only
```

```text
Send the interface-3 control request (orchestrate-issues' 17-key shape) with
Send the interface-3 control request with
```

```text
Project it into the owner object as orchestrate-issues does and adopt
Project it into the owner object (rename `id` to `action_id` and `kind` to `launch_kind`; add `kind: owner`, `interface_version: 2`, `ledger_repo_root` and `run_id`) and adopt
```

`home/common/agent-skills/README.md` (§ Lifecycle helpers), old then new:

```text
orchestrate-issues §4 adds it to `resume` prompts, and from-issue to direct re-entry, `delegate` and the Phase-5 rollover;
`orchestrate-control step` fetches it for each `resume` dispatch as its `resume_pack`, which orchestrate-issues adds to the owner prompt, and from-issue adds it to direct re-entry, `delegate` and the Phase-5 rollover;
```

`python/README.md` (§ `orchestrate-control`), old then new:

```text
Teaching the `orchestrate-issues` skill to call the command is a follow-up (D11).
The `orchestrate-issues` skill drives every run through `start` and `step` (#404).
```

Then lower the loose ceiling (D13). Run (timeout 900 s) `just agent-instruction-budget`. Expected at planning: exactly one failing line,

```text
tightness: profile orchestration-dispatcher on claude: hot ceiling 27809 is more than 5% above its measured 20470 bytes; run `just agent-instruction-load tighten`
```

Do not run `tighten` (it lowers every ceiling above its measure, not only the loose ones). For each `tightness:` line, set that ceiling to the measured bytes the line prints, and append to the profile's `note` one space and the sentence "Ceiling lowered for #404: the skill hands every control round to orchestrate-control start and step (#404 D9, D13)." Keep the file's format by writing it as `json.dumps(model, indent=2, ensure_ascii=False) + "\n"`; for the expected line:

```python
import json
from pathlib import Path
path = Path("home/common/agent-skills/instruction-load.json")
model = json.loads(path.read_text(encoding="utf-8"))
(profile,) = [p for p in model["profiles"] if p["id"] == "orchestration-dispatcher"]
assert profile["ceiling_bytes"] == {"claude": 27809}
profile["ceiling_bytes"]["claude"] = 20470  # the measure the tightness line printed
profile["note"] += (" Ceiling lowered for #404: the skill hands every control round to "
                    "orchestrate-control start and step (#404 D9, D13).")
path.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

A `ceiling:` line (a breach) or a `lint:` line means the text grew or broke a lint rule: fix the text, never raise a ceiling.

- [ ] **Step 4: Verify**

1. Run `shasum -a 256 home/common/claude-code/skills/orchestrate-issues/SKILL.md` and `wc -c < home/common/claude-code/skills/orchestrate-issues/SKILL.md`. Expected at planning: `a771dcb79cff7765e645ea763251a8d8aa929523539878c85aac9d6f4774d9ef` and `20470`; a different value means a block or replacement was not copied verbatim, so diff the file against the blocks (an edit the plan review accepted changes both values, and the measured ceiling with them).
2. Run (timeout 300 s) this check of the kept regions (D7); expected `kept regions identical`:

```bash
python3 - <<'PY'
import subprocess
path = "home/common/claude-code/skills/orchestrate-issues/SKILL.md"
base = subprocess.run(["git", "show", "648f833c:" + path], capture_output=True, text=True,
                      check=True).stdout
head = open(path, encoding="utf-8").read()
def region(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i) + len(end)]
for start, end in (
        ("<!-- agent-dispatch: id=orchestration-issue-owner",
         "Never inline issue bodies or any content artifact in that prompt."),
        ("```text\n--repo-root <ledger_repo_root>\n", "from-issue <num> --auto\n```"),
        ("For `wait`, adapter state consists only of", "Never poll or repeat short sleeps.")):
    assert region(base, start, end) == region(head, start, end), start
print("kept regions identical")
PY
```

3. Run `wc -c < home/common/agent-skills/skills/from-issue/acquire-durable.md` (expected `1978`, at most 1994) and `if grep -n 'orchestrate-issues' home/common/agent-skills/skills/from-issue/acquire-durable.md; then exit 1; fi` (expected: no output, exit 0).
4. Run (timeout 900 s): `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_eval_cases.py home/common/agent-skills/tests/test_instruction_load.py`
   Expected: `OK (skipped=3)`, 344 tests at planning.
5. Run (timeout 900 s): `just agent-instruction-budget`. Expected: `check: pass`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/orchestrate-issues/SKILL.md \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  home/common/agent-skills/skills/from-issue/acquire-durable.md \
  home/common/agent-skills/README.md python/README.md \
  home/common/agent-skills/instruction-load.json
launch-commit … -- -m "feat(orchestrate-issues): drive every run through orchestrate-control start and step (#404)" -m "<session trailers>"
```
