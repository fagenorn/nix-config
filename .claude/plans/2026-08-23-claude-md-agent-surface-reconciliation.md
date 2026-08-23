# CLAUDE.md agent-surface reconciliation Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make `CLAUDE.md` true again about the agent surface it describes, so an agent
that reads it stops acting on a deleted plugin configuration, stops treating
`orchestrate-issues` as a Codex gap, and stops reading `~/.codex/skills/` as broken Nix
wiring.

**Architecture:** Prose-only correction, no configuration change. `CLAUDE.md`'s overloaded
"Global guidance has one source at ..." bullet splits into two siblings under the existing
**Claude Code is declaratively managed** list — a shared-surface bullet and a
Claude-only-surface-and-plugins bullet — and one stale comment line in
`home/common/claude-code/default.nix` loses a skill count that already drifted. Every
sentence dictated below was verified against the live modules before it was written down;
an implementer that finds a claim no longer true must fix the sentence, not ship it.

**Tech stack:** Markdown (`CLAUDE.md`), Nix / home-manager modules, `just build`
(`nix build .#darwinConfigurations.mbp.system`) for evaluation, `git grep` + shell for
content assertions. No new file, no new dependency, no new test.

## Global Constraints

- Nothing in the live configuration changes. The only files this plan may modify are
  `CLAUDE.md` and one comment line in `home/common/claude-code/default.nix`.
- Do not re-add Superpowers in any form — input, patch, marketplace or plugin.
- Do not change which agent any skill is exposed to, including `orchestrate-issues`.
- Do not touch `patches/agent-plugins/codex-plugin-cc.patch`, `lib/agent-plugins.nix`, any
  flake input, or `flake.lock`.
- Add no activation script — including a prune or a warning — that reaches into
  `~/.codex/skills/`.
- Delete nothing under `~/.codex/` during the pipeline; that stays the owner's one-time
  manual step, recorded in a commit body (per D3).
- Create no `docs/` tree, CONTEXT-MAP, ADR home or `docs/standards/`. `CLAUDE.md` remains
  the single context document.
- Do not rewrite or restructure `CLAUDE.md` beyond the two bullets named here.
- Never run `just switch`. Activation is the author's call.
- Never disable GPG signing: no `-c commit.gpgsign=false`, no `--no-gpg-sign`. Surface a
  signing failure rather than working around it.
- Every commit message ends with
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Test seams

- **There is no automated seam for documentation prose, and none is added** (per D7). No
  test in this repo references `CLAUDE.md`; `tests/test_agent_costs.py`,
  `tests/test_branch_protection.py` and `tests/test_claude_permission_guard.py` pin no doc
  wording. A wording-pinning test would fail on every legitimate edit.
- **The seam is a content assertion against the live modules.** Each task carries one
  re-runnable shell gate that cross-checks the prose it wrote against
  `enabledPlugins` / `extraKnownMarketplaces` / `home.file.".claude/skills/<name>"` in
  `home/common/claude-code/default.nix`, `marketplaceName` in `lib/agent-plugins.nix`, the
  contents of `patches/agent-plugins/`, the set of `home.file.".codex/…"` declarations, and
  the live `~/.codex/config.toml`. **Scope of that proof, stated exactly** (per D14): the gate
  pins the enabled-plugin count and both plugin names, each plugin's marketplace and that
  marketplace's source type, the `nix-codex` marketplace name, the one-file
  `patches/agent-plugins/` count, the two `~/.claude/skills` Claude-only links, the complete
  set of `home.file.".codex/…"` declarations, and the absence of a store-backed marketplace in
  the live Codex config. It does **not** pin the pinned flake input, the patch wiring inside
  `lib/agent-plugins.nix`, or the generated UI/UX skill's two destinations — sentences resting
  on those are verified by hand at authoring time and carry no automated guard. The gate
  proves the claims it enumerates and nothing about taste, completeness, or prose quality.
- **`just build` is the seam for the `.nix` edit only** (per D7). It runs in Task 2 because
  a `.nix` file is touched and the repo rule is unconditional. It proves the flake still
  evaluates and the darwin system still builds. It says nothing about `CLAUDE.md`; Task 1
  therefore does not run it.
- **The `superpower` sweep is scoped** (per D11): `.claude/plans/` and `.claude/specs/` are
  point-in-time artifacts and are excluded, `home/common/codex/default.nix` keeps its
  why-not module comment, and `CLAUDE.md` is checked by exact stale-phrase absence rather
  than by word absence, because the corrected clause itself names Superpowers.

Gate scripts are written to `"$(git rev-parse --show-toplevel)/.superpowers/gates/"` — inside
the working tree but ignored via `.superpowers/` in `.git/info/exclude`, so they are never
committed, and per-worktree, so they never collide with a parallel run. Deliberately **not**
under `.git/`: Claude Code treats `.git/` as a protected path and denies agent writes there,
which would block the sdd implementer subagent that has to run these gates
(`home/common/agent-skills/skills/sdd/scripts/sdd-workspace:11-15` records the same
constraint and the same working-tree remedy).

## Task index

Task 1 — Correct the CLAUDE.md agent-surface bullets — CLAUDE.md — full — [task-1.md](2026-08-23-claude-md-agent-surface-reconciliation.tasks/task-1.md)
Task 2 — Drop the stale skill count from the skillsDir comment — home/common/claude-code/default.nix — low-risk — [task-2.md](2026-08-23-claude-md-agent-surface-reconciliation.tasks/task-2.md)

Lane notes: Task 1 is `full` — it is a semantic-documentation rewrite of the repo's only
context document, which is the public contract every agent reads before touching the
agent-tooling modules; the mechanical lane excludes semantic-documentation effect and the
low-risk lane excludes public contracts. Task 2 is `low-risk` — a bounded single-comment
change in a `.nix` file, locally verifiable by `just build`, with no behavioral,
concurrency, lifecycle, destructive, security, release or migration surface. Neither task
is mechanical: both change what a reader is told.

## Decisions

The design spec at
`.claude/specs/2026-08-23-claude-md-agent-surface-reconciliation-design.md` owns the single
decision ledger; its rows are cited here by ID and never restated.

- Task 1 implements **D1** (record `orchestrate-issues` as Claude-only rather than exposing
  it), **D2** (the corrected install surface), **D3** (explain `~/.codex/skills/`; the
  one-time removal goes in the commit body and never gates the ship phase), **D4** (split
  the overloaded bullet), **D6 as amended by D13** (the `.superpowers/` clause is
  present-tense fact, not changelog — and names three distinct homes, not one directory) and
  **D10** (hedged on precedence: "duplicates", never "overrides").
- Task 2 implements **D5** (delete the count rather than update it) and **D7** (`just build`
  runs because a `.nix` file is touched).
- Planning appended **D11** (how the spec's `git grep -in superpower` seam is scoped to
  something achievable) and **D12** (why this plan ships as a two-member package).
- The Phase-5 standards review appended **D13** (the corrected `.superpowers/` prose) and
  **D14** (gate location outside `.git/`, and the gate's proof scope stated by enumeration).
  Both tasks carry D14; Task 1 carries D13.

Carry into the handoff, not into a task: the spec asks that the owner be told the stale
`~/.codex/skills/codebase-design` copy predates the **test seam** definition the `design`,
`writing-plans` and `sdd` skills all lean on, so a Codex session reading that copy works
from a smaller vocabulary than the shared tree defines. That is context for the manual
cleanup, not work this plan performs.

---

## Standards review provenance

- **Reviewer:** Codex, in an isolated read-only runtime (fresh `CODEX_HOME`, approval policy
  `never`, sandbox `read-only`). No native fallback was used.
- **Reviewed at:** base SHA `a3e13184274507e7c7f7623a3773df752af39678`, branch
  `worktree-issue-105`, plan package HEAD `43a9821`.
- **Focus:** none configured (`codex.planReview.focus` unset); standard review bar applied.
- **Findings:** 4 raised — 2 Blocking, 2 Should fix, 0 Discussion. **4 accepted, 0 rejected,
  0 deferred.** Every finding was re-verified against the live worktree before it was applied.
- **Dispositions:** the gate-location blocker and the gate's overstated proof scope are
  recorded together as **D14**; the `.superpowers/` prose blocker is recorded as **D13**,
  which amends **D6**. The two pre-edit gate narratives were corrected in `task-1.md` and
  `task-2.md` as routine factual fixes and carry no ledger row.
- The reviewer's transcript is deliberately not stored in this repository.
