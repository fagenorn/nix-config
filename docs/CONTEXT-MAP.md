# Context Map

## Areas

| Area | Context file | Gist | governs |
|---|---|---|---|
| Delivery | [CONTEXT](./areas/delivery/CONTEXT.md) | Carrying an issue to merge: lanes, skills, programs, plans, test suite | `home/common/agent-skills/skills/**`, `home/common/claude-code/skills/**`, `home/common/agent-skills/default.nix`, `lib/impeccable.nix`, `python/agent_tools/delivery/**`, `python/agent_tools/agent_model_matrix.py`, `python/agent_tools/instruction_load.py`, `python/agent_tools/skill_lint.py` |
| Verification | [CONTEXT](./areas/verification/CONTEXT.md) | Post-merge checks of held issues and recorded verification passes | `python/agent_tools/verification/**`, `home/common/verify-pending/**`, `hosts/common/darwin-verify-pending.nix` |
| Claims | [CONTEXT](./areas/claims/CONTEXT.md) | Who delivers an issue, landing locks, owner asks and issue links | `python/agent_tools/claims/**` |
| Release | [CONTEXT](./areas/release/CONTEXT.md) | Releasing a project through profiles, adapters and the transaction core | `python/agent_tools/release/**` |
| Project contract | [CONTEXT](./areas/project-contract/CONTEXT.md) | The authored project contract, its resolution, adoption and platform manifest | `python/agent_tools/project_contract/**`, `home/common/agent-skills/platform-manifest.json`, `.agents/project.json` |
| Guard | [CONTEXT](./areas/guard/CONTEXT.md) | The lifecycle guard that adjudicates pushes, PRs, merges and releases | `home/common/claude-code/lifecycle_guard.py`, `python/agent_tools/guard/**` |
| Hosts | [CONTEXT](./areas/hosts/CONTEXT.md) | Per-host agent runtime: Claude Code install, accounts, cache proxy, launchers | `home/common/claude-code/default.nix`, `home/common/claude-code/accounts/**`, `python/agent_tools/hosts/**`, `lib/agent-tools.nix`, `lib/agent-plugins.nix`, `home/common/agent-tools/**`, `patches/agent-plugins/**`, `home/linux/claude-local/**` |
| Console | [CONTEXT](./areas/console/CONTEXT.md) | The local page and service saying whether the owner is needed | `python/agent_tools/console/**`, `home/common/console/**`, `hosts/common/darwin-console.nix`, `home/common/claude-code/console-session-start.sh` |
| System | [CONTEXT](./areas/system/CONTEXT.md) | Decisions spanning areas | `*` |

## Terms

| Term | Area |
|---|---|
| Account binding | Hosts |
| Account profile | Hosts |
| Activation unit | Release |
| Adapter | Release |
| Adoption | Project contract |
| Answered item | Console |
| Base policy | Guard |
| Blocking edge | Claims |
| Cache proxy | Hosts |
| Brief | Console |
| Bring-back | Console |
| Candidate | Release |
| Capacity strip | Console |
| Check | Verification |
| Claim | Claims |
| Code map | Delivery |
| Command table | Hosts |
| Compiled policy | Guard |
| Console | Console |
| Console service | Console |
| Decision prompt | Claims |
| Delivery | Delivery |
| Delivery run | Console |
| Deprecation | Project contract |
| Derived row | Guard |
| Detaching word | Guard |
| Digest | Console |
| Fleet registry | Project contract |
| Goal | Console |
| Held issue | Verification |
| Held work | Console |
| Inbox item | Console |
| Keepalive ping | Hosts |
| Land lock | Claims |
| Lane | Delivery |
| Last looked | Console |
| Launcher | Hosts |
| Lifecycle verb | Guard |
| Light lane | Delivery |
| Limit reading | Console |
| Limit sensing | Hosts |
| Limit stop | Console |
| Manager | Console |
| Marker | Claims |
| Message | Console |
| Migration | Project contract |
| Not yet managed | Console |
| Nudge | Console |
| Outside sprints | Console |
| Owner prompt | Verification |
| Owner-action marker | Claims |
| Plan-gated floor | Guard |
| Platform manifest | Project contract |
| Prefix reorder | Hosts |
| Probe | Verification |
| Project contract | Project contract |
| Projection | Project contract |
| Publication-free profile | Release |
| Question round | Console |
| Quiet project | Console |
| Raise label | Guard |
| Receipt | Release |
| Release profile | Release |
| Removal | Project contract |
| Report | Console |
| ResolvedProject | Project contract |
| Row check | Guard |
| Session | Console |
| Sprint | Console |
| Stale claim | Claims |
| Suite member | Delivery |
| Transaction | Release |
| Triage record | Delivery |
| Verification pass | Verification |
| Verified tree | Verification |
| Verify block | Verification |
| Waiting since | Console |

## Relationships

- **Delivery → Claims**: a delivery holds a **Claim** and lands under the **Land lock**.
- **Delivery → Verification**: a delivery that leaves evidence criteria holds its issue with a **Verify block**.
- **Verification → Claims**: an **Owner prompt** is an **Owner-action marker**.
- **Release → Guard**: the forge adapter passes each mutation through the guard.
- **Guard → Project contract**: a **Derived row** comes from a resolved **Project contract** and the **Fleet registry**.
- **Hosts → Verification**: every host runs **Verification passes** on a schedule.
- **Project contract → every area**: each command reads the **ResolvedProject**.
- **Hosts → Console**: the **Cache proxy** reports each **Limit reading** to the console.
- **Console → Project contract**: the console's projects are the **Fleet registry**'s entries.
- **Console → Claims**: an **Inbox item** from the tracker is a live **Owner-action marker**, read by the claims area's marker reader.
- **Console → Verification**: an **Inbox item** of a held check is a live **Owner prompt**, answered through the runner's owner path.
