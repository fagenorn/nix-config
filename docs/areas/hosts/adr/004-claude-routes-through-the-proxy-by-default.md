# ADR-hosts-004 — `claude` routes through the cache proxy by default

- **Status:** accepted
- **Decided in:** #438; #450

## Context

#438 shipped routing as opt-in because the measured time-to-first-token gap of the routed path was not shown to be small. #450 re-measured it (`docs/spikes/cache-proxy-ttft-gap.md` § Issue 450). The proxy hop itself added no measurable time, and one real effect was found: Claude Code sends its `<total_tokens>` budget line only to api.anthropic.com, so a routed turn opened with a thinking block far more often until `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown` restored the line.

## Decision

`claude` reaches the API through the proxy whenever the proxy is healthy, unless launched with `CLAUDE_CACHE_PROXY=0`. The paired median difference, routed with the probe minus direct, was 9.7 ms, with the 95% CI's upper end at 149.2 ms. That upper end is over the +100 ms bound the measurement was planned against, so the planned rule was not met. The owner chose the looser rule of an estimate within +100 ms after the measurement, because 100 pairs cannot narrow the CI enough to pass the planned rule.

## Consequences

- A routed session has no Remote Control, which Claude Code turns off behind a non-first-party base URL; `CLAUDE_CACHE_PROXY=0 claude` keeps it for that launch.
- A dead proxy costs a launch at most a half-second probe, after which the launch goes direct. A session keeps the route it started with.
- The planned rule was not met: the default rests on the looser rule the owner chose after the measurement.
