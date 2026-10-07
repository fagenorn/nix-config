# Skills to best practice, with a growth gate (#291)

Program spec. It settles the rules, the gate, and the slices. Each slice ships
as its own issue under #291, and each slice's own spec cites rows here ("per D4")
rather than restating them.

## Problem

The skill corpus grew from 24.6k to 73.9k words between 2026-08-04 and
2026-10-07. Agents pay for that growth on every run: one `from-issue --auto`
owner loads ~175 KB of instructions on its hot path alone (the
`implementation-owner` and `orchestrated-issue-owner` load profiles), before it
reads any code. The growth has no counterweight:

- The `instruction-load.json` ceilings are the only size check. They were
  raised 45 times and lowered 9 times, and each raise came from the PR whose
  prose needed it. They also cover only hot bytes, so 107 KB of conditional
  prose has no ceiling at all.
- The ceiling check runs only inside the advisory `Agent Workflow Tests` job,
  so a breach blocks nothing.
- `test_workflow_skill_contracts.py` pins about 480 English phrases. A
  sentence whose phrase is pinned cannot be deleted without editing a test, so
  removing text costs more than adding it.
- The evals last ran on 2026-08-15 (three runs). Nobody can show that a
  sentence is unnecessary, so the safe move is always to add one more.

Measured against Anthropic's
[skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices),
the large skills fail its checklist:

- Three `SKILL.md` files exceed 500 lines once reflowed to 100 columns
  (`from-issue` ~730, `ship-issue` ~655, `ship-release` ~524).
- `from-issue` spends 40% of its body on four acquisition routes, and only one
  of them applies to any invocation.
- Much prose restates rules that `workflow-state`, `artifact-budget` and
  `resolve-project` already enforce.
- Reference files route readers to other reference files.
- None of the 20+ reference files over 100 lines has a table of contents.

## Solution

Two halves, landed in this order.

**1. Checks and balances first** (slices S1–S2). Growth becomes a human
decision, and the checklist rules that can be checked mechanically become a
required CI check. The gate goes in before any slimming. That way every
slimming PR banks its savings, and every in-flight issue that grows prose
(#279–#284 among them) meets the gate.

**2. Then the corpus** (slices S3–S9). Bring each skill to the checklist and
cut its loaded surface. In each skill's slice, delete that skill's prose pins
(D6). Measure with evals before and after.

### Vocabulary

- **Reference file**: a `.md` file inside a skill directory, other than
  `SKILL.md`, a payload, and anything under `evals/` or `scripts/`.
- **Payload**: a file handed to a subagent by path rather than read by the
  agent running the skill. It is a `*-prompt.md` file, or a file that a
  `model-matrix.json` dispatch site's prompt names.
- **Reflowed lines**: each physical line counts `max(1, ceil(len/100))`, so
  a 1,229-column line cannot slip past a line count.

### The rules (what `skill-lint` checks)

These are checked over every authored skill: the shared, Claude-only and Codex
trees.

| Rule | Check | Source |
|---|---|---|
| L1 frontmatter | `name` equals its directory, ≤ 64 chars, `[a-z0-9-]+`, contains neither `anthropic` nor `claude`, no XML; `description` non-empty, ≤ 1024 chars, no XML | Best practices: YAML frontmatter |
| L2 body length | `SKILL.md` body ≤ 500 reflowed lines | Best practices: token budgets |
| L3 contents | a reference file over 100 reflowed lines carries a `## Contents` list before its first other `##` heading | Best practices: TOC for long references |
| L4 one level deep | (a) every reference file is named in its skill's `SKILL.md`; (b) a reference file names no other reference file. Naming `SKILL.md` or a payload is allowed, and payloads are exempt | Best practices: avoid nested references |
| L5 trigger clause | the description does not open with `I ` or `You `, and it contains a trigger clause (`Use when`, `Use for`, `Use to`, `Use before`, `Use after`, `Invoke before`) | Best practices: writing descriptions |

Third person, conciseness and consistent terminology cannot be linted. Each
slice's reviewer brief carries them as rubric items instead.

### The gate (what the `Instruction Budget` check enforces)

`Instruction Budget` is a new required check in its own workflow file. On
pull requests it runs on `opened`, `synchronize`, `reopened`, `labeled` and
`unlabeled`, with full history. It compares the PR merge commit (`HEAD`)
against its first parent, the base:

1. `skill-lint check` passes.
2. The tree breaches no ceiling. That covers each profile's hot bytes,
   **each profile's conditional bytes** (new), and **the corpus** (new): the
   total bytes of every authored skill tree, `claude-code/agents/*.md` and
   the `AGENTS.md` frame, plus a separate ceiling on the total bytes of all
   skill descriptions, which every session loads.
3. **Tightness:** every ceiling is at most measured × 1.05. A PR that cuts
   prose therefore has to lower its ceilings, which banks the saving.
   `instruction_load tighten` lowers ceilings to the measured value and can
   never raise one.
4. **Raise control:** the PR needs the `instruction-budget-raise` label when
   it makes any change to `instruction-load.json` other than lowering a
   ceiling. That covers a raise, a new or removed profile or host, a document
   moved between hot, conditional and unread, and an edit to `excluded_sites`.
   The label is also needed for any change to the gate itself: its workflow,
   `skill_lint`, `instruction_load`, the debt allowlist, and
   `branch-protection.json`. Separately, the debt allowlist may only shrink
   against the base, label or not.

On push to `main`, steps 1–3 run. Step 4 needs a PR, and a labelled raise was
already decided there. The label is read from the event payload, so no API
permission is needed.

Branch protection becomes `strict: true`. Without it, two PRs that each pass
on their own base can merge into a breach on `main`. `just
agent-instruction-budget` runs steps 1–4 locally against `origin/main`.

## Decisions

- **The budget unit stays `instruction-load.json`.** Its profiles measure what
  an agent actually loads on a route, which a per-file word count cannot do.
  The corpus and description ceilings are added there, derived from the same
  files. No second budget file is added. `skill-lint` adds only the
  structural rules.
- **The label is a human signal, and it is not airtight.** The skills and
  `AGENTS.md` say that only the user applies it. The Claude lifecycle guard
  refuses the direct forms (`gh pr edit`/`gh issue edit --add-label
  instruction-budget-raise`). That catches the honest mistake, not a
  determined bypass: Codex has no PreToolUse hook, and `gh api`, GraphQL or
  `curl` with a token are outside the guard. The protection that holds is the
  required check plus the user seeing the label on the PR, the same posture as
  `.agents/knowledge/rejections/ungated-agent-merges.md`.
- **Skill names stay as they are.** The guide accepts action-oriented names,
  and the collection is internally consistent. Descriptions are rewritten to
  third person with a trigger clause.
- **Content moves to where it is used:**
  - Mutually exclusive routes move to per-route reference files, which
    `SKILL.md` selects with a one-line condition.
  - Rules a helper enforces become one line: "run X; act on its refusal." The
    helper's error text owns the detail. Where that text is not enough, the
    helper's message is improved (best practices: "solve, don't defer").
  - Rationale and history move to specs and ADRs.
  - Everything else is cut unless an agent without it would get the step
    wrong.
- **Targets for each heavy-skill slice:** `SKILL.md` ≤ 300 reflowed lines, and
  hot plus conditional bytes of its profiles −35% or better against the
  2026-10-07 measurement. Moving a document between hot and conditional does
  not count toward the target, and it needs the label anyway.

## Test seams

- **`skill-lint check`** (new `agent_tools.skill_lint`, a command-table row):
  unit-tested over fixture skill trees in the style of
  `test_instruction_load.py`'s `FIXTURE_MATRIX`, plus one live-tree test.
- **`instruction_load check` / `tighten`**: unit-tested over two in-memory
  revisions (the existing `revision_reader` seam). The tests cover:
  - raise refusal and label override;
  - every reclassification edit;
  - gate-file edits;
  - allowlist growth;
  - tightness;
  - the conditional, corpus and description ceilings.
- **`tests/test_branch_protection.py`** is rewritten for the new workflow and
  for the two required contexts (`Nix Eval`, `Instruction Budget`) with
  `strict: true`.
- **The lifecycle guard's adversarial table** in
  `tests/test_claude_permission_guard.py` grows rows for the label verbs.
- **Skill behaviour** is tested at the existing seams only: the machine-read
  checks that D6 keeps, plus the eval harness. No new prose-pinning test is
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
  skills). Nix does not author them, so `skill-lint` and the corpus ceiling
  skip them.
- Cross-skill chains (one skill invoking another through the Skill tool).
  That is normal composition, not a nested reference.

## Slices

| Slice | Content | Blocked by |
|---|---|---|
| S1 | `skill-lint`, `instruction_load check`/`tighten`, conditional, corpus and description ceilings, the `Instruction Budget` workflow (required, `strict`), `just agent-instruction-budget`; current L1–L4 debt recorded in a shrink-only allowlist | — |
| S2 | The guard refuses the direct label verbs; skills and `AGENTS.md` state that only the user applies the label | S1 |
| S3 | Eval working-tree mode (D7); pipeline cases where only plan-only cases exist; a recorded baseline on `main` for each heavy skill on Sonnet and Opus | — |
| S4 | `from-issue` (SKILL, AUTO, ship-handoff, REVIEW-CONTRACT, companions) | S1, S3 |
| S5 | `ship-issue` (SKILL + 5 references) | S1, S3 |
| S6 | `sdd` (SKILL, final-review, fix-loop, payloads) | S1, S3 |
| S7 | `ship-release`, `orchestrate-issues` (+ Codex stub) | S1, S3 |
| S8 | Shared documents and the remaining skills: `claude-code/agents/*.md`, the `AGENTS.md` frame, and every skill not in S4–S7. Covers descriptions, contents lists, cuts and the test policy | S1, S3 |
| S9 | Close-out: allowlist deleted, evals re-run against baseline, every ceiling tight | S4–S8 |

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The budget stays in `instruction-load.json`: hot and conditional ceilings per profile, plus corpus and description ceilings derived from the same files; `skill-lint` adds structure only | The Bar, DRY: one authoritative home; profiles already measure the routed load | A separate per-skill word budget file: a second source that disagrees with the profiles |
| D2 | Any change to `instruction-load.json` other than lowering a ceiling, and any change to the gate's own files, needs the `instruction-budget-raise` label; the guard refuses the direct label verbs on Claude as a mistake-catcher, not as enforcement | User asked for checks and balances; review found reclassification and self-edit loopholes; `rejections/ungated-agent-merges.md` | Skill prose alone ("agents must not raise ceilings"): the regime that produced 45 raises. Guarding all of `gh api`: skills use it legitimately |
| D3 | Ceilings must sit within 5% of measured; `tighten` only lowers | Without tightness a 30% cut leaves slack that later growth refills for free | Absolute caps only: savings would not be banked |
| D4 | L4 applies to reference files; payloads (`*-prompt.md` or named by a dispatch site) and naming `SKILL.md` are exempt | Best practices concern the *reader's* chains; a payload is read by a subagent | Banning all sibling mentions: forces sdd's reviewer payloads into SKILL.md |
| D5 | `Instruction Budget` is its own workflow with label event types and full history, required with `strict: true`; `Agent Workflow Tests` stays advisory | A size gate that cannot block is the current failure; the `ci.yaml` triggers cannot see label changes | Folding it into `ci.yaml`: label events do not re-run it, and the payload goes stale |
| D6 | Skill-text tests keep only text a tool or subagent consumes. That is: the dispatch marker lines and the `Agent(...)` call lines mirrored in `model-matrix.json`; the three carrier clauses `test_dispatch_contracts` places in dispatch regions; shell examples vetted by `test_shell_example_contracts`; frontmatter; JSON key sets of lifecycle contracts; `workflow-state`/`resolve-project` argv. Prose pins (~80% of `test_workflow_skill_contracts.py`, plus the phrase pins in `test_ship_release_contracts.py` and `WorktreesGuidanceTest`) are deleted in the slice that slims their skill. Heading anchors that only tests read may be renamed, with the test updated in the same commit. `docs/standards/agent-helpers.md` records the rule | The Bar, "tests that can fail": a phrase pin fails on rewording, not on behaviour | Converting pins to fuzzy "concept present" checks: same ratchet, weaker signal |
| D7 | Evals run working-tree skills in a temporary `CLAUDE_CONFIG_DIR`: `skills/` links the tree, the generated `settings.json`, `CLAUDE.md` and `agents/` are copied in, and the working tree's `agent_tools` commands are put ahead on `PATH`. If credentials do not carry over, the user runs `claude setup-token` once and the token is passed by env | Evals README: deployed skills shadow project copies; best practices: evaluate before and after | `just switch` per slice: it changes the user's live machine mid-run, and parallel slices would race |
| D8 | Each document has exactly one owning slice; S8 owns the shared ones (`agents/*.md`, `AGENTS.md`, `doc-grounded-questions`, `worktrees`). Slices run in parallel across owners (`max_parallel` 2), and `strict` protection serializes merges | The review found shared documents in up to 9 profiles | Parallel edits to shared documents: every slice would fight over the same ceilings |
| D9 | Skill names are kept; descriptions are rewritten to third person with a trigger clause | The guide accepts action names; the collection is consistent | Gerund renames: churn with no discovery gain |
| D10 | Upstream-pinned skills are outside `skill-lint` and the corpus ceiling | Nix does not author them; they bump via inputs | Patching upstream skills: a maintenance burden |
| D11 | Evals run on both Sonnet and Opus for heavy-skill owners | Best practices: test every model you use; `model-matrix.json` routes both | Opus only: hides a skill that over-relies on model strength |
