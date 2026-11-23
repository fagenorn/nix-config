# The Bar

Layer 0: the universal bar, true on every project in every language. Paste this whole file into implementer and Standards-reviewer briefs. Stack idioms are Layer 1 (`stacks/*.md`); project deltas are Layer 2 (the repo's `docs/standards/`).

### B1. Defense in depth

Every trust boundary is checked on both sides. The outer check exists for experience — fail fast, say something useful; the inner check exists for correctness, because a malicious or buggy caller must not be able to bypass it. "The other side has it covered" never justifies dropping either.

### B2. Production-grade by default

Committed code carries no placeholder waiting to be filled, no half-wired path. Incomplete work is finished or deleted before commit; a deliberate stub is *visibly* a stub and is named in the architecture doc. Known limitations belong in docs, never in source.

### B3. Root causes

No catch to mute an error, no sleep to paper over a race, no special case to hide a wrong shape. Symptom-shaped evidence is good at proving a mechanism wrong and bad at telling you which knob is right — read the contract before building a mechanism around an observation.

### B4. Single responsibility

One file, module or function, one reason to change. Split **when the second concern arrives, not when the file hurts** — every deferral makes the split costlier. Boundaries follow domain operations, not code kinds; a `helpers` or `utils` module is a missing boundary.

### B5. DRY — knowledge, not keystrokes

Every policy, format, constant and contract has exactly one authoritative home; everything else derives from it or links to it. Two call sites that merely *look* alike are not duplication, and extracting them is speculative abstraction — a wrong abstraction costs more than a repeated line. Deduplicate when the copies must change together.

### B6. YAGNI

Build the capability that was asked for, well. No configuration, abstraction, compatibility shim or error handling for cases that cannot happen yet and callers that do not exist.

### B7. Framework-first

If the design starts with "we'll write a custom X that…", the framework probably already has it — check before building. When it genuinely doesn't, raise the gap at a checkpoint rather than quietly building around it.

### B8. Maintainability over cleverness

Name for intent, not implementation. Keep units short enough to read without scrolling.

### B9. Moves keep their history

Relocate and rename through the VCS's own move so `--follow` still works, and re-point every *living* document in the same commit. Point-in-time records — accepted decisions, past plans, published reports — keep their original paths: a citation into an accepted record is part of that record.

### B10. Truthful terminal states

A run that did no work is Failed, not Completed — status surfaces are truth, not progress bars, and a swallowed inner failure must not present as success. Log the original error object before any swallow, translate or rethrow, especially across a framework seam where the framework will reshape or absorb it.

### B11. The log stream is the debugger

If diagnosing a failure needed a temporary print statement or an attached debugger, the missing log line *is* the bug — add the error or warning call that should have been there and leave it in; probes never ship. Structured named fields beat interpolated prose, and every call to an external service logs its response body on the failure path: a provider's 4xx body is the pointer to the request you got wrong.

### B12. Fail loud

At a closed-set dispatch site — an enum switch, a discriminated union, a registry lookup, a parsed variant — the default branch throws. A silent fallback there turns a near-compile-time bug into a runtime mystery.

### B13. Token economy

The agent-facing surface is scarce: design it like it. Few tools and few parameters, because each is a failure site and not merely tokens; short stable handles rather than raw identifiers in anything a model reads or writes; standing instructions paid once in a prompt, never re-injected per turn. Prefer input forms a model emits reliably — a short relative form over a precise absolute one — and let defaults absorb the common case so it need emit nothing at all.

### B14. Tests that can fail

A test earns its place by failing for exactly one reason. Assert observable behaviour — the row written, the response returned — never that a particular method was called; a call-count assertion against a mock survives every implementation that keeps the call. Shape fixtures like the values production actually carries rather than the shortest string that parses, or a bug in the consumer and a matching shortcut in the assertion cancel out and both stay green. When a guard's boundary is redundant with a filter upstream of it, delete the guard and ask which test turns red; if none does, the guard is untested.

At review, three kinds of test are findings: a test whose subject is a mock or fake rather than the code, so it passes with the code under test deleted; a test that pins wording — a decision record's, a docstring's, a prompt's or a message's — unless the message is a contract that a caller or a person parses; and a test that stays green with the behaviour it names broken.

### B15. Verify before claiming done

Run it and show the behaviour. Absence of an error is not evidence of success, and neither is a plausible diff. State what you ran and what it printed, or say plainly that you did not verify.

### B16. Test runs leave nothing behind

A test run creates what it uses and removes it when it ends, takes no fixed port, and leaves nothing behind. ([decision](https://github.com/fagenorn/nix-config/issues/1417))

### B17. Files stay under 1,500 lines

No source or test file is over 1,500 lines. A file already over it may not grow and a file under it may grow up to it, judged against the change's merge base. ([decision](https://github.com/fagenorn/nix-config/issues/1422))

### B18. Comments say why the code is as it is

A comment states in the present tense a constraint, an invariant or a consequence a reader would not guess; it does not restate the code, tell how the code came to be or name an issue or pull request. It may cite a decision-record id, a rule id in an enforcer or a suppression, and on a workaround an upstream bug link with the condition for removing it. ([decision](https://github.com/fagenorn/nix-config/issues/1420))

### B19. Comments stay short

A comment block is at most five lines, each at most 120 characters; a module docstring or file header is exempt from this cap but not from B18. A why that needs more room is a decision record, cited by its id. ([decision](https://github.com/fagenorn/nix-config/issues/1420))

### B20. No TODO or FIXME

Committed code carries no `TODO` and no `FIXME` comment: unfinished work is an issue on the tracker. ([decision](https://github.com/fagenorn/nix-config/issues/1420))

### B21. Decision records stay under 1,500 bytes

A decision record is at most 1,500 bytes. A record already over it may not grow, judged against the change's merge base. ([decision](https://github.com/fagenorn/nix-config/issues/1428))

### B22. A decision record is a title and one paragraph

After its title header a decision record holds one paragraph and nothing else: no section heading, status line, list, second paragraph or numbered sub-decision. Breaches are judged against the change's merge base; an added record has none to carry. ([decision](https://github.com/fagenorn/nix-config/issues/1428))

### B23. No skipped or disabled test is added

A test its framework skips, disables or excludes proves nothing while it looks like coverage. The count of them may not rise against the merge base. ([decision](https://github.com/fagenorn/nix-config/issues/1421))

### B24. No two tests share a body

A test whose body, minus comments and whitespace, repeats another's adds cost without a check: give the case to the first test as data. The count of copies may not rise against the merge base. ([decision](https://github.com/fagenorn/nix-config/issues/1421))
