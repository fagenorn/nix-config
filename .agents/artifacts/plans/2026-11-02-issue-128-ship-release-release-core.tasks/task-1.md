# Task 1: Verification receipt

**Files:**
- Create: `python/agent_tools/release_verification.py`
- Modify: `tests/forge_world.py` (add `ForgeWorld.verification_ready`)
- Create: `tests/test_release_verification.py`
- Modify: `justfile` (add `tests/test_release_verification.py` after `tests/test_release_command.py`)

**Interfaces:**
- Consumes: `agent_tools.canonical.telemetry_digest`; `agent_tools.transaction_history.format_at`
  (integer epoch ms to `2026-09-21T14:13:20.000Z` form); `tests.forge_world.ForgeWorld`,
  `CANONICAL` (slug `fagenorn/nix-config`, branch `main`, commit `"1" * 40`, tag `v1.2.3`).
- Produces (Tasks 2, 3 and 5 rely on these exact names):

```python
SCHEMA = "release-verification/v1"
READ_BUDGET_SECONDS = 30
PAGE_SIZE = 100
STRIPPED = ("GITHUB_TOKEN", "GH_TOKEN")

class VerificationRefused(Exception):
    """`code` is `candidate_stale` or `verification_unavailable`; `detail` ≤ 240 chars."""
    def __init__(self, code: str, detail: str) -> None: ...

def observe(*, project_id: str, profile_id: str, profile_digest: str, repository: str,
            integration_branch: str, default_branch: str, commit: str, version: str,
            clock: Callable[[], int] | None = None) -> dict[str, Any]: ...
def canonical_text(receipt: Mapping[str, Any]) -> str: ...   # sorted, compact, ASCII, no NaN, no newline
def evidence_id(receipt: Mapping[str, Any]) -> str: ...      # "verification:" + telemetry_digest(receipt)
```

- `ForgeWorld.verification_ready(*, tip=CANONICAL["commit"], commit=CANONICAL["commit"],
  checks=None, runs=None, total_count=None, protection_exit=0, slug=CANONICAL["slug"],
  integration=CANONICAL["branch"], default=CANONICAL["branch"], sleep=0.0) -> None`.

**Invariants** (spec §3, D5, D22):
- Exactly three reads, in this order, each `[ "gh", "api", <path> ]` with no other argument:
  1. `repos/<repository>/git/ref/heads/<integration_branch>`;
  2. `repos/<repository>/branches/<default_branch>/protection`;
  3. `repos/<repository>/commits/<commit>/check-runs?per_page=100`.
- The child environment is `os.environ` minus `STRIPPED`. One monotonic deadline covers all
  three reads, and each `subprocess.run` gets `timeout=` the time remaining. When none
  remains, the read is not started and `verification_unavailable` is raised.
- Read 1: a failure (non-zero exit, timeout, `OSError`, bad JSON, no string `object.sha`) is
  `verification_unavailable`. A `sha` other than `commit` is `candidate_stale`, and reads 2
  and 3 never run.
- Read 2: any failure, or a missing, non-list or empty `required_status_checks.checks`, is
  `verification_unavailable`. Each entry must be `{context: non-empty str, app_id: int|None}`.
  An entry may carry other members, which are ignored. Any other shape is
  `verification_unavailable`. `required` keeps protection's order.
- Read 3: any failure, a non-int `total_count`, `total_count > PAGE_SIZE` or a non-list
  `check_runs` is `verification_unavailable`.
- Per required context, the matching runs are those whose `name == context`, and also whose
  `app.id == app_id` when `app_id` is not None. No match gives
  `{"context": c, "status": "missing", "conclusion": None}`. Otherwise the match with the
  largest `id` gives `{"context": c, "status": run["status"], "conclusion": run["conclusion"]}`.
- `result`:
  - `passed` when every check is `status == "completed"` and `conclusion == "success"`;
  - otherwise `failed` when some check is `completed` with another conclusion;
  - otherwise `pending`.
- The receipt is exactly `{schema, project, profile, profile_digest, candidate: {commit,
  version}, required: [{context, app_id}], checks: [...], result, observed_at}`, where
  `observed_at = format_at(clock())` and the clock defaults to `time.time_ns() // 1_000_000`.
- The module docstring states these rules and cites spec §3 and D22.

- [ ] **Step 1: Extend the fake world, then write the failing tests**

Add to `ForgeWorld` (its docstring says the reads stay outside the spelling fixture, D12):

```python
    def verification_ready(self, *, tip=CANONICAL["commit"], commit=CANONICAL["commit"],
                           checks=None, runs=None, total_count=None, protection_exit=0,
                           slug=CANONICAL["slug"], integration=CANONICAL["branch"],
                           default=CANONICAL["branch"], sleep=0.0):
        """Register release_verification's three reads (spec §3). Defaults: required
        `Nix Eval` and `Instruction Budget` (app_id null), one completed success run each."""
        checks = [{"context": "Nix Eval", "app_id": None},
                  {"context": "Instruction Budget", "app_id": None}] if checks is None else checks
        if runs is None:
            runs = [{"id": index + 1, "name": entry["context"], "status": "completed",
                     "conclusion": "success", "app": {"id": 15368}}
                    for index, entry in enumerate(checks)]
        self.respond_json("gh", ["api", f"repos/{slug}/git/ref/heads/{integration}"],
                          {"object": {"sha": tip, "type": "commit"}}, sleep=sleep)
        protection = ["api", f"repos/{slug}/branches/{default}/protection"]
        if protection_exit:
            self.respond("gh", protection, exit=protection_exit, stderr="gh: Not Found (HTTP 404)")
        else:
            self.respond_json("gh", protection, {"required_status_checks": {
                "strict": True, "contexts": [c["context"] for c in checks], "checks": checks}})
        self.respond_json("gh", ["api", f"repos/{slug}/commits/{commit}/check-runs?per_page=100"],
                          {"total_count": len(runs) if total_count is None else total_count,
                           "check_runs": runs})
```

Create `tests/test_release_verification.py`:

```python
"""release_verification: the candidate's required-CI receipt (#128 spec §3, D5, D22).

Run: just agent-workflow-tests"""
import unittest
from unittest import mock

from agent_tools import release_verification as verification
from agent_tools.canonical import telemetry_digest
from .forge_world import CANONICAL, ForgeWorld

NOW = 1_790_000_000_000


def observe(**overrides):
    arguments = {"project_id": "fagenorn/nix-config", "profile_id": "github-release",
                 "profile_digest": "sha256:" + "a" * 64, "repository": CANONICAL["slug"],
                 "integration_branch": "main", "default_branch": "main",
                 "commit": CANONICAL["commit"], "version": "v1.2.3", "clock": lambda: NOW}
    return verification.observe(**{**arguments, **overrides})


def run(identifier, name, status="completed", conclusion="success", app=15368):
    return {"id": identifier, "name": name, "status": status, "conclusion": conclusion,
            "app": {"id": app}}


class ReceiptTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def test_passed_receipt_is_closed_and_canonical(self):
        self.world.verification_ready()
        receipt = observe()
        self.assertEqual(sorted(receipt), ["candidate", "checks", "observed_at", "profile",
                                           "profile_digest", "project", "required", "result",
                                           "schema"])
        self.assertEqual(receipt["schema"], "release-verification/v1")
        self.assertEqual(receipt["candidate"], {"commit": CANONICAL["commit"], "version": "v1.2.3"})
        self.assertEqual(receipt["required"], [{"context": "Nix Eval", "app_id": None},
                                               {"context": "Instruction Budget", "app_id": None}])
        self.assertEqual(receipt["checks"], [
            {"context": "Nix Eval", "status": "completed", "conclusion": "success"},
            {"context": "Instruction Budget", "status": "completed", "conclusion": "success"}])
        self.assertEqual((receipt["result"], receipt["observed_at"]),
                         ("passed", "2026-09-21T14:13:20.000Z"))
        self.assertEqual(verification.evidence_id(receipt),
                         "verification:" + telemetry_digest(receipt))
        self.assertNotIn("\n", verification.canonical_text(receipt))
        self.assertEqual([c["argv"][0] for c in self.world.calls()], ["api", "api", "api"])
        self.assertFalse(any(c["token_visible"] for c in self.world.calls()))

    def test_failed_pending_and_missing(self):
        cases = {"failed": [run(1, "Nix Eval", conclusion="failure"), run(2, "Instruction Budget")],
                 "pending": [run(1, "Nix Eval", status="in_progress", conclusion=None),
                             run(2, "Instruction Budget")],
                 "missing": [run(2, "Instruction Budget")]}
        for name, runs in cases.items():
            with self.subTest(case=name):
                self.world.verification_ready(runs=runs)
                receipt = observe()
                self.assertEqual(receipt["result"], "pending" if name == "missing" else name)
        self.assertEqual(receipt["checks"][0],
                         {"context": "Nix Eval", "status": "missing", "conclusion": None})

    def test_the_run_with_the_largest_id_decides(self):
        for runs, result in (([run(5, "Nix Eval", conclusion="failure"), run(7, "Nix Eval")],
                              "passed"),
                             ([run(7, "Nix Eval", conclusion="failure"), run(5, "Nix Eval")],
                              "failed")):
            with self.subTest(result=result):
                self.world.verification_ready(checks=[{"context": "Nix Eval", "app_id": None}],
                                              runs=runs)
                self.assertEqual(observe()["result"], result)

    def test_a_required_app_id_must_match(self):
        self.world.verification_ready(checks=[{"context": "Nix Eval", "app_id": 15368}],
                                      runs=[run(1, "Nix Eval", app=999)])
        receipt = observe()
        self.assertEqual((receipt["result"], receipt["checks"][0]["status"]), ("pending", "missing"))


class RefusalTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def assertRefused(self, code):
        with self.assertRaises(verification.VerificationRefused) as caught:
            observe()
        self.assertEqual(caught.exception.code, code)
        self.assertLessEqual(len(caught.exception.detail), 240)

    def test_a_moved_integration_tip_is_stale_and_reads_nothing_else(self):
        self.world.verification_ready(tip="9" * 40)
        self.assertRefused("candidate_stale")
        self.assertEqual(len(self.world.calls()), 1)

    def test_an_unestablished_floor_is_unavailable(self):
        for name, kwargs in (("protection 404", {"protection_exit": 1}),
                             ("no required checks", {"checks": [], "runs": []}),
                             ("more than one page", {"total_count": 101})):
            with self.subTest(case=name):
                self.world.reset()
                self.world.verification_ready(**kwargs)
                self.assertRefused("verification_unavailable")

    def test_a_failed_tip_read_is_unavailable(self):
        self.assertRefused("verification_unavailable")

    def test_the_shared_budget_bounds_every_read(self):
        self.world.verification_ready(sleep=2)
        with mock.patch.object(verification, "READ_BUDGET_SECONDS", 1):
            self.assertRefused("verification_unavailable")


if __name__ == "__main__":
    unittest.main()
```

The fake `gh` logs `argv` without the tool name.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m agent_tools.suite_runner tests/test_release_verification.py 2>&1 | tail -4`
Expected: FAIL, `ModuleNotFoundError: No module named 'agent_tools.release_verification'`.

- [ ] **Step 3: Write `release_verification.py`**

Write it to the Interfaces and Invariants above. The design calls that are not obvious:
- Parse each stdout with `json.loads`. Any `ValueError`, `OSError` or
  `subprocess.TimeoutExpired` becomes `VerificationRefused("verification_unavailable",
  "<path>: <reason>"[:240])`.
- Take the matching run's `id` only when it is an `int`. A run without an int `id` never
  matches.
- `canonical_text` is `json.dumps(receipt, sort_keys=True, separators=(",", ":"),
  ensure_ascii=True, allow_nan=False)`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m agent_tools.suite_runner tests/test_release_verification.py tests/test_release_command.py tests/test_forge_adapter.py 2>&1 | tail -4`
Expected: `summary members=3 passed=3 failed=0`. This shows the `ForgeWorld` addition broke no
existing suite.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release_verification.py tests/forge_world.py \
  tests/test_release_verification.py justfile
git commit -m "feat(issue-128/T1): release verification receipt"
```
