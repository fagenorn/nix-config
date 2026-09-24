# Task 3: Builder evidence kinds and the end-to-end delivery loop

Decisions: D3, D5, D7, D15, D16, D19, D21, D22, D28, D32. Spec §1 (the kind table
and "The observed facts per observation kind"), §6 "Phase-7 handoff" and "The
delivery loop".

**Files:**
- Modify: `S/workflow_delivery_build.py`, `S/workflow-state.py` (`--kind` choices), `S/artifact_budget.py` (the ship-handoff wire bound, D28), `CLAUDE.md` (the Task-2 bullet)
- Test: `T/test_delivery_workflow.py`, `T/test_artifact_budget.py`

**Interfaces:**
- Consumes: Task 2's builder, `BuilderHarness`, `WORKTREE_NAME`, `LATER`; Task 1's
  slot PR binding.
- Produces: `--kind` choices gain `selected-output`, `observation`,
  `authority-observation` (the closed set is now six). `BuilderHarness` gains
  `direct_request(**changes) -> dict` (the 16-key interface-2 request, every fact
  `null`/empty unless changed) and `acquire(contract, intent) -> dict` (direct
  spawn at `self.worktree`, returning the validated `owner` object). Tasks 4–6
  reuse both.

**Invariants (exact builder values, per D5):**
- `selected-output` input is exactly `contract, head, tree, acceptance_ref,
  review_ref, test_ref` (non-empty strings). Output: `slot_id "reviewed"`,
  `subject_kind "commit"`, `subject_value head`, `data_identity_digest =
  canonical_digest({"kind": "git-tree", "value": tree})`, repository/branch/base
  from the contract, `evidence_digest = canonical_digest({"head", "acceptance_ref",
  "review_ref", "test_ref"})`, evidence ids `[f"acceptance:{acceptance_ref}@{head}"]`,
  `[f"review:{review_ref}@{head}"]`, `[f"test:{test_ref}@{head}"]`.
- `observation` input is exactly `contract, observation_kind, source_kind,
  source_reference, observed_at, evidence` plus that kind's facts, flat:
  `branch_published {head}`; `pr_opened {pr_number, pr_url, head}`; `pr_merged
  {pr_number, pr_url, head, merge_sha}` (adds `merged: true`); `tracker_closed
  {close_reason (string or null), observation_identity}`; `remote_branch_absent`,
  `local_branch_absent`, `worktree_absent {}`; `selected_output {selection}`;
  `implementation_delivered {selection, merge_sha, integrated_ref,
  merge_observation_id}`; `cleanup_complete {remote_branch_observation_ids,
  local_branch_observation_ids, worktree_observation_ids, detail_pointer,
  read_evidence}`. Any other kind (including `repository_record_proposed`) refuses.
- Every contract-determined member is filled from the contract: `project`,
  repository ids (`repository_id`, `provider_repository_id`,
  `tracker_repository_id`), `branch`, `base`, `issue`, and for `worktree_absent`
  `path = recorded_worktree_identity =` the `remove_worktree` literal with
  `probe_mode "no_follow"`, `absent true`. `evidence_digest = "sha256:" +
  sha256(evidence.encode("utf-8")).hexdigest()`; `cleanup_complete`'s
  `read_evidence_digest` is derived from `read_evidence` the same way.
- `implementation_delivered`: `selected_subject {kind: selection.subject_kind,
  value: selection.subject_value}`, `integration_subject {same kind, value:
  merge_sha}`, `presence {kind "reachability", repository_id, selected_value,
  integration_value: merge_sha, integrated_ref, succeeded true}`, evidence ids
  copied from the selection. A selection whose `contract_digest` differs refuses.
- `authority-observation` input is exactly `contract, scope_id, launch_id,
  authority_kind (native_guard|host|provider), verdict (allowed|rejected|unknown),
  reason_code, observed_at, evidence`; `scope_id` must be one of the contract's
  builder scope ids; `opaque_host_reference`, `revocation_subject` and
  `evaluation_use_key` are `null`. `intent_revocation` refuses (revocation tooling
  is out of scope).
- The loop needs no successor intent: the stored chain keeps exactly one intent.
- `validate-report --boundary ship-handoff` reads under
  `workflow_responses.wire_max_bytes`, like `workflow-response`; the other
  delivery boundaries keep the phase-report bound (D28).
- Refusal subTests assert each case's stderr fragment (D32).

- [ ] **Step 1: Write the failing tests**

Add to `BuilderHarness`:

```python
    def direct_request(self, **changes):
        value = {"interface_version": 2, "issue": 171, "now": NOW,
            "attempt_budget_minutes": 30, "new_run": False, "owner_unavailable": False,
            "tracker": None, "worktree": None, "forge": None, "delivery_contract": None,
            "authorization_intents": [], "authority_observations": [],
            "reevaluation_evidence": [], "delivery_observations": [],
            "requested_scope": None, "recovery": None}
        value.update(changes)
        return value

    def acquire(self, contract, intent):
        request = self.direct_request(
            tracker={"issue": 171, "state": "open", "open_blockers": [],
                     "decision_blockers": []},
            forge={"state": "none", "url": None, "merge_sha": None},
            worktree={"issue": 171, "recorded": None,
                      "candidate": {"path": self.worktree, "state": "absent"}},
            delivery_contract=contract, authorization_intents=[intent])
        owner = json.loads(self.cli("direct-owner", "--repo-root", self.root,
            "--request-file", "-", stdin=json.dumps(request).encode()).stdout)
        self.assertEqual((owner["kind"], owner["worktree"]), ("owner", self.worktree))
        return owner
```

Add this class:

```python
URL = "https://github.com/fagenorn/nix-config/pull/5"
SOURCES = {"selected_output": "repository", "branch_published": "repository",
           "pr_opened": "provider", "pr_merged": "provider", "tracker_closed": "tracker",
           "remote_branch_absent": "repository", "worktree_absent": "filesystem",
           "local_branch_absent": "repository", "implementation_delivered": "repository",
           "cleanup_complete": "filesystem"}


class DeliveryLoopTest(BuilderHarness, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load(MODEL, "delivery_model_loop", package=True)

    def observed(self, kind, **facts):
        return self.build("observation", {"contract": self.contract, "observation_kind": kind,
            "source_kind": SOURCES[kind], "source_reference": f"probe:{kind}",
            "observed_at": NOW, "evidence": f"{kind} evidence", **facts})

    def checkpoint(self, observations, authority, scope, *, ok=True):
        value = {"interface_version": 2, "issue": 171, "custody": self.custody,
            "contract_digest": self.digest,
            "delivery_observations": sorted(observations, key=lambda item: item["id"]),
            "authority_observations": authority, "reevaluation_evidence": [],
            "requested_scope": scope, "detail_state": "none", "report_path": None,
            "notes": ""}
        completed = self.cli("checkpoint-delivery", *self.run_args, "--now", LATER,
                             "--checkpoint-file", "-",
                             stdin=self.validated("ship-checkpoint", value), ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def validated(self, boundary, value):
        """Pipe one wire object through artifact-budget, as an owner must, and return its bytes."""
        completed = subprocess.run(
            [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
             boundary, "--input", "-", "--policy", str(POLICY)],
            input=json.dumps(value).encode(), capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout

    def handoff(self, owner, intent):
        """The Phase-7 ship-handoff/v2 a first ship receives, with realistic artifacts."""
        def artifact(kind, path, size):
            return {"kind": kind, "path": path, "budget_status": "within_budget",
                    "metrics": {"root_bytes": size, "total_bytes": size, "file_count": 1,
                                "largest_member_bytes": size}}
        return {"interface_version": 2, "state": "complete",
            "ledger_repo_root": str(self.root), "run_id": owner["run_id"],
            "owner": owner["owner"], "owner_worktree": self.worktree,
            "custody": self.custody, "issue_number": 171, "branch": WORKTREE_NAME,
            "worktree_path": self.worktree,
            "spec_artifact": artifact("design-spec",
                ".claude/specs/2026-09-23-issue-171-delivery-contract-source-design.md", 47301),
            "plan_artifact": artifact("implementation-plan",
                ".claude/plans/2026-09-24-issue-171-delivery-contract-source.md", 8375),
            "head_sha": "a" * 40, "review_state": "clean", "auto": True,
            "report_path": None, "notes": "", "delivery_contract": self.contract,
            "delivery_contract_digest": self.digest, "authorization_intents": [intent],
            "authorization_chain_digest": self.model.canonical_digest(
                {"intent_ids": [intent["id"]]}),
            "authority_observation_ids": [], "reevaluation_evidence_ids": [],
            "authority_evaluation_consumption_ids": [],
            "pending_stage_ids": [stage["id"] for stage in self.contract["stages"]],
            "selected_outputs": [], "requested_scope": None}

    def deliver(self, proposed):
        """Drive one implementation custody through every stage with builder outputs only."""
        self.project()
        built = self.build("contract", self.contract_input())
        self.contract = built["contract"]; self.digest = self.model.canonical_digest(self.contract)
        owner = self.acquire(self.contract, built["initial_intent"])
        self.custody = owner["custody"]
        self.run_args = ("--repo-root", self.root, "--run-id", owner["run_id"])
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        handed = self.validated("ship-handoff", self.handoff(owner, built["initial_intent"]))
        # A real handoff outgrows the phase-report bound; that is why D28 moves it.
        self.assertGreater(len(handed), policy["phase_reports"]["wire_max_bytes"])
        self.assertLessEqual(len(handed), policy["workflow_responses"]["wire_max_bytes"])
        state = self.root / f".superpowers/workflows/{owner['run_id']}/state.json"
        head, merge_sha = "a" * 40, "b" * 40
        selection = self.build("selected-output", {"contract": self.contract, "head": head,
            "tree": "c" * 40, "acceptance_ref": ".claude/specs/issue-171.md",
            "review_ref": "clean", "test_ref": "checks"})
        self.assertEqual(selection["test_evidence_ids"], [f"test:checks@{head}"])
        facts = {"select_reviewed_output": [self.observed("selected_output", selection=selection)],
            "publish_branch": [self.observed("branch_published", head=head)],
            "open_pr": [self.observed("pr_opened", pr_number=5, pr_url=URL, head=head)],
            "merge_pr": [self.observed("pr_merged", pr_number=5, pr_url=URL, head=head,
                                       merge_sha=merge_sha)],
            "close_tracker": [self.observed("tracker_closed", close_reason="completed",
                                            observation_identity="github:issue:171:closed")],
            "delete_remote_branch": [self.observed("remote_branch_absent")],
            "remove_worktree": [self.observed("worktree_absent")],
            "delete_local_branch": [self.observed("local_branch_absent")]}
        pending, authority = [], []
        for stage in self.contract["stages"]:
            if stage["id"] in proposed:
                scope = self.build("scope", {"contract": self.contract, "stage_id": stage["id"]})
                echoed = self.checkpoint(pending, authority, scope)
                self.assertEqual((echoed["kind"], echoed["requested_scope"]),
                                 ("delivery_checkpointed", scope))
                self.assertEqual(echoed["requirements"], [{"kind": "observation",
                    "subject_id": scope["id"], "reason_code": "native_evaluation_required",
                    "detail_pointer": None}])
                pending, authority = [], [self.build("authority-observation", {
                    "contract": self.contract, "scope_id": scope["id"],
                    "launch_id": self.custody["action_id"], "authority_kind": "native_guard",
                    "verdict": "allowed", "reason_code": "guard_allowed",
                    "observed_at": LATER, "evidence": stage["id"]})]
                if stage["id"] == "merge_pr":
                    before = state.read_bytes()
                    second = self.observed("pr_opened", pr_number=6, pr_url=URL + "6", head=head)
                    refused = self.checkpoint([second], [], None, ok=False)
                    self.assertEqual((refused.returncode, state.read_bytes()), (2, before))
            pending += facts[stage["id"]]
        by_kind = {item["observation_kind"]: item["id"] for items in facts.values() for item in items}
        completing = pending + [
            self.observed("implementation_delivered", selection=selection, merge_sha=merge_sha,
                          integrated_ref="refs/heads/main",
                          merge_observation_id=by_kind["pr_merged"]),
            self.observed("cleanup_complete",
                          remote_branch_observation_ids=[by_kind["remote_branch_absent"]],
                          local_branch_observation_ids=[by_kind["local_branch_absent"]],
                          worktree_observation_ids=[by_kind["worktree_absent"]],
                          detail_pointer=".superpowers/issue-delivery/171/detail.json",
                          read_evidence="detail read")]
        historical = {"issue": 171, "state": "merged", "pr_url": URL, "merge_sha": merge_sha,
            "issue_closed": True, "discussion_items": [], "detail_state": "none",
            "report_path": None, "notes": "delivered"}
        summary = {"interface_version": 2, "issue": 171, "state": "delivery_complete",
            "custody": self.custody, "historical_owner_result": historical,
            "delivery_contract_digest": self.digest,
            "delivery_observations": sorted(completing, key=lambda item: item["id"]),
            "authority_observations": authority, "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "delivered"}
        validated = self.validated("ship-summary", summary)
        self.assertLessEqual(len(validated), policy["phase_reports"]["wire_max_bytes"])
        finished = json.loads(self.cli("finish", *self.run_args, "--now", LATER,
            "--summary-file", "-", stdin=validated).stdout)
        self.assertEqual((finished["kind"], finished["pending_stage_ids"]),
                         ("delivery_complete", []))
        stored = json.loads(state.read_text(encoding="utf-8"))["issues"]["171"]
        self.assertEqual(len(stored["delivery"]["authorization_intents"]), 1)
        self.assertEqual(stored["attempts"][-1]["state"], "merged")

    def test_every_builder_scope_is_covered_when_its_stage_is_ready(self):
        self.deliver({"select_reviewed_output", "publish_branch", "open_pr", "merge_pr",
                      "close_tracker", "delete_remote_branch", "remove_worktree",
                      "delete_local_branch"})

    def test_one_custody_completes_the_selection_gated_loop(self):
        self.deliver({"merge_pr", "close_tracker", "remove_worktree", "delete_local_branch"})

    def test_evidence_kinds_are_exact_and_closed(self):
        self.project()
        self.contract = self.build("contract", self.contract_input())["contract"]
        opened = self.observed("pr_opened", pr_number=5, pr_url=URL, head="a" * 40)
        self.assertEqual(opened["subject"], {"provider_repository_id": "fagenorn/nix-config",
            "pr_number": 5, "pr_url": URL, "expected_head": "a" * 40, "base": "main"})
        self.assertEqual(opened["evidence_digest"],
            "sha256:" + hashlib.sha256(b"pr_opened evidence").hexdigest())
        gone = self.observed("worktree_absent")["subject"]
        self.assertEqual(gone, {"path": self.worktree, "recorded_worktree_identity":
            self.worktree, "probe_mode": "no_follow", "absent": True})
        base = {"contract": self.contract, "source_kind": "provider",
                "source_reference": "probe", "observed_at": NOW, "evidence": "x"}
        for kind, value, reason in (
                ("observation", {**base, "observation_kind": "repository_record_proposed"},
                 b"unsupported observation kind"),
                ("observation", {**base, "observation_kind": "pr_opened", "pr_number": 5},
                 b"builder input keys"),
                ("observation", {**base, "observation_kind": "worktree_absent", "path": "/x"},
                 b"builder input keys"),
                ("authority-observation", {"contract": self.contract, "scope_id": "sha256:" + "0" * 64,
                    "launch_id": "171:1:1", "authority_kind": "host", "verdict": "allowed",
                    "reason_code": "r", "observed_at": NOW, "evidence": "x"},
                 b"unknown scope"),
                ("authority-observation", {"contract": self.contract,
                    "scope_id": self.build("scope", {"contract": self.contract,
                                                     "stage_id": "merge_pr"})["id"],
                    "launch_id": None, "authority_kind": "intent_revocation",
                    "verdict": "revoked", "reason_code": "r", "observed_at": NOW,
                    "evidence": "x"},
                 b"unsupported authority kind")):
            with self.subTest(kind=kind, variant=value.get("observation_kind") or value.get("authority_kind")):
                refused = self.build(kind, value, ok=False)
                self.assertEqual((refused.returncode, refused.stdout), (2, b""))
                self.assertIn(reason, refused.stderr)
```

Add `import hashlib` to the module imports. The reason fragments above extend
Task 2's fixed refusal vocabulary (D32): a kind outside the closed set is
`unsupported observation kind` or `unsupported authority kind`, a scope id the
contract does not seal is `unknown scope`, and a missing or extra fact is Task 2's
`builder input keys`, because a kind's facts are part of its input key set.

In `T/test_artifact_budget.py`, beside `test_workflow_response_takes_its_own_wire_bound`,
add `test_ship_handoff_reads_under_the_response_wire_bound`: the legacy candidate
of `test_ship_handoff_residuals_requires_durable_report_path` with
`review_state "clean"` and `notes "ok"`, its `worktree_path` padded past
`phase_reports.wire_max_bytes`, validates on stdin with exit 0; padded past
`workflow_responses.wire_max_bytes` it exits 2 with `artifact-budget: invalid
report\n`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k DeliveryLoopTest 2>&1 | tail -5`
Expected: ERROR in all three — `selected-output`/`observation` are invalid
`--kind` choices at the starting commit.
Run: `python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py -k ship_handoff_reads 2>&1 | tail -5`
Expected: FAIL — the padded handoff exits 2 under the phase-report bound.

- [ ] **Step 3: Implement**

Extend `DeliveryBuilder.build` with the three kinds exactly as the invariants
state, each output passing `validate_delivery_object` for its kind
(`selected-output`, `delivery-observation`, `authority-observation`) inside
`DeliveryRuntime.build_delivery`, and each refusal naming the rule it broke with
the Invariants' fragments. Observation kinds come from
`STAGE_ACTIONS[*][2]` plus the three postconditions; subjects are built by one
per-kind table in the module, not by branches spread through `build`. Extend
`--kind` `choices`. In `CLAUDE.md`, change the Task-2 bullet's "and seals each
stage's scope." to "and seals each stage's scope, the reviewed selection, every
delivery observation and each authority observation an owner submits, so no
agent composes a digest."

In `S/artifact_budget.py`, give `ship-handoff` the `response_wire_max` bound
beside `workflow-response` (D28).

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py 2>&1 | tail -3` → `OK`.
Run: `python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py 2>&1 | tail -3` → `OK`.
Run: `just agent-workflow-tests 2>&1 | tail -3` → `OK (skipped=1)`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow_delivery_build.py \
  home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/scripts/artifact_budget.py CLAUDE.md \
  home/common/agent-skills/tests/test_delivery_workflow.py \
  home/common/agent-skills/tests/test_artifact_budget.py
git commit -m "feat(workflow-state): build selections and delivery evidence; prove the delivery loop"
```
