# Task 2: Listed-commit pin, the reader parameter and the cheap proof

Spec sections 2, 4, 5 and 7, per D2, D3, D5, D6, D9 and D11. After this task, `guard-policy compile` and `derive` read each branch at the commit `origin` lists, with no fetch when the checkout already holds that commit, on the Task 1 sparse export with no inventory. `adopt-project` reads exactly as before.

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py` (`RemoteHeads`, `remote_heads`, new `pin_listed`, module docstring and the inspection section comment)
- Modify: `python/agent_tools/adopt_verify.py` (new `SourceReader`, `FETCH_READER`; `remote_source`, `pin_integration_branch`, `VerificationSource.inventory`, module docstring)
- Modify: `python/agent_tools/guard_policy.py` (`CONTRACT_READER`, `prove`, module docstring)
- Modify: `tests/guard_policy_world.py` (new `GuardPolicyWorld.advance`)
- Test: `tests/test_guard_policy.py`
- Modify: `python/README.md` (§ guard-policy)
- Modify: `home/common/claude-code/README.md` (§ Guard policy: cost paragraph, residual list)

**Interfaces:**
- Consumes (Task 1): `contract_export.export_contract(root: Path, commit: str, destination: Path) -> None`, which refuses `adopt.git.export_failed`. (Existing): `adopt_inspection.fetch_pinned(root, branch, timeout) -> str`, `export_commit(root, commit, destination)`, `tree_inventory(root, revision)`, `run_git`, `REMOTE`, `GIT_TIMEOUT_SECONDS`; `adopt_verify.remote_source(root, run_resolver, operand=None, *, network_timeout=...)`; `guard_policy.prove(entry, root, slug)`.
- Produces:
  - `adopt_inspection.RemoteHeads` gains a third field `listed: Mapping[str, str]`: branch name to the object id `origin` listed for it. An id is kept only when it is 40 or 64 lowercase hex characters (`re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value)`). `remote_heads` fills it from the same one `ls-remote` (no new network read) as a `types.MappingProxyType`.
  - `adopt_inspection.pin_listed(root: Path, branch: str, listed: str | None, timeout: float = GIT_TIMEOUT_SECONDS) -> str`. When `listed` is not `None` and `run_git(root, "cat-file", "-e", f"{listed}^{{commit}}")` exits 0, it returns `listed` and runs nothing else. Otherwise it returns `fetch_pinned(root, branch, timeout)`.
  - `adopt_verify.SourceReader`, a frozen dataclass with `pin: Callable[[Path, str, str | None, float], str]` (root, branch, listed id, network timeout → pinned commit), `export: Callable[[Path, str, Path], None]` (root, commit, new destination) and `inventory: bool`.
  - `adopt_verify.FETCH_READER = SourceReader(pin=<calls fetch_pinned(root, branch, timeout), ignoring the listed id>, export=export_commit, inventory=True)`: today's read.
  - `adopt_verify.remote_source(root, run_resolver, operand=None, *, network_timeout=GIT_TIMEOUT_SECONDS, reader: SourceReader = FETCH_READER)`. Every pin and export it makes goes through `reader`, passing `heads.listed.get(branch)`. The yielded source's `inventory` is `tree_inventory(root, pinned)` when `reader.inventory` is true and `None` otherwise.
  - `adopt_verify.pin_integration_branch(root, run_resolver, branch, destination, unconfirmed, network_timeout=GIT_TIMEOUT_SECONDS, *, listed: str | None = None, reader: SourceReader = FETCH_READER) -> tuple[str, Path]`.
  - `VerificationSource.inventory: list[tuple[str, str]] | None`. `None` means that no inventory was taken, so `verify_repository` raises (`TypeError`) instead of passing an empty inventory (D5).
  - `guard_policy.CONTRACT_READER = adopt_verify.SourceReader(pin=adopt_inspection.pin_listed, export=contract_export.export_contract, inventory=False)`. `prove` passes `reader=CONTRACT_READER`.
  - Test support: `GuardPolicyWorld.advance(root: Path, branch: str) -> str`.

**Invariants:**
- One `ls-remote` per `remote_source` call, as today. A listing failure still refuses as today, and no ref already present is consulted (D2).
- `pin_listed` writes nothing when the listed commit is present: no remote-tracking ref, no `FETCH_HEAD`, no object. When the commit is missing it is exactly `fetch_pinned`, and the pin is the commit `fetch_pinned` reads back (D2, D3).
- The row's `evidence.source.ref` stays `refs/remotes/origin/<branch read>`, and `evidence.source.commit` is the pinned id (D3).
- `adopt_project` and every other caller that passes no `reader` behave exactly as at base: same children, same writes, same reports. The adopt suites prove it unedited (D5).
- `adopt_verify` and `adopt_inspection` import neither `resolve_project` nor `contract_export` (issue 148 D26). `guard_policy` hands the reader in.
- A refusal raised by `export_contract` (`adopt.git.export_failed`) reaches `prove`'s existing `except AdoptError` and becomes `fetch_failed`. There is no fallback to a fetch or to another commit (spec section 2).
- `lifecycle_guard.py`, `default.nix` and `tests/test_claude_permission_guard.py` are not edited (D1).

- [ ] **Step 1: Write the failing tests**

Add to `GuardPolicyWorld` in `tests/guard_policy_world.py`, after `publish`:

```python
    def advance(self, root: Path, branch: str) -> str:
        """Push one new commit onto `origin`'s `branch` from another clone, so the checkout
        `root` does not hold it; return its id."""
        bare = self.git(root, "remote", "get-url", "origin").strip()
        other = Path(tempfile.mkdtemp(dir=self.tmp)) / "elsewhere"
        self.git(self.tmp, "clone", "--quiet", "--branch", branch, bare, str(other))
        self.git(other, "config", "commit.gpgsign", "false")
        (other / "advanced.txt").write_text(f"{branch}\n", encoding="utf-8")
        self.git(other, "add", "advanced.txt")
        self.git(other, "commit", "--quiet", "-m", f"advance {branch}")
        self.git(other, "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
        return self.git(other, "rev-parse", "HEAD").strip()
```

In `tests/test_guard_policy.py`, add `import subprocess` and `from .guard_policy_world import REAL_GIT` (beside the existing `GuardPolicyWorld` import). Add a module-level helper after `EVIDENCE_MEMBERS`:

```python
def holds(root, commit: str) -> bool:
    """Whether the checkout's object store holds `commit`."""
    return subprocess.run([REAL_GIT, "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
                          capture_output=True, timeout=60).returncode == 0
```

In `DerivationTest.test_the_contract_is_read_from_origin_and_the_checkout_is_left_alone`, record `moved = self.world.git(root, "rev-parse", "HEAD")` directly after the `commit --quiet -am "local only"` line. Replace its last assertion (`self.assertEqual(self.world.git(root, "rev-parse", "refs/remotes/origin/main"), published)`) with the two assertions below (per D3, D11):

```python
        # D3: origin's listed commit is already held, so nothing is fetched and the moved
        # remote-tracking ref stays where it was; the row still reads origin's commit.
        self.assertEqual(self.world.git(root, "rev-parse", "refs/remotes/origin/main"), moved)
        self.assertEqual(
            self.world.policy()["derived_repositories"]["fagenorn/one"]["evidence"]["source"],
            {"ref": "refs/remotes/origin/main", "commit": published.strip()})
```

Append to `DeriveTest`:

```python
    def test_a_listed_commit_already_held_is_read_without_a_fetch(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        main = self.world.git(root, "rev-parse", "main").strip()
        self.world.git(root, "update-ref", "-d", "refs/remotes/origin/main")
        report = self.derived("fagenorn/one")
        self.assertEqual(report["row"]["evidence"]["source"],
                         {"ref": "refs/remotes/origin/main", "commit": main})
        self.assertEqual(self.world.git(root, "for-each-ref", "refs/remotes/origin"), "")
        self.assertFalse((root / ".git/FETCH_HEAD").exists())

    def test_a_commit_pushed_since_the_last_fetch_is_fetched(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        pushed = self.world.advance(root, "main")
        self.assertFalse(holds(root, pushed))
        report = self.derived("fagenorn/one")
        self.assertEqual(report["row"]["evidence"]["source"],
                         {"ref": "refs/remotes/origin/main", "commit": pushed})
        self.assertEqual(self.world.git(root, "rev-parse", "refs/remotes/origin/main").strip(),
                         pushed)
        self.assertFalse((root / ".git/FETCH_HEAD").exists())

    def test_a_nodo_shaped_row_derives_through_both_pin_paths(self):
        nodo = self.world.project("nodocom", NODO, integration_branch="dev",
                                  publication_free=True, override=True)
        self.world.git(nodo, "update-ref", "-d", "refs/remotes/origin/main")
        self.world.git(nodo, "update-ref", "-d", "refs/remotes/origin/dev")
        held = self.derived(NODO)["row"]
        self.assertEqual((held["default_branch"], held["integration_branch"]), ("main", "dev"))
        self.assertEqual(held["evidence"]["source"],
                         {"ref": "refs/remotes/origin/dev",
                          "commit": self.world.git(nodo, "rev-parse", "dev").strip()})
        self.assertEqual(self.world.git(nodo, "for-each-ref", "refs/remotes/origin"), "")
        pushed = self.world.advance(nodo, "dev")
        fetched = self.derived(NODO)["row"]
        self.assertEqual((fetched["default_branch"], fetched["integration_branch"]),
                         ("main", "dev"))
        self.assertEqual(fetched["evidence"]["source"],
                         {"ref": "refs/remotes/origin/dev", "commit": pushed})
        # Only the branch whose listed commit was missing is fetched.
        self.assertEqual(self.world.git(nodo, "for-each-ref", "--format=%(refname) %(objectname)",
                                        "refs/remotes/origin").strip(),
                         f"refs/remotes/origin/dev {pushed}")
```

Append to `ProjectRefusalTest`:

```python
    def test_a_symlinked_projection_target_is_contract_unresolved(self):
        """D9: the sparse export leaves a symlinked projection file absent."""
        root = self.world.project("fixture/one", "fagenorn/one")
        (root / "CLAUDE.real.md").write_bytes((root / "CLAUDE.md").read_bytes())
        (root / "CLAUDE.md").unlink()
        (root / "CLAUDE.md").symlink_to("CLAUDE.real.md")
        self.world.git(root, "add", "-A")
        self.world.git(root, "commit", "--quiet", "-m", "symlinked target")
        self.world.publish(root, ["main"])
        refusal = self.refused("contract_unresolved")
        self.assertIn("projection.claude.entry.missing", refusal["detail"])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -6`
Expected: FAIL. Four tests fail: `test_the_contract_is_read_from_origin_and_the_checkout_is_left_alone` and `test_a_listed_commit_already_held_is_read_without_a_fetch` (the fetch rewrites or recreates the ref), `test_a_nodo_shaped_row_derives_through_both_pin_paths` (refs reappear) and `test_a_symlinked_projection_target_is_contract_unresolved` (the full export follows the link and derives). `test_a_commit_pushed_since_the_last_fetch_is_fetched` already passes at base: it guards the fetch path.

- [ ] **Step 3: Write the minimal implementation**

1. `adopt_inspection`: add `listed` to `RemoteHeads` and fill it in `remote_heads`, recording a branch's id only when it passes the hex check. Add `pin_listed` after `fetch_pinned`, with a docstring stating the Produces contract. Update the module docstring and the "Inspection" section comment: which functions touch the network (`remote_heads`, `fetch_pinned`, and `pin_listed` through `fetch_pinned`), and that `pin_listed` writes nothing when the commit is held.
2. `adopt_verify`: define `SourceReader` and `FETCH_READER` after `VerificationSource`. Thread `reader` and the listed id through `remote_source` (default branch, operand branch, hop) and `pin_integration_branch`, and keep every refusal and the selection order unchanged. Type `inventory` as optional, and extend the `VerificationSource` docstring with the fact that `None` means no inventory was taken. In the `remote_source` docstring, replace the fixed "fetched … exported with `git archive`" wording with what the default reader does and add one paragraph on `reader`. In the module docstring, name the reader parameter and say that `--register` uses the default reader.
3. `guard_policy`: import `contract_export`, define `CONTRACT_READER` above `prove` and pass it. Rewrite the module docstring sentences "The only repository writes are the remote-tracking refs of the branches read and the fetched objects" and "it writes no file beyond the fetched objects and remote-tracking refs" from the implemented code. Facts: each branch is read at the commit `origin` lists; it is fetched only when the checkout lacks that commit; the contract and its projection files are exported sparsely; no inventory is taken; the only repository writes are the remote-tracking refs of the branches fetched and the fetched objects.
4. `python/README.md` § guard-policy: in the `compile` paragraph (the sentence beginning "Its only repository writes") and the `derive` paragraph (the sentence beginning "It writes no file beyond"), state the same facts as item 3 and name `contract_export` and `resolve_project.projection_paths`. The paragraph on `adopt-project verify --register` stays as it is.
5. `home/common/claude-code/README.md` § Guard policy:
   - **Cost and offline behaviour**: replace the first three sentences (one listing, one fetch per branch, and the #377 5 s / 7 s estimate) with facts written from the code. Every repository-bound verb in a repository with a row costs one listing, one fetch only for a branch whose listed commit the checkout lacks, a sparse export of the contract and its projection files per branch read, the resolver and one provider read. The spec's estimate for Nodo on 2026-10-13 is about 3.3 s steady and about 5.4 s after a push, built from component timings; label it an estimate (Task 3 replaces it with measurements).
   - Replace "Two sessions judged at once may fetch into the same registered root; a fetch that loses a ref lock fails `fetch_failed`…" with its narrowed form: only a fetch writes a ref, so contention arises only when both sessions fetch a missing commit.
   - **Residual** list: add one bullet after the transport bullet. The checkout's object store is user-writable: a session that plants an object under the id `origin` lists forges that read, as it already could before a fetch that finds the object present (issue 385).
   - Do not change the `### Allow surface` text or any other section.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -4`
Expected: `OK`. All tests pass, the four above included.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py 2>&1 | tail -4` (timeout 1800 s)
Expected: `OK`, with no test file edited.

Run: `git diff --quiet 6958c11645165f1a725ac73a7dcc87c9ef617d03 -- home/common/claude-code/lifecycle_guard.py home/common/claude-code/default.nix tests/test_claude_permission_guard.py home/common/agent-skills/tests && echo UNTOUCHED`
Expected: `UNTOUCHED`.

Run: `if git grep -n -E 'import.*(contract_export|resolve_project)' -- 'python/agent_tools/adopt_*.py'; then exit 1; fi`
Expected: no output, exit 0.

Run: the guard-suite invocation (Global Constraints).
Expected: `OK`. The round trip and the tampered-state tests run the real `derive` with `CONTRACT_READER` (AC3).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_inspection.py python/agent_tools/adopt_verify.py python/agent_tools/guard_policy.py tests/guard_policy_world.py tests/test_guard_policy.py python/README.md home/common/claude-code/README.md
launch-commit … -- -m "feat(guard-policy): read origin at its listed commits on a sparse export (issue 385)"
```
