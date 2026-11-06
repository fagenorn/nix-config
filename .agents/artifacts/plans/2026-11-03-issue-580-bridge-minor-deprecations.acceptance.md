# Acceptance record — issue 580

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | C11.a on mbp and eleven-m5: platform.deprecations is not empty after the owner switches each host to a generation containing this change (owner decision 4) | evidence | `resolve-project platform-status` on each host; green when exit 0, `platform.platform_version` is `1.1.0` and `platform.deprecations` holds at least 1 entry | pending owner switch on mbp and eleven-m5 | — | after `just switch` by the owner, per host | unverified |
