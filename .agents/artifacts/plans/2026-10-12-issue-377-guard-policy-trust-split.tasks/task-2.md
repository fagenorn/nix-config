# Task 2: Trust split — five-member base, two-member compiled policy, the bad-file rule

Spec sections 1, 2 (without `--derive-bin`), 3 "Guard" steps 1–2, 4 and 5 (per D1, D4, D5, D11). One commit: the guard, the compiler, the Nix base policy and wrapper, and both suites change together, because a seven-member base or compiled file is outside the other side's schema after this task. The row check is Task 3; until then a well-formed compiled row is used without a recheck, as on `main` (D11).

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Modify: `home/common/claude-code/default.nix`
- Test: `tests/test_claude_permission_guard.py`
- Modify: `python/agent_tools/guard_policy.py`
- Modify: `tests/guard_policy_world.py`
- Test: `tests/test_guard_policy.py`
- Modify: `python/README.md` (§ guard-policy)

**Interfaces:**
- Consumes (Task 1): `guard_policy._admit(proven, literal_slugs)`, `guard_policy.derive_repository`.
- Produces (Task 3 relies on these exact names):
  - Guard: `BASE_POLICY_KEYS` (the five trusted members), `COMPILED_POLICY_KEYS` (`derived_repositories`, `derivation`); `class BasePolicy` with attributes `authorized_owners` (frozenset), `integration_bases` (dict), `git_bin`, `gh_bin`, `jq_bin`; `load_base_policy(path) -> (BasePolicy | None, reason | None)`; `load_compiled_policy(path) -> (rows: dict, reason | None)`, which on any failure returns `({}, reason)`; `Context(args, base, cwd)` with attributes `repository`, `base_branch`, `derived_row` (dict or None), `compiled_problem` (str or None), `row_problem` (str or None), `integration_bases`; `ownership_problem(context)`.
  - Guard argv: `--base-policy` (required), `--policy` (required, the compiled policy), the existing `--git-bin`, `--gh-bin`, `--jq-bin`, `--child-timeout-seconds`.
  - Compiler: `POLICY_MEMBERS = ("derived_repositories", "derivation")`, `DERIVATION_SCHEMA_VERSION = 2`, `compile_policy(base, entries) -> tuple[dict[str, dict], list[dict]]` (rows, refusals).
  - Guard suite: `write_policy(**members)` writes a compiled policy starting from `{"derived_repositories": {}, "derivation": None}`; `write_base(**members)` writes the built base policy with `members` replaced; both drop a member given as `ABSENT`; `invoke_raw(raw, *guard_args, env=None, timeout=5)` appends `--base-policy <BASE_POLICY_PATH>` and `--policy <cls.policy>` when absent from `guard_args`.

**Invariants:**
- `main` loads only the base policy, right after the detaching-word check; a base policy that is missing, unreadable, not JSON or outside its closed five-key schema (or with a bad member value) blocks every call with `invalid policy: <reason>`.
- The compiled policy is opened only in `Context.__init__`, so a command with no push, PR creation, merge or release creation never opens it.
- A compiled policy that is missing, unreadable, a directory, not JSON, outside its closed two-key schema, or that carries any malformed row contributes no row at all (`({}, reason)`), never blocks by itself, and is never partially read. Row validation is today's: slug key, exactly `default_branch`, `integration_branch`, `evidence`, ref-name branches, object `evidence`; `derivation` null or object.
- No value from the compiled policy other than a validated row's two branches reaches any decision; `git_bin`, `gh_bin`, `jq_bin` come from `--git-bin`/`--gh-bin`/`--jq-bin` or the base policy only.
- For a repository with a row: if it is a key of the base `integration_bases`, the row problem is the literal conflict; else if `origin/HEAD` does not name the row's `default_branch`, it is today's message. Only a row with no problem adds its `integration_branch` to `integration_bases`.
- Messages, verbatim (tests pin them):
  - literal conflict: `repository {S} has both a literal integration base and a derived policy row; repair: run claude-guard-policy`
  - no row, owner not literal, compiled problem present: `repository {S} is outside standing authorization; the compiled policy contributed no row: {reason}; repair: run claude-guard-policy`
  - no row, owner not literal, no compiled problem: `repository {S} is outside standing authorization` (unchanged)
  - origin/HEAD mismatch: unchanged.
- The compiler's base policy has exactly the five trusted members; its output has exactly `derived_repositories` and `derivation` (with `derivation.schema_version` 2); a `literal_conflict` project gets no row and the literal stays in the base.

- [ ] **Step 1: Write the failing tests**

Guard suite, `tests/test_claude_permission_guard.py`:

(a) Harness. `write_policy` becomes:

```python
    @classmethod
    def write_policy(cls, **members):
        """A compiled policy file: no rows and a null derivation, `members` replaced
        (ABSENT removes one)."""
        return cls._write_fixture({"derived_repositories": {}, "derivation": None, **members})

    @classmethod
    def write_base(cls, **members):
        """A base policy file: the built base policy with `members` replaced (ABSENT removes one)."""
        return cls._write_fixture({**cls.base_policy, **members})

    @classmethod
    def _write_fixture(cls, document):
        document = {key: value for key, value in document.items() if value is not ABSENT}
        handle, name = tempfile.mkstemp(dir=cls.fixture_dir.name, suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream)
        return Path(name)
```

and `invoke_raw` becomes:

```python
    def invoke_raw(self, raw, *guard_args, env=None, timeout=5):
        if "--base-policy" not in guard_args:
            guard_args = (*guard_args, "--base-policy", str(BASE_POLICY_PATH))
        if "--policy" not in guard_args:
            guard_args = (*guard_args, "--policy", str(self.policy))
        child_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
        child_env.update(env or {})
        return subprocess.run(
            [self.guard, *guard_args], input=raw, text=True, capture_output=True,
            timeout=timeout, check=False, env=child_env,
        )
```

Update the setUpClass comment above `cls.base_policy` to say every invocation passes the built base policy and a fixture compiled policy (`cls.policy`, one row for Nodo) as later arguments.

(b) In `test_detaching_refusal_precedes_the_push_grammar`, `bad_policy` becomes `("--base-policy", "/nonexistent/lifecycle-guard-base-policy.json")` and its comment says the check runs before the base policy loads.

(c) In `test_base_policy_alone_loads_and_authorizes_no_nodo_verb`, `base` becomes `("--gh-bin", str(self.fake_gh), "--policy", str(self.write_policy()))`.

(d) Delete `test_built_base_policy_holds_only_the_unregistered_literals`, `test_registered_hook_reads_the_compiled_policy`, `test_a_policy_outside_the_schema_blocks_every_call` and `test_a_policy_path_that_is_no_readable_file_blocks_every_call`; their cases move into the tests below. Add, in the derived-policy block, retitling its banner comment to "Policy trust split (issue 377) and derived rows (issue 126)":

```python
    COMPILED_ROW_SHAPES = {
        "derived_repositories is a list": {"derived_repositories": []},
        "derived key is not a slug": {"derived_repositories": {"nodocom": NODO_ROW}},
        "row is not an object": {"derived_repositories": {NODO: "dev"}},
        "row lacks evidence": {"derived_repositories": {
            NODO: {"default_branch": "main", "integration_branch": "dev"}}},
        "row has an extra member": {"derived_repositories": {NODO: {**NODO_ROW, "owner": "x"}}},
        "empty branch": {"derived_repositories": {NODO: {**NODO_ROW, "integration_branch": ""}}},
        "branch is not a ref name": {
            "derived_repositories": {NODO: {**NODO_ROW, "default_branch": "main; true"}}},
        "branch is not a string": {"derived_repositories": {NODO: {**NODO_ROW, "default_branch": None}}},
        "evidence is not an object": {"derived_repositories": {NODO: {**NODO_ROW, "evidence": []}}},
        "derivation is a list": {"derived_repositories": {NODO: NODO_ROW}, "derivation": []},
        "missing derivation": {"derived_repositories": {NODO: NODO_ROW}, "derivation": ABSENT},
        "an extra member": {"derived_repositories": {NODO: NODO_ROW}, "grants": []},
    }

    def test_built_base_policy_holds_exactly_the_five_trusted_members(self):
        """Issue 377 R1, R5: the store file holds the trusted members and the #375 literals."""
        self.assertEqual({"authorized_owners", "integration_bases", "git_bin", "gh_bin", "jq_bin"},
                         set(self.base_policy))
        self.assertEqual(["fagenorn"], self.base_policy["authorized_owners"])
        self.assertEqual({"fagenorn/arcwave": "dev"}, self.base_policy["integration_bases"])
        for member, name in (("git_bin", "git"), ("gh_bin", "gh"), ("jq_bin", "jq")):
            self.assertRegex(self.base_policy[member], rf"^/nix/store/[^/]+/bin/{name}$")
        source = Path(__file__).resolve().parents[1] / "home/common/claude-code/default.nix"
        self.assertNotIn("elevenyellow", source.read_text(encoding="utf-8"))

    def test_registered_hook_names_the_base_and_compiled_policies(self):
        wrapper = self.guard.read_text(encoding="utf-8")
        self.assertRegex(wrapper, r'--base-policy /nix/store/\S+-claude-bash-lifecycle-guard-'
                                  r'base-policy\.json --policy /\S+/\.agents/state/guard/'
                                  r'policy\.json "\$@"\n')
        self.assertIn(f"--base-policy {BASE_POLICY_PATH} ", wrapper)

    def test_a_compiled_policy_cannot_add_an_owner(self):
        """Issue 377 criterion 1, R1: an owner in the compiled policy grants nothing."""
        repo = self.make_repo("git@github.com:intruder/tool.git")
        for name, policy in (
            ("beside the rows", self.write_policy(authorized_owners=["intruder"])),
            ("as the seven-member shape", self.write_policy(
                **{**self.base_policy, "authorized_owners": ["fagenorn", "intruder"]})),
        ):
            args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
            for label, command in (
                ("push", "git push -u origin topic"),
                ("PR creation", 'gh pr create --repo intruder/tool --base main --head t '
                                '--title "x" --body "y"'),
                ("merge", "gh pr merge 7 --repo intruder/tool --merge --delete-branch"),
                ("release creation", 'gh release create v1.2.3 --repo intruder/tool '
                                     '--verify-tag --title "v1.2.3" --notes-file notes.md'),
            ):
                with self.subTest(policy=name, verb=label):
                    result = self.run_guard(command, cwd=repo, guard_args=args)
                    self.assertEqual(2, result.returncode, command)
                    self.assertIn(f"lifecycle guard: unsafe {label}: repository intruder/tool "
                                  "is outside standing authorization", result.stderr)

    def test_a_compiled_policy_cannot_substitute_the_tools(self):
        """Issue 377 criterion 2, R1: no program the compiled policy names is ever run.

        The fake `gh` comes from a fixture base policy, never `--gh-bin`: an override
        takes precedence over every policy value, so it would hide a guard that took
        `gh_bin` from the compiled policy."""
        base = self.write_base(gh_bin=str(self.fake_gh))
        markers = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        tools = {}
        for member in ("git_bin", "gh_bin", "jq_bin"):
            tool = markers / member
            tool.write_text(f"#!/bin/sh\ntouch {markers / (member + '.ran')}\nexit 0\n",
                            encoding="utf-8")
            tool.chmod(0o755)
            tools[member] = str(tool)
        tampered = self.write_policy(derived_repositories={NODO: NODO_ROW}, derivation={},
                                     **tools)
        repo = self.make_repo("git@github.com:fagenorn/tool.git")
        for command in ("git push -u origin topic",
                        "gh pr merge 7 --repo fagenorn/tool --merge --delete-branch"):
            with self.subTest(command=command):
                untampered = self.run_guard(command, cwd=repo,
                                            guard_args=("--base-policy", str(base)))
                self.assertEqual(0, untampered.returncode, untampered.stderr)
                result = self.run_guard(command, cwd=repo, guard_args=(
                    "--base-policy", str(base), "--policy", str(tampered)))
                self.assertEqual((0, untampered.stderr), (result.returncode, result.stderr))
        self.assertEqual([], sorted(path.name for path in markers.glob("*.ran")))

    def test_a_row_beside_a_literal_integration_base_is_refused(self):
        """Issue 377 D5: the compiled policy cannot recast a literal repository."""
        slug = "fagenorn/arcwave"
        self.assertEqual("dev", self.base_policy["integration_bases"][slug])
        policy = self.write_policy(derivation={}, derived_repositories={
            slug: {"default_branch": "main", "integration_branch": "release", "evidence": {}}})
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
        repo = self.make_repo(f"git@github.com:{slug}.git")
        for label, command in (
            ("push", "git push -u origin topic"),
            ("PR creation", f'gh pr create --repo {slug} --base release --head t '
                            '--title "x" --body "y"'),
            ("merge", f"gh pr merge 7 --repo {slug} --merge --delete-branch"),
        ):
            with self.subTest(verb=label):
                result = self.run_guard(command, cwd=repo, guard_args=args)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(
                    f"lifecycle guard: unsafe {label}: repository {slug} has both a literal "
                    "integration base and a derived policy row; repair: run claude-guard-policy",
                    result.stderr)
        self.assertEqual(0, self.run_guard("git push -u origin topic", cwd=repo).returncode)

    def test_a_bad_compiled_policy_contributes_no_row(self):
        """Issue 377 D4, R4: the whole file is dropped and nothing the base allows is blocked."""
        fixtures = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        (fixtures / "directory").mkdir()
        (fixtures / "not-json.json").write_text("{", encoding="utf-8")
        unreadable = self.write_policy(derived_repositories={NODO: NODO_ROW}, derivation={})
        unreadable.chmod(0)
        shapes = {
            "missing": fixtures / "absent.json",
            "a directory": fixtures / "directory",
            "unreadable": unreadable,
            "not JSON": fixtures / "not-json.json",
            "the seven-member shape": self.write_policy(
                **{**self.base_policy, "derived_repositories": {NODO: NODO_ROW},
                   "derivation": {}}),
            **{name: self.write_policy(**members)
               for name, members in self.COMPILED_ROW_SHAPES.items()},
        }
        literal = self.make_repo("git@github.com:fagenorn/tool.git")
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        for name, path in shapes.items():
            with self.subTest(policy=name):
                args = ("--gh-bin", str(self.fake_gh), "--policy", str(path))
                self.assertEqual(0, self.invoke_command("true", *args).returncode)
                allowed = self.run_guard("git push -u origin topic", cwd=literal, guard_args=args)
                self.assertEqual(0, allowed.returncode, allowed.stderr)
                refused = self.run_guard("git push -u origin topic", cwd=nodo, guard_args=args)
                self.assertEqual(2, refused.returncode)
                self.assertIn(f"lifecycle guard: unsafe push: repository {NODO} is outside "
                              "standing authorization; the compiled policy contributed no row: ",
                              refused.stderr)
                self.assertIn("; repair: run claude-guard-policy", refused.stderr)
        control = self.run_guard("git push -u origin topic", cwd=nodo)
        self.assertEqual(0, control.returncode, control.stderr)

    def test_a_bad_base_policy_blocks_every_call(self):
        """Issue 377 R4: the store file is an installation defect, so even `true` is refused."""
        fixtures = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        (fixtures / "not-json.json").write_text("{", encoding="utf-8")
        unreadable = self.write_base()
        unreadable.chmod(0)
        shapes = {
            "missing": fixtures / "absent.json",
            "a directory": fixtures,
            "unreadable": unreadable,
            "not JSON": fixtures / "not-json.json",
            "a missing member": self.write_base(jq_bin=ABSENT),
            "an extra member": self.write_base(grants=[]),
            "the #375 seven-member shape": self.write_base(derived_repositories={},
                                                           derivation=None),
            "owners is not a list": self.write_base(authorized_owners="fagenorn"),
            "an empty integration base": self.write_base(integration_bases={"a/b": ""}),
            "a relative tool": self.write_base(git_bin="git"),
        }
        for name, path in shapes.items():
            with self.subTest(base=name):
                result = self.invoke_command("true", "--base-policy", str(path))
                self.assertEqual(2, result.returncode, name)
                self.assertIn("lifecycle guard: invalid policy:", result.stderr)
        control = self.invoke_command("true", "--base-policy", str(self.write_base()))
        self.assertEqual(0, control.returncode, control.stderr)

    def test_a_command_with_no_repository_bound_verb_never_opens_the_compiled_policy(self):
        """Issue 377 section 4. Opening a FIFO that has no writer blocks, so an open would
        surface here as the five-second invocation timeout."""
        fifo = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "policy.json"
        os.mkfifo(fifo)
        repo = self.make_repo("https://github.com/fagenorn/argus.git")
        for command, status in (("true", 0), ("git branch -d issue-30-safe", 0),
                                ("setsid x", 2)):
            with self.subTest(command=command):
                result = self.invoke_command_in(command, repo, "--policy", str(fifo))
                self.assertEqual(status, result.returncode, result.stderr)
```

Compiler suite, `tests/test_guard_policy.py` and `tests/guard_policy_world.py`:

(e) `GuardPolicyWorld.write_base` drops `"derived_repositories": {}` and `"derivation": None` from its default document.

(f) In `test_a_nodo_shaped_and_a_single_branch_project_both_derive`, replace the `set(policy)` assertion and the `for member in guard_policy.BASE_MEMBERS` loop (with the `base = …` line) by:

```python
        self.assertEqual(set(policy), {"derived_repositories", "derivation"})
        self.assertEqual(set(guard_policy.POLICY_MEMBERS), set(policy))
```

and `self.assertEqual(derivation["schema_version"], 1)` by `… 2)`.

(g) In `test_an_absent_registry_is_the_empty_fleet`, replace the `integration_bases` and `authorized_owners` assertions by `self.assertEqual(set(policy), {"derived_repositories", "derivation"})`.

(h) Replace `test_literal_conflict_withholds_both_rows` and `test_an_unsupported_name_does_not_keep_its_literal_row` by:

```python
    def test_literal_conflict_withholds_the_derived_row_only(self):
        """Issue 377 D5: the compiled policy cannot subtract a store literal."""
        self.world.write_base(integration_bases={"fagenorn/one": "dev",
                                                 "fagenorn/arcwave": "dev"})
        self.world.project("fixture/one", "fagenorn/one")
        self.refused("literal_conflict")
        self.assertEqual(self.world.policy()["derived_repositories"], {})
        self.assertNotIn("integration_bases", self.world.policy())

    def test_literal_conflict_is_judged_before_the_name(self):
        self.world.write_base(integration_bases={"fagenorn/one": "dev"})
        self.world.project("fixture/one", "fagenorn/one", integration_branch="dev+ci")
        self.refused("literal_conflict")
```

(i) In `test_an_unusable_base_policy`, add the case `"the #375 seven-member shape": {**valid, "derived_repositories": {}, "derivation": None},`.

- [ ] **Step 2: Run the suites and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -4`
Expected: FAIL — `test_a_nodo_shaped_and_a_single_branch_project_both_derive` (seven members written) and `test_literal_conflict_withholds_the_derived_row_only` among the failures; `FAILED`.

Run the guard-suite invocation (Global Constraints) with `git add` of the test edits.
Expected: FAIL — `test_built_base_policy_holds_exactly_the_five_trusted_members`, `test_registered_hook_names_the_base_and_compiled_policies`, `test_a_bad_compiled_policy_contributes_no_row` and `test_a_compiled_policy_cannot_add_an_owner` (the seven-member shape loads at base) among the failures; the output ends in `FAILED`.

- [ ] **Step 3: Write the minimal implementation**

`home/common/claude-code/lifecycle_guard.py`, to the interfaces, invariants and messages above:
- Replace `POLICY_KEYS`, `Policy` and `load_policy` with `BASE_POLICY_KEYS`, `COMPILED_POLICY_KEYS`, `BasePolicy`, `load_base_policy` and `load_compiled_policy`; reuse today's member checks and reason texts, the key-set reason naming each file's own sorted keys. The literal/derived overlap check leaves the loader.
- `main`: `--base-policy` required, `--policy` required; load the base policy where `load_policy` is called today; the tool fallbacks read the base policy; pass the base policy to `Context`.
- `Context.__init__`: after `repository` and `base_branch`, call `load_compiled_policy(args.policy)`, keep its reason as `compiled_problem`, take `derived_row`, compute `row_problem` (literal conflict first, then the existing `origin/HEAD` check), and add the row's integration branch to `integration_bases` only when `row_problem` is None.
- `ownership_problem`: a row returns `row_problem`; no row keeps the owner check and appends the compiled reason in the message above.
- Module docstring and the `BasePolicy` / loader docstrings: the wrapper passes `--base-policy` (store) and `--policy` (compiled path); a later occurrence replaces the wrapper's, which is how a test loads fixtures; written from the code.

`home/common/claude-code/default.nix`:
- `lifecycleGuardBasePolicy` drops `derived_repositories` and `derivation`; its comment says it holds the five trusted members, is the only place the guard reads them from, and is copied by no one (the compiler only validates it).
- The wrapper's `exec` line becomes `… -I ${./lifecycle_guard.py} --base-policy ${lifecycleGuardBasePolicy} --policy ${lifecycleGuardPolicyPath} "$@"`; the `checkPhase` pipes the harmless payload into `"$target"` with no argument. Rewrite the comment above `lifecycleGuard` from that code (the check loads the base policy; the compiled path is not opened for a payload with no repository-bound verb).
- `lifecycleGuardPolicyPath`'s comment: derived rows only. In the `integrationBases` comment, "a repository present in both makes the compiler withhold both rows and the guard refuse the policy" becomes: the compiler refuses that project its derived row (`literal_conflict`), the literal row stays in the base policy, and the guard refuses the guarded verbs of a repository that has both a literal row and a compiled row.
- `home.activation.claudeGuardPolicy`: the comment and the two messages of the non-1 branch say that registered projects then lose their derived guard row, and with it their derived integration branch, so only a repository that relies on a derived row for its authorization is refused until `claude-guard-policy` succeeds, while authorization from the base policy (an authorized owner or a literal integration row) still applies; they no longer say that every Bash call is blocked. The second message keeps "could not be removed" and says the hook reads whatever rows are there. Status 1's message and the removal itself are unchanged.

`python/agent_tools/guard_policy.py`: `POLICY_MEMBERS`, `DERIVATION_SCHEMA_VERSION = 2`, `read_base` demanding exactly `BASE_MEMBERS` (drop the compiled-policy check), `compile_policy` returning `(rows, refusals)` with no `integration_bases` stripping, `_write` writing `{"derived_repositories": rows, "derivation": {...}}`. Rewrite the module docstring's second paragraph and the comment above `GUARD_SLUG` (a row outside these shapes makes the guard drop the whole compiled policy) from the code.

`python/README.md` § guard-policy: the base policy has exactly the five trusted members; `compile` writes `derived_repositories` and `derivation` only (`derivation.schema_version` 2); a `literal_conflict` project gets no row and the literal row stays in the base policy (issue 377 D5), so the closing sentence about removing derived slugs from the written `integration_bases` goes; the lifecycle guard reads its trusted members from the base policy only. In the `name_unsupported` sentence, the guard's `load_policy` becomes `load_compiled_policy`, and "the guard refuses the whole policy over one such row, which would block every Bash call" becomes that the guard drops the whole compiled policy over one such row, which removes every derived row and blocks nothing the base policy allows (issue 377 D4).

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -4`
Expected: PASS — `OK`.

Run the guard-suite invocation.
Expected: PASS — `OK`, exit 0 (`just build` included: the wrapper's check passed as registered).

Run:

```bash
set -e
f=home/common/claude-code/lifecycle_guard.py
if grep -qE '^POLICY_KEYS = |^class Policy[:(]|^def load_policy\(' "$f"; then exit 1; fi
grep -q '^BASE_POLICY_KEYS = ' "$f"
grep -q '^def load_compiled_policy(' "$f"
if grep -q 'derived_repositories = { };' home/common/claude-code/default.nix; then exit 1; fi
if grep -qE 'blocks? every (Bash )?call' home/common/claude-code/default.nix; then exit 1; fi
if grep -q 'withhold both rows' home/common/claude-code/default.nix; then exit 1; fi
if grep -qE '`load_policy`|block every Bash call' python/README.md; then exit 1; fi
echo SPLIT
```

Expected: `SPLIT`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py home/common/claude-code/default.nix \
  tests/test_claude_permission_guard.py python/agent_tools/guard_policy.py \
  tests/guard_policy_world.py tests/test_guard_policy.py python/README.md
launch-commit … -- -m "feat(guard): trusted members come only from the store base policy (#377)"
```
