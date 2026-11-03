# Task 2: `step` facts and one control round

**Files:**
- Modify: `python/agent_tools/orchestrate_control.py`
- Modify: `tests/orchestrate_world.py`
- Test: `tests/test_orchestrate_control.py`

**Interfaces:**
- Consumes (Task 1): `Refusal`, `InvocationError`, `Bindings`, `load_bindings`, `strict_json`, `run_child`, `why`, `validate_bytes`, `workflow_response`, `tracker_env`, `require_github`, `ROUTE`, `_Parser`, `main`; world `OrchestrateWorld` (`run`, `start`, `fault`, `calls`, `ws`, `git`, `root`, `cwd`), `PRELUDE`, `GH_TAIL`, `SLUG`, `INVALID`.
- Produces (module):
  - `DECISION_LABELS = frozenset({"wayfinder:research", "wayfinder:prototype", "wayfinder:grilling", "wayfinder:task"})`, `TRACKER_CHUNK = 100`, `CLOSED_KINDS = ("spawn", "resume", "retry", "delivery_remainder", "delivery_contract", "wait", "finalize")`, `DISPATCH_KINDS = ("spawn", "resume", "retry")`.
  - `@dataclass(frozen=True) class StepInput`: `session: dict`, `first_sweep: bool`, `owners: list[dict]`, `contracts_due: tuple[int, ...]`, `refused_contracts: tuple[int, ...]`; `read_step_input(raw: bytes) -> StepInput` (raises `InvocationError`).
  - `tracker_facts(b: Bindings, issues: Sequence[int]) -> list[dict]`, `forge_facts(b: Bindings, issues: Sequence[int]) -> dict[str, dict]`, `worktree_facts(repo_root: str, b: Bindings, issues: Sequence[int], requirements: Sequence[dict]) -> list[dict]`.
  - `control_request(b: Bindings, session: dict, tracker: list, forge: dict, worktrees: list, owners: list, pairs: Mapping[int, dict]) -> dict` (a pair is `{"contract": …, "initial_intent": …}`).
  - `run_control(repo_root: str, run_id: str, request: dict, *, previous: dict | None = None) -> dict`.
  - `asks_for_contract(summary: dict) -> bool`.
  - `project(response: dict, repo_root: str, run_id: str) -> list[dict]` (closed-set check; this task projects no dispatch kind).
  - `step(args: argparse.Namespace, done: list[str]) -> dict`.
- Produces (world): `issue`, `blocker` (static), `missing`, `pull`, `truncate_forge`, `candidate`, `add_worktree`, `seed_spawn`, `step`, `requests`.
- Produces (suite): module constant `STEP_ORDER`, functions `steps_before(step)` and `assert_refused(case, done, command, step, completed)`.

**Invariants:**
- `step` runs `bindings`, `bootstrap`, `tracker`, `forge`, `worktrees`, `control`, `project` in order (Task 4 inserts `contracts` before `control`); the first refusal stops it.
- Exactly one tracker GraphQL call per started chunk of 100 session issues and exactly one paginated forge call per step; none sees any variable the bound `unset_before_invocation` lists — the fixture binds `GITHUB_TOKEN`, `GH_TOKEN` and the unfamiliar `ORCH_TEST_SENTINEL`, all exported to the command (D30).
- Facts cover exactly the session's issues in session order; out-of-session requirements are not observed, but their recorded paths exclude candidates (D19).
- Every reply is validated before any field is read; the `control` request never carries `now`.
- `project` refuses any kind outside `CLOSED_KINDS`, before projecting anything (D23).

- [ ] **Step 1: Extend the world**

`GH_TAIL`: before the final `unregistered call` lines, answer `api graphql` (D27). The query is the argv element after `-f` that starts with `query=`:
- With `--paginate` in argv: sort `world["pulls"]` by `number`, cut into pages of 2 (`[[]]` when empty), and print the `--slurp` array: page `i` is `{"data": {"repository": {"pullRequests": {"pageInfo": {"hasNextPage": not last or world["forge_truncated"], "endCursor": f"c{i}"}, "nodes": <page>}}}}`.
- Otherwise: for every `re.findall(r"(i\d+): issueOrPullRequest\(number: (\d+)\)", query)` pair, the alias maps to `None` when the number is in `world["missing"]`, else to `{"__typename": spec["typename"], "number": n}` plus, for an `Issue`, `"state": spec["state"]` and `"blockedBy": {"pageInfo": {"hasNextPage": spec["truncated"]}, "nodes": spec["blocked_by"]}`, where `spec = world["issues"].get(str(n), {"typename": "Issue", "state": "OPEN", "blocked_by": [], "truncated": False})`. Print `{"data": {"repository": {<aliases>}}}`.

Methods (each rewrites `state/gh.json`):
- `issue(self, number, *, state="OPEN", blocked_by=(), typename="Issue", truncated=False)`.
- `@staticmethod blocker(number, *, state="OPEN", labels=(), repo=SLUG, labels_truncated=False) -> dict`: `{"number", "state", "url": f"https://github.com/{repo}/issues/{number}", "repository": {"nameWithOwner": repo}, "labels": {"pageInfo": {"hasNextPage": labels_truncated}, "nodes": [{"name": l} for l in labels]}}`.
- `missing(self, number)`; `truncate_forge(self)`.
- `pull(self, number, head, *, state="OPEN", cross=False, merge_oid=None)`: node `{"number", "headRefName": head, "isCrossRepository": cross, "state", "url": f"https://github.com/{SLUG}/pull/{number}", "mergeCommit": {"oid": merge_oid} if merge_oid else None}`.
- `candidate(self, issue, suffix="") -> str`: `str(self.root / ".worktrees" / f"worktree-issue-{issue}-orchestrated{suffix}")`.
- `add_worktree(self, path, branch)`: `git worktree add --quiet -b <branch> <path>`.
- `step(self, session, *, first_sweep=False, owners=(), contracts_due=(), refused_contracts=(), repo_root=None) -> tuple[CompletedProcess, dict | None]`: stdin `json.dumps({"session", "first_sweep", "owners": list(owners), "contracts_due": list(contracts_due), "refused_contracts": list(refused_contracts)})`; argv `step --repo-root <repo_root or root> --input -`; returns the process and the parsed stdout (None when empty).
- `requests(self) -> list[dict]`: the parsed `stdin` of every logged `workflow-state control` call, in order.
- `seed_spawn(self, session, issues, *, paths=None) -> dict[int, dict]`: the world acting as an adapter, through the source `workflow-state` directly (unlogged, D26). `paths` maps an issue to its worktree (default `self.candidate(n)`) for every session issue. For each seeded issue, `ws build-delivery --repo-root <root> --kind contract --input -` with `{"issue", "worktree": paths[n], "source_kind": session["source"]["kind"], "source_reference": session["source"]["reference"]}`; then one `ws control --repo-root <root> --run-id <run_id> --request-file -` with an interface_version 3 request over all session issues: `host_route` `claude-code`, `max_parallel` = `len(issues)`, `attempt_budget_minutes` 240, the session's `human_directed`, open trackers without blockers, `owners: []`, `{"issue", "recorded": None, "candidate": {"path": paths[n], "state": "absent"}}` worktrees, forge `none`, the built pairs (`[initial_intent]`) for seeded issues and null/`[]` otherwise, `[]`/null for the other five maps, no `now`. Assert both exit 0, and return the reply's `spawn` actions by issue; assert every seeded issue is among them.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_orchestrate_control.py` (and `from pathlib import Path` at the top):

```python
STEP_ORDER = ["bindings", "bootstrap", "tracker", "forge", "worktrees", "control", "project"]


def steps_before(step):
    return STEP_ORDER[:STEP_ORDER.index(step)]


def assert_refused(case, done, command, step, completed):
    case.assertEqual(done.returncode, 2, done.stdout + done.stderr)
    out = json.loads(done.stdout)
    case.assertEqual(set(out), {"command", "outcome", "step", "detail", "completed_steps",
                                "response"})
    case.assertEqual((out["command"], out["outcome"], out["step"], out["completed_steps"]),
                     (command, "refused", step, completed))
    case.assertLessEqual(len(out["detail"]), 300)
    case.assertNotIn("\n", out["detail"])
    return out


def keyed(issues, value):
    return {str(issue): value for issue in issues}


class FactsTest(unittest.TestCase):
    def test_the_request_carries_the_bound_policy_and_control_accepts_it(self):
        def policy(contract):
            contract["bindings"]["workflow"]["orchestration"].update(
                max_parallel=3, attempt_budget_minutes=45)
        world = OrchestrateWorld(self, mutate=policy)
        session = world.start("12", "14")["session"]
        done, out = world.step(session, first_sweep=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((out["command"], out["outcome"], out["run_id"]),
                         ("step", "ready", session["run_id"]))
        self.assertEqual((out["response"]["interface_version"], out["response"]["run_id"]),
                         (3, session["run_id"]))
        request = world.requests()[0]
        self.assertNotIn("now", request)
        self.assertEqual({k: v for k, v in request.items()
                          if k not in ("tracker", "worktrees", "forge")}, {
            "interface_version": 3, "host_route": "claude-code", "max_parallel": 3,
            "attempt_budget_minutes": 45, "human_directed": True, "issues": [12, 14],
            "owners": [], "delivery_contracts": keyed([12, 14], None),
            "authorization_intents": keyed([12, 14], []),
            "authority_observations": keyed([12, 14], []),
            "reevaluation_evidence": keyed([12, 14], []),
            "delivery_observations": keyed([12, 14], []),
            "requested_scopes": keyed([12, 14], None), "recoveries": keyed([12, 14], None)})

    def test_no_gh_child_sees_an_unset_variable(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        done, _ = world.step(session)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual([c["token_visible"] for c in world.calls("gh")], [False, False])
        self.assertEqual(world.env["GITHUB_TOKEN"], "harness-token")
        self.assertEqual(world.env["ORCH_TEST_SENTINEL"], "harness-token")

    def test_a_non_control_reply_refuses_at_control(self):
        world = OrchestrateWorld(self)
        session = world.start("12")["session"]
        boot = world.ws("init-run", "--repo-root", world.root, "--run-id", session["run_id"])
        world.fault("workflow-state", "control", stdout=boot.stdout.decode())
        done, _ = world.step(session)
        assert_refused(self, done, "step", "control",
                       ["bindings", "bootstrap", "tracker", "forge", "worktrees", "contracts"])
        self.assertIsNone(json.loads(done.stdout)["response"])

    def test_a_bootstrap_of_another_run_refuses_at_bootstrap(self):
        world = OrchestrateWorld(self)
        session = world.start("12")["session"]
        other = world.ws("init-run", "--repo-root", world.root, "--creation-key", "other")
        world.fault("workflow-state", "init-run", stdout=other.stdout.decode())
        assert_refused(self, world.step(session)[0], "step", "bootstrap", ["bindings"])


class TrackerTest(unittest.TestCase):
    def test_open_blockers_split_into_numbers_and_decision_blockers(self):
        world = OrchestrateWorld(self)
        world.issue(12, blocked_by=[
            world.blocker(5, labels=["wayfinder:task", "bug"]),
            world.blocker(9, labels=["bug"]),
            world.blocker(6),
            world.blocker(10, repo="Fagenorn/Nix-Config"),
            world.blocker(7, state="CLOSED", labels=["wayfinder:research"]),
            world.blocker(8, state="CLOSED", repo="other/repo")])
        world.issue(14, state="CLOSED")
        session = world.start("12", "14")["session"]
        world.step(session)
        self.assertEqual(world.requests()[0]["tracker"], [
            {"issue": 12, "state": "open", "open_blockers": [6, 9, 10],
             "decision_blockers": [{"issue": 5, "url": f"https://github.com/{SLUG}/issues/5"}]},
            {"issue": 14, "state": "closed", "open_blockers": [], "decision_blockers": []}])
        (read,) = [c["argv"] for c in world.calls("gh", "api") if "--paginate" not in c["argv"]]
        self.assertEqual(read[:3] + read[4:], ["api", "graphql", "-f",
                                               "-f", "owner=fagenorn", "-f", "name=nix-config"])
        self.assertIn("blockedBy(first: 50)", read[3])
        self.assertIn("labels(first: 25)", read[3])

    def test_a_cross_repository_open_blocker_refuses_at_tracker(self):
        world = OrchestrateWorld(self)
        world.issue(12, blocked_by=[world.blocker(5, repo="other/repo")])
        session = world.start("12")["session"]
        out = assert_refused(self, world.step(session)[0], "step", "tracker",
                             steps_before("tracker"))
        self.assertIn("other/repo", out["detail"])

    def test_a_truncated_page_a_missing_issue_or_a_pull_request_refuses_at_tracker(self):
        cases = {
            "blockers truncated": lambda w: w.issue(12, truncated=True),
            "labels truncated": lambda w: w.issue(12, blocked_by=[
                w.blocker(5, labels=["bug"], labels_truncated=True)]),
            "missing": lambda w: w.missing(12),
            "pull request": lambda w: w.issue(12, typename="PullRequest")}
        for name, arrange in cases.items():
            with self.subTest(name):
                world = OrchestrateWorld(self)
                arrange(world)
                session = world.start("12")["session"]
                assert_refused(self, world.step(session)[0], "step", "tracker",
                               steps_before("tracker"))

    def test_a_non_github_tracker_refuses_at_tracker(self):
        world = OrchestrateWorld(self, mutate=lambda c: c["bindings"]["tracker"]
                                 .__setitem__("kind", "gitlab"))
        session = world.start("12")["session"]
        assert_refused(self, world.step(session)[0], "step", "tracker", steps_before("tracker"))
        self.assertEqual(world.calls("gh"), [])

    def test_one_tracker_call_per_hundred_issues(self):
        world = OrchestrateWorld(self)
        minted = json.loads(world.ws("init-run", "--repo-root", world.root,
                                     "--creation-key", "k101").stdout)
        session = world.start(*map(str, range(1, 102)), "--run-id", minted["run_id"])["session"]
        world.fault("workflow-state", "control", exit=2, stderr="workflow-state: fixture stop\n")
        assert_refused(self, world.step(session)[0], "step", "control", steps_before("control"))
        api = world.calls("gh", "api")
        reads = [c["argv"] for c in api if "--paginate" not in c["argv"]]
        self.assertEqual([next(a for a in argv if a.startswith("query="))
                          .count("issueOrPullRequest(") for argv in reads], [100, 1])
        self.assertEqual(len([c for c in api if "--paginate" in c["argv"]]), 1)


class ForgeTest(unittest.TestCase):
    def test_the_forge_listing_is_paginated_uncapped_and_matched(self):
        world = OrchestrateWorld(self)
        world.pull(3, "feature-x")
        world.pull(4, "issue-12-old", state="CLOSED")
        world.pull(5, "issue-140-other")
        world.pull(6, "issue-14-fork", cross=True)
        world.pull(9, "worktree-issue-12-new")
        world.pull(12, "issue-16-done", state="MERGED", merge_oid="a" * 40)
        session = world.start("12", "14", "16")["session"]
        world.step(session)
        url = f"https://github.com/{SLUG}/pull/"
        self.assertEqual(world.requests()[0]["forge"], {
            "12": {"state": "open", "url": url + "9", "merge_sha": None},
            "14": {"state": "none", "url": None, "merge_sha": None},
            "16": {"state": "merged", "url": url + "12", "merge_sha": "a" * 40}})
        (listing,) = [c["argv"] for c in world.calls("gh", "api") if "--paginate" in c["argv"]]
        self.assertEqual(listing[:5] + listing[6:], ["api", "graphql", "--paginate", "--slurp",
                                                     "-f", "-f", "owner=fagenorn",
                                                     "-f", "name=nix-config"])
        self.assertIn("pullRequests(first: 100, after: $endCursor)", listing[5])

    def test_a_truncated_forge_listing_refuses_at_forge(self):
        world = OrchestrateWorld(self)
        world.pull(3, "feature-x")
        world.truncate_forge()
        session = world.start("12")["session"]
        assert_refused(self, world.step(session)[0], "step", "forge", steps_before("forge"))


class WorktreeTest(unittest.TestCase):
    def test_recorded_worktrees_normalize_to_three_states(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14", "16", "18")["session"]
        world.seed_spawn(session, [12, 14, 16, 18])
        world.add_worktree(world.candidate(12), "worktree-issue-12-orchestrated")
        Path(world.candidate(16)).mkdir(parents=True)
        world.add_worktree(world.candidate(18), "topic")
        world.step(session)
        recorded = lambda n, state: {"issue": n, "candidate": None,
                                     "recorded": {"path": world.candidate(n), "state": state}}
        self.assertEqual(world.requests()[0]["worktrees"], [
            recorded(12, "matching_issue_branch"), recorded(14, "absent"),
            recorded(16, "mismatch"), recorded(18, "mismatch")])

    def test_a_leftover_worktree_or_branch_moves_the_candidate_to_2(self):
        world = OrchestrateWorld(self)
        world.add_worktree(world.candidate(12), "worktree-issue-12-orchestrated")
        world.git("branch", "issue-14-orchestrated")
        session = world.start("12", "14", "16")["session"]
        done, _ = world.step(session)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        free = lambda n, suffix="": {"issue": n, "recorded": None, "candidate": {
            "path": world.candidate(n, suffix), "state": "absent"}}
        self.assertEqual(world.requests()[0]["worktrees"],
                         [free(12, "-2"), free(14, "-2"), free(16)])

    def test_candidate_exhaustion_refuses_at_worktrees(self):
        world = OrchestrateWorld(self)
        for suffix in ["", *(f"-{n}" for n in range(2, 10))]:
            world.git("branch", f"issue-12-orchestrated{suffix}")
        session = world.start("12")["session"]
        out = assert_refused(self, world.step(session)[0], "step", "worktrees",
                             steps_before("worktrees"))
        self.assertIn("12", out["detail"])

    def test_a_subset_session_observes_only_its_issues_and_avoids_their_paths(self):
        world = OrchestrateWorld(self)
        full = world.start("12", "14")["session"]
        world.add_worktree(world.candidate(14), "issue-12-elsewhere")
        world.seed_spawn(full, [12], paths={12: world.candidate(14),
                                            14: world.candidate(14, "-3")})
        world.git("worktree", "remove", "--force", world.candidate(14))
        subset = world.start("14", "--run-id", full["run_id"])["session"]
        world.step(subset)
        request = world.requests()[0]
        self.assertEqual((request["issues"], [t["issue"] for t in request["tracker"]],
                          list(request["forge"])), ([14], [14], ["14"]))
        self.assertEqual(request["worktrees"], [{"issue": 14, "recorded": None, "candidate": {
            "path": world.candidate(14, "-2"), "state": "absent"}}])


class StepInputTest(unittest.TestCase):
    def test_a_malformed_input_is_an_invalid_invocation(self):
        world = OrchestrateWorld(self)
        session = world.start("12", "14")["session"]
        good = {"session": session, "first_sweep": False, "owners": [], "contracts_due": [],
                "refused_contracts": []}

        def changed(**members):
            return json.dumps({**good, **members})
        accepted = world.run("step", "--repo-root", world.root, "--input", "-",
                             stdin=json.dumps(good))
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        owner = {"event_id": "e", "issue": 99, "custody": {}, "state": "unavailable"}
        cases = {
            "not json": "{",
            "duplicate key": '{"first_sweep": true, ' + changed()[1:],
            "extra member": changed(extra=1),
            "missing member": json.dumps({k: v for k, v in good.items() if k != "owners"}),
            "empty issues": changed(session={**session, "issues": []}),
            "source and direction disagree": changed(session={**session, "source": {
                "kind": "standing_repository", "reference": "sweep:label:x"}}),
            "foreign due": changed(contracts_due=[99]),
            "repeated refused": changed(refused_contracts=[12, 12]),
            "foreign owner": changed(owners=[owner]),
            "first_sweep not boolean": changed(first_sweep=1)}
        for name, text in cases.items():
            with self.subTest(name):
                done = world.run("step", "--repo-root", world.root, "--input", "-", stdin=text)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))
        for argv in (["step", "--repo-root", "relative", "--input", "-"],
                     ["step", "--repo-root", str(world.root), "--input", "file.json"]):
            with self.subTest(argv=argv):
                done = world.run(*argv, stdin=json.dumps(good))
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))


class ClosedSetTest(unittest.TestCase):
    def test_an_unknown_action_kind_refuses_at_project_with_the_response(self):
        world = OrchestrateWorld(self)
        session = world.start("12")["session"]
        canned = {"interface_version": 3, "run_id": session["run_id"],
                  "now": "2026-10-22T00:00:00Z", "summaries": [], "deltas": [],
                  "actions": [{"id": "x", "kind": "teleport"}], "next_deadline": None,
                  "admission": None}
        world.fault("workflow-state", "control", stdout=json.dumps(canned) + "\n")
        world.fault("artifact-budget", "validate-report", passthrough=True)
        out = assert_refused(self, world.step(session)[0], "step", "project",
                             steps_before("project"))
        self.assertEqual(out["response"], canned)
        self.assertIn("teleport", out["detail"])
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py` (timeout 900 s)
Expected: the Task 1 tests pass; every new test fails — `step` is not yet a subcommand, so each run is an invalid invocation (`world.requests()` is empty, stdout is empty, and `StepInputTest` fails on its accepted well-formed input).

- [ ] **Step 4: Write `step` through one control round**

- Parser: subcommand `step` with `--repo-root` (required) and `--input` (required); `_parse` raises `InvocationError` unless the root is absolute and `--input` is exactly `-` (D29).
- `read_step_input(raw)`: `strict_json`; any failure below raises `InvocationError`. Members exactly `session`, `first_sweep`, `owners`, `contracts_due`, `refused_contracts`. `session` members exactly `interface_version` (the `int` 1), `run_id` (non-empty string), `issues` (non-empty list of unique positive `int`s, no `bool`), `human_directed` (`bool`), `source` (members exactly `kind` and `reference`; `kind` is `explicit_user` exactly when `human_directed` is true, else `standing_repository`; `reference` non-empty string). `first_sweep` is a `bool`. `owners` is a list of objects each with an `int` `issue` in `session.issues` (D29). `contracts_due` and `refused_contracts` are lists of unique `int`s drawn from `session.issues`.
- `step(args, done)`: read stdin (`sys.stdin.buffer.read()`), parse it (an `InvocationError` reaches `main`'s invalid-invocation path), then:
  1. `bindings` — `load_bindings(args.repo_root)`.
  2. `bootstrap` — `workflow_response("bootstrap", "init-run", "--repo-root", args.repo_root, "--run-id", run_id)`; `kind` must be `workflow_bootstrap` and `run_id` the session's, else refuse at `bootstrap`.
  3. `tracker` — `require_github("tracker", b)`, then `tracker_facts`.
  4. `forge` — `forge_facts`.
  5. `worktrees` — `worktree_facts(args.repo_root, b, issues, reply["requirements"])`.
  6. `control` — `run_control(args.repo_root, run_id, control_request(b, session, tracker, forge, worktrees, owners, {}))`.
  7. `project` — `project(reply, args.repo_root, run_id)`.
  Ready: `{"command": "step", "outcome": "ready", "run_id": run_id, "control_calls": 1, "response": reply, "dispatches": <project's list>, "contracts_due": sorted(i for each summary that asks_for_contract and i not in refused), "refused_contracts": sorted(input refused_contracts), "contract_refusals": [], "ends_run": <rule>}` where `ends_run` is true exactly when `[a["kind"] for a in reply["actions"]] == ["delivery_contract"]` and every issue that action lists is in `refused_contracts`. `asks_for_contract(summary)`: any `summary["requirements"]` entry has `reason_code == "delivery_contract_required"`.
- `tracker_facts(b, issues)` (D8, D20, D27): owner and name from `repo_slug.split("/")`; for each chunk of `TRACKER_CHUNK` issues in session order, one `run_child("tracker", [b.tracker_cli, "api", "graphql", "-f", "query=" + q, "-f", "owner=" + owner, "-f", "name=" + name], env=tracker_env(b))` where `q` is
  `query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { <fields> } }` and `<fields>` joins, per issue `n`, `i<n>: issueOrPullRequest(number: <n>) { __typename ... on Issue { number state blockedBy(first: 50) { pageInfo { hasNextPage } nodes { number state url repository { nameWithOwner } labels(first: 25) { pageInfo { hasNextPage } nodes { name } } } } } }` with single spaces. A non-zero exit, unparsable output or a missing `data.repository` refuses at `tracker`. Per issue: a null alias (`issue N not found`), a `__typename` other than `Issue`, a state other than `OPEN`/`CLOSED`, or a `hasNextPage` on `blockedBy` or any blocker's `labels` refuses. Each blocker: not `OPEN` → dropped; `repository.nameWithOwner.casefold() != repo_slug.casefold()` → refuse naming the issue, the blocker and its repository; a label in `DECISION_LABELS` → `{"issue": number, "url": url}` in `decision_blockers`; else its number in `open_blockers`. Both lists ascending by number. Entry: `{"issue", "state": "open"|"closed", "open_blockers", "decision_blockers"}`.
- `forge_facts(b, issues)` (D9, D24, D27): one `run_child("forge", [cli, "api", "graphql", "--paginate", "--slurp", "-f", "query=" + FORGE_QUERY, "-f", "owner=…", "-f", "name=…"], env=tracker_env(b))`, `FORGE_QUERY = "query($owner: String!, $name: String!, $endCursor: String) { repository(owner: $owner, name: $name) { pullRequests(first: 100, after: $endCursor) { pageInfo { hasNextPage endCursor } nodes { number headRefName isCrossRepository state url mergeCommit { oid } } } } }"`. The output must be a non-empty list of pages, each with `data.repository.pullRequests.nodes` a list; the last page's `pageInfo.hasNextPage` must be false (`the pull-request listing is incomplete`); else refuse at `forge`. For issue `n`: candidates are nodes with `isCrossRepository` false whose `headRefName`, with `b.worktree_prefix` removed when it starts with it, starts with `f"issue-{n}-"`; the highest `number` wins. None → `{"state": "none", "url": None, "merge_sha": None}`; `OPEN`/`CLOSED` → lower-case state, its `url`, `merge_sha` None; `MERGED` → `"merged"`, its `url`, and `mergeCommit.oid`, which must be 40 lower-case hex characters. Any other state or a missing `url` refuses. Result keyed `str(n)` in session order.
- `worktree_facts(repo_root, b, issues, requirements)` (D10, D19, D21): one `run_child("worktrees", ["git", "-C", repo_root, "worktree", "list", "--porcelain"])` and one `["git", "-C", repo_root, "for-each-ref", "--format=%(refname)", "refs/heads"]`; a non-zero exit refuses at `worktrees`. `live` maps `os.path.realpath(<worktree path>)` to its branch (`refs/heads/` stripped; None when detached). `branches` is the set of `refs/heads/` names. `strip(name)` removes the prefix when the name starts with it. Recorded paths: every requirement's `recorded_worktree`, realpath'd. For each session issue in order: with a requirement, `path = recorded_worktree` and state `absent` when `not os.path.lexists(path)`, `matching_issue_branch` when `live.get(realpath(path))` is a branch whose `strip` starts with `f"issue-{n}-"`, else `mismatch`; entry `{"issue", "recorded": {"path", "state"}, "candidate": None}`. Without one, try `os.path.normpath(os.path.join(b.worktree_root, f"{b.worktree_prefix}issue-{n}-orchestrated{s}"))` for `s` in `""`, `"-2"` … `"-9"`; take the first that does not `lexists`, whose realpath is in neither `live` nor the recorded set nor the candidates already taken, and whose final component and `strip(final component)` are both absent from `branches`; entry `{"issue", "recorded": None, "candidate": {"path", "state": "absent"}}`. None free → `Refusal("worktrees", f"no free candidate worktree for issue {n} (-orchestrated through -9 are taken)")`.
- `control_request(...)`: keys in this order — `interface_version` 3, `host_route` `ROUTE`, `max_parallel`, `attempt_budget_minutes`, `human_directed`, `issues`, `tracker`, `owners`, `worktrees`, `forge`, `delivery_contracts` (`pairs[n]["contract"]` or None), `authorization_intents` (`[pairs[n]["initial_intent"]]` or `[]`), `authority_observations`, `reevaluation_evidence`, `delivery_observations` (`[]`), `requested_scopes`, `recoveries` (None); every map keyed `str(n)` in session order; never `now`.
- `run_control(repo_root, run_id, request, *, previous=None)`: `workflow_response("control", "control", "--repo-root", repo_root, "--run-id", run_id, "--request-file", "-", stdin=json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode())`; a `Refusal` is re-raised with `response=previous`. The validator accepts every workflow-response type (bootstrap, owner, phase gate, …), so before any field is read the reply must be a control response of this run: no `kind` member, `interface_version` the `int` 3, `run_id` equal to the session's, and `actions` and `summaries` lists; anything else raises `Refusal("control", "control returned a reply that is not this run's control response", response=previous)` (D30).
- `project(response, repo_root, run_id)`: first check every action's `kind` against `CLOSED_KINDS` (any other → `Refusal("project", f"unknown action kind {kind!r}", response=response)`, D23); then a `spawn`, `resume`, `retry` or `delivery_remainder` action refuses with `Refusal("project", f"{kind} actions are not projected", response=response)`; the other kinds produce no dispatch, so the list is empty.

- [ ] **Step 5: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py` (timeout 900 s)
Expected: OK, 27 tests, no failures, errors or skips. A tracker call per issue fails `test_one_tracker_call_per_hundred_issues`; a capped or single-page forge read fails the forge test (PR 9 and PR 12 sit on the third page).

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/orchestrate_control.py tests/orchestrate_world.py tests/test_orchestrate_control.py
git commit -m "feat(agent-tools): orchestrate-control step facts and control round (#403)"
```
