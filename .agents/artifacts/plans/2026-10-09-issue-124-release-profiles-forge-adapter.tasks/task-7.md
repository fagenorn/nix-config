# Task 7: Forge invoke, guard enforcement and post-invocation observation

**Files:**
- Modify: `python/agent_tools/forge_adapter.py` (`invoke`)
- Modify: `tests/fixtures/forge-adapter-spellings.json` (four invoke rows)
- Modify: `tests/forge_world.py`
- Test: `tests/test_forge_adapter.py`; create `tests/test_release_adapter_core.py`
- Modify: `python/README.md` (`## Release adapters` after `## Release profiles`)
- Modify: `justfile` (add `tests/test_release_adapter_core.py` after `tests/test_forge_adapter.py`)

Decisions: D7, D8, D9, D11, D12, D17, D22, D23 (working checkout, precondition-read failures). Spec §7 (invoke half). AC3, AC7 and AC8 are owned here.

**Interfaces:**
- Consumes: Task 6's `forge_adapter.inspect`, `CHILD_TIMEOUT_SECONDS`, `release_adapter.invoke_result_problems`, `core_binding`, `ForgeWorld`, the fixture `canonical` block; `adopt_planning.normalize_remote_url(url) -> str | None`; `transaction_invocation.ERROR_CLASSES`; Task 2's `bind_candidate`; `tests/test_transaction_custody.CustodyCase` (`self.store`, `self.acquire`, `self.clock`).
- Produces: `forge_adapter.invoke(request: Mapping) -> dict` returning exactly `{"result", "error_class", "reference"}`. `forge_adapter`'s public callables are exactly `describe`, `inspect`, `invoke`.

**Invariants:**
- `invoke` makes at most one provider mutation, never retries, never reads the target (`tag.ref`, `tag.object`, `release.view`), and returns only `INVOKE_RESULTS` — no `succeeded` (#85, #206).
- Spec §7's invoke steps apply in order, stopping at the first refusal, with these exact values:
  1. **Shape.** Unknown or not-`supported` operation (`pr_merge`, D8) → `rejected`/`unsupported_operation`, reference `"<op>: <descriptor reason or unknown_operation>"`; invalid parameters (Task 6's set; `title` free of `"`, `$`, `` ` ``, `\`, NUL, CR, LF; SemVer `version`; 40-hex `commit`) → `rejected`/`invalid_input`. No child process either way.
  2. **Checkout (D23).** `git rev-parse --show-toplevel` in the process working directory; later `git` calls and the guard payload use it as `cwd`.
  3. **Same repository.** `normalize_remote_url(git remote get-url origin)`, the one line of `git remote get-url --push --all origin` (D24) and `invoke.repository`'s stripped stdout all equal `target.repository`, else `rejected`/`precondition_failed`.
  4. **Containment (`tag`).** `tag.compare` ∈ `{identical, ahead}`, else `rejected`/`precondition_failed`.
  5. **Local tag (`tag`).** `git for-each-ref --format=%(objecttype) refs/tags/<tag>` (D25): empty → `git tag -a <tag> <commit> -m "release: <tag>"`; `tag` with `git rev-parse refs/tags/<tag>^{commit}` == commit → reuse; otherwise `rejected`/`precondition_failed`. A failed lookup or tag creation is a failed precondition read (below).
  6. **Render** the fixture's `tag.push` / `release.create` spelling; `release` writes `notes` to a `tempfile.mkstemp(prefix="forge-release-notes-", suffix=".md")` file (mode 0600, removed in a `finally`); `assert shlex.split(raw) == argv`.
  7. **Guard.** `claude-bash-lifecycle-guard` by name, stdin `{"tool_name": "Bash", "tool_input": {"command": raw}, "cwd": <checkout>}`; non-zero, timeout or missing → `rejected`/`authorization_denied`, reference `"guard: " + ≤240 chars of stderr`.
  8. **Mutation** once, tokens scrubbed: exit 0 → `accepted`, reference `refs/tags/<tag>` or the stripped stdout URL (else `release:<tag>`); `already exists` (git) or `HTTP 422` (gh) → `rejected`/`precondition_failed`; timeout or other non-zero → `unknown`/`transient_transport`.
- A failed precondition read in steps 2–5 (non-zero, timeout, bad output, missing executable) → `rejected` with `transient_transport` (timeout) or `provider_unavailable`: nothing was mutated (D23).

## Fixture rows added (exact)

| id | operation | kind | raw |
|---|---|---|---|
| `invoke.repository` | shared | read | `gh api repos/fagenorn/nix-config --jq .full_name` |
| `tag.compare` | tag | read | `gh api repos/fagenorn/nix-config/compare/1111…1111...main --jq .status` |
| `tag.push` | tag | mutation | `git push origin refs/tags/v1.2.3` |
| `release.create` | release | mutation | `gh release create v1.2.3 --repo fagenorn/nix-config --verify-tag --title "v1.2.3 — release" --notes-file /tmp/forge-notes-fixture.md` |

The local `git` calls of steps 2, 3 and 5 are not fixture rows: they are neither provider spellings nor guarded verbs (D22); the adapter suite pins them through the call log.

- [ ] **Step 1: Write the failing tests**

Extend `ForgeWorld` with `checkout` (a real temporary directory) and `invoke_ready(slug=C["slug"], *, full_name=None, push_urls=None, tag_local=None, tag_lookup_exit=0, tag_create_exit=0, compare="ahead", guard_exit=0, push_exit=0, push_stderr="", push_sleep=0, create_exit=0, create_stdout=<release URL>, create_stderr="")`, registering the happy path: toplevel → `checkout`; origin → `git@github.com:<slug>.git`; `get-url --push --all origin` → `push_urls` (default that one origin URL; parameter `push_urls=None`); `invoke.repository` → `full_name or C["slug"]`; `tag.compare` → `compare`; `for-each-ref` → empty stdout, exit `tag_lookup_exit` (default 0) (or `tag` plus `rev-parse` → `tag_local` when given); `git tag -a` → `tag_create_exit` (default 0); the guard → `guard_exit` (stderr `lifecycle guard: refused`); push and create as given (create keyed with its `--notes-file` path replaced by `<NOTES>`; the real path is logged).

Add to `tests/test_forge_adapter.py`:

```python
class InvokeCase(ForgeCase):
    def invoke(self, operation, **extra):
        parameters = {"target": TARGET, "candidate": CANDIDATE, **extra}
        if operation == "release":
            parameters.setdefault("title", C["title"])
            parameters.setdefault("notes", "release notes body")
        result = forge_adapter.invoke({"kind": "effect", "operation": operation, "parameters": parameters})
        self.assertEqual(release_adapter.invoke_result_problems(result), [])
        return result

    def mutations(self):
        return [c for c in self.world.calls() if (c["tool"], c["argv"][:2]) in
                (("git", ["push", "origin"]), ("gh", ["release", "create"]))]

class PublicSurfaceTest(unittest.TestCase):
    def test_exactly_three_public_operations(self):
        public = sorted(name for name, value in vars(forge_adapter).items()
                        if callable(value) and not name.startswith("_")
                        and getattr(value, "__module__", None) == forge_adapter.__name__)
        self.assertEqual(public, ["describe", "inspect", "invoke"])

class InvokeResultSetTest(InvokeCase):
    def test_happy_paths_render_the_fixture_and_pass_the_guard(self):
        self.world.invoke_ready()
        self.assertEqual(self.invoke("tag"), {"result": "accepted", "error_class": None,
                                              "reference": "refs/tags/v1.2.3"})
        [push] = self.mutations()
        self.assertEqual(["git", *push["argv"]], ROWS["tag.push"]["argv"])
        [guard] = [c for c in self.world.calls() if c["tool"] == "claude-bash-lifecycle-guard"]
        payload = json.loads(guard["stdin"])
        self.assertEqual(payload, {"tool_name": "Bash", "tool_input": {"command": ROWS["tag.push"]["raw"]},
                                   "cwd": str(self.world.checkout)})
        self.assertFalse(any(c["token_visible"] for c in self.world.calls()))

    def test_release_create_matches_the_fixture_and_removes_the_notes_file(self):
        self.world.invoke_ready()
        self.assertEqual(self.invoke("release")["result"], "accepted")
        [create] = self.mutations()
        notes = create["argv"][-1]
        self.assertTrue(Path(notes).is_absolute())
        self.assertFalse(Path(notes).exists())
        expected = [notes if token == C["notes_path"] else token for token in ROWS["release.create"]["argv"]]
        self.assertEqual(["gh", *create["argv"]], expected)
        [guard] = [c for c in self.world.calls() if c["tool"] == "claude-bash-lifecycle-guard"]
        self.assertEqual(json.loads(guard["stdin"])["tool_input"]["command"],
                         ROWS["release.create"]["raw"].replace(C["notes_path"], notes))

class InvokeFailureTest(InvokeCase):
    def test_pr_merge_is_refused_before_any_call(self):
        result = forge_adapter.invoke({"kind": "effect", "operation": "pr_merge", "parameters": {
            "target": TARGET, "pr": C["pr"], "expected_base_tip": C["base_tip"], "expected_head": C["head"]}})
        self.assertEqual((result["result"], result["error_class"]), ("rejected", "unsupported_operation"))
        self.assertEqual(self.world.calls(), [])

    def outcome(self, operation="tag"):
        result = self.invoke(operation)
        return result["result"], result["error_class"]

    def test_each_refusal_stops_before_the_mutation(self):
        cases = (
            ("guard denial", dict(guard_exit=2), ("rejected", "authorization_denied")),
            ("other owner origin", dict(slug="someone-else/nix-config"), ("rejected", "precondition_failed")),
            ("redirected repository", dict(full_name="someone/renamed"), ("rejected", "precondition_failed")),
            ("uncontained commit", dict(compare="behind"), ("rejected", "precondition_failed")),
            ("tag at another commit", dict(tag_local="9" * 40), ("rejected", "precondition_failed")),
            ("push url elsewhere", dict(push_urls=["git@github.com:someone-else/nix-config.git"]),
             ("rejected", "precondition_failed")),
            ("two push urls", dict(push_urls=["git@github.com:fagenorn/nix-config.git"] * 2),
             ("rejected", "precondition_failed")),
            ("local tag lookup fails", dict(tag_lookup_exit=128), ("rejected", "provider_unavailable")),
            ("local tag creation fails", dict(tag_create_exit=128), ("rejected", "provider_unavailable")),
        )
        for name, ready, expected in cases:
            with self.subTest(name):
                self.world.reset()
                self.world.invoke_ready(**ready)
                self.assertEqual(self.outcome(), expected)
                self.assertEqual(self.mutations(), [])

    def test_provider_answers(self):
        cases = (
            ("tag exists remotely", "tag",
             dict(push_exit=1, push_stderr="! [rejected] v1.2.3 -> v1.2.3 (already exists)"),
             ("rejected", "precondition_failed")),
            ("release exists", "release",
             dict(create_exit=1, create_stdout="", create_stderr="HTTP 422: Validation Failed"),
             ("rejected", "precondition_failed")),
            ("push timeout", "tag", dict(push_sleep=2), ("unknown", "transient_transport")),
        )
        for name, operation, ready, expected in cases:
            with self.subTest(name):
                self.world.reset()
                self.world.invoke_ready(**ready)
                saved = forge_adapter.CHILD_TIMEOUT_SECONDS
                forge_adapter.CHILD_TIMEOUT_SECONDS = 0.5
                try:
                    self.assertEqual(self.outcome(operation), expected)
                finally:
                    forge_adapter.CHILD_TIMEOUT_SECONDS = saved
                self.assertEqual(len(self.mutations()), 1)
```

With `slug="someone-else/nix-config"` only the origin changes; `target.repository` stays `fagenorn/nix-config`.

`tests/test_release_adapter_core.py`:

```python
"""Outcomes are observed after invocation (#124 AC8). Run: just agent-workflow-tests"""
import unittest

from agent_tools import forge_adapter, release_adapter, release_profile
from . import release_test_support as support
from .forge_world import ForgeWorld
from .test_forge_adapter import ROWS
from .test_transaction_custody import CustodyCase

class PostInvocationObservationTest(CustodyCase):
    def setUp(self):
        super().setUp()
        self.world = ForgeWorld(self)
        compiled = release_profile.compile_profile("github-release", support.forge_profile(),
                                                   support.base_contract())
        self.inputs = release_profile.bind_candidate(compiled, support.CANDIDATE)
        self.binding = release_adapter.core_binding(forge_adapter, compiled, "forge")
        self.tid = self.store.create("release-k", self.inputs["subject"],
                                     concurrency_keys=self.inputs["concurrency_keys"],
                                     proof=self.inputs["proof"], recovery=self.inputs["recovery"],
                                     authority_class="test").transaction_id
        self.custody = self.acquire(self.tid)
        for target in ("awaiting_verification", "ready", "publishing"):
            self.store.advance(self.tid, target, reason="r", external_state="known", custody=self.custody)
        self.tag = self.inputs["proof"]["units"][0]

    def test_an_accepted_invoke_that_never_lands_is_observed_absent(self):
        self.world.invoke_ready()
        self.world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        self.store.inspect_action(self.custody, name="tag", parameters=self.tag["parameters"],
                                  effect=self.binding)
        after = self.store.invoke_action(self.custody, name="tag", parameters=self.tag["parameters"],
                                         effect=self.binding)
        events = [e for e in after.events if e["type"] in ("invocation_returned", "action_inspected")]
        self.assertEqual([(e["type"], e.get("result"), e.get("outcome")) for e in events[-2:]],
                         [("invocation_returned", "accepted", None), ("action_inspected", None, "absent")])
        reads = [c["argv"] for c in self.world.calls() if c["tool"] == "gh"]
        target_reads = [i for i, argv in enumerate(reads) if argv == ROWS["tag.ref"]["argv"][1:]]
        self.assertEqual(len(target_reads), 2)
        between = reads[target_reads[0] + 1:target_reads[1]]
        self.assertEqual(between, [ROWS["invoke.repository"]["argv"][1:], ROWS["tag.compare"]["argv"][1:]])

if __name__ == "__main__":
    unittest.main()
```

If the store refuses `ready` without anchor verification for this recovery plan, follow `tests/test_transaction_invocation.py`'s `ProtocolCase.publishing()` path exactly (read it first); the assertions stay as written.

- [ ] **Step 2: Run and watch them fail**

Run: `unittest tests/test_forge_adapter.py tests/test_release_adapter_core.py`
Expected: FAIL/ERROR — `forge_adapter` has no `invoke`; `PublicSurfaceTest` lists two names.

- [ ] **Step 3: Implement** `invoke` per the invariants, the four fixture rows, the `ForgeWorld` extensions, and the README section. The README section describes only code at this commit: descriptors and registry, the closed result shapes (no `succeeded`), `core_binding` and its digest pin, the forge operations (`pr_merge` `target_cas_unproven`), the two mutation spellings with `--verify-tag` and the guard call, and the shared fixture (cite #124 decision IDs).

- [ ] **Step 4: Verify**

Run (900 s): `unittest tests/test_forge_adapter.py tests/test_release_adapter_core.py tests/test_transaction_invocation.py`
Expected: PASS, no skips. Then `if rg -q 'succeeded' python/agent_tools/forge_adapter.py python/agent_tools/release_adapter.py; then exit 1; fi` exits 0.

- [ ] **Step 5: Commit** exactly the **Files** above as `feat(release): forge invoke behind the lifecycle guard, observed after invocation (#124)`.
