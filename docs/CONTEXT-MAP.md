# Context Map

## Areas

| Area | Context file | Gist | governs |
|---|---|---|---|
| Delivery | [CONTEXT](./areas/delivery/CONTEXT.md) | Carrying an issue to merge: lanes, skills, programs, plans, test suite | `home/common/agent-skills/skills/**`, `home/common/claude-code/skills/**`, `home/common/agent-skills/default.nix`, `lib/impeccable.nix`, `python/agent_tools/lane_triage.py`, `python/agent_tools/issue_branch.py`, `python/agent_tools/artifact_budget.py`, `python/agent_tools/suite_runner.py`, `python/agent_tools/run_profile.py`, `python/agent_tools/host_admission.py` |
| Verification | [CONTEXT](./areas/verification/CONTEXT.md) | Post-merge checks of held issues and recorded verification passes | `python/agent_tools/verify_*.py`, `python/agent_tools/verified_tree.py`, `home/common/verify-pending/**`, `hosts/common/darwin-verify-pending.nix` |
| Claims | [CONTEXT](./areas/claims/CONTEXT.md) | Who delivers an issue, landing locks, owner asks and issue links | `python/agent_tools/claims/**` |
| Release | [CONTEXT](./areas/release/CONTEXT.md) | Releasing a project through profiles, adapters and the transaction core | `python/agent_tools/release*.py`, `python/agent_tools/transaction_*.py`, `python/agent_tools/*_adapter.py` |
| Project contract | [CONTEXT](./areas/project-contract/CONTEXT.md) | The authored project contract, its resolution, adoption and platform manifest | `python/agent_tools/resolve_project.py`, `python/agent_tools/adopt_*.py`, `python/agent_tools/agent_platform.py`, `python/agent_tools/fallback_audit.py`, `home/common/agent-skills/platform-manifest.json`, `.agents/project.json` |
| Guard | [CONTEXT](./areas/guard/CONTEXT.md) | The lifecycle guard that adjudicates pushes, PRs, merges and releases | `home/common/claude-code/lifecycle_guard.py`, `python/agent_tools/guard_policy.py` |
| Hosts | [CONTEXT](./areas/hosts/CONTEXT.md) | Per-host agent runtime: Claude Code install, accounts, cache proxy, launchers | `home/common/claude-code/default.nix`, `home/common/claude-code/accounts/**`, `python/agent_tools/cache_*.py`, `python/agent_tools/subagent_prefix.py`, `python/agent_tools/keepalive_pings.py`, `python/agent_tools/model_pricing.py`, `lib/agent-tools.nix`, `lib/agent-plugins.nix`, `home/common/agent-tools/**`, `patches/agent-plugins/**`, `home/linux/claude-local/**` |
| System | [CONTEXT](./areas/system/CONTEXT.md) | Decisions spanning areas | `*` |

## Terms

| Term | Area |
|---|---|
| Account binding | Hosts |
| Account profile | Hosts |
| Activation unit | Release |
| Adapter | Release |
| Adoption | Project contract |
| Base policy | Guard |
| Blocking edge | Claims |
| Cache proxy | Hosts |
| Candidate | Release |
| Check | Verification |
| Claim | Claims |
| Code map | Delivery |
| Command table | Hosts |
| Compiled policy | Guard |
| Decision prompt | Claims |
| Delivery | Delivery |
| Deprecation | Project contract |
| Derived row | Guard |
| Detaching word | Guard |
| Fleet registry | Project contract |
| Held issue | Verification |
| Keepalive ping | Hosts |
| Land lock | Claims |
| Lane | Delivery |
| Launcher | Hosts |
| Lifecycle verb | Guard |
| Light lane | Delivery |
| Marker | Claims |
| Migration | Project contract |
| Owner prompt | Verification |
| Owner-action marker | Claims |
| Plan-gated floor | Guard |
| Platform manifest | Project contract |
| Prefix reorder | Hosts |
| Probe | Verification |
| Project contract | Project contract |
| Projection | Project contract |
| Publication-free profile | Release |
| Raise label | Guard |
| Receipt | Release |
| Release profile | Release |
| Removal | Project contract |
| ResolvedProject | Project contract |
| Row check | Guard |
| Stale claim | Claims |
| Suite member | Delivery |
| Transaction | Release |
| Triage record | Delivery |
| Verification pass | Verification |
| Verified tree | Verification |
| Verify block | Verification |

## Relationships

- **Delivery → Claims**: a delivery holds a **Claim** and lands under the **Land lock**.
- **Delivery → Verification**: a delivery that leaves evidence criteria holds its issue with a **Verify block**.
- **Verification → Claims**: an **Owner prompt** is an **Owner-action marker**.
- **Release → Guard**: the forge adapter passes each mutation through the guard.
- **Guard → Project contract**: a **Derived row** comes from a resolved **Project contract** and the **Fleet registry**.
- **Hosts → Verification**: every host runs **Verification passes** on a schedule.
- **Project contract → every area**: each command reads the **ResolvedProject**.
