# Foreground verification and in-turn waits stop the forced-suspend cascade, issue 261

## Problem

The repository's verification commands (`just agent-workflow-tests` at about
8 to 10 minutes, `just build` at up to 15 minutes under load) run past the
host's Bash ceiling. Claude Code does not kill a command that outlives its
timeout. It moves the command to the background and tells the agent that it
will be notified. A dispatched implementer, fixer, reviewer or ship owner then
ends its turn while that job is still live. Its owner receives the host's
interim notice ("This agent stopped with background work of its own still
running … the result below may be interim"). It replies with text only and is
left with no live child. The host treats that reply as the owner's last turn
and forces a hand-back, and the owner suspends `blocked_on=external`. Over 29
runs this caused about 60 relaunches, ≈226 M re-orientation tokens and more
than 5 hours of wall time. It also left orphaned children that needed
`TaskStop`, and produced phantom agent spans of many hours.

Host facts, read from the pinned Claude Code 2.1.284:

- The Bash default timeout is 120 s and the maximum is 600 s.
  `BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS` override them, and the
  effective maximum is never below the default.
- A command that exceeds its timeout is *moved to the background*, not killed.
  A message that arrives while a command is running also moves that command to
  the background.
- A subagent's stall watchdog is deferred while one of its tools is in flight,
  so a long foreground Bash call does not get the subagent reaped.
- When a child stops while its own background work is still running, the
  notification says so and calls the result possibly interim. A message sent
  to a stopped agent resumes it from its transcript.

## Solution

Three changes land together, one per link in the cascade (per D1):

1. **The host allows a long foreground command.** The managed settings `env`
   sets `BASH_MAX_TIMEOUT_MS` to 60 minutes, so an explicit timeout can cover
   the longest verification command with headroom (per D2).
2. **A leaf agent never ends its turn on its own live command.** A third
   leaf-agent clause joins the two existing ones: run long commands in the
   foreground under an explicit timeout, wait inside the same turn if the host
   backgrounds one anyway, and never end the turn while a command you started
   is still running. It reaches every dispatched role through the existing
   carriers, and through the four Claude agent definitions (per D3, D4).
3. **An owner treats an interim child result as still running.** One canonical
   owner paragraph classifies the host's interim notice as not a completion and
   prescribes re-engaging the same child. It forbids a text-only reply, a
   suspension and a replacement for it. The dispatcher gets the matching
   classification for an owner's interim notice (per D5, D6).

Suspension semantics are unchanged. A usage limit, a transport failure, a human
gate or an attempt deadline still suspends exactly as before. An interim child
result is simply not one of them.

## Decisions

### Managed settings

`settings.env` gains `BASH_MAX_TIMEOUT_MS = "3600000"` next to the existing
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`. `BASH_DEFAULT_TIMEOUT_MS` stays unset,
so the default remains 120 s. The explicit per-command timeout is the
mechanism, and the 60-minute ceiling is what makes it expressible (per D2).
`just show-claude-settings` prints the new key. The architecture document's
Claude Code section gains one sentence naming the key and why it exists.

### The third leaf-agent clause

The clause text is defined in exactly one place: the dispatch-contract
test's clause table, under the id `own-commands`. Every carrier repeats it
verbatim because a pasted template carries no link into the subagent's context:

> Run each long command, every verification command included, in the foreground with an explicit timeout above its expected duration. If the host moves one to the background anyway, wait for it within the same turn: never end your turn while a command you started is still running.

- **Carriers.** All nine existing carriers (the five sdd prompt templates, the
  ship-owner prompt, the orchestrated owner prompt, and the from-issue and sdd
  leaf-clause sections) carry it exactly once in their rendered region, beside
  the two existing clauses. Both leaf-clause paragraphs that say "these two
  sentences" now say three. The orchestrated owner prompt already cites the
  from-issue section, so its blockquote gains the clause and nothing else.
- **Agent definitions.** `implementer`, `mechanic`, `reviewer` and
  `reviewer-lite` carry the same clause once in their body (the text after
  the frontmatter). They join the carrier set for this clause only and do not
  take the other two (per D4). That covers typed dispatches that no carrier
  composes, such as ship-issue's review dispatches, and a fresh fix-round
  dispatch.
- **How to wait is outcome-specified.** The clause states the outcome: hold
  the result before reporting, and do not let the turn end on a live command.
  It names no tool. The waiting primitive is host-version-specific, and the
  explicit timeout makes backgrounding the exception rather than the path
  (per D3). The clause avoids the literal background-dispatch flag, which the
  nested-workflow contract forbids outside orchestrate-issues.
- **Ship's CI watch is unchanged.** Its chunked `timeout 300` foreground watch
  already satisfies the clause, because its Bash timeout exceeds the command's
  own bound. The clause generalizes that rule to every command. It does not
  replace the watch's retry protocol.

### The owner rule: interim child results

One canonical paragraph, headed **Interim child results**, appears
byte-identical (whitespace-normalized) in from-issue's dispatch rules, in
sdd's report handling and in ship-issue's review phase. Each skill can run
without the others, so each one carries the rule. A test pins that the copies
stay identical, which is the configured-review-paragraph precedent (per D5).
It says, in order:

1. A child return the host marks interim (it stopped with background work of
   its own still running, or its result may be interim) is not a completion:
   the child is still running.
2. Re-engage that same child by its recorded agent identity. Message it to
   wait for its own job inside its turn and then return its final report, and
   wait for that report. The owner may end its own turn while the re-engaged
   child is live, because the host wakes it with the child's next
   notification. That is a child's work, not a command the owner started.
3. Never answer it with a text-only reply, never suspend for it (it is not an
   `external` wait), and never dispatch a replacement or stop the child.
4. A registered lifecycle worker stays registered under its existing worker
   id. An interim result is not the `returned` event, and re-engagement is not
   a resume, so it registers nothing new.
5. If the message cannot be delivered, the child is one the owner cannot wait
   for. Follow the existing Writing-workers route (task-stop, then release
   `--event stopped`), and then the skill's ordinary handling of a lost child.
   This is the one case that may lead to a fresh dispatch (per D8).
6. Only the child's final hand-back counts as its result.

The rule's other surfaces point to that paragraph and do not restate it:

- The from-issue suspension procedure's "an external wait" gains a
  parenthetical that excludes a child's interim result.
- AUTO.md's Phases 2–4 subagent section gains one line that routes an interim
  result to the paragraph.

**The dispatcher variant.** orchestrate-issues classifies host notifications
by task handle. A new first case, ahead of "owner return without a terminal
write", covers an owner launch's notification that the host marks interim.
The owner is still running, so the dispatcher sends no observation, runs no
`check-launch`, writes nothing, stops no task and relaunches nothing. The same
handle notifies again with the owner's real return. Without this case an owner
that correctly waits on a re-engaged child would be observed `unavailable` and
relaunched. That is the cascade moved one level up (per D6).

## Test seams

All of these are existing seams. The plan adds no new test surface.

- **Dispatch contracts** (`test_dispatch_contracts.py`). The clause table
  gains `own-commands`. A carrier declares the clause ids it must hold: the
  nine existing carriers hold all three, and the four agent definitions,
  enrolled with a frontmatter-stripping region kind, hold only
  `own-commands`. The existing source-tree, stray-copy, mutation
  (remove/relocate/duplicate/region-break) and enrolment tests then cover the
  new clause unchanged. The installed-tree test keeps checking the skill
  carriers it already checks.
- **Workflow skill contracts** (`test_workflow_skill_contracts.py`). This is
  the section/`normalized`/`assert_ordered` anchor style. One test pins the
  canonical paragraph's ordered anchors and its identity across the three
  skills. One pins the suspension and AUTO pointers. One pins
  orchestrate-issues' interim case: its anchors, and that it precedes case (a).
- **Built settings** (`tests/test_claude_permission_guard.py`, run against the
  artifact `just show-claude-settings` prints). It asserts that
  `env.BASH_MAX_TIMEOUT_MS` is `"3600000"`, which meets the 30-minute floor,
  and that `BASH_DEFAULT_TIMEOUT_MS` is absent.

Verification is `just build` and `just agent-workflow-tests`, each run in the
foreground with an explicit timeout.

## Out of scope

- Host-contention scheduling. The deferral in
  `.agents/knowledge/rejections/host-contention-scheduling.md` stands. This
  changes how agents wait, not how host load is scheduled.
- `workflow-state` semantics: suspension states, the `blocked_on` set, worker
  registration verbs and the anti-zombie bound.
- Declaring per-command expected durations in the project contract.
- Codex configuration and the Codex orchestrate stub. The shared-tree text
  reaches Codex unchanged, and the owner rule is conditional on a host notice
  Codex never emits.
- Rewriting CI-MERGE.md's rationale for the 300 s watch (its "reaped when
  silent" premise predates the in-flight watchdog deferral), and the watch's
  retry protocol.
- Making ship-issue's review dispatches leaf-clause carriers. The agent
  definitions cover them.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Fix all three links (host ceiling, leaf clause, owner and dispatcher classification) in one change | Issue's "three parts land together"; the cascade survives any one link left in place | Settings only: a message still backgrounds a running command, and owners still misread interim notices |
| D2 | `BASH_MAX_TIMEOUT_MS="3600000"`; leave `BASH_DEFAULT_TIMEOUT_MS` unset (120 s) | Binary: the max is the ceiling for an explicit timeout; issue example 60 min ≥ 30-min floor; YAGNI and reversibility | Raise the default too: every accidental hang, including interactive main-session ones, would block for many minutes, and the explicit timeout makes it unnecessary |
| D3 | A third leaf-agent clause (`own-commands`) in all nine carriers, outcome-worded with no tool named | Dispatch-contract precedent (one constant, verbatim carriers, exactly-once); the-bar Token economy; the waiting primitive differs by host version | A shared standard document linked from prompts: a pasted prompt carries no link, which is why the leaf clauses exist |
| D4 | The four Claude agent definitions also carry the clause, enrolled as clause-specific carriers | The stray-copy guard reads agent definitions, so a copy there must be enrolled; covers ship-issue's typed reviews and Claude dispatches no template composes; templates still needed for Codex, which has no agent definitions | Agent definitions only: Codex and general-purpose owners would lose the rule. Templates only: ship-issue reviewers would be uncovered |
| D5 | One canonical **Interim child results** paragraph, identical in from-issue, sdd and ship-issue, test-pinned for identity; the worker stays registered; the owner may end its turn on a live re-engaged child | Configured-review identical-copy precedent; each skill runs standalone; sdd's resume-by-identity precedent; the host wakes an owner with a live child; `returned` would falsely release a live worker | Single home in from-issue only: sdd and ship-issue run without it. Owner blocking in-turn on the child: there is no host primitive to block on an agent |
| D6 | orchestrate-issues gains an interim-owner case, first in its classification order, that sends no observation and relaunches nothing | Its case (a) would observe a waiting owner `unavailable`, which is the cascade one level up; the issue's demo requires no relaunch | Leave the dispatcher alone: an owner following D5 would be relaunched |
| D7 | Settings are pinned in the built-settings test, not by parsing Nix source | That test already asserts the generated surface; acceptance names the generated `settings.json` | A source-level grep of `default.nix`: it tests text, not the artifact the host reads |
| D8 | Grill: an undeliverable re-engagement message falls back to the existing Writing-workers stop-and-release route; a delivered one keeps the original registration | from-issue Writing workers ("a background worker this owner cannot wait for is first stopped … released with `--event stopped`"); launch fence (#222) keeps a stopped worker from committing | Suspending `external` on a failed send: that is the cascade this issue removes. Re-registering on re-engagement: it would leave two live ids for one agent and block the owner's suspend/finish |
