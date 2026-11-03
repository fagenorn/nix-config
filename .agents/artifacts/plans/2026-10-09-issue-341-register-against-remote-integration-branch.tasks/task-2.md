# Task 2: Register from the fetched remote default branch

Spec: `.agents/artifacts/specs/2026-10-09-issue-341-register-against-remote-integration-branch-design.md`, `## Solution` steps 1–7 (D2–D7, D9, D11). This task implements every step except the step-4 hop: when the contract at the remote default `D` names a different branch `B`, it refuses `integration_branch_unresolved`. Task 3 replaces that refusal with the hop.

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py`
- Modify: `python/agent_tools/adopt_verify.py`
- Modify: `python/agent_tools/adopt_project.py` (`command_verify` only)
- Test: `home/common/agent-skills/tests/test_adopt_verify.py`

**Interfaces:**
- Consumes (Task 1): `VerificationSource(ref, commit, resolver_root, inventory, branch=None)`, `head_source(root)`, `verify_repository(root, source, run_resolver)`, `Verification(report, resolve_payload, source, evidence_candidates)`, `integration_branch(payload) -> str | None`.
- Produces, in `adopt_inspection`:
  - `REMOTE = "origin"`.
  - `run_git(root: Path, *args: str, network: bool = False) -> tuple[int, bytes]` — when `network`, the child env is `{**os.environ, "GIT_TERMINAL_PROMPT": "0"}`; otherwise unchanged (inherits). Same 300 s timeout and `adopt.git.unavailable` refusal.
  - `tree_inventory(root: Path, revision: str) -> list[tuple[str, str]]` — `git_or_fail(root, "ls-tree", "-r", "-z", revision)`; each NUL record is `<mode> <type> <object>\t<path>`; returns sorted `(path, object)` pairs, the same shape `tracked_inventory` returns. A record without a tab-separated path or without exactly three head fields refuses `adopt_failure`/`adopt.git.unparseable_tree`.
  - `has_remote(root: Path) -> bool` — `REMOTE in git_or_fail(root, "remote").decode("utf-8", "surrogateescape").split()`.
  - `@dataclass(frozen=True) class RemoteHeads` with `default: str | None` and `branches: frozenset[str]`.
  - `remote_heads(root: Path) -> RemoteHeads` — one `run_git(root, "ls-remote", "--symref", REMOTE, "HEAD", "refs/heads/*", network=True)`. Non-zero exit refuses `adopt_failure`/`adopt.git.remote_unreachable`. Parse each line by its first tab: `ref: refs/heads/X` with name `HEAD` gives the symref target `X`; a name starting `refs/heads/` adds its suffix to `branches`. `default` is `X` only when `X` is in `branches`, else `None`.
  - `fetch_pinned(root: Path, branch: str) -> str` — `run_git(root, "fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--no-auto-maintenance", "--no-recurse-submodules", "--refmap=", REMOTE, f"+refs/heads/{branch}:refs/remotes/{REMOTE}/{branch}", network=True)` (D4, D11), then `run_git(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/{REMOTE}/{branch}^{{commit}}")`. Either non-zero refuses `adopt_failure`/`adopt.git.fetch_failed`. Returns the stripped 40-hex id.
  - `export_commit(root: Path, commit: str, destination: Path) -> None` — `destination` must not exist. `git archive -o <destination>.tar <commit>`, then `destination.mkdir()` and `tarfile.open(...).extractall(destination, filter="data")`, the `adopt_apply.gate_cold_clone_resolves` precedent (D5). A non-zero archive, `tarfile.TarError` or `OSError` refuses `adopt_failure`/`adopt.git.export_failed`.
- Produces, in `adopt_verify`:
  - `remote_source(root: Path, run_resolver: Resolver) -> contextlib.AbstractContextManager[VerificationSource]` (a `@contextlib.contextmanager` generator).
  - `require_integrated(verification: Verification) -> None`.
  - `register_project(root, verification)` keeps its signature; its inner checks change (below).

**Invariants:**
- `remote_source` order: no `origin` → `not_integrated`/`adopt.registration.no_remote`; `remote_heads`; `default is None` → `not_integrated`/`adopt.registration.remote_default_unknown`; then inside one `tempfile.TemporaryDirectory()`: `R = fetch_pinned(root, D)`, `export_commit(root, R, scratch/"default")`, `run_resolver(scratch/"default", "resolve")`. If it exits non-zero, or `integration_branch(payload)` is `None` or equals `D`, yield `VerificationSource(ref=f"refs/remotes/origin/{D}", commit=R, resolver_root=scratch/"default", inventory=tree_inventory(root, R), branch=D)`. Otherwise refuse `not_integrated`/`adopt.registration.integration_branch_unresolved` (Task 3 replaces this refusal).
- The temporary directory is removed on success and on every refusal (the `with` block encloses the `yield`).
- `require_integrated`: `verification.evidence_candidates == []` refuses `not_integrated`/`adopt.registration.not_integrated` (D7). Called only under `--register`, before `registration_allowed`.
- `register_project` inner checks, in this order, before the registry transaction (which is unchanged): missing project id, adoption commit or contract branch → existing `adopt.registration.incomplete`; `verification.source.branch is None` or the contract's `integration_branch(verification.resolve_payload) != verification.source.branch` → `not_integrated`/`adopt.registration.integration_branch_unresolved`; `not commit_is_ancestor(root, adoption_commit, verification.source.commit)` → `not_integrated`/`adopt.registration.not_integrated` (D7: the pinned id, never a branch name).
- The only repository writes under `--register` are `refs/remotes/origin/<branch>` and fetched objects: local branches, index, working tree, untracked files and `.git/FETCH_HEAD` are untouched (spec Out of scope, D11).
- Plain `verify` is unchanged by this task.
- `adopt_inspection`'s module docstring sentence "and nothing that writes" becomes true again: say that its one repository write is `fetch_pinned`'s update of one `refs/remotes/origin/<branch>` ref, and `export_commit` writes only into the directory its caller names. The module's opening "bounded, read-only inspection" line and the `# Git, as a child process` section comment's "Every query below is read-only" are corrected the same way (PR-04): every query is read-only except `fetch_pinned`'s one remote-tracking ref update.

- [ ] **Step 1: Write the failing tests**

In `test_adopt_verify.py`: add `from unittest import mock`, `from agent_tools import adopt_verify` and `from agent_tools.adopt_inspection import AdoptError`, and these helpers beside `verifiable_repo`:

```python
def publish(root: Path, refs: tuple[str, ...] = ("main",), *,
            default: str = "main") -> Path:
    """A local bare `origin` holding `refs`, its `HEAD` naming `default`.

    Each entry is `src` (pushed to the same-named branch) or `src:branch`,
    where `src` is any local revision. `origin` is re-pointed when it exists:
    plan identity derives from the GitHub URL the fixtures add (#148 D35), so
    it is re-pointed only after `plan`/`apply`.
    """
    bare = Path(tempfile.mkdtemp()).resolve() / "origin.git"
    git(bare.parent, "init", "--quiet", "--bare", "-b", default, str(bare))
    verb = "set-url" if "origin" in git(root, "remote").split() else "add"
    git(root, "remote", verb, "origin", str(bare))
    specs = []
    for ref in refs:
        src, _, branch = ref.partition(":")
        specs.append(f"{src}:refs/heads/{branch or src}")
    git(root, "push", "--quiet", "origin", *specs)
    return bare
```

In `verifiable_repo`, before the first `commit(root)`, add:

```python
    # A cold export carries tracked files only: an empty standards directory
    # would read as a missing knowledge path under `--register`.
    for standards in contract["bindings"]["paths"]["standards"]:
        write(root, f"{standards}/bar.md", "# the bar\n")
```

Migrate `RegistrationTest`:
- Delete `test_an_unintegrated_adoption_commit_refuses_not_integrated` (replaced by the apply-branch case below).
- `test_registration_after_the_merge_writes_exactly_two_members`: call `publish(root)` after the `merge`, and add `self.assertEqual(report["revision"]["ref"], "refs/remotes/origin/main")`.
- `test_a_merged_readoption_is_still_adopted_and_registers`: call `publish(root)` after the second `merge`.
- `test_a_second_identical_registration_is_byte_identical`, `test_two_projects_are_stored_ordered_by_project_id`, `test_two_concurrent_registrations_both_survive`, `test_the_resolver_lists_the_registered_project_as_compatible`: call `publish(<each root>)` right after each `verifiable_repo(...)`.
- `test_the_same_id_at_another_root_refuses_and_changes_nothing`: `publish(root)` and `publish(other)`.
- `test_registration_needs_a_conformant_checkout`: after `write(root, "AGENTS.md", "hand-edited\n")` add `commit(root, "drift a projection")` and `publish(root)`; assertions unchanged.

Add (import `init_repo`, `scaffold`, `fixture_contract`, `tree_snapshot` from `.test_adopt_project` as already imported):

```python
class RemoteRegistrationTest(VerifyTestCase):
    def refuse_with(self, root: Path, code: str, repair_id: str) -> None:
        payload = self.refuse(root, code, "--register")
        self.assertEqual(payload["error"]["repair_id"], repair_id, payload)
        self.assertFalse(self.registry_path().exists())

    def test_a_diverged_local_branch_registers_from_the_remote(self):
        root = init_repo()
        write(root, "README.md", "# before adoption\n")
        commit(root, "base")
        base = git(root, "rev-parse", "HEAD").strip()
        contract = fixture_contract()
        scaffold(root, contract, self.home)
        for standards in contract["bindings"]["paths"]["standards"]:
            write(root, f"{standards}/bar.md", "# the bar\n")
        write(root, ".agents/runtime/.gitignore", "*\n")
        git(root, "add", "-f", ".agents/runtime/.gitignore")
        commit(root, "contract")
        write_adoption_records(root)
        commit(root, "adopt")
        adoption = git(root, "rev-parse", "HEAD").strip()
        # Freshness (PR-02): origin first holds only `base`, pushed from this
        # checkout, so its `refs/remotes/origin/main` is stale; the adoption
        # then advances on origin itself, never through a push that updates
        # `root`'s remote-tracking ref.
        bare = publish(root, ("HEAD~2:main",))
        stale = git(root, "rev-parse", "refs/remotes/origin/main").strip()
        git(root, "push", "--quiet", "origin", f"{adoption}:refs/staging/adopt")
        git(bare, "update-ref", "refs/heads/main", adoption)
        self.assertNotEqual(stale, adoption)
        # Diverge: local main falls behind the adoption (no contract at all),
        # gains unpushed work, an unstaged edit and an untracked file.
        git(root, "reset", "--quiet", "--hard", base)
        write(root, "user-work.md", "# unpushed\n")
        commit(root, "unpushed user work")
        write(root, "README.md", "# unstaged edit\n")
        untracked = write(root, "scratch.txt", "untracked bytes\n")
        local_main = git(root, "rev-parse", "refs/heads/main").strip()
        status = git(root, "status", "--porcelain")
        snapshot = tree_snapshot(root)

        report = self.report(root, "--register")

        self.assertEqual(report["result"], "adopted", report["checks"])
        self.assertIs(report["registered"], True)
        self.assertEqual(report["revision"], {
            "ref": "refs/remotes/origin/main", "commit": adoption})
        self.assertEqual(report["adoption_commit"], adoption)
        self.assertEqual(report["evidence_record"],
                         f".agents/artifacts/evidence/{'a1' * 32}.json")
        self.assertEqual(report["root"], str(root))
        self.assertEqual(self.registry()["projects"], [
            {"project_id": "fixture/target", "root": str(root)}])
        self.assertEqual(git(root, "rev-parse", "refs/heads/main").strip(),
                         local_main)
        self.assertEqual(git(root, "status", "--porcelain"), status)
        self.assertEqual(tree_snapshot(root), snapshot)
        self.assertEqual(untracked.read_text("utf-8"), "untracked bytes\n")
        self.assertFalse((root / ".git" / "FETCH_HEAD").exists())
        self.assertEqual(
            git(root, "rev-parse", "refs/remotes/origin/main").strip(), adoption)
        plain = self.report(root)
        self.assertEqual(plain["result"], "not_conformant", plain)
        self.assertEqual(plain["revision"]["ref"], "HEAD")

    def test_an_unpushed_adoption_refuses_not_integrated(self):
        root = verifiable_repo(self.home)
        publish(root, ("HEAD~1:main",))
        self.assertEqual(self.report(root)["result"], "adopted")
        self.refuse_with(root, "not_integrated",
                         "adopt.registration.not_integrated")

    def test_an_adoption_only_on_its_apply_branch_refuses_not_integrated(self):
        root = apply_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err or out)
        plan_id = json.loads(out)["plan"]["plan_id"]
        code, out, err = run("apply", "--plan-id", plan_id, home=self.home)
        self.assertEqual(code, 0, err or out)
        branch = json.loads(out)["branch"]
        publish(root)
        git(root, "checkout", "--quiet", branch)
        self.assertEqual(self.report(root)["result"], "adopted")
        self.refuse_with(root, "not_integrated",
                         "adopt.registration.not_integrated")

    def test_a_configured_fetch_mapping_cannot_move_a_local_branch(self):
        # PR-01: `--refmap=` disables configured `remote.origin.fetch`
        # mappings, so even one aimed at a local branch is not applied.
        root = verifiable_repo(self.home)
        publish(root)
        git(root, "branch", "keep", "HEAD~1")
        keep = git(root, "rev-parse", "refs/heads/keep").strip()
        git(root, "config", "--add", "remote.origin.fetch",
            "+refs/heads/main:refs/heads/keep")
        report = self.report(root, "--register")
        self.assertIs(report["registered"], True)
        self.assertEqual(git(root, "rev-parse", "refs/heads/keep").strip(), keep)

    def test_no_origin_refuses_not_integrated(self):
        self.refuse_with(verifiable_repo(self.home), "not_integrated",
                         "adopt.registration.no_remote")

    def test_an_origin_without_a_default_branch_refuses_not_integrated(self):
        root = verifiable_repo(self.home)
        bare = Path(tempfile.mkdtemp()).resolve() / "empty.git"
        git(bare.parent, "init", "--quiet", "--bare", "-b", "main", str(bare))
        git(root, "remote", "add", "origin", str(bare))
        self.refuse_with(root, "not_integrated",
                         "adopt.registration.remote_default_unknown")

    def test_an_unreachable_origin_refuses_adopt_failure(self):
        root = verifiable_repo(self.home)
        git(root, "remote", "add", "origin",
            str(Path(tempfile.mkdtemp()).resolve() / "missing.git"))
        self.refuse_with(root, "adopt_failure", "adopt.git.remote_unreachable")


class RegisterProjectInnerCheckTest(VerifyTestCase):
    """The inner checks of D7, which no CLI path reaches: walking from the
    pinned commit already makes them hold for every CLI registration."""

    def attempt(self, root: Path, adoption: str, contract_branch: str,
                pinned: str) -> AdoptError:
        source = adopt_verify.VerificationSource(
            ref="refs/remotes/origin/main", commit=pinned,
            resolver_root=root, inventory=[], branch="main")
        verification = adopt_verify.Verification(
            {"project_id": "fixture/target", "adoption_commit": adoption,
             "registered": False},
            {"bindings": {"vcs": {"integration_branch": contract_branch}}},
            source, [f".agents/artifacts/evidence/{'a1' * 32}.json"])
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            with self.assertRaises(AdoptError) as caught:
                adopt_verify.register_project(root, verification)
        self.assertFalse(self.registry_path().exists())
        return caught.exception

    def test_an_adoption_commit_off_the_pinned_commit_refuses(self):
        root = verifiable_repo(self.home)
        pinned = git(root, "rev-parse", "HEAD").strip()
        git(root, "checkout", "--quiet", "-b", "side", "HEAD~1")
        write(root, "side.md", "# side\n")
        commit(root, "side")
        side = git(root, "rev-parse", "HEAD").strip()
        error = self.attempt(root, side, "main", pinned)
        self.assertEqual((error.code, error.repair_id),
                         ("not_integrated", "adopt.registration.not_integrated"))

    def test_a_contract_naming_another_branch_refuses(self):
        root = verifiable_repo(self.home)
        pinned = git(root, "rev-parse", "HEAD").strip()
        error = self.attempt(root, pinned, "dev", pinned)
        self.assertEqual(
            (error.code, error.repair_id),
            ("not_integrated", "adopt.registration.integration_branch_unresolved"))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py -k RemoteRegistrationTest -k RegisterProjectInnerCheckTest`
Expected: FAIL — `test_a_diverged_local_branch_registers_from_the_remote` refuses `not_integrated` (ancestry still checked against local `main`), `test_no_origin_refuses_not_integrated` reports exit 0, and both inner-check tests fail on the `AdoptError` codes or repair ids.

- [ ] **Step 3: Write the minimal implementation**

1. `adopt_inspection.py`: add `import os`, `import tarfile`, `from dataclasses import dataclass`, and the produced names above, each with a docstring stating its git command and refusal. Rewrite the module docstring's "nothing that writes" sentence per the last invariant.
2. `adopt_verify.py`: add `import contextlib`, `import tempfile`, `from collections.abc import Iterator`, import the new `adopt_inspection` names, and write `remote_source`, `require_integrated` and the new `register_project` checks per the invariants. `commit_is_ancestor`'s parameter `branch` is renamed `revision` and its docstring says it takes a commit id or ref.
3. `adopt_project.py` `command_verify`:

Only the body after the existing `require_manifest()` call is replaced; that call stays first, before the target is touched or fetched (PR-05).

```python
    require_manifest()
    root = adopt_inspection.require_repository(args.repo_root)
    if not args.register:
        verification = adopt_verify.verify_repository(
            root, adopt_verify.head_source(root), run_resolver)
    else:
        with adopt_verify.remote_source(root, run_resolver) as source:
            verification = adopt_verify.verify_repository(
                root, source, run_resolver)
        adopt_verify.require_integrated(verification)
        if adopt_verify.registration_allowed(verification.report["result"]):
            adopt_verify.register_project(root, verification)
    emit_json(verification.report)
    return adopt_verify.verify_exit_code(verification.report["result"])
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py`
Expected: PASS, 30 tests, no failures.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_apply.py`
Expected: PASS (plan and apply untouched).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_inspection.py python/agent_tools/adopt_verify.py python/agent_tools/adopt_project.py home/common/agent-skills/tests/test_adopt_verify.py
git commit -m "feat(adopt): register against the fetched origin default branch (#341)"
```
