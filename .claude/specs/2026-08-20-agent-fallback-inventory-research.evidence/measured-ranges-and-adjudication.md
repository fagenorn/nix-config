# Evidence member — measured ranges and the per-hit adjudication

This file is an **evidence member** of
`.claude/specs/2026-08-20-agent-fallback-inventory-research.md`, which is the root of
this document package and the file issue #61's resolution comment links. It carries
bulk evidence only: every `sed -n … | wc -c` invocation behind the root's byte table,
and the per-hit map of all 209 distinct sweep hits with each hit's disposition. It
states no synthesis and reaches no conclusion of its own — every conclusion these
records feed lives in the root, so a reader who found this file alone has found a set
of records, not a finding, and must read the root for what they mean. Its provenance
is the root's exactly: a **re-derivation authored 2026-09-02 under issue #115**, not
the never-committed 2026-08-20 original, whose content is unrecoverable. Nothing here
is a recovered byte, and no sentence in this file may be cited as evidence of what
the original said. The measurement unit and method these ranges implement, the two
sweep passes and the row rule the map adjudicates against, the disposition table it
reconciles with, and the bounds on what any of it asserts are stated once, in the
root; read them there. Directional words in the records below — "above", "below" —
were written while these records sat inside the root and resolve against it.

## The measured ranges

Every number in the byte table is the sum of these invocations, run from the
repository root. Nothing else was measured.

**Project binding — 4,242 bytes**

```
sed -n '13p;15p;17p' home/common/agent-skills/skills/ship-issue/SKILL.md              ->  918
sed -n '12p'         home/common/agent-skills/skills/doc-grounded-questions/SKILL.md  ->  383
sed -n '12p'         home/common/agent-skills/skills/to-issues/SKILL.md               ->  466
sed -n '11,13p'      home/common/agent-skills/skills/writing-plans/SKILL.md           ->  227
sed -n '16p'         home/common/agent-skills/skills/research/SKILL.md                ->  592
sed -n '49p'         home/common/agent-skills/skills/design/SKILL.md                  ->  259
sed -n '24p'         home/common/agent-skills/skills/ship-release/SKILL.md            ->  445
sed -n '5,8p'        home/common/agent-skills/skills/from-issue/bindings.md           ->  714
sed -n '16,18p'      home/common/agent-skills/skills/ship-issue/REVIEW.md              ->  238
```

**Command — 1,636 bytes**

```
sed -n '222p'          home/common/agent-skills/skills/ship-issue/SKILL.md                 -> 1005
sed -n '23,25p;59,63p' home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md   ->  631
```

**Tracker — 3,173 bytes**

```
sed -n '18p;87,89p'  home/common/agent-skills/skills/to-issues/SKILL.md      ->  919
sed -n '28p;30p;75p' home/common/agent-skills/skills/ship-release/SKILL.md   -> 1145
sed -n '12p;14p'     home/common/agent-skills/skills/from-issue/bindings.md  ->  525
sed -n '207p'        home/common/agent-skills/skills/ship-issue/SKILL.md     ->  345
sed -n '465p'        home/common/agent-skills/skills/from-issue/SKILL.md     ->  159
sed -n '49p'         home/common/agent-skills/skills/wayfind/DISCIPLINE.md   ->   80
```

**Doc discovery — 6,955 bytes**

```
sed -n '18p;20p;24p;26p'      home/common/agent-skills/skills/doc-grounded-questions/SKILL.md      -> 1343
sed -n '26,29p;36,38p;41,45p' home/common/agent-skills/skills/doc-grounded-questions/REFERENCE.md  ->  760
sed -n '38,41p'               home/common/agent-skills/skills/grill-with-docs/SKILL.md             ->  852
sed -n '29p;133p'             home/common/agent-skills/skills/grill-with-docs/CONTEXT-FORMAT.md    ->  663
sed -n '28p'                  home/common/agent-skills/skills/to-issues/SKILL.md                   ->  587
sed -n '71p'                  home/common/agent-skills/skills/ship-release/SKILL.md                ->  498
sed -n '65p'                  home/common/agent-skills/skills/ship-release/CHANGELOG.md            ->  243
sed -n '39p;59p'              home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md        ->  233
sed -n '23p'                  home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md   ->   72
sed -n '36,47p'               home/common/claude-code/skills/codex-collaboration/PLAN-REVIEW.md    ->  869
sed -n '28p;33p;38p'          home/common/agent-skills/skills/ship-issue/CONSOLIDATE.md            ->  835
```

**Agent capability — 8,322 bytes**

```
sed -n '37p'                    home/common/agent-skills/skills/worktrees/SKILL.md                     ->  720
sed -n '121p;237,241p;359p'     home/common/agent-skills/skills/ship-issue/SKILL.md                    ->  727
sed -n '28p;31,37p'             home/common/agent-skills/skills/ship-issue/REVIEW.md                   ->  551
sed -n '18,20p;31p'             home/common/agent-skills/skills/from-issue/standards-review.md         -> 1204
sed -n '180p'                   home/common/agent-skills/skills/from-issue/SKILL.md                    ->  298
sed -n '60,62p'                 home/common/agent-skills/skills/from-issue/ship-handoff.md             ->  167
sed -n '32p'                    home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md ->  248
sed -n '39p;59p'                home/common/agent-skills/skills/doc-grounded-questions/SKILL.md        ->  476
sed -n '38p'                    home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md          ->   94
sed -n '51p'                    home/common/agent-skills/skills/sdd/SKILL.md                           ->  263
sed -n '4p;115,116p'            home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md     ->  203
sed -n '111,112p'               home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md     ->  161
sed -n '29p;31p'                home/common/agent-skills/skills/sdd/final-review.md                    -> 1315
sed -n '18p'                    home/common/agent-skills/skills/sdd/fix-loop.md                        ->  157
sed -n '38,40p;65,68p;119,141p' home/common/claude-code/skills/codex-collaboration/SKILL.md            -> 1738
```


## The adjudication, hit by hit

All 209 distinct `file:line` hits of the two published passes, in file-then-line
order, each with its disposition: a row ID where it became part of a row,
otherwise the exclusion class, abbreviated `fail-closed`, `state-vocabulary`,
`cross-reference`, `off-subject`, `default-selection` and `budget-degrade` for
the six classes of the disposition table above, in that table's order. Paths are
relative to `home/common/`. Counting this list reproduces every total in that
table.

One attribution in it is deliberately coarse, for the reason
`## Method and evidence base` gives: `resolve-bindings:5`, `:6`, `:92` and `:94`
are docstring lines that announce behaviour implemented in branches carrying no
pass vocabulary, so each is attributed to **all seven** rows that reading the
file produced — A1-A5, C1 and C2 — rather than to the one row whose cited range
happens to contain it (`:92` and `:94` fall inside A5's `91-107`; `:5` and `:6`
fall inside no row's cited range at all). No other hit is attributed that way:
the only three that carry several row IDs — `from-issue/bindings.md:6`
(A9, B4, C9), `ship-issue/SKILL.md:13` (A6, B1) and `:15` (A8, C4) — each states
every site named on it, which is also why the byte table counts each of those
lines once, under project binding.

```
agent-skills/scripts/diff-scope.py:30 fail-closed
agent-skills/scripts/diff-scope.py:394 fail-closed
agent-skills/scripts/diff-scope.py:430 fail-closed
agent-skills/scripts/resolve-bindings:5 A1,A2,A3,A4,A5,C1,C2
agent-skills/scripts/resolve-bindings:6 A1,A2,A3,A4,A5,C1,C2
agent-skills/scripts/resolve-bindings:92 A1,A2,A3,A4,A5,C1,C2
agent-skills/scripts/resolve-bindings:94 A1,A2,A3,A4,A5,C1,C2
agent-skills/scripts/workflow-state.py:129 state-vocabulary
agent-skills/scripts/workflow-state.py:145 state-vocabulary
agent-skills/scripts/workflow-state.py:149 state-vocabulary
agent-skills/scripts/workflow-state.py:152 state-vocabulary
agent-skills/scripts/workflow-state.py:321 fail-closed
agent-skills/scripts/workflow-state.py:398 state-vocabulary
agent-skills/scripts/workflow-state.py:965 fail-closed
agent-skills/scripts/workflow-state.py:1252 state-vocabulary
agent-skills/scripts/workflow-state.py:1369 fail-closed
agent-skills/scripts/workflow-state.py:1517 state-vocabulary
agent-skills/scripts/workflow-state.py:1520 state-vocabulary
agent-skills/scripts/workflow-state.py:1521 fail-closed
agent-skills/scripts/workflow-state.py:1704 state-vocabulary
agent-skills/scripts/workflow-state.py:1800 state-vocabulary
agent-skills/scripts/workflow-state.py:1801 fail-closed
agent-skills/scripts/workflow-state.py:1838 state-vocabulary
agent-skills/scripts/workflow-state.py:1875 state-vocabulary
agent-skills/scripts/workflow-state.py:1878 state-vocabulary
agent-skills/scripts/workflow-state.py:1882 state-vocabulary
agent-skills/scripts/workflow-state.py:1888 state-vocabulary
agent-skills/scripts/workflow-state.py:2044 state-vocabulary
agent-skills/scripts/workflow-state.py:2058 state-vocabulary
agent-skills/scripts/workflow-state.py:2063 state-vocabulary
agent-skills/scripts/workflow-state.py:2068 state-vocabulary
agent-skills/scripts/workflow-state.py:2089 state-vocabulary
agent-skills/scripts/workflow-state.py:2104 state-vocabulary
agent-skills/scripts/workflow-state.py:2120 state-vocabulary
agent-skills/scripts/workflow-state.py:2141 state-vocabulary
agent-skills/scripts/workflow-state.py:2179 fail-closed
agent-skills/scripts/workflow-state.py:2231 state-vocabulary
agent-skills/scripts/workflow-state.py:2515 state-vocabulary
agent-skills/scripts/workflow-state.py:2518 fail-closed
agent-skills/scripts/workflow-state.py:2564 state-vocabulary
agent-skills/scripts/workflow-state.py:2579 state-vocabulary
agent-skills/scripts/workflow-state.py:2842 state-vocabulary
agent-skills/skills/design/SKILL.md:49 A6
agent-skills/skills/design/SKILL.md:129 cross-reference
agent-skills/skills/doc-grounded-questions/REFERENCE.md:3 cross-reference
agent-skills/skills/doc-grounded-questions/REFERENCE.md:27 D2
agent-skills/skills/doc-grounded-questions/REFERENCE.md:36 D3
agent-skills/skills/doc-grounded-questions/REFERENCE.md:37 D3
agent-skills/skills/doc-grounded-questions/SKILL.md:8 cross-reference
agent-skills/skills/doc-grounded-questions/SKILL.md:12 A6
agent-skills/skills/doc-grounded-questions/SKILL.md:14 cross-reference
agent-skills/skills/doc-grounded-questions/SKILL.md:18 D17
agent-skills/skills/doc-grounded-questions/SKILL.md:20 D1
agent-skills/skills/doc-grounded-questions/SKILL.md:22 cross-reference
agent-skills/skills/doc-grounded-questions/SKILL.md:26 D5
agent-skills/skills/doc-grounded-questions/SKILL.md:39 E7
agent-skills/skills/doc-grounded-questions/SKILL.md:59 E15
agent-skills/skills/from-issue/AUTO.md:11 state-vocabulary
agent-skills/skills/from-issue/AUTO.md:13 state-vocabulary
agent-skills/skills/from-issue/AUTO.md:17 state-vocabulary
agent-skills/skills/from-issue/AUTO.md:113 cross-reference
agent-skills/skills/from-issue/REVIEW-CONTRACT.md:17 fail-closed
agent-skills/skills/from-issue/REVIEW-CONTRACT.md:19 fail-closed
agent-skills/skills/from-issue/REVIEW-CONTRACT.md:36 fail-closed
agent-skills/skills/from-issue/REVIEW-CONTRACT.md:38 E9
agent-skills/skills/from-issue/REVIEW-CONTRACT.md:39 D9
agent-skills/skills/from-issue/REVIEW-CONTRACT.md:41 cross-reference
agent-skills/skills/from-issue/REVIEW-CONTRACT.md:59 D19
agent-skills/skills/from-issue/REVIEW-CONTRACT.md:88 off-subject
agent-skills/skills/from-issue/REVIEW-CONTRACT.md:108 off-subject
agent-skills/skills/from-issue/REVIEW-CONTRACT.md:115 off-subject
agent-skills/skills/from-issue/SKILL.md:62 state-vocabulary
agent-skills/skills/from-issue/SKILL.md:79 state-vocabulary
agent-skills/skills/from-issue/SKILL.md:98 state-vocabulary
agent-skills/skills/from-issue/SKILL.md:119 fail-closed
agent-skills/skills/from-issue/SKILL.md:155 cross-reference
agent-skills/skills/from-issue/SKILL.md:180 E4
agent-skills/skills/from-issue/SKILL.md:207 fail-closed
agent-skills/skills/from-issue/SKILL.md:271 state-vocabulary
agent-skills/skills/from-issue/SKILL.md:356 state-vocabulary
agent-skills/skills/from-issue/SKILL.md:439 cross-reference
agent-skills/skills/from-issue/SKILL.md:465 C12
agent-skills/skills/from-issue/bindings.md:6 A9,B4,C9
agent-skills/skills/from-issue/bindings.md:8 A9
agent-skills/skills/from-issue/bindings.md:10 cross-reference
agent-skills/skills/from-issue/ship-handoff.md:1 cross-reference
agent-skills/skills/from-issue/ship-handoff.md:60 E19
agent-skills/skills/from-issue/standards-review.md:19 E3
agent-skills/skills/from-issue/standards-review.md:20 E3
agent-skills/skills/from-issue/standards-review.md:31 E3
agent-skills/skills/grill-with-docs/ADR-FORMAT.md:5 cross-reference
agent-skills/skills/grill-with-docs/CONTEXT-FORMAT.md:29 D15
agent-skills/skills/grill-with-docs/CONTEXT-FORMAT.md:133 D12
agent-skills/skills/grill-with-docs/CONTEXT-FORMAT.md:147 cross-reference
agent-skills/skills/grill-with-docs/SKILL.md:40 D6
agent-skills/skills/grill-with-docs/SKILL.md:41 D6
agent-skills/skills/grill-with-docs/SKILL.md:47 cross-reference
agent-skills/skills/grill-with-docs/SKILL.md:156 cross-reference
agent-skills/skills/handoff/SKILL.md:51 fail-closed
agent-skills/skills/handoff/SKILL.md:86 fail-closed
agent-skills/skills/improve-codebase-architecture/LICENSE:23 off-subject
agent-skills/skills/improve-codebase-architecture/LICENSE:26 off-subject
agent-skills/skills/improve-codebase-architecture/SKILL.md:32 E6
agent-skills/skills/research/SKILL.md:16 A6
agent-skills/skills/sdd/SKILL.md:36 fail-closed
agent-skills/skills/sdd/SKILL.md:51 E10
agent-skills/skills/sdd/conformance-reviewer-prompt.md:23 D10
agent-skills/skills/sdd/conformance-reviewer-prompt.md:48 fail-closed
agent-skills/skills/sdd/conformance-reviewer-prompt.md:112 E20
agent-skills/skills/sdd/correctness-reviewer-prompt.md:4 E11
agent-skills/skills/sdd/correctness-reviewer-prompt.md:8 cross-reference
agent-skills/skills/sdd/correctness-reviewer-prompt.md:42 fail-closed
agent-skills/skills/sdd/correctness-reviewer-prompt.md:77 off-subject
agent-skills/skills/sdd/correctness-reviewer-prompt.md:116 E20
agent-skills/skills/sdd/final-review.md:29 E16
agent-skills/skills/sdd/final-review.md:31 E16
agent-skills/skills/sdd/fix-loop.md:18 E17
agent-skills/skills/sdd/fix-loop.md:20 off-subject
agent-skills/skills/sdd/fix-loop.md:21 off-subject
agent-skills/skills/sdd/re-review-prompt.md:55 fail-closed
agent-skills/skills/sdd/scripts/review-package:1081 fail-closed
agent-skills/skills/sdd/scripts/task-brief:25 fail-closed
agent-skills/skills/sdd/scripts/task-brief:26 fail-closed
agent-skills/skills/sdd/scripts/task-brief:40 fail-closed
agent-skills/skills/sdd/task-reviewer-prompt.md:66 fail-closed
agent-skills/skills/ship-issue/CONSOLIDATE.md:28 D18
agent-skills/skills/ship-issue/CONSOLIDATE.md:33 D13
agent-skills/skills/ship-issue/CONSOLIDATE.md:38 D14
agent-skills/skills/ship-issue/REVIEW.md:7 budget-degrade
agent-skills/skills/ship-issue/REVIEW.md:18 A11
agent-skills/skills/ship-issue/REVIEW.md:26 cross-reference
agent-skills/skills/ship-issue/REVIEW.md:28 E20
agent-skills/skills/ship-issue/REVIEW.md:31 E18
agent-skills/skills/ship-issue/REVIEW.md:42 budget-degrade
agent-skills/skills/ship-issue/SKILL.md:13 A6,B1
agent-skills/skills/ship-issue/SKILL.md:15 A8,C4
agent-skills/skills/ship-issue/SKILL.md:17 A10
agent-skills/skills/ship-issue/SKILL.md:80 fail-closed
agent-skills/skills/ship-issue/SKILL.md:82 fail-closed
agent-skills/skills/ship-issue/SKILL.md:121 E8
agent-skills/skills/ship-issue/SKILL.md:155 default-selection
agent-skills/skills/ship-issue/SKILL.md:207 C10
agent-skills/skills/ship-issue/SKILL.md:218 budget-degrade
agent-skills/skills/ship-issue/SKILL.md:220 budget-degrade
agent-skills/skills/ship-issue/SKILL.md:222 B2
agent-skills/skills/ship-issue/SKILL.md:225 budget-degrade
agent-skills/skills/ship-issue/SKILL.md:232 budget-degrade
agent-skills/skills/ship-issue/SKILL.md:237 E2
agent-skills/skills/ship-issue/SKILL.md:239 E2
agent-skills/skills/ship-issue/SKILL.md:240 E2
agent-skills/skills/ship-issue/SKILL.md:359 E5
agent-skills/skills/ship-release/CHANGELOG.md:65 D16
agent-skills/skills/ship-release/SKILL.md:24 A7
agent-skills/skills/ship-release/SKILL.md:71 D8
agent-skills/skills/ship-release/SKILL.md:75 C7
agent-skills/skills/to-issues/SKILL.md:12 A6
agent-skills/skills/to-issues/SKILL.md:14 cross-reference
agent-skills/skills/to-issues/SKILL.md:28 D7
agent-skills/skills/to-issues/SKILL.md:87 C8
agent-skills/skills/to-issues/SKILL.md:89 C8
agent-skills/skills/wayfind/DISCIPLINE.md:49 C11
agent-skills/skills/wayfind/SKILL.md:83 default-selection
agent-skills/skills/worktrees/SKILL.md:37 E1
agent-skills/skills/writing-plans/SKILL.md:11 A6
agent-skills/skills/writing-plans/SKILL.md:185 fail-closed
agent-skills/skills/writing-plans/SKILL.md:244 fail-closed
agent-skills/skills/writing-plans/SKILL.md:255 cross-reference
claude-code/skills/codex-collaboration/CERTIFICATION.md:5 cross-reference
claude-code/skills/codex-collaboration/CERTIFICATION.md:18 fail-closed
claude-code/skills/codex-collaboration/CERTIFICATION.md:43 fail-closed
claude-code/skills/codex-collaboration/CERTIFICATION.md:44 fail-closed
claude-code/skills/codex-collaboration/DIFF-REVIEW.md:9 fail-closed
claude-code/skills/codex-collaboration/DIFF-REVIEW.md:10 fail-closed
claude-code/skills/codex-collaboration/DIFF-REVIEW.md:16 cross-reference
claude-code/skills/codex-collaboration/DIFF-REVIEW.md:19 cross-reference
claude-code/skills/codex-collaboration/DIFF-REVIEW.md:20 cross-reference
claude-code/skills/codex-collaboration/DIFF-REVIEW.md:59 B3
claude-code/skills/codex-collaboration/DIFF-REVIEW.md:61 B3
claude-code/skills/codex-collaboration/DIFF-REVIEW.md:68 budget-degrade
claude-code/skills/codex-collaboration/DIFF-REVIEW.md:69 budget-degrade
claude-code/skills/codex-collaboration/DIFF-REVIEW.md:200 off-subject
claude-code/skills/codex-collaboration/DIFF-REVIEW.md:201 off-subject
claude-code/skills/codex-collaboration/PLAN-REVIEW.md:4 cross-reference
claude-code/skills/codex-collaboration/PLAN-REVIEW.md:12 fail-closed
claude-code/skills/codex-collaboration/PLAN-REVIEW.md:14 fail-closed
claude-code/skills/codex-collaboration/PLAN-REVIEW.md:37 D11
claude-code/skills/codex-collaboration/PLAN-REVIEW.md:38 D11
claude-code/skills/codex-collaboration/PLAN-REVIEW.md:46 D11
claude-code/skills/codex-collaboration/PLAN-REVIEW.md:65 fail-closed
claude-code/skills/codex-collaboration/PLAN-REVIEW.md:83 off-subject
claude-code/skills/codex-collaboration/PLAN-REVIEW.md:94 off-subject
claude-code/skills/codex-collaboration/PLAN-REVIEW.md:95 off-subject
claude-code/skills/codex-collaboration/SKILL.md:22 cross-reference
claude-code/skills/codex-collaboration/SKILL.md:38 E12
claude-code/skills/codex-collaboration/SKILL.md:39 E12
claude-code/skills/codex-collaboration/SKILL.md:65 E13
claude-code/skills/codex-collaboration/SKILL.md:66 E13
claude-code/skills/codex-collaboration/SKILL.md:112 cross-reference
claude-code/skills/codex-collaboration/SKILL.md:119 E14
claude-code/skills/codex-collaboration/SKILL.md:126 E14
claude-code/skills/codex-collaboration/SKILL.md:135 E14
claude-code/skills/codex-collaboration/SKILL.md:136 E14
claude-code/skills/codex-collaboration/SKILL.md:139 E14
claude-code/skills/codex-collaboration/SKILL.md:141 E14
claude-code/skills/orchestrate-issues/SKILL.md:53 state-vocabulary
claude-code/skills/orchestrate-issues/SKILL.md:55 state-vocabulary
claude-code/skills/orchestrate-issues/SKILL.md:56 state-vocabulary
claude-code/skills/orchestrate-issues/SKILL.md:60 state-vocabulary
claude-code/skills/orchestrate-issues/SKILL.md:63 state-vocabulary
```

Four rows are absent from that list because neither pass's vocabulary appears on
their lines; each was found by reading the surrounding file while adjudicating a
different hit in the same file:

```
C3  skills/to-issues/SKILL.md:18
C5  skills/ship-release/SKILL.md:30
C6  skills/ship-release/SKILL.md:28
D4  skills/doc-grounded-questions/SKILL.md:24 + REFERENCE.md:41-45
```

The further lines of a multi-line row citation are likewise absent from the map
wherever only some of them carry a pass's vocabulary — `E14`'s 23-line block
matched on lines 119, 126, 135, 136, 139 and 141 only, and of `C9`'s
`from-issue/bindings.md:6,12,14` only `:6` matched, so `:12` and `:14` appear
nowhere above. The map lists hits, not row lines; the two are reconciled by the
row citations published in `Per-site inventory`.

