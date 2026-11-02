# Task 1: `watch_operation` watches only a publication-triggered operation

Per D10 and D11. Read the plan root's Global Constraints first.

**Files:**
- Modify: `python/agent_tools/release_adapter.py` (`watch_operation` and its docstring)
- Modify: `tests/test_release_adapter_core.py` (new `WatchOperationTest`)
- Modify: `python/README.md` (§ Release adapters, the GitHub Actions paragraph's `watch_operation` sentence; § Release profiles, one clause of the `resolve-project` deploy-binding sentence)

**Interfaces:**
- Consumes: `release_adapter.watch_operation(descriptor: Mapping[str, Any]) -> str | None` as it is at base.
- Produces: the same signature with the narrowed rule. `resolve_project.validate_deploy` (unchanged) then reports any adapter with no single inspectable `publication_triggered` operation as `contract.deploy.adapter_unwatchable`, which Task 6 pins for `launchd-agent`.

**Invariants:**
- `watch_operation` returns the name of the descriptor's single operation whose `mode` is `"publication_triggered"` and whose `inspect` is `"supported"`, and `None` when there are zero or several such operations. No other mode (`local_apply`, `provider_deploy`, `convergent_pull`, or any publication mode) ever counts.
- `watch_operation(DESCRIPTORS["github-actions-health"]) == "deploy"` and `watch_operation(DESCRIPTORS["github-forge"]) is None` stay true (the existing `test_the_registry_carries_one_watch_operation` in `tests/test_actions_health_adapter.py` keeps passing unedited).
- No descriptor, digest or other function changes.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_release_adapter_core.py` (import `actions_health_adapter` beside the existing `agent_tools` imports):

```python
class WatchOperationTest(unittest.TestCase):
    """Only a publication_triggered operation is a deploy watch (issue 547 D10)."""

    def descriptor(self, *modes, inspect="supported"):
        descriptor = actions_health_adapter.describe()
        entry = descriptor["operations"]["deploy"]
        descriptor["operations"] = {f"op{index}": {**entry, "mode": mode, "inspect": inspect}
                                    for index, mode in enumerate(modes)}
        return descriptor

    def test_only_a_single_inspectable_publication_triggered_operation_is_watched(self):
        cases = ((("publication_triggered",), "supported", "op0"),
                 (("local_apply",), "supported", None),
                 (("provider_deploy",), "supported", None),
                 (("convergent_pull",), "supported", None),
                 (("materialize", "publication_triggered"), "supported", "op1"),
                 (("local_apply", "publication_triggered"), "supported", "op1"),
                 (("publication_triggered", "publication_triggered"), "supported", None),
                 (("publication_triggered",), "unsupported", None))
        for modes, inspect, expected in cases:
            with self.subTest(modes=modes, inspect=inspect):
                self.assertEqual(release_adapter.watch_operation(self.descriptor(*modes, inspect=inspect)),
                                 expected)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_adapter_core.py -k WatchOperation 2>&1 | tail -4'`
Expected: FAIL — the `("local_apply",)` subtest gets `'op0'` (and `("local_apply", "publication_triggered")` gets `None`), because base counts every activation mode.

- [ ] **Step 3: Write the minimal implementation**

In `watch_operation`, select `name` where `entry["mode"] == "publication_triggered" and entry["inspect"] == "supported"`; keep the single-or-`None` rule. Rewrite its docstring to state the new rule and that a `local_apply` adapter is therefore never a deploy watch (cite "issue 547 D10" beside "issue 465 D3"). The module docstring's sentence "`watch_operation` names the one operation of a descriptor that a deploy watch inspects" stays true; leave it.

In `python/README.md`, replace only the sentence "`release_adapter.watch_operation(descriptor)` names a descriptor's single inspectable activation-mode operation, or returns `None` when there is none or more than one." with one that states the narrowed rule and its consequence: the resolver reports a deploy binding naming an adapter without such an operation as `contract.deploy.adapter_unwatchable` (issue 547 D10). Change nothing else on that line.

In `python/README.md`'s § Release profiles, the sentence beginning "`resolve-project` holds such a binding" states the old rule a second time. Replace only its clause "a descriptor with exactly one inspectable activation-mode operation (`contract.deploy.adapter_unwatchable`)" with "a descriptor with exactly one inspectable `publication_triggered` operation (`contract.deploy.adapter_unwatchable`, issue 547 D10)". Change nothing else on that line.

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_adapter_core.py tests/test_actions_health_adapter.py 2>&1 | tail -4'`
Expected: PASS, `OK`, and the count is base's 17 plus 1.

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py -k DeployWatchTest 2>&1 | tail -4'`
Expected: PASS, `OK` (the `github-forge` unwatchable case still holds).

Run: `if grep -q 'inspectable activation-mode operation' python/README.md; then exit 1; fi`
Expected: exit 0 (neither statement of the old rule remains).

Run (timeout 3600 s): `just build`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release_adapter.py tests/test_release_adapter_core.py python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-547/T1): watch only a publication-triggered operation" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"c053465280688135eb6c60b8babbbcb55e87f308","head":"60148b635853a2861836f07c3f6f4a4bbf5a03b3"}],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":8,"boundary":"all","deleted_lines":4,"record_bytes":4096,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1a","last_task":5,"owner":1,"path":"python/agent_tools/release_adapter.py"},{"bounds":[{"added_lines":26,"boundary":"all","deleted_lines":0,"record_bytes":4096,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":7,"owner":1,"path":"tests/test_release_adapter_core.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":34816,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":7,"owner":1,"path":"python/README.md"}]}}
```
