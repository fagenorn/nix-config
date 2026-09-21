# Task 1: Build and publish the pure delivery model

**Files:**
- Delete: `home/common/agent-skills/scripts/delivery_model.py`
- Create: `home/common/agent-skills/scripts/delivery_model/__init__.py`
- Create: `home/common/agent-skills/scripts/delivery_model/_canonical.py`
- Create: `home/common/agent-skills/scripts/delivery_model/_objects.py`
- Create: `home/common/agent-skills/scripts/delivery_model/_wire.py`
- Create: `home/common/agent-skills/scripts/delivery_model/_reconcile.py`
- Create: `home/common/agent-skills/tests/_delivery_model_fixtures.py`
- Create: `home/common/agent-skills/tests/test_delivery_model.py`
- Modify: `home/common/agent-skills/default.nix`
- Modify: `justfile`

**Interfaces:**
- Produces `MODEL_INTERFACE_VERSION = 1` and `DeliveryModelError(ValueError)`.
- Produces `canonical_bytes(value: object, *, omit_derived: str | None = None) -> bytes` and `canonical_digest(value: object, *, omit_derived: str | None = None) -> str`. Bytes are sorted-key compact UTF-8 JSON plus one newline; booleans never pass integer fields; duplicate keys remain a boundary-decoder concern. Digest is `sha256:<64 lowercase hex>` over canonical bytes after omitting only the named top-level derived member.
- Produces `validate_delivery_object(value: object, *, expected_kind: str | None = None, notes_max_characters: int) -> dict[str, object]`. It dispatches the closed v1 kinds in the spec, validates exact keys/types/order/derived identities/cross-references, and returns a detached normalized copy. It also accepts the nested strict `delivery` value, v2 checkpoint/handoff/summary envelopes, and closed workflow-response union used by Task 2; it does not validate workflow schema, ledger freshness, source authenticity or legacy result rows.
- Produces `validate_custody_ref(value: object, *, issue: int) -> dict[str, object]`, accepting only the implementation/remainder union and its exact derived action id.
- Produces `match_scope(contract: object, intent: object, requested: object, *, selected_outputs: list[object], at_time: str, revocation_observations: list[object]) -> dict[str, object]`. The intent contains the declared scope, expiry and revocation key; the contract supplies the digest and complete slot constraints. The return has exactly `matched` (bool), nullable `scope_id`, and `reason_code` (closed string). It applies only the narrowing table and never reads time/ledger state.
- Produces `reduce_delivery(contract: object, delivery: object, *, evaluation: object) -> dict[str, object]`. `evaluation` has exactly RFC3339 `at_time`, nullable `custody`, nullable boolean `current_launch` (null exactly when custody is null), nullable `requested_scope`, `source_kind` (`control | direct | checkpoint | summary`), and sorted candidate `authorization_intents`, `authority_observations`, `reevaluation_evidence`, and `delivery_observations`. The result has exactly complete normalized `next_delivery`, ordered `pending_stage_ids`, nullable `next_stage_id`, sorted `requirements`, `completion_state` (`pending | delivery_complete`), nullable typed `blocking`, and nullable strict `authority_evaluation`. Workflow-state can persist `next_delivery` without reconstructing accepted facts or consumption state.
- `__init__.py` exports exactly these eight names and no other public names. The
  four underscore modules are private, use normal relative imports, and own
  canonical primitives, objects/evidence, wire envelopes and reconciliation,
  respectively. Publish the whole directory at
  `~/.agents/lib/python/delivery_model`; callers explicitly load its
  `__init__.py` as interface version 1.

**Invariants:**
- Per D1–D4 and D13, this package is the sole owner of new delivery validation,
  canonical identity, narrowing and reduction. `_canonical` → `_objects` →
  `_wire`/`_reconcile`; the facade imports them without cycles, duplicate policy,
  registries or caller injection. It has no CLI, I/O, clock, provider, ledger,
  schema selection, activation or import side effect.
- All strict objects reject unknown/missing keys, bool-as-int, invalid nulls, duplicate or unsorted set-like arrays, bad RFC 3339 UTC values, bad ids/digests, broken intent predecessors, stage graph cycles/forward references, slot mismatches and conflicting observation identities.
- `stages`, `stage_facts`, and `pending_stage_ids` retain contract order. Other set-like arrays are sorted by scalar or member id and unique.
- Selection precedes every slot use; publish precedes open. Selected output has
  explicit nonempty acceptance/review/test evidence arrays; merge requires all
  three and an open PR, not `implementation_delivered`. Fresh post-merge
  reachability or record presence independently observes delivery.
- A host rejection remains operative until either a valid post-rejection intent covering the exact tuple or accepted reevaluation evidence independently permits one fresh evaluation. Before exposing that evaluation, the result appends one `authority-evaluation-consumption/v1` keyed by rejection and basis; workflow-state persists it first. Replay, transfer and crash never reissue the same basis. Human completion may satisfy an exact effect while preserving the rejection and granting no mutation right.
- An intent-revocation observation carries the exact target intent id and revocation key. Direct/control may retain trusted late facts under their original old launch, but only a current-custody allowed fact authorizes the current effect.
- `validate_delivery_object` checks structural/canonical truth only. `reduce_delivery` owns intent-chain, contract/slot, launch/effect, rejection and one-shot reevaluation semantics over caller-supplied facts. Workflow-state remains the transaction/trusted-source owner and supplies the current time/launch; neither the model nor artifact-budget authenticates an opaque host reference.
- The publication stanza adds one library target; it does not change the installed workflow/artifact wrappers or activate a new protocol.

- [ ] **Step 1: Write public model/publication tests and capture RED**

Private _delivery_model_fixtures.py uses explicit relative imports and strict
synthetic builders receiving the model; valid seeds normalize, deliberate
invalid builders leave rejection to the public assertion. It has no policy, I/O,
clock, provider, ledger, entry point, fallback or second implementation.

Public tests cover D1–D19 model behavior: canonical identity/bool-as-int; closed
shape/order/reference/graph validation; intent chain/expiry/revocation; exact
slot/literal/data/spend narrowing; all acceptance/review/test categories;
current/old launch authority; D18 consumption/replay/crash/transfer/bases and
rejection precedence; D19 missing/wrong/uncovered/covered/post-fold scope; every
stage and independent postcondition; exact cleanup/record subjects; full
workflow-response nesting; source/installed loading failures. Run and retain
python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py -v
before implementation; RED must be the absent package, never an invented result.

- [ ] **Step 2: Implement and publish the pure model**

Implement the eight-name interface. Keep __init__.py a facade and the acyclic
_canonical → _objects → _wire/_reconcile ownership. Validate outer shape/type,
identity, ordering, then references; return detached values. Apply the exact
narrowing/reduction/response contract, including typed requirements, D18
consumption/action and authority time/custody rules. The model validates
legacy-result placement, while Task 2 composes the legacy row validator; it owns
no workflow I/O, freshness or source authentication.

Publish the managed .agents/lib/python/delivery_model directory and register its
test once. Load only lexical __init__.py as a package, clean partial members,
accept managed directory symlinks and fail before decode/mutation for
missing/partial/wrong input. No sys.path, fallback or workflow-state/artifact
cutover belongs to Task 1.

- [ ] **Step 3: Verify, scope, sign and review**

Run exactly:

    python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py -v
    python3 -m unittest home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_workflow_state.py -v
    git diff --check

A temporary index initialized from HEAD must contain only the ten declared paths
(standalone deletion, five package files, fixture/test, publication and optional
justfile), every U10 diff 1..65,536 bytes, while the real index stays empty. The
immutable Task-1 range has nine net paths. Stage only that allowlist; sign
feat: add canonical delivery model with the Codex coauthor. Independent
complete-range conformance and quality must accept it before Task 2. No
activation, workflow schema change, live-ledger access or partial cutover.
