# Shared Verification Blocker c1 Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A pure module, `agent_tools.verification_blocker`, holds the vocabulary, the three closed wire shapes, the secret-shape rule and the content identity of a shared verification blocker, and the `verification-observe` command is its only reader, printing typed observations and wired into the command table and the Claude permission surface, with no caller yet.

**Architecture:** Task 1 writes the pure module and its import-level tables (D1–D5, D15). Task 2 writes the adapter as a thin shell over `build_failure` and `observe` (D6–D8, D11–D14), its command-table row and its `python/README.md` section. Task 3 adds the two allow entries, the Claude Code README count and the guard suite's rows (D9).

**Tech stack:** Python 3 standard library (`json`, `re`, `unicodedata`, `argparse`, `subprocess`, `unittest`), Git, Just, Nix.

Spec: `.agents/artifacts/specs/2026-11-02-issue-543-verification-blocker-c1-design.md`; a bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/543.

## Global Constraints

- Base `328f08daca0cd21e71a622f98c91c3f3a7a6728c`, the immutable delivery base. Spec commits `8ff1ae5c` and `f9ffab69`, plus the planning commit that appends D14 and D15.
- Standard library only: `python/pyproject.toml` keeps `dependencies = []`. New code is two `agent_tools` modules and one command-table row (docs/standards/agent-helpers.md rules 1–5).
- Not edited: `home/common/claude-code/lifecycle_guard.py`; `python/agent_tools/adopt_inspection.py`, `resolve_project.py` and `canonical.py`; any skill, guidance or `.agents/instructions` document; `CLAUDE.md`; `AGENTS.md`; `home/common/agent-skills/README.md`; anything under `home/common/agent-skills/tests/`; `tests/test_agent_tools_launchers.py` (D9; no instruction ceiling moves).
- Comments, docstrings and README sentences describe the code as it behaves at the task's commit, never a later task's. No `TODO` or `FIXME`. Code prose and the README cite this spec as `issue 543 Dn`, never a bare `Dn`. Commit messages say "issue 543", never a bare `#543`.
- The live lifecycle guard reads a command's raw text, so no gate command or commit message pairs `git` with `push`; the tests run Git from Python, which no Bash call shows.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`; commits are SSH-signed, subjects at most 64 bytes, ending with the session's trailer lines. Scratch files go under the root `launch-scope scratch` prints. Never run `just switch`, and never push.
- Focused tests: Task 1's module ends `Ran 14 tests` (under 1 s); Task 2's ends `Ran 13 tests` (about 20 s).
- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests`, timeout 3600 s each.

## Test seams

- The pure module by import in `tests/test_verification_blocker.py`: tables over the three shapes and declarations, one pinned literal id, strict load (D10).
- The adapter as `python -m agent_tools.verification_observe` in `tests/test_verification_observe.py`, over the `tests/test_verified_tree.py` harness (eval fixture project, temporary `HOME` manifest, hermetic Git) plus a local bare `origin` with automatic maintenance off and a publishing clone. Assertions read exit codes, stdout bytes, stderr lines and refs, never helper call counts (D10).
- The guard suite, `tests/test_claude_permission_guard.py`, only against the built settings and base policy.
- Integration: `just agent-workflow-tests` (both new modules listed) and `just build`.

## Delivery estimate and boundaries

Figures come from a scratch prototype of all four new files, green under the tests below while planning: `verification_blocker.py` about 310 lines, its tests about 290, `verification_observe.py` about 210, its tests about 310, one `python/README.md` section of about 4 KB, and one- to five-line edits to `lib/agent-tools.nix`, the `justfile`, `default.nix`, the Claude Code README and the guard suite. One boundary, `all`: c1 is already the parent's first slice, and no task stands alone (the adapter needs the module, the allow entries need the command).

## Task index

Task 1 — Pure verification blocker module — `python/agent_tools/verification_blocker.py`, `tests/test_verification_blocker.py`, `justfile` — full — [task-1.md](2026-11-02-issue-543-verification-blocker-c1.tasks/task-1.md)

Task 2 — `verification-observe` adapter command — `python/agent_tools/verification_observe.py`, `tests/test_verification_observe.py`, `lib/agent-tools.nix`, `python/README.md`, `justfile` — full — [task-2.md](2026-11-02-issue-543-verification-blocker-c1.tasks/task-2.md)

Task 3 — Allow `verification-observe` in the Claude permission surface — `home/common/claude-code/default.nix`, `home/common/claude-code/README.md`, `tests/test_claude_permission_guard.py` — full — [task-3.md](2026-11-02-issue-543-verification-blocker-c1.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 1 | `tests/test_verification_blocker.py`: `ShapeTest` and `DeclarationTest` (malformed and unclassified refused), `SecretShapeTest` (every D4 clause, a superset of `is_secret_path`), `IdentityTest` (the pinned id, equal across key order, distinct per changed member, none for an invalid failure). No shape has a member for logs, env values, transcripts or the worktree path (closed objects, D2). Fails at Task 1 Step 2; green at the final gate. |
| AC2 | code (classified) | Task 2 | `tests/test_verification_observe.py`: `FailureTest` (one resolved command, the guard, no host path in stdout) and `ObserveTest` (equal, changed, `null`, nested entries; `test_a_failed_fetch_prints_nothing_and_moves_nothing`, `test_a_failed_or_malformed_read_after_the_fetch_is_refused`). Fails at Task 2 Step 2; green at the final gate. |
| AC3 | code (classified) | Task 3 | Tasks 1 and 2 add both modules to `just agent-workflow-tests`; Task 3 Step 4 runs `tests/test_claude_permission_guard.py` against the build, ending `OK`. |
| AC4 | code (classified) | Task 3 | Each task's focused tests; Task 3 Step 4 runs `just build`; sdd's final verification runs `just build` and `just agent-workflow-tests`, whose `verified-tree check` `run` holds `nix-build` and `agent-workflow-tests` and never `nix-activate`. No command in this plan runs `just switch`. |

## Decisions

The plan rests on the spec's D1–D13. Planning appends D14 (one read per selected path, no optional locks) and D15 (the guard's ref-free checks before the fetch, the byte bound after it, the pure module's imports). Standards review appends D16 (a PATH `git` shim as the post-fetch read-failure seam).

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, gpt-6-astra, xhigh), isolated read-only mode, base `328f08daca0cd21e71a622f98c91c3f3a7a6728c`, plan head `0f0074a4`, no focus, no fallback. Accepted 3, rejected 0, deferred 0. PR543-B1 (Task 2 built before staging its new module): Task 2 Step 4 now stages before `just build`. PR543-B2 (Task 3 forecast undercounted `default.nix`): `r3a.added_lines` is 4. PR543-S1 (no post-fetch read failure tested): Task 2 adds `test_a_failed_or_malformed_read_after_the_fetch_is_refused` per D16; counts move to 13 and 27.

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"d2d5053b910d0f1003aace10dbed4ae174d296eb","kind":"git-range-ownership/v1","process_ranges":[{"base":"328f08daca0cd21e71a622f98c91c3f3a7a6728c","boundaries":["all"],"head":"ce1694dfdc8a3f7202f7968a3387bcd12a09b795"},{"base":"653290110492ea143a0cb88a76f256b5452dd791","boundaries":["all"],"head":"34484a1804b31d92f5a30b166da69d680c398cb8"},{"base":"6e0424b483eb89927bf4bc602a940b1cbe4e6a93","boundaries":["all"],"head":"b6614a46cf4ad91fbdca7e7d9c00cbbaff1911d8"}],"tree":"637dea7967513131eb60e2673a0703da365ff741"},"boundaries":[{"acceptance":"Issue 543 complete: AC1-AC4 green under the focused tests, just agent-workflow-tests and just build","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3"],"process_package":{"plan":".agents/artifacts/plans/2026-11-02-issue-543-verification-blocker-c1.md","spec":".agents/artifacts/specs/2026-11-02-issue-543-verification-blocker-c1-design.md","tasks":[".agents/artifacts/plans/2026-11-02-issue-543-verification-blocker-c1.tasks/task-1.md",".agents/artifacts/plans/2026-11-02-issue-543-verification-blocker-c1.tasks/task-2.md",".agents/artifacts/plans/2026-11-02-issue-543-verification-blocker-c1.tasks/task-3.md"]},"tasks":[1,2,3]}],"delivery_base":"328f08daca0cd21e71a622f98c91c3f3a7a6728c","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":480,"boundary":"all","deleted_lines":0,"record_bytes":40960,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":3,"owner":0,"path":".agents/artifacts/specs/2026-11-02-issue-543-verification-blocker-c1-design.md"},{"bounds":[{"added_lines":140,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-543-verification-blocker-c1.md"},{"bounds":[{"added_lines":420,"boundary":"all","deleted_lines":0,"record_bytes":28672,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-543-verification-blocker-c1.tasks/task-1.md"},{"bounds":[{"added_lines":440,"boundary":"all","deleted_lines":0,"record_bytes":32768,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-543-verification-blocker-c1.tasks/task-2.md"},{"bounds":[{"added_lines":130,"boundary":"all","deleted_lines":0,"record_bytes":10240,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-543-verification-blocker-c1.tasks/task-3.md"}],"proposed_boundary":"all","schema_version":3}
```
