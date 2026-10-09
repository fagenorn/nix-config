# Operation: `plan-review`

Uses SKILL.md's retained `ResolvedProject` and validated direct-command result, `bindings.workflow.review.plan`, and the `Blocking`, `Should fix` and `Discussion` headings. It never resolves, reads policy, infers a path or supplies a default.

## Caller input gate

Pipe the planning result's exact received bytes through `artifact-budget validate-report --boundary producer --input -` and keep only the validated stdout before reading any field. Require `state: complete` and the exact D11 `implementation-plan` artifact; any other state, legacy producer fields or a validation failure stops the operation with no prose fallback (D11, D14).

Take the root path and four metrics from that object only, run `artifact-budget check --kind implementation-plan --root <plan-root> --format json`, and require exit 0, `within_budget` and all four metrics matching. Exit 2 or 3, or missing or stale metrics, stops before packet construction (D5, D6).

## The packet

From the invocation directory, resolve the canonical worktree root and build one self-contained prompt with:

1. The operation name, invocation directory, worktree root, current branch and base SHA.
2. The issue title, body, URL and acceptance criteria, the Phase-0 investigation summary, and the open questions with their dispositions.
3. Absolute paths to the approved spec and the plan root, with its `root_bytes`, `total_bytes`, `file_count` and `largest_member_bytes`; no member list or plan content.
4. Every applicable `AGENTS.md` and `CLAUDE.md` from the invocation directory up to the worktree root.
5. Available `bindings.paths.hints` paths and the domain docs selected from the snapshot's context, standards and architecture paths: the context map and only the area `CONTEXT.md` files whose `governs:` globs intersect the plan's paths or whose terms appear in the issue; ADRs cited by the issue, spec, plan or a selected area; and the applicable standards (`~/.agents/standards/the-bar.md`, its `stacks/` shards for the diff's file types, the project's intersecting `docs/standards/` shards). A worktree `GROUNDING.md` routes this selection but never replaces it. Without a map, fall back to the retained `bindings.paths.{context,standards,architecture}` paths.
6. Relevant manifests and the retained `bindings.workflow.verification` entries, labelled as context on how the work is verified elsewhere, not a request to run anything. Item 3's metrics are already validated, so a reviewer that shells out to `artifact-budget` exceeds its contract.
7. The absolute path to the caller's `REVIEW-CONTRACT.md`, with concrete values for every placeholder it names.

## Reviewer contract

Include these rules in substance, beside SKILL.md's read-only rules:

- Read the plan root and every indexed member in checker discovery order first. A missing or unreadable member is a reported contract failure; never parse numbered bodies from the root instead.
- Review only conformance to the issue, acceptance criteria, approved spec, live code, project docs and supplied coding bar. Add no features and do not relitigate accepted scope or review the whole branch instead of the plan.
- Return exactly three top-level sections, `Blocking`, `Should fix` and `Discussion`, with `None.` under an empty one.
- Give every finding a stable ID, the affected member or root section, live `path:line` evidence, confidence (`high`, `medium`, `low`), the required or suggested correction, and unresolved unknowns (`none` when empty).
- Report every supplied artifact that could not be read.

## Verify and disposition

The parent Claude agent owns the result:

1. Re-open every cited live file and reject findings whose evidence is stale, absent or does not support the claim.
2. Apply verified Blocking findings. Apply verified Should-fix items under `--auto`, otherwise present them to the user. Raise Discussion items at the normal checkpoint, or apply the autonomous decision rule.
3. Record only non-obvious applied findings (scope, interface, behavioral, test-seam, irreversible, user-preference) in the spec's decision ledger (`| ID | Choice | Grounding | Rejected alternative |`), merging related ones, and cite row IDs from the plan.
4. Add or update a short `## Standards review provenance` section in the plan: reviewer (`Codex` or `Claude fallback`), base SHA, isolated read-only mode, optional focus, accepted/rejected/deferred counts, and the fallback reason when one applies.
5. Keep the raw reviewer transcript out of the repository, plan, issue, PR and commit messages.

After the last accepted edit, run `artifact-budget check --kind implementation-plan` on the whole package and replace the retained metrics; if the spec or its ledger changed, run the design-spec check too. An invalid or over-budget artifact is not a completed disposition, and Phase 5 never advances on stale measurements (D5, D14).

Return control once every accepted finding has an explicit disposition and the plan is ready for the caller's Phase-5 checkpoint.
