# Task 3: Validate control's reply bytes before commit

Acceptance 2 of #220. Per D5, D6, D8, D10, D15.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`artifact_budget_validate`,
  `control_summary`, `command_control`, `print_json`, new `render_json`)
- Modify: `home/common/agent-skills/tests/test_delivered_control.py` (imports, one helper,
  one test)
- Modify: `home/common/agent-skills/tests/test_workflow_state.py`
  (`test_control_finalizes_on_blocked_issues_from_current_facts`, one expectation)

**Interfaces:**
- Consumes: from Task 1's test file — `DeliveredControlTest` and its `BuilderHarness` methods
  `project()`, `build(kind, value)`, `contract_input()`, `control_request(issues, *,
  contracts, intents, worktrees)`, `cli(...)`, and `self.root`, `self.home`,
  `self.worktree`; `NOW`, `POLICY` from `test_delivery_workflow`. At base,
  `artifact_budget_validate(command, input_path=None, *, boundary=None, input_bytes=None)
  -> dict` and `transact(repo_root, run_id, mutation, *, allow_missing=False,
  migration_contracts=None) -> Any`, which commits only after `mutation` returns.
- Produces: `render_json(value: Any) -> bytes` in `workflow-state.py` — the one home of the
  wire format, which `print_json(value)` now writes (per D15); the refusal text
  `artifact-budget <command> rejected the <boundary> boundary` (or
  `... rejected the detail input` when `boundary` is None).

**Invariants:**
- The bytes control validates are the bytes it prints: one `bytes` value, rendered once with
  `sort_keys=True, separators=(",", ":")` plus `"\n"`, UTF-8. The validator's canonical
  stdout is never substituted for it (per D5).
- Validation runs inside the ledger transaction, after the reply is fully built and before
  `control(state)` returns, so a rejection raises before `commit_state`: the state file is
  byte-identical, stdout is empty, the exit status is 2, and stderr is one line
  `workflow-state: artifact-budget validate-report rejected the workflow-response boundary`
  (per D5, D8).
- The validator is the one `artifact_budget_validate` already resolves (source
  `artifact_budget.py` plus `../artifact-budget-policy.json`, else the installed executable
  and policy), invoked with `validate-report --boundary workflow-response --input -`; no new
  import machinery (per D5).
- `orchestrate-issues` §4's adapter-side validation is not touched (per D6).
- Control's summary blockers are ordered by `(kind, issue)`, the wire's closed order;
  `control_blockers` itself and the direct-owner terminal it feeds are unchanged (per D10).

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_delivered_control.py`, add `import os`,
`import shutil` and `import tempfile` to the standard-library imports (alphabetical with the
existing ones), and add `SCRIPTS` to the `from .test_delivery_workflow import (...)` list
(it is defined there as `ROOT / "home/common/agent-skills/scripts"`). Then append these
methods to `DeliveredControlTest`, after the last existing test:

```python
    def isolated_workflow(self, wire_max_bytes):
        """A source-layout copy of the scripts tree beside a policy of its own.

        The copy resolves `artifact_budget.py` and `../artifact-budget-policy.json`
        exactly as the source tree does, so its control reply meets the real
        boundary under `workflow_responses.wire_max_bytes` = ``wire_max_bytes``.
        """
        tree = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tree, True)
        shutil.copytree(SCRIPTS, tree / "agent-skills/scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        policy["workflow_responses"]["wire_max_bytes"] = wire_max_bytes
        (tree / "agent-skills/artifact-budget-policy.json").write_text(
            json.dumps(policy), encoding="utf-8")
        return tree / "agent-skills/scripts/workflow-state.py"

    def test_a_rejected_reply_leaves_the_ledger_byte_identical(self):
        """Acceptance 2: a reply the boundary rejects commits nothing and prints nothing."""
        self.project()
        built = self.build("contract", self.contract_input())
        workflow = self.isolated_workflow(64)
        env = {**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        run_args = ("--repo-root", str(self.root), "--run-id", "atomic")
        initialized = subprocess.run(
            [sys.executable, str(workflow), "init-run", *run_args, "--now", NOW],
            capture_output=True, check=False, env=env)
        self.assertEqual(initialized.returncode, 0, initialized.stderr.decode())
        state = self.root / ".superpowers/workflows/atomic/state.json"
        before = state.read_bytes()
        request = json.dumps(self.control_request(
            [171], contracts={"171": built["contract"]},
            intents={"171": [built["initial_intent"]]},
            worktrees=[{"issue": 171, "recorded": None,
                        "candidate": {"path": self.worktree, "state": "absent"}}])).encode()
        refused = subprocess.run(
            [sys.executable, str(workflow), "control", *run_args, "--request-file", "-"],
            input=request, capture_output=True, check=False, env=env)
        self.assertEqual(
            (refused.returncode, refused.stdout, refused.stderr),
            (2, b"", b"workflow-state: artifact-budget validate-report rejected the "
                     b"workflow-response boundary\n"))
        self.assertEqual(state.read_bytes(), before)
        # Under the real policy the same request spawns and commits.
        admitted = self.cli("control", *run_args, "--request-file", "-", stdin=request)
        self.assertEqual([a["kind"] for a in json.loads(admitted.stdout)["actions"]],
                         ["spawn", "wait"])
        self.assertNotEqual(state.read_bytes(), before)
```

In `home/common/agent-skills/tests/test_workflow_state.py`,
`test_control_finalizes_on_blocked_issues_from_current_facts`, change the `combined`
blocker expectation to the wire's `(kind, issue)` order (per D10):

```python
        self.assertEqual(combined["summaries"][0]["blockers"], [
            {
                "kind": "decision", "issue": 41,
                "url": "https://github.com/fagenorn/nix-config/issues/41",
            },
            {"kind": "issue", "issue": 40, "url": None},
        ])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivered_control.py -k rejected_reply 2>&1 | tail -4`
Expected: FAIL — the tuple starts `(0, b'{"actions":` where `(2, b'', b'workflow-state: ...')`
is expected: control printed and committed a reply the boundary rejects.

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k test_control_finalizes_on_blocked_issues_from_current_facts 2>&1 | tail -3`
Expected: FAIL — control still renders `issue` before `decision`.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/scripts/workflow-state.py`:

1. `artifact_budget_validate`: replace the refusal
   `raise WorkflowError(f"artifact-budget {command} rejected the terminal result")` with

```python
        subject = "detail input" if boundary is None else f"{boundary} boundary"
        raise WorkflowError(f"artifact-budget {command} rejected the {subject}")
```

   (`validate-detail-input` is the only caller without a boundary.)
2. Replace `print_json` with `render_json` and a `print_json` that writes it, so the wire
   format has a single home (per D15):

```python
def render_json(value: Any) -> bytes:
    """The wire rendering of ``value``: what `print_json` writes and control validates."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def print_json(value: Any) -> None:
    sys.stdout.write(render_json(value).decode("utf-8"))
```

   The bytes are unchanged for every caller: `json.dumps` escapes non-ASCII by default, so
   the decoded text is ASCII and `json.dump` plus `"\n"` wrote the same characters.
3. `control_summary`: pass
   `blockers=sorted(control_blockers(tracker), key=lambda item: (item["kind"], item["issue"]))`
   instead of `blockers=control_blockers(tracker)`. Do not edit `control_blockers`: its
   other two callers feed `direct-owner`'s terminal, which is out of scope (per D1, D10).
4. `command_control`: change the inner `def control(state: dict[str, Any] | None) ->
   tuple[dict[str, Any], bool]` annotation to `-> tuple[bytes, bool]`. At the end of that
   function, render the reply dict to bytes, validate, and return the bytes instead of the
   dict:

```python
        reply = render_json({
            "interface_version": CONTROL_INTERFACE_VERSION,
            # ... the existing members, unchanged ...
            "admission": report,
        })
        # The reply is the only source of action order, so a reply the boundary
        # rejects must not commit: validation raises before `transact` commits,
        # and the validated bytes are the bytes printed (#220 D5).
        artifact_budget_validate(
            "validate-report", boundary="workflow-response", input_bytes=reply)
        return reply, changed
```

   and after the transaction:

```python
    reply = transact(args.repo_root, args.run_id, control,
                     migration_contracts=migration_contracts)
    sys.stdout.buffer.write(reply)
    return 0
```

   replacing `response = transact(...)` and `print_json(response)`.

- [ ] **Step 4: Verify**

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivered_control.py 2>&1 | tail -3`
Expected: `OK`, 5 tests.

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_admission_replay.py > "${TMPDIR:-/tmp}/issue-220-task3.log" 2>&1; tail -3 "${TMPDIR:-/tmp}/issue-220-task3.log"; grep -E '^(FAIL|ERROR):' "${TMPDIR:-/tmp}/issue-220-task3.log"`
Expected: `OK` and no `FAIL:`/`ERROR:` lines. Every existing control test now also passes the
boundary inside control. If one fails with `rejected the workflow-response boundary`, its
reply was always invalid on the wire: report it as a finding rather than weakening the
validation or the test.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/tests/test_delivered_control.py \
  home/common/agent-skills/tests/test_workflow_state.py
git commit -m "fix(issue-220): validate control's reply at the workflow-response boundary before commit"
```

The message ends with the two trailer lines from the plan's Global Constraints.
