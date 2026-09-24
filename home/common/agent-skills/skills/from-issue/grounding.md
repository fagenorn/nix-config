# Doc grounding (from-issue)

This included document receives values from the phase owner's retained `ResolvedProject`; use `bindings.paths.context` and `bindings.paths.standards` and never resolve, infer, or read project policy.

Loaded from `SKILL.md`; applies to Phases 2–5, which ground in the project's docs before their first clarifying question, option set, or review pass.

Invoke `doc-grounded-questions`: it receives the retained `bindings.paths.context` and `bindings.paths.standards`, then caches the result in the worktree's git-dir `GROUNDING.md` (`"$(git rev-parse --git-dir)/GROUNDING.md"` — never a working-tree path, which would get committed and collide across parallel runs).

**Ground once per phase, not once per decision.** After the phase's first pass, read `GROUNDING.md` instead of re-running it; re-invoke only when a decision reaches an area the cache doesn't cover, then append that area. Each new phase starts a new cache. Included routines reuse passed paths and never infer a policy value.
