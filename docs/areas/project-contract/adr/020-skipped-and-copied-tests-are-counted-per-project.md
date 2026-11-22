# ADR-project-contract-020 — Skipped tests and copied test bodies are counted per project

- **Status:** accepted
- **Decided in:** #1464 (per #1421, #1414, #1412)

## Context

A test its framework skips or disables still looks like coverage, and a test whose body is a copy of another proves nothing new. The decision of #1414 is that a rule which the tree already violates is held by the never-rise check of ADR-project-contract-017, never by a baseline file or a raise label. #1421 sets the skipped-test rule and #1412 the copied-body rule, for every stack the standards give a shard.

## Decision

**D1. Two count rules.** B18 (skipped tests) and B19 (copied test bodies) are count rules of the never-rise check under ADR-project-contract-017: each fails when the project's total rises against the merge base, wherever a violation moves to. Each has its own id in the bar, its own enforcer and its own command, and each enforcer cites its rule in its own source.

**D2. Test files per stack.** A test file is chosen by its stack's rules, the stacks keyed by the prefix of the standards' shards (`PY`, `NET`, `NODE`, `TSR`), and a stack shard with no row in the registry fails a test. One reader of test declarations serves both rules, so neither recognises a test, a suite or an attribute section of its own.

**D3. Read by tokens.** A test file is read as tokens with comments and whitespace dropped and strings kept whole, so a marker or a body is never read from a comment or from the inside of a string.

**D4. One violation per skipped test.** A skipped test is one violation at its line, however many markers mark it. A marker on a suite header applies to each test inside the suite, a JavaScript declaration with no callback is skipped, and a marker that marks no test counts once at its own line, except a C# attribute on anything but a test or a suite, which counts nothing. Focusing markers count, because they exclude the other tests from the run. An expected failure runs the test and does not count.

## Consequences

- A skipped test already in the tree stays until someone removes it, and a test added under a skipped suite is a rise.
- A skip moved from one file to another keeps the count.
- Known limit: a skip decided at run time by a condition the lexer cannot see, a framework's own configuration file or a skipping helper under another name, is not counted.
- Rejected: one violation per marker, because a test added under a skipped suite would be invisible.
- Rejected: an assertion-count heuristic, because issue 1464 found it mostly false positives.
- Rejected: committed fixture files, because the suites build each fixture in a temporary git world.
