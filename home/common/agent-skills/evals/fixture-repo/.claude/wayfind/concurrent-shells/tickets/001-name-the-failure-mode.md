---
type: wayfinder:task
state: open
assignee:
blocked_by: []
---

## Question

What does a lost update actually look like today? Drive two `python3 -m tinytask`
mutations at one task file so the interleaving is observable, and record the
concrete failure: which write survives, whether anything on disk shows that a loss
happened at all, and whether an ordinary user would notice. Every later ticket
prices its options against these facts — record them, fix nothing.
