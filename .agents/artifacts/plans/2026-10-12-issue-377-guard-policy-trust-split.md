# Guard Policy Trust Split Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The lifecycle guard takes `authorized_owners`, `integration_bases`, `git_bin`, `gh_bin` and `jq_bin` only from the store-built base policy, and uses a derived row from the user-writable compiled policy only after a store-built row check re-derives that repository in the same invocation (https://github.com/fagenorn/nix-config/issues/377).

**Architecture:** `guard-policy` gains a `derive --repository <slug>` subcommand that re-derives one repository's row with the compiler's own proof. The policy splits into a five-member base policy (Nix store) and a two-member compiled policy (`~/.agents/state/guard/policy.json`); the guard loads the base on every call and the compiled policy only when it builds the repository context, where a bad compiled file contributes no row. Before relying on a row the guard runs the row check (a store script that execs `guard-policy derive`) in its own process group under a per-invocation deadline, and refuses unless the fresh row carries the same two branches.

**Tech stack:** Python 3 standard library (`agent_tools` under `python/`, the standalone `home/common/claude-code/lifecycle_guard.py`), `unittest`, Nix (home-manager module `home/common/claude-code/default.nix`), `git` and `gh` as child processes.

Spec: `.agents/artifacts/specs/2026-10-12-issue-377-guard-policy-trust-split-design.md` (requirements R1–R6, sections 1–7, `## Test seams`; its `## Decision ledger` rows D1–D12 are cited by ID; "issue 126 Dn" cites the ledger that spec names).

## Global Constraints

- Base: `69a1047920707528fc97729b57b705332a360d27` (`origin/main` at planning). Tasks land in index order; a later task assumes every earlier one (D11).
- `home/common/claude-code/lifecycle_guard.py` stays one standard-library file that imports nothing from `agent_tools`; it runs `git`, `gh` and `jq` by the absolute paths the base policy names (or a test override) and the row check by the absolute path `--derive-bin` names, and never executes a path read from the compiled policy (R1, `docs/standards/agent-helpers.md`).
- `python/agent_tools/guard_policy.py` stays a thin command module over importable functions (rule 2); strict JSON loads use `agent_tools.canonical` hooks (rule 4); tests drive it as `python -m agent_tools.guard_policy` (rule 5).
- Unchanged: the guard's verb grammar, protection demand and waiver, release arm, branch deletion, detaching words, raise label; `tests/fixtures/forge-adapter-spellings.json`, `tests/fixtures/guarded-command-shapes.json`; the fleet registry schema; the repositories an untampered host authorizes (R5). Every existing guard-suite test keeps its verdict; a test changes only where its policy fixture or a message the spec changes forces it.
- No test contacts GitHub or a network remote, reads the host's fleet registry or reads `~/.agents/state/guard/policy.json`. Nothing in this plan runs `claude-guard-policy`, the row check against the host, or `just switch`.
- Prose that lands in code or documentation describes the code as it behaves at that task's commit; where a task lists facts instead of a sentence, write the sentence from the implemented code. Messages a test pins are given verbatim in the task. Use full issue URLs or the words "issue 377", never a bare `#377`.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python suites run as `env PYTHONPATH="$PWD/python" python3 -m unittest <test file> [-k <pattern>]` (timeout 900 s). A `Run:` line piped into `tail` runs under `set -o pipefail`; judge it by the command's own exit status and the expected text.
- `just build` (timeout 3600 s) evaluates the git tree, so `git add` every new file first. The guard suite runs against that build and is in no `just` recipe. Its one invocation (timeout 1200 s), called **the guard-suite invocation** below:

  ```bash
  set -e -o pipefail
  just build
  REQ=$(nix-store --query --requisites ./result)
  CLAUDE_SETTINGS_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-code-settings\.json$') \
  CLAUDE_GUARD_BASE_POLICY_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$') \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4
  ```

- Final gate, once on the final head (sdd's, not per task): `just agent-workflow-tests` (timeout 3600 s), `just build` (timeout 3600 s) and the guard-suite invocation, which must print `OK`.

## Test seams

Per D8 and D10; implementers test only at these.

- Compiler command: `python -m agent_tools.guard_policy compile|derive` as a child process over `tests/guard_policy_world.py` (`tests/test_guard_policy.py`).
- Guard command: the built wrapper named by the generated settings, with a fixture base policy (`--base-policy`), a fixture compiled policy (`--policy`) and, from Task 3, a stub row check (`--derive-bin`) as trailing overrides on every invocation (`tests/test_claude_permission_guard.py`).
- Round trip (Task 3): one guard-suite test drives the built guard with a compiled policy written by `compile` and the real `derive` as its row check, over one `GuardPolicyWorld`.
- Build: `just build` runs the wrapper's check as registered.

## Delivery estimate and boundaries

Estimates: 10 changed files — 2 production Python files, 1 Nix file, 1 test-support and 2 test modules, 3 prose files and the spec ledger — about +230 production lines and +450 test lines, one review package. Aggregate-growth risks: `tests/test_claude_permission_guard.py` (1373 lines at base, about 1650 after) and `lifecycle_guard.py` (1480 lines, about +130). Task 1 is deliverable alone (additive). Tasks 2 and 3 are each security-bearing and independently reviewable (D11). Nothing changes on the host until a later `just switch`, outside this plan.

## Task index

Task 1 — `guard-policy derive`: re-derive one repository's row — `python/agent_tools/guard_policy.py`, `tests/guard_policy_world.py`, `tests/test_guard_policy.py`, `python/README.md` — full — [task-1.md](2026-10-12-issue-377-guard-policy-trust-split.tasks/task-1.md)
Task 2 — Trust split: five-member base, two-member compiled policy, the bad-file rule — `home/common/claude-code/lifecycle_guard.py`, `home/common/claude-code/default.nix`, `tests/test_claude_permission_guard.py`, `python/agent_tools/guard_policy.py`, `tests/guard_policy_world.py`, `tests/test_guard_policy.py`, `python/README.md` — full — [task-2.md](2026-10-12-issue-377-guard-policy-trust-split.tasks/task-2.md)
Task 3 — Row check at use under an invocation deadline — `home/common/claude-code/lifecycle_guard.py`, `home/common/claude-code/default.nix`, `tests/test_claude_permission_guard.py`, `tests/guard_policy_world.py` — full — [task-3.md](2026-10-12-issue-377-guard-policy-trust-split.tasks/task-3.md)
Task 4 — Guard prose: trust split, row check, residual — `home/common/claude-code/README.md`, `docs/standards/agent-helpers.md` — full — [task-4.md](2026-10-12-issue-377-guard-policy-trust-split.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 2 | `tests/test_claude_permission_guard.py`: `test_a_compiled_policy_cannot_add_an_owner` |
| AC2 | code (classified) | Task 2 | `tests/test_claude_permission_guard.py`: `test_a_compiled_policy_cannot_substitute_the_tools` |
| AC3 | code (classified) | Task 3 | `tests/test_claude_permission_guard.py`: `test_a_row_for_an_unregistered_repository_is_refused_at_use`, `test_a_compiled_policy_round_trips_through_the_guard` (its forged row) |
| AC4 | code (classified) | Task 3 | The whole guard suite through the guard-suite invocation (`OK`), including `test_built_base_policy_holds_exactly_the_five_trusted_members`, the Nodo verbs confirmed by the stub row check and the round trip's allowed Nodo PR |
| AC5 | human (classified) | Task 4 | Judgment by the Task 4 reviewer and the code reviewer: the rewritten `## Guard policy` of `home/common/claude-code/README.md` states every fact of spec section 7 and no longer lists issue 126 D17 as open |
| AC6 | evidence (classified) | Task 4 | Commands `just build` and `just agent-workflow-tests` (timeouts 3600 s), from the worktree root on the final head, clean tree; threshold: both exit 0; acceptance-record row `AC6`, filled from sdd's final gate run |

## Decisions

- Two closed schemas, the compiler's two-member output and five-member base: D1. The bad-file rule (compiled: no row; base: block every call): D4.
- The row check, its command and comparison: D2; network on every row-bound verb with no cache or lock: D3; its path as a wrapper argument: D7.
- Literal/derived overlap refused at use, literal never withheld: D5.
- Deadline and process group: D6; its test without an override flag: D10 (appended by this plan); refusal once the deadline leaves too little time for the next child, no 10 ms floor: D12 (appended by the standards review).
- Test seams: D8. Delivery order and the unchecked-row interval on the branch: D11 (appended by this plan).
- No glossary or ADR: D9.

## Standards review provenance

- Reviewer: Codex (codex-companion plan-review, model gpt-6-astra, reasoning effort xhigh), isolated read-only mode, no focus, no fallback.
- Base: `69a1047920707528fc97729b57b705332a360d27`.
- Disposition: accepted 4, rejected 0, deferred 0. Discussion: none.
  - B1 (blocking): the deadline's 10 ms floor let chained children run past it (R6). Applied in Task 3 per spec D12 (appended by this review).
  - S1: the tool-substitution test took the fake `gh` from `--gh-bin`. Applied in Task 2: it comes from a fixture base policy.
  - S2: the activation messages overstated what a missing compiled policy refuses (Task 2), and Task 4 called an estimated cost measured.
  - S3: Task 2 now names the `integrationBases` comment in `default.nix` and the `load_policy` sentence of `python/README.md` § guard-policy.

---
