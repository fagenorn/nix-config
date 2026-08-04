---
name: to-issues
description: Break a plan, spec, or PRD into independently-grabbable issues on the project's issue tracker using tracer-bullet vertical slices. Use when user wants to convert a plan into issues, create implementation tickets, or break down work into issues.
---

# To Issues

Break a plan into independently-grabbable issues using vertical slices (tracer bullets).

## Project bindings (resolve first)

This skill is project-agnostic. Before acting, resolve project-specific values:

1. If `.claude/skills.config.json` exists at the project root, read it for the bindings below.
2. For any absent key (or no config file), auto-detect: issue tracker = `gh` if the git remote is github.com
   (else `glab`/none); verify commands from the manifest (package.json scripts, *.slnx/*.sln -> dotnet test,
   Cargo.toml -> cargo test, go.mod -> go test, Makefile -> make test); branches from the repo default.
3. Defaults when neither config nor detection yields a value: integrationBranch=main, defaultBranch=main,
   commit.coAuthoredBy=true, unsetGithubToken=false, deploy.adapter=none, specDir=.claude/specs, planDir=.claude/plans.
4. Degrade gracefully: any configured-but-absent doc path, sibling skill, or hints file is skipped silently —
   never read a file that does not exist, never hard-fail on a missing optional binding.

Keys this skill uses: `issueTracker{kind,cli}`, `docPaths{context,adrDir}` (both optional, used only for grounding).

### Resolve the issue tracker

Determine where issues live and which backend creates them:

1. If `issueTracker` is set in config, use it. `kind: github` → use the `cli` (default `gh`); `kind: gitlab` → `glab`;
   `kind: none` → there is no tracker, so present the breakdown but do not attempt to publish issues (output the
   slices as a markdown list / file for the user to file manually).
2. Else auto-detect from the git remote: `git remote get-url origin` pointing at github.com → `gh`; gitlab → `glab`.
3. Else, if neither config nor remote resolves a tracker, ask the user exactly one question:
   *"Where do issues live, and which CLI or MCP creates them?"* — then proceed with their answer.

## Process

### 1. Gather context

Work from whatever is already in the conversation context. If the user passes an issue reference (issue number, URL, or path) as an argument, fetch it from the issue tracker and read its full body and comments.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the current state of the code. Issue titles and descriptions should use the project's domain vocabulary. If the project documents a domain glossary (e.g. `docPaths.context`) or architectural decision records (e.g. `docPaths.adrDir`), read the relevant parts so titles and descriptions use the project's terminology and respect existing decisions in the area you're touching. If those docs are absent, skip this grounding step silently.

### 3. Draft vertical slices

Break the plan into **tracer bullet** issues. Each issue is a thin vertical slice that cuts through ALL integration layers end-to-end, NOT a horizontal slice of one layer.

Slices may be human-required or autonomous/agent-executable. Human-required slices need a person in the loop — an architectural decision, a design review, a credential or approval only a human can grant. Autonomous slices can be implemented and merged without human interaction. Prefer autonomous over human-required where possible.

<vertical-slice-rules>
- Each slice delivers a narrow but COMPLETE path through every layer (schema, API, UI, tests)
- A completed slice is demoable or verifiable on its own
- Prefer many thin slices over few thick ones
</vertical-slice-rules>

### 4. Quiz the user

Present the proposed breakdown as a numbered list. For each slice, show:

- **Title**: short descriptive name
- **Type**: human-required / autonomous
- **Blocked by**: which other slices (if any) must complete first
- **User stories covered**: which user stories this addresses (if the source material has them)

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the dependency relationships correct?
- Should any slices be merged or split further?
- Are the correct slices marked human-required vs autonomous?

Iterate until the user approves the breakdown.

### 5. Publish the issues to the issue tracker

For each approved slice, publish a new issue to the resolved issue tracker. Use the issue body template below. These issues are considered ready for autonomous agents.

**Triage labels are conditional.** Apply a triage/ready-for-agent label ONLY if a label taxonomy was provided by the user or detected for the project (for example, a project label config or labels the user named when answering the tracker question). If no label taxonomy is available, skip labeling and say so explicitly (e.g. "Published without a triage label — no label taxonomy was configured.").

Publish issues in dependency order (blockers first) so you can reference real issue identifiers in the "Blocked by" field.

If the resolved tracker is `kind: none`, do not publish — emit the breakdown as a markdown list (one block per slice using the template below) for the user to file manually.

<issue-template>
## Parent

A reference to the parent issue on the issue tracker (if the source was an existing issue, otherwise omit this section).

## What to build

A concise description of this vertical slice. Describe the end-to-end behavior, not layer-by-layer implementation.

Avoid specific file paths or code snippets — they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it here and note briefly that it came from a prototype. Trim to the decision-rich parts — not a working demo, just the important bits.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## Blocked by

- A reference to the blocking ticket (if any)

Or "None - can start immediately" if no blockers.

</issue-template>

Do NOT close or modify any parent issue.
