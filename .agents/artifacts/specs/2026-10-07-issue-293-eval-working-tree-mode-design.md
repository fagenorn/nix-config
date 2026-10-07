# Evals run working-tree skills, with a Sonnet/Opus baseline (#293)

Slice S3 of the [#291 program spec](2026-10-07-issue-291-skill-best-practices-design.md),
per #291 D7 and #291 D11. Rows here are issue-local (D1…); program rows are cited
as "#291 Dn".

## Problem

Slices S4–S8 slim the heavy skills, and S9 re-runs the evals against a baseline
to show nothing broke. Today that loop cannot run:

- The evals exercise the **deployed** skills. A user-level skill shadows a project
  copy of the same name, so the only way to evaluate an edit is `just switch`, which
  changes the live machine mid-run and races between parallel slices (#291 D7).
- Only `from-issue` has `pipeline` cases. `ship-issue`, `sdd`, `ship-release` and
  `orchestrate-issues` have plan-only cases, which a person grades by hand.
- The runner records wall time and a verdict, but no token counts, because
  `claude -p --output-format text` reports none.
- `results/` is gitignored, so a baseline recorded today lives only on the machine
  and in the worktree that ran it. S9 has nothing to compare against.

## Solution

1. **Working-tree mode.** `EVAL_TREE=<checkout>` makes `run-eval.sh` build a private
   Claude environment from that checkout for each invocation. No `just switch`.
   Unset, the runner behaves as today (deployed mode).
2. **Token capture.** Both modes run `claude -p --output-format json`. The final
   result text still lands in the transcript file the asserts grep, and each row
   gains token, cost and turn counts.
3. **Pipeline cases.** One new cheap-first `pipeline` case each for `ship-issue`,
   `sdd`, `ship-release` and `orchestrate-issues`, graded by scripted asserts in
   the existing tinytask sandbox.
4. **A committed baseline.** `results/results.jsonl` becomes a tracked file. The
   execution phase appends one row per pipeline case of the five skills on each of
   `sonnet` and `opus`, and commits them.

### Working-tree mode, in order

Each invocation with `EVAL_TREE` set does this once, before any trial:

1. **Validate the tree.** `EVAL_TREE` is normalized to an absolute physical path.
   It must contain both skill roots (`home/common/agent-skills/skills` and
   `home/common/claude-code/skills`), `home/common/agent-guidance/AGENTS.md`,
   `home/common/claude-code/agents/`, `python/agent_tools/` and `lib/agent-tools.nix`.
   If any is missing the runner dies (exit 2).
2. **Make one temp root** (`mktemp -d`, then physical path) holding `config/` (the
   `CLAUDE_CONFIG_DIR`) and `bin/` (the PATH shims). Register the cleanup trap
   (D3) immediately after `mktemp` succeeds, before anything is written into it.
3. **Populate `config/`:**
   - `skills/<name>/` is a real directory for every skill directory in both roots
     (the shared tree first, then the Claude-only tree, the same search order the
     runner uses for `evals.json`). Every regular file under the tree's copy,
     except `__pycache__` contents, is a symlink at the same relative path to the
     tree's file. That is the layout Home Manager's recursive links deploy, which
     Claude already discovers (D11). A name present in both roots dies, because
     deployment would collide on it too.
   - `CLAUDE.md` is a copy of the tree's `home/common/agent-guidance/AGENTS.md`.
   - `agents/` is a copy of the tree's `home/common/claude-code/agents/*.md`.
   - `settings.json` is a copy of the generated settings (D4), with `enabledPlugins`
     and `extraKnownMarketplaces` removed.
4. **Populate `bin/`.** One executable shim per row of the command table in the
   tree's `lib/agent-tools.nix` (D5). Each shim sets `PYTHONPATH` to `<tree>/python`
   and execs `python3 -P -m agent_tools.<module> "$@"`, the module being the
   command name with `-` replaced by `_` (the table's own rule). `bin/` goes first
   on `PATH` for the claude run and for the runner's own `resolve-project` call.
5. **Probe auth.** Run `CLAUDE_CONFIG_DIR=<config> claude auth status`. A non-zero
   exit dies with exit 2 and one message naming the one-time step: run
   `claude setup-token` and export the printed token as `CLAUDE_CODE_OAUTH_TOKEN`
   (D2). No sandbox is built and no row is written. The probe proves a credential
   is present, not that it is valid: `auth status` reports an env token as logged
   in without checking it, so a bad token shows up as a non-zero claude exit in
   the trial's row.
6. **Run trials** exactly as deployed mode does, with `CLAUDE_CONFIG_DIR` and the
   `PATH` prefix exported to the `claude` child. Skills and `evals.json` resolve
   from the tree's skill roots. The fixture, `assert-lib.sh` and `results/` stay
   the runner's own (D6).

### Result rows

Every row keeps today's fields, adds the fields below, and sets them to `null` where
they do not apply (a plan-only row, or a run with no parseable result object):

| Field | Value |
|---|---|
| `tree` | `"deployed"`, or the absolute `EVAL_TREE` path |
| `tree_rev` | `git -C <tree> rev-parse HEAD`; `null` in deployed mode |
| `tree_dirty` | whether `git status --porcelain` is non-empty for the instruction paths (both skill roots, the agents directory, `AGENTS.md`); `null` in deployed mode |
| `input_tokens` | sum over every `modelUsage` entry of `inputTokens + cacheReadInputTokens + cacheCreationInputTokens` |
| `uncached_input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_tokens` | the same sums, one component each |
| `cost_usd` | the result's `total_cost_usd` |
| `num_turns` | the result's `num_turns` |
| `models` | the `modelUsage` keys, sorted |

`input_tokens` counts every prompt-side token every model consumed, subagents
included (D1). The raw result object is kept as `result.json` in the sandbox, next
to the transcript.

### New pipeline cases

All four use the existing fixture: the tracker, review, release and deploy
capabilities are unsupported, and the integration branch is the default branch.
Three cases need a new setup kind (D7). Setup inputs live under
`evals/setups/issue-3/`, built from fixture issue 3 (rename `list --all` to
`list --include-done`): a design spec, an implementation plan, and the
implementation as a patch.

| Skill | Setup kind | Drives | Stops | Graded by (scripted asserts) |
|---|---|---|---|---|
| `ship-issue` | `shippable-worktree`: worktree `worktree-issue-3-rename-flag` from `origin/main` with the spec, the plan and the applied patch committed | `/ship-issue 3`, standalone, on the tracker-free route | After pushing the branch; no local merge | origin carries the branch at the worktree's `HEAD`; local and origin `main` unchanged; the worktree's git directory holds a `verified-tree.json` for that tree (Phase 2 ran); the fixture's tests pass in the worktree |
| `sdd` | `planned-worktree`: the same worktree with only the spec and the plan committed | `/sdd <plan>` | After the last task's review, before the final review | a commit on the branch touches `tinytask/`; `list --include-done` works and `list --all` is a usage error; the fixture's tests pass in the worktree; the SDD progress ledger records the task done; `main` unchanged |
| `ship-release` | `release-ready`: annotated `v0.1.0` on the initial commit, then a `feat:` branch merged into `main` with `--no-ff` and pushed | `/ship-release` on the single-branch, tracker-free route | After the local tag (Phase 4.5); no forge step | exactly one new annotated `v*` tag, newer than `v0.1.0`, pointing at `main`'s tip; origin carries no new tag (the tracker-free route skips the push); no durable release state file remains |
| `orchestrate-issues` | none | `/orchestrate-issues 1 3`, the prompt mapping issues 1 and 3 to their fixture files as open and unblocked | After the first `control` response is rendered; launch no agent | a run ledger under the fixture's `.superpowers/workflows/` covers issues 1 and 3; no worktree was created; no commit on `main`; the output names the dispatch for both issues |

Every case prompt carries the resolve-once sentence the existing cases use, and an
explicit stop. The `ship-release` case runs a real release, but only inside the
disposable sandbox. The R8 contract in `test_ship_release_contracts.py` (every
release eval stays plan-only) narrows to the property it protects: a plan-only case
keeps its non-execution guard, and a `pipeline` case must use the `release-ready`
setup (D8).

### Baseline procedure (execution phase)

1. Confirm that the instruction paths at the branch's `HEAD` equal `origin/main`'s
   (`git diff --quiet origin/main HEAD -- <instruction paths>`), so a run of this
   tree is a run of main's skills.
2. For each of `from-issue` 1–3 and the four new cases, on `EVAL_MODEL=sonnet` and
   on `EVAL_MODEL=opus`, run one trial (14 runs). Use working-tree mode when its
   auth probe passes. Otherwise use deployed mode, after confirming that each of the
   five deployed skill directories is byte-identical to the tree's copy, apart from
   `__pycache__` (D9).
3. A case that fails is recorded as it is, as a `FAIL` verdict. The baseline
   measures main; it is not a gate. A case that cannot run (a runner `die`) is fixed
   before the baseline is recorded.
4. Commit the appended `results/results.jsonl` rows.

## Decisions

- **Runner interface.** One new variable, `EVAL_TREE`; one optional override,
  `EVAL_SETTINGS` (D4). `just evals` already passes the environment through and runs
  from the repository root, so `EVAL_TREE=. just evals from-issue 1` works with no
  recipe change.
- **Modes share everything after setup.** The sandbox, setup hooks, asserts, verdict
  rules and row writer are unchanged code paths. Only the skill roots, `PATH` and
  `CLAUDE_CONFIG_DIR` differ.
- **What working-tree mode does not cover.** The legacy flat helpers
  (`workflow-state`, `artifact-budget`, `sdd-workspace`), `~/.agents/standards` and
  `~/.agents/share` still come from the deployed home. So do the absolute
  `~/.agents/bin/…` paths that some skills name, and the `impeccable` and plugin
  skills, which are omitted. None of these is in S4–S8's slimming scope. Helper
  changes are out of the program's scope (#291 Out of scope).
- **README.** The "Evals exercise the DEPLOYED skills" section is rewritten into
  a section on the two modes. It covers the auth step, the result fields, the
  committed results file, and a `jq` one-liner for comparing a skill's rows across
  revisions.

## Test seams

- **The runner as a black box** (AC1). A new bash test under
  `home/common/agent-skills/evals/tests/` copies the `evals/` directory to a temp
  dir and runs the copy, so rows land in the copy's `results/`. It sets
  `EVAL_TREE` to the repository root and `EVAL_SETTINGS` to a fixture file, and puts
  a fake `claude` first on `PATH`. The fake answers `auth status` with an exit code
  the test chooses. On `-p` it records what it sees: the config directory listing,
  every `skills/*` link target, the bytes of `CLAUDE.md` and `agents/*.md`, the
  settings keys, and `command -v resolve-project`. It checks every link target
  under `skills/` against the tree, so the test covers every skill. It then prints a canned result
  object. The test asserts on what the fake recorded and on whether the temp root
  still exists after the run. It covers four exit paths: the claude run exits 0;
  the claude run exits non-zero; the auth probe refuses (exit 2, the message names
  `claude setup-token`, no row, no sandbox); and SIGTERM to the runner during the
  claude run. The temp root must be gone on all four. The prior art is the
  fake-binary-on-PATH style of the lifecycle guard tests. `just agent-workflow-tests`
  runs it after the unittest list.
- **The case files as data** (AC2). A new unittest module reads every `evals.json`
  in both skill roots. It asserts that each of `from-issue`, `ship-issue`, `sdd`,
  `ship-release` and `orchestrate-issues` has at least one `"mode": "pipeline"` case
  with a prompt and at least one assert. It asserts that every setup kind a case
  names is an arm of the runner's setup dispatch. It asserts that the
  `setups/issue-3/` spec and plan pass `artifact-budget check` for their kinds under
  the tree's policy file. The prior art is `test_ship_release_contracts.py`'s evals
  reads.
- **The row writer** is covered by the bash test: a row from the fake run carries
  the canned token sums and `tree`/`tree_rev`.
- No test runs a real model. The evidence AC is graded from the committed rows.

## Acceptance criteria

| AC | Kind | Criterion | Verified by |
|---|---|---|---|
| AC1 | code | Working-tree mode builds the temp config dir with skills linked to the checkout, settings, `CLAUDE.md` and agents present, and removes it on every exit path | The bash test under `home/common/agent-skills/evals/tests/` passes inside `just agent-workflow-tests`, covering the four exit paths above |
| AC2 | code | `ship-issue`, `sdd`, `ship-release`, `orchestrate-issues` each have ≥1 `"mode": "pipeline"` case | The case-count unittest passes inside `just agent-workflow-tests` |
| AC3 | evidence | The baseline is recorded | `jq` over the committed `home/common/agent-skills/evals/results/results.jsonl` finds, for each of the five skills × {`sonnet`, `opus`}, ≥1 row with `ts >= "2026-10-07"`, `mode == "pipeline"`, a non-null `verdict`, a numeric `wall_s` and a numeric `input_tokens` (D10) |
| AC4 | human | If credentials cannot carry over, the user runs `claude setup-token` once | The user, on mbp, runs it and exports `CLAUDE_CODE_OAUTH_TOKEN`. After that, `EVAL_TREE=. just evals from-issue 1` passes the auth probe. The issue's demo then holds: an uncommitted marker line added to the working-tree `from-issue/SKILL.md` shows up in that run's transcript, and the edit is then reverted. Credentials do not carry over today (a fresh config dir reports `loggedIn: false`), so this step is due |

## Out of scope

- Slimming or otherwise changing any skill (S4–S8), and any change to a helper's
  behaviour.
- Running evals in CI. The bash test uses a fake `claude`, and no CI job spends
  model tokens.
- Building the settings from the tree with Nix inside the runner.
- Working-tree copies of the legacy flat helpers, the standards or the shared data
  files.
- Converting the existing plan-only cases to pipeline cases. Each skill gains one
  new pipeline case, and its plan-only cases stay.
- More than one trial per (case, model) in the baseline. `EVAL_TRIALS` already
  exists for S9 to add repeats.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Switch to `--output-format json`, keep the transcript file as the result's `.result` text, and define `input_tokens` as the sum of the uncached, cache-read and cache-creation input counts over every `modelUsage` entry, recording the components, `output_tokens`, `cost_usd`, `num_turns` and `models` beside it | Measured: the result object carries per-model `modelUsage` with these counts; text mode already printed only the final message, so asserts see the same bytes | `stream-json`: changes what `out_matches` greps. Top-level `usage` only: misses subagents and other models |
| D2 | No credential copying. The only carry-over is whatever `claude auth status` accepts in the fresh dir, which is in practice `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`) from the environment. A refused probe exits 2 before any spend, naming `claude setup-token` | Measured: a fresh `CLAUDE_CONFIG_DIR` reports `loggedIn: false`, and keychain entries are per config dir. The Bar: fail loud, truthful terminal states | Copying `.credentials.json` or keychain items into a temp dir: spreads a secret, and is stale on macOS anyway. Writing a `FAIL` row for an auth refusal: a broken setup posing as a skill result |
| D3 | One temp root holds `config/` and `bin/`. An `EXIT` trap removes it, and `INT` and `TERM` traps exit 130 and 143 so that the `EXIT` trap runs. Bash runs a signal trap only once the foreground claude pipeline returns, and the runner does not kill that child itself: a terminal Ctrl-C already reaches the whole process group. Sandboxes (`eval-*`) are still kept for inspection | AC1 "every exit path"; README: sandboxes are kept on purpose | Removing the root at the end of the script: a `die` or a signal leaks it, and the root can hold session state |
| D4 | Settings come from `EVAL_SETTINGS`, by default `~/.claude/settings.json` (the generated settings, as last materialized), minus `enabledPlugins` and `extraKnownMarketplaces`. A missing file dies | Settings are not in S4–S8's scope; the deployed file is the generator's output; plugins reference marketplaces the temp dir lacks and no eval uses them | A Nix build of the tree's settings per run: minutes per invocation for a file the slices do not touch. Keeping the plugin keys: triggers marketplace installs from inside the sandbox |
| D5 | Shims cover exactly the command-table rows, read from the tree's `lib/agent-tools.nix` `commands` list, as `PYTHONPATH=<tree>/python python3 -P -m agent_tools.<module>` | #291 D7 names the `agent_tools` commands; agent-helpers rule 3 (`-m`) and rule 5 (the recipes' `PYTHONPATH`); `-P` keeps the sandbox cwd from shadowing the package; the table is the single home for the command set (DRY) | Shimming the flat helpers too: they default to `~/.agents/share` policy and installed paths, so a shim would need a layout shim (YAGNI). Hard-coding the command list: a second copy |
| D6 | In tree mode, the skill roots and `evals.json` come from `EVAL_TREE`, while the fixture, `assert-lib.sh` and `results/` stay the runner's own | Lets the bash test run a copied runner against the real tree without touching the committed results file; when `EVAL_TREE=.` names the runner's own checkout, both are the same | An `EVAL_RESULTS` override: a knob that exists only for the test |
| D7 | Three new closed setup kinds (`shippable-worktree`, `planned-worktree`, `release-ready`), fed by committed inputs under `evals/setups/issue-3/`; the fixture repo itself is unchanged | Runner's closed `case` dispatch dies on an unknown kind (the Bar: fail loud); README: other evals must leave the fixture untouched | Generating the spec and plan inside the case prompt: grades the drafting, not the skill under test. Adding the artifacts to `fixture-repo/`: every other eval would see them |
| D8 | The ship-release pipeline case performs the release inside the sandbox, through the local tag, and R8 narrows from "all plan-only" to "plan-only cases keep their guard; a pipeline case uses `release-ready`" | The sandbox's bare origin is disposable; the tracker-free route is the fixture's documented shape (ship-release eval 4); #291 D6 lets a test that pins wording rather than behaviour change | Stopping after Phase 1: grades only the changelog, which plan-only eval 4 already covers |
| D9 | The baseline runs one trial per (case, model). It prefers working-tree mode. Before the [human] step it falls back to deployed mode, after a byte-identity check of the five deployed skill directories against the tree | The evidence AC must stay achievable without the human step; deployed equals `origin/main` at `f0e47f5c` (orchestrator measurement); cost of 14 runs vs more | Blocking the baseline on `setup-token`: the evidence AC would depend on the human one. Three trials each: triples spend before S9 has asked for variance |
| D10 | `results/results.jsonl` becomes a tracked, append-only file, and the rest of `results/` stays ignored. AC3's "dated after 2026-10-07" is graded as `ts >= "2026-10-07"`: the program's measurement date, and no earlier row carries `input_tokens` | S9 must compare against the baseline, which an ignored file cannot carry across worktrees; the issue names this path | A separate committed `baseline.jsonl`: a second results home, and the AC names `results.jsonl`. Strict `> 2026-10-08`: would force the baseline into tomorrow for no information gain |
| D11 | Mirror Home Manager's recursive layout (a real directory per skill, per-file symlinks) rather than one directory symlink per skill (grill) | Deployed `~/.claude/skills/<name>/` are real directories of file symlinks, which is the layout Claude is known to discover; per-file links still show an edit to the working-tree file | Directory symlinks: whether Claude discovers a symlinked skill directory is unverified, and a silent miss would fall back to no skill at all |
