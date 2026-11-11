# Agent skills — project adapter contract

The skills in `skills/` are project-agnostic: they carry zero project residue and read everything
project-specific through one retained `ResolvedProject` snapshot at each phase entry. A new project
onboards through the project contract; included documents receive the owner's snapshot and never infer policy.

| Surface | Lives at (per repo) | Carries |
|---|---|---|
| **Values** | `.agents/project.json` | Tracker, branches, verify commands, doc paths, naming — every binding the skills resolve. See the per-skill "Keys used" lines. |
| **Prose hints** | paths in `bindings.paths.hints` | Project-specific prose the generic skills receive from the retained snapshot. |
| **Domain language** | `docs/CONTEXT-MAP.md` + `docs/areas/<area>/CONTEXT.md` | The map is an index (≤150 lines): areas, term → area table, `governs:` globs (root-relative). Area files are budgeted glossaries. Format: `skills/grill-with-docs/CONTEXT-FORMAT.md`; linter: `~/.agents/bin/context-map-lint`. |
| **Decisions** | `docs/areas/<slug>/adr/` — every area's own, including the reserved `system` area for decisions no single area owns | 1–3 sentence records, gated on hard-to-reverse AND surprising AND real-trade-off. Ids are `ADR-<slug>-NNN`, numbered per directory from `001`; no global sequence. Format: `skills/grill-with-docs/ADR-FORMAT.md`. |
| **Standards, Layer 2** | `docs/standards/` + ≤40-line README index with `governs:` globs | Project deltas only. Layers 0–1 are machine-global: `~/.agents/standards/the-bar.md` (universal) and `~/.agents/standards/stacks/*.md` (per-stack trap libraries) — a new project inherits both for free. Precedence: direct instruction > project > stack > bar > convention. |
| **Rejection KB** | paths in `bindings.paths.rejections` | One file per consciously-rejected direction; `to-issues` checks it before proposing slices. |
| **Decision maps** (optional) | tracker issues labelled `wayfinder:*`; no tracker → `.claude/wayfind/<effort>/` | Big fuzzy efforts charted by the `wayfind` skill; an owner's fog gate emits decision tickets into them. The markdown fallback lives under `.claude/` because the docs root is reserved (see the linter's layout rules). |

## The `bindings.paths.hints` binding

`bindings.paths.hints` in the retained snapshot names the prose-hints files:

- Each path is explicit and is read only by the consuming phase; an empty list
  means that phase receives no hints.

Hints are read **only by the consuming agent at the moment of use** — never loaded into an
orchestrator context.

## Onboarding a new project

1. Copy a sibling project's `.agents/project.json`, edit the values, and use
   `resolve-project write-projections` to generate its entries.
2. Write the map skeleton: `docs/CONTEXT-MAP.md` with one area (or run a `grill-with-docs` session
   and let the first terms create it).
3. Optionally seed `docs/standards/README.md` (empty index) and `.claude/hints/`.
4. Everything else is machine-global via nix (`home/common/agent-skills/`): the skills, the
   standards layers 0–1, and the linter arrive with the home-manager generation.

## Vendored skills

A directory under `skills/` may be a **vendored adaptation** of an upstream skill rather than an
authored one. Such a directory carries the upstream `LICENSE` inside it as its provenance record: the
upstream URL, the pinned revision, the date it was inspected, and every way the adaptation departs
from upstream, followed by the upstream notice reproduced unmodified. Keeping the notice in that file
and out of `SKILL.md` keeps it out of the body that loads with the skill, while `SKILL.md` still
links to it so the provenance is one hop away.

A refresh is a manual comparison against a newer revision, made by hand and not at build time
(ADR-delivery-003): re-apply the recorded adaptations and move the pin.

## Global guidance and skill sources

Nix writes nothing under `~/.codex/` and nothing under `~/.agents/skills/` (ADR-delivery-001), so Codex gets no guidance file, skill view or config splice, and its own runtime state is neither populated nor pruned. The global guidance reaches Claude alone, as `~/.claude/CLAUDE.md` through `programs.claude-code.memory`, and the skills reach Claude through `skillsDir`.

## Impeccable

Impeccable (`pbakaus/impeccable`) is pinned by the `impeccable` flake input to an immutable `skill-v<version>` tag. `lib/impeccable.nix` builds it once into one derived skill tree. The tree is upstream's `.claude/skills/impeccable` unchanged, plus the host system's pinned prebuilt design-detector engine in the launcher's sibling slot `scripts/bin/<os>-<arch>/impeccable`. Claude gets that tree through a recursive `~/.claude/skills/impeccable`. `~/.agents/bin/impeccable` puts the detector on PATH by exec'ing the tree's own launcher. Detector availability is that pinned engine. It is never downloaded on demand, and nothing is installed under `~/.impeccable/bin/`, although the engine may still write runtime caches under `~/.impeccable`. The session sets `IMPECCABLE_NO_UPDATE_CHECK=1` because Nix owns the version. For the same reason, the store-writing verbs (`update`, `install`, `link`, `pin`) cannot change the Nix-owned tree. A bump edits the input's tag, the engine version and both hashes in `lib/impeccable.nix` together. Evaluation fails when the engine version and the tree's `scripts/VERSION` disagree, and on any system other than `aarch64-darwin` or `x86_64-linux`.

## Retired skills

Skills that are no longer installed are listed in `retiredSkillNames` in `home/common/agent-skills/default.nix`. Home Manager's own cleanup removes their old links on switch, and an activation step then warns about any retired skill directory that is still present, without deleting anything.

## Claude-only skills

Three skills are linked only into `~/.claude/skills/` from `home/common/claude-code/skills/`: `codex-collaboration`, `deliver-standard` and `deliver-batch` (ADR-delivery-002). `deliver-batch` (#637) replaced `orchestrate-issues`; its `SKILL.md` starts the Workflow-tool program `deliver-batch.js`, which stays beside `deliver-standard.js` in the `deliver-standard` directory. `deliver-standard`'s `SKILL.md` starts the Workflow-tool program `deliver-standard.js` beside it, and `home/common/agent-skills/tests/test_deliver_standard_program.py` runs that program's control flow under `node` against stub agents. Its args take a claim holder id (`session_id` or `batch_id`), `mode` (`plan`, `ready` or `ship`) and `lane: direct`; it holds the issue with a `forge-claim` claim, renewed at every stage boundary and released at close-out, and `deliver-direct` step 1 claims and releases through the same `forge-claim`. `deliver-batch.js` ships in the same directory and delivers a batch of one repo's issues through `deliver-standard.js` children: a standard-lane issue first runs its child in `mode: plan` under a plan-ahead queue of `max_parallel` slots, keeps that slot until a delivery slot is free, which it takes ahead of every waiting issue that is not planned, then resumes the returned `cont` in `mode: ready` (#744), while a direct-lane or re-adopted issue goes straight to a delivery slot; with just-in-time `forge-claim` claims, a serial land queue under `forge-claim land`, and owner asks through `forge-claim owner-action`: a session-launched run returns its decision questions, conflicts and needed labels to the session and posts nothing, while an unattended run (`unattended: true`) posts decision questions as box prompts, which the child reads once fully ticked, and conflicts and needed labels as markers. A returned batch is continued as a new run on its `relaunch`, which forwards each unfinished child's `cont`, never by resuming the run, because a resume replays its tracker reads; it opens a PR only at an `Accepted head:` it records and re-adopts one only there, and its breaker reads the child's `dead_agents`. `home/common/agent-skills/tests/test_deliver_batch_program.py` runs it against stub agents and a stub child workflow.

`deliver-standard.js` takes `review_sizing` (#747; default off, a trial). On, when the Codex plan review is configured and available, the Claude plan review checks only the acceptance-planning rules, the project's documented conventions and docs, and the plan's internal consistency, and leaves code correctness to Codex; and when the three-tasks-per-chunk rule would split the final review, a clerk step first adds up the `git diff --shortstat` insertions and deletions of the delivery range and every declared branch range, and the review is chunked, with its integration review, only above 1500 changed lines (a size the clerk could not read, a failed command or a failed step keeps the chunks; a resume that skips the final review reports the shape it had, from `cont.final_reviewed.whole`). Off, both reviews run as before. The setting is an argument, never kept in `cont`; `deliver-batch.js` takes the same argument and passes it to every child and its `relaunch`. The trial's findings and token readings are the orchestrator's own observations, not program output.

`deliver-standard.js` and `deliver-batch.js` take `clerk_model` (#803; `sonnet`, the default, or `haiku`, a trial): it sets the model of every clerk call of both programs, and any other value is refused at args. `home/common/claude-code/agents/clerk.md` stays on Sonnet and every other agent type is unchanged, so nothing changes unless the trial is on. Like `review_sizing` it is an argument, never kept in `cont`, and `deliver-batch.js` passes it to every child and its `relaunch` when it is `haiku`. The trial's token, cost and schema-failure readings are the orchestrator's own observations, not program output.

`deliver-standard.js` takes `amend` (#811) on a resume whose cont carries a standard-lane plan: a list of `{file, find, replace}` edits of files in the plan directory (`file` relative to it, or an absolute path under it). A clerk runs the `plan-amend` command, which applies them all or none, after renewing the claim when the plan was reviewed. The command adds one line per edit under `## Amendments` in plan.md naming the stop it answers, before the next task, and skips an edit already recorded there. A file outside the plan directory (by spelling or through a symlink), a missing file, or a find text that does not occur exactly once stops at stage `amend` with the cont unchanged. `amend` is an argument, never kept in cont, and the amended plan is not reviewed again. `deliver-batch.js` takes `amend` as `{"<issue>": [...]}` beside `conts` and checks every entry before any agent. It sends each list with its cont to the first child call of the run, and keeps it in its `relaunch` with that cont, where an edit already applied is skipped. Every stop of a child after its amend was applied carries `amended: true`, and `deliver-batch.js` then drops that issue's amend from its `relaunch` (keeping the cont), so a relaunch that has to plan again is not refused by an amend that is already in the plan.

## .superpowers paths

The `.superpowers/` name is historical: it is a git-ignored home for run state that no skill commits, and the tracked `.gitignore` is the backstop for it (`.git/info/exclude` is machine-local and cannot be). The one home live skills still use is `.superpowers/workflows/<run-id>/`, whose `handoffs/` directory is the only place the `handoff` skill accepts a caller-provided destination for the current run. There is no Superpowers input, patch, marketplace or plugin in this repo.

## Code map

The `design` skill leaves a code map for the planner: a navigation lead (ADR-delivery-004, #354). It is one Markdown file in the git directory of the worktree the design ran in (`git rev-parse --git-dir`), named after the spec file with `.code-map.md` in place of `.md`. That is outside the working tree, so it is never staged, committed, pushed or reviewed, no artifact-budget kind measures it, and in a linked worktree it goes when the worktree is removed. A rerun of `design` on the same spec overwrites it; the grill and the planner's ledger appends leave it alone, so it may be stale when it is read.

Its first line is a title naming the spec file. Each entry names a module, seam or contract the spec's Decisions decide about, with a `Why:` line, a `Code:` line and a `Tests:` line; a path is repository-relative and stands outside parentheses, and its symbols or test names follow in parentheses. It holds no decision, requirement, rationale, line number or code excerpt, and only what the design agent had already read. When it cannot be written, the design still completes and its `notes` say so.

The deliver-standard planner leaves a second code map (#743), `context.md` beside `plan.md` in the program's plan directory (`<worktree git dir>/deliver-standard`), so it is never committed either. Unlike the design map, it carries line ranges. Per area the plan touches, it lists the files and symbols, their tests and fixtures, the callers that matter and the facts the planner confirmed, each with a pointer. The program names it as read-first to the plan reviewer, the Codex plan review (as a lead, never evidence), the plan reviser and each task's implementer and fixer. They open the code to check a claim it makes or where it is silent, and a reviewer checks against HEAD any claim a finding relies on. The task reviews, the final review and its fix waves get no map, so they judge the code alone. The direct lane has no planner and no map, and `deliver-batch.js` gets the map through its `deliver-standard.js` children.

`writing-plans` looks for it at the path its caller named, else by that naming rule, before it maps files. It takes the entries as leads, checks every mapped path and symbol it writes into a task against the current tree, and never cites, links or copies the code map into the plan. With no code map it plans as before. The autonomous plan dispatch names the file; the design dispatch and the interactive Phase 4 text do not mention it.
