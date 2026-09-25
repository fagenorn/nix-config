# Host admission preparation for issue #150

**Durability: intentionally temporary.** Delete this file after its adapter and
schema conclusions have been recorded in issue #150's design or implementation
plan.

## Question and boundary

What existing host-domain, conformance, and runtime seams can support issue
[#150](https://github.com/fagenorn/nix-config/issues/150)'s discrete agent-slot
claim/release contract, and what is unproven or unavailable on this collaboration
host?

This note is bounded to adapter, schema, and execution-seam evidence. It does
not propose a complete design, acquire the issue, change lifecycle state, or
probe agent capacity. "Slot" below means an agent execution slot only, never
CPU, memory, or Nix-daemon capacity.

## Findings

### Existing repository seams

| Seam | Evidence | What it can own for #150 | Boundary |
|---|---|---|---|
| Conformance host domain and registry | `DOMAINS` includes `host`; registered host checks already cover required capabilities, policy-path safety, executor-helper presence, and tracker credentials. `local` selects the workflow-entry ladder plus every host check, while `doctor` selects every domain ([conformance-registry.py](../../home/common/agent-skills/scripts/conformance-registry.py#L23), [registry](../../home/common/agent-skills/scripts/conformance-registry.py#L290), [selection](../../home/common/agent-skills/scripts/conformance-registry.py#L392)). | Declare and evaluate a closed host-admission capability such as adapter present/protocol supported, then expose an explicit unsupported result through `local` and `doctor`. | The report is a bounded observation. It is not a mutable reservation ledger and cannot itself make claim/release atomic. The registry also forbids timestamps in report objects ([conformance-registry.py](../../home/common/agent-skills/scripts/conformance-registry.py#L41)). |
| Conformance evaluator and report | Evaluators return declared outcomes; undeclared findings fail. Reports expose fixed check fields and bounded facts ([conformance.py](../../home/common/agent-skills/scripts/conformance.py#L581), [evaluation](../../home/common/agent-skills/scripts/conformance.py#L607), [report](../../home/common/agent-skills/scripts/conformance.py#L670)). Existing host checks already translate resolved capability/tool facts into outcomes ([conformance-checks.py](../../home/common/agent-skills/scripts/conformance-checks.py#L264)). | Report whether a supported admission adapter can be queried and name a closed reason when it cannot. | Dynamic available/reserved counts and reservation ownership need a runtime-owned API. Encoding them as timeless conformance facts would not satisfy atomic admission or release. |
| Orchestration dispatch boundary | The current adapter consumes ordered `spawn`, `resume`, `retry`, `wait`, and `finalize` actions, and dispatches a host owner only after receiving an exact action envelope ([orchestrate-issues](../../home/common/claude-code/skills/orchestrate-issues/SKILL.md#L96), [execution](../../home/common/claude-code/skills/orchestrate-issues/SKILL.md#L116)). Host task handles are already correlation data beside lifecycle `action_id`, not lifecycle identity ([orchestrate-issues](../../home/common/claude-code/skills/orchestrate-issues/SKILL.md#L121)). | This is the concrete execution seam for querying capacity and acquiring an opaque role-set claim before any owner launch. The claim can be correlated with `action_id` without replacing it. | Current source expressly says not to calculate slots, create reservations, or repeat rejected spawns; it uses a documented sequential/direct route or reports unsupported capability ([orchestrate-issues](../../home/common/claude-code/skills/orchestrate-issues/SKILL.md#L28), [capacity boundary](../../home/common/claude-code/skills/orchestrate-issues/SKILL.md#L37)). No current reservation implementation exists. |
| Event-driven wake boundary | The adapter installs one one-shot observer for a control `wait`, replaces it by wait ID, rejects stale wakes, and forbids polling ([orchestrate-issues](../../home/common/claude-code/skills/orchestrate-issues/SKILL.md#L166)). It also refreshes control facts on current owner notifications and current wait-ID wakes ([orchestrate-issues](../../home/common/claude-code/skills/orchestrate-issues/SKILL.md#L83)). | A runtime admission adapter can publish a release/capacity wake into this existing event re-entry seam, so queued work is reconsidered after a lifecycle event rather than through spawn or sleep loops. | The current observer contract has no admission claim ID or slot-release event. Those require a new typed host event and durable runtime authority. |
| Workflow control `max_parallel` | `workflow-state control` counts active issue attempts and subtracts them from the caller-supplied `max_parallel` before proposing resume/retry/spawn actions ([workflow-state.py](../../home/common/agent-skills/scripts/workflow-state.py#L2095)). | It remains the workflow-level issue concurrency ceiling. | It does not observe host worker/reviewer slots or reserve them. Issue #150 explicitly requires a limited-slot replay where this clamp alone is insufficient. |
| Standards review route | Native Codex is routed to one fresh native reviewer when the configured collaboration review route is unavailable ([standards-review.md](../../home/common/agent-skills/skills/from-issue/standards-review.md#L18)). | A claim should include reviewer capacity before admitting an owner whose workflow requires independent review. | Current source does not document direct `codex exec` as fallback after native capacity refusal. The unmerged issue #100 proposal cannot establish current #150 capability. |

The smallest compatible architecture is therefore a **runtime-owned admission
adapter** between the ordered control action and native host dispatch. Its API
must atomically claim the discrete roles needed by that action (controller,
owner, worker, reviewer), return an opaque claim plus available/reserved counts,
release from authoritative lifecycle events, and emit one wake when capacity is
freed. Conformance should discover and report this adapter; it should not own
the mutable claims. `workflow-state`'s action identity and the host task handle
remain separate correlation keys.

### Runtime API inventory

| Surface | Supported information/action | Admission significance |
|---|---|---|
| Native collaboration tools exposed in this session | `spawn_agent` attempts a launch; `list_agents` lists visible thread states; `wait_agent` waits for mailbox/final-status updates; `interrupt_agent`, messages, and follow-ups operate on known threads. | There is no exposed capacity query, atomic claim/reserve, explicit slot release, queue registration, or claim-completion subscription. A spawn refusal is an admission result after an attempted launch, not a pre-launch reservation. `list_agents` is therefore inventory, not an authoritative available-slot count. |
| Codex app-server thread APIs | `thread/list` can filter by `parentThreadId` or experimental `ancestorThreadId`; `thread/loaded/list` reports in-memory IDs; thread status can be `notLoaded`, `idle`, `systemError`, or `active`; `thread/status/changed`, `turn/completed`, and `thread/closed` are lifecycle notifications. Official documentation describes these APIs and status/event behavior ([App Server: thread listing](https://learn.chatgpt.com/docs/app-server#list-threads-with-pagination--filters), [loaded threads and unsubscribe](https://learn.chatgpt.com/docs/app-server#list-loaded-threads)). Local 0.153.1 schemas define the corresponding types (`ThreadListParams`, `ThreadLoadedListResponse`, `ThreadStatus`, `ThreadStatusChangedNotification`, `TurnCompletedNotification`) in [`codex_app_server_protocol.v2.schemas.json`](/private/tmp/nix-codex-appserver-schema-20260920/codex_app_server_protocol.v2.schemas.json). | These are useful inputs for an adapter that actually owns those app-server threads. They expose lifecycle and topology, but no discrete capacity total, available/reserved count, atomic claim, or claim release. No evidence establishes that a separately started CLI app-server is the authority for this native collaboration host. |
| App-server unsubscribe/archive | `thread/unsubscribe` removes one connection's subscription. Last-subscriber unload happens only after no subscribers and no activity for 30 minutes, then emits `thread/status/changed: notLoaded` and `thread/closed`. `thread/archive` moves persisted logs and attempts descendants ([official lifecycle documentation](https://learn.chatgpt.com/docs/app-server#unsubscribe-from-a-loaded-thread)). Local CLI 0.153.1 exposes `codex agents` as a TUI and `codex archive` as a mutating session command. | Neither operation is an immediate slot release transaction. Unsubscribe is delayed and subscription-scoped; archive is persistence mutation. Neither should be used to manufacture capacity on this host. |
| App-server model APIs | `model/list` returns catalog models, supported/default reasoning effort, service tiers, and related picker metadata ([official model/list documentation](https://learn.chatgpt.com/docs/app-server#list-models)). | Catalog availability is not execution admission or current model-service capacity. The local protocol contains no model/effort slot reservation field. |
| App-server diagnostics | `ServerDiagnosticsResponse` contains generic named integer gauges and process memory/id fields in the 0.153.1 schema. | No named agent-slot contract is specified. Treating an arbitrary gauge as a capacity API would be unsupported. |
| `codex exec --json` | Official documentation promises JSONL events such as `thread.started`, `turn.started`, `turn.completed`, `item.*`, and usage in the completion example ([non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode#make-output-machine-readable)). | The documented event contract does not promise selected model or reasoning-effort fields. A successful CLI review proves that invocation ran; it does not prove native owner/reviewer admission, shared-slot accounting, or observed per-turn model/effort. Absence from the documentation is not proof that every local event omits extra fields. |

### Metadata, admission, and execution telemetry are different contracts

The local 0.153.1 `Thread` schema is explicit: `model` is the current configured
model when loaded or the latest persisted model, and `reasoningEffort` has the
same configured/persisted meaning. Both descriptions say they are **not
per-turn execution telemetry** (`Thread.properties.model` and
`Thread.properties.reasoningEffort` in the local protocol schema). The
`TurnCompletedNotification` contains a `Turn`; `Turn` has identity, status,
items, and timing, but no selected model or effort. `ModelReroutedNotification`
names `fromModel` and `toModel` only when a reroute occurs. Consequently:

- persisted/configured model and effort are metadata;
- acceptance or refusal of a spawn/turn is actual admission behavior;
- the model and effort that executed a particular turn require telemetry tied
  to that turn;
- none of the inspected supported surfaces proves all three for native
  collaboration.

### What is unproven or unavailable on this host

1. **Pre-launch capacity and atomic claims are unavailable in the exposed
   collaboration API.** No inspected native tool, app-server method, or local
   schema reports total/available/reserved discrete agent slots or atomically
   reserves controller/owner/worker/reviewer roles.
2. **App-server observation is not currently connected.** At the one fresh
   read-only observation below, the standard local control socket did not
   exist. This supports only a transient statement about that observation. It
   does not prove a standing outage and does not justify starting another
   daemon or equating it with native collaboration.
3. **Visible thread count is not proven to equal admission occupancy.** The
   caller reports native `agent thread limit reached` refusals at times when
   visible inventory looked lower, interleaved with a successful continuation
   spawn. Exact independent timestamps were not supplied, so these are useful
   falsifying cases for a future limited-slot replay, not standing live
   evidence.
4. **Model service capacity is distinct from thread-slot capacity.** The caller
   separately observed `Selected model is at capacity` while another delegated
   owner continued. That supports keeping model admission errors distinct in
   the schema, but without a timestamped execution record it is not upgraded to
   a standing claim.
5. **A direct CLI review is not a supported native-admission route.** The caller
   reports one successful configured CLI plan review after native refusals.
   Current `standards-review.md` still routes native Codex to a fresh native
   reviewer and does not define that fallback. The execution proves only that
   the separate CLI command ran.
6. **Immediate release from completion is unproven.** Native final-status
   messages can trigger orchestration work, and app-server has lifecycle
   notifications, but no inspected API atomically binds either event to a
   discrete slot claim and wakes exactly the next queued action.

## Validated live observation

The following schema-version-1 `research-observations` object was materialized
temporarily and validated with
`~/.agents/bin/agent-evidence research`; validation returned
`VALID research-observations issue-150-control-socket-20260920`. The temporary
JSON input was then deleted.

```json
{
  "schema_version": 1,
  "kind": "research-observations",
  "evidence_id": "issue-150-control-socket-20260920",
  "captured_at": "2026-09-20T00:25:49Z",
  "question": "Is the already-running local Codex app-server control socket available for read-only introspection in this collaboration host?",
  "claim": {
    "classification": "transient",
    "conclusion": "At the recorded observation, the expected local app-server control socket was absent, so the proxy route was unavailable without starting a separate daemon.",
    "observation_ids": [
      "obs-control-socket-20260920T002549Z"
    ],
    "follow_up": "At a later independent timepoint, recheck the socket and use initialize plus thread/list only if an app-server daemon is already running; do not start one merely to infer native collaboration admission."
  },
  "observations": [
    {
      "id": "obs-control-socket-20260920T002549Z",
      "execution_id": "exec-stat-control-socket-20260920T002549Z",
      "observed_at": "2026-09-20T00:25:49Z",
      "source": "filesystem socket test: /Users/anis/.codex/app-server-control/app-server-control.sock",
      "outcome": "socket_absent"
    }
  ]
}
```

## Acceptance-focused implications

- The first implementation slice should define a closed, versioned admission
  adapter contract and conformance outcome before changing scheduling behavior.
- The execution adapter must acquire the full required role set before owner
  launch. Reserving only an owner would fail #150's limited-slot and independent
  review cases.
- Claim/release state must have one runtime authority and atomic transitions;
  neither `list_agents`, `max_parallel`, nor app-server loaded-thread count is
  that authority today.
- Release must be driven by a correlated lifecycle event and produce a one-shot
  wake through the existing wait/event seam. A rejected spawn must remain a
  bounded unsupported/admission result, never a retry loop.
- Hosts without the new adapter must report the capability as unsupported. The
  evidence here does not support a compatibility shim based on counting threads,
  archiving sessions, or launching a separate app-server.

## Primary sources

- [Issue #150](https://github.com/fagenorn/nix-config/issues/150), live acceptance
  and scope.
- [Issue #122](https://github.com/fagenorn/nix-config/issues/122), conformance
  domain/report acceptance implemented by the cited source.
- Repository sources cited inline: `conformance-registry.py`,
  `conformance-checks.py`, `conformance.py`, `workflow-state.py`,
  `orchestrate-issues/SKILL.md`, and `from-issue/standards-review.md`.
- [Official Codex App Server documentation](https://learn.chatgpt.com/docs/app-server).
- [Official Codex non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode).
- Codex CLI 0.153.1 generated schema bundle at
  `/private/tmp/nix-codex-appserver-schema-20260920/codex_app_server_protocol.v2.schemas.json`.

## Current-session declaration clarification — 2026-09-20

The collaboration tool instructions for this session explicitly declare four concurrent agent slots, including root. This is useful static host configuration; the API inventory above should not be read as claiming that no declared numeric budget exists anywhere. What remains absent is an authoritative dynamic query/reservation transaction that binds availability, all required roles, native launch and correlated release atomically. Visible thread metadata and a static ceiling still cannot prove a live slot is reserved.

Root refreshed #150's live body again during #117: it remains open with no comments and no native blockers. The current acceptance still requires a **supported host route**, in addition to the limited-slot replay. A deterministic fixture host can prove the state machine and supply an honestly labeled baseline, but by itself it does not prove integration with this native host or authorize calling unsupported native capacity “supported.” Both Claude and Codex entry paths must use a supported capability or return explicit unsupported-capability results. Do not close the issue by satisfying only the replay while omitting the actual route requirement.
