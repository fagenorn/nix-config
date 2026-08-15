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

## Evals exercise the DEPLOYED skills

The sandboxed `claude -p` reads skills from `~/.claude/skills` — the store links
from the last `just switch`, not this working tree (user-level skills shadow
project-level copies of the same name, so injecting the working tree into the
sandbox does not work). Editing a skill therefore means: commit, `just switch`,
then run the eval. A failed parity run is one `git revert` + re-switch away from
the previous behavior.

## Cheap-first

Pipeline prompts stop the flow after Phase 5 and grade the artifacts — spec, plan, worktree
placement, decision logs. The implementation never runs. A full end-to-end run costs an
order of magnitude more and is reserved for risky landings.

## Conventions

- `"expected_today": "fail"` plus a `note` marks a case that documents a gap not yet closed.
  The runner reports `EXPECTED-FAIL` and exits 0; if it passes anyway you get
  `UNEXPECTED-PASS` telling you to drop the flag.
- `fixture-repo/` is `tinytask`, a stdlib-only python3 CLI with docs, an ADR, a
  `.claude/skills.config.json`, and three issue fixtures under `issues/` (well-specified,
  fuzzy, mechanical). It also ships one pre-charted decision map,
  `.claude/wayfind/concurrent-shells/` — the markdown-tracker shape `wayfind` falls back to
  when `issueTracker.kind` is `none`: a map, an unblocked ticket, a ticket blocked by it, and
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

Every run appends one JSON line per trial to `results/results.jsonl` (gitignored):
timestamp, skill, eval id/name, mode, model, trial number, verdict, per-assert
pass/fail, wall seconds, claude exit code, sandbox path, and the `EVAL_MAX_USD`
ceiling when one was set (the harness has no per-run actual-cost source — `claude -p
--output-format text` does not report spend, so only the ceiling is recorded).
Plan-only runs record a `PRINTED` verdict. With `EVAL_TRIALS=N` (N>1) the runner
reruns the eval in a fresh sandbox per trial and prints a summary — pass rate and
nearest-rank p50/p90 wall time — so repeatability comparisons (before/after a skill
edit) are one `jq` away:

```sh
jq -r 'select(.skill=="from-issue" and .id==1) | [.ts,.verdict,.wall_s] | @tsv' \
  results/results.jsonl
```
