# Agent workflow observation ledger

Schema: `agent-workflow-observation/v1`

The original cohort is fixed. A complete `AGENT_WORKFLOW_OBSERVATION_V1=` JSON
object is a valid raw observation when it has schema
`agent-workflow-observation/v1`, trigger `workflow_dispatch`, four raw-string
outcomes, and non-negative integer elapsed seconds, and its run and job completed
on Ubuntu without cancellation or timeout. The marker is the source of truth.
`suite: failure` is valid but non-passing. Unknown, missing, or malformed records,
cancellation, timeout, and setup failures are classified separately. Metadata
fallback never supplies raw outcomes or a passing result.

## Original cohort observations

Pinned commit: `d1094c968ea16818de8073889d25ea9f99bd8deb`.

1. [Run 35513790832](https://github.com/fagenorn/nix-config/actions/runs/35513790832)
   — `d1094c968ea16818de8073889d25ea9f99bd8deb`; completed `workflow_dispatch` on
   `ubuntu-24.04`; job conclusion: `success`;
   raw outcomes: `checkout: success`, `install_nix: success`,
   `provision_just: success`, `suite: failure`; job-work elapsed: 111 seconds.
2. [Run 35514069941](https://github.com/fagenorn/nix-config/actions/runs/35514069941)
   — `d1094c968ea16818de8073889d25ea9f99bd8deb`; completed `workflow_dispatch` on
   `ubuntu-24.04`; job conclusion: `success`;
   raw outcomes: `checkout: success`, `install_nix: success`,
   `provision_just: success`, `suite: failure`; job-work elapsed: 122 seconds.
3. [Run 35514254859](https://github.com/fagenorn/nix-config/actions/runs/35514254859)
   — `d1094c968ea16818de8073889d25ea9f99bd8deb`; completed `workflow_dispatch` on
   `ubuntu-24.04`; job conclusion: `success`;
   raw outcomes: `checkout: success`, `install_nix: success`,
   `provision_just: success`, `suite: failure`; job-work elapsed: 121 seconds.

## Non-passing suite observations

- valid observations: 3
- passing suite outcomes: 0
- non-passing suite outcomes: 3

Decision: keep advisory — original three-run Ubuntu cohort evaluated. Follow-up
[#160](https://github.com/fagenorn/nix-config/issues/160) must be resolved before
any future promotion decision.

## Incomplete or fallback records

- incomplete/fallback records: 0
