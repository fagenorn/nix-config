# Issue 193: build-delivery serves contracts already installed in a ledger

## Problem

An owner builds every delivery object with `workflow-state build-delivery`.
Each kind other than `contract` takes the owner's installed contract as input:
`initial-intent`, `scope`, `selected-output`, `observation`,
`authority-observation` and `authorization-chain`. Before building, the builder
checks that it could have produced that contract itself. The check has two
parts. The contract's `provenance.kind` must be `explicit_user` or
`standing_repository`. And the initial intent the builder re-derives from the
contract must equal the one the contract records by id and digest.

A contract that an adapter wrote by hand, before the builder existed, fails
both parts. Such a contract is already installed in a live ledger, and the
lifecycle accepted it: installation validates the contract and its intent
against the model and never asks the builder. Its owner is still stranded.
Nodocom run `orch-1643-1655` shows how:

- #1647 could not build `selected-output`, stalled three times at `select`, and
  reported `terminal_failed` although its PR was open.
- #1648 merged but could not seal a single observation. `finish --summary-file`
  then refused its `delivery_complete` summary ("delivery summary is
  incomplete"), and it suspended on `human_gate`.

Both issues were shipped outside the ledger. `transition` treats an installed
contract as immutable, and nothing migrates one.

The acceptance criteria, numbered for reference:

- **AC1:** a ledger that holds an installed hand-built contract, whose
  provenance kind is outside the builder's source kinds, gets `selected-output`
  and `observation` objects from `build-delivery`, and `finish` reaches
  `delivery_complete`.
- **AC2:** the same input with no ledger entry, or with a mutated contract, is
  still refused.

## Solution

When the builder cannot re-derive a contract, it asks the ledgers under
`--repo-root` instead of refusing outright. If a ledger has installed that
exact contract, the builder serves it. It checks the contract against that
ledger's stored initial intent rather than a re-derived one. The derivation
path itself does not change: a contract the builder can re-derive is served
byte for byte as it is today, and no ledger is read.

The installed initial intent is then the contract's reference intent for
every kind. `initial-intent` returns it, `scope` returns the scope it declares
for the stage, and `authority-observation` accepts only its scope ids. That is
the point of the change. The ledger compares each requested scope, and each
authority observation's scope id, against the intents it holds. A re-derived
scope for a hand-built intent would not match those intents: for example, the
builder derives a slot `pr_ref` where the installed intent says `none`. Serving
such a scope would move the stall from `select` to `merge`. Downstream code
needs no change. `transition`, the reducer, `finish` and the ship-handoff
validator all check against the contract's recorded intent pair and the
ledger. None of them re-derives an intent or reads `provenance.kind`.

This gives no agent any authority it did not already have. Installation
through `control` or `direct-owner` already admits any model-valid contract,
and the ledger folds whatever it admitted. The builder only stops refusing to
seal objects for a contract the lifecycle has already accepted. It keeps
refusing any contract that no ledger has installed. The same fallback covers
any future builder change that stops an installed contract from re-deriving
(per D1, D2).

### Options considered

1. **Ledger-verified acceptance (chosen).** This is the read path described
   above. It writes nothing and is fully reversible. Contracts that re-derive
   see no behaviour change.
2. **Audited migration.** A new verb would replace an installed legacy contract
   with a builder-derived one and carry its observations forward. A re-derived
   contract has a different digest, so every observation, selection and
   authority id would have to be re-sealed. The ledger would need a write path
   that breaks `transition`'s immutability. The builder-derived initial intent
   would also mint new scopes, such as a slot PR reference, which amounts to a
   new authorization the lifecycle never granted. Rejected (D1).
3. **Widening the source kinds**, or trusting any self-consistent contract.
   This would serve a contract nobody installed, which AC2 forbids. Rejected
   (D2).

## Decisions

### 1. When the ledger is consulted (per D2, D5)

A contract *re-derives* when it is model-valid, its provenance kind is in the
builder's source kinds, and the intent the builder derives from it has exactly
the contract's recorded id and canonical digest. The builder gains one pure
predicate, `requires_installation(contract)`, which the runtime facade
forwards. It is true only for a model-valid contract that does not re-derive.
For an invalid contract it is false, so the normal `contract is invalid`
refusal still fires with no ledger read.

For every kind except `contract`, if the input is an object with a `contract`
member, the command runs the predicate on that member. Any other input goes
straight to the build, which refuses it as it does today. Only when the
predicate is true does the command look up the installed intent (§2). It then passes the result to the build as a value
through one new keyword, `installed_intent`, which is absent or `None` when
nothing was found. The builder and runtime keep their no-I/O shape and
interface version 1.

Inside the builder, the contract check now yields the contract together with
its reference initial intent:

- A contract that re-derives yields the derived intent, as today. Any
  `installed_intent` is ignored.
- A contract that does not re-derive, with `installed_intent` given, yields
  that intent. The builder first checks it again: it must be a valid
  authorization intent with no predecessor, whose id and canonical digest equal
  the contract's recorded pair. Otherwise the build refuses.
- A contract that does not re-derive, with no `installed_intent`, refuses with
  its derivation reason plus the not-installed clause (§4).

### 2. Finding the installing ledger (per D3, D4)

The lookup lives in workflow-state beside `check-launch`, and it is the only
new I/O. It computes the supplied contract's canonical digest with the delivery
model. It then walks the run directories under
`<repo-root>/.superpowers/workflows/`, in sorted order, keeping only names that
match the run-id pattern, and handles each `state.json` as follows:

- A run entry that is a symlink or not a directory is not an installing ledger.
  Neither is an absent file, a non-regular file, a file that does not parse, or
  one that has no issue entry for the contract's `issue`.
  The same goes for an entry whose delivery `contract_digest` differs. These
  are skipped.
- The first file whose entry carries the digest is re-read through the unlocked
  reader that `check-launch` uses. That reader migrates schemas 1–3 on a
  detached copy, validates the result, and never writes. The lookup extracts
  that reader into one function so the two readers cannot drift apart. If
  validation fails, the build refuses with `installing ledger <run-id> is
  invalid`. Otherwise the lookup checks the match again on the validated state:
  the installed contract's recomputed digest must equal the supplied contract's
  digest. It then returns the root intent of the delivery's
  `authorization_intents`.
- If nothing matches, the lookup returns `None`. A root with no workflows
  directory has nothing to match.

The lookup takes no lock. `atomic_write_state` publishes with `os.replace`, so
an unlocked reader sees a whole file. Taking the lock would create
`state.lock`, which is a write. Any ledger that installed the contract holds
the same root intent, because the contract pins that intent's id and digest.
So the first match is sufficient. The lookup reads only ledgers under
`--repo-root`, never under a worktree, and it adds no flag and no input member.
An in-flight owner re-running its existing invocation after the helper update
is therefore served.

### 3. What each kind returns (per D6)

| Kind | For a contract that re-derives | For an installed contract that does not |
|---|---|---|
| `initial-intent` | the derived intent | the installed root intent, byte for byte |
| `scope` | the intent's declared scope for the stage | the same rule, applied to the installed intent |
| `authority-observation` | `scope_id` must be one of the intent's scope ids | the same rule, applied to the installed intent |
| `authorization-chain` | roots checked against the contract's recorded pair (unchanged) | unchanged |
| `selected-output`, `observation` | unchanged | unchanged once the contract is served |

A stage's scope is the one scope in the reference intent whose `action` and
`effect` equal the stage's own. `STAGE_ACTIONS` gives each stage kind a
distinct action, so a contract that re-derives always has exactly one, and it
equals today's `_scope` output byte for byte. If an intent declares zero
matching scopes, or more than one, `scope` refuses. The old claim that declared
and actual scopes "come from the one `_scope` function" becomes "come from the
one reference intent", and it holds whichever way that intent was obtained.

### 4. Refusal behaviour (per D7)

Every refusal still exits 2, prints nothing on stdout, and writes one stderr
line, `workflow-state: build-delivery refused: <reason>`.

| Input | Ledgers under `--repo-root` | Outcome |
|---|---|---|
| model-invalid contract | not read | `contract is invalid: …` (unchanged) |
| contract that re-derives | not read | served exactly as today |
| contract that does not re-derive (reason R) | none installs it | `R; no ledger under the repo root installs this contract` |
| contract that does not re-derive | installed, ledger valid, intent verifies | served (§3) |
| contract that does not re-derive | the first matching ledger fails validation | `installing ledger <run-id> is invalid` |
| contract that does not re-derive | installed, but the intent fails the builder's re-check | `installed initial intent does not match the contract` |
| installed contract with one member mutated | the original is installed | its digest matches nothing, so `R; no ledger …` |

R is one of three existing texts, left unchanged:

- `source kind of the contract cannot source an initial intent`
- `derived intent does not match the contract's initial intent`
- `derived intent cannot be regenerated: the contract has no reviewed slot or worktree stage`

The first applies when the provenance kind is outside the source kinds, and in
that case derivation is not attempted. The other two apply when derivation
mismatches or cannot run.

`scope` adds one refusal: `the contract's initial intent declares no single
scope for stage <id>`. Every other refusal stays as it is: `unknown stage`,
`unknown scope`, `authorization chain: …`, the selection refusals,
`builder input keys: …`, the unsupported kind, source and verdict refusals,
`unknown builder kind`, and every `--kind contract` refusal, including the
resolver relay and the worktree-policy veto from #181.

### 5. Documentation (per D11)

- **`build-delivery --help`.** The authoritative statement. "It takes no lock,
  reads no ledger or clock and writes nothing" becomes "It takes no lock, reads
  no clock and writes nothing." It gains one more sentence: "A contract the
  builder cannot re-derive is served only when a ledger under --repo-root has
  installed it, and then against that ledger's stored initial intent; that is
  the only time it reads a ledger."
- **`CLAUDE.md`.** In the "Delivery objects are built" bullet, "read-only — no
  lock, ledger, clock or write" is restated the same way.
- **Docstrings.** The `command_build_delivery` docstring, the build module's
  docstring (the scope-source sentence, §3) and the contract-check docstring.
- **`from-issue/ship-handoff.md`.** "the one initial intent the builder
  regenerates from that contract" becomes "the one initial intent the builder
  prints for that contract".
- The sanctioned-exception sentences stay, because the builder still writes
  nothing. ship-issue already says "fed the installed contract" and stays too.
  The #171 and #181 specs are point-in-time records and are not edited. This
  ledger refines #171 D3's read-only builder.

## Test seams (per D8)

1. **Delivery-loop CLI seam.** Uses `DeliveryLoopTest.deliver` in the delivery
   workflow suite: `build-delivery` runs as a subprocess, `direct-owner`
   installs, and the test drives `checkpoint-delivery` and then `finish
   --summary-file`. `deliver` gains a contract source. The builder source is
   today's. The *hand-built* source takes a built contract and re-seals it:
   - the provenance kind becomes `orchestrate-issues`;
   - the initial intent's `open_pr` and `merge_pr` scopes declare the literal
     PR ref `{"kind":"literal","value":"5"}`, which the builder never derives
     but the model binds;
   - its source reference changes;
   - the ids are re-sealed, and the contract records the new intent's pair.

   With that source:
   - *AC2, no ledger entry.* Before installation, every contract-taking kind
     refuses with the not-installed clause, exit 2 and empty stdout.
   - *AC1.* After installation, `initial-intent` returns the hand-built intent
     byte for byte. The ship handoff built from that intent validates. The full
     loop then runs with builder outputs only, and `finish` returns
     `delivery_complete`. The literal PR ref means an implementation that
     re-derives a scope or a scope id fails the loop: the checkpoint parks on
     `authorization_intent_required`, or `unknown scope` refuses. The
     sub-assertion that depends on slot-bound PR numbers, where a second opened
     PR is refused, stays on the builder source.
   - *AC2, mutated.* A copy of the installed contract with one member changed
     refuses with the not-installed clause.
2. **Ledger-read seam.** Same harness. The test takes one hand-built contract
   and one contract that re-derives. For each, it writes a `state.json` under
   its own run directory whose entry for the issue carries that contract's
   digest but fails validation. The hand-built contract then refuses with
   `installing ledger <run-id> is invalid`. The contract that re-derives still
   builds, which proves the derivation path reads no ledger.
   `check-launch`'s existing tests guard the shared reader.
3. **Help seam.** `test_help_states_the_contract_resolution_root` pins the new
   clause, with whitespace normalized.

The existing builder tests (`initial-intent`/`scope` regeneration, the builder
delivery loop, evidence kinds) stay unchanged and pin the byte-identical
derivation path. Verification uses the resolved `nix-build` and
`agent-workflow-tests` command ids.

## Out of scope

- **Nodocom-shaped intents that declare `pr_ref: none` on PR stages.** Once
  served, such an issue folds selection and publication. But the model binds a
  PR number only through a literal or slot `pr_ref`, so its PR stages never
  fold and `delivery_complete` needs a successor intent from `control`. That
  is a new authorization, and it is the adapter's call, not this change's
  (D9).
- #192, the neighbouring case: legacy worktree paths that cannot get a contract
  at all.
- Migrating or re-homing an installed contract, or relaxing `transition`'s
  immutability.
- Changing `--kind contract`, the source kinds, or the contract, intent or
  ledger schemas.
- Serving scopes that successor intents declare. The builder still admits only
  the reference intent's scopes, as it does today.
- A legacy contract whose reviewed slot is not the builder's `reviewed` commit
  slot. The selection keeps the builder's vocabulary, and the ledger refuses
  the mismatch at checkpoint.
- Repairing nodocom run `orch-1643-1655`, and moving these scripts into
  `agent_tools` (D10).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Serve a ledger-installed contract that does not re-derive by checking it against the installing ledger's stored initial intent (the issue's first remedy). No migration, and no ledger write. | Issue "Expected", option 1. `transition` treats an installed contract as immutable. The-bar YAGNI. Autonomous rule: never self-answer a request for new authorization. | Audited migration. It re-seals every id under a new digest, needs a ledger write path that breaks immutability, and its derived intent mints scopes (a slot PR reference) that nobody authorized. |
| D2 | Fallback only. A contract that re-derives is served exactly as today and no ledger is read. A model-valid contract that does not re-derive is served if and only if a ledger under `--repo-root` has installed it. There is no provenance allowlist and no date cutoff, so a future derivation change is covered too. | Installation (`control`/`direct-owner`) already admits any model-valid contract, and the ledger is the lifecycle's trust anchor. The builder "grants no authority". AC2. | Always consulting ledgers, which adds reads and failure modes to every call. Widening `_SOURCE_KINDS`, which serves uninstalled hand-built contracts. A cutoff date, which is arbitrary and misses later derivation changes. |
| D3 | Find the installing ledger by scanning every run under `<repo-root>/.superpowers/workflows/`, matching the issue entry's installed contract by canonical digest. There is no new flag and no new input member. | The issue title: the stranded owners are *in flight* and re-run the invocation their loaded skill prose already fixes. The-bar token economy. The contract names its issue. | A required or optional `--run-id`, or a run id in the input. Either changes the callers' shape, and an in-flight owner on the old prose would stay refused. |
| D4 | Read without a lock, as `check-launch` does. Non-matching, absent, non-regular or unparsable files are skipped. The first raw match, in sorted run order, is fully validated through `check-launch`'s reader, which is extracted into one shared function. An invalid match refuses and names its run. The match is re-checked on the validated state. | `check-launch` precedent (atomic `os.replace` publication, and lock creation is a write). The-bar DRY (two readers that must change together) and fail loud. The contract pins its root intent, so any match holds the same intent. | Taking the state lock, which is a write and breaks the read-only contract. Refusing on any unreadable unrelated ledger, which lets one stale run block every legacy contract. Raw-JSON trust, where an unvalidated ledger could supply the intent. |
| D5 | Keep the builder pure. It gains `requires_installation(contract)`, forwarded by the runtime, and `build` takes the found intent as a value (`installed_intent`). workflow-state runs the predicate and does all the I/O. The builder checks the intent again (a valid root intent whose id and digest equal the contract's recorded pair). Interface version stays 1. | Builder docstring: no I/O. #181 D5 rejected a callback injected into the builder. The-bar defense in depth. agent-helpers: the command is a thin shell. | An injected lookup callable, which puts I/O inside the pure seam. A pre-read map of every ledger, which is an eager scan. An exception-driven retry in the command, which couples it to refusal classes. |
| D6 | All six contract-taking kinds read the contract's *reference* initial intent, derived or installed. `initial-intent` returns it. `scope` returns its one declared scope with the stage's action and effect, and zero or several refuse. `authority-observation` admits its scope ids. Output for a contract that re-derives stays byte-identical. | The ledger's `match_scope` compares `pr_ref` and the other members against held intents, and its delivery validation requires authority scope ids to be held. ship-handoff builds `authorization_intents` from `initial-intent`. `STAGE_ACTIONS` actions are distinct. | Changing only the contract check. `scope` and `authority-observation` would still re-derive and disagree with the installed intent, parking at `merge` on `authorization_intent_required`. |
| D7 | Every existing refusal text stays. When a contract neither re-derives nor is installed, its derivation reason gains `; no ledger under the repo root installs this contract`. There are three new texts: `installed initial intent does not match the contract`, `installing ledger <run-id> is invalid`, and `the contract's initial intent declares no single scope for stage <id>`. | Existing `assertIn(b"derived intent")` pins. The-bar: the log stream is the debugger (say why a legacy contract is refused). #171's exit-2, empty-stdout contract. | New replacement texts, which break pinned diagnostics. A silent reuse of the old text, which hides that the ledger was consulted. |
| D8 | The regression runs at the `DeliveryLoopTest.deliver` CLI seam with a hand-built fixture: provenance `orchestrate-issues`, and PR-stage scopes that declare the literal PR ref `"5"`. That literal is completable but never builder-derived, so any implementation that re-derives fails. The seam covers the pre-install refusal, the mutated-contract refusal and an invalid-ledger refusal, and a derived build next to that invalid ledger proves the ledger-free path. | AC1 and AC2. The-bar: tests that can fail, with fixtures shaped like production. The existing end-to-end loop is the highest seam. | A pure builder test with a fake intent only, which misses the scan and the reader. A fixture whose scopes equal the builder's, which cannot detect re-derivation. |
| D9 | Out of scope: completing intents that declare `pr_ref: none` on PR stages (the nodocom shape). This change serves them every builder object. Their PR stages fold only after a successor intent from `control`. | The model's PR binding accepts only literal or slot refs (`none` bound nothing before #171 either). A successor intent is new authorization. The suggested scope boundary. | Teaching the model to bind the opened PR for `pr_ref: none`, which changes authority matching for every contract. Minting the successor here. |
| D10 | Edit the existing flat scripts (build module, runtime facade, workflow-state). There is no new module or command, and no move into `agent_tools`. | `docs/standards/agent-helpers.md`: new *helpers* go to the package, and a legacy script moves with its cluster's PR. Precedent: #181 edited the same files. Sibling issues edit workflow-state's `control`, so this change stays beside `check-launch`/`build-delivery`. | Moving the delivery cluster into `agent_tools` here, which is its own PR. |
| D11 | Prose surfaces: `build-delivery --help` (authoritative, and pinned by the help test), the `CLAUDE.md` delivery bullet, three docstrings, and ship-handoff's "regenerates" sentence. The sanctioned-exception sentences, ship-issue and the #171/#181 specs stay unchanged, and this ledger refines #171 D3. | The-bar: truthful statements, and point-in-time records keep their text. #181 D7 precedent (help text is authoritative). | Leaving "reads no ledger" in place, which becomes false. Editing accepted specs. |
