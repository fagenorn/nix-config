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

Reading the snapshot the way the gate does: at `224954b3`, `64` product lines and `3`
product files, both under ≤1,000 / ≤20, so this branch's own size prerequisite is
satisfied — see the post-merge reading below for the figure at the merged tip. The
`excluded: … 2 artifact` count is the spec and the plan — the two artifact files this run
had committed when the range was measured. The invocation also names this evidence file,
which is still uncommitted at that moment and so matches no row and contributes nothing;
naming it costs nothing (an unmatched `--artifact-path` is deliberately not an error, per
D3) and it starts counting on any re-run made after this document is committed. One path
per file throughout, never `<specDir>`/`<planDir>`.

**Re-run this command fresh at ship time.** These integers are a snapshot at the SHA above;
review fixups and the Phase-1 sync merge both move the range, so the PR body must quote a run
made after the branch's final commit, not this one.

## Post-merge reading (the figure that shipped)

The snapshot above is a real run at `224954b3`, not the figure that shipped. PR #27 merged
with head `b83e618e898ba80372756d0542f8872ded0e1672` (merge commit
`5aa2834f10796c7c71ae7c6f377610d1e63f3f36`). `git merge-base b83e618e fc498cb7` is
`fc498cb732ce8378711739c62463e5285e36133c` — the same base the snapshot used, so the two runs
are directly comparable. Two commits landed on the branch after the snapshot: `6f0b4cf`
(`docs(issue-22): record the A10 diff-scope run for the retuned gate`, this evidence file) and
`b83e618` (`test(ship-issue): pin the gate prerequisites' polarity`). Those two are what moved
64 → 76 product lines and 2 → 3 excluded artifacts.

The same command, with `..b83e618e898ba80372756d0542f8872ded0e1672` substituted as the head:

```
product: 76 lines, 3 files
excluded: 0 lockfile, 0 generated, 3 artifact
  72  home/common/agent-skills/tests/test_workflow_skill_contracts.py
  2  home/common/agent-skills/skills/ship-issue/SKILL.md
  2  home/common/agent-skills/skills/ship-issue/evals/evals.json
```

The gate's conclusion is unchanged: `76` ≤ 1,000 and `3` ≤ 20 — the same verdict by the same
margin. The third excluded artifact is this evidence file itself, now committed, exactly as the
snapshot's own prose predicted ("it starts counting on any re-run made after this document is
committed"). This addendum is also the fresh run the paragraph above asks for, made at the
branch's final commit.
