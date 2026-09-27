# Instruction load: 1b92fdf → a80e5bf

- Base: `1b92fdf5b98c23266329256a70eb0bc6608dd659`
- Head: `a80e5bf91c9d8d6c4f3a0cc4abb5cddb19ec1ed7`
- Regenerate: `just agent-instruction-load report --base 1b92fdf5b98c23266329256a70eb0bc6608dd659 --head a80e5bf91c9d8d6c4f3a0cc4abb5cddb19ec1ed7 --output <path>`

Bytes are UTF-8 lengths and words are whitespace-separated tokens; neither is a token count. A hot member loads on every run of its profile's standard route and a conditional member only on a named branch. A shared-tree member counts on both hosts; a Claude-only-tree member or an agent definition counts on Claude only.

Not measured: received prompts (each profile names its prompt's source document), the harness system prompt and skill listing, project instructions, and plugin or generated skills. The frame, the global guidance file installed for both hosts, is reported once and kept out of every profile total.

## Frame

| Member | Base bytes | Head bytes | Δ bytes | Base words | Head words | Δ words |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `agent-guidance/AGENTS.md` | 580 | 580 | 0 | 80 | 80 | 0 |

## Hot totals

| Profile | Host | Base bytes | Head bytes | Δ bytes | Base words | Head words | Δ words | Affected | Note |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| from-issue-controller | claude | 88142 | 87439 | -703 | 11912 | 11813 | -99 | yes | Direct autonomous `--auto` run of Phases 0–5 and the rollover. Design, grill and planning run in their owners. The hot path keeps from-issue's top-level acquisition routes and AUTO.md's rollover, whose route-scoping is deferred (#155 D6). |
| from-issue-controller | codex | 88142 | 87439 | -703 | 11912 | 11813 | -99 | yes | Direct autonomous `--auto` run of Phases 0–5 and the rollover. Design, grill and planning run in their owners. The hot path keeps from-issue's top-level acquisition routes and AUTO.md's rollover, whose route-scoping is deferred (#155 D6). |
| orchestration-dispatcher | claude | 22594 | 22461 | -133 | 3100 | 3081 | -19 | yes | One control-adapter run. It loads only its entry, whose resolver paragraph and lifecycle-call rule stay per entry (#155 D5). Ceiling re-measured after merging origin/main at 382b59c (#155 D19). |
| orchestrated-issue-owner | claude | 147326 | 146623 | -703 | 19857 | 19758 | -99 | yes | Dispatcher-owned `--auto` run of Phases 0–7 in one owner: from-issue with AUTO.md, sdd at Phase 6 and the ship prompt at Phase 7. It carries from-issue's top-level acquisition routes and AUTO.md's rollover, which its route never takes (#155 D6). Ceiling re-measured after merging origin/main at 7c21ebe (#155 D19). |
| design-and-grill-owner | claude | 28445 | 28256 | -189 | 4171 | 4141 | -30 | yes | Phases 2–3 from AUTO.md's prompt: design, grill-with-docs and doc-grounded-questions. Their producer-report and explorer-escalation blocks stay per skill (#155 D5). |
| design-and-grill-owner | codex | 28445 | 28256 | -189 | 4171 | 4141 | -30 | yes | Phases 2–3 from AUTO.md's prompt: design, grill-with-docs and doc-grounded-questions. Their producer-report and explorer-escalation blocks stay per skill (#155 D5). |
| planning-owner | claude | 22423 | 22322 | -101 | 3296 | 3281 | -15 | yes | Phase 4 from AUTO.md's prompt: writing-plans and doc-grounded-questions, plus the review contract for a mechanical-only self-grade. The producer-report block stays per skill (#155 D5). |
| planning-owner | codex | 22423 | 22322 | -101 | 3296 | 3281 | -15 | yes | Phase 4 from AUTO.md's prompt: writing-plans and doc-grounded-questions, plus the review contract for a mechanical-only self-grade. The producer-report block stays per skill (#155 D5). |
| implementation-owner | claude | 138319 | 137669 | -650 | 18572 | 18481 | -91 | yes | Post-rollover Phases 6–7: from-issue with AUTO.md, sdd and the ship prompt; the Phase 0–5 documents stay unread. It carries from-issue's top-level acquisition routes, whose route-scoping is deferred (#155 D6). Ceiling re-measured after merging origin/main at 7c21ebe (#155 D19). |
| implementation-owner | codex | 138319 | 137669 | -650 | 18572 | 18481 | -91 | yes | Post-rollover Phases 6–7: from-issue with AUTO.md, sdd and the ship prompt; the Phase 0–5 documents stay unread. It carries from-issue's top-level acquisition routes, whose route-scoping is deferred (#155 D6). Ceiling re-measured after merging origin/main at 7c21ebe (#155 D19). |
| ship-owner | claude | 52939 | 52871 | -68 | 7341 | 7330 | -11 | yes | ship-issue from ship-handoff.md's prompt, with its sync, review and consolidation files. The lifecycle stdin clause stays per entry (#155 D5). |
| ship-owner | codex | 52939 | 52871 | -68 | 7341 | 7330 | -11 | yes | ship-issue from ship-handoff.md's prompt, with its sync, review and consolidation files. The lifecycle stdin clause stays per entry (#155 D5). |
| release-owner | claude | 41994 | 41929 | -65 | 6224 | 6211 | -13 | yes | One delegated release through ship-release and its changelog rubric. |
| release-owner | codex | 41994 | 41929 | -65 | 6224 | 6211 | -13 | yes | One delegated release through ship-release and its changelog rubric. |
| researcher | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | The background researcher works from the job list in research's prompt and loads no skill document. |
| researcher | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | The background researcher works from the job list in research's prompt and loads no skill document. |
| architecture-scan-owner | claude | 12998 | 12945 | -53 | 1801 | 1793 | -8 | yes | The read-only scan from improve-codebase-architecture's prompt. The codebase-design vocabulary and the grounding pass are ambiguous between caller and scan owner, so they count as hot. |
| architecture-scan-owner | codex | 12998 | 12945 | -53 | 1801 | 1793 | -8 | yes | The read-only scan from improve-codebase-architecture's prompt. The codebase-design vocabulary and the grounding pass are ambiguous between caller and scan owner, so they count as hot. |
| research | claude | 3685 | 3617 | -68 | 508 | 497 | -11 | yes | A standalone research launch. It loads only its entry. |
| research | codex | 3685 | 3617 | -68 | 508 | 497 | -11 | yes | A standalone research launch. It loads only its entry. |
| wayfind | claude | 20492 | 20356 | -136 | 3107 | 3085 | -22 | yes | One decision session. Grilling is the default mode; research and prototype sessions are conditional. |
| wayfind | codex | 20492 | 20356 | -136 | 3107 | 3085 | -22 | yes | One decision session. Grilling is the default mode; research and prototype sessions are conditional. |
| to-issues | claude | 9376 | 9308 | -68 | 1432 | 1421 | -11 | yes | One slicing run. The wide-refactor exception is conditional. |
| to-issues | codex | 9376 | 9308 | -68 | 1432 | 1421 | -11 | yes | One slicing run. The wide-refactor exception is conditional. |
| ship-release | claude | 41994 | 41929 | -65 | 6224 | 6211 | -13 | yes | A direct interactive release, with the current session as owner. |
| ship-release | codex | 41994 | 41929 | -65 | 6224 | 6211 | -13 | yes | A direct interactive release, with the current session as owner. |
| plan-reviewer | claude | 9854 | 9854 | 0 | 1448 | 1448 | 0 | no | The Phase-5 plan reviewer: its agent definition on Claude and the review contract it is told to read. Its prompt comes from standards-review.md. |
| plan-reviewer | codex | 8839 | 8839 | 0 | 1283 | 1283 | 0 | no | The Phase-5 plan reviewer: its agent definition on Claude and the review contract it is told to read. Its prompt comes from standards-review.md. |
| from-issue-mechanic | claude | 679 | 679 | 0 | 97 | 97 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| from-issue-mechanic | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| from-issue-mechanical-reviewer | claude | 1015 | 1015 | 0 | 165 | 165 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| from-issue-mechanical-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| inline-ship-reviewer | claude | 1015 | 1015 | 0 | 165 | 165 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/ship-handoff.md, whose leaf clauses #153 holds (#155 D5). |
| inline-ship-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/ship-handoff.md, whose leaf clauses #153 holds (#155 D5). |
| design-explorer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from design/SKILL.md. |
| design-explorer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from design/SKILL.md. |
| grill-explorer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from grill-with-docs/SKILL.md. |
| grill-explorer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from grill-with-docs/SKILL.md. |
| planning-explorer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from writing-plans/SKILL.md. |
| planning-explorer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from writing-plans/SKILL.md. |
| grounding-explorer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from doc-grounded-questions/SKILL.md. |
| grounding-explorer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from doc-grounded-questions/SKILL.md. |
| sdd-mechanic | claude | 679 | 679 | 0 | 97 | 97 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/implementer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-mechanic | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/implementer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-implementer | claude | 1089 | 1089 | 0 | 166 | 166 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/implementer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-implementer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/implementer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-task-reviewer | claude | 1015 | 1015 | 0 | 165 | 165 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/task-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-task-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/task-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-task-rereviewer | claude | 1443 | 1443 | 0 | 223 | 223 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/re-review-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-task-rereviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/re-review-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-lane-verifier | claude | 1443 | 1443 | 0 | 223 | 223 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-lane-verifier | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-fix-implementer | claude | 1089 | 1089 | 0 | 166 | 166 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/fix-loop.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-fix-implementer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/fix-loop.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-fix-escalation-reviewer | claude | 1015 | 1015 | 0 | 165 | 165 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/fix-loop.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-fix-escalation-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/fix-loop.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-conformance-reviewer | claude | 1015 | 1015 | 0 | 165 | 165 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/conformance-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-conformance-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/conformance-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-correctness-reviewer | claude | 1015 | 1015 | 0 | 165 | 165 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/correctness-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-correctness-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/correctness-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-fixer | claude | 1089 | 1089 | 0 | 166 | 166 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-fixer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-rereviewer | claude | 1443 | 1443 | 0 | 223 | 223 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-rereviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-escalation-reviewer | claude | 1015 | 1015 | 0 | 165 | 165 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-escalation-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| ship-issue-reviewer | claude | 1015 | 1015 | 0 | 165 | 165 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from ship-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| ship-issue-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from ship-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| ship-issue-rereviewer | claude | 1443 | 1443 | 0 | 223 | 223 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from ship-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| ship-issue-rereviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from ship-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |

## Conditional totals

| Profile | Host | Base bytes | Head bytes | Δ bytes | Base words | Head words | Δ words | Affected | Note |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| from-issue-controller | claude | 44273 | 44137 | -136 | 6204 | 6182 | -22 | yes | Direct autonomous `--auto` run of Phases 0–5 and the rollover. Design, grill and planning run in their owners. The hot path keeps from-issue's top-level acquisition routes and AUTO.md's rollover, whose route-scoping is deferred (#155 D6). |
| from-issue-controller | codex | 34273 | 34205 | -68 | 4835 | 4824 | -11 | yes | Direct autonomous `--auto` run of Phases 0–5 and the rollover. Design, grill and planning run in their owners. The hot path keeps from-issue's top-level acquisition routes and AUTO.md's rollover, whose route-scoping is deferred (#155 D6). |
| orchestration-dispatcher | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | One control-adapter run. It loads only its entry, whose resolver paragraph and lifecycle-call rule stay per entry (#155 D5). Ceiling re-measured after merging origin/main at 382b59c (#155 D19). |
| orchestrated-issue-owner | claude | 63441 | 63305 | -136 | 9312 | 9290 | -22 | yes | Dispatcher-owned `--auto` run of Phases 0–7 in one owner: from-issue with AUTO.md, sdd at Phase 6 and the ship prompt at Phase 7. It carries from-issue's top-level acquisition routes and AUTO.md's rollover, which its route never takes (#155 D6). Ceiling re-measured after merging origin/main at 7c21ebe (#155 D19). |
| design-and-grill-owner | claude | 22612 | 22544 | -68 | 3460 | 3449 | -11 | yes | Phases 2–3 from AUTO.md's prompt: design, grill-with-docs and doc-grounded-questions. Their producer-report and explorer-escalation blocks stay per skill (#155 D5). |
| design-and-grill-owner | codex | 22612 | 22544 | -68 | 3460 | 3449 | -11 | yes | Phases 2–3 from AUTO.md's prompt: design, grill-with-docs and doc-grounded-questions. Their producer-report and explorer-escalation blocks stay per skill (#155 D5). |
| planning-owner | claude | 13313 | 13313 | 0 | 1987 | 1987 | 0 | no | Phase 4 from AUTO.md's prompt: writing-plans and doc-grounded-questions, plus the review contract for a mechanical-only self-grade. The producer-report block stays per skill (#155 D5). |
| planning-owner | codex | 13313 | 13313 | 0 | 1987 | 1987 | 0 | no | Phase 4 from AUTO.md's prompt: writing-plans and doc-grounded-questions, plus the review contract for a mechanical-only self-grade. The producer-report block stays per skill (#155 D5). |
| implementation-owner | claude | 35237 | 35169 | -68 | 5098 | 5087 | -11 | yes | Post-rollover Phases 6–7: from-issue with AUTO.md, sdd and the ship prompt; the Phase 0–5 documents stay unread. It carries from-issue's top-level acquisition routes, whose route-scoping is deferred (#155 D6). Ceiling re-measured after merging origin/main at 7c21ebe (#155 D19). |
| implementation-owner | codex | 20203 | 20203 | 0 | 2883 | 2883 | 0 | no | Post-rollover Phases 6–7: from-issue with AUTO.md, sdd and the ship prompt; the Phase 0–5 documents stay unread. It carries from-issue's top-level acquisition routes, whose route-scoping is deferred (#155 D6). Ceiling re-measured after merging origin/main at 7c21ebe (#155 D19). |
| ship-owner | claude | 35421 | 35300 | -121 | 5332 | 5313 | -19 | yes | ship-issue from ship-handoff.md's prompt, with its sync, review and consolidation files. The lifecycle stdin clause stays per entry (#155 D5). |
| ship-owner | codex | 20387 | 20334 | -53 | 3117 | 3109 | -8 | yes | ship-issue from ship-handoff.md's prompt, with its sync, review and consolidation files. The lifecycle stdin clause stays per entry (#155 D5). |
| release-owner | claude | 17890 | 17769 | -121 | 2692 | 2673 | -19 | yes | One delegated release through ship-release and its changelog rubric. |
| release-owner | codex | 17890 | 17769 | -121 | 2692 | 2673 | -19 | yes | One delegated release through ship-release and its changelog rubric. |
| researcher | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | The background researcher works from the job list in research's prompt and loads no skill document. |
| researcher | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | The background researcher works from the job list in research's prompt and loads no skill document. |
| architecture-scan-owner | claude | 10376 | 10376 | 0 | 1604 | 1604 | 0 | no | The read-only scan from improve-codebase-architecture's prompt. The codebase-design vocabulary and the grounding pass are ambiguous between caller and scan owner, so they count as hot. |
| architecture-scan-owner | codex | 10376 | 10376 | 0 | 1604 | 1604 | 0 | no | The read-only scan from improve-codebase-architecture's prompt. The codebase-design vocabulary and the grounding pass are ambiguous between caller and scan owner, so they count as hot. |
| research | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | A standalone research launch. It loads only its entry. |
| research | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | A standalone research launch. It loads only its entry. |
| wayfind | claude | 45479 | 45343 | -136 | 7189 | 7167 | -22 | yes | One decision session. Grilling is the default mode; research and prototype sessions are conditional. |
| wayfind | codex | 45479 | 45343 | -136 | 7189 | 7167 | -22 | yes | One decision session. Grilling is the default mode; research and prototype sessions are conditional. |
| to-issues | claude | 1053 | 1053 | 0 | 177 | 177 | 0 | no | One slicing run. The wide-refactor exception is conditional. |
| to-issues | codex | 1053 | 1053 | 0 | 177 | 177 | 0 | no | One slicing run. The wide-refactor exception is conditional. |
| ship-release | claude | 17890 | 17769 | -121 | 2692 | 2673 | -19 | yes | A direct interactive release, with the current session as owner. |
| ship-release | codex | 17890 | 17769 | -121 | 2692 | 2673 | -19 | yes | A direct interactive release, with the current session as owner. |
| plan-reviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | The Phase-5 plan reviewer: its agent definition on Claude and the review contract it is told to read. Its prompt comes from standards-review.md. |
| plan-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | The Phase-5 plan reviewer: its agent definition on Claude and the review contract it is told to read. Its prompt comes from standards-review.md. |
| from-issue-mechanic | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| from-issue-mechanic | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| from-issue-mechanical-reviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| from-issue-mechanical-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| inline-ship-reviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/ship-handoff.md, whose leaf clauses #153 holds (#155 D5). |
| inline-ship-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/ship-handoff.md, whose leaf clauses #153 holds (#155 D5). |
| design-explorer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from design/SKILL.md. |
| design-explorer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from design/SKILL.md. |
| grill-explorer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from grill-with-docs/SKILL.md. |
| grill-explorer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from grill-with-docs/SKILL.md. |
| planning-explorer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from writing-plans/SKILL.md. |
| planning-explorer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from writing-plans/SKILL.md. |
| grounding-explorer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from doc-grounded-questions/SKILL.md. |
| grounding-explorer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | The built-in Explore type: no installed definition and no skill document. Its prompt is composed from doc-grounded-questions/SKILL.md. |
| sdd-mechanic | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/implementer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-mechanic | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/implementer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-implementer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/implementer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-implementer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/implementer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-task-reviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/task-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-task-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/task-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-task-rereviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/re-review-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-task-rereviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/re-review-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-lane-verifier | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-lane-verifier | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-fix-implementer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/fix-loop.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-fix-implementer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/fix-loop.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-fix-escalation-reviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/fix-loop.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-fix-escalation-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/fix-loop.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-conformance-reviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/conformance-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-conformance-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/conformance-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-correctness-reviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/correctness-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-correctness-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/correctness-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-fixer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-fixer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-rereviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-rereviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-escalation-reviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| sdd-final-escalation-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5). |
| ship-issue-reviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from ship-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| ship-issue-reviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from ship-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| ship-issue-rereviewer | claude | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from ship-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |
| ship-issue-rereviewer | codex | 0 | 0 | 0 | 0 | 0 | 0 | no | Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from ship-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5). |

## Documents

| Member | Hosts | Base bytes | Head bytes | Δ bytes | Base words | Head words | Δ words |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `agents/implementer.md` | claude | 1089 | 1089 | 0 | 166 | 166 | 0 |
| `agents/mechanic.md` | claude | 679 | 679 | 0 | 97 | 97 | 0 |
| `agents/reviewer-lite.md` | claude | 1443 | 1443 | 0 | 223 | 223 | 0 |
| `agents/reviewer.md` | claude | 1015 | 1015 | 0 | 165 | 165 | 0 |
| `codebase-design/DEEPENING.md` | claude, codex | 2559 | 2559 | 0 | 388 | 388 | 0 |
| `codebase-design/DESIGN-IT-TWICE.md` | claude, codex | 3343 | 3343 | 0 | 512 | 512 | 0 |
| `codebase-design/SKILL.md` | claude, codex | 6810 | 6810 | 0 | 916 | 916 | 0 |
| `codex-collaboration/DIFF-REVIEW.md` | claude | 11205 | 11205 | 0 | 1713 | 1713 | 0 |
| `codex-collaboration/PLAN-REVIEW.md` | claude | 6171 | 6171 | 0 | 867 | 867 | 0 |
| `codex-collaboration/SKILL.md` | claude | 3829 | 3761 | -68 | 502 | 491 | -11 |
| `design/SKILL.md` | claude, codex | 10497 | 10429 | -68 | 1520 | 1509 | -11 |
| `doc-grounded-questions/REFERENCE.md` | claude, codex | 4474 | 4474 | 0 | 704 | 704 | 0 |
| `doc-grounded-questions/SKILL.md` | claude, codex | 6188 | 6135 | -53 | 885 | 877 | -8 |
| `from-issue/AUTO.md` | claude, codex | 22616 | 22148 | -468 | 2907 | 2844 | -63 |
| `from-issue/REVIEW-CONTRACT.md` | claude, codex | 8839 | 8839 | 0 | 1283 | 1283 | 0 |
| `from-issue/SKILL.md` | claude, codex | 41525 | 41411 | -114 | 5577 | 5560 | -17 |
| `from-issue/bindings.md` | claude, codex | 815 | 815 | 0 | 77 | 77 | 0 |
| `from-issue/decision-ledger.md` | claude, codex | 1018 | 1018 | 0 | 154 | 154 | 0 |
| `from-issue/grounding.md` | claude, codex | 1026 | 1026 | 0 | 138 | 138 | 0 |
| `from-issue/investigate.md` | claude, codex | 3174 | 3174 | 0 | 445 | 445 | 0 |
| `from-issue/ship-handoff.md` | claude, codex | 10547 | 10547 | 0 | 1174 | 1174 | 0 |
| `from-issue/standards-review.md` | claude, codex | 4552 | 4552 | 0 | 626 | 626 | 0 |
| `grill-with-docs/ADR-FORMAT.md` | claude, codex | 3851 | 3851 | 0 | 605 | 605 | 0 |
| `grill-with-docs/CONTEXT-FORMAT.md` | claude, codex | 10602 | 10602 | 0 | 1643 | 1643 | 0 |
| `grill-with-docs/SKILL.md` | claude, codex | 11760 | 11692 | -68 | 1766 | 1755 | -11 |
| `handoff/SKILL.md` | claude, codex | 7626 | 7626 | 0 | 1123 | 1123 | 0 |
| `orchestrate-issues/SKILL.md` | claude | 22594 | 22461 | -133 | 3100 | 3081 | -19 |
| `prototype/LOGIC.md` | claude, codex | 5594 | 5594 | 0 | 958 | 958 | 0 |
| `prototype/SKILL.md` | claude, codex | 4836 | 4836 | 0 | 776 | 776 | 0 |
| `prototype/UI.md` | claude, codex | 6789 | 6789 | 0 | 1103 | 1103 | 0 |
| `research/SKILL.md` | claude, codex | 3685 | 3617 | -68 | 508 | 497 | -11 |
| `sdd/SKILL.md` | claude, codex | 19977 | 19977 | 0 | 2844 | 2844 | 0 |
| `sdd/conformance-reviewer-prompt.md` | claude, codex | 6281 | 6281 | 0 | 828 | 828 | 0 |
| `sdd/correctness-reviewer-prompt.md` | claude, codex | 6951 | 6951 | 0 | 963 | 963 | 0 |
| `sdd/final-review.md` | claude, codex | 6888 | 6888 | 0 | 906 | 906 | 0 |
| `sdd/fix-loop.md` | claude, codex | 5462 | 5462 | 0 | 749 | 749 | 0 |
| `sdd/implementer-prompt.md` | claude, codex | 5678 | 5678 | 0 | 828 | 828 | 0 |
| `sdd/re-review-prompt.md` | claude, codex | 6097 | 6097 | 0 | 857 | 857 | 0 |
| `sdd/task-reviewer-prompt.md` | claude, codex | 9813 | 9813 | 0 | 1365 | 1365 | 0 |
| `ship-issue/CI-MERGE.md` | claude, codex | 3906 | 3906 | 0 | 625 | 625 | 0 |
| `ship-issue/CONSOLIDATE.md` | claude, codex | 4931 | 4931 | 0 | 718 | 718 | 0 |
| `ship-issue/HUMAN-GATE.md` | claude, codex | 5819 | 5819 | 0 | 903 | 903 | 0 |
| `ship-issue/REVIEW.md` | claude, codex | 8187 | 8187 | 0 | 1136 | 1136 | 0 |
| `ship-issue/SKILL.md` | claude, codex | 35584 | 35516 | -68 | 4896 | 4885 | -11 |
| `ship-issue/SYNC.md` | claude, codex | 4237 | 4237 | 0 | 591 | 591 | 0 |
| `ship-release/CHANGELOG.md` | claude, codex | 11060 | 11060 | 0 | 1675 | 1675 | 0 |
| `ship-release/SKILL.md` | claude, codex | 30934 | 30869 | -65 | 4549 | 4536 | -13 |
| `to-issues/SKILL.md` | claude, codex | 9376 | 9308 | -68 | 1432 | 1421 | -11 |
| `to-issues/WIDE-REFACTORS.md` | claude, codex | 1053 | 1053 | 0 | 177 | 177 | 0 |
| `wayfind/DISCIPLINE.md` | claude, codex | 2894 | 2894 | 0 | 493 | 493 | 0 |
| `wayfind/SKILL.md` | claude, codex | 8732 | 8664 | -68 | 1341 | 1330 | -11 |
| `worktrees/SKILL.md` | claude, codex | 7228 | 7160 | -68 | 1103 | 1092 | -11 |
| `writing-plans/SKILL.md` | claude, codex | 16235 | 16187 | -48 | 2411 | 2404 | -7 |

## Members by profile

### from-issue-controller

- Launched by: entry `from-issue`
- Prompt: none (an entry)
- claude — hot: `from-issue/SKILL.md`, `from-issue/AUTO.md`, `from-issue/bindings.md`, `from-issue/investigate.md`, `from-issue/grounding.md`, `from-issue/decision-ledger.md`, `from-issue/standards-review.md`, `doc-grounded-questions/SKILL.md`, `worktrees/SKILL.md`; conditional: `from-issue/ship-handoff.md`, `handoff/SKILL.md`, `wayfind/SKILL.md`, `wayfind/DISCIPLINE.md`, `doc-grounded-questions/REFERENCE.md`, `codex-collaboration/SKILL.md`, `codex-collaboration/PLAN-REVIEW.md`
- codex — hot: `from-issue/SKILL.md`, `from-issue/AUTO.md`, `from-issue/bindings.md`, `from-issue/investigate.md`, `from-issue/grounding.md`, `from-issue/decision-ledger.md`, `from-issue/standards-review.md`, `doc-grounded-questions/SKILL.md`, `worktrees/SKILL.md`; conditional: `from-issue/ship-handoff.md`, `handoff/SKILL.md`, `wayfind/SKILL.md`, `wayfind/DISCIPLINE.md`, `doc-grounded-questions/REFERENCE.md`
- Unread: `from-issue/REVIEW-CONTRACT.md` — handed to the plan reviewer by absolute path, never read into this conversation
- Unread: `codex-collaboration/DIFF-REVIEW.md` — diff-review is not a Phase 0–5 operation

### orchestration-dispatcher

- Launched by: entry `orchestrate-issues`
- Prompt: none (an entry)
- claude — hot: `orchestrate-issues/SKILL.md`; conditional: none

### orchestrated-issue-owner

- Launched by: sites `orchestration-issue-owner`
- Prompt: `orchestrate-issues/SKILL.md` (not measured)
- claude — hot: `from-issue/SKILL.md`, `from-issue/AUTO.md`, `from-issue/bindings.md`, `from-issue/investigate.md`, `from-issue/grounding.md`, `from-issue/decision-ledger.md`, `from-issue/standards-review.md`, `from-issue/ship-handoff.md`, `doc-grounded-questions/SKILL.md`, `worktrees/SKILL.md`, `sdd/SKILL.md`, `sdd/implementer-prompt.md`, `sdd/task-reviewer-prompt.md`, `sdd/final-review.md`, `sdd/conformance-reviewer-prompt.md`; conditional: `sdd/fix-loop.md`, `sdd/re-review-prompt.md`, `sdd/correctness-reviewer-prompt.md`, `codex-collaboration/SKILL.md`, `codex-collaboration/PLAN-REVIEW.md`, `codex-collaboration/DIFF-REVIEW.md`, `handoff/SKILL.md`, `wayfind/SKILL.md`, `wayfind/DISCIPLINE.md`, `doc-grounded-questions/REFERENCE.md`
- Unread: `from-issue/REVIEW-CONTRACT.md` — handed to the plan reviewer by absolute path, never read into this conversation

### design-and-grill-owner

- Launched by: sites `from-issue-design-grill`
- Prompt: `from-issue/AUTO.md` (not measured)
- claude — hot: `design/SKILL.md`, `grill-with-docs/SKILL.md`, `doc-grounded-questions/SKILL.md`; conditional: `grill-with-docs/CONTEXT-FORMAT.md`, `grill-with-docs/ADR-FORMAT.md`, `doc-grounded-questions/REFERENCE.md`, `research/SKILL.md`
- codex — hot: `design/SKILL.md`, `grill-with-docs/SKILL.md`, `doc-grounded-questions/SKILL.md`; conditional: `grill-with-docs/CONTEXT-FORMAT.md`, `grill-with-docs/ADR-FORMAT.md`, `doc-grounded-questions/REFERENCE.md`, `research/SKILL.md`

### planning-owner

- Launched by: sites `from-issue-planning`
- Prompt: `from-issue/AUTO.md` (not measured)
- claude — hot: `writing-plans/SKILL.md`, `doc-grounded-questions/SKILL.md`; conditional: `doc-grounded-questions/REFERENCE.md`, `from-issue/REVIEW-CONTRACT.md`
- codex — hot: `writing-plans/SKILL.md`, `doc-grounded-questions/SKILL.md`; conditional: `doc-grounded-questions/REFERENCE.md`, `from-issue/REVIEW-CONTRACT.md`

### implementation-owner

- Launched by: sites `from-issue-phase-delegate`
- Prompt: `from-issue/AUTO.md` (not measured)
- claude — hot: `from-issue/SKILL.md`, `from-issue/AUTO.md`, `from-issue/bindings.md`, `from-issue/ship-handoff.md`, `sdd/SKILL.md`, `sdd/implementer-prompt.md`, `sdd/task-reviewer-prompt.md`, `sdd/final-review.md`, `sdd/conformance-reviewer-prompt.md`, `sdd/correctness-reviewer-prompt.md`, `worktrees/SKILL.md`; conditional: `sdd/fix-loop.md`, `sdd/re-review-prompt.md`, `codex-collaboration/SKILL.md`, `codex-collaboration/DIFF-REVIEW.md`, `from-issue/decision-ledger.md`, `handoff/SKILL.md`
- codex — hot: `from-issue/SKILL.md`, `from-issue/AUTO.md`, `from-issue/bindings.md`, `from-issue/ship-handoff.md`, `sdd/SKILL.md`, `sdd/implementer-prompt.md`, `sdd/task-reviewer-prompt.md`, `sdd/final-review.md`, `sdd/conformance-reviewer-prompt.md`, `sdd/correctness-reviewer-prompt.md`, `worktrees/SKILL.md`; conditional: `sdd/fix-loop.md`, `sdd/re-review-prompt.md`, `from-issue/decision-ledger.md`, `handoff/SKILL.md`
- Unread: `from-issue/investigate.md` — Phase 0 ran in the earlier controller
- Unread: `from-issue/grounding.md` — Phases 2–5 ran in the earlier controller
- Unread: `from-issue/standards-review.md` — Phase 5 ran in the earlier controller
- Unread: `from-issue/REVIEW-CONTRACT.md` — the Phase-5 reviewer contract, handed over by path
- Unread: `codex-collaboration/PLAN-REVIEW.md` — plan-review ran at Phase 5

### ship-owner

- Launched by: sites `from-issue-ship-owner`
- Prompt: `from-issue/ship-handoff.md` (not measured)
- claude — hot: `ship-issue/SKILL.md`, `ship-issue/SYNC.md`, `ship-issue/REVIEW.md`, `ship-issue/CONSOLIDATE.md`; conditional: `ship-issue/CI-MERGE.md`, `ship-issue/HUMAN-GATE.md`, `doc-grounded-questions/SKILL.md`, `doc-grounded-questions/REFERENCE.md`, `codex-collaboration/SKILL.md`, `codex-collaboration/DIFF-REVIEW.md`
- codex — hot: `ship-issue/SKILL.md`, `ship-issue/SYNC.md`, `ship-issue/REVIEW.md`, `ship-issue/CONSOLIDATE.md`; conditional: `ship-issue/CI-MERGE.md`, `ship-issue/HUMAN-GATE.md`, `doc-grounded-questions/SKILL.md`, `doc-grounded-questions/REFERENCE.md`
- Unread: `codex-collaboration/PLAN-REVIEW.md` — plan-review is not a ship operation

### release-owner

- Launched by: sites `ship-release-owner`
- Prompt: `ship-release/SKILL.md` (not measured)
- claude — hot: `ship-release/SKILL.md`, `ship-release/CHANGELOG.md`; conditional: `doc-grounded-questions/SKILL.md`, `doc-grounded-questions/REFERENCE.md`, `worktrees/SKILL.md`
- codex — hot: `ship-release/SKILL.md`, `ship-release/CHANGELOG.md`; conditional: `doc-grounded-questions/SKILL.md`, `doc-grounded-questions/REFERENCE.md`, `worktrees/SKILL.md`

### researcher

- Launched by: sites `research-background-researcher`
- Prompt: `research/SKILL.md` (not measured)
- claude — hot: none; conditional: none
- codex — hot: none; conditional: none

### architecture-scan-owner

- Launched by: sites `improve-architecture-scan-owner`
- Prompt: `improve-codebase-architecture/SKILL.md` (not measured)
- claude — hot: `codebase-design/SKILL.md`, `doc-grounded-questions/SKILL.md`; conditional: `codebase-design/DEEPENING.md`, `codebase-design/DESIGN-IT-TWICE.md`, `doc-grounded-questions/REFERENCE.md`
- codex — hot: `codebase-design/SKILL.md`, `doc-grounded-questions/SKILL.md`; conditional: `codebase-design/DEEPENING.md`, `codebase-design/DESIGN-IT-TWICE.md`, `doc-grounded-questions/REFERENCE.md`

### research

- Launched by: entry `research`
- Prompt: none (an entry)
- claude — hot: `research/SKILL.md`; conditional: none
- codex — hot: `research/SKILL.md`; conditional: none

### wayfind

- Launched by: entry `wayfind`
- Prompt: none (an entry)
- claude — hot: `wayfind/SKILL.md`, `grill-with-docs/SKILL.md`; conditional: `wayfind/DISCIPLINE.md`, `grill-with-docs/CONTEXT-FORMAT.md`, `grill-with-docs/ADR-FORMAT.md`, `research/SKILL.md`, `prototype/SKILL.md`, `prototype/LOGIC.md`, `prototype/UI.md`, `worktrees/SKILL.md`
- codex — hot: `wayfind/SKILL.md`, `grill-with-docs/SKILL.md`; conditional: `wayfind/DISCIPLINE.md`, `grill-with-docs/CONTEXT-FORMAT.md`, `grill-with-docs/ADR-FORMAT.md`, `research/SKILL.md`, `prototype/SKILL.md`, `prototype/LOGIC.md`, `prototype/UI.md`, `worktrees/SKILL.md`

### to-issues

- Launched by: entry `to-issues`
- Prompt: none (an entry)
- claude — hot: `to-issues/SKILL.md`; conditional: `to-issues/WIDE-REFACTORS.md`
- codex — hot: `to-issues/SKILL.md`; conditional: `to-issues/WIDE-REFACTORS.md`

### ship-release

- Launched by: entry `ship-release`
- Prompt: none (an entry)
- claude — hot: `ship-release/SKILL.md`, `ship-release/CHANGELOG.md`; conditional: `doc-grounded-questions/SKILL.md`, `doc-grounded-questions/REFERENCE.md`, `worktrees/SKILL.md`
- codex — hot: `ship-release/SKILL.md`, `ship-release/CHANGELOG.md`; conditional: `doc-grounded-questions/SKILL.md`, `doc-grounded-questions/REFERENCE.md`, `worktrees/SKILL.md`

### plan-reviewer

- Launched by: sites `from-issue-plan-review`
- Prompt: `from-issue/standards-review.md` (not measured)
- claude — hot: `agents/reviewer.md`, `from-issue/REVIEW-CONTRACT.md`; conditional: none
- codex — hot: `from-issue/REVIEW-CONTRACT.md`; conditional: none

### from-issue-mechanic

- Launched by: sites `from-issue-mechanical-implementation`, `from-issue-ledger-remainder`
- Prompt: `from-issue/SKILL.md` (not measured)
- claude — hot: `agents/mechanic.md`; conditional: none
- codex — hot: none; conditional: none

### from-issue-mechanical-reviewer

- Launched by: sites `from-issue-mechanical-review`
- Prompt: `from-issue/SKILL.md` (not measured)
- claude — hot: `agents/reviewer.md`; conditional: none
- codex — hot: none; conditional: none

### inline-ship-reviewer

- Launched by: sites `from-issue-inline-ship-review`
- Prompt: `from-issue/ship-handoff.md` (not measured)
- claude — hot: `agents/reviewer.md`; conditional: none
- codex — hot: none; conditional: none

### design-explorer

- Launched by: sites `design-bounded-fact-lookup`
- Prompt: `design/SKILL.md` (not measured)
- claude — hot: none; conditional: none
- codex — hot: none; conditional: none

### grill-explorer

- Launched by: sites `grill-bounded-fact-lookup`
- Prompt: `grill-with-docs/SKILL.md` (not measured)
- claude — hot: none; conditional: none
- codex — hot: none; conditional: none

### planning-explorer

- Launched by: sites `planning-bounded-fact-lookup`
- Prompt: `writing-plans/SKILL.md` (not measured)
- claude — hot: none; conditional: none
- codex — hot: none; conditional: none

### grounding-explorer

- Launched by: sites `doc-grounded-bounded-code-lookup`
- Prompt: `doc-grounded-questions/SKILL.md` (not measured)
- claude — hot: none; conditional: none
- codex — hot: none; conditional: none

### sdd-mechanic

- Launched by: sites `sdd-mechanic-implementation`
- Prompt: `sdd/implementer-prompt.md` (not measured)
- claude — hot: `agents/mechanic.md`; conditional: none
- codex — hot: none; conditional: none

### sdd-implementer

- Launched by: sites `sdd-nonmechanical-implementation`
- Prompt: `sdd/implementer-prompt.md` (not measured)
- claude — hot: `agents/implementer.md`; conditional: none
- codex — hot: none; conditional: none

### sdd-task-reviewer

- Launched by: sites `sdd-first-pass-task-review`
- Prompt: `sdd/task-reviewer-prompt.md` (not measured)
- claude — hot: `agents/reviewer.md`; conditional: none
- codex — hot: none; conditional: none

### sdd-task-rereviewer

- Launched by: sites `sdd-scoped-task-rereview`
- Prompt: `sdd/re-review-prompt.md` (not measured)
- claude — hot: `agents/reviewer-lite.md`; conditional: none
- codex — hot: none; conditional: none

### sdd-lane-verifier

- Launched by: sites `sdd-lane-task-verification`
- Prompt: `sdd/SKILL.md` (not measured)
- claude — hot: `agents/reviewer-lite.md`; conditional: none
- codex — hot: none; conditional: none

### sdd-fix-implementer

- Launched by: sites `sdd-post-rescue-implementation`, `sdd-rescue-fallback-implementation`, `sdd-round-five-implementation`
- Prompt: `sdd/fix-loop.md` (not measured)
- claude — hot: `agents/implementer.md`; conditional: none
- codex — hot: none; conditional: none

### sdd-fix-escalation-reviewer

- Launched by: sites `sdd-task-rereview-escalation`
- Prompt: `sdd/fix-loop.md` (not measured)
- claude — hot: `agents/reviewer.md`; conditional: none
- codex — hot: none; conditional: none

### sdd-conformance-reviewer

- Launched by: sites `sdd-final-conformance-review`
- Prompt: `sdd/conformance-reviewer-prompt.md` (not measured)
- claude — hot: `agents/reviewer.md`; conditional: none
- codex — hot: none; conditional: none

### sdd-correctness-reviewer

- Launched by: sites `sdd-final-correctness-review`
- Prompt: `sdd/correctness-reviewer-prompt.md` (not measured)
- claude — hot: `agents/reviewer.md`; conditional: none
- codex — hot: none; conditional: none

### sdd-final-fixer

- Launched by: sites `sdd-final-review-fixer`
- Prompt: `sdd/final-review.md` (not measured)
- claude — hot: `agents/implementer.md`; conditional: none
- codex — hot: none; conditional: none

### sdd-final-rereviewer

- Launched by: sites `sdd-final-conformance-rereview`, `sdd-final-correctness-rereview`
- Prompt: `sdd/final-review.md` (not measured)
- claude — hot: `agents/reviewer-lite.md`; conditional: none
- codex — hot: none; conditional: none

### sdd-final-escalation-reviewer

- Launched by: sites `sdd-final-rereview-escalation`
- Prompt: `sdd/final-review.md` (not measured)
- claude — hot: `agents/reviewer.md`; conditional: none
- codex — hot: none; conditional: none

### ship-issue-reviewer

- Launched by: sites `ship-issue-merge-delta-review`, `ship-issue-full-conformance-review`, `ship-issue-full-correctness-fallback`
- Prompt: `ship-issue/SKILL.md` (not measured)
- claude — hot: `agents/reviewer.md`; conditional: none
- codex — hot: none; conditional: none

### ship-issue-rereviewer

- Launched by: sites `ship-issue-scoped-fix-rereview`
- Prompt: `ship-issue/SKILL.md` (not measured)
- claude — hot: `agents/reviewer-lite.md`; conditional: none
- codex — hot: none; conditional: none
