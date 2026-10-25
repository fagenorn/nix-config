# Owner hand-off economics: a dollar-per-issue replay, a lifecycle eval and the threshold sweep — issue 432

Design for https://github.com/fagenorn/nix-config/issues/432 (body as edited 2026-10-25T12:20Z,
with the threshold-sweep comment). A bare "Dn" cites this spec's ledger. Base: `48481846`
(origin/main). Related: https://github.com/fagenorn/nix-config/issues/424 (meter),
https://github.com/fagenorn/nix-config/issues/431 (direct relaunch),
https://github.com/fagenorn/nix-config/issues/423 (keepalive, not built here).

## Triage

input: {"signals": {"contract_change": {"value": "hit", "evidence": "workflow-state progress/ledger gain a hand-off cap and start baseline; agent-costs gains a report; eval harness gains toggles"}, "concurrency_or_persistence": {"value": "hit", "evidence": "a per-attempt hand-off counter and launch context baseline persist in the workflow ledger"}, "open_design_questions": {"value": "hit", "evidence": "eval design (live vs replay), guard threshold and boot-slimming shape are open"}, "criteria_shape": {"value": "hit", "evidence": "six acceptance criteria, two are evidence-only"}}, "paths": [...run-eval.sh, agent_costs.py, context_meter.py, workflow-state.py, attempt_custody.py, from-issue SKILL.md, resume-pack.md, tests/test_agent_costs.py]}
verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

The #424 meter made owners hand off at 110k, but nobody knows whether that saves money.
Today a change can be judged only in context sizes, or in dollars after days of live data.

- **Hand-offs can cost more than they save.** A hand-off at context C into a fresh owner
  that boots to B saves the read price on C − B for each later call, and pays the write
  price on B once. Owners run on Claude Opus 5.5, whose cache read is 0.05× base input
  (D2), not the 0.1× the issue assumed. Break-even is therefore about 25·B/(C − B) calls:
  about 25 calls at B = 60k and C = 120k, about 125 at B = 100k, never when B ≥ C.
- **Fresh-owner boots are large.** In the two sessions on this host on 2026-10-25 (39 owner
  transcripts, before and after the meter deploy), 24 relaunched owners reached their first
  gate call at a median of 98k (p25 83k, p75 131k), from a median start of 29k. In
  jarbird #45 a Phase-6 owner reached 135k in two minutes. Most of that was sdd's
  whole-package plan read (eight task members, part of it re-read from a persisted tool
  output) and an early read of `ship-handoff.md`. It crossed 110k and handed off at once.
- **The 120k ceiling was never optimised.** It is the round line of a one-off cost study
  (Oct 10–24), adopted by #421 and #424. That study ignores boot cost and cache expiry.
- **Idle waits are a counter-force.** A wait over the 5-minute subagent TTL rewrites the
  whole context at 1.25×: 107 such rewrites in those 39 transcripts, a median of 3 per
  owner. Big contexts pay more each time.
- **Small waste.** 30 of the 39 owners ran `workflow-state progress --help` once before
  their first gate call, because `progress` needs eight flags and the skill gives none.
- **The evals cannot see any of this.** From-issue eval 1 has no lifecycle identity, and
  orchestrate-issues eval 7 stops at the first control step. The fixture is too small to
  cross 110k, tree mode still runs the deployed `workflow-state` and meter, and
  `agent-costs` has no per-issue dollars, boots, hand-off chains or trial variance. It also
  prices Opus 5.5 at Opus-5 rates: input +25%, reads 2.5×.

## Solution

Two layers, measurement first (D1):

1. **Owner report and replay in `agent-costs`.** A new `--report owners` builds one
   lineage per issue from transcripts that carry lifecycle identity. A lineage is every
   owner launch plus everything those owners dispatched. The report prices each call at
   current per-model list prices and reports list-price dollars per delivered issue, peak
   context, boots, cache deaths, hand-offs and the variance across issues or eval trials.
   `--policy` arms replay the same lineages under counterfactual hand-off policies:
   threshold (with a sweep and a per-phase variant), boot slimming, just-started guard,
   hand-off cap, keepalive on/off and no `--help` call. Each arm is compared with the
   current policy on paired per-issue differences, and the report says keep or reject
   (D5, D7, D8).
2. **A lifecycle-identity pipeline eval.** From-issue eval 8 runs `/from-issue 4 --auto` on
   a seeded multi-task issue, in tree mode, through the direct route: real gates,
   the tree's meter, hand-offs, Phase 6, the entry to Phase 7, and at least one owner wait
   on a child longer than five minutes. Its trials calibrate the replay and confirm the kept
   combination against a baseline arm, within a stated spend cap (D15).

Candidates are judged in the replay first. Only the kept ones are built into the product,
each in its own commit with contract tests (D9). The live eval then confirms the kept
combination against the baseline arm. The plan sequences five vertical slices:

- **S1. Pricing and the owner report.** Observed accounting, lineages, delivered issues,
  eval grouping and JSON output.
- **S2. The replay.** Policy arms, the sweep and the decision rule.
- **S3. The harness and eval 8.** Tree shims, the derived settings, `EVAL_POLICY`, the
  `tracked-issue` setup and eval 8 itself. The baseline trials start right after this
  slice and run in the background.
- **S4. The kept candidates,** one commit each.
- **S5. Evidence.** Live candidate trials, the A/B report and the user verdict.

## Decisions

### Pricing (per D2)

- `agent_costs` prices each call by model ID, not by family. Rows are per MTok: input,
  output, 5-minute write, 1-hour write and cache read. They come from the Anthropic pricing
  page, fetched 2026-10-25:
  - Opus 5.5: 4 / 20 / 5 / 8 / 0.20.
  - Opus 5 and 4.5–4.8: 5 / 25 / 6.25 / 10 / 0.50.
  - Sonnet 5.5: 2 / 10 / 2.50 / 4 / 0.10.
  - Sonnet 5: 2 / 10 / 2.50 / 4 / 0.20.
  - Sonnet 4.5 and 4.6: 3 / 15 / 3.75 / 6 / 0.30.
  - Haiku 5.5 by request prompt size: up to 100k 0.10 / 0.50 / 0.125 / 0.20 / 0.01; over
    100k 0.50 / 2.50 / 0.625 / 1 / 0.05.
  - Haiku 4.5: 1 / 5 / 1.25 / 2 / 0.10.
  - Fable 5.1: 10 / 50 / 12.50 / 20 / 0.25. Fable 5: 10 / 50 / 12.50 / 20 / 1.
- An ID with a date suffix matches its base row. Any other ID is priced at its family's
  newest row, and the footer counts those calls as approximate. `<synthetic>` costs nothing.
- The table and the source URL and date live in one place. All three reports (issues,
  cache, owners) read it, so the cache report's figures move too. The Codex stratum's
  pricing does not change.

### The owner report (`agent-costs --report owners`, per D3, D4, D17)

- **Owner transcript.** A transcript is an owner's when one of its Bash tool calls is a
  registering command, as `context_meter_commands` recognises it (`workflow-state
  progress`, `mark-progress` or `sdd-gate` with `--action-id`), carrying `--run-id` and an
  `--action-id` of the form `<issue>:<attempt>:<launch>`. A root transcript can be an owner
  (the direct controller of Phases 0–5).
- **Lineage.** One lineage per `(run_id, issue)`. Its owner launches are ordered by launch
  ordinal, then first timestamp; two transcripts may share an action ID (controller and
  delegated owner).
- **Descendants.** Every other transcript is attributed by walking its `.meta.json`
  `parentAgentId` up to the nearest owner transcript. A subagent with no parent sits under
  its session's root transcript. Anything that reaches no owner is unattributed, and the
  footer shows its count and dollars.
- **Calls.** One reader serves the cache report and the owner report (D17). It merges
  usage per message ID, keeps start and end times, tool names, Bash command text and Agent
  tool-call IDs, and applies the cache report's death rule (gap > TTL − 10 s, TTL 300 s for
  a subagent and 3,600 s for a root, rewrite > 50% of a context above 5k).
- **Per-transcript facts:**
  - start context, peak context and calls;
  - the registering call's context (the boot end, `B`, of a relaunched or delegated owner);
  - the phase of each call (D5);
  - observed gate calls with their `--phase`, booleans and whether they carried
    `--handoff-path`;
  - `progress --help` calls;
  - `mark-progress` calls;
  - long child waits: a gap over 300 s while an Agent child the transcript dispatched is
    still out.
- **Delivered.**
  - A live lineage is delivered when one of its transcripts ran `workflow-state finish` and
    the reply reports the delivery merged. That transcript may be an owner or a descendant,
    since the ledger-only bookkeeper often runs `finish`. The plan pins the reply field from
    a real finish reply and tests it on a fixture.
  - An eval trial is delivered when its results row's verdict is `PASS`.
  - Dollars per delivered issue = all attributed spend of the lineages or trials in scope,
    undelivered ones included, ÷ the delivered count. Undelivered spend is also shown on
    its own line.
- **Eval grouping.** `--eval-results <results.jsonl> --eval <skill>:<id>` groups by trial
  instead of issue. Each row's `workdir` selects the project directories whose name starts
  with the mangled sandbox path (every non-alphanumeric character becomes `-`). Its arm is
  `(tree_rev, policy)`.
- **Output.** Text by default, `--format json` for asserts and the A/B report. There are
  six tables:
  1. Per lineage or trial: launches, hand-offs, boots, deaths, long child waits, peak, owner
     dollars, total dollars, delivered.
  2. Per arm: n, delivered, dollars per delivered issue (mean and sample sd), peak p50/p90.
  3. Fresh-owner boots by phase: count, `B` p50/p90, start p50, boot calls p50, and slimmable
     tokens p50 (D12).
  4. The simulated arms.
  5. Calibration.
  6. The footer: pricing source, approximate calls, unattributed spend and the comparative
     telemetry disclaimer.
- **Flags.** Window, `--projects-dir` and `--top` behave as for `--report cache`;
  `--project` and `--artifacts` are refused.

### The replay (per D5, D7, D8, D9)

- **Arms.** Each `--policy NAME=SPEC` names one arm; `--sweep` adds the sweep arms of D7.
  The baseline arm is always computed: the current policy, with a 110k threshold for every
  phase, no guard, no cap, observed boots, keepalive off and help calls kept.
- **Policy grammar.** A SPEC uses the product knobs of `agent_tools.phase_budget` (D6):
  `threshold=<tokens>`, `threshold:<a>-<b>=<tokens>`, `guard=<tokens>` and `cap=<n>`. It
  adds replay-only knobs: `boot=observed|slim`, `keepalive=off|on` and `help=keep|drop`.
- **Identity replay.** Replaying a lineage with its observed decisions reproduces its
  observed dollars exactly. A unit test pins this, and the calibration table prints it.
- **Normalisation.** Before any arm is applied, each observed `handoff` relaunch is undone:
  - the fresh owner's boot calls are removed;
  - its later calls get back the context the hand-off cut (C − B);
  - the outgoing owner's hand-off overhead calls are removed.

  Transfers that do not depend on the policy stay as observed in every arm: `fresh_start`,
  `delegate`, the Phase-5 rollover and the ship owner.
- **Shift model.** An arm hands off at call k (context C), in working phase p. Every later
  call keeps its observed increments, output and timestamps, but its context drops by
  C − B(p), added up over successive hand-offs. The cut comes out of the call's cache-read
  part first, then its write part (a death call's rewrite). Every call after the hand-off is
  priced as a subagent's, at the 5-minute write price under the 300 s death rule, because a
  fresh owner is always a subagent.
- **Boot model.** A fresh owner's boot is m(p) calls whose context grows linearly from the
  start size S to B(p). Each call writes its increment at the 5-minute price, reads the
  prefix before it and adds the median boot output. The outgoing owner adds h calls at C,
  and the relauncher one wake call. S, m, h and B(p) come from the corpus's observed boots
  and hand-offs. Where the corpus has none, the defaults are S = 29k, m = 20 and h = 6, and
  the report prints which applied. The calibration table compares each observed boot's real
  cost with its modelled cost.
- **Hand-off point.**
  - **Mid-phase.** A registered owner's mid-phase hand-off falls on the first Bash call at
    or after its context reaches the crossing threshold, with no Agent child of that owner
    still out (the safe point). The crossing threshold is `phase_budget.crossing_threshold`
    (D6, D10).
  - **Phase boundary.** An observed phase-boundary gate is re-decided with
    `phase_budget.select_phase_action`, using the call's own booleans, the run's direct flag
    and the arm's threshold for the next phase. A run is direct when one of its lineage's
    owners acquired through `workflow-state direct-owner`; the run ID cannot tell, since
    new runs are all `rel_` IDs. A `handoff` answer there hands off; the guard does not
    apply there (D10).
- **Phase of a call.** The working phase is one more than the last `--phase` reported at or
  before the call. Calls before the transcript's first gate call take the phase that call
  reports. A transcript registered first by `sdd-gate` or `mark-progress` is in Phase 6.
- **Cap.** With `cap=n`, a hand-off is skipped while the lineage's consecutive hand-offs
  since its last phase advance or `mark-progress` call number n or more (D11).
- **Keepalive.** With `keepalive=on`, each idle gap over the TTL costs ⌈gap/270 s⌉ − 1
  cache reads of the prefix at the model's read price (an idealised `max_tokens: 0`
  keepalive), and the death rewrite is not charged (D14).
- **Help.** `help=drop` removes each `progress --help` call: its own cost, and the growth
  its result added to every later context of that transcript (D13).
- **Slim boots.** `boot=slim` replaces each fresh owner's B with B − slimmable, for observed
  boots and simulated ones alike. Slimmable is the context growth caused by the boot's
  tool results that read plan task members other than the resumed task's (including a
  persisted tool output re-read of them) and `ship-handoff.md` before Phase 7 (D12). The
  live candidate arm measures the real slim B, and the report states the difference.
- **Known bias.** The shift model does not see a fresh owner's later re-reads of what its
  predecessor knew, so it favours hand-offs. The A/B report states this. An arm that hands
  off more often than the baseline is kept only if the live arm confirms it (D18).
- **Evaluation order (D18).** Arms are evaluated as a coordinate pass, because a slimmer
  boot moves the best threshold:
  1. boot mode;
  2. the threshold sweep under the chosen boot mode;
  3. the guard sweep, then cap, then help, each at the choices so far;
  4. keepalive, for information only;
  5. the final combination against the baseline arm.
- **Simulated-arms table.** One row per arm:
  - dollars per delivered issue;
  - mean paired saving per lineage against the baseline arm, over every lineage in scope
    (delivery does not change between arms), with its one-sided 90% lower bound
    (mean − 1.2816·sd/√n) and the share of lineages that save;
  - hand-offs, deaths and peak p90 per issue;
  - `keep` or `reject` (D8).

### Policy home (`agent_tools.phase_budget`, per D6)

- `phase_budget` stays the one home of the gate's budget policy. It holds a frozen
  `PhaseBudget` value with these fields and defaults: turn ceiling 120, turn headroom 2,
  context headroom 10,000, a hand-off threshold per phase (110,000 for every phase), guard
  (0, off) and cap (none). Around it are four functions:
  - `parse(spec)` for the knob grammar above; an unknown key or a bad value raises
    `ValueError`.
  - `current()`: the defaults, overridden by the environment variable `AGENT_PHASE_BUDGET`
    (the same grammar) when it is set. It is read once per process.
  - `handoff_threshold(budget, phase)`.
  - `crossing_threshold(budget, phase, baseline)`: the phase threshold, raised to
    baseline + guard when a guard is on and the baseline is known.
- `select_phase_action` moves unchanged from `workflow-state` into this module.
  `workflow-state progress` imports it, and so does the replay. Its context comparison
  reads the threshold for `--phase` + 1, the phase the context is carried into. Explicit
  `--context-ceiling` and `--context-headroom` flags still override it.
- The meter's crossing threshold and `progress`'s defaults both come from `current()`.
  Production never sets `AGENT_PHASE_BUDGET`. Only the eval harness does (D15).
- So that every knob `parse` accepts holds in the meter as well as the gate, the meter's
  per-owner state record gains `phase`, the owner's working phase. It is `--phase` + 1 of
  the owner's last progress call, or 6 for an owner registered by `sdd-gate` or
  `mark-progress`. Until then it is unknown, and the threshold of the default phase table
  applies. A record written before this change is accepted, and gains the field at its next
  write. This ships with the policy home (S3), whatever the sweep chooses (D6).

### The live eval (from-issue eval 8) and the harness (per D15, D16)

- **The eval.** Eval 8, `lifecycle-owner-economics`, is a pipeline eval with setup kind
  `tracked-issue`, the fifth closed kind. It takes no parameters, and the fixture repo
  itself stays unchanged apart from the new issue file and its slow test. The setup:
  - writes a read-only tracker and forge shim, `<WORK>/bin/gh`, and puts `<WORK>/bin` first
    on the run's `PATH`, which every agent of the run inherits;
  - switches the sandbox copy's tracker binding to `github`, `fixture/tinytask` (capability
    supported), then commits and pushes that on `main` in the sandbox;
  - logs every shim call to `<WORK>/gh-calls.jsonl`.
- **The shim** serves the GitHub calls owners actually make:
  - `gh issue view <n>`, as text or `--json <fields>` with optional `--jq`, built from
    `issues/<nnn>-*.md`: state open, no labels, no comments, no blockers;
  - `gh api` sub-issue and dependency reads answer `[]`;
  - `gh pr list` answers `[]`, `gh pr view` answers "no pull requests found";
  - `gh auth status` succeeds;
  - `gh issue comment` and `gh issue edit` succeed and are logged.

  Every other call, `gh pr create` and `gh pr merge` included, exits 1 naming the verb, so
  delivery stops at the forge boundary in Phase 7.
- **The seeded issue.** `issues/004-*.md` asks for one feature across tinytask's model,
  store and CLI: about four plan tasks, with docs. One acceptance criterion requires
  `TINYTASK_ACCEPTANCE=1 python3 -m unittest tests.test_acceptance` to pass. That test,
  added to the fixture, takes about 5½ minutes and is skipped unless the variable is set,
  so the ordinary fixture suite stays fast.
- **Prompt.** The usual resolver preamble and authorisation to self-answer every decision,
  plus the fact that the sandbox forge cannot publish, so the run ends when ship-issue stops
  there.
- **Asserts.** They read a scratch copy of the trial's project directories through
  `agent-costs --report owners --format json`:
  1. a ledger attempt for issue 4 with lifecycle identity reached phase ≥ 6;
  2. every owner gate call carried the meter's measured note;
  3. some owner call reached ≥ 110,000 context;
  4. Phase 7 was entered: a ship owner was dispatched, or the ledger records the Phase-6
     gate's `delegate`;
  5. at least one owner long child wait;
  6. the feature branch's ordinary suite passes and the feature is present.

  A trial that fails any of these is `FAIL`, not a cost sample. Eval 8 is tree mode only:
  its asserts run the tree's `agent-costs` (`PYTHONPATH=$EVAL_TREE/python`). In deployed
  mode they fail and say so.
- **Acquisition probe.** Before the first paid trial, a sandbox built by the setup is driven
  by hand through `workflow-state direct-owner`, with the shim's tracker observation, to
  `kind: owner`. This proves the route before any model spend.
- **Invocation and spend.** The documented invocation is `EVAL_MODEL=opus EVAL_TIMEOUT=7200
  EVAL_MAX_USD=40 EVAL_TRIALS=2 EVAL_TREE=<checkout> EVAL_SETTINGS=<settings>
  [EVAL_POLICY=<spec>] just evals from-issue 8`. The live evidence is two arms of two trials
  each, at most four trials and $160 in total:
  - the baseline arm, at the S3 head, before any candidate lands;
  - the candidate arm, at the final head.

  Two runner invocations may run at once.
- **Tree mode.**
  - It gains a `workflow-state` shim: `PYTHONPATH=<tree>/python python3 -P
    <tree>/home/common/agent-skills/scripts/workflow-state.py`.
  - It writes a derived settings file under its temporary root: `EVAL_SETTINGS` with every
    hook command that names the `agent-tools-context-meter` launcher replaced by the shim
    `<root>/bin/context-meter`. The run passes that file to `--settings`. A settings file
    with no meter hook is an error before any sandbox. The guard's entry is unchanged.
  - Calls an agent makes by the absolute `~/.agents/bin/workflow-state` path still reach the
    deployed helper. The owner report counts them per trial, and the A/B report states them
    as a condition.
- **`EVAL_POLICY`.** It is accepted only with `EVAL_TREE`, and is validated before any
  sandbox by the tree's `phase_budget.parse`. That parser accepts only the product knobs,
  so the replay-only `boot`, `keepalive` and `help` are refused there. It is exported to
  the claude run as `AGENT_PHASE_BUDGET`, and each results row records it as `policy`
  (null when unset).

### Candidates: what ships if kept (per D9–D14)

- **Threshold (D7).** The sweep's chosen value, or values per phase group, becomes
  `PhaseBudget`'s default. Choosing 110k for every phase changes nothing. Only a numeric
  arm can be chosen; `never` is reported as a reference (D27).
- **Boot slimming (D12).**
  - In `sdd`, initial validation stays the only whole-package read, and it is done once per
    ledger. When `progress.md` already names the plan (a resume), the owner reads the root
    header and only the resumed task's member, through its Task-index link.
  - In from-issue's fresh-owner guidance (`delegated-owner.md` and the resume-pack index
    line), `ship-handoff.md` is read when Phase 6's gates pass, not at boot.
  - Both edits are byte-neutral or smaller per profile. They are toggled by tree revision.
- **Just-started guard (D10).**
  - The meter's per-owner state record gains `baseline`, the measured context of the call
    that registered the owner. It lives in the meter's state, not the ledger. A record
    written before this change gets one at its next measured call.
  - The crossing fires at `crossing_threshold(current(), phase, baseline)`. The re-arm rule
    is unchanged, with "below the threshold" read against that same value. Phase-boundary
    gates are not guarded.
  - Swept at G ∈ {0, 20k, 40k, 60k}.
- **Hand-off cap (D11).**
  - Ledger attempts gain `handoff_streak`, an integer that defaults to 0. Schema 11 brings a
    10 → 11 migration that adds 0. Each gate's `phase_inputs` also record the streak and cap
    it decided with (D25).
  - `progress` with `--handoff-path` adds 1. A `progress` whose phase passes the attempt's
    phase resets it to 0, and so does `mark-progress` `advanced`.
  - `select_phase_action` answers `continue` where its context branch would answer `handoff`
    once the streak is at or above `cap`.
  - Simulated at cap ∈ {1, 2, 3}.
- **No `--help` (D13).**
  - `progress` and `suspend` take `--issue` and `--attempt` as optional and derive them from
    `--action-id`; when both are given they must agree, and a call needs one or the other.
  - The phase-gate paragraph of from-issue's `SKILL.md` swaps its flag prose for one literal
    template:

    ```
    workflow-state progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> --phase <completed> --next-needs-context <bool> --artifacts-sufficient <bool> --remainder-self-contained <bool> | artifact-budget validate-report --boundary workflow-response --input -
    ```

    It adds `--turn-count <n>` only when the count is observed.
  - The suspension template drops `--issue` and `--attempt`. Net bytes do not grow.
- **Keepalive (D14).** This is replay only. Its simulated value is reported for #423, and
  nothing ships.

### A/B report and verdict (per D8)

- The A/B report is a section of the plan's acceptance record. It is pasted from
  `agent-costs --report owners` output and the eval rows, and covers:
  1. the corpus (window, lineages, owners, delivered, broken down by project and by before
     or after the meter deploy), the pricing source and the identity-replay check;
  2. the baseline policy's dollars per delivered issue;
  3. the threshold sweep table, the chosen value and why;
  4. each candidate alone and in the final combination: dollars, saving, bound, keep or
     reject;
  5. the live arms: per-trial dollars and verdicts, mean ± sd, and the calibration (the
     candidate arm as the replay predicts it from the baseline trials, against the candidate
     trials' observed cost);
  6. the conditions: host, Claude Code version, absolute-path calls.
- The PR body closes with the user verdict: what works, what does not, the measured
  numbers and the recommended route (including what the keepalive simulation means for
  #423).

### Docs

- `python/README.md` (agent-costs) gains the owners report contract, the pricing source and
  the replay model.
- `evals/README.md` gains the workflow-state shim, the derived settings, `EVAL_POLICY` and
  `policy`, the `tracked-issue` kind and eval 8's invocation and cost.
- If a kept candidate touches them, the Claude Code README's meter section (guard and
  phase) and the agent-skills README's Lifecycle helpers (cap, identity derivation) are
  updated too.

## Acceptance criteria

Refined from the issue; "Measured by" names the check.

- **AC1** [code] Eval 8 launches owners with lifecycle identity (direct `--auto`) on a
  fixture issue that crosses 110k, reaches Phase 6, enters Phase 7, and includes an owner
  wait on a child over 300 s. Measured by: a trial's asserts over its transcripts (measured
  gate notes, peak, ledger phase, long child wait).
- **AC2** [code] `agent-costs --report owners` reports list-price dollars per delivered
  issue at per-model prices, peak context and per-issue or per-trial variance, for live
  transcripts and for eval runs (`--eval-results`). Measured by: unit tests on fixture
  transcripts covering a boot, a cache rewrite after a TTL gap, a hand-off chain and eval
  grouping.
- **AC3** [code] Each candidate is a replay toggle that applies to any eval run or live
  corpus: the threshold with the sweep and the per-phase variant, boot slimming, the guard,
  the cap, keepalive and help. The live harness toggles the threshold knobs and any kept
  guard or cap through `EVAL_POLICY`, and tree-revision candidates through `EVAL_TREE`.
  Measured by: replay unit tests and the harness test.
- **AC4** [evidence] The A/B report gives the baseline's and each candidate's dollars per
  delivered issue with variance, which were kept and which rejected with their numbers, and
  the threshold sweep. The sweep covers at least 90k, 110k, 140k and 170k, and the
  per-phase grid when boots differ by phase. The report names the chosen value and why.
- **AC5** [code] Kept candidates are merged with contract tests. `just agent-workflow-tests`,
  `just agent-instruction-budget` (no raise label) and `just build` pass.
- **AC6** [evidence] In eval 8, the candidate arm's mean dollars per delivered trial is
  below the baseline arm's, and every trial's verdict is `PASS`. If no candidate is kept,
  the report says so instead and AC6 is reported as not met.

## Test seams

1. **`agent-costs --report owners` from source** (agent-helpers rule 5). Tests run
   `python -m agent_tools.agent_costs` over fixture transcripts in a temporary projects
   directory, with `.meta.json` parents, and assert on its JSON and text output. The
   transcripts have production shapes: usage repeated per content block, a `<synthetic>`
   record, Opus 5.5 and Opus 5 models. Cases:
   - a relaunched owner's boot from 29k to 98k;
   - a 6-minute gap with a full rewrite, priced as a 5-minute write;
   - a two-launch hand-off chain with a worker child;
   - delivered and undelivered lineages in the dollar formula;
   - eval grouping from a results fixture (two arms × two trials, mean and sd);
   - the Haiku 5.5 tier switch at a 100k prompt;
   - an unknown model priced approximately.

   Prior art: `tests/test_agent_costs.py` and the cache report tests.
2. **The replay** (the same module, `--policy` and `--sweep`). Cases:
   - identity replay equals observed;
   - the never-hand-off arm undoes the chain: the boot is removed and later contexts rise
     by C − B;
   - a 140k arm moves the hand-off and cuts later contexts by C − B(p);
   - a hand-off waits for an outstanding Agent child;
   - keepalive turns a death into pings;
   - the guard defers a crossing until baseline + G;
   - cap 2 blocks the third consecutive hand-off, and a `mark-progress` resets it;
   - `help=drop` removes the call and its growth;
   - `boot=slim` subtracts the task-member and `ship-handoff.md` reads;
   - the keep rule on a constructed corpus: one clear win, one inside the noise.
3. **`phase_budget`** (imported). Cases: the grammar, the `AGENT_PHASE_BUDGET` override, an
   unknown key raising, per-phase thresholds, `crossing_threshold`, and the moved
   `select_phase_action` keeping its existing test table.
4. **`workflow-state progress` and `suspend` CLI** (`test_workflow_state.py`). Cases:
   identity derived from `--action-id`, a mismatch refused, and the defaults read through
   `current()` at `--phase` + 1. If the cap is kept, also its streak transitions, the
   migration and a `continue` at the cap.
5. **`context-meter` command** (`tests/test_context_meter.py`). Cases: the crossing uses
   `current()` under `AGENT_PHASE_BUDGET`; phase tracking crosses at a per-phase threshold;
   an old two-key record is accepted and upgraded. If the guard is kept, also its baseline.
6. **Eval harness** (`test-run-eval-tree.sh` with the fake claude, and
   `test_eval_cases.py`). Cases:
   - the `workflow-state` shim runs the tree's script;
   - the derived settings point the meter at the shim and leave the guard;
   - a settings file with no meter hook is refused;
   - `EVAL_POLICY` is validated, exported and recorded, and refused without `EVAL_TREE`;
   - the `tracked-issue` shim answers `issue view` and `pr list`, refuses `pr create`, and
     logs every call;
   - eval 8's shape, with the closed setup kinds.
7. **Skill text** (`test_workflow_skill_contracts.py`, agent-helpers rule 6; if kept): the
   `progress` template argv is pinned, and `test_shell_example_contracts` vets it. Phrase
   pins whose text is slimmed are deleted.
8. **Gates and evidence.** `just agent-workflow-tests`, `just agent-instruction-budget`
   without the raise label, `just build`, and the eval 8 arms with the A/B report on mbp.

## Out of scope

- `just switch`, any host declaration change, the `instruction-budget-raise` label.
- Building #423 keepalive (it is only simulated), the caching proxy (#422, #429), and Claude
  Code's 1-hour TTL options.
- anis-desktop transcripts (not on this host), and repricing the Codex stratum.
- The cache report's `--context-threshold` default (it stays 120,000).
- A real forge or PR merge in evals, and Phase 7's delivery stages beyond the forge
  boundary.
- Phase 2–5 subagent boots, orchestrate-issues dispatcher changes, Codex hosts (no hooks,
  no meter), pruning the meter's state, and moving `workflow-state` into the package beyond
  `select_phase_action`.
- A gate-side guard (D10) and a meter-side cap (D11).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Measure in two layers: a deterministic replay of real owner transcripts in `agent-costs` prices every candidate and the whole sweep, and a small live lifecycle eval (eval 8) calibrates it and confirms the kept combination | issue: dollars per delivered issue from evals, "settle empirically", spend within `EVAL_MAX_USD`; a full-pipeline trial costs tens of dollars and over an hour, so five-plus arms × trials cannot resolve 10% effects live | all-live A/B (noise and spend); replay only (no calibration, and AC1/AC6 need live runs) |
| D2 | Price per model ID from the Anthropic pricing page (2026-10-25): Opus 5.5 $4/$20, 5m write $5, 1h $8, read $0.20 (0.05×); Sonnet 5.5 read 0.05×; Haiku 5.5 two prompt-size tiers; unknown IDs at the family's newest row, flagged approximate; one table for all reports. This supersedes the issue's 0.1× read figure, so the break-even is about 25·B/(C − B) calls | issue: "pricing and TTL figures come from current primary sources"; owners run `claude-opus-5-5`; the current family table prices it at Opus-5 rates | keeping family pricing (overprices the dominant read bucket 2.5×, which is the very trade-off being measured); per-report tables (several homes) |
| D3 | An owner transcript is one with a registering command carrying `--run-id` and `--action-id` (the meter's D8 test, reused); lineage = `(run_id, issue)`, ordered by launch ordinal; descendants are attributed through `.meta.json` `parentAgentId` to the nearest owner | the meter's owner definition (#424 D8); action IDs are exact lifecycle identity; meta files carry `parentAgentId` | agent_costs' cwd and dir-name issue heuristic (misses owners working from the primary checkout and children in other dirs) |
| D4 | Delivered: a live lineage one of whose transcripts (owner or descendant, since the bookkeeper often runs it) got a `finish` reply reporting the delivery merged; an eval trial whose verdict is `PASS`. Dollars per delivered issue = all spend in scope (undelivered included) ÷ delivered count, with undelivered spend shown | issue: "dollars per delivered issue (boots, waits and cache deaths included)"; the ledger's finish is the terminal truth; the eval fixture has no forge, so a trial delivers at its asserts | `classify_outcome` final-text heuristics (not identity-bound); counting a Phase-7 gate (a failed ship also records it) |
| D5 | The replay is a shift model. An identity replay reproduces observed dollars exactly. Observed `handoff` relaunches are undone first, and other transfers stay. After a simulated hand-off, later calls keep increments, outputs and gaps, minus C − B(p) taken from cache reads first. A fresh owner is a subagent (5-minute TTL). Boots are m(p) linear calls to B(p), with S, m, h and B(p) fitted from the corpus and printed with a calibration. A mid-phase hand-off lands on the first Bash call past the crossing with no Agent child out. Arms are compared with the baseline-policy replay, not with observed cost | the corpus mixes pre- and post-meter owners, so observed cost is not a policy arm; the meter fires on Bash calls and tells the owner to wait for a safe point; the cache report's death rule | re-running models per arm (that is the live eval); per-tool read modelling of every call (no data to fit it); comparing arms with observed cost (confounds the meter deploy) |
| D6 | The policy lives in `agent_tools.phase_budget` as one frozen `PhaseBudget` with `parse`, `current()`, per-phase thresholds, `crossing_threshold`, and `select_phase_action` moved in unchanged. Eval arms override it only through `AGENT_PHASE_BUDGET`, in the same grammar as `--policy`, read once per process; production never sets it. The meter tracks each owner's working phase (`phase` in its state record), so every accepted knob holds in the meter as well as the gate | #424 D7 (one home for the phase budget); the-bar DRY (gate, meter and replay share one decision function); hooks and Bash calls inherit the claude process environment | patched tree copies per arm (tests one code and ships another); one environment variable per knob (several homes); settings-file keys (helpers and hooks do not read settings); re-implementing the gate in the replay (drifts) |
| D7 | Sweep thresholds {90k, 110k, 140k, 170k, 200k, never}, plus a per-phase grid (Phases 0–5 × 6–7, each in {110k, 140k, 170k, 200k}) when the median Phase-6/7 fresh-owner boot differs from the Phase 1–5 one by more than 25%. The chosen value is the arm with the lowest dollars per delivered issue; an arm whose paired difference to a simpler arm is inside the noise loses to it (single beats per-phase, then the current 110k) | issue comment: 120k was never optimised, sweep at least 90/110/140/170k, per-phase if boots differ; observed boots are 98k median, and the jarbird Phase-6 boot was 135k | a single-value A/B (the issue rejects it); a finer grid (noise is coarser than its resolution) |
| D8 | Keep a candidate when its paired per-issue saving against the baseline-policy replay has mean > 0 and a one-sided 90% lower bound (mean − 1.2816·sd/√n) > 0, alone and in the final combination; a kept combination that regresses in eval 8 (higher mean or any `FAIL`) is dropped back to its last passing subset | issue: "ships only if the eval A/B shows it pays", "rejected candidates are reported with their numbers"; two live trials per arm cannot resolve small effects, so the many-issue replay carries the statistics | live-only verdicts; a fixed percentage bar with no variance term |
| D9 | Every candidate is a replay toggle over any eval run or corpus (AC3's "dry run"); live toggles exist for the threshold and for kept candidates only; a rejected candidate leaves no product code | issue AC3 "measured by the eval harness's tests or a dry run"; the-bar YAGNI and no half-wired paths; the cap would need a ledger schema change | implementing all five as product toggles defaulting off (dead switches, and a schema migration for a rejected cap) |
| D10 | Just-started guard: baseline = the owner's context at its registering call (boot end for a relaunched owner); the meter's crossing fires at `max(threshold(phase), baseline + G)`; `baseline` lives in the meter's per-owner state record, not in the ledger the triage assumed; phase-boundary gates stay unguarded, and the report counts boundary hand-offs inside G | issue item 3 and the jarbird #45 case (registered at 136.6k, crossed at once); the crossing instruction is the only mid-phase trigger | launch start as the baseline (about 29k, so the guard is vacuous at every swept threshold); a gate-side guard (needs a second meter-owned progress option, a wider rewrite proof and new `phase_inputs` fields, for rare boundary cases) |
| D11 | Hand-off cap: if kept, a persisted attempt `handoff_streak` (schema 11, migration adds 0) that a finalised hand-off increments and a phase advance or an `advanced` marker resets; at the cap the gate answers `continue` | issue item 4; no existing ledger field records phase or marker per launch; the anti-zombie bound's reset rule (#250) | meter-side counting (per-agent state cannot span launches or see `mark-progress`'s outcome); stopping the attempt at the cap (wastes the attempt, while continuing makes progress); deriving the streak from `launches` (they carry no phase or marker) |
| D12 | Boot slimming: an sdd resume reads the plan root header plus the resumed task's member only, and fresh owners read `ship-handoff.md` once Phase 6's gates pass; the edits are byte-neutral per profile and toggled by tree revision; the replay's slim boot subtracts those reads' measured growth | the jarbird #45 boot (eight task members, a persisted re-read, an early `ship-handoff.md`); sdd: "initial validation is the only whole-package read"; budget headroom of 55 bytes (implementation owner) and 2 bytes (controller) | a resume-pack reading list (more helper contract and prose); a separate boot-profile document (new instruction load) |
| D13 | No `--help`: `progress` and `suspend` derive `--issue`/`--attempt` from `--action-id` (they must agree if both are given), and from-issue's gate paragraph becomes one literal command template, byte-neutral; the replay prices it as `help=drop` | issue item 5 (either fix; both are cheap); `parse_action_id` exists, and `mark-progress`/`resume-pack` already take only `--action-id`; 30 of 39 owners probed `--help` | the template alone (still repeats identity the action ID holds); derivation alone (owners still probe for flag names) |
| D14 | Keepalive is replay-only: an idealised `max_tokens: 0` ping every 270 s of an idle gap over the TTL, priced as a cache read of the prefix; its value is reported for #423 and nothing ships | issue scope: "keepalive off" toggle, #423 out of scope; the prompt-caching guide's keepalive pricing | building a keepalive here (#423's scope); omitting it (the user asked whether keeping cache warm beats a hand-off) |
| D15 | Eval 8 runs `/from-issue 4 --auto` (direct route) on a seeded about-four-task issue with a 5½-minute acceptance test. A `tracked-issue` setup gives the sandbox a read-only `gh` shim (tracker reads served from the issue file, forge reads empty, forge writes refused) and a GitHub tracker binding. Delivery is graded at Phase-7 entry. The runs use `EVAL_MODEL=opus`, two trials per arm, at most $40 per trial and $160 in total; the baseline arm runs at the S3 head, the candidate arm at the final head | `direct-owner` requests a tracker observation that tracker kind `none` cannot supply (eval 2's note), and relaunched owners see no eval prompt, so the shim must sit on PATH; orchestrated control refuses kind `none`; production owners run Opus | a real GitHub sandbox repo (external effects, not authorised); an orchestrate-issues eval (control refuses kind `none`, and the harness would need a dispatcher loop); extending eval 1 (no lifecycle identity) |
| D16 | Tree mode shims `workflow-state` and runs claude with derived settings whose `agent-tools-context-meter` hook points at the tree shim, refusing settings without a meter hook; `EVAL_POLICY` is tree-only, validated up front, exported as `AGENT_PHASE_BUDGET` and recorded as the row's `policy`; absolute `~/.agents/bin/workflow-state` calls stay deployed and are counted as a condition | evals README: flat helpers and the store-path meter hook escape tree mode; an invalid policy would surface only as a non-blocking meter error mid-run | overriding `HOME` (breaks the login); leaving the meter deployed (tree meter changes untested); validating the policy in the product only (fails late and silently in hooks) |
| D17 | Surface: `agent-costs --report owners` with `--format json`, `--policy NAME=SPEC` (repeatable), `--sweep`, `--eval-results PATH` with `--eval SKILL:ID`; one transcript call reader shared with the cache report; the report and the replay are two package modules, and there is no new command | issue: extend `just agent-costs` rather than add scripts; agent-helpers rules 1–2; the cache report precedent (#421 D2); asserts need structured output | a new command (the issue names agent-costs); text-only output (asserts would scrape tables); a second call reader (deaths and usage merging must change together) |
| D18 | (grill) Evaluate as a coordinate pass: boot mode first, then the threshold sweep under it, then guard, cap and help at the choices so far, then keepalive for information, then the final combination against baseline. State the shift model's pro-hand-off bias (a fresh owner's later re-reads are invisible), and keep an arm that hands off more than baseline only when the live arm confirms it | a slimmer boot lowers B and so moves the best threshold; the shift model keeps observed increments after a hand-off; the-bar truthful terminal states | a full factorial (hundreds of arms; the noise outruns the resolution); an independent per-candidate verdict only (misses the boot × threshold interaction); trusting the replay for hand-off-adding arms (biased toward them) |
| D19 | (plan) Module layout: the price table moves to a new `agent_tools.model_pricing`; the call reader moves out of `agent_cache_report` into a new `agent_tools.transcript_calls`, and both reports import it; D17's two modules are `agent_tools.agent_owner_report` and `agent_tools.agent_owner_replay`; `context_meter_commands` gains `invocations()`, and `registers_owner` is derived from it; the new tests are `tests/test_agent_owner_report.py`, `tests/test_agent_owner_replay.py` and `tests/test_phase_budget.py`, with builders in `tests/owner_transcripts.py`, and all three join the `agent-workflow-tests` recipe | the-bar single responsibility (split when the second concern arrives: the reader gains a second consumer and the table a third); agent-helpers rules 1–2; `agent_costs.py` is 2,048 lines and its test file 2,200 | importing `agent_cache_report._read_records`/`_Call` across modules (private names); growing `agent_costs.py` or `tests/test_agent_costs.py` further |
| D20 | (plan) Owner-report pins, taken from real transcripts of 2026-10-24/25: a lineage is delivered when a Bash `workflow-state finish` tool result starts with a JSON object whose `kind` is `delivery_complete`, keyed by that object's `run_id` and `issue`; Phase 7 is entered when a `progress --phase 6` call gets a `phase_gate` reply; a gate call is measured when a `PreToolUse:Bash` `hook_additional_context` attachment for its tool use holds the meter's measured-note prefix; a child is out from its Agent tool use until the last record of the transcript whose `.meta.json` `toolUseId` names that tool use. The action ID is an opaque key: issue, attempt and launch come from reply `issue`/`custody` fields, then from `--issue`/`--attempt` flags, then from another transcript of the same run with the same action ID; an owner left unresolved counts as unattributed | real `finish` replies (issues 400, 402–404, 421, 422) carry `kind: delivery_complete`; `workflow-state` is the one parser of the action-ID grammar, and the spec keeps moving `workflow-state` code out of scope beyond `select_phase_action` | parsing the action ID in the package (a second home for its grammar); classifying final texts (not identity-bound) |
| D21 | (plan) Grammar and model details. A SPEC is comma-separated `key=value` items with decimal integer values. `threshold=` sets every phase and is also the value for an unknown phase; `threshold:a-b=` overrides Phases a–b (0 ≤ a ≤ b ≤ 7, a later item wins); a key repeated without a range raises. `phase_budget.parse` accepts only `PRODUCT_KNOBS` (`threshold` at first; `guard` or `cap` join it only in the commit that builds that candidate into the meter or gate), and the replay parses with `REPLAY_KNOBS`; `threshold=never` and `boot`, `keepalive`, `help` are the replay's own. `progress`'s four budget flags default to `None` and resolve from `current()`; the default ceiling is `handoff_threshold(phase + 1)` plus the default headroom. Replay model: the relauncher's wake call is one cache read of the relauncher transcript's last context before the hand-off, or nothing when the relauncher is unattributed; a missing `B(p)` falls back to the median over all phases, then to 98,000, flagged as a default; a boot's slimmable growth is split across the call's tool results by result length; "inside the noise" means the paired lower bound is ≤ 0 | D6, D9 (no half-wired product toggles); D7, D18; the 98k median boot this spec observed | accepting `guard`/`cap` in the product before they are kept (a live arm would be silently inert); a mutable default argument |
| D22 | (plan) Live arms. Each arm runs in a detached scratch worktree at its pinned commit: the baseline at Task 6's commit, the candidate at the final code head. The runner and `EVAL_TREE` are both that checkout, `TMPDIR` is under the launch scratch root, and `EVAL_SETTINGS` is the worktree build's settings. The sdd controller, not an implementer, launches each arm as two concurrent `EVAL_TRIALS=1` invocations through `launch-scope exec` in the background: the baseline right after Task 6 commits, the candidate after Task 7. While a trial runs, the controller waits for it before any phase gate, hand-off, suspension or exit. A trial starts only when `deadline_at` is at least 100 minutes away, with `EVAL_TIMEOUT` = min(7200, remaining − 600 s). A trial that is never started or is killed is recorded as an evidence gap, never as a sample. New results rows are copied into the worktree's `results.jsonl` | tree mode links the checkout's skills into the sandbox, so editing it mid-trial changes the arm; a launch's reap kills its processes and deletes its scratch root; attempt deadline 2026-10-25T15:57:54Z; D15 allows two runner invocations at once | running from the live worktree (arm drift); one `EVAL_TRIALS=2` invocation (twice the wall time); letting an implementer launch the arm (its shell ends with it) |
| D23 | (plan) Under D15's cap there is no third live arm. If the candidate arm regresses (higher mean or any `FAIL`), Task 8 `git revert`s each kept candidate that hands off more often than the baseline in the replay (D18), one revert per candidate commit, and keeps the others on their replay verdict, labelled "replay-only, live unconfirmed"; AC6 is then reported as not met | D8's drop-back; D15's $160 cap; D18's bias toward hand-offs | a re-run arm (over the cap); reverting every candidate (throws away replay-proven wins that add no hand-offs) |
| D24 | (standards review) The replay's comparator is pinned. `ORIGIN` spells the pre-issue-432 policy in literals (110k in every phase, no guard, no cap); `BASELINE` uses it, and every `--policy` and sweep arm takes the knobs it does not name from it through `phase_budget.parse(..., base=ORIGIN)`. The sweep's final step prices each chosen candidate alone, drops those that reject, then prices one `combined` row over exactly the survivors, which is the set Task 7 builds | Codex review: Task 7 moves `PhaseBudget`'s defaults and Task 8 re-runs the sweep at the final head, so a default-reading baseline moves the comparator; a combination that holds alone-rejected candidates is not the shipped subset (D8: "alone and in the final combination") | reading `PhaseBudget()` (the comparator drifts with each kept default); re-running the whole coordinate pass without the rejected candidate (more arms than the noise resolves, D18); confining re-runs to the commit before 7A (Task 8 needs the final head) |
| D25 | (standards review) A kept cap is decided and validated from durable inputs. At schema 11 each gate's `phase_inputs` gain `handoff_streak` and `cap` as decided, so the existing recompute-and-compare validation survives later increments, resets and policy changes. The 10 → 11 step sits with the bound-ledger upgrades in `attempt_store` (locked reads, `check_unlocked`, `workflow-state migrate`), `attempt_identity` admits 11, and older schemas keep their routes. It adds `handoff_streak: 0` to attempts and `handoff_streak: 0, cap: null` to stored inputs. The streak resets on a phase advance or an `advanced` marker only, in the product and the replay alike, so `OwnerCall.mark_progress` keeps the reply's `outcome`. Extends D11 | Codex review: `validate_attempt` recomputes `phase_action` from `phase_inputs` alone; `workflow_delivery.migrate` ends at 7/8 and `attempt_store._schema_ten` owns 8/9 → 10, with `attempt_identity._MAX_SCHEMA_VERSION = 10`; `record_progress_marker` answers `baseline`, `unchanged`, `diverged` or `advanced` and resets only on `advanced` (#250 D3) | validating against the live streak (a later increment or reset invalidates history); exempting capped decisions from validation (an unchecked action); resetting the replay on any `mark-progress` (prices a rule that does not ship) |
| D26 | (standards review) A live eval trial is a sample only when its results row has `claude_exit` 0. Any other exit is an evidence gap even when every assert passed: the owner report leaves such rows out of its arms and lists them under `interrupted`. The live prediction replays a results file filtered to the baseline arm's `tree_rev` | Codex review: `run-eval.sh` grades a timed-out run and sets `PASS` from asserts alone; D22 (a killed trial is an evidence gap); Task 8 needs a prediction from baseline trials only, and the report groups by arm, not by source | grading on asserts only (a timeout after Phase-7 entry would count as delivered); a new arm-filter flag (a `jq` filter over the existing input suffices); reading `result.json`'s `subtype` (not on the results row) |
| D27 | (standards review) `threshold=never` stays in the sweep as a reference row, verdict `info`: reported for AC4, never chosen or built. The threshold candidate is the cheapest numeric arm, and when `never` is cheapest the report says so. Narrows D7 | Codex review: no `PhaseBudget` value represents it (thresholds are integers ≥ 1) and 7A moves only numeric defaults; the replay's `budget is None` also drops phase-boundary and turn hand-offs, which removes hand-off rather than tuning it, outside D9's candidates | a sentinel such as 1,000,000 (the turn branch still hands off, so it ships a policy the replay did not price); a new `never` product knob (a feature outside the issue, D9) |
