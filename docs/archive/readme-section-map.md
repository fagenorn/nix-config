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
