# Guard row check cost, 2026-10-13

Measured on 2026-10-13 on host `mbp`, 10 consecutive runs of the built row check for `elevenyellow/nodocom` took a median of 3.61 s and a maximum of 4.56 s (the first run), and none of the 10 fetched.

The row check is the one the lifecycle guard runs on every repository-bound verb in a repository that has a derived row; the decision to pay that cost is [ADR-guard-007](../areas/guard/adr/007-derived-rows-rechecked-at-use.md).
