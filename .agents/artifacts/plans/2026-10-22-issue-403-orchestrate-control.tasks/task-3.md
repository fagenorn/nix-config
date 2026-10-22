# Task 3: Dispatch projection and resume packs

**Files:**
- Modify: `python/agent_tools/orchestrate_control.py`
- Modify: `tests/orchestrate_world.py`
- Test: `tests/test_orchestrate_control.py`

**Interfaces:**
- Consumes (Tasks 1–2): `Refusal`, `run_child`, `validate_bytes`, `CLOSED_KINDS`, `DISPATCH_KINDS`, `project(response, repo_root, run_id)` (its signature is kept); world `start`, `step`, `seed_spawn`, `add_worktree`, `candidate`, `fault`, `calls`, `ws`, `root`; suite `assert_refused`, `steps_before`.
- Produces (module): `owner_object(action: dict, repo_root: str, run_id: str) -> dict`; `resume_pack(repo_root: str, run_id: str, action_id: str) -> str | None`; `project` now returns one dispatch entry per `spawn`, `resume`, `retry` and `delivery_remainder` action, in returned order.
- Produces (world): `validate(self, value: dict) -> subprocess.CompletedProcess` — the source `artifact-budget validate-report --boundary workflow-response --input -` run directly (unlogged, bytes) on `json.dumps(value)`.

**Invariants:**
- A dispatch entry is exactly `{action_id, launch_kind, issue, attempt, owner, worktree, handoff_path, owner_object, resume_pack}` (D17).
- `owner_object` is the validator's stdout for the projected object, decoded, less its trailing newline; nothing unvalidated reaches it.
- An owner object is the action with `id`→`action_id`, `kind`→`launch_kind`, plus `kind: "owner"`, `interface_version: 2`, `ledger_repo_root` (`--repo-root` exactly as given, D29) and `run_id`, every other member kept; a remainder object is the action verbatim.
- `resume_pack` is the `resume-pack` stdout text, never decoded as JSON, only for `resume`; any failure leaves it null and never refuses.
- Any other projection or validation failure refuses at `project` with the response attached and prints no partial `dispatches` (D23).

- [ ] **Step 1: Add the world's direct validator**

`validate(self, value)`: `subprocess.run([sys.executable, str(BUDGET), "validate-report", "--boundary", "workflow-response", "--input", "-"], input=json.dumps(value).encode(), capture_output=True, env=self.env, timeout=120)`.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_orchestrate_control.py`:

```python
ENVELOPE = ("action_id", "launch_kind", "issue", "attempt", "owner", "worktree", "handoff_path")


def projected(action, root, run_id):
    value = {k: v for k, v in action.items() if k not in ("id", "kind")}
    value.update(action_id=action["id"], launch_kind=action["kind"], kind="owner",
                 interface_version=2, ledger_repo_root=str(root), run_id=run_id)
    return value


class ProjectTest(unittest.TestCase):
    def resumed(self, world):
        """Seed issue 12's spawn, give it a live worktree, then report its owner unavailable."""
        session = world.start("12")["session"]
        spawn = world.seed_spawn(session, [12])[12]
        world.add_worktree(world.candidate(12), "worktree-issue-12-orchestrated")
        owner = {"event_id": "12-unavailable", "issue": 12, "custody": spawn["custody"],
                 "state": "unavailable"}
        return session, world.step(session, owners=[owner])

    def test_a_resume_carries_its_owner_object_and_resume_pack(self):
        world = OrchestrateWorld(self)
        session, (done, out) = self.resumed(world)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (action,) = [a for a in out["response"]["actions"] if a["kind"] != "wait"]
        self.assertEqual(action["kind"], "resume")
        (dispatch,) = out["dispatches"]
        self.assertEqual(set(dispatch), {*ENVELOPE, "owner_object", "resume_pack"})
        self.assertEqual({k: dispatch[k] for k in ENVELOPE}, {
            "action_id": action["id"], "launch_kind": "resume", "issue": 12,
            "attempt": action["attempt"], "owner": action["owner"],
            "worktree": action["worktree"], "handoff_path": action["handoff_path"]})
        expected = projected(action, world.root, session["run_id"])
        self.assertEqual(json.loads(dispatch["owner_object"]), expected)
        checked = world.validate(expected)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(dispatch["owner_object"], checked.stdout.decode().removesuffix("\n"))
        (call,) = world.calls("workflow-state", "resume-pack")
        self.assertEqual(call["argv"], ["resume-pack", "--repo-root", str(world.root),
                                        "--run-id", session["run_id"], "--action-id", action["id"]])
        pack = world.ws(*call["argv"])
        self.assertEqual(pack.returncode, 0, pack.stderr)
        self.assertEqual(dispatch["resume_pack"], pack.stdout.decode())

    def test_a_failing_resume_pack_leaves_it_null(self):
        world = OrchestrateWorld(self)
        world.fault("workflow-state", "resume-pack", exit=2,
                    stderr="workflow-state: resume-pack refused: fixture\n")
        _, (done, out) = self.resumed(world)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (dispatch,) = out["dispatches"]
        self.assertEqual((dispatch["launch_kind"], dispatch["resume_pack"]), ("resume", None))

    def test_a_remainder_dispatch_is_its_action_verbatim(self):
        world = OrchestrateWorld(self)
        session = world.start("12")["session"]
        remainder = {"interface_version": 2, "kind": "delivery_remainder",
                     "ledger_repo_root": str(world.root), "run_id": session["run_id"],
                     "issue": 12, "source_attempt": 1, "owner": "12:r1",
                     "custody": {"kind": "remainder", "remainder": 1, "launch": 1,
                                 "action_id": "12:r1:1"},
                     "worktree": world.candidate(12), "contract": None, "contract_digest": None,
                     "pending_stage_ids": [], "deadline_at": "2026-10-22T01:00:00Z",
                     "requirements": [], "authority_evaluation": None, "requested_scope": None}
        canned = {"interface_version": 3, "run_id": session["run_id"],
                  "now": "2026-10-22T00:00:00Z", "summaries": [], "deltas": [],
                  "actions": [remainder], "next_deadline": None, "admission": None}
        world.fault("workflow-state", "control", stdout=json.dumps(canned) + "\n")
        world.fault("artifact-budget", "validate-report", passthrough=True)
        done, out = world.step(session)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(out["dispatches"], [{
            "action_id": "12:r1:1", "launch_kind": "delivery_remainder", "issue": 12,
            "attempt": 1, "owner": "12:r1", "worktree": world.candidate(12),
            "handoff_path": None, "resume_pack": None,
            "owner_object": json.dumps(remainder, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":"))}])
        self.assertEqual(world.calls("workflow-state", "resume-pack"), [])

    def test_an_owner_object_the_boundary_refuses_refuses_at_project(self):
        world = OrchestrateWorld(self)
        world.fault("artifact-budget", "validate-report", stdin_kind="owner", exit=2,
                    stderr="artifact-budget: invalid report\n")
        _, (done, _) = self.resumed(world)
        out = assert_refused(self, done, "step", "project", steps_before("project"))
        self.assertIn("validate-report", out["detail"])
        self.assertIn("resume", [a["kind"] for a in out["response"]["actions"]])
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py -k ProjectTest` (timeout 900 s)
Expected: 4 failures — each step refuses at `project` with `resume actions are not projected` (or `delivery_remainder actions are not projected`), so the exit-0 assertions and the `validate-report` detail assertion fail.

- [ ] **Step 4: Project dispatches**

Replace `project`'s refusal of dispatch kinds; keep the closed-set check first, so an unknown kind still refuses before anything is projected (D23).

- `owner_object(action, repo_root, run_id)`: `{k: v for k, v in action.items() if k not in ("id", "kind")}` updated with `action_id=action["id"]`, `launch_kind=action["kind"]`, `kind="owner"`, `interface_version=2`, `ledger_repo_root=repo_root`, `run_id=run_id`.
- For each action in returned order:
  - `spawn`/`resume`/`retry`: object `owner_object(...)`; envelope `action_id = action["id"]`, `launch_kind = action["kind"]`, `issue`, `attempt`, `owner`, `worktree`, `handoff_path` from the action.
  - `delivery_remainder`: object the action itself; envelope `action_id = action["custody"]["action_id"]`, `launch_kind = "delivery_remainder"`, `issue`, `attempt = action["source_attempt"]`, `owner`, `worktree` from the action, `handoff_path = None` (D17).
  - `owner_object` text: `validate_bytes("project", json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()).decode("utf-8").removesuffix("\n")`.
  - `resume_pack`: `resume_pack(repo_root, run_id, action["id"])` for `resume`, else None.
  - Other kinds add nothing.
- `resume_pack(repo_root, run_id, action_id)`: `run_child("project", ["workflow-state", "resume-pack", "--repo-root", repo_root, "--run-id", run_id, "--action-id", action_id])`; a `Refusal` (the child cannot start), a non-zero exit or stdout that is not UTF-8 returns None; otherwise the stdout decoded as UTF-8, unchanged (newline kept).
- Every `Refusal` raised inside `project` (validation) is re-raised as `Refusal("project", <detail>, response=response)`; a `KeyError`, `TypeError` or `UnicodeDecodeError` while projecting refuses the same way with `detail` naming the action's `id` or kind. The list is returned only when every action projected.
- Update the module docstring's `project` description to match.

- [ ] **Step 5: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py` (timeout 900 s)
Expected: OK, 30 tests. A projection that drops, renames or adds a member beyond the six the invariant names fails the `projected` comparison in `test_a_resume_carries_its_owner_object_and_resume_pack`; a refusal on a failed pack fails `test_a_failing_resume_pack_leaves_it_null`; projecting a remainder through `owner_object` fails `test_a_remainder_dispatch_is_its_action_verbatim`.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/orchestrate_control.py tests/orchestrate_world.py tests/test_orchestrate_control.py
git commit -m "feat(agent-tools): orchestrate-control projects owner dispatches (#403)"
```
