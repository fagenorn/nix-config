# Task 3: `release deploy inspect`

Spec § The `release deploy inspect` command and § Acceptance mapping (AC2, command half); per D5, D10, D16. After this task, `release deploy inspect --commit <MERGE_SHA> [--repo-root PATH]` runs these steps:

1. it resolves the project with `deploy` required;
2. it refuses an unregistered deploy adapter;
3. it removes `bindings.tracker.credential_env.unset_before_invocation` from its own environment;
4. it calls the registered adapter's `inspect` for its watch operation;
5. it prints the observation and exits 0 whatever the outcome.

Typed refusals exit 2. No launcher or command-table row is added: `release` already has one.

**Files:**
- Modify: `python/agent_tools/release.py` (imports, new `COMMIT` and `command_deploy_inspect`, `build_parser`, `main`, the module docstring)
- Test: `tests/test_release_command.py` (new `DeployInspectTest`, one import line)
- Modify: `python/README.md` (§ Release profiles, a paragraph after the `release profile inspect` one)

**Interfaces:**
- Consumes:
  - `resolve_project.resolve(repo_root, required)`;
  - `resolve_project.registered_deploy_adapter(deploy) -> str | None` (Task 2);
  - `release_adapter.REGISTRY`, `DESCRIPTORS` and `watch_operation` (Task 1);
  - `tests/actions_world.py`: `ActionsWorld`, `run`, `CONFIG`, `MERGE`, `OLDER` (Task 1);
  - `ReleaseCommandCase` (`setUp`, `write_contract`, `contract`, `run_release`).
- Produces:
  - `release.command_deploy_inspect(args: argparse.Namespace) -> int`;
  - the parser area `deploy` with action `inspect`, `--commit` (required) and `--repo-root`;
  - error codes `parameters_invalid` (repair `release.deploy.commit_invalid`, pointer `/commit`) and `deploy_adapter_unregistered` (repair `release.deploy.adapter_unregistered`, pointer `/bindings/deploy/adapter`).

**Invariants:**
- The `--commit` check runs before `resolve`. The adapter is called only after resolution and the registration check, so a refusal reads nothing: no `gh` call and no HTTP request.
- The unset names come from the resolved binding alone, with nothing hardcoded (D10). The command holds no state between calls (D5).
- `release adapter inspect` and `release profile inspect` behave exactly as before. `AdapterInspectTest`, `ProfileInspectTest` and `PublicationFreeInspectTest` stay green and are not edited.

- [ ] **Step 1: Write the failing tests**

In `tests/test_release_command.py`, add `from .actions_world import CONFIG, MERGE, OLDER, ActionsWorld, run` directly above `from .forge_world import CANONICAL, ROWS, ForgeWorld`. Then insert this class directly before `if __name__ == "__main__":`:

```python
class DeployInspectTest(ReleaseCommandCase):
    """`release deploy inspect` over a JarBird-shaped contract (issue 465 D5, D10, D16)."""

    def setUp(self):
        super().setUp()
        self.world = ActionsWorld(self)
        contract = self.contract()
        profile = json.loads((REPO / "tests/fixtures/release/publication-free-profile.json")
                             .read_text("utf-8"))
        contract["release"] = {"profiles": {"forge-main": profile}}
        contract["bindings"]["deploy"] = {"adapter": "github-actions-health", "command": None,
                                          "config": dict(CONFIG, health_url=self.world.url())}
        contract["bindings"]["tracker"]["credential_env"]["unset_before_invocation"] = [
            "GITHUB_TOKEN", "GH_TOKEN"]
        contract["capabilities"]["deploy"]["support"] = "supported"
        self.write_contract(contract)

    def deploy(self, commit=MERGE, env=None):
        return self.run_release("deploy", "inspect", "--commit", commit, env=env)

    def verdict(self, *runs, **health):
        self.world.runs(*runs)
        self.world.health(**health)
        code, observation, err = self.deploy()
        self.assertEqual(code, 0, err)
        return observation["outcome"], observation["reason"]

    def test_satisfied_needs_a_successful_run_and_a_matching_health_commit(self):
        self.assertEqual(self.verdict(run(8, MERGE), commit=MERGE), ("satisfied", "deployed"))
        self.assertEqual(self.verdict(run(8, MERGE), commit=OLDER),
                         ("diverged", "health_commit_mismatch"))
        self.assertEqual(self.verdict(run(8, MERGE, conclusion="failure"), commit=MERGE),
                         ("diverged", "run_failed"))
        self.assertEqual(self.verdict(run(8, MERGE, conclusion="failure"), commit=OLDER),
                         ("diverged", "silent_rollback"))

    def test_the_credential_binding_decides_what_gh_sees(self):
        self.assertEqual(self.verdict(run(8, MERGE, status="queued")),
                         ("in_progress", "run_in_progress"))
        contract = self.contract()
        contract["bindings"]["tracker"]["credential_env"]["unset_before_invocation"] = []
        self.write_contract(contract)
        self.assertEqual(self.verdict(run(8, MERGE, status="queued")),
                         ("in_progress", "run_in_progress"))
        self.assertEqual([call["token_visible"] for call in self.world.calls()], [False, True])

    def test_typed_refusals_exit_2_before_any_read(self):
        def refusal(*args, **kwargs):
            code, payload, _ = self.deploy(*args, **kwargs)
            return code, payload["error"]["code"], payload["error"]["repair_id"]

        for commit in (MERGE.upper(), MERGE[:7], "HEAD"):
            with self.subTest(commit=commit):
                self.assertEqual(refusal(commit), (2, "parameters_invalid",
                                                   "release.deploy.commit_invalid"))
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        self.assertEqual(refusal(env={"PATH": empty.name}),
                         (2, "capability_unavailable",
                          "capability.deploy.release_adapter_unavailable"))
        contract = self.contract()
        contract["capabilities"]["deploy"]["support"] = "unsupported"
        self.write_contract(contract)
        self.assertEqual(refusal(), (2, "capability_unavailable", "capability.deploy.unsupported"))
        contract = self.contract()
        contract["release"] = "unsupported"
        contract["capabilities"]["deploy"]["support"] = "supported"
        contract["bindings"]["commands"]["deploy-list"] = {"argv": ["gh", "run", "list"],
                                                           "cwd": ".", "env": []}
        contract["bindings"]["deploy"] = {"adapter": "railway", "command": "deploy-list",
                                          "config": {}}
        self.write_contract(contract)
        self.assertEqual(refusal(), (2, "deploy_adapter_unregistered",
                                     "release.deploy.adapter_unregistered"))
        self.assertEqual(self.world.calls(), [])
        self.assertEqual(self.world.requests, [])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Unit run on `tests/test_release_command.py -k DeployInspectTest`.

Expected: `FAILED (errors=3)`, each a `JSONDecodeError`: argparse rejects the area `deploy` on stderr and leaves stdout empty.

- [ ] **Step 3: Write the minimal implementation**

1. Add `import os` and `import re` to `python/agent_tools/release.py`, and add `registered_deploy_adapter` to the `agent_tools.resolve_project` import list in sorted position. Insert this directly before `def build_parser`:

```python
COMMIT = re.compile(r"[0-9a-f]{40}")


def command_deploy_inspect(args: argparse.Namespace) -> int:
    """The registered deploy adapter's observation for one merge commit (issue 465 D5, D10).

    A malformed `--commit`, a resolver refusal (`deploy` is required) and an unregistered
    deploy adapter are typed errors. Otherwise the tracker's credential variables are removed
    from this process before the adapter's `inspect` runs, and the observation is printed
    whatever its outcome.
    """
    if COMMIT.fullmatch(args.commit) is None:
        raise _adapter_error("parameters_invalid", "release.deploy.commit_invalid", "/commit",
                             "--commit must be 40 lowercase hex characters")
    bindings = resolve(args.repo_root, ["deploy"])["bindings"]
    name = registered_deploy_adapter(bindings["deploy"])
    if name is None:
        raise _adapter_error(
            "deploy_adapter_unregistered", "release.deploy.adapter_unregistered",
            "/bindings/deploy/adapter",
            f"{bindings['deploy']['adapter']} is not a registered adapter: "
            "the binding's command is the deploy reader")
    for variable in bindings["tracker"]["credential_env"]["unset_before_invocation"]:
        os.environ.pop(variable, None)
    operation = release_adapter.watch_operation(release_adapter.DESCRIPTORS[name])
    return emit_json(release_adapter.REGISTRY[name].inspect({
        "kind": "effect", "operation": operation, "parameters": {
            "target": {"kind": "github_repository",
                       "repository": bindings["tracker"]["repo_slug"],
                       "branch": bindings["vcs"]["default_branch"]},
            "candidate": {"commit": args.commit},
            "config": bindings["deploy"]["config"]}}))
```

2. In `build_parser`, before `return parser`, add the `deploy` area:

```python
    deploy = areas.add_parser("deploy", help="deploy watching")
    deploy_actions = deploy.add_subparsers(dest="action", required=True)
    deploy_inspect = deploy_actions.add_parser(
        "inspect", help="print the deploy observation for one commit on stdout")
    deploy_inspect.add_argument("--commit", required=True,
                                help="the merge commit, 40 lowercase hex characters")
    add_repo_root(deploy_inspect)
```

3. In `main`, dispatch by area: `return {"profile": command_profile_inspect, "adapter": command_adapter_inspect, "deploy": command_deploy_inspect}[args.area](args)`.

4. In the module docstring, replace the paragraph that begins `` `release adapter inspect <adapter> <operation> --parameters <json>` is the one adapter read `` with:

```text
`release adapter inspect <adapter> <operation> --parameters <json>` is the one project-free
adapter read (D15): it resolves no project, calls the registered adapter's `inspect` for one
effect and prints the observation. `release deploy inspect --commit <sha>` (issue 465 D5) is
the deploy read ship-release Phase 5 polls: it resolves the project with `deploy` required,
removes the tracker's `credential_env.unset_before_invocation` names from its own environment
(D10), asks the registered deploy adapter's `inspect` about the commit and prints the
observation with exit 0 whatever its outcome. No adapter `invoke` is reachable from any
command.
```

5. In `python/README.md` § Release profiles, insert this paragraph directly after the paragraph that begins `` `release profile inspect <profile-id> [--repo-root PATH]` ``:

```text
`release deploy inspect --commit <sha> [--repo-root PATH]` (issue 465 D5) is the deploy read that ship-release Phase 5 polls. A `--commit` that is not 40 lowercase hex characters is `parameters_invalid` (repair `release.deploy.commit_invalid`). It then resolves the project as `resolve-project resolve --require deploy` does, so a refusal, `capability_unavailable` for an unsupported or blocked deploy included, reaches the caller byte for byte. A `bindings.deploy.adapter` outside the registry is `deploy_adapter_unregistered` (repair `release.deploy.adapter_unregistered`), because that binding's command is the deploy reader. All three exit 2 before any read. Otherwise it removes every name in `bindings.tracker.credential_env.unset_before_invocation` from its own environment (D10) and calls the registered adapter's `inspect` for its watch operation. The request has the tracker's `repo_slug` and the default branch as a `github_repository` target, the commit as the candidate, and `bindings.deploy.config` as the config. It prints the observation as compact sorted-key JSON and exits 0 whatever the outcome, and it keeps no state between calls.
```

- [ ] **Step 4: Verify**

1. Run the Unit run on `tests/test_release_command.py`.

   Expected: `OK`, with the existing profile and adapter cases included.

2. Run the Unit run on `tests/test_actions_health_adapter.py home/common/agent-skills/tests/test_resolve_project.py -k DeployWatch -k ClassificationTest`.

   Expected: `OK` at this head.

3. Run the Build.

   Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release.py tests/test_release_command.py python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(release): deploy inspect reads the registered deploy adapter (issue 465)" -m "<trailers>"
```
