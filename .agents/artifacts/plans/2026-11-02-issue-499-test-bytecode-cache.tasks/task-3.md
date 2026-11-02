# Task 3: workflow-state imports its delivery module; a second `init-run` compiles nothing

Spec § Decisions (**The delivery loader**, **Installed layout**), § Test seams item 3, § Acceptance. Rests on D4, D5, D6, D7 and D9. After this task `_delivery()` in `workflow-state` loads `workflow_delivery.py` through a spec loader instead of `runpy.run_path`, so the module's bytecode is cached like any import's, and a test proves that a second `init-run` under one cache compiles nothing. This task owns AC1 and AC2: its gate runs every AC1 check, and it writes the acceptance record's rows.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py`
- Create: `.agents/artifacts/plans/2026-11-02-issue-499-test-bytecode-cache.acceptance.md`

**Interfaces:**
- Consumes: Task 1's `tests/test_suite_runner.py::MemberEnvironmentTest` and `::BytecodeCacheTest`, and the plan root's harness check, which Task 2 made pass; in `test_delivery_workflow.py`, the module constants `SCRIPTS`, `WORKFLOW` and `NOW` and the imports `importlib.util`, `os`, `subprocess`, `sys`, `tempfile`, `mock` and `Path`, all present at base.
- Produces: `_delivery()` with its signature, return value and caching unchanged; `DeliveryAdmissionTest.test_a_second_init_run_compiles_nothing_into_its_bytecode_cache`.

**Invariants (D4):**
- The entry path per layout is unchanged: `Path(__file__).parent / "workflow_delivery.py"` when that parent is named `scripts`, else `Path.home() / ".agents/lib/python/workflow_delivery.py"`.
- Each load builds a spec named `_workflow_delivery` from that file location, creates a fresh module from it and executes it through `spec.loader.exec_module`; nothing is registered in `sys.modules`.
- The interface check is an attribute read: `getattr(module, "WORKFLOW_DELIVERY_INTERFACE_VERSION", None) != 1` raises `ValueError("interface")`.
- `_DELIVERY_RUNTIMES` still caches one runtime per notes limit, a failed load is not kept, and every failure, a spec that cannot be made included, is raised as `WorkflowError("delivery runtime: …")` chained from the cause.
- `workflow-state.py` no longer imports `runpy`.

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_delivery_workflow.py`, in `class DeliveryAdmissionTest`, directly after the method `test_public_source_and_installed_admission_fail_closed` and before `test_direct_checkpoint_and_failure_remainder_round_trip`, add:

```python
    def test_a_second_init_run_compiles_nothing_into_its_bytecode_cache(self):
        """Issue 499 AC1. Two source-layout `init-run`s, each in a fresh root,
        share one fresh bytecode cache. The first leaves the delivery module's
        own bytecode at its source's mirrored path; the second compiles
        nothing, so every cache file keeps its bytes and modification time. The
        main script is never cached and lies outside the check."""
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            cache = base / "pycache"; home = base / "home"
            cache.mkdir(); home.mkdir()
            env = {key: value for key, value in os.environ.items()
                   if key != "PYTHONDONTWRITEBYTECODE"}
            env.update(HOME=str(home), PYTHONPYCACHEPREFIX=str(cache))

            def init_run(name):
                repo = base / name; repo.mkdir()
                completed = subprocess.run([sys.executable, str(WORKFLOW), "init-run",
                    "--repo-root", str(repo), "--creation-key", "bytecode", "--now", NOW],
                    capture_output=True, text=True, env=env, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)

            def cached():
                return {str(path.relative_to(cache)): (path.read_bytes(), path.stat().st_mtime_ns)
                        for path in cache.rglob("*") if path.is_file()}

            with mock.patch.object(sys, "pycache_prefix", str(cache)):
                delivery = Path(importlib.util.cache_from_source(
                    str(SCRIPTS / "workflow_delivery.py")))
            init_run("first")
            self.assertTrue(delivery.is_file(), delivery)
            first = cached()
            init_run("second")
            second = cached()
            self.assertEqual(sorted(second), sorted(first))
            self.assertEqual([name for name in first if second[name] != first[name]], [])
```

The test hands its own cache to the children and strips `PYTHONDONTWRITEBYTECODE`, so it never rests on the outer suite run's cache (D6). The expected path comes from CPython's own `cache_from_source` under the test's prefix (D9). The presence assertion is the one that fails today: `runpy` compiles the delivery module without writing bytecode, though the builder's and projection's bytecode does land in the cache. The unchanged-cache assertions hold with either loader, and they catch a load path that recompiles on every start.

- [ ] **Step 2: Run the test and watch it fail**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k test_a_second_init_run_compiles_nothing 2>&1 | tail -4'`
Expected: `Ran 1 test` and `FAILED (failures=1)`, from `AssertionError: False is not true : <cache>/…/workflow_delivery.<cache tag>.pyc`.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/agent-skills/scripts/workflow-state.py`:

1. Delete the line `import runpy`. `importlib.util` is already imported.
2. Replace `_delivery` with the following, given in full because D4 fixes its shape against `runpy`'s behaviour. It uses the spec-loader shape of `_host_admission`, but keeps no module: as with `runpy`, each load executes a fresh one, and only the runtime is cached per notes limit:

```python
def _delivery():
    """The delivery runtime, built once per process for each notes limit (#262 D1).

    The delivery module is imported from its file through the import system, so
    its bytecode is cached like any import's (issue 499): the `scripts` sibling
    in the source layout, `~/.agents/lib/python/workflow_delivery.py`
    installed. Each load executes a fresh module that is registered nowhere in
    `sys.modules`. The notes limit is read from the artifact-budget policy on
    every call. A load that fails is not kept, so the next call loads again.
    """
    src = Path(__file__).parent
    entry = src / "workflow_delivery.py" if src.name == "scripts" else Path.home() / ".agents/lib/python/workflow_delivery.py"
    try:
        if _DELIVERY_RUNTIMES:
            runtime = _DELIVERY_RUNTIMES.get(phase_notes_maximum())
            if runtime is not None:
                return runtime
        spec = importlib.util.spec_from_file_location("_workflow_delivery", entry)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot load {entry}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if getattr(module, "WORKFLOW_DELIVERY_INTERFACE_VERSION", None) != 1:
            raise ValueError("interface")
        maximum = phase_notes_maximum()
        runtime = module.DeliveryRuntime(notes_max_characters=maximum)
    except Exception as exc:
        raise WorkflowError(f"delivery runtime: {exc}") from exc
    _DELIVERY_RUNTIMES[maximum] = runtime
    return runtime
```

Change nothing else in the file. A missing file still fails inside the `try`, now from `exec_module`, with the same `FileNotFoundError` text that `runpy` raised (`[Errno 2] No such file or directory: '<entry>'`, checked while planning).

- [ ] **Step 4: Verify**

Run (timeout 300 s): the Step 2 command.
Expected: `Ran 1 test` and `OK`.

Run (timeout 1200 s; about 60 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k DeliveryAdmissionTest 2>&1 | tail -4'`
Expected: `Ran 25 tests` and `OK` (24 at base, plus this one). They cover the source and installed layouts through the CLI, the dependency refusals, and the in-process `_delivery()` calls.

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k test_installed_symlinked_policy_validates_a_terminal_result 2>&1 | tail -4'`
Expected: `Ran 1 test` and `OK`.

Run (timeout 60 s): `bash -c 'set -e; f=home/common/agent-skills/scripts/workflow-state.py; if grep -n "runpy" "$f"; then exit 1; fi; grep -c "spec_from_file_location(\"_workflow_delivery\", entry)" "$f"'`
Expected: `1`.

AC1, every check (Task 1's seams, Task 2's harness check, this task's seam):
- Run (timeout 300 s): the runner-module command from the plan root with `-k MemberEnvironmentTest -k BytecodeCacheTest`. Expected: `Ran 10 tests` and `OK`.
- Run (timeout 60 s): the harness check from the plan root. Expected: exit 0, printing `home/common/agent-skills/tests/test_eval_cases.py tests/test_suite_runner.py`.

Run (timeout 3600 s): `just build`
Expected: exit 0.

- [ ] **Step 5: Write the acceptance record**

Create `.agents/artifacts/plans/2026-11-02-issue-499-test-bytecode-cache.acceptance.md` with exactly this content. The sdd controller writes the `Verdict` column, so leave it `—`:

```markdown
# Acceptance record — issue #499

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] Suite child processes write and reuse bytecode in a per-run cache, and `workflow-state` loads its delivery module through the import system, so a second invocation compiles nothing. Measured by: a test added to the agent workflow test suite that asserts no recompilation on the second invocation, using the cache directory's contents or `-X importtime`. | code | `home/common/agent-skills/tests/test_delivery_workflow.py::DeliveryAdmissionTest::test_a_second_init_run_compiles_nothing_into_its_bytecode_cache`, `tests/test_suite_runner.py::MemberEnvironmentTest` and `::BytecodeCacheTest`, and the plan's harness check, run by `just agent-workflow-tests` | in final verification | — | `just agent-workflow-tests` on the final head, `failed=0` | — |
| AC2 | [evidence] Suite CPU work drops. Measured by: the suite runner's timing table on the merge commit's push to main (Agent Workflow Tests (advisory), hosted ubuntu-24.04, default worker cap); threshold: summed module seconds at least 150 s below the last push to main before the merge. | evidence | `gh run view <run-id> --repo fagenorn/nix-config --log \| grep -F "suite-runner: summary"` for the merge commit's push-triggered `ci.yaml` run on `main` and the last push run before it; threshold: the earlier `cpu=` minus the merge run's `cpu=` is at least 150.0 s | not measured — post-merge (D7) | — | post-merge, per D7: the "Agent Workflow Tests (advisory)" job of both runs, each with `failed=0`, `jobs=4` and the same `members=`; a non-qualifying merge run is read from its re-run, a non-qualifying baseline gives way to the latest earlier qualifying push run with the reason recorded; ship holds the issue for verification | — |
```

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_delivery_workflow.py .agents/artifacts/plans/2026-11-02-issue-499-test-bytecode-cache.acceptance.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(workflow-state): import the delivery module so its bytecode is cached (issue 499)" -m "<session trailer lines>"
```
