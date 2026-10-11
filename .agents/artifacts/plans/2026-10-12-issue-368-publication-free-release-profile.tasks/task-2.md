# Task 2: `bind_candidate` refusal and the adapter-binding proof

Spec section 2 (per D3, D8). A compiled publication-free profile must never become `TransactionStore.create` inputs: the transaction core accepts a plan with no unit, so `bind_candidate`, the only producer of those inputs from a profile, is where it stops. `release_adapter.core_binding` already refuses every request for such a profile; this task pins that with a test and changes no adapter code.

**Files:**
- Modify: `python/agent_tools/release_profile.py` (`bind_candidate`)
- Test: `tests/test_release_profile.py`, `tests/test_release_adapter_core.py` (additions only)

**Interfaces:**
- Consumes (Task 1): `tests/release_test_support.publication_free_profile() -> dict`; `release_profile.compile_profile("forge-target", <that profile>, support.base_contract(), descriptors)` returns a `ResolvedReleaseProfile` whose `publication` and `activation` are empty; the class `PublicationFreeTest` in `tests/test_release_profile.py`.
- Produces: `release_profile.bind_candidate(compiled, candidate)` raises `ValueError` for a compiled profile with no publication node. Signature unchanged.

**Invariants:**
- The refusal comes after the existing `TypeError` check on `compiled` and before the candidate is read, so it holds for any `candidate` value, a malformed one included.
- The message contains the profile id in `repr` form followed by ` declares no publication` (the test pins `'forge-target' declares no publication`).
- `bind_candidate` over a publishing profile returns what it returned at base.
- `python/agent_tools/release_adapter.py` and `python/agent_tools/forge_adapter.py` are not edited.
- With a publication-free compiled profile, no `gh`, `git` or `claude-bash-lifecycle-guard` child process is started by any `CoreBinding` request.

- [ ] **Step 1: Write the tests**

Add this method to the existing class `PublicationFreeTest` in `tests/test_release_profile.py` (the module already defines `compile_`, `tree`, `D` and imports `tempfile`, `Path`, `TransactionStore`):

```python
    def test_bind_candidate_refuses_it_before_reading_the_candidate(self):
        compiled = compile_("forge-target", support.publication_free_profile())
        for candidate in (support.CANDIDATE, None):
            with self.subTest(candidate=candidate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                before = tree(root)
                with self.assertRaisesRegex(ValueError, "'forge-target' declares no publication"):
                    inputs = release_profile.bind_candidate(compiled, candidate)
                    TransactionStore(root).create(
                        "k", inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
                        proof=inputs["proof"], recovery=inputs["recovery"], authority_class="test")
                self.assertEqual(tree(root), before)
```

Append to `tests/test_release_adapter_core.py`, above the `if __name__` line (the module already imports `forge_adapter`, `release_adapter`, `release_profile`, `support` and `ForgeWorld`):

```python
class PublicationFreeBindingTest(unittest.TestCase):
    """No request reaches the adapter through a publication-free profile (#368 D3, D8)."""

    def test_every_request_is_refused_before_any_child_process(self):
        world = ForgeWorld(self)
        publishing = release_profile.compile_profile("github-release", support.forge_profile(),
                                                     support.base_contract())
        release = release_profile.bind_candidate(publishing, support.CANDIDATE)["proof"]["units"][1]
        self.assertEqual(release["parameters"]["operation"], "release")
        compiled = release_profile.compile_profile(
            "forge-target", support.publication_free_profile(), support.base_contract())
        binding = release_adapter.core_binding(forge_adapter, compiled, "forge")
        requests = {"inspect": {"parameters": release["parameters"]},
                    "invoke": {"parameters": release["parameters"]},
                    "observe": {"predicate": "publication_visible",
                                "parameters": {"parameters": release["parameters"]}}}
        for name, request in requests.items():
            with self.subTest(request=name):
                with self.assertRaisesRegex(ValueError, "is not a node bound to this alias"):
                    getattr(binding, name)(request)
        self.assertEqual(world.calls(), [])

```

The request is the exact `release` unit a publishing profile for the same repository binds, so the refusal cannot come from a malformed request. `ForgeWorld` replaces `PATH` with its own `gh`, `git` and `claude-bash-lifecycle-guard` and logs every call; `world.calls() == []` is the "no child process" proof.

- [ ] **Step 2: Run the tests**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_profile.py tests/test_release_adapter_core.py -k PublicationFree`
Expected: `test_bind_candidate_refuses_it_before_reading_the_candidate` FAILS — with `support.CANDIDATE` no `ValueError` is raised; with `None` the `ValueError` raised is the candidate-shape message, not the pinned one. `test_every_request_is_refused_before_any_child_process` PASSES already: it pins behaviour Task 1 made reachable. Show it can fail: temporarily change its `"forge-target"` compile to `support.forge_profile()`, observe `ValueError not raised` (the request is then a bound node and reaches the adapter), and restore the line.

- [ ] **Step 3: Implement**

In `bind_candidate`, directly after the `isinstance(compiled, ResolvedReleaseProfile)` check and before `_candidate_problem`: when `compiled["publication"]` is empty, raise `ValueError` whose text names `compiled["profile_id"]` with `!r` and says it declares no publication, so no release candidate can be bound to it. Extend the function's docstring with that refusal, written from the code.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_profile.py tests/test_release_adapter_core.py`
Expected: PASS, 0 failures, 0 errors.

Run: `git diff --numstat 40fa1f82c5a5 -- 'tests/test_release_*.py'` — every row has `0` in its second column — and the never-edited gate of Global Constraints (it covers both adapter modules).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release_profile.py tests/test_release_profile.py tests/test_release_adapter_core.py
```

Commit through `launch-commit` with the message `feat(release-profile): bind_candidate refuses a publication-free profile (#368)`.
