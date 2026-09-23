# Dispatch contracts: launch by type, read before write — issue 153

Design for [#153](https://github.com/fagenorn/nix-config/issues/153), one slice of
[#99](https://github.com/fagenorn/nix-config/issues/99), 2026-09-23. Siblings:
[#154](https://github.com/fagenorn/nix-config/issues/154) (shell examples and
worktree-checker guidance), [#155](https://github.com/fagenorn/nix-config/issues/155)
(prose consolidation after the behavior fixes),
[#100](https://github.com/fagenorn/nix-config/issues/100) (strict project resolver,
retiring the legacy bindings fallback). Decisions D1–D13 bind the plan.

## Problem

The #99 audit counted four recurring agent error classes whose total is 417
(119 + 64 + 37 + 197). The number is a count of error turns, not an HTTP status
and not a provider or transport failure. Two of those classes trace to what the
shared dispatch prose does not say:

- **119 dead named launches.** Every one came from inside a subagent. A subagent
  cannot spawn a named teammate; a launch that passes a name returns an error
  instead of work. The #99 diagnosis: leaf agents read orchestrator-flavoured
  skill prose and name their launches. The implementer template already restricts *delivery*
  ("Never deliver it via SendMessage …"); nothing restricts *launching*.
- **64 write-before-read errors.** No dispatch template tells its recipient to
  read an existing file before writing it.

A prose fix alone does not hold: the next edit can drop a sentence silently. The
fix is two canonical clauses in every applicable dispatch template, held by
contract tests that fail independently per missing clause and that pass against
both the source skill trees and the skill trees the Nix build installs.

"Leaf agent" in this spec means any agent running as a subagent — launched by
an `Agent` dispatch — as opposed to the top-level session.

## Solution

### The two clauses

Exactly these sentences, byte-identical in every carrier (whitespace may wrap to
the carrier's width and indentation):

- **Launch by type** (recovered verbatim from #99's retained work):
  `Launch any subagent by type only, never by name: a subagent cannot spawn a named teammate, and a named launch returns an error instead of work.`
- **Read before write** (recovered, one word sharpened per D3):
  `Read an existing file before writing to it: overwriting content you have not read destroys work you cannot see.`

Neither sentence names a reader or a host, so both are safe inside the
correctness rubric, which must stay reviewer-agnostic (its suite forbids
`Codex`, `Claude` and `native` in the rubric's output-format and diff
sections). The launch clause restricts *naming*, never launching: the implementer and ship-owner templates
legitimately dispatch subagents ("Nested Agent calls are supported").

### Carriers — where the clauses live (D1, D2)

A **carrier** is skill-authored text that reaches a subagent's prompt. Two
kinds exist, and both are enrolled:

**Verbatim templates** — the dispatcher pastes the body whole, so the clauses
sit physically inside the body:

| Carrier | Skill tree | Rendered region |
|---|---|---|
| `sdd/implementer-prompt.md` | shared | its single unlabeled fenced block |
| `sdd/task-reviewer-prompt.md` | shared | its single unlabeled fenced block |
| `sdd/re-review-prompt.md` | shared | its single unlabeled fenced block |
| `sdd/correctness-reviewer-prompt.md` | shared | its single unlabeled fenced block |
| `sdd/conformance-reviewer-prompt.md` | shared | its single unlabeled fenced block |
| `from-issue/ship-handoff.md` | shared | its single unlabeled fenced block |
| `orchestrate-issues/SKILL.md` | Claude-only | the issue-owner blockquote following the `orchestration-issue-owner` call line ("with this entire prompt"), quote markers stripped |

**Composition rules** — a workflow skill whose controller composes prompts
(no verbatim body) states once that every prompt it composes for an `Agent`
dispatch carries both sentences verbatim, and states the sentences:

| Carrier | Skill tree | Rendered region | Covers |
|---|---|---|---|
| `from-issue/SKILL.md` | shared | the `## Dispatch, phase-budget and attempt-budget rules` section | every prompt from-issue and its phase files compose: design and plan owners, the phase delegate, the rollover implementation owner, the ledger-only bookkeeper, the mechanical implementer and reviewer, the Phase-5 plan reviewer, the inline-fallback reviewer |
| `sdd/SKILL.md` | shared | the `## Agent tiers` section | every prompt sdd composes: fresh fix-round, post-rescue, rescue-fallback and round-five implementers, the final-review fixer, lane verification and re-review escalations |

The from-issue rule is a sibling of the existing **Structured report-backs**
rule in the same section, which already binds "every `Agent` dispatch"; the
new paragraph opens `**Leaf-agent clauses.**` and says a prompt built from one
of the skill's templates already carries them. The sdd rule sits in
`## Agent tiers`, beside its existing "Dispatch by agent type" sentence. `AUTO.md`'s "Both prompts
must carry, inline" list gains one pointer bullet — the two leaf-agent clauses
from `SKILL.md`'s dispatch rules, verbatim — so that list stays complete; the
pointer is not a carrier (the rule it points at is).

Placement inside each template: the two sentences form their own paragraph,
inside the rendered region, immediately before the region's output section —
`## Report Format` (implementer), `## Output Format` (the four reviewers), the
`Return exactly canonical JSON` paragraph (ship-handoff), and the
`Persist the compact result` line (orchestrate-issues). A separate paragraph,
not a splice: the retained work inserted the launch sentence between the
implementer's "the controller reads your final message directly" and "Never
deliver it via SendMessage", which re-points that sentence's "it". The
implementer's delivery sentence keeps its words and place and is not copied
anywhere (D5).

Dispatch sites that are **not** carriers, and why (D1):

- Skills whose every dispatch goes to a recipient declared without `Agent`,
  `Write` or `Edit` tools, so both clauses would be inert: the `Explore`
  lookups in `design`, `grill-with-docs`, `doc-grounded-questions` and
  `writing-plans`, and the reviewer and Codex-transport dispatches of
  `ship-issue` and `codex-collaboration`. (from-issue and sdd also compose
  reviewer dispatches; their rules cover those too, because one rule per skill
  carries no recipient carve-out — D2.)
- Standalone skills outside the issue-delivery pipeline, each with one dispatch
  and no carrier: the `ship-release` owner, the `research` background researcher
  and the `improve-codebase-architecture` scan owner. They are the named
  residual; whether one standing rule should replace per-carrier copies is
  #155's consolidation question.

### The installed skill tree (D7, D8)

The Nix build installs skills unchanged from source: the shared tree reaches
Claude as `.claude/skills/<name>/<file>` links and Codex as whole-directory
`.agents/skills/<name>` links; the two Claude-only skills reach only
`.claude/skills`. All of it lives in the build's single `home-manager-files`
output, a requisite of `./result`.

"Installed skill tree" means **that built output**, not the activated home:
`~/.claude/skills` reflects the generation last switched to and cannot contain
this change until a switch, while the built output exists after `just build`.
The suite reads it through one environment variable,
`AGENT_SKILLS_INSTALLED_HOME` — any directory laid out like the home
home-manager populates. It checks two views of it:

- **Claude view** — `<root>/.claude/skills`: every carrier.
- **Codex view** — `<root>/.agents/skills`: every shared-tree carrier. Claude-only
  carriers are not published there, so the view never lists them.

A new recipe `agent-installed-skill-tests`, depending on `build`, finds the
`home-manager-files` output among `./result`'s requisites exactly the way
`show-claude-settings` finds the settings artifact — refusing unless exactly one
matches — and runs the dispatch-contract module with the variable set to it.
Pointing the variable at `$HOME` after a switch checks the activated home with
the same code.

Unset variable: the installed-tree class is skipped with a reason naming the
recipe; `just agent-workflow-tests` and CI's advisory job still run the
source-tree and checker tests. Set variable whose root lacks either view
directory, or whose view lacks a carrier it publishes: a failure, never a skip
and never a fallback to the source tree.

### Selective recovery (D12)

Retained branch `worktree-issue-99-skill-prose-fixes` holds one WIP commit,
`3c9709ca470bd473d49b39a611ca6cab258973db` (parent `95b6caf`). It stays
read-only: hunks are read with `git show 3c9709ca:<path>` and
`git diff 95b6caf 3c9709ca -- <path>`, re-applied by hand to the current tree,
never checked out, cherry-picked, merged or rebased, and the branch tip is
confirmed unchanged at the end.

| Retained hunk | Disposition |
|---|---|
| `LEAF_LAUNCH_CLAUSE` text | recovered verbatim |
| `READ_BEFORE_WRITE_CLAUSE` text | recovered, "a file" → "an existing file" (D3) |
| clause paragraphs in the six fenced templates | recovered for placement; re-based on current text (`ship-handoff.md`'s closing sentence changed since `95b6caf`); delivery sentence and the reviewers' "Deliver … yourself, as your own final message" sentence dropped (D5) |
| `DISPATCH_PROMPT_TEMPLATES`, `NON_TEMPLATE_SINGLE_FENCE_DOCS`, `unlabeled_fenced_blocks()`, `test_dispatch_prompt_templates_are_enrolled`, `test_dispatch_prompts_carry_the_leaf_agent_clauses` | recovered into the new module, generalized over carriers and trees and split per contract (D9–D11) |
| `LEAF_DELIVERY_CLAUSE` | excluded (D5) |
| every `.claude/skills.config.json` "if it exists" / "when present" guard, `SKILL_TREES`/`skill_documents()` and `test_bindings_config_mentions_are_guarded_on_presence` | excluded — #100 |
| shell-text extraction, the heredoc/chain/pipe/redirect tests, the worktrees isolation-checker section and its test | excluded — #154 |
| `env -u GITHUB_TOKEN` rewording, all `ship-release` and `test_ship_release_contracts.py` changes | excluded — unrelated #99 work |
| the retained spec, plan and task files | excluded — superseded by this spec |

Every commit that lands a recovered hunk carries a
`Recovered-From: 3c9709ca470bd473d49b39a611ca6cab258973db` trailer in the same
trailer block as the co-author and session lines, and its body names the source
branch and lists the hunks it recovered or adapted. Commits of new work carry no
such trailer.

## Decisions

**The contract is asserted on the rendered region (D6).** A clause counts only
inside the text the recipient receives: the fence body, the blockquote with its
quote markers removed, or the named section. Prose outside that region is
dispatcher-facing; a file-wide match would pass with the clause somewhere no
subagent reads it. Rendering fails loud when its region is missing or ambiguous
— a fence carrier without exactly one unlabeled fence, an absent anchor line,
an anchor not followed by a quote block, an absent heading.

**One authoritative home per clause (D4).** The new test module holds each
clause once, in a closed contract-id → sentence mapping
(`launch-by-type`, `read-before-write`). Carriers repeat the text physically
because a template is pasted wholesale and a link never reaches the subagent's
context; the suite asserts every copy against the one constant, whitespace-
normalized, so the copies cannot drift. This is the suite's existing
`REPORT_CANDIDATE_CLAUSE` pattern.

**Exactly once.** Each clause occurs exactly once in each carrier's rendered
region. A duplicate is a failure; it would also make a removal fixture vacuous.

## Test seams

One new module, `home/common/agent-skills/tests/test_dispatch_contracts.py`,
registered in `agent-workflow-tests` and run alone by
`agent-installed-skill-tests`. No other test surface. Its public boundary is
one function, `missing_contracts(carrier, document_text)` → the set of contract
ids whose clause is absent from that carrier's rendered region, plus the
carrier and contract tables it closes over. Four test classes:

1. **Source trees** — one method per contract (`launch-by-type`,
   `read-before-write`), each iterating every carrier in the source view
   (shared carriers under `home/common/agent-skills/skills`, Claude-only under
   `home/common/claude-code/skills`) with one `subTest` per carrier. Removing
   one clause from one carrier reds only that contract's method, in only that
   carrier's subtest.
2. **Installed trees** — the same two methods over the Claude and Codex views
   of `AGENT_SKILLS_INSTALLED_HOME`; skipped when it is unset (D8).
3. **Checker mutations** — derived from the live source text of every carrier,
   not hand-written strings: for each carrier × contract, removing that clause
   (a pattern tolerant of the region's wrapping, indentation and quote markers)
   yields exactly `{that contract}`; removing it and re-appending it outside
   the rendered region still yields exactly `{that contract}`; the unmodified
   text yields the empty set. This is the issue's demo: fixtures fail when
   either clause is absent, and pass with the corrected text.
4. **Enrolment guard** — the documents under `from-issue/` and `sdd/` carrying
   exactly one unlabeled fenced block, minus a declared non-template set, equal
   the fence-kind carriers. The declared set's only member is
   `from-issue/SKILL.md`, whose single fence is the `## The flow` diagram; that
   file is still a carrier, of the section kind. A new single-fence template
   fails the guard until enrolled; blockquote and section carriers are enrolled
   explicitly and are outside the guard's reach.

Prior art: the permission-guard suite's `CLAUDE_SETTINGS_PATH` built-artifact
seam and `show-claude-settings`' requisite discovery; the contract suite's
whitespace-normalized clause constants; the environment-capability skips
already in `test_workflow_state.py`.

## Open questions resolved

- **Q1 applicable templates** → the seven verbatim templates plus the from-issue
  and sdd composition rules; excluded sites named above (D1).
- **Q2 installed tree** → the built `home-manager-files` output via
  `AGENT_SKILLS_INSTALLED_HOME`, both consumer views, a building recipe;
  skip when unset, fail when malformed (D7, D8).
- **Q3 wording and source of truth** → retained wording, one word sharpened;
  test constants authoritative (D3, D4).
- **Q4 read-before-write in reviewer prompts** → yes, every carrier (D2).
- **Q5 provenance** → hand re-application from `git show`, `Recovered-From`
  trailer plus body inventory, tip unchanged (D12).
- **Q6 independent, behavior-level failure** → rendered-region check, one
  method per contract per tree, live-text mutation matrix (D6, D10).

## Acceptance criteria and verification

| #153 criterion | Satisfied by | Verified by |
|---|---|---|
| 1. Every applicable template: launch by type only | launch clause in all nine carriers | `launch-by-type` methods, source and installed classes |
| 2. Templates require reading an existing file before writing | read-before-write clause in all nine carriers | `read-before-write` methods, source and installed classes |
| 3. Contract tests fail independently per missing contract; pass on source and installed trees | per-contract methods; mutation matrix; installed class over the built output | `just agent-workflow-tests` green (installed class skipped); `just agent-installed-skill-tests` green with the installed class run, not skipped |
| 4. Selective recovery with provenance; unrelated #99 work excluded | recovery table above | `git log --format='%(trailers:key=Recovered-From)'` names `3c9709ca` on each recovering commit; the branch tip still `3c9709ca`; the branch diff adds no `.claude/skills.config.json` guard, no `env -u GITHUB_TOKEN`, no shell-form test, no `worktrees` or `ship-release` change, no delivery clause outside the implementer template |

`just build` must pass (no `.nix` file changes, but the installed recipe builds
anyway). `just agent-model-matrix` stays green: no marker or call line moves.
The existing suites that pin these documents stay green, notably the
orchestrate-issues blockquote extraction and the correctness rubric's
reviewer-agnostic check.

## Out of scope

- Any add, restore or conditional guard on a direct read of
  `.claude/skills.config.json` or `.agents/project.json` — #100.
- Shell-form examples and worktree-checker guidance — #154.
- Consolidating the per-carrier copies into a standing rule (global agent
  guidance, agent definitions under `home/common/claude-code/agents/`, or a
  shared include), and any other context reduction — #155.
- The residual dispatch sites listed under Carriers.
- Spreading the `SendMessage` delivery clause (D5).
- CI changes: the installed check is local, like the permission-guard suite.
- `.nix` changes, `CLAUDE.md` edits, ADRs, and any `docs/` tree (D13).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Carriers are the six fenced templates, the orchestrate-issues issue-owner blockquote, and one composition rule each in from-issue and sdd (plus a pointer bullet in `AUTO.md`); Explore/reviewer/transport dispatches and the three standalone-skill owners are excluded and named as residual | #153 AC1 "every applicable dispatch template"; the audit attributes all 119 launches to subagents but not to sites, so coverage follows which pipeline subagents hold `Agent` or `Write`: the issue owner, design/plan owners, ship owner, implementers and the owners from-issue and sdd compose; from-issue's "Structured report-backs" rule already binds every dispatch | The retained six templates only — misses the issue owner and the owners from-issue and sdd compose, the heaviest launchers; every dispatch site — the excluded recipients are declared without `Agent`/`Write`/`Edit`, and the standalone skills sit outside #153's pipeline |
| D2 | Both clauses go in every carrier, including the read-only reviewer templates | AC2 is unqualified ("Dispatch templates require …"); a template does not control its recipient's toolset — the shared text is read by Codex hosts and from-issue permits `general-purpose` dispatch | Derive per-carrier applicability from recipient tools — an exception set the suite must encode, to save one sentence per template |
| D3 | Launch clause verbatim from the retained work; read-before-write reworded to "an existing file"; neither rationale claims a tool refusal | AC2's own words ("an existing file"); "a file" tells an agent to read a path it is about to create; a scratchpad probe overwrote unread files without refusal, and a refusal claim would be false on Codex | Keep "a file" — invites a failing read of a new path; cite the write tool's refusal — host-specific and not reproducible |
| D4 | The test module's contract mapping is each clause's one authoritative home; carriers repeat the text and are asserted whitespace-normalized against it | the-bar DRY; a pasted template carries no link target into the subagent's context; `REPORT_CANDIDATE_CLAUSE` precedent | A shared document the templates link to — the link never reaches the subagent |
| D5 | The `SendMessage` delivery clause stays only where it is (implementer) and is not spread | #153 names two contracts; delivery is not among the audit's four classes; the-bar YAGNI | Recover `LEAF_DELIVERY_CLAUSE` into every carrier — a third, unevidenced contract |
| D6 | A clause counts only inside the carrier's rendered region, and rendering fails loud on a missing or ambiguous region | the-bar Fail loud and Tests that can fail; dispatcher-facing prose never reaches the recipient | File-wide substring — green with the clause where no subagent reads it |
| D7 | "Installed tree" is the built `home-manager-files` output, read through `AGENT_SKILLS_INSTALLED_HOME` in a Claude view (all carriers) and a Codex view (shared carriers); a new `agent-installed-skill-tests` recipe builds, discovers exactly one output and runs the module | CLAUDE_SETTINGS_PATH and `show-claude-settings` precedent; skills install via `skillsDir` and whole-directory `.agents/skills` links from one output | The live `~/.claude/skills` — the activated generation, stale until a switch; a synthesized temp layout — a copy of source that proves nothing about the build |
| D8 | Unset variable skips the installed class with a reason naming the recipe; a set variable with a missing view or carrier fails | Precedented capability skips in `test_workflow_state.py`; the-bar Truthful terminal states and Fail loud | A module-level required variable like the permission guard — breaks `agent-workflow-tests` and CI's advisory job; silent fallback to source — a green installed run that checked nothing installed |
| D9 | The checks live in a new `test_dispatch_contracts.py`, not in `test_workflow_skill_contracts.py` | the-bar Single responsibility; the installed recipe must run only these checks against another root | Extend the 3,500-line contract suite as the retained work did — the installed run would drag every repo-rooted test along |
| D10 | Independence is proved by one test method per contract per tree plus a live-text mutation matrix (remove, relocate outside the region, unmodified) over every carrier × contract, with each clause required exactly once | #153 AC3 "fail independently"; the-bar: fixtures shaped like production values | One combined clause test — a missing launch clause masks a missing read-before-write clause; hand-written fixture strings — pass while the real carriers drift |
| D11 | Fence carriers are guarded by the recovered enrolment test (single-unlabeled-fence docs under `from-issue/` and `sdd/` minus `{from-issue/SKILL.md}`); blockquote and section carriers are enrolled explicitly | Retained #99 D6/D21/D23, re-verified at `4f74c47`: seven such docs exist, the six templates plus `from-issue/SKILL.md`'s flow diagram | Glob-only enrolment (silently covers nothing once a template gains a second fence) or constants-only (silently ignores a new template) |
| D12 | Recovery re-applies adapted hunks read with `git show`/`git diff` from `3c9709ca`; each recovering commit carries a `Recovered-From: 3c9709ca…` trailer and a body inventory; the retained branch tip is verified unchanged | #153 AC4 and "keep that branch and worktree read-only"; `ship-handoff.md` changed since `95b6caf`; a trailer is queryable with `git log --format=%(trailers)` | Cherry-pick or merge — imports the #100/#154 hunks and conflicts on the moved base; provenance recorded only in the spec — detached from the code history it describes |
| D13 | No ADR, context doc or `CLAUDE.md` edit | The ADR gate needs hard-to-reverse and surprising; this is reversible prose held by tests, and the repo has no ADR home. `CLAUDE.md`'s command list is not exhaustive and no sentence in it is falsified by this change | Found `docs/areas/system/adr/` for a reversible prose fix; list the new recipe in `CLAUDE.md` — prose growth that #155 is chartered to consolidate |
