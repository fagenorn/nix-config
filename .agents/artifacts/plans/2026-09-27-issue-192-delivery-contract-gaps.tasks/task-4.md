# Task 4: The delivery model follows one selection chain per slot

Spec §4 and T10, per D6, D7, D15, D16, D20, D21. A selection stays immutable,
but a slot may now hold a chain: one v1 root, then sync selections
(`selected-output/v2`). The chain's tip is the slot's **current selection**, and
every slot use reads it. The builder kind that seals links comes in Task 5, so
this task's tests build links with a fixture.

**Files:**
- Modify: `home/common/agent-skills/scripts/delivery_model/_objects.py`
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py`
- Modify: `home/common/agent-skills/scripts/delivery_model/_reconcile.py`
- Test: `home/common/agent-skills/tests/_delivery_model_fixtures.py`
- Test: `home/common/agent-skills/tests/test_delivery_model.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–3.
- Produces (Task 5's builder and tests rely on these):
  - `selected-output/v2`: exactly the v1 members with `schema_version: 2`, plus
    `sync: {prior_selection_id, first_parent, integration_parent}`.
    `validate_delivery_object(..., expected_kind="selected-output")` accepts it.
  - `_objects._selection_chain(selections, *, contract_digest, target) -> list[dict]`
    (root first, tip last) and `_objects._selection_chains(contract, contract_digest, selections) -> list[list[dict]]`.
  - The `delivery` validator's rejection text
    `a merged selection chain cannot be extended` (D21).
  - Fixtures `sync_selection(model, prior, *, head, integration_parent, review_ref="merge-delta-clean")`
    and `at_head(model, contract, selected)`.
- The public model seams (`validate_delivery_object`, `match_scope`,
  `reduce_delivery`, `MODEL_INTERFACE_VERSION`) keep their signatures.

**Invariants:**
- v1 grammar is unchanged, and a v1 is always a chain's root. A v2's
  `subject_kind` is `commit`. Its two parents are distinct non-empty strings,
  and neither equals its `subject_value`. Its `prior_selection_id` is a digest.
  Its id is derived exactly as v1's.
- One chain rule home, `_selection_chain`. Over the selections that pass the slot
  filter (contract digest, slot, subject kind, repository, branch, base), it
  requires exactly one v1 root. Every link must extend the selection its
  `prior_selection_id` names, with `first_parent` equal to that selection's
  head. No selection may be extended twice, every member must be reachable from
  the root, no head may repeat, and each link's three evidence arrays must
  contain its prior's. Anything else rejects `conflicting selected outputs`.
- Every consumer reads the tip. That covers `_selection_for_stage`, and through
  it stage scope matching, publish/open/merge observation matching,
  `_pr_numbers` and `_selected_head`. It also covers `match_scope`,
  `_scope_mismatch`, and the `implementation_delivered` postcondition, which
  matches only the tip.
- The `delivery` and `ship-handoff` validators accept a selection only as a
  member of a select stage's chain. The `delivery` validator also rejects a
  `pr_merged` observation whose `expected_head` is a non-tip member's head
  (final once merged).
- A delivery with no sync selection behaves exactly as at base. Every existing
  model, runtime and loop test stays green unchanged.
- `reduce_delivery` validates the merged delivery with pending facts, then
  recomputes facts and postconditions exactly as today (D20).

- [ ] **Step 1: Add the fixtures**

Append to `home/common/agent-skills/tests/_delivery_model_fixtures.py`:

```python
def sync_selection(model, prior, *, head, integration_parent,
                   review_ref="merge-delta-clean"):
    """A sealed selected-output/v2 extending `prior` by one sync merge (#192 D6, D15).

    Its first parent is `prior`'s head. Acceptance is inherited, and review and
    test evidence add this head's, as the `sync-selection` builder kind seals.
    """
    value = copy.deepcopy(prior)
    value.pop("sync", None)
    link = {"prior_selection_id": prior["id"], "first_parent": prior["subject_value"],
            "integration_parent": integration_parent}
    value.update(
        schema_version=2, id="", subject_value=head, sync=link,
        data_identity_digest=model.canonical_digest({"kind": "git-tree", "value": "t" + head}),
        evidence_digest=model.canonical_digest({"head": head, "review_ref": review_ref,
                                                "test_ref": "checks", "sync": link}),
        review_evidence_ids=sorted({*prior["review_evidence_ids"],
                                    f"review:{review_ref}@{head}"}),
        test_evidence_ids=sorted({*prior["test_evidence_ids"], f"test:checks@{head}"}))
    return seal(model, value)


def at_head(model, contract, selected):
    """`selected`'s selected_output, then branch_published and pr_opened (PR 17) at its head."""
    head = selected["subject_value"]
    return [observation(model, contract, "selected_output", {"selected_output": selected}),
            observation(model, contract, "branch_published", {
                "repository_id": "sim-repo", "branch": "feature", "selected_head": head}),
            observation(model, contract, "pr_opened", pr_subject("pr_opened", head=head))]
```

- [ ] **Step 2: Write the failing tests**

In `home/common/agent-skills/tests/test_delivery_model.py`, add `sync_selection`
and `at_head` to the fixture import list. Then add these members to
`DeliveryModelTest`, after `test_ship_handoff_cross_references_and_contract_order`:

```python
    SYNC_H1, SYNC_H2 = "e" * 40, "9" * 40
    INTEGRATION_1, INTEGRATION_2 = "d" * 40, "f" * 40

    def selected_at_h0(self):
        """The fixtures' head H0 (`a` * 40) selected, published and opened, then folded."""
        contract, delivery = contract_and_delivery(self.model)
        delivery = with_observed(self.model, contract, delivery, ["select", "publish", "open"])
        folded = self.model.reduce_delivery(contract, delivery, evaluation=evaluation())
        return contract, folded["next_delivery"], folded["next_delivery"]["selected_outputs"][0]

    def fold(self, contract, delivery, observations):
        return self.model.reduce_delivery(contract, delivery, evaluation=evaluation(
            delivery_observations=sorted(observations, key=lambda item: item["id"])))

    def link(self, prior, head, integration_parent):
        return sync_selection(self.model, prior, head=head,
                              integration_parent=integration_parent)

    def test_a_sync_selection_is_selected_output_v2(self):
        _, _, h0 = self.selected_at_h0()
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)
        self.assertEqual(self.validate(h1, "selected-output"), h1)

        def resealed(change):
            bad = copy.deepcopy(h1)
            change(bad)
            return seal(self.model, bad)

        for label, bad in (
                ("tree subject", resealed(lambda value: value.update(subject_kind="tree"))),
                ("equal parents", resealed(lambda value: value["sync"].update(
                    integration_parent=value["sync"]["first_parent"]))),
                ("head as first parent", resealed(lambda value: value["sync"].update(
                    first_parent=value["subject_value"]))),
                ("head as integration parent", resealed(lambda value: value["sync"].update(
                    integration_parent=value["subject_value"]))),
                ("empty parent", resealed(lambda value: value["sync"].update(
                    integration_parent=""))),
                ("prior not a digest", resealed(lambda value: value["sync"].update(
                    prior_selection_id="h0"))),
                ("extra sync member", resealed(lambda value: value["sync"].update(merge="m"))),
                ("no sync member", resealed(lambda value: value.pop("sync"))),
                ("v1 carrying sync", resealed(lambda value: value.update(schema_version=1))),
                ("schema 3", resealed(lambda value: value.update(schema_version=3)))):
            with self.subTest(label=label):
                self.assert_invalid(bad, "selected-output")

    def test_the_tip_of_the_chain_drives_every_slot_stage(self):
        contract, delivery, h0 = self.selected_at_h0()
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)
        selected = observation(self.model, contract, "selected_output", {"selected_output": h1})
        bare = self.fold(contract, delivery, [selected])
        facts = {fact["stage_id"]: fact for fact in bare["next_delivery"]["stage_facts"]}
        self.assertEqual((bare["next_stage_id"], facts["select"]["observation_id"],
                          facts["publish"]["state"], facts["open"]["state"]),
                         ("publish", selected["id"], "pending", "pending"))
        self.assertEqual([item["id"] for item in bare["next_delivery"]["selected_outputs"]],
                         sorted([h0["id"], h1["id"]]))
        opened = self.fold(contract, bare["next_delivery"],
                           at_head(self.model, contract, h1)[1:])
        self.assertEqual(opened["next_stage_id"], "merge")
        h2 = self.link(h1, self.SYNC_H2, self.INTEGRATION_2)
        again = self.fold(contract, opened["next_delivery"], at_head(self.model, contract, h2))
        self.assertEqual((again["next_stage_id"], len(again["next_delivery"]["selected_outputs"])),
                         ("merge", 3))

    def test_selection_sets_that_are_not_one_chain_are_rejected(self):
        contract, delivery, h0 = self.selected_at_h0()
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)
        stray = selection(self.model, self.model.canonical_digest(contract),
                          subject_value="c" * 40)
        off_chain = copy.deepcopy(h1)
        off_chain["sync"]["first_parent"] = "c" * 40
        narrowed = copy.deepcopy(h1)
        narrowed["review_evidence_ids"] = [f"review:merge-delta-clean@{self.SYNC_H1}"]
        for label, links in (
                ("second v1 root", [stray]),
                ("dangling prior", [self.link(stray, self.SYNC_H1, self.INTEGRATION_1)]),
                ("fork", [h1, self.link(h0, self.SYNC_H2, self.INTEGRATION_2)]),
                ("first parent off the chain", [seal(self.model, off_chain)]),
                ("evidence not a superset", [seal(self.model, narrowed)]),
                ("repeated head", [h1, self.link(h1, h0["subject_value"], self.INTEGRATION_2)])):
            with self.subTest(label=label):
                with self.assertRaisesRegex(self.model.DeliveryModelError,
                                            "conflicting selected outputs"):
                    self.fold(contract, delivery, [
                        observation(self.model, contract, "selected_output",
                                    {"selected_output": item}) for item in links])

    def test_a_merge_at_the_tip_is_final(self):
        contract, delivery, h0 = self.selected_at_h0()
        merged = self.fold(contract, delivery, [
            observation(self.model, contract, "pr_merged", pr_subject("pr_merged"))])
        self.assertEqual(post_state(merged, "pr_merged"), "observed")
        with self.assertRaisesRegex(self.model.DeliveryModelError,
                                    "a merged selection chain cannot be extended"):
            self.fold(contract, merged["next_delivery"], at_head(
                self.model, contract, self.link(h0, self.SYNC_H1, self.INTEGRATION_1)))
        # A merge at a head the chain has not reached yet is history until it does.
        early = self.fold(contract, delivery, [observation(
            self.model, contract, "pr_merged", pr_subject("pr_merged", head=self.SYNC_H2))])
        self.assertEqual((early["next_stage_id"], post_state(early, "pr_merged")),
                         ("merge", "pending"))

    def test_match_scope_binds_the_tip_and_refuses_a_superseded_head(self):
        contract, delivery, declared = contract_and_delivery_for_stage(self.model, "merge")
        h0 = selection(self.model, self.model.canonical_digest(contract))
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)

        def match(selected):
            return self.model.match_scope(
                contract, delivery["authorization_intents"][0],
                requested_scope(self.model, declared, selected), selected_outputs=[h0, h1],
                at_time="2026-09-21T00:00:00Z", revocation_observations=[])

        self.assertEqual(match(h1), {"matched": True, "scope_id": declared["id"],
                                     "reason_code": "matched"})
        self.assertEqual(match(h0), {"matched": False, "scope_id": None,
                                     "reason_code": "scope_target_mismatch"})

    def test_only_the_current_selection_is_delivered(self):
        contract, delivery, h0 = self.selected_at_h0()
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)
        opened = self.fold(contract, delivery, at_head(self.model, contract, h1))["next_delivery"]
        merge = observation(self.model, contract, "pr_merged",
                            pr_subject("pr_merged", head=self.SYNC_H1))

        def delivered(selected):
            head = selected["subject_value"]
            return observation(self.model, contract, "implementation_delivered", {
                "selected_subject": {"kind": "commit", "value": head},
                "integration_subject": {"kind": "commit", "value": "b" * 40},
                "presence": {"kind": "reachability", "repository_id": "sim-repo",
                             "selected_value": head, "integration_value": "b" * 40,
                             "integrated_ref": "refs/heads/main", "succeeded": True},
                "merge_observation_id": merge["id"],
                **{name: list(selected[name]) for name in (
                    "acceptance_evidence_ids", "review_evidence_ids", "test_evidence_ids")}})

        superseded = self.fold(contract, opened, [merge, delivered(h0)])
        self.assertEqual((post_state(superseded, "pr_merged"),
                          post_state(superseded, "implementation_delivered")),
                         ("observed", "pending"))
        current = self.fold(contract, opened, [merge, delivered(h1)])
        self.assertEqual(post_state(current, "implementation_delivered"), "observed")

    def test_a_handoff_carries_a_whole_selection_chain_or_none(self):
        contract, delivery = contract_and_delivery(self.model)
        h0 = selection(self.model, self.model.canonical_digest(contract))
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)
        handoff = ship_handoff(self.model, contract, delivery)
        chained = copy.deepcopy(handoff)
        chained["selected_outputs"] = sorted([h0, h1], key=lambda item: item["id"])
        self.assertEqual(self.validate(chained, "ship-handoff"), chained)
        stray = selection(self.model, self.model.canonical_digest(contract),
                          subject_value="c" * 40)
        for label, selections in (("a link without its root", [h1]),
                                  ("two roots", [h0, stray])):
            bad = copy.deepcopy(handoff)
            bad["selected_outputs"] = sorted(selections, key=lambda item: item["id"])
            with self.subTest(label=label):
                self.assert_invalid(bad, "ship-handoff")
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py -k sync_selection_is -k tip -k not_one_chain -k merge_at_the_tip -k current_selection_is -k whole_selection_chain`
Expected: `FAILED`. Every test that builds a v2 fails, because v1 grammar rejects
`sync`. The one exception is the "second v1 root" subtest, which already raises
`conflicting selected outputs`.

- [ ] **Step 4: Implement the chain**

`_objects.py`:

1. Hoist `_EVIDENCE_IDS = ("acceptance_evidence_ids", "review_evidence_ids", "test_evidence_ids")`.
   `_selected` accepts v2. A value whose `schema_version` is the int 2 must have
   the v1 member set plus `sync`, and any other value exactly the v1 set.
   `schema_version` must be the int 1 or 2. The existing checks are unchanged.
   For v2, then:
   `link = _object(value["sync"], _members("prior_selection_id first_parent integration_parent"), "sync")`,
   `_digest(link["prior_selection_id"], "prior selection")`, and both parents
   through `_string`. Reject when `subject_kind != "commit"`, when the parents
   are equal, or when `subject_value` is either parent. `_derived` stays last.

2. Add the one chain home. The algorithm is the decision (§4), so write it as
   given:

```python
def _selection_chain(selections: list[dict[str, Any]], *, contract_digest: str,
                     target: dict[str, Any]) -> list[dict[str, Any]]:
    """One slot's selection chain, root first; its last member is the current selection.

    Only selections that pass the slot filter take part: the contract digest,
    and the slot target's slot, subject kind, repository, branch and base. They
    must form one chain from a single v1 root in which each sync selection
    extends the selection its ``prior_selection_id`` names from that
    selection's head, no selection is extended twice, every member is reached
    from the root, no head repeats, and each link's evidence contains its
    prior's. Anything else rejects ``conflicting selected outputs`` (#192 §4).
    """
    constraints = target["constraints"]
    members = [item for item in selections
               if item["contract_digest"] == contract_digest
               and item["slot_id"] == target["slot_id"]
               and item["subject_kind"] == target["subject_kind"]
               and item["repository_id"] == constraints["repository_id"]
               and item["branch"] == constraints["branch"]
               and item["base"] == constraints["base"]]
    if not members:
        return []
    roots = [item for item in members if "sync" not in item]
    links: dict[str, list[dict[str, Any]]] = {}
    for item in members:
        if "sync" in item:
            links.setdefault(item["sync"]["prior_selection_id"], []).append(item)
    if len(roots) != 1 or any(len(items) > 1 for items in links.values()):
        _reject("conflicting selected outputs")
    chain = [roots[0]]
    while chain[-1]["id"] in links:
        prior, link = chain[-1], links[chain[-1]["id"]][0]
        if link["sync"]["first_parent"] != prior["subject_value"] or any(
                not set(prior[name]) <= set(link[name]) for name in _EVIDENCE_IDS):
            _reject("conflicting selected outputs")
        chain.append(link)
    if (len(chain) != len(members)
            or len({item["subject_value"] for item in chain}) != len(chain)):
        _reject("conflicting selected outputs")
    return chain


def _selection_chains(contract: dict[str, Any], contract_digest: str,
                      selections: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Every select stage's chain; rejects a selection that sits in none of them."""
    chains = [_selection_chain(selections, contract_digest=contract_digest,
                               target=stage["target_ref"])
              for stage in contract["stages"]
              if stage["kind"] == "select_reviewed_output"
              and stage["target_ref"].get("kind") == "slot"]
    members = {item["id"] for chain in chains for item in chain}
    if any(item["contract_digest"] != contract_digest or item["id"] not in members
           for item in selections):
        _reject()
    return chains
```

3. `_selection_for_stage` keeps its signature and its `None` for a non-slot
   target. Its body becomes the tip of
   `_selection_chain(delivery["selected_outputs"], contract_digest=delivery["contract_digest"], target=target)`,
   or `None` for an empty chain. Its docstring is
   `"""The stage slot's current selection: the tip of its chain, or None."""`.

4. In `_postcondition_observation_matches`, for `implementation_delivered`,
   directly after `if len(selected) != 1: return False`, return False unless
   `selected[0]["id"]` is the id of a non-None
   `_selection_for_stage(contract, delivery, stage)` for some
   `select_reviewed_output` stage. This is the tip rule.

`_wire.py`:

5. Import `_selection_chains` from `._objects`, and drop `_selection_for_stage`
   from that import once nothing in `_wire.py` uses it.

6. In `_delivery`, replace the `for item in value["selected_outputs"]:` block
   that calls `_selection_for_stage` with:

```python
    chains = _selection_chains(contract, digest, value["selected_outputs"])
    superseded = {item["subject_value"] for chain in chains for item in chain[:-1]}
    if any(item["observation_kind"] == "pr_merged"
           and item["subject"]["expected_head"] in superseded
           for item in value["delivery_observations"]):
        _reject("a merged selection chain cannot be extended")
```

7. In `_ship_handoff`, keep `_sorted_unique` and `_selected(item)` for each
   selection. Replace the per-item `_selection_for_stage` check with one call,
   `_selection_chains(contract, digest, value["selected_outputs"])`, so the
   handoff's selections form one chain per select stage, or are empty.

`_reconcile.py`:

8. Import `_selection_for_stage` from `._objects`.

9. In `match_scope`, after the `intent_revoked` early return, compute each
   select stage's tip once, deduplicated by id:

```python
    current = list({tip["id"]: tip for tip in (
        _selection_for_stage(c, {"contract_digest": canonical_digest(c),
                                 "selected_outputs": selections}, stage)
        for stage in c["stages"] if stage["kind"] == "select_reviewed_output")
        if tip is not None}.values())
```

   In the slot block, `bound` stays the selections with that `slot_id`.
   `len(bound) != 1` becomes `not bound`, and the `actual != expected` tuple
   check applies to every member of `bound` (any mismatch returns
   `slot_constraint_mismatch`). Both `_scope_mismatch` calls, the one in the
   loop and the fallback after it, receive `current` instead of `selections`.
   `_scope_mismatch` itself does not change (D21).

10. Add two helpers, and use them in `reduce_delivery` so the merged delivery is
    validated with pending facts (D20):

```python
def _stage_facts(contract: dict[str, Any], contract_digest: str,
                 stage_observation: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One stage fact per contract stage, observed where ``stage_observation`` names one."""
    facts = []
    for stage in contract["stages"]:
        observed = stage_observation.get(stage["id"])
        fact = {"schema_version": 1, "kind": "delivery-stage-fact", "id": "",
                "contract_digest": contract_digest, "stage_id": stage["id"],
                "state": "observed" if observed else "pending",
                "observation_id": observed["id"] if observed else None}
        fact["id"] = canonical_digest(fact, omit_derived="id")
        facts.append(fact)
    return facts


def _pending_postconditions(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {name: {"state": ("not_applicable"
                             if contract["deliverable"]["obligations"][name] == "not_applicable"
                             else "pending"), "observation_id": None}
            for name in _POSTCONDITIONS}
```

   Directly before the first
   `validate_delivery_object(next_delivery, expected_kind="delivery", ...)`
   (the one after the selected-output merge loop), set
   `next_delivery["stage_facts"] = _stage_facts(c, d["contract_digest"], {})` and
   `next_delivery["postconditions"] = _pending_postconditions(c)`. Put this
   comment above them:
   `# A sync selection un-matches facts observed at the prior head, so the merged`
   `# delivery is validated with pending facts; they are recomputed below (#192 D20).`
   Then replace the inline fact loop with
   `next_delivery["stage_facts"] = _stage_facts(c, d["contract_digest"], stage_observation)`.
   Start `post` from `_pending_postconditions(c)`, and skip names whose state is
   `not_applicable` in the matching loop. The facts and postconditions it
   produces are byte-identical to base.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py`
Expected: `OK`, 7 tests more than at base, no `FAIL:`/`ERROR:`.

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_delivery.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_admission_replay.py home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_workflow_state.py`
Expected: `OK`. Every single-selection delivery, handoff, checkpoint and summary
path behaves as at base.

Run: `if grep -n "_selection_for_stage" home/common/agent-skills/scripts/delivery_model/_wire.py; then exit 1; else echo wire-reads-chains; fi`
Expected: `wire-reads-chains`.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/scripts/delivery_model/_objects.py home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/scripts/delivery_model/_reconcile.py home/common/agent-skills/tests/_delivery_model_fixtures.py home/common/agent-skills/tests/test_delivery_model.py
git commit -m "feat(delivery-model): follow one selection chain per slot (#192)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
