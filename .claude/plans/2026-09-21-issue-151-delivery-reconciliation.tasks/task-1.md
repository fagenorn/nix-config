# Task 1: Build and publish the pure delivery model

**Files:**
- Create: `home/common/agent-skills/scripts/delivery_model.py`
- Create: `home/common/agent-skills/tests/test_delivery_model.py`
- Modify: `home/common/agent-skills/default.nix`
- Modify: `justfile`

**Interfaces:**
- Produces `MODEL_INTERFACE_VERSION = 1` and `DeliveryModelError(ValueError)`.
- Produces `canonical_bytes(value: object, *, omit_derived: str | None = None) -> bytes` and `canonical_digest(value: object, *, omit_derived: str | None = None) -> str`. Bytes are sorted-key compact UTF-8 JSON plus one newline; booleans never pass integer fields; duplicate keys remain a boundary-decoder concern. Digest is `sha256:<64 lowercase hex>` over canonical bytes after omitting only the named top-level derived member.
- Produces `validate_delivery_object(value: object, *, expected_kind: str | None = None, notes_max_characters: int) -> dict[str, object]`. It dispatches the closed v1 kinds in the spec, validates exact keys/types/order/derived identities/cross-references, and returns a detached normalized copy. It also accepts the nested strict `delivery` value, v2 checkpoint/handoff/summary envelopes, and closed workflow-response union used by Task 2; it does not validate workflow schema, ledger freshness, source authenticity or legacy result rows.
- Produces `validate_custody_ref(value: object, *, issue: int) -> dict[str, object]`, accepting only the implementation/remainder union and its exact derived action id.
- Produces `match_scope(contract: object, intent: object, requested: object, *, selected_outputs: list[object], at_time: str, revocation_observations: list[object]) -> dict[str, object]`. The intent contains the declared scope, expiry and revocation key; the contract supplies the digest and complete slot constraints. The return has exactly `matched` (bool), nullable `scope_id`, and `reason_code` (closed string). It applies only the narrowing table and never reads time/ledger state.
- Produces `reduce_delivery(contract: object, delivery: object, *, evaluation: object) -> dict[str, object]`. `evaluation` has exactly RFC3339 `at_time`, nullable `custody`, nullable boolean `current_launch` (null exactly when custody is null), nullable `requested_scope`, `source_kind` (`control | direct | checkpoint | summary`), and sorted candidate `authorization_intents`, `authority_observations`, `reevaluation_evidence`, and `delivery_observations`. The result has exactly normalized `stage_facts`, `postconditions`, ordered `pending_stage_ids`, nullable `next_stage_id`, sorted `requirements`, `completion_state` (`pending | delivery_complete`), and nullable `blocking` with exact `blocked_on`, `reason_code`, and `subject_id`. It is deterministic and does not mutate any input.
- Publishes the same regular source file as `~/.agents/lib/python/delivery_model.py`; later source and installed callers explicitly load that lexical path and require interface version 1.

**Invariants:**
- Per D1–D4 and D13, this module is the only source of new delivery object validation, canonical identity, scope narrowing and delivery reduction. It has no CLI, filesystem access, clock read, provider call, ledger write, workflow-schema selector, activation behavior or import side effect.
- All strict objects reject unknown/missing keys, bool-as-int, invalid nulls, duplicate or unsorted set-like arrays, bad RFC 3339 UTC values, bad ids/digests, broken intent predecessors, stage graph cycles/forward references, slot mismatches and conflicting observation identities.
- `stages`, `stage_facts`, and `pending_stage_ids` retain contract order. Other set-like arrays are sorted by scalar or member id and unique.
- Selection precedes every slot use; publish precedes open; merge requires selected output, an open PR, and pre-merge acceptance/review/test evidence but not `implementation_delivered`. Fresh post-merge reachability or record presence independently observes delivery.
- A host rejection remains operative until a valid later intent covering the exact tuple or accepted reevaluation evidence permits one fresh evaluation. New spelling, owner, context or host does not clear it. Human completion may satisfy an exact effect while preserving the rejection and granting no mutation right.
- `validate_delivery_object` checks structural/canonical truth only. `reduce_delivery` owns intent-chain, contract/slot, launch/effect, rejection and one-shot reevaluation semantics over caller-supplied facts. Workflow-state remains the transaction/trusted-source owner and supplies the current time/launch; neither the model nor artifact-budget authenticates an opaque host reference.
- The publication stanza adds one library target; it does not change the installed workflow/artifact wrappers or activate a new protocol.

- [ ] **Step 1: Write the complete pure-model and publication tests**

Create `test_delivery_model.py` with fixture builders that return strict complete
objects (no `**kwargs` are copied into wire objects):

```python
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[4]
SOURCE = ROOT / "home/common/agent-skills/scripts/delivery_model.py"
DEFAULT_NIX = ROOT / "home/common/agent-skills/default.nix"


def load_model(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("delivery model loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


class DeliveryModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_model(SOURCE, "delivery_model_source_test")

    def scope(self, *, scope_id=None, audience="private", data_kind="selected_output_slot"):
        value = {
            "schema_version": 1,
            "kind": "scope-tuple",
            "id": "sha256:" + "0" * 64,
            "principal": {"kind": "agent", "stable_id": "worker-1"},
            "action": "merge_pull_request",
            "effect": "provider_write",
            "target": {
                "project_id": "sim-project", "provider": "github",
                "repository_id": "sim-repo", "repository_slug": "sim.invalid/repo",
                "issue": 151, "branch": "feature", "base": "main",
                "pr_ref": {"kind": "literal", "value": "17"},
                "output_ref": {"kind": "slot", "slot_id": "reviewed"},
            },
            "endpoint": {"kind": "literal", "value": "provider:merge"},
            "data": ({"kind": "selected_output_slot", "slot_id": "reviewed",
                      "classification": "source", "audience": audience}
                     if data_kind == "selected_output_slot" else
                     {"kind": "none"}),
            "risk": "repository_write",
            "spend": {"kind": "none"},
        }
        value["id"] = scope_id or self.model.canonical_digest(value, omit_derived="id")
        return value

    def selection(self, contract_digest):
        value = {
            "schema_version": 1, "kind": "selected-output",
            "id": "sha256:" + "0" * 64,
            "contract_digest": contract_digest,
            "slot_id": "reviewed", "subject_kind": "commit",
            "subject_value": "a" * 40,
            "data_identity_digest": "sha256:" + "2" * 64,
            "repository_id": "sim-repo", "branch": "feature", "base": "main",
            "evidence_digest": "sha256:" + "3" * 64,
            "review_evidence_ids": ["review-1", "test-1"],
        }
        value["id"] = self.model.canonical_digest(value, omit_derived="id")
        return value

    def test_import_is_pure_and_interface_is_exact(self):
        with tempfile.TemporaryDirectory() as raw:
            before = set(Path(raw).iterdir())
            prior = Path.cwd()
            try:
                os.chdir(raw)
                module = load_model(SOURCE, "delivery_model_purity_test")
            finally:
                os.chdir(prior)
            self.assertEqual(module.MODEL_INTERFACE_VERSION, 1)
            self.assertEqual(set(Path(raw).iterdir()), before)
            self.assertFalse(hasattr(module, "main"))

    def test_canonical_bytes_and_derived_digest_are_exact(self):
        value = {"z": [2, 1], "id": "ignored", "a": "é"}
        body = b'{"a":"\xc3\xa9","z":[2,1]}\n'
        self.assertEqual(self.model.canonical_bytes(value, omit_derived="id"), body)
        self.assertEqual(
            self.model.canonical_digest(value, omit_derived="id"),
            "sha256:" + hashlib.sha256(body).hexdigest(),
        )

    def test_strict_scope_rejects_unknown_bool_null_and_wrong_id(self):
        cases = []
        unknown = self.scope(); unknown["extra"] = "x"; cases.append(unknown)
        boolean_issue = self.scope(); boolean_issue["target"]["issue"] = True; cases.append(boolean_issue)
        null_audience = self.scope(); null_audience["data"]["audience"] = None; cases.append(null_audience)
        wrong_id = self.scope(); wrong_id["id"] = "sha256:" + "f" * 64; cases.append(wrong_id)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(self.model.DeliveryModelError):
                self.model.validate_delivery_object(
                    value, expected_kind="scope-tuple", notes_max_characters=4096
                )

    def test_slot_narrowing_matches_exact_subject_and_payload_only(self):
        contract, delivery = strict_contract_and_delivery(self.model)
        intent = copy.deepcopy(delivery["authorization_intents"][-1])
        declared = copy.deepcopy(intent["scopes"][0])
        selected = self.selection(self.model.canonical_digest(contract))
        requested = copy.deepcopy(declared)
        requested["target"]["output_ref"] = {
            "kind": "literal", "value": selected["subject_value"]
        }
        requested["data"] = {
            "kind": "literal", "digest": selected["data_identity_digest"],
            "classification": "source", "audience": "private",
        }
        requested["id"] = self.model.canonical_digest(requested, omit_derived="id")
        matched = self.model.match_scope(
            contract, intent, requested, selected_outputs=[selected],
            at_time="2026-09-21T00:00:00Z", revocation_observations=[],
        )
        self.assertEqual(matched, {
            "matched": True, "scope_id": declared["id"], "reason_code": "matched"
        })
        for field, replacement in (
            ("audience", "public"),
            ("digest", "sha256:" + "9" * 64),
        ):
            bad = copy.deepcopy(requested); bad["data"][field] = replacement
            bad["id"] = self.model.canonical_digest(bad, omit_derived="id")
            self.assertFalse(self.model.match_scope(
                contract, intent, bad, selected_outputs=[selected],
                at_time="2026-09-21T00:00:00Z", revocation_observations=[],
            )["matched"])
        other_pr = copy.deepcopy(requested)
        other_pr["target"]["pr_ref"] = {"kind": "literal", "value": "18"}
        other_pr["id"] = self.model.canonical_digest(other_pr, omit_derived="id")
        self.assertEqual(
            self.model.match_scope(
                contract, intent, other_pr, selected_outputs=[selected],
                at_time="2026-09-21T00:00:00Z", revocation_observations=[],
            )["reason_code"],
            "scope_target_mismatch",
        )

    def test_matcher_checks_expiry_revocation_contract_and_slot_constraints(self):
        for variant, reason in (
            ("expired", "intent_expired"),
            ("revoked", "intent_revoked"),
            ("foreign_contract", "contract_mismatch"),
            ("wrong_slot_constraint", "slot_constraint_mismatch"),
        ):
            with self.subTest(reason=reason):
                case = authorization_case(self.model, variant=variant)
                result = self.model.match_scope(
                    case["contract"], case["intent"], case["requested_scope"],
                    selected_outputs=[case["selected_output"]],
                    at_time="2026-09-21T00:00:00Z",
                    revocation_observations=case["revocation_observations"],
                )
                self.assertEqual((result["matched"], result["reason_code"]), (False, reason))

    def test_reducer_keeps_merge_and_delivery_independent(self):
        contract, empty_delivery = strict_contract_and_delivery(self.model)
        before = copy.deepcopy(empty_delivery)
        initial = self.model.reduce_delivery(
            contract, empty_delivery, evaluation=evaluation_context()
        )
        self.assertEqual(initial["next_stage_id"], "select")
        opened = with_observed_stages(self.model, contract, empty_delivery,
                                      ["select", "publish", "open"])
        pre_merge = self.model.reduce_delivery(
            contract, opened, evaluation=evaluation_context()
        )
        self.assertEqual(pre_merge["next_stage_id"], "merge")
        self.assertEqual(pre_merge["postconditions"]["implementation_delivered"]["state"], "pending")
        merged = with_observed_stages(self.model, contract, opened, ["merge"])
        after_merge = self.model.reduce_delivery(
            contract, merged, evaluation=evaluation_context()
        )
        self.assertEqual(after_merge["postconditions"]["pr_merged"]["state"], "observed")
        self.assertEqual(after_merge["postconditions"]["implementation_delivered"]["state"], "pending")
        self.assertEqual(empty_delivery, before)

    def test_conflicting_observation_and_operational_denial_refuse(self):
        contract, delivery = strict_contract_and_delivery(self.model)
        conflict = with_conflicting_observation_ids(self.model, contract, delivery)
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.reduce_delivery(
                contract, conflict, evaluation=evaluation_context()
            )
        denied = with_host_rejection(self.model, contract, delivery)
        reduced = self.model.reduce_delivery(
            contract, denied, evaluation=evaluation_context(
                custody=implementation_custody(), current_launch=True,
                requested_scope=denied["authorization_intents"][-1]["scopes"][0],
            )
        )
        self.assertEqual(reduced["blocking"]["blocked_on"], "human_gate")
        self.assertEqual(reduced["blocking"]["reason_code"], "host_rejected")

    def test_rejection_successor_reevaluation_and_launch_binding(self):
        contract, delivery = strict_contract_and_delivery(self.model)
        custody = implementation_custody()
        denied = with_host_rejection(self.model, contract, delivery, custody=custody)
        requested = denied["authorization_intents"][-1]["scopes"][0]
        still_denied = self.model.reduce_delivery(
            contract, denied,
            evaluation=evaluation_context(
                custody=custody, current_launch=True, requested_scope=requested,
                authorization_intents=[cosmetic_successor(self.model, denied)],
            ),
        )
        self.assertEqual(still_denied["blocking"]["reason_code"], "host_rejected")

        successor = covering_successor(self.model, denied, requested)
        reevaluation = reevaluation_for(self.model, contract, denied)
        permitted = self.model.reduce_delivery(
            contract, denied,
            evaluation=evaluation_context(
                custody=custody, current_launch=True, requested_scope=requested,
                authorization_intents=[successor],
                reevaluation_evidence=[reevaluation],
            ),
        )
        self.assertEqual(permitted["requirements"][0]["reason_code"], "native_evaluation_required")
        replay = delivery_with_reevaluation_consumed(self.model, denied, reevaluation)
        one_shot = self.model.reduce_delivery(
            contract, replay,
            evaluation=evaluation_context(
                custody=custody, current_launch=True, requested_scope=requested,
                authorization_intents=[successor],
                reevaluation_evidence=[reevaluation],
            ),
        )
        self.assertEqual(one_shot["blocking"]["reason_code"], "host_rejected")
        wrong_launch = self.model.reduce_delivery(
            contract, denied,
            evaluation=evaluation_context(
                custody=next_launch(custody), current_launch=True,
                requested_scope=requested,
                authority_observations=[allowed_for(self.model, custody, requested)],
            ),
        )
        self.assertEqual(wrong_launch["requirements"][0]["reason_code"], "authority_launch_mismatch")

    def test_workflow_response_validation_is_structural_only(self):
        stale_but_well_formed = {
            "action_id": "151:1:1", "current": False,
            "current_action_id": "151:1:2", "reason": "superseded_launch",
        }
        self.assertEqual(
            self.model.validate_delivery_object(
                stale_but_well_formed, expected_kind="workflow-response",
                notes_max_characters=4096,
            ),
            stale_but_well_formed,
        )
        malformed = checkpoint_response_fixture(self.model)
        malformed["custody"]["action_id"] = "151:r1:9"
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.validate_delivery_object(
                malformed, expected_kind="workflow-response",
                notes_max_characters=4096,
            )

    def test_source_and_generated_installed_layout_load_same_model(self):
        source = load_model(SOURCE, "delivery_model_source_layout")
        with tempfile.TemporaryDirectory() as raw:
            store = Path(raw) / "nix-store/delivery_model.py"
            store.parent.mkdir(parents=True)
            store.write_bytes(SOURCE.read_bytes())
            installed = Path(raw) / ".agents/lib/python/delivery_model.py"
            installed.parent.mkdir(parents=True)
            installed.symlink_to(store)
            target = load_model(installed, "delivery_model_installed_layout")
            fixture = {"kind": "fixture", "items": [1, 2]}
            self.assertEqual(source.canonical_bytes(fixture), target.canonical_bytes(fixture))
            self.assertEqual(target.MODEL_INTERFACE_VERSION, 1)

    def test_nix_publication_and_managed_test_registration(self):
        nix = DEFAULT_NIX.read_text(encoding="utf-8")
        self.assertIn('".agents/lib/python/delivery_model.py"', nix)
        self.assertIn("source = ./scripts/delivery_model.py;", nix)
        just = (ROOT / "justfile").read_text(encoding="utf-8")
        self.assertIn("test_delivery_model.py", just)


if __name__ == "__main__":
    unittest.main()
```

In the same test file define these complete fixture helpers immediately above
the test class: `strict_contract_and_delivery(model)` builds a normal repository
contract with the exact `select_reviewed_output`, `publish_branch`, `open_pr`,
and `merge_pr` stages, pending delivery/merge postconditions and explicit
not-applicable tracker/cleanup postconditions from the normative appendix. Its
merge scope declares literal PR `17` and a separate `reviewed` output/data slot;
`with_observed_stages(model, contract, delivery, stage_ids)` adds strict typed
observations in contract order and recomputes their ids;
`with_conflicting_observation_ids(model, contract, delivery)` supplies two distinct bodies with one
derived id; `with_host_rejection(model, contract, delivery)` supplies the exact merge scope and a
launch-bound rejected host observation. Also define the exact helper names used
above for evaluation contexts, custody, intent successors, revocation,
reevaluation, contract/slot mutation and allowed observations. Every helper
first validates one common valid seed. Positive helpers and semantic-negative
helpers recompute every affected id/digest and validate before return so the
case reaches the intended semantic check. In particular,
`authorization_case(model, variant=...)` reseals the intent, its enclosing
contract references, selected output and revocation observation after expiry or
slot mutations; its foreign-contract variant returns two individually valid but
semantically cross-bound identities. Deliberately structural-invalid
helpers, including `with_conflicting_observation_ids`, return the one named
mutation without validating that final invalid object; the test's
`assertRaises` is the first rejection. Keep each literal local to this test
module rather than adding fixture JSON or a second model implementation.

- [ ] **Step 2: Run the focused test and observe RED**

Run:

```bash
python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py -v
```

Expected: exit nonzero because `delivery_model.py` does not exist. Record this
terminal result. If the failure instead comes from an existing unrelated import,
fix the test invocation before implementation.

- [ ] **Step 3: Implement the pure model and publication**

Implement the six public functions and two public symbols in **Interfaces**. Use exact-key helpers,
`type(value) is int`, strict UTC `Z` parsing, digest regexes, and detached values
produced through validation rather than caller-owned mutable references.

Validation order is deterministic: outer exact keys/types; derived digest/id;
member order/uniqueness; then cross-object references. For an object with a
derived member, omit that one top-level key, serialize by `canonical_bytes`, and
compare the supplied value before returning. Reject two different canonical
bodies that claim one id before reduction.

`match_scope` validates the supplied contract, intent, request, selections,
explicit time and revocation observations, then evaluates the normative table
member by member. Expiry and revocation come from the intent and bound
observations, never the tuple or ambient state. Resolve a slot only from one
validated immutable `selected-output/v1` with the same contract, slot, subject
constraints, repository, branch and base. A literal PR stays equality-only; a
selected commit never binds an unrelated PR. The payload digest may narrow only
data declared with that same slot; classification/audience remain exact. Return
a closed reason such as `scope_target_mismatch`, `scope_data_mismatch`,
`contract_mismatch`, `slot_constraint_mismatch`, `intent_expired`, or
`intent_revoked`, never a fuzzy subset result.

`reduce_delivery` validates the contract, delivery and complete evaluation
context; folds candidate facts only from the allowed `source_kind`; validates
the append-only intent chain, current custody/launch and observation effect
binding; applies rejection persistence and one-shot reevaluation; derives stage
facts/postconditions without mutating input; and scans contract order. The
caller-supplied current-launch boolean is a transaction fact, not permission.
Unmet local evidence produces a typed requirement and leaves custody active.
Only closed reasons map to blocking: missing/new user authority or an operative
host denial → `human_gate`; provider/forge wait → `external`; actual tool
transport failure → `transport`; unknown stays nonblocking/reaper-only.
`control` and `direct` may supply normalized successor intents plus all four
candidate fact arrays. `checkpoint` and `summary` require the candidate intent
array to be empty and may carry only their specified observation/evidence arrays;
an owner report therefore cannot append authority intent. Every accepted runtime
authority observation must bind the evaluation custody launch and requested
scope; a null custody/current launch is valid only for projection with no
requested effect.

Add the Home Manager publication beside the existing Python library targets.
The managed public leaf is a lexical symlink to a regular Nix-store file; source
and installed loaders use `Path.is_file()` plus `SourceFileLoader`, allow that
managed symlink topology, and reject missing paths, directories and a wrong
interface. They do not require the public leaf itself to pass a no-follow
regular-file test:

```nix
".agents/lib/python/delivery_model.py" = {
  source = ./scripts/delivery_model.py;
};
```

Add `home/common/agent-skills/tests/test_delivery_model.py` once to the existing
`agent-workflow-tests` recipe. Do not change workflow state or artifact report
selection in this task.

- [ ] **Step 4: Verify the pure gate and package scope**

```bash
set -euo pipefail
python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py -v
python3 -m unittest \
  home/common/agent-skills/tests/test_artifact_budget.py \
  home/common/agent-skills/tests/test_workflow_state.py -v
git diff --check -- \
  home/common/agent-skills/scripts/delivery_model.py \
  home/common/agent-skills/tests/test_delivery_model.py \
  home/common/agent-skills/default.nix justfile
test -z "$(git diff --cached --name-only)"
python3 - <<'PY'
import subprocess

allowed = {
    "home/common/agent-skills/scripts/delivery_model.py",
    "home/common/agent-skills/tests/test_delivery_model.py",
    "home/common/agent-skills/default.nix",
    "justfile",
}
records = subprocess.check_output(
    ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]
).split(b"\0")
changed = {record[3:].decode("utf-8") for record in records if record}
assert changed == allowed, (changed, allowed)
PY
candidate_index=$(mktemp "${TMPDIR:-/tmp}/issue-151-task1-index-XXXXXX")
rm "$candidate_index"
trap 'rm -f "$candidate_index"' EXIT HUP INT TERM
GIT_INDEX_FILE="$candidate_index" git read-tree HEAD
GIT_INDEX_FILE="$candidate_index" git add -- \
  home/common/agent-skills/scripts/delivery_model.py \
  home/common/agent-skills/tests/test_delivery_model.py \
  home/common/agent-skills/default.nix justfile
GIT_INDEX_FILE="$candidate_index" git diff --cached --check
GIT_INDEX_FILE="$candidate_index" python3 - <<'PY'
import os
import subprocess

allowed = {
    "home/common/agent-skills/scripts/delivery_model.py",
    "home/common/agent-skills/tests/test_delivery_model.py",
    "home/common/agent-skills/default.nix",
    "justfile",
}
env = {**os.environ, "GIT_INDEX_FILE": os.environ["GIT_INDEX_FILE"]}
candidate = set(subprocess.check_output(
    ["git", "diff", "--cached", "--name-only", "--"], env=env,
).decode().splitlines())
assert candidate == allowed, (candidate, allowed)
for path in sorted(allowed):
    patch = subprocess.check_output(
        ["git", "diff", "--cached", "--unified=10", "--", path], env=env,
    )
    assert 0 < len(patch) <= 65_536, (path, len(patch))
PY
rm -f "$candidate_index"
trap - EXIT HUP INT TERM
test -z "$(git diff --cached --name-only)"
```

Expected: all commands exit 0; the new test passes, existing workflow/report
tests remain green, exactly four Task 1 paths differ, and no whitespace error is
reported. The temporary index measures new files without touching the real
index. If a file needs a bounded test split to stay under the per-file cap, stop
and amend this member's Files roster, allowlist and root task index before adding
it. Then, after the signed commit, build the actual complete Task-1-only review
package from the immutable Task 1 base through that commit; require full changed
path/line coverage and unchanged package limits before review.

- [ ] **Step 5: Commit the independently reviewable pure seam**

```bash
set -euo pipefail
git add \
  home/common/agent-skills/scripts/delivery_model.py \
  home/common/agent-skills/tests/test_delivery_model.py \
  home/common/agent-skills/default.nix justfile
test -z "$(git diff --name-only)"
test "$(git diff --cached --name-only | sort)" = "$(printf '%s\n' \
  home/common/agent-skills/default.nix \
  home/common/agent-skills/scripts/delivery_model.py \
  home/common/agent-skills/tests/test_delivery_model.py \
  justfile)"
git commit -S -m "feat: add canonical delivery model" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Expected: signed commit succeeds. Independent conformance and quality review
must cover the complete Task 1 range. Do not begin Task 2 until its findings are
resolved and the pure interface above is accepted.
