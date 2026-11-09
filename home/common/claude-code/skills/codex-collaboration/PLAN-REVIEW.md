# Operation: `plan-review`

Uses SKILL.md's retained `ResolvedProject` and validated direct-command result, `bindings.workflow.review.plan`, and the `Blocking`, `Should fix` and `Discussion` headings. It never resolves, reads policy, infers a path or supplies a default.

## Caller input

An absolute plan path (the plan root; its task files sit beside it and are linked from it), and when the caller gives them, the issue number and repository, the acceptance criteria and an approved spec path. Stop before packet construction when the plan path is missing, relative or unreadable. Nothing is validated or measured beyond that.

## The packet

From the invocation directory, resolve the canonical worktree root and build one self-contained prompt with:

1. The operation name, invocation directory, worktree root, current branch and base SHA.
2. The issue reference and the caller's acceptance criteria; the reviewer may read the issue with read-only `gh issue view`.
3. The absolute plan root, its task files, and the spec path when given.
4. Every applicable `AGENTS.md` and `CLAUDE.md` from the invocation directory up to the worktree root.
5. Available `bindings.paths.hints` paths and the domain docs selected from the snapshot's context, standards and architecture paths: the context map and only the area `CONTEXT.md` files whose `governs:` globs intersect the plan's paths or whose terms appear in the issue; ADRs cited by the issue, spec, plan or a selected area; and the applicable standards (`~/.agents/standards/the-bar.md`, its `stacks/` shards for the diff's file types, the project's intersecting `docs/standards/` shards). A worktree `GROUNDING.md` routes this selection but never replaces it. Without a map, fall back to the retained `bindings.paths.{context,standards,architecture}` paths.
6. The retained `bindings.workflow.verification` entries, labelled as context on how the work is verified elsewhere, not a request to run anything.

## Reviewer contract

Include these rules in substance, beside SKILL.md's read-only rules:

- Read the plan root and every task file it links first. A missing or unreadable one is a reported contract failure.
- Review conformance to the issue, acceptance criteria, spec when given, live code, project docs and supplied coding bar, and whether every acceptance criterion maps to a task whose test can fail. Add no features and do not relitigate accepted scope or review the whole branch instead of the plan.
- Return exactly three top-level sections, `Blocking`, `Should fix` and `Discussion`, with `None.` under an empty one.
- Give every finding a stable ID, the affected task file or root section, live `path:line` evidence, confidence (`high`, `medium`, `low`), the required or suggested correction, and unresolved unknowns (`none` when empty).
- Report every supplied artifact that could not be read.

## Disposition

Return the validated result unmodified to the calling controller with reviewer identity `Codex`: `Blocking` findings reported as `critical`, `Should fix` as `important` and `Discussion` as `minor`; verdict `pass` when `Blocking` and `Should fix` are both `None.`, otherwise `findings`. Keep the raw transcript out of the repository, plan, issue, PR and commits.
