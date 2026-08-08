---
name: codex-collaboration
description: Run a private, isolated Codex plan review for from-issue Phase 5 and disposition its findings. Only when from-issue requests it and Codex review is enabled.
user-invocable: false
---

# Codex Collaboration

Support one operation: `plan-review`. Keep Codex review-only and keep the parent
Claude agent responsible for every plan edit and disposition.

## Resolve policy

Read `<repo-root>/.claude/skills.config.json` when present. Resolve
`codex.planReview` as follows:

- Missing `enabled` means `true`.
- `enabled: false` means return control so `from-issue` can use its fresh native
  reviewer flow. Do not launch Codex.
- A non-empty `focus` adds project-specific emphasis without replacing the
  standard review bar.
- Continue to apply the existing `projectHints` binding when its file exists.

If this skill or the `codex:codex-reviewer` plugin agent is unavailable, the
caller uses the native reviewer flow. This is capability fallback, not a Codex
runtime failure.

## Build the review packet

Start from the invocation directory and resolve the canonical Git
workspace/worktree root. Build one self-contained delegation prompt containing:

1. The operation name, invocation directory, worktree root, current branch, and
   base SHA.
2. The issue title/body/URL, acceptance criteria, Phase-0 investigation summary,
   open questions and their dispositions.
3. Absolute paths to the approved specification and implementation plan.
4. Every applicable `AGENTS.md` and `CLAUDE.md` from the invocation directory up
   through the worktree root.
5. `.claude/skills.config.json`, configured documentation paths, standards,
   architecture, relevant ADRs, and `projectHints`, skipping absent optional
   files.
6. Relevant manifests and inferred verification commands.
7. The configured `codex.planReview.focus`, when non-empty.
8. The caller's complete common-miss checklist and project coding bar.

Tell the reviewer to inspect the live files at HEAD. Paths and summaries are
routing context, never substitutes for reading the worktree.

## Reviewer contract

Include these rules verbatim in substance:

- Remain read-only. Do not edit files; mutate Git; create commits, branches, or
  worktrees; change issues or PRs; install dependencies; or perform shipping
  actions.
- Use read-only repository and Git inspection only. Do not transfer a Claude
  transcript or review the whole branch as a substitute for reviewing the plan.
- Review only for conformance to the issue, acceptance criteria, approved spec,
  live implementation context, project docs, and supplied coding bar. Do not add
  features or relitigate accepted scope.
- Return exactly three top-level sections: `Blocking`, `Should fix`, and
  `Discussion`. Write `None.` under an empty section.
- For every finding include a stable ID, the affected plan task or section,
  evidence with live `path:line` references, confidence (`high`, `medium`, or
  `low`), the required or suggested correction, and unresolved unknowns
  (`none` when empty).
- Explicitly report which supplied artifacts could not be read.

## Launch

Dispatch the plugin agent `codex:codex-reviewer` once with the complete packet.
Run it in the foreground. The agent forwards the packet to
`codex-companion task --fresh --reviewer --timeout-ms 840000`, which guarantees a
fresh isolated `CODEX_HOME`, approval policy `never`, and sandbox `read-only`.

Parallel reviews are valid. A queued or active review is never a reason to use a
Claude fallback. Wait for the requested job. The patched reviewer runtime does
not share a broker with interactive commands or with another reviewer.

## Validate and fall back

A valid result has all three required headings and either `None.` or findings
with evidence, confidence, and unknowns. Treat only these as Codex failures:

- the executable is missing or authentication is unavailable;
- the process crashes or reaches its hard timeout;
- the agent returns `CODEX_REVIEW_FAILURE:`;
- the result is empty or malformed after one completed fresh run.

On a real failure, dispatch exactly one fresh Claude `general-purpose` standards
reviewer with the same packet and the same read-only/output contract. Do not ask
that fallback reviewer to imitate Codex. Record the concrete failure class and
that Claude fallback was used. Do not retry Codex and do not fall back because of
concurrency.

## Verify and disposition

The parent Claude agent owns the result:

1. Re-open every cited live file and verify each finding. Reject findings whose
   evidence is stale, absent, or does not support the claim.
2. Apply verified Blocking findings to the plan. Apply verified Should-fix items
   in `--auto`; otherwise present them to the user. Raise Discussion items at the
   normal checkpoint, or apply the documented autonomous decision rule.
3. Preserve one `Auto-resolved decisions` entry per applied finding using the
   caller's required template. Never collapse several findings into one entry.
4. Add or update a concise `## Standards review provenance` section in the plan:
   reviewer (`Codex` or `Claude fallback`), base SHA, isolated/read-only mode,
   optional focus, counts accepted/rejected/deferred, and fallback reason when
   applicable.
5. Do not store the raw reviewer transcript in the repository, plan, issue, PR,
   or commit message.

Return control only after all accepted findings have explicit dispositions and
the plan is clean enough for the caller's Phase-5 checkpoint.
