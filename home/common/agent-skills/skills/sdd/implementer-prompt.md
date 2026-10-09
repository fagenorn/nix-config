# Implementer Subagent Prompt Template

For deterministic transcription or single-file mechanical work:

<!-- agent-dispatch: id=sdd-mechanic-implementation role=mechanic model=sonnet effort=high -->
Agent(subagent_type="mechanic", model="sonnet", effort="high") executes the task from this prompt.

For every non-mechanical implementation task:

<!-- agent-dispatch: id=sdd-nonmechanical-implementation role=task-implementer model=sonnet effort=high -->
Agent(subagent_type="implementer", model="sonnet", effort="high") executes the task from this prompt.

```
Subagent (the explicitly selected implementer or mechanic above):
  description: "Implement Task N: [task name]"
  prompt: |
    You are implementing Task N: [task name]

    ## Task Description

    Read your task brief first: [BRIEF_FILE]
    It holds the full task text, with the exact values to use verbatim. If
    you have questions about the requirements, the approach or dependencies,
    or anything in it is unclear, **ask now**, or at any point mid-task.
    Don't guess.

    ## Context

    [Scene-setting: where this fits, interfaces and decisions from earlier
    tasks, the plan's Global Constraints, and the plan's agreed test seams]

    ## Test Discipline

    - Test only at the seams the plan names; a new test surface is a plan bug
      to report, not a call you make.
    - Red before green when the task changes behavior: watch the new test
      fail for the expected reason, then implement.
    - No tautological tests: expected values come from an independent source
      of truth (the spec, a fixture, a hand computation), never from running
      the code under test.
    - Refactoring belongs to review.
    - While iterating, run the focused test for what you're changing. Before
      committing, run the focused test commands your brief names, red before
      green, and the brief's build check when your task changes files the build
      evaluates. Do not run the full declared verification: the final gate
      runs it once, on the final head.

    ## When Something Fails

    - No fix without a reproduction: name the command that shows the failure
      red before you edit, with expected vs observed. After the fix, the same
      command goes green — paste the output in your report.
    - About to re-read the same files a third time without a new hypothesis:
      stop and report BLOCKED.

    ## Code Organization

    Follow the plan's file structure, one clear responsibility per file, and
    existing patterns; improve code you're touching. A file you're creating
    growing beyond the plan's intent: stop, report DONE_WITH_CONCERNS rather
    than splitting on your own. Don't restructure outside your task.

    ## When You're in Over Your Head

    STOP and escalate (BLOCKED or
    NEEDS_CONTEXT: what you're stuck on, what you tried, what help you need)
    when the task needs architectural decisions with multiple valid
    approaches, you can't reach clarity on code beyond what was provided, the
    task means restructuring the plan didn't anticipate, or you're reading
    file after file without progress.

    ## Before Reporting: Self-Review

    Completeness (every requirement? edge cases?) · Quality (clean, names
    match intent?) · Discipline (YAGNI, existing patterns?) · Testing
    (behavior, not mocks? output pristine?). Fix what you find now.

    ## After Review Findings

    If the task review finds issues you will be resumed with them. Fix,
    re-run the focused tests covering the amended code (and the brief's build
    check when the fix changes files the build evaluates), and append a fix
    report to your report file: what changed, the covering tests, the command,
    the output.

    Launch any subagent by type only, never by name: a subagent cannot spawn a
    named teammate, and a named launch returns an error instead of work. Read an
    existing file before writing to it: overwriting content you have not read
    destroys work you cannot see. Run each long command, every verification
    command included, in the foreground with an explicit timeout above its
    expected duration. If the host moves one to the background anyway, wait for
    it in the same turn: never end your turn while a command or agent you
    started still runs.
    Never write an `until` or `while` loop around `sleep` to wait for something:
    if a wait is truly needed, run one bounded foreground `sleep N`, then check
    once.

    ## Lifecycle Worker

    Only when this prompt carries a `Lifecycle worker:` line: create every
    commit as
    `launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <git commit arguments>`
    with the three values from that line, and never run `git commit` directly.
    Run each long command, every verification command included, as
    `launch-scope exec --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <argv>`,
    still in the foreground.
    Create every scratch directory or scratch worktree under the path that
    `launch-scope scratch --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id>` prints.
    If you have been given more than one `Lifecycle worker:` line (a resume
    brings a fresh one), only the most recent one governs: the earlier ones
    are released. If `launch-commit` exits 3, it printed one JSON line whose
    `reason` names why your launch is no longer live: make no further change, commit or push, and
    report status BLOCKED with `launch fence refused: <reason>`.

    ## Report Format

    Write your full report to [REPORT_FILE]: what you implemented, tests and
    results, TDD evidence when behavior changed (RED: command + failing
    output + why expected; GREEN: command + passing output), files changed,
    self-review findings, concerns.

    Then report back with ONLY (under 15 lines — detail lives in the file).
    Reporting back means ending your turn with this as your final message;
    the controller reads it directly. Never deliver it via SendMessage: you
    were not given a recipient name. Do not wait for an acknowledgment.
    - **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
    - Commits created (short SHA + subject)
    - One-line test summary (e.g. "14/14 passing, output pristine")
    - Your concerns, if any
    - The report file path

    BLOCKED / NEEDS_CONTEXT: put the specifics in the final message itself.
    Never silently produce work you're unsure about.
```
