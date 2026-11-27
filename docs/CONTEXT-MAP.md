# Context Map
## Areas
| Area | Context file | Gist | governs |
|---|---|---|---|
| Delivery | [CONTEXT](./areas/delivery/CONTEXT.md) | Carrying an issue to merge: lanes, skills, programs, plans, test suite | `home/common/agent-skills/skills/**`, `home/common/claude-code/skills/**`, `home/common/agent-skills/default.nix`, `lib/impeccable.nix`, `python/agent_tools/delivery/**`, `python/agent_tools/agent_model_matrix.py`, `python/agent_tools/instruction_load.py`, `python/agent_tools/skill_lint.py`, `dotnet/Delivery/**`, `dotnet/Delivery.Tests/**` |
| Verification | [CONTEXT](./areas/verification/CONTEXT.md) | Post-merge checks of held issues and recorded verification passes | `python/agent_tools/verification/**`, `home/common/verify-pending/**`, `hosts/common/darwin-verify-pending.nix`, `dotnet/Verification/**`, `dotnet/Verification.Tests/**` |
| Claims | [CONTEXT](./areas/claims/CONTEXT.md) | Who delivers an issue, landing locks, owner asks and issue links | `python/agent_tools/claims/**`, `dotnet/Claims/**`, `dotnet/Claims.Tests/**` |
| Release | [CONTEXT](./areas/release/CONTEXT.md) | Releasing a project through profiles, adapters and the transaction core | `python/agent_tools/release/**`, `dotnet/Release/**`, `dotnet/Release.Tests/**` |
| Project contract | [CONTEXT](./areas/project-contract/CONTEXT.md) | The authored project contract, its resolution, adoption and platform manifest | `python/agent_tools/project_contract/**`, `home/common/agent-skills/platform-manifest.json`, `.agents/project.json`, `dotnet/ProjectContract/**`, `dotnet/ProjectContract.Tests/**` |
| Guard | [CONTEXT](./areas/guard/CONTEXT.md) | The lifecycle guard that adjudicates pushes, PRs, merges and releases | `home/common/claude-code/lifecycle_guard.py`, `python/agent_tools/guard/**`, `dotnet/Guard/**`, `dotnet/Guard.Tests/**` |
| Hosts | [CONTEXT](./areas/hosts/CONTEXT.md) | Per-host agent runtime: Claude Code install, accounts, cache proxy, launchers | `home/common/claude-code/default.nix`, `home/common/claude-code/accounts/**`, `python/agent_tools/hosts/**`, `lib/agent-tools.nix`, `lib/agent-plugins.nix`, `home/common/agent-tools/**`, `patches/agent-plugins/**`, `home/linux/claude-local/**`, `dotnet/Hosts/**`, `dotnet/Hosts.Tests/**` |
| Console | [CONTEXT](./areas/console/CONTEXT.md) | The local page and service saying whether the owner is needed | `python/agent_tools/console/**`, `home/common/console/**`, `hosts/common/darwin-console.nix`, `home/common/claude-code/console-session-start.sh`, `dotnet/Console/**`, `dotnet/Console.Tests/**` |
| System | [CONTEXT](./areas/system/CONTEXT.md) | Decisions spanning areas | `*`, `dotnet/System/**`, `dotnet/System.Tests/**` |
## Terms
| Term | Area |
|---|---|
| Account binding | Hosts |
| Account label | Console |
| Account profile | Hosts |
| Accounts panel | Console |
| Activation line | Console |
| Activation unit | Release |
| Adapter | Release |
| Adoption | Project contract |
| Approved release path | Guard |
| Answered item | Console |
| Approved adoption | Console |
| Attempt | Delivery |
| Awaiting look | Delivery |
| Base policy | Guard |
| Blocking edge | Claims |
| Cache proxy | Hosts |
| Brief | Console |
| Bring-back | Console |
| Candidate | Release |
| Capacity strip | Console |
| Check | Verification |
| Claim | Claims |
| Cleanup issue | Delivery |
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
| Drafted contract | Console |
| Enforcer | Delivery |
| Engine | Delivery |
| Excluded profile | Console |
| Fixture project | Delivery |
| Fleet preflight | Project contract |
| Fleet registry | Project contract |
| Folder trust | Console |
| Fix change | Delivery |
| Goal | Console |
| Grader | Delivery |
| Guest | Console |
| Held issue | Verification |
| Held work | Console |
| Inbox item | Console |
| Judged rule | Delivery |
| Keepalive ping | Hosts |
| Land lock | Claims |
| Lane | Delivery |
| Last looked | Console |
| Launcher | Hosts |
| Lifecycle verb | Guard |
| Limit reading | Console |
| Limit sensing | Hosts |
| Limit stop | Console |
| Lint-time issue | Delivery |
| Live fault | Console |
| Live-fault lane | Delivery |
| Lock bump | Project contract |
| Look approval | Delivery |
| Look file set | Delivery |
| Look marker | Delivery |
| Manager | Console |
| Marker | Claims |
| Message | Console |
| Merged adoption | Console |
| Migration | Project contract |
| Never-rise check | Project contract |
| Not yet managed | Console |
| Notice | Console |
| Nudge | Console |
| Outcome | Delivery |
| Outside sprints | Console |
| Owner prompt | Verification |
| Owner-action marker | Claims |
| Permission card | Console |
| Picture | Console |
| Pinned profile | Console |
| Plan question | Console |
| Plan-gated floor | Guard |
| Platform command | Project contract |
| Platform constant | Project contract |
| Platform manifest | Project contract |
| Platform package | Project contract |
| Pre-pull-request verification | Project contract |
| Prefix reorder | Hosts |
| Production rule | Guard |
| Probe | Verification |
| Procedure | Delivery |
| Production rules | Project contract |
| Project contract | Project contract |
| Project question | Console |
| Projection | Project contract |
| Proven revision | Project contract |
| Publication-free profile | Release |
| Question round | Console |
| Question thread | Console |
| Quiet project | Console |
| Read-only route | Guard |
| Receipt | Release |
| Registration | Console |
| Release approval | Release |
| Release card | Console |
| Release profile | Release |
| Removal | Project contract |
| Report | Console |
| Retired host | Verification |
| ResolvedProject | Project contract |
| Routed set | Delivery |
| Router | Delivery |
| Row check | Guard |
| Session | Console |
| Sign-in state | Console |
| Spend | Console |
| Spend page | Console |
| Sprint | Console |
| Stale claim | Claims |
| Standard | Delivery |
| Step | Delivery |
| Stop | Delivery |
| Suite member | Delivery |
| Suppression | Delivery |
| Transaction | Release |
| Unknown binding | Project contract |
| Verification pass | Verification |
| Verified tree | Verification |
| Verify block | Verification |
| Waiting since | Console |
- **Console → Claims**: an **Inbox item** from the tracker is a live **Owner-action marker**, read by the claims area's marker reader; an **Inbox item** of a held check is a live **Owner prompt** of Verification, answered through the runner's owner path. **Console → Project contract**: the console's projects are the **Fleet registry**'s entries. **Delivery → Claims, Verification**: a delivery holds a **Claim** and lands under the **Land lock**; one that leaves evidence criteria holds its issue with a **Verify block**. **Verification → Claims**: an **Owner prompt** is an **Owner-action marker**. **Release → Guard**: the forge adapter passes each mutation through the guard. **Guard → Project contract**: a **Derived row** comes from a resolved **Project contract** and the **Fleet registry**. **Project contract → every area**: each command reads the **ResolvedProject**. **Hosts → Verification, Console**: every host runs **Verification passes** on a schedule, and the **Cache proxy** reports each **Limit reading** to the console.
