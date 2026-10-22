# Task 1 — Compile shipping recipes and replace manual assembly

Implement spec D1–D4. Read `workflow_delivery_build.py`, `DELIVERY-LOOP.md`,
`POST-SELECTION-SYNC.md`, `REMAINDER.md`, package helper standards and Python
standards. Add an importable stateless compiler and thin `ship-delivery` CLI.
Validate tool-produced context/prior payloads, strict recipes, current custody,
canonical builder outputs and final report. Support ordered sync selections,
local observation references across custody takeovers, holds, denied/partial
effects and failed summaries; predecessor authority never enters new output.
Replace manual ship JSON mechanics with the actual complete compiler interface,
document every recipe and reference, and add the isolated Nix command-table row.

Test the public module against real workflow-state/artifact-budget and temporary
ledgers: complete delivery, sync, hold, denial, malformed/stale/crossed input;
feed generated payloads to real checkpoint/finish boundaries. Extend installed
launcher coverage. Run focused tests, `just agent-workflow-tests`, instruction
budget and `just build eleven-m5`; report any unavailable check honestly.

Keep long logs outside the repository and pass paths rather than inlining them.
Commit with inherited signing and `Co-Authored-By: Codex <noreply@openai.com>`.
