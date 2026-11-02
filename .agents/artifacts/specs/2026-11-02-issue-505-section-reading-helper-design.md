# Section-reading helper; the from-issue resume reads SKILL.md by section — issue 505

Design for https://github.com/fagenorn/nix-config/issues/505 (parent
https://github.com/fagenorn/nix-config/issues/448). A bare "Dn" cites this spec's ledger; "#448 Dn"
cites the parent spec `2026-10-26-issue-448-slim-owner-boot-design.md`. Base: `328f08da`
(origin/main). Siblings that own adjacent scope: https://github.com/fagenorn/nix-config/issues/506
(AUTO.md and ship-handoff.md by section, through this helper),
https://github.com/fagenorn/nix-config/issues/507 (sdd and plan root by section) and
https://github.com/fagenorn/nix-config/issues/504 (the boot report).

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "adds a new agent_tools CLI command (public interface) and changes the from-issue resume entry contract"}, "concurrency_or_persistence": {"value": "no", "evidence": "read-only text helper; no locking, ledger or persisted state touched"}, "open_design_questions": {"value": "doubt", "evidence": "command name/CLI shape and exactly which Phase 2-5-only dispatch clauses move are not fixed by the issue"}, "criteria_shape": {"value": "hit", "evidence": "one acceptance criterion is a 7-day post-deploy token measurement no deterministic code check verifies"}}, "paths": ["python/agent_tools/skill_sections.py", "lib/agent-tools.nix", "home/common/agent-skills/skills/from-issue/SKILL.md", "home/common/agent-skills/skills/from-issue/resume-pack.md", "home/common/agent-skills/tests/test_workflow_skill_contracts.py", "tests/test_skill_sections.py", "python/README.md"]}
Verdict: {"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

#448's cut 2 told a relaunched owner with a verified resume pack to "Read `SKILL.md` through
`## Files beside this one`, then only the sections that index names for your phase". No tool the
owner has can do that. The Read tool reads by line range, not by heading, so owners grep the
headings and then read all 30.6k bytes of from-issue's `SKILL.md`, or `sed` most of it. The
2026-11-01 reading on #448 measured the result: Phase 6–7 skill bodies fell from 10.6k to 2.2k
tokens per fresh boot, and `SKILL.md` read as a skill file rose from 0 to 8.1k. The cut saved
about nothing.

The always-read `## Dispatch, phase-budget and attempt-budget rules` section (10,065 bytes) also
carries clauses that only Phases 2–4 use. Every relaunched owner reads them, the Phase 6–7 owners
included, although those owners never receive a producer report.

## Solution

1. **`skill-sections`**, a new `agent_tools` command. It prints only the named `##` sections of a
   Markdown file, in file order, and prints the file's opening when asked. It fails, printing
   nothing, on any name it cannot resolve to exactly one heading (D1–D3).
2. **The resume entry runs it.** `resume-pack.md` replaces its reading sentence with the helper's
   argv. The first call prints `SKILL.md`'s opening and index, and a second call prints the
   sections the index names for the owner's phase. A rollover owner's check-2 index read uses the
   same first call (D4, D5).
3. **The Phase 2–4 clauses leave the always-read section.** The artifact report boundary and the
   implementation-plan projection confirmation move into a new `## Producer reports` section
   before `## Phase 2`, and the index names that section for Phases 2–4 (D6).
4. **No raise.** The index names short handles that the helper resolves, and the bytes this saves
   pay for the entry's growth, so the instruction corpus does not grow (D7).

## Decisions

### The helper (per D1–D3)

- **Interface.** `skill-sections [--opening] <file> <section>...` takes at least one section name.
  Its module is `agent_tools.skill_sections`, a row in the command table, a thin argv shell over
  importable functions: one parses a document into its opening and its ordered `##` sections, one
  resolves names to sections. The launcher installs as `~/.agents/bin/skill-sections`.
- **Structure.** A section runs from its `## ` heading line up to the next level-1 or level-2
  heading, or to the end of the file. `###` and deeper headings stay inside their section. A
  heading counts only outside a fenced code block: a fence opens on a line indented at most three
  spaces that starts with three or more backticks or tildes, and closes on a line of the same
  character at least as long, with only whitespace after it. A fence left unclosed runs to the end
  of the file. A heading's text is the line after `## `, stripped of surrounding whitespace. The
  opening is everything before the first `##` heading, frontmatter included.
- **Resolution.** A name selects the heading whose text equals it. Failing that, it selects the
  one heading whose text starts with the name followed by a character that is not a letter or
  digit, so `Phase 6` selects `Phase 6 — Execute`, and never `Phase 60`. A name that matches no
  heading is unknown. A name whose exact match is not unique, or which has no exact match and
  more than one prefix match, is ambiguous.
- **Output.** All names are resolved before anything is printed. On success the command writes, to
  stdout, the opening (with `--opening`) and then each selected section's bytes unchanged, in file
  order. A section is printed once, however often or in whatever order it was named. It exits 0.
- **Failure.** An unknown or ambiguous name, an unreadable or non-UTF-8 file, or a usage error
  exits 2 with nothing on stdout. One stderr report names every unresolved name, says whether it
  is unknown or ambiguous (with the candidates), and lists the file's `##` headings in order, so
  the caller can correct the call without reading the file.
- **Contract home.** `python/README.md` gains a `## skill-sections` section with this contract.
  `home/common/agent-skills/README.md`'s resume-pack paragraph says the owner prints `SKILL.md`'s
  index and sections through `skill-sections`.

### The resume entry (per D4, D5)

- **Reading rule.** The sentence that tells the owner to read `SKILL.md` through the index
  becomes: print `SKILL.md`'s opening and index with
  `skill-sections --opening <from-issue-dir>/SKILL.md 'Files beside this one'`, then, the same
  way, only the sections that index names for your phase, and start from `next_action`.
  `<from-issue-dir>` is the directory of the entry the prompt names, as in `### Resume pack`.
- **Check 2.** A Phase-5 rollover owner needs the index before its delegated-owner checks. Check 2
  points it at the same helper call, so no whole-file read remains anywhere in a verified-pack
  path. The order is unchanged: checks 1–3 come before the reading rule, and a failed check still
  loads the whole skill through the Skill tool.
- **Index handles.** The index's `resume-pack.md` line keeps the read list, as #448 D7 placed it,
  and names each section by a handle the helper resolves: `Lifecycle identity`,
  `Decision ledger`, `Skill-tool`, `Dispatch`, `Terminal return`, `Suspension`, then
  `Producer reports` in Phases 2–4, then `Phase <n>`, then the file the index names for that phase
  and the phase's sub-skill. The handles never use the em dash in the phase headings.
- **Unchanged.** The other index lines (`AUTO.md`, `delegated-owner.md`, `ship-handoff.md`), the
  Skill-tool rule, the pack's JSON and `workflow-state` stay as they are.

### The clause move (per D6)

Each paragraph of the dispatch section, judged by its own text:

| Paragraph | Used in | Disposition |
|---|---|---|
| Structured report-backs, Leaf-agent clauses | every `Agent` dispatch, Phases 2–7 | stays |
| Writing workers, Self-reap, Interim child results | Phase 2–4 subagents, sdd's writers, the Phase-7 ship owner, every exit | stays |
| Artifact report boundary | producer reports: AUTO.md's design and plan subagents, or the inline `design`, `grill-with-docs` and `writing-plans` | moves |
| `implementation-plan` projection confirmation | the Phase-4 plan report; Phase 5's caller input gate repeats its own check | moves |
| Decomposition stop | Phase 4's projection, and Phase 6's sdd `decompose_required` | stays |
| Executable phase gate and its actions, the route note, the deadline rejection | every phase boundary | stays |

The two moving paragraphs (1,199 bytes) form `## Producer reports`, placed between
`## Phase 1 — Worktree` and `## Phase 2 — Brainstorm`. The heading replaces the bold
`Artifact report boundary.` lead-in, and the text is otherwise verbatim. The Decomposition stop it
cites stays in the always-read section. The issue says "Phase 2–5"; Phase 5 reads
`standards-review.md`, whose caller input gate validates the plan report itself, so the section is
named for Phases 2–4 only.

### Instruction budget (per D7)

Measured at `328f08da`: the corpus is 403,959 bytes against a 403,959 ceiling, so it has no
headroom. Headroom per profile: from-issue-controller has 26 bytes hot and 99 conditional on each
host; orchestrated-issue-owner has 498 hot and 179 conditional; implementation-owner has 50 hot
and 129 conditional. `SKILL.md` (30,603 bytes) is hot in all three profiles, and the planning and
execution contract tests cap it at 30,611. `resume-pack.md` (1,785 bytes) is conditional in all
three. The change therefore holds:

- the corpus does not grow: `resume-pack.md`'s growth is at most `SKILL.md`'s shrinkage;
- `resume-pack.md` grows by at most 99 bytes;
- `SKILL.md` does not grow.

A measured candidate satisfies all three: the handle index line saves 80 bytes, the heading swap
saves 9 more, and the entry's reading rule plus check 2's pointer add 84, so the corpus falls 5
bytes. No ceiling is raised. `tighten` is needed only if a ceiling ends more than 5% above its
measure, and none comes close.

## Test seams

1. **The CLI** (`tests/test_skill_sections.py`, added to `just agent-workflow-tests`). It runs
   `python -m agent_tools.skill_sections` from source, as agent-helpers rule 5 asks, over fixture
   documents shaped like real skill files: frontmatter, `###` subsections, and fenced blocks
   holding `##` lines under both backtick and tilde fences. It imports the parse and resolve
   functions for structural cases. Prior art: `tests/test_lane_triage.py`. Tests assert:
   - the output equals the named sections' source slices, concatenated in file order, whatever the
     argument order or repetition; `--opening` prepends the text before the first `##`;
   - `##` inside a fence never splits a section, `###` stays inside it, and `#` ends it;
   - `Phase 6` resolves to `Phase 6 — Execute` and not to `Phase 60`; an exact match wins over a
     prefix match; two prefix matches are ambiguous;
   - unknown and ambiguous names, a missing file and no section exit 2 with empty stdout, and
     stderr names each unresolved name and lists the headings.
2. **The skill-text contracts** (`test_workflow_skill_contracts.py`, `SlimBootContractsTest`).
   They pin identifiers only, under agent-helpers rule 6 and #448 D20:
   - every backticked section span on the verified-pack read lines resolves to exactly one heading
     through `agent_tools.skill_sections` against its document. This replaces the heading-equality
     check, so a renamed heading that breaks a handle fails it;
   - `Phase <n>` resolves for every phase from 0 to 7, and `Producer reports` is named;
   - `resume-pack.md` carries the `skill-sections --opening <from-issue-dir>/SKILL.md 'Files beside
     this one'` argv after its check-3 anchors. This replaces the `## Files beside this one`
     anchor, in the same commit;
   - the dispatch section holds neither `--boundary producer` nor `review-feasibility confirm`,
     and `## Producer reports` holds both. The existing `PROJECTION_MACHINE_TEXT` and Phase 6 pins
     still hold.
3. **Shell-example vetting.** `skill-sections` joins `COMMAND_VOCABULARY` in
   `test_shell_example_contracts.py`, so the entry's argv is checked as a single plain command.
4. **Build and gate.** `just build` import-checks the module and asserts the command-table row,
   and `just agent-instruction-budget` passes without the raise label.

## Out of scope

- Reading `AUTO.md` or `ship-handoff.md` by section, and moving `ship-handoff.md` reads to Phase 7
  (#506). Reading sdd or a plan root by section (#507). Boot-report reweighting and medians
  (#504).
- `delegated-owner.md` section reads. The index already names the section, and the issue does not
  ask for it.
- Section levels other than `##`, a `--through` range, a heading list mode, locating a skill by
  name, and stripping frontmatter.
- The resume pack's JSON, its byte bound and `workflow-state` (no risk-path edit). The issue's
  "text moved into the resume pack" bound is respected by moving none.
- A permission allow-list entry. The allow list holds only the ledger-writing lifecycle helpers,
  and read-only helpers such as `lane-triage` run under `defaultMode = "auto"` without one.
- Refactoring `skill_lint`'s own fence toggle onto the new parser.
- The `[evidence]` criterion: mean from-issue `SKILL.md` tokens per fresh boot at most 4k, over the
  7 days after the first `just switch` that includes this change. It is measured after deploy with
  `just agent-costs --report boot`. This design adds no measurement code, and ship handles the open
  evidence row as #448 D12's hold did.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | One command, `skill-sections [--opening] <file> <section>...`: module `agent_tools.skill_sections`, a command-table row, a thin shell over a parse function and a resolve function. It takes the file by path. The opening prints only with `--opening`. | agent-helpers rules 1–2; the issue ("prints only the named `##` sections of a skill file"); the index's own word "the opening" (AUTO.md line); the entry prompt already holds the absolute `<from-issue-dir>` | `md-sections`/`doc-sections`: they name the syntax, not the use, and no caller outside skills is approved (#507 is human-gated). Repeated `--section` flags: more tokens per call. Locating the skill by name: it couples the helper to two hosts' install layouts. Always printing the opening: the second call would repeat 1,198 bytes, and the output would no longer be exactly the named sections |
| D2 | A name selects its exact heading, or else the one heading it prefixes at a non-alphanumeric boundary (`Phase 6` → `Phase 6 — Execute`). Unknown or ambiguous names exit 2 with empty stdout, and one stderr report lists every unresolved name and the file's `##` headings. | the-bar Token economy (short stable handles; forms a model emits reliably — the phase headings carry an em dash); the-bar Fail loud; AC "fails clearly on an unknown heading" | Exact match only: owners would have to spell `Phase 6 — Execute`, and the index would grow by the full phase titles. Case-insensitive or fuzzy matching: a typo could resolve silently to the wrong section. A `--list` mode: an extra call and parameter, when the error output already lists the headings |
| D3 | A section runs to the next `#`/`##` heading outside a fenced block (backtick or tilde fences, closed by the same character at least as long, unclosed to the end of the file). `###` stays inside. The output is the selected byte slices verbatim, in file order, each once, and nothing is printed until every name resolves. | design, wayfind, writing-plans, ship-issue, ship-release and grill-with-docs files hold `##` lines inside fences; AC "in file order"; the-bar Truthful terminal states (no partial output on exit 2) | A plain `## ` line scan: it would split template headings out of prompts. Reusing `skill_lint`'s toggle: it knows only backticks and no closing-length rule, and it is private to lint L3. Printing in argument order: the AC says file order |
| D4 | Only the resume entry names the helper: its reading rule, and check 2's index read for the rollover owner. The other index read lines, the Skill-tool rule and the allow list are unchanged. | Issue scope ("the from-issue resume entry uses it"); #506 owns AUTO.md and ship-handoff.md; check 2 already sends the rollover owner to the index (commit 314fe8dc), so leaving it out would keep one whole-file read | Converting `delegated-owner.md` reads as well: not in the issue, and the index already narrows them. Naming the helper in the index line: it costs hot bytes, and only the entry's readers use it. A `Bash(skill-sections:*)` allow entry: the allow list holds only ledger-writing lifecycle helpers, and `lane-triage` runs without one |
| D5 | Two calls: `--opening` with `Files beside this one`, then the handles the index names for the phase. The read list stays in the index, which names short handles (`Decision ledger`, `Skill-tool`, `Dispatch`, `Terminal return`, `Suspension`, `Phase <n>`). | #448 D7 (the read list stays in the index; moving it breaches the controller's conditional ceiling); the corpus has 0 bytes of headroom; D2 makes the handles resolvable | One call with the whole list in the entry: about 250 bytes would move into a conditional member that has 99 bytes of headroom. Keeping the full heading texts in the index: the entry's growth would then have nothing to offset it |
| D6 | Only the Artifact report boundary and the `implementation-plan` projection confirmation are Phase 2–4-only. They move verbatim into a new `## Producer reports` section before `## Phase 2`, under a heading that replaces the bold lead-in, and the index names it for Phases 2–4. Every other dispatch paragraph stays, the Decomposition stop included. | Each clause's text: producer reports arrive only from Phases 2–4 (AUTO.md's subagents, or the inline `design`/`grill-with-docs`/`writing-plans`); `standards-review.md`'s caller input gate re-validates the plan report at Phase 5; Phase 6 takes the Decomposition stop | Splitting the paragraphs across the Phase 2/3/4 sections: a Phase-3 or Phase-4 owner would also have to read Phase 2's section, or the text would be duplicated. AUTO.md's `Phases 2–4 run as subagents`: it is read only with `--auto`, durable interactive owners receive producer reports too, and AUTO.md is #506's file. Naming the section for Phases 2–5: Phase 5 never uses it |
| D7 | Budget: the corpus does not grow, `resume-pack.md` grows by at most 99 bytes, and `SKILL.md` does not grow. The handle index line pays for the entry; no ceiling is raised and no other file is trimmed. | Issue and #448 decisions (no raise; byte-neutral move); the measured `328f08da` headroom; the `SKILL.md` size pins in the planning and execution contract tests | Raising the corpus or a conditional ceiling: forbidden without the label. Trimming AUTO.md or ship-handoff.md for bytes: #506's files |
| D8 | Seams: CLI tests from source; contract pins that every verified-pack section span resolves through `agent_tools.skill_sections` (replacing heading equality), `Phase 0`–`Phase 7` resolve, the entry's argv follows its checks, and the dispatch section lost the `--boundary producer` and `review-feasibility confirm` argv to `## Producer reports`; `skill-sections` joins the shell-example vocabulary. | agent-helpers rules 5–6 (argv, identifiers and vetted shell examples only); #448 D20 and D23 (identifier pins); the-bar Tests that can fail (a renamed heading turns the resolution pin red) | English pins on the entry's sentences: rule 6 forbids them. Adding the command to `LAUNCHER_FLOOR`: it is a floor, and `just build`'s import check plus the table assertion already prove the launcher |
