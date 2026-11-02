# Task 3: Driver `run` and `abandon`

**Files:**
- Modify: `python/agent_tools/release_driver.py`
- Modify: `tests/release_driver_support.py`
- Modify: `tests/test_release_driver.py`

**Interfaces:**
- Consumes:
  - Task 2's `Driver`, `Refusal`, `token`, `creation_key`, `Project`, `CUSTODY_TTL_MS`,
    `EXECUTOR_ID` and `AUTHORITY_CLASS`, and its preview plan derivation. Refactor that
    derivation into one private method that both `preview` and `run` call, so `run`
    "re-derives the plan exactly as `preview` does" (§5).
  - Task 1's `release_verification.observe`, `evidence_id`, `canonical_text` and
    `VerificationRefused`.
  - `release_adapter.core_binding(adapter, compiled, alias)`.
  - `TransactionStore`'s `create`, `acquire`, `release`, `issue_grant`, `check_grant`,
    `inspect_action`, `invoke_action`, `record_evidence`, `advance`, `start_cohort`,
    `collect_obligation` and `settle_proof`.
  - From `agent_tools.transaction_core`: `CreationConflict`, `LeaseUnavailable`,
    `TransactionBusy`, `GrantInvalid`, `InvocationRefused`, `ProofRefused` and
    `TransactionError`.
- Produces:

```python
GRANT_AUTHORITY = "release-irreversible"
SCOPE_AUTHORITY = "release-scope"
OPERATOR = "operator"
ACTIVATION_NOT_APPLICABLE = "activation-not-applicable"

class Driver:
    def run(self, candidate: Mapping[str, str] | None,
            confirmations: Sequence[str]) -> dict[str, Any]: ...
    # {schema_version, transaction_id, state, next, actions: [{name, status, attempts}],
    #  receipt_digest}; next is "done" | "confirm" | "wait" | "attention"
    def abandon(self) -> dict[str, Any]: ...   # {schema_version, transaction_id, state}
```

- Test support (Task 5 reuses it):
  - `StatefulForge(world)`: a `github-forge` registry entry whose provider state follows
    its own accepted invokes.
  - `NeverVisible(world)`: a `StatefulForge` whose predicate reads are always `unknown`.
  - `release(driver)`: preview, then run with every listed token.

**Invariants** (§5, D6, D7, D14, D20, D21, D25):
- **Router (D20).** It holds one `core_binding(registry[identity["adapter"]], compiled,
  alias)` per `compiled["adapters"]` alias. `inspect` and `invoke` pick the binding by
  `request["parameters"]["action"]`'s node `adapter`, and `observe` picks it by
  `request["collector"]`.
- **Before any write.**
  1. `run` raises `shape_refusal()`.
  2. It derives the plan as `preview` does, and a document refusal is raised as
     `Refusal(code)`.
  3. A supplied token outside the listed set refuses `confirmation_stale`, naming those
     tokens.
  4. A listed token that is not supplied refuses `confirmation_required`, naming the
     actions.

  None of these creates the store root.
- **Setup.**
  - new mode: `store(create=True)`, then `create(creation_key(..., n + 1), …,
    authority_class="release")`.
  - resume mode: the current transaction.
  - Both then `acquire(…, executor_id="release-driver", subject_path=str(project.root),
    ttl_ms=900000)`.
  - `CreationConflict`, `LeaseUnavailable` or `TransactionBusy` at create or acquire is
    `release_busy`.
  - With acquisition ordinal `a`, the count of lease-opening events after `acquire`,
    issue one grant per supplied token `(grant_id=token, actor="operator",
    actor_kind="human", authority_class="release-irreversible")`.
  - Then issue `release-scope:<a>` (authority `release-scope`) only when some compiled
    node's effect is not `irreversible`.
  - From `attention_required`, advance to `parked_from` with reason `resume`.
- **The drive** runs from the current state, and forward and parking advances pass no
  `external_state`:
  - `created → awaiting_verification`.
  - In `awaiting_verification`, with no evidence id starting `verification:`, take the
    receipt: new mode reuses the plan's receipt; resume re-observes the stored candidate.
    A refusal or a non-`passed` result parks `attention_required`, with reason
    `verification: <code or result>` and `next: attention`. Otherwise record
    `record_evidence(evidence_id=evidence_id(r), form="event",
    reference=canonical_text(r))`, then advance `→ ready → publishing`.
  - In `publishing`, run the action loop over the stored `proof_plan["units"]` with
    `phase == "publication"`, in stored order, then advance `→ published`.
  - In `published` with no activation nodes, record `activation-not-applicable`. It is
    `form="event"`, with reference `canonical_text({"activation": "none",
    "profile_digest": d})`, and is skipped when already recorded. Then advance
    `→ proving`. With activation nodes, advance `→ activating`, run the loop over
    `phase == "activation"`, then advance `→ proving`.
  - In `proving`:
    - call `start_cohort`, then `collect_obligation(obligation_id=…, observer=router)`
      for each `proof_plan["obligations"]` entry, then `settle_proof`;
    - `succeeded` gives `done` and `attention_required` gives `attention`; any other
      state gives `wait`;
    - a `ProofRefused` from those calls gives `wait`.
- **The action loop** (per unit):
  1. Call `inspect_action`. `satisfied` moves on; `in_progress` or `unknown` gives `wait`;
     `diverged` parks with reason `<name>: diverged`.
  2. When the node's effect is `irreversible`, call `check_grant(custody, token(plan_digest,
     name, attempts + 1, a))`. `GrantInvalid` gives `confirm`, with no park.
  3. Call `invoke_action`. `InvocationRefused` parks with reason
     `<name>: refused <reason>`. Then `satisfied` continues, `in_progress` or `unknown`
     gives `wait`, and `absent` or `diverged` parks with reason `<name>: <status>`.
  4. A park returns `attention`.
- **Ending (D21).** On every normal return, `store.release(custody)` unless the state is
  terminal. Never in a `finally`, so a raised effect leaves custody to lapse.
  `receipt_digest` is `terminal["receipt_digest"]` or `None`.
- **`abandon()`.**
  - With no nonterminal current transaction it refuses `no_release`.
  - It acquires custody (`release_busy` as above) and advances to `abandoned` with reason
    `abandoned by operator` and `external_state="known"`.
  - A `TransactionError` from that advance releases custody and refuses
    `abandon_refused`, with the core's message cut to 240 characters.

- [ ] **Step 1: Extend the support module and write the failing tests**

Append to `tests/release_driver_support.py`:

```python
from agent_tools import forge_adapter
from .forge_world import ROWS

URL = f"https://github.com/{CANONICAL['slug']}/releases/tag/{CANONICAL['tag']}"


class StatefulForge:
    """`github-forge` for registry injection (D20): delegates to the real adapter and,
    after an accepted invoke, makes the provider show what that invoke created."""

    def __init__(self, world) -> None:
        self.world = world
        world.invoke_ready()
        world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        world.not_found("gh", ROWS["release.view"]["argv"][1:])

    def describe(self):
        return forge_adapter.describe()

    def inspect(self, request):
        return forge_adapter.inspect(request)

    def invoke(self, request):
        result = forge_adapter.invoke(request)
        if result["result"] == "accepted":
            self.land(request["operation"])
        return result

    def land(self, operation: str) -> None:
        if operation == "tag":
            self.world.respond_json("gh", ROWS["tag.ref"]["argv"][1:],
                                    {"object": {"type": "tag", "sha": CANONICAL["tag_object"]}})
            self.world.respond_json("gh", ROWS["tag.object"]["argv"][1:],
                                    {"object": {"type": "commit", "sha": CANONICAL["commit"]}})
        elif operation == "release":
            self.world.respond_json("gh", ROWS["release.view"]["argv"][1:],
                                    {"tag_name": CANONICAL["tag"], "draft": False, "html_url": URL})


class NeverVisible(StatefulForge):
    """Publication succeeds, but `publication_visible` never reads satisfied."""

    def inspect(self, request):
        observation = forge_adapter.inspect(request)
        if request.get("kind") == "predicate":
            observation = {**observation, "outcome": "unknown", "reason": "store_unreachable"}
        return observation


def release(driver, candidate_doc=None):
    """Preview, then run with every token the preview lists; returns (preview, run)."""
    shown = driver.preview(candidate_doc)
    return shown, driver.run(candidate_doc, [c["token"] for c in shown["confirmations"]])
```

Append to `tests/test_release_driver.py`. Add `import json`, `release_profile` to the
`agent_tools` import, and `CANONICAL, ROWS` to the `.forge_world` import.

```python
def pushes(world):
    return [c for c in world.calls() if c["argv"] == ROWS["tag.push"]["argv"][1:]]


def creates(world):
    return [c for c in world.calls() if c["argv"][:2] == ["release", "create"]]


class RunTest(DriverCase):
    def forge(self, cls=rs.StatefulForge):
        self.world.verification_ready()
        return self.driver(registry={"github-forge": cls(self.world)})

    def test_a_confirmed_release_publishes_once_and_seals(self):
        driver = self.forge()
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertTrue(result["receipt_digest"].startswith("sha256:"))
        self.assertEqual((len(pushes(self.world)), len(creates(self.world))), (1, 1))
        events = driver.store().load(result["transaction_id"]).events
        def seq(predicate):
            return next(e["seq"] for e in events if predicate(e))
        verification = next(e for e in events if e["type"] == "evidence_recorded"
                            and e["evidence_id"].startswith("verification:"))
        self.assertEqual(json.loads(verification["reference"])["result"], "passed")
        self.assertLess(verification["seq"], seq(lambda e: e.get("to") == "ready"))
        self.assertLess(seq(lambda e: e.get("evidence_id") == "activation-not-applicable"),
                        seq(lambda e: e.get("to") == "proving"))
        self.assertIsNone(driver.store().load(result["transaction_id"]).custody)

    def test_actions_run_in_bind_candidate_order_with_its_parameters(self):
        driver = self.forge()
        _, result = rs.release(driver, rs.candidate())
        declared = [(e["name"], dict(e["parameters"]))
                    for e in driver.store().load(result["transaction_id"]).events
                    if e["type"] == "action_declared"]
        units = release_profile.bind_candidate(driver.compiled, rs.candidate())["proof"]["units"]
        self.assertEqual(declared, [(u["name"], u["parameters"]) for u in units])

    def test_a_diverged_tag_parks_and_is_never_reported_released(self):
        driver = self.forge()
        self.world.respond_json("gh", ROWS["tag.ref"]["argv"][1:],
                                {"object": {"type": "tag", "sha": CANONICAL["tag_object"]}})
        self.world.respond_json("gh", ROWS["tag.object"]["argv"][1:],
                                {"object": {"type": "commit", "sha": "9" * 40}})
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
        status = driver.status()["release"]
        self.assertEqual((status["reason"], status["terminal"]), ("tag: diverged", None))
        self.assertEqual(pushes(self.world), [])

    def test_proof_that_never_converges_parks(self):
        driver = self.forge(rs.NeverVisible)
        _, result = rs.release(driver, rs.candidate())
        for _ in range(4):
            if result["state"] == "attention_required":
                break
            self.clock.advance(120_000)
            result = driver.run(None, [])
        status = driver.status()["release"]
        self.assertEqual((status["state"], status["parked_from"], status["reason"],
                          status["terminal"]),
                         ("attention_required", "proving", "proof_did_not_converge", None))


class RunRefusalTest(DriverCase):
    def setUp(self):
        super().setUp()
        self.registry = {"github-forge": rs.StatefulForge(self.world)}

    def test_missing_partial_or_stale_tokens_write_nothing(self):
        self.world.verification_ready()
        driver = self.driver(registry=self.registry)
        tokens = [c["token"] for c in driver.preview(rs.candidate())["confirmations"]]
        for code, supplied in (("confirmation_required", []),
                               ("confirmation_required", tokens[:1]),
                               ("confirmation_stale", ["tag:000000000000", tokens[1]])):
            with self.subTest(supplied=supplied):
                self.assertRefusal(code, driver.run, rs.candidate(), supplied)
        self.assertFalse((driver.project.common_dir / "agent-release").exists())

    def test_red_or_pending_ci_reserves_no_version(self):
        driver = self.driver(registry=self.registry)
        for code, runs in (("verification_failed",
                            [{"id": 1, "name": "Nix Eval", "status": "completed",
                              "conclusion": "failure", "app": {"id": 15368}}]),
                           ("verification_pending", [])):
            with self.subTest(code=code):
                self.world.verification_ready(runs=runs)
                self.assertRefusal(code, driver.run, rs.candidate(), [])
                self.assertFalse((driver.project.common_dir / "agent-release").exists())
        self.world.verification_ready()
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((driver.current()[0], result["next"]), (1, "done"))

    def test_a_published_version_is_never_reused(self):
        self.world.verification_ready()
        driver = self.driver(registry=self.registry)
        rs.release(driver, rs.candidate())
        self.assertEqual(driver.preview(rs.candidate())["refusal"]["code"], "version_reserved")
        self.assertRefusal("version_reserved", driver.run, rs.candidate(), [])

    def test_live_custody_is_release_busy(self):
        driver = self.driver(registry=self.registry)
        tid = rs.seed(driver)
        driver.store().acquire(tid, executor_id="other", subject_path=str(driver.project.root),
                               ttl_ms=10_000_000)
        tokens = [c["token"] for c in driver.preview(None)["confirmations"]]
        self.assertRefusal("release_busy", driver.run, None, tokens)


class AbandonTest(DriverCase):
    def test_guard_denied_first_action_abandons_and_frees_the_version(self):
        self.world.verification_ready()
        forge = rs.StatefulForge(self.world)
        self.world.invoke_ready(guard_exit=1)
        driver = self.driver(registry={"github-forge": forge})
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
        self.assertEqual(driver.abandon()["state"], "abandoned")
        self.assertEqual(pushes(self.world), [])
        self.world.invoke_ready()
        again = driver.preview(rs.candidate())
        self.assertEqual((again["mode"], again["runnable"]), ("new", True))

    def test_abandon_refuses_after_an_effect_or_with_nothing_to_abandon(self):
        self.assertRefusal("no_release", self.driver().abandon)
        self.world.verification_ready()
        forge = rs.StatefulForge(self.world)
        self.world.invoke_ready(create_exit=1, create_stderr="gh: HTTP 422")
        driver = self.driver(registry={"github-forge": forge})
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual(result["next"], "attention")
        self.assertEqual(len(pushes(self.world)), 1)
        self.assertRefusal("abandon_refused", driver.abandon)
        self.assertEqual(driver.status()["release"]["state"], "attention_required")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m agent_tools.suite_runner tests/test_release_driver.py 2>&1 | tail -4`
Expected: FAIL, `AttributeError: 'Driver' object has no attribute 'run'`, and the Task 2
classes still pass.

- [ ] **Step 3: Implement `run`, the drive, the loop, the router and `abandon`**

Follow the Invariants. The router is a private class in `release_driver.py`. Its
docstring cites D20 and says it adds no seam: fixture adapters enter only through the
`registry` argument.

If the tag reads in `test_a_diverged_tag_parks…` make the forge adapter report another
outcome than `diverged`, make the tag point at another commit the way
`tests/test_forge_adapter.py` builds its `diverged` row. Keep the asserted reason
`tag: diverged`. If `test_proof_that_never_converges_parks` needs a longer cohort spacing,
change only the clock step, up to the profile's `convergence_window_ms` (1,800,000), and
the loop bound, up to `transaction_plan.MAX_COHORT_ATTEMPTS + 1`. The final assertion
stays. If the core's no-effect gate refuses `abandoned` after a guard-refused
attempt, stop and report it: that contradicts D14's grounding and needs a ledger row, not
a workaround.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m agent_tools.suite_runner tests/test_release_driver.py tests/test_release_adapter_core.py 2>&1 | tail -4`
Expected: `summary members=2 passed=2 failed=0`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release_driver.py tests/release_driver_support.py \
  tests/test_release_driver.py
git commit -m "feat(issue-128/T3): release driver run and abandon"
```
