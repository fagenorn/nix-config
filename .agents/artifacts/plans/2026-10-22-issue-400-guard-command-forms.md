# Guard Command Forms Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The lifecycle guard adjudicates a guarded `git`/`gh` verb wherever the program would actually run it, and accepts exactly two harmless invocation forms: a credential-scrub prefix and `git -C <dir>`, the latter judged against the repository it targets.

**Architecture:** All behaviour lives in `home/common/claude-code/lifecycle_guard.py`. The verb pass steps over wrapper option arguments; raw-text sites match a verb's words in order; a per-word recognizer reads `git` global options and `gh` flags and refuses unaccepted forms before any lookup; `main` derives each verb's canonical text in one function and builds one repository context per target directory. Every grammar judges the canonical text unchanged.

**Tech stack:** Python 3 standard library (the guard), `unittest` against the built guard (`tests/test_claude_permission_guard.py`), the JSON shape fixture shared with `home/common/agent-skills/tests/test_shell_example_contracts.py`, Nix (`just build`).

Spec: `.agents/artifacts/specs/2026-10-22-issue-400-guard-command-forms-design.md`; its `## Decision ledger` rows are cited by ID. Issue: https://github.com/fagenorn/nix-config/issues/400.

## Global Constraints

- Base `336d9e05` (`origin/main` at planning); spec commit `64337002`. Tasks land in index order, each on the one before it.
- The guard stays one standalone standard-library file that imports nothing from `agent_tools` (`docs/standards/agent-helpers.md`) and runs `git`, `gh` and `jq` only by its base-policy paths. This change starts no new child process: recognition and stripping are text work, and per-directory contexts reuse the existing lookups.
- Every refusal goes through `block` (exit 2). No new module-level statement may raise: the guard runs as a script, and a traceback outside the `__main__` handler exits 1, which Claude Code treats as a non-blocking error.
- Exactly one `UNSET_GITHUB_TOKEN_PREFIX = "unset GITHUB_TOKEN && "` assignment stays, alone on its line (D9): the shell-example suite reads it with a line regex and fails on zero or two.
- Unchanged: the logic of `detaching_word` and `detaching_command_flags`, the raise-label pass, every grammar's accepted argv, the allow surface (`EXPECTED_ALLOW`, `home/common/claude-code/default.nix`), `home/common/agent-skills/tests/test_shell_example_contracts.py`, the ship-issue skill, `CLAUDE.md`, `AGENTS.md`, `.agents/instructions/`.
- Code comments, docstrings and README sentences describe the code as it behaves at that task's commit. Write "issue 400", never a bare `#400`.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root. Never run `just switch`.
- **The guard-suite invocation** (timeout 1200 s; 3600 s when the build is cold). `just build` evaluates the tracked files of the working tree, so the suite runs the guard as edited; it is not part of `just agent-workflow-tests`:

  ```bash
  set -e -o pipefail
  just build
  REQ=$(nix-store --query --requisites ./result)
  CLAUDE_SETTINGS_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-code-settings\.json$') \
  CLAUDE_GUARD_BASE_POLICY_PATH=$(printf '%s\n' "$REQ" | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$') \
  PYTHONPATH="$PWD/python" python3 -m unittest tests/test_claude_permission_guard.py 2>&1 | tail -4
  ```

  `-k <pattern>` after the test file focuses it (repeat `-k` for several).
- **The shell-example run** (timeout 600 s): `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | tail -4`.
- Final gate (sdd, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each). Task 4 runs the full guard-suite invocation on the final code.

## Test seams

- The guard process boundary only (D11): hook JSON on stdin, exit status and stderr out, the guard run as registered from the built settings with the built base policy, the fake `gh` (`run_guard`), the fixture compiled policy and the stub row check. No test imports `lifecycle_guard.py`.
- Fixture repositories from `make_repo(origin, default_branch=…)` and `tagged_repo(slug)`.
- `tests/fixtures/guarded-command-shapes.json` (D10): the guard suite reads `skill_forms`, `refused_shapes` and the new `invocation_shapes`; the shell-example suite reads `skill_forms` and `refused_shapes` only.

## Delivery estimate and boundaries

Estimates: four changed files plus this plan and the spec ledger. `lifecycle_guard.py` about +270 net lines (1726 → about 2000), `tests/test_claude_permission_guard.py` about +190 (1856 → about 2045), the fixture about +40, the README five sentence edits. One review package. If a package boundary demands it, Tasks 1–2 and Tasks 3–4 are independently deliverable slices. Planning dry-ran every task's tests red at its starting state and green after a staged implementation, the guard run from source in a scratch wrapper with the built base policy; the full suite was green at each stage except `test_registered_hook_names_the_base_policy_compiled_policy_and_row_check`, which reads the registered store wrapper and so cannot pass against a scratch one.

## Task index

Task 1 — Wrapper option arguments and the credential-scrub prefix — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `tests/fixtures/guarded-command-shapes.json`, `home/common/claude-code/README.md` — full — [task-1.md](2026-10-22-issue-400-guard-command-forms.tasks/task-1.md)
Task 2 — Raw-text sites: verb words in order, `env -S` segments, evaluators by basename — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `tests/fixtures/guarded-command-shapes.json`, `home/common/claude-code/README.md` — full — [task-2.md](2026-10-22-issue-400-guard-command-forms.tasks/task-2.md)
Task 3 — git and gh invocation recognition — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `tests/fixtures/guarded-command-shapes.json`, `home/common/claude-code/README.md` — full — [task-3.md](2026-10-22-issue-400-guard-command-forms.tasks/task-3.md)
Task 4 — `git -C <dir>` judged against its target repository — `home/common/claude-code/lifecycle_guard.py`, `tests/test_claude_permission_guard.py`, `tests/fixtures/guarded-command-shapes.json`, `home/common/claude-code/README.md` — full — [task-4.md](2026-10-22-issue-400-guard-command-forms.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | Guard suite `test_credential_scrub_prefix_forms_and_wrapper_near_misses`: every AC1 command, allowed and refused, run through the guard as registered. |
| AC2 | code | Task 4 | Guard suite `test_git_dash_c_is_judged_against_its_target_repository`: two fixture repositories, the payload `cwd` in one and `-C` naming the other. |
| AC3 | code | Task 3 | Guard suite `test_every_invocation_shape_gets_its_verdict` over the fixture's `invocation_shapes`: `git -c`, `git --git-dir=`, path-qualified `git` and `gh`, `gh --repo X pr merge`, `gh pr --repo X merge` (Task 3 rows) and `env -S`/`--split-string` payloads (Task 2 rows), each exit 2. |
| AC4 | code | Task 1 | Guard suite `test_every_guarded_command_shape_gets_its_verdict` (the env-wrapper rows now `env_prefixed` verdicts, exit 0 for both push and both merge forms) and the shell-example run, both green; the shell-example suite again in sdd's final `just agent-workflow-tests`, and the guard suite in Task 4's full run (D11: it needs the build and is outside that recipe). |
| AC5 | code | Task 4 | `just build`: inside every guard-suite invocation, and in sdd's final gate on the final head. |

## Decisions

- Scrub prefix spellings per D1, none on branch deletion per D2, the literal kept per D9.
- Recognition: git per D3, gh per D4, recognition refusals per D6; raw-text matching per D5 and D12.
- `-C` spelling and resolution per D7; one context per target directory per D8.
- Fixture per D10; the one test seam per D11.
- One home for canonical text per D13; residual forms left to a follow-up per D14.

---
