# Direct autonomous controller budget evidence

## Verdict and scope

- Verdict: `pending`
- Representative trace: run `direct-75-000002`, attempt `1`, owner `75:1`, worktree `/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-75-certify-deployed-direct-autonomous-controller-budget-v2`.
- Reviewed pre-terminal HEAD: `f26dacac3fa7b0414500456aa2e6ffee0105eac4`.
- Budget contract: each D2-required controller's maximum logical single-turn input must be `<=150000`; cached and derived fresh input remain separate.
- Scope: this is one trace only. It cannot establish a universal reduction, percentage, aggregate, counterfactual, or causal native-wait cost.
- Remaining evidence, closed list: the canonical terminal-ledger state/bytes/digest; the representative-run merge; terminal-prefix byte counts and SHA-256 digests for both design-expected controller classes and the three additional D2-promoted controller sessions observed below; every required controller's D3 maximum record; the final reproduction-matrix replay and D8 verdict; and the final evidence commit identified by the D7 path-scoped query.

## Deployment freshness

The issue-74 deployment merge is `f3fac9554761d0c3085d70bf4526cf3e7486de3e` (parents `c780b38f613c59a7d6674dc081d9f67666054ebf` and `f0d8783b3c3c9aa48cc2715f3cf587962189589b`, committed `2026-08-20T18:34:13+01:00`). Its tested base is `c780b38f613c59a7d6674dc081d9f67666054ebf` (committed `2026-08-20T16:01:22+01:00`). The reviewed HEAD is `f26dacac3fa7b0414500456aa2e6ffee0105eac4` (parent `0a7f30718bca3561956cba93454d6be9dc8690a2`, committed `2026-08-20T20:24:22+01:00`). All three objects resolve as commits.

The activated generation is `/nix/store/xyli57wig0ckrdp9phcpn9w3qij1wfvj-darwin-system-25.11.ebec37a`. Platform `stat` recorded activation epoch `1787249448`, rendered `2026-08-20 19:10:48.195903371 +0100` (`2026-08-20T18:10:48.195903371Z`). The acquiring Codex process/session anchor is session `01a0205e-6256-7200-b4c9-464070fa7964`, whose `session_meta` start is `2026-08-20T18:10:51.625Z` and whose metadata event was written at `2026-08-20T18:10:57.952Z`. The fresh implementation-owner session started at `2026-08-20T19:28:19.703Z`.

| Installed path | Resolved installed identity | Tracked path | At issue-74 merge | At base |
|---|---|---|---|---|
| `/Users/anis/.agents/skills/from-issue/SKILL.md` | `/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/SKILL.md` | `home/common/agent-skills/skills/from-issue/SKILL.md` | byte-equal | different |
| `/Users/anis/.agents/skills/from-issue/AUTO.md` | `/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/AUTO.md` | `home/common/agent-skills/skills/from-issue/AUTO.md` | byte-equal | different |
| `/Users/anis/.agents/bin/workflow-state` | `/nix/store/4lnap72cp17x7z3pkr0dd2181qy8wrdz-hm_workflowstate.py` | `home/common/agent-skills/scripts/workflow-state.py` | byte-equal | different |

Ordering disposition: `2026-08-20T17:34:13Z <= 2026-08-20T18:10:48.195903371Z < 2026-08-20T18:10:51.625Z`; deployment freshness passes for the observed process/session anchor.

## Lifecycle trace

The acquiring direct-owner session is `01a0205e-6256-7200-b4c9-464070fa7964`. The distinct fresh implementation-owner session is `01a020a5-4ed0-7b33-b1ae-e11e2440769e`; its structured `session_meta` names parent `01a02089-c83e-7682-ad5c-f70c4d841c1e` and agent path `/root/issue_75_remainder/phase6_implementation_owner`.

The exact pre-rollover observation prefix is the first `174` JSONL records of `/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7c6e-74f2-9ab6-c1353b0adf08.jsonl`: `1002268` bytes, SHA-256 `54fff1437807e7dc28c257628d1e99995e23e53ef7b16ba80b5b9eb842835b3c`. This is an observation prefix through Phase 5, not a controller terminal prefix.

The sealed structured observation is `{"timestamp":"2026-08-20T19:24:52.987Z","run_id":"direct-75-000002","issue":75,"attempt":1,"owner":"75:1","worktree":"/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-75-certify-deployed-direct-autonomous-controller-budget-v2","phase":5,"phase_action":"delegate"}`. The source handoff records that same envelope and reviewed HEAD, and the fresh session starts later with a different ID. Its structured dispatch and first incoming message are encrypted, however, so an exact fresh-owner adoption record cannot be observed or compared. This required pre-terminal fact is unavailable and therefore fails rather than remaining. The canonical ledger path is `/Users/anis/tmp/nix-config/.superpowers/workflows/direct-75-000002/state.json`; it remains mutable and its terminal bytes/digest are therefore remaining evidence.

Current structured role inventory, captured through the structured session start `2026-08-20T20:02:34.967Z`:

| Session | Start (UTC) | Role and structured authority evidence | D2 controller? |
|---|---|---|---|
| `01a0205e-6256-7200-b4c9-464070fa7964` | `2026-08-20T18:10:51.625Z` | direct acquisition; returned `kind=owner`; persisted Phases 0, 1, and 2 | yes |
| `01a0205e-62ae-75d3-9c11-f9760bd34d33` | `2026-08-20T18:10:51.708Z` | guardian child of acquiring session | no |
| `01a0206b-7943-7461-8505-94e1fe312179` | `2026-08-20T18:25:09.467Z` | `/root/issue75_design_grill` bounded design worker | no |
| `01a0206b-7a78-7fb3-9a4b-cee44b222c44` | `2026-08-20T18:25:09.766Z` | guardian associated by `session_meta` with acquiring root session | no |
| `01a02085-d54c-7cf3-923a-1415f260a3c9` | `2026-08-20T18:53:56.968Z` | direct resume; returned `kind=owner`; persisted Phase 3 | yes, promoted |
| `01a02085-d5d0-70d1-b44c-c6a1845512cd` | `2026-08-20T18:53:57.091Z` | guardian child of resumed session | no |
| `01a02089-c83e-7682-ad5c-f70c4d841c1e` | `2026-08-20T18:58:15.768Z` | `/root/issue_75_remainder`; persisted Phase 4 | yes, promoted |
| `01a0208a-ddfb-7511-8862-c9a8ecee253d` | `2026-08-20T18:59:26.870Z` | `/root/issue_75_remainder/phase4_planning` bounded planner | no |
| `01a0208a-de71-7711-947a-d8ad9c966fad` | `2026-08-20T18:59:26.978Z` | guardian associated by `session_meta` with resumed root session | no |
| `01a02098-7c6e-74f2-9ab6-c1353b0adf08` | `2026-08-20T19:14:19.406Z` | `/root/issue_75_remainder/phase5_remainder`; persisted Phase 5 | yes, promoted |
| `01a02098-7dbc-7570-813b-971d78c97abb` | `2026-08-20T19:14:19.722Z` | guardian associated by `session_meta` with resumed root session | no |
| `01a0209b-2867-71e3-91da-d35cd7693928` | `2026-08-20T19:17:14.499Z` | `/root/issue_75_remainder/phase5_remainder/phase5_plan_review` bounded reviewer | no |
| `01a0209b-28e9-7a71-942e-5a36e8b58601` | `2026-08-20T19:17:14.620Z` | guardian associated by `session_meta` with resumed root session | no |
| `01a020a5-4ed0-7b33-b1ae-e11e2440769e` | `2026-08-20T19:28:19.703Z` | `/root/issue_75_remainder/phase6_implementation_owner`; structured dispatch target and session identity observed, but exact adoption envelope is encrypted/unavailable | unresolved; retained as the design-expected fresh controller |
| `01a020aa-6b0b-7f43-a54a-422f1c60fdc2` | `2026-08-20T19:33:54.598Z` | `/root/issue_75_remainder/phase6_implementation_owner/sdd_task_1` bounded SDD implementer | no |
| `01a020aa-6c53-7a51-8207-2f12f87c12fb` | `2026-08-20T19:33:54.915Z` | guardian associated by `session_meta` with resumed root session | no |
| `01a020c0-c9fb-7de2-9b52-cd16e34e89ea` | `2026-08-20T19:58:20.695Z` | `/root/issue_75_remainder/phase6_implementation_owner/sdd_task_1_review` bounded Task-1 reviewer | no |
| `01a020c4-ab48-7172-b9d1-8d358b7821de` | `2026-08-20T20:02:34.967Z` | guardian associated by `session_meta` with resumed root session | no |

The intended two-controller ownership boundary already fails: four sessions have direct structured acquire/persist authority, including three pre-rollover sessions beyond the acquiring controller. That lower bound already exceeds two. The design-expected fresh controller is retained in the pending input table, but its exact adoption and D2 inclusion remain unresolved because the adoption payload is unavailable. These failures are retained while the pre-terminal verdict remains `pending`.

## Controller input

No provisional maximum is reported. D3 selection waits until each required session's relevant terminal prefix is closed.

| role | session | prefix path | bytes | sha256 | selected at | logical | cached | fresh | <=150000 | status |
|---|---|---|---|---|---|---|---|---|---|---|
| acquiring direct controller | `01a0205e-6256-7200-b4c9-464070fa7964` | `/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-6256-7200-b4c9-464070fa7964.jsonl` | remaining | remaining | remaining | remaining | remaining | remaining | remaining | remaining | pending |
| resumed pre-rollover controller | `01a02085-d54c-7cf3-923a-1415f260a3c9` | `/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-53-56-01a02085-d54c-7cf3-923a-1415f260a3c9.jsonl` | remaining | remaining | remaining | remaining | remaining | remaining | remaining | remaining | pending |
| Phase-4 persister | `01a02089-c83e-7682-ad5c-f70c4d841c1e` | `/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-58-15-01a02089-c83e-7682-ad5c-f70c4d841c1e.jsonl` | remaining | remaining | remaining | remaining | remaining | remaining | remaining | remaining | pending |
| Phase-5 persister | `01a02098-7c6e-74f2-9ab6-c1353b0adf08` | `/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7c6e-74f2-9ab6-c1353b0adf08.jsonl` | remaining | remaining | remaining | remaining | remaining | remaining | remaining | remaining | pending |
| fresh implementation controller | `01a020a5-4ed0-7b33-b1ae-e11e2440769e` | `/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-28-19-01a020a5-4ed0-7b33-b1ae-e11e2440769e.jsonl` | remaining | remaining | remaining | remaining | remaining | remaining | remaining | remaining | pending |

## Pre-rollover boundary

The immutable range is `f3fac9554761d0c3085d70bf4526cf3e7486de3e..f26dacac3fa7b0414500456aa2e6ffee0105eac4`. Its exact changed-path result is:

```text
.claude/plans/2026-08-20-direct-autonomous-controller-budget.md
.claude/plans/2026-08-20-direct-autonomous-controller-budget.tasks/task-1.md
.claude/plans/2026-08-20-direct-autonomous-controller-budget.tasks/task-2.md
.claude/specs/2026-08-20-direct-autonomous-controller-budget-design.md
```

Those are exactly the allowed design and complete plan-package paths. There is no implementation path and the evidence report did not yet exist at the reviewed HEAD.

The structured dispatch/task inventory before the sealed `2026-08-20T19:24:52.987Z` observation contains the design worker, Phase-4 planner, Phase-5 worker, and Phase-5 plan reviewer shown above; none has an SDD agent path. Therefore the no-pre-delegate-SDD and no-pre-delegate-implementation-edit checks pass. The fresh-owner activity sequence is its `session_meta` at `2026-08-20T19:28:19.703Z`, first completed command at `2026-08-20T19:28:31.816Z`, plan validation/SDD setup at `2026-08-20T19:28:59.306Z`, and first SDD task-agent session at `2026-08-20T19:33:54.598Z`.

## Historical comparison

| session | absolute rollout path | bytes | full-file sha256 | selected at | logical | cached | fresh |
|---|---|---:|---|---|---:|---:|---:|
| `01a01acf-a82d-7953-813b-401d252e02da` | `/Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T17-16-51-01a01acf-a82d-7953-813b-401d252e02da.jsonl` | `3602290` | `bc0ba7e33587cfdc393edd887722917c32ed31e69e04be5bb0c51cb57b7e27b9` | `2026-08-19T21:06:37.416Z` | `182769` | `177920` | `4849` |
| `01a01bd9-8c37-7181-86de-58c82f6a643a` | `/Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T22-07-17-01a01bd9-8c37-7181-86de-58c82f6a643a.jsonl` | `4825757` | `8a7fcc81553099856293417d4bb6f9e8c948598b9a88b266b5485db506b5eaca` | `2026-08-19T22:38:57.734Z` | `213313` | `210688` | `2625` |

These directly re-extracted rows are descriptive context only. The historical sessions differ from this trace in issue scope, runtime, and workflow. Until the required issue-75 terminal maxima are available, no per-controller comparison is made; no percentage, average, aggregate, counterfactual, universal reduction, or native-wait attribution follows from these observations.

## Reproduction matrix

Each row records exact stdout. Empty successful output is written as `<empty>`.

### R1 — immutable Git anchors

- Anchor: repository object database.
- Command:

```bash
bash -c 'set -euo pipefail; git cat-file -e f3fac9554761d0c3085d70bf4526cf3e7486de3e^{commit}; git cat-file -e c780b38f613c59a7d6674dc081d9f67666054ebf^{commit}; git cat-file -e f26dacac3fa7b0414500456aa2e6ffee0105eac4^{commit}; git show -s --format="%H %P %cI" f3fac9554761d0c3085d70bf4526cf3e7486de3e c780b38f613c59a7d6674dc081d9f67666054ebf f26dacac3fa7b0414500456aa2e6ffee0105eac4 | paste -sd ";" -'
```

- Observed: `f3fac9554761d0c3085d70bf4526cf3e7486de3e c780b38f613c59a7d6674dc081d9f67666054ebf f0d8783b3c3c9aa48cc2715f3cf587962189589b 2026-08-20T18:34:13+01:00;c780b38f613c59a7d6674dc081d9f67666054ebf 0c4981e1258a4d6a008c4e1d0c7a781bbdb0a4a4 6e24fa11ab47188a67aa7cc208e62e6d3818b2a3 2026-08-20T16:01:22+01:00;f26dacac3fa7b0414500456aa2e6ffee0105eac4 0a7f30718bca3561956cba93454d6be9dc8690a2 2026-08-20T20:24:22+01:00`
- Disposition: `pass`.

### R2 — pre-rollover Git paths

- Anchor: `f3fac9554761d0c3085d70bf4526cf3e7486de3e..f26dacac3fa7b0414500456aa2e6ffee0105eac4`.
- Command:

```bash
git diff --name-only f3fac9554761d0c3085d70bf4526cf3e7486de3e f26dacac3fa7b0414500456aa2e6ffee0105eac4 -- | LC_ALL=C sort | paste -sd ',' -
```

- Observed: `.claude/plans/2026-08-20-direct-autonomous-controller-budget.md,.claude/plans/2026-08-20-direct-autonomous-controller-budget.tasks/task-1.md,.claude/plans/2026-08-20-direct-autonomous-controller-budget.tasks/task-2.md,.claude/specs/2026-08-20-direct-autonomous-controller-budget-design.md`
- Disposition: `pass`.

### R3 — activated generation and time

- Anchor: `/run/current-system` at capture.
- Command:

```bash
{ readlink /run/current-system; stat -c '%Y %y' /run/current-system; } | paste -sd ';' -
```

- Observed: `/nix/store/xyli57wig0ckrdp9phcpn9w3qij1wfvj-darwin-system-25.11.ebec37a;1787249448 2026-08-20 19:10:48.195903371 +0100`
- Disposition: `pass`.

### R4 — installed definitions

- Anchor: installed absolute paths versus full merge/base object IDs.
- Command:

```bash
bash -c 'set -euo pipefail; cmp -s /Users/anis/.agents/skills/from-issue/SKILL.md <(git show f3fac9554761d0c3085d70bf4526cf3e7486de3e:home/common/agent-skills/skills/from-issue/SKILL.md); ! cmp -s /Users/anis/.agents/skills/from-issue/SKILL.md <(git show c780b38f613c59a7d6674dc081d9f67666054ebf:home/common/agent-skills/skills/from-issue/SKILL.md); cmp -s /Users/anis/.agents/skills/from-issue/AUTO.md <(git show f3fac9554761d0c3085d70bf4526cf3e7486de3e:home/common/agent-skills/skills/from-issue/AUTO.md); ! cmp -s /Users/anis/.agents/skills/from-issue/AUTO.md <(git show c780b38f613c59a7d6674dc081d9f67666054ebf:home/common/agent-skills/skills/from-issue/AUTO.md); cmp -s /Users/anis/.agents/bin/workflow-state <(git show f3fac9554761d0c3085d70bf4526cf3e7486de3e:home/common/agent-skills/scripts/workflow-state.py); ! cmp -s /Users/anis/.agents/bin/workflow-state <(git show c780b38f613c59a7d6674dc081d9f67666054ebf:home/common/agent-skills/scripts/workflow-state.py); printf "%s;%s;%s;%s\n" "$(realpath /Users/anis/.agents/skills/from-issue/SKILL.md)" "$(realpath /Users/anis/.agents/skills/from-issue/AUTO.md)" "$(realpath /Users/anis/.agents/bin/workflow-state)" "SKILL:merge=equal,base=different;AUTO:merge=equal,base=different;workflow-state:merge=equal,base=different"'
```

- Observed: `/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/SKILL.md;/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/AUTO.md;/nix/store/4lnap72cp17x7z3pkr0dd2181qy8wrdz-hm_workflowstate.py;SKILL:merge=equal,base=different;AUTO:merge=equal,base=different;workflow-state:merge=equal,base=different`
- Disposition: `pass`.

### R5 — sealed Phase-5 observation prefix

- Anchor: first 174 records of `/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7c6e-74f2-9ab6-c1353b0adf08.jsonl`.
- Command:

```bash
{ head -n 174 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7c6e-74f2-9ab6-c1353b0adf08.jsonl | wc -c; head -n 174 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7c6e-74f2-9ab6-c1353b0adf08.jsonl | shasum -a 256; } | xargs
```

- Observed: `1002268 54fff1437807e7dc28c257628d1e99995e23e53ef7b16ba80b5b9eb842835b3c -`
- Disposition: `pass`.

### R6 — Phase-5 delegate fields

- Anchor: record 174 of the R5 prefix.
- Command:

```bash
sed -n '174p' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7c6e-74f2-9ab6-c1353b0adf08.jsonl | jq -c '{timestamp,run_id:(.payload.item.command[2]|capture("--run-id (?<v>[^ ]+)").v),issue:(.payload.item.stdout|fromjson|.issue),attempt:(.payload.item.stdout|fromjson|.attempt),owner:(.payload.item.stdout|fromjson|.owner),worktree:(.payload.item.stdout|fromjson|.worktree),phase:(.payload.item.stdout|fromjson|.phase),phase_action:(.payload.item.stdout|fromjson|.phase_action)}'
```

- Observed: `{"timestamp":"2026-08-20T19:24:52.987Z","run_id":"direct-75-000002","issue":75,"attempt":1,"owner":"75:1","worktree":"/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-75-certify-deployed-direct-autonomous-controller-budget-v2","phase":5,"phase_action":"delegate"}`
- Disposition: `pass`.

### R7 — controller identity and rollover ordering

- Anchor: structured `session_meta` plus R6.
- Command:

```bash
jq -s -c '(.[]|select(.type=="session_meta" and .payload.id=="01a0205e-6256-7200-b4c9-464070fa7964")|.payload|{direct_id:.id,direct_start:.timestamp,direct_cwd:.cwd}) as $d | (.[]|select(.type=="event_msg" and .payload.type=="item_completed" and .payload.item.type=="CommandExecution" and ((.payload.item.stdout//"")|contains("\"phase\":5")))|{phase5_at:.timestamp}) as $p | (.[]|select(.type=="session_meta" and .payload.id=="01a020a5-4ed0-7b33-b1ae-e11e2440769e")|.payload|{fresh_id:.id,fresh_start:.timestamp,fresh_cwd:.cwd,parent:.source.subagent.thread_spawn.parent_thread_id,agent_path:.source.subagent.thread_spawn.agent_path}) as $f | $d+$p+$f+{distinct:($d.direct_id!=$f.fresh_id),fresh_after_phase5:($f.fresh_start>$p.phase5_at)}' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-6256-7200-b4c9-464070fa7964.jsonl /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7c6e-74f2-9ab6-c1353b0adf08.jsonl /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-28-19-01a020a5-4ed0-7b33-b1ae-e11e2440769e.jsonl
```

- Observed: `{"direct_id":"01a0205e-6256-7200-b4c9-464070fa7964","direct_start":"2026-08-20T18:10:51.625Z","direct_cwd":"/Users/anis/tmp/nix-config","phase5_at":"2026-08-20T19:24:52.987Z","fresh_id":"01a020a5-4ed0-7b33-b1ae-e11e2440769e","fresh_start":"2026-08-20T19:28:19.703Z","fresh_cwd":"/Users/anis/tmp/nix-config","parent":"01a02089-c83e-7682-ad5c-f70c4d841c1e","agent_path":"/root/issue_75_remainder/phase6_implementation_owner","distinct":true,"fresh_after_phase5":true}`
- Disposition: `pass`.

### R7b — fresh-owner envelope adoption

- Anchor: structured Phase-5 handoff, structured spawn call, fresh `session_meta`, and first incoming owner message.
- Command:

```bash
jq -s -c '(.[]|select(.type=="response_item" and .payload.type=="agent_message" and .payload.author=="/root/issue_75_remainder/phase5_remainder")|([.payload.content[]|select(.type=="input_text")|.text]|join(""))|select(contains("\"reviewed_head_sha\""))|split("Payload:\n")[1]|fromjson|{source_envelope:(.owner|{run_id,issue,attempt,owner,worktree}),reviewed_head_sha}) as $handoff | (.[]|select(.type=="response_item" and .payload.type=="function_call" and .payload.name=="spawn_agent" and ((.payload.arguments|fromjson|.task_name)=="phase6_implementation_owner"))|(.payload.arguments|fromjson)|{spawned_task:.task_name,dispatch_payload_encrypted:(.message|startswith("gAAAA"))}) as $spawn | (.[]|select(.type=="session_meta" and .payload.id=="01a020a5-4ed0-7b33-b1ae-e11e2440769e")|{fresh_session:.payload.id,fresh_start:.payload.timestamp,parent:.payload.source.subagent.thread_spawn.parent_thread_id,agent_path:.payload.source.subagent.thread_spawn.agent_path}) as $fresh | ([.[]|select(.type=="response_item" and .payload.type=="agent_message" and .payload.recipient=="/root/issue_75_remainder/phase6_implementation_owner")]|min_by(.timestamp)|{incoming_at:.timestamp,incoming_encrypted:any(.payload.content[]; .type=="encrypted_content")}) as $incoming | $handoff+$spawn+$fresh+$incoming+{adoption_envelope_observable:false}' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-58-15-01a02089-c83e-7682-ad5c-f70c4d841c1e.jsonl /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-28-19-01a020a5-4ed0-7b33-b1ae-e11e2440769e.jsonl
```

- Observed: `{"source_envelope":{"run_id":"direct-75-000002","issue":75,"attempt":1,"owner":"75:1","worktree":"/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-75-certify-deployed-direct-autonomous-controller-budget-v2"},"reviewed_head_sha":"f26dacac3fa7b0414500456aa2e6ffee0105eac4","spawned_task":"phase6_implementation_owner","dispatch_payload_encrypted":true,"fresh_session":"01a020a5-4ed0-7b33-b1ae-e11e2440769e","fresh_start":"2026-08-20T19:28:19.703Z","parent":"01a02089-c83e-7682-ad5c-f70c4d841c1e","agent_path":"/root/issue_75_remainder/phase6_implementation_owner","incoming_at":"2026-08-20T19:28:21.556Z","incoming_encrypted":true,"adoption_envelope_observable":false}`
- Disposition: `fail` — the source envelope, dispatch target, and fresh identity are observable, but the required exact adoption comparison is not.

### R8 — D2 authority inventory

- Anchor: every session-day rollout through `2026-08-20T20:02:34.967Z`, seeded by structured `direct-75-000002` workflow-state authority and recursively closed over structured parent links.
- Command:

```bash
find /Users/anis/.codex/sessions/2026/08/20 -maxdepth 1 -type f -name '*.jsonl' -exec jq -s -c 'def objectjson: (fromjson? | if type=="object" then . else null end); . as $all | ([$all[]|select(.type=="session_meta")|(.payload.source as $source|{id:.payload.id,start:.payload.timestamp,parent:(if ($source|type)=="object" then ($source.subagent.thread_spawn.parent_thread_id//.payload.session_id//null) else null end),agent_path:(if ($source|type)=="object" then ($source.subagent.thread_spawn.agent_path//null) else null end),guardian:(if ($source|type)=="object" then ($source.subagent.other=="guardian") else false end)})]|first) as $meta | {meta:$meta,authority:[$all[]|select(.type=="event_msg" and .payload.type=="item_completed" and .payload.item.type=="CommandExecution" and ((.payload.item.command|tostring)|contains("workflow-state")) and (((((.payload.item.stdout//"")|objectjson)|.run_id//null)=="direct-75-000002") or ((.payload.item.command|tostring)|contains("direct-75-000002"))))|((.payload.item.stdout//"")|objectjson)|select(.!=null)|{kind:(.kind//"progress"),phase:(.phase//null),phase_action:(.phase_action//null)}]}' {} \; | jq -s -c 'map(select(.meta!=null)) as $sessions | [$sessions[]|select((.authority|length)>0)|.meta.id] as $seeds | def closure($ids): [$sessions[] as $s|select($s.meta.parent!=null and any($ids[]; .==$s.meta.parent))|$s.meta.id] as $children | (($ids+$children)|unique) as $all | if ($all|length)==($ids|length) then $all else closure($all) end; closure($seeds) as $ids | [$sessions[] as $s|select(any($ids[]; .==$s.meta.id) and $s.meta.start<="2026-08-20T20:02:34.967Z")|{id:$s.meta.id,start:$s.meta.start,parent:$s.meta.parent,agent_path:$s.meta.agent_path,guardian:$s.meta.guardian,authority:[$s.authority[]|if .phase==null then .kind else "\(.kind):\(.phase):\(.phase_action)" end]}]|sort_by(.start)'
```

- Observed: `[{"id":"01a0205e-6256-7200-b4c9-464070fa7964","start":"2026-08-20T18:10:51.625Z","parent":null,"agent_path":null,"guardian":false,"authority":["observe","observe","owner","progress:0:continue","progress:1:continue","progress:2:handoff","progress:2:handoff"]},{"id":"01a0205e-62ae-75d3-9c11-f9760bd34d33","start":"2026-08-20T18:10:51.708Z","parent":"01a0205e-6256-7200-b4c9-464070fa7964","agent_path":null,"guardian":true,"authority":[]},{"id":"01a0206b-7943-7461-8505-94e1fe312179","start":"2026-08-20T18:25:09.467Z","parent":"01a0205e-6256-7200-b4c9-464070fa7964","agent_path":"/root/issue75_design_grill","guardian":false,"authority":[]},{"id":"01a0206b-7a78-7fb3-9a4b-cee44b222c44","start":"2026-08-20T18:25:09.766Z","parent":"01a0205e-6256-7200-b4c9-464070fa7964","agent_path":null,"guardian":true,"authority":[]},{"id":"01a02085-d54c-7cf3-923a-1415f260a3c9","start":"2026-08-20T18:53:56.968Z","parent":null,"agent_path":null,"guardian":false,"authority":["observe","owner","progress:3:delegate"]},{"id":"01a02085-d5d0-70d1-b44c-c6a1845512cd","start":"2026-08-20T18:53:57.091Z","parent":"01a02085-d54c-7cf3-923a-1415f260a3c9","agent_path":null,"guardian":true,"authority":[]},{"id":"01a02089-c83e-7682-ad5c-f70c4d841c1e","start":"2026-08-20T18:58:15.768Z","parent":"01a02085-d54c-7cf3-923a-1415f260a3c9","agent_path":"/root/issue_75_remainder","guardian":false,"authority":["progress:4:delegate"]},{"id":"01a0208a-ddfb-7511-8862-c9a8ecee253d","start":"2026-08-20T18:59:26.870Z","parent":"01a02089-c83e-7682-ad5c-f70c4d841c1e","agent_path":"/root/issue_75_remainder/phase4_planning","guardian":false,"authority":[]},{"id":"01a0208a-de71-7711-947a-d8ad9c966fad","start":"2026-08-20T18:59:26.978Z","parent":"01a02085-d54c-7cf3-923a-1415f260a3c9","agent_path":null,"guardian":true,"authority":[]},{"id":"01a02098-7c6e-74f2-9ab6-c1353b0adf08","start":"2026-08-20T19:14:19.406Z","parent":"01a02089-c83e-7682-ad5c-f70c4d841c1e","agent_path":"/root/issue_75_remainder/phase5_remainder","guardian":false,"authority":["progress:5:delegate"]},{"id":"01a02098-7dbc-7570-813b-971d78c97abb","start":"2026-08-20T19:14:19.722Z","parent":"01a02085-d54c-7cf3-923a-1415f260a3c9","agent_path":null,"guardian":true,"authority":[]},{"id":"01a0209b-2867-71e3-91da-d35cd7693928","start":"2026-08-20T19:17:14.499Z","parent":"01a02098-7c6e-74f2-9ab6-c1353b0adf08","agent_path":"/root/issue_75_remainder/phase5_remainder/phase5_plan_review","guardian":false,"authority":[]},{"id":"01a0209b-28e9-7a71-942e-5a36e8b58601","start":"2026-08-20T19:17:14.620Z","parent":"01a02085-d54c-7cf3-923a-1415f260a3c9","agent_path":null,"guardian":true,"authority":[]},{"id":"01a020a5-4ed0-7b33-b1ae-e11e2440769e","start":"2026-08-20T19:28:19.703Z","parent":"01a02089-c83e-7682-ad5c-f70c4d841c1e","agent_path":"/root/issue_75_remainder/phase6_implementation_owner","guardian":false,"authority":[]},{"id":"01a020aa-6b0b-7f43-a54a-422f1c60fdc2","start":"2026-08-20T19:33:54.598Z","parent":"01a020a5-4ed0-7b33-b1ae-e11e2440769e","agent_path":"/root/issue_75_remainder/phase6_implementation_owner/sdd_task_1","guardian":false,"authority":[]},{"id":"01a020aa-6c53-7a51-8207-2f12f87c12fb","start":"2026-08-20T19:33:54.915Z","parent":"01a02085-d54c-7cf3-923a-1415f260a3c9","agent_path":null,"guardian":true,"authority":[]},{"id":"01a020c0-c9fb-7de2-9b52-cd16e34e89ea","start":"2026-08-20T19:58:20.695Z","parent":"01a020a5-4ed0-7b33-b1ae-e11e2440769e","agent_path":"/root/issue_75_remainder/phase6_implementation_owner/sdd_task_1_review","guardian":false,"authority":[]},{"id":"01a020c4-ab48-7172-b9d1-8d358b7821de","start":"2026-08-20T20:02:34.967Z","parent":"01a02085-d54c-7cf3-923a-1415f260a3c9","agent_path":null,"guardian":true,"authority":[]}]`
- Disposition: `fail` — enumeration is complete at capture; four sessions have structured acquire/persist authority, already more than the intended two, while fresh-owner D2 inclusion remains unresolved by R7b.

### R8b — fresh-owner activity sequence

- Anchor: fresh-owner and Task-1 implementer structured rollout records.
- Command:

```bash
jq -s -c '(.[]|select(.type=="session_meta" and .payload.id=="01a020a5-4ed0-7b33-b1ae-e11e2440769e")|{fresh_session:.payload.id,fresh_start:.payload.timestamp}) as $meta | ([.[]|select(.type=="event_msg" and .payload.type=="item_completed" and .payload.item.type=="CommandExecution")|.timestamp]|min) as $first_command | ([.[]|select(.type=="event_msg" and .payload.type=="item_completed" and .payload.item.type=="CommandExecution" and ((.payload.item.command|tostring)|contains("artifact-budget check --kind implementation-plan")) and ((.payload.item.command|tostring)|contains("sdd-workspace")))|.timestamp]|min) as $sdd_setup | (.[]|select(.type=="session_meta" and .payload.id=="01a020aa-6b0b-7f43-a54a-422f1c60fdc2")|{sdd_session:.payload.id,sdd_start:.payload.timestamp,sdd_parent:.payload.source.subagent.thread_spawn.parent_thread_id,sdd_path:.payload.source.subagent.thread_spawn.agent_path}) as $sdd | $meta+{first_command_at:$first_command,first_sdd_setup_at:$sdd_setup}+$sdd' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-28-19-01a020a5-4ed0-7b33-b1ae-e11e2440769e.jsonl /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-33-54-01a020aa-6b0b-7f43-a54a-422f1c60fdc2.jsonl
```

- Observed: `{"fresh_session":"01a020a5-4ed0-7b33-b1ae-e11e2440769e","fresh_start":"2026-08-20T19:28:19.703Z","first_command_at":"2026-08-20T19:28:31.816Z","first_sdd_setup_at":"2026-08-20T19:28:59.306Z","sdd_session":"01a020aa-6b0b-7f43-a54a-422f1c60fdc2","sdd_start":"2026-08-20T19:33:54.598Z","sdd_parent":"01a020a5-4ed0-7b33-b1ae-e11e2440769e","sdd_path":"/root/issue_75_remainder/phase6_implementation_owner/sdd_task_1"}`
- Disposition: `pass`.

### R9 — historical session `01a01acf-a82d-7953-813b-401d252e02da`

- Anchor: full fixed rollout path.
- Command:

```bash
jq -s -c 'def integer: if type=="number" then floor==. else false end; . as $all | ($all[]|select(.type=="session_meta")|{session:.payload.id,start:.payload.timestamp,cwd:.payload.cwd}) as $meta | [$all[]|select(.type=="event_msg" and .payload.type=="token_count")|. as $event|$event.payload.info.last_token_usage as $usage|select($usage!=null)|{timestamp:$event.timestamp,logical:$usage.input_tokens,cached:$usage.cached_input_tokens}] as $records | ($records|max_by([.logical,.timestamp])) as $selected | $meta+$selected+{fresh:($selected.logical-$selected.cached)}' /Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T17-16-51-01a01acf-a82d-7953-813b-401d252e02da.jsonl
```

- Observed: `{"session":"01a01acf-a82d-7953-813b-401d252e02da","start":"2026-08-19T16:16:51.788Z","cwd":"/Users/anis/tmp/nix-config","timestamp":"2026-08-19T21:06:37.416Z","logical":182769,"cached":177920,"fresh":4849}`
- Disposition: `pass`.

### R10 — historical session `01a01bd9-8c37-7181-86de-58c82f6a643a`

- Anchor: full fixed rollout path.
- Command:

```bash
jq -s -c 'def integer: if type=="number" then floor==. else false end; . as $all | ($all[]|select(.type=="session_meta")|{session:.payload.id,start:.payload.timestamp,cwd:.payload.cwd}) as $meta | [$all[]|select(.type=="event_msg" and .payload.type=="token_count")|. as $event|$event.payload.info.last_token_usage as $usage|select($usage!=null)|{timestamp:$event.timestamp,logical:$usage.input_tokens,cached:$usage.cached_input_tokens}] as $records | ($records|max_by([.logical,.timestamp])) as $selected | $meta+$selected+{fresh:($selected.logical-$selected.cached)}' /Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T22-07-17-01a01bd9-8c37-7181-86de-58c82f6a643a.jsonl
```

- Observed: `{"session":"01a01bd9-8c37-7181-86de-58c82f6a643a","start":"2026-08-19T21:07:17.204Z","cwd":"/Users/anis/tmp/nix-config","timestamp":"2026-08-19T22:38:57.734Z","logical":213313,"cached":210688,"fresh":2625}`
- Disposition: `pass`.

### R11 — historical full-file identities

- Anchor: both fixed rollout paths.
- Command:

```bash
{ wc -c /Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T17-16-51-01a01acf-a82d-7953-813b-401d252e02da.jsonl; shasum -a 256 /Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T17-16-51-01a01acf-a82d-7953-813b-401d252e02da.jsonl; wc -c /Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T22-07-17-01a01bd9-8c37-7181-86de-58c82f6a643a.jsonl; shasum -a 256 /Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T22-07-17-01a01bd9-8c37-7181-86de-58c82f6a643a.jsonl; } | xargs
```

- Observed: `3602290 /Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T17-16-51-01a01acf-a82d-7953-813b-401d252e02da.jsonl bc0ba7e33587cfdc393edd887722917c32ed31e69e04be5bb0c51cb57b7e27b9 /Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T17-16-51-01a01acf-a82d-7953-813b-401d252e02da.jsonl 4825757 /Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T22-07-17-01a01bd9-8c37-7181-86de-58c82f6a643a.jsonl 8a7fcc81553099856293417d4bb6f9e8c948598b9a88b266b5485db506b5eaca /Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T22-07-17-01a01bd9-8c37-7181-86de-58c82f6a643a.jsonl`
- Disposition: `pass`.

### R12 — terminal ledger

- Anchor: `/Users/anis/tmp/nix-config/.superpowers/workflows/direct-75-000002/state.json`.
- Command/query: remaining evidence; after terminal, capture the exact full bytes and SHA-256 and select compact run/issue/attempt/owner/worktree/state/finished/result/result-source fields.
- Observed: unavailable before terminal.
- Disposition: `remaining`.

### R13 — representative-run merge

- Anchor: issue-75 shipping result.
- Command/query: remaining evidence; resolve and verify the full merge object after shipping.
- Observed: unavailable before shipping.
- Disposition: `remaining`.

### R14 — required controller terminal prefixes and maxima

- Anchor: the five absolute controller rollout paths in the controller table.
- Command/query: remaining evidence; close each prefix at its terminal relay/task-complete record, record exact bytes/SHA-256, and apply D3 independently with the later-timestamp tie-break.
- Observed: unavailable before terminal relay.
- Disposition: `remaining`.

### R15 — final matrix and D8 verdict

- Anchor: clean checkout of the final evidence branch.
- Command/query: remaining evidence; replay every non-remaining row and derive `not certified` if any row fails, otherwise `unknown` if any row is unavailable, otherwise `certified`.
- Observed: unavailable until all terminal rows are closed.
- Disposition: `remaining`.

### R16 — final evidence commit

- Anchor: clean final checkout.
- Command/query: remaining evidence; run `git log -1 --format=%H -- .claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md` and require it to equal full `HEAD`.
- Observed: unavailable before the final evidence commit exists.
- Disposition: `remaining`.
