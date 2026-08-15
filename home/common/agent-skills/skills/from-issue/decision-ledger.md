# Decision ledger format (C1)

One issue-level ledger table lives in the SPEC, under a section named exactly `## Decision ledger`. The plan and ADRs cite rows by ID ("per D3") and never restate or duplicate them.

```markdown
| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | <what was decided, one line> | <doc/standard/user statement it rests on> | <the alternative and why not, one line> |
```

- Log ONLY non-obvious decisions: scope, interface, behavioral, test-seam, irreversible, or user-preference calls.
- Do NOT log routine task splits, commit boundaries, obvious verification commands, or mechanical pattern-following.
- Consolidation is permitted and encouraged: merge related decisions into one row. Later phases (plan, Phase-5 review) append new rows; a row that reverses an earlier one names it ("reverses D2") in its Choice.

When a subagent prompt needs the format (see `AUTO.md`), paste this file's table block and the three rules verbatim.
