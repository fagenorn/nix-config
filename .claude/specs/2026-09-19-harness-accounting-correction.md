# Correct Codex telemetry counting

Approved scope: the September 19 retrospective follow-through, issue #97. Keep the existing structured telemetry contract and human Claude tables. Correct replayed legacy usage, consume modern response usage, and make measurement limits visible. This is comparative telemetry, never billing.

## Behavior

Prefer valid `token_usage_record` response usage when a rollout has modern records. Deduplicate on response identity; repeated records and copied rollouts cannot double count a response. Never add modern usage to legacy snapshots from the same rollout. Record the selected source and excluded/ambiguous observations so this preference cannot masquerade as full historical coverage.

For legacy-only rollouts, count `last_token_usage` only when its cumulative snapshot advances or resets; replaying an unchanged cumulative snapshot does not create a turn. Equal last usage with a different cumulative snapshot represents distinct work. Recognize counter resets without adding historical cumulative totals. If cumulative evidence is absent, retain usable last usage with an explicit ambiguity count. Malformed/missing measurements remain observable, not claimed complete zero usage. Cache and reasoning are subsets of input/output.

Expose additive per-run Codex measurement metadata and a truthful JSON window declaration. Preserve `--days` file-mtime selection and whole-file accounting; a selected session spanning that boundary includes all its records. Do not label this as event-time monthly usage. Event-time filtering and fleet role attribution remain separate work. Keep schema version 1 because existing fields retain their shapes and the record consumer permits additive fields; verify that consumer.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|---|---|---|---|
| D1 | Modern response usage wins per rollout; legacy fallback is explicit | Audit found modern and cumulative counters disagree in coverage | Sum both formats or claim their totals are equivalent |
| D2 | Keep file-mtime selection and explicitly describe whole-file usage | Existing CLI documents this stable behavior | Silently change --days to event-time filtering |
| D3 | Add measurement metadata without changing existing token fields | agent-gate-bundle validates required record fields; canonical digest covers additions | A breaking format revision for compatible metadata |
| D4 | Deduplicate modern response identity across selected rollouts | Copied/replayed session files must not create new model work | Deduplicate only adjacent lines |

## Verification

Synthetic transcript fixtures cover duplicate legacy snapshots, equal legitimate calls, counter resets, modern-only and mixed formats, missing/invalid records, repeated response IDs in multiple files, root/child metadata and selected files spanning the mtime cutoff. Existing Claude golden text and evidence-gate tests stay green. Read a bounded retained real rollout for validation without committing its contents.
