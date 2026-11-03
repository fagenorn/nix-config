# Issue 255 Isolated Git Record View Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make CORE's review records, commit subjects and the issue-100 recipe output independent of every Git attribute and configuration source the host or repository carries, so the same pins derive the same bundle anywhere for one Git version (https://github.com/fagenorn/nix-config/issues/255).

**Architecture:** One runner, `review_actual.record_git`, renders every record-shaping Git call in a fresh, template-free bare view directory that borrows the source's objects through an absolute alternate, under a scrubbed environment (D1, D7). `git_diff`, a new single `commit_subject` and issue 100's recipe go through it; the argv, `RECORD_POLICY`, both policy digests and the committed bundle stay byte-for-byte unchanged (D2, D4). Tests pair a biting raw-Git control with an isolation assertion at four tiers: CORE records, portable derivation, source/built parity, and the full-shape real objects (D6, D8). The [spec](../specs/2026-10-06-issue-255-record-view-isolation-design.md) owns every contract and the ledger D1–D10.

**Tech stack:** Python 3 standard library, unittest, Git 2.51.2 plumbing, Nix, just.

## Global Constraints

- No closed error code is added, and every published command keeps its closed error set (D1). `RECORD_POLICY`, `RECORD_POLICY_SHA256`, `PACKING_POLICY`, `PACKING_POLICY_SHA256`, caps, the issue-100 pins and domains, the five committed files under `tests/fixtures/retained-review-evidence/` and `ANCHOR_SHA256` do not change (D2).
- `record_git` runs no `git init`, sets no `GIT_CONFIG_GLOBAL`, and keeps no view between calls (D1, D7).
- Every invocation outside the spec's § *What stays outside the runner* list that renders a record or a recorded field goes through `record_git`; nothing in that list moves (D4).
- The REPLAY and EVIDENCE specs are not edited; RP24's lift lives in this spec and in `review_derivation`'s module docstring (D5).
- Every hostile test owns its `HOME`, `XDG_CONFIG_HOME` and `GIT_CONFIG_GLOBAL` and sets `GIT_CONFIG_NOSYSTEM=1` (D6).
- The retained root is `/Users/anis/tmp/nix-config`. No test writes it; hostile repository files go only into disposable clones or copies, and a retained run is quiescent: no commit, fetch or gc in any worktree while it runs (RP11).
- Every long command carries an explicit `timeout`. A skipped test is never acceptance.
- Commits go through `launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-255-256-259 --worker-id <worker> -- <git commit args>`, are SSH-signed, have subjects of at most 64 UTF-8 bytes, and end with the session trailer lines.
- Code and docstrings describe verified behaviour. Out of scope: the spec's § *Out of scope*.

## Test seams

- Suites run as `PYTHONPATH=python python3 -m unittest tests.<module>` from the worktree root; commands run as `python -m agent_tools.<module>`.
- `tests/hostile_git_test_support.py` is new, standard-library only and not a suite; `hostile_git_env` is the one combined hostile setup every tier uses (D8).
- CORE records: `actual_inputs` and `select_candidate` in process under `patch.dict(os.environ, env, clear=True)`; inventory through `record_git` (D7).
- Portable derivation: `DerivationTest.derive` over copies of the class repositories, compared with `self.shared()`.
- Only `tests/test_agent_tools_launchers.py` touches built launchers; its `AgentToolsLauncherTest` imports no `agent_tools` (CP18). Full shape runs only under `just agent-retained-tests /Users/anis/tmp/nix-config` (RP10).
- No test reads a private name. Verification command IDs: `agent-workflow-tests`, `nix-build` (`just build`), `just agent-installed-skill-tests`, `just agent-retained-tests`.

## Delivery estimate and boundaries

Estimates only. Product: ten paths in three tasks, two of them new test files (about 12 KB and 2.5 KB); source growth about 60 lines in `review_actual.py` and a net reduction in `review_issue100.py` and `review_projection.py`. Each derivation over the real objects takes minutes, so Task 3's retained gate runs once at the end with a 4-hour bound. One boundary: the guard is not acceptable without the tests that prove it.

Planning prototyped Tasks 1 and 2 in a scratch copy at the spec commit: the CORE suite failed at base on every isolation assertion with every control biting, and passed with the runner; the portable derivation case refused with `domain_mismatch` at base and passed with the runner, and every existing review suite with the new one passed (260 tests in about 37 minutes). The prototype was discarded.

## Task index

Task 1 — Isolated record runner and CORE record tests — python/agent_tools/review_actual.py, python/agent_tools/review_projection.py, tests/hostile_git_test_support.py, tests/test_review_record_view.py, justfile — full — [task-1.md](2026-10-06-issue-255-record-view-isolation.tasks/task-1.md)
Task 2 — Issue-100 recipe through the runner, portable derivation and RP24 lift — python/agent_tools/review_issue100.py, python/agent_tools/review_derivation.py, tests/test_review_derivation.py — full — [task-2.md](2026-10-06-issue-255-record-view-isolation.tasks/task-2.md)
Task 3 — Source/built parity, full-shape case and final gates — tests/test_agent_tools_launchers.py, tests/test_review_retained_full.py — full — [task-3.md](2026-10-06-issue-255-record-view-isolation.tasks/task-3.md)

## Decisions

Spec ledger rows D1–D7 bind every task. Planning appended D8 (tier allocation of the hostile proofs and the shared support module), D9 (index-and-`HEAD` `.gitattributes` has no biting control) and D10 (one `commit_subject` error for both callers).

---

## Standards review provenance

Reviewer: Codex (gpt-6-astra, xhigh), isolated read-only `plan-review`, base `31be729`, no fallback. Findings: 4 accepted (B1 Task 3's red copy takes the working tests; S1 in-range `.gitattributes` test, per D11; S2 gates keep producer exit status and logs; S3 Task 3 subject shortened), 0 rejected, 0 deferred.
