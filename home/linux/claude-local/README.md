# claude-local

## The wrapper

The wrapper pre-flights `/health` (a dead server is a one-line error, not a wall of API failures) and reads the model id from `/v1/models` rather than hardcoding it.

## Two request shapes

**Two request shapes must both work, and the second is the one that bites.** Beyond the agent loop, `defaultMode = "auto"` makes Claude Code call a *safety classifier* before each Bash command, as a separate request with its own shape. A backend that serves the agent loop perfectly can still fail the classifier, and the failure surfaces as `<model> is temporarily unavailable` with every Bash call denied — which reads like a transient outage rather than a protocol mismatch. Diagnose this class of problem with a logging proxy between the CLI and the server; the error text alone will mislead you. Two concrete mismatches have appeared, and both are *deliberate* NInfer semantics rather than oversights:

- `cache_control` on a non-final content block (the classifier sends this; Anthropic allows up to four breakpoints anywhere) was rejected until upstream `9e163eee`, so **that revision is the minimum** — it also brought real `cache_read_input_tokens` accounting.
- The second, `thinking.display:"omitted"`, is handled by `anthropic-shim.py`; its docstring explains why.

## Fan-out

**Fan-out is the real mismatch, not prompt size.** `--max-concurrency 2`, and every subagent pays a cold full prefill, so `orchestrate-issues`/`sdd` fan-out serializes into a queue. Admission is graceful (five concurrent requests queued to 37s with no rejection), but `--pending-timeout-ms` defaults to 30s, so deep fan-out can start failing admission. Single-session work is what this is for. The `[claude-code:unrecognized_model]` line on stderr is cosmetic: the CLI has no catalog entry for `qwen3.8-27b`, and `CLAUDE_CODE_MAX_CONTEXT_TOKENS` is what actually fixes the window it assumes.
