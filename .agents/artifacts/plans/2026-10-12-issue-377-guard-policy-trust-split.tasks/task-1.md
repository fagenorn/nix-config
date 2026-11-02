# Task 1: `guard-policy derive` — re-derive one repository's row

Spec section 3 "Command" and section 5 (per D2, D8). Additive: `compile` keeps its current output and behaviour in this task; nothing calls `derive` yet.

**Files:**
- Modify: `python/agent_tools/guard_policy.py`
- Modify: `tests/guard_policy_world.py`
- Test: `tests/test_guard_policy.py`
- Modify: `python/README.md` (§ guard-policy)

**Interfaces:**
- Consumes: the existing `guard_policy` functions `origin_slug`, `_proof`, `unsupported_name`, `_refusal`, `ProjectRefused`, `CompileRefused`, `_platform_refusal`; `agent_platform.load_manifest`, `agent_platform.read_registry`; `adopt_verify.remote_source`.
- Produces (Tasks 2 and 3 rely on these exact names):
  - `entry_slug(entry: dict) -> tuple[Path, str]` — compile steps 1 and 2: `root_unavailable` unless the root is a git repository, then `origin_slug(root)`. Raises `ProjectRefused`.
  - `prove(entry: dict, root: Path, slug: str) -> dict` — steps 3 to 10: the `remote_source` block and `_proof` exactly as `derive` runs them today, with the same `AdoptError` → `branch_unresolved` / `fetch_failed` mapping. Raises `ProjectRefused`.
  - `derive(entry) -> tuple[str, dict]` unchanged in contract, now `slug = entry_slug(entry)[1]` composed with `prove`.
  - `_admit(proven: list[tuple[dict, str, dict]], literal_slugs) -> tuple[dict[str, dict], list[dict]]` — step 11 (`duplicate_repository` among proven rows), then `literal_conflict` for a slug in `literal_slugs`, then `name_unsupported`, in that order, exactly the loop `compile_policy` runs today; `compile_policy` calls it with `base["integration_bases"]`.
  - `derive_repository(entries: list[dict], repository: str) -> tuple[dict | None, list[dict]]` — the row and the refusals for one slug (algorithm below).
  - `run_derive(repository: str) -> tuple[int, dict]` — exit status and report.
  - `DERIVE_REPORT_SCHEMA_VERSION = 1`; the `derive` subparser with required `--repository`.
  - `GuardPolicyWorld.derive(repository: str, *, env: dict | None = None) -> tuple[int, dict, str]` in `tests/guard_policy_world.py`, mirroring `compile`: runs `[sys.executable, "-m", "agent_tools.guard_policy", "derive", "--repository", repository]` with `env or self.env`, `cwd=self.tmp`, timeout 300, and returns `(returncode, json.loads(stdout), stderr)`.

**Invariants:**
- The report is one line of JSON on stdout with exactly the keys `schema_version`, `repository`, `outcome`, `row`, `refused`, `cause`; `schema_version` is `1`; `repository` echoes the argument.
- `derived` ⇔ exit 0 ⇔ `row` is an object and `cause` is null. `refused` ⇔ exit 1 ⇔ `row` and `cause` are null. `unavailable` ⇔ exit 2 ⇔ `row` is null, `refused` is `[]`, `cause` is `{reason_code, detail}` with `reason_code` in `CAUSES` (`registry_invalid`, `platform_unavailable` or `internal`).
- `refused` lists, in registry order, each entry whose `origin` names the slug and that has no row, as `_refusal` objects (`project_id`, `root`, `reason_code`, `detail`); an entry whose steps 1–2 fail or whose `origin` names another slug is never listed and never reaches `prove` (no fetch, no provider read).
- `derive` writes no file: only the fetched objects and remote-tracking refs `prove` always writes. It reads no base policy and never reports `literal_conflict`.
- A row `derive` returns equals, member for member, the row `compile` writes for the same registry and `origin` state.
- `compile`'s output and every existing `tests/test_guard_policy.py` case are unchanged.

`derive_repository(entries, repository)`:
1. For each entry: `root, slug = entry_slug(entry)`; on `ProjectRefused`, or when `slug != repository`, skip the entry.
2. For each remaining entry: `row = prove(entry, root, slug)`; on `ProjectRefused` append `_refusal(entry, error)`; otherwise collect `(entry, slug, row)`.
3. `rows, more = _admit(proven, frozenset())`; refusals are step 2's followed by `more`.
4. Return `(rows.get(repository), refusals)`.

`run_derive(repository)` loads the platform manifest (`platform_unavailable` on `PlatformManifestError`) and then the registry (`registry_invalid`), as `run_compile` does in that order, calls `derive_repository`, and maps `CompileRefused` and any other `Exception` (cause `internal`, detail `"<TypeName>: <message>"`) to exit 2. `main` dispatches on `args.command`; for `derive` it prints one stderr line per refusal in `compile`'s wording (`guard-policy: <project_id> (<root>) has no derived row: <code>: <detail>`), a cause line `guard-policy: no row was derived: <code>: <detail>` for exit 2, then the report.

- [ ] **Step 1: Write the failing tests**

Add to `tests/guard_policy_world.py`, after `compile`:

```python
    def derive(self, repository: str, *, env: dict | None = None) -> tuple[int, dict, str]:
        """Run `derive` from source: `(exit status, parsed report, stderr)`."""
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.guard_policy", "derive",
             "--repository", repository],
            capture_output=True, text=True, timeout=300, env=env or self.env, cwd=self.tmp)
        return done.returncode, json.loads(done.stdout), done.stderr
```

Add to `tests/test_guard_policy.py`, before `class ProjectRefusalTest`:

```python
REPORT_MEMBERS = {"schema_version", "repository", "outcome", "row", "refused", "cause"}


class DeriveTest(WorldCase):
    """`guard-policy derive --repository <slug>`: the row check the guard runs (issue 377 D2)."""

    def derived(self, repository: str) -> dict:
        code, report, err = self.world.derive(repository)
        self.assertEqual((code, set(report)), (0, REPORT_MEMBERS), (report, err))
        self.assertEqual((report["schema_version"], report["repository"], report["outcome"],
                          report["cause"]), (1, repository, "derived", None))
        return report

    def refused_for(self, repository: str) -> dict:
        code, report, err = self.world.derive(repository)
        self.assertEqual((code, set(report)), (1, REPORT_MEMBERS), (report, err))
        self.assertEqual((report["repository"], report["outcome"], report["row"],
                          report["cause"]), (repository, "refused", None, None))
        return report

    def test_a_registered_slug_derives_the_row_compile_writes(self):
        self.world.project("nodocom", NODO, integration_branch="dev", publication_free=True,
                           override=True)
        self.world.project("fixture/single", "fagenorn/single")
        report = self.derived(NODO)
        self.assertEqual(report["refused"], [])
        self.assertEqual((report["row"]["default_branch"], report["row"]["integration_branch"]),
                         ("main", "dev"))
        self.assertEqual(self.world.compile()[0], 0)
        self.assertEqual(report["row"], self.world.policy()["derived_repositories"][NODO])
        self.assertEqual(self.derived("fagenorn/single")["row"]["integration_branch"], "main")

    def test_an_unregistered_slug_is_refused_with_an_empty_list(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.assertEqual(self.refused_for("acme/forged")["refused"], [])

    def test_an_absent_registry_refuses_every_slug(self):
        self.assertEqual(self.refused_for(NODO)["refused"], [])

    def test_a_failing_proof_is_refused_with_its_code(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        self.world.provider("fagenorn/one", exit=1)
        code, report, err = self.world.derive("fagenorn/one")
        self.assertEqual(code, 1, report)
        [refusal] = report["refused"]
        self.assertEqual((refusal["project_id"], refusal["root"], refusal["reason_code"]),
                         ("fixture/one", str(root), "provider_unproven"))
        self.assertIn("fixture/one ", err)

    def test_two_entries_on_one_slug_are_duplicate_repository(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.project("fixture/two", "fagenorn/one")
        report = self.refused_for("fagenorn/one")
        self.assertEqual([(r["project_id"], r["reason_code"]) for r in report["refused"]],
                         [("fixture/one", "duplicate_repository"),
                          ("fixture/two", "duplicate_repository")])

    def test_a_name_the_guard_does_not_load_is_refused(self):
        self.world.project("fixture/one", "fagenorn/one", integration_branch="dev+ci")
        [refusal] = self.refused_for("fagenorn/one")["refused"]
        self.assertEqual(refusal["reason_code"], "name_unsupported")

    def test_a_literal_integration_base_is_not_derive_s_concern(self):
        """Step 12 needs the base policy, which derive never reads."""
        self.world.write_base(integration_bases={"fagenorn/one": "dev"})
        self.world.project("fixture/one", "fagenorn/one")
        self.assertEqual(self.derived("fagenorn/one")["refused"], [])

    def test_an_entry_naming_another_slug_is_never_fetched(self):
        self.world.project("fixture/one", "fagenorn/one")
        other = self.world.project("fixture/two", "fagenorn/two")
        self.world.git(other, "update-ref", "-d", "refs/remotes/origin/main")
        self.assertEqual(self.world.git(other, "for-each-ref", "refs/remotes/origin"), "")
        self.derived("fagenorn/one")
        self.assertEqual(self.world.git(other, "for-each-ref", "refs/remotes/origin"), "")

    def test_an_unusable_registry_or_manifest_is_unavailable(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.write_registry("{")
        code, report, err = self.world.derive("fagenorn/one")
        self.assertEqual((code, report["outcome"], report["row"], report["refused"]),
                         (2, "unavailable", None, []), report)
        self.assertEqual(report["cause"]["reason_code"], "registry_invalid")
        self.assertIn("registry_invalid", err)
        self.world.register()
        (self.world.home / ".agents/share/platform-manifest.json").unlink()
        code, report, _ = self.world.derive("fagenorn/one")
        self.assertEqual((code, report["cause"]["reason_code"]), (2, "platform_unavailable"))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py -k DeriveTest 2>&1 | tail -4`
Expected: FAIL — every `DeriveTest` case errors with `json.decoder.JSONDecodeError` (argparse rejects `derive` as an invalid choice and prints nothing on stdout).

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/guard_policy.py`, to the interfaces, invariants and algorithm above:
- Split `derive` into `entry_slug` and `prove`; keep `derive` as their composition so `compile_policy` is unchanged in behaviour.
- Move `compile_policy`'s admission loop into `_admit(proven, literal_slugs)` and call it from both `compile_policy` and `derive_repository`.
- Add `derive_repository`, `run_derive`, the `derive` subparser (`help="re-derive one repository's row"`, `--repository` required, `help="the owner/name slug"`) and the dispatch in `main`.
- Extend the module docstring by one paragraph for `derive --repository <slug>`: what it reads, its one-line report and its three exit statuses, written from the code.

In `python/README.md` § guard-policy, add one paragraph for `guard-policy derive --repository <slug>`: it reads the registry, runs steps 1 and 2 for every entry and steps 3 to 10 only for entries whose `origin` names the slug, then step 11 and the name check among them; its report keys; outcomes `derived` (0), `refused` (1, `refused` empty when no entry names the slug) and `unavailable` (2, with `cause`); it writes no file beyond the fetched objects and remote-tracking refs, reads no base policy and never reports `literal_conflict`; the lifecycle guard runs it as its row check (issue 377).

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -4`
Expected: PASS — `OK`, exit 0, every pre-existing case included.

Run: `git diff --quiet 69a1047920707528fc97729b57b705332a360d27 -- home/common/claude-code tests/test_claude_permission_guard.py && echo UNTOUCHED`
Expected: `UNTOUCHED`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/guard_policy.py tests/guard_policy_world.py tests/test_guard_policy.py python/README.md
launch-commit … -- -m "feat(guard-policy): derive one repository's row for the guard's row check (#377)"
```
