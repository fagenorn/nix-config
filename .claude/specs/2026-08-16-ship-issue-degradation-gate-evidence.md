# Degradation gate retune — A10 evidence

Issue: https://github.com/fagenorn/nix-config/issues/22
Spec: `.claude/specs/2026-08-16-ship-issue-degradation-gate-design.md` (A10)

A10 asks for the prescribed invocation to produce its two integers on a real range. It is
evidence, not a gate: the retuned gate cannot be observed deciding a live ship yet, because a
skill is read through the activated generation's `~/.claude/skills` link and
`~/.agents/bin/diff-scope` does not exist until the next `just switch` (out of scope here, per
the spec). This run therefore invokes the script directly from the worktree; the flags,
the range and the reading are identical to what the gate prescribes.

Recorded 2026-08-17, on `worktree-issue-22-degradation-gate-retune` at
`224954b30e0c0162fd95d83cd9a3365f5773b2b3` with
`BASE_SHA=fc498cb732ce8378711739c62463e5285e36133c` (`git merge-base HEAD origin/main`).

```
$ python3 home/common/agent-skills/scripts/diff-scope.py fc498cb732ce8378711739c62463e5285e36133c..224954b30e0c0162fd95d83cd9a3365f5773b2b3 --format text \
  --artifact-path .claude/specs/2026-08-16-ship-issue-degradation-gate-design.md \
  --artifact-path .claude/plans/2026-08-16-ship-issue-degradation-gate.md \
  --artifact-path .claude/specs/2026-08-16-ship-issue-degradation-gate-evidence.md
```

```
product: 64 lines, 3 files
excluded: 0 lockfile, 0 generated, 2 artifact
  60  home/common/agent-skills/tests/test_workflow_skill_contracts.py
  2  home/common/agent-skills/skills/ship-issue/SKILL.md
  2  home/common/agent-skills/skills/ship-issue/evals/evals.json
```

Reading it the way the gate does: `64` product lines and `3` product files, both
under ≤1,000 / ≤20, so this branch's own size prerequisite is satisfied. The `excluded: …
2 artifact` count is the spec and the plan — the two artifact files this run had committed when
the range was measured. The invocation also names this evidence file, which is still uncommitted
at that moment and so matches no row and contributes nothing; naming it costs nothing (an
unmatched `--artifact-path` is deliberately not an error, per D3) and it starts counting on any
re-run made after this document is committed. One path per file throughout, never
`<specDir>`/`<planDir>`.

**Re-run this command fresh at ship time.** These integers are a snapshot at the SHA above;
review fixups and the Phase-1 sync merge both move the range, so the PR body must quote a run
made after the branch's final commit, not this one.
