# Task 1: Correct Codex record selection and coverage

**Files:** Modify `scripts/agent-costs.py`, `tests/test_agent_costs.py`; extend `tests/test_agent_gate_bundle.py` only if needed for consumer compatibility.

**Interfaces:** Preserve the existing scanner/group/projection entry points and fields. Add a documented per-run `measurement` object for Codex (Claude may use null), including selected source counts, duplicate observations skipped, missing/invalid usage observations and ambiguous legacy observations. Add JSON window keys declaring file-mtime selection and whole-selected-file usage. Keep schema version 1. Internal helpers and transient response identities may be added, but must not leak raw IDs or transcript content into public records.

**Invariants:** Follow specification D1–D4. Modern payload has `response_id` and `usage` with input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens, reasoning_output_tokens, total_tokens. A valid nonempty response ID is required for modern identity. Counters must be nonnegative integers (not booleans), subsets must fit their parents; optional counters may default to zero only when that format omits them. Duplicate modern identities with conflicting usage must be marked ambiguous/invalid, never summed. Deduplicate modern responses across selected files, not just within a file. Scope identities by thread when necessary to avoid unrelated collisions. Existing legacy metadata uses thread_source; modern uses source `cli` or a source.subagent object: report roots and children correctly. Source/coverage counters must be deterministic. Missing-only sessions must not claim measured zero token usage.

- [ ] Add meaningful failing fixtures. This minimum regression must fail at baseline (adapt only the existing fixture helper name/signature if necessary):

```python
def test_replayed_legacy_snapshot_is_not_a_new_turn(self):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "rollout.jsonl"
        event = codex_usage(1000, cached=600, out=50)
        path.write_text("\n".join(json.dumps(x) for x in [codex_meta("s1"), event, event]) + "\n")
        result = costs.scan_codex_file(path)
        self.assertEqual(result["input_total"], 1000)
        self.assertEqual(result["turns"], 1)
```

- [ ] Add modern, mixed-format, duplicate-across-files, invalid/missing, reset and equal-legitimate-call fixtures. Fix unrealistic cumulative fixture totals so distinct work advances the cumulative signature; do not weaken existing subset/peak assertions. Add a mtime-boundary fixture proving whole-file selection remains explicit, not event-time filtering.
- [ ] Implement source selection and deduplication. Legacy uses changed cumulative snapshots as completion evidence and sums last usage, handling reset as a new epoch. Missing cumulative evidence can use last usage only with ambiguity marked. Do not use final cumulative totals as a substitute for observed completions. Modern wins for an entire rollout, and excluded legacy observations are visible in measurement. Deduplication across files must preserve accurate selected modern usage and avoid counting a root’s response again in a copied child rollout.
- [ ] Verify `python3 -m unittest -q tests/test_agent_costs.py tests/test_agent_gate_bundle.py`; all tests including Claude text golden pass. Inspect one retained transcript only if needed; never print or commit private content. Explain any limitation in the report.
- [ ] Self-review the bounded diff and commit only task-owned code/tests with a signed commit and `Co-authored-by: Codex <noreply@openai.com>` trailer. Parent owns plan/spec commits and delivery.
