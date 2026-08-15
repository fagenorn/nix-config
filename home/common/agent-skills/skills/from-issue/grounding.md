# Doc grounding (from-issue)

Loaded from `SKILL.md`; applies to Phases 2–5, which ground in the project's docs before their first clarifying question, option set, or review pass.

Invoke `doc-grounded-questions`: it reads the context map / context doc, the ADRs owned by the areas it loaded (`docs/areas/<slug>/adr/`, plus `system`), and `docPaths.standards`, then caches the result in the worktree's git-dir `GROUNDING.md` (`"$(git rev-parse --git-dir)/GROUNDING.md"` — never a working-tree path, which would get committed and collide across parallel runs).

**Ground once per phase, not once per decision.** After the phase's first pass, read `GROUNDING.md` instead of re-running it; re-invoke only when a decision reaches an area the cache doesn't cover, then append that area. Each new phase starts a new cache. Without the skill, do the same by hand: read whichever configured doc paths exist, write the same `GROUNDING.md`, reuse it for the rest of the phase.
