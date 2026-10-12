# Task 3: Atomic cutover — the guard reads derived rows, Nix builds the base policy and compiles at activation, Nodo's literals go

Spec sections 4, 5 and 6 (per D1, D3, D4, D5, D6, D8, D15, D16; issue 116 D3 and D4). This task is **one commit**: after it the registered hook reads the compiled policy, and `home/common/claude-code/default.nix` names neither `elevenyellow` nor `elevenyellow/nodocom`. A commit holding only part of it either authorizes Nodo from two tables or from none.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py` (`POLICY_KEYS`, `Policy`, `load_policy`, `Context`, `ownership_problem` and its four call sites)
- Modify: `home/common/claude-code/default.nix`
- Test: `tests/test_claude_permission_guard.py`

**Interfaces:**
- Consumes (Task 2): the compiled policy's seven members and the derived row's three; the launcher `agentTools.launchers.guard-policy` with `compile --base <path> --output <path>` and exit statuses 0, 1, 2; `tests/guard_policy_world.GuardPolicyWorld` (`project`, `compile(base=...)`, `output`).
- Produces: the store file `claude-bash-lifecycle-guard-base-policy.json` (found by that name suffix in the build's requisites); the installed command `claude-guard-policy`; the compiled path `<home directory>/.agents/state/guard/policy.json`; `home.activation.claudeGuardPolicy`. Task 4 documents these.

## The guard's contract

- `POLICY_KEYS` gains `derived_repositories` and `derivation`; a new `DERIVED_ROW_KEYS` is `default_branch`, `integration_branch`, `evidence`.
- `load_policy` keeps every existing check and message, then refuses (returning `(None, reason)`, which `main` already prints as `invalid policy: <reason>`) when: `derived_repositories` is not an object; a key does not fully match `SLUG_PATTERN`; a row is not an object with exactly `DERIVED_ROW_KEYS`; `default_branch` or `integration_branch` is not a string fully matching `REF_NAME_PATTERN`; `evidence` is not an object; a derived key is also an `integration_bases` key (D5); `derivation` is neither `null` nor an object. Each reason starts with the policy path like the existing ones and names the offending repository or member. The guard does not interpret `evidence` or `derivation` further.
- `Policy` gains `derived_repositories` (a dict). Its docstring no longer says the values are Nix-owned or the file a store file: say what the file is from the implemented code (the compiled policy, or any policy of that schema passed as `--policy`).
- `Context` gains `derived_row` (`policy.derived_repositories.get(self.repository)`, so `None` for an unknown or underived repository) and builds `integration_bases` as a copy of the policy's, plus `{repository: row["integration_branch"]}` when the repository has a derived row whose two branches differ. `authorized_bases`, `validate_pr_create`, `validate_merge`, `validate_release_merge` and the permanent-head check keep reading `context.integration_bases` unchanged (D16).
- `ownership_problem` takes the context: `ownership_problem(context)`, called as such by `validate_push`, `validate_pr_create`, `validate_release` and `validate_merge`. It returns, verbatim:
  - `repository unknown is outside standing authorization` when the repository is `None`;
  - with no derived row, `repository <slug> is outside standing authorization` unless the owner is in `authorized_owners`;
  - with a derived row, `repository <slug>: origin/HEAD names <branch>, its derived policy row names <row default_branch>` when `context.base_branch` differs from the row's `default_branch`, with `no branch` for an unresolvable `origin/HEAD` (D8, D16); otherwise `None`, whoever the owner is.

**Invariants:**
- A derived row authorizes exactly its repository: another repository of the same owner is refused unless that owner is a literal (R2, D3).
- For a repository with no derived row every verdict is what it was at base (the 51 existing tests pass with zero lines of them edited).
- A policy outside the schema, a missing file included, blocks every Bash call; the detaching-word refusal still precedes the policy load.
- The guard still imports nothing from `agent_tools`, starts no new child and reads one file.
- The built base policy holds `authorized_owners` `["fagenorn"]` and `integration_bases` `{"fagenorn/arcwave": "dev"}`; `default.nix` does not contain the string `elevenyellow`.
- `just build` fails when the guard source or the base policy cannot load (R7): the wrapper's `checkPhase` runs the guard with a trailing `--policy <base policy>`.

- [ ] **Step 1: Write the failing tests**

All four edits to `tests/test_claude_permission_guard.py` are additions; no existing line changes.

(a) Add the import and four constants, so that the lines from `import unittest` down to `EXPECTED_ALLOW = [` read:

```python
import unittest

from .guard_policy_world import GuardPolicyWorld


SETTINGS_PATH = Path(os.environ["CLAUDE_SETTINGS_PATH"])
BASE_POLICY_PATH = Path(os.environ["CLAUDE_GUARD_BASE_POLICY_PATH"])
NODO = "elevenyellow/nodocom"
NODO_ROW = {"default_branch": "main", "integration_branch": "dev", "evidence": {}}
ABSENT = object()
```

(b) At the end of `setUpClass`, after `cls.fake_gh.chmod(0o755)`, and continuing through `tearDownClass` into the top of `invoke_raw`, the class reads:

```python
        # The registered wrapper names the compiled policy of this host, which no
        # test may read: every invocation passes a fixture policy as a later
        # `--policy`, the built base policy plus one derived row for Nodo.
        cls.base_policy = json.loads(BASE_POLICY_PATH.read_text(encoding="utf-8"))
        cls.policy = cls.write_policy(derived_repositories={NODO: NODO_ROW}, derivation={})

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    @classmethod
    def write_policy(cls, **members):
        """A policy file: the built base policy with `members` replaced (ABSENT removes one)."""
        document = {**cls.base_policy, **members}
        document = {key: value for key, value in document.items() if value is not ABSENT}
        handle, name = tempfile.mkstemp(dir=cls.fixture_dir.name, suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream)
        return Path(name)

    def invoke_raw(self, raw, *guard_args, env=None):
        if "--policy" not in guard_args:
            guard_args = (*guard_args, "--policy", str(self.policy))
```

(the two `if "--policy" not in guard_args` lines are the only addition to `invoke_raw`; `tearDownClass` is unchanged).

(c) Immediately above `def test_hostile_interpreter_environment_is_ignored`, add:

```python
    # ------------------------------------------------------------------
    # Derived policy (issue 126): the base policy, the compiled file the hook
    # reads, and the rows a registered project is judged by.
    # ------------------------------------------------------------------

    def test_built_base_policy_holds_only_the_unregistered_literals(self):
        """R3: no hand-authored Nodo fact in the Nix source or the built base policy."""
        self.assertEqual(
            {"authorized_owners", "integration_bases", "git_bin", "gh_bin", "jq_bin",
             "derived_repositories", "derivation"}, set(self.base_policy))
        self.assertEqual(["fagenorn"], self.base_policy["authorized_owners"])
        self.assertEqual({"fagenorn/arcwave": "dev"}, self.base_policy["integration_bases"])
        self.assertEqual({}, self.base_policy["derived_repositories"])
        self.assertIsNone(self.base_policy["derivation"])
        source = Path(__file__).resolve().parents[1] / "home/common/claude-code/default.nix"
        self.assertNotIn("elevenyellow", source.read_text(encoding="utf-8"))

    def test_registered_hook_reads_the_compiled_policy(self):
        wrapper = self.guard.read_text(encoding="utf-8")
        self.assertRegex(wrapper, r'--policy /\S+/\.agents/state/guard/policy\.json "\$@"\n')
        self.assertNotIn(str(BASE_POLICY_PATH), wrapper)

    def test_base_policy_alone_loads_and_authorizes_no_nodo_verb(self):
        base = ("--gh-bin", str(self.fake_gh), "--policy", str(BASE_POLICY_PATH))
        self.assertEqual(0, self.invoke_command("true", *base).returncode)
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        refused = self.run_guard("git push -u origin topic", cwd=repo, guard_args=base)
        self.assertEqual(2, refused.returncode)
        self.assertIn(f"repository {NODO} is outside standing authorization", refused.stderr)
        allowed = self.run_guard("git push -u origin topic", cwd=repo)
        self.assertEqual(0, allowed.returncode, allowed.stderr)

    def test_derived_row_never_authorizes_its_owner_s_other_repositories(self):
        """R2, D3: the row is keyed by the exact repository."""
        sibling = self.make_repo("git@github.com:elevenyellow/other.git")
        for label, command in (
            ("push", "git push -u origin topic"),
            ("PR creation", 'gh pr create --repo elevenyellow/other --base main --head t '
                            '--title "x" --body "y"'),
            ("merge", "gh pr merge 7 --repo elevenyellow/other --merge --delete-branch"),
            ("release creation", 'gh release create v1.2.3 --repo elevenyellow/other '
                                 '--verify-tag --title "v1.2.3" --notes-file notes.md'),
        ):
            with self.subTest(verb=label):
                result = self.run_guard(command, cwd=sibling)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: unsafe {label}: repository elevenyellow/other "
                              "is outside standing authorization", result.stderr)

    def test_derived_repository_is_refused_when_origin_head_differs_from_its_row(self):
        """R6, D8: every repository-bound verb, with a reason naming both branches."""
        for live, named in (("trunk", "trunk"), (None, "no branch")):
            repo = self.make_repo(f"git@github.com:{NODO}.git", default_branch=live)
            for label, command in (
                ("push", "git push -u origin topic"),
                ("PR creation", f'gh pr create --repo {NODO} --base dev --head t '
                                '--title "x" --body "y"'),
                ("merge", f"gh pr merge 7 --repo {NODO} --merge --delete-branch"),
                ("release creation", f'gh release create v1.2.3 --repo {NODO} '
                                     '--verify-tag --title "v1.2.3" --notes-file notes.md'),
            ):
                with self.subTest(origin_head=live, verb=label):
                    result = self.run_guard(command, cwd=repo)
                    self.assertEqual(2, result.returncode, command)
                    self.assertIn(
                        f"lifecycle guard: unsafe {label}: repository {NODO}: origin/HEAD "
                        f"names {named}, its derived policy row names main", result.stderr)
            # Branch deletion is not repository-bound and stays judged on its grammar.
            self.assertEqual(0, self.run_guard("git branch -d topic", cwd=repo).returncode)

    def test_literal_owner_does_not_bypass_the_derived_row_check(self):
        """R6, D8: a derived row is checked even when the owner is a literal authorized owner."""
        slug = "fagenorn/nix-config"
        policy = self.write_policy(derivation={}, derived_repositories={
            slug: {"default_branch": "main", "integration_branch": "main", "evidence": {}}})
        self.assertIn("fagenorn", self.base_policy["authorized_owners"])
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
        repo = self.make_repo(f"git@github.com:{slug}.git", default_branch="trunk")
        for label, command in (
            ("push", "git push -u origin topic"),
            ("PR creation", f'gh pr create --repo {slug} --base trunk --head t '
                            '--title "x" --body "y"'),
            ("merge", f"gh pr merge 7 --repo {slug} --merge --delete-branch"),
        ):
            with self.subTest(verb=label):
                result = self.run_guard(command, cwd=repo, guard_args=args)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(
                    f"lifecycle guard: unsafe {label}: repository {slug}: origin/HEAD "
                    "names trunk, its derived policy row names main", result.stderr)

    def test_single_branch_derived_row_keeps_the_default_branch_only_rule(self):
        policy = self.write_policy(derivation={}, derived_repositories={
            "acme/tool": {"default_branch": "main", "integration_branch": "main",
                          "evidence": {}}})
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
        repo = self.make_repo("git@github.com:acme/tool.git")
        create = 'gh pr create --repo acme/tool --base {} --head t --title "x" --body "y"'
        self.assertEqual(
            0, self.run_guard(create.format("main"), cwd=repo, guard_args=args).returncode)
        self.assertEqual(
            2, self.run_guard(create.format("dev"), cwd=repo, guard_args=args).returncode)
        release_arm = self.run_guard(
            "gh pr merge 1 --repo acme/tool --merge", cwd=repo, guard_args=args,
            env={"FAKE_PR_MODE": "nonzero"})
        self.assertEqual(2, release_arm.returncode)
        self.assertIn("declared integration branch", release_arm.stderr)

    def test_a_policy_outside_the_schema_blocks_every_call(self):
        """R5, R6: a missing, malformed or overlapping policy refuses even `true`."""
        row = dict(NODO_ROW)
        cases = {
            "missing derivation": {"derivation": ABSENT},
            "missing derived_repositories": {"derived_repositories": ABSENT},
            "missing integration_bases": {"integration_bases": ABSENT},
            "extra member": {"grants": []},
            "derived_repositories is a list": {"derived_repositories": []},
            "derived key is not a slug": {"derived_repositories": {"nodocom": row}},
            "row is not an object": {"derived_repositories": {NODO: "dev"}},
            "row lacks evidence": {"derived_repositories": {
                NODO: {"default_branch": "main", "integration_branch": "dev"}}},
            "row has an extra member": {"derived_repositories": {NODO: {**row, "owner": "x"}}},
            "empty branch": {"derived_repositories": {NODO: {**row, "integration_branch": ""}}},
            "branch is not a ref name": {
                "derived_repositories": {NODO: {**row, "default_branch": "main; true"}}},
            "branch is not a string": {
                "derived_repositories": {NODO: {**row, "default_branch": None}}},
            "evidence is not an object": {"derived_repositories": {NODO: {**row, "evidence": []}}},
            "derivation is a list": {"derivation": []},
            "derived and literal overlap": {"integration_bases": {NODO: "dev"}},
        }
        for name, members in cases.items():
            with self.subTest(policy=name):
                members = {"derived_repositories": {NODO: row}, "derivation": {}, **members}
                result = self.invoke_command("true", "--policy", str(self.write_policy(**members)))
                self.assertEqual(2, result.returncode, name)
                self.assertIn("lifecycle guard: invalid policy:", result.stderr)
        missing = self.invoke_command(
            "true", "--policy", str(Path(self.fixture_dir.name) / "absent-policy.json"))
        self.assertEqual(2, missing.returncode)
        self.assertIn("lifecycle guard: invalid policy: cannot load", missing.stderr)
        control = self.invoke_command("true", "--policy", str(self.write_policy(
            derived_repositories={NODO: row}, derivation={})))
        self.assertEqual(0, control.returncode, control.stderr)

    def test_a_compiled_policy_round_trips_through_the_guard(self):
        """D10: the compiler's file is the guard's input, so the schema cannot drift."""
        world = GuardPolicyWorld(self)
        world.project("nodocom", NODO, integration_branch="dev", publication_free=True,
                      override=True)
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((0, [NODO]), (code, report["derived"]), stderr)
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output))
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        allowed = self.run_guard(
            f'gh pr create --repo {NODO} --base dev --head issue-7-topic '
            '--title "x" --body "y"', cwd=repo, guard_args=args)
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        sibling = self.make_repo("git@github.com:elevenyellow/other.git")
        refused = self.run_guard("git push -u origin topic", cwd=sibling, guard_args=args)
        self.assertEqual(2, refused.returncode)
        self.assertIn("outside standing authorization", refused.stderr)
```

- [ ] **Step 2: Run the suite and watch it fail**

Run the guard-suite invocation of Global Constraints on the starting commit plus the test edits.
Expected: FAIL — the build has no base policy, so `CLAUDE_GUARD_BASE_POLICY_PATH` is empty and the output ends `IsADirectoryError: [Errno 21] Is a directory: '.'`, `Ran 0 tests`, `FAILED (errors=1)`.

- [ ] **Step 3: Change the guard**

Edit `home/common/claude-code/lifecycle_guard.py` to the contract above.

- [ ] **Step 4: Change the Nix module**

In `home/common/claude-code/default.nix`:

(a) In the `let` block, beside `agentPlugins`, add `agentTools = import ../../../lib/agent-tools.nix { inherit pkgs; };`.

(b) The owner roster and its comment become:

```nix
  # The GitHub owners whose repositories carry standing authorization for the
  # guarded verbs (push, PR creation, merge, release creation) without being
  # registered projects. A registered project is not listed here: its
  # repository gets a derived row in the compiled policy, which authorizes that
  # one repository. Adding a name here hands every repository under it the
  # standing chain, so keep the list to owners whose unregistered repos we
  # ship from. Branch deletion stays guarded regardless of ownership.
  authorizedOwners = [
    "fagenorn"
  ];

  # Unregistered repositories whose integration branch is not the branch
  # origin/HEAD points at. The guard otherwise requires every guarded PR to be
  # opened against, and merged into, the default branch. A registered project
  # never gets a row here: its integration branch comes from its derived row,
  # and a repository present in both makes the compiler withhold both rows and
  # the guard refuse the policy. A repository with neither keeps the
  # default-branch-only rule, and the default branch stays acceptable
  # everywhere.
  #
```

(c) The integration-branch table and its comment become (the second and third paragraphs change only where they named Nodo):

```nix
  # Unregistered repositories whose integration branch is not the branch
  # origin/HEAD points at. The guard otherwise requires every guarded PR to be
  # opened against, and merged into, the default branch. A registered project
  # never gets a row here: its integration branch comes from its derived row,
  # and a repository present in both makes the compiler withhold both rows and
  # the guard refuse the policy. A repository with neither keeps the
  # default-branch-only rule, and the default branch stays acceptable
  # everywhere.
  #
  # Declaring a branch here widens which branch may be targeted AND waives the
  # merge's forge-protection demand for that branch: an integration branch is
  # the development-pace branch, deliberately unprotected, and its CI gate
  # lives in the shipping flow's wait-for-checks (a path-filtered CI has no
  # required status check that could report on every PR shape anyway). The
  # default branch keeps the full demand for feature merges — required status
  # checks plus enforce_admins — even if it is ever also declared here.
  #
  # Declaring a branch also opens the merge grammar's release arm: a PR whose
  # head IS the declared integration branch and whose base is the default
  # branch may be merged without `--delete-branch` (the integration branch is
  # permanent; deleting it would strand every in-flight worktree). That arm is
  # gated on the PR's own check rollup — every check completed and green — read
  # by the guard itself, in place of the forge-protection demand: the same
  # path-filtered CI means no required-status-check rule on the default branch
  # could stand in for the release PR's actual checks.
  integrationBases = {
    # arcwave is a private free-plan repository: GitHub refuses branch
    # protection there, so the default-branch merge demand can never be met.
    # Feature PRs integrate on `dev`; releases promote `dev` to `main`.
    "fagenorn/arcwave" = "dev";
  };
```

(d) Replace `lifecycleGuardPolicy` and `lifecycleGuard` with:

```nix
  # The base policy: the literal rows above and the tool paths, as one store
  # JSON file that is a valid guard policy by itself, with no derived row. The
  # wrapper's build check and the guard suite load it, and `guard-policy
  # compile` copies it into the compiled policy. The tool paths keep git, gh
  # and jq in the closure.
  lifecycleGuardBasePolicy = pkgs.writeText "claude-bash-lifecycle-guard-base-policy.json" (
    builtins.toJSON {
      authorized_owners = authorizedOwners;
      integration_bases = integrationBases;
      git_bin = "${pkgs.git}/bin/git";
      gh_bin = "${pkgs.gh}/bin/gh";
      jq_bin = "${pkgs.jq}/bin/jq";
      derived_repositories = { };
      derivation = null;
    }
  );

  # The compiled policy the registered hook reads: the base policy plus one
  # derived row per registered project, written by `claude-guard-policy`.
  lifecycleGuardPolicyPath = "${config.home.homeDirectory}/.agents/state/guard/policy.json";

  # `guard-policy compile` with the base policy and the compiled path fixed, and
  # the store git, gh and ssh first on PATH. It takes no argument; the
  # activation step below and a repair from an authenticated shell both run it.
  claudeGuardPolicy = pkgs.writeShellScriptBin "claude-guard-policy" ''
    export PATH="${
      lib.makeBinPath [
        pkgs.git
        pkgs.gh
        pkgs.openssh
      ]
    }:$PATH"
    exec ${agentTools.launchers.guard-policy} compile \
      --base ${lifecycleGuardBasePolicy} --output ${lifecycleGuardPolicyPath}
  '';

  # The registered hook: one argument-free store path. Bash's `-p` ignores
  # BASH_ENV and inherited functions, `-I` and the unset keep PYTHONPATH, user
  # site and NIX_PYTHON* `.pth` hooks out, and `exec` hands the hook's timeout
  # kill to Python. `--policy` names the compiled policy, whose path is fixed at
  # evaluation time. The check runs the guard against the base policy, so the
  # build refuses a guard source or a base policy that cannot load.
  lifecycleGuard = pkgs.writeTextFile {
    name = "claude-bash-lifecycle-guard";
    executable = true;
    destination = "/bin/claude-bash-lifecycle-guard";
    text = ''
      #!${pkgs.runtimeShell} -p
      unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
      exec ${pkgs.python3}/bin/python3 -I ${./lifecycle_guard.py} --policy ${lifecycleGuardPolicyPath} "$@"
    '';
    checkPhase = ''
      if ! printf '%s' '{"tool_name":"Bash","tool_input":{"command":"true"}}' \
        | "$target" --policy ${lifecycleGuardBasePolicy}; then
        echo "claude-bash-lifecycle-guard: refused a harmless Bash payload" >&2
        exit 1
      fi
    '';
  };
```

(e) Add `claudeGuardPolicy` to `home.packages` after `lifecycleGuard`.

(f) Immediately above `home.activation.claudeCodeSettings`, add:

```nix
  # Compile the guard policy the registered hook reads, on every switch. It runs
  # after linkGeneration because the compiler loads the platform manifest from
  # ~/.agents/share, and before the settings copy. It never aborts the switch:
  # exit 1 leaves a policy without the refused projects' rows, and any other
  # failure leaves no policy file, which makes the hook block every Bash call.
  home.activation.claudeGuardPolicy =
    lib.hm.dag.entryBetween [ "claudeCodeSettings" ] [ "writeBoundary" "linkGeneration" ]
      ''
        guardPolicyStatus=0
        run ${claudeGuardPolicy}/bin/claude-guard-policy >/dev/null || guardPolicyStatus=$?
        if [ "$guardPolicyStatus" -eq 1 ]; then
          echo "claude-guard-policy: the projects named above have no derived guard row; rerun claude-guard-policy from an authenticated shell" >&2
        elif [ "$guardPolicyStatus" -ne 0 ]; then
          run rm -f ${lifecycleGuardPolicyPath}
          echo "claude-guard-policy: no guard policy was written (exit $guardPolicyStatus), so the lifecycle guard blocks every Bash call; rerun claude-guard-policy from an authenticated shell" >&2
        fi
      '';
```

Each comment above was checked against a built prototype; if the implemented code differs from a comment, rewrite the comment from the code.

- [ ] **Step 5: Verify**

Run the guard-suite invocation of Global Constraints (it builds first).
Expected: `Ran 59 tests` and `OK` (the 51 at base plus the 8 added).

Run, as one script:

```bash
set -e
if git grep -q elevenyellow -- home/common/claude-code/default.nix; then exit 1; fi
if ! grep -q 'derived_repositories' home/common/claude-code/lifecycle_guard.py; then exit 1; fi
if grep -n "agent_tools\|importlib\|__file__" home/common/claude-code/lifecycle_guard.py; then exit 1; fi
if [ "$(git diff --numstat 450f1de3627b -- tests/test_claude_permission_guard.py | cut -f2)" != 0 ]; then exit 1; fi
REQ=$(nix-store --query --requisites ./result)
ACTIVATE=$(printf '%s\n' "$REQ" | grep -- '-home-manager-generation$')/activate
order=$(grep -o '"Activating %s" "\(linkGeneration\|claudeGuardPolicy\|claudeCodeSettings\)"' "$ACTIVATE" | cut -d'"' -f4 | tr '\n' ' ')
if [ "$order" != "linkGeneration claudeGuardPolicy claudeCodeSettings " ]; then echo "order: $order"; exit 1; fi
POLICY=$(printf '%s\n' "$REQ" | grep -- '-claude-guard-policy$')/bin/claude-guard-policy
if ! grep -q -- '-claude-bash-lifecycle-guard-base-policy.json --output /.*/.agents/state/guard/policy.json$' "$POLICY"; then exit 1; fi
env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -1
```

Expected: exit 0 and a last line `OK`. At the task's starting commit the first check exits 1. Read `$POLICY` and `$ACTIVATE`; do **not** execute either (Global Constraints).

After committing, run the half-wired gate of Global Constraints. Expected: exit 0, no `half-wired` line.

- [ ] **Step 6: Commit (one commit)**

```bash
git add home/common/claude-code/lifecycle_guard.py home/common/claude-code/default.nix tests/test_claude_permission_guard.py
```

Commit through `launch-commit` with the message `feat(claude-code): the lifecycle guard reads a compiled policy and Nodo's literals are derived (issue 126)`. A review fix-up to this task amends nothing: it is a new commit that keeps both gates green.
