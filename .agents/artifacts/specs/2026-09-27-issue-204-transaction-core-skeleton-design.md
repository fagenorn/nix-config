# Transaction core 1/6: store, identity, lifecycle skeleton and the asserted sweep harness

Design for [#204](https://github.com/fagenorn/nix-config/issues/204), slice 1 of 6 of
[#123](https://github.com/fagenorn/nix-config/issues/123), 2026-09-27, against main `b31c6e2`.
Written in autonomous mode: every choice below is an agent judgment inside the issue's
delegated scope, recorded in the decision ledger, not a human answer.

## Problem

The repository has a settled transaction contract (#82 identity, lifecycle, terminals and crash
safety; #72 runtime-state placement; #117 attempts as first consumer) and a throwaway prototype
that exercised it (`prototype-release-transactions/` at commit `dc98ba9`), but no shipped module.
Every later slice of #123 (leases and fencing, write intent and retry, proof and receipts,
recovery, terminal truth) needs a real place to land: a persisted transaction with a stable
identity, a closed lifecycle that cannot be forged into a false terminal, and an executable
harness that proves the core stays neutral across unlike project shapes. Today a later slice
would have to invent all three at once, and the prototype's sweep only prints where cells land,
so nothing fails when the core regresses.

## Solution

Ship one standard-library-only library module, `agent_tools.transaction_core`, that owns
exactly four things: the on-disk store under a caller-supplied root, `rel_` + UUIDv7 identity with
creation-key deduplication, the closed lifecycle transition table with its terminal guards, and a
strict closed-schema validator for everything it reads or writes. It has no command-table row and
no caller yet (D1).

Beside it, in the test tree only, port the prototype's simulated world and four project shapes as
fixtures, plus a small fixture executor that drives those shapes through the shipped store's
public interface. The prototype's print-only sweep becomes an asserted table keyed by
(shape, scenario); this slice fills the `success` row for all four shapes. A neutrality test
tokenizes the shipped module and fails on any project name, provider name or provider verb.

Two options were weighed for how the sweep reaches the core:

- **Fixture executor over a thin core (chosen, D6).** The core only persists and transitions;
  the fixture executor walks each shape's verification, publication, activation and proof against
  the simulated world and asks the core to advance. Later slices move action protocol, leases,
  retry and proof *into* the core one at a time, and the executor shrinks as they do.
- **Port the prototype's whole `Run` engine now.** That drags leases, retry budgets, adapter
  resolution, recovery and receipts into slice 1 — all explicitly out of scope — and ships a
  thousand lines whose persistence story does not exist yet.

A third, a core-side "driver" interface the world plugs into, was rejected as speculative
abstraction: nobody but the fixture would call it until the adapter slice defines the real
describe/inspect/invoke seam (#85).

## Decisions

### Module and interface

`agent_tools.transaction_core` is a library module (D1). `lib/agent-tools.nix` already
import-checks every module under `agent_tools`, so `just build` covers it with no Nix edit; it gets
no row in the command table because no command calls it until the attempts cutover (#125).

Public surface, all importable names:

- `TransactionStore(root)` — `root` is a `pathlib.Path` that must be absolute and must already
  exist as a directory; a relative or missing root raises `TransactionError` at construction. The
  store never derives, creates or searches for a root (D2).
- `store.create(creation_key, subject) -> Transaction` — deduplicated create (D4).
- `store.load(transaction_id) -> Transaction` — lock-free validated read.
- `store.advance(transaction_id, target, *, reason, external_state=None) -> Transaction` — one
  lifecycle transition (D7, D8).
- `Transaction` — a frozen dataclass snapshot: `transaction_id`, `creation_key`, `subject`,
  `state`, `parked_from`, `revision`, `events` (a tuple of event mappings). Its `subject` and
  events are read-only copies; mutating them cannot reach disk.
- `STATES`, `TERMINALS`, `TRANSITIONS` — the closed vocabularies as module constants, the single
  home later slices extend.
- Errors, all subclasses of `TransactionError`: `StateInvalid` (a file fails the closed schema),
  `TransactionBusy` (the lock is held elsewhere), `TransitionRefused` (illegal edge, terminal
  source, or ungrounded terminal), `CreationConflict` (same creation key, different subject),
  `UnknownTransaction` (no such id under this root). A caller can tell every refusal apart
  without parsing text (D9).

The module never logs to stdout and never touches anything outside `root`.

### Identity

`transaction_id` is `rel_` followed by a lowercase hyphenated RFC 9562 UUIDv7, hand-rolled from
the standard library: 48-bit Unix milliseconds from the wall clock, version nibble `7`, 12 random
bits, variant `10`, 62 random bits, randomness from `secrets`. No monotonic-within-millisecond
counter: ids are opaque, and the event sequence, not id order, carries ordering (D3). The validator
checks the full pattern, version and variant before any id is joined onto a path, so a crafted id
cannot traverse out of `root`.

### On-disk layout

Under the caller's `root` the store writes only:

```
<root>/creation.lock                    stable lock file serializing creates
<root>/creation-keys/<sha256>.json      one index entry per creation key
<root>/<transaction_id>/lock            stable per-transaction lock file
<root>/<transaction_id>/state.json      the transaction's whole state
```

`<sha256>` is the lowercase hex SHA-256 of the UTF-8 creation key, so arbitrary keys map to safe
file names. Lock files are created once and never deleted. Temporary files live in the directory
of the file they replace and never survive a successful write. One directory per transaction; the
index directory's name cannot collide with a `rel_` id. The caller places `root` under the #72
runtime subtree and owns its sentinel; the core neither writes nor checks the sentinel (D2).

### State schema `transaction-state/v1`

`state.json` is one closed JSON object; an unknown, missing or ill-typed key anywhere is
`StateInvalid`:

| Key | Type | Rule |
|---|---|---|
| `schema` | string | exactly `transaction-state/v1`; anything else fails closed |
| `transaction_id` | string | `rel_` + valid UUIDv7; equals the directory name |
| `creation_key` | string | non-empty; its SHA-256 names an index entry pointing back to this id |
| `subject` | object | opaque, immutable JSON object the core never interprets |
| `state` | string | member of `STATES`; equals the fold of `events` |
| `parked_from` | string or null | non-null exactly when `state` is `attention_required`; equals the fold |
| `revision` | integer | equals `len(events)` |
| `events` | array | the append-only typed history below |

The history lives inside `state.json` rather than a separate append file, so one atomic replace
publishes state and history together and no crash can leave them disagreeing (D5). Two event
types exist, both closed:

- `created`: `{"seq": 1, "type": "created", "at": <timestamp>}` — exactly one, always first.
- `transitioned`: `{"seq": n, "type": "transitioned", "at", "from", "to", "reason",
  "external_state"}` — `from`/`to` are `STATES` members forming a `TRANSITIONS` edge, `from`
  equals the fold before it, `reason` is a non-empty string, `external_state` is `"known"`,
  `"unknown"` or null, and must be `"known"` when `to` is a terminal.

`seq` runs 1..n without gaps and alone orders history; `at` is not required to be monotonic,
because the wall clock may step back. `reason` is caller-supplied and must be secret-free (#72),
as must `subject`; the core stores both verbatim. `at` is a UTC timestamp `YYYY-MM-DDTHH:MM:SS.mmmZ`; no event may
follow one whose `to` is a terminal. `state`, `parked_from` and `revision` are a projection: the
validator folds the events and requires the stored projection to match, so a hand-edited `state`
cannot disagree with history. Loading uses the strict JSON hooks `reject_duplicate_keys` and
`reject_nonfinite_literal` from `agent_tools.canonical`; writing uses sorted keys, compact
separators, ASCII escaping and a trailing newline. The subject must survive that strict round trip
(no non-finite numbers, string keys only) or `create` refuses it.

This is deliberately #82's model cut to this slice: no leases, actions, attempts, authorization,
observation or evidence-reference events. Each later slice adds its keys and event types under a
new schema version with an adjacent migration, never by loosening v1 (D5).

### Write discipline

Every mutation follows one sequence: open the stable lock file, take `fcntl.flock` exclusive and
**non-blocking**; on contention raise `TransactionBusy` immediately, before reading or writing
anything (D10). Under the lock, reread `state.json`, validate it fully (a failure raises
`StateInvalid` with nothing written), compute the new state by appending events to the validated
history, validate the candidate — including that the prior events are its exact prefix, the inner
check of append-only — then write a temporary file in the transaction directory, `fsync` it,
`os.replace` it over `state.json` and `fsync` the directory. This mirrors the shipped
workflow-state write path. `load` takes no lock and creates nothing: atomic replace guarantees it
sees a whole file, and it validates what it reads. Only `create` makes new paths: `advance` opens
the existing lock file without `O_CREAT`, so an id with no transaction directory is
`UnknownTransaction` and a directory holding state but no lock file is `StateInvalid`; neither call
ever leaves a stray file or directory behind (D13). Every error message names the transaction id
or path and the rule that failed, so a refusal is diagnosable from its text alone.

### Creation and deduplication

`create(creation_key, subject)` takes the root creation lock (non-blocking, `TransactionBusy` on
contention) and then:

1. If the key's index entry exists, validate it (closed object: `schema`
   `transaction-creation-key/v1`, `creation_key`, `transaction_id`, with the entry's key equal to
   the requested one). If that transaction's `state.json` exists, validate it fully and compare
   its subject to the requested subject by `agent_tools.canonical.telemetry_digest`, the package's
   one canonical-JSON home, so `1`, `1.0` and `true` stay distinct: equal returns the existing transaction and writes
   nothing, so no second `created` event exists; different raises `CreationConflict`. If the state
   is missing, a previous create crashed after writing the index; finish that creation under the
   indexed id.
2. Otherwise mint an id, atomically write the index entry, then create the transaction directory
   and its lock file and atomically write the initial state (`state: created`, one `created` event,
   `revision: 1`).

Writing the index before the state is what makes a crash between the two recoverable without an
orphan: the index is the durable intent, and a retry completes it (D4).

### Lifecycle

`STATES` are the seven forward states `created`, `awaiting_verification`, `ready`, `publishing`,
`published`, `activating`, `proving`; the two nonterminal parkings `attention_required` and
`recovering`; and exactly four terminals `succeeded`, `abandoned`, `rolled_back`, `failed`.
`TRANSITIONS` is an explicit closed edge set (D7):

| From | Allowed targets |
|---|---|
| `created` | `awaiting_verification`, `attention_required`, `abandoned` |
| `awaiting_verification` | `ready`, `attention_required`, `abandoned` |
| `ready` | `publishing`, `attention_required`, `abandoned` |
| `publishing` | `published`, `attention_required` |
| `published` | `activating`, `proving`, `attention_required` |
| `activating` | `proving`, `attention_required` |
| `proving` | `succeeded`, `attention_required` |
| `attention_required` | the recorded `parked_from`, `recovering`, `abandoned`, `failed` |
| `recovering` | `rolled_back`, `attention_required`, `abandoned`, `failed` |
| any terminal | nothing |

`published → proving` is the declared-`activation: none` path the prototype's publish-only shape
takes. Entering `attention_required` records the state it left as `parked_from`; leaving it
returns only to that state or to `recovering`, so a park cannot be used to skip a phase.
`abandoned` is admissible only before the first publication effect or from a parking, and
`failed` only from a parking, matching #82's grounds for them; the positive grounds themselves
(no effect exists, recovery exhausted, required proof accepted) are later slices' evidence rules.

`advance` refuses with `TransitionRefused`, before any write, when the source is a terminal, the
edge is not in `TRANSITIONS`, the target is not in `STATES` (fail loud: no fallback), or the target
is a terminal and `external_state` is not exactly `"known"` — so unknown or unstated external
reality can never produce a terminal (D8). The refusal does not reroute the transaction into
`attention_required`; parking is an explicit caller transition with its own event.

### Sweep harness (test fixtures only)

Ported from `dc98ba9` into the test tree with provenance in each file's docstring, never under
`python/` (D6):

- **World fixture** — the prototype's `World` and `SimAdapter` describe/inspect/invoke seam, its
  fault vocabulary and predicate hooks, unchanged in behavior.
- **Shapes fixture** — the four shapes `platform`, `product`, `daemon`, `library`, ported whole as
  authored data (subject, profile groups, adapter registry). Provider names live here, which is
  exactly why this is fixture code and not the core.
- **Scenario fixture** — only the `success` scenario for now; each later slice ports the scenario
  definitions its rows assert, so no scenario sits in the tree unasserted.
- **Fixture executor** — a happy-path walker: create the transaction (creation key
  `<shape>:<scenario>`, the shape's subject), check candidate verification through the world,
  then run each publication action in dependency order (inspect, invoke if absent, inspect),
  then activation (or skip to `proving` when the profile declares `none`), then collect every
  required profile obligation plus the prototype's derived publication-visible and
  running-subject-identity floor, and advance at each boundary. Any observation other than
  `satisfied` parks the transaction in `attention_required` with the observation as the reason,
  and `external_state` is passed as `"known"` only when every inspection returned a definite
  outcome. It deliberately carries none of the prototype's lease, retry, authorization or
  recovery logic; those arrive in the core in later slices (D6).

The asserted table maps each (shape, scenario) cell to its expected landing: the final state and
the exact sequence of states the persisted history passes through. The `success` row expects
`succeeded` for all four shapes, with `library` skipping `activating` and the other three passing
through it. The test reloads each transaction from disk with a fresh `TransactionStore` before
comparing, so it asserts persisted truth, not in-memory state.

### Neutrality check

A test-side checker takes module source text, removes comments (by `tokenize`) and docstrings
(module, class and function docstrings located by `ast`), splits every remaining token —
identifiers and string literal contents alike — into lowercase alphanumeric words (splitting on
`_`, punctuation and case boundaries, so `GitPush` is `git`, `push` and `HTTPServer` is `http`,
`server`; D19), and reports any word in three closed lists (D11):

- project names: `nix`, `nixos`, `darwin`, `fagenorn`, `palmier`, `nodo`, `argus`;
- provider names: `github`, `gitlab`, `gh`, `git`, `ghcr`, `docker`, `oci`, `railway`,
  `launchd`, `launchctl`, `plist`, `homebrew`, `brew`, `cachix`, `sops`, `anthropic`, `claude`,
  `codex`;
- provider verbs: `push`, `merge`, `tag`, `deploy`, `switch`, `restart`, `rebuild`, `upload`,
  `rebase`, `checkout`.

Word matching replaces the prototype's substring match, which flags `oci` inside `associated`.
The test asserts the checker finds nothing in the shipped module's source (read through
`inspect.getsource`), finds `deploy` when a function named with it is appended to that source,
and finds nothing when the same word is appended only as a comment — so the stripping is proven,
not assumed.

### Wiring and documentation

`just agent-workflow-tests` lists its test files explicitly, so the two new test files are added
to that recipe. CLAUDE.md's "Agent helper package" paragraph gains one sentence naming
`agent_tools.transaction_core` as the first core slice: a library with no command and no caller
until #125's cutover, so the lifecycle paths it describes stay the shipped implementation (D12).

## Test seams

Three seams, all through public interfaces, following the unittest style of
`tests/test_agent_tools_canonical.py` and the relative-import support modules under `tests/`:

1. **Store interface plus its documented layout.** `TransactionStore` under a
   `tempfile.TemporaryDirectory` root. Observable behavior only: returned snapshots, errors
   raised, and the bytes of `state.json` and the index entry. Covers the id pattern and UUIDv7
   bits, dedup (same id, one `created` event, unchanged bytes), `CreationConflict`, crash-resume of
   an index-without-state create, relative/missing root refusal, schema refusal (an extra key, a
   wrong schema string, a forged `state` disagreeing with the fold, a duplicate key, a gap in `seq`)
   with byte-identical prior state, lock contention on both the per-transaction and the creation
   lock (held by the test through a separate open of the documented lock file) with byte-identical
   prior state, every terminal refusing every target, every illegal edge, and terminal targets
   refused for `external_state` `"unknown"` and omitted.
2. **Fixture executor against the store.** The asserted sweep table's `success` row for all four
   shapes, compared against the reloaded persisted history.
3. **Neutrality checker over module source.** Clean against the shipped module, failing on a
   planted provider verb in code, clean when the verb appears only in a comment.

No test asserts that an internal helper was called.

## Out of scope

Leases, fencing epochs and terms, renewal; write intent, inspect-before-retry and retry budgets;
adapter describe/inspect/invoke inside the core and profile resolution; proof plans, evidence,
cutoffs and receipts; rollback and recovery mechanics; authorization and grants; the grounds
predicates behind `abandoned`, `failed` and `rolled_back`; schema migration machinery (v1 is the
first version); the attempts cutover, workflow-state and control adapters (#125); any CLI command
or command-table row; the thirteen non-success scenarios and their rows; state cleanup (#72's
receipt-backed predicates); cross-repository parent transactions (deferred rejection).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | One library module `agent_tools.transaction_core` named for transactions, not releases, with no command-table row; the Nix build's recursive import check covers it. | agent-helpers rules 1–2; `lib/agent-tools.nix` walks every module; #117 makes attempts the first consumer; YAGNI. | A command row or `release_*` naming: no caller exists, and "release" misnames the first consumer. |
| D2 | The store takes an absolute, pre-existing root and writes only beneath it; it never derives, creates or searches for a root and leaves the #72 sentinel to the caller. | #72 explicit ledger roots and owning-module sentinel; #204 "the core never derives one". | Creating missing roots or defaulting to `.agents/runtime/...`: derives policy the caller owns and can scatter state. |
| D3 | Hand-rolled RFC 9562 UUIDv7 from wall-clock ms plus `secrets` randomness, no intra-millisecond counter, validated (pattern, version, variant) before any path join. | #82 `rel_` + UUIDv7; stdlib has no UUIDv7; the-bar defense in depth. | A monotonic counter (ordering is the event sequence's job) or trusting the id string (path traversal). |
| D4 | Dedup through a root-level creation lock and `creation-keys/<sha256>.json` index written before the state; a repeat create with the same subject (equal `telemetry_digest`) returns the existing id writing nothing, a different subject is `CreationConflict`, and an index without state completes under the indexed id. | #82 creation_key dedup and immutable subject; #117 "state module's index"; crash-safety. | Scanning every transaction directory (O(n), racy) or state-before-index (a crash leaves an orphan and a second id). |
| D5 | History lives inside `state.json` (schema `transaction-state/v1`), with `state`/`parked_from`/`revision` a validated projection of the event fold; v1 carries only `created` and `transitioned` events and later slices extend by new schema versions. | #82 "state contains … typed append-only events … validates the event fold, rebuilds the projection"; the-bar single home. | A separate `events.jsonl` append file (two files cannot be replaced atomically together) or #82's full field set now (unused fields, no invariants to check them). |
| D6 | The sweep reaches the core through a test-only fixture executor over the store's public API, porting the prototype's world and all four shapes whole but only the `success` scenario; the prototype's lease/retry/recovery logic is not ported. | #204 "fixtures, not production code" and "this slice asserts the success row"; the-bar YAGNI and no unasserted placeholders. | Porting the whole `Run` engine (drags out-of-scope slices in) or all fourteen scenarios now (inert, unasserted data). |
| D7 | `TRANSITIONS` is an explicit closed edge table: forward chain plus `published → proving`, every forward state and `recovering` may park, a park resumes only to its recorded `parked_from` or `recovering`, `abandoned` only from pre-publication states or a parking, `failed` only from a parking, `rolled_back` only from `recovering`, `succeeded` only from `proving`. | #82 lifecycle and terminal grounds; prototype's activation-`none` path; the-bar fail loud. | A permissive any-to-any table checked only for terminals (lets a park skip phases and lets `failed` or `succeeded` be reached from anywhere). |
| D8 | A terminal target requires `external_state == "known"`; `"unknown"` or omitted is `TransitionRefused` with no write and no automatic reroute to `attention_required`; the validator also rejects any stored terminal event not marked `"known"`. | #82 "unknown external reality is never terminal"; the-bar truthful terminal states and defense in depth. | Silently parking on unknown (a hidden transition the caller did not request) or trusting the caller's target alone. |
| D9 | One error hierarchy under `TransactionError` with five typed refusals, every one raised before any write. | #204 criteria "refused before any write"; the-bar fail loud. | A single error with message parsing: callers and tests would match text. |
| D10 | Advisory `fcntl.flock` taken non-blocking; contention raises `TransactionBusy` at once and the caller owns any retry; reads are lock-free. | #204 "a concurrent writer holding the lock is refused before any write"; the-bar no sleep to paper over races; workflow-state atomic-replace precedent. | A blocking lock (a stuck holder hangs every caller) or a timed retry loop (policy and sleeps inside the core). |
| D11 | The neutrality check is a test-side checker that strips comments via `tokenize` and docstrings via `ast`, matches whole lowercase words against three closed lists, and proves itself with a planted-code and a planted-comment case. | #123/#204 neutrality criterion; prototype README invariant; the-bar tests that can fail. | The prototype's substring match (flags `oci` in `associated`) or stripping every triple-quoted string (hides real string literals). |
| D12 | Add the two test files to `agent-workflow-tests` and one CLAUDE.md sentence naming the module as a caller-less first slice; no Nix change. | justfile lists files explicitly; the-bar "a deliberate stub is named in the architecture doc". | Leaving CLAUDE.md silent (an unused core module reads as dead code) or a new recipe (the demo belongs in the existing suite). |
| D13 | Only `create` makes paths; `advance` opens the lock without creating it and `load` is a pure read, so an unknown id is `UnknownTransaction` and state without its lock file is `StateInvalid`, with nothing left behind. | #72 state-based cleanup (no stray residue); #132's read-only query precedent; the-bar defense in depth. | Lazily creating the lock or directory on advance (manufactures residue for ids that never existed). |
| D14 | Tests split into `tests/test_transaction_core.py` (seam 1) and `tests/test_transaction_core_sweep.py` (seams 2 and 3, the neutrality checker living in that file), with the fixtures as relatively imported non-`test_` siblings `tests/transaction_core_world.py`, `tests/transaction_core_shapes.py` and `tests/transaction_core_sweep_support.py`. | D12's two recipe entries; `tests/` relative-import support-module precedent (`agent_model_drift_test_support.py`); D6 fixtures stay out of `python/`. | Fixtures under `python/` (ships provider names into the built package) or a third test file for neutrality (a recipe entry for one small class). |
| D15 | `TRANSITIONS` is a read-only mapping from every state to a frozenset; `attention_required` maps to every parkable state plus `abandoned` and `failed`, and one separate resume rule narrows a forward-state target from a parking to the recorded `parked_from`; the validator's fold and `advance` share that one edge predicate. | D7 closed table; the-bar single home and fail loud. | A placeholder token such as `<parked_from>` inside the table (a non-state value every reader would special-case). |
| D16 | Refusal edges: a malformed id or a missing transaction directory is `UnknownTransaction`; a present directory whose lock file or `state.json` is missing or not a regular file, or whose index entry does not point back, is `StateInvalid` for `load` and `advance` alike; `create` arguments that cannot form a valid v1 state (empty key, non-object or non-round-tripping subject) are `StateInvalid` raised before the creation lock, so nothing is created. | D9 typed refusals; D13 no residue; workflow-state `require_regular_path` precedent. | A bare `ValueError` for bad arguments (an untyped sixth refusal) or a `load` that tolerates a missing lock file (two readers of one layout disagreeing). |
| D17 | The fixture executor addresses the world by action id `node["id"]`, runs each phase in stable declaration-order dependency order, derives the floor (`publication_visible` per publication node, `running_subject_identity` per activation node) before the profile's required obligations in declared order, never collects advisory (`required: false`) obligations, and parks when a dependency was not satisfied. | Prototype `Run._derive_floor_obligations` and `collect_next_obligation` at `dc98ba9`; a scratch run of this walk lands all four shapes on `succeeded`. | Collecting advisory obligations (their predicates are unsupported by design, so the success row would park) or a hash-ordered walk (nondeterministic histories). |
| D18 | Every path the store joins under `root` (transaction directory, `creation-keys`, both lock files, `state.json`, index entries) is checked with `lstat` and opened with `O_NOFOLLOW`; a symlinked or wrong-type path is refused (`UnknownTransaction` for the transaction directory on load/advance, `StateInvalid` otherwise) and never followed, and `root` is fsynced after a new child directory | Phase-5 plan review SF-2/D-3; the spec's "never touches anything outside `root`" and D16's `require_regular_path` precedent in `workflow-state.py` | Following symlinks with `is_dir()`/`is_file()` checks, which lets a planted link redirect writes outside `root` |
| D19 | The neutrality checker also splits each token on case boundaries (lower→Upper and acronym→Word, so `GitPush` is `git`, `push` and `HTTPServer` is `http`, `server`) before lowercasing | Final correctness review C-1: lowercasing before splitting let a CamelCase identifier such as `PushRefused` evade the only neutrality guard | Splitting only on `_` and punctuation, which fuses every CamelCase identifier into one unmatched word |
