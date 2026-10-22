# Ship delivery request compiler

Implement the accepted [design](../specs/2026-10-22-issue-411-ship-delivery-design.md).

## Global constraints

Reuse canonical builders/validators; no reducer, custody or external-effect change.
All Python helper code lives in the package with a thin CLI. Existing delivery
scope/fence/hold/sync/finish guarantees remain. No instruction-budget increase or
English phrase-pinning tests. Signed commits carry Codex attribution.

## Test seams

Public module to real builder/validator/ledger; installed isolated launcher.

## Delivery estimate and boundaries

One cohesive full-risk task: compiler, executable wiring, actual shipping caller
and real-engine tests must land together. Controller supplies independent review.

## Task index

Task 1 — Compile shipping recipes and replace manual assembly — `python/agent_tools/ship_delivery*.py`, `lib/agent-tools.nix`, `justfile`, `home/common/agent-skills/tests/test_ship_delivery.py`, `tests/test_agent_tools_launchers.py`, `python/README.md`, `home/common/agent-skills/skills/ship-issue/*.md`, `home/common/agent-skills/README.md` — full — [task-1.md](2026-10-22-issue-411-ship-delivery.tasks/task-1.md)
