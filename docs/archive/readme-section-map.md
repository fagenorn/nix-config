# README section map

Where each section of the three READMEs that issue 694 dissolved went: contract text to a module docstring, decisions to ADRs, measurements to this archive, procedures to docs/guides/. A point-in-time record of base commit `58908955a256f53b09ff27702d3e9847ba030708`: paths are as of the commit that last changed this file, and later moves do not rewrite it. Kinds: `contract`, `decision`, `evidence`, `how-to`, `overview`, `superseded`.

| Source | Section | Kind | Destination |
|---|---|---|---|
| `python/README.md` | `verified-tree` | contract | `python/agent_tools/verified_tree.py` |
| `python/README.md` | `verified-tree` | decision | `docs/areas/verification/adr/001-a-recorded-pass-covers-exactly-the-plan.md` |
| `python/README.md` | verify-pending | contract | `python/agent_tools/verify_block.py`, `python/agent_tools/verify_pending.py`, `python/agent_tools/verify_run.py`, `python/agent_tools/verify_issues.py`, `python/agent_tools/verify_exec.py`, `python/agent_tools/verify_facts.py`, `python/agent_tools/verify_owner.py`, `python/agent_tools/verify_checks.py`, `python/agent_tools/keepalive_pings.py`, `home/common/verify-pending/default.nix` |
| `python/README.md` | verify-pending | decision | `docs/areas/verification/adr/002-verify-run-forms-are-an-allowlist.md`, `docs/areas/verification/adr/003-only-verification-commands-run-unattended.md`, `docs/areas/verification/adr/004-only-trusted-authors-count.md`, `docs/areas/verification/adr/005-a-check-is-its-block-version.md`, `docs/areas/verification/adr/006-contracts-read-at-the-integration-commit.md`, `docs/areas/verification/adr/007-a-switch-kicks-a-pass.md`, `docs/areas/verification/adr/008-macs-verify-only-while-logged-in.md`, `docs/areas/verification/adr/009-owner-prompts-settle-on-the-owners-answer.md` |
| `python/README.md` | forge-claim | contract | `python/agent_tools/forge_markers.py`, `python/agent_tools/forge_claim.py` |
| `python/README.md` | forge-claim | decision | `docs/areas/claims/adr/001-markers-decide-labels-filter.md`, `docs/areas/claims/adr/002-stale-claims-are-flagged-never-stolen.md`, `docs/areas/claims/adr/003-forge-time-not-host-time.md` |
| `python/README.md` | forge-claim land | contract | `python/agent_tools/forge_land_lock.py` |
| `python/README.md` | forge-claim land | decision | `docs/areas/claims/adr/004-the-land-lock-is-a-cas-ref.md`, `docs/areas/claims/adr/005-land-lock-staleness-follows-option-b.md` |
| `python/README.md` | forge-claim owner-action | contract | `python/agent_tools/forge_owner_action.py` |
| `python/README.md` | forge-claim owner-action | decision | `docs/areas/claims/adr/006-owner-action-markers-outlive-claims.md` |
| `python/README.md` | forge-issue | contract | `python/agent_tools/forge_issue.py` |
| `python/README.md` | forge-issue | decision | `docs/areas/claims/adr/007-blocking-edges-by-database-id.md` |
| `python/README.md` | owner-actions | contract | `python/agent_tools/owner_actions.py` |
| `python/README.md` | owner-actions | decision | `docs/areas/claims/adr/008-owner-counts-are-cached-for-the-status-line.md` |
| `python/README.md` | Transaction core | contract | `python/agent_tools/transaction_core.py` |
| `python/README.md` | Transaction core | superseded | `docs/areas/release/adr/001-attempts-first-transaction-consumer.md` |
| `python/README.md` | Transaction core | decision | `docs/areas/release/adr/002-release-driver-is-the-core-caller.md` |
| `python/README.md` | Release profiles | contract | `python/agent_tools/release_profile.py`, `python/agent_tools/release.py` |
| `python/README.md` | Release profiles | decision | `docs/areas/release/adr/003-profiles-judged-in-two-tiers.md`, `docs/areas/release/adr/004-publication-free-profiles.md` |
| `python/README.md` | Release adapters | contract | `python/agent_tools/release_adapter.py`, `python/agent_tools/forge_adapter.py`, `python/agent_tools/actions_health_adapter.py`, `python/agent_tools/railway_deploy_adapter.py`, `python/agent_tools/codesigned_artifact_adapter.py`, `python/agent_tools/launchd_agent_adapter.py` |
| `python/README.md` | Release adapters | decision | `docs/areas/release/adr/005-adapters-never-claim-success.md`, `docs/areas/release/adr/006-forge-merge-needs-the-protection-floor.md`, `docs/areas/release/adr/007-deploy-watches-are-activation-units.md` |
| `python/README.md` | Release driver | contract | `python/agent_tools/release_driver.py`, `python/agent_tools/release_verification.py`, `python/agent_tools/release_cutover.py`, `python/agent_tools/release.py` |
| `python/README.md` | Release driver | decision | `docs/areas/release/adr/008-preview-creates-nothing.md` |
| `python/README.md` | adopt-project | contract | `python/agent_tools/adopt_project.py`, `python/agent_tools/adopt_links.py`, `python/agent_tools/adopt_references.py`, `python/agent_tools/adopt_verify.py`, `python/agent_tools/adopt_migrate.py` |
| `python/README.md` | adopt-project | decision | `docs/areas/project-contract/adr/004-adoption-edits-nothing-without-an-answer.md`, `docs/areas/project-contract/adr/005-registration-reads-the-remote.md` |
| `python/README.md` | Platform deprecations | contract | `python/agent_tools/agent_platform.py`, `python/agent_tools/resolve_project.py` |
| `python/README.md` | Platform deprecations | decision | `docs/areas/project-contract/adr/002-platform-2-removes-the-legacy-surfaces.md`, `docs/areas/project-contract/adr/003-deprecation-status-reports-presence.md` |
| `python/README.md` | Platform deprecations | how-to | `docs/guides/retire-the-deploy-watch.md` |
| `python/README.md` | Project schema 2 | contract | `python/agent_tools/resolve_project.py` |
| `python/README.md` | Project schema 2 | decision | `docs/areas/project-contract/adr/001-schema-2-drops-the-deploy-watch.md` |
| `python/README.md` | fallback-audit | contract | `python/agent_tools/fallback_audit.py` |
| `home/common/claude-code/README.md` | Allow surface and lifecycle guard | contract | `home/common/claude-code/lifecycle_guard.py` |
| `home/common/claude-code/README.md` | Detaching words | contract | `home/common/claude-code/lifecycle_guard.py` |
| `home/common/claude-code/README.md` | Detaching words | decision | `docs/areas/guard/adr/001-detaching-words-refused-in-raw-text.md` |
| `home/common/claude-code/README.md` | Transmitting git invocations | contract | `home/common/claude-code/lifecycle_guard.py` |
| `home/common/claude-code/README.md` | Transmitting git invocations | decision | `docs/areas/guard/adr/002-transmitting-git-refused-as-push.md` |
| `home/common/claude-code/README.md` | Adjudicated verbs | contract | `home/common/claude-code/lifecycle_guard.py` |
| `home/common/claude-code/README.md` | Adjudicated verbs | decision | `docs/areas/guard/adr/003-lifecycle-commands-in-an-allowlist-grammar.md`, `docs/areas/guard/adr/008-merge-arms-keep-the-required-check-floor.md` |
| `home/common/claude-code/README.md` | Pre-push hook | contract | `home/common/claude-code/lifecycle_guard.py` |
| `home/common/claude-code/README.md` | Pre-push hook | decision | `docs/areas/guard/adr/004-pre-push-hook-judges-what-git-pushes.md` |
| `home/common/claude-code/README.md` | The raise label | contract | `home/common/claude-code/lifecycle_guard.py` |
| `home/common/claude-code/README.md` | The raise label | decision | `docs/areas/guard/adr/005-raise-label-refusal-catches-mistakes.md` |
| `home/common/claude-code/README.md` | Guard policy | contract | `home/common/claude-code/lifecycle_guard.py`, `python/agent_tools/guard_policy.py` |
| `home/common/claude-code/README.md` | Guard policy | decision | `docs/areas/guard/adr/006-two-policy-files-one-trust-rule-each.md`, `docs/areas/guard/adr/007-derived-rows-rechecked-at-use.md` |
| `home/common/claude-code/README.md` | Guard policy | evidence | `docs/archive/guard-row-check-cost-2026-10-13.md` |
| `home/common/claude-code/README.md` | Guard policy | how-to | `docs/guides/start-a-new-session-after-a-switch.md` |
| `home/common/claude-code/README.md` | Guard/core decision | decision | `docs/areas/guard/adr/008-merge-arms-keep-the-required-check-floor.md` |
| `python/README.md` | guard-policy | contract | `python/agent_tools/guard_policy.py` |
| `python/README.md` | guard-policy | decision | `docs/areas/guard/adr/006-two-policy-files-one-trust-rule-each.md`, `docs/areas/guard/adr/007-derived-rows-rechecked-at-use.md` |
| `python/README.md` | `cache-proxy` | contract | `python/agent_tools/cache_proxy.py`, `python/agent_tools/cache_keepalive.py`, `python/agent_tools/subagent_prefix.py`, `python/agent_tools/model_pricing.py`, `python/agent_tools/keepalive_pings.py` |
| `python/README.md` | `cache-proxy` | decision | `docs/areas/hosts/adr/001-cache-proxy-is-a-transparent-loopback.md`, `docs/areas/hosts/adr/002-keepalive-replays-idle-subagents.md`, `docs/areas/hosts/adr/003-subagent-prefix-reorder.md` |
| `home/common/claude-code/README.md` | Cache proxy | decision | `docs/areas/hosts/adr/004-claude-routes-through-the-proxy-by-default.md` |
| `home/common/claude-code/README.md` | Accounts | decision | `docs/areas/hosts/adr/005-account-profiles-link-shared-config.md` |
| `home/common/claude-code/README.md` | Plugins | decision | `docs/areas/hosts/adr/006-codex-plugin-is-a-pinned-input-plus-patch.md` |
| `python/README.md` | Package and launchers | overview | `python/README.md` |
| `python/README.md` | Package and launchers | decision | `docs/areas/system/adr/002-one-agent-tools-package.md` |
| `python/README.md` | artifact-budget | contract | `python/agent_tools/artifact_budget.py` |
| `python/README.md` | issue-branch | contract | `python/agent_tools/issue_branch.py` |
| `python/README.md` | `lane-triage` | contract | `python/agent_tools/lane_triage.py` |
| `python/README.md` | `lane-triage` | decision | `docs/areas/delivery/adr/005-the-light-lane-runs-in-shadow.md` |
| `python/README.md` | `agent-workflow-tests` runner | contract | `python/agent_tools/suite_runner.py` |
| `python/README.md` | `agent-workflow-tests` runner | decision | `docs/areas/delivery/adr/006-suite-members-run-in-parallel.md` |
| `python/README.md` | `agent-workflow-tests` runner | evidence | `docs/archive/suite-runner-job-count.md` |
| `python/README.md` | agent-run-profile | contract | `python/agent_tools/run_profile.py` |
| `home/common/agent-skills/README.md` | Global guidance and skill sources | decision | `docs/areas/delivery/adr/001-codex-is-a-reviewer-only.md` |
| `home/common/agent-skills/README.md` | Claude-only skills | decision | `docs/areas/delivery/adr/002-delivery-skills-are-claude-only.md` |
| `home/common/agent-skills/README.md` | Vendored skills | decision | `docs/areas/delivery/adr/003-vendored-skills-refresh-by-hand.md` |
| `home/common/agent-skills/README.md` | Code map | decision | `docs/areas/delivery/adr/004-code-maps-are-leads.md` |
| `home/common/agent-skills/README.md` | Host admission | contract | `python/agent_tools/host_admission.py` |
