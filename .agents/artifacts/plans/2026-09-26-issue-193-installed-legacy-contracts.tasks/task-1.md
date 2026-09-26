# Task 1: The builder serves a contract against its reference initial intent

Decisions: D2, D5, D6, D7, D11 (the two build-module docstrings), D12 (the
runtime-facade seam). Spec §1 "When the ledger is consulted", §3 "What each kind
returns", §4 "Refusal behaviour". Work from the worktree root. Every shell block
starts with `set -euo pipefail` (`set -uo pipefail` in the watch-it-fail step)
and these abbreviations, which the blocks below omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
```

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow_delivery_build.py` (module
  docstring, `DeliveryBuilder.build`, a new public `requires_installed_intent`,
  `_selection`, `_observation`, `_authority`, `_chain`, `_checked_contract`, and
  two new private methods beside it)
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py`
  (`DeliveryRuntime.build_delivery`, and a new `requires_installed_intent`
  directly above `check_worktree_policy`)
- Test: `home/common/agent-skills/tests/test_workflow_delivery.py` (one new
  class, `InstalledIntentTest`, after `WorktreePolicyCheckTest`)

**Interfaces:**
- Consumes: nothing from another task. It uses the live
  `DeliveryRuntime.build_delivery(kind, value, *, policy)`, the facade's
  `validate(value, kind)` and `model.canonical_digest(value)`, and the test
  module's existing `ENTRY`, `NOW`, `resolved_snapshot(root)` and
  `seal(model, value)`.
- Produces, for Task 2:
  - `DeliveryBuilder.build(kind: str, value: object, *, policy: dict | None, installed_intent: object = None) -> object`
  - `DeliveryBuilder.requires_installed_intent(value: object) -> bool`
  - `DeliveryRuntime.build_delivery(kind: str, value: object, *, policy: dict[str, Any] | None, installed_intent: object = None) -> object`,
    which forwards `installed_intent=installed_intent` to the builder and still
    validates every output as today
  - `DeliveryRuntime.requires_installed_intent(contract: object) -> bool`, a pure
    forward to the builder
  - The refusal texts `<R>; no ledger under the repo root installs this contract`,
    `installed initial intent does not match the contract` and
    `the contract's initial intent declares no single scope for stage <stage id>`,
    where `<R>` is one of the three unchanged derivation texts and the stage id is
    bare, not `repr`-quoted.

**Invariants:**
- A contract re-derives when it is model-valid, its `provenance.kind` is in
  `_SOURCE_KINDS`, and `_intent(contract)` has exactly the contract's recorded
  `initial_authorization_intent_id` and `initial_authorization_intent_digest`.
  One private method, `_derivation`, decides this for both
  `requires_installed_intent` and `_checked_contract` (spec §1).
- For a contract that re-derives, every kind's output is byte-identical to the
  base, and `installed_intent` is ignored even when given (D2). The unchanged
  `DeliveryBuilderTest` and `DeliveryLoopTest` cases in
  `T/test_delivery_workflow.py` pin this.
- `requires_installed_intent` never raises. A model-invalid value, including a
  non-object, answers `False`.
- A contract that does not re-derive and has no `installed_intent` refuses with
  its derivation reason plus `; no ledger under the repo root installs this contract`.
- A given `installed_intent` becomes the reference only if it is a model-valid
  `authorization-intent` with `predecessor_intent_id` `None`, whose `id` and
  canonical digest equal the contract's recorded pair. Any other value refuses
  with `installed initial intent does not match the contract`.
- `initial-intent` returns the reference intent. `scope` returns the one scope in
  it whose `(action, effect)` equals the stage record's, and refuses zero or
  several. `authority-observation` admits exactly its scope ids (D6).
- `authorization-chain`, `selected-output` and `observation` change only in which
  contracts they accept. Their bodies after the contract check are as at base.
- The module still does no I/O. Both `WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION`
  and `WORKFLOW_DELIVERY_INTERFACE_VERSION` stay `1` (D5).

- [ ] **Step 1: Write the failing tests**

In `T/test_workflow_delivery.py`, insert this class after `WorktreePolicyCheckTest`,
before `if __name__ == "__main__":`. Every name it uses is already imported or
defined in the module.

```python
class InstalledIntentTest(unittest.TestCase):
    """#193 D5-D7, D12: the builder's own check of an installed intent, behind the facade."""

    NOT_INSTALLED = "; no ledger under the repo root installs this contract"

    @classmethod
    def setUpClass(cls):
        cls.runtime = runpy.run_path(str(ENTRY))["DeliveryRuntime"](
            notes_max_characters=10_000)
        built = cls.runtime.build_delivery("contract", {
            "issue": 193, "worktree": "/repo/.worktrees/worktree-issue-193-legacy",
            "source_kind": "explicit_user", "source_reference": "invocation:/from-issue 193",
            "now": NOW}, policy=resolved_snapshot("/repo"))
        cls.derived, cls.derived_intent = built["contract"], built["initial_intent"]

    def resealed(self, change):
        """The derived intent after `change`, sealed again under a new id."""
        intent = copy.deepcopy(self.derived_intent)
        change(intent)
        return seal(self.runtime.model, intent)

    def legacy(self, intent):
        """A hand-built contract: unsourced provenance kind, recording `intent`."""
        contract = copy.deepcopy(self.derived)
        contract["provenance"]["kind"] = "orchestrate-issues"
        contract["initial_authorization_intent_id"] = intent["id"]
        contract["initial_authorization_intent_digest"] = (
            self.runtime.model.canonical_digest(intent))
        return contract

    def hand_built_intent(self):
        return self.resealed(lambda intent: intent["source"].update(
            reference="orchestrate-issues:orch-193"))

    def tampered(self):
        """A sourced contract whose recorded intent no longer re-derives."""
        contract = copy.deepcopy(self.derived)
        contract["provenance"]["created_at"] = "2026-09-22T00:00:00Z"
        return contract

    def unregenerable(self):
        """A sourced, model-valid contract whose worktree stage is not literal.

        ``_contract_facts`` rejects it, so ``_derivation`` returns the third
        reason through its ``except ValueError`` (per D14).
        """
        contract = copy.deepcopy(self.derived)
        slot = next(stage["target_ref"] for stage in contract["stages"]
                    if stage["target_ref"].get("kind") == "slot")
        for stage in contract["stages"]:
            if stage["kind"] == "remove_worktree":
                stage["target_ref"] = copy.deepcopy(slot)
        return contract

    def build(self, kind, value, installed):
        return self.runtime.build_delivery(kind, value, policy=None,
                                           installed_intent=installed)

    def refusal(self, kind, value, installed):
        with self.assertRaises(ValueError) as caught:
            self.build(kind, value, installed)
        return str(caught.exception)

    def test_only_a_valid_contract_that_does_not_re_derive_needs_an_installed_intent(self):
        invalid = copy.deepcopy(self.derived)
        invalid["issue"] = 0
        malformed = copy.deepcopy(self.derived)
        malformed["stages"][0]["target_ref"] = None
        for label, contract, expected in (
                ("derives", self.derived, False),
                ("hand-built", self.legacy(self.hand_built_intent()), True),
                ("tampered", self.tampered(), True),
                ("model-invalid", invalid, False), ("not an object", "contract", False),
                ("null nested member", malformed, False),
                ("unregenerable", self.unregenerable(), True)):
            with self.subTest(label=label):
                self.assertIs(self.runtime.requires_installed_intent(contract), expected)

    def test_without_an_installed_intent_the_derivation_reason_gains_the_ledger_clause(self):
        for label, contract, reason in (
                ("hand-built", self.legacy(self.hand_built_intent()),
                 "source kind of the contract cannot source an initial intent"),
                ("tampered", self.tampered(),
                 "derived intent does not match the contract's initial intent"),
                ("unregenerable", self.unregenerable(),
                 "derived intent cannot be regenerated: the contract has no "
                 "reviewed slot or worktree stage")):
            with self.subTest(label=label):
                self.assertEqual(self.refusal("initial-intent", {"contract": contract}, None),
                                 reason + self.NOT_INSTALLED)

    def test_a_contract_that_re_derives_ignores_any_installed_intent(self):
        self.assertEqual(self.build("initial-intent", {"contract": self.derived},
                                    self.hand_built_intent()), self.derived_intent)

    def test_the_installed_intent_must_be_the_contracts_valid_root(self):
        intent = self.hand_built_intent()
        successor = self.resealed(
            lambda value: value.update(predecessor_intent_id=intent["id"]))
        self.runtime.validate(successor, "authorization-intent")
        for label, contract, installed in (
                ("another intent", self.legacy(intent), self.derived_intent),
                ("not an intent", self.legacy(intent), {"kind": "authorization-intent"}),
                ("a successor", self.legacy(successor), successor)):
            with self.subTest(label=label):
                self.assertEqual(
                    self.refusal("initial-intent", {"contract": contract}, installed),
                    "installed initial intent does not match the contract")
        self.assertEqual(self.build("initial-intent", {"contract": self.legacy(intent)},
                                    intent), intent)

    def test_scope_refuses_a_stage_the_installed_intent_does_not_declare(self):
        action = next(stage["action"] for stage in self.derived["stages"]
                      if stage["id"] == "close_tracker")
        intent = self.resealed(lambda value: value.update(scopes=[
            scope for scope in value["scopes"] if scope["action"] != action]))
        contract = self.legacy(intent)
        self.assertEqual(
            self.refusal("scope", {"contract": contract, "stage_id": "close_tracker"}, intent),
            "the contract's initial intent declares no single scope for stage close_tracker")
        merge = self.build("scope", {"contract": contract, "stage_id": "merge_pr"}, intent)
        self.assertIn(merge, intent["scopes"])
```

The "a successor" case validates the successor first and records its own pair in
the contract, so only the predecessor rule can refuse it.

- [ ] **Step 2: Run the tests and watch them fail**

```bash
set -uo pipefail
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
PYTHONPATH=python python3 -m unittest $T/test_workflow_delivery.py -k InstalledIntentTest 2>&1 \
  | grep -E '^(Ran|OK|FAILED)|Error:' | sort | uniq -c
```

Expected: `Ran 5 tests` and `FAILED (errors=16)`: the planning probe's 13 plus
the "null nested member" and two "unregenerable" subtests added at standards
review (per D14). The errors are
`TypeError: DeliveryRuntime.build_delivery() got an unexpected keyword argument 'installed_intent'`
and `AttributeError: 'DeliveryRuntime' object has no attribute 'requires_installed_intent'`.
A planning probe saw exactly this at `6c23e64`.

- [ ] **Step 3: Implement the builder change**

In `S/workflow_delivery_build.py`:

1. **Module docstring.** Replace the sentence that begins "Declared scopes (in
   the initial intent) and actual scopes" and ends "can only disagree when the
   inputs differ." with this text (reflow freely):

   > Every kind that takes a contract works from its reference initial intent:
   > the one derived from the contract when it re-derives, else the intent a
   > ledger installed with it, which workflow-state finds and hands in as
   > ``installed_intent``. Declared scopes (in that intent) and actual scopes
   > (kind ``scope``) come from the one reference intent, so exact matching can
   > only disagree when the inputs differ.

   Keep the rest of the docstring, including "This private helper has no I/O".

2. **Contract check.** Replace `_checked_contract` with these three methods,
   in this order. The code is given in full because its order and texts are
   the D7 refusal table:

```python
    def _valid_contract(self, value: object) -> dict[str, Any]:
        try:
            return self._model.validate_delivery_object(
                value, expected_kind="delivery-contract",
                notes_max_characters=self._notes_max)
        except ValueError as error:
            _refuse(f"contract is invalid: {error}")

    def _derivation(self, contract: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """The intent a model-valid contract re-derives, or the reason it does not."""
        if contract["provenance"]["kind"] not in _SOURCE_KINDS:
            return None, "source kind of the contract cannot source an initial intent"
        try:
            intent = self._intent(contract)
        except ValueError as error:
            return None, str(error)
        if (intent["id"], self._model.canonical_digest(intent)) != (
                contract["initial_authorization_intent_id"],
                contract["initial_authorization_intent_digest"]):
            return None, "derived intent does not match the contract's initial intent"
        return intent, None

    def _checked_contract(self, value: object, installed_intent: object
                          ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Validate a supplied contract and return it with its reference initial intent.

        A contract that re-derives yields its derived intent and ignores
        ``installed_intent``. Otherwise the installed intent is the reference,
        and it must be a valid root intent carrying the contract's recorded id
        and digest.
        """
        contract = self._valid_contract(value)
        intent, reason = self._derivation(contract)
        if reason is None:
            return contract, intent
        if installed_intent is None:
            _refuse(f"{reason}; no ledger under the repo root installs this contract")
        try:
            installed = self._model.validate_delivery_object(
                installed_intent, expected_kind="authorization-intent",
                notes_max_characters=self._notes_max)
        except ValueError:
            installed = None
        if installed is None or installed["predecessor_intent_id"] is not None or (
                installed["id"], self._model.canonical_digest(installed)) != (
                contract["initial_authorization_intent_id"],
                contract["initial_authorization_intent_digest"]):
            _refuse("installed initial intent does not match the contract")
        return contract, installed
```

   `_intent` raises only through `_contract_facts`, whose text is the third
   derivation reason. Catching `ValueError` there hands that text on unchanged.

3. **Predicate.** Add this public method directly after `build`:

```python
    def requires_installed_intent(self, value: object) -> bool:
        """Whether ``value`` is a model-valid contract that does not re-derive.

        Only then may workflow-state look for a ledger that installed it. A
        value the model cannot validate answers False whatever it raises (a
        null nested member raises ``AttributeError``, not ``ValueError``), and
        then meets its own refusal in ``build`` (per D14).
        """
        try:
            return self._derivation(self._valid_contract(value))[1] is not None
        except Exception:
            return False
```

   workflow-state calls this predicate outside the builder call's
   `except Exception` boundary, so it must never raise: a malformed contract
   that escaped as a traceback would turn today's exit-2 refusal into exit 1.

4. **`build`.** Change the signature to
   `build(self, kind: str, value: object, *, policy: dict | None, installed_intent: object = None) -> object`.
   Keep the `contract` arm as is, since it takes no installed intent. Then:
   - `initial-intent`:
     `_, intent = self._checked_contract(_closed(value, {"contract"})["contract"], installed_intent)`,
     then return `copy.deepcopy(intent)`.
   - `scope`: keep the `_closed` and `stage_id` string checks. Then call
     `contract, intent = self._checked_contract(value["contract"], installed_intent)`.
     Keep the `unknown stage: {value['stage_id']!r}` lookup. Then set
     `declared = [item for item in intent["scopes"] if (item["action"], item["effect"]) == (stage["action"], stage["effect"])]`.
     When `len(declared) != 1`, refuse
     `"the contract's initial intent declares no single scope for stage " + stage["id"]`.
     Otherwise return `copy.deepcopy(declared[0])`. The `scope` arm no longer
     calls `_scope`.
   - Pass `installed_intent` as a second positional argument to `_selection`,
     `_observation`, `_authority` and `_chain`. Give each a matching
     `installed_intent: object` parameter.
5. **Kind bodies.** In `_selection`, `_observation` and `_chain`, the contract
   line becomes `contract, _ = self._checked_contract(value["contract"], installed_intent)`.
   In `_authority`, it becomes
   `contract, intent = self._checked_contract(value["contract"], installed_intent)`,
   and the scope set becomes `scopes = {item["id"] for item in intent["scopes"]}`.
   Leave the `unknown scope: ... is not a stage scope of the contract` text as is.
   Change nothing else in these bodies. `_chain` still compares roots to the
   contract's recorded pair.

In `S/workflow_delivery.py`:

6. Change `build_delivery`'s signature to
   `build_delivery(self, kind: str, value: object, *, policy: dict[str, Any] | None, installed_intent: object = None) -> object`.
   Call `self._builder.build(kind, value, policy=policy, installed_intent=installed_intent)`.
   Leave its output validation unchanged.
7. Directly above `check_worktree_policy`, add:

```python
    def requires_installed_intent(self, contract: object) -> bool:
        """Whether ``contract`` is model-valid but does not re-derive (#193 D5)."""
        return self._builder.requires_installed_intent(contract)
```

- [ ] **Step 4: Verify**

```bash
set -euo pipefail
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
PYTHONPATH=python python3 -m unittest $T/test_workflow_delivery.py 2>&1 | tail -3
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py 2>&1 | tail -3
flat() { tr -s '[:space:]' ' ' < "$1"; }
if flat $S/workflow_delivery_build.py | grep -qF 'come from the one ``_scope`` function'; then exit 1; fi
flat $S/workflow_delivery_build.py | grep -cF 'come from the one reference intent'
grep -c 'This private helper has no I/O' $S/workflow_delivery_build.py
grep -c 'WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION = 1' $S/workflow_delivery_build.py
grep -c 'def requires_installed_intent' $S/workflow_delivery_build.py $S/workflow_delivery.py
```

Expected: `test_workflow_delivery.py` ends `Ran 11 tests` and `OK` (6 at base
plus these 5). `test_delivery_workflow.py` runs unchanged, ends `Ran 45 tests`
and `OK`, and so pins the byte-identical derivation path; it takes about 80
seconds. The prohibition line passes, although it exits the gate at base, where
the old sentence wraps across two lines. Then `1`, `1`, `1`, and `…build.py:1`
with `…delivery.py:1`.

- [ ] **Step 5: Commit**

```bash
set -euo pipefail
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
git add $S/workflow_delivery_build.py $S/workflow_delivery.py $T/test_workflow_delivery.py
git commit -m "feat(workflow): serve a contract against its reference initial intent" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014t9cPhYQiiTKbbAn8vTEaq"
```
