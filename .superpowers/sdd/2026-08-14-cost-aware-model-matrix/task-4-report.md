# Task 4 report

## Status

Implementation complete. The focused and full unit contracts, matrix validator,
representative trace, and whitespace check pass. The required Darwin build was
started after sandbox escalation but was terminated before completion at the task
owner's explicit time bound; no build verdict is available.

## Changes

- Registered explicit Opus/high ship ownership and shipping review dispatches.
- Restricted shipping fix re-review to Sonnet/medium `reviewer-lite` after named
  prior findings and over a bounded fix diff.
- Registered Sonnet/medium Codex bridge transport and Opus/high native fallback,
  while explicitly preserving the external Codex runtime model.
- Replaced placeholder scenario rows with registered dispatch IDs and added a
  deterministic four-family `representative` trace.
- Added `just agent-model-matrix` to validate the contract and print the demo trace.
- Updated the matrix CLI's event schema to emit `workflow`, `dispatch`, `role`,
  `model`, and `effort`; this script change is necessary for the Task 4 interface
  even though the brief's file list omitted the script.

## Verification

- RED: `python3 -m unittest -v home/common/agent-skills/tests/test_agent_model_matrix.py`
  failed on seven missing shipping/Codex dispatches and the absent
  `representative` scenario.
- GREEN: the same focused command passed 17/17 tests.
- `python3 -m unittest discover -s home/common/agent-skills/tests -v` passed
  52/52 tests.
- `python3 home/common/agent-skills/scripts/agent-model-matrix.py validate` passed.
- `python3 home/common/agent-skills/scripts/agent-model-matrix.py trace representative`
  passed and emitted 11 JSONL events covering orchestration, from-issue, sdd, and
  shipping with explicit model and effort.
- `git diff --check` passed before commit.
- `nix build .#darwinConfigurations.mbp.system` first failed because the sandbox
  could not open `/Users/anis/.cache/nix/fetcher-cache-v4.sqlite`. The escalated
  retry was accepted and started, then was explicitly terminated before completion
  at the task owner's instruction. Ship phase must rerun the build.
- Removed generated `__pycache__` directories.

## Concerns

- The Darwin build remains unverified because the escalated retry was interrupted,
  not because it produced a build failure.
