# Qwen effort implementation plan

> **For agentic workers:** execute with the `sdd` skill, one implementer per task
> reviewed between tasks. The caller delegated this single task to a fresh agent.

**Goal:** Make Claude effort reach Qwen and bound default reasoning (#410).

**Architecture:** Patch oMLX's request schema and Anthropic route merge helper.
A generated host command checks patches and merges only owned settings. A portable
flake check runs against the existing pinned upstream source.

**Tech stack:** Nix, Python standard library, Pydantic, Jinja2, GNU patch.

## Global Constraints

Preserve unrelated model/server settings and secrets. No live package/settings
mutation during implementation. Preserve signing and include agent attribution.
No new agent-workflow scripts; the host support command owns only oMLX config.

## Test seams

Pinned upstream adapter schema/route/budget resolver and real Qwen template.
Temporary-directory configuration application and failure behavior.
Caller-owned Darwin build and live streamed request smoke.

## Delivery estimate and boundaries

Estimate: 9 implementation/test/configuration files plus these artifacts.
One adapter/configuration change; no independent partial delivery satisfies #410.
The upstream source remains a flake input, with no vendored source copy.

## Task index

Task 1 — Honor and bound Qwen effort — patches/omlx/anthropic-effort.patch, hosts/darwin/eleven-m5/omlx.nix, hosts/darwin/eleven-m5/omlx-configure.py, tests/test_omlx_configure.py, tests/omlx_adapter_probe.py, lib/omlx-check.nix, flake.nix, .github/workflows/ci.yaml — full — [task-1.md](2026-10-22-qwen-effort.tasks/task-1.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | Adapter probe parses all supported efforts, rejects unsupported values, renders Qwen low/medium/xhigh instructions |
| AC2 | code | Task 1 | Adapter probe asserts thinking and forced/explicit override precedence |
| AC3 | code | Task 1 | Portable flake check tests twice-applied configuration and patch failures; caller runs `just build eleven-m5` |
| AC4 | evidence | Task 1 | Caller records AC4 after low/medium Claude-shaped local streamed requests: at least one valid text/tool response each, zero adapter errors, configured default budget4096 |

## Decisions

Per D1–D4 in [the spec](../specs/2026-10-22-qwen-effort-design.md).
