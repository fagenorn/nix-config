# Slim the repository CLAUDE.md (#330)

Follow-up to the #291 program, which deferred the repository `CLAUDE.md` to
this issue. It cites #291's rows as "#291 D6" and its own rows as "D1".

## Problem

Claude Code loads the repository `CLAUDE.md` in every session in this
repository. At the 2026-10-09 baseline (`8e2bfb72`) it is 5,342 words, and most
of them are not instructions. They are history and internals: the
transaction-core slices one by one, the lifecycle guard's tokeniser
semantics, the NInfer latency measurements, the plugin patch-merge procedure,
and `workflow-state` verb contracts. Anthropic's memory guidance asks for
concise, specific and actionable memory that points to detail instead of
holding it. Each session pays for all 5.3k words before it reads any code, and
an agent that needs one gotcha has to search a wall of prose for it.

## Solution

Cut `CLAUDE.md` to what an agent needs before it touches a file. That is at
most 2,136 words (0.40 × 5,342), and the plan aims for about 1,900 so that
later edits have room. Every removed fact goes to one home beside the code it
describes. If such a home already holds the fact, the fact is only deleted
from `CLAUDE.md`.

The retained `CLAUDE.md` keeps its section skeleton (intro, Commands,
Architecture, Key conventions & gotchas) and the generated bootstrap import as
its last line. Each section it slims ends in a pointer to the home that now
holds the detail.

## Decisions

### What stays (the retention rule)

A sentence stays in `CLAUDE.md` only if it is one of these:

- a command, or the verification rule (`just build` before claiming success);
- the architecture map: the flake → `lib/helpers.nix` → layered modules
  chain, `scanPaths`, `mergeFilesOrdered`, and the `myvars`/`libx` threading;
- an invariant or gotcha that leads an agent to a wrong edit if it is missing.
  Examples: edit settings in `default.nix` and never in
  `~/.claude/settings.json`; the zsh fragment order; the `homebrew-` tap-key
  prefix; never merge patch text; merge MCP servers into `~/.claude.json` with
  jq and never overwrite the file; never use `--bare` with `claude-local`;
  keep the guard's adversarial table green;
- a one-line pointer to a home. The pointer also says that new detail of
  that kind goes to the home and not to `CLAUDE.md`. Past plans have edited
  `CLAUDE.md` paragraphs directly, for example the helper-package paragraph in
  #204, #263 and #279, and without that redirect the next issue regrows the
  file. Those past plans are point-in-time records and keep their wording.

Rationale, history, measurements, internal algorithms, and per-verb helper
contracts move out (per D1).

### Where each block lands

Block IDs name the `CLAUDE.md` blocks at `8e2bfb72`. The plan expands each
block into its facts.

| Block | Content at base | Home |
|---|---|---|
| B1 | Commands: the CI and branch-protection paragraph | Condensed in place. The trigger and job detail is already in `ci.yaml`, `instruction-budget.yaml` and `branch-protection.json` |
| B2 | Agent helper package: `agent_tools`, launchers, `verified-tree`, `launch-scope`, `lane-triage`, the transaction-core slices 1–6, retained review evidence | New `python/README.md`; a 2–3 sentence summary stays |
| B3 | The #117 attempt-lifecycle decision paragraph | `python/README.md`, transaction-core section (the spec link moves with it) |
| B4 | Homebrew `--zap` shim rationale | Already in the `hosts/common/darwin-common.nix` comments; deleted only |
| B5 | Claude Code: settings materialization, `BASH_MAX_TIMEOUT_MS`, `show-claude-settings`, the full lifecycle-guard semantics, the guard/core decision, the plugin wiring, the `codex-plugin-cc` patch editing and test procedure, the `palmier-pro` MCP jq merge | New `home/common/claude-code/README.md`. Gotchas stay per the retention rule |
| B6 | Agent guidance and skills sourcing, Codex skill links, Impeccable packaging, retired skills, the Claude-only skills and the Codex stub, `.superpowers` path homes, launch-fenced workers | Existing `home/common/agent-skills/README.md`, new sections |
| B7 | `workflow-state` contracts: `build-delivery`, host admission, the anti-zombie bound and `mark-progress`, `resume-pack` | Existing `home/common/agent-skills/README.md`, "Lifecycle helpers" section |
| B8 | Local-model Claude Code: env choices, the `--exclude-dynamic-system-prompt-sections` rationale, both request shapes, the minimum NInfer revision, the shim's streaming and `coproc exec`, fan-out limits | New `home/linux/claude-local/README.md`. Facts already in `default.nix` or `anthropic-shim.py` comments are deleted only (per D2) |

Two homes are new READMEs (`python/`, `home/common/claude-code/`). The third is
the `claude-local` README. No new `docs/` file is added, and the
architecture binding still points at `CLAUDE.md` (per D3).

### How moved text is written

Text moves without being rewritten (per D2). The only edits allowed are
these: name the subject where the old sentence leaned on context in
`CLAUDE.md`, split a long paragraph into one subsection per command or
concern, and repair a pointer that was already dead at the base. One example
is `.out-of-scope/host-contention-scheduling.md`, which now lives under
`.agents/knowledge/rejections/`. A relocated fact must not contradict the code
it sits beside. When the plan finds a contradiction, it files an issue and
does not edit the code.

### Auditing criterion 2

The plan carries a fact-to-home table. Each row is one removed fact (a
sentence or clause of a B-block) with its destination: a path and a heading,
or a path and a line for a code comment. Each row is marked as moved or as
already present. The reviewer checks the diff against that table in both
directions. Every deleted `CLAUDE.md` sentence must map to a row, and every
row's destination must hold the fact at HEAD (per D4).

### Tests that read `CLAUDE.md`

- `CommittedProjectionTest` and `check-projections` require the managed
  import line exactly once. The slimmed file keeps that line as its last line
  and never edits it, so `just agent-workflow-tests` covers criterion 3.
- Four phrase pins in `test_workflow_skill_contracts.py` assert `CLAUDE.md`
  prose: the launch fence, the progress marker, the resume pack and
  `launch-scope`. They are deleted in the same commit that removes their
  prose (per D5).

## Test seams

- `just agent-workflow-tests`, existing, for criterion 3. That means
  `CommittedProjectionTest` and the `check-projections` tests, and every
  remaining test still passing after the pin deletion.
- `just build`, existing. The project's verification is still run, although
  no `.nix` code changes. Comments added to `.nix` files must still evaluate.
- `wc -w CLAUDE.md` compared with `git show 8e2bfb72:CLAUDE.md | wc -w`, for
  criterion 1. This is evidence recorded at review, not a committed test
  (per D6).
- Reviewer audit of the fact-to-home table, for criterion 2 (per D4).

No new test is written.

## Out of scope

- Any change to behaviour or code: Nix, Python, the guard, helpers, CI.
  Comments may be added only where the plan names a comment as a home.
- Rewriting, condensing or correcting relocated content beyond the edits D2
  allows.
- `.agents/instructions/bootstrap.md`, `AGENTS.md`, the generated import
  line, `.agents/project.json` (including the architecture binding), and the
  global `home/common/agent-guidance/AGENTS.md`.
- Bringing `CLAUDE.md` under the `Instruction Budget` gate or adding a
  word-count test. That changes the gate, which needs the user's
  `instruction-budget-raise` label (#291 D2). It is a possible follow-up issue
  (per D6).
- ADRs. Nothing here is hard to reverse, so no ADR qualifies.

## Triage

Input:

```json
{"signals":{"contract_change":{"value":"no","evidence":"documentation relocation only; CLAUDE.md is authored prose and the managed bootstrap import line is kept unchanged"},"concurrency_or_persistence":{"value":"no","evidence":"no code, locking or persisted state touched"},"open_design_questions":{"value":"doubt","evidence":"where each removed fact lands (existing spec/ADR vs new README beside the code) is a judgment call"},"criteria_shape":{"value":"hit","evidence":"the fact-preservation criterion is verified by reviewer audit, not a deterministic check"}},"paths":["CLAUDE.md","docs/architecture.md","home/common/claude-code/README.md","home/linux/claude-local/README.md","python/README.md"]}
```

Verdict:

```json
{"hits":["open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
```

Ran: full (shadow).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Retention rule: only commands, the architecture map, wrong-edit gotchas and pointers stay; rationale, history, measurements, internals and per-verb helper contracts move; each pointer redirects future detail to its home | Anthropic memory guidance (concise, actionable, point to detail); #291 "content moves to where it is used" | Trimming every paragraph proportionally: keeps the history in a shorter form and misses the 40% target. A pointer without the redirect: past plans (#204, #263, #279) appended to `CLAUDE.md` paragraphs, so the file would regrow |
| D2 | Every moved fact gets one home beside its code: an existing doc or comment first, otherwise a README in the code's directory. A fact already present in a comment is deleted from `CLAUDE.md`, not copied. Moved text is not rewritten, except to name the subject, split by concern and repair a pointer that was already dead | The Bar: DRY (one authoritative home), Moves keep their history; issue scope: rewriting is out | One `docs/agent-architecture.md` catch-all: far from the code it describes, and a second always-stale index. Rewriting while moving: hides lost facts from the audit |
| D3 | `CLAUDE.md` stays `bindings.paths.architecture` and keeps the architecture map; no `docs/architecture.md` is created | The resolved snapshot names `CLAUDE.md` as the architecture path; `project.json` is out of scope | A new architecture doc with the binding moved to it: a contract change, and the triage recorded `contract_change: no` |
| D4 | Criterion 2 is audited through a fact-to-home table in the plan: one row per removed fact, marked moved or already present, checked by the reviewer in both directions | Criterion 2 is a `[code]` reviewer audit; a table makes a both-way check finite | A free reviewer read of the diff: cannot show that no fact was dropped |
| D5 | Delete the four `CLAUDE.md` phrase pins in `test_workflow_skill_contracts.py` together with their prose, and do not re-point them at the new homes | `docs/standards/agent-helpers.md` rule 6 and #291 D6: phrase pins are deleted in the slice that slims their document | Re-pointing the pins to the READMEs: carries the ratchet that D6 removed into new files |
| D6 | No committed size check for `CLAUDE.md` in this issue; criterion 1 is measured evidence at review, and gating `CLAUDE.md` is left as a follow-up that the user decides | #291 D2: any change to the gate needs the user's raise label; scope stays tight. An advisory unit test would block nothing | Adding `CLAUDE.md` to `instruction-load.json` here: needs a new authorization. An advisory word-count test: the ungated ceiling pattern #291 found to be raised 45 times |
