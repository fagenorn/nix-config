# adopt-project Rewrites Relative Markdown Links Across the Moves Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `adopt-project plan` derives, from the base tree and the planned moves, the rewritten bytes of every Markdown file whose relative links the moves would break, publishes a `link_rewrites` summary inside `plan_id`, and `apply` commits those bytes behind a commit gate that refuses any new broken relative link.

**Architecture:** One new standard-library module, `agent_tools.adopt_links`, owns the link grammar, tree-based resolution, target mapping and re-emission, with a pure core (`plan_link_rewrites`, `broken_count`) and thin git readers. `compose_plan` calls it before `compute_plan_id`; each changed file becomes an ordinary `write-file` in the tail, the summary enters the document, the evidence record and the id, and a ready gate reports the unrewritable links. `adopt_apply` gains the `no-new-broken-link` commit gate over `HEAD` versus the index and the same count as a post-commit proof over the commit versus its parent, and its status gate folds a split rename back onto the planned move.

**Tech stack:** Python 3 standard library (`agent_tools` package under `python/`: `posixpath`, `re`, `urllib.parse`), `unittest`, git fixture repositories.

Spec: `.agents/artifacts/specs/2026-10-10-issue-345-adopt-rewrite-markdown-links-design.md` (its `## Decision ledger` rows D1–D18 are cited by ID).

## Global Constraints

- Base: `901da282a0fb89579dce803108fddfb2f2b9138b` (`origin/main` at planning).
- Standard library only; no Markdown dependency (D3). New helper code lives in `python/agent_tools/` per `docs/standards/agent-helpers.md`.
- Unchanged closed sets: `ADOPT_ERROR_CODES`, `ACTIONS`, `OUTCOMES`, `PLAN_STATES`, `OPERATION_KINDS`, `PROVENANCES`, `LIFECYCLE_CLASSES`, `QUESTION_IDS`, `EVIDENCE_RECORD_MEMBERS` (D7, D8). `READY_GATES` gains exactly `no-unrewritable-link` (last); `COMMIT_GATES` gains exactly `no-new-broken-link` (before `cold-clone-resolves`) (D9). `apply` keeps exactly `--plan-id` and `--acknowledge-deletions`; `verify` gains no check.
- New repair ids: `adopt.link.unrewritable` (ready gate), `adopt.gate.no-new-broken-link` (commit gate, derived by `run_commit_gates`) and `adopt.commit.new_broken_link` (post-commit proof, D17).
- Prose that lands in code (docstrings, comments, fixed strings, README sentences) describes the code as it behaves at that task's commit.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `env PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]` (timeout at least 900 s; the adopt suites start git and resolver subprocesses).
- Final gate, once on the final head (sdd's, not per task): `just agent-workflow-tests` (timeout 3600 s). No `.nix` file changes, so `just build` runs only if one does.

## Test seams

- `adopt_links` functions, imported in-process by the new `home/common/agent-skills/tests/test_adopt_links.py` (D3 tables, AC2 boundary cases).
- `plan` on a fixture repository: `AdoptTestCase.plan` / `ready_plan` and the fixture builders in `home/common/agent-skills/tests/test_adopt_project.py`, run as `python -m agent_tools.adopt_project` under a temporary `HOME`; in-process `adopt_planning` functions the module already imports.
- `apply` by plan id: `ApplyTestCase.succeed` / `refuse` / `stored_plan` / `rewrite_stored_plan` and `apply_repo` in `home/common/agent-skills/tests/test_adopt_apply.py`; in-process `adopt_apply.expected_status` / `fold_split_renames`.

## Delivery estimate and boundaries

Estimates: 9 changed files — new `adopt_links.py` and `test_adopt_links.py`, `adopt_inspection.py`, `adopt_planning.py`, `adopt_project.py`, `adopt_apply.py`, `test_adopt_project.py`, `test_adopt_apply.py`, `justfile`, `python/README.md` — about +450 production lines and +590 test lines. One review package; Task 1 is independently deliverable if a package boundary forces a split.

## Task index

Task 1 — `adopt_links`: grammar, resolution, mapping and re-emission — `python/agent_tools/adopt_links.py`, `python/agent_tools/adopt_inspection.py`, `home/common/agent-skills/tests/test_adopt_links.py`, `justfile` — full — [task-1.md](2026-10-10-issue-345-adopt-rewrite-markdown-links.tasks/task-1.md)
Task 2 — `plan` derives the rewrites, the summary, the id input and the ready gate — `python/agent_tools/adopt_inspection.py`, `python/agent_tools/adopt_planning.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_project.py` — full — [task-2.md](2026-10-10-issue-345-adopt-rewrite-markdown-links.tasks/task-2.md)
Task 3 — `apply` commits the rewrites behind `no-new-broken-link` and proves the commit's links — `python/agent_tools/adopt_inspection.py`, `python/agent_tools/adopt_apply.py`, `python/agent_tools/adopt_project.py`, `home/common/agent-skills/tests/test_adopt_apply.py` — full — [task-3.md](2026-10-10-issue-345-adopt-rewrite-markdown-links.tasks/task-3.md)
Task 4 — The rewrite contract is documented — `python/README.md` — full — [task-4.md](2026-10-10-issue-345-adopt-rewrite-markdown-links.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 3 | `test_adopt_apply.py`: `LinkRewriteApplyTest.test_the_linked_fixture_applies_with_every_link_resolving` and `CommitLinkProofTest` (with Task 2's `LinkRewritePlanTest.test_the_linked_fixture_plans_to_ready_with_the_rewrites`) |
| AC2 | code (classified) | Task 2 | `test_adopt_project.py`: `LinkRewritePlanTest.test_anchors_titles_and_reference_definitions_survive_and_urls_stay` (with Task 1's `test_adopt_links.py` tables `LinkGrammarTest`, `ResolutionTest`, `RewriteTest`) |
| AC3 | code (classified) | Task 2 | `test_adopt_project.py`: `LinkRewritePlanTest.test_the_summary_is_published_and_enters_the_plan_id` and `test_a_different_rewrite_set_is_a_different_plan_id` (with Task 3's `LinkRewriteApplyTest.test_the_evidence_record_carries_the_summary`) |
| AC4 | code (classified) | Task 3 | `test_adopt_apply.py`: `LinkRewriteApplyTest.test_an_unrewritable_link_fails_the_commit_gate` (with Task 2's `LinkRewritePlanTest.test_a_dissolved_directory_link_keeps_the_plan_draft`) |
| AC5 | code (classified) | Task 4 | `just agent-workflow-tests` passes on the final head, run by sdd's final gate after Task 4 (Tasks 1–3's suites already green) |

## Decisions

- What is scanned and rewritten, both directions: D1, D2; `generated_file` targets dropped from the scan: D10, D13.
- Grammar and resolution: D3, refined by D15. Mapping and the unrewritable cases: D5; the derivation's view of deletions and survivors: D12 (appended by this plan).
- Re-emission: D4, refined by D14 (appended by this plan) and D18 (angle-target escaping, plan review).
- Bytes from the base tree, `overlap` unchanged: D6. `write-file` placement and the status fold: D7, widened by D16 (appended by this plan).
- The summary, its place in the document, the evidence record and `plan_id`: D8; published for every outcome: D13.
- The two gates: D9, refined by D17 (the post-commit link proof, plan review); AC4's forced-`ready` apply test: D11.

## Standards review provenance

Reviewer: Codex (codex-companion plan-review, gpt-6-astra, xhigh), isolated read-only mode, no focus, base `901da282a0fb89579dce803108fddfb2f2b9138b`; no fallback. The reviewer could not reach GitHub for the issue body and reviewed against the supplied issue text. Accepted 3 / rejected 0 / deferred 0: PR-B1 (the link gate does not cover what verification commands or a `pre-commit` hook stage → D17, Task 3), PR-B2 (raw angle re-emission changes an encoded name's referent → D18, Task 1), PR-S1 (stale module docstrings and Task 4's `./` sentence → Tasks 2–4).

---
