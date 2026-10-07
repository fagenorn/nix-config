# Skills to best practice, with a growth gate (#291)

Program spec. It settles the rules, the gate, and the slices. Each slice ships
as its own issue under #291, and each slice's own spec cites rows here ("per D4")
rather than restating them.

## Problem

The skill corpus grew from 24.6k to 73.9k words between 2026-08-04 and
2026-10-07. Agents pay for that growth on every run: one `from-issue --auto`
owner loads ~175 KB of instructions (the `implementation-owner` and
`orchestrated-issue-owner` load profiles), before it reads any code. The
growth has no counterweight:

- The `instruction-load.json` ceilings are the only size check. They were
  raised 45 times and lowered 9 times, and each raise came from the PR whose
  prose needed it. The check runs only inside the advisory
  `Agent Workflow Tests` job, so a breach blocks nothing anyway.
- `test_workflow_skill_contracts.py` pins about 480 English phrases. A
  sentence whose phrase is pinned cannot be deleted without editing a test, so
  removing text costs more than adding it.
- The evals last ran on 2026-08-15 (three runs). Nobody can show that a
  sentence is unnecessary, so the safe move is always to add one more.

Measured against Anthropic's
[skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices),
the large skills fail its checklist. Three `SKILL.md` files exceed 500 lines
once reflowed to 100 columns (`from-issue` ~730, `ship-issue` ~655,
`ship-release` ~524). `from-issue` spends 40% of its body on four
acquisition routes, and only one of them applies to any invocation. Much
prose restates rules that `workflow-state`, `artifact-budget` and
`resolve-project` already enforce. Reference files route readers to other
reference files. None of the 20+ reference files over 100 lines has a table
of contents.

## Solution

Two halves, landed in this order.

**1. Checks and balances first** (slices S1–S2). Growth becomes a human
decision, and the checklist rules that can be checked mechanically become a
required CI check. The gate goes in before any slimming. That way every
slimming PR banks its savings, and every in-flight issue that grows prose
(#279–#284 among them) meets the gate.

**2. Then the corpus** (slices S3–S9). Bring each skill to the checklist and
cut its always-loaded surface. In each skill's slice, delete that skill's
prose pins and replace them with the test policy in D6. Re-run the evals
before and after.

### The rules (what `skill-lint` checks)

These are checked over every skill under the shared, Claude-only and Codex
trees:

| Rule | Check | Source |
|---|---|---|
| L1 frontmatter | `name` ≤ 64 chars, `[a-z0-9-]+`, no `anthropic`/`claude`, no XML; `description` non-empty, ≤ 1024 chars, no XML | best practices: YAML frontmatter |
| L2 body length | `SKILL.md` body ≤ 500 *reflowed* lines (each physical line counts `max(1, ceil(len/100))`) | best practices: token budgets |
| L3 contents | any skill `.md` over 100 reflowed lines carries a `## Contents` list before its first other `##` heading | best practices: TOC for long references |
| L4 one level deep | every non-`SKILL.md` file in a skill is named in that skill's `SKILL.md`; a reference file names no sibling reference file except a dispatch payload (D4) | best practices: avoid nested references |
| L5 description voice | description does not open with `I `/`You ` and contains a `Use when`/`Use for`/`Use to` trigger clause | best practices: writing descriptions |

L2 reflows lines so that a 1,229-column line cannot launder length past a
line count.

### The gate (what the `Instruction Budget` check enforces)

A new required CI context, `Instruction Budget`, runs on pull requests:

1. `skill-lint check` passes (L1–L5).
2. The live tree breaches no `instruction-load.json` ceiling.
3. **No ceiling rises** compared with the PR's base, and no new profile is
   added above the tightness bound, unless the PR carries the label
   `instruction-budget-raise` (D2).
4. **Ceilings stay tight:** every ceiling is at most measured × 1.05 (D3).
   A PR that cuts prose therefore has to lower its ceilings, which banks the
   saving.

`instruction_load` gains a `check` subcommand for steps 2–4. Today it only
reports. `just agent-instruction-budget` runs steps 1–4 locally against
`origin/main`.

## Decisions

- **The budget unit stays `instruction-load.json` ceilings** (bytes per
  profile per host). They already measure what an agent actually loads on a
  route, which a per-file word count cannot do. No second budget file is
  added. `skill-lint` adds only the structural rules.
- **The label is a human signal, and the guard enforces it.** The lifecycle
  guard refuses agent commands that apply `instruction-budget-raise`:
  `gh pr edit`/`gh issue edit --add-label`, and `gh api` writes to a labels
  endpoint carrying it. The skills say that only the user applies it. This
  matches `.agents/knowledge/rejections/ungated-agent-merges.md`: merge safety
  comes from a required check, not from prose.
- **Skill names stay as they are.** The guide accepts action-oriented names,
  and the collection is internally consistent. Renaming would break `/from-issue`
  muscle memory and every cross-skill reference for no discovery gain.
- **Content moves to where it is used:**
  - Mutually exclusive routes move to per-route reference files, which
    `SKILL.md` selects with a one-line condition.
  - Rules a helper enforces become one line: "run X; act on its refusal."
    The helper's error text owns the detail, and where it does not say enough,
    the helper's message is improved (best practices: "solve, don't defer").
  - Rationale and history move to specs and ADRs.
  - Everything else is cut unless an agent without it would get the step
    wrong.
- **Each slimmed skill gets a target:** `SKILL.md` ≤ 300 reflowed lines for the
  five heavy skills, and its hot load profile −35% or better against the
  2026-10-07 ceiling.

## Test seams

- **`skill-lint check`** (new `agent_tools.skill_lint`, a command-table row):
  unit-tested over fixture skill trees in the style of
  `test_instruction_load.py`'s `FIXTURE_MATRIX`, plus one live-tree test.
- **`instruction_load check`**: unit-tested over two in-memory revisions
  (the existing `revision_reader` seam), covering ceiling-raise refusal,
  label override, tightness, and new-profile admission.
- **The lifecycle guard's adversarial table** in
  `tests/test_claude_permission_guard.py` grows rows for the label verbs.
- **Skill behaviour** is tested at the existing seams only: the machine-read
  checks D6 keeps, plus the eval harness. No new prose-pinning test is
  written.

## Out of scope

- Moving the lifecycle protocol into `agent_tools` (#123/#125). Slimming
  replaces restated helper rules with a pointer to the helper. It does not
  change any helper's behaviour, except to improve error text the skill
  previously had to explain.
- Changing workflow semantics: phases, gates, review axes, lanes. A slice that
  finds a rule which is wrong rather than wordy files an issue.
- The repository `CLAUDE.md` (4.7k words, loaded in every session here). It is
  not a skill, and it gets a follow-up issue under the same rules.
- Upstream-pinned skills (`impeccable`, `skill-creator`, the codex plugin's
  skills). `skill-lint` skips trees Nix does not author.

## Slices

| Slice | Content | Blocked by |
|---|---|---|
| S1 | `skill-lint` (L1–L5), `instruction_load check`, `Instruction Budget` CI job (required), `just agent-instruction-budget`; fixes the current tree until L1/L5 pass, records L2–L4 debt in a shrinking allowlist | — |
| S2 | Lifecycle guard refuses agents applying `instruction-budget-raise`; skills/AGENTS.md state the rule | S1 |
| S3 | Evals: working-tree mode for `run-eval.sh` (D7); ≥3 cases each for from-issue, ship-issue, sdd, ship-release, orchestrate-issues; baseline run on `main` recorded | — |
| S4 | `from-issue` (SKILL, AUTO, ship-handoff, REVIEW-CONTRACT, companions) | S1, S3 |
| S5 | `ship-issue` (SKILL + 5 references) | S1, S3 |
| S6 | `sdd` (SKILL, final-review, fix-loop, prompts) | S1, S3 |
| S7 | `ship-release`, `orchestrate-issues` (+ Codex stub) | S1, S3 |
| S8 | The remaining skills: descriptions, TOCs, cuts, and test policy for each | S1 |
| S9 | Close-out: allowlist empty, evals re-run against baseline, ceilings at measured | S4–S8 |

Each of S4–S8 removes its skills' entries from the S1 allowlist. The allowlist
can only shrink, and S9 deletes it.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Budget stays in `instruction-load.json` profile ceilings; `skill-lint` adds structure only | The Bar, DRY: one authoritative home; profiles already measure the routed load | A separate per-skill word budget file: a second source that disagrees with the profiles |
| D2 | A ceiling can rise only on a PR labelled `instruction-budget-raise`, which only the user applies; the guard refuses agent label writes | User asked for checks and balances; `rejections/ungated-agent-merges.md` | Skill prose alone ("agents must not raise ceilings"): that is the regime that produced 45 raises |
| D3 | Ceilings must sit within 5% of measured | Without tightness a 30% cut leaves slack that later growth refills for free | Absolute caps only: savings would not be banked |
| D4 | L4 lets a reference file name a sibling only when that sibling is a dispatch payload handed to a subagent by path (marked with a dispatch marker or living under `prompts/`) | Best practices concern the *reader's* chains; a payload is not read by this agent | Banning all sibling mentions: forces sdd's reviewer prompts into SKILL.md |
| D5 | `Instruction Budget` is a required context in `.github/branch-protection.json`; `Agent Workflow Tests` stays advisory | A size gate that cannot block is the current failure | Making the whole agent suite required: out of scope, and slow |
| D6 | Skill-text tests keep only text a tool or subagent consumes. That is: the dispatch marker lines and the `Agent(...)` call lines mirrored in `model-matrix.json` (`agent_model_matrix`); the three carrier clauses that `test_dispatch_contracts` places in dispatch regions; shell examples vetted by `test_shell_example_contracts`; frontmatter; JSON key sets of lifecycle contracts; `workflow-state`/`resolve-project` argv. Prose pins (~80% of `test_workflow_skill_contracts.py`, plus the phrase pins in `test_ship_release_contracts.py` and `WorktreesGuidanceTest`) are deleted in the slice that slims their skill. Heading anchors that only tests read may be renamed, with the test updated in the same commit. `docs/standards/agent-helpers.md` records the rule | The Bar, "tests that can fail": a phrase pin fails on rewording, not on behaviour | Converting pins to fuzzy "concept present" checks: same ratchet, weaker signal |
| D7 | Evals run working-tree skills in a temporary `CLAUDE_CONFIG_DIR` whose `skills/` links the tree. If auth cannot carry, S3 falls back to a committed branch plus `just switch`, and that switch needs the user's go | Evals README: deployed skills shadow project copies; best practices: evaluate before and after | Grading by hand only: the regime that left evals unrun since August |
| D8 | Slices ship sequentially per skill and in parallel across skills (`max_parallel` 2); a slice syncs `instruction-load.json` and the contract-test file from `main` before review | Hot shared files would conflict | One mega-PR: unreviewable |
| D9 | Skill names are kept; descriptions are rewritten to third person with a trigger clause | Guide accepts action names; the collection is consistent | Gerund renames: churn with no discovery gain |
| D10 | Upstream-pinned skills are outside `skill-lint` | Nix does not author them; they bump via inputs | Patching upstream skills: a maintenance burden |
