---
name: improve-codebase-architecture
description: Finds deepening opportunities, reports them as HTML and routes the pick to design. Use to improve codebase architecture.
disable-model-invocation: true
---

# Improve Codebase Architecture

Surface architectural friction and propose **deepening opportunities**: refactors that turn shallow modules into deep ones, for testability and AI-navigability.

- Invoke `codebase-design` for the vocabulary (**module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**) and its principles; use those terms exactly in every suggestion.
- Invoke `doc-grounded-questions` before scanning for the project's domain language, decisions and standards. Use its domain names, treat recorded decisions as constraints, and grade candidates against the standards. Without documentation, continue on code alone.

## 1. Explore

**Scope before you scan.** A direction the user named (module, subsystem, path or pain point) is authoritative and goes straight to its code, tests and docs. Otherwise run `git log --oneline --no-merges -50`, rank the repeatedly changed paths, and follow the strongest concentration; widen only when history is scattered or shows no concentration. History selects where to look; it is never by itself evidence that a module should change.

Then launch one fresh scan owner:

<!-- agent-dispatch: id=improve-architecture-scan-owner role=issue-owner model=opus effort=high -->
Agent(subagent_type="general-purpose", model="opus", effort="high") performs the one read-only architecture scan and returns evidence-backed deepening candidates without writing to the repository.

If the host cannot dispatch, run the same bounded scan inline and disclose the fallback. Discovery writes nothing to the repository and at most one findings artifact under the OS temporary directory.

Each candidate needs these seven evidence items, in order:

1. The **module and callers**.
2. The **interface knowledge callers currently carry**.
3. **Where locality or leverage is lost**.
4. The **deletion-test result**: would deleting the shallow module concentrate complexity, or merely move it? "Concentrates" is the signal.
5. The **dependency category** (`in-process`, `local-substitutable`, `ports & adapters` or `mock`) and, for a real seam, **two justified adapters**.
6. The **existing tests** and the **proposed interface-level test surface**.
7. Any **context or decision conflict**, with why reopening a recorded decision is justified.

Look for friction, not rule matches: one concept spread across many small modules; **shallow** modules; pure functions extracted for testability while the bugs hide in their callers; coupling that leaks across seams; code that is untested or hard to test through its interface.

## 2. Present candidates as an HTML report

The caller renders every candidate that clears the evidence bar, **zero to five**, never padded. Zero is a truthful no-candidate report and a **successful run**. Rate each `Strong`, `Worth exploring` or `Speculative`, and add a **Top recommendation** when any candidate exists.

Read [HTML-REPORT.md](HTML-REPORT.md) when rendering, and follow its machine-checkable markup and safe-rendering rules exactly. Write one self-contained file, `architecture-review-<timestamp>.html`, in `$TMPDIR` (else `/tmp`, or `%TEMP%` on Windows), so nothing lands in the repository. Open it (`open`, `xdg-open` or `start`) and always print its absolute path. Failing to generate the report fails the run; a browser-open or CDN failure is only a disclosed warning.

Each candidate card shows the files, the problem, the solution in plain English, the benefits in terms of locality, leverage and tests, a before/after diagram, and the recommendation strength as a badge. Surface a candidate that contradicts a recorded decision only when the friction justifies reopening it, and mark the conflict.

Propose no interfaces yet. After writing the file, ask which candidate to explore and propose the top recommendation.

## 3. Route the selection

Selection is the first point where the repository may change. In order:

1. **Fog gate.** If the destination or its decision questions cannot be stated precisely yet, invoke `wayfind`, then return control: no design worktree, no automatic resume. After the map is written, make the final non-empty output line exactly `WAYFIND_COMPLETE: map created; control returned before issue creation, planning, or implementation.` and stop.
2. **Isolation.** Reuse the workspace only if it is already an isolated linked worktree; otherwise invoke `worktrees` for a candidate-named worktree cut from the configured remote integration-branch ref, before writing any spec or domain document.
3. **Design.** Invoke `design`, carrying the scan evidence as grounding without re-asking what the selection settled.
4. **Domain and decisions.** After the design is approved, invoke `grill-with-docs`. If the user rejects the candidate for a reason future scans need, offer to record that decision.
5. **Scope gate, then stop.** Recommend `writing-plans` for one cohesive build or `to-issues` for several independently shippable slices, without invoking either. Create no issues, plan or implementation. Make the final non-empty output line exactly `DESIGN_COMPLETE: spec committed and grilled; control returned before planning or implementation.` and stop.

This is an attributed adaptation; see [LICENSE](LICENSE) for provenance and the upstream notice.
