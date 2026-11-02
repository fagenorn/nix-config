# Task 2: Schema 10: remainder custody, span claims, the capacity wake and the decision cases

The settle step of `commit_state` starts feeding the planner Task 1's inputs: remainders get custody, a held claim becomes a claim entry on its launch's span, an `owner_unavailable` release closes the span, the write that frees capacity wakes a `host_capacity` suspension, and a record of a delivered issue gives its launch span up. The schema becomes 10 and the 9 → 10 bind is that same step. Control still decides from the ledger (Task 3) and no new seal is applied (Task 6). The task also adds AC3's check, one twin-run case per control decision, which every later task keeps green. Decisions: D1, D3, D4, D7, D12, D13, D15–D17, D19, D20, D22, D23, D25.

**Files:**
- Modify: `python/agent_tools/attempt_store.py`
- Modify: `python/agent_tools/attempt_identity.py` (`_MAX_SCHEMA_VERSION = 10`, `schema_refusal`'s docstring)
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`SCHEMA_VERSION`, `commit_state`, `transact`, the bind site of `command_direct_owner`, `validate_state`'s docstring)
- Create: `home/common/agent-skills/tests/test_control_cutover.py`, `home/common/agent-skills/tests/test_control_decisions.py`
- Modify: `justfile` (both new files after `test_attempt_custody.py` in `agent-workflow-tests`)
- Modify (floor, D16 and D22 only): `home/common/agent-skills/tests/test_workflow_state.py`, `test_attempt_migration.py`, `test_attempt_custody.py`, `test_delivery_workflow.py`, `test_host_admission.py`, `tests/test_attempt_identity.py`

**Interfaces:**
- Consumes (Task 1): `settle_plan`'s new keywords, `held_claim`, `owner_gone`, `gate_open`, `claim_id`, `span_epoch`, and the remainder functions of `attempt_delivery`.
- Produces in `agent_tools.attempt_store`:
  - `CORE_STATE_SCHEMA_VERSION = 10`
  - `LockedRead(state, identity, changed, bound_launches, bound_remainders)`: `bound_remainders` is `plan_remainder_migration` of a document stored below schema 10, else `{}`; `bound_launches` is package 2's plan for one stored below schema 9, else `{}`
  - `remainder_custody_of(store: Path, run: str, issue: int, remainder: int) -> Transaction | None`, `custody_of`'s twin
  - `settle_custody(store, state, *, now_ms, canonical, bound_launches, bound_remainders, report=None, delivered: frozenset[int] = frozenset()) -> list[PendingSeal]`
- Produces in `workflow-state.py`: `SCHEMA_VERSION = 10`; `commit_state(run_dir, state_path, state, *, run_id, identity, bound_launches=None, bound_remainders=None, report=None)`.
- Produces in `test_control_cutover.py`: the `Cutover` mixin and `BASE_COMMIT`, `RUN_ID`, `MERGED`, `ROLES`, `BOTH`, which Tasks 3 to 6 use; in `test_control_decisions.py`: `DecisionTest`.

**Invariants:**
- **Schema.** A stored schema-10 document is current. A schema-9 one is validated as its schema-10 candidate and planned, with `changed` set; its dry-run row is `migrate` with no new field or reason, and `migrate --apply` reports it `migrated`. Older documents compose through 8 → 9 first. `locked_read`, `check_unlocked` and `_row_verdict` agree. A repeated `migrate --apply` changes no byte under `.superpowers`, and the package-2 helper exits 2 on a schema-10 ledger without writing.
- **Planning.** The settle step plans every attempt, then every remainder, of each issue. A record is `latest` when no attempt or remainder of its issue follows it (D23). Each plan gets `claim=held_claim(admission, current)`, `owner_gone=owner_gone(admission, current)`, `gate_open=gate_open(admission["claims"], current)` (None or false when `admission` is None) and `delivered=issue in delivered`.
- **Remainder custody.** Key `remainder_key(run, issue, n)`, arguments `attempt_custody.creation_arguments(subject)`, launch `remainder_launch_id(issue, n, len(launches))`. Subject: `worktree` is `canonical(record["worktree"])`; `prior` is the custody transaction of attempt `source_attempt` for remainder 1 and of remainder `n - 1` otherwise (one created earlier in the same settle counts; null when that record has none); `bound_launch` is `bound_remainders.get((issue, n))`. A remainder carries no owner report. A live remainder recorded at another worktree than its subject's is the `custody projection mismatch` an attempt gets.
- A record that ends in the write that launches its successor gives the worktree up before the successor acquires: the preflight's rule for a holder whose own plan ends its span covers attempt-to-remainder and remainder-to-remainder (D3).
- **Applying.** `claim` is `record_evidence(custody, evidence_id=claim_id(executor, span_epoch(custody)), form="snapshot", reference=op.reference)` on the span the plan holds then. `unpark` advances to `created` with the operation's reason. A `seal_succeeded` operation is not applied in this task and yields no pending seal.
- `commit_state` passes `delivered`: the issues whose entry `_delivery().delivery_complete(...)` answers true for. `pending_seals` and `transact`'s unchanged-repeat path keep their behaviour and plan with `delivered` empty.
- Replies are unchanged: `test_admission_replay.py` passes unedited on its committed baseline.
- **Decision cases** (D13, D20). One test method per row of the spec's decision table, named by its number. Each runs its commands twice in one root: on the whole package-2 helper extracted from `BASE_COMMIT`, then, after `.superpowers` is removed, on this checkout's. The replies are validated at the `workflow-response` boundary and compared as bytes once every minted run id is replaced. Store assertions read the head pass, which runs last. Row 7 is a dead owner's merged attempt reconciled while no capacity is left for its remainder; row 5 takes remainder 1 to the merge stage before it fails, so its recovery proof names a stage with a scope (D19).

- [ ] **Step 1: Write the failing tests**

Create `home/common/agent-skills/tests/test_control_cutover.py`:

```python
"""Control-plane cutover to core state (#339), through the CLI from source.

Run: just agent-workflow-tests
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools import attempt_custody as ac
from agent_tools import attempt_delivery as ad

from .test_attempt_custody import DeliveredCustody
from .test_delivered_control import DELIVERED, DISPATCH, LIVE, at
from .test_delivery_workflow import WORKFLOW

REPO = Path(__file__).resolve().parents[4]
BASE_COMMIT = "079b835c54fabe6baf550097c40debc595a81bda"
RUN_ID = re.compile(rb"rel_[0-9a-f-]{36}")
MERGED = {"state": "merged", "url": f"https://github.com/fagenorn/nix-config/pull/{DELIVERED}",
          "merge_sha": "b" * 40}
ROLES = {"owner": 1, "reviewer": 1, "worker": 1}
MATCHING = {DELIVERED: "matching_issue_branch"}
BOTH = {**MATCHING, LIVE: "matching_issue_branch"}


class Cutover(DeliveredCustody):
    """`DeliveredCustody` over either helper generation: `cli` runs this checkout's helper
    ("head") or the whole package-2 helper extracted from `BASE_COMMIT` ("base", D16)."""

    generation = "head"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        found = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                                f"{BASE_COMMIT}^{{commit}}"], capture_output=True)
        if found.returncode != 0:
            raise AssertionError(
                f"base commit {BASE_COMMIT} is missing; fetch it, do not skip (D16)")
        cls.base = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.base, True)
        archive = subprocess.run(
            ["git", "-C", str(REPO), "archive", BASE_COMMIT, "python/agent_tools",
             "home/common/agent-skills/scripts",
             "home/common/agent-skills/artifact-budget-policy.json"],
            capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(cls.base)], input=archive.stdout, check=True)

    def cli(self, *args, stdin=None, ok=True, cwd=None):
        if self.generation == "head":
            return super().cli(*args, stdin=stdin, ok=ok, cwd=cwd)
        completed = subprocess.run(
            [sys.executable, str(self.base / WORKFLOW.relative_to(REPO)), *map(str, args)],
            input=stdin, capture_output=True, check=False, cwd=cwd,
            env={**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONPATH": str(self.base / "python")})
        if ok:
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        return completed

    def declare(self, slots):
        (self.home / ".agents/share/host-declaration.json").write_text(json.dumps(
            {"schema_version": 1, "routes": {
                "claude-code": {"support": "supported", "agent_slots": slots},
                "codex": {"support": "unsupported"}}}), encoding="utf-8")

    def transaction(self, key):
        identity = self.core().lookup(key)
        return None if identity is None else self.core().load(identity)

    def remainder(self, issue, ordinal=1):
        return self.transaction(ad.remainder_key(
            self.ledger_document()["transaction_id"], issue, ordinal))

    def delivery(self, issue, ordinal=1):
        digest = self.ledger_document()["issues"][str(issue)]["delivery"]["contract_digest"]
        return self.transaction(ad.delivery_key(issue, digest, ordinal))

    def claim_ids(self, transaction):
        return [entry["evidence_id"] for entry in transaction.evidence
                if entry["evidence_id"].startswith("admission-claim:")]

    def launched(self, reply):
        return [a["custody"]["action_id"] for a in reply["actions"] if a["kind"] in DISPATCH]

    def reason(self, transaction):
        """The reason of the transaction's last lifecycle transition."""
        return [event["reason"] for event in transaction.events
                if event["type"] == "transitioned"][-1]

    def sweep(self, minute, *, forge=None, observations=None, max_parallel=2, ok=True,
              **kwargs):
        """One control sweep as bytes in, completed process out; `kwargs` as `request`."""
        request = json.loads(self.request(minute, **kwargs))
        request["max_parallel"] = max_parallel
        for issue, fact in (forge or {}).items():
            request["forge"][str(issue)] = fact
        for issue, items in (observations or {}).items():
            request["delivery_observations"][str(issue)] = items
        return self.cli("control", *self.run_args, "--request-file", "-",
                        stdin=json.dumps(request).encode(), ok=ok)

    def reply(self, minute, **kwargs):
        return json.loads(self.validated("workflow-response",
                                         self.sweep(minute, **kwargs).stdout))

    def held(self, state="unavailable", issue=LIVE, launch=1):
        return {"event_id": f"{issue}-{state}-{launch}", "issue": issue, "state": state,
                "custody": {"kind": "implementation", "attempt": 1, "launch": launch,
                            "action_id": f"{issue}:1:{launch}"}}

    def failing(self, action_id, minute):
        """The owner of launch `action_id` reports `failed` before selecting an output."""
        issue, attempt, launch = action_id.split(":")
        custody = {"kind": "implementation", "attempt": int(attempt), "launch": int(launch),
                   "action_id": action_id}
        return self.finish(self.summary(custody, "failed"), minute)

    def select(self, minute):
        """Observe 207's selected output through a sweep, so `deliver` can follow."""
        contract = self.built[DELIVERED]["contract"]
        self.selection = self.build("selected-output", {
            "contract": contract, "head": "a" * 40, "tree": "c" * 40,
            "acceptance_ref": f".claude/specs/issue-{DELIVERED}.md", "review_ref": "clean",
            "test_ref": "checks"})
        selected = self.observed(contract, at(minute), "selected_output",
                                 selection=self.selection)
        return self.sweep(minute, recorded=MATCHING, contracts=True,
                          observations={DELIVERED: [selected]})

    def rewrite(self, change):
        """Edit the stored ledger by hand, in the helper's own serialization."""
        document = self.ledger_document()
        change(document)
        self.ledger.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8")

    def four_slots(self):
        """Two issues on a four-slot route: 207 is launched and 209 waits for a role set."""
        self.setup_run()
        self.declare(4)
        first = self.reply(0, recorded={DELIVERED: None, LIVE: None}, contracts=True)
        self.assertEqual(first["admission"]["waiting"], [LIVE])

    def reconciled(self):
        """207 is spawned under a contract and merged on the forge by minute 31: that sweep
        reconciles attempt 1 and launches remainder r1, whose custody is returned."""
        self.spawn(DELIVERED)
        reply = self.reply(31, recorded=MATCHING, forge={DELIVERED: MERGED})
        (custody,) = [a["custody"] for a in reply["actions"] if a["kind"] in DISPATCH]
        self.assertEqual(custody["action_id"], f"{DELIVERED}:r1:1")
        return custody

    def delivered(self):
        """`reconciled`, then remainder r1 selects an output and completes the delivery."""
        custody = self.reconciled()
        self.select(32)
        self.deliver(custody, at(33))


class SpanClaimTest(Cutover, unittest.TestCase):
    def test_an_unavailable_owner_gives_its_span_up_in_that_write(self):
        self.spawn(DELIVERED, LIVE)
        withheld = self.reply(5, recorded=BOTH, owners=[self.held()], max_parallel=1)
        self.assertEqual(self.launched(withheld), [])
        released = {claim["holder"]: claim["release_event"]
                    for claim in self.ledger_document()["admission"]["claims"]}
        self.assertEqual((self.records(LIVE)[0][0]["state"], released[f"{LIVE}:1:1"]),
                         ("active", "owner_unavailable"))
        gone = self.custody(LIVE)
        self.assertEqual((gone.state, gone.custody, self.lease(self.worktrees[LIVE])["holder"]),
                         ("created", None, None))
        taken = self.reply(6, recorded=BOTH, owners=[self.held()])
        self.assertEqual(self.launched(taken), [f"{LIVE}:1:2"])
        held = self.custody(LIVE)
        self.assertEqual((held.custody.executor_id, self.claim_ids(held)[-1]),
                         (f"{LIVE}:1:2", f"admission-claim:{LIVE}:1:2:2"))

    def test_a_delivered_record_holds_no_span(self):
        self.delivered()
        held = self.remainder(DELIVERED)
        self.assertIsNotNone(held)
        self.assertEqual((self.records(DELIVERED)[1][0]["state"], held.custody,
                          self.lease(self.worktrees[DELIVERED])["holder"]),
                         ("active", None, None))


class CapacityWakeTest(Cutover, unittest.TestCase):
    def refused(self):
        custody = self.spawn(DELIVERED, LIVE)
        reply = self.reply(1, recorded=BOTH, owners=[self.held("launch_refused")])
        self.assertEqual(reply["admission"]["waiting"], [LIVE])
        return custody

    def test_ac2_a_refused_launch_parks_and_the_freeing_write_wakes_it(self):
        self.refused()
        parked = self.custody(LIVE)
        self.assertEqual((parked.state, parked.custody, self.reason(parked)),
                         ("attention_required", None, "suspended:host_capacity"))
        before = self.tree()
        self.assertEqual(self.reply(2, recorded=BOTH)["admission"]["waiting"], [LIVE])
        self.assertEqual(self.tree(), before)
        self.failing(f"{DELIVERED}:1:1", 3)  # another owner's exit frees capacity
        woken = self.custody(LIVE)
        self.assertEqual((woken.state, woken.custody, self.reason(woken)),
                         ("created", None, "capacity_released"))
        resumed = self.reply(4, recorded=BOTH)
        self.assertIn(f"{LIVE}:1:2", self.launched(resumed))
        self.assertEqual(self.custody(LIVE).custody.executor_id, f"{LIVE}:1:2")

    def test_ac2_a_waiting_issue_spends_nothing_and_is_admitted_when_the_span_closes(self):
        self.four_slots()
        held = self.custody(DELIVERED)
        self.assertEqual((held.custody.executor_id, self.claim_ids(held)),
                         (f"{DELIVERED}:1:1", [f"admission-claim:{DELIVERED}:1:1:1"]))
        document = self.ledger_document()
        self.assertIsNone(self.core().lookup(
            ac.creation_key(document["transaction_id"], LIVE, 1)))
        self.assertFalse(document["issues"].get(str(LIVE), {"attempts": []})["attempts"])
        before = self.tree()
        waiting = {DELIVERED: "matching_issue_branch", LIVE: None}
        idle = self.reply(1, recorded=waiting, contracts=True)
        self.assertEqual((idle["admission"]["waiting"], self.tree()), ([LIVE], before))
        self.select(2)
        self.deliver({"kind": "implementation", "attempt": 1, "launch": 1,
                      "action_id": f"{DELIVERED}:1:1"}, at(3))
        self.assertIsNone(self.custody(DELIVERED).custody)  # closed by the owner's command
        admitted = self.reply(4, recorded={DELIVERED: "absent", LIVE: None}, contracts=True,
                              closed={DELIVERED})
        self.assertEqual(self.launched(admitted), [f"{LIVE}:1:1"])

    def test_ac2_check_launch_prints_the_base_bytes_and_touches_nothing(self):
        self.generation = "base"
        self.spawn(DELIVERED)
        elsewhere = ("--repo-root", self.root, "--run-id",
                     "rel_01890a5d-ac96-774b-bcce-b302099a8057")
        probes = [(self.run_args, f"{DELIVERED}:1:1"), (self.run_args, "999:1:1"),
                  (self.run_args, f"{DELIVERED}:2:1"), (elsewhere, f"{DELIVERED}:1:1")]

        def answers():
            return [self.cli("check-launch", *run, "--action-id", action).stdout
                    for run, action in probes]

        expected, before = answers(), self.tree()
        self.generation = "head"
        self.assertEqual((answers(), self.tree()), (expected, before))  # a schema-9 ledger
        self.cli("migrate", "--repo-root", self.root, "--apply")
        self.assertEqual(self.ledger_document()["schema_version"], 10)
        bound = self.tree()
        self.assertEqual((answers(), self.tree()), (expected, bound))


class SchemaTenTest(Cutover, unittest.TestCase):
    def migrate(self, *flags):
        return json.loads(self.cli("migrate", "--repo-root", self.root, *flags).stdout)

    def schema_nine(self, fixture):
        """Run `fixture` on the package-2 helper and return to this one (D16)."""
        self.generation = "base"
        fixture()
        self.generation = "head"
        self.assertEqual(self.ledger_document()["schema_version"], 9)

    def test_ac4_the_bind_is_dry_run_first_and_the_base_helper_refuses_schema_10(self):
        def fixture():
            self.spawn(DELIVERED, LIVE)
            self.reply(1, recorded=BOTH, owners=[self.held("launch_refused")])

        self.schema_nine(fixture)
        before = self.tree()
        (row,) = self.migrate()["ledgers"]
        self.assertEqual((row["schema_version"], row["verdict"], row["reason"]),
                         (9, "migrate", None))
        self.assertEqual(self.tree(), before)
        (row,) = self.migrate("--apply")["ledgers"]
        self.assertEqual((row["schema_version"], row["verdict"]), (10, "migrated"))
        self.assertEqual(self.claim_ids(self.custody(DELIVERED)),
                         [f"admission-claim:{DELIVERED}:1:1:1"])
        self.assertEqual(self.custody(LIVE).state, "attention_required")
        bound = self.tree()
        self.assertEqual(self.migrate("--apply")["ledgers"][0]["verdict"], "current")
        self.assertEqual(self.tree(), bound)
        self.generation = "base"
        for command in (("check-launch", "--action-id", f"{DELIVERED}:1:1"),
                        ("register-worker", "--action-id", f"{DELIVERED}:1:1", "--now", at(2))):
            with self.subTest(command=command[0]):
                refused = self.cli(command[0], *self.run_args, *command[1:], ok=False)
                self.assertEqual(refused.returncode, 2, refused.stdout)
                self.assertIn(b"unknown_schema", refused.stderr)
                self.assertEqual(self.tree(), bound)

    def test_the_bind_gives_a_live_remainder_custody_at_its_launch_count(self):
        self.schema_nine(self.reconciled)
        self.assertIsNone(self.remainder(DELIVERED))
        self.migrate("--apply")
        held = self.remainder(DELIVERED)
        self.assertIsNotNone(held)
        self.assertEqual((held.subject["bound_launch"], held.custody.executor_id, held.state),
                         (1, f"{DELIVERED}:r1:1", "created"))
        self.assertEqual(self.claim_ids(held), [f"admission-claim:{DELIVERED}:r1:1:2"])
```

Create `home/common/agent-skills/tests/test_control_decisions.py`:

```python
"""One case per control decision of the current control interface (#339 AC3, D13): the
reply equals the package-2 helper's in the same root (D20), and the store is read back.

Run: just agent-workflow-tests
"""

import json
import os
import shutil
import unittest

from agent_tools import attempt_custody as ac
from agent_tools import attempt_delivery as ad

from .test_control_cutover import BOTH, MATCHING, MERGED, ROLES, RUN_ID, Cutover
from .test_delivered_control import DELIVERED, DISPATCH, LIVE, at

FIRST, SECOND = f"{DELIVERED}:1:1", f"{LIVE}:1:1"


class DecisionTest(Cutover, unittest.TestCase):
    def twin(self, scenario, slots=7):
        """Run `scenario` (it returns completed commands) on both generations and compare;
        the head pass's replies, decoded. The head pass runs last, so the store is its."""
        self.setup_run()
        replies = {}
        for generation in ("base", "head"):
            self.generation = generation
            shutil.rmtree(self.root / ".superpowers")
            self.declare(slots)
            minted = json.loads(self.cli("init-run", "--repo-root", self.root,
                                         "--creation-key", "twin", "--now", at(0)).stdout)
            self.run_args = ("--repo-root", self.root, "--run-id", minted["run_id"])
            self.ledger = (self.root / ".superpowers/workflows" / minted["run_id"]
                           / "state.json")
            replies[generation] = [
                RUN_ID.sub(b"RUN", self.validated("workflow-response", done.stdout))
                for done in scenario()]
        self.assertEqual(replies["head"], replies["base"])
        return [json.loads(raw) for raw in replies["head"]]

    def spawned(self, *issues, **kwargs):
        return self.sweep(0, recorded=dict.fromkeys(issues), contracts=True, **kwargs)

    def dispatched(self, reply):
        return [(a["kind"], a["custody"]["action_id"]) for a in reply["actions"]
                if a["kind"] in DISPATCH]

    def deltas(self, reply):
        return [(d["issue"], d["kind"], d["state"]) for d in reply["deltas"]]

    def run_id(self):
        return self.ledger_document()["transaction_id"]

    def unsealed_retry(self):
        return [self.spawned(DELIVERED), self.failing(FIRST, 3), self.sweep(4, recorded=MATCHING),
                self.failing(f"{DELIVERED}:2:1", 5), self.sweep(6, recorded=MATCHING)]

    def test_01_spawn(self):
        (reply,) = self.twin(lambda: [self.spawned(DELIVERED)])
        self.assertEqual((self.dispatched(reply), self.deltas(reply)),
                         ([("spawn", FIRST)], [(DELIVERED, "spawned", "active")]))
        held = self.custody(DELIVERED)
        self.assertEqual((held.custody.executor_id, self.claim_ids(held)),
                         (FIRST, [f"admission-claim:{FIRST}:1"]))
        (claim,) = [e for e in held.evidence if e["evidence_id"].startswith("admission-")]
        self.assertEqual((claim["form"], json.loads(claim["reference"])),
                         ("snapshot", {"roles": ROLES, "route": "claude-code"}))

    def test_02_resume(self):
        reply = self.twin(lambda: [self.spawned(DELIVERED), self.sweep(31, recorded=MATCHING)])[-1]
        self.assertEqual(self.dispatched(reply), [("resume", f"{DELIVERED}:1:2")])
        self.assertIn((DELIVERED, "resumed", "active"), self.deltas(reply))
        held = self.custody(DELIVERED)
        self.assertEqual((held.state, held.custody.executor_id, ac.span_epoch(held.custody),
                          self.claim_ids(held)[-1:]),
                         ("created", f"{DELIVERED}:1:2", 2,
                          [f"admission-claim:{DELIVERED}:1:2:2"]))
        # The earlier launch's claim is void: a snapshot does not outlive its fence.
        self.assertEqual([e["admissible"] for e in held.evidence
                          if e["evidence_id"].startswith("admission-")], [False, True])

    def test_03_retry(self):
        reply = self.twin(lambda: [self.spawned(DELIVERED), self.failing(FIRST, 3),
                                   self.sweep(4, recorded=MATCHING)])[-1]
        self.assertEqual((self.dispatched(reply), self.deltas(reply)), (
            [("retry", f"{DELIVERED}:2:1")], [(DELIVERED, "retried", "active")]))
        first, second = self.custody(DELIVERED), self.custody(DELIVERED, 2)
        self.assertEqual((first.state, second.subject["prior"], second.state,
                          second.custody.executor_id, self.claim_ids(second)),
                         ("abandoned", first.transaction_id, "created", f"{DELIVERED}:2:1",
                          [f"admission-claim:{DELIVERED}:2:1:2"]))

    def test_04_remainder_launch(self):
        reply = self.twin(lambda: [self.spawned(DELIVERED), self.sweep(
            31, recorded=MATCHING, forge={DELIVERED: MERGED})])[-1]
        self.assertEqual(self.dispatched(reply), [("delivery_remainder", f"{DELIVERED}:r1:1")])
        attempt, held = self.custody(DELIVERED), self.remainder(DELIVERED)
        self.assertIsNotNone(held)
        self.assertEqual(dict(held.subject), ad.remainder_subject(
            run=self.run_id(), issue=DELIVERED, remainder=1, prior=attempt.transaction_id,
            worktree=os.path.realpath(self.worktrees[DELIVERED]), bound_launch=None))
        self.assertEqual((attempt.custody, held.custody.executor_id, self.claim_ids(held)),
                         (None, f"{DELIVERED}:r1:1", [f"admission-claim:{DELIVERED}:r1:1:2"]))
        self.assertEqual(self.lease(self.worktrees[DELIVERED])["holder"]["transaction_id"],
                         held.transaction_id)

    def recovery(self):
        contract = self.built[DELIVERED]["contract"]
        scope = self.build("scope", {"contract": contract, "stage_id": "merge_pr"})

        def evidence(kind, minute, digit):
            return {"source_kind": kind, "reference": f"{kind}:probe", "observed_at": at(minute),
                    "evidence_digest": "sha256:" + digit * 64}

        proof = {"schema_version": 1, "kind": "delivery-recovery", "id": "",
                 "contract_digest": self.model.canonical_digest(contract),
                 "stage_id": "merge_pr", "requested_scope": scope,
                 "failure": {"kind": "effect_failure", "effect_attempted": True,
                             "classification": "transient", **evidence("host", 39, "4")},
                 "effect_absence": {"kind": "effect_absence", "absent": True,
                                    "probe_succeeded": True, **evidence("filesystem", 41, "5")},
                 "basis": {"kind": "changed_relevant_evidence", "scope_id": scope["id"],
                           **evidence("tracker", 42, "6")}}
        proof["id"] = self.model.canonical_digest(proof, omit_derived="id")
        return proof

    def test_05_recover(self):
        def scenario():
            custody, sweeps = self.reconciled_twin()
            self.merge_checkpoint(custody, 33)  # r1 reaches the merge stage, then fails
            return [*sweeps, self.finish(self.summary(custody, "failed"), 40),
                    self.sweep(43, recorded=MATCHING, contracts=True,
                               recoveries={DELIVERED: self.recovery()})]

        reply = self.twin(scenario)[-1]
        self.assertEqual(self.dispatched(reply), [("delivery_remainder", f"{DELIVERED}:r2:1")])
        first, second = self.remainder(DELIVERED), self.remainder(DELIVERED, 2)
        self.assertIsNotNone(second)
        self.assertEqual((first.state, second.subject["prior"], second.custody.executor_id),
                         ("abandoned", first.transaction_id, f"{DELIVERED}:r2:1"))

    def reconciled_twin(self):
        """`reconciled` as scenario steps: (r1's custody, the two completed sweeps)."""
        first = self.spawned(DELIVERED)
        second = self.sweep(31, recorded=MATCHING, forge={DELIVERED: MERGED})
        (custody,) = [a["custody"] for a in json.loads(second.stdout)["actions"]
                      if a["kind"] in DISPATCH]
        return custody, [first, second]

    def test_06_refuse(self):
        reply = self.twin(self.unsealed_retry)[-1]
        self.assertEqual((self.dispatched(reply), self.deltas(reply)),
                         ([], [(DELIVERED, "retry_refused", "failed")]))
        self.assertEqual(self.custody(DELIVERED, 2).state, "abandoned")

    def test_07_reconcile(self):
        # A dead owner's merged attempt, with no capacity left for its remainder (D19).
        reply = self.twin(lambda: [self.spawned(DELIVERED, LIVE), self.sweep(
            5, recorded=BOTH, forge={DELIVERED: MERGED}, max_parallel=1,
            owners=[self.held(issue=DELIVERED)])])[-1]
        self.assertEqual((self.dispatched(reply), self.deltas(reply),
                          [summary["state"] for summary in reply["summaries"]]),
                         ([], [], ["merged", "active"]))
        self.assertEqual(self.records(DELIVERED)[0][0]["result_source"], "superseded")
        held = self.custody(DELIVERED)
        self.assertEqual((held.state, held.custody, held.terminal, self.events(DELIVERED)[-1]),
                         ("created", None, None, "lease_released"))

    def test_08_terminal(self):
        def scenario():
            done = self.unsealed_retry()
            self.before = self.tree()
            return [*done, self.sweep(7, recorded=MATCHING)]

        reply = self.twin(scenario)[-1]
        self.assertEqual((self.dispatched(reply), self.deltas(reply), self.tree()),
                         ([], [], self.before))

    def watched(self):
        """A live owner and a sweep with nothing to decide; the tree before that sweep."""
        done = [self.spawned(DELIVERED)]
        self.before = self.tree()
        return [*done, self.sweep(1, recorded=MATCHING)]

    def test_09_idle(self):
        reply = self.twin(self.watched)[-1]
        self.assertEqual((self.dispatched(reply), self.deltas(reply), self.tree()),
                         ([], [], self.before))

    def test_18_wait(self):
        (wait,) = self.twin(self.watched)[-1]["actions"]
        self.assertEqual(
            (wait["kind"], wait["wake_on"], wait["deadline_at"], wait["wait_seconds"]),
            ("wait", ["deadline", "owner_notification", "tracker_change"], at(30), 29 * 60))

    def assert_reaped(self, reply):
        self.assertEqual((self.dispatched(reply), self.deltas(reply)),
                         ([], [(DELIVERED, "expired", "suspended")]))
        held = self.custody(DELIVERED)
        self.assertEqual((held.state, held.custody, self.reason(held), self.events(DELIVERED)[-3:]),
                         ("attention_required", None, "expiry",
                          ["lease_lapse_detected", "stop_synthesized", "transitioned"]))

    def test_10_observe_that_ends_one_resume(self):
        reply = self.twin(lambda: [self.spawned(DELIVERED), self.sweep(
            31, recorded={DELIVERED: "mismatch"})])[-1]
        self.assertIn("worktree_fact",
                      [r["kind"] for r in reply["summaries"][0]["requirements"]])
        self.assert_reaped(reply)

    def test_12_reap_of_an_expired_launch(self):
        late = {DELIVERED: "matching_issue_branch", LIVE: None}
        reply = self.twin(lambda: [
            self.spawned(DELIVERED), self.sweep(10, recorded=late, contracts=True),
            self.sweep(31, recorded=BOTH, max_parallel=1)])[-1]
        self.assert_reaped(reply)

    def test_11_contract(self):
        (reply,) = self.twin(lambda: [self.sweep(0, recorded={DELIVERED: None})])
        self.assertEqual([a["kind"] for a in reply["actions"]], ["delivery_contract"])
        self.assertIn("delivery_contract_required", [
            r.get("reason_code") for r in reply["summaries"][0]["requirements"]])
        digest = self.model.canonical_digest(self.built[DELIVERED]["contract"])
        self.assertEqual((self.custody(DELIVERED), self.transaction(
            ad.delivery_key(DELIVERED, digest, 1))), (None, None))

    def test_13_withheld_for_a_role_set(self):
        (reply,) = self.twin(lambda: [self.spawned(DELIVERED, LIVE)], slots=4)
        self.assertEqual((self.dispatched(reply), reply["admission"]["waiting"]),
                         ([("spawn", FIRST)], [LIVE]))
        self.assertIsNone(self.core().lookup(ac.creation_key(self.run_id(), LIVE, 1)))

    def test_14_withheld_at_max_parallel(self):
        (reply,) = self.twin(lambda: [self.spawned(DELIVERED, LIVE, max_parallel=1)])
        self.assertEqual((self.dispatched(reply), reply["admission"]["waiting"]),
                         ([("spawn", FIRST)], []))
        self.assertIsNone(self.core().lookup(ac.creation_key(self.run_id(), LIVE, 1)))

    def refused(self):
        return [self.spawned(DELIVERED, LIVE),
                self.sweep(1, recorded=BOTH, owners=[self.held("launch_refused")])]

    def test_15_launch_refused(self):
        reply = self.twin(self.refused)[-1]
        self.assertEqual((self.dispatched(reply), reply["admission"]["waiting"]), ([], [LIVE]))
        self.assertEqual(self.records(LIVE)[0][0]["blocked_on"], "host_capacity")
        held = self.custody(LIVE)
        self.assertEqual((held.state, held.custody, self.reason(held)),
                         ("attention_required", None, "suspended:host_capacity"))

    def test_16_gate_opened_by_a_later_release(self):
        reply = self.twin(lambda: [*self.refused(), self.failing(FIRST, 3),
                                   self.sweep(4, recorded=BOTH)])[-1]
        self.assertIn(("resume", f"{LIVE}:1:2"), self.dispatched(reply))
        held = self.custody(LIVE)
        self.assertEqual(
            ([e["reason"] for e in held.events if e["type"] == "transitioned"],
             held.custody.executor_id),
            (["suspended:host_capacity", "capacity_released"], f"{LIVE}:1:2"))

    def test_17_owner_unavailable(self):
        reply = self.twin(lambda: [self.spawned(DELIVERED, LIVE),
                                   self.sweep(5, recorded=BOTH, owners=[self.held()])])[-1]
        self.assertEqual(self.dispatched(reply), [("resume", f"{LIVE}:1:2")])
        released = {claim["holder"]: claim["release_event"]
                    for claim in self.ledger_document()["admission"]["claims"]}
        self.assertEqual(released[SECOND], "owner_unavailable")
        held = self.custody(LIVE)
        reacquired = [e for e in held.events if e["type"] == "lease_reacquired"][-1]
        self.assertEqual((reacquired["reason"], held.custody.executor_id,
                          self.claim_ids(held)[-1:]),
                         ("released", f"{LIVE}:1:2", [f"admission-claim:{LIVE}:1:2:2"]))

    def test_19_finalize(self):
        (reply,) = self.twin(lambda: [self.sweep(0, recorded={DELIVERED: None},
                                                 closed={DELIVERED}, contracts=True)])
        self.assertEqual([a["kind"] for a in reply["actions"]], ["finalize"])
        # The controller's seat has no custody: the run transaction is the store's only one.
        store = self.root / ".superpowers/attempt-transactions"
        self.assertEqual([path.name for path in store.glob("rel_*")], [self.run_id()])
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTEST T/test_control_cutover.py T/test_control_decisions.py` (timeout 900 s)
Expected: FAIL, 26 tests, 14 failures, no error (measured at this task's start). All 7 of `test_control_cutover.py`: on the schema (`9 != 10`, `'current'` for `'migrate'`), a missing claim entry, an open `Custody` for `None`, a remainder custody that is `None`, `'suspended:host_capacity'` for `'capacity_released'`. Of `DecisionTest`: rows 1, 2, 3 and 17 on the missing claim entry, 4 and 5 on the missing remainder custody, 16 on `'resumed'` for `'capacity_released'`; the other twelve pass, because package 2 already has their store effect. A reply mismatch between the two passes, or a fixture command refused before those assertions, is not an expected failure: stop and report it.

- [ ] **Step 3: Implement**

The schema step first; `transact` and the bind site of `command_direct_owner` hand both plans to `commit_state`. Then `_read_plans`, `_new_subject`, `_require_recorded_worktree`, `_preflight` and `_apply`, to the invariants above.

- [ ] **Step 4: Apply the declared floor changes**

Only these (D16, D22): the current schema number where a test pins it (9 becomes 10) and the unknown-schema fixtures (11); and package 2's custody tests that pin event positions or a whole event list on a slot route, where one `evidence_recorded` now follows each acquisition of a claimed launch.

- [ ] **Step 5: Show that the twin comparison can fail**

In `twin`, temporarily append `b" "` to each head reply before the comparison and run `-k test_01_spawn`: it must fail on `replies["head"] != replies["base"]`. Then set `BASE_COMMIT` to forty zeros and rerun: the class must error with `is missing; fetch it, do not skip`. Restore both; `git diff` shows neither change.

- [ ] **Step 6: Verify**

Run: `PYTEST T/test_control_cutover.py T/test_control_decisions.py T/test_attempt_custody.py T/test_attempt_migration.py T/test_admission_replay.py T/test_delivered_control.py T/test_host_admission.py tests/test_attempt_identity.py tests/test_attempt_custody.py`
Expected: `OK`; `test_control_cutover.py` runs 7 tests and `test_control_decisions.py` 19.

Run: `PYTEST T/test_workflow_state.py T/test_delivery_workflow.py`
Expected: `OK`.

Run: `git diff --stat BASE -- T/fixtures T/test_admission_replay.py`
Expected: empty output.

Run the root's review-package budget command for `python/agent_tools/attempt_store.py`, `home/common/agent-skills/scripts/workflow-state.py` and `T/test_workflow_state.py`.
Expected: each at most 60000.

- [ ] **Step 7: Commit**

```bash
git add python home tests justfile
launch-commit … -- -m "feat(attempt-store): schema 10 with remainder custody, span claims and the capacity wake (#339)"
```
