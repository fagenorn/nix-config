# agent_tools — the agent helper package

Agent-workflow Python is moving into one standard-library package, `agent_tools`, under `python/` (with its `pyproject.toml`).

## Package and launchers

`lib/agent-tools.nix` builds it into one Python environment, import-checks every module so that a broken import fails `just build`, and holds the command table.

Each row becomes a `~/.agents/bin/<command>` launcher, which unsets the `NIX_PYTHON*` variables and runs `python3 -I -m agent_tools.<module>` from that environment, so nothing on `PYTHONPATH` or in the working directory can shadow the store copy; `just agent-installed-skill-tests` proves it.

## Review packaging and feasibility

`review-package` and `review-feasibility` use the package command table; their source entry points are `python -m agent_tools.review_package` and `python -m agent_tools.review_feasibility`.

Actual production and generic projection share packing and the external `artifact-budget` policy queried by PATH; projection binds its policy identity.

`review-feasibility project` reads committed plans and authenticated Git history without mutating them, while `validate-result` checks closed canonical v3 results and producer exits.

Actual production also calls external `sdd-workspace` by PATH.

## `verified-tree`

`verified-tree` records a passing run of the declared verification against the git tree it verified (what a Git-backed build sees: the index's entries with tracked files' working-tree edits applied, built in a temporary index, so an untracked file is outside it until committed) as `verified-tree.json` in the worktree's own git directory; `verified-tree check` answers `verified` only for that same tree under the same verification ids, which is how sdd's final gate lets ship skip a rerun (#263).

## `launch-scope`

`launch-scope` (#276) contains a lifecycle agent's long commands: `launch-scope exec` checks that the launch (or worker) is live, runs the command in a new session whose processes carry `AGENT_LAUNCH_SCOPE=<repo-scope>/<run-id>/<action-id>/<nonce>` (`<repo-scope>` is a hash of the registry's real path, so another repository's launch with the same run and action ids is never touched), and kills whatever the command left behind when it returns, while `launch-scope reap --action-id` (an owner, before its exit write) and `reap --sweep` (the orchestrate-issues stop pass, for every non-current launch of the run) kill the marked processes, and the process groups those processes prove, recorded in a host-local registry under the ledger repository's git common dir at `agent-launch/<run-id>/<action-id>/`; on darwin an Apple platform binary (`/bin`, `/usr/bin`) exposes no environment, so an orphaned group holding only such processes is never proved and survives a sweep.

`launch-scope scratch` (#277) prints the launch's one scratch root, a `launch-scope-*` directory under the system temp directory that the owner and its workers share, recorded as `scratch.json` in the launch's registry directory; once a reap finds the launch's processes gone it force-removes every worktree registered inside that root, present or missing, and deletes the root, never running a repository-wide `git worktree prune` (#277 D10); and every reap reports the registered worktrees outside the main checkout and outside every recorded root as `unattributed_worktrees`, deleting none of them.

## `lane-triage`

`lane-triage evaluate --repo-root <root> --input -` (#279) reads an owner's triage record on stdin, reads `bindings.workflow.light_lane` (an optional `resolve-project` member; absent or `null` means unsupported) through `agent_tools.resolve_project.resolve`, the one public function that composes exactly what `resolve-project resolve` prints, and prints the verdict `{hits, lane, mode}` without writing anything: `lane` is `light` only when no signal is `hit` or `doubt` and no predicted path matches a `risk_paths` glob, an absent or `null` member exits 2 with `light_lane_unsupported`, and `from-issue` Phase 0 records the verdict while every attempt still runs full.

## adopt-project

`adopt-project plan` asks two kinds of open question: `project-id`, answered by declaring exactly one remote or authoring a contract with the project id, and `candidate-class` (#340), one per tracked or targeted-ignored agent path that no classification row settles (none covers it, or a targeted-ignored one it covers resolves outside the repository or cannot be read), keyed by its `subject` (the path) and carrying the one `value` the question accepts: `archive-history` for a tracked path, which plans a `git mv` to `.agents/knowledge/archive/adopted/<path>`, `retain-product` for an ignored one, and `null`, no answer, for a secret-shaped tracked path, which stays open until a central classification row covers it or it leaves the repository, or for a tracked symlink resolving outside the repository, which stays open until it leaves the repository; `plan --answer QUESTION SUBJECT VALUE` (repeatable, order-independent) settles a `candidate-class` question, refusing the first violation as `adopt.decisions.invalid_answer` (an id other than `candidate-class`, a subject answered twice, or a value other than the offered one) or `adopt.decisions.unmatched_answer` (a subject that is not an undecided candidate of this inspection), checking each answer in `(id, subject, value)` order and changing nothing on a refusal; the answers enter `decisions.answered` and therefore `plan_id`, and `apply --plan-id` re-applies them from the stored plan (refusing a malformed `decisions.answered` as `adopt.plan.malformed`), so the plan id, not an `apply` flag, authenticates them.

## Transaction core

`agent_tools.transaction_core` is the transaction core's library surface, with no command-table row and no caller until #125's cutover: slice 1 (#204) holds caller-rooted transaction state under a closed schema and lifecycle, slice 2 (#205) adds fenced custody — a lease authority over concurrency keys in `agent_tools.transaction_custody`, epoch-fenced writes, and evidence and grant admissibility derived from the fence — and slice 3 (#206) adds the administrative protocol — a durable write intent before every external call, inspection before any retry, and an automatic-retry budget — in `agent_tools.transaction_invocation`; slice 4 (#207) then adds an immutable proof plan compiled at creation (`agent_tools.transaction_plan`), core-collected obligations, and one convergence cohort (at most three attempts) that `settle_proof` alone seals into `succeeded` or parks as `proof_rejected` or `proof_did_not_converge`, never rolling back (`agent_tools.transaction_proof`); slice 5 (#208) adds an immutable recovery plan compiled at creation beside the proof plan (`agent_tools.transaction_recovery_plan`), rollback anchors verified in `ready` before publication, `abandoned` only while no action has had an effect, and `begin_recovery`, `settle_recovery` and `roll_forward` as the only ways into `recovering`, into `rolled_back` and to a linked child transaction (`agent_tools.transaction_recovery`); slice 6 (#209) writes a permanent, content-addressed terminal receipt under the store root's `receipts/` and reads it back before the one `state.json` write that enters any terminal, which ends with a `receipt_sealed` event naming it, then re-reads that receipt on every load (`agent_tools.transaction_receipt`), and makes `dispose_failed` the only way into `failed`: it takes a fresh grant and one closed ground, and it yields an `effects_unobservable` qualifier with per-key hazard markers only when a human grant at the transaction's authority class asserts an observability ground (`agent_tools.transaction_disposition`), with the `transaction-state/v6` validator and snapshot fold in `agent_tools.transaction_history`, over the durable-file primitives in `agent_tools.transaction_storage`.

The [#117 attempt-lifecycle decision](../.agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md) selects attempts as the transaction core's first consumer and ship-release second.

The decision governs the planned single-store migration, immutable subject/identity, fenced custody and terminal evidence, and maps the already-delivered agent-slot admission (#150) and delivery contracts, remainders and authorization continuity (#151/#171) onto that core.

The decision is an architecture decision: runtime core delivery belongs to the open #123/#125, and the lifecycle paths and behavior that `home/common/agent-skills/README.md` describes remain the shipped implementation until that cutover.

## Retained review evidence

The retained review evidence that `derive-review-feasibility-fixtures` derives is committed as five files under `tests/fixtures/retained-review-evidence/` (#235); `replay-retained` replays that directory under the anchor digest held in `tests/retained_evidence_test_support.py`, and an authentic replay exits 2 with `projection_unavailable`, because two of the retained issue-121 boundaries are authenticated refusals rather than measurements.
