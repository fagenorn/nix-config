# Acceptance mapping for issue #97

The original machine-readable reporter shipped through #120. The September 19 follow-through corrects Codex observation counting and adds explicit measurement limits. The current schema exposes runs under `strata.<host>.runs[]`; unsupported measurements are null rather than fabricated zeros.

| Original requirement / printed aggregate | JSON location relative to a run |
|---|---|
| Per-group token totals | `tokens.{input_total,fresh,cache_create,cache_read,output,reasoning}` |
| Issue outcome | `outcome` |
| Model and effort mix | `models`, `efforts` |
| Agent launches by type and terminal statuses | `agents_by_type`, `agent_statuses`, `agents_killed` |
| Phase and skill-attribution turns | `phase_turns`, `attr_turns` |
| Turns, sessions and subagents | `turns`, `sessions`, `subagents` |
| Skill loads and repeated loads | `skill_loads`, `repeats` |
| Peak context, stop reasons and user nudges | `peak_ctx`, `stop_reasons`, `interventions` |
| Dispatch/result size distributions | `agent_prompt_bytes`, `agent_result_bytes` |
| Comparative list-price estimates | `cost_usd`, `cost_by_family`; Codex cost remains null |

The old issue's `.effort_mix` demo was illustrative, not the shipped spelling. The corresponding query is `just agent-costs --format json | jq '.strata.claude.runs[] | {run_id, efforts}'`. Stratum and fleet totals are derived from these same runs. Existing Claude text/JSON parity and byte-identity tests guard the original promise.

`--days` continues to select files by modification time and count all observations in each selected file. JSON now names this selection and usage scope explicitly. This is not event-time monthly reporting; a session crossing the cutoff is not partially clipped. Missing records, mixed-format selection and excluded observations limit completeness. Request token volume and billing remain different measures.

## Bounded audit-sample replay

Re-ran the actual baseline reporter at `ea03ccdd` and the corrected scanner on the two retained sessions cited in the retrospective, without retaining their contents. Values below are `input_total + output`, with cache and reasoning not added twice.

| Sample | Baseline reporter | Corrected reporter | Selected completions | Source |
|---|---:|---:|---:|---|
| Nodo, August 26 | 185,922,225 | 185,069,427 | 1,520 | legacy |
| Arcwave, September 15 | 275,759,020 | 261,290,381 | 2,326 | modern |

The audit diagnostic had summed each legacy `last_token_usage.total_tokens`; the reporter itself summed the separate input and output fields. Those source fields are not always internally equal, so its original diagnostic baseline differs slightly from this reporter-to-reporter comparison. The corrected totals agree with the audit’s deduplicated legacy Nodo total and unique modern Arcwave total. This is accounting correction and record selection, not a claim of tokens saved during execution. Arcwave excludes legacy observations when selecting modern usage; equality with the legacy cumulative counter is neither required nor claimed.
