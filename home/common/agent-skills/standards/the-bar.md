# The Bar

Layer 0: the universal bar, true on every project in every language. Paste this whole file into implementer and Standards-reviewer briefs. Stack idioms are Layer 1 (`stacks/*.md`); project deltas are Layer 2 (the repo's `docs/standards/`).

### Defense in depth

Every trust boundary is checked on both sides. The outer check exists for experience — fail fast, say something useful; the inner check exists for correctness, because a malicious or buggy caller must not be able to bypass it. "The other side has it covered" never justifies dropping either.

### Production-grade by default

Committed code carries no `TODO`, no `FIXME`, no placeholder waiting to be filled, no half-wired path. Incomplete work is finished or deleted before commit; a deliberate stub is *visibly* a stub and is named in the architecture doc. Known limitations belong in docs, never in source.

### Root causes

No catch to mute an error, no sleep to paper over a race, no special case to hide a wrong shape. Symptom-shaped evidence is good at proving a mechanism wrong and bad at telling you which knob is right — read the contract before building a mechanism around an observation.

### Single responsibility

One file, module or function, one reason to change. Split **when the second concern arrives, not when the file hurts** — every deferral makes the split costlier. Boundaries follow domain operations, not code kinds; a `helpers` or `utils` module is a missing boundary.

### DRY — knowledge, not keystrokes

Every policy, format, constant and contract has exactly one authoritative home; everything else derives from it or links to it. Two call sites that merely *look* alike are not duplication, and extracting them is speculative abstraction — a wrong abstraction costs more than a repeated line. Deduplicate when the copies must change together.

### YAGNI

Build the capability that was asked for, well. No configuration, abstraction, compatibility shim or error handling for cases that cannot happen yet and callers that do not exist.

### Framework-first

If the design starts with "we'll write a custom X that…", the framework probably already has it — check before building. When it genuinely doesn't, raise the gap at a checkpoint rather than quietly building around it.

### Maintainability over cleverness

Name for intent, not implementation. Keep units short enough to read without scrolling. Comments say *why*; the code already says what.

### Truthful terminal states

A run that did no work is Failed, not Completed — status surfaces are truth, not progress bars, and a swallowed inner failure must not present as success. Log the original error object before any swallow, translate or rethrow, especially across a framework seam where the framework will reshape or absorb it.

### The log stream is the debugger

If diagnosing a failure needed a temporary print statement or an attached debugger, the missing log line *is* the bug — add the error or warning call that should have been there and leave it in; probes never ship. Structured named fields beat interpolated prose, and every call to an external service logs its response body on the failure path: a provider's 4xx body is the pointer to the request you got wrong.

### Fail loud

At a closed-set dispatch site — an enum switch, a discriminated union, a registry lookup, a parsed variant — the default branch throws. A silent fallback there turns a near-compile-time bug into a runtime mystery; exhaustiveness is the point of the closed set.

### Token economy

The agent-facing surface is scarce: design it like it. Few tools and few parameters, because each is a failure site and not merely tokens; short stable handles rather than raw identifiers in anything a model reads or writes; standing instructions paid once in a prompt, never re-injected per turn. When a surface grows, check what fraction of it is signal rather than plumbing.

### Tests that can fail

A test earns its place by failing for exactly one reason. Assert observable behaviour — the row written, the response returned — never that a particular method was called; a call-count assertion against a mock survives every implementation that keeps the call. Shape fixtures like the values production actually carries rather than the shortest string that parses, or a bug in the consumer and a matching shortcut in the assertion cancel out and both stay green. When a guard's boundary is redundant with a filter upstream of it, delete the guard and ask which test turns red; if none does, the guard is untested.

### Verify before claiming done

Run it and show the behaviour. Absence of an error is not evidence of success, and neither is a plausible diff. State what you ran and what it printed, or say plainly that you did not verify.
