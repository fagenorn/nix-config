# ADR-delivery-002 — The delivery programs and the Codex bridge are Claude-only skills

- **Status:** accepted
- **Decided in:** #637

## Context

Three skills do not make sense outside Claude Code. `codex-collaboration` drives Codex as a reviewer. `deliver-standard` and `deliver-batch` each start a Workflow-tool program (`deliver-standard.js`, `deliver-batch.js`), and that tool exists only in Claude Code. `deliver-batch` (#637) replaced `orchestrate-issues`.

## Decision

`codex-collaboration`, `deliver-standard` and `deliver-batch` are linked only into `~/.claude/skills/`, from `home/common/claude-code/skills/`, never into the shared skill source that other agents read.

## Consequences

- Another agent cannot start a delivery or a batch; Codex stays a reviewer (ADR-delivery-001).
- The two programs sit beside each other in the `deliver-standard` directory, and their control flow is tested under `node` against stub agents by `test_deliver_standard_program.py` and `test_deliver_batch_program.py`.
