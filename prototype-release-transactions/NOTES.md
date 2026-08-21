# Verdict — prototype for issue #86

Question: does the settled release contract survive concrete no-mutation dry runs for three
unlike real projects and one adversarial future shape, without project-specific core
branches?

**Answer: yes for structure, no for proof convergence.** All four shapes ran on one
unbranched core (verified mechanically — see README *Invariant*), and no scenario needed a
new profile group, publication mode, activation mode, adapter operation, effect class,
recovery action, posture, or terminal outcome. Every gap found sits in the **proof and
terminal-truth layer**, and two of them let a healthy release reach a false terminal.

## Findings

### 1. The core-derived subject-identity floor has no name in the closed vocabulary
`#88` makes exact expected/running subject identity a **mandatory core-derived** obligation
for every declared unit — a profile author cannot forget or weaken it. But `#88`'s closed
profile vocabulary is `liveness | readiness | product_smoke | observability |
rollback_readiness`, and none of those means "this is the exact artifact" or "this is the
exact running code". The prototype had to mint `subject_identity` outside the closed set,
which means evidence envelopes and terminal receipts carry a `semantic` value the settled
contract does not define. Needs either a sixth semantic, or an explicit
`derived_obligation_class` distinct from profile-declared semantics.

*Where:* `core.py::Run._derive_floor_obligations`. Visible on every shape.

### 2. Common-cutoff proof can livelock, and the failure mode is a false rollback
`#88` fixes one `proof_cutoff_at`, gives every snapshot a finite freshness window, and
requires expired snapshots to be **recollected rather than extended**. It declares no
convergence rule. When collecting the obligation set takes longer than the shortest
freshness window, recollecting one snapshot expires another, forever. The prototype's
`expired_snapshot` scenario shows a perfectly healthy platform release cycling through
recollection and then being **rolled back**, and the same case on the publish-only shape
terminating **failed** — burning a SemVer that `#81` says is never rebound — with nothing
actually wrong externally.

Missing concepts: a resolution-time feasibility check that the whole snapshot set can be
collected inside the shortest declared window; a bounded recollection budget; and a typed
outcome for *proof could not converge* that is distinct from *proof rejected*, because they
warrant opposite operator responses.

*Where:* `core.py::Run.recollect_stale`, `Run.evaluate_and_seal`.
*Reproduce:* `python3 prototype-release-transactions/drive.py platform expired_snapshot`.

### 3. Lease renewal is indistinguishable from lease loss, so it invalidates its own proof
`#82` gives leases a finite expiry and a fencing epoch; `#88` admits only evidence whose
fence matches the current epoch. Reacquiring an expired lease necessarily raises the epoch,
so an ordinary renewal *by the same owner* silently invalidates every observation that owner
already collected — and a long proving phase can renew repeatedly. The contract discusses
lease **loss** (correctly: stop before another side effect) but never lease **renewal**. It
needs one of: owner-scoped evidence admissibility, a renewal that preserves the epoch while
still fencing out other executors, or an explicit statement that renewal restarts proof.

*Where:* `core.py::Run.takeover`, `Run.evaluate_and_seal` (lease check before cutoff).

### 4. A permanently unobservable release can never terminate, and its ledger is immortal
`unknown` is never terminal (correct). Manual disposition also requires fresh authoritative
inspection (correct). `#72` gates runtime-state cleanup on a verified terminal receipt
(correct). Composed, they mean a release whose external truth becomes *permanently*
unobservable — retired provider, deleted account, decommissioned host — stays nonterminal
forever and its ledger can never be collected. The contract needs a bounded, evidence-backed
way to close or archive an unobservable release that records "the effects are unknown and no
longer observable" without pretending to know them.

*Where:* `core.py::Run.dispose_no_recovery`.
*Reproduce:* `python3 prototype-release-transactions/drive.py product unknown_external_state`.

## Observations that are friction, not gaps

* **`rolled_back` forces a per-unit disposition for every immutable publication unit.**
  `#83` allows `rolled_back` only when every affected unit reaches a restore goal or an
  accepted bounded residue. An immutable published artifact is by definition never
  restorable, so every publish-and-activate profile must author a `compensate` edge whose
  only content is "the artifact remains, referenced by nothing" — otherwise rollback is
  structurally unreachable. Expressible, but easy to get wrong, and the core cannot tell a
  harmless unreferenced artifact from real residue. Worth a conformance lint rather than new
  vocabulary.
* **Publication into a live mutable path is expressible but self-defeating.** The daemon
  shape wants build-and-sign to land directly where the resident process reads. Modelling it
  as `materialize` into a retained store plus `promote` into the live path keeps publication
  immutable *and* keeps a restore anchor; overwriting in place would satisfy the schema while
  destroying its own anchor. `#83`'s preflight `rollback_readiness` check catches this only
  for units that declare `restorable`.
* **`in_progress` needs the observation deadline to be mandatory, not optional.** Without
  it, a convergent unit with one permanently stale frozen member observes forever (the
  `fleet_stall` scenario). `#84` does declare finite observation deadlines; the prototype
  had to make the core apply a default when the profile omitted one.

## What did *not* break

* No new profile group, publication mode, activation mode, or effect class.
* No new adapter operation beyond `describe`/`inspect`/`invoke`, and no case where the core
  needed a provider verb.
* No new recovery action or posture; `restore` + `compensate` covered every shape, and
  `supersedable_only` correctly made the adversarial shape's rollback impossible instead of
  faking one.
* Terminal set held: `succeeded | abandoned | rolled_back | failed` covered every landing,
  and `unknown` never became terminal.
* Unsupported modes, missing anchors, and unsupported required collectors were all rejected
  **before the first mutation** on all four shapes.
* Cross-repository parent transactions were deliberately out of scope here; `#87` carries its
  own scenario checks.

## Disposition

Findings 1–4 are decision-shaped, not build-shaped: they change `#88`'s vocabulary and
convergence rules and `#82`'s lease semantics. Route them back to the map as decision
tickets before the release core is implemented. Then drop this worktree — the answer above is
the only thing worth keeping.
