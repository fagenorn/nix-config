# Acceptance record — issue #351

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [evidence] Guard refusals of push, merge and branch deletion drop to zero — measured: `grep -c "lifecycle guard: unsafe \(push\|merge\|branch deletion\)"` over the subagent transcripts of the next orchestrated run that ships ≥ 3 issues on nodocom; threshold 0, baseline 15 refusals across 9 ship phases. | evidence | `grep -c "lifecycle guard: unsafe \(push\|merge\|branch deletion\)"` over the run's subagent transcripts; threshold: 0 (baseline 15). | not measured — post-merge | — | the next orchestrated run that ships at least 3 issues on nodocom, with the merged skill text installed on the orchestrating host | unverified |
