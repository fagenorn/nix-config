# Direct autonomous controller budget evidence

## Verdict and scope

- Verdict: `pending`
- Representative trace: run `direct-75-000002`, attempt `1`, owner `75:1`, worktree `/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-75-certify-deployed-direct-autonomous-controller-budget-v2`.
- Reviewed pre-terminal HEAD: `f26dacac3fa7b0414500456aa2e6ffee0105eac4`.
- Budget contract: each D2-required controller's maximum logical single-turn input must be `<=150000`; cached and derived fresh input remain separate.
- Scope: this is one trace only. It cannot establish a universal reduction, percentage, aggregate, counterfactual, or causal native-wait cost.
- Remaining evidence, closed list: the canonical terminal-ledger state/bytes/digest; the representative-run merge; terminal-prefix byte counts and SHA-256 digests for every D2-required controller and the fresh assigned controller retained because adoption is unavailable; every retained controller's D3 maximum record; the final reproduction-matrix replay and D8 verdict; and the final evidence commit identified by the D7 path-scoped query. Additional qualifying controllers add measurement obligations rather than failures; unavailable evidence becomes `unknown` at finalization unless an observed contradiction independently fails.

## Deployment freshness

The issue-74 deployment merge is `f3fac9554761d0c3085d70bf4526cf3e7486de3e` (parents `c780b38f613c59a7d6674dc081d9f67666054ebf` and `f0d8783b3c3c9aa48cc2715f3cf587962189589b`, committed `2026-08-20T18:34:13+01:00`). Its tested base is `c780b38f613c59a7d6674dc081d9f67666054ebf` (committed `2026-08-20T16:01:22+01:00`). The reviewed HEAD is `f26dacac3fa7b0414500456aa2e6ffee0105eac4` (parent `0a7f30718bca3561956cba93454d6be9dc8690a2`, committed `2026-08-20T20:24:22+01:00`). All three objects resolve as commits.

The representative deployment capture recorded generation `/nix/store/xyli57wig0ckrdp9phcpn9w3qij1wfvj-darwin-system-25.11.ebec37a`, activation epoch `1787249448`, rendered `2026-08-20 19:10:48.195903371 +0100` (`2026-08-20T18:10:48.195903371Z`). This comes from record 353 in the acquiring session's sealed observation prefix: first `353` records, `1693527` bytes, SHA-256 `19b61f680fe26638494d744661303b5a99edac4c263a3f9001d369f65251e42c`. The acquiring Codex process/session anchor is session `01a0205e-6256-7200-b4c9-464070fa7964`, whose `session_meta` start is `2026-08-20T18:10:51.625Z` and whose metadata event was written at `2026-08-20T18:10:57.952Z`. The fresh implementation-owner session started at `2026-08-20T19:28:19.703Z`.

| Installed path at capture | Immutable resolved identity | Tracked path | At issue-74 merge | At base |
|---|---|---|---|---|
| `/Users/anis/.agents/skills/from-issue/SKILL.md` | `/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/SKILL.md` | `home/common/agent-skills/skills/from-issue/SKILL.md` | byte-equal | different |
| `/Users/anis/.agents/skills/from-issue/AUTO.md` | `/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/AUTO.md` | `home/common/agent-skills/skills/from-issue/AUTO.md` | byte-equal | different |
| `/Users/anis/.agents/bin/workflow-state` | `/nix/store/4lnap72cp17x7z3pkr0dd2181qy8wrdz-hm_workflowstate.py` | `home/common/agent-skills/scripts/workflow-state.py` | byte-equal | different |

The installed resolutions come from record 110 in the Task-1 implementer session's sealed observation prefix: first `110` records, `1353720` bytes, SHA-256 `971113b571531b23863f265166fe29826639760b9237d94e553fabc2cc1d3ff1`. Reproduction compares the immutable `/nix/store` files, not the mutable Home Manager symlinks. Ordering disposition: `2026-08-20T17:34:13Z <= 2026-08-20T18:10:48.195903371Z < 2026-08-20T18:10:51.625Z`; deployment freshness passes for the observed process/session anchor.

## Lifecycle trace

The acquiring direct-owner session is `01a0205e-6256-7200-b4c9-464070fa7964`. The distinct fresh implementation-owner session is `01a020a5-4ed0-7b33-b1ae-e11e2440769e`; its structured `session_meta` names parent `01a02089-c83e-7682-ad5c-f70c4d841c1e` and agent path `/root/issue_75_remainder/phase6_implementation_owner`.

The exact pre-rollover observation prefix is the first `174` JSONL records of `/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7c6e-74f2-9ab6-c1353b0adf08.jsonl`: `1002268` bytes, SHA-256 `54fff1437807e7dc28c257628d1e99995e23e53ef7b16ba80b5b9eb842835b3c`. This is an observation prefix through Phase 5, not a controller terminal prefix.

The sealed structured observation is `{"timestamp":"2026-08-20T19:24:52.987Z","run_id":"direct-75-000002","issue":75,"attempt":1,"owner":"75:1","worktree":"/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-75-certify-deployed-direct-autonomous-controller-budget-v2","phase":5,"phase_action":"delegate"}`. The source handoff records that same envelope and reviewed HEAD, and the fresh session starts later with a different ID. The fresh session's first message exposes only the plaintext `NEW_TASK` header ending at `Payload:\n`; it contains zero plaintext payload bytes and an encrypted payload body. Whether that hidden body contains the adoption envelope is unknown, so exact adoption comparison is unavailable and remains pending rather than failing. The canonical ledger path is `/Users/anis/tmp/nix-config/.superpowers/workflows/direct-75-000002/state.json`; it remains mutable and its terminal bytes/digest are therefore remaining evidence.

Current structured role inventory, captured from records whose event timestamps are at or before `2026-08-20T20:02:34.967Z`:

| Session | Start (UTC) | Role and structured authority evidence | D2 controller? |
|---|---|---|---|
| `01a0205e-6256-7200-b4c9-464070fa7964` | `2026-08-20T18:10:51.625Z` | invoked `/Users/anis/.agents/bin/workflow-state direct-owner` at `2026-08-20T18:17:23.237Z`; exit 0 returned `kind=owner` for `direct-75-000002`; persisted Phases 0, 1, and 2 | yes |
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
| `01a020a5-4ed0-7b33-b1ae-e11e2440769e` | `2026-08-20T19:28:19.703Z` | `/root/issue_75_remainder/phase6_implementation_owner`; structured dispatch target and session identity observed, but the plaintext ends at the payload header and the adoption body is encrypted/unavailable | unresolved; retained as the assigned fresh controller |
| `01a020aa-6b0b-7f43-a54a-422f1c60fdc2` | `2026-08-20T19:33:54.598Z` | `/root/issue_75_remainder/phase6_implementation_owner/sdd_task_1` bounded SDD implementer | no |
| `01a020aa-6c53-7a51-8207-2f12f87c12fb` | `2026-08-20T19:33:54.915Z` | guardian associated by `session_meta` with resumed root session | no |
| `01a020c0-c9fb-7de2-9b52-cd16e34e89ea` | `2026-08-20T19:58:20.695Z` | `/root/issue_75_remainder/phase6_implementation_owner/sdd_task_1_review` bounded Task-1 reviewer | no |

Four sessions have direct structured acquire/persist authority and therefore qualify as D2-required controllers. The assigned fresh controller is retained in the pending input table because its exact adoption and D2 inclusion are unresolved by the encrypted body. D2 imposes evidence obligations on every qualifying session; neither additional required controllers nor unavailable adoption evidence is itself a failure. The pre-terminal verdict remains `pending`.

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

The sealed R8 query finds exactly five successful pre-delegate `spawn_agent` tasks—`issue75_design_grill`, `issue_75_remainder`, `phase4_planning`, `phase5_remainder`, and `phase5_plan_review`—and joins every structured return target to its exact `session_meta` identity. It directly computes `pre_delegate_sdd_dispatches=0`, `dispatch_session_matches=true`, `inventory_exact=true`, and `no_pre_delegate_sdd=true`. Together with the R2 path result, the no-pre-delegate-SDD and no-pre-delegate-implementation-edit checks pass. The fresh-owner activity sequence is its `session_meta` at `2026-08-20T19:28:19.703Z`, first completed command at `2026-08-20T19:28:31.816Z`, plan validation/SDD setup at `2026-08-20T19:28:59.306Z`, and first SDD task-agent session at `2026-08-20T19:33:54.598Z`.

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

- Anchor: first 353 records of `/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-6256-7200-b4c9-464070fa7964.jsonl`; deployment capture is exact record 353.
- Command:

```bash
{ head -n 353 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-6256-7200-b4c9-464070fa7964.jsonl | wc -c | xargs; head -n 353 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-6256-7200-b4c9-464070fa7964.jsonl | shasum -a 256 | cut -d ' ' -f 1; sed -n '353p' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-6256-7200-b4c9-464070fa7964.jsonl | jq -c 'select(.timestamp=="2026-08-20T18:20:23.842Z" and .type=="event_msg" and .payload.type=="item_completed" and .payload.item.type=="CommandExecution" and ((.payload.item.command|tostring)|contains("readlink /run/current-system"))) | .payload.item as $i | ($i.stdout|split("\n")) as $lines | ($lines|map(select(startswith("'\''/run/current-system'\''")))|first|capture("\\|(?<activation_time>[^|]+)\\|(?<activation_epoch>[0-9]+)$")) as $stat | {observed_at:.timestamp,current_system:$lines[0],activation_time:$stat.activation_time,activation_epoch:($stat.activation_epoch|tonumber),status:$i.status,exit_code:$i.exit_code}'; } | paste -sd ';' -
```

- Observed: `1693527;19b61f680fe26638494d744661303b5a99edac4c263a3f9001d369f65251e42c;{"observed_at":"2026-08-20T18:20:23.842Z","current_system":"/nix/store/xyli57wig0ckrdp9phcpn9w3qij1wfvj-darwin-system-25.11.ebec37a","activation_time":"2026-08-20 19:10:48.195903371 +0100","activation_epoch":1787249448,"status":"completed","exit_code":0}`
- Disposition: `pass`.

### R3b — normalized deployment ordering assertion

- Anchor: issue-74 merge object plus the exact `1693527`-byte R3 prefix with SHA-256 `19b61f680fe26638494d744661303b5a99edac4c263a3f9001d369f65251e42c`.
- Command:

```bash
set -euo pipefail
test "$(head -c 1693527 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-6256-7200-b4c9-464070fa7964.jsonl | shasum -a 256 | cut -d ' ' -f 1)" = 19b61f680fe26638494d744661303b5a99edac4c263a3f9001d369f65251e42c
jq -n -e -c --arg merge_time "$(git show -s --format=%cI f3fac9554761d0c3085d70bf4526cf3e7486de3e)" --argjson merge_epoch "$(git show -s --format=%ct f3fac9554761d0c3085d70bf4526cf3e7486de3e)" --slurpfile r <(head -c 1693527 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-6256-7200-b4c9-464070fa7964.jsonl) '($r[]|select(.type=="session_meta" and .payload.id=="01a0205e-6256-7200-b4c9-464070fa7964")|.payload.timestamp) as $start | ($r[]|select(.timestamp=="2026-08-20T18:20:23.842Z" and .type=="event_msg" and .payload.type=="item_completed" and .payload.item.type=="CommandExecution")|.payload.item.stdout|split("\n")|map(select(startswith("'\''/run/current-system'\''")))|first|capture("\\|(?<activation_time>[^|]+)\\|(?<activation_epoch>[0-9]+)$")) as $activation | ($start|sub("\\.[0-9]+Z$";"Z")|fromdateiso8601) as $start_epoch | {merge_time:$merge_time,merge_time_utc:($merge_epoch|gmtime|strftime("%Y-%m-%dT%H:%M:%SZ")),activation_time:$activation.activation_time,activation_time_utc:(($activation.activation_epoch|tonumber)|gmtime|strftime("%Y-%m-%dT%H:%M:%SZ")),process_session_start:$start,process_session_start_utc:($start_epoch|gmtime|strftime("%Y-%m-%dT%H:%M:%SZ")),merge_le_activation:($merge_epoch<=($activation.activation_epoch|tonumber)),activation_lt_process_session_start:(($activation.activation_epoch|tonumber)<$start_epoch)} | .+{ordered:(.merge_le_activation and .activation_lt_process_session_start)} | select(.ordered)'
```

- Observed: `{"merge_time":"2026-08-20T18:34:13+01:00","merge_time_utc":"2026-08-20T17:34:13Z","activation_time":"2026-08-20 19:10:48.195903371 +0100","activation_time_utc":"2026-08-20T18:10:48Z","process_session_start":"2026-08-20T18:10:51.625Z","process_session_start_utc":"2026-08-20T18:10:51Z","merge_le_activation":true,"activation_lt_process_session_start":true,"ordered":true}`
- Disposition: `pass`.

### R4 — installed definitions

- Anchor: first 110 records of `/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-33-54-01a020aa-6b0b-7f43-a54a-422f1c60fdc2.jsonl`, exact realpath-capture record 110, immutable resolved store files, and full merge/base object IDs.
- Command:

```bash
set -euo pipefail
sed -n '110p' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-33-54-01a020aa-6b0b-7f43-a54a-422f1c60fdc2.jsonl | jq -e 'select(.timestamp=="2026-08-20T19:38:02.269Z" and ((.payload.item.command|tostring)|contains("/Users/anis/.agents/skills/from-issue/SKILL.md /Users/anis/.agents/skills/from-issue/AUTO.md /Users/anis/.agents/bin/workflow-state"))) | .payload.item as $i | (([$i.stdout|split("\n")[]|select(contains("hm_fromissue") or contains("hm_workflowstate"))]) == ["/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/SKILL.md","/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/AUTO.md","/nix/store/4lnap72cp17x7z3pkr0dd2181qy8wrdz-hm_workflowstate.py"] and $i.status=="completed" and $i.exit_code==0)' >/dev/null
cmp -s /nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/SKILL.md <(git show f3fac9554761d0c3085d70bf4526cf3e7486de3e:home/common/agent-skills/skills/from-issue/SKILL.md)
! cmp -s /nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/SKILL.md <(git show c780b38f613c59a7d6674dc081d9f67666054ebf:home/common/agent-skills/skills/from-issue/SKILL.md)
cmp -s /nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/AUTO.md <(git show f3fac9554761d0c3085d70bf4526cf3e7486de3e:home/common/agent-skills/skills/from-issue/AUTO.md)
! cmp -s /nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/AUTO.md <(git show c780b38f613c59a7d6674dc081d9f67666054ebf:home/common/agent-skills/skills/from-issue/AUTO.md)
cmp -s /nix/store/4lnap72cp17x7z3pkr0dd2181qy8wrdz-hm_workflowstate.py <(git show f3fac9554761d0c3085d70bf4526cf3e7486de3e:home/common/agent-skills/scripts/workflow-state.py)
! cmp -s /nix/store/4lnap72cp17x7z3pkr0dd2181qy8wrdz-hm_workflowstate.py <(git show c780b38f613c59a7d6674dc081d9f67666054ebf:home/common/agent-skills/scripts/workflow-state.py)
{ head -n 110 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-33-54-01a020aa-6b0b-7f43-a54a-422f1c60fdc2.jsonl | wc -c | xargs; head -n 110 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-33-54-01a020aa-6b0b-7f43-a54a-422f1c60fdc2.jsonl | shasum -a 256 | cut -d ' ' -f 1; printf '%s\n' '/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/SKILL.md;/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/AUTO.md;/nix/store/4lnap72cp17x7z3pkr0dd2181qy8wrdz-hm_workflowstate.py;SKILL:merge=equal,base=different;AUTO:merge=equal,base=different;workflow-state:merge=equal,base=different'; } | paste -sd ';' -
```

- Observed: `1353720;971113b571531b23863f265166fe29826639760b9237d94e553fabc2cc1d3ff1;/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/SKILL.md;/nix/store/rljfw86192lmwdsf9gi9d9njpfhyjd5z-hm_fromissue/AUTO.md;/nix/store/4lnap72cp17x7z3pkr0dd2181qy8wrdz-hm_workflowstate.py;SKILL:merge=equal,base=different;AUTO:merge=equal,base=different;workflow-state:merge=equal,base=different`
- Disposition: `pass`.

### R4b — acquiring direct-owner executable and result

- Anchor: exact record 246 inside the R3 sealed acquiring-session observation prefix.
- Command:

```bash
sed -n '246p' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-6256-7200-b4c9-464070fa7964.jsonl | jq -c 'select(.timestamp=="2026-08-20T18:17:23.237Z" and .type=="event_msg" and .payload.type=="item_completed" and .payload.item.type=="CommandExecution") | .payload.item as $i | ($i.command[2]|split(" ")) as $argv | ($i.stdout|fromjson) as $owner | {timestamp,executable:$argv[0],verb:$argv[1],run_id:$owner.run_id,issue:$owner.issue,attempt:$owner.attempt,owner:$owner.owner,kind:$owner.kind,status:$i.status,exit_code:$i.exit_code}'
```

- Observed: `{"timestamp":"2026-08-20T18:17:23.237Z","executable":"/Users/anis/.agents/bin/workflow-state","verb":"direct-owner","run_id":"direct-75-000002","issue":75,"attempt":1,"owner":"75:1","kind":"owner","status":"completed","exit_code":0}`
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
sed -n '174p' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7c6e-74f2-9ab6-c1353b0adf08.jsonl | jq -c 'def arg($argv;$name): ($argv|index($name)) as $index | if $index==null then null else $argv[$index+1] end; select(.timestamp=="2026-08-20T19:24:52.987Z" and .type=="event_msg" and .payload.type=="item_completed" and .payload.item.type=="CommandExecution") | .payload.item as $item | select($item.status=="completed" and $item.exit_code==0 and ($item.command|type)=="array" and ($item.command|length)==3 and $item.command[0]=="/bin/zsh" and $item.command[1]=="-lc") | ($item.command[2]|split(" ")) as $argv | ($item.stdout|fromjson) as $result | select($argv[0]=="workflow-state" and $argv[1]=="progress" and arg($argv;"--run-id")=="direct-75-000002" and arg($argv;"--issue")=="75" and arg($argv;"--attempt")=="1" and arg($argv;"--phase")=="5" and $result.issue==75 and $result.attempt==1 and $result.owner=="75:1" and $result.worktree=="/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-75-certify-deployed-direct-autonomous-controller-budget-v2" and $result.phase==5 and $result.phase_action=="delegate") | {timestamp,run_id:arg($argv;"--run-id"),issue:$result.issue,attempt:$result.attempt,owner:$result.owner,worktree:$result.worktree,phase:$result.phase,phase_action:$result.phase_action}'
```

- Observed: `{"timestamp":"2026-08-20T19:24:52.987Z","run_id":"direct-75-000002","issue":75,"attempt":1,"owner":"75:1","worktree":"/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-75-certify-deployed-direct-autonomous-controller-budget-v2","phase":5,"phase_action":"delegate"}`
- Disposition: `pass`.

### R7 — controller identity and sealed rollover ordering

- Anchor: structured `session_meta` plus exact record 174 from the R5 sealed prefix/R6.
- Command:

```bash
jq -n -c --slurpfile d /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-6256-7200-b4c9-464070fa7964.jsonl --slurpfile p <(sed -n '174p' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7c6e-74f2-9ab6-c1353b0adf08.jsonl) --slurpfile f /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-28-19-01a020a5-4ed0-7b33-b1ae-e11e2440769e.jsonl '($d[]|select(.type=="session_meta" and .payload.id=="01a0205e-6256-7200-b4c9-464070fa7964")|.payload|{direct_id:.id,direct_start:.timestamp,direct_cwd:.cwd}) as $direct | ($p[0]|{phase5_at:.timestamp}) as $phase5 | ($f[]|select(.type=="session_meta" and .payload.id=="01a020a5-4ed0-7b33-b1ae-e11e2440769e")|.payload|{fresh_id:.id,fresh_start:.timestamp,fresh_cwd:.cwd,parent:.source.subagent.thread_spawn.parent_thread_id,agent_path:.source.subagent.thread_spawn.agent_path}) as $fresh | $direct+$phase5+$fresh+{distinct:($direct.direct_id!=$fresh.fresh_id),fresh_after_phase5:($fresh.fresh_start>$phase5.phase5_at)}'
```

- Observed: `{"direct_id":"01a0205e-6256-7200-b4c9-464070fa7964","direct_start":"2026-08-20T18:10:51.625Z","direct_cwd":"/Users/anis/tmp/nix-config","phase5_at":"2026-08-20T19:24:52.987Z","fresh_id":"01a020a5-4ed0-7b33-b1ae-e11e2440769e","fresh_start":"2026-08-20T19:28:19.703Z","fresh_cwd":"/Users/anis/tmp/nix-config","parent":"01a02089-c83e-7682-ad5c-f70c4d841c1e","agent_path":"/root/issue_75_remainder/phase6_implementation_owner","distinct":true,"fresh_after_phase5":true}`
- Disposition: `pass`.

### R7b — fresh-owner envelope adoption

- Anchor: exact structured Phase-5 handoff record 310, spawn record 315, fresh `session_meta` record 1, and first incoming owner-message record 10.
- Command:

```bash
jq -s -c '(.[]|select(.type=="response_item" and .payload.type=="agent_message" and .payload.author=="/root/issue_75_remainder/phase5_remainder")|([.payload.content[]|select(.type=="input_text")|.text]|join(""))|split("Payload:\n")[1]|fromjson|{source_envelope:(.owner|{run_id,issue,attempt,owner,worktree}),reviewed_head_sha}) as $handoff | (.[]|select(.type=="response_item" and .payload.type=="function_call" and .payload.name=="spawn_agent")|(.payload.arguments|fromjson)|{spawned_task:.task_name,dispatch_payload_encrypted:(.message|startswith("gAAAA"))}) as $spawn | (.[]|select(.type=="session_meta")|{fresh_session:.payload.id,fresh_start:.payload.timestamp,parent:.payload.source.subagent.thread_spawn.parent_thread_id,agent_path:.payload.source.subagent.thread_spawn.agent_path}) as $fresh | (.[]|select(.type=="response_item" and .payload.type=="agent_message" and .payload.recipient=="/root/issue_75_remainder/phase6_implementation_owner")) as $first | ([$first.payload.content[]|select(.type=="input_text")|.text]|join("")) as $plain | ($handoff+$spawn+$fresh+{incoming_at:$first.timestamp,plaintext_ends_at_payload_header:($plain|endswith("Payload:\n")),plaintext_payload_bytes:($plain|split("Payload:\n")[1]|utf8bytelength),encrypted_body_present:any($first.payload.content[]; .type=="encrypted_content")}) | .+{adoption_comparison:(if .plaintext_payload_bytes==0 and .encrypted_body_present then "unavailable" else "observable" end)}' <(sed -n '310p' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-58-15-01a02089-c83e-7682-ad5c-f70c4d841c1e.jsonl) <(sed -n '315p' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-58-15-01a02089-c83e-7682-ad5c-f70c4d841c1e.jsonl) <(sed -n '1p' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-28-19-01a020a5-4ed0-7b33-b1ae-e11e2440769e.jsonl) <(sed -n '10p' /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-28-19-01a020a5-4ed0-7b33-b1ae-e11e2440769e.jsonl)
```

- Observed: `{"source_envelope":{"run_id":"direct-75-000002","issue":75,"attempt":1,"owner":"75:1","worktree":"/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-75-certify-deployed-direct-autonomous-controller-budget-v2"},"reviewed_head_sha":"f26dacac3fa7b0414500456aa2e6ffee0105eac4","spawned_task":"phase6_implementation_owner","dispatch_payload_encrypted":true,"fresh_session":"01a020a5-4ed0-7b33-b1ae-e11e2440769e","fresh_start":"2026-08-20T19:28:19.703Z","parent":"01a02089-c83e-7682-ad5c-f70c4d841c1e","agent_path":"/root/issue_75_remainder/phase6_implementation_owner","incoming_at":"2026-08-20T19:28:21.556Z","plaintext_ends_at_payload_header":true,"plaintext_payload_bytes":0,"encrypted_body_present":true,"adoption_comparison":"unavailable"}`
- Disposition: `remaining` — the visible plaintext is only the message header; the encrypted body may or may not contain the adoption envelope, so exact comparison is unavailable rather than failed.

### R8 — D2 authority inventory

- Anchor: the `17` run-associated rollout prefixes listed literally as `session|bytes|sha256|absolute path` in the command, each ending at the last captured event at or before `2026-08-20T20:02:34.967Z`; authority is seeded by completed successful parsed `workflow-state direct-owner` acquisitions/adoptions or `workflow-state progress` persistence for the exact `direct-75-000002` identity and recursively closed over structured parent links. The pre-delegate task cutoff is the sealed Phase-5 observation time `2026-08-20T19:24:52.987Z`.
- Command:

```bash
set -euo pipefail
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
while IFS='|' read -r id bytes sha rollout; do
  head -c "$bytes" "$rollout" > "$tmp/$id.jsonl"
  test "$(wc -c < "$tmp/$id.jsonl" | xargs)" = "$bytes"
  test "$(shasum -a 256 "$tmp/$id.jsonl" | cut -d ' ' -f 1)" = "$sha"
done <<'PREFIXES'
01a0205e-6256-7200-b4c9-464070fa7964|2437520|746009b5f458d26de4a349f7adbf4177e19ba15cf198302be752fc60cce8d277|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-6256-7200-b4c9-464070fa7964.jsonl
01a0205e-62ae-75d3-9c11-f9760bd34d33|341650|6da32e339f85914afde26c8d9624b40dd74dfc5c13948ca2f990e77fa3a5aa1d|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-10-51-01a0205e-62ae-75d3-9c11-f9760bd34d33.jsonl
01a0206b-7943-7461-8505-94e1fe312179|1911066|187668156c00b333230785aaec3cee8efa0b339ce9e99c927d7db94a8feb3553|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-25-09-01a0206b-7943-7461-8505-94e1fe312179.jsonl
01a0206b-7a78-7fb3-9a4b-cee44b222c44|244015|eab2ccb36a2cecbb5825173f0c2787897e6523a802ef52efd27f122c3cb1b708|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-25-09-01a0206b-7a78-7fb3-9a4b-cee44b222c44.jsonl
01a02085-d54c-7cf3-923a-1415f260a3c9|1513996|7c5848dd53d3f924a9acfb2585b8e51df80967eace677315e30850abd3ac4dfd|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-53-56-01a02085-d54c-7cf3-923a-1415f260a3c9.jsonl
01a02085-d5d0-70d1-b44c-c6a1845512cd|187554|4ffaef0e50f7f2249188987afdc48c772c70cb7a0621553056121ba0f8772572|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-53-57-01a02085-d5d0-70d1-b44c-c6a1845512cd.jsonl
01a02089-c83e-7682-ad5c-f70c4d841c1e|707327|cdc2e9219019dbb6b0ec6aecdfcb242af44b8c9e35ffd74334c5a88262de830d|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-58-15-01a02089-c83e-7682-ad5c-f70c4d841c1e.jsonl
01a0208a-ddfb-7511-8862-c9a8ecee253d|3991406|d19528f0486f570b9f1f5e12571231440b44eca818d678e35f547c65964a3c95|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-59-26-01a0208a-ddfb-7511-8862-c9a8ecee253d.jsonl
01a0208a-de71-7711-947a-d8ad9c966fad|246676|6a25f089c586a907365911a24814422ad980bbb0eb1839b7f60b0841c3cc7ad4|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T19-59-26-01a0208a-de71-7711-947a-d8ad9c966fad.jsonl
01a02098-7c6e-74f2-9ab6-c1353b0adf08|1069766|a43f3888c760e3b51e23891c791503d2cdcb0a3e98b3e4067df933f8c10cad7d|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7c6e-74f2-9ab6-c1353b0adf08.jsonl
01a02098-7dbc-7570-813b-971d78c97abb|183079|79d6eda0c1f46c336ea471ca496b93cf1e73e8fb8389333fd540fed6bee7ed37|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-14-19-01a02098-7dbc-7570-813b-971d78c97abb.jsonl
01a0209b-2867-71e3-91da-d35cd7693928|1217432|a3829bba6d55873392157873eac241e392db5eb5e91b2cb980e78979f27ec251|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-17-14-01a0209b-2867-71e3-91da-d35cd7693928.jsonl
01a0209b-28e9-7a71-942e-5a36e8b58601|72008|f0112959427a69529567f1d571c7c12c2763337ed11289eb322bb50df25f807d|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-17-14-01a0209b-28e9-7a71-942e-5a36e8b58601.jsonl
01a020a5-4ed0-7b33-b1ae-e11e2440769e|872739|5c6e3affe12939971bcd65c8d99ec325be400ea3540cca49e6c3cb0c74bb237b|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-28-19-01a020a5-4ed0-7b33-b1ae-e11e2440769e.jsonl
01a020aa-6b0b-7f43-a54a-422f1c60fdc2|2195637|ce73dae17682b6fe45aff8c60c6f034e4f7699cc30afabae0e5dbf0194d65965|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-33-54-01a020aa-6b0b-7f43-a54a-422f1c60fdc2.jsonl
01a020aa-6c53-7a51-8207-2f12f87c12fb|120973|d8f9e6a9ec41d9b29f46b8e184cad0c9e0831f5c248023543c90802523042ff2|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-33-54-01a020aa-6c53-7a51-8207-2f12f87c12fb.jsonl
01a020c0-c9fb-7de2-9b52-cd16e34e89ea|430043|bb344d6f4b5eab12dce96d84301f26fe560e707819ed297a3764665e24d6618c|/Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-58-20-01a020c0-c9fb-7de2-9b52-cd16e34e89ea.jsonl
PREFIXES
find "$tmp" -maxdepth 1 -type f -name '*.jsonl' -exec jq -s -c 'def cutoff: "2026-08-20T20:02:34.967Z"; def delegate: "2026-08-20T19:24:52.987Z"; def objectjson: (fromjson? | if type=="object" then . else null end); def arg($argv;$name): ($argv|index($name)) as $index | if $index==null then null else $argv[$index+1] end; . as $all | ([$all[]|select(.type=="session_meta" and .timestamp<=cutoff)|(.payload.source as $source|{id:.payload.id,start:.payload.timestamp,parent:(if ($source|type)=="object" then ($source.subagent.thread_spawn.parent_thread_id//.payload.session_id//null) else null end),agent_path:(if ($source|type)=="object" then ($source.subagent.thread_spawn.agent_path//null) else null end),guardian:(if ($source|type)=="object" then ($source.subagent.other=="guardian") else false end)})]|first) as $meta | {meta:$meta,authority:[$all[]|select(.timestamp<=cutoff and .type=="event_msg" and .payload.type=="item_completed" and .payload.item.type=="CommandExecution")|.payload.item as $item|select($item.status=="completed" and $item.exit_code==0 and ($item.command|type)=="array" and ($item.command|length)==3 and $item.command[0]=="/bin/zsh" and $item.command[1]=="-lc")|($item.command[2]|capture("^(?:now=\\$\\(date -u \\+%Y-%m-%dT%H:%M:%SZ\\); )?(?<executable>/Users/anis/\\.agents/bin/workflow-state|~/\\.agents/bin/workflow-state|workflow-state) (?<verb>direct-owner|progress) (?<args>.*)$")?) as $invocation|select($invocation!=null)|($invocation.args|split(" ")) as $argv|(($item.stdout//"")|objectjson) as $result|select($result!=null and $result.issue==75 and $result.attempt==1 and $result.owner=="75:1" and $result.worktree=="/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-75-certify-deployed-direct-autonomous-controller-budget-v2" and (if $invocation.verb=="direct-owner" then $result.kind=="owner" and $result.run_id=="direct-75-000002" else arg($argv;"--run-id")=="direct-75-000002" and arg($argv;"--issue")=="75" and arg($argv;"--attempt")=="1" and ($result.phase|type)=="number" and ($result.phase_action=="continue" or $result.phase_action=="handoff" or $result.phase_action=="delegate") end))|{kind:($result.kind//"progress"),phase:($result.phase//null),phase_action:($result.phase_action//null)}],dispatches:[$all[]|select(.timestamp<delegate and .type=="response_item" and .payload.type=="function_call" and .payload.name=="spawn_agent")|. as $call|(.payload.arguments|fromjson) as $args|([$all[]|select(.type=="response_item" and .payload.type=="function_call_output" and .payload.call_id==$call.payload.call_id)|.payload.output]|first|fromjson?) as $result|select($result!=null)|{source:$meta.id,at:.timestamp,task:$args.task_name,target:$result.task_name}]}' {} \; | jq -s -c 'map(select(.meta!=null)) as $sessions | [$sessions[]|select((.authority|length)>0)|.meta.id] as $seeds | def closure($ids): [$sessions[] as $s|select($s.meta.parent!=null and any($ids[]; .==$s.meta.parent))|$s.meta.id] as $children | (($ids+$children)|unique) as $all | if ($all|length)==($ids|length) then $all else closure($all) end; closure($seeds) as $ids | [$sessions[] as $s|select(any($ids[]; .==$s.meta.id) and $s.meta.start<="2026-08-20T20:02:34.967Z")|{id:$s.meta.id,start:$s.meta.start,parent:$s.meta.parent,agent_path:$s.meta.agent_path,guardian:$s.meta.guardian,authority:[$s.authority[]|if .phase==null then .kind else "\(.kind):\(.phase):\(.phase_action)" end]}]|sort_by(.start) as $inventory | [[$sessions[].dispatches[]] as $dispatches|$dispatches[]|. as $d|([$inventory[]|select(.agent_path==$d.target)|.id]|first) as $session|$d+{session:$session,session_match:($session!=null)}]|sort_by(.at) as $dispatches | {session_count:($inventory|length),controllers:[$inventory[]|select((.authority|length)>0)|{id,authority}],pre_delegate_dispatches:$dispatches,pre_delegate_sdd_dispatches:([$dispatches[]|select(.task|ascii_downcase|test("(^|_)sdd($|_)"))]|length),dispatch_session_matches:all($dispatches[];.session_match),inventory_exact:([$dispatches[]|{task,session}]==[{"task":"issue75_design_grill","session":"01a0206b-7943-7461-8505-94e1fe312179"},{"task":"issue_75_remainder","session":"01a02089-c83e-7682-ad5c-f70c4d841c1e"},{"task":"phase4_planning","session":"01a0208a-ddfb-7511-8862-c9a8ecee253d"},{"task":"phase5_remainder","session":"01a02098-7c6e-74f2-9ab6-c1353b0adf08"},{"task":"phase5_plan_review","session":"01a0209b-2867-71e3-91da-d35cd7693928"}]),no_pre_delegate_sdd:(([$dispatches[]|select(.task|ascii_downcase|test("(^|_)sdd($|_)"))]|length)==0 and all($dispatches[];.session_match))}'
```

- Observed: `{"session_count":17,"controllers":[{"id":"01a0205e-6256-7200-b4c9-464070fa7964","authority":["owner","progress:0:continue","progress:1:continue","progress:2:handoff","progress:2:handoff"]},{"id":"01a02085-d54c-7cf3-923a-1415f260a3c9","authority":["owner","progress:3:delegate"]},{"id":"01a02089-c83e-7682-ad5c-f70c4d841c1e","authority":["progress:4:delegate"]},{"id":"01a02098-7c6e-74f2-9ab6-c1353b0adf08","authority":["progress:5:delegate"]}],"pre_delegate_dispatches":[{"source":"01a0205e-6256-7200-b4c9-464070fa7964","at":"2026-08-20T18:25:09.431Z","task":"issue75_design_grill","target":"/root/issue75_design_grill","session":"01a0206b-7943-7461-8505-94e1fe312179","session_match":true},{"source":"01a02085-d54c-7cf3-923a-1415f260a3c9","at":"2026-08-20T18:58:15.733Z","task":"issue_75_remainder","target":"/root/issue_75_remainder","session":"01a02089-c83e-7682-ad5c-f70c4d841c1e","session_match":true},{"source":"01a02089-c83e-7682-ad5c-f70c4d841c1e","at":"2026-08-20T18:59:26.835Z","task":"phase4_planning","target":"/root/issue_75_remainder/phase4_planning","session":"01a0208a-ddfb-7511-8862-c9a8ecee253d","session_match":true},{"source":"01a02089-c83e-7682-ad5c-f70c4d841c1e","at":"2026-08-20T19:14:19.344Z","task":"phase5_remainder","target":"/root/issue_75_remainder/phase5_remainder","session":"01a02098-7c6e-74f2-9ab6-c1353b0adf08","session_match":true},{"source":"01a02098-7c6e-74f2-9ab6-c1353b0adf08","at":"2026-08-20T19:17:14.435Z","task":"phase5_plan_review","target":"/root/issue_75_remainder/phase5_remainder/phase5_plan_review","session":"01a0209b-2867-71e3-91da-d35cd7693928","session_match":true}],"pre_delegate_sdd_dispatches":0,"dispatch_session_matches":true,"inventory_exact":true,"no_pre_delegate_sdd":true}`
- Disposition: `pass` — the sealed inventory contains `17` sessions; parsed successful owner/progress authority identifies four required controllers; the exact five-entry structured pre-delegate dispatch/task inventory joins to five session identities and directly asserts no pre-delegate SDD; read-only `observe` results do not seed authority; and the assigned fresh controller remains retained for measurement with adoption classification pending in R7b.

### R8b — sealed fresh-owner activity sequence

- Anchor: exact fresh-owner prefix `872739` bytes with SHA-256 `5c6e3affe12939971bcd65c8d99ec325be400ea3540cca49e6c3cb0c74bb237b`, and exact Task-1 implementer prefix `2195637` bytes with SHA-256 `ce73dae17682b6fe45aff8c60c6f034e4f7699cc30afabae0e5dbf0194d65965`.
- Command:

```bash
set -euo pipefail
test "$(head -c 872739 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-28-19-01a020a5-4ed0-7b33-b1ae-e11e2440769e.jsonl | shasum -a 256 | cut -d ' ' -f 1)" = 5c6e3affe12939971bcd65c8d99ec325be400ea3540cca49e6c3cb0c74bb237b
test "$(head -c 2195637 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-33-54-01a020aa-6b0b-7f43-a54a-422f1c60fdc2.jsonl | shasum -a 256 | cut -d ' ' -f 1)" = ce73dae17682b6fe45aff8c60c6f034e4f7699cc30afabae0e5dbf0194d65965
jq -s -c '(.[]|select(.type=="session_meta" and .payload.id=="01a020a5-4ed0-7b33-b1ae-e11e2440769e")|{fresh_session:.payload.id,fresh_start:.payload.timestamp}) as $meta | ([.[]|select(.type=="event_msg" and .payload.type=="item_completed" and .payload.item.type=="CommandExecution")|.timestamp]|min) as $first_command | ([.[]|select(.type=="event_msg" and .payload.type=="item_completed" and .payload.item.type=="CommandExecution" and ((.payload.item.command|tostring)|contains("artifact-budget check --kind implementation-plan")) and ((.payload.item.command|tostring)|contains("sdd-workspace")))|.timestamp]|min) as $sdd_setup | (.[]|select(.type=="session_meta" and .payload.id=="01a020aa-6b0b-7f43-a54a-422f1c60fdc2")|{sdd_session:.payload.id,sdd_start:.payload.timestamp,sdd_parent:.payload.source.subagent.thread_spawn.parent_thread_id,sdd_path:.payload.source.subagent.thread_spawn.agent_path}) as $sdd | $meta+{first_command_at:$first_command,first_sdd_setup_at:$sdd_setup}+$sdd' <(head -c 872739 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-28-19-01a020a5-4ed0-7b33-b1ae-e11e2440769e.jsonl) <(head -c 2195637 /Users/anis/.codex/sessions/2026/08/20/rollout-2026-08-20T20-33-54-01a020aa-6b0b-7f43-a54a-422f1c60fdc2.jsonl)
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

- Anchor: every absolute rollout path retained in the controller table.
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
