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

**Deployed (the default).** The sandboxed `claude -p` reads skills from `~/.claude/skills`
- the store links from the last `just switch`, not this working tree (user-level skills
shadow project-level copies of the same name, so injecting the working tree into the
sandbox does not work). Editing a skill therefore means: commit, `just switch`, then run
the eval. A failed parity run is one `git revert` + re-switch away from the previous
behavior. The row records `tree: "deployed"` with `tree_rev` and `tree_dirty` null.

**Working tree.** `EVAL_TREE=. just evals from-issue 1` evaluates a checkout without a
switch. The runner resolves the eval from that checkout's two skill roots, then, for a
pipeline eval, builds a temporary root `${TMPDIR:-/tmp}/run-eval-tree.XXXXXX` holding:

- `config/`, exported as `CLAUDE_CONFIG_DIR` for the probe and the run: `skills/<name>/`
  real directories whose files are symlinks to the tree's files (a name in both skill
  roots is an error), `CLAUDE.md` (a copy of the tree's `AGENTS.md`), `agents/` (copies of
  the tree's agent files) and `settings.json` (`EVAL_SETTINGS` without its
  `enabledPlugins` and `extraKnownMarketplaces` keys);
- `bin/`, put first on `PATH`: one shim per command in the tree's `lib/agent-tools.nix`
  table, each running `python3 -P -m agent_tools.<module>` from the tree's `python/`, so
  `resolve-project`, `workflow-state` and the rest are the tree's code, not the installed
  ones.

The temp root is removed on every exit path: a normal end, an error, a non-zero claude
exit, Ctrl-C (exit 130) and SIGTERM (exit 143). A plan-only eval creates none of it.

Tree mode does not cover the legacy flat helpers (`workflow-state`, `artifact-budget`,
`sdd-workspace`), `~/.agents/standards` and `~/.agents/share`: those still come from the
deployed home, as do the absolute `~/.agents/bin/...` paths some skills name. The
`impeccable` and plugin skills are omitted (the settings copy drops `enabledPlugins` and
`extraKnownMarketplaces`). Helper changes are outside what this mode measures.

**One-time login.** A temp config dir has no stored login, so the runner probes
`claude auth status` against it and refuses (exit 2, before any sandbox or row) if that
fails. Run `claude setup-token` once and export the printed token as
`CLAUDE_CODE_OAUTH_TOKEN`; the temp config dir picks it up.

`EVAL_SETTINGS` names the settings file copied into the config dir. It defaults to
`$HOME/.claude/settings.json` and is read only in tree mode; a missing or non-JSON file
is an error.

A row from tree mode records `tree` (the checkout's absolute path), `tree_rev` (its
`HEAD`) and `tree_dirty` (whether `git status --porcelain` shows changes under the
instruction paths: both skill roots, `home/common/claude-code/agents` and
`home/common/agent-guidance/AGENTS.md`, ignoring each skill's own `evals/`).

## Cheap-first

The `from-issue` pipeline cases stop the flow after Phase 5 and grade the artifacts - spec,
plan, worktree placement, decision logs. The implementation never runs. A full end-to-end
run costs an order of magnitude more and is reserved for risky landings. A pipeline case
of another skill names its own stop in its prompt.

## Conventions

- `"expected_today": "fail"` plus a `note` marks a case that documents a gap not yet closed.
  The runner reports `EXPECTED-FAIL` and exits 0; if it passes anyway you get
  `UNEXPECTED-PASS` telling you to drop the flag.
- `fixture-repo/` is `tinytask`, a stdlib-only python3 CLI with docs, an ADR, a
  complete `.agents/project.json` contract, and three issue fixtures under `issues/` (well-specified,
  fuzzy, mechanical). It also ships one pre-charted decision map,
  `.claude/wayfind/concurrent-shells/` — the markdown-tracker shape `wayfind` falls back to
  when its tracker capability is unsupported: a map, an unblocked ticket, a ticket blocked by it, and
  fog. The wayfind evals work it; every other eval must leave it untouched. Verify the fixture
  with `python3 -m unittest discover` from its root.
- Env: `EVAL_MODEL` (default `sonnet`), `EVAL_TIMEOUT` seconds (default 2700),
  `EVAL_MAX_USD` (optional ceiling), `EVAL_TRIALS` (default 1).
- Sandboxes are kept after the run and their path is printed, so you can inspect the spec
  and plan a failing assert complained about. Clean up with `rm -rf $TMPDIR/eval-*`.
- Asserts may carry a `"contract": "..."` key documenting a target artifact contract
  (e.g. the compact decision-ledger row shape) the assert depends on; the runner ignores
  it, integration re-verifies it when the contract lands.

## Results persistence

Every run appends one JSON line per trial to `results/results.jsonl`, which is committed
and append-only (the rest of `results/` is gitignored). Fields: timestamp, skill, eval
id/name, mode, model, trial number, verdict, per-assert pass/fail, wall seconds, claude
exit code, sandbox path, the `EVAL_MAX_USD` ceiling when one was set, the tree fields
above, and the usage the claude run reported (`--output-format json`):

- `input_tokens` = `uncached_input_tokens` + `cache_read_input_tokens` +
  `cache_creation_input_tokens`, each summed over every model in the result's
  `modelUsage`;
- `output_tokens`, `cost_usd`, `num_turns` and `models` (the sorted model ids used).

All of those are `null` for a plan-only run (verdict `PRINTED`), and for a run whose
stdout held no single parseable result object (a timeout or a crash), which still
writes its row. `result.json` and `stderr.txt` stay in the sandbox beside `output.txt`,
the transcript the asserts grep: the result text followed by claude's stderr.

With `EVAL_TRIALS=N` (N>1) the runner reruns the eval in a fresh sandbox per trial and
prints a summary - pass rate and nearest-rank p50/p90 wall time. Comparing runs before and
after a skill edit is one `jq` away:

```sh
jq -r 'select(.skill=="from-issue" and .id==1 and .input_tokens != null) | [.ts, .model, (.tree_rev // "deployed"), .verdict, .wall_s, .input_tokens] | @tsv' \
  results/results.jsonl
```
