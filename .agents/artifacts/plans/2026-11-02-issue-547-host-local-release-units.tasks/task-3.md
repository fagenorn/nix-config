# Task 3: `codesigned-artifact` install, registration and docs

Per D1, D2, D3, D6, D7, D8, D9, D12, D15, D20, D21, D22, D23. Read the plan root's Global Constraints and the spec's § `codesigned-artifact` `invoke` steps and § Shared rules first. This task implements those steps, with D20's staging layout.

**Files:**
- Modify: `python/agent_tools/codesigned_artifact_adapter.py` (add `invoke`, `INVOKE_BUDGET_SECONDS = 120`, docstring)
- Modify: `tests/test_codesigned_artifact_adapter.py` (new `InvokeTest`; Task 2's `DescribeTest` absence assertion becomes a registration assertion)
- Modify: `python/agent_tools/release_adapter.py` (import the module, add `"codesigned-artifact"` to `REGISTRY`)
- Modify: `tests/test_release_adapter_core.py` (new `RegistryTest`)
- Modify: `tests/test_release_grammar.py` (`DescriptorTest.test_registry_is_closed` expects three names)
- Modify: `python/README.md` (§ Release adapters: one new paragraph after the GitHub Actions paragraph)

**Interfaces:**
- Consumes: Task 2's `HostWorld` (`bundle`, `installed`, `identities`, `fail`, `environ`, `dirty`, `calls`, `tree`), `IDENTITY`, `OTHER`, and the test module's `Case`, `PATH`, `CONFIG`.
- Produces: `codesigned_artifact_adapter.invoke(request) -> {"result", "error_class", "reference"}`, and `release_adapter.REGISTRY["codesigned-artifact"]`, so `DESCRIPTORS` carries it (Tasks 6 and 7 compile and bind against it).

**Invariants:**
- `invoke` returns only a closed `InvokeResult` (`release_adapter.invoke_result_problems(result) == []`) and never raises.
- A refusal before the first successful rename leaves the install path (the installed bundle, or its absence) byte-for-byte unchanged and no `.<name>.release-staging` sibling. A refusal before step 7 also leaves the whole `world.tree()` unchanged; one in steps 7–8 may only have created the parent directory and removed stale siblings (D20). A shape, operation or uid refusal starts no child process. A refusal before the identity step runs no `codesign`.
- No write follows a symlink: the stamp lands only in the staged copy, and the source checkout and every link target keep their bytes (D23).
- `invoke` runs `git`, `security` and `codesign` only, by name, with the environment unchanged. It never runs `claude-bash-lifecycle-guard` (D12) and never runs a build.
- `accepted` means the install path holds the staged bundle with both stamp keys, signed with the selected identity's hash or `-`. Its siblings `.<name>.release-staging` and `.<name>.release-previous` are gone.
- The `github-forge` and `github-actions-health` descriptor digests and both forge fixture profile digests equal their base values (D22).

## `invoke`, in order, stopping at the first refusal

The reference of a refusal is `<step>: <detail>`, cut to 240 characters. One `INVOKE_BUDGET_SECONDS` deadline covers every child. A child started with no budget left is a timeout.
1. **Shape.** The request is exactly `{kind: "effect", operation, parameters}`, else `invalid_input`. An operation that `describe()` does not declare is `unsupported_operation`. Parameters that fail the module's existing shape check (the one `inspect` applies) are `invalid_input`. No child starts.
2. **Authority.** `os.getuid() == 0` is `authorization_denied`.
3. **Checkout** (124 D23). `git rev-parse --show-toplevel` in the process's working directory gives the root, which must be absolute. Then `git -C <root> rev-parse HEAD` must equal the candidate commit, and `git -C <root> status --porcelain --untracked-files=no` must print nothing, else `precondition_failed`. A read that times out is `transient_transport`. One that cannot start, or exits non-zero, is `provider_unavailable`. These answers also apply to the `security` read in step 5.
4. **Source.** `<root>/<source>` must be a directory that is not a symlink, `<source>/Contents` must not be a symlink, and `<source>/Contents/Info.plist` must be a regular file, not a symlink (`os.lstat`), that loads as a dict. Otherwise `precondition_failed` with reference `source: …` (D23).
5. **Identity.** Parse `security find-identity -v -p codesigning` stdout with D21's pattern, keeping order.
   - When `identity_env` names a variable whose value is non-empty, that value must equal a listed name, or a listed hash case-insensitively. Its hash is used. Otherwise refuse `precondition_failed` with reference `identity: no_signing_identity …`, with no ad-hoc fallback.
   - Otherwise the first name that starts with `identity_prefix` gives the hash.
   - Otherwise `-` when `adhoc_fallback` is true, and the same refusal when it is false.
6. **Install path.** An existing install path that is a symlink or not a directory is `precondition_failed`.
7. **Staging** (D20). Make the parent directory if missing, and remove any stale `.<name>.release-staging` and `.<name>.release-previous` siblings.
   - Create `.<name>.release-staging/` and copy the source into it as `<name>` with `shutil.copytree(..., symlinks=True)`.
   - Set `AgentReleaseVersion` and `AgentReleaseCommit` in its `Contents/Info.plist`. Write binary when the file starts with `b"bplist00"`, else XML, to a `tempfile.mkstemp` file inside the staged `Contents/`, then `os.replace` it onto `Contents/Info.plist`: never write through an existing path (D23). Other bundle symlinks stay as copied.
   - Run `codesign --force --sign <hash or -> <staged>`, then `codesign --verify --deep --strict <staged>`.
   - Any failure removes the staging directory and returns `rejected`: an `OSError` is `provider_unavailable`, a timeout `transient_transport`, a missing `codesign` `provider_unavailable`, and a non-zero exit `precondition_failed`.
8. **Swap** (D15, D20). When the install path exists, `os.rename` it to `.<name>.release-previous`, then `os.rename` the staged `<name>` onto the install path.
   - An `OSError` from a rename means it did not happen. Before any rename succeeded, remove staging and return `rejected`/`provider_unavailable`. After one, return `unknown`/`transient_transport` and leave the files as they are.
   - Then remove the previous sibling and the empty staging directory, ignoring `OSError`.
   - Return `accepted` with the absolute install path as the reference.

- [ ] **Step 1: Write the failing tests**

In `tests/test_codesigned_artifact_adapter.py` (add `import os, plistlib` and `from pathlib import Path`, and import `OTHER`), first retire Task 2's absence assertion: rename `DescribeTest.test_descriptor_is_exact_valid_and_fresh` to `test_descriptor_is_exact_valid_fresh_and_registered`, and replace its line `self.assertNotIn("codesigned-artifact", release_adapter.REGISTRY)` with `self.assertIs(release_adapter.REGISTRY["codesigned-artifact"], adapter)`. Then add:

```python
class InvokeTest(Case):
    def invoke(self, parameters=None):
        return adapter.invoke({"kind": "effect", "operation": "install",
                               "parameters": parameters or self.parameters()})

    def test_installs_a_stamped_signed_bundle_then_inspects_satisfied(self):
        self.world.bundle()
        installed = self.world.home / PATH[2:]
        self.assertEqual(self.invoke(), {"result": "accepted", "error_class": None,
                                         "reference": str(installed)})
        with open(installed / "Contents/Info.plist", "rb") as handle:
            self.assertEqual(plistlib.load(handle), {
                "CFBundleIdentifier": "dev.example.notifier", "CFBundleName": "Notifier",
                "AgentReleaseVersion": "v1.2.3", "AgentReleaseCommit": self.candidate["commit"]})
        self.assertEqual(os.readlink(installed / "Contents/Resources/current"), "../MacOS/notifier")
        signs = [c["argv"] for c in self.world.calls("codesign") if "--sign" in c["argv"]]
        self.assertEqual([argv[:3] for argv in signs], [["--force", "--sign", IDENTITY[0]]])
        self.assertEqual((Path(signs[0][3]).name, Path(signs[0][3]).parent.name),
                         ("Notifier.app", ".Notifier.app.release-staging"))
        self.assertEqual(sorted(p.name for p in installed.parent.iterdir()), ["Notifier.app"])
        self.assertEqual(self.world.calls("claude-bash-lifecycle-guard"), [])
        observed = self.effect()
        self.assertEqual((observed["outcome"], observed["reason"]), ("satisfied", "installed"))
```

Add `InvokeTest.test_each_refusal_leaves_the_installed_bundle_unchanged`, a table over rows `(name, arrange, (result, error_class), reference fragment, children)`. For each row: `self.setUp()`, `self.world.bundle()` (except where noted), `arrange()`, snapshot `world.tree()`, invoke, then assert the pair, that the fragment is in the reference, and that no `.Notifier.app.release-staging` exists. A row marked `staging` fails in steps 7–8: it asserts only that the install path's `tree()` entries are unchanged (none, where nothing was installed), allowing the parent-directory creation and stale-sibling removal D20 specifies. Every other row asserts the whole tree unchanged. `children` is `False` where `world.calls()` must be `[]`, and `"no-sign"` where no codesign `--sign` call may appear. Rows:
- target path `/abs/N.app`: `invalid_input`, no children.
- operation `publish` in both the request and parameters: `unsupported_operation`, no children.
- `mock.patch.object(adapter.os, "getuid", return_value=0)` around the call: `authorization_denied`, no children.
- candidate commit `"f" * 40`: `precondition_failed`, `checkout`, no-sign.
- `world.dirty()`: `precondition_failed`, no-sign.
- `os.chdir(world.home)`: `provider_unavailable`, no-sign.
- no `world.bundle()`: `precondition_failed`, `source`, no-sign.
- source `Contents/Info.plist` replaced by a symlink to `world.root / "outside.plist"` holding `plistlib.dumps({"CFBundleIdentifier": "dev.example.notifier"})`: `precondition_failed`, `source`, no-sign (only the checkout's `git` reads run), and the outside file's bytes are unchanged.
- source `Contents/Info.plist` overwritten with `plistlib.dumps([1])`: `precondition_failed`, no-sign.
- `world.identities(IDENTITY, exit=1, stderr="keychain locked")`: `provider_unavailable`, no-sign.
- `world.identities(OTHER)`: `precondition_failed`, `no_signing_identity`, no-sign.
- `environ(NOTIFIER_SIGNING_IDENTITY="Nobody")` with `adhoc_fallback=True`: `precondition_failed`, `no_signing_identity`, no-sign.
- install path a symlink to `world.checkout`: `precondition_failed`, no-sign. The symlink is intact.
- `fail("codesign", "sign", exit=1, stderr="errSecInternalComponent")`: `precondition_failed`, `errSecInternalComponent`, staging.
- `fail("codesign", "verify", exit=1)`: `precondition_failed`, staging.
- `adapter.INVOKE_BUDGET_SECONDS` patched to 1 with `fail("codesign", "sign", exit=0, sleep=3)`: `transient_transport`, staging.
- `os.rename` patched (`mock.patch.object(adapter.os, "rename", …)`) to raise `OSError` when the destination is the install path and otherwise call the real rename, with nothing installed: `provider_unavailable`, staging.

Add `InvokeTest.test_identity_selection_and_replacement`. Each case is accepted, and the asserted codesign `--sign` argument and installed stamp hold:
- `identities(IDENTITY, OTHER)` and `environ(NOTIFIER_SIGNING_IDENTITY=OTHER[1])` sign with `OTHER[0]`.
- The same with the value `OTHER[0].lower()` signs with `OTHER[0]`.
- The value `""` falls back to the prefix and signs with `IDENTITY[0]`.
- `identities()` with `adhoc_fallback=True` signs with `-`, and `effect(self.parameters(adhoc_fallback=True))` is `satisfied`.
- `world.bundle(binary=True)`: the installed `Info.plist` starts with `b"bplist00"`.
- `install(stamp=("v1.2.2", "f" * 40))`, plus empty `.Notifier.app.release-staging/` and `.Notifier.app.release-previous/` siblings: the parent then lists only `Notifier.app`, now stamped `v1.2.3`.

Add `InvokeTest.test_a_failed_swap_after_the_old_bundle_moved_is_unknown`: `install(stamp=("v1.2.2", "f" * 40))`, then the rename patch above. The result is `unknown`/`transient_transport`.

In `tests/test_release_adapter_core.py` (import `codesigned_artifact_adapter`, `forge_adapter` and `actions_health_adapter` if absent, and `release_profile`):

```python
class RegistryTest(unittest.TestCase):
    def test_codesigned_artifact_is_registered(self):
        self.assertIs(release_adapter.REGISTRY["codesigned-artifact"], codesigned_artifact_adapter)
        descriptor = release_adapter.DESCRIPTORS["codesigned-artifact"]
        self.assertEqual(descriptor, codesigned_artifact_adapter.describe())
        self.assertIsNone(release_adapter.watch_operation(descriptor))

    def test_prior_descriptors_and_forge_profiles_keep_their_base_digests(self):
        """Issue 547 D22: values measured at base 328f08da."""
        digest = release_adapter.descriptor_digest
        self.assertEqual(digest(release_adapter.DESCRIPTORS["github-forge"]),
                         "sha256:efe2899b3f41bfde870ab28366beb81a8359e5eb050a2be1534b71810473004a")
        self.assertEqual(digest(release_adapter.DESCRIPTORS["github-actions-health"]),
                         "sha256:2453a459491301250c59b62fa08b4846b13ada3970a4b0583710426b251dc55e")
        self.assertEqual(release_profile.profile_digest(support.forge_profile()),
                         "sha256:4be9656c19dce516d183fb3c581fbf3be8026ea490497ff15d8292fc79f06573")
        self.assertEqual(release_profile.profile_digest(support.publication_free_profile()),
                         "sha256:f98d60dd0f7484bfee7fd017d4edd4b6c23007db767b0a2f2a504a9c4b6cddab")
```

In `tests/test_release_grammar.py`, `test_registry_is_closed` expects `["codesigned-artifact", "github-actions-health", "github-forge"]` for both `REGISTRY` and `DESCRIPTORS`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_codesigned_artifact_adapter.py tests/test_release_adapter_core.py tests/test_release_grammar.py 2>&1 | tail -4'`
Expected: FAIL. `InvokeTest` fails with `AttributeError` (no `invoke`), and `test_codesigned_artifact_is_registered`, `test_descriptor_is_exact_valid_fresh_and_registered` and `test_registry_is_closed` with `KeyError`/inequality. The digest test passes: it pins.

- [ ] **Step 3: Write the minimal implementation**

Implement `invoke` as above, and update the module docstring so it describes `invoke`'s steps and failure mapping. Register the module. `release_adapter`'s module docstring names no adapter list, so leave it.

Add one paragraph to `python/README.md`'s § Release adapters, after the GitHub Actions one. Write it from the implemented code. It states:
- the registered name and module;
- the one operation (`install`, `materialize`, `in_place`, supported, both non-spend effect classes, no recovery operation);
- the predicates;
- the `installed_bundle` `path` rule and the closed config;
- the identity selection and ad-hoc policy;
- the D20 staging and swap, with the `rejected`/`unknown` boundary, and the uid-0 refusal;
- the stamp keys, and that the inspection classification is the issue 547 spec's table;
- the build limitation (D9): it installs what the checkout holds when HEAD is the candidate and no tracked file changed, and cannot prove the bundle was built from that commit;
- that `tests/host_world.py` fakes `security` and `codesign` with a fake-only `PATH`.

Keep the paragraph under 1,800 bytes, and edit no other line.

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_codesigned_artifact_adapter.py tests/test_release_adapter_core.py tests/test_release_grammar.py tests/test_release_profile.py tests/test_forge_adapter.py tests/test_actions_health_adapter.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `if grep -qi argus python/agent_tools/codesigned_artifact_adapter.py python/agent_tools/release_adapter.py; then exit 1; fi`
Expected: exit 0.

Run (timeout 3600 s): `just build`
Expected: exit 0 (`DESCRIPTORS` builds with three adapters at import).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/codesigned_artifact_adapter.py tests/test_codesigned_artifact_adapter.py python/agent_tools/release_adapter.py tests/test_release_adapter_core.py tests/test_release_grammar.py python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-547/T3): install and register codesigned-artifact" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":3,"records":[{"bounds":[{"added_lines":455,"boundary":"all","deleted_lines":0,"record_bytes":36864,"support":{"covers":["r2b","r3a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3a","last_task":3,"owner":3,"path":"python/agent_tools/codesigned_artifact_adapter.py"},{"bounds":[{"added_lines":440,"boundary":"all","deleted_lines":0,"record_bytes":34816,"support":{"covers":["r2c","r3b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3b","last_task":3,"owner":3,"path":"tests/test_codesigned_artifact_adapter.py"},{"bounds":[{"added_lines":11,"boundary":"all","deleted_lines":5,"record_bytes":5120,"support":{"covers":["r1a","r3c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3c","last_task":5,"owner":3,"path":"python/agent_tools/release_adapter.py"},{"bounds":[{"added_lines":60,"boundary":"all","deleted_lines":0,"record_bytes":8192,"support":{"covers":["r1b","r3d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3d","last_task":7,"owner":3,"path":"tests/test_release_adapter_core.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":2048,"support":{"covers":["r3e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3e","last_task":6,"owner":3,"path":"tests/test_release_grammar.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":2,"record_bytes":38912,"support":{"covers":["r1c","r3f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3f","last_task":7,"owner":3,"path":"python/README.md"}]}}
```
