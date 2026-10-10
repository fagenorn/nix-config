# Attempt run identity on the transaction core, issue 337

Design for [#337](https://github.com/fagenorn/nix-config/issues/337), package 1 of 3 of
[#125](https://github.com/fagenorn/nix-config/issues/125), executing the
[#117 decision](2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md) over the
[#204 core](2026-09-27-issue-204-transaction-core-skeleton-design.md). Base: main `eca16cd8`.
Decisions were taken autonomously under `from-issue --auto`; each non-obvious one is a ledger row.

## Problem

An attempt run is named by whoever starts it, in one of four ad-hoc dialects: `direct-<issue>-<seq6>`
from `direct-owner`, and `orchestrate-…`, `issues-…` and `run-<date>-…` from the orchestrator and
earlier skill text. Nothing but the name ties a `-r2` retry to the run it retried, the names
contradict the ledgers they label (`run-20261009-337-338-339` holds issue 337 only), and the
transaction core that #125 moves the lifecycle onto has its own identity scheme that no run uses.
Package 2 (#338) needs every run to already carry one core identity, and every retained ledger to be
reachable from it, before it can hang fenced custody and receipts on that identity. A migration that
guesses identity from names, silently rewrites what it cannot read, or strands a live owner halfway
through an attempt would lose exactly the evidence the core exists to keep.

## Solution

Every run gets exactly one identity: a core transaction id, `rel_` + UUIDv7, minted by
`TransactionStore.create` under a creation key, in a store dedicated to attempt runs under the
ledger root. The transaction is an identity record: its immutable subject holds what the run is
(direct or orchestrated, the direct issue and sequence, the recorded predecessor) and, for a legacy
run, its typed alias (dialect, the legacy id, the grouping and retry its name states). It holds no
lifecycle; the workflow-state ledger stays the one writable lifecycle store until #338.

New runs are minted only this way: `init-run --creation-key` and `direct-owner` mint and name the
new ledger by the transaction id; no command mints a legacy-dialect id again. Ledger schema 8 binds
each ledger to its transaction id. Schema 7 and older ledgers migrate by one adjacent, pure-then-
effectful step under the ledger's own lock, on the next write (migrate-on-write) or through
`workflow-state migrate --apply`, after a read-only `workflow-state migrate` dry run has inventoried
every ledger with the identical transform. Unknown dialect, unknown schema, invalid state and
ambiguous lineage are refused with the ledger's bytes untouched. A migrated legacy ledger keeps its
legacy id as its handle, so every live owner, worker id, launch reference and #150 claim holder
keeps working unchanged; a helper from before this package refuses schema 8 without writing.

## Decisions

### Identity model

- **One run, one transaction.** A run (one ledger) maps to exactly one core transaction, the *run
  transaction*, created in state `created` and never advanced by this package (per D1). Its
  `concurrency_keys` are `["attempt-run:" + <creation key>]`, `authority_class` is `"attempt-run"`,
  and its proof and recovery declarations are the empty ones the core accepts
  (`{"units": [], "obligations": [], "collectors": {}}` and `{"effects": {}, "units": []}`), so no
  custody, proof or receipt machinery is engaged (per D6).
- **Run subject `attempt-run/v1`**, a closed JSON object:

  | Field | Value |
  |---|---|
  | `schema` | `"attempt-run/v1"` |
  | `kind` | `"direct"` or `"orchestrated"` |
  | `issue` | the direct run's issue (int), else `null` |
  | `sequence` | the direct run's per-issue sequence (int ≥ 1), else `null` |
  | `prior_run` | the predecessor's handle as recorded in the ledger, else `null` |
  | `alias` | the typed legacy alias below, or `null` for a run minted by this package |

- **Typed legacy alias** (`alias`): `{dialect, run_id, issues, date, retry}` where `dialect` is one
  of `direct`, `orchestrate`, `issues`, `run`; `run_id` is the legacy id exactly; `issues` is the
  list of issue numbers the id names, in the id's order (for `direct`, the one issue); `date` is the
  id's `YYYYMMDD` or `null`; `retry` is the `-r<n>` ordinal or `null`. The alias records what the
  legacy name *says*; it is never membership or lineage (per D3).
- **Handle.** A ledger's handle is its recorded `run_id`: the transaction id for a minted run, the
  legacy id for a migrated one. The handle names the ledger's directory, as today; the directory
  is a location checked against content, never a source of identity (per D4).
- **Creation keys** (the alias index is the core's creation-key index, per D2):
  - direct runs, legacy or new: `attempt-run/v1:direct:<issue>:<sequence>`;
  - legacy non-direct runs: `attempt-run/v1:legacy:<legacy run_id>`;
  - new orchestrated runs: `attempt-run/v1:run:<caller key>`, where the caller key matches
    `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`.
  Alias resolution of a legacy id is: classify, derive the key, read the index. A core read-only
  `TransactionStore.lookup(creation_key) -> str | None` is added for it: it reads the index exactly
  as `create` does and writes, creates and locks nothing (per D2).
- **Launch-reference aliases.** The two legacy launch forms, implementation `issue:attempt:launch`
  and remainder `issue:r<n>:launch`, stay run-scoped strings inside the ledger, parsed by the
  existing action-id parser. Together with the run's handle they resolve to (run transaction,
  issue, lineage implementation or remainder, ordinal, launch). No new launch store is written:
  #338 aliases them to core launch identities when those exist (per D5).

### Dialect grammar

Issue numbers are `[1-9][0-9]{0,6}` (an 8-digit token is never an issue); a date is 8 digits that
form a valid calendar date; `<r>` is `-r[1-9][0-9]*`. Matching is full-string and exactly one rule
may match:

| Dialect | Grammar | Example |
|---|---|---|
| `direct` | `direct-<issue>-<6 digits, value ≥ 1>` | `direct-100-000003` |
| `orchestrate` | `orchestrate(-<issue>)+[<r>]` | `orchestrate-21-24-r2` |
| `issues` | `issues(-<issue>)+[-<date>][<r>]` | `issues-29-30-20260817-r2` |
| `run` | `run-<date>(-<issue>)+[<r>]` | `run-20261009-337-338-339` |
| `core` | `rel_` + a UUIDv7 the core's `is_id` accepts | minted runs only |

Anything else (for example the harness's `issue-14-test`) is `unknown_dialect`. A ledger at
schema ≤ 7 whose id is `core` is also `unknown_dialect`: no core id predates schema 8.

### Ledger schema 8

`SCHEMA_VERSION` becomes 8 and the state gains one field, `transaction_id` (a `rel_` UUIDv7).
Validation adds: `transaction_id` is a core id; a `core`-dialect `run_id` equals `transaction_id`;
`prior_run` is `null` for an orchestrated run and, for a direct run, a handle that is either `core`
or `direct` for the same issue with a lower sequence (the existing "cannot precede itself" rule
stays). Every locked read and every unlocked read of a schema-8 ledger also checks the binding
read-only: the store loads `transaction_id` and the subject's handle (`alias.run_id`, else the
transaction id) equals the ledger's `run_id`, else the read is refused. A missing store or an
unknown transaction is a refusal, never a re-mint (per D4).

### Migration transform (7 → 8)

The step is the last adjacent step after the existing pure 1 → 7 chain, which is unchanged except
that the delivery runtime's chain passes a schema-8 document through untouched instead of refusing
it. It runs in two halves, in this order:

1. **Plan (pure, in `agent_tools.attempt_identity`)**: from the schema-7 document alone, classify
   `run_id`, check lineage, and return the creation key and subject, or a refusal with a closed
   reason. It reads no file and no directory name.
2. **Bind (effectful, in workflow-state under the ledger's lock)**: take the attempt mint lock,
   `create` under the plan's key and subject (which deduplicates), release the mint lock, set
   `transaction_id` and `schema_version: 8`, then hand the state to the mutation and the existing
   commit (validate, then atomic replace).

Refusal reasons form a closed set, and every one is raised before any write:

| Reason | When |
|---|---|
| `unknown_schema` | `schema_version` is not an int in 1–8 |
| `invalid_state` | the existing 1 → 7 chain or schema-7 validation refuses (the six retained schema-1 ledgers land here) |
| `unknown_dialect` | `run_id` matches no legacy rule, or is `core` at schema ≤ 7 |
| `ambiguous_lineage` | an orchestrated-dialect run records a `prior_run`; a direct run's ledger issues are not exactly its id's issue; a direct `prior_run` is not a `direct` id for the same issue with a lower sequence |
| `location_mismatch` | (dry run only) the directory's name differs from the recorded `run_id` |

Lineage is only what the ledger recorded. A `-r<n>` suffix records `retry: n` in the alias and
links nothing; a direct `prior_run` that skips a sequence is kept as recorded. A predecessor is kept
as its handle in `prior_run`, so migrating one ledger never reads or locks another; it resolves
through the index once the predecessor is bound (per D3).

The step is idempotent: the plan is a function of the unchanging schema-7 bytes, so a crash after
`create` and before the ledger's replace leaves the ledger byte-identical, and the retry's `create`
returns the same transaction (#204 D4's "index without state completes" covers a crash inside
`create`). A schema-8 ledger never re-enters the step. The bind half runs inside every locked read, and a
locked reader commits every ledger it bound: `direct-owner`, which today reads its issue's legacy
ledgers under their locks but writes only the selected one, also commits each other ledger it
migrated, so no index entry outlives an unbound ledger past the call that made it (per D14). A
legacy ledger of the issue that the step refuses refuses the whole `direct-owner` call, as a
corrupt one does today.

### Dry run and apply: `workflow-state migrate`

`workflow-state migrate --repo-root <root> [--apply]`; the thin shell lives in workflow-state because
apply must write under the owning module's lock, and every rule lives in `attempt_identity` (per D7).

- **Dry run (default)** lists the non-dot entries of `<root>/.superpowers/workflows` that hold a
  `state.json`, reads each without a lock (as `check-launch` does), runs the plan half, and resolves
  read-only through `lookup` any transaction id already bound or indexed (all `null` while the
  store root does not exist yet). It creates, locks and
  writes nothing, not even the store root.
- **Apply** runs the dry run, then for each ledger whose verdict is `migrate` performs a no-op
  `transact` on its handle, so the bind half runs under the ledger's lock on freshly re-read bytes;
  the dry-run verdict is advisory and a refusal under the lock is reported as `refused`. Refused
  ledgers are never opened for writing, and no lock file is created for them.
- **Report** `attempt-migration-report/v1` on stdout, canonical JSON with sorted keys:
  `{schema, mode: "dry_run" | "apply", ledgers: [...], counts: {current, migrate, migrated,
  refused}}`; each ledger row is `{ledger, run_id, schema_version, dialect, alias, issues, prior_run,
  prior_transaction_id, transaction_id, verdict, reason}`, where `issues` is the ledger's recorded
  membership, sorted by `ledger`, with no clock value,
  so two dry runs over unchanged ledgers print identical bytes. `verdict` is one of `current`,
  `migrate`, `migrated` (apply only) and `refused`; `reason` is the closed reason or `null`.
- **Exit codes:** 0 when every ledger received a verdict (refusals are reported data: retained
  schema-1 ledgers are refused forever by design); 2 on usage, an unreadable workflows directory
  or a store error (per D8).

### Minting new runs

- **`init-run`** takes exactly one of `--run-id` and `--creation-key`. `--creation-key K` creates
  or deduplicates the run transaction for `attempt-run/v1:run:K`, then initializes the ledger at
  `workflows/<transaction id>` (or returns the existing one's bootstrap), so repeating the call with
  K returns the same run. `--run-id X` only re-bootstraps an existing ledger X (migrating it on
  write if needed); a missing X is refused before any directory is created. The reserved-direct
  refusal stays.
- **`direct-owner`** keeps its legacy prefix scan of `direct-<issue>-*` (removed by #339) and
  additionally reads the index for `attempt-run/v1:direct:<issue>:<s>` for `s` from one past the
  greatest scanned sequence upward until the first miss; the union, ordered by sequence, replaces
  today's scanned list. A new direct run takes the next sequence after the greatest one found,
  mints under that key with `prior_run` set as today, and its ledger is named by the transaction id.
  An index entry whose ledger is absent (a crash between mint and ledger write) is excluded from
  the retained list. The next mint computes that same sequence and predecessor, so `create`
  returns the reserved id instead of a second one. TODO(execute): confirm against the
  selection rules near the scan, which rely on sequence order only.
- The orchestrate-issues skill's §2 "mint a new one" becomes a call to `init-run --creation-key
  orchestrate-issues:<YYYYMMDD>:<issues in caller order joined by ->`, taking `run_id` from the
  bootstrap; from-issue's durable acquisition takes `run_id` from `init-run --creation-key` the same
  way. The run-reuse listing rule is unchanged (#339).

### Store root, locks and ordering

- **Store root:** `<ledger root>/.superpowers/attempt-transactions/`, a sibling of `workflows/`,
  created by workflow-state on its write paths only (#204 D2 leaves root creation to the caller),
  and given the same `*` `.gitignore` as `workflows/`. No existing ledger moves (#72).
- **Attempt mint lock:** `<store root>/attempt-runs.lock`, taken with a **blocking** exclusive
  `flock` around every `create`. The core's creation and per-transaction locks are non-blocking
  (`TransactionBusy`); since every creator in this store holds the mint lock, they are never
  contended, and concurrent migrations or mints queue instead of failing (per D9).
- **Order**, outermost first: `.direct-<issue>.lock` → ledger `state.lock`s (direct-owner in
  sequence order, as today) → attempt mint lock → core `creation.lock` → core `<id>/lock`. Nothing
  takes a `state.lock` while holding the mint lock: `init-run --creation-key` mints, releases the
  mint lock, then takes the new ledger's `state.lock`.

### Compatibility and older helpers

- Live legacy owners keep working because a migrated ledger keeps its legacy handle and every
  lifecycle field: `progress`, `suspend`, `finish`, `checkpoint-delivery`, `register-worker`,
  `release-worker`, `mark-progress`, `check-launch`, `current-launch` and `owner-liveness` accept the
  legacy `--run-id`, action ids and worker ids exactly as before, whether the migrating write was
  theirs or control's. D16's launch fence on attempt-keyed transports is #338's.
- `check-launch` and the #193 installed-contract lookup stay read-only: a schema ≤ 7 ledger is
  validated on a detached copy through the plan half too (so an unmigratable ledger answers as a
  refusal), and a schema-8 ledger's binding is checked by a lock-free `load`. Neither creates the
  store root, a lock or a directory. #132/#133 projections are otherwise untouched.
- An older helper refuses schema 8 through its existing schema checks, before any write: its locked
  reads' migration chain rejects any version outside 1–6 before reaching 7, and its unlocked reads
  reject the unknown `transaction_id` field (per D26). There is no reverse
  transform: rolling this package back leaves migrated ledgers refused and preserved, and recovery
  is redeploying a schema-8 reader (#117 Migration; per D10).

### Packaging

The plan half, the grammar and the report shaping are one new module, `agent_tools.attempt_identity`
(Phase-0's split into identity and migration modules is unnecessary at this size; per D7).
workflow-state imports it and `agent_tools.transaction_core` with a plain import. In source mode the
recipes' `PYTHONPATH` supplies the package. Installed, `~/.agents/bin/workflow-state` becomes a
launcher that clears the `NIX_PYTHON*` variables and runs the store copy of the script under the
agent_tools environment's interpreter, which `lib/agent-tools.nix` now exports beside its
launchers. TODO(execute): settle whether that launcher can pass `-I` given the script's
path-loading of its installed delivery runtime; the installed-layout tests decide (per D11). The python/README.md transaction-core paragraph ("no caller until #125") and the agent-skills README's lifecycle-helper section gain the run identity and `migrate` contract.

## Test seams

Two seams carry acceptance, both already in the suite. No other seam may be invented.

1. **The workflow-state CLI**, driven from source like `LifecycleHarness`, with a new
   `home/common/agent-skills/tests/test_attempt_migration.py` for the migration fixtures. Its
   outputs, its ledger bytes and the store tree are the observable behaviour.
2. **`agent_tools.attempt_identity`'s pure functions** (classify, plan, report rows), imported
   normally by a new `tests/test_attempt_identity.py`, following the transaction-core unit tests.
   Both new files join `just agent-workflow-tests`.

Fixtures are ledgers written as the retained ones are shaped: one per dialect (`direct-41-000001`,
`direct-41-000002` recording it as `prior_run`, `orchestrate-21-24-r2`, `issues-29-30-20260817-r2`,
`run-20261009-337-338-339` holding only issue 337), at schema 7 through the existing `_as_legacy`
down-converter, which now also drops `transaction_id` and moves the ledger to the fixture's
legacy handle (a down-converted `rel_` id would be `unknown_dialect`); the existing 1 → 7 migration
tests use the same legacy-dialect fixtures. Plus a schema-1 fixture. Each carries an attempt with an implementation launch and
one with a remainder launch and the matching #150 claim. A "tree snapshot" is every path under
`.superpowers` with its bytes.

| Criterion | Deterministic check (seam) |
|---|---|
| AC1 one scheme; legacy rows readable with lineage | `init-run --creation-key K` twice → the same `run_id`, a `rel_` UUIDv7 equal to the ledger's `transaction_id`; `init-run --run-id new-x` refused and the tree snapshot unchanged; a new `direct-owner` run is `core` with `prior_run` set to the legacy predecessor's handle; after apply every fixture row is `current`, `lookup` of each legacy id returns its `transaction_id`, `direct-41-000002`'s `prior_transaction_id` is `direct-41-000001`'s, and `check-launch` and `current-launch` on both launch forms print the same bytes as before migration (1, 2) |
| AC2 no identity from directories | `run-20261009-337-338-339`: the report row carries alias `issues` `[337, 338, 339]` beside recorded `issues` `[337]`, and the bound subject holds no membership; `orchestrate-21-24-r2` gets `retry: 2`, `prior_run: null` and no predecessor; a fixture whose directory is renamed away from its recorded `run_id` is `location_mismatch` in the dry run and refused by the locked read, both unchanged (1, 2) |
| AC3 dry run, adjacent, atomic, idempotent; refusals byte-identical | two dry runs print identical bytes and leave the tree snapshot unchanged; apply, then apply again → the second reports zero `migrated` and an identical snapshot; refusal fixtures (`issue-14-test`, `schema_version: 9`, a direct `prior_run` naming another issue, an orchestrated run recording a `prior_run`, the schema-1 fixture) keep their bytes and get no index entry; a run transaction created in advance under the plan's key (a simulated crash before the ledger replace) is the one apply binds; a held mint lock makes apply wait without writing until it is released (1, 2) |
| AC4 live legacy owner; old helper refuses | on a schema-7 fixture with an active owner, (a) control's write migrates and the owner's `progress`, `register-worker`, `release-worker`, `suspend`, then `finish` succeed under the legacy ids, and (b) the owner's own `progress` is the migrating write; the base helper, extracted with `git archive` from the pinned base commit `eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7` into a scratch tree, exits non-zero on `check-launch` and `progress` against the migrated ledger with the snapshot unchanged; a missing commit fails the test (1) |
| AC5 regression floor; #132/#133 unchanged | the whole `just agent-workflow-tests` suite green at the package head with its only declared change being harness and fixture run ids, which become `init-run --creation-key` runs or legacy-dialect fixtures; `test_admission_replay` keeps its committed baseline; `just build` and `just agent-installed-skill-tests` pass (1) |

## Out of scope

- Custody leases, epochs, fencing (including D16's attempt-keyed transport fence), receipts,
  late-result intake, suspension in core vocabulary, and per-issue-subject lifecycle transactions
  (#338).
- Control reading core state, replacing the `direct-owner` prefix scan, the run-reuse listing and
  the #193 lookup with the index, event-driven wakeups, and porting #150 claims and #151 delivery
  objects onto the core (#339).
- Any layout move of existing ledgers or runtime roots (#72), any reverse migration, and archiving
  or repairing the six retained schema-1 ledgers.
- Moving workflow-state itself into the package (#178).

## Triage

Input: {"signals":{"contract_change":{"value":"hit","evidence":"Workflow-state ledger schema advances and run identity changes to rel_+UUIDv7 with typed legacy aliases"},"concurrency_or_persistence":{"value":"hit","evidence":"Atomic, idempotent state migration under the owning module's lock over persisted ledgers"},"open_design_questions":{"value":"hit","evidence":"#117 leaves exact field names, alias indexing and grouped-run mapping to #123/#125"},"criteria_shape":{"value":"hit","evidence":"Five acceptance criteria"}},"paths":["home/common/agent-skills/scripts/workflow-state.py","python/agent_tools/transaction_core.py","python/agent_tools/transaction_storage.py","python/agent_tools/attempt_identity.py","python/agent_tools/attempt_migration.py","home/common/agent-skills/tests/test_workflow_state.py","home/common/agent-skills/tests/test_attempt_migration.py","justfile"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The minted unit is the run: one created-only *run transaction* per ledger holds identity (subject `attempt-run/v1`), and lifecycle stays in the ledger until #338 moves custody onto per-issue-subject transactions that reference it. | #337 "new attempts are minted under exactly one run identity" and its demo's "one new run minted"; #338 AC1 owns "lifecycle state lives in the core's store"; #117 D2 rejects a group transaction as a shared mutable lifecycle owner, which a created-only identity record is not. | Per-issue transactions now (custody-less records no caller reads until #338, YAGNI) or a non-core group id (a second identity scheme). |
| D2 | The alias index is the core's creation-key index: legacy direct and new direct runs share `direct:<issue>:<sequence>`, legacy non-direct runs use `legacy:<run_id>`, new orchestrated runs use the caller's key; the core gains a read-only `lookup`. | #117 "canonical lookup uses the state module's index"; #204 D4 index and dedup; the-bar DRY (one index). | A separate alias file or index (a second identity authority, with its own crash rules) or scanning directories (#117 forbids). |
| D3 | Lineage is only what a ledger recorded (`prior_run`, kept as a handle). Name-stated grouping, dates and `-r<n>` retries are descriptive alias fields. Ambiguity is decided from one ledger's bytes, so the dry run and the forward step run one transform and never lock two ledgers. | #337 "identity is never inferred from repository or workflow directory names"; retained ledgers: every non-direct `prior_run` is null and names contradict content; #117 D14 "identical transform". | Inferring a `-r2` run's predecessor from its name (guessing) or refusing every `-r<n>` run as ambiguous (strands live retried runs whose lineage was simply never recorded). |
| D4 | A migrated ledger keeps its legacy id as its handle and directory; schema 8 adds only `transaction_id`, checked against the core subject on every read; minted runs use the transaction id as the handle. | #337 "live legacy owners keep working"; launch-scope registries, worker ids and #150 claim holders embed the handle; #72 no layout move. | Rewriting `run_id` to the `rel_` id (breaks every live `--run-id`, worker id and registry path mid-attempt) or copying alias fields into the ledger (two homes for identity). |
| D5 | Launch-reference aliases resolve through the existing action-id parser against the migrated ledger; no launch identity is stored in this package. | #117: both forms "alias core launch identities", which only #338's custody creates; #150 claims are keyed by the unchanged strings. | Minting core launch ids now (custody without its fence) or a launch alias table (YAGNI before #338). |
| D6 | The run transaction uses the core's empty proof and recovery plans, one inert concurrency key and authority class `attempt-run`; no custody or receipt API is called. | Phase-0 Q6 "minimal subject; no custody"; #204 accepts empty plans; #338 owns custody and receipts. | Declaring attempt obligations or recovery effects now (pre-empts #338's design and #88 plan compilation). |
| D7 | One package module, `agent_tools.attempt_identity`, holds grammar, plan and report; the thin `migrate` shell and the bind half live in workflow-state, the owner of `state.lock` and the commit path. | agent-helpers rules 1–2; #117 D14 "under the owning module's lock"; the-bar single responsibility. | A separate `attempt-migration` command (it would re-implement the ledger lock and commit) or two modules (one reason to change at this size). |
| D8 | `migrate` exits 0 whenever every ledger got a verdict, reporting refusals as data; apply never opens a refused ledger for writing. | Retained schema-1 ledgers fail today and must be preserved as evidence (Phase-0 Q2); the-bar truthful terminal states (the report counts refusals). | Exit non-zero on any refusal (permanently red over archived evidence) or repairing schema-1 ledgers (guessing). |
| D9 | A blocking attempt mint lock wraps every `create` in the dedicated store, innermost of all blocking locks, and no `state.lock` is taken while it is held. | Core creation and transaction locks are non-blocking (`TransactionBusy`); concurrent migrate-on-write across runs is normal; the-bar root causes (no retry loop). | Retrying on `TransactionBusy` (sleep-shaped race handling) or making the core's locks blocking (changes #204's contract for every consumer). |
| D10 | Older helpers are excluded by the schema bump alone; there is no reverse transform, and rollback means redeploying a schema-8 reader. Deploying this package is one-way for every ledger it migrates. | #117 Migration: "never an old writer against unknown/newer state or an ad-hoc reverse transform"; the base chain refuses versions outside 1–6. | A down-converter (a second writer generation) or a version handshake (agent-helpers rule 3). |
| D11 | Installed workflow-state runs under the agent_tools environment's interpreter, exported by `lib/agent-tools.nix`, and imports the core with a plain import. | agent-helpers rule 3 bans path loading; the core is a multi-module package that a single-file copy cannot carry; #178 will move workflow-state into the package. | Calling a package command by subprocess under the ledger lock (a JSON wire for every read) or copying the core's twelve modules into `~/.agents/lib/python`. |
| D12 | `init-run --run-id` only re-bootstraps existing ledgers, and tests' free-form run ids become `--creation-key` runs or legacy-dialect fixtures; that is the regression floor's one declared change. | #337 "no `run_` or other legacy dialect is minted again"; #117 seam 2 allows declared schema changes. | Keeping free-form ids for tests (a fifth, test-only dialect the product would also accept). |
| D13 | The old-helper test runs the real base generation, extracted with `git archive` from the pinned base commit, and fails if the commit is missing. | the-bar tests that can fail; #337 AC4 names "an older helper". | Asserting only the current helper's refusal of schema 9 (proves a different generation's rule). |
| D14 | The bind half runs in every locked read, and a locked reader commits every ledger it bound, including the ledgers `direct-owner` only reads. | #117 D14 migrate-on-write under the owning lock; #204 D4 index-before-state; the-bar truthful states (no index entry naming a ledger that still claims schema 7 beyond one call). | Binding only on a ledger's own mutation (`direct-owner`'s read-only ledgers would leave index entries whose ledgers stay at schema 7). |
| D15 | A run's direct reservation comes from its identity, not its name: a schema-8 ledger is direct when its bound subject's `kind` is `direct`, a schema-7 ledger when its id classifies as the `direct` dialect. That one answer drives `select_phase_action`, the attempt validator, `progress`, and the refusal of `control` and `init-run --run-id` against a direct run, which for a `rel_` handle is checked under the ledger's lock. This settles the spec's direct-owner reserved-slot TODO. | D4 (minted direct runs are named by the transaction id); #337 "identity is never inferred from repository or workflow directory names"; `is_reserved_direct_run_id` today gates exactly these four sites. | Keeping the name check (a minted direct run would get non-direct phase selection, and control could take it over) or adding a `run_kind` ledger field (a second home for identity, which D4 rejects). |
| D16 | Installed `workflow-state` runs as `python3 -I <store script>` under the agent_tools environment, after the launcher clears `NIX_PYTHON*`, which settles the spec's D11 TODO. Its delivery runtime and host-admission library still load by absolute path, and resolve-project still runs as a launcher, and none of them reads `sys.path` or `PYTHON*`. | `lib/agent-tools.nix` gives every launcher `-I`; `tests/test_agent_tools_launchers.py`'s hostile-channel cases; agent-helpers rule 3. | Running without `-I`, so a hostile `PYTHONPATH` could shadow `agent_tools.transaction_core` under the ledger lock. |
| D17 | `direct-owner` mints a new direct run's transaction (deduplicated under `direct:<issue>:<sequence>`) when it first computes the new run's handle, before the one-issue policy runs. An observe or contract reply therefore names the run the next call will allocate, as it does today, and an index entry that has no ledger yet is reused, not duplicated. The policy's last-resort issue derivation from the run directory's name is replaced by the request's issue. | The spec's "the next mint computes that same sequence and predecessor, so `create` returns the reserved id"; `command_direct_owner` returns `observed_run_id` for an unallocated new run; `_apply_one_issue_policy` parses `run_dir.name`. | Minting only at allocation (observe replies for an unallocated run would lose their `run_id`, a wire change) or keeping the directory-name fallback (it cannot parse a `rel_` directory, and it reads identity from a directory name). |
| D18 | `launch-scope`'s path-segment grammar admits `_` (`[A-Za-z0-9_.:-]+`), so a minted `rel_` handle works as a `--run-id` for `exec`, `scratch`, `reap` and `launch-commit`. | Every worker runs its commands through `launch-scope exec --run-id <handle>` (CLAUDE.md); the core's id format `rel_` + UUIDv7 is fixed by #204 D3; `_` is as path-safe as `.` and `-`. | Leaving the grammar (every minted run is refused by its own launch fence) or a launch-scope-only alias of the handle (a second name for one run, which D4 rejects). |
| D19 | The regression floor's declared change (D12) also covers what the schema bump forces on tests: the expected current schema number (7 → 8), the `transaction_id` field in hand-built current-schema states, the `identity` argument of direct `validate_state` calls, and reading a minted direct run's handle from the index instead of a `direct-<issue>-<seq6>` literal. No assertion about lifecycle behaviour changes. | D12; #337 AC5 "regression floor"; the-bar tests that can fail (a changed expectation must be named, not hidden). | Keeping schema-7 expectations behind a compatibility shim (a second current schema) or rewriting assertions freely during the sweep (an unreviewable floor). |
| D20 | Run identity is threaded as one value, `attempt_identity.RunIdentity(kind, issue, sequence)`: the locked and unlocked readers derive it (from the bound subject at schema 8, from the legacy alias at schema ≤ 7), `validate_state`, `validate_attempt` and `commit_state` take it, and `select_phase_action` takes `direct: bool`. The dry run and apply migrate schemas 1–6 with empty migration contracts, as `read_state_unlocked` already does. | D15; agent-helpers rule 1 (pure rules in the package); `validate_state` is pure today and must stay so (the store is read by the readers only). | Re-reading the store inside `validate_state` (an effect in a pure validator, and a load per commit) or passing `run_id` and re-classifying the name (D15 forbids name-derived identity for `rel_` runs). |
| D21 | Migration fixtures: the orchestrated-dialect fixtures (`orchestrate-21-24-r2`, `issues-29-30-20260817-r2`) are down-converted copies of `DeliveredControlHarness.deliver_through_remainder`'s issue-207 ledger, so they carry both launch forms (`207:1:4`, `207:r1:1`) and the #150 claim; `run-20261009-337-338-339` holds one spawned issue 337; the direct fixtures are issue 41's direct-owner runs (one terminal, then `new_run`) down-converted to `direct-41-000001` and `direct-41-000002`. | Spec Test seams (one fixture per dialect, both launch forms); a direct run's ledger must hold exactly its id's issue, so the 207 ledger cannot be a direct fixture. | Renumbering the 207 ledger into issue 41 (rewrites action ids and claim holders, so the fixture is no longer a real ledger shape). |
| D22 | Task 8's skill edits fit the current instruction ceilings: no ceiling in `instruction-load.json` is raised, and `just agent-instruction-budget` runs without `--raise-label`; if an edit would exceed a ceiling, the edited paragraph is condensed instead. | User instruction: only the user applies the `instruction-budget-raise` label; #292 D9. | Raising a ceiling in the same branch (the gate then needs a label no agent may apply). |
| D23 | `direct-owner` checks every retained ledger of the issue (scanned and index-probed) with the read-only checker under its held `state.lock` before it binds any, then binds and commits them in sequence order; a refusal therefore leaves every ledger, the index and the mint untouched. | Plan review (Codex B1): binding and committing each scanned ledger at once breaks the § Migration transform promise that a refused ledger refuses the whole call when a valid sequence precedes it; `command_direct_owner` already holds every retained lock to the end of the call (`workflow-state.py` scan loop). | Relaxing the promise so earlier valid ledgers stay bound (a refused call would still write and mint, contrary to "every refusal is raised before any write"). |
| D24 | The migration fixtures (`MigrationFixtures`) build on `LifecycleHarness`; the issue-207 source ledger comes from the #220 driver run as a nested `DeliveredControlHarness` test case in its own root and HOME, and only its parsed state is installed. Task 2 switches the driver's `setup_run` to `init-run --creation-key delivered`. | Plan review (Codex B2): `DeliveredControlHarness` rests on `BuilderHarness`, which has no `init_run`, `run_cli` or `read_state`, `setup_run` creates its own root, and the two harnesses' `control` signatures differ; D12 makes `init-run --run-id` refuse a new run, so the driver must mint. | Multiple inheritance from both harnesses (conflicting `control` and root ownership) or a hand-built 207 ledger (no longer the real shape D21 requires). |
| D25 | Harness `finish` keeps a schema-8 ledger at schema 8, clearing only each issue's delivery contract and remainders before the legacy result-file call; a schema ≤ 7 ledger keeps the schema-2 copy. AC4's owner `finish` therefore runs on the migrated ledger and must keep its handle and `transaction_id`. | Plan review (Codex B3): the schema-2 copy drops `transaction_id` and leaves a minted `rel_` handle at schema 2, which the dialect grammar refuses as `unknown_dialect`, and it bypasses the migrated schema-8 ledger AC4 targets; legacy `finish` refuses only a contracted issue (`workflow-state.py:3839`). | Keeping the schema-2 copy for every run (breaks every minted-run `finish` in the floor and proves nothing about schema 8) or a product change letting schema ≤ 7 carry a `rel_` id (contradicts the grammar). |
| D26 | The base-helper test first runs the extracted helper's `check-launch` on the schema-7 ledger (exit 0), then requires exit 2 with a `workflow-state: … workflow state schema …` refusal on schema 8 for `check-launch` and `progress`, with the tree unchanged. The spec's compatibility sentence now names both base checks. | Plan review (Codex S1): any non-zero exit would also accept an import or setup failure; the base `check-launch` refuses at its field-set check and `progress` at the chain's version check (`workflow-state.py` `validate_state`, `workflow_delivery.py` `migrate`). | Asserting only a non-zero exit (cannot tell a refusal from a broken extraction). |
