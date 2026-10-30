# Claude-compatible wait guidance, and ending the turn on another session's blocker — issue 474

Issue: https://github.com/fagenorn/nix-config/issues/474. This was designed autonomously
(`from-issue --auto`), so every call made without the user is a row in the Decision ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "doubt", "evidence": "the no-wait-loops leaf-agent clause is a pinned dispatch contract (test_dispatch_contracts.CONTRACTS) copied into nine carriers; its wording changes, no schema or code interface does"}, "concurrency_or_persistence": {"value": "no", "evidence": "skill prose and contract tests only; no locking, ledger or persisted state touched"}, "open_design_questions": {"value": "no", "evidence": "the issue names both Claude-compatible wait forms and the end-the-turn rule; only exact wording remains"}, "criteria_shape": {"value": "no", "evidence": "three acceptance criteria, each verified by a contract test or just agent-workflow-tests"}}, "paths": ["home/common/agent-skills/skills/from-issue/SKILL.md", "home/common/agent-skills/skills/from-issue/ship-handoff.md", "home/common/agent-skills/skills/sdd/SKILL.md", "home/common/agent-skills/skills/sdd/implementer-prompt.md", "home/common/agent-skills/skills/sdd/task-reviewer-prompt.md", "home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md", "home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md", "home/common/agent-skills/skills/sdd/re-review-prompt.md", "home/common/claude-code/skills/orchestrate-issues/SKILL.md", "home/common/agent-skills/tests/test_dispatch_contracts.py", "home/common/agent-skills/tests/test_workflow_skill_contracts.py"]}
Verdict: {"hits":["contract_change"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

Every prompt that from-issue, sdd and orchestrate-issues send to a subagent carries the
`no-wait-loops` leaf-agent clause: "if a wait is truly needed, run one bounded foreground
`sleep N`, then check once." Claude Code agents follow it by putting the check in the same
call as the sleep (`sleep N && <check>`).

The pinned Claude Code (2.1.310, read from the store) refuses that call. Any Bash call whose first
command is `sleep N` with N ≥ 25, outside `run_in_background`, is refused:
`Blocked: sleep N followed by: …`, or `Blocked: standalone sleep N` when nothing follows. The
refusal names the fix itself: "use Monitor with an until-loop … To wait for a command you
started, use run_in_background: true. Do not chain shorter sleeps to work around this block."

The Oct 21–30 retro counted 23 such refusals in 4 sessions. It also found owners blocked on bare
`sleep 1800`–`3000` calls while they waited for children. The skill text and the harness disagree,
and each refusal costs the agent a turn.

There is a second gap. from-issue does not say what an owner does when its work waits on an
owner or issue that another session holds. Its Suspension procedure lists "an external wait" but
does not name this case, so an owner polls a session it cannot influence.

## Solution

1. Rewrite the clause in its one authoritative constant and in all nine carriers at the same
   time. The new clause names the waits Claude Code accepts.
2. In from-issue's Suspension procedure, name a blocker that another session owns as an
   external wait: the owner ends the turn and never polls it.
3. Add one contract class to `test_workflow_skill_contracts.py`. It bans the chained form across
   the skill trees, asserts both wait forms at each former site and asserts the rule in from-issue.
4. Raise no instruction ceiling.

## Decisions

### The clause (AC 1, AC 2)

The `no-wait-loops` constant in the dispatch-contract suite becomes, exactly:

> Never loop `sleep` in the foreground or chain a check onto it: use Monitor with an
> until-condition, or one short bare `sleep N` call and check in the next.

- **Meaning.** A wait that lasts until a condition holds goes to Monitor. Its until-loop runs in
  the background and notifies the agent once, which is the form the harness's own refusal
  recommends. A short fixed wait is one bare `sleep N` call with nothing chained to it, and the
  check goes in the following call. A foreground `until`/`while` loop around `sleep` stays
  banned, as #309 decided. Repeating short sleeps is polling, so the clause says "one". Per D1
  and D2.
- **Carriers.** The nine skill carriers change together and keep their regions: the five sdd
  prompt fences (implementer, task reviewer, re-review, correctness, conformance), the
  ship-handoff fence, the orchestrate-issues owner-prompt blockquote, from-issue's **Leaf-agent
  clauses** quote and sdd's `## Agent tiers` quote. Each region holds the clause exactly once,
  wrapped the way that carrier already wraps its text. The issue counted seven sites. The two
  SKILL.md quotes are the sources the prompts are pasted from, so they change too.
- **Unchanged.** The agent definitions keep only `own-commands` (#309 D10). The remainder
  prompt's placeholder still forwards "the four leaf-agent clauses", and the other three
  clauses are untouched.

### The end-the-turn rule (AC 2)

In from-issue's `## Suspension procedure`, the external-wait item becomes:

> an external wait (a blocker another session owns: end the turn, never poll)

This replaces "(never a child's interim result)". The **Interim child results** paragraph in
the same file already says that rule: "never suspend for it (it is not an `external` wait)". The
procedure already records the state: `workflow-state suspend --blocked-on external` writes it,
and the `Suspended (…)` line is the last thing the owner emits. The new text only names the
cross-session case and forbids polling it. Per D3.

### The contract test (AC 1–3)

Add a new class to `test_workflow_skill_contracts.py`, docstring-tagged #474. It follows
`HandBuiltTimeContractsTest` (#309 D9):

- **Ban.** No `*.md` under the three `SKILL_TREES` (shared, Claude-only, Codex) may match
  either of two shapes. Each document is read with its `>` quote markers removed.
  1. Prose, checked after whitespace normalization: a `sleep …` code span followed by
     ", then check" (the retired family).
  2. Shell, checked line by line: a `sleep <arg>` that opens a command, at the start of a line
     or code span, and is followed by `&&`, `||` or `;`.

  A pattern self-test proves what the shapes match. It hits the retired clause,
  `sleep 30 && gh pr checks 1` and `sleep 60; workflow-state …`. It spares
  `` `sleep <wait_seconds>` ``, "background `sleep <wait_seconds>`; every wait",
  `until <check>; do sleep 2; done` and the new clause.

  The ban fails before the change on all nine carriers. The issue counted 7 matches over the
  sites it listed.
- **Per site.** A literal tuple in the test lists the nine former sites. Each site, read as its
  carrier wraps it (line breaks, indentation and `>` markers removed), must name
  "Monitor with an until-condition" and "bare `sleep N` call".
- **from-issue.** The `## Suspension procedure` section must hold "a blocker another session
  owns: end the turn, never poll".

The full clause text keeps one home, the constant. Per D4.

### Budget (CI gate)

`just agent-instruction-budget` must pass without the `instruction-budget-raise` label. Ceilings
may be lowered but never raised.

Measured at be429270, the tightest profiles are:

- implementation-owner, hot: 7 clause copies, 18 B of headroom.
- from-issue-controller, hot: 1 copy, 45 B.
- orchestration-dispatcher: 41 B.

The new clause is 155 B and the old one 158 B. The end-the-turn rule adds 26 B. Applying both
edits, with each carrier re-wrapped at its own width, and measuring them with the gate's own
`measure` gives these hot changes: implementation-owner +5 B, controller +23 B,
orchestrated-issue-owner +8 B and dispatcher −1 B. Every profile stays under its ceiling. The
final wrapping can move these numbers by a few bytes. The gate, run on the real diff, decides.
Per D5.

### Grill refinements

- **A Monitor is a command the agent started.** The `own-commands` clause, which comes just
  before this clause, still decides whether an agent may end its turn while a Monitor runs.
  Claude Code 2.1.310 lets a subagent that stopped with background work running resume when that
  work reports, and it marks the subagent's return to its parent "may be interim". from-issue's
  **Interim child results** paragraph already handles that return. This issue adds no protocol
  for it. Per D6.
- **The dropped parenthetical keeps a tested home.** "(never a child's interim result)" occurs
  only in from-issue's Suspension procedure. Its rule stays in the Interim child results
  paragraph, which `test_the_paragraph_states_the_rule_in_order` pins in order.
- **The ban was prototyped at be429270.** Run over the three trees, the prose shape matched
  exactly the nine carriers and the shell shape matched nothing. Every spared fixture stayed
  clear, and so did the new clause.
- **No glossary or ADR change.** No context map or decision-record path is bound
  (`knowledge.context` unsupported). The choice is a wording change that is easy to reverse.

## Test seams

- **The dispatch-contract suite (existing).** Its per-carrier presence check reads the source and
  installed views. Its stray-copy guard and mutation checks cover the new clause through the
  changed constant alone, with no code change.
- **The new class in `test_workflow_skill_contracts.py`.** It covers the ban, the per-site forms
  and the from-issue rule. Its pattern self-test follows #310's `ObserverSleepExampleTest`
  date-pattern test, and its retired-wording ban follows #317's `STALE_TURN_END_WORDING`.
- **The instruction-budget gate.**

Verification bindings: `just agent-workflow-tests` and `just build`. The plan also runs
`just agent-instruction-budget`.

## Out of scope

- orchestrate-issues' one-shot background observer `sleep <wait_seconds>` and its wait-ID
  rules. It is not a chained foreground check, and the ban's shapes spare it.
- An end-the-turn rule in orchestrate-issues, sdd, ship-issue or the leaf-agent clauses.
- Codex-specific wording and the Codex orchestrate stub.
- Agent definitions, the `own-commands` clause, and how an owner waits for its own background
  child beyond what this clause says.
- Any hook, lifecycle-guard rule, helper or settings change that enforces waits.
- Raising, or deliberately tightening, instruction ceilings.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The clause becomes the exact text in Decisions. Monitor with an until-condition comes first. The bare-sleep form is "one short bare `sleep N` call", checked in the next call. No numeric threshold. | Issue: "Monitor with an until-condition, or a bare `sleep` as its own call followed by the check in the next call". Claude Code 2.1.310 refuses a first-command `sleep N` (N ≥ 25), chained or standalone, points to Monitor and says "Do not chain shorter sleeps". Phase-0 disposition 1. | Stating "under 25 s": a host-version detail copied nine times, and the harness's refusal already redirects. An unbounded "bare sleep as its own call": it invites the standalone `sleep 1800` the retro saw. |
| D2 | One host-neutral clause stays in the shared tree. It names Monitor for Claude, and the one-short-bare-sleep form also serves Codex. There is no Claude-only variant. | CLAUDE.md: skills are single-sourced, and Codex reads the shared tree. The-bar DRY. Phase-0 disposition 4. | A Claude-only clause or a Codex override: the carrier suite would have to tell two clause texts apart, for a host that never hit the refusal. |
| D3 | The end-the-turn rule goes in from-issue's Suspension procedure. The external-wait item reads "(a blocker another session owns: end the turn, never poll)" and replaces "(never a child's interim result)". It is not added to the leaf clauses or to orchestrate-issues. | The issue requires it in from-issue only. Suspension already records `blocked_on` and ends the turn. The Interim child results paragraph already says the dropped rule (DRY). D5's budget. | A carrier clause: about 50 B × 7 hot copies breaks implementation-owner's 18 B headroom, and leaf agents never hold a cross-session blocker. Keeping the parenthetical: it repeats a rule the same file states. |
| D4 | The AC test is one new class in `test_workflow_skill_contracts.py`. It holds a structural ban (retired "`sleep …`, then check" prose, and a sleep-first shell chain) with a pattern self-test, two clause tokens at each of the nine literal former sites, and D3's fragment in the Suspension section. | ACs 1–2 name this file and "asserts both phrases at each site". A user instruction outranks Layer 2 (standards README), and rule 6 already allows carrier-clause pins. Rule 3 forbids the `sys.path` edit that importing CONTRACTS would need. Precedents: #309 D9 and #317. | Testing only in the dispatch-contract suite: it misses the AC's file and the per-site form check. Importing CONTRACTS or CARRIERS: a new `sys.path` edit. Matching any "sleep … check" prose: it gives false positives on the new clause. |
| D5 | No instruction ceiling rises. The clause shrinks by 3 B (155 against 158) to fund D3's +26 B, and the gate must pass with no label. | CLAUDE.md: only the user applies `instruction-budget-raise`. Headroom measured at be429270: implementation-owner 18 B over 7 copies, controller 45 B, dispatcher 41 B. | Raising a ceiling: it would park an autonomous ship on a human gate for a wording change. |
| D6 | An agent that arms Monitor and then ends its turn is left to the existing rules: `own-commands`, and the Interim child results re-engagement. Neither the clause nor this issue adds a wait-for-Monitor protocol. | Issue: "changes the Claude-facing guidance only". The host's own refusal names Monitor to every agent. Claude Code 2.1.310 resumes such an agent and marks its return to the parent "may be interim", which from-issue already handles. | A new in-turn wait rule for monitors or background children: a protocol change that no acceptance criterion asks for, paid for in hot bytes across seven carriers. |
| D7 | Plan: the #474 class checks each former site over its whole document (`>` markers removed, whitespace normalized), not over the carrier region. Its self-test spares the new clause through the fragment after the `sleep N` span, not the full text. The shell shape's argument excludes backticks, so `` `sleep <wait_seconds>`; `` stays spared. | D4: the region renderers, and the exactly-once-in-region check, live in `test_dispatch_contracts.py`, and importing them needs a `sys.path` edit (rule 3). The full clause keeps one home. Prototyped at edc73af8: 28 failures before, none after. | Copying the region renderers into the new class: a second carrier model. The full new clause as a fixture: a second home that drifts from `CONTRACTS`. |
