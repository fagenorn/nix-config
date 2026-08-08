---
name: to-issues
description: Break a plan, spec, or PRD into independently-grabbable tracker issues using tracer-bullet vertical slices. Use to convert plans into implementation tickets.
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

Keys this skill uses: `issueTracker{kind,cli}`, `docPaths{context,contextMap}` (optional, used only for grounding; `docPaths.adrDir` is a legacy override where a repo still has a central ADR directory).

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

If you have not already explored the codebase, do so to understand the current state of the code. Issue titles and descriptions should use the project's domain vocabulary. If the project documents a domain glossary (the map's area files, else `docPaths.context`) or architectural decision records (each area's `docs/areas/<slug>/adr/`, plus `system`; legacy repos: `docPaths.adrDir`), read the relevant parts so titles and descriptions use the project's terminology and respect existing decisions in the area you're touching. If those docs are absent, skip this grounding step silently.

Look for opportunities to prefactor the code to make the implementation easier — "make the change easy, then make the easy change." Prefactoring is its own leading slice, not a preamble folded into the first feature slice.

### 3. Draft vertical slices

**Check the rejection KB first.** If `.out-of-scope/` exists at the repo root, read its files (one per
consciously-rejected idea) before drafting. Never propose a slice that re-litigates a rejected
direction — mention the rejection file instead; only the user can revive one.

Break the plan into **tracer bullet** issues. Each issue is a thin vertical slice that cuts through ALL integration layers end-to-end, NOT a horizontal slice of one layer.

Slices may be human-required or autonomous/agent-executable. Human-required slices need a person in the loop — an architectural decision, a design review, a credential or approval only a human can grant. Autonomous slices can be implemented and merged without human interaction. Prefer autonomous over human-required where possible.

<vertical-slice-rules>
- Each slice delivers a narrow but COMPLETE path through every layer (schema, API, UI, tests)
- A completed slice is demoable or verifiable on its own
- Each slice is sized to fit one fresh context window — oversized slices are the root cause of ultra-long implementation sessions
- Any prefactoring is its own slice, and comes first
- Prefer many thin slices over few thick ones
</vertical-slice-rules>

**Wide refactors are the exception to vertical slicing.** A wide refactor is one mechanical change — rename a column, retype a shared symbol — whose blast radius fans across the whole codebase, so a single edit breaks thousands of call sites at once and no vertical slice can land green. Don't force it into a tracer bullet; sequence it as **expand–contract**. First expand: add the new form beside the old so nothing breaks. Then migrate the call sites in batches sized by blast radius (per package, per directory), each batch its own slice blocked by the expand, keeping CI green batch to batch because the old form still exists. Finally contract: delete the old form once no caller remains, in a slice blocked by every migrate batch. When even the batches can't stay green alone, keep the sequence but let them share an integration branch that all block a final integrate-and-verify slice — green is promised only there.

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

**Record conscious rejections.** When the user rules a proposed direction out during this quiz (not
merely deferring it), write one short file per rejection to `.out-of-scope/<slug>.md` — the idea in a
line, why it was rejected, the date, and any link (spec section, wayfind ticket) — and commit them
with the breakdown. This is the KB step 3 checks; it stops future sessions from re-proposing settled
rejections for near-zero cost.

### 5. Publish the issues to the issue tracker

For each approved slice, publish a new issue to the resolved issue tracker. Use the issue body template below. These issues are considered ready for autonomous agents.

**Triage labels are conditional.** Apply a triage/ready-for-agent label ONLY if a label taxonomy was provided by the user or detected for the project (for example, a project label config or labels the user named when answering the tracker question). If no label taxonomy is available, skip labeling and say so explicitly (e.g. "Published without a triage label — no label taxonomy was configured.").

Publish issues in dependency order (blockers first) so you can reference real issue identifiers in the "Blocked by" field.

**Record blocking edges natively where the tracker has a native relationship** — it renders the frontier in the tracker's own UI, so whoever picks up work next can query what is takeable without re-reading the plan.

- **GitHub** — issue dependencies: `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`. **IMPORTANT: `issue_id` is the blocker's numeric database id, not the `#number` and not the `node_id`.** Get it with `gh api repos/<owner>/<repo>/issues/<n> --jq .id`. Passing the issue number here is the standard trap — it silently links an unrelated issue or fails. Read open blockers back from `issue_dependencies_summary.blocked_by`.
- **GitLab** — post the `/blocked_by #<blocker>` quick action as a note (`glab issue note <child> --message "/blocked_by #<blocker>"`). Native blocking links are a Premium/Ultimate feature; on the free tier fall back to the body's "Blocked by" section.

Where the tracker has no native relationship (or the API call is unavailable), the template's "Blocked by" section is the record. A slice is unblocked when every slice blocking it is closed.

If the resolved tracker is `kind: none`, do not publish — emit the breakdown as a markdown list (one block per slice using the template below) for the user to file manually.

<issue-template>
## Parent

A reference to the parent issue on the issue tracker (if the source was an existing issue, otherwise omit this section).

## What to build

A concise description of this vertical slice. Describe the end-to-end behavior, not layer-by-layer implementation.

Avoid specific file paths or code snippets — they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it here and note briefly that it came from a prototype. Trim to the decision-rich parts — not a working demo, just the important bits.

**Demo:** one line — what a reviewer can run, see, or click when this slice lands.

## Decisions

Links to the decisions this slice depends on — ADRs, wayfind decision tickets, spec sections — one
line each with the answer's gist. This is pre-resolved uncertainty: an implementing agent grounds in
these instead of re-deriving (or re-asking) them. Omit the section when nothing applies.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## Blocked by

- A reference to the blocking ticket (if any)

Or "None - can start immediately" if no blockers.

</issue-template>

**The body is the contract; the discussion is context.** Issue bodies are read weeks later in fresh
contexts: state behavior and outcomes, not procedures; no file paths, no line numbers, no "as
discussed above". Anything an implementer must know goes in the body or a linked durable artifact,
never only in a comment thread.

**Every acceptance criterion must be falsifiable.** For each one, name the observation that would show it false, and confirm that observation actually fails at the commit the implementer starts from. A criterion already true at the base commit grades nothing — it is how an implementer "completes" an issue as a no-op. Vertical slicing prevents most of this by construction (a slice delivering behaviour that did not exist before is red at base), but check by hand. Reject two other recurring shapes: a criterion that can only be satisfied by work another slice owns, and one that restates the request instead of deriving from the artifact.

Do NOT close or modify any parent issue.
