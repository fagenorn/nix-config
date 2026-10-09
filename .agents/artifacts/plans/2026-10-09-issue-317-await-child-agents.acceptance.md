# Acceptance record — issue #317

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AC1 | [code] The owner dispatch contract (the leaf-agent clauses, from-issue Phase 7 / ship-handoff) states that a background child agent is awaited within the turn, and the carrier test pins that clause — measured: test_dispatch_contracts.py | code | test_dispatch_contracts.py | in final verification | — | — | | met |
| AC2 | [evidence] In an orchestrated run, no owner launch hands back a waiting-for-child line — measured: the hand-back texts of one orchestrate-issues run over two or more issues that reach Phase 7, none matching "waiting for" | evidence | hand-back texts of the run's owner launches; threshold: zero matches of `waiting for` | not measured — post-merge | — | post-merge orchestrated run, ≥2 issues reaching Phase 7 | | unverified |
