# Lifecycle Guard Extraction Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Move the Claude Code `PreToolUse` Bash lifecycle guard out of its Nix
`''` string into a standalone, standard-library-only
`home/common/claude-code/lifecycle_guard.py` that reads the Nix-owned values from a
store JSON policy, with behaviour unchanged
([#176](https://github.com/fagenorn/nix-config/issues/176)).

**Architecture:** The guard text is extracted verbatim (dedented) and changed only
by the spec's edits E1–E6 (Task 1). The Nix module writes `lifecycleGuardPolicy`
with `builtins.toJSON`. It turns `lifecycleGuard` into a three-line store wrapper
that unsets `NIX_PYTHON*` and execs `python3 -I <source> --policy <policy> "$@"`,
and whose `checkPhase` runs it once on a harmless payload (Task 1). Living
documents and the helper standards shard learn the new file (Task 2). The spec's
demonstration table closes the change (Task 3).

**Tech stack:** Python 3 stdlib (`argparse`, `json`, `unittest` subprocess round
trips), Nix/Home Manager (`pkgs.writeText`, `pkgs.writeTextFile` with
`checkPhase`), `just`, `jq`, Markdown.

Spec (source of truth, read it whole):
`.claude/specs/2026-09-24-issue-176-lifecycle-guard-extraction-design.md`, D1–D14.
Its parent `.claude/specs/2026-09-24-agent-tools-package-design.md` binds as
"parent D*n*" (parent D4, D9, D10, D16).

## Global Constraints

- The behaviour stays identical. Every existing case in
  `tests/test_claude_permission_guard.py`, the adversarial table included, passes
  with no existing line changed. The only test edit is one appended method (D9).
- `lifecycle_guard.py` is the base's built guard text, dedented, plus E1–E6 and
  nothing else. There is no reformatting, and no grammar, message or check-order
  change. Its mode is `100644`, it uses only the standard library, and it imports
  nothing from `agent_tools` (D12, parent D4).
- Nix values reach the guard only through the policy file: exactly five keys and
  no version field (D3). Nothing in the source is interpolated. The hook
  registration expression in `settings.hooks.PreToolUse` is not edited (D1).
- `authorizedOwners`, `integrationBases` and their comments stay byte-identical in
  `default.nix` (D6). Scope is the spec's Files table plus its Out of scope
  list. Leave `agent_tools`, the allow list, `justfile`, CI and any linter
  wiring alone.
- Flakes see tracked files only, so `git add` the new `.py` before the first
  `just build`. Never run `just switch`. CI's `Nix Eval` evaluates the Linux host,
  and that host cannot be evaluated on darwin, because an IFD needs a Linux
  builder.
- Captures and demonstrations live under
  `CAP="${TMPDIR:-/tmp}"; CAP="${CAP%/}/issue-176"` and are never committed. Task 1
  writes `base-sha`, `base-settings.json`, `base-guard.py` and
  `new-settings.json` there, and Task 3 reads them.
- The guard suite is not part of `just agent-workflow-tests`. It runs as
  `CLAUDE_SETTINGS_PATH="$CAP/<x>-settings.json" python3 tests/test_claude_permission_guard.py`.
  Summarize test output to the `FAIL:`/`ERROR:` ids plus the `Ran`/`OK`/`FAILED`
  lines, and summarize build output to its `error:` lines.
- Commits are conventional and SSH-signed. Never disable signing, and surface a
  signing failure. Each message ends with the attribution trailer lines the
  executing harness prescribes.

## Test seams

- **Seam 3, the guard's registered hook** (parent D9). This is the only
  committed seam. The built settings reach the suite through
  `CLAUDE_SETTINGS_PATH`, and the suite drives the registered command with its
  override flags. Planned counts: 36 tests at base, and 37 after Task 1.
- **Shown once, not committed.** Three demonstrations run once:
  - the removal variants, which show the new case goes red without `-I` or
    without the `unset` (Task 1);
  - the policy-defect table, run against the source by hand (Task 1, spec
    "Behaviour on policy defects");
  - the spec's demonstration table (Task 3).

## Delivery estimate and boundaries

These figures are estimates. Six files change:

- The new source is about 990 lines and 37 KB of moved text.
- `default.nix` loses about 940 lines and gains about 35.
- The test gains 18 lines, and the docs gain three sentences.

Git cannot detect a move out of a Nix string, so the raw diff is about 85 KB.
Review the extraction through the fidelity diff instead: `diff -u` of the base
built guard against the new file is about 9 KB in 12 hunks (Task 1, Step 9), and
`git blame -w -C -C` follows the history (D12). The growth risk is an edit
outside E1–E6. The planned removed-line list catches it. Tasks run in index
order.

## Task index

Task 1 — Extract the guard behind a store policy and wrapper — `home/common/claude-code/lifecycle_guard.py` (create), `home/common/claude-code/default.nix`, `tests/test_claude_permission_guard.py` — full — [task-1.md](2026-09-24-issue-176-lifecycle-guard-extraction.tasks/task-1.md)

Task 2 — Document the guard's source and govern it by the helper shard — `CLAUDE.md`, `docs/standards/README.md`, `docs/standards/agent-helpers.md` — full — [task-2.md](2026-09-24-issue-176-lifecycle-guard-extraction.tasks/task-2.md)

Task 3 — Demonstrate the acceptance table — no files (verification only; temporary edits reverted) — full — [task-3.md](2026-09-24-issue-176-lifecycle-guard-extraction.tasks/task-3.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| AC1: the source is its own file, and the Nix module holds no Python for it | 1 (move), 3 (demo) |
| AC2: no interpolation; an owner change touches only the store policy | 1 (policy, wrapper), 3 (demo) |
| Regression floor: the suite passes with no changed assertion, and the hook shape is unchanged | 1, 3 |
| Demo: `just show-claude-settings`, byte-compile, lint, suite against the built hook | 3 |
| Living documents and the standards shard | 2 (D10, D11, D14) |

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D12 from the
design phase. Planning added two rows:

- **D13** refines D8 and the Lints demonstration. The command is
  `ruff check --isolated --select E4,E7,E9,F`, run from a scratch `devenv.nix`
  (Tasks 1 and 3).
- **D14** refines D11. The shard sentence scopes rule 3 and records that the
  guard's tool paths are pinned by its policy (Task 2).

A planning probe ran every task's commands and edits, exactly as written, in a
scratch copy of `dbbc09a`, and every check passed:

- The darwin build passed, and the suite passed 37 of 37. At base the new case
  failed, and it failed again with `-I` or the `unset` removed.
- With `WORKFLOW_POLICY_SURFACE=source`, `just agent-workflow-tests` gave
  `Ran 1222 tests` and `OK (skipped=2)`.
- The fidelity diff removed exactly the 22 planned lines. The hooks matched base
  apart from store hashes, and the rest of the settings was identical.
- Adding an owner moved only the policy path.
- With a string owner, the build failed in `checkPhase` with `invalid policy`.
- The policy-defect table gave exit 2 for all ten defects.

---
