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
- Export exactly eight names: `MODEL_INTERFACE_VERSION = 1`,
  `DeliveryModelError(ValueError)`, `canonical_bytes`, `canonical_digest`,
  `validate_delivery_object`, `validate_custody_ref`, `match_scope`, and
  `reduce_delivery`. The six callables have these exact APIs:
  `canonical_bytes(value: object, *, omit_derived: str | None = None) -> bytes`;
  `canonical_digest(value: object, *, omit_derived: str | None = None) -> str`;
  `validate_delivery_object(value: object, *, expected_kind: str | None = None,
  notes_max_characters: int) -> dict[str, object]`;
  `validate_custody_ref(value: object, *, issue: int) -> dict[str, object]`;
  `match_scope(contract: object, intent: object, requested: object, *,
  selected_outputs: list[object], at_time: str, revocation_observations:
  list[object]) -> dict[str, object]`; and `reduce_delivery(contract: object,
  delivery: object, *, evaluation: object) -> dict[str, object]`. Task 2 may not
  add a ninth name.
- The private relative-import package owns canonical primitives,
  objects/evidence, wire envelopes and reconciliation once, and is published as
  `~/.agents/lib/python/delivery_model`. Callers load only its `__init__.py` as
  interface version 1.

**Invariants:**
- The design's D1–D4, D13 and closed tables bind every field, order,
  relationship, narrowing, evidence category and response. The acyclic
  `_canonical` → `_objects` → `_wire`/`_reconcile` package is pure: no CLI, I/O,
  clock, provider, ledger, schema choice, activation, registry or import side
  effect.
- Structural validation rejects all malformed shape/type/order/identity/
  reference/graph cases and returns detached normalized values. Reduction owns
  contract, stage, scope, intent, authority, rejection and D18 consumption
  semantics over supplied facts. Workflow-state remains the freshness,
  transaction and trusted-source owner.
- Publication adds the managed library and test only; it changes no workflow or
  artifact wrapper and activates no protocol.

- [ ] **Step 1: Write public model/publication tests and capture RED**

Fixture helpers use explicit relative imports and strict synthetic builders;
they contain no policy or I/O. Public tests cover every D1–D19 scenario and
negative in the design, including canonical/closed validation, graphs,
narrowing, evidence categories, current/old custody, D18 replay/crash/transfer,
D19 scope outcomes, postconditions, cleanup/record subjects, complete response
nesting and source/installed loading. Capture the absent-package RED with
`python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py -v`.

- [ ] **Step 2: Implement and publish the pure model**

Implement the facade and private ownership above, preserving the design's exact
validation order, narrowing, reduction, typed requirements and D18 rules.
Publish and register the whole package once. Lexical package loading accepts the
managed symlink layout, cleans partial modules and fails before decode/mutation;
it never edits `sys.path` or falls back. Workflow cutover belongs to Task 2.

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
