# Task 2: Atomically adopt schema 3 and delivery transports

**Files:**
- Modify: `home/common/agent-skills/scripts/delivery_model/_objects.py`
- Modify: `home/common/agent-skills/scripts/delivery_model/_reconcile.py`
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Create: `home/common/agent-skills/scripts/workflow_delivery.py`
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Modify: `home/common/agent-skills/tests/_delivery_model_fixtures.py`
- Modify: `home/common/agent-skills/tests/test_delivery_model.py`
- Modify: `home/common/agent-skills/tests/test_workflow_state.py`
- Modify: `home/common/agent-skills/tests/test_artifact_budget.py`
- Create: `home/common/agent-skills/tests/test_delivery_workflow.py`
- Create: `home/common/agent-skills/tests/test_workflow_delivery.py`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md`
- Modify: `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`
- Modify: `home/common/agent-skills/default.nix`
- Modify: `justfile`

**Interfaces:**
- Retain Task 1's eight-name v1 facade. Private `_objects`/`_reconcile`/`_wire`
  own D19 stage relationships/reduction/envelopes; workflow-state supplies facts,
  not policy copies.
- Private `workflow_delivery.py` exports only interface version 1 and
  `DeliveryRuntime`; it owns v2 admission, schema-3 delivery validation and the
  pure transition. Workflow-state retains CLI, custody, locks, writes/effects.
- Workflow-state writes schema 3. `upgrade_state(value, *, run_id,
  migration_contracts)` composes 1→2→3 in memory, validates the candidate with
  keyword `run_id`, and writes once at most. Current-launch validates legacy
  reads without lock, upgrade or write.
- Control v2 keeps v1 top-level keys, replaces `owners`, and adds issue-keyed
  `forge`, `delivery_contracts`, `authorization_intents`,
  `authority_observations`, `reevaluation_evidence`, `delivery_observations`,
  `requested_scopes`. Each map has exactly the requested canonical decimal keys;
  values are forge objects, strict contract|null, sorted unique fact arrays, or
  strict scope|null. Missing/extra/`01`, or null contract with facts/scope,
  refuses before lock. Direct keeps v1 keys plus singular contract,
  those four fact arrays and required nullable `requested_scope`. Owner facts are
  exact event_id/issue/custody/state=unavailable; duplicate event/custody,
  historical-as-current, hybrid, unknown or mismatch refuses.
- Control output retains v1 outer keys. Summary replaces attempt with
  custody|null and adds contract digest, ordered stages and sorted requirements;
  delta remains issue/custody/kind/state. Spawn/resume/retry/direct owner add
  custody, contract/digest, stages, requirements and nullable evaluation/scope;
  observe admits all eight requirements and terminal stays v1. Remainder adds
  evaluation/scope. A finish remainder uses null scope plus the ready-stage
  requirement, or a missing-postcondition observation requirement when no stage
  is ready; it invents no stage. Model validation covers every nested member.
- `ship-checkpoint/v2` requires nullable post-fold ready-stage scope. Ordinary
  `delivery_checkpointed` echoes it and is active|suspended; count-3
  `delivery_stalled` has no action/requirements/evaluation/block/scope. Finish is
  `finish --repo-root ROOT --run-id RUN --now UTC --summary-file FILE`: complete
  has no pending stage; genuine owner failure has the accepted reason/source;
  eligible retry returns remainder; partial progress/requirements never fail.
- Artifact-budget validates v2 checkpoint/response bytes before decode.
  Bootstrap selects active, else latest remainder, else implementation custody;
  callers normalize requirements. Legacy v1 summaries are read-only. Handoff
  keeps scope as history; effect calls bind the echo and current-launch fence.

**Invariants:**
- Per D8/D14/D17, migrations preserve attempts/outcomes/result bytes/details and
  initialize no delivery truth. Request-derived contract|null context must match
  candidate facts/remainder. Malformed, ambiguous or mismatched input writes
  nothing. Legacy current-launch returns four exact keys, changing no bytes.
- Per D3/D18, every effect and observation uses the exact current launch. Late
  direct/control facts retain original launch; old allow grants nothing and old
  rejection remains. A post-rejection action appears only with its first durably
  persisted consumption; replay/transfer/crash cannot reissue it. Successor
  intent and reevaluation evidence are independent bases.
- Per D19, caller-built scope binds only to the post-fold ready stage. Null
  returns its local or pending dependency/postcondition requirement; wrong scope
  refuses, uncovered scope human-gates, and covered scope may native-evaluate.
  Stage change, transfer and resume require fresh proposals.
- Selected-output ingestion verifies acceptance/review/test categories; ids imply
  none. Checkpoint deduplicates; blockers suspend. Merge folds before expiry.
  Same-token suspensions store 0/1/2/3; three resumes are allowed, 3 stalls, and
  real progress resets 0.
- Implementation/remainder identities stay disjoint. Resume keeps ordinal/deadline
  and spends no retry; only failure+absent effect+recovery allocates remainder 2,
  never 3. Implementation retry/capacity remains.
- One source-only atomic cutover has no activation or mixed generation.
  Structure grants no authority; locked checks remain.

- [ ] **Step 1: Tests and fixtures**

Keep every existing test named in the Task-2 source roster and add the following
public cases. `_delivery_model_fixtures.py` supplies sealed, independently
constructed stage scopes and ready-stage history; it never derives history from
a requested scope. `test_delivery_model.py` covers: pre-fold wrong stage; null
ready-stage requirement; uncovered human gate; covered ordinary native
evaluation; select then publish/open/merge proposals; selected literal and exact
slot forms; endpoint/audience/principal/risk/spend/target/slot/data/repository/
base mismatches; current/old launch authority; D18 consumption/replay; all
cleanup literal tracker/branch/worktree targets; postcondition-only null scope;
and exact wire/report nesting. Preserve the v1 model export set.

`test_workflow_state.py` covers detached 1→2→3 migration, exact legacy bytes,
one final schema-3 write, malformed legacy/no-write current-launch, v2
control/direct request maps and custody. `test_delivery_workflow.py` uses only
synthetic ledgers/layouts and subprocess CLI round trips for bootstrap, owner
facts, direct/control, current, checkpoint, finish, remainders, denial/resume,
stale launch and lexical source/installed loaders. `test_artifact_budget.py`
accepts exact v2 handoff/checkpoint/summary/workflow-response canonical bytes
and rejects all hybrids. `test_workflow_skill_contracts.py` and orchestration
evals require one atomic caller contract.

- [ ] **Step 2: Admission and migration**

Install private `workflow_delivery.py` and the model lexically; require runtime
interface 1 and model interface 1, clean all partial modules on failure, never
alter `sys.path`, load a leaf, or fall back. `MIGRATORS={1:1→2,2:2→3}` operates
on a detached copy. Schema 1 adds only suspension defaults/prior_run; schema 2
adds only empty delivery/remainders. Validate historical shape before migration;
write at most one validated v3 state under lock. Lock-free current-launch only
validates and projects legacy state, returning its exact four keys and no write.

`DeliveryRuntime` owns v2 admission, schema-3 delivery validation and pure
transition; workflow-state owns CLI, custody, locks and atomic writes. Control
and direct validate all closed fields before lock, reload, validate current
custody, fold/reduce and return detached typed responses. Control maps have the
exact canonical issue key set; null contract cannot carry facts/scope. Direct is
the singular analogue. Trusted controller/owner creates actual scope from
command/provider/audience/data/principal/risk/spend, never from intent.

- [ ] **Step 3: D1–D20 delivery semantics**

Retain the eight-name v1 facade. `_objects` is the sole stage/effect/target/slot
relationship authority; `_reconcile` folds facts before selecting the ordered
ready stage; `_wire` validates exact transports. A requested scope must match
contract project/repository/issue, ready action/effect and slot/literal target.
Before selection only its validated slot may be proposed; after selection exact
slot equality or its validated literal narrowing may be used with exact data
classification/audience. Wrong, dependency, completed, stale or contractless
scope refuses with no effect/write. Null ready scope returns the exact local
scope_tuple requirement; dependency and no-stage postcondition requirements
remain typed observations. Uncovered scope human-gates; covered ordinary scope
requires fresh native evaluation. Historical allow is retained but grants
nothing; rejection requires durable one-shot D18 consumption before a new
evaluation. Transfer/resume/remainder always needs a fresh proposal.

Every owner/control/remainder action and ordinary checkpoint carries required
nullable `requested_scope`; nested action echo, custody, contract digest,
pending stages, requirements and evaluation agree exactly. Handoff retains its
prior scope only as history. Summaries, terminal and stalled outputs carry none.
Checkpoint folds facts before evaluating the next scope; finish-created
remainder has null scope and custody plus ready-stage or postcondition
requirement. Count three stalls; preserve 0/1/2/3 counters, retry/capacity and
remainder-2-only recovery rules.

- [ ] **Step 4: Reports and callers**

Artifact-budget validates raw UTF-8 bytes and named v2 boundaries before any
decode, rejects duplicate keys/hybrids, and emits canonical bytes. Bootstrap
selects active custody, then latest remainder, then implementation. Callers in
all seven skills/docs and orchestration: validate init/direct/control/current/
checkpoint/finish responses before decode; consume bootstrap requirements; copy
returned contract/custody/pending stages; derive actual scope; require exact echo;
fence current-launch before effect and again before observation; checkpoint every
partial/denial/provider result; use summary only for complete postconditions or
genuine custody failure. They never infer stage from tracker or intent, fabricate
authority/retry/terminal state, or activate source integration.

- [ ] **Step 5: Required verification and delivery gates**

Run the exact focused six-module unittest command, `just agent-workflow-tests`,
`just build`, and quick validation for from-issue, ship-issue and orchestrate-
issues in the documented PyYAML devenv. Retain argv/stdout/stderr/exit receipts.
Run `git diff --check`; temporary-index audit must contain exactly all 23 paths,
with each U10 diff 1..65536 bytes and empty real index. Then sign one atomic
commit:
`feat: reconcile delivery lifecycle` with the stated Codex coauthor. Gate raw
producer bytes before decode, then fresh checker and complete review-package
ranges for immutable Task base `980abb67c443d02c35babbface505e1d580a6008` and
Delivery base `4cd9408c4e538d6c9f0b9941e43d05d43a77c9a8`; never change a cap,
base, roster, activation state or live ledger to make a gate pass.

## Preservation and review constraints

Migration preserves attempts, results, result sources, timestamps, durable detail,
outcomes and lineage byte-for-byte except adjacent default fields; it creates no
authority or delivery truth. Invalid legacy/hybrid/version/attempt/result rows
and legacy current queries leave bytes and inventory unchanged. Normalize before
lock, validate/upgrade detached state, validate custody, reduce, atomically
persist one final v3 state, then render. Rejection writes nothing; retry cannot
duplicate consumption. Runtime owns this transition; workflow-state owns CLI,
locks and writes.

Effects use exact returned scope/custody with current-launch fences; history never authorizes.

No step authorizes activation, forge/live-ledger writes, cap/base changes, reduced tests or partial review.

## Exact verification and boundary precision

Versions, ordinals and suspension/retry counters are plain integers, never booleans. `current-launch` returns exactly
`action_id`, `current`, `current_action_id`, and `reason`. Every nonnull legacy result slot, including `historical_owner_result`, passes legacy and v1 model validation before decode.
`test_workflow_delivery.py` covers the pure no-I/O transition and fail-closed source/installed loading.

Run and retain real argv/stdout/stderr/exit receipts for:
```sh
python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_delivery.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_workflow_skill_contracts.py -v
just agent-workflow-tests
just build
task_root=$PWD; cd /private/tmp/issue-151-skill-validation-env
for skill in home/common/agent-skills/skills/{from-issue,ship-issue} home/common/claude-code/skills/orchestrate-issues; do devenv shell -- python3 /Users/anis/.codex/skills/.system/skill-creator/scripts/quick_validate.py "$task_root/$skill"; done
```
Use the existing PyYAML devenv.

D21 recovery closes direct/control/remainder wire shapes: direct/v2 has required
nullable `recovery`; control/v2 has the exact canonical issue-keyed `recoveries`
map (including explicit nulls); no summary, handoff or checkpoint has recovery;
and every remainder has nullable recovery plus `finished_at` (null live; actual
failed/stalled terminal time). A recovery is exactly the design's version-1
`delivery-recovery` object with derived id, exact transient failure and verified
absence objects, and one exact changed-evidence/new-authorization/
human-transient-retry basis. It binds actual scope/stage, does not grant
authority, folds null-first with successor intent, and D18 unresolved
denial/unknown still parks. Only trusted direct/control input can atomically mint
r2 after the latest failed/stalled r1, with retryable ready work and no active or
existing r2; it emits no evaluation/effect/consumption, gives r2 null requested
scope and fresh post-fold requirements, and never lets finish/stale owner output
mint r2. Add public valid recovery plus absence, denial, replay, third, active
and stale-proof no-write tests. Preserve the finite-custody invariant: disjoint
attempt/remainder ordinals and budgets, canonical creation key, current guard
before every effect/observation, fixed-deadline parking, 0/1/2 resume then fourth
suspension records three stalls, progress reset, and terminal-remainder-first
selection; identical direct/control replay returns existing/completed without a
write. Retain raw receipts and do not activate, install a generation or mutate a
live ledger.
