# Task 1: The read-only `check-launch` query

Discharges AC1 and AC5. Rests on spec rows D1, D2, D3, D4, D5, D15, and on the
new D16.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the first task).
- Produces, for Tasks 2–5 to reference in prose:
  - CLI verb `workflow-state check-launch --repo-root <path> --run-id <run-id> --action-id <issue:attempt:launch>` — all three flags required.
  - Exit 0 prints one canonical JSON object with exactly the four keys
    `action_id` (str, the echoed argument), `current` (bool),
    `current_action_id` (str or null), `reason` (str, closed 7-value set).
  - `render_action_id(attempt: dict[str, Any]) -> str`
  - `parse_action_id(value: str) -> tuple[int, int, int]`
  - `command_check_launch(args: argparse.Namespace) -> int`
  - `ACTION_ID_PATTERN: re.Pattern[str]`

**Invariants:**
- The verb creates nothing: after querying a repository root with no
  `.superpowers/` directory, that directory still does not exist — no run
  directory, no `workflows/.gitignore`, no `state.lock`.
- The verb mutates nothing: `state.json` is byte-identical before and after every
  query, and repeating a query returns byte-identical stdout.
- `current == (current_action_id is not None and action_id == current_action_id)`
  holds for every answer.
- `current_action_id` is non-null exactly when the issue's latest attempt has
  state `active`.
- Every answer is exit 0; every error is exit 2 with empty stdout, a
  `workflow-state: <message>` stderr line, and no traceback.

---

- [ ] **Step 1: Write the failing tests**

Add these four helpers to `WorkflowStateLifecycleTest`, immediately after the
existing `suspend(...)` helper (around line 511), mirroring its flag-verb shape:

```python
    def check_launch_raw(self, *, action_id, repo_root=None, run_id=None, ok=True):
        return self.run_cli(
            "check-launch",
            "--repo-root", self.root if repo_root is None else repo_root,
            "--run-id", self.run_id if run_id is None else run_id,
            "--action-id", action_id,
            ok=ok,
        )

    def check_launch(self, **kwargs):
        """Query one launch identity and pin the redundancy invariant on the way."""
        completed = self.check_launch_raw(**kwargs)
        answer = json.loads(completed.stdout)
        self.assertEqual(
            set(answer), {"action_id", "current", "current_action_id", "reason"}
        )
        self.assertEqual(answer["action_id"], kwargs["action_id"])
        # The boolean is deliberately redundant with the two identity fields
        # (per D1); if they ever disagree the discriminator is lying.
        self.assertEqual(
            answer["current"],
            answer["current_action_id"] is not None
            and answer["action_id"] == answer["current_action_id"],
        )
        return answer
```

Add these four tests at the **end of `WorkflowStateLifecycleTest`** — after
`test_human_directed_control_resumes_a_gated_suspension` and before
`class ArtifactBudgetPolicyResolutionTest` (around line 5096):

```python
    def test_check_launch_supersedes_a_predecessor_attempt_after_a_failed_owner(self):
        # The successor attempt is opened by an owner-reported failure, never by
        # expiry: issue #133 changes expiry accounting and touches this same
        # helper, and an expiry-driven fixture would be invalidated by it. Do
        # not "simplify" this back to `expire`/`legacy_expiry_record`.
        self.init_run()
        worktree = str(Path(self.root) / "wt-14")
        spawned = self.spawn(issue=14, worktree=worktree)
        self.assertEqual(spawned["id"], "14:1:1")
        live = self.state_path.read_bytes()
        self.assertEqual(self.check_launch(action_id="14:1:1"), {
            "action_id": "14:1:1", "current": True,
            "current_action_id": "14:1:1", "reason": "current",
        })
        self.assertEqual(self.state_path.read_bytes(), live)

        self.fail_owner(issue=14, attempt=1, now="2026-08-13T20:05:00Z")
        self.assertEqual(self.check_launch(action_id="14:1:1"), {
            "action_id": "14:1:1", "current": False,
            "current_action_id": None, "reason": "inactive_attempt",
        })

        # The retry reuses the predecessor's worktree, which is the shared-checkout
        # reality this guard exists for.
        retried = self.retry(issue=14, worktree=worktree, now="2026-08-13T20:10:00Z")
        self.assertEqual(retried["id"], "14:2:1")
        after = self.state_path.read_bytes()
        self.assertEqual(self.check_launch(action_id="14:1:1"), {
            "action_id": "14:1:1", "current": False,
            "current_action_id": "14:2:1", "reason": "superseded_attempt",
        })
        self.assertEqual(self.check_launch(action_id="14:2:1"), {
            "action_id": "14:2:1", "current": True,
            "current_action_id": "14:2:1", "reason": "current",
        })
        self.assertEqual(self.state_path.read_bytes(), after)

    def test_check_launch_supersedes_a_predecessor_launch_after_a_resume(self):
        self.init_run()
        worktree = str(Path(self.root) / "wt-14")
        self.assertEqual(self.spawn(issue=14, worktree=worktree)["id"], "14:1:1")
        self.suspend(
            issue=14, attempt=1, blocked_on="transport", now="2026-08-13T20:05:00Z",
        )
        self.assertEqual(self.check_launch(action_id="14:1:1"), {
            "action_id": "14:1:1", "current": False,
            "current_action_id": None, "reason": "inactive_attempt",
        })

        resumed = self.resume(issue=14, worktree=worktree, now="2026-08-13T20:06:00Z")
        self.assertEqual(resumed["id"], "14:1:2")
        after = self.state_path.read_bytes()
        self.assertEqual(self.check_launch(action_id="14:1:1"), {
            "action_id": "14:1:1", "current": False,
            "current_action_id": "14:1:2", "reason": "superseded_launch",
        })
        self.assertEqual(self.check_launch(action_id="14:1:2"), {
            "action_id": "14:1:2", "current": True,
            "current_action_id": "14:1:2", "reason": "current",
        })
        self.assertEqual(self.state_path.read_bytes(), after)

    def test_check_launch_creates_nothing_for_a_run_that_does_not_exist(self):
        # `transact`/`workflow_paths` would create `.superpowers/`, the run dir,
        # the workflows `.gitignore` and `state.lock` (per D4). The whole-tree
        # assertion is what proves this verb uses neither.
        first = self.check_launch_raw(action_id="14:1:1")
        self.assertEqual(json.loads(first.stdout), {
            "action_id": "14:1:1", "current": False,
            "current_action_id": None, "reason": "unknown_run",
        })
        self.assertFalse((self.root / ".superpowers").exists())
        self.assertFalse(self.workflows_dir.exists())
        second = self.check_launch_raw(action_id="14:1:1")
        self.assertEqual(second.stdout, first.stdout)
        self.assertFalse((self.root / ".superpowers").exists())

    def test_check_launch_separates_well_formed_negatives_from_errors(self):
        self.init_run()
        self.spawn(issue=14, worktree=str(Path(self.root) / "wt-14"))
        before = self.state_path.read_bytes()
        # Assert the WHOLE answer, not just `reason`. The helper's redundancy
        # invariant only cross-checks `current` against `current_action_id`, so
        # an implementation that echoed the queried id back as
        # `current_action_id` and answered `current: true` would satisfy it and
        # still let a superseded launch merge — exactly the bug under test.
        live = "14:1:1"
        answers = (
            ("absent run", {"action_id": live, "run_id": "issue-99-absent"},
             {"action_id": live, "current": False,
              "current_action_id": None, "reason": "unknown_run"}),
            ("issue not in the ledger", {"action_id": "99:1:1"},
             {"action_id": "99:1:1", "current": False,
              "current_action_id": None, "reason": "unknown_issue"}),
            ("attempt beyond the count", {"action_id": "14:9:1"},
             {"action_id": "14:9:1", "current": False,
              "current_action_id": live, "reason": "unknown_attempt"}),
            ("launch beyond the latest", {"action_id": "14:1:9"},
             {"action_id": "14:1:9", "current": False,
              "current_action_id": live, "reason": "superseded_launch"}),
        )
        for label, kwargs, expected in answers:
            with self.subTest(row=label):
                completed = self.check_launch_raw(**kwargs)
                self.assertEqual(json.loads(completed.stdout), expected)
                # Canonical stdout: sorted keys, compact separators, one
                # trailing newline, exactly as `print_json` emits it.
                self.assertEqual(
                    completed.stdout,
                    json.dumps(expected, sort_keys=True,
                               separators=(",", ":")) + "\n",
                )
                # Re-run through the helper so the redundancy invariant is
                # checked on this row too.
                self.check_launch(**kwargs)
                self.assertEqual(self.state_path.read_bytes(), before)
        errors = (
            ("repository root does not exist",
             {"action_id": "14:1:1", "repo_root": str(self.root / "absent")}),
            ("run id outside the grammar",
             {"action_id": "14:1:1", "run_id": "bad/run"}),
            ("action id with two components", {"action_id": "14:1"}),
            ("action id with a zero ordinal", {"action_id": "14:0:1"}),
        )
        for label, kwargs in errors:
            with self.subTest(row=label):
                completed = self.check_launch_raw(ok=False, **kwargs)
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
                self.assertNotIn("Traceback", completed.stderr)
                self.assertEqual(self.state_path.read_bytes(), before)

        # A ledger that cannot be read is a fault, not a refusal (per D3). Both
        # rows destroy the fixture, so they run last.
        self.state_path.write_text("{not json", encoding="utf-8")
        corrupt = self.check_launch_raw(action_id="14:1:1", ok=False)
        self.assertEqual((corrupt.returncode, corrupt.stdout), (2, ""))
        self.assertNotIn("Traceback", corrupt.stderr)

        self.state_path.unlink()
        self.state_path.symlink_to(self.root / "elsewhere.json")
        linked = self.check_launch_raw(action_id="14:1:1", ok=False)
        self.assertEqual((linked.returncode, linked.stdout), (2, ""))
        self.assertNotIn("Traceback", linked.stderr)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (the file has its own `unittest.main()`; the package path contains hyphens,
so run it as a script, not with `-m unittest <dotted>`):
```sh
python3 home/common/agent-skills/tests/test_workflow_state.py -v -k check_launch
```
Expected: 4 failures — `workflow-state.py` exits 2 with argparse's
`invalid choice: 'check-launch'`, so `run_cli` fails each test.

- [ ] **Step 3: Extract the action-id render/parse pair**

In `home/common/agent-skills/scripts/workflow-state.py`:

1. Beside `RUN_ID_PATTERN` (around line 47) add:

```python
ACTION_ID_PATTERN = re.compile(r"^([1-9][0-9]*):([1-9][0-9]*):([1-9][0-9]*)$")
```

2. Immediately **before** `bootstrap_response` (around line 1518) add the pair:

```python
def render_action_id(attempt: dict[str, Any]) -> str:
    """Render an attempt's current launch identity as ``issue:attempt:launch``."""
    return f"{attempt['issue']}:{attempt['attempt']}:{len(attempt['launches'])}"


def parse_action_id(value: str) -> tuple[int, int, int]:
    """Split an ``issue:attempt:launch`` identity into its three ordinals.

    The grammar has one home: this module renders every action id and is the only
    thing that parses one back (per D6).
    """
    matched = ACTION_ID_PATTERN.fullmatch(value)
    if matched is None:
        raise WorkflowError("invalid action_id")
    return int(matched[1]), int(matched[2]), int(matched[3])
```

3. Route **all four** identical renderings through `render_action_id`, replacing
   the inline f-strings (per D16):
   - `bootstrap_response` — the `"action_id"` entry in the requirement dict.
   - `direct_owner_response` — the `"action_id"` value.
   - `command_control`'s dispatch-action append (around line 2237) — the `"id"`
     value on the `spawn`/`resume`/`retry` action only. Leave the `"finalize"`
     and `"wait:<deadline>"` action ids alone: those are not launch identities.
   - `command_check_launch` — see Step 4.

- [ ] **Step 4: Implement `check-launch`**

Add `command_check_launch` immediately after `command_finish` and before
`print_json` (around line 2847):

```python
def command_check_launch(args: argparse.Namespace) -> int:
    """Answer whether one launch identity is an issue's current launch.

    Read-only by construction: no clock, no lock, and neither ``transact`` nor
    ``workflow_paths`` — between them those create ``.superpowers/``, the run
    directory, the workflows ``.gitignore`` and ``state.lock``, and ``transact``
    persists whenever a mutation reports ``changed`` (per D4).

    A positive answer requires evidence. Every absence the ledger can express is
    a well-formed negative at exit 0; only an unreadable ledger or an argument
    that is not a well-formed question is an error (per D3).
    """
```

Body, in this exact order — the precedence is what makes the classification
deterministic (per D5), and the answer/error split is D3's:

1. `repo_root = resolve_repo_root(args.repo_root)` — stats and resolves only,
   never creates; a missing, symlinked or non-directory root raises.
2. `if not RUN_ID_PATTERN.fullmatch(args.run_id): raise WorkflowError("invalid run_id")`
   — checked directly, **not** via `workflow_paths`, which creates directories.
3. `issue, attempt_ordinal, launch_ordinal = parse_action_id(args.action_id)`.
4. `state_path = repo_root / ".superpowers" / "workflows" / args.run_id / "state.json"`.
5. `if not require_regular_path(state_path, "workflow state", allow_missing=True):`
   → answer `reason="unknown_run"`, `current_action_id=None`, exit 0. A present
   symlink or non-regular file raises from inside that call.
6. `state = read_locked_state(state_path, args.run_id)` — despite its name it
   takes no lock: it opens `O_RDONLY|O_NOFOLLOW`, decodes, and returns
   `validate_state(upgrade_state(value))`, giving this query byte-identical
   validation and prior-schema upgrade semantics to every writer.
   `upgrade_state` fills prior-schema fields **in memory only**. Carry exactly
   one comment above this line, saying why there is no lock:

```python
    # No lock: `atomic_write_state` publishes by `os.replace`, so an unlocked
    # reader sees either the whole prior file or the whole new one, never a torn
    # one — and taking the lock would mean creating `state.lock`, which is a write.
```

7. Classify, in this precedence, computing `current_action_id` first:

```python
    issue_state = state["issues"].get(str(issue))
    if issue_state is None or not issue_state["attempts"]:
        current_action_id, reason = None, "unknown_issue"
    else:
        attempts = issue_state["attempts"]
        latest = attempts[-1]
        # Only an `active` latest attempt has a live launch; every other member
        # of ATTEMPT_STATES (handed_off, suspended, stopped, failed, merged)
        # entitles nobody, and `validate_state` has already closed that set, so
        # there is no default fall-through here (per D5).
        current_action_id = (
            render_action_id(latest) if latest["state"] == "active" else None
        )
        if attempt_ordinal > len(attempts):
            reason = "unknown_attempt"
        elif attempt_ordinal < len(attempts):
            reason = "superseded_attempt"
        elif current_action_id is None:
            reason = "inactive_attempt"
        elif launch_ordinal != len(latest["launches"]):
            reason = "superseded_launch"
        else:
            reason = "current"
```

8. Print through the existing `print_json` (sorted keys, `(",", ":")`
   separators, trailing newline) and return 0:

```python
    print_json({
        "action_id": args.action_id,
        "current": reason == "current",
        "current_action_id": current_action_id,
        "reason": reason,
    })
    return 0
```

Nothing is added to `main()`'s error path: it already prints
`workflow-state: <message>` to stderr and returns 2 for every `WorkflowError`
and `OSError`, and argparse failures exit 2 on their own.

- [ ] **Step 5: Register the subparser**

In `build_parser()`, after the `progress` subparser block and before
`return parser`:

```python
    check_launch = subparsers.add_parser("check-launch")
    check_launch.add_argument("--repo-root", required=True)
    check_launch.add_argument("--run-id", required=True)
    check_launch.add_argument("--action-id", required=True)
    check_launch.set_defaults(handler=command_check_launch)
```

Do **not** use `add_run_arguments`: it adds `--now`, and this verb takes no
clock (per D4).

- [ ] **Step 6: Verify**

Run:
```sh
python3 home/common/agent-skills/tests/test_workflow_state.py -v
```
Expected: OK, zero failures and zero errors, over the whole file — the four new
tests pass and every pre-existing lifecycle test (including the `action_id`
assertions at lines ~639, ~1709, ~3380, ~3528) still passes, proving the four
renderings did not drift.

Then confirm the grammar has exactly one home:
```sh
S=home/common/agent-skills/scripts/workflow-state.py
count=$(grep -c ":{len(attempt\['launches'\])}" "$S")
if [ "$count" -ne 1 ]; then
  echo "expected exactly one inline action-id rendering (render_action_id), found $count"; exit 1
fi
if grep -q 'launch = len(attempt\["launches"\])' "$S"; then
  echo "bootstrap_response still renders the action id itself"; exit 1
fi
```
Expected: no output, exit 0. At the commit this task starts from the first check
counts **2** and the second matches, so both gates fail before the change —
that is what makes them falsifiable.

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py \
        home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(issue-132): add the read-only check-launch query"
```
Include the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
Never disable commit signing.
