# README section map

Where each section of the three READMEs that issue 694 dissolved went: contract text to a module docstring, decisions to ADRs, measurements to this archive, procedures to docs/guides/. A point-in-time record of base commit `58908955a256f53b09ff27702d3e9847ba030708`: paths are as of the commit that last changed this file, and later moves do not rewrite it. Kinds: `contract`, `decision`, `evidence`, `how-to`, `overview`, `superseded`.

| Source | Section | Kind | Destination |
|---|---|---|---|
| `python/README.md` | `verified-tree` | contract | `python/agent_tools/verified_tree.py` |
| `python/README.md` | `verified-tree` | decision | `docs/areas/verification/adr/001-a-recorded-pass-covers-exactly-the-plan.md` |
| `python/README.md` | verify-pending | contract | `python/agent_tools/verify_block.py`, `python/agent_tools/verify_pending.py`, `python/agent_tools/verify_run.py`, `python/agent_tools/verify_issues.py`, `python/agent_tools/verify_exec.py`, `python/agent_tools/verify_facts.py`, `python/agent_tools/verify_owner.py`, `python/agent_tools/verify_checks.py`, `python/agent_tools/keepalive_pings.py`, `home/common/verify-pending/default.nix` |
| `python/README.md` | verify-pending | decision | `docs/areas/verification/adr/002-verify-run-forms-are-an-allowlist.md`, `docs/areas/verification/adr/003-only-verification-commands-run-unattended.md`, `docs/areas/verification/adr/004-only-trusted-authors-count.md`, `docs/areas/verification/adr/005-a-check-is-its-block-version.md`, `docs/areas/verification/adr/006-contracts-read-at-the-integration-commit.md`, `docs/areas/verification/adr/007-a-switch-kicks-a-pass.md`, `docs/areas/verification/adr/008-macs-verify-only-while-logged-in.md`, `docs/areas/verification/adr/009-owner-prompts-settle-on-the-owners-answer.md` |
