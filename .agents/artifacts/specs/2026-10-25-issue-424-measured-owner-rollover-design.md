# Measured owner rollover: a context meter hook, a 120k ceiling and a mid-phase hand-off — issue 424

Design for https://github.com/fagenorn/nix-config/issues/424. A bare "Dn" cites this
spec's ledger. Base: `04a39660` (origin/main). Blocker
https://github.com/fagenorn/nix-config/issues/421 is closed (merged as PR 426).

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "changes workflow-state progress default context ceiling and adds a PreToolUse hook that rewrites progress commands"}, "concurrency_or_persistence": {"value": "hit", "evidence": "once-per-crossing injection needs persisted per-agent state across hook invocations"}, "open_design_questions": {"value": "hit", "evidence": "hook output shape (updatedInput vs deny), coexistence ordering with the lifecycle guard, and crossing-state storage are open"}, "criteria_shape": {"value": "hit", "evidence": "seven acceptance criteria, two of them eval evidence on mbp"}}, "paths": ["home/common/claude-code/default.nix", "home/common/claude-code/README.md", "home/common/agent-skills/scripts/workflow-state.py", "home/common/agent-skills/skills/from-issue/SKILL.md", "home/common/agent-skills/tests/test_workflow_state.py", "home/common/agent-skills/tests/test_workflow_skill_contracts.py", "python/agent_tools/context_meter.py", "python/tests/test_context_meter.py", "justfile"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

An issue owner is meant to hand its work to a fresh owner before its context grows too
large, but in practice that almost never happens:

- **The count is guessed.** The phase gate (`workflow-state progress`) takes the owner's
  context size as `--context-tokens`, and the model supplies it. In 14 days, 958 of 1,659
  progress calls left it out and the rest passed round guesses (median 85,000), because
  nothing gives the model a real number. An unknown count is not a budget signal, so the
  gate almost never hands off.
- **The ceiling is too high.** The 150k ceiling (hand-off at 140k) lets owners grow well
  into the range where every reread is expensive. Rereads above 120k cost about $2.2k list
  price per 14 days.
- **The gate only runs between phases.** Owners grow inside Phase 6 (SDD) and Phase 7
  (ship), where no gate runs for a long time. General-purpose owners peak at a median of
  181k and a p90 of 316k.

## Solution

A new `PreToolUse` hook on Bash, the **context meter**, measures the calling agent's real
context size from its own transcript and gives the gate that number. The ceiling drops to
120k with 10k headroom, and the meter also starts the existing hand-off in the middle of
a phase:

1. **Measured count.** On every Bash call that runs `workflow-state progress`, the meter
   reads the agent's own transcript, takes the last API call's input + cache-read +
   cache-creation tokens, and rewrites the command to carry that value as
   `--context-tokens`. Any value the model wrote is replaced. Every other command passes
   through untouched.
2. **New ceiling, one home.** The phase-budget defaults live in one package module.
   `workflow-state progress` takes its defaults from it, and so does the meter's hand-off
   threshold (ceiling minus headroom: 110,000). Skill text stops restating the numbers and
   stops asking the model to report context usage.
3. **Mid-phase trigger.** When an owner's measured context reaches the threshold, the meter
   injects one instruction, once per crossing: at the next safe point, run the phase gate
   and obey its action. The gate, now fed the measured count, returns `handoff`, and the
   owner takes the existing hand-off path (handoff → resume pack → fresh owner). No
   checkpoint call is added to skill text.
4. **Next to the guard.** The meter is a second command hook on the same Bash matcher as
   the fail-closed lifecycle guard. It never grants or denies anything, and the only text it
   changes is the value of one option, so the guard's verdict on the original command still
   holds for the rewritten one.

## Decisions

### The meter command

- An `agent_tools` command, `context-meter`: a thin command module plus one command-table
  row, registered by its store launcher path, with no arguments, as a second command hook
  in the existing `matcher = "Bash"` PreToolUse entry. Its timeout is 10 s. Only Bash calls
  reach it (per D1, D2).
- Input: the hook payload on stdin. Output: nothing (pass through), or one JSON object
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput"?, "additionalContext"?}, "systemMessage"?}`.
  `updatedInput` is the whole Bash `tool_input` with only `command` replaced. The output
  never contains `permissionDecision`, `decision` or `continue`, and the meter never exits
  with 2 (per D3, D6).
- Policy lives in importable functions grouped by reason to change, behind the thin shell:
  where the agent's transcript is and how its last call's context is read; how a progress
  invocation is recognised and rewritten, and which commands make an agent an owner; and
  the per-agent crossing state. The plan picks the module boundaries (agent-helpers rules 1–2).

### Measurement (per D4)

- Own transcript: a payload with `agent_id` reads
  `<dirname(transcript_path)>/<session_id>/subagents/agent-<agent_id>.jsonl`; one without it
  reads `transcript_path`. If `session_id` or `agent_id` is not a plain identifier, the
  path is empty, or the file is missing or unreadable, the call is **unmeasured**.
- Measured context: `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`
  from the newest `type: "assistant"` record whose `message.usage` is an object and whose
  model is not `<synthetic>`. In a main transcript, records with `isSidechain: true` are
  skipped. The file is read backwards from the end within a fixed byte window, a partial
  last line is skipped, and finding no qualifying record inside the window means unmeasured.
  When PreToolUse fires, the record that carries the current tool call is already written,
  so the value is the context of the call that issued the command.

### Progress rewrite (per D5)

- A progress invocation is a word whose basename is `workflow-state` followed directly by
  the word `progress`, wherever it sits in the command. Every such invocation is rewritten.
- Rewrite: from the start of the invocation to the end of its simple command, remove every
  spelling of the option that argparse would take as `--context-tokens` (separate value,
  `=value`, unique abbreviation), then insert `--context-tokens <measured>` directly after
  `progress`. When the call is unmeasured, the options are removed and nothing is inserted,
  which leaves the count unmeasured. All other bytes, the ceiling and headroom flags
  included, stay as they are.
- Proof: the rewrite is emitted only if tokenising the result gives the original words
  minus the removed option words plus the inserted pair. A command that fails to tokenise,
  or whose rewrite fails the proof, passes through unchanged (per D3).
- Each rewritten call gets a one-line `additionalContext` note naming the measured value
  (or saying the call was unmeasured). This puts the evidence in the eval transcript
  (per D10).

### Owners and the crossing (per D8, D9)

- Threshold: `CONTEXT_CEILING − CONTEXT_HEADROOM` from the phase-budget module, compared
  as `measured ≥ threshold`, the same comparison the gate uses.
- An agent becomes an **owner** the first time it runs `workflow-state progress`,
  `workflow-state mark-progress` or `sdd-gate` carrying `--action-id`. The meter records
  this as persisted per-agent state. Unregistered agents never get the instruction.
- Per-agent state: one small JSON file per `(session_id, agent_id or main)` under
  `~/.agents/state/context-meter/`, holding `{owner, notified}`. It is written only for
  owners, and every read-modify-write happens under an exclusive `flock`, so parallel tool
  calls cannot inject twice. If an agent has no state file and the call is not a
  registering command, the meter returns without reading the transcript.
- For an owner, each measured call works as follows:
  - **Measured below the threshold:** clears `notified`. This re-arms the trigger after a
    compaction.
  - **First measurement at or above the threshold:** sets `notified`. The instruction is
    injected unless the call is itself a progress call, because the gate already acts on
    that measurement.
  - **Later calls still above the threshold:** inject nothing.
  - **Unmeasured calls:** change nothing.
  
  A fresh owner is a new agent with fresh state.
- Known limitation: if the guard happens to deny the same call that carries the crossing
  instruction, the instruction may never reach the model. It is not resent until the next
  crossing. Because the guard refuses only malformed lifecycle verbs, this is rare.
- The instruction is one `additionalContext` paragraph. It names the measured tokens and the
  threshold and says: at the next safe point (the step in hand committed, no worker you
  dispatched still running), run your phase gate (`workflow-state progress` for your last
  completed phase, with truthful booleans) and obey its action. It also says the notice
  will not be repeated. Progress already accepts a repeated phase number, so this needs no
  new `workflow-state` interface.

### Failure posture (per D6)

- The meter never blocks work. A malformed or non-Bash payload passes through silently, and
  so does a non-progress call it cannot measure.
- If a progress call was recognised but the meter could not measure it or prove the
  rewrite, it adds a `systemMessage` naming the reason. The user sees this; the model does
  not.
- An unexpected exception exits 1 with the exception on stderr. Claude Code shows that as a
  non-blocking hook error, and the tool call still runs.

### Phase-budget defaults (per D7)

- A new package module, `agent_tools.phase_budget`, is the only home of the four
  phase-budget defaults: turn ceiling 120 and turn headroom 2 (unchanged), context
  ceiling 120000 and context headroom 10000.
- `workflow-state progress` takes its argparse defaults from this module (it already
  imports `agent_tools`), and the meter computes its threshold from it. No other file
  restates the defaults. Explicit ceiling flags keep working, which is what the tests use.
- `select_phase_action` does not change. One effect is expected: a non-direct run's
  measured self-contained `delegate` needs both a turn count and a context count. With the
  context count now always measured, that branch can fire whenever the model also reports
  turns, which is how it was designed to work.

### Skill text (per D11)

- `from-issue` phase gate: drop the sentence that restates the four ceiling values. Drop
  the context-token request but keep the turn-count clause (observed when available,
  never fabricated).
- The line for runs without lifecycle identity names the ceilings as
  `workflow-state progress`'s defaults instead of giving numbers.
- `rollover.md` and `delegated-owner.md`: drop "with truthful available usage".
- Net effect: the instruction load shrinks.

### Registration and docs (per D1, D12)

- The settings attrset's Bash PreToolUse entry lists the guard and then the meter. The
  guard's own registration is unchanged. The command list in the installed-layout launcher
  test gains `context-meter`.
- The Claude Code module README gains a short section on the meter: what it rewrites, what
  it injects, where its state lives (never pruned, a documented limitation), and that it
  grants nothing. The detailed contract stays in the meter's module docstring and
  `python/README.md`.

## Test seams

1. **The meter command** (new hook test module, added to `just agent-workflow-tests`):
   tests run `python -m agent_tools.context_meter` with a PreToolUse payload on stdin,
   fixture transcripts in a temporary projects directory, and `HOME` set to a temporary
   directory. They assert only on stdout JSON and the exit code. Prior art: commands driven
   from source (agent-helpers rule 5), as in `tests/test_lane_triage.py`. Cases:
   - The issue's 87,412 fixture: a progress command with no count and one with a wrong
     count (separate, `=` and abbreviated forms) both come out carrying exactly 87412. A
     non-progress command produces no output.
   - The crossing: 105k → 112k → 118k injects exactly once. Dropping below 110k and
     crossing again injects a second time.
   - A non-owner is never notified.
   - A progress call at or above the threshold sets `notified` without injecting.
   - The subagent transcript path is derived from the payload.
   - Synthetic and duplicated-usage records are handled correctly.
   - An unmeasured progress call loses the model's value and carries a `systemMessage`.
   - Malformed input passes through.
   - No output ever carries a permission decision.
   - A compound command such as `workflow-state progress … && git push origin x` comes out
     differing only in its `--context-tokens` words.
2. **`workflow-state progress` CLI** (`test_workflow_state.py`'s progress helper): with no
   ceiling flags, measured 110000 gives `handoff` and 109999 gives `continue`. Existing
   fixtures that pass explicit values stay as they are.
3. **Skill text** (`test_workflow_skill_contracts.py`): the positive pin on the restated
   ceilings becomes the assertion that the `from-issue` text names no `--context-ceiling`,
   `--context-headroom` or `--context-tokens` argv (agent-helpers rule 6).
4. **Settings and guard** (`tests/test_claude_permission_guard.py`, run against the built
   settings and base policy as the Claude Code README describes; it is not part of
   `just agent-workflow-tests`): discovery finds exactly the guard and the meter in the one
   Bash entry and checks the guard's registration as before. The adversarial table is
   unchanged and green.
5. **Instruction Budget**: `just agent-instruction-budget` passes without the raise label.
6. **Evidence** (per D12): on mbp, a tree-mode run
   `EVAL_TREE=<worktree> EVAL_SETTINGS=<built settings> just evals from-issue 1`. The eval
   transcript's progress notes show that every gate call carried a measured count, the
   `just agent-costs` peak-context table shows no owner call above 125k, and the eval
   verdict passes.

## Out of scope

- Turn ceilings, and measuring the turn count. Turn defaults move into the shared module
  but keep their values, and the turn count stays model-reported.
- Hand-off mechanics: the `handoff`, `delegate`, resume-pack and relaunch paths are not
  changed.
- Metering agents that are not owners: the Phase-7 ship-issue agent, workers, reviewers,
  the orchestrate-issues dispatcher and interactive sessions without lifecycle identity.
  An owner resumed into inline Phase-7 shipping is registered only at its next
  progress-type call (a residual).
- Codex and other hosts without hooks: their progress calls simply carry no count, so the
  context is unmeasured and the gate keeps its current behaviour for unknown usage.
- Pruning the meter's state directory; any change to `agent_costs`; moving `workflow-state`
  into the package.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The meter is an `agent_tools` command (`context-meter`, one command-table row), registered by store launcher path as a second command hook in the existing Bash PreToolUse entry, timeout 10 s; the guard's registration is unchanged | agent-helpers rules 1–2 (helpers are package commands, thin shells); guard README: the guard is standalone because it is a fail-closed trust boundary | a standalone file beside `lifecycle_guard.py` (that isolation serves the guard's trust boundary, and the meter needs the shared default); folding the meter into the guard (one fail-closed hook cannot also be a fail-open measurement) |
| D2 | Matcher `Bash` only: the meter sees Bash calls for both the rewrite and the crossing check | token economy / YAGNI; owners run Bash every few calls (git, workflow-state, launch-scope), which keeps detection lag short | an all-tools matcher (a Python process before every Read/Grep/Edit of every agent on the machine, for a lag Bash already keeps short) |
| D3 | The rewrite is `updatedInput` without `permissionDecision`: it grants nothing, the guard judges the original command, the rewritten command differs only in `--context-tokens` words (proved by re-tokenising), and any doubt means pass through | Claude Code 2.1.302 hook pipeline: every matching hook receives the original input, a blocking hook denies whatever another hook rewrote, and a decision-less rewrite is judged by the normal permission flow; issue: "coexists with the fail-closed lifecycle guard" | `permissionDecision: "allow"` with the rewrite (would auto-approve a whole compound command past the allowlist and the auto classifier); denying and asking the model to resend (blocks work and costs a turn) |
| D4 | Context is read from the agent's own transcript (subagent: `<dir>/<session>/subagents/agent-<id>.jsonl`; main: `transcript_path`), as input + cache-read + cache-creation of the newest non-synthetic assistant record with usage, read backwards within a bounded window; this is the same sum agent-costs uses for `peak_ctx` | the PreToolUse input schema of the pinned binary (no agent transcript path on PreToolUse; `agent_id` only in subagents); the on-disk transcript layout; issue's definition | using `transcript_path` for subagents (it is the session's main transcript); a full-file scan on every call (cost grows with the transcript) |
| D5 | Every `workflow-state progress` invocation drops all spellings argparse accepts for `--context-tokens` and gets `--context-tokens <measured>` right after `progress`; an unmeasured call keeps only the drop; ceiling and headroom flags pass untouched | issue: "the hook's value always wins", "replacing any value the model supplied"; the 14-day data shows the model's values are guesses | appending a last-wins value (leaves the guess in the command and depends on argparse order); keeping the model's value when unmeasured (a guess must never drive the gate); overriding ceiling flags (not requested) |
| D6 | Failure posture: never exit 2 or deny; expected unmeasured cases pass silently; a recognised progress call the meter could not measure or rewrite gets a user-visible `systemMessage`; an unexpected exception exits 1 (a non-blocking hook error) with the error on stderr | the-bar: fail loud, the log stream is the debugger; issue: a measurement hook must never block work | fail-closed (would block owners on a transcript-format change); silent exit 0 on an exception (hides a broken meter) |
| D7 | A new `agent_tools.phase_budget` module is the one home of the phase-budget defaults (turn 120/2 unchanged, context 120000/10000); `workflow-state progress`'s argparse defaults and the meter's threshold import it | the-bar DRY (one home per constant); `workflow-state` already imports `agent_tools`; issue: "one authoritative default" | constants inside the hook module (`workflow-state` would depend on the hook); moving only the context pair (splits one concept across two homes) |
| D8 | An agent is an owner once it runs `workflow-state progress`, `workflow-state mark-progress` or `sdd-gate` with `--action-id`; only owners get the crossing instruction | issue: "an owner's measured context"; skill call map: these commands carry an owner's own identity, and delegated Phase-6 and resumed SDD owners reach `sdd-gate` long before their first progress call | every agent (would push a hand-off notice into workers, reviewers, the dispatcher and interactive sessions); progress only (misses delegated and resumed owners for a whole phase, where the growth is); any `--action-id` command (the dispatcher's `owner-liveness`/`check-launch` and ship-issue's `register-worker` carry an id that is not their own); reading prompt text (ties the meter to wording) |
| D9 | Crossing state is one JSON file per (session, agent) under `~/.agents/state/context-meter/` holding `{owner, notified}`, read-modify-write under `flock`; first measurement at or above the threshold sets `notified` (and injects unless it is a progress call), a measurement below it clears `notified`, and the files are never pruned (documented) | the `~/.agents/state/` precedent (guard, fleet, adopt); parallel tool calls need an atomic once; issue: "once per crossing and never on every turn" | the temp directory (its location varies by environment); Claude's projects directory (owned by Claude Code); scanning the transcript for an earlier notice (rereads the whole file on every call) |
| D10 | Both model-facing texts use `additionalContext`: the once-per-crossing instruction (run the phase gate at the next safe point and obey it), and a one-line note on each rewritten progress call naming the measured value | Claude Code delivers `additionalContext` to the model as a transcript attachment; the transcript keeps the model's original tool input, so the rewritten value would not show up there otherwise | `systemMessage` for the instruction (only the user sees it); no progress note (the evidence criterion could not be read from the eval transcript) |
| D11 | Skill text: the phase gate drops the restated ceilings and the context-token request (the turn-count clause stays), the line for runs without lifecycle identity cites the defaults by reference, the rollover and delegated-owner files drop "with truthful available usage", and the skill-contract pin becomes a negative argv assertion | issue: skills stop restating the numbers and stop asking for usage, with no new checkpoint calls; agent-helpers rule 6; the Instruction Budget gate | also dropping turn-count reporting (the turn budget is out of scope); adding a mid-phase checkpoint step to the skill text (forbidden by the issue) |
| D12 | Verification: the hook test module joins `just agent-workflow-tests`; the guard suite runs against the built settings as its README describes (it is not in that recipe), with discovery updated for exactly {guard, meter}; evidence comes from the tree-mode eval on mbp with `EVAL_SETTINGS` set to the built settings, plus `just agent-costs`, with no `just switch` | `run-eval.sh` tree mode applies a given settings file's hooks; the host is mbp; `just switch` is not authorized | switching to install the hook (not authorized); leaving the evidence for the ship phase (tree mode can produce it now); adding the guard suite to the recipe (it needs a built result) |
