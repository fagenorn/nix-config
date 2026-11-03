# Subagent start-up trim: brief-driven agents without CLAUDE.md, hidden skills, an orchestration launcher without claude.ai connectors — issue 425

Design for https://github.com/fagenorn/nix-config/issues/425. A bare "Dn" cites this
spec's ledger. Base: `04a39660` (origin/main). Binary facts are from the strings of the
pinned Claude Code 2.1.302; probe facts are from three `claude -p --model haiku` runs on
mbp on 2026-10-25 in a scratch directory (no overrides, `--settings` overrides, and
`ENABLE_CLAUDEAI_MCP_SERVERS=false`), read from their transcripts.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "adds a new orchestration launch command and changes generated settings and agent-definition frontmatter"}, "concurrency_or_persistence": {"value": "no", "evidence": "static Nix-generated settings, agent frontmatter and a launcher script; no locking or persisted state"}, "open_design_questions": {"value": "hit", "evidence": "the issue's first task must establish which setting can hide claude.ai-provided skills, and the launcher's shape is open"}, "criteria_shape": {"value": "hit", "evidence": "two of four criteria are [evidence] measurements (agent-costs before/after, eval verdict) no deterministic code check verifies"}}, "paths": ["home/common/claude-code/agents/mechanic.md", "home/common/claude-code/agents/reviewer-lite.md", "home/common/claude-code/default.nix", "home/common/claude-code/accounts/bin/claude-account", "home/common/claude-code/README.md", "home/common/agent-skills/tests/test_dispatch_contracts.py", "home/common/claude-code/skills/orchestrate-issues/SKILL.md"]}
Verdict: {"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

Every subagent pays a fixed start-up bill before it does any work, and the cache report
of issue 421 (`just agent-costs --report cache`) now shows it per agent type:

- the skill listing, sent to every agent that has the Skill tool: about 24k characters
  in an interactive session (20,786 in the `-p` probe, 18,906 for a `mechanic` subagent
  in this repository), a third of it skills no pipeline agent uses: Office-format and
  Google skills, a morning brief, a memory import, a chart guide, three Artifact guides
  and a second copy of skill-creator;
- the user, project and local `CLAUDE.md` files: in this repository about 14.4 KB
  (`CLAUDE.md` 12,584 bytes, its imported `bootstrap.md` 1,231, the user file 616), which
  the brief-driven leaf agents (`reviewer-lite`, `mechanic`) never need, because their
  dispatch brief carries everything;
- claude.ai connector instructions and tool names: in the probe, one connector's
  instructions (2,157 characters) and 25 `mcp__claude_ai…` names in the deferred-tool
  list (4,112 characters against 746 without them), which no orchestration agent uses.

## Solution

Three independent trims, each with its test:

1. `reviewer-lite` and `mechanic` declare `omitClaudeMd: true`; `implementer` and
   `reviewer` keep their instruction files.
2. The generated settings carry `skillOverrides` that hide twelve skill entries from the
   model's listing.
3. A new command, `claude-orchestrate`, starts Claude Code exactly as `claude` does but
   with claude.ai connectors off. Plain `claude` keeps them.

Demo: start an orchestration session with `claude-orchestrate`, dispatch one
`reviewer-lite` (and one `mechanic`, which unlike it carries a skill listing), and read
their start-up rows in `just agent-costs --report cache`: no `CLAUDE.md`, none of the
hidden skills, no claude.ai MCP instructions.

## Decisions

### Brief-driven agents run without CLAUDE.md

`omitClaudeMd` is an agent-frontmatter boolean: "Run this agent without the user,
project and local CLAUDE.md instruction files when it runs as a subagent; managed policy
files are kept. … No effect on the main session agent." The built-in Explore and Plan
agents already set it. Here it removes the global guidance (`~/.claude/CLAUDE.md`), the
project `CLAUDE.md` with its imports and any local file from a `reviewer-lite` or
`mechanic` subagent; both are dispatched only with self-contained briefs. `implementer`
and `reviewer` do not get the key (the issue's decision).

Per D5 neither file grows. The 19-byte frontmatter line is paid for in the same file by
rewording its own non-pinned prose shorter, without dropping an instruction: the
`own-commands` clause that `test_dispatch_contracts` pins, `reviewer-lite`'s two mode
names and the existing frontmatter fields stay verbatim. The Instruction Budget profiles
that hold these definitions sit one byte under their ceilings (`mechanic.md` 759 of 760, `reviewer-lite.md` 1,561 of 1,562,
whole file counted), and the corpus ceiling counts the agents directory too, so a net
growth would need the human-applied `instruction-budget-raise` label. A ceiling the cut
leaves more than 5% loose is lowered (a lowering needs no label).

### Hidden skills

The setting is `skillOverrides`, a map from skill name to `on`, `name-only`,
`user-invocable-only` or `off` ("`user-invocable-only` hides it from the model but keeps
/name; `off` hides it from both. Absent = on."). It lives in the generated settings, so it
holds in every session and every account profile (each profile links the one
`settings.json`), interactive sessions included.

Per D1, every entry is `user-invocable-only`, keyed by the name the listing prints:

| Kind (how Claude Code loads it) | Keys |
|---|---|
| Bundled with Claude Code | `artifact-design`, `artifact-diagramming`, `artifact-capabilities`, `dataviz` |
| Synced from claude.ai | `anthropic-skills:docx`, `anthropic-skills:pptx`, `anthropic-skills:xlsx`, `anthropic-skills:pdf`, `anthropic-skills:google-workspace`, `anthropic-skills:morning`, `anthropic-skills:import-memory`, `anthropic-skills:skill-creator` |

A synced skill matches its full `anthropic-skills:` name before its bare one, so the full
name hides exactly that skill and never a future user or project skill that happens to be
called `pdf`. Bundled skills match their bare name. The probe hid `anthropic-skills:docx`,
`anthropic-skills:pdf`, `anthropic-skills:skill-creator` and `dataviz` this way; the nine
of the twelve that a `-p` session lists measured 6,705 of its 20,786 listing characters
(32.3%).

**What cannot be hidden.** Nothing in the issue's list. The limit found on the way is
general: a plugin's skills ignore user-level `skillOverrides` (the override lookup returns
only administrator overrides for a plugin skill, and `/skills` shows it locked on); in the
probe `"skill-creator:skill-creator": "off"` left it listed. A plugin skill leaves the
listing only when its plugin is disabled. That is why, per D2, the kept skill-creator is
the plugin's `skill-creator:skill-creator` and the hidden one is the claude.ai copy;
`enabledPlugins` does not change. The three Artifact skills are registered only in
sessions that have the Artifact tool (none in `claude -p`), so their keys take effect only
there; with `artifact-design` hidden, an Artifact publish works from the tool's own
quickstart guidance, which the tool counts as loading it.

Not used: `disableBundledSkills` (it removes every bundled skill, including
`update-config`, `code-review`, `simplify`, `loop` and `claude-api`) and
`syncClaudeAiSkills: false` (it removes every claude.ai skill, including the kept
`deep-research`, `docs` and browser skills).

### The orchestration launcher

Per D4, `claude-orchestrate [claude args]` is a third launcher script in the Claude
package's `bin`, beside `claude` and `claude-account`, so it is on PATH on every host. It
exports `ENABLE_CLAUDEAI_MCP_SERVERS=false` unconditionally (an inherited value cannot turn
connectors back on) and execs `claude-account run "$@"`, the command `claude` runs: the
same account resolution, plugin mod and `/account` switch loop. The export survives an
account switch, because `run` relaunches `claude --resume` from its own process.

Claude Code reads the variable at session start: any of `0`, `false`, `no`, `off` skips
the claude.ai connector fetch. Every subagent and background agent of that session shares
its MCP connections, so none of them carries claude.ai connector instructions or tools; in
the probe the variable removed the `mcp_instructions_delta` attachment and all 25 claude.ai
tool names, and left the 13 synced claude.ai skills listed (those are governed by
`skillOverrides`, not by connectors). Other MCP servers (palmier-pro on mbp, a project's
`.mcp.json`) are untouched. No tool is allowlisted or denied: the connectors' own tools go
with them, and project tools such as `mcp__nodo-admin__*` stay.

Plain `claude` is unchanged and keeps connectors. An orchestration is started by running
`claude-orchestrate` and then `/orchestrate-issues …` inside it; the skill's text does not
change (D8).

### Documentation

`home/common/claude-code/README.md` gains, under `## Settings`, the hidden-skill map, its
value, the key rule and the plugin limit; and, beside the account launcher it wraps, a
paragraph on `claude-orchestrate` (what it sets, that `claude` does not, and that the
account behaviour is `run`'s). The `agent-installed-skill-tests` recipe comment names the
Claude settings and launchers among what it checks. `CLAUDE.md`, the global guidance and
`orchestrate-issues/SKILL.md` are unchanged (D8).

### Evidence runs

Per D7, on mbp and before any activation (no `just switch`):

- **Start-up overhead (AC3).** One harness, run twice in a scratch sandbox under the
  launch-scope scratch root: a git checkout of this repository, so the real project
  `CLAUDE.md` loads; the agent definitions under test as project copies in its
  `.claude/agents/`, kept out of git; session persistence on; one `-p` root prompt that
  dispatches exactly one `reviewer-lite` and one `mechanic`, each with a fixed one-file
  brief. Both are needed: `reviewer-lite` has no Skill tool, so it carries no skill
  listing at all (seen in a real `reviewer-lite` transcript), while `mechanic` carries the
  listing, the deferred tools and the MCP instructions. *Before*: the deployed `claude`
  with the deployed settings and the base commit's agent definitions. *After*: the built
  `claude-orchestrate` from the build output, with `--settings <the built settings file>`
  and this branch's agent definitions. Each run is bracketed by its own window,
  `just agent-costs --report cache --events-since <start> --events-before <end>`, and the
  start-up rows are compared against AC3's thresholds: the `reviewer-lite` first request
  (write plus read) at least 2.5k tokens smaller, the `mechanic` skill listing at least
  30% smaller, and, read from each after-run subagent transcript's
  `mcp_instructions_delta` names as well, no `claude.ai …` server. An after run whose
  subagents still carry an `instructions` attachment did not load the copies under test
  and is void, not a measurement.
- **No regression (AC4).**
  `EVAL_TREE=<this worktree> EVAL_SETTINGS=<the built settings file> ENABLE_CLAUDEAI_MCP_SERVERS=false just evals from-issue 1`
  — the eval's tree mode already loads a checkout's agents and a given settings file; the
  variable in its environment stands in for the launcher.
- Both results go in the plan's acceptance record with the command lines and their
  output. A miss is recorded as a miss, never tuned toward the threshold.

## Test seams

1. **Agent frontmatter** — `home/common/agent-skills/tests/test_agent_model_matrix.py`,
   run by `just agent-workflow-tests`: a sibling of
   `test_every_custom_agent_explicitly_matches_its_matrix_role` reading the same
   `frontmatter()` helper asserts `omitClaudeMd` is `true` for `mechanic` and
   `reviewer-lite` and absent for `implementer` and `reviewer`. It fails at the base.
2. **Built settings and launchers** — a new installed-tier module,
   `tests/test_claude_code_installed.py`, following `tests/test_impeccable_installed.py`
   (skip when its inputs are unset; the recipe always sets them). It reads two build
   outputs, which `just agent-installed-skill-tests` discovers in `./result`'s closure by
   store-path suffix, exactly one each, as `just show-claude-settings` does:
   `CLAUDE_SETTINGS_PATH`, the settings artifact that recipe prints, and
   `CLAUDE_CODE_PACKAGE`, the built Claude package.
   - Settings: `skillOverrides` equals exactly the twelve-entry map above, each
     `user-invocable-only`; `enabledPlugins` equals the two entries it has today, which
     pins the kept skill-creator copy.
   - Launchers, through observable behaviour: each runs from the package's `bin` with
     `HOME` and the working directory in a temp dir, `CLAUDE_BIN` naming a stub that
     records its argv and environment, and the account variables (`CLAUDE_CONFIG_DIR`,
     `CLAUDE_ACCOUNT`, `CLAUDE_ACCOUNTS_DIR`, `CLAUDE_CODE_PLUGIN_DIRS`,
     `CLAUDE_ACCOUNT_LAUNCHER`) removed, so the calling session's account cannot steer it. `claude-orchestrate --version`, called with
     `ENABLE_CLAUDEAI_MCP_SERVERS=true` in its environment, hands the stub
     `ENABLE_CLAUDEAI_MCP_SERVERS=false` and the argv `--version`; `claude --version`,
     called without the variable, hands the stub none.
3. **Build and gates** — `just build mbp`, the anis-desktop evaluation (CI `Nix Eval`),
   and `just agent-instruction-budget` green without the raise label.

## Out of scope

- Tool allowlists or denylists, agent `tools:` lines, and the lifecycle guard.
- Interactive `claude` beyond the global `skillOverrides`: it keeps connectors, and
  nothing else about it changes.
- `CLAUDE.md`, the global guidance, `orchestrate-issues/SKILL.md` and `run-eval.sh`; the
  instruction-load model, which does not model `omitClaudeMd` (its preface already keeps
  the frame and project instructions out of every profile total).
- Hiding anything beyond the issue's list: plugin skills (`codex:*`), `name-only` trims,
  disabling the Artifact tool or the plugin.
- `claude-local` on Linux, account profiles' `.claude.json` copies, and activation.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Hide with `skillOverrides` in the generated settings, every entry `user-invocable-only`, keyed by the listed name: the full `anthropic-skills:<name>` for synced claude.ai skills, the bare name for bundled ones | Binary: the setting's schema text and its lookup (synced skills match the full name first, bundled the bare name); probe: four keys hid their skills; the issue asks to hide them from the listing only | `off` — also removes the user's `/name` in interactive sessions, which the issue does not ask for; `disableBundledSkills` — removes every bundled skill; `syncClaudeAiSkills: false` — removes the kept claude.ai skills; bare synced names — could catch a future user or project skill of the same name |
| D2 | Keep the plugin `skill-creator:skill-creator` and hide `anthropic-skills:skill-creator`; `enabledPlugins` unchanged | Binary and probe: a plugin skill ignores user `skillOverrides`, so the only way to hide the plugin copy is to disable the plugin; the plugin is declared in Nix and present for every account, the synced copy depends on each account's claude.ai sync | Disabling the plugin and keeping the claude.ai copy — changes the declared plugin surface and ties the skill to per-account sync |
| D3 | `omitClaudeMd: true` on `mechanic` and `reviewer-lite` only, asserted in `test_agent_model_matrix.py` next to the existing frontmatter-per-agent test | Issue decision; that test already reads every agent's frontmatter; agent-helpers rule 6 allows frontmatter pins | `test_dispatch_contracts.py` — it pins body clauses, not frontmatter; a matrix role field — the matrix owns tiers, and a second home would duplicate the frontmatter |
| D4 | `claude-orchestrate`, a third script in the Claude package's `bin` beside `claude` and `claude-account`, exporting `ENABLE_CLAUDEAI_MCP_SERVERS=false` unconditionally and exec'ing `claude-account run "$@"` | Issue names the variable and asks to keep interactive `claude` as is; `claudeWithAccounts` already prints both launchers there; `claude-local` naming precedent | A `claude-account orchestrate` mode — puts connector policy into the accounts launcher (single responsibility); `disableClaudeAiConnectors` through `--settings` — takes the flag the evidence and eval harnesses pass; the settings `env` block — would disable interactive sessions too |
| D5 | The 19-byte frontmatter line is paid for inside each file by shortening its non-pinned prose, so no file, profile or corpus measure grows and no raise label is needed; a ceiling left more than 5% loose is lowered | Instruction Budget gate: the two profiles sit one byte under their ceilings and the corpus counts agents; a raise needs the human `instruction-budget-raise` label, which only the user applies | Raising the ceilings — needs the human label, an authorization this run cannot grant itself, and leaves the required check red until then |
| D6 | Built settings and launchers are tested in a new installed-tier module run by `just agent-installed-skill-tests`, which passes the settings artifact and the Claude package found in `./result`'s closure; launchers are judged by the environment a `CLAUDE_BIN` stub receives | Installed-tier precedent (`test_impeccable_installed.py`, the recipe's discovery by store-path suffix); `show-claude-settings` discovery; the-bar: tests assert observable behaviour with an independent expected value | Extending `test_claude_permission_guard.py` — the guard's suite, needs the base-policy input and no recipe runs it; a Nix build check — the expected list would sit beside the value it checks; parsing `default.nix` — brittle |
| D7 | Evidence is measured before activation on mbp: AC3 by one sandbox harness that dispatches a `reviewer-lite` and a `mechanic`, run before (deployed `claude`, deployed settings, base agents) and after (built `claude-orchestrate`, `--settings` built file, branch agents), each bracketed by an `agent-costs --report cache` window, the listing clause read from the `mechanic` row and a run whose subagents still load `CLAUDE.md` void; AC4 by the eval's tree mode with the built settings and the variable set | CLAUDE.md: switch only when asked; run-eval tree mode (`EVAL_TREE`, `EVAL_SETTINGS`); issue 421's window flags; probe: flag-file overrides take effect; a real `reviewer-lite` transcript carries no skill listing (no Skill tool) | Measuring after a `just switch` — needs the user's activation, so an autonomous run would hold the issue; measuring AC3 from an eval run — evals run with `--no-session-persistence`, so they leave no transcript; a `reviewer-lite`-only harness — it has no listing to shrink |
| D8 | Docs go to the claude-code README; `CLAUDE.md`, the global guidance and `orchestrate-issues/SKILL.md` stay unchanged | CLAUDE.md: detail of that kind goes to the module README; the skill is read only after launch, so it cannot choose the launcher, and its profile ceiling is tight | A launch note in the skill — read too late to matter, and grows a gated profile |
| D9 | AC3's harness (plan): each run's sandbox is a fresh local clone of this repository at the base commit with `.claude/` in its own `.git/info/exclude`, launched with `CLAUDE_ACCOUNT` set to the caller's account and `ENABLE_CLAUDEAI_MCP_SERVERS`, `CLAUDE_CODE_PLUGIN_DIRS` and `CLAUDE_ACCOUNT_LAUNCHER` unset; the report reads a `--projects-dir` copy holding only that run's session (found by the `-p` result's `session_id`) inside the run's window, and the thresholds use `scan_transcript`'s exact start-up values; a before run whose subagents lack an `instructions` attachment is void, like an after run whose subagents carry one | Concurrent orchestration workers write `mechanic` and `reviewer-lite` transcripts into the same window, and `--report cache` refuses `--project`; an unbound scratch path resolves to the `default` account; planning probe (2026-10-25): a project `mechanic` copy with `omitClaudeMd: true` started without an `instructions` attachment, and its session was found by id under `~/.claude/projects` | A window over all of `~/.claude/projects` — the medians would mix in other workers' subagents; a `git worktree add` sandbox — writes worktree metadata into the primary repository and needs a forced remove |
| D10 | The anis-desktop half of AC2 is the PR's required `Nix Eval` check, not a local gate (plan) | On mbp the evaluation stops at an x86_64-linux build it needs while evaluating (`catppuccin-install-hook`: "required system or feature not available"); `Nix Eval` is required on `main` | Evaluating it locally — impossible without a Linux builder; dropping it — the criterion names it, and the check gates the merge anyway |
