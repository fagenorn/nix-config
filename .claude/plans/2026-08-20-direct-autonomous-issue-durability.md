# Direct Autonomous Issue Durability Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make direct `from-issue --auto` acquisition durable and restart-safe through one strict `workflow-state direct-owner` interface while preserving all dispatcher-owned and interactive-direct behavior.

**Architecture:** Extend the existing standard-library lifecycle helper with an issue-locked discovery/acquisition transaction over retained direct ledgers, and deepen its current one-issue control policy so both public acquisition paths derive the same attempt, deadline, worktree, retry, and refusal outcomes. Keep `from-issue` as an external-I/O adapter that satisfies only requested observations, adopts the persisted owner envelope, and stops on the helper's terminal response.

**Tech stack:** Python 3 standard library (`argparse`, `fcntl`, `json`, hardened filesystem primitives), `unittest` subprocess/concurrency fixtures, Markdown skill contracts, Nix/Home Manager publication, Just.

## Global Constraints

- `.claude/specs/2026-08-20-direct-autonomous-issue-durability-design.md` is authoritative; implementations cite D1–D14 and do not duplicate its decision rationale.
- Phase-0 scope is direct lifecycle acquisition plus the `from-issue` adapter only. Do not change dispatcher request/response envelopes, ordinary interactive-direct ledger-free behavior, or the existing explicitly durable interactive route.
- `workflow-state` remains Python-standard-library-only and performs no tracker query, Git inspection, owner spawn, waiter installation, process-liveness check, or wall-clock read. Every decision instant and normalized observation comes from the request.
- The exact public acquisition command is `workflow-state direct-owner --repo-root <absolute-ledger-repository-root> --request-file <absolute-json-path>` with direct interface version 1 and only the strict request/response shapes in D2/D6.
- Direct IDs are module-owned `direct-<positive-issue>-<six-decimal-sequence>` identities from `000001` through `999999`. Discovery scans retained directories under `.direct-<issue>.lock`; no active-run index, cleanup, migration, pointer, random ID, or new retry policy is permitted.
- Lock order is stable issue lock then run lock. `progress` and `finish` remain run-lock-only. Accepted acquisition is persisted before `owner` stdout; every invalid request, corruption, ambiguity, inapplicable authorization, and active-owner refusal leaves all existing `state.json` bytes unchanged.
- Public `init-run` and `control` reject reserved direct identities before creating or opening their run directory; `progress` and `finish` accept only the exact direct identity returned to an owner and retain their existing validation.
- The existing schema version, fixed deadline, two-attempt cap, late-finish authority, retained-worktree rules, handoff representation, compact terminal result, owner mutation commands, and dispatcher action order/wire shapes do not change.
- The direct adapter sends literal `new_run` and `owner_unavailable` booleans on every request, false by default and true only under a current explicit user instruction for that exact exceptional transition. Restart, silence, tracker reopening, and desire to continue never imply authorization.
- All implementation tasks are `full`: they touch concurrency, lifecycle, reserved identity, CLI wire shape, or public workflow semantics. SDD performs a full per-task review after each task and, after all tasks, the mandatory independent two-axis whole-branch review: conformance against the spec/plan and correctness against the implementation diff. Apply and re-review required fixes before completion.
- The worktree was based on `e66f199d79562930a9dde95726c406e711dad340`; execution records its own implementation BASE after the plan commit. Scope all range checks to the files named in the task `Files` blocks so design/plan commits and integration advances cannot create false scope failures.
- After the two-axis review and any fix wave, final repository verification is exactly `just agent-workflow-tests` followed by `just build`; both must exit 0 at the reviewed HEAD.
- Use test-first commits, preserve configured SSH signing, append `Co-Authored-By: Codex <noreply@openai.com>`, and never disable signing.

## Test seams

- Direct-owner CLI seam: strict request files plus injected UTC instants assert canonical newline-terminated `observe`, `owner`, and `terminal` responses, then reopen `state.json` after each accepted transition.
- Durable/concurrency seam: independent subprocesses race first acquisition; byte snapshots and reconstructed processes prove no in-memory discovery state, no duplicate run/attempt, and no rewrite on active-owner refusal or discovery failure.
- Filesystem seam: malformed namespace entries, non-directory/symlinked run entries, non-regular/symlinked issue and run locks, unsafe state, missing/corrupt ledgers, wrong issue/run identities, ambiguous nonterminal histories, and sequence exhaustion fail under the hardened no-follow routines.
- Public capability seam: `init-run`/`control` reject reserved direct IDs both before creation and after a retained run exists, byte-unchanged, while `progress`/`finish` accept an emitted direct identity.
- Policy-equivalence seam: existing control scenarios remain green while direct scenarios assert the same handoff resume, unavailable-owner resume, expiry, owner-failure retry, attempt-2 refusal, fixed deadline, and retained worktree results.
- Skill contract seam: direct autonomous acquisition names only `direct-owner`, loops through exact requested external facts, never auto-asserts either flag, adopts `owner`, and returns `terminal` without a dispatcher waiter; adjacent invocation modes remain unchanged.
- Repository seams: `just agent-workflow-tests` proves deterministic helper and prose contracts; `just build` proves the updated helper and skill files are distributed through existing Nix wiring.

## Task index

Task 1 — Add the strict direct-owner lifecycle acquisition interface — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-1.md](2026-08-20-direct-autonomous-issue-durability.tasks/task-1.md)

Task 2 — Route direct autonomous from-issue through durable acquisition — `.claude/specs/2026-08-19-workflow-control-plane-design.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/AUTO.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-08-20-direct-autonomous-issue-durability.tasks/task-2.md)

## Decisions

- Task 1 implements the shared acquisition boundary, strict wire shapes, namespace/locking model, authorization rules, compact projections, public capability split, and helper-prose correction per D1–D7 and D11–D13.
- Task 2 implements the invocation-shape adapter boundary, adjacent handoff/worktree contracts, external-observation loop, and predecessor-spec amendment per D2, D6, D8, D10, and D13.
- Both tasks prove only the public seams selected by D9/D12; no private implementation function becomes a test API.

## Phase-5 review provenance and dispositions

- Reviewer: native fresh reviewer `/root/issue73_plan_review`
- Report: `/Users/anis/tmp/nix-config/.git/worktrees/worktree-issue-73-direct-autonomous-durability/PLAN-REVIEW.md`
- Reviewed HEAD: `0b41b2d04c20a27368f9b95d4a9c2a653aedf1e7`
- Fallback: native because `codex-collaboration` is unavailable in native Codex

| Finding | Disposition |
| --- | --- |
| Dispatcher-only handoff and universal direct-worktree prose contradict direct autonomous resume/adoption | accepted — Task 2 now updates the phase-gate, Phase-1, and corresponding contract tests with acquisition-mode-specific behavior per D10 |
| Shared policy lacks a provenance-safe retained-worktree input for authorized new runs | accepted — Task 1 now passes a discovery-validated retained terminal path into the shared policy, which alone chooses it versus a candidate per D11 |
| Reserved capability test proves creation refusal but not takeover refusal | accepted — Task 1 now snapshots an existing direct ledger and proves both public commands fail byte-unchanged per D12 |
| New per-issue lock and non-directory namespace entries lack filesystem coverage | accepted — Task 1 adds issue-lock sentinel and regular-file run-entry cases per D12 |
| Lifecycle terminal tests do not pin the closed response shape | accepted — Task 1 now asserts complete merged, stopped, and refused terminal objects per D12 |
| Adjacent accepted spec and helper docstring remain stale | accepted — Tasks 1–2 correct both live statements and include the predecessor spec in owned path checks per D13 |

### Focused re-review

- Reviewed HEAD: `f2d1dff7d4eecf91dc5a5222035b36e56a6bc045`
- Result: all six original findings resolved; one new Should-fix accepted

| Finding | Disposition |
| --- | --- |
| Strict-request tests omit boolean version/budget, zero budget, non-boolean authorizations, and a missing member | accepted — Task 1 adds the complete mutation-free failure matrix per D14 |

---
