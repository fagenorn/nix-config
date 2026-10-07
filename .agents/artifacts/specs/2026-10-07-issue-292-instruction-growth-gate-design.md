# Instruction growth gate (#292)

Slice S1 of the [program spec](2026-10-07-issue-291-skill-best-practices-design.md)
(#291). Rows of that spec are cited as "program D4", its rules as "L1"–"L5",
its gate steps as "gate step 1"–"gate step 4"; rows of this spec's own ledger
are cited as plain "D3". Nothing the program settles is restated here.

## Problem

Instruction size only grows. The one size check (`instruction-load.json`'s hot
ceilings) sits inside an advisory job, covers only hot bytes, and is raised by
the same PR whose prose needs the room. The best-practice rules that a machine
can check (program L1–L5) are checked nowhere. The user wants growth to become
their decision: a PR that grows agent instructions should go red until they say
yes, and a PR that cuts prose should bank the cut.

## Solution

Program "The gate" section, built as follows:

1. **`skill-lint check`**, a new `agent_tools.skill_lint` module with a
   command-table row, enforces L1–L5 over the authored skill trees. Today's
   violations are recorded in a shrink-only debt file (D5, D6).
2. **`instruction_load check` and `tighten`**, two new subcommands of the
   existing module. The model gains conditional, corpus and description
   ceilings (D3, D4). `check` runs gate steps 1–4 in order; `tighten` lowers
   ceilings to measured (D7).
3. **The `Instruction Budget` workflow**, its own file and job, triggered as
   program D5 says. It runs `check` against `HEAD^1` on a pull request, and
   with no base on a push to `main` (D9, D10).
4. **Branch protection**: `.github/branch-protection.json` requires `Nix Eval`
   and `Instruction Budget` with `strict: true`. The live protection is applied
   by the user after merge (D2).
5. **`just agent-instruction-budget`** runs `check --base origin/main` locally
   (D9).
6. **The test policy**: `docs/standards/agent-helpers.md` gains the skill-text
   test rule (program D6) (D13).

The PR that adds the gate passes its own gate without the label (D1). It does so
because its ceilings are set by `tighten`, and because raise control has no base
gate to compare against.

## Decisions

### `agent_tools.skill_lint`

- **Owns the skill-tree knowledge** that the lint and the corpus ceiling share.
  That covers the list of authored tree roots, the classification of a skill
  directory's files (SKILL.md, reference file, payload, and the `evals/` and
  `scripts/` exclusions, per the program's Vocabulary), the reflowed-line
  count, frontmatter parsing, and the matcher that decides when one document
  names another. `instruction_load` imports these and does not copy them
  (D3, D11).
- **Authored trees** are the shared, Claude-only and Codex skill source roots.
  Upstream-pinned skills never appear under them, so program D10 holds
  structurally and needs no exclusion list (D3).
- **Rules and their keys.** Every violation has a stable key of the form
  `<rule> <repo-relative path>`. The rules are `L1`, `L2`, `L3`, `L4a`
  (a reference file its `SKILL.md` does not name), `L4b` (a reference file
  naming a sibling reference file; the key appends ` names <basename>`) and
  `L5`. One line of human text follows each key.
- **Frontmatter** is the block between a leading `---` line and the next
  `---` line, read as `key: value` lines with single-line scalars, optionally
  quoted. A block scalar, a missing fence or a duplicate key is itself an L1
  violation. No YAML library is used (D12).
- **L4 scope.** L4 judges same-skill siblings only; cross-skill mentions are
  composition (program "Out of scope"). A payload is a `*-prompt.md` file, or
  a reference file whose basename appears on the `call` line of a
  `model-matrix.json` dispatch site in the same skill (D11).
- **Debt file.** The debt file is `home/common/agent-skills/skill-lint-debt.json`,
  shaped `{"debt": [<key>, …]}`. It is loaded through the canonical strict-JSON
  hooks, and its keys must be sorted and unique. `check` fails on a violation
  whose key is not listed. It also fails on a listed key that no violation
  produces any more (a stale entry), so a fix must also delete its debt entry
  (D5).
- **CLI.** `skill-lint check [--root <repo>]` lints the working tree. It exits
  0 when clean, 1 on violations or stale entries (one line each), and 2 when it
  cannot run (an unreadable or malformed debt file, or a missing tree root).
  The module is a thin shell over an importable `lint` function. That function
  reads through the snapshot seam (see Test seams) and returns a list of
  violations.

### `agent_tools.instruction_load`

- **Model schema** (D4). Each profile gains `conditional_ceiling_bytes`, a map
  from host to bytes keyed exactly like `ceiling_bytes`, which stays the hot
  ceiling. The top level gains `corpus_ceiling_bytes` and
  `description_ceiling_bytes`, each a single non-negative integer. All three are
  required, and `validate` reports them the way it reports `ceiling_bytes`
  today. `report` is unchanged.
- **Measurement** (D3). `measure` adds two numbers. `corpus` is the bytes of
  every `.md` file in an authored skill directory outside `evals/` and
  `scripts/`, plus every `.md` file in the agent-definitions directory, plus the
  frame. `descriptions` is the UTF-8 bytes of every authored `SKILL.md`'s
  frontmatter `description` value. Neither number is per host.
- **`check [--base <rev>] [--raise-label] [--root <repo>]`** reads the head
  from the working tree and the base through `revision_reader`. It reports
  every failing step rather than stopping at the first, with each line prefixed
  by its step (`lint`, `ceiling`, `tightness`, `raise`, `debt`) and each naming
  its remedy. It exits 0 when every step passes, 1 when any fails, and 2 when it
  cannot run (an unknown base, or a head or base model that does not load
  strictly). The steps are:
  1. `skill_lint.lint` with the debt file, as `skill-lint check` runs it.
  2. The head model validates, and no hot, conditional, corpus or description
     ceiling is below its measurement.
  3. Tightness: `100 × ceiling ≤ 105 × measured` for every ceiling (D7).
  4. Only with `--base`, and only when the base carries the gate workflow (D1):
     - Raise control (D8). The head model must equal the base model after
       lowering-normalisation, and no gate file may differ from the base,
       unless `--raise-label` is given.
     - The debt-file key set at head must be a subset of the base's. The label
       does not waive this.
- **Gate files** are listed once, in `instruction_load`: the workflow file, the
  `skill_lint` and `instruction_load` modules, the debt file and
  `branch-protection.json`. Because the list lives in a gate file, changing it
  needs the label. A file counts as edited when it is added, removed or changed
  between base and head.
- **`tighten [--root <repo>]`** loads and validates the working-tree model and
  measures it. It sets every ceiling above its measurement to that measurement,
  leaves every ceiling at or below its measurement alone, and rewrites the file
  in its existing canonical form (two-space-indented JSON with a trailing
  newline, which the live file already round-trips). It never raises a ceiling,
  so it cannot clear a breach (D7).
- The parser keeps `prog="agent-instruction-load"`. The remedy text for a loose
  or breached ceiling names `just agent-instruction-load tighten`.

### The workflow and protection

- `.github/workflows/instruction-budget.yaml`, workflow and job both named
  `Instruction Budget`. It triggers on `pull_request` (`branches: [main]`,
  `types: [opened, synchronize, reopened, labeled, unlabeled]`) and on `push`
  to `main`. Permissions are `contents: read`. Concurrency is one group per PR,
  cancelling the PR's earlier runs, and keyed by event and SHA otherwise, after
  `ci.yaml`'s precedent.
- The single job is plain: no `if:`, `needs:`, `continue-on-error:`,
  `strategy:` or `uses:`, which keeps the existing green-without-work pins
  valid. Its steps are a checkout with `fetch-depth: 0`, then one `run` step.
  That step reads the event name and the label's presence from `env`, where the
  label's presence is computed by an expression over
  `github.event.pull_request.labels`. On a pull request it calls `check --base
  HEAD^1`, adding `--raise-label` when the label is present; otherwise it calls
  `check` with no base. It runs `PYTHONPATH=python python3 -m
  agent_tools.instruction_load` on the runner's own interpreter, with no Nix
  install (D10).
- `.github/branch-protection.json` sets `strict: true` and requires two checks,
  `Nix Eval` and `Instruction Budget`, both with `app_id` 15368. The other keys
  are unchanged.
- Comments that call `Nix Eval` the sole required context (in `ci.yaml`, the
  `protect-main` recipe and `CLAUDE.md`'s CI paragraph) name both contexts.
  `CLAUDE.md` gains one Commands line for `just agent-instruction-budget`. No
  other `CLAUDE.md` text changes (program "Out of scope").

### Local entry, Nix, test list

- `just agent-instruction-budget *args` runs `check --base origin/main {{args}}`
  from source. A local run that needs the label's waiver passes `--raise-label`
  explicitly. The recipe never fetches (D9). A branch behind `origin/main`
  reports main's later changes as its own edits, so it should be synced before
  the result is read; CI compares the merge commit and has no such skew.
- `lib/agent-tools.nix` gains the `skill-lint` row. The import check already
  walks every module, so it needs no edit.
- `just agent-workflow-tests` gains `test_skill_lint.py`. The other two suites
  are already listed.

## Test seams

These are the program's seams (program "Test seams"); this slice adds no other.

- **The snapshot seam.** The existing `Reader` (a path to bytes) gains a
  listing companion that returns every repository-relative file path. The
  working-tree and revision readers each provide one, and tests build both from
  one `dict`, in the style of `test_instruction_load.py`'s `dict_reader`. The
  corpus and the lint need it, because both enumerate trees.
- **`test_skill_lint.py`** (new). Fixture trees fail each rule in turn: L1 in
  every listed form, L2 at 500 and 501 reflowed lines (including one long
  line), L3 with and without contents, L4a, L4b with a payload exemption and a
  `SKILL.md` exemption, and L5 in both forms. Further cases cover debt
  suppression, a stale debt entry, an unsorted debt file, and the CLI exit codes.
  One live-tree test runs the live debt file.
- **`test_instruction_load.py`** (extended). Two in-memory revisions drive
  `check`. Each mutation in the issue's raise list fails without
  `--raise-label` and passes with it. A grown debt file fails both ways. A loose
  ceiling fails, and `tighten` then passes it with no ceiling raised. A breach
  survives `tighten`. A base without the gate workflow skips step 4, and a
  lowering-only change passes unlabelled. Live tests cover the live tree's
  tightness and the new ceilings. One CLI test over a temporary git repository
  pins the exit codes and `--raise-label`, after `ReportCommandTest`.
- **`tests/test_branch_protection.py`** (rewritten). It parses every workflow
  under `.github/workflows/` with the existing indentation parser. It pins that
  each required context is exactly one plain job, and the green-without-work
  bans on both required jobs. On the new workflow it pins the five
  pull-request types, the push trigger, `fetch-depth: 0`, the payload-derived
  label, and the `instruction_load check` invocation, the analogue of the
  `nix eval` pin. It also pins the exact protection payload.

## Acceptance criteria → measurement

| Criterion (issue order) | Measured by |
|---|---|
| `skill-lint check` reports L1–L5 on fixtures, fails outside the debt file, passes live | `test_skill_lint.py` in `just agent-workflow-tests` |
| `check` fails the eight listed edits, passes the first seven with the label, fails a grown debt file either way | `test_instruction_load.py` |
| `check` fails a ceiling above measured × 1.05; `tighten` fixes it without raising | `test_instruction_load.py` |
| Protection declares both contexts, `strict: true`; workflow has the label types and full history | `tests/test_branch_protection.py` |
| [evidence] Live protection lists both contexts, strict on | `just show-protection` after the user runs `just protect-main` post-merge (D2); remaining evidence in the ship handoff |
| Every ceiling on this branch within 5% | `Instruction Budget` green on this PR (D1) |

## Out of scope

- S2: the guard's refusal of label verbs, and skill or `AGENTS.md` prose about
  who applies the label.
- Any skill slimming, any rewritten description, any deleted prose pin
  (S4–S8). L5 debt is recorded rather than fixed (D6).
- Evals (S3), and `CLAUDE.md` slimming beyond the context mentions above.
- New `report` columns for the new ceilings, and a command-table row for
  `instruction_load`.
- Creating the `instruction-budget-raise` label, applying live protection, or
  any other forge write (D2).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Bootstrap: step 4 (raise control and debt shrink) runs only when the base revision contains the gate workflow file; steps 1–3 always run, so this PR is gated by tightness and lint but not by a label | The issue requires `Instruction Budget` green on this PR; a base without the gate has nothing to protect; afterwards every base carries it, and deleting it is itself a gate-file edit | Requiring the label on this PR (contradicts the acceptance criterion); a one-off allowlisted SHA (hidden state in a gate file) |
| D2 | `just protect-main` is run by the user after merge; the [evidence] criterion is reported as remaining evidence; no agent step applies live protection or creates the label | Live protection is outside the delivery contract and must not require a context that `main` cannot yet report; forge writes are not the agent's to authorize | Agent-applied protection before merge (would block every other open PR on an unreportable context) |
| D3 | Corpus = `.md` files of authored skill dirs outside `evals/`/`scripts/` + agent definitions + frame; descriptions = frontmatter `description` value bytes summed over authored `SKILL.md`; both host-agnostic single numbers; authored trees = the three source roots, so upstream skills are excluded structurally | Program gate step 2 and Vocabulary; program D10; `evals/` and `scripts/` are never loaded as instructions | Per-host corpus/description ceilings (no route loads "the corpus" per host); counting every file (LICENSE, JSON evals are not instructions) |
| D4 | Additive schema: per-profile `conditional_ceiling_bytes` beside the unchanged `ceiling_bytes` (hot); top-level `corpus_ceiling_bytes`, `description_ceiling_bytes` | Keeps `report`'s consumers and existing tests intact; program D1 keeps one budget file | Reshaping `ceiling_bytes` into `{host: {hot, conditional}}` (breaks every consumer for no gain) |
| D5 | Debt file `skill-lint-debt.json` = sorted unique violation keys only; a stale entry fails lint; shrink = head key set ⊆ base key set, so debt cannot follow a renamed or split file and must be paid there | Program gate step 4; stale-entry failure banks fixes the way tightness banks cuts (program D3); byte growth of a debt file is already caught by the ceilings | Recording measured line counts per entry (duplicates the byte budget's job); silently tolerating stale entries (the debt never visibly shrinks) |
| D6 | L5 violations (five descriptions today) are recorded as debt too, although the issue names L1–L4 | Program D8 gives those documents to S7/S8 and program D9 schedules description rewrites there; one description is pinned by a test; new skills still must pass L5 | Rewriting five descriptions in S1 (edits documents another slice owns and a prose pin) |
| D7 | Tightness is the integer test `100 × ceiling ≤ 105 × measured`; `tighten` sets every ceiling above measured to measured, never raises, and rewrites in the file's canonical form | Program D3; integer arithmetic has no rounding to argue about; a zero measurement then demands a zero ceiling | Float `measured * 1.05` with rounding (edge-dependent); tightening only ceilings outside the 5% band (leaves slack to refill) |
| D8 | Raise control compares head to base after lowering-normalisation: each head ceiling at or below its base value is set to the base value, and anything still unequal (any raise, profile, host, member move, `excluded_sites`, note or key) needs the label; the label waives only that and gate-file edits | Program gate step 4: "any change other than lowering a ceiling"; one equality test covers every listed and unlisted edit | Enumerating allowed edit kinds (an unlisted edit slips through) |
| D9 | `check` reads head from the working tree and base via `revision_reader`; `--base` absent = push mode (steps 1–3); the label is the explicit `--raise-label` flag, which CI derives from the event payload and a local run passes by hand | Program: label read from the payload, no API permission; one code path in CI (working tree = merge commit) and locally (pre-commit work) | Querying the forge for labels (needs a token and network); reading head from a revision (local runs could not check uncommitted work) |
| D10 | CI runs `check` from source on the runner's `python3`, with no Nix install, and branches on event in shell, not a step `if:` | Package has no dependencies; `Agent Workflow Tests` already uses the runner's `python3`; existing pins ban step-level `if:` on required jobs; a required check should have few failure sites | Calling the `just` recipe (needs Nix to provision `just`, and its base is `origin/main`, not `HEAD^1`) |
| D11 | Payload = `*-prompt.md`, or a reference file whose basename is on a same-skill dispatch site's `call` line (dispatch sites carry no prompt field); L4 judges same-skill siblings only; the naming matcher moves to `skill_lint`, and `instruction_load` imports it | Program D4 and Vocabulary; the matrix's site shape; `REVIEW-CONTRACT.md` is named on its site's call; the bar's DRY | Treating `unread` profile members as payloads (`unread` also means "not this route"); two copies of the matcher |
| D12 | Frontmatter is parsed as fenced single-line `key: value` scalars; any other shape is an L1 violation | The package has no dependencies (stack shard: environment declared); every live skill already fits; fail loud on what the parser cannot vouch for | Adding PyYAML (a new dependency for one block) |
| D13 | The skill-text test policy becomes rule 6 of `docs/standards/agent-helpers.md`, and the standards README's `governs` column gains `home/common/agent-skills/tests/**` so the rule loads where those tests are edited | Issue item 6; the README is how a shard is selected | A new standards shard (one rule does not warrant a file) |
| D14 | Accepted limit: on `pull_request` the job runs the head's own workflow and checker, so a PR that edits a gate file can neuter its own run; the gate-file rule catches the honest edit, and a neutering edit stays visible in the diff the user reviews | Program D2 (the label is a human signal, not airtight; the protection that holds is the required check plus the user's review); `rejections/ungated-agent-merges.md` | `pull_request_target` running the base's checker over head data (never runs on the PR that adds the workflow, so this PR could not go green, and it widens the token's event scope) |
