# Skill evals

Measurement harness for the skills in `../skills/`. Each skill keeps its cases in
`../skills/<skill>/evals/evals.json`; everything here is the shared machinery.

```sh
just evals from-issue 3      # pipeline eval: sandbox, run, grade, verdict
just evals ship-issue 1      # plan-only eval: prints prompt + expected output
EVAL_MODEL=opus just evals from-issue 1
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
  `EVAL_MAX_USD` (optional ceiling).
- Sandboxes are kept after the run and their path is printed, so you can inspect the spec
  and plan a failing assert complained about. Clean up with `rm -rf $TMPDIR/eval-*`.
