# Project bindings (from-issue)

Loaded from `SKILL.md` at startup. Resolve once, carry the values.

1. Read `.claude/skills.config.json` at the project root if it exists.
2. Auto-detect what it doesn't set: issue tracker = `gh` if the remote is github.com, else `glab`/none; verify commands from the manifest (npm scripts, dotnet, cargo, go, make); branches from the repo default.
3. Defaults when neither yields a value: integrationBranch=main, defaultBranch=main, commit.coAuthoredBy=true, unsetGithubToken=false, specDir=.claude/specs, planDir=.claude/plans, codex.planReview.enabled=true, codex.planReview.focus=null.
4. Degrade gracefully: a configured-but-absent doc path, sibling skill, or hints file is skipped silently. Never read a file that doesn't exist; never hard-fail on a missing optional binding.

Keys used: `integrationBranch`, `defaultBranch`, `issueTracker{kind,cli}`, `unsetGithubToken`, `commit.coAuthoredBy`, `docPaths{context,contextMap,standards,architecture,gitWorktrees}` (`docPaths.adrDir` is a legacy override; ADR homes normally come from the map's areas), `specDir`, `planDir`, `branchNaming{pattern,worktreePrefix}`, `projectHints`, `codex.planReview{enabled,focus}`, `repoSlug`.

`<tracker-cli>` = resolved `issueTracker.cli`; `<integration-branch>`, `<default-branch>` likewise. When `issueTracker.kind=none`, skip every issue/PR-linkage step and operate on the branch alone (a "tracker URL" the user gives you is just a label).

**tracker-cli hygiene.** When `unsetGithubToken` is true, prefix *every* `<tracker-cli>` call — including ones you add ad-hoc — with `unset GITHUB_TOKEN &&`; some harnesses export a token without the target org's access. When false (default), use the ambient credential.
