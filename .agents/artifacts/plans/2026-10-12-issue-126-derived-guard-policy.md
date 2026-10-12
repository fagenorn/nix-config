# Derived Lifecycle-Guard Policy Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The lifecycle guard's facts for every registered project are compiled from the fleet registry and each project's contract on `origin`, and the two hand-authored Nodo rows leave `home/common/claude-code/default.nix` in the same commit that makes the guard read the compiled policy (https://github.com/fagenorn/nix-config/issues/126).

**Architecture:** A new `agent_tools` command, `guard-policy compile`, copies the Nix-built base policy and adds one derived row per registered project that passes the twelve-step proof of spec section 2; a home-manager activation step and the installed `claude-guard-policy` command run it. The guard keeps reading one `--policy` file, now the compiled one under `~/.agents/state/guard/`, and treats a derived row as authorization for exactly that repository. Three small reuse seams land first so the compiler shares registration's branch rule, the pinned fetch and the forge adapter's slug rule instead of copying them.

**Tech stack:** Python 3 standard library (`agent_tools` under `python/`, the standalone `lifecycle_guard.py`), `unittest`, Nix (home-manager module `home/common/claude-code/default.nix`, command table `lib/agent-tools.nix`), `git` and `gh` as child processes.

Spec: `.agents/artifacts/specs/2026-10-12-issue-126-derived-guard-policy-design.md` (requirements R1–R7; its `## Decision ledger` rows D1–D16 are cited by ID; "issue 116 Dn" cites the ledger that spec names).

## Global Constraints

- Base: `450f1de3627bd206a325ec1e46990d0d6cc61dc3` (`origin/main` at planning). Tasks land in index order; a later task assumes every earlier one.
- Task 3 is one commit: the guard reading derived rows, the base policy, the compiled-policy path, the activation step and the removal of both Nodo literals (spec section 6, issue 116 D4). Gate, run by Tasks 3 and 4 — no commit of the branch may hold both tables or neither:

  ```bash
  for c in $(git rev-list 450f1de3627b..HEAD); do
    literal=0; derived=0
    if git grep -q elevenyellow "$c" -- home/common/claude-code/default.nix; then literal=1; fi
    if git grep -q derived_repositories "$c" -- home/common/claude-code/lifecycle_guard.py; then derived=1; fi
    if [ $((literal + derived)) -ne 1 ]; then echo "half-wired at $c"; exit 1; fi
  done
  ```

- `home/common/claude-code/lifecycle_guard.py` stays one standard-library file that imports nothing from `agent_tools`, reads one policy file and runs `git`, `gh` and `jq` by the absolute paths its policy names (`docs/standards/agent-helpers.md`). New helper code lives in `agent_tools`; a command is a module plus one row of `lib/agent-tools.nix` (rule 1); the command module is a thin shell over importable functions (rule 2); no `sys.path` edit, `importlib` load or `__file__` lookup (rule 3); digests come from `agent_tools.canonical.telemetry_digest` (rule 4); tests drive the command as `python -m agent_tools.guard_policy` (rule 5).
- No test contacts GitHub or a network remote, reads the host's fleet registry, or reads the host's compiled policy (`~/.agents/state/guard/policy.json`). Nothing in this plan runs the installed `claude-guard-policy` or `just switch`: both write host state and fetch in registered checkouts, which is the orchestrating session's proof step (spec `## Acceptance and hold`).
- No write to `elevenyellow/nodocom` or `/Users/anis/Projects/nodocom`. `fagenorn`, `fagenorn/arcwave` and https://github.com/fagenorn/nix-config/issues/129 are out of scope (D3, D5).
- The contract is never read by a parser of the compiler's own and no resolved snapshot or contract body is written to any file, scratch included (D11, `.agents/instructions/bootstrap.md`).
- Unchanged: the guard's grammar for every verb, its protection demand and waiver, the release arm's rollup check, branch deletion, detaching words, the raise label (spec section 5); `tests/fixtures/forge-adapter-spellings.json`, `tests/fixtures/guarded-command-shapes.json`, `tests/forge_world.py`; the fleet registry schema.
- Prose that lands in code or documentation (docstrings, comments, error messages, README sentences) describes the code as it behaves at that task's commit. Where a task lists facts instead of a sentence, write the sentence from the implemented code. Messages a test pins are given verbatim. Use full issue URLs or the words "issue 126" in prose, never a bare `#126`.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python suites run as `env PYTHONPATH="$PWD/python" python3 -m unittest <test file> [-k <pattern>]` (timeout 900 s).
- `just build` (timeout 3600 s) evaluates the git tree, so `git add` every new file before it runs; its `./result` link is git-ignored. The guard suite runs against that build and is in no `just` recipe (spec `## Out of scope`). From Task 3 on its one invocation is (timeout 900 s):

  ```bash
  set -e
  just build
  REQ=$(nix-store --query --requisites ./result)
  CLAUDE_SETTINGS_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-code-settings\.json$') \
  CLAUDE_GUARD_BASE_POLICY_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$') \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4
  ```

  Before Task 3 the suite takes `CLAUDE_SETTINGS_PATH` alone and prints `Ran 51 tests` and `OK`.
- Final gate, once on the final head (sdd's, not per task): `just agent-workflow-tests` (timeout 3600 s), `just build` (timeout 3600 s) and the guard-suite invocation above, which must print `OK`.

## Test seams

Per D10 and D15; implementers test only at these.

- Compiler command: `python -m agent_tools.guard_policy compile` as a child process over `tests/guard_policy_world.py` (`tests/test_guard_policy.py`, added to `just agent-workflow-tests`).
- Below the release grammar (D15): `guard_policy.target_profiles` as an imported function on a hand-built snapshot, in the same suite.
- Guard command: the built wrapper named by the generated settings, with a fixture policy as a trailing `--policy` on every invocation (`tests/test_claude_permission_guard.py`).
- Round trip: one guard-suite test feeds a file the compiler seam wrote to the guard seam.
- Reuse seams (D13): `github_remote.github_slug`, `adopt_inspection.remote_heads` / `fetch_pinned` and `adopt_verify.remote_source` as imported functions, in `tests/test_forge_adapter.py` and `home/common/agent-skills/tests/test_adopt_verify.py`.
- Build: `just build` runs the wrapper's check against the base policy and the package's import check.

## Delivery estimate and boundaries

Estimates: 17 changed files — 6 production Python modules (2 new), 2 Nix files, the `justfile`, 1 new test support module, 1 new and 3 extended test modules, 2 READMEs and the spec ledger — about +450 production lines and +780 test lines, one review package. A prototype of this shape passed `just build`, the guard suite (59 tests) and `just agent-workflow-tests` at planning; it was not committed. Task 1 and Task 2 are each deliverable alone and change no behaviour of the guard: until Task 3 nothing calls the compiler. Task 3 is the security-bearing unit and cannot be split (Global Constraints). Aggregate-growth risks: `tests/test_claude_permission_guard.py` (about 1150 lines at base, about 1320 after) and `home/common/claude-code/lifecycle_guard.py` (about 1420 lines, about +40).

After the pull request merges nothing changes on the host until the next `just switch`. From that switch on the hook reads the compiled file, and a switch whose compile cannot reach `origin` or the provider leaves the affected project without a row until `claude-guard-policy` is rerun (spec section 4, D2, D4). That switch and the Nodo proof are outside this plan.

## Task index

Task 1 — Reuse seams: the shared slug rule, bounded network git children, the source's remote default — `python/agent_tools/github_remote.py`, `python/agent_tools/forge_adapter.py`, `python/agent_tools/adopt_inspection.py`, `python/agent_tools/adopt_verify.py`, `tests/test_forge_adapter.py`, `home/common/agent-skills/tests/test_adopt_verify.py` — full — [task-1.md](2026-10-12-issue-126-derived-guard-policy.tasks/task-1.md)
Task 2 — The `guard-policy` compiler, its command and its suite — `python/agent_tools/guard_policy.py`, `lib/agent-tools.nix`, `justfile`, `tests/guard_policy_world.py`, `tests/test_guard_policy.py`, `python/README.md` — full — [task-2.md](2026-10-12-issue-126-derived-guard-policy.tasks/task-2.md)
Task 3 — Atomic cutover: the guard reads derived rows, Nix builds the base policy and compiles at activation, Nodo's literals go — `home/common/claude-code/lifecycle_guard.py`, `home/common/claude-code/default.nix`, `tests/test_claude_permission_guard.py` — full — [task-3.md](2026-10-12-issue-126-derived-guard-policy.tasks/task-3.md)
Task 4 — Guard prose and the acceptance evidence — `home/common/claude-code/README.md` — full — [task-4.md](2026-10-12-issue-126-derived-guard-policy.tasks/task-4.md)

## Acceptance map

Criteria in issue order: the five of `## Acceptance criteria`, then the five of `### Additional acceptance criteria`. The issue's 2026-09-27 scope split moved AC1 and AC4–AC7 to https://github.com/fagenorn/nix-config/issues/210; their rows record that hand-over.

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence (classified) | Task 4 | Command `gh issue view 210 --repo fagenorn/nix-config --json state,stateReason`; conditions: read-only, final head; threshold: `CLOSED` and `COMPLETED`; acceptance-record row `AC1` |
| AC2 | code (classified) | Task 3 | `tests/test_claude_permission_guard.py`: `test_built_base_policy_holds_only_the_unregistered_literals` |
| AC3 | code (classified) | Task 3 | `tests/test_claude_permission_guard.py`: `test_a_compiled_policy_round_trips_through_the_guard` (PR against `dev`), `test_prefixed_merge_reaches_acceptance_on_the_integration_base` (its merge, on the derived-row fixture), `test_base_policy_alone_loads_and_authorizes_no_nodo_verb` (nothing but the derived row allows them) |
| AC4 | evidence (classified) | Task 4 | The AC1 command and threshold; acceptance-record row `AC4` |
| AC5 | evidence (classified) | Task 4 | The AC1 command and threshold; acceptance-record row `AC5` |
| AC6 | evidence (classified) | Task 4 | The AC1 command and threshold; acceptance-record row `AC6` |
| AC7 | evidence (classified) | Task 4 | The AC1 command and threshold; acceptance-record row `AC7` |
| AC8 | code (classified) | Task 2 | `tests/test_guard_policy.py`: `DerivationTest.test_a_nodo_shaped_and_a_single_branch_project_both_derive` |
| AC9 | human (classified) | Task 4 | Judgment: after this pull request merges, one `just switch` and one Nodo pull request into `dev` with its merge pass through the derived guard on the host. Made by the orchestrating session under the owner's 2026-10-11 decision 5; no task of this plan may run it, so the row stays `human_pending` and the issue is held as `needs-verification` |
| AC10 | evidence (classified) | Task 4 | Command `gh issue view <n> --repo fagenorn/nix-config --json state,stateReason` for `367` and `368`; conditions: read-only; threshold: both `CLOSED` and `COMPLETED`, and `git grep -c elevenyellow HEAD -- home/common/claude-code/default.nix` prints nothing (the recorded gap was fixed in Nodo's contract and the grammar, with no local Nodo row left behind); acceptance-record row `AC10` |

## Decisions

- One schema with two producers, and where the compiled file lives: D1. What the file may hold: D11.
- The proof and its sources — fetch at every compile, exact-repository rows, the provider check: D2, D3, D7. How the compiler reuses the branch rule, the pinned fetch and the slug rule: D9, refined by D13 (appended by this plan).
- Compile outcomes and the activation step that never aborts a switch: D4. The report's `cause`, the recorded platform version and when a literal row is withheld: D14 (appended by this plan).
- Derived/literal overlap: D5. No per-invocation recheck: D6. The live default-branch check: D8, with the unresolvable case and the activation ordering in D16 (appended by this plan).
- Test seams: D10, extended by D15 (appended by this plan).
- No glossary or ADR; the three terms are fixed in the guard README: D12.

---
