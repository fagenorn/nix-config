# Release Profiles, Adapter Contract and Forge Adapter Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A required, closed `release` contract member compiles into an immutable `ResolvedReleaseProfile` whose candidate binding is exactly the transaction core's `create` input; a three-operation adapter contract with a GitHub forge adapter enforces every mutation through the real lifecycle guard; the three release-profile conformance checks judge real compiler rules.

**Architecture:** New standard-library modules `release_adapter` (descriptors, registry, typed results, `core_binding`), `forge_adapter`, `release_profile` (grammar, compiler, `bind_candidate`), `release_bridge` and the read-only `release` command. `resolve_project` validates the member and derives `capabilities.release`; `conformance_checks` calls the compiler's rules; `lifecycle_guard.py` gains a tag-push arm, a `gh release create` arm and the #116 D5 repair, pinned against one shared spelling fixture.

**Tech stack:** Python 3 standard library, `unittest`; Home Manager / Nix (`lib/agent-tools.nix`, `home/common/claude-code/default.nix`); Just.

Spec: `.agents/artifacts/specs/2026-10-09-issue-124-release-profiles-forge-adapter-design.md`. Its `## Decision ledger` (D1–D17, plus D18–D23 appended by this plan) is cited by ID; spec section numbers are written "spec §N".

## Global Constraints

- Python standard library only; no network in any test. Every external executable (`git`, `gh`, `claude-bash-lifecycle-guard`) is invoked by name on `PATH`; no module reads its own source through `__file__` (agent-helpers rule 3, D17).
- `home/common/claude-code/lifecycle_guard.py` stays standard-library-only and imports nothing from `agent_tools` (D9).
- No module copies the proof or recovery vocabulary of `transaction_plan` / `transaction_recovery_plan`; the core compilers are its only home (D2).
- No `ResolvedProject` member is added; `capabilities` keeps exactly its eleven entries (D1).
- No adapter `invoke` is reachable from any CLI; the `release` command is read-only (D15).
- No release, tag, push, Release, branch-protection or billing mutation is performed by any task or test.
- Test commands run from the worktree root, in the foreground under `launch-scope exec … --`, as `PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]` with a timeout of at least 600 s. Each new test file is added to the `agent-workflow-tests` recipe in `justfile` by the task that creates it.
- The guard suite runs only against a built settings artifact: after `just build` (timeout 3600 s), `CLAUDE_SETTINGS_PATH="$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')" python3 -m unittest tests/test_claude_permission_guard.py`.
- Final gate, once on the final head (sdd's final gate): `just build` (3600 s), `just agent-workflow-tests` (3600 s), the guard suite above, and `just agent-instruction-budget` with no `--raise-label` (600 s), which must print `check: pass`.
- Every commit is signed and ends with the session's `Co-Authored-By` and `Claude-Session` trailers.

## Test seams

The spec's seams; no task adds one below them:

- Resolver CLI `python -m agent_tools.resolve_project resolve` (`ResolverTestCase`).
- `release_profile` functions with an injected descriptor registry (descriptor data only), and `python -m agent_tools.release` as a subprocess.
- The real `TransactionStore` with `release_adapter.core_binding` (prior art `ProtocolCase`, `CustodyCase`).
- The forge adapter against fake `gh`/`git`/`claude-bash-lifecycle-guard` on `PATH` (`tests/forge_world.py`).
- The guard CLI in `tests/test_claude_permission_guard.py` with `tests/fixtures/forge-adapter-spellings.json`.
- The conformance engine run (`test_conformance*`, its S3 in-process seam) and the adoption planner (`test_adopt_project`).

## Delivery estimate and boundaries

Estimates only: ~30 files (5 new modules ~2,000 lines; new tests and fixtures ~2,400 lines). Group **A** (Tasks 1–5: compiler, resolver, conformance, bridge, inspection) and group **B** (Tasks 6–8: adapter runtime, forge invoke, guard) are independently deliverable in that order (D16, refined by D18): if `diff-scope` reports the branch over the review limit at ship time, A and B ship as two PRs. The demo is ship-time evidence, read-only: `release profile inspect github-release` and `release adapter inspect github-forge pr_merge --parameters '{…}'` against a live open PR (Task 6 builds the command; the shipping owner records its state and protection facts in the delivery evidence).

## Task index

Task 1 — Descriptor schema, closed registry, forge descriptor and profile grammar — `python/agent_tools/{release_adapter,forge_adapter,release_profile}.py`, `tests/release_test_support.py`, `tests/fixtures/release/*.json`, `tests/test_release_grammar.py`, `justfile` — full — [task-1.md](2026-10-09-issue-124-release-profiles-forge-adapter.tasks/task-1.md)

Task 2 — Admissibility compiler, `ResolvedReleaseProfile` and `bind_candidate` — `python/agent_tools/release_profile.py`, `tests/release_test_support.py`, `tests/test_release_profile.py`, `justfile` — full — [task-2.md](2026-10-09-issue-124-release-profiles-forge-adapter.tasks/task-2.md)

Task 3 — Required `release` member, derived `capabilities.release`, conformance activation — `python/agent_tools/{resolve_project,conformance_checks,conformance_registry}.py`, `.agents/project.json`, `home/common/agent-skills/evals/fixture-repo/.agents/project.json`, `home/common/agent-skills/skills/ship-release/SKILL.md`, `home/common/agent-skills/tests/test_{resolve_project,conformance_checks,conformance_registry,workflow_skill_contracts}.py` — full — [task-3.md](2026-10-09-issue-124-release-profiles-forge-adapter.tasks/task-3.md)

Task 4 — nix-config's `github-release` profile and the legacy deploy bridge — `.agents/project.json`, `python/agent_tools/{release_bridge,adopt_planning}.py`, `tests/fixtures/legacy-skills-config-1722a65d.json`, `tests/test_release_bridge.py`, `home/common/agent-skills/tests/test_{adopt_project,conformance_checks,resolve_project,resolve_platform,conformance,conformance_registry}.py`, `justfile` — full — [task-4.md](2026-10-09-issue-124-release-profiles-forge-adapter.tasks/task-4.md)

Task 5 — The `release` command and `ReleaseProfileInspection` — `python/agent_tools/release.py`, `lib/agent-tools.nix`, `python/README.md`, `tests/test_release_command.py`, `justfile` — full — [task-5.md](2026-10-09-issue-124-release-profiles-forge-adapter.tasks/task-5.md)

Task 6 — Typed results, `core_binding`, forge inspect, read spellings, `adapter inspect` — `python/agent_tools/{release_adapter,forge_adapter,release}.py`, `tests/fixtures/forge-adapter-spellings.json`, `tests/forge_world.py`, `tests/test_{forge_adapter,release_command}.py`, `justfile` — full — [task-6.md](2026-10-09-issue-124-release-profiles-forge-adapter.tasks/task-6.md)

Task 7 — Forge invoke, guard enforcement, post-invocation observation — `python/agent_tools/forge_adapter.py`, `tests/fixtures/forge-adapter-spellings.json`, `tests/forge_world.py`, `tests/test_{forge_adapter,release_adapter_core}.py`, `python/README.md`, `justfile` — full — [task-7.md](2026-10-09-issue-124-release-profiles-forge-adapter.tasks/task-7.md)

Task 8 — Guard arms, the D5 repair, `PATH` wiring, ship-release 4.5f — `home/common/claude-code/{lifecycle_guard.py,default.nix,README.md}`, `tests/test_claude_permission_guard.py`, `home/common/agent-skills/skills/ship-release/SKILL.md`, `home/common/agent-skills/tests/test_ship_release_contracts.py` — full — [task-8.md](2026-10-09-issue-124-release-profiles-forge-adapter.tasks/task-8.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 2 | `tests/test_release_profile.py::AcceptanceOneTest` (accepts both profiles; rejects the three cases; store tree unchanged, D20) |
| AC2 | code (classified) | Task 3 | `test_resolve_project.py::ReleaseMemberTest` |
| AC3 | code (classified) | Task 7 | `tests/test_forge_adapter.py`: `PublicSurfaceTest`, `InvokeResultSetTest`, Task 6's `TagInspectTest` |
| AC4 | code (classified) | Task 8 | `test_claude_permission_guard.py::…test_every_adapter_spelling_is_an_allowed_row`, whole guard suite green |
| AC5 | code (classified) | Task 4 | `tests/test_release_bridge.py::ProjectionTest`, the sweep test in `test_adopt_project.py` |
| AC6 | code (classified) | Task 3 | `test_conformance_checks.py::ReleaseProfileChecksTest` (Task 4 adds nix-config's passed ×3) |
| AC7 | code (classified) | Task 7 | `tests/test_forge_adapter.py`: `InspectFailureTest`, `PrMergeInspectTest` (Task 6), `InvokeFailureTest`, `SpellingFixtureTest` |
| AC8 | code (classified) | Task 7 | `tests/test_release_adapter_core.py::PostInvocationObservationTest` |
| AC9 | code (classified) | Task 6 | `tests/test_forge_adapter.py::HostCapacityTest` |

## Decisions

Members cite the spec ledger by ID (D1–D17). Appended by this plan: D18 (group A carries descriptors, registry and the `release` command), D19 (descriptor shape), D20 (AC1/AC6 proofs), D21 (ship-release citation, one-line 4.5f), D22 (fixture coverage, repository classes), D23 (lowering, digest, blocked precedence, bridge questions, invoke checkout, precondition reads).

---

Task members are the normative executable instructions. Read this root once for shared constraints and then only the selected linked member.
