# Task 6: Typed results, `core_binding`, forge inspect, read spellings and `adapter inspect`

**Files:**
- Modify: `python/agent_tools/release_adapter.py` (typed results and `core_binding`)
- Modify: `python/agent_tools/forge_adapter.py` (`inspect`)
- Modify: `python/agent_tools/release.py` (`adapter inspect` subcommand)
- Create: `tests/fixtures/forge-adapter-spellings.json` (the `canonical` block and the seven inspect read rows)
- Create: `tests/forge_world.py` (fake provider world)
- Test: `tests/test_forge_adapter.py`; modify `tests/test_release_command.py`
- Modify: `justfile` (add `tests/test_forge_adapter.py` after `tests/test_release_command.py`)

Decisions: D7, D8, D11, D12, D15, D17, D22. Spec §6, §7 (inspect half). AC9 is owned here.

**Interfaces:**
- Consumes: Task 1's `release_adapter`; Task 2's `ResolvedReleaseProfile` (`adapters[alias]`, nodes); `transaction_invocation.OUTCOMES`/`ERROR_CLASSES` (read only); Task 5's `release.build_parser`.
- Produces (`release_adapter`): `EFFECT_OUTCOMES = transaction_invocation.OUTCOMES`, `PREDICATE_OUTCOMES = ("satisfied", "unsatisfied", "unknown")`, `INVOKE_RESULTS = ("accepted", "rejected", "unknown")`; validators returning `list[str]` problems — `effect_observation_problems` (exactly `{outcome ∈ EFFECT_OUTCOMES, reason: non-empty str, observed_subject: object, references: list[str], observed_at: int epoch ms, facts: object}`), `predicate_observation_problems` (exactly `{outcome ∈ PREDICATE_OUTCOMES, reason, references, observed_at}`), `invoke_result_problems` (exactly `{result ∈ INVOKE_RESULTS, error_class, reference: non-empty str}`, `error_class` None exactly when `accepted`, else in `ERROR_CLASSES`; no `succeeded` anywhere); `reference_text(obs) = json.dumps({"reason", "references"}, sort_keys=True, separators=(",", ":"))`; `core_binding(adapter, profile: ResolvedReleaseProfile, alias) -> CoreBinding` with `.inspect`, `.invoke`, `.observe`.
- Produces (`forge_adapter`): `inspect(request) -> dict`; `CHILD_TIMEOUT_SECONDS = 30` (tests lower it).
- Produces (CLI): `release adapter inspect <adapter> <operation> --parameters <json>` → the effect observation, exit 0. Exit 2 errors: `adapter_unknown` (`release.adapter.unknown`), `operation_unknown` (`release.adapter.operation_unknown`, also when `inspect` is `unsupported`), `parameters_invalid` (`release.adapter.parameters_invalid`, not a JSON object). It resolves no project.

**Adapter request (closed, D7):** `{"kind": "effect", "operation", "parameters"}` or `{"kind": "predicate", "predicate", "operation", "parameters"}`. Forge parameters: `target` (`kind == "github_repository"`, `repository`, `branch`; `handle` ignored); `tag`/`release` add `candidate: {version, commit}` (`release` also `title`, `notes`); `pr_merge` adds `pr` (positive int), `expected_base_tip`, `expected_head` (40-hex). `action`, `operation`, `config` are tolerated; anything else unknown or missing → `unknown`/`parameters_invalid`, no child process.

**Invariants:**
- `core_binding` raises `ValueError` when `adapter.describe()`'s `name` or `descriptor_digest` differs from `profile["adapters"][alias]` (the profile pins the implementation, D5, D17), when a request's `parameters["action"]` is not a node bound to `alias`, or when an adapter result fails its validator. It adds no retry, ordering or outcome policy.
- `.inspect(req)` → `{"outcome", "reference": reference_text(obs)}` of `adapter.inspect({"kind": "effect", "operation": req["parameters"]["operation"], "parameters": req["parameters"]})`; `.invoke(req)` → the adapter's `invoke` result unchanged; `.observe(req)` unwraps the core's derived nesting `p = req["parameters"]["parameters"]`, calls `adapter.inspect({"kind": "predicate", "predicate": req["predicate"], "operation": p["operation"], "parameters": p})` and returns `{"outcome", "reason", "reference"}`.
- Forge inspect issues only the fixture's read spellings, `gh` by name, `GITHUB_TOKEN`/`GH_TOKEN` removed from the child environment, each under `CHILD_TIMEOUT_SECONDS`; it never reads `target_commitish`, never mutates, never calls the guard.
- `forge_adapter` imports no `host_admission` or `launch_*` module (AC9).

## Forge inspect (exact, spec §7, D11)

A failed `gh api` call's status is the `(HTTP NNN)` in its stderr; a satisfied effect's reason is `observed`.

- `tag`: `tag.ref` 404 → `absent`/`tag_absent`; `object.type == "commit"` → `diverged`/`tag_not_annotated`; `"tag"` → `tag.object` for that sha, whose `object.sha` == `candidate.commit` → `satisfied`, else `diverged`/`tag_target_mismatch`. `observed_subject = {"tag", "commit": peeled sha or null}`.
- `release`: `release.view` 404 → `absent`/`release_absent`; `draft` → `diverged`/`release_draft`; `tag_name` ≠ version → `diverged`/`release_tag_mismatch`; else the `tag` result; `references` gain `html_url`.
- `pr_merge`: `pr_merge.view`, `pr_merge.base_ref`, `pr_merge.merge_commit` (only when `MERGED`), `pr_merge.protection`. `OPEN` → `absent`/`pr_open`; `MERGED` with `parents[].sha` == `[expected_base_tip, expected_head]` → `satisfied`, else `diverged`/`merge_parents_mismatch`; `CLOSED` → `diverged`/`pr_closed`. `facts = {"state", "base", "head", "head_oid", "base_tip", "protection": {"status": protected|unprotected (404)|inaccessible (403), "required_contexts", "enforce_admins"}}`.
- Other non-zero → `unknown`/`lookup_failed`; timeout → `lookup_timeout`; bad JSON or fields → `payload_invalid`; no `gh` → `executable_missing`; `facts.detail` ≤ 240 chars of stderr.
- Predicate `publication_visible` from the effect result: `satisfied` → `satisfied`/`observed`; `absent` → `unsatisfied`/`ref_absent`; `tag_not_annotated` → `unsatisfied`/`ref_not_immutable`; other `diverged` → `unsatisfied`/`subject_mismatch`; `unknown` (or any other predicate) → `unknown`/`store_unreachable`.

## The spelling fixture (D12, D22)

`tests/fixtures/forge-adapter-spellings.json` = `{"canonical": {...}, "rows": [...]}`; `canonical` = `{"slug": "fagenorn/nix-config", "branch": "main", "tag": "v1.2.3", "commit": "1"*40, "tag_object": "2"*40, "pr": 336, "head": "4"*40, "base_tip": "5"*40, "merge_commit": "3"*40, "title": "v1.2.3 — release", "notes_path": "/tmp/forge-notes-fixture.md"}` (the 40-character strings written out). Each row is exactly `{id, operation, kind, raw, argv}` with `shlex.split(raw) == argv`. This task writes the read rows:

| id | operation | raw |
|---|---|---|
| `tag.ref` | tag | `gh api repos/fagenorn/nix-config/git/ref/tags/v1.2.3` |
| `tag.object` | tag | `gh api repos/fagenorn/nix-config/git/tags/2222…2222` |
| `release.view` | release | `gh api repos/fagenorn/nix-config/releases/tags/v1.2.3` |
| `pr_merge.view` | pr_merge | `gh pr view 336 --repo fagenorn/nix-config --json state,baseRefName,headRefName,headRefOid,mergeCommit,url,statusCheckRollup` |
| `pr_merge.base_ref` | pr_merge | `gh api repos/fagenorn/nix-config/git/ref/heads/main` |
| `pr_merge.merge_commit` | pr_merge | `gh api repos/fagenorn/nix-config/git/commits/3333…3333` |
| `pr_merge.protection` | pr_merge | `gh api repos/fagenorn/nix-config/branches/main/protection` |

## The fake world (`tests/forge_world.py`)

`ForgeWorld(test_case)` writes executable `gh`, `git` and `claude-bash-lifecycle-guard` scripts (`#!{sys.executable}`) into a temporary `bin/` and patches `os.environ` until cleanup: `PATH` = that bin only, `GITHUB_TOKEN=harness-token`, `FORGE_WORLD=<state dir>`. Each script logs `{"tool", "argv", "stdin", "token_visible"}` to `<state>/calls.jsonl` and answers from `<state>/responses.json` keyed by `json.dumps([tool, *argv])` (`{"exit", "stdout", "stderr", "sleep"}`); unregistered → exit 64; a `gh` that sees a token → exit 65. API: `respond(tool, argv, *, exit=0, stdout="", stderr="", sleep=0)`, `respond_json(tool, argv, value)`, `not_found(tool, argv)` (exit 1, stderr `gh: Not Found (HTTP 404)`), `forbidden(...)` (HTTP 403), `calls() -> list[dict]`, `argvs(tool) -> list[list[str]]`, and `canonical(slug=…, **overrides)` building the standard happy-path responses for the fixture's canonical values with `slug` substituted (repository classes: default-only `fagenorn/nix-config`; distinct-integration `elevenyellow/nodocom` with branch `dev`; other-owner `someone-else/nix-config`).

- [ ] **Step 1: Write the failing tests**

`tests/test_forge_adapter.py`:

```python
"""Forge adapter against a fake provider world (#124 AC3, AC7, AC9). Run: just agent-workflow-tests"""
import ast
import json
import shlex
import unittest
from pathlib import Path

from agent_tools import forge_adapter, release_adapter
from .forge_world import ForgeWorld

FIXTURE = json.loads((Path(__file__).parent / "fixtures/forge-adapter-spellings.json").read_text("utf-8"))
C = FIXTURE["canonical"]
ROWS = {row["id"]: row for row in FIXTURE["rows"]}
TARGET = {"kind": "github_repository", "repository": C["slug"], "branch": C["branch"]}
CANDIDATE = {"version": C["tag"], "commit": C["commit"]}

def effect(operation, **parameters):
    return {"kind": "effect", "operation": operation, "parameters": {"target": TARGET, **parameters}}

class ForgeCase(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def tag_ref(self, object_type="tag", sha=C["tag_object"]):
        self.world.respond_json("gh", ROWS["tag.ref"]["argv"][1:], {"object": {"type": object_type, "sha": sha}})

    def tag_object(self, peeled=C["commit"]):
        self.world.respond_json("gh", ROWS["tag.object"]["argv"][1:], {"object": {"type": "commit", "sha": peeled}})

    def inspect(self, request):
        observation = forge_adapter.inspect(request)
        self.assertEqual(release_adapter.effect_observation_problems(observation), [])
        return observation

class TagInspectTest(ForgeCase):
    def test_target_read_from_tag_not_release_commitish(self):
        self.tag_ref()
        self.tag_object(peeled=C["commit"])
        self.world.respond_json("gh", ROWS["release.view"]["argv"][1:], {
            "tag_name": C["tag"], "draft": False, "target_commitish": "main",
            "html_url": "https://github.com/fagenorn/nix-config/releases/tag/v1.2.3"})
        observation = self.inspect(effect("release", candidate=CANDIDATE, title=C["title"], notes="n"))
        self.assertEqual((observation["outcome"], observation["observed_subject"]["commit"]),
                         ("satisfied", C["commit"]))
        self.assertEqual(self.world.argvs("gh"), [ROWS[i]["argv"][1:] for i in
                                                  ("release.view", "tag.ref", "tag.object")])

    def test_lightweight_tag_is_diverged(self):
        self.tag_ref(object_type="commit", sha=C["commit"])
        observation = self.inspect(effect("tag", candidate=CANDIDATE))
        self.assertEqual((observation["outcome"], observation["reason"]), ("diverged", "tag_not_annotated"))

    def test_absent_mismatch_and_predicates(self):
        self.world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        self.assertEqual(self.inspect(effect("tag", candidate=CANDIDATE))["outcome"], "absent")
        predicate = forge_adapter.inspect({"kind": "predicate", "predicate": "publication_visible",
                                           "operation": "tag",
                                           "parameters": {"target": TARGET, "candidate": CANDIDATE}})
        self.assertEqual(release_adapter.predicate_observation_problems(predicate), [])
        self.assertEqual((predicate["outcome"], predicate["reason"]), ("unsatisfied", "ref_absent"))
        self.tag_ref()
        self.tag_object(peeled="9" * 40)
        self.assertEqual(self.inspect(effect("tag", candidate=CANDIDATE))["reason"], "tag_target_mismatch")

    def test_draft_release_is_diverged(self):
        self.world.respond_json("gh", ROWS["release.view"]["argv"][1:],
                                {"tag_name": C["tag"], "draft": True, "html_url": "u"})
        self.assertEqual(self.inspect(effect("release", candidate=CANDIDATE, title="t", notes="n"))["reason"],
                         "release_draft")

class PrMergeInspectTest(ForgeCase):
    def pr(self, state, parents=(C["base_tip"], C["head"]), protection=None):
        self.world.respond_json("gh", ROWS["pr_merge.view"]["argv"][1:], {
            "state": state, "baseRefName": "main", "headRefName": "topic", "headRefOid": C["head"],
            "mergeCommit": {"oid": C["merge_commit"]} if state == "MERGED" else None,
            "url": "https://github.com/fagenorn/nix-config/pull/336", "statusCheckRollup": []})
        self.world.respond_json("gh", ROWS["pr_merge.base_ref"]["argv"][1:], {"object": {"sha": C["base_tip"]}})
        self.world.respond_json("gh", ROWS["pr_merge.merge_commit"]["argv"][1:],
                                {"parents": [{"sha": sha} for sha in parents]})
        if protection is None:
            self.world.respond_json("gh", ROWS["pr_merge.protection"]["argv"][1:], {
                "required_status_checks": {"contexts": ["Nix Eval"]}, "enforce_admins": {"enabled": True}})
        else:
            protection("gh", ROWS["pr_merge.protection"]["argv"][1:])

    def request(self):
        return effect("pr_merge", pr=C["pr"], expected_base_tip=C["base_tip"], expected_head=C["head"])

    def test_states_and_protection_facts(self):
        for state, parents, protection, outcome, status in (
                ("OPEN", (), None, "absent", "protected"),
                ("MERGED", (C["base_tip"], C["head"]), None, "satisfied", "protected"),
                ("MERGED", (C["head"], C["base_tip"]), None, "diverged", "protected"),
                ("CLOSED", (), self.world.not_found, "diverged", "unprotected"),
                ("OPEN", (), self.world.forbidden, "absent", "inaccessible")):
            with self.subTest(state=state, outcome=outcome, status=status):
                self.world.reset()
                self.pr(state, parents, protection)
                observation = self.inspect(self.request())
                self.assertEqual((observation["outcome"], observation["facts"]["protection"]["status"]),
                                 (outcome, status))
                self.assertEqual(observation["facts"]["base_tip"], C["base_tip"])

class InspectFailureTest(ForgeCase):
    def test_lookup_failures_are_unknown(self):
        argv = ROWS["tag.ref"]["argv"][1:]
        for name, respond, reason in (
                ("nonzero", lambda: self.world.respond("gh", argv, exit=1, stderr="boom"), "lookup_failed"),
                ("invalid json", lambda: self.world.respond("gh", argv, stdout="{"), "payload_invalid"),
                ("timeout", lambda: self.world.respond("gh", argv, sleep=2), "lookup_timeout")):
            with self.subTest(name):
                self.world.reset()
                respond()
                forge_adapter.CHILD_TIMEOUT_SECONDS, saved = 0.5, forge_adapter.CHILD_TIMEOUT_SECONDS
                try:
                    observation = self.inspect(effect("tag", candidate=CANDIDATE))
                finally:
                    forge_adapter.CHILD_TIMEOUT_SECONDS = saved
                self.assertEqual((observation["outcome"], observation["reason"]), ("unknown", reason))

    def test_invalid_parameters_make_no_call(self):
        observation = self.inspect({"kind": "effect", "operation": "tag", "parameters": {"target": TARGET}})
        self.assertEqual(observation["reason"], "parameters_invalid")
        self.assertEqual(self.world.calls(), [])

    def test_repository_classes_render_their_own_slug(self):
        for slug in ("elevenyellow/nodocom", "someone-else/nix-config"):
            with self.subTest(slug=slug):
                self.world.reset()
                self.world.canonical(slug=slug)
                target = {**TARGET, "repository": slug}
                observation = self.inspect({"kind": "effect", "operation": "tag",
                                            "parameters": {"target": target, "candidate": CANDIDATE}})
                self.assertEqual(observation["outcome"], "satisfied")
                self.assertTrue(all(slug in " ".join(argv) for argv in self.world.argvs("gh")))

class SpellingFixtureTest(unittest.TestCase):
    def test_rows_are_closed_and_tokenize_to_their_argv(self):
        for row in FIXTURE["rows"]:
            with self.subTest(row=row["id"]):
                self.assertEqual(sorted(row), ["argv", "id", "kind", "operation", "raw"])
                self.assertEqual(shlex.split(row["raw"]), row["argv"])
                self.assertIn(row["kind"], ("read", "mutation"))

class HostCapacityTest(unittest.TestCase):
    def test_capacity_is_declared_not_implemented(self):
        self.assertEqual(forge_adapter.describe()["host_capacity"], "not_required")
        tree = ast.parse(Path(forge_adapter.__file__).read_text("utf-8"))
        names = [alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                 for alias in node.names] + [node.module or "" for node in ast.walk(tree)
                                             if isinstance(node, ast.ImportFrom)]
        for name in names:
            self.assertFalse("host_admission" in name or name.split(".")[-1].startswith("launch_"), name)

if __name__ == "__main__":
    unittest.main()
```

(`ForgeWorld.reset()` clears responses and the call log.) Add `core_binding` tests to the same file as `CoreBindingTest`: compile `release_test_support.forge_profile()` with `release_test_support.descriptors()`, bind alias `forge`; assert `core_binding(forge_adapter, compiled, "forge").inspect({"parameters": <bound tag unit parameters>, …})` returns exactly `{"outcome", "reference"}` with a JSON `reference`; that a binding against a descriptor whose digest differs (compile with a descriptor copy whose `collector.max_concurrent_collections` is 2) raises `ValueError`; and that `observe` on a derived request `{"predicate": "publication_visible", "parameters": {"name": "tag", "parameters": <unit parameters>}}` returns `{"outcome": "unsatisfied", "reason": "ref_absent", "reference": …}` when `tag.ref` is 404.

In `tests/test_release_command.py` add `AdapterInspectTest(ReleaseCommandCase)`, running `python -m agent_tools.release adapter inspect …` without `--repo-root` (the subcommand takes none): unknown adapter → exit 2 `adapter_unknown`; `github-forge merge` → `operation_unknown`; `--parameters '[1]'` → `parameters_invalid`; with `ForgeWorld.env()` (its bin as `PATH`, plus `FORGE_WORLD`) in the child and an `OPEN` PR registered, `release adapter inspect github-forge pr_merge --parameters <canonical pr_merge parameters>` exits 0 with `outcome == "absent"` and `facts.protection.status == "protected"`.

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_adapter.py`
Expected: ERROR — `AttributeError: module 'agent_tools.forge_adapter' has no attribute 'inspect'` (and the fixture file is missing).

- [ ] **Step 3: Implement** the result validators, `reference_text`, `core_binding`, forge `inspect` (one private `_gh(argv) -> (status, payload | None, detail)` runner that scrubs the two token variables and maps 404/403/timeout/missing executable), the fixture rows, the fake world, and the `adapter inspect` subcommand (which calls `release_adapter.REGISTRY[name].inspect` and prints with `resolve_project.emit_json`; it resolves no project).

- [ ] **Step 4: Verify**

Run (900 s): `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_adapter.py tests/test_release_command.py tests/test_release_profile.py tests/test_release_grammar.py`
Expected: PASS, no skips.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release_adapter.py python/agent_tools/forge_adapter.py python/agent_tools/release.py \
  tests/fixtures/forge-adapter-spellings.json tests/forge_world.py tests/test_forge_adapter.py \
  tests/test_release_command.py justfile
git commit -m "feat(release): adapter results, core binding and forge inspect (#124)"
```
