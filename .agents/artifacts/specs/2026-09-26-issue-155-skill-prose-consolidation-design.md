# Skill prose consolidation and the instruction-load baseline — issue 155

Design for [#155](https://github.com/fagenorn/nix-config/issues/155), the third
slice of [#99](https://github.com/fagenorn/nix-config/issues/99), 2026-09-26.
Siblings: [#153](https://github.com/fagenorn/nix-config/issues/153) (dispatch
contracts, [PR #166](https://github.com/fagenorn/nix-config/pull/166)),
[#154](https://github.com/fagenorn/nix-config/issues/154) (shell forms,
[PR #187](https://github.com/fagenorn/nix-config/pull/187)),
[#100](https://github.com/fagenorn/nix-config/issues/100) (strict resolver). Base:
`origin/main` at `affa05e`. Decisions D1–D15 bind the plan; the grill added D16–D21.

## Problem

The #99 audit counted four recurring agent error classes whose total is 417
(119 + 64 + 37 + 197). The number counts error turns; it is not an HTTP status and
not a provider or transport failure. #153 and #154 fixed three of the classes by
adding text to shared skills, and #100's strict resolver retired the fourth. Both
slices deferred prose growth to this one.

Two things are still missing.

- **One authoritative explanation per corrected rule.** A rule stated twice, where
  only one copy is held by a test, drifts the first time someone edits the other.
  The retrospective's instruction is "keep one authoritative explanation of each
  rule" ([§4](2026-09-19-agent-harness-retrospective.md)).
- **Knowing what each role loads.** The only size evidence so far is whitespace word
  counts of root `SKILL.md` files ([session cases §8](2026-09-19-harness-session-cases.md)),
  which say nothing about the members a design owner, an implementation owner or a
  ship owner actually reads, on Claude or on Codex. Without that, a slice can grow a
  leaf's hot path and nobody sees it. The issue forbids claiming savings from word
  counts alone.

Measured at `affa05e`: a repeated-sentence scan of both source skill trees finds
most repetition *held on purpose* — per-entry copies each asserted against one test
constant, because every entry can be the first thing a fresh session loads. The
un-held restatements are few and small. The biggest block a leaf loads without
using is not repetition at all: from-issue's top-level-only acquisition routes.

## Solution

### The corrected rules and their homes (D1)

| #99 class | Rule now | Authoritative home | Surfaces that derive from it | This slice |
|---|---|---|---|---|
| 119 named launches | launch by type only | `CONTRACTS["launch-by-type"]` in `test_dispatch_contracts.py` | nine carriers verbatim (six fenced templates, the orchestrate-issues issue-owner blockquote, the from-issue and sdd composition rules); `AUTO.md`'s pointer bullet | guard against un-enrolled copies (D3) |
| 64 write-before-read | read an existing file first | `CONTRACTS["read-before-write"]` | the same nine carriers | same guard |
| 37 config probes | retired by #100: resolve once, fail closed | `RESOLUTION_SENTENCE` and `REFUSAL_REPORTING_SENTENCE` in `test_workflow_skill_contracts.py` | 13 policy entries (11 shared, 2 Claude-only) | remove each entry's un-held restatement (E1) |
| 197 shell forms | one plain command per call | `worktrees/SKILL.md` `## Shell forms the isolation checker refuses` | sanctioned prefix derived from `lifecycle_guard.py`; sanctioned lifecycle call spelled by from-issue's lifecycle-call rule and held in three entries by `STDIN_CLAUSE` | `ship-release` names the home instead of restating the reason (E4) |

A clause is its own explanation: the text after its colon is the rationale, so the
leaf-clause rules have one explanation already, copied where a link cannot reach.

### Consolidation edits (D2)

A restatement is removed only when it is un-held — no test asserts it — and a held statement of
the same rule sits in the same member, or in a member that every route loading it
also loads. Four edits qualify; nothing else is cut.

- **E1 — resolver restatement, 13 entries.** Each policy entry opens with "Run
  `resolve-project resolve --repo-root <checkout>` once at phase entry and retain the
  full `ResolvedProject` in memory" and then states the held `RESOLUTION_SENTENCE`,
  which says the same thing. The first sentence shrinks to naming the command ("Run
  `resolve-project resolve --repo-root <checkout>`.", writing-plans keeping its own
  placeholder); the held sentences, bindings and exceptions stay word for word. About
  12 words (≈70 bytes) per entry.
- **E2 — `workflow-state` PATH fallback, two entries.** `from-issue/SKILL.md` and
  `orchestrate-issues/SKILL.md` each state the fallback twice: once in the
  lifecycle-call rule ("the helper named bare or as `~/.agents/bin/workflow-state`")
  and again as a standalone sentence. The condition folds into the lifecycle-call
  rule ("named bare, or as `~/.agents/bin/workflow-state` when the bare name does not
  resolve on PATH") and the standalone sentence goes. ship-issue states it once and is
  untouched.
- **E3 — direct-acquisition flags in `AUTO.md`.** Its opening paragraph restates
  `SKILL.md`'s `new_run`/`owner_unavailable` rule, and every route that loads
  `AUTO.md` also loads `SKILL.md`. The restatement goes; the sentence that only
  `AUTO.md` carries — a resume is not a takeover, both flags stay `false` — stays,
  anchored to direct autonomous acquisition. About 60 words.
- **E4 — shell-form pointer in `ship-release`.** Phase 2 justifies `--body-file` by
  restating that "a heredoc into `gh` is refused by the worktree isolation checker";
  it names `worktrees/SKILL.md`'s shell-form section instead.

Each edit changes no behavior: every sentence a test asserts, every binding, path and
flag survives; one test delimiter moves (D20).

Expected effect, from a prototype of the roster below at `affa05e`: the from-issue
controller's hot path is ≈97 KB on Claude and ≈87 KB on Codex, the implementation
owner's ≈131 KB, the ship owner's ≈53 KB, the design-and-grill owner's ≈28 KB, the
planning owner's ≈22 KB. E1–E3 take roughly 0.2–1 KB from each owner, under 1 % of its
hot path; template-driven leaves do not move. The generated report is authoritative,
and D5 and D6 say why the rest stays.

### What stays repeated, and why (D5, D6)

The report's notes carry these as the preserved behavior behind every unchanged or
barely-changed total.

| Repeated block | Where | Held by | Why it stays |
|---|---|---|---|
| resolver and refusal sentences | 13 entries | #100's policy-entry assertions | each entry can be a fresh session's first load |
| the two leaf clauses | 9 carriers | #153's `CONTRACTS` | a pasted or composed prompt is the only skill text that reaches a leaf on both hosts |
| producer-report candidate clause, budget and return sections (≈4.2 KB in design, ≈3.6 KB in grill) | design, grill-with-docs, writing-plans, handoff | `REPORT_CANDIDATE_CLAUSE` and the producer-report assertions | each producer runs standalone |
| lifecycle stdin clause | from-issue, ship-issue, orchestrate-issues | #171's `STDIN_CLAUSE` | each entry issues lifecycle calls on its own |
| explorer escalation sentence | design, grill, writing-plans, doc-grounded, research | #98's `test_cheap_tier_escalation_…` | model routing is #98's contract |
| the authorization-carry and denial rule | from-issue's checkpoint rule and notes, `AUTO.md`'s two `human_gate` gates | `AUTO.md`'s exact `human_gate` count | the authorization contract pins its shape |

The largest leaf-irrelevant block is not repeated: from-issue's direct autonomous and
explicit durable acquisition routes (≈8.9 KB, 1,104 words) are read by every leaf
that loads `SKILL.md` — the orchestrated issue owner and the implementation owner —
though only a top-level controller runs them, and `AUTO.md`'s rollover (≈8.5 KB) is
read by the orchestrated issue owner, whose route never takes it. Moving them into a
route-scoped sibling is the next reduction lever, deferred with its measured size
(D6).

### The instruction-load model (D7, D8, D11, D16, D18)

**Terms.** A **profile** is one group of dispatch sites from `model-matrix.json` that
share a prompt source, an agent definition and a member list, or a top-level entry
the user invokes; it is what the issue calls a role, renamed because the matrix's
`role` field already names the tier vocabulary (`issue-owner`, `reviewer`, …). A
**member** is a document the profile reads itself. It is **hot** when the profile's
instructions direct it there on every run of its standard route, and **conditional**
when only a named branch does: a capability or availability condition, a failure or
fix loop, a missing grant, a fallback, a "for details" pointer, or output produced
only on that branch. Ambiguous means hot, so a misclassification overstates the hot
path rather than hiding growth. A profile's **received prompt** is annotated by its
source document and not measured (D8); every prompt source is itself a member of the
composing profile that reads it. The **frame** is the global guidance file
(`~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`, one source), reported once and kept
out of profile totals; which subagent types a host hands it to is host behavior this
repository neither controls nor asserts. The **hot entry surface** is the set of hot
totals, one per profile and host.

**File.** `home/common/agent-skills/instruction-load.json`, repository data beside
`model-matrix.json`, never installed. Top-level keys, closed: `frame`, `profiles`,
`excluded_sites`. A profile has exactly `id`, one of `entry` (a skill name) or
`launch` (a non-empty list of dispatch-site ids), `hosts` (a subset of `claude`,
`codex`), `prompt` (a member-spelled document, or null for an entry), `hot`,
`conditional`, `unread` (a map from member to reason, possibly empty),
`ceiling_bytes` (one integer per listed host) and `note` (non-empty).
`excluded_sites` maps a site id to a non-empty reason.

**Member spelling.** `<skill>/<file>` resolves to exactly one document in the shared
tree or the Claude-only tree; `agents/<name>.md` is a Claude agent definition;
`agent-guidance/AGENTS.md` is the frame. Host counting derives from the source tree: a
Claude-only-tree member or an agent definition counts only toward the Claude total,
everything else toward both. Nix installs no agent definition for Codex, so a typed
dispatch counts none there.

**Roster.** The pipeline rows below fix the profile set the #99 audit exercised. The
remaining matrix sites group under the same rule (by prompt source and agent
definition); the plan enumerates them and every member under the rules above, and the
completeness check enforces the result.

| Profile | Launched by | Hosts | Prompt source | Standard route |
|---|---|---|---|---|
| from-issue controller | entry `from-issue` | claude, codex | — | direct autonomous `--auto`, Phases 0–5 and rollover |
| orchestration dispatcher | entry `orchestrate-issues` | claude | — | one run |
| orchestrated issue owner | `orchestration-issue-owner` | claude | `orchestrate-issues/SKILL.md` | dispatcher-owned, Phases 0–7 |
| design-and-grill owner | `from-issue-design-grill` | claude, codex | `from-issue/AUTO.md` | Phases 2–3 |
| planning owner | `from-issue-planning` | claude, codex | `from-issue/AUTO.md` | Phase 4 |
| implementation owner | `from-issue-phase-delegate` | claude, codex | `from-issue/AUTO.md` | post-rollover Phases 6–7 |
| ship owner | `from-issue-ship-owner` | claude, codex | `from-issue/ship-handoff.md` | implementation custody |
| sdd implementer, reviewers, bookkeeper, mechanics, explorer | their matrix sites | claude, codex | their template or composer | one dispatch |
| release owner, researcher, architecture scan owner | their matrix sites | claude, codex | their skill | one dispatch |
| research, wayfind, to-issues, ship-release | entries | claude, codex | — | one run |

The four standalone entries are the policy entries E1 edits whose standalone run no
pipeline profile already covers; a standalone run of a pipeline skill reads what its
pipeline profile reads. `sdd-codex-rescue-transport` is excluded: a plugin agent that
reads plugin documents outside the source trees. The Codex `orchestrate-issues` stub
is not a profile: Codex declares that route unsupported.

**Validation, fail loud.** `validate(model, read)` returns ordered violations, empty
when the model is sound:

- unknown or missing keys, duplicate keys (the `agent_tools.canonical` hook), duplicate
  profile ids, a member listed twice in one profile (across `hot`, `conditional` and
  `unread`), `ceiling_bytes` hosts differing from `hosts`, an empty `note` or reason;
- a member that resolves to no document or to two;
- **completeness** — every `dispatch_sites[].id` of `model-matrix.json`, read through
  `agent_model_matrix.load_matrix`, sits in exactly one profile's `launch` or in
  `excluded_sites`, and no unknown id appears;
- **reachability** — every hot or conditional member except an entry profile's own
  `SKILL.md` is named in the profile's prompt source or in another of its members: as
  `<skill>/<file>`, by basename from a document of the same skill, or as
  `` `<skill>` `` for a `SKILL.md`; an agent definition is named by a launch site's
  `subagent_type`;
- **closure** — every `*.md` document of a member's own skill that the member names by
  basename is listed in that profile as hot, conditional or `unread`, so text moved
  into a sibling cannot leave the count (D18).

### Measurement, the command and the report (D9, D14, D17)

For each member, **bytes** are the UTF-8 length and **words** the count of
whitespace-separated tokens, the prior audits' unit. A profile and host's hot total
sums the hot members counted for that host; the conditional total likewise. Neither
figure is a token count, and the report says so. `measure(model, read)` computes both
through a reader `read(path) → bytes | None`: one reader serves the working tree, one
serves a revision.

`agent_tools.instruction_load` is a package module with no command-table row, run by a
new recipe the way `agent-costs` runs its module:

```text
just agent-instruction-load report --base <rev> --head <rev> --output <path>
```

It reads the model and the matrix at `--head` and every member at each revision with
`git show <rev>:<path>` (a member absent at a revision measures zero and is marked
absent), validates the model at `--head`, and writes Markdown to `--output`, or to
stdout when omitted; `--format json` emits the same data. The output is therefore a
function of the two SHAs alone. `--output` exists because the worktree checker refuses
a redirect. An unknown revision, an invalid model or a git failure exits 2 with one
stderr line and writes no file.

The Markdown carries: a header with both full SHAs, the regeneration command, what is
measured and what is not (received prompts, the harness system prompt and skill
listing, project instructions, plugin and generated skills); the frame; a table of hot
totals, one row per profile and host, with base and head bytes and words, their
deltas, an affected mark (any member changed) and the profile's `note`; the same for
conditional totals; a per-document table; and each profile's member lists per host
with its prompt source and its `unread` entries.

**The committed report** is a point-in-time record at
`<bindings.paths.artifacts.specs>/<generation-date>-issue-155-instruction-load-report.md`,
generated after the last content change with base `git merge-base HEAD origin/main`
and head `HEAD`, then committed alone, so its head is that commit's parent and
`git diff <head> HEAD` touches only the report. A later sync that changes a measured
member regenerates it (D19).

### The ceiling (D10, D19)

Each profile and host's hot bytes must not exceed its `ceiling_bytes`, set to the
post-#155 measured values. A change that grows a hot path past its ceiling raises the
ceiling and rewrites that profile's `note` to say why, in the same commit; reviewers
see the reason in the diff. Shrinking needs no edit. The failure names the profile,
the host, both numbers and each hot member's bytes.

Until this slice lands, growth merged from `origin/main` predates the gate: a sync that
changes a measured member re-measures, sets the affected ceilings to the merged
values with a note naming the merge commit, and regenerates the report. Once the slice
is on `main`, every other branch meets the gate as written.

### Guards (D3, D13)

- **Leaf clauses** (#153's module): every occurrence of either clause, matched with the
  module's wrapping-tolerant pattern, in any living `*.md` of either source tree outside
  `evals/`, in a Claude agent definition or in the global guidance file, lies inside an
  enrolled carrier's rendered region. A copy anywhere else is not held against the
  constant and fails — including the standing rule D4 rejects (D21).
- **Resolver** (#100's `assert_policy_entries`): each policy entry states
  "`ResolvedProject` in memory" exactly once.
- **Shell forms** (#154's module): every living document other than
  `worktrees/SKILL.md` that mentions the isolation checker names `worktrees/SKILL.md`.
  A paraphrase that avoids the term is outside its reach, a named limitation.

## Decisions

- Modules touched: 14 skill documents in both source trees — the 13 policy entries
  (E1; from-issue and orchestrate-issues also take E2, ship-release E4) and `AUTO.md`
  (E3);
  `test_dispatch_contracts.py`, `test_shell_example_contracts.py` and
  `test_workflow_skill_contracts.py` gain one guard each, and E2 moves one end anchor
  in the last (D20); new
  `agent_tools.instruction_load`, `instruction-load.json`, `test_instruction_load.py`
  (registered in `agent-workflow-tests`) and the `agent-instruction-load` recipe; one
  generated report. No `.nix` file: `lib/agent-tools.nix` import-checks every module it
  finds.
- Interface, one reader seam throughout (D17): `load_model(data)`,
  `validate(model, read)` → ordered violations, `measure(model, read)` → per-member and
  per-profile-and-host totals, `over_ceiling(model, measurement)` → breaches, for any
  `read(path) → bytes | None`; command `report --base --head [--output]
  [--format markdown|json] [--root]`.
- Behavior: no skill semantics change. E1–E4 keep every sentence a test asserts; the
  guards and the ceiling add failure modes only.

## Test seams

1. **`test_instruction_load.py`**, through the module's public functions and command,
   following `test_agent_model_matrix.py`:
   - the live model validates clean;
   - mutations of the live model each yield exactly their violation: a matrix site
     dropped, an unknown member, an ambiguous member, an unnamed member, a named sibling
     left unlisted, an unknown key, a duplicate profile id, a ceiling host missing, an
     empty note;
   - the live working tree breaches no ceiling; a reader over the live tree that grows
     one hot member by one byte breaches exactly the profiles and hosts that count it;
   - the command in a throwaway two-commit fixture repository (`GIT_CONFIG_GLOBAL`
     pointed at the null device, local signing off, the `test_sdd_workspace.py`
     precedent) reports hand-computed byte and word deltas in JSON, writes the
     Markdown file with both SHAs, reads its model at `--head` even when the working
     tree's model differs, and exits 2 with no file for an unknown revision.
2. **#153's module** — the stray-copy guard over both source trees, the agent
   definitions and the global guidance; live-text mutations: a clause appended to a
   non-carrier document, to a carrier outside its region, and to the global guidance,
   each fail naming that document.
3. **#154's module** — the pointer guard; mutation: `ship-release/SKILL.md` with the
   pointer removed fails.
4. **#100's helper** — mutation: an entry with the restatement restored raises, as
   `test_refusal_reporting_matrix_rejects_a_missing_clause` does for its clause.

The installed recipe is unchanged: #154's installed sweep already reads every source
document's copy in both views (D12).

## Acceptance criteria and verification

| Criterion | Satisfied by | Verified by |
|---|---|---|
| Each corrected #99 rule has one authoritative explanation; other surfaces derive or link | the homes table; E1, E4; the three guards | the guards and existing contract suites green |
| A fresh before/after report records bytes and words and the members loaded per affected role and host | the committed generated report, one row per profile and host | regenerating with its SHAs reproduces it byte for byte; every roster profile appears per host |
| The hot entry surface is smaller, or a no-growth result names the preserved behavior; unexplained growth fails | E1–E3 shrink the owners' hot paths; each unchanged profile's note names what holds it; the ceiling | the report's JSON has no positive hot delta and a negative one for every affected profile; the ceiling test |
| #153 and #154 suites green on source and installed trees | no carrier region or example changes | `just agent-workflow-tests`; `just agent-installed-skill-tests` with its installed classes run, not skipped |
| No unrelated content from the retained aggregate branch | nothing recovered (D15) | no `Recovered-From` trailer; the branch diff adds no `env -u GITHUB_TOKEN`, no `.claude/skills.config.json` guard, no retained spec, plan or task file; the tip of `worktree-issue-99-skill-prose-fixes` still `3c9709ca` |

Also: `just build` (import-checks the new module) and `just agent-model-matrix` pass.
Parent #99: the report is the fresh baseline, and nothing in this slice calls 417 a
provider or HTTP failure.

## Out of scope

- Route-scoping from-issue's top-level acquisition routes and `AUTO.md`'s rollover out
  of the leaf-loaded entry (D6): a follow-up, moving #171 and #181 lifecycle text their
  suites pin by section and file.
- Any change to a held repeated block (D5), to the leaf clauses or their carriers, to
  shell examples, to model routing (#98) or to helper behavior.
- The producer-report candidate clause's `mktemp`/`trap` prose, which describes a
  trap-based cleanup that one command per call cannot express, while `AUTO.md` and the
  `workflow-state` calls use stdin. Changing it changes the producer boundary in four
  skills; a follow-up.
- Measuring received prompt regions, the skill listing, project instructions, plugin or
  generated skills (D7, D8).
- Tokenizer counts or cost estimates (D14).
- `CLAUDE.md`, ADRs, context docs, `.nix` files and CI (D15).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The corrected rules' homes are the existing test constants (leaf clauses, resolver sentences) and `worktrees/SKILL.md`'s shell-form section; carriers, entries and sanctioned forms derive from them | #153 D4, #154 D5/D23/D30, #100's suite; the-bar DRY ("derives from it or links to it") | A new prose home (shared include or global guidance) — a second home beside the constants, and no surer to reach a leaf |
| D2 | Remove a restatement only when no test holds it and a held statement of the rule sits in the same member or in one every loading route also loads: E1–E4, nothing else | the-bar DRY; session cases §8 "keep invariants on the hot path; do not solve growth by silently weakening checks"; the `affa05e` scan | Cut every repeated block — deletes per-entry invariants other suites hold on purpose (D5); cut only #99-rule text — leaves E2's and E3's restatements on the same hot paths |
| D3 | Q2: the leaf clauses stay verbatim in all nine carriers; a guard fails on any copy outside an enrolled carrier's rendered region | #153 D1/D4/D6: a pasted or composed prompt is the only skill text that reaches a leaf; the region check passes today with a second copy outside the region | Replace copies with a pointer — it never reaches the leaf; no guard — an un-enrolled copy drifts unseen |
| D4 | Q4: no standing rule replaces the per-carrier copies, and the three residual sites stay non-carriers; they enter the load model as profiles | top-level sessions legitimately name their launches (this run's orchestrator addresses its owners by name), so a global rule would contradict them; Codex subagent loading of global guidance is unverified; #153 D1 found no attribution to those sites | Global-guidance rule — wrong at top level and paid by every session in every repo; agent-definition rule — Claude-only; three new carriers — ~270 words of unevidenced growth |
| D5 | Q5: the resolver paragraph stays in all 13 entries and only its restating opener goes (E1); every held repeated block is kept and named in the report as preserved behavior | each held copy is asserted per entry because each entry loads alone; changing them changes #100's, #153's, #171's, #98's or the authorization contract | Collapse per-entry copies into a pointer — a standalone invocation then loads no invariant |
| D6 | Route-scoping the top-level-only acquisition routes (≈8.9 KB) and the rollover (≈8.5 KB) out of the leaf-loaded from-issue entry is deferred to a follow-up, named with its measured size | the largest block a leaf loads unused, but #171/#181 text asserted by section and by file, merged at `affa05e`; prefer the smaller, reversible slice | Move it now — the widest blast radius in the tree, against in-flight lifecycle work |
| D7 | Q1: a profile is a matrix dispatch-site group or a top-level entry; members are documents the profile reads itself, hot on every run of its standard route, conditional on a named branch, ambiguous → hot; global guidance is the frame; project instructions, harness text, plugin and generated skills are excluded | issue: "the actual instruction members loaded per affected role and host"; `model-matrix.json` is the one home of dispatch sites | Root `SKILL.md` word counts — say nothing about a role's load; one row per site — 37 rows, most duplicates |
| D8 | Received prompts are annotated by source and not measured; each source is a member of its composer | #153's module is the one home of the rendered-region rule; no template changes here, so every delta stays exact | Port the renderer into the package — a second home, or a refactor of #153's suite and installed recipe; whole template bytes — `orchestrate-issues/SKILL.md` is 22 KB against a ~2 KB blockquote |
| D9 | Q3: the report is generated by `agent_tools.instruction_load` through `just agent-instruction-load` over a checked-in `instruction-load.json`, and committed alone as a point-in-time record in the specs directory, base the merge-base with `origin/main`, head its parent commit | agent-helpers rules 1–5; `agent_costs` (module plus recipe, no command row) and `model-matrix.json` precedents; the retrospective records live in the specs directory | Hand-written Markdown — not reproducible; a script in the tests tree — sidesteps the package rule; a command-table row — installs a repository-maintenance tool on every machine and edits `.nix` |
| D10 | A standing ceiling: each profile and host's hot bytes ≤ its `ceiling_bytes`, set to post-#155 values; raising one rewrites that profile's `note` in the same commit | retrospective §4 "hot-path instruction size does not grow without an explicit reason"; the issue's "unexplained growth fails" | Report only — growth stays invisible until the next audit; an exact-equality baseline — every skill edit touches the model and parallel branches conflict on it |
| D11 | The model validates fail-loud: closed schema, one-document resolution, tree-derived host counting, completeness against every matrix site (or a reasoned exclusion), and reachability of every member from the profile's prompt source or another member | the-bar Fail loud and Tests that can fail; `agent_model_matrix.validate` precedent; reachability ties a declared load to the prose that causes it | Unchecked declarations — a model can list files no instruction loads, and a new dispatch site goes untracked |
| D12 | No installed-tree class for the load model | #154's installed sweep already reads every source document's installed copy in both views, and host counting derives from the source tree | An installed member check — duplicates #154's sweep |
| D13 | Guards sit in the owning suites: #100's helper requires "`ResolvedProject` in memory" once per entry; #154's module requires a document mentioning the isolation checker to name `worktrees/SKILL.md` | makes E1 and E4 durable beside the constants they protect | No guards — a restatement returns silently; guards in the new module — away from the rules' homes |
| D14 | Bytes are the ceiling unit; words are reported beside them; the report claims no token savings | issue: "may not claim savings from word counts alone"; session cases §8: words are not tokenizer counts | Tokenizer counts — host-specific and not reproducible offline |
| D15 | Nothing is recovered from `3c9709ca`; no ADR, context doc, `CLAUDE.md`, `.nix` or CI edit | the retained branch holds no consolidation or measurement work; no `CLAUDE.md` sentence is falsified; `bindings.paths.context` is empty | Recover the retained design prose — superseded by #153 and #154 |
| D16 | The load model's unit is a **profile** (`profiles` in the file); "role" stays the matrix's tier field and the issue's wording | `model-matrix.json` and `agent_model_matrix` already use `role` for the tier vocabulary a dispatch site selects; two meanings of one term in adjacent files invite a misread (grill, glossary challenge) | Keep "role" — `design-and-grill owner` and `planning owner` would both be the `issue-owner` role |
| D17 | The report is a function of its two SHAs: the model and the matrix are read at `--head`, members at each revision, all through one `read(path)` seam that `validate`, `measure` and the ceiling test share; refines D9 | the-bar Truthful terminal states — a record regenerated later must say what it said; one seam keeps the working-tree and revision paths from diverging | Read the model from the working tree — the same SHAs regenerate differently once the model changes; separate root- and revision-based functions — two implementations of resolution |
| D18 | Closure: every same-skill `*.md` a member names by basename is listed in the profile as hot, conditional or `unread` with a reason; refines D11 | the issue: savings may not be claimed from word counts alone — without closure, moving text into an unlisted sibling lowers the count while the load stays; D6's follow-up is exactly such a move and must classify its new file | No closure — the ceiling rewards hiding text in a sibling; closure over cross-skill mentions too — every entry names skills other profiles run, so `unread` lists would dwarf the data |
| D19 | Before this slice lands, a sync that changes a measured member re-measures, resets the affected ceilings to the merged values with a note naming the merge commit, and regenerates the report; refines D9, D10 | growth already on `main` was reviewed there and predates the gate; the report's head must be the commit whose members it measures | Fail the sync — blocks shipping on another issue's reviewed change; keep stale ceilings and report — the committed baseline no longer describes the branch |
| D20 | E2 stays in from-issue although one test ends the durable-acquisition section at the removed sentence; that end anchor moves to `## The flow`, the section's real boundary, with every assertion inside unchanged; refines D2 | the sentence is a delimiter there, not asserted content; the durable section is the last subsection of `## Lifecycle identity` | Drop E2 in from-issue — keeps a fallback restatement to spare a delimiter; assert the sentence's presence — pins prose no rule needs |
| D21 | The stray-copy guard also scans the Claude agent definitions and the global guidance file; refines D3 | D4 rejects a standing rule in either place; a guard there makes that decision fail loudly instead of drifting | Scan skill trees only — a clause pasted into global guidance, reaching every session in every repo, would pass unseen |
