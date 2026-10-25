# Skill evals

Measurement harness for the skills in `../skills/` (shared tree) and
`../../claude-code/skills/` (Claude-only tree — `codex-collaboration`,
`orchestrate-issues`). Each skill keeps its cases in
`<skill-root>/<skill>/evals/evals.json`; everything here is the shared machinery.
The runner searches the shared tree first, then the Claude-only tree.

```sh
just evals from-issue 3      # pipeline eval: sandbox, run, grade, verdict
just evals ship-issue 1      # plan-only eval: prints prompt + expected output
EVAL_MODEL=opus just evals from-issue 1
EVAL_TRIALS=5 just evals from-issue 1   # repeat 5x: pass rate + p50/p90 wall time
```

## Two kinds of eval

**`"mode": "pipeline"`** — `run-eval.sh` copies `fixture-repo/` into a temp dir, gives it
a git history and a bare `origin`, runs an optional `setup` hook, invokes `claude -p` with
the eval's prompt, then runs the eval's `asserts` (shell snippets with `assert-lib.sh`
sourced) and prints PASS/FAIL per assert plus a verdict. Non-zero exit on failure.

**`"mode": "plan-only"`** (the default when `mode` is absent, which is why `ship-release`'s
existing file still works) — the runner prints the prompt and the `expected_output`. Grade
by pasting the prompt into a session and reading the transcript against it.

## Two modes: deployed and working tree

**Deployed (the default).** The sandboxed `claude -p` reads skills from
`~/.claude/skills` — the store links from the last `just switch`, not this working tree
(under the default setting sources, user-level skills shadow project-level copies of the
same name). Editing a skill therefore means: commit, `just switch`, then run the eval. A
failed parity run is one `git revert` + re-switch away from the previous behavior. The
row records `tree: "deployed"` with `tree_rev`, `tree_dirty` and `tree_mode` null.

**Working tree.** `EVAL_TREE=. just evals from-issue 1` evaluates a checkout without a
switch, under your normal login: the runner never sets `CLAUDE_CONFIG_DIR`. It resolves
the eval from that checkout's two skill roots, then, for a pipeline eval, makes the
checkout's instructions the sandbox repo's project copies. Right after the fixture's
initial commit it creates, inside the sandbox repo:

- `.claude/skills/<name>`, a symlink to each skill directory of both skill roots (a name
  in both roots is an error);
- `.claude/agents/<file>`, a symlink to each of the checkout's
  `home/common/claude-code/agents/*.md`;
- `.claude/CLAUDE.md`, a symlink to the checkout's `home/common/agent-guidance/AGENTS.md`,
  loaded as project memory beside the fixture's own root `CLAUDE.md`, which is unchanged.

Those three paths, and only those, are listed in the sandbox's `.git/info/exclude`, so
they never show in `git status` and the agent under test cannot commit them; the
fixture's tracked `.claude/` content and the specs, plans and maps an eval writes there
stay visible to git.

The run adds `--setting-sources project,local`, which drops the user-level sources —
so `~/.claude/skills`, `~/.claude/agents` and `~/.claude/CLAUDE.md` no longer shadow the
project copies — and `--settings "$TREE_ROOT/settings.json"`, which brings the user's
generated settings back by flag, so its hooks (the lifecycle guard), permissions, env and
enabled plugins still apply. That file is derived from `EVAL_SETTINGS` (default
`$HOME/.claude/settings.json`, read only in tree mode): a copy in which every hook object
of type `command` whose command ends in `-agent-tools-context-meter`, under any event and
any matcher, runs the tree's `context-meter` shim instead of the store-path meter. Nothing
else in the file changes. A missing or non-JSON file is an error before any sandbox, and so
is a file with no such hook (`settings file has no context-meter hook`). The one
limit: user-level settings and memory are replaced, not merged — the run sees the
flag-passed settings file and the project copies above, and nothing else from
`~/.claude` (user-level skills outside the checkout, such as `impeccable`, are not
loaded).

The runner also builds a temporary root `${TMPDIR:-/tmp}/run-eval-tree.XXXXXX` whose
`bin/` goes first on `PATH`: one shim per command in the tree's `lib/agent-tools.nix`
table, each running `python3 -P -m agent_tools.<module>` from the tree's `python/`, so
`resolve-project`, `context-meter` and the rest of the package commands are the tree's
code, not the installed ones. `bin/workflow-state` is one more shim, running the tree's
`home/common/agent-skills/scripts/workflow-state.py`, and the root also holds the derived
`settings.json` above. That root is removed on every exit path: a normal end, an error, a
non-zero claude exit, Ctrl-C (exit 130) and SIGTERM (exit 143). A plan-only eval creates
none of it. The sandbox, with its `.claude/` links, is kept like any other.

Tree mode does not cover the remaining flat helpers (`artifact-budget`, `sdd-workspace`),
`~/.agents/standards` and `~/.agents/share`: those still come from the deployed home. A
skill that calls `workflow-state` by name reaches the tree's shim, but an absolute
`~/.agents/bin/workflow-state` call still reaches the deployed helper, as do the other
absolute `~/.agents/bin/...` paths some skills name. Changes to those helpers are outside
what this mode measures.

`EVAL_POLICY=threshold=140000` sets a hand-off policy for the run. It is tree mode only
(`EVAL_POLICY requires EVAL_TREE` otherwise) and takes the product knobs of
`agent_tools.phase_budget`; the runner validates it with `phase_budget.parse` before any
sandbox, so a spec the package rejects dies as `invalid EVAL_POLICY '<value>': <reason>`.
It is exported as `AGENT_PHASE_BUDGET` to the claude run only, and the row records it as
`policy`. The claude run carries `AGENT_PHASE_BUDGET` exactly when `EVAL_POLICY` is set: with
it unset, an `AGENT_PHASE_BUDGET` inherited from the launching shell is removed.

A row from tree mode records `tree` (the checkout's absolute path), `tree_rev` (its
`HEAD`), `tree_mode` (`"project-skills"`, the layout above) and `tree_dirty` (whether `git status --porcelain` shows changes under the
instruction paths: both skill roots, `home/common/claude-code/agents` and
`home/common/agent-guidance/AGENTS.md`, ignoring each skill's own `evals/`).

## Cheap-first

The `from-issue` pipeline cases stop the flow after Phase 5 and grade the artifacts — spec,
plan, worktree placement, decision logs. The implementation never runs. A full end-to-end
run costs an order of magnitude more and is reserved for risky landings. A pipeline case
of another skill names its own stop in its prompt.

## Eval 8: lifecycle-owner economics

`from-issue` eval 8, `lifecycle-owner-economics`, is the one full-flow case. It runs
`/from-issue 4 --auto` (the direct route, so the owner has lifecycle identity) on a seeded
issue, `fixture-repo/issues/004-priorities-and-due-dates.md`: one feature across the model,
store, CLI and docs, whose last criterion needs `tests/test_acceptance.py` to pass. That
test takes about 330 s and is skipped unless `TINYTASK_ACCEPTANCE=1`, so it gives the owner
a long child wait and the ordinary suite stays fast. The case takes no parameters, and its
prompt names no phase to stop at: the run ends when ship-issue stops at the forge boundary.

Its setup kind, `tracked-issue`, runs `setups/tracked-issue/setup.sh <WORK> <REPO>`:

- It writes `$WORK/bin/gh`, a wrapper around `setups/tracked-issue/gh.py`, a read-only
  stand-in for `gh`. `run-eval.sh` puts `$WORK/bin` first on the claude run's `PATH`, so
  every agent of the run inherits it, and every call is appended to `$WORK/gh-calls.jsonl`
  as `{"argv": [...], "exit": n}`.
- The shim serves `issue view` for the issue files under `issues/` (as text, or as
  `--json <fields>` with an optional `--jq`, always open with no labels or comments),
  answers `[]` to `pr list` and to the `api` sub-issue and dependency reads, reports no pull
  request for `pr view`, and succeeds on `auth status`, `issue comment` and `issue edit`.
  Every other verb, `pr create` and `pr merge` included, exits 1 with
  `gh shim: <verb> is not available in this sandbox`.
- It rewrites the sandbox's `.agents/project.json` so the tracker binding is `github` and
  its capability is supported, then commits and pushes that on the sandbox's `main`.

The asserts read the owner report of the trial's transcripts (`owner_report` in
`assert-lib.sh` copies the project directories of the sandbox path to `$WORK/projects`
and runs the tree's `agent_tools.agent_costs --report owners --format json`), so eval 8
needs `EVAL_TREE`; without it the asserts fail with `eval 8 needs EVAL_TREE (tree mode)`.
The first five check issue 4's lineages (a ledger phase of at least 6, every owner gate
call measured, an owner call of at least 110,000 tokens of context, Phase 7 entered and an
owner long child wait); the sixth checks the feature branch's suite and `--priority`.

```sh
EVAL_MODEL=opus EVAL_TIMEOUT=7200 EVAL_MAX_USD=40 EVAL_TRIALS=2 EVAL_TREE=. \
  EVAL_SETTINGS=<settings> [EVAL_POLICY=<spec>] just evals from-issue 8
```

A trial is bounded by `EVAL_MAX_USD` (a trial costs tens of dollars and takes up to two
hours), so two trials can cost twice that. Compare arms from the rows with
`just agent-costs --report owners --eval-results results/results.jsonl --eval from-issue:8`.

## Conventions

- `"expected_today": "fail"` plus a `note` marks a case that documents a gap not yet closed.
  The runner reports `EXPECTED-FAIL` and exits 0; if it passes anyway you get
  `UNEXPECTED-PASS` telling you to drop the flag.
- `fixture-repo/` is `tinytask`, a stdlib-only python3 CLI with docs, an ADR, a
  complete `.agents/project.json` contract, and four issue fixtures under `issues/` (well-specified,
  fuzzy, mechanical, and eval 8's priorities and due dates, with its slow `tests/test_acceptance.py`). It also ships one pre-charted decision map,
  `.claude/wayfind/concurrent-shells/` — the markdown-tracker shape `wayfind` falls back to
  when its tracker capability is unsupported: a map, an unblocked ticket, a ticket blocked by it, and
  fog. The wayfind evals work it; every other eval must leave it untouched. Verify the fixture
  with `python3 -m unittest discover` from its root.
- A pipeline case's `setup.kind` is one of five closed kinds: `dirty-worktree`,
  `shippable-worktree`, `planned-worktree`, `release-ready` and `tracked-issue`. The
  middle three take no parameters and read their inputs (the issue-3 spec, plan package and
  `implementation.patch`) from the committed `setups/issue-3/`; `tracked-issue` takes none
  either and is described under Eval 8 above; `fixture-repo/` itself
  stays unchanged. Every pipeline assert also sees `BASE_MAIN`, local `main`'s SHA right
  after the setup.
- Env: `EVAL_MODEL` (default `sonnet`), `EVAL_TIMEOUT` seconds (default 2700),
  `EVAL_MAX_USD` (optional ceiling), `EVAL_TRIALS` (default 1), `EVAL_TREE` (a checkout
  to evaluate instead of the deployed skills), `EVAL_SETTINGS` (the settings file tree mode
  derives its `--settings` from; default `$HOME/.claude/settings.json`) and `EVAL_POLICY`
  (a phase-budget spec, tree mode only), all described above.
- Every pipeline run keeps its session: the runner passes no `--no-session-persistence` and
  starts `claude` with `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1`, because Claude Code writes
  no transcript for a `-p` run started inside a Claude Code session without it, and the
  context meter and `agent-costs` read transcripts. The sandbox's transcripts land in the
  login's projects directory, `~/.claude/projects/`, under the sandbox path's project name
  (every non-alphanumeric character of the path replaced by `-`), so `agent-costs` counts
  eval spend. The run also gets `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`, so `-p` waits for
  its background agents instead of stopping them 10 minutes after the last turn;
  `EVAL_TIMEOUT` still bounds it.
- Sandboxes are kept after the run and their path is printed, so you can inspect the spec
  and plan a failing assert complained about. Clean up with `rm -rf $TMPDIR/eval-*`.
- Asserts may carry a `"contract": "..."` key documenting a target artifact contract
  (e.g. the compact decision-ledger row shape) the assert depends on; the runner ignores
  it, integration re-verifies it when the contract lands.

## Results persistence

Every run appends one JSON line per trial to `results/results.jsonl`, which is committed
and append-only (the rest of `results/` is gitignored). Fields: timestamp, skill, eval
id/name, mode, model (the root session's `EVAL_MODEL`; the models subagents used show
under `models`), trial number, verdict, per-assert pass/fail, wall seconds, claude
exit code, sandbox path, the `EVAL_MAX_USD` ceiling when one was set, the tree fields
above, `policy` (the `EVAL_POLICY` spec, or `null` when it is unset or empty), and the usage the claude run reported (`--output-format json`):

- `input_tokens` = `uncached_input_tokens` + `cache_read_input_tokens` +
  `cache_creation_input_tokens`, each summed over every model in the result's
  `modelUsage`;
- `output_tokens`, `cost_usd`, `num_turns` and `models` (the sorted model ids used).

All of those are `null` for a plan-only run (verdict `PRINTED`), and for a run whose
stdout held no single parseable result object (a timeout or a crash), which still
writes its row. `result.json` and `stderr.txt` stay in the sandbox beside `output.txt`,
the transcript the asserts grep: the result text followed by claude's stderr.

With `EVAL_TRIALS=N` (N>1) the runner reruns the eval in a fresh sandbox per trial and
prints a summary — pass rate and nearest-rank p50/p90 wall time. Comparing runs before and
after a skill edit is one `jq` away:

```sh
jq -r 'select(.skill=="from-issue" and .id==1 and .input_tokens != null) | [.ts, .model, (.tree_rev // "deployed"), .verdict, .wall_s, .input_tokens] | @tsv' \
  results/results.jsonl
```
