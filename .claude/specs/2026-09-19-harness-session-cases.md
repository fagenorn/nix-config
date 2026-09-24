# Harness retrospective: session cases and workflow evidence

Durability: **intentionally temporary** audit evidence, retained with the September 19 retrospective until recommendations are incorporated into durable issue decisions. No raw transcript copies or credentials are included. This file records an audit; it changes no harness behavior.

## Method and limits

Primary activity window: August 19–September 18, 2026 UTC. Workflow artifacts and source were inspected September 19. Cases combine high-volume sessions, explicit user corrections, and positive delivery evidence; they are purposive samples, not a random experiment. A large session is not inherently waste. Transcript tool-call counts are attempts, not successful operations. A waiting response can also contain useful reasoning or commentary. Recorded request tokens count repeatedly presented cached context; they are not unique information, billed dollars, or user quota.

The workflow scan reads only `.superpowers/workflows/*/state.json` in arcwave, nodocom, argus and nix-config, selects attempts started on/after August 19 and before September 20, and counts attempts and launches. “Latest” means the last retained run by its file's `updated_at`, not a fresh forge observation. These data include superseded/stale runs and omit activity outside this ledger. They must not be presented as project success rates. Scratch calculations live under `/private/tmp/harness-audit-20260919/` and are not durable source dependencies.

## 1. Arcwave: coordination is doing too much model work

Source: [Codex orchestration session, September 15–16](/Users/anis/.codex/sessions/2026/09/15/rollout-2026-09-15T15-20-41-01a0a571-001a-7113-957c-86a61ee27bfd.jsonl). SQLite identifies the root request as `@orchestrate-issues --label agent:ready` and root model as `gpt-6-astra`.

The transcript contains 2,326 unique `token_usage_record` response IDs. Sum `payload.usage` once per response, never `turn_token_usage` or `thread_token_usage`: 260,868,559 input tokens, of which 258,830,848 cached; 421,822 output; 261,290,381 total. The input cache fraction is 99.22%. This is a response-level measure for this root, excluding child and guardian usage. It differs from the SQLite `tokens_used` field; that field is not substituted for the response sum.

| Root action | Calls | Request-token total associated with responses issuing this action |
|---|---:|---:|
| `wait_agent` | 976 | 109,026,287 |
| `wait` | 211 | 23,849,936 |
| `spawn_agent` | 215 | 23,637,321 |
| `followup_task` | 269 | 32,615,124 |
| `send_message` | 109 | 11,579,904 |
| `exec` | 517 | 57,797,179 |

Association method: collect response-item function/custom tool names since the preceding usage record, then attach the next unique usage record to that response's tool set. All 2,321 tool-bearing usage records in this case have one tool name; five have none. `wait_agent` accounts for 41.73% of total request tokens; the two wait tools together account for 50.85%. This establishes concentration on wait-producing responses, not that 50.85% of spending can be removed. Cached context dominates.

The cause is visible in assistant messages: [line 365](/Users/anis/.codex/sessions/2026/09/15/rollout-2026-09-15T15-20-41-01a0a571-001a-7113-957c-86a61ee27bfd.jsonl:365) says two owners share the remaining review-agent slot; lines 444, 517, 616, 818 and 860 narrate repeated transfers between owners' implementers and reviewers. The root has four compaction records, so the problem is not explained solely by compaction.

**Inference:** nested workflow ownership exceeds the useful concurrency supported by the available slots, making the top model act as a scheduler. Reserve worker/reviewer capacity before starting another owner; use one owner when necessary; relay completion through host events. Where the host still needs a waiting tool, batch notifications and wait appropriately rather than recreating ownership. Do not increase fan-out as the first remedy.

The repository's [installation rationale](/Users/anis/tmp/nix-config/home/common/claude-code/default.nix:1138) deliberately exposes `orchestrate-issues` only to Claude. This session demonstrates that a user can nevertheless request it from Codex; a host-specific capability response and supported route are needed. Historical instructions and available tool capabilities must be distinguished from what current clients support.

## 2. Nodo: a phase stop missed the user's completion intent

Source: [Claude session, August 25](/Users/anis/.claude/projects/-Users-anis-Projects-nodocom/02ff1141-cfe6-4822-8fba-522146f3ca30.jsonl:318).

For issue 1314 the assistant verified all six acceptance criteria already delivered on `dev`, ran five relevant integration tests, then recorded `stopped`. At line 321 the user asked why `--auto` had not driven the full flow; at line 334 they asked why the issue was still open. The assistant's line 324 explanation defended the phase-stop rule rather than completing tracker reconciliation.

**What worked:** detecting already-delivered work prevented a duplicate implementation; concrete tests supported that judgment.

**What failed:** “nothing to implement” was treated as the end of the user's task. Add a terminal path for already-delivered issues: verify all criteria, reconcile the authorized tracker state, preserve supporting evidence, then terminate. Closing or modifying a tracker still follows the actual authorization in the invocation; a generic audit must not silently change issues.

This is a workflow finding grounded in one explicit correction, not a measured fleet frequency. The relevant current contract is [from-issue AUTO content stops](/Users/anis/tmp/nix-config/home/common/agent-skills/skills/from-issue/AUTO.md:60).

## 3. Arcwave: a decision record was called complete before it shipped

Source: [Claude wayfind session, September 12](/Users/anis/.claude/projects/-Users-anis-Projects-arcwave/672f2e17-e667-44ec-895a-7f561fcf335e.jsonl:669).

The assistant closed decision ticket 113 and updated its map, but left record PR 116 pending. On the user's “what next”, it prescribed a new `/ship-issue` session. The user replied at line 677 that they wanted to run `/wayfind 1`; line 685 acknowledges the incorrect interpretation and undertakes shipping.

**Inference:** the termination condition is local to the skill rather than the requested deliverable. For a task producing repository evidence, completion should name the expected durable location and required delivery state. Do not reopen the substantive decision; finish its already-authorized publication path. Current [wayfind resolution steps](/Users/anis/tmp/nix-config/home/common/agent-skills/skills/wayfind/SKILL.md:82) emphasize record/close/gist but do not express that repository-delivery obligation.

## 4. Argus: long experiments, repeated gates, and context rebuilding

Source: [Codex prototype/personality session, September 4–9](/Users/anis/.codex/sessions/2026/09/04/rollout-2026-09-04T20-39-26-01a06dee-de13-7851-88c4-2e46b4cab1ec.jsonl). It contains 79 compaction records, 6,023 `exec` calls, 1,218 `wait_agent` calls, 219 spawn attempts, and 8,368 usage-record entries. These are descriptive counts, not all avoidable work or independently verified completions.

At [line 2403](/Users/anis/.codex/sessions/2026/09/04/rollout-2026-09-04T20-39-26-01a06dee-de13-7851-88c4-2e46b4cab1ec.jsonl:2403), the assistant reports being blocked at a design-skill approval checkpoint; at line 12711 it again requests approval for a six-call local comparison, followed at line 12718 by the user explicitly asking it to keep going until the goal is achieved. Later user messages at lines 29491 and 31640 reiterate permission to use local Ninfer.

Not all gates have the same origin. The first sampled request at line 751 names OpenRouter transfer; line 30940 names a separate approval boundary concerning the endpoint potentially forwarding data. Those are not evidence that all permission checks are unnecessary. Distinguish skill approval, scope change, and actual runtime/automatic-review denial. Preserve real enforcement; propagate existing authorization and explain genuinely new boundaries precisely.

**Inference:** for open-ended experiments, carry a compact current hypothesis, success criterion, existing authorization scope, best candidate and next experiment through phase transitions. Stop repeating design ceremony for bounded iterations within that authorization. Measure useful experiments and acceptance progress, not merely passing safeguard tests. The user was asking for a working result; this transcript alone does not prove the final production goal was achieved.

## 5. Reviews caught defects that simpler token minimization would miss

Source: [Nodo issue 1316 Codex session](/Users/anis/.codex/sessions/2026/08/26/rollout-2026-08-26T08-02-42-01a03ce0-d331-7073-8d84-872ca7eec066.jsonl:6667).

After a broad test cancellation-token migration, the correctness pass identified teardown and watchdogs incorrectly inheriting already-cancelled test tokens. At line 6712 the owner reports fixing an independent watchdog, bounded database cleanup, and guaranteed CTS disposal. Earlier failures at lines 5112 and 5535 exposed analyzer fixes choosing incorrect EF overload shapes. This is concrete evidence for retaining semantic review even when the initial edit appears mechanical.

The [nix-config workflow ledger](/Users/anis/tmp/nix-config/.superpowers/workflows/run-20260902-115-130/state.json) records issue 120's final review finding that duplicate trials could satisfy an exact-three evidence gate, and issue 115's shipping review catching a regression. These are retained owner reports, not independent re-runs of the historical tests.

Current [SDD final-review policy](/Users/anis/tmp/nix-config/home/common/agent-skills/skills/sdd/final-review.md) already combines verified findings into one fix wave and scopes re-review. Preserve that mechanism. Evaluate review cost against accepted findings and regressions prevented, rather than reducing every review to the least expensive tier.

## 6. Budget checks sometimes arrive after the expensive work

The same [nix-config ledger](/Users/anis/tmp/nix-config/.superpowers/workflows/run-20260902-115-130/state.json) records:

- Issue 121: tasks 1–6 reviewed, 873 tests and build passing, but final review package 589,625 bytes exceeds the 524,288 aggregate cap. Tasks 7–8 had not started. The retained attempt recommends splitting or changing the cap.
- Issue 122: all seven tasks implemented and reviewed, but one 79,762-byte whole-file diff exceeds a 65,536-byte member cap. Subsequent history includes splitting the engine/tests and merging the work.
- Issue 115: final package blocked by research documents, with an 80,800-byte largest member. A later attempt recovered and merged the work.

**Inference:** the hard review boundary is valuable, but package feasibility should be projected at planning and checked incrementally before investing in every task. Declare a split when projected changed files or evidence cannot fit. Do not automatically raise a cap or omit unreviewed changes to make the gate pass.

## 7. Repeated launches and environment failures

In the shallow retained ledger census, there are 217 attempt records across 118 state files: Arcwave 12 attempts/38 launches, Nodo 156/302, Argus 23/29, nix-config 26/49. These cover 132 distinct project/issue pairs and 418 launches. Of 198 attempts with a `phase_inputs` object, 185 have `context_tokens: null`; these last recorded observations cannot establish how often the context trigger actually fired. Rollover telemetry needs observable values or an explicit unmeasured state.

[Nodo orchestration 1444–1446](/Users/anis/Projects/nodocom/.superpowers/workflows/orch-1444-1446/state.json) has 11 launches each for issues 1444 and 1445. Issue 1444's terminal notes identify a repo-wide unavailable pinned browser image and point to repair issue 1456. This does not prove all 11 launches were due to that image. [Arcwave's September sweep](/Users/anis/Projects/arcwave/.superpowers/workflows/orchestrate-agent-ready-20260914T185053Z/state.json) records a pre-existing macOS-only lockfile breaking Linux CI for issue 145, after five launches. Check shared blockers before repeated issue-level re-entry and resume only after a relevant change or completed dependency.

A positive recovery case is [Nodo issue 1437](/Users/anis/Projects/nodocom/.superpowers/workflows/orch-1432-1437/state.json): the dispatcher records the observed merge, closure, cleanup and retained detail after its owner hit a session limit before `finish`. Durable state and forge reconciliation are doing useful work.

## 8. Instruction growth and conflicting configuration surfaces

Using whitespace word counts on each root `SKILL.md`, current source versus the last touching commit before August 16 UTC:

| Skill | Earlier words | Current words | Growth |
|---|---:|---:|---:|
| from-issue | 2,301 | 4,300 | 87% |
| sdd | 1,603 | 2,519 | 57% |
| ship-issue | 1,992 | 3,572 | 79% |
| writing-plans | 1,614 | 2,395 | 48% |

These are words, not tokenizer counts or marginal per-turn costs. Research, doc-grounded-questions and wayfind roots stayed unchanged in this comparison. Six sampled installed roots match repository bytes, so the observed legacy references are not explained by a stale installation alone.

[Bootstrap](/Users/anis/tmp/nix-config/.agents/instructions/bootstrap.md) requires one fail-closed `resolve-project` result. [from-issue bindings](/Users/anis/tmp/nix-config/home/common/agent-skills/skills/from-issue/bindings.md:5), [research](/Users/anis/tmp/nix-config/home/common/agent-skills/skills/research/SKILL.md) and [doc-grounded-questions](/Users/anis/tmp/nix-config/home/common/agent-skills/skills/doc-grounded-questions/SKILL.md) still describe legacy config/default/fallback paths. This creates a real contradictory instruction surface in the current harness; it is not a measured attribution of historical token loss.

Move procedural mechanics into deterministic commands and phase-specific references, and finish the existing canonical-configuration migration. Keep invariants on the hot path; do not solve growth by silently weakening checks.

## 9. Short, focused reviews provide a useful counterexample

Two non-guardian Codex child sessions selected from the inventory were inspected as counterexamples to the expensive roots:

- [Argus task review, September 4](/Users/anis/.codex/sessions/2026/09/04/rollout-2026-09-04T12-59-47-01a06c4a-0b34-7120-81a6-73a1745adfe7.jsonl:90): eight `exec` calls; checked the two-file review package, read a missing context range and returned a compliant verdict while explicitly separating Task 2's unverified requirements from Task 3's review scope.
- [Nodo task review, September 8](/Users/anis/.codex/sessions/2026/09/08/rollout-2026-09-08T01-56-18-01a07e84-0e92-7161-89f1-496d8fa1be01.jsonl:59): six `exec` calls; verified recursive deletion closure, ordered locks, rechecking membership, commit-before-counting, and independently asserted preserved tenant data, then returned task compliance and quality verdicts.

These show that bounded delegation can produce substantive review without a long controller loop. They do not estimate reviewer accuracy, and they are not paired comparisons against a single-agent baseline.

## 10. The current cost parser needs a counting correction

The Codex parser in [agent-costs.py](/Users/anis/tmp/nix-config/scripts/agent-costs.py:412) sums `last_token_usage` on every `token_count` event. Those events can repeat a cumulative state without a new completion.

| Session | token_count events | Consecutive unchanged cumulative states | Naive last-usage sum | Sum only when cumulative changes | Final cumulative counter |
|---|---:|---:|---:|---:|---:|
| Nodo August 26, `01a03ce0…` | 1,533 | 13 | 186,033,963 | 185,069,427 | 185,069,427 |
| Arcwave September 15, `01a0a571…` | 2,451 | 129 | 275,830,131 | 260,492,050 | 260,492,050 |

Both inspected cumulative sequences were monotonic, with no resets. The Nodo overcount is 0.52%; the Arcwave overcount is 5.89% against that cumulative counter. Arcwave's newer response-ID records total 261,290,381 instead, so its naive-event overcount against that record source is 5.56%. The disagreement between the two non-naive totals must be represented rather than silently reconciled: newer usage records contain 2,326 completions while the cumulative sequence changes 2,322 times.

Sources: the [Nodo transcript](/Users/anis/.codex/sessions/2026/08/26/rollout-2026-08-26T08-02-42-01a03ce0-d331-7073-8d84-872ca7eec066.jsonl:8676) and [Arcwave transcript](/Users/anis/.codex/sessions/2026/09/15/rollout-2026-09-15T15-20-41-01a0a571-001a-7113-957c-86a61ee27bfd.jsonl:18109). The scratch audit counts each event's full cumulative-token tuple, compares it with its predecessor, and separately sums its last-usage tuple. This diagnostic is not proposed as an unqualified estimator for all versions: missing snapshots, counter resets, truncation and boundary-crossing sessions still require tests.

**Recommendation:** retain the delivered structured telemetry interface, but add fixtures for repeated snapshots, modern per-response records, cumulative reset, compaction and an audit-window boundary. Report the source format and coverage. Do not price modern-only totals as a whole-month fleet bill or conflate cached input with fresh input. This is a correctness follow-up to #120 and a prerequisite for interpreting #98's model-routing measurements.

## Follow-through measurement clarification

The legacy diagnostic table above sums `last_token_usage.total_tokens`. Re-running the actual baseline reporter at `ea03ccdd` sums `input_tokens + output_tokens` instead: Nodo 185,922,225; Arcwave 275,759,020. Seven Nodo snapshots and four Arcwave snapshots have internally unequal fields, explaining that small baseline difference. The correction selects 185,069,427 from deduplicated legacy Nodo observations and 261,290,381 from unique modern Arcwave responses. This is accounting correction, not a reduction in historical execution work.
