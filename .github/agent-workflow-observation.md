# Agent workflow observation ledger

Schema: `agent-workflow-observation/v1`

This ledger records three qualifying advisory observations from the CI job. A
qualifying observation contains the exact `AGENT_WORKFLOW_OBSERVATION_V1=` marker,
parses every `schema`, `trigger`, `raw.checkout`, `raw.install_nix`,
`raw.provision_just`, `raw.suite`, and `elapsed_seconds` field, has no `unknown`
raw value, and has successful raw `checkout`, `install_nix`, `provision_just`, and
`suite` outcomes. The marker is the source of truth. A malformed or missing marker,
a setup failure, or a cancelled/timed-out job or run is non-qualifying. GitHub job
metadata is fallback evidence only for cancellation, timeout, or missing-summary
status and duration.

## Qualifying observations

1.
2.
3.

## Failed attempts

-
