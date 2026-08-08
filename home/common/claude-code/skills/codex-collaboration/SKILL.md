---
name: codex-collaboration
description: Run a private, isolated Codex pass — plan-review (from-issue Phase 5) or decision-check (gated --auto cross-check) — and disposition its findings.
user-invocable: false
---

# Codex Collaboration

Support two operations: `plan-review` and `decision-check`. Keep Codex
review-only and keep the parent Claude agent responsible for every plan edit
and disposition.

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
5. `.claude/skills.config.json` and `projectHints` when present, plus domain
   docs selected map-first, all by path, skipping absent files: the context map
   (`docPaths.contextMap`, else `docs/CONTEXT-MAP.md`, else legacy root
   `CONTEXT-MAP.md`) and only the area
   `CONTEXT.md` files whose `governs:` globs intersect the plan's touched paths
   or whose terms appear in the issue; ADRs only when cited by the issue, spec,
   plan, or a selected area file; the standards layers that apply —
   `~/.agents/standards/the-bar.md`, its `stacks/` shards matching the diff's
   file types, and the project's `docs/standards/` shards whose globs
   intersect. A worktree `GROUNDING.md` is a routing hint for this selection,
   never a substitute for it. Only when the project has no map, fall back to
   the `docPaths.{context,standards,architecture}` whole-doc paths.
6. Relevant manifests and inferred verification commands.
7. The configured `codex.planReview.focus`, when non-empty.
8. The absolute path to the caller's review contract (`REVIEW-CONTRACT.md`) —
   the common-miss checklist and coding bar travel by path, with concrete
   values supplied for every placeholder the contract names.

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

## Operation: `decision-check`

Gated behind `codex.decisionReview` in `.claude/skills.config.json` — **default
off**; when absent or false, callers never invoke this operation. A one-shot
"refute this recommendation" pass for the high-stakes class of `--auto`
self-answered decisions (the caller decides eligibility).

- Packet: the question as it would have been asked, the `➡️` recommendation
  with its grounding, and the grounding paths selected by the same map-first
  protocol as `plan-review` item 5. Paths, never contents.
- Brief, included in substance: "Try to refute this recommendation against the
  cited grounding and the live repo. Read-only. Return exactly: `Verdict:
  concur | refute`, then ≤200 words of rationale citing `path:line` evidence."
- Dispatch `codex:codex-reviewer` once, foreground, fresh and isolated — same
  runtime contract as `plan-review`.
- The caller appends a `Cross-check:` field to the decision's
  `Auto-resolved decisions` entry: the verdict plus a one-line gist. On
  `refute`, the caller re-grounds once and decides, logging both views — the
  cross-check advises, it never overrules.
- **No Claude fallback for this operation.** On any Codex failure, record
  `Cross-check: unavailable (<failure class>)` and continue — this is an
  optional de-correlation pass, not a gate.
