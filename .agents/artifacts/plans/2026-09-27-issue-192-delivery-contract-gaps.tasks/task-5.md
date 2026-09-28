# Task 5: The `sync-selection` and `current-selection` builder kinds, and a remainder merges after a sync

Spec §5, T7–T9 and T12, per D8, D10, D11, D14, D15, D17, D21, D24, D25.
`sync-selection` seals each link of a sync run, and `current-selection` serves
the installing ledger's current selection to an owner that did not build it.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow_delivery_build.py`
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `CLAUDE.md`
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py`
- Test: `home/common/agent-skills/tests/test_workflow_delivery.py`

**Interfaces:**
- Consumes (Task 4): `selected-output/v2`, the chain rules and their texts,
  and `current_selection(delivery) -> dict | None`. From Task 1:
  `DeliveryBuilder.build(..., worktree_branch=None)` and the test constants
  `LIVE`, `NOW` and `resolved_snapshot` of `test_workflow_delivery.py`.
- Produces (Task 6's prose names these):
  - `build-delivery --kind sync-selection`, whose input is exactly
    `{contract, prior_selection, head, tree, parents, review_ref, test_ref}`. It
    prints one canonical `selected-output/v2`.
  - Its refusals are exactly those `_sync_selection` raises in step 3, in code
    order after the closed-key, text and contract checks (D21).
  - `build-delivery --kind current-selection`, whose input is exactly
    `{contract}`. It prints the current selection of the contract's reviewed
    slot, as sealed, from the one ledger that installed the contract.
  - `DeliveryBuilder.build(..., installed_delivery=None)` and
    `DeliveryRuntime.build_delivery(..., installed_delivery=None)`; only kind
    `current-selection` reads it.
  - Its refusals are exactly those `_current_selection` raises in step 3,
    after the closed-key and contract checks. workflow-state's lookup refuses
    first with `the contract is installed by more than one ledger: <run>, <run>`
    (D25).
  - `workflow-state.py`: `_installing_runs(repo_root, issue, digest)` and
    `installing_ledger_delivery(runtime, repo_root_value, contract)`.

**Invariants:**
- The sealed link is exactly spec §5's, as `_sync_selection` in step 3 seals it:
  the prior's acceptance ids, review and test ids that add this head's, and
  `evidence_digest` over `{head, review_ref, test_ref, sync}`.
- A prior selection is valid only when the model accepts it as a
  `selected-output` whose contract digest, slot, subject kind (`commit`),
  repository, branch and base are the contract's reviewed slot's (D21).
- The builder does no git or I/O: parents and review are the owner's (D7),
  `review_ref`/`test_ref` are any non-empty text (D8), and workflow-state reads
  the ledger. Existing kinds' bytes and
  `WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION` (1) are unchanged.
- The intent lookup keeps its first match and every #193 skip guard through
  `_installing_runs`. Only `current-selection` refuses two raw matches (D25).

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_delivery_workflow.py`:

1. In `WorktreePolicyTest.test_help_states_the_contract_resolution_root`, replace
   the clause whose three string literals start `"A contract the builder cannot
   re-derive` and end `that is the only time it reads a ledger."` with these three:

```python
                "A contract the builder cannot re-derive is served only when a ledger under "
                "--repo-root has installed it, and then against that ledger's stored initial "
                "intent.",
                "--kind current-selection serves the current selection of the contract's "
                "reviewed slot from the one ledger that installed the contract. Those are "
                "the only times it reads a ledger.",
                "--kind sync-selection seals a selection that extends --input's "
                "prior_selection by one sync merge commit whose first parent is that "
                "selection's head.",
```

2. Add this test to `DeliveryBuilderTest`, after
   `test_authorization_chain_seals_the_handoff_chain_digest`:

```python
    def test_sync_selection_seals_one_link_and_refuses_each_malformed_input(self):
        self.project()
        contract = self.build("contract", self.contract_input())["contract"]
        h0, h1, m1, m2 = "a" * 40, "e" * 40, "d" * 40, "f" * 40
        prior = self.build("selected-output", {"contract": contract, "head": h0,
            "tree": "c" * 40, "acceptance_ref": ".claude/specs/issue-171.md",
            "review_ref": "clean", "test_ref": "checks"})
        value = {"contract": contract, "prior_selection": prior, "head": h1,
                 "tree": "8" * 40, "parents": [h0, m1], "review_ref": "merge-delta-clean",
                 "test_ref": "checks"}
        raw = json.dumps(value).encode()
        first = self.cli("build-delivery", "--repo-root", self.root, "--kind",
                         "sync-selection", "--input", "-", stdin=raw).stdout
        self.assertEqual(first, self.cli("build-delivery", "--repo-root", self.root, "--kind",
                                         "sync-selection", "--input", "-", stdin=raw).stdout)
        link = json.loads(first)
        self.assertEqual(first, self.model.canonical_bytes(link))
        self.validate(link, "selected-output")
        sync = {"prior_selection_id": prior["id"], "first_parent": h0,
                "integration_parent": m1}
        self.assertEqual({key: link[key] for key in (
            "schema_version", "subject_kind", "subject_value", "branch", "base", "sync")},
            {"schema_version": 2, "subject_kind": "commit", "subject_value": h1,
             "branch": WORKTREE_NAME, "base": "main", "sync": sync})
        self.assertEqual(link["data_identity_digest"], self.model.canonical_digest(
            {"kind": "git-tree", "value": "8" * 40}))
        self.assertEqual(link["evidence_digest"], self.model.canonical_digest(
            {"head": h1, "review_ref": "merge-delta-clean", "test_ref": "checks",
             "sync": sync}))
        self.assertEqual((link["acceptance_evidence_ids"], link["review_evidence_ids"],
                          link["test_evidence_ids"]),
                         (prior["acceptance_evidence_ids"],
                          [f"review:clean@{h0}", f"review:merge-delta-clean@{h1}"],
                          [f"test:checks@{h0}", f"test:checks@{h1}"]))
        other = self.build("contract", self.contract_input(now=LATER))["contract"]
        foreign = self.build("selected-output", {"contract": other, "head": h0,
            "tree": "c" * 40, "acceptance_ref": "spec", "review_ref": "clean",
            "test_ref": "checks"})
        invalid = b"prior_selection is not a valid selection of this contract"
        parents = b"parents must be two distinct non-empty strings other than head"
        for label, changes, reason in (
                ("foreign prior", {"prior_selection": foreign}, invalid),
                ("tampered prior", {"prior_selection": {**prior, "subject_value": m2}},
                 invalid),
                ("head unchanged", {"head": h0}, b"head equals the prior selection's head"),
                ("one parent", {"parents": [h0]}, parents),
                ("equal parents", {"parents": [h0, h0]}, parents),
                ("empty parent", {"parents": [h0, ""]}, parents),
                ("head as a parent", {"parents": [h0, h1]}, parents),
                ("not a list", {"parents": f"{h0} {m1}"}, parents),
                ("first parent off the chain", {"parents": [m2, m1]},
                 b"parents[0] is not the prior selection's head")):
            with self.subTest(label=label):
                refused = self.build("sync-selection", {**value, **changes}, ok=False)
                self.assertEqual((refused.returncode, refused.stdout, refused.stderr),
                                 (2, b"", b"workflow-state: build-delivery refused: "
                                  b"sync selection: " + reason + b"\n"))
        missing = dict(value)
        missing.pop("test_ref")
        refused = self.build("sync-selection", missing, ok=False)
        self.assertEqual((refused.returncode, refused.stdout), (2, b""))
        self.assertIn(b"builder input keys", refused.stderr)
```

3. Append this class to `home/common/agent-skills/tests/test_workflow_delivery.py`,
   before the `if __name__ == "__main__":` block. It pins the builder's re-check,
   which no CLI path reaches (#193 D12). The foreign delivery is the module's
   imported fixture, a valid delivery of another contract that holds a
   selection, so dropping the digest comparison turns it red:

```python
class CurrentSelectionTest(unittest.TestCase):
    """#192 D25: the builder re-checks the delivery workflow-state hands it."""

    def test_a_missing_foreign_or_malformed_delivery_is_refused(self):
        runtime = runpy.run_path(str(ENTRY))["DeliveryRuntime"](notes_max_characters=10_000)
        contract = runtime.build_delivery("contract", {
            "issue": 154, "worktree": f"/repo/.worktrees/{LIVE}",
            "source_kind": "explicit_user",
            "source_reference": "invocation:/from-issue 154 --auto", "now": NOW},
            policy=resolved_snapshot("/repo"))["contract"]
        for label, delivery, reason in (
                ("no ledger", None, "no ledger under the repo root installs this contract"),
                ("malformed", {}, "the installed delivery is invalid"),
                ("another contract's",
                 contract_and_delivery_for_stage(runtime.model, "merge")[1],
                 "the installed delivery is invalid")):
            with self.subTest(label=label):
                with self.assertRaises(ValueError) as caught:
                    runtime.build_delivery("current-selection", {"contract": contract},
                                           policy=None, installed_delivery=delivery)
                self.assertEqual(str(caught.exception), "current selection: " + reason)
```

4. Add these members to `DeliveryLoopTest`, after `test_evidence_kinds_are_exact_and_closed`:

```python
    H0, H1, H2, M1, M2 = "a" * 40, "e" * 40, "9" * 40, "d" * 40, "f" * 40
    CLEANUP = {"close_tracker": ("tracker_closed", {
                   "close_reason": "completed",
                   "observation_identity": "github:issue:171:closed"}),
               "delete_remote_branch": ("remote_branch_absent", {}),
               "remove_worktree": ("worktree_absent", {}),
               "delete_local_branch": ("local_branch_absent", {})}

    def sync_checkpoint(self, observations, authority, scope):
        """One checkpoint whose reply must pass the workflow-response boundary too (T7)."""
        reply = self.checkpoint(observations, authority, scope)
        self.validated("workflow-response", reply)
        return reply

    def scope_of(self, stage_id):
        return self.build("scope", {"contract": self.contract, "stage_id": stage_id})

    def allowed(self, scope, evidence):
        return self.build("authority-observation", {"contract": self.contract,
            "scope_id": scope["id"], "launch_id": self.custody["action_id"],
            "authority_kind": "native_guard", "verdict": "allowed",
            "reason_code": "guard_allowed", "observed_at": LATER, "evidence": evidence})

    def sync(self, prior, head, integration_parent):
        """The sync selection extending `prior` by one merge, as the route builds it."""
        return self.build("sync-selection", {"contract": self.contract,
            "prior_selection": prior, "head": head, "tree": "8" * 40,
            "parents": [prior["subject_value"], integration_parent],
            "review_ref": "merge-delta-clean", "test_ref": "checks"})

    def at_head(self, selected):
        """`selected`'s selected_output, then branch_published and pr_opened (PR 5) at its head."""
        head = selected["subject_value"]
        return [self.observed("selected_output", selection=selected),
                self.observed("branch_published", head=head),
                self.observed("pr_opened", pr_number=5, pr_url=URL, head=head)]

    def installed(self):
        """A fresh project whose contract one direct owner installs; this test holds its custody."""
        self.project()
        built = self.build("contract", self.contract_input())
        self.contract = built["contract"]
        self.digest = self.model.canonical_digest(self.contract)
        owner = self.acquire(self.contract, built["initial_intent"])
        self.custody = owner["custody"]
        self.run_args = ("--repo-root", self.root, "--run-id", owner["run_id"])
        self.ledger = self.root / f".superpowers/workflows/{owner['run_id']}/state.json"

    def current(self):
        """The ledger's current selection, as an owner that did not build it reads it (D24)."""
        return self.build("current-selection", {"contract": self.contract})

    def selected_at_h0(self):
        """One implementation custody checkpoints H0's selection with the merge_pr scope."""
        self.installed()
        h0 = self.build("selected-output", {"contract": self.contract, "head": self.H0,
            "tree": "c" * 40, "acceptance_ref": ".claude/specs/issue-171.md",
            "review_ref": "clean", "test_ref": "checks"})
        echoed = self.sync_checkpoint(self.at_head(h0), [], self.scope_of("merge_pr"))
        self.assertEqual(echoed["requirements"][0]["reason_code"], "native_evaluation_required")
        return h0

    def remainder_after_stop(self):
        """The custody stops `terminal_failed`; remainder 1 takes over and synchronizes."""
        historical = {"issue": 171, "state": "stopped", "pr_url": URL, "merge_sha": None,
            "issue_closed": False, "discussion_items": [], "detail_state": "none",
            "report_path": None, "notes": "The PR conflicts with main after review."}
        summary = {"interface_version": 2, "issue": 171, "state": "terminal_failed",
            "custody": self.custody, "historical_owner_result": historical,
            "delivery_contract_digest": self.digest, "delivery_observations": [],
            "authority_observations": [], "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "stopped"}
        remainder = json.loads(self.cli("finish", *self.run_args, "--now", LATER,
            "--summary-file", "-", stdin=self.validated("ship-summary", summary)).stdout)
        self.validated("workflow-response", remainder)
        self.assertEqual((remainder["kind"], remainder["custody"]["action_id"]),
                         ("delivery_remainder", "171:r1:1"))
        self.custody = remainder["custody"]
        synced = self.sync_checkpoint([], [], None)
        self.assertEqual(synced["pending_stage_ids"][0], "merge_pr")

    def cycles(self, stages, pending, authority):
        """Propose each stage with the previous effect's facts; return the last effect's."""
        absent = {}
        for stage in stages:
            scope = self.scope_of(stage)
            echoed = self.sync_checkpoint(pending, authority, scope)
            self.assertEqual((echoed["requested_scope"], echoed["requirements"][0]["reason_code"]),
                             (scope, "native_evaluation_required"))
            kind, facts = self.CLEANUP[stage]
            pending, authority = [self.observed(kind, **facts)], [self.allowed(scope, stage)]
            absent[kind] = pending[0]["id"]
        return pending, authority, absent

    def finish_delivered(self, selected, merged, pending, authority, absent):
        """Finish `delivery_complete` with `implementation_delivered` over `selected`."""
        completing = pending + [
            self.observed("implementation_delivered", selection=selected,
                          merge_sha=merged["subject"]["merge_sha"],
                          integrated_ref="refs/heads/main", merge_observation_id=merged["id"]),
            self.observed("cleanup_complete",
                          remote_branch_observation_ids=[absent["remote_branch_absent"]],
                          local_branch_observation_ids=[absent["local_branch_absent"]],
                          worktree_observation_ids=[absent["worktree_absent"]],
                          detail_pointer=".superpowers/issue-delivery/171/detail.json",
                          read_evidence="detail read")]
        historical = {"issue": 171, "state": "merged", "pr_url": URL,
            "merge_sha": merged["subject"]["merge_sha"], "issue_closed": True,
            "discussion_items": [], "detail_state": "none", "report_path": None,
            "notes": "delivered"}
        summary = {"interface_version": 2, "issue": 171, "state": "delivery_complete",
            "custody": self.custody, "historical_owner_result": historical,
            "delivery_contract_digest": self.digest,
            "delivery_observations": sorted(completing, key=lambda item: item["id"]),
            "authority_observations": authority, "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "delivered"}
        finished = json.loads(self.cli("finish", *self.run_args, "--now", LATER,
            "--summary-file", "-", stdin=self.validated("ship-summary", summary)).stdout)
        self.validated("workflow-response", finished)
        self.assertEqual((finished["kind"], finished["pending_stage_ids"]),
                         ("delivery_complete", []))
        return json.loads(self.ledger.read_text(encoding="utf-8"))["issues"]["171"]["delivery"]

    def merge_fact(self, delivery):
        return next(item for item in delivery["stage_facts"] if item["stage_id"] == "merge_pr")

    def test_current_selection_is_read_from_the_one_installing_ledger(self):
        """T12 (D24, D25): the installing ledger's tip, or a named refusal."""
        def refused(reason):
            completed = self.build("current-selection", {"contract": self.contract}, ok=False)
            self.assertEqual((completed.returncode, completed.stdout, completed.stderr),
                             (2, b"", b"workflow-state: build-delivery refused: " + reason + b"\n"))

        self.project()
        self.contract = self.build("contract", self.contract_input())["contract"]
        refused(b"current selection: no ledger under the repo root installs this contract")
        self.installed()
        refused(b"current selection: the installing ledger holds no selection of the "
                b"contract's reviewed slot")
        h0 = self.selected_at_h0()
        self.assertEqual(self.current(), h0)
        h1 = self.sync(h0, self.H1, self.M1)
        self.sync_checkpoint(self.at_head(h1), [], self.scope_of("merge_pr"))
        self.assertEqual(self.current(), h1)
        shutil.copytree(self.ledger.parent, self.ledger.parent.with_name("zz-copy"))
        refused(b"the contract is installed by more than one ledger: "
                + self.ledger.parent.name.encode() + b", zz-copy")

    def test_a_remainder_merges_after_a_post_selection_sync(self):
        """T7: the remainder reads H0 from the ledger; publish, open and merge follow H1."""
        h0 = self.selected_at_h0()
        self.remainder_after_stop()
        prior = self.current()
        self.assertEqual(prior, h0)
        h1 = self.sync(prior, self.H1, self.M1)
        merge = self.scope_of("merge_pr")
        echoed = self.sync_checkpoint(self.at_head(h1), [], merge)
        self.assertEqual((echoed["requested_scope"], echoed["pending_stage_ids"][0],
                          echoed["requirements"][0]["reason_code"]),
                         (merge, "merge_pr", "native_evaluation_required"))
        merged = self.observed("pr_merged", pr_number=5, pr_url=URL, head=self.H1,
                               merge_sha="b" * 40)
        cleaned = self.cycles(tuple(self.CLEANUP), [merged], [self.allowed(merge, "merge_pr")])
        tip = self.current()
        self.assertEqual(tip, h1)
        stored = self.finish_delivered(tip, merged, *cleaned)
        self.assertEqual([item["id"] for item in stored["selected_outputs"]],
                         sorted([h0["id"], h1["id"]]))
        self.assertEqual(self.merge_fact(stored)["observation_id"], merged["id"])

    def test_a_merge_landed_at_a_sync_run_folds_into_the_chain(self):
        """T8, the #150 shape: the PR merged out of band at H2, two syncs above H0.

        The merge folds before the chain, or in the chain's one checkpoint as
        CI-MERGE.md says; both shapes fold.
        """
        for together in (False, True):
            with self.subTest(one_checkpoint=together):
                h0 = self.selected_at_h0()
                self.remainder_after_stop()
                merged = self.observed("pr_merged", pr_number=5, pr_url=URL, head=self.H2,
                                       merge_sha="b" * 40)
                if not together:
                    early = self.sync_checkpoint([merged], [], None)
                    self.assertEqual(early["pending_stage_ids"][0], "merge_pr")
                h1 = self.sync(self.current(), self.H1, self.M1)
                h2 = self.sync(h1, self.H2, self.M2)
                close = self.scope_of("close_tracker")
                folded = self.sync_checkpoint(([merged] if together else [])
                    + [self.observed("selected_output", selection=h1)] + self.at_head(h2),
                    [], close)
                self.assertEqual((folded["requested_scope"], folded["pending_stage_ids"][0]),
                                 (close, "close_tracker"))
                kind, facts = self.CLEANUP["close_tracker"]
                cleaned = self.cycles(tuple(self.CLEANUP)[1:], [self.observed(kind, **facts)],
                                      [self.allowed(close, "close_tracker")])
                stored = self.finish_delivered(self.current(), merged, *cleaned)
                self.assertEqual([item["id"] for item in stored["selected_outputs"]],
                                 sorted([h0["id"], h1["id"], h2["id"]]))
                self.assertEqual(self.merge_fact(stored)["observation_id"], merged["id"])

    def test_chain_violations_leave_the_ledger_byte_identical(self):
        """T9: every refused fold exits 2 and writes nothing."""
        h0 = self.selected_at_h0()
        merge = self.scope_of("merge_pr")

        def refused(observations, authority, scope):
            before = self.ledger.read_bytes()
            completed = self.checkpoint(observations, authority, scope, ok=False)
            self.assertEqual((completed.returncode, completed.stdout, self.ledger.read_bytes()),
                             (2, b"", before))

        second_root = self.build("selected-output", {"contract": self.contract,
            "head": self.H1, "tree": "c" * 40, "acceptance_ref": ".claude/specs/issue-171.md",
            "review_ref": "clean", "test_ref": "checks"})
        h1 = self.sync(h0, self.H1, self.M1)
        with self.subTest(refusal="a second v1 root"):
            refused([self.observed("selected_output", selection=second_root)], [], None)
        with self.subTest(refusal="a merge_pr scope without the tip's observations"):
            refused([self.observed("selected_output", selection=h1)], [], merge)
        self.sync_checkpoint(self.at_head(h1), [], merge)
        with self.subTest(refusal="a fork of H0"):
            refused([self.observed("selected_output",
                                   selection=self.sync(h0, self.H2, self.M2))], [], None)
        merged = self.observed("pr_merged", pr_number=5, pr_url=URL, head=self.H1,
                               merge_sha="b" * 40)
        self.sync_checkpoint([merged], [self.allowed(merge, "merge_pr")],
                             self.scope_of("close_tracker"))
        with self.subTest(refusal="a sync selection after the merge at the tip"):
            refused([self.observed("selected_output",
                                   selection=self.sync(h1, self.H2, self.M2))], [], None)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k sync_selection_seals -k current_selection_is_read -k post_selection_sync -k landed_at_a_sync_run -k chain_violations -k test_help_states`
Expected: `FAILED`. `--kind sync-selection` and `--kind current-selection` exit 2
with `invalid choice` wherever a test builds a link or reads the current
selection, and the help pin misses its new clauses.

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_delivery.py -k CurrentSelectionTest`
Expected: `FAILED`, with `TypeError` errors for the unexpected keyword
`installed_delivery`.

- [ ] **Step 3: Implement the builder kinds and wire them**

In `workflow_delivery_build.py`, add
`_SYNC_INPUT = {"contract", "prior_selection", "head", "tree", "parents", "review_ref", "test_ref"}`
beside `_SELECTION_INPUT`. `build` gains the keyword
`installed_delivery: object = None`. Route `kind == "sync-selection"` to
`self._sync_selection(value, installed_intent)` and
`kind == "current-selection"` to
`self._current_selection(value, installed_intent, installed_delivery)`, both
before the final `unknown builder kind` refusal. Implement both as written,
because the check order and the sealed fields are the interface (D8, D21, D25):

```python
    def _sync_selection(self, value: object, installed_intent: object) -> dict[str, Any]:
        """Seal one sync selection extending ``prior_selection`` by one merge (#192 §5)."""
        value = _closed(value, _SYNC_INPUT)
        refs = {name: _text(value[name], name) for name in (
            "head", "tree", "review_ref", "test_ref")}
        contract, _ = self._checked_contract(value["contract"], installed_intent)
        digest = self._model.canonical_digest(contract)
        _, _, branch, base, _ = self._contract_facts(contract)
        repository = contract["project"]["repository_id"]
        try:
            prior = self._model.validate_delivery_object(
                value["prior_selection"], expected_kind="selected-output",
                notes_max_characters=self._notes_max)
        except Exception:
            # A null nested member raises AttributeError, not ValueError (#193 D14).
            prior = None
        if prior is None or (prior["contract_digest"], prior["slot_id"], prior["subject_kind"],
                             prior["repository_id"], prior["branch"], prior["base"]) != (
                digest, _SLOT, "commit", repository, branch, base):
            _refuse("sync selection: prior_selection is not a valid selection of this contract")
        head = refs["head"]
        if head == prior["subject_value"]:
            _refuse("sync selection: head equals the prior selection's head")
        parents = value["parents"]
        if (not isinstance(parents, list) or len(parents) != 2
                or not all(isinstance(item, str) and item for item in parents)
                or parents[0] == parents[1] or head in parents):
            _refuse("sync selection: parents must be two distinct non-empty strings "
                    "other than head")
        if parents[0] != prior["subject_value"]:
            _refuse("sync selection: parents[0] is not the prior selection's head")
        sync = {"prior_selection_id": prior["id"], "first_parent": parents[0],
                "integration_parent": parents[1]}
        return self._seal({
            "schema_version": 2, "kind": "selected-output", "contract_digest": digest,
            "slot_id": _SLOT, "subject_kind": "commit", "subject_value": head,
            "data_identity_digest": self._model.canonical_digest(
                {"kind": "git-tree", "value": refs["tree"]}),
            "repository_id": repository, "branch": branch, "base": base,
            "evidence_digest": self._model.canonical_digest({
                "head": head, "review_ref": refs["review_ref"],
                "test_ref": refs["test_ref"], "sync": sync}),
            "acceptance_evidence_ids": list(prior["acceptance_evidence_ids"]),
            "review_evidence_ids": sorted({*prior["review_evidence_ids"],
                                           f"review:{refs['review_ref']}@{head}"}),
            "test_evidence_ids": sorted({*prior["test_evidence_ids"],
                                         f"test:{refs['test_ref']}@{head}"}),
            "sync": sync,
        })

    def _current_selection(self, value: object, installed_intent: object,
                           installed_delivery: object) -> dict[str, Any]:
        """The contract's current selection, from the ledger that installed it (#192 D24)."""
        contract, _ = self._checked_contract(_closed(value, {"contract"})["contract"],
                                             installed_intent)
        if installed_delivery is None:
            _refuse("current selection: no ledger under the repo root installs this contract")
        try:
            if installed_delivery["contract_digest"] != self._model.canonical_digest(contract):
                raise ValueError("the delivery belongs to another contract")
            current = self._model.current_selection(installed_delivery)
        except Exception:
            # A null nested member raises AttributeError, not ValueError (#193 D14).
            current = False
        if current is False:
            _refuse("current selection: the installed delivery is invalid")
        if current is None:
            _refuse("current selection: the installing ledger holds no selection of the "
                    "contract's reviewed slot")
        return current
```

In the module docstring, directly after the sentence that ends with
`installed_intent` and a full stop, add these two lines:

```text
The ``current-selection`` kind serves the current selection from the delivery
that ledger holds, which workflow-state hands in as ``installed_delivery``.
```

In `workflow_delivery.py`, add `"sync-selection": "selected-output"` and
`"current-selection": "selected-output"` to `_BUILD_OUTPUT_KINDS`, so the
runtime validates each before it is printed. `build_delivery` gains
`installed_delivery=None` and passes it to `self._builder.build`.

In `workflow-state.py`:

1. Import `Iterator` from `typing` beside `Any` and `Callable`. Add, beside
   `installed_initial_intent`, the one scan of #193 D3, D13 and D14:
   `_installing_runs(repo_root: Path, issue: str, digest: str) -> Iterator[Path]`.
   Its body is `installed_initial_intent`'s `workflows` non-symlink-directory
   check (a bare `return` when it fails) and its sorted `for run_dir` loop with
   the skip `try`, both moved unchanged. Where the loop now compares
   `_stored_contract_digest(raw_state, issue)` with `digest`, it does
   `yield run_dir` on a match. Its docstring is
   `"""Each run under repo_root whose raw state records digest for issue, sorted (#193 D3)."""`.

2. Put `installed_initial_intent` on that scan. After `resolve_repo_root`,
   delete its `workflows` check, and keep the digest `try` and `issue`. Replace
   the `for run_dir` loop header, its skip `try` and the digest comparison with
   `run_dir = next(_installing_runs(repo_root, issue, digest), None)` and
   `if run_dir is None: return None`. The loop body's validating re-read,
   dedented, now runs once on that `run_dir` and returns its root intent, and
   the trailing `return None` goes. The docstring keeps its rules, and every
   #193 skip and refusal test stays green unchanged.

3. Add the selection lookup after it, as written:

```python
def installing_ledger_delivery(runtime: Any, repo_root_value: str,
                               contract: object) -> dict[str, Any] | None:
    """The validated delivery the one ledger that installed ``contract`` holds, or None.

    Read-only like ``installed_initial_intent``, over the same scan (#192 D25).
    A selection can differ between ledgers where a root intent cannot, so two
    raw matches refuse naming both runs instead of taking the first. A value
    with no canonical bytes or issue matches no ledger and meets the builder's
    own contract refusal.
    """
    repo_root = resolve_repo_root(repo_root_value)
    try:
        digest = runtime.model.canonical_digest(contract)
        issue = str(contract["issue"])
    except Exception:
        return None
    runs = list(_installing_runs(repo_root, issue, digest))
    if len(runs) > 1:
        raise WorkflowError("build-delivery refused: the contract is installed by more "
                            "than one ledger: " + ", ".join(run.name for run in runs))
    if not runs:
        return None
    invalid = f"build-delivery refused: installing ledger {runs[0].name} is invalid"
    try:
        state = read_state_unlocked(runs[0] / "state.json", runs[0].name)
        delivery = state["issues"][issue]["delivery"]
        if runtime.model.canonical_digest(delivery["contract"]) != digest:
            raise WorkflowError(invalid)
    except Exception as error:
        raise WorkflowError(invalid) from error
    return copy.deepcopy(delivery)
```

4. In `command_build_delivery`, after the installed-intent lookup, add:

```python
    installed_delivery = None
    if args.kind == "current-selection" and isinstance(value, dict) and "contract" in value:
        installed_delivery = installing_ledger_delivery(runtime, args.repo_root,
                                                        value["contract"])
```

   and pass `installed_delivery=installed_delivery` to `runtime.build_delivery`.
   In its docstring, replace `finds; that is the only ledger read (#193 D2).`
   with:

```text
    finds, and --kind current-selection is served the current selection of the
    one ledger ``installing_ledger_delivery`` finds (#192 D24); those are the
    only ledger reads (#193 D2).
```

5. Add `"sync-selection"` and `"current-selection"` to the `--kind` choices,
   directly after `"selected-output"`. In the parser description, replace
   `intent; that is the only time it reads a ledger. ` with
   `intent. --kind current-selection serves the current selection of the
   contract's reviewed slot from the one ledger that installed the contract.
   Those are the only times it reads a ledger. `, and insert this sentence
   directly after `The other kinds resolve no project policy. `:
   `--kind sync-selection seals a selection that extends --input's
   prior_selection by one sync merge commit whose first parent is that
   selection's head. `

In `CLAUDE.md`, in the "Delivery objects are built" bullet, replace
`and seals each stage's scope, the reviewed selection, every delivery observation,`
with
`and seals each stage's scope, the reviewed selection and each sync selection that extends it after a post-review sync of the integration branch, every delivery observation,`.
Then replace `stored initial intent; that is the only time it reads a ledger.`
with this text, on the bullet's one line:

```text
stored initial intent; `--kind current-selection` serves the current selection of the contract's reviewed slot from the one ledger that installed it; those are the only times it reads a ledger.
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py`
Expected: `OK`, 5 tests more than after Task 2, no `FAIL:`/`ERROR:`. The #193
installed-ledger tests pass unchanged through `_installing_runs`.

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_delivery.py home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_admission_replay.py`
Expected: `OK`, and `test_workflow_delivery.py` has 1 test more than after Task 1.

Run: `if grep -q "each sync selection that extends it" CLAUDE.md && grep -q "those are the only times it reads a ledger" CLAUDE.md; then echo claude-ok; else exit 1; fi`
Expected: `claude-ok`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow_delivery_build.py home/common/agent-skills/scripts/workflow_delivery.py home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_delivery.py CLAUDE.md
git commit -m "feat(workflow-state): seal sync selections and serve the current one so a synced PR merges (#192)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
