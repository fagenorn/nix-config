# Task 4: Delivery contracts, chaining, the refusal table and the `step` contract

**Files:**
- Modify: `python/agent_tools/orchestrate_control.py`
- Modify: `tests/orchestrate_world.py`
- Test: `tests/test_orchestrate_control.py`
- Modify: `python/README.md` (the `orchestrate-control` section)

**Interfaces:**
- Consumes (Tasks 1–3): `Refusal`, `run_child`, `why`, `strict_json`, `read_step_input`, `worktree_facts`, `control_request(..., pairs)`, `run_control(..., previous=)`, `asks_for_contract`, `project`, `step`; world `start`, `step`, `seed_spawn`, `candidate`, `fault`, `clear_faults`, `listing`, `calls`, `requests`, `ws`, `git`, `validate`, `root`, `cwd`; suite `STEP_ORDER`, `steps_before`, `assert_refused`, `keyed`, `projected`.
- Produces (module): `build_pair(step: str, repo_root: str, issue: int, worktree: str, session: dict) -> tuple[dict | None, str | None]` — `(pair, None)` or `(None, <builder stderr line>)`.
- Produces (world): `snapshot(self, path) -> list[tuple[str, str, int | None]]`.

**Invariants:**
- `step` runs `bindings`, `bootstrap`, `tracker`, `forge`, `worktrees`, `contracts`, `control`, `project`.
- Builds before the first call: on `first_sweep`, every in-session requirement with a null `contract_digest`; and every `contracts_due` issue; each at most once per call; never an issue in `refused_contracts` (D4, D13). The worktree is the recorded path, else the candidate.
- Chaining (D6, D18): only when the first reply's only action is `delivery_contract`; at most one further call, made only when a listed issue has a pair; that call repeats the facts, sends `owners: []` and a pair for each issue whose first-reply summary asks for one and has one. A reply with any dispatch is never followed by a second call.
- A builder exit 2 with empty stdout is a refusal (`contract_refusals`, `refused_contracts`); any other builder failure refuses at `contracts` before the first call and at `control` in the chained phase, with the first reply attached (D28).
- The command creates no file under `--repo-root` (outside `workflow-state`'s `.superpowers/` ledger store) or the working directory (D3, D22).

- [ ] **Step 1: Update the suite's step order and add the world's snapshot**

In the suite: `STEP_ORDER = ["bindings", "bootstrap", "tracker", "forge", "worktrees", "contracts", "control", "project"]` (Task 2's refusal assertions follow through `steps_before`).

`snapshot(self, path)`: sorted `(relative path, "d" | "f" | "l", st_mtime_ns for a regular file else None)` for every entry under `path` (via `os.walk`, links not followed), skipping the top-level `.superpowers` directory and everything under it.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_orchestrate_control.py`:

```python
REFUSED_LINE = "workflow-state: build-delivery refused: fixture"


def builds(world):
    return [json.loads(c["stdin"]) for c in world.calls("workflow-state", "build-delivery")]


def contract_input(world, issue, session, path=None):
    return {"issue": issue, "worktree": path or world.candidate(issue),
            "source_kind": session["source"]["kind"],
            "source_reference": session["source"]["reference"]}


def asking(response):
    return sorted(s["issue"] for s in response["summaries"]
                  if any(r.get("reason_code") == "delivery_contract_required"
                         for r in s["requirements"]))


class ContractTest(unittest.TestCase):
    def test_first_sweep_builds_for_null_digest_requirements_from_the_recorded_worktree(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        world.seed_spawn(session, [12])
        boot = json.loads(world.ws("init-run", "--repo-root", world.root,
                                   "--run-id", session["run_id"]).stdout)
        (requirement,) = boot["requirements"]
        requirement["contract_digest"] = None
        world.fault("workflow-state", "init-run", stdout=json.dumps(boot) + "\n")
        world.fault("workflow-state", "control", exit=2, stderr="workflow-state: fixture stop\n")
        assert_refused(self, world.step(session, first_sweep=True)[0], "step", "control",
                       steps_before("control"))
        self.assertEqual(builds(world), [contract_input(world, 12, session)])
        self.assertEqual(world.calls("workflow-state", "build-delivery")[0]["argv"],
                         ["build-delivery", "--repo-root", str(world.root), "--kind", "contract",
                          "--input", "-"])
        assert_refused(self, world.step(session)[0], "step", "control", steps_before("control"))
        self.assertEqual(len(builds(world)), 1)

    def test_contracts_due_are_built_and_refused_ones_never(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14", "16")["session"]
        done, out = world.step(session, contracts_due=[12], refused_contracts=[14])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(builds(world), [contract_input(world, 12, session)])
        self.assertEqual(out["control_calls"], 1)
        self.assertIn(14, asking(out["response"]))
        self.assertEqual(out["contracts_due"], [i for i in asking(out["response"]) if i != 14])
        self.assertEqual((out["refused_contracts"], out["contract_refusals"]), ([14], []))

    def test_a_builder_refusal_is_reported_and_joins_refused_contracts(self):
        world = OrchestrateWorld(self)
        world.fault("workflow-state", "build-delivery", issue=14, exit=2,
                    stderr=REFUSED_LINE + "\n")
        session = world.start("12", "14")["session"]
        done, out = world.step(session, first_sweep=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(out["control_calls"], 2)
        first, second = world.requests()
        self.assertEqual(first["delivery_contracts"], keyed([12, 14], None))
        self.assertIsNotNone(second["delivery_contracts"]["12"])
        self.assertIsNone(second["delivery_contracts"]["14"])
        self.assertEqual((len(second["authorization_intents"]["12"]),
                          second["authorization_intents"]["14"]), (1, []))
        self.assertEqual(second["owners"], [])
        for fact in ("tracker", "forge", "worktrees", "issues", "max_parallel"):
            self.assertEqual(second[fact], first[fact])
        self.assertEqual(out["contract_refusals"], [{"issue": 14, "detail": REFUSED_LINE}])

    def test_owners_ride_the_first_call_once_and_never_the_chained_one(self):
        # S1 (D30): the owner observations the adapter passes must be non-empty here,
        # or re-sending them on the chained call would go unnoticed.
        ...
        self.assertEqual(out["refused_contracts"], [14])
        self.assertNotIn(14, out["contracts_due"])
        self.assertEqual([d["issue"] for d in out["dispatches"]], [12])
        self.assertFalse(out["ends_run"])

    def test_a_builder_failure_before_control_refuses_at_contracts(self):
        cases = {"crash": {"exit": 1, "stderr": "boom\n"},
                 "exit 2 with output": {"exit": 2, "stdout": "{}", "stderr": "x\n"},
                 "no pair": {"exit": 0, "stdout": '{"contract": {}}'}}
        for name, rule in cases.items():
            with self.subTest(name):
                world = OrchestrateWorld(self)
                world.fault("workflow-state", "build-delivery", issue=12, **rule)
                session = world.start("12")["session"]
                out = assert_refused(self, world.step(session, contracts_due=[12])[0], "step",
                                     "contracts", steps_before("contracts"))
                self.assertIsNone(out["response"])
                self.assertEqual(world.requests(), [])


class ChainTest(unittest.TestCase):
    def test_a_fresh_set_chains_one_contract_round_into_spawns(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        done, out = world.step(session, first_sweep=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(out["control_calls"], 2)
        first, second = world.requests()
        self.assertEqual(first["delivery_contracts"], keyed([12, 14], None))
        self.assertTrue(all(second["delivery_contracts"][k] is not None for k in ("12", "14")))
        self.assertEqual(builds(world), [contract_input(world, 12, session),
                                         contract_input(world, 14, session)])
        actions = {a["id"]: a for a in out["response"]["actions"]}
        self.assertEqual([(d["action_id"], d["launch_kind"], d["issue"], d["worktree"])
                          for d in out["dispatches"]],
                         [("12:1:1", "spawn", 12, world.candidate(12)),
                          ("14:1:1", "spawn", 14, world.candidate(14))])
        for dispatch in out["dispatches"]:
            expected = projected(actions[dispatch["action_id"]], world.root, session["run_id"])
            self.assertEqual(json.loads(dispatch["owner_object"]), expected)
            self.assertEqual(dispatch["owner_object"],
                             world.validate(expected).stdout.decode().removesuffix("\n"))
            self.assertIsNone(dispatch["resume_pack"])
        self.assertEqual((out["contracts_due"], out["refused_contracts"],
                          out["contract_refusals"], out["ends_run"]), ([], [], [], False))

    def test_a_reply_with_a_dispatch_is_never_chained(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        done, out = world.step(session, contracts_due=[12, 14])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((out["control_calls"], len(world.requests())), (1, 1))
        self.assertEqual([d["launch_kind"] for d in out["dispatches"]], ["spawn", "spawn"])

    def test_every_listed_refusal_ends_the_run(self):
        world = OrchestrateWorld(self)
        for issue in (12, 14):
            world.fault("workflow-state", "build-delivery", issue=issue, exit=2,
                        stderr=REFUSED_LINE + "\n")
        session = world.start("12", "14")["session"]
        done, out = world.step(session, first_sweep=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(out["response"]["actions"], [
            {"id": "delivery_contract", "kind": "delivery_contract", "issues": [12, 14]}])
        self.assertEqual((out["control_calls"], out["dispatches"], out["refused_contracts"],
                          out["ends_run"]), (1, [], [12, 14], True))
        self.assertEqual([r["issue"] for r in out["contract_refusals"]], [12, 14])

    def test_a_failure_in_the_chained_phase_refuses_at_control_with_the_first_reply(self):
        cases = {"second call": ("control", {"call": 2, "exit": 2,
                                             "stderr": "workflow-state: fixture stop\n"}),
                 "chained build crash": ("build-delivery", {"issue": 14, "exit": 1,
                                                            "stderr": "boom\n"})}
        for name, (sub, rule) in cases.items():
            with self.subTest(name):
                world = OrchestrateWorld(self)
                world.fault("workflow-state", sub, **rule)
                session = world.start("12", "14")["session"]
                out = assert_refused(self, world.step(session, first_sweep=True)[0], "step",
                                     "control", steps_before("control"))
                self.assertEqual(out["response"]["actions"], [
                    {"id": "delivery_contract", "kind": "delivery_contract",
                     "issues": [12, 14]}])

    def test_a_chained_reply_that_is_not_a_control_response_keeps_the_first_reply(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        boot = world.ws("init-run", "--repo-root", world.root, "--run-id", session["run_id"])
        world.fault("workflow-state", "control", call=2, stdout=boot.stdout.decode())
        out = assert_refused(self, world.step(session, first_sweep=True)[0], "step",
                             "control", steps_before("control"))
        self.assertEqual(out["response"]["actions"], [
            {"id": "delivery_contract", "kind": "delivery_contract", "issues": [12, 14]}])


class RefusalTableTest(unittest.TestCase):
    def test_every_start_step_refuses_with_its_name(self):
        world = OrchestrateWorld(self)
        world.listing("--label", "none", [])
        rows = [("bindings", lambda: None, ["start", "--repo-root", world.cwd, "12"]),
                ("route", lambda: world.fault("workflow-state", "host-route", exit=2,
                                              stderr="workflow-state: fixture\n"),
                 ["start", "--repo-root", world.root, "12"]),
                ("issues", lambda: None, ["start", "--repo-root", world.root, "--label", "none"]),
                ("bootstrap", lambda: world.fault("workflow-state", "init-run", exit=2,
                                                  stderr="workflow-state: fixture\n"),
                 ["start", "--repo-root", world.root, "12"])]
        order = ["bindings", "route", "issues", "bootstrap"]
        for step, arrange, argv in rows:
            with self.subTest(step):
                world.clear_faults()
                arrange()
                out = assert_refused(self, world.run(*argv), "start", step,
                                     order[:order.index(step)])
                self.assertIsNone(out["response"])

    def test_every_step_step_refuses_with_its_name_and_the_response_after_control(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        taken = [f"issue-12-orchestrated{s}" for s in ["", *(f"-{n}" for n in range(2, 10))]]
        rows = [
            ("bindings", lambda: None, {"repo_root": world.cwd}),
            ("bootstrap", lambda: world.fault("workflow-state", "init-run", exit=2,
                                              stderr="workflow-state: fixture\n"), {}),
            ("tracker", lambda: world.fault("gh", "api", exit=1, stderr="gh: fixture\n"), {}),
            ("forge", lambda: world.fault("gh", "api", argv_has="--paginate", exit=1,
                                          stderr="gh: fixture\n"), {}),
            ("worktrees", lambda: [world.git("branch", name) for name in taken], {}),
            ("contracts", lambda: world.fault("workflow-state", "build-delivery", issue=12,
                                              exit=1, stderr="boom\n"),
             {"contracts_due": [12]}),
            ("control", lambda: world.fault("workflow-state", "control", exit=2,
                                            stderr="workflow-state: fixture\n"), {}),
            ("project", lambda: world.fault("artifact-budget", "validate-report",
                                            stdin_kind="owner", exit=2,
                                            stderr="artifact-budget: invalid report\n"),
             {"contracts_due": [12, 14]})]
        for step, arrange, extra in rows:
            with self.subTest(step):
                world.clear_faults()
                arrange()
                out = assert_refused(self, world.step(session, **extra)[0], "step", step,
                                     steps_before(step))
                if step == "project":
                    self.assertEqual(out["response"]["run_id"], session["run_id"])
                else:
                    self.assertIsNone(out["response"])
                if step == "worktrees":
                    world.git("branch", "-D", *taken)

    def test_no_file_is_created_under_the_ledger_root_or_working_directory(self):
        world = OrchestrateWorld(self)
        before = (world.snapshot(world.root), world.snapshot(world.cwd))
        session = world.start("12", "14")["session"]
        done, out = world.step(session, first_sweep=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len(out["dispatches"]), 2)
        world.fault("workflow-state", "control", exit=2, stderr="workflow-state: fixture\n")
        assert_refused(self, world.step(session)[0], "step", "control", steps_before("control"))
        self.assertTrue((world.root / ".superpowers").is_dir())
        self.assertEqual((world.snapshot(world.root), world.snapshot(world.cwd)), before)
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py` (timeout 900 s)
Expected: the new tests fail (no `build-delivery` call is ever made, `control_calls` is always 1, `dispatches` is empty on a fresh set), and every Task 2 refusal at `control` or `project` now fails its `completed_steps` assertion until `contracts` runs.

- [ ] **Step 4: Build contracts and chain**

- `build_pair(step, repo_root, issue, worktree, session)`: `run_child(step, ["workflow-state", "build-delivery", "--repo-root", repo_root, "--kind", "contract", "--input", "-"], stdin=json.dumps({"issue": issue, "worktree": worktree, "source_kind": session["source"]["kind"], "source_reference": session["source"]["reference"]}).encode())`. Exit 0: `strict_json` must give an object whose members are exactly `contract` and `initial_intent`, both objects → `(that object, None)`; otherwise `Refusal(step, "build-delivery printed no contract pair")`. Exit 2 with empty stdout → `(None, stderr decoded as UTF-8 with replacement, less its trailing newline)` (D29). Anything else → `Refusal(step, f"build-delivery exit {code}{why(done)}")`.
- In `step`, after `worktrees`: `paths = {w["issue"]: (w["recorded"] or w["candidate"])["path"] for w in worktrees}`; `refused = set(input.refused_contracts)`, `pairs = {}`, `refusals = []`. A helper `attempt(step_name, issue)` calls `build_pair` and records a pair in `pairs`, or adds the issue to `refused` and appends `{"issue": issue, "detail": line}` to `refusals`.
  - `contracts`: the wanted set is, when `first_sweep`, every bootstrap requirement in session issues whose `contract_digest` is None, plus `contracts_due`; in session order, `attempt("contracts", issue)` for each wanted issue not in `refused` and not in `pairs`.
  - `control`: `first = run_control(root, run_id, control_request(..., input.owners, pairs))`; `reply, calls = first, 1`. When `[a["kind"] for a in first["actions"]] == ["delivery_contract"]`: for each listed issue in `paths` not in `pairs` and not in `refused`, `attempt("control", issue)`, re-raising any `Refusal` as `Refusal("control", detail, response=first)` (D28); then, when some listed issue is in `pairs`, `send = {i: pairs[i] for i in pairs if i in set(asking issues of first's summaries)}`, `reply = run_control(root, run_id, control_request(..., [], send), previous=first)` and `calls = 2`. Append `control` to `done` only after this.
  - Ready: `control_calls = calls`, `response = reply`, `contracts_due` = `asks_for_contract` issues of `reply`'s summaries not in `refused`, ascending; `refused_contracts = sorted(refused)`; `contract_refusals = refusals` in build order; `ends_run` per Task 2's rule against `reply` and the final `refused`.
- `test_owners_ride_the_first_call_once_and_never_the_chained_one` (D30) replaces the `...` body above. Pass `step` a non-empty, schema-valid `owners` list (one `{event_id, issue, custody, state: "unavailable"}` observation) while the first control reply is `delivery_contract`-only, then assert: the first logged request's `owners` equals the input list exactly, the chained request's `owners` is `[]`, and `control_calls` is 2. Preferred arrangement: a ledger state in which real `control` accepts that observation and still answers contract-only. If no such state exists, capture a contract-only reply of this same run by calling the source `control` once through `world.ws` with the identical request minus `owners` (a contract-only reply reserves no dispatch), then `fault("workflow-state", "control", call=1, stdout=<that reply>)` so the helper's first call is answered with it while its logged request still carries the owners; the chained call reaches the real `control`.
- Update the module docstring to the full `step` contract.

- [ ] **Step 5: Write the `step` contract into `python/README.md`**

Extend the `orchestrate-control` section, from the code at this commit: the `step` usage line; the stdin object and which members the adapter passes back from the previous step; the eight steps in order and what each reads (bindings resolved on every call, D5); the tracker, forge and worktree facts with their refusals (D8–D10, D19–D21, D24, D27); the contract builds, the builder-refusal outputs and `refused_contracts` (D13, D17); chaining, what the chained request carries, and that chained-phase failures refuse at `control` with the first reply (D6, D18, D28); the closed action set and the dispatch entry (D17, D23); the ready object; that a refusal carries the latest validated reply once `control` has returned; that the only writes are `workflow-state`'s own ledger writes and that a dispatch reserved before a refusal is left to the ledger's deadline expiry (D22); that one adapter process calls `step` serially per run (D25); and that teaching `orchestrate-issues` to call the command is a follow-up (D11).

- [ ] **Step 6: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py` (timeout 900 s)
Expected: OK, 44 tests, no failures, errors or skips. Re-sending `owners` on the chained call fails `test_owners_ride_the_first_call_once_and_never_the_chained_one`; a reply of another type on the chained call fails `test_a_chained_reply_that_is_not_a_control_response_keeps_the_first_reply`; chaining after a dispatch fails `test_a_reply_with_a_dispatch_is_never_chained`; a helper that writes a request or contract file under the root or the working directory fails `test_no_file_is_created_under_the_ledger_root_or_working_directory`.

- [ ] **Step 7: Commit**

```bash
git add python/agent_tools/orchestrate_control.py tests/orchestrate_world.py tests/test_orchestrate_control.py python/README.md
git commit -m "feat(agent-tools): orchestrate-control contracts and chaining (#403)"
```
