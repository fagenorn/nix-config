# Task 2: `orchestrate-control step` gathers the awaited observations

**Files:**
- Modify: `python/agent_tools/orchestrate_control.py` (module docstring, imports, `control_request`, `control_rounds`, `step`)
- Modify: `tests/orchestrate_world.py` (module docstring, `GIT_SHIM`, `add_origin`, `publish`, `entry`, `failure`, `park`)
- Modify: `tests/test_orchestrate_control.py` (import, `READY`, `observed`, new `GatherTest`)
- Modify: `python/README.md` (`## orchestrate-control`)
- Modify: `home/common/claude-code/default.nix` (the permissions allow-list comment only)
- Modify: `home/common/agent-skills/README.md` (`### Verification blockers`, the last sentence pair of its second paragraph)

**Interfaces:**
- Consumes: Task 1's `agent_tools.verification_observe.observe_all(repo_root, requirements) -> (observations, refused)` and `agent_tools.verification_blocker.BlockerRefused`; the interface-3 bootstrap's `verification` list (issue 545 D6).
- Produces: `control_request(b, session, tracker, forge, worktrees, owners, pairs, *, human_directed: bool, verification: list) -> dict`; `control_rounds(args, bindings, request, facts, contracts, observations: list[dict]) -> tuple[dict, int]`; the ready object's new member `verification_refusals: [{"blocker_id": str, "detail": str}]`. The step input, the refused object, the control request's other members and interface 4 are unchanged (D3, D15).

**Invariants:**
- `bootstrap` checks `init-run`'s reply is the session's run, then calls `observe_all(args.repo_root, boot.get("verification"))` once, then appends `bootstrap` to `completed_steps`; the step count and names are unchanged (D3).
- A `BlockerRefused` from it (a non-list member, or an element the adapter's validator refuses) refuses at `bootstrap` with `str(refusal)` as `detail`; nothing is fetched (D3).
- The first `control` request's `verification` is the observations in bootstrap order; the chained second sends `[]`, as it sends `owners` `[]` (D3).
- `verification_refusals` holds one `{blocker_id, detail}` per refused requirement, in bootstrap order, `detail` being `" ".join(reason.split())[:DETAIL_LIMIT]`; `[]` when none. A refused requirement never refuses the step, is left out of the request, and its attempt stays parked (D3, D12).
- With no requirement listed nothing is fetched, so every existing test keeps passing without an `origin` (D11).
- Tests assert exit codes, stdout objects, the logged `control` requests, the logged `git fetch` argv and refs; never internal call counts (D11).

- [ ] **Step 1: Write the failing tests**

`tests/orchestrate_world.py`. Append to the module docstring, after `fails loudly. Nothing contacts a network remote.`:

```text

`add_origin()`, which only the gathering tests call, gives the project a local bare `origin`
cloned from it, a `publisher` clone that advances it, and a fourth shim, `git`, that logs each
`git fetch` call's argv as tool `git` and runs the real Git (issue 546 D11).
```

Before `GH_TAIL = `, add:

```python
GIT_SHIM = '''#!{python}
import json, os, sys
argv = sys.argv[1:]
words = argv
while words[:1] == ["-C"]:
    words = words[2:]
if words[:1] == ["fetch"]:
    with open({log!r}, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({{"tool": "git", "argv": argv, "stdin": "", "call": 0,
                                  "token_visible": False}}) + "\\n")
os.execv({git!r}, [{git!r}, *argv])
'''
```

Before `def requests(self)`, add these methods to `OrchestrateWorld`:

```python
    def add_origin(self) -> None:
        """A bare `origin` cloned from the project, a `publisher` clone and the `git` shim."""
        real = shutil.which("git", path=os.environ["PATH"])
        self.origin = self.root.parent / "origin.git"
        self.publisher = self.root.parent / "publisher"
        self._git_in(self.root.parent, "clone", "--quiet", "--bare", str(self.root),
                     str(self.origin))
        self.git("remote", "add", "origin", str(self.origin))
        self._git_in(self.root.parent, "clone", "--quiet", str(self.origin), str(self.publisher))
        self._git_in(self.publisher, "config", "commit.gpgsign", "false")
        shim = self.bin / "git"
        shim.write_text(GIT_SHIM.format(python=sys.executable, git=real,
                                        log=str(self.state / "calls.jsonl")), "utf-8")
        shim.chmod(0o755)

    def publish(self, files: dict[str, str]) -> None:
        """One commit on `origin`'s main from the publisher, writing `files`."""
        for name, text in files.items():
            (self.publisher / name).write_text(text, "utf-8")
        self._git_in(self.publisher, "add", "-A")
        self._git_in(self.publisher, "commit", "--quiet", "-m", "publish")
        self._git_in(self.publisher, "push", "--quiet", "origin", "HEAD:main")

    def entry(self, path: str) -> dict:
        """The `{path, mode, object}` entry `origin`'s main holds at `path`, read with Git
        independently of the command; `mode` and `object` are None when it holds nothing."""
        listed = self._git_in(self.origin, "ls-tree", "--full-tree", "main", "--", path).strip()
        if not listed:
            return {"path": path, "mode": None, "object": None}
        mode, _, rest = listed.partition(" ")
        return {"path": path, "mode": mode, "object": rest.split("\t")[0].split(" ")[1]}

    def failure(self, path: str) -> dict:
        """A `verification-failure` of the project's `nix-build` whose one fact selects `path`
        as `origin` holds it now."""
        contract = json.loads((self.root / ".agents/project.json").read_text("utf-8"))
        return {"kind": "verification-failure", "schema_version": 1,
                "repository": {"project_id": contract["project"]["id"],
                               "integration_branch":
                                   contract["bindings"]["vcs"]["integration_branch"]},
                "command": {"id": "nix-build", "argv": ["just", "build"], "cwd": ".",
                            "env": []},
                "failure_class": "dependency",
                "facts": [{"name": "pinned", "source": {"paths": [path]},
                           "value": {"objects": [self.entry(path)]}}]}

    def park(self, session: dict, action_id: str, failure: dict) -> None:
        """Suspend `action_id` on `failure` through the source `workflow-state`, unlogged."""
        done = self.ws("suspend", "--repo-root", self.root, "--run-id", session["run_id"],
                       "--action-id", action_id, "--blocked-on", "verification",
                       "--verification-input", "-", stdin=json.dumps(failure).encode())
        self.case.assertEqual(done.returncode, 0, done.stdout + done.stderr)
```

`real` is resolved from this process's `PATH`, which never holds the world's `bin/`, so the shim cannot call itself. `publish` uses `push` only inside test code; no gate command spells it.

`tests/test_orchestrate_control.py`: before `from .orchestrate_world import …` add `from agent_tools import verification_blocker as vb` and a blank line. Insert before `class RefusalTableTest(unittest.TestCase):`:

```python
READY = {"command", "outcome", "run_id", "control_calls", "response", "dispatches",
         "contracts_due", "refused_contracts", "contract_refusals", "verification_refusals",
         "ends_run"}


def observed(world, record, path):
    """The observation of `record`'s blocker as `origin` holds `path` now."""
    return {"kind": "verification-observation", "schema_version": 1,
            "blocker_id": vb.blocker_id(record), "repository": record["repository"],
            "facts": world.failure(path)["facts"]}


class GatherTest(unittest.TestCase):
    """`step` observes every awaited blocker once, after at most one fetch (issue 546 D3)."""

    def parked(self, parked=((61, "flake.lock"),), others=()):
        """A world with `origin`, a session of the parked issues then `others`, each parked
        issue spawned with a live worktree and suspended on its path's failure."""
        world = OrchestrateWorld(self)
        world.add_origin()
        world.publish({"flake.lock": "lock 1\n", "Cargo.lock": "cargo 1\n"})
        issues = [issue for issue, _ in parked]
        session = world.start(*(str(n) for n in (*issues, *others)))["session"]
        world.seed_spawn(session, issues)
        failures = []
        for issue, path in parked:
            world.add_worktree(world.candidate(issue), f"worktree-issue-{issue}-orchestrated")
            failures.append(world.failure(path))
            world.park(session, f"{issue}:1:1", failures[-1])
        return world, session, failures

    def ready(self, done, out):
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(set(out), READY)
        return out

    def test_an_equal_observation_resumes_nothing_and_an_unrelated_commit_keeps_it_equal(self):
        world, session, (x,) = self.parked()
        out = self.ready(*world.step(session))
        (fetch,) = world.calls("git")
        self.assertEqual(fetch["argv"], [
            "-C", str(world.root), "fetch", "--quiet", "--no-tags", "--no-write-fetch-head",
            "--no-auto-maintenance", "--no-recurse-submodules", "--refmap=", "origin",
            "+refs/heads/main:refs/remotes/origin/main"])
        (request,) = world.requests()
        self.assertEqual(request["verification"], [observed(world, x, "flake.lock")])
        self.assertEqual(request["verification"][0]["facts"], x["facts"])
        self.assertEqual((out["dispatches"], out["verification_refusals"]), ([], []))
        world.publish({"README.md": "readme 2\n"})
        out = self.ready(*world.step(session))
        self.assertEqual(len(world.calls("git")), 2)
        self.assertEqual(world.requests()[1]["verification"][0]["facts"], x["facts"])
        self.assertEqual((out["dispatches"], out["verification_refusals"]), ([], []))

    def test_a_selected_change_resumes_the_parked_attempt(self):
        world, session, (x,) = self.parked()
        world.publish({"flake.lock": "lock 2\n"})
        out = self.ready(*world.step(session))
        (request,) = world.requests()
        self.assertEqual(request["verification"], [observed(world, x, "flake.lock")])
        self.assertNotEqual(request["verification"][0]["facts"], x["facts"])
        self.assertEqual([(d["launch_kind"], d["action_id"]) for d in out["dispatches"]],
                         [("resume", "61:1:2")])
        self.assertEqual(out["verification_refusals"], [])

    def test_an_unreachable_origin_is_reported_and_the_attempt_stays_parked(self):
        world, session, (x,) = self.parked()
        world.git("remote", "set-url", "origin", str(world.root.parent / "missing.git"))
        out = self.ready(*world.step(session))
        (request,) = world.requests()
        self.assertEqual(request["verification"], [])
        (refusal,) = out["verification_refusals"]
        self.assertEqual(set(refusal), {"blocker_id", "detail"})
        self.assertEqual(refusal["blocker_id"], vb.blocker_id(x))
        self.assertTrue(refusal["detail"].startswith("git fetch: "), refusal["detail"])
        self.assertLessEqual(len(refusal["detail"]), 300)
        self.assertEqual(out["dispatches"], [])
        (summary,) = [s for s in out["response"]["summaries"] if s["issue"] == 61]
        self.assertEqual([r["blocker_id"] for r in summary["requirements"]
                          if r["kind"] == "verification"], [vb.blocker_id(x)])

    def test_two_blockers_are_observed_in_bootstrap_order_after_one_fetch(self):
        world, session, (x, y) = self.parked(((61, "flake.lock"), (62, "Cargo.lock")))
        out = self.ready(*world.step(session))
        self.assertEqual(len(world.calls("git")), 1)
        (request,) = world.requests()
        self.assertEqual(request["verification"], sorted(
            [observed(world, x, "flake.lock"), observed(world, y, "Cargo.lock")],
            key=lambda item: item["blocker_id"]))
        self.assertEqual(out["verification_refusals"], [])

    def test_no_awaited_blocker_never_fetches(self):
        world = OrchestrateWorld(self)
        world.add_origin()
        session = world.start("12", "14")["session"]
        out = self.ready(*world.step(session, first_sweep=True))
        self.assertEqual(out["control_calls"], 2)
        self.assertEqual(world.calls("git"), [])
        self.assertEqual([r["verification"] for r in world.requests()], [[], []])
        self.assertEqual(out["verification_refusals"], [])

    def test_the_chained_call_sends_no_observation(self):
        world, session, (x,) = self.parked(others=(62,))
        out = self.ready(*world.step(session))
        self.assertEqual(out["control_calls"], 2)
        first, chained = world.requests()
        self.assertEqual((first["verification"], chained["verification"]),
                         ([observed(world, x, "flake.lock")], []))
        self.assertEqual(len(world.calls("git")), 1)

    def test_a_malformed_bootstrap_requirement_refuses_at_bootstrap(self):
        world = OrchestrateWorld(self)
        world.add_origin()
        session = world.start("12")["session"]
        boot = json.loads(world.ws("init-run", "--repo-root", world.root,
                                   "--run-id", session["run_id"]).stdout)
        requirement = {"kind": "verification", "blocker_id": "sha256:" + "1" * 64,
                       "sources": [{"name": "pinned", "paths": ["flake.lock"]}]}
        cases = (({}, "requirements: must be a list"),
                 ([{**requirement, "extra": 1}],
                  "requirements[0]: requirement: missing [], unknown ['extra']"))
        for verification, detail in cases:
            with self.subTest(detail=detail):
                world.clear_faults()
                world.fault("workflow-state", "init-run",
                            stdout=json.dumps({**boot, "verification": verification}) + "\n")
                world.fault("artifact-budget", "validate-report",
                            stdin_kind="workflow_bootstrap", passthrough=True)
                out = assert_refused(self, world.step(session)[0], "step", "bootstrap",
                                     ["bindings"])
                self.assertEqual(out["detail"], detail)
        self.assertEqual(world.calls("git"), [])
```

The chained case parks 61 and leaves 62 without a contract, so a step without `first_sweep` gets a first reply whose only action is `delivery_contract` for 62 and chains. The malformed case reaches the command through the fault and passthrough rules because the source validator itself refuses such a bootstrap: both sides of the boundary check (D3).

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 900 s): `PYTHONPATH="$PWD/python" python3 -m unittest tests.test_orchestrate_control.GatherTest 2>&1 | grep -E '^(Ran|OK|FAILED)'`
Expected: `Ran 7 tests`, `FAILED (failures=8)`: every ready object lacks `verification_refusals` (`Items in the second set but not the first`), and the malformed bootstrap is not refused at `bootstrap` (two subtests).

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/orchestrate_control.py` (D3):
- Imports (agent-helpers rule 3, a packaged sibling imported normally): `from agent_tools.verification_blocker import BlockerRefused` and `from agent_tools.verification_observe import observe_all`, after the `agent_tools.canonical` import.
- `control_request` gains a required keyword `verification: list` and sends `"verification": verification`. Its docstring becomes: `The interface-4 `control` request: the facts, the bound policy, the built pairs, `human_directed`, which only an explicit session's first sweep sets (issue 458 D4), and `verification`, the observations `bootstrap` gathered (issue 546 D3).`
- `control_rounds` gains a last positional parameter `observations: list[dict]`; the first `control_request` passes `verification=observations`, the chained one `verification=[]`. Append to its docstring: `The observations ride the first call only: it commits any resolution, so the chained call sends `[]` (issue 546 D3).`
- `step`, right after the `init-run did not answer the session's run` check and before `done.append("bootstrap")`:

  ```python
      try:  # every awaited blocker, observed once after at most one fetch (issue 546 D3)
          observations, unobserved = observe_all(args.repo_root, boot.get("verification"))
      except BlockerRefused as refusal:
          raise Refusal("bootstrap", str(refusal)) from refusal
  ```

  pass `observations` as `control_rounds`' last argument, and add to the ready object, between `contract_refusals` and `ends_run`:

  ```python
              "verification_refusals": [
                  {"blocker_id": blocker, "detail": " ".join(reason.split())[:DETAIL_LIMIT]}
                  for blocker, reason in unobserved],
  ```
- Module docstring, four edits, each line at most 100 characters:
  - in the `step` paragraph, `` `bootstrap` (`init-run --run-id` for the session's run) `` becomes `` `bootstrap` (`init-run --run-id` for the session's run, then `verification_observe.observe_all` over every `verification` requirement it lists, after at most one fetch; a list the adapter refuses refuses here) ``;
  - `` `owners` empty (the observations ride the first call only) `` becomes `` `owners` and `verification` empty (the observations ride the first call only) ``;
  - the ready member list gains `"verification_refusals"` before `"ends_run"`, and its explanation gains, before `and `ends_run` is true`: `` `verification_refusals` one `{blocker_id, detail}` per requirement `bootstrap` could not observe, in bootstrap order (left out of the request, so its attempt stays parked), ``;
  - the closing `…environment, and writes no file.` becomes `…environment, and writes no file of its own: besides `workflow-state`'s ledger writes, its one write is the fetch's update of `refs/remotes/origin/<integration_branch>` and that commit's objects, made only when the bootstrap lists a requirement (issue 546 D4).`

`python/README.md` § `orchestrate-control` (D4), seven edits:
1. After ``requires that run in the answer`` (the `bootstrap` sentence of the `step` paragraph), replace the period with: ``, then observes in process, through `agent_tools.verification_observe.observe_all`, every `verification` requirement the bootstrap lists, the session's issues or not, after one resolution and at most one fetch, and none when it lists none (issue 546); a `verification` member that is not a list, or an element the adapter refuses, refuses at `bootstrap` with that `BlockerRefused` line, while a requirement it cannot observe never refuses the step.``
2. ``and `verification` is `[]` (issue 545).`` becomes ``and `verification` holds the observations, in bootstrap order (issue 546).``
3. ``with the same facts, `owners` empty (the observations ride the first call only) and the pair`` becomes ``with the same facts, `owners` and `verification` empty (the observations ride the first call only: it commits any resolution, so a resent observation would name a resolved record) and the pair``.
4. The ready literal gains `"verification_refusals",` before `"ends_run"`.
5. After ``the previous list plus this call's refusals, ascending;`` insert `` `verification_refusals` one `{blocker_id, detail}` per requirement `bootstrap` could not observe, in bootstrap order, `detail` the adapter's reason collapsed to one line of at most 300 characters (the requirement is left out of the request, its attempt stays parked, and the next step observes it anew);``.
6. ``The command writes no file; its only writes are `workflow-state`'s own ledger writes under the ledger repository's `.superpowers/`.`` becomes ``The command writes no file of its own. Its writes are `workflow-state`'s ledger writes under the ledger repository's `.superpowers/` and, when the bootstrap lists a requirement, the fetch's update of `refs/remotes/origin/<integration_branch>` in the ledger repository with that commit's objects, the adapter's only write (issue 543 D6).``
7. ``The command writes no file and holds no lock.`` becomes ``The command holds no lock of its own: a fetch that loses Git's ref lock refuses every requirement, and the next step observes them again (issue 546 D12).``

`home/common/claude-code/default.nix`, comment only (D4): `(orchestrate-control's through its` / `# workflow-state children)` becomes `(orchestrate-control's through its` / `# workflow-state children, plus the verification-observe fetch it makes in process when a` / `# run awaits a verification blocker)`, keeping the rest of the sentence and every allow entry.

`home/common/agent-skills/README.md` § `### Verification blockers`, the second paragraph's last sentences: ``Known limitation: no caller gathers observations yet: `orchestrate-control` sends `verification: []`, and acquire-direct fails loudly on a `verification` requirement and on a `suspended` reply; that is issue 546.`` becomes ``` `orchestrate-control step` gathers the observations (`python/README.md` § `orchestrate-control`). Known limitation: acquire-direct fails loudly on a `verification` requirement and on a `suspended` reply; that is issue 546.``` (Task 3 rewrites this.)

- [ ] **Step 4: Verify**

Run (timeout 2400 s): `PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner --jobs 4 tests/test_orchestrate_control.py tests/test_verification_observe.py home/common/agent-skills/tests/test_verification_control.py 2>&1 | tail -1`
Expected: `suite-runner: summary members=3 passed=3 failed=0` (the existing `FactsTest` still sees `verification: []`, and `test_no_file_is_created_under_the_ledger_root_or_working_directory` stays green without an `origin`).
Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base 763d8d48570c747ad368d0849939328ad12b49ed; grep -c '"verification": \[\]' python/agent_tools/orchestrate_control.py; grep -c 'no caller gathers' home/common/agent-skills/README.md`
Expected: `check: pass`, then `0`, then `0` (each terminal `grep -c` exiting 1 is the passing case).
Stage first (the Git-backed flake reads only tracked content), then run (timeout 3600 s): `just build`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/orchestrate_control.py tests/orchestrate_world.py tests/test_orchestrate_control.py python/README.md home/common/claude-code/default.nix home/common/agent-skills/README.md
launch-commit … -- -m "feat(orchestrate-control): gather blocker observations" -m "Issue 546." -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":2,"records":[{"bounds":[{"added_lines":46,"boundary":"all","deleted_lines":22,"record_bytes":18432,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2a","last_task":2,"owner":2,"path":"python/agent_tools/orchestrate_control.py"},{"bounds":[{"added_lines":85,"boundary":"all","deleted_lines":2,"record_bytes":9216,"support":{"covers":["r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":2,"owner":2,"path":"tests/orchestrate_world.py"},{"bounds":[{"added_lines":165,"boundary":"all","deleted_lines":4,"record_bytes":12288,"support":{"covers":["r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":2,"owner":2,"path":"tests/test_orchestrate_control.py"},{"bounds":[{"added_lines":10,"boundary":"all","deleted_lines":10,"record_bytes":53248,"support":{"covers":["r1c","r2d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2d","last_task":3,"owner":2,"path":"python/README.md"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":2,"record_bytes":2048,"support":{"covers":["r2e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2e","last_task":2,"owner":2,"path":"home/common/claude-code/default.nix"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":19456,"support":{"covers":["r2f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2f","last_task":3,"owner":2,"path":"home/common/agent-skills/README.md"}]}}
```
