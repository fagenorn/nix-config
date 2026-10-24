# Guard Refusal Forms Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The lifecycle guard accepts `gh pr merge … [--match-head-commit <sha>] …`, `ship-issue` spells that flag with the reviewed head, and every refusal of the five guarded operations that lies in the command's text names its problem and prints the accepted forms from the one form table the validators match against.

**Architecture:** All guard behaviour stays in `home/common/claude-code/lifecycle_guard.py`. A literal `FORM_TABLE` holds each operation's forms in a small template notation plus three properties; `main` compiles it first on every invocation, and one shared matcher replaces the per-verb parsers (Task 1). A refusal formatter appends `; accepted: …; optional prefix: …` to every text refusal, filling slots from the repository context (Task 2), and a problem namer replaces the generic grammar misses with the first problem that applies (Task 3). `ship-issue` then spells the new flag inside its instruction budget (Task 4).

**Tech stack:** Python 3 standard library (`shlex`, `re`, `collections.namedtuple`), `unittest` against the built guard at the process boundary, the JSON shape fixture shared with the shell-example suite, Markdown skill documents under the Instruction Budget gate, Nix (`just build`).

Spec: `.agents/artifacts/specs/2026-10-24-issue-402-guard-refusal-forms-design.md` (designed at `61304bde`; this plan appends ledger rows D15–D17). Its `## Decision ledger` rows are cited by ID. Issue: https://github.com/fagenorn/nix-config/issues/402.

## Global Constraints

- Base `ca3e4423` (`origin/main` at planning). Tasks land in index order, each on the one before it.
- The guard stays one standalone standard-library file that imports nothing from `agent_tools` (`docs/standards/agent-helpers.md`) and starts no new child process.
- No new module-level statement may raise: `FORM_TABLE` is a literal and everything derived from it is computed inside `main` or a function it calls (D14). A traceback outside the `__main__` handler exits 1, which Claude Code treats as non-blocking.
- Every refusal prints one line through `block` and exits 2. A refusal of the repository or forge state prints `lifecycle guard: unsafe <operation>: <problem>` exactly as at base, and the unlabelled lookup refusals (`PR lookup timed out`, `protection lookup failed: …`, …) keep their text (D3).
- Verdict invariant (D2): every command keeps base `ca3e4423`'s exit status except a merge carrying `--match-head-commit <sha>` in its place.
- Exactly one `UNSET_GITHUB_TOKEN_PREFIX = "unset GITHUB_TOKEN && "` assignment stays, alone on its line (the shell-example suite reads it with a line regex).
- Unchanged: `detaching_word`, the raise-label pass, `guarded_operations` and every recognition helper, `SCRUB_PREFIXES`, `Context`, `ownership_problem`, `authorized_bases`, the PR, protection and rollup lookups and their argv, the allow surface, `home/common/claude-code/default.nix`, `CLAUDE.md`, `AGENTS.md`, `.agents/instructions/`, `ship-release`, the forge adapter, `home/common/agent-skills/instruction-load.json`.
- Message vocabulary, exact: the operation label from `OPERATION_LABELS`; the clause `; accepted: <form>[; or <form>…]`; the prefix clause `; optional prefix: unset GITHUB_TOKEN && | env -u GITHUB_TOKEN`, never on branch deletion.
- Code comments, docstrings and README sentences describe the code as it behaves at that task's commit; write "issue 402", never a bare `#402`; no `TODO` or `FIXME` in committed code (the-bar).
- A closed-set dispatch on a form id (`"tag"`/`"branch"`, `"feature"`/`"release"`) ends in a branch that raises (the-bar Fail loud).
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root. Never run `just switch`.
- **Guard-suite invocation** (timeout 1200 s; 3600 s when the build is cold). `just build` evaluates the working tree's tracked files, so the suite runs the guard as edited; the suite is not part of `just agent-workflow-tests`:

  ```bash
  set -e -o pipefail
  just build
  REQ=$(nix-store --query --requisites ./result)
  CLAUDE_SETTINGS_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-code-settings\.json$') \
  CLAUDE_GUARD_BASE_POLICY_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$') \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4
  ```

  `-k <pattern>` after the test file focuses it (repeat `-k` for several).
- **Shell-example run** (timeout 600 s): `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | tail -4`.
- **Instruction Budget run** (timeout 600 s): `set -o pipefail; just agent-instruction-budget 2>&1 | tail -3`; the passing output ends `check: pass`.
- Final gate (sdd, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each), plus the guard-suite invocation and the Instruction Budget run, which neither recipe covers.

## Test seams

- The guard process boundary only (issue 400 D11): hook JSON in, exit status and stderr out, the guard run as registered from the built settings with the built base policy, the fake `gh` (`run_guard`), the fixture compiled policy (one row for `NODO`, `elevenyellow/nodocom`, `main`/`dev`) and the stub row check. No test imports or reads `lifecycle_guard.py`.
- Fixture repositories from `make_repo(origin, default_branch=…)` and `tagged_repo(slug, tag=…, annotated=…)`; PR facts from `FAKE_PR_JSON`, `RELEASE_PR` and `release_env(**overrides)`.
- `tests/fixtures/guarded-command-shapes.json` (D12): the guard suite reads `values`, `skill_forms`, `refused_shapes`, `invocation_shapes` and the new `form_values`; the shell-example suite reads `anchor`, `verbs`, `values`, `skill_forms` and `refused_shapes` only.
- `ship-issue` text: the shell-example suite (R1–R3), `home/common/agent-skills/tests/test_workflow_skill_contracts.py::WorkflowSkillContractsTest`'s merge-spelling pin, and its size through the Instruction Budget run.
- D14's negative case and the unreachable quoting step are checked by hand on scratch copies and leave nothing in the suite (D17).

## Delivery estimate and boundaries

Estimates only: eight changed files plus this plan and the spec ledger. `lifecycle_guard.py` about +330/−110 lines (2092 → about 2310); `tests/test_claude_permission_guard.py` about +330 (2098 → about 2430); the fixture about 20 changed lines; the README three sentence groups; three `ship-issue` documents (+211 bytes net, measured, D15); two strings in `test_workflow_skill_contracts.py`. One review package. If a package boundary demands a split, Task 1 with Task 4 (the flag and its spelling: AC1, AC4, AC5) and Tasks 2–3 (the messages: AC2, AC3) are independently deliverable slices.

## Task index

Task 1 — Form table, fail-closed compile and the shared matcher; the merge takes `--match-head-commit` — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `home/common/claude-code/README.md` — full — [task-1.md](2026-10-24-issue-402-guard-refusal-forms.tasks/task-1.md)
Task 2 — The accepted-forms clause on every text refusal; forms are true — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `tests/fixtures/guarded-command-shapes.json`, `home/common/claude-code/README.md` — full — [task-2.md](2026-10-24-issue-402-guard-refusal-forms.tasks/task-2.md)
Task 3 — Refusals name the first problem — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `tests/fixtures/guarded-command-shapes.json` — full — [task-3.md](2026-10-24-issue-402-guard-refusal-forms.tasks/task-3.md)
Task 4 — `ship-issue` merges with `--match-head-commit <reviewed HEAD_SHA>` — `tests/fixtures/guarded-command-shapes.json`, `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/ship-issue/CI-MERGE.md`, `home/common/agent-skills/skills/ship-issue/REMAINDER.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-4.md](2026-10-24-issue-402-guard-refusal-forms.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | Guard suite `test_merge_takes_an_optional_head_commit_flag`: the feature arm with the flag, with `--subject`, behind both scrub prefixes and into `dev`, and the release arm, each exit 0; 39- and 41-character, uppercase, attached, misplaced, valueless and doubled values each exit 2 `unsafe merge:`. |
| AC2 | code | Task 3 | Guard suite `test_the_retro_commands_name_their_problem_and_cure`: the #2342 command (Nodo row, fake PR `issue-2342-topic` into `dev`) prints exactly its `missing --delete-branch` line with the feature form and the filled form exits 0; `unset GITHUB_TOKEN; git push -q origin HEAD:issue-402-topic 2>&1 \| tail -2` prints exactly its forbidden-`>` line with both push forms; `test_refusals_name_the_first_problem` holds one row per named problem class, each with `; accepted: `. |
| AC3 | code | Task 2 | Guard suite `test_every_printed_form_is_allowed_where_printed`: each operation's whole table printed in the fixture repository, a Nodo-row repository and with no context, plus the AC2 refusals' forms, every `[…]` subset filled from `form_values`, run bare and behind each printed prefix, all exit 0; all five operations covered. |
| AC4 | code | Task 4 | Guard suite `test_every_guarded_command_shape_gets_its_verdict` (`merge.subject` and `merge.plain`, carrying `--match-head-commit <reviewed HEAD_SHA>`, exit 0 bare, `prefixed` and `env_prefixed`) and the shell-example suite's `test_every_guarded_command_is_a_cited_form` (R1 holds `SKILL.md`'s new spelling to the template), both green; the shell-example suite again under sdd's final `just agent-workflow-tests`. |
| AC5 | code | Task 4 | `just build`, run first by Task 4's guard-suite invocation on the final guard and skill tree (its check runs the registered guard, so a `FORM_TABLE` that does not compile fails it, D14), then by sdd's final gate on the final head. |

## Decisions

- Form table, notation and properties per D1; one shared matcher per D2, read per D16; compiled first on every invocation per D14 (Task 1).
- The merge flag's spelling-only check per D10 (Task 1).
- Which refusals carry the clause per D3; listed forms and arms per D6; fills per D7; the prefix clause per D8; `-C` outside the forms per D9 (Task 2).
- Problem precedence per D4, read per D16; forbidden characters per D5 (Task 3); the quoting step and the hand-checked compile failure per D17 (Tasks 1, 3).
- The shape fixture per D12; forms are true per D13 (Tasks 2–4).
- `ship-issue`'s spellings and side clauses per D11, their byte budget per D15 (Task 4).

---
