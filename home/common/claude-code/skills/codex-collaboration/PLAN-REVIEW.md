# Operation: `plan-review`

Read this when running `plan-review`. SKILL.md owns the shared runtime contract
(resolve policy, pre-flight, transport dispatch, validation, one-time fallback);
this file owns the packet, the reviewer contract, and the disposition.

## Caller input gate

Before using the planning result, pipe its exact received bytes through
`artifact-budget validate-report --boundary producer --input -` and retain only
the validated stdout bytes. Only then read `state` or any artifact field. Require
`state: complete` and the exact D11 `implementation-plan` artifact; legacy
producer-specific fields, another state, or validation failure stops the
operation without a prose fallback (D11, D14).

Take the root path and four metrics only from that validated object. Run
`artifact-budget check --kind implementation-plan --root <plan-root> --format
json` and require exit 0, `within_budget`, and an exact match with all four
metrics. Exit 2/3 or missing/stale metrics stops before packet construction or
dispatch (D5, D6).

## Build the review packet

Start from the invocation directory and resolve the canonical Git
workspace/worktree root. Build one self-contained delegation prompt containing:

1. The operation name, invocation directory, worktree root, current branch, and
   base SHA.
2. The issue title/body/URL, acceptance criteria, Phase-0 investigation summary,
   open questions and their dispositions.
3. Absolute paths to the approved specification and implementation-plan root,
   plus its `root_bytes`, `total_bytes`, `file_count`, and
   `largest_member_bytes`. Supply no member list or plan content.
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
6. Relevant manifests and inferred verification commands, labelled in the packet
   as context describing how this work is verified elsewhere — explicitly
   not a request to execute anything. Item 3's four metrics are supplied
   so the reviewer need not re-measure them, and the caller has already
   validated them at its own input gate; a reviewer shelling out to
   `artifact-budget` is exceeding its contract, not filling a gap in it.
7. The configured `codex.planReview.focus`, when non-empty.
8. The absolute path to the caller's review contract (`REVIEW-CONTRACT.md`) —
   the common-miss checklist and coding bar travel by path, with concrete
   values supplied for every placeholder the contract names.

## Reviewer contract

Include these rules verbatim in substance, alongside SKILL.md's read-only rules:

- Read the plan root and every indexed member in checker discovery order before
  reviewing. A missing or unreadable member is a contract failure and must be
  reported explicitly; never fall back to parsing numbered bodies from the root.
- Review only for conformance to the issue, acceptance criteria, approved spec,
  live implementation context, project docs, and supplied coding bar. Do not add
  features or relitigate accepted scope.
- Do not review the whole branch as a substitute for reviewing the plan.
- Return exactly three top-level sections: `Blocking`, `Should fix`, and
  `Discussion`. Write `None.` under an empty section.
- For every finding include a stable ID, the affected task member or root section,
  evidence with live `path:line` references, confidence (`high`, `medium`, or
  `low`), the required or suggested correction, and unresolved unknowns
  (`none` when empty).
- Explicitly report which supplied artifacts could not be read.

## Verify and disposition

The parent Claude agent owns the result:

1. Re-open every cited live file and verify each finding. Reject findings whose
   evidence is stale, absent, or does not support the claim.
2. Apply verified Blocking findings to the plan. Apply verified Should-fix items
   in `--auto`; otherwise present them to the user. Raise Discussion items at the
   normal checkpoint, or apply the documented autonomous decision rule.
3. Record applied findings in the spec's decision ledger (`| ID | Choice |
   Grounding | Rejected alternative |`) — only the non-obvious ones (scope,
   interface, behavioral, test-seam, irreversible, user-preference); the plan
   cites row IDs ("per D3") instead of restating rationale. Consolidation is
   permitted and encouraged: related findings merge into one row. Routine
   mechanical dispositions get no row.
4. Add or update a concise `## Standards review provenance` section in the plan:
   reviewer (`Codex` or `Claude fallback`), base SHA, isolated/read-only mode,
   optional focus, counts accepted/rejected/deferred, and fallback reason when
   applicable.
5. Do not store the raw reviewer transcript in the repository, plan, issue, PR,
   or commit message.

After the last accepted edit, run `artifact-budget check --kind
implementation-plan` on the complete package and replace the retained metrics.
If disposition amended the spec or its decision ledger, re-run the design-spec
check too. An invalid or over-budget artifact is not a completed disposition and
Phase 5 may not advance on stale measurements (D5, D14).

Return control only after all accepted findings have explicit dispositions and
the plan is clean enough for the caller's Phase-5 checkpoint.
