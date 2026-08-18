---
name: improve-codebase-architecture
description: Scan a codebase for deepening opportunities, present them as a visual HTML report, then grill through whichever one you pick.
disable-model-invocation: true
---

# Improve Codebase Architecture

Surface architectural friction and propose **deepening opportunities** — refactors that turn shallow modules into deep ones. The aim is testability and AI-navigability.

This command is _informed_ by the project's domain model and built on a shared design vocabulary:

- Invoke `codebase-design` for the architecture vocabulary (**module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**) and its principles (the deletion test, "the interface is the test surface", "one adapter = hypothetical seam, two = real"). Use these terms exactly in every suggestion — don't drift into "component," "service," "API," or "boundary."
- Invoke `doc-grounded-questions` before scanning to resolve the project's domain language, decisions, and standards. Use the domain names it finds, treat recorded decisions as constraints rather than invitations to re-litigate, and carry standards into candidate grading. If the project has no documentation surfaces, continue on code alone.

## Process

### 1. Explore

**Scope before you scan — YAGNI.** Deepening a module pays off by making future changes to it easier, so decide *where* to look before you look:

- If the user named a direction — a module, subsystem, path, or pain point — that scope is authoritative, bypasses inference entirely, and goes straight to the code, tests, and relevant documentation.
- Otherwise, run `git log --oneline --no-merges -50`, rank repeatedly changed paths, and follow the strongest concentration into the code, tests, and documentation covering it. Widen only when the history is scattered or yields no meaningful concentration.

History selects where to look. It is never, by itself, evidence that a module should change.

Then launch one fresh scan owner to walk the codebase organically and note where understanding or change loses locality:

<!-- agent-dispatch: id=improve-architecture-scan-owner role=issue-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") performs the one read-only architecture scan and returns evidence-backed deepening candidates without writing to the repository.

If the host cannot dispatch a sub-agent, perform the same bounded scan inline and disclose that fallback. Discovery writes nothing to the repository. It may write at most one structured findings artifact, and only under the OS temporary directory.

For every suspected candidate, establish these seven evidence items in order:

1. The **module and callers**.
2. The **interface knowledge callers currently carry**.
3. Record **where locality or leverage is lost**.
4. The **deletion-test result**: would deleting the shallow module concentrate complexity, or merely move it?
5. The **dependency category** (`in-process`, `local-substitutable`, `ports & adapters`, or `mock`) and, when claiming a real seam, **two justified adapters**.
6. The **existing tests** and the **proposed interface-level test surface**.
7. Any **context or decision conflict**, including why reopening a recorded decision would be justified.

Do not follow rigid heuristics. Look for the same friction upstream calls out:

- Where does understanding one concept require bouncing between many small modules?
- Where are modules **shallow** — interface nearly as complex as the implementation?
- Where have pure functions been extracted just for testability, but the real bugs hide in how they're called (no **locality**)?
- Where do tightly coupled modules leak across their seams?
- Which parts of the codebase are untested, or hard to test through their current interface?

Apply the **deletion test** to anything you suspect is shallow: would deleting it concentrate complexity, or just move it? A "yes, concentrates" is the signal you want.

### 2. Present candidates as an HTML report

The caller, not the scan owner, renders every candidate that clears the evidence bar, up to five. The valid result is **zero to five** candidates. Never pad toward a count. Zero produces a truthful no-candidate report and is a **successful run**. Use `Strong`, `Worth exploring`, or `Speculative` for recommendation strength, and include a **Top recommendation** when at least one candidate exists.

Read [HTML-REPORT.md](HTML-REPORT.md) only when rendering. Write a self-contained HTML file to the OS temp directory so nothing lands in the repository. Resolve the temp directory from `$TMPDIR`, falling back to `/tmp` (or `%TEMP%` on Windows), and write to `architecture-review-<timestamp>.html` so each run gets a fresh file.

Open it for the user — `xdg-open <path>` on Linux, `open <path>` on macOS, `start <path>` on Windows — and always print the absolute path. A report generation failure is a failed run. A browser-open failure or CDN failure is only a disclosed warning because the readable report and its absolute path remain available.

Treat the report template as a trust boundary before opening it. HTML-escape every repository-derived value before interpolation, including repository, module, caller, and file names; prose; evidence; decision text; and diagram text equivalents. Mermaid uses only opaque generated Mermaid node IDs with escaped text labels and no raw HTML labels; repository text never becomes Mermaid syntax. Follow [HTML-REPORT.md](HTML-REPORT.md)'s machine-checkable candidate markup: zero candidates use its explicit zero-state marker with no candidate article or top-recommendation section, while each positive candidate uses one marked article with all seven evidence surfaces, before/after text surfaces, and one top-recommendation link to a candidate.

Each candidate gets a **before/after** visualisation and a card containing:

- **Files** — which files/modules are involved
- **Problem** — why the current architecture is causing friction
- **Solution** — plain English description of what would change
- **Benefits** — explained in terms of locality and leverage, and how tests would improve
- **Before / After diagram** — side-by-side, custom-drawn, illustrating the shallowness and the deepening
- **Recommendation strength** — one of `Strong`, `Worth exploring`, `Speculative`, rendered as a badge

Use domain vocabulary resolved by `doc-grounded-questions`. If a candidate contradicts a recorded decision, surface it only when the friction justifies reopening that decision, and mark the conflict clearly.

Do NOT propose interfaces yet. After the file is written, ask the user which candidate they would like to explore and propose the top recommendation.

### 3. Route the selection

Selection is the first point at which repository mutation may begin. Follow this ladder in order:

1. **Fog gate.** If the destination or its current decision questions still cannot be stated precisely, invoke `wayfind`, then return control. Create no design worktree and do not automatically resume this skill after the map is charted. After the map is written, make the final non-empty output line exactly `WAYFIND_COMPLETE: map created; control returned before issue creation, planning, or implementation.` and stop.
2. **Isolation.** Reuse the current workspace only if it is already an isolated linked worktree. Otherwise invoke `worktrees` for a candidate-named worktree cut from the configured remote integration-branch ref before writing a spec or domain document.
3. **Design.** Invoke `design`, carrying the scan evidence as grounding without re-asking what the selection settled.
4. **Domain and decisions.** After the design is approved, invoke `grill-with-docs`. If the user rejects the candidate for a load-bearing reason that future scans need to know, offer to record that decision through this workflow.
5. **Scope gate, then stop.** Recommend `writing-plans` for one cohesive build or `to-issues` for several independently shippable slices. Do not invoke either workflow. Do not create issues, plan, implement, or execute the candidate. Make the final non-empty output line exactly `DESIGN_COMPLETE: spec committed and grilled; control returned before planning or implementation.` and stop.

This is an attributed adaptation; see [LICENSE](LICENSE) for provenance and the upstream notice.
