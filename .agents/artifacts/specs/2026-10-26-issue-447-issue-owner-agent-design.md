# Issue owners launch as an `issue-owner` agent type that blocks unused tools — issue 447

Design for https://github.com/fagenorn/nix-config/issues/447. A bare "Dn" cites this
spec's ledger. Base: `ca6ba1ae` (origin/main). Binary facts are from the strings of the
pinned Claude Code 2.1.310 (`.claude-unwrapped`); doc facts are from the official
sub-agents and permissions pages (code.claude.com/docs/en/sub-agents, /permissions).

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "the role-to-subagent_type dispatch contract (agent_model_matrix ALLOWED_SUBAGENT_TYPES, model-matrix.json call strings) changes for issue-owner, auto-owner and ship-owner sites"}, "concurrency_or_persistence": {"value": "no", "evidence": "no locking, ledger or persisted state is touched; only an agent definition, skill dispatch lines and their tests"}, "open_design_questions": {"value": "doubt", "evidence": "whether agent frontmatter disallowedTools can block deferred and MCP tools is unconfirmed, and roles shared with ship-release and improve-codebase-architecture need a scope call"}, "criteria_shape": {"value": "hit", "evidence": "the evidence criterion (>=11k-token smaller first request, still dispatches) is not verified by a deterministic code check"}}, "paths": ["home/common/claude-code/agents/issue-owner.md", "home/common/agent-skills/skills/from-issue/SKILL.md", "home/common/agent-skills/skills/from-issue/AUTO.md", "home/common/claude-code/skills/orchestrate-issues/SKILL.md", "home/common/agent-skills/model-matrix.json", "python/agent_tools/agent_model_matrix.py", "home/common/agent-skills/tests/test_agent_model_matrix.py", "home/common/agent-skills/tests/test_dispatch_contracts.py"]}
Verdict: {"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

Every issue owner — the from-issue phase delegate (and its relaunches), the autonomous
design-and-grill and planning owners, the ship owner (and the remainder owner it
launches) and the orchestrate-issues owner — is dispatched as `general-purpose`. That
type has no agent definition in this repository, so none of issue 425's start-up trims
reach it, and each owner boots with tools it never calls. On 43 fresh owners (the boot
analysis for issue 432) the fixed tool schemas were 16.7k tokens of a 94k mean boot;
the Artifact tool alone was 11.7k. The claude.ai Docs connector's tools come on top
whenever the session was not started through `claude-orchestrate`.

## Solution

1. A new agent definition, `issue-owner`, deployed with the other agents (the existing
   recursive `~/.claude/agents` source). It denies exactly the Artifact, ArtifactComments
   and ArtifactData tools and the claude.ai Docs connector, and keeps everything else:
   Agent, Skill, Bash, the file tools, ToolSearch and every project MCP server.
2. The five owner dispatch sites of from-issue and orchestrate-issues name
   `subagent_type="issue-owner"` instead of `general-purpose`. That is the whole
   skill-text change: four bytes shorter per site, no other wording moves.
3. The model matrix maps the three owner roles to the new type, and two tests pin the
   definition and the sites.

Demo: in a scratch session, dispatch one `general-purpose` and one `issue-owner`
subagent with the same brief; the `issue-owner` lists no Artifact or Docs tool, still
dispatches its own child, and its first request is the smaller one.

## Decisions

### The definition

Per D1 the frontmatter is five single-line fields, the shape the repository's
frontmatter parser and `agent_model_matrix` read:

- `name: issue-owner`;
- `description:` one short sentence saying it is the owner type that from-issue and
  orchestrate-issues owner sites name. The description is paid in the Agent tool listing
  of every session that has the Agent tool, so it stays one line and tells the main
  session not to pick it for ordinary work;
- `model: opus`, `effort: high` (per D3);
- `disallowedTools: Artifact, ArtifactComments, ArtifactData, mcp__claude_ai_Claude_Docs`.

No `tools:` line (issue 425's decision: block named tools, never an allowlist) and no
`omitClaudeMd` (owners need the project and global instructions).

How Claude Code reads it (2.1.310): the agent's `disallowedTools` goes through the same
matcher the built-in Explore and Plan agents use. An entry matches a tool by exact name;
`mcp__<server>` or `mcp__<server>__*` matches every tool of that server; `mcp__*` every
MCP tool. The docs give `disallowedTools: mcp__github` as removing "every tool from the
github MCP server while keeping tools from other servers and the built-in tools." The
connector's tools are named `mcp__claude_ai_Claude_Docs__<tool>`, so the server-level
entry covers all eight and any the connector adds. Whether the filter also removes the
deferred tools (ArtifactComments, ArtifactData) from the deferred-tool listing, and
whether it applies to the background owners orchestrate-issues launches (background
subagents keep Artifact on their keep-list), is what the plan's first task confirms.

### No body, so no profile growth

Per D2 the definition has no markdown body. A definition's body becomes the subagent's
system prompt in place of the general-purpose prompt; with none, the owner runs on its
dispatch prompt, the environment details Claude Code adds, `CLAUDE.md` and its skills.
Everything an owner needs is already in its prompt: from-issue's **Leaf-agent clauses**
put the four clauses into every prompt it composes, the orchestrate-issues owner prompt
and the ship-owner fence carry them, and each prompt states its return schema.

Claude Code 2.1.310 loads a definition whose body is empty (its loader rejects only a
missing name or description and trims the body), but no document states what an empty
system prompt does at spawn. The plan's first task therefore also confirms that a
body-less `issue-owner` spawns, dispatches its own child and returns its report. If it
does not, the work returns to the caller with that finding: a body would grow the owner
profiles, which only the user's raise label allows, so no task falls back to one.

That is also the only shape that fits the Instruction Budget without the raise label. A
definition listed in a profile counts whole (as `agents/reviewer.md` does in the
reviewer profiles), and the owner profiles on Claude have 4 (design-and-grill), 8
(implementation owner) and 18 (planning) bytes of slack. A body-less definition loads no
instruction text into the owner, so it is listed in no profile and the model stays
truthful. The corpus ceiling counts every `agents/*.md` and has 8,840 bytes of slack;
the file costs a few hundred, and the five renames save 20.

The carrier-declaration test now enrols every agent definition that has a body as an
`own-commands` carrier; `issue-owner` has none, and the frontmatter test pins that it
stays empty (a later body must be enrolled and listed in the owner profiles).

### Tiers

Per D3 the definition pins the `issue-owner` role's tier, opus/high, as `implementer.md`
pins `implementer`'s while the `task-implementer` sites pass `model="sonnet"`. Every
owner site already passes both `model` and `effort`, and the call's parameters override
the frontmatter (docs: "The parameter overrides the `effort` field"), so the two
auto-owner sites keep `effort="xhigh"`. `agent_model_matrix` needs no new logic: the
custom-agent role set gains `issue-owner`, whose frontmatter tier is checked against its
role like the other four.

### The role-to-type mapping

Per D4:

| Role | Allowed types | Sites |
|---|---|---|
| `auto-owner` | `issue-owner` | from-issue-design-grill, from-issue-planning |
| `issue-owner` | `issue-owner`, `general-purpose` | orchestration-issue-owner, from-issue-phase-delegate → `issue-owner`; improve-architecture-scan-owner stays `general-purpose` |
| `ship-owner` | `issue-owner`, `general-purpose` | from-issue-ship-owner → `issue-owner`; ship-release-owner stays `general-purpose` |

`researcher` keeps `general-purpose`. The remainder owner of `ship-handoff.md` launches
through the `from-issue-ship-owner` site, so it changes with it and its text does not.
Codex has no agent definitions; there the type name is as inert as `reviewer` or
`mechanic` already are. Every account profile links `~/.claude/agents` whole, so the
definition and the renamed skill text arrive together in one activation on every host.

### Documentation

The comment above the `~/.claude/agents` source in the Claude Code module names
`issue-owner` with the other tiered agents. `CLAUDE.md`, the module README and the
skills' prose are unchanged.

### Evidence run

Per D6, on mbp and before any activation: one `claude -p` probe in a fresh local clone
under the launch-scope scratch root, with this branch's `issue-owner.md` as a git-excluded
project copy in `.claude/agents/` and session persistence on. Its root prompt dispatches,
with one identical brief, one `general-purpose` and one `issue-owner` subagent; each
lists its tool names, dispatches one `Explore` child over a fixed one-file lookup and
relays the child's one-line answer. The measurement is each subagent's first request
(input plus cache write plus cache read) from the subagent transcripts, read inside the
run's `just agent-costs --report cache` window, and the AC holds when the
`general-purpose` figure exceeds the `issue-owner` figure by at least 11,000 tokens and
the `issue-owner` child returned. If the probe session has no Artifact tool in its pool
(issue 425 found none under `-p`), the probe still records its delta and the dispatch,
and the AC is measured after the user's `just switch` from the first real owners'
start-up rows (`issue-owner` against the issue-432 `general-purpose` baseline); the plan
records that as post-merge verification. A miss is recorded as a miss.

## Test seams

1. **Definition frontmatter** — `test_agent_model_matrix.py`, beside the omitClaudeMd
   test, through its `frontmatter()` helper: `issue-owner.md`'s `disallowedTools`, split
   on commas, equals exactly the four entries; it has no `tools` and no `omitClaudeMd`;
   its body is empty. The existing every-agent tier test lists it with opus/high. Fails at
   the base (no file).
2. **Dispatch sites** — same module: the matrix sites whose role is an owner role and
   whose path lies in the from-issue or orchestrate-issues source directory equal a literal set of
   the five ids, each call reads `Agent(subagent_type="issue-owner", …)`, and no file of
   those two directories contains `subagent_type="general-purpose"`. The `ALLOWED_SUBAGENT_TYPES`
   mirror follows D4, and `validate()` stays green on the repository. Fails at the base.
3. **Carrier declaration** — `test_dispatch_contracts.py`: the enrolled agent carriers
   equal the definitions with a non-empty body.
4. **Renamed pins** — the orchestrate-issues owner call anchor in
   `test_workflow_skill_contracts.py` moves to the new string.
5. **Gates** — `just agent-workflow-tests`, `just agent-instruction-budget` with no raise
   label, `just build mbp`, and CI `Nix Eval` for anis-desktop.

## Out of scope

- The `improve-architecture-scan-owner`, `ship-release-owner` and `research` sites, and
  every non-owner site.
- Launch flags, `claude-orchestrate`, settings, permissions and the lifecycle guard.
- Blocking anything beyond the issue's list: ArtifactCheck, other claude.ai connectors,
  `omitClaudeMd` for owners.
- The Agent-tool depth limit, owner prompts and every other skill sentence.
- Activation (`just switch`) and changes to `agent-costs`. A switch made while an
  orchestration runs can hand a session whose agent list predates it a type it has not
  loaded; activating between runs avoids that, as for any new agent.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | `disallowedTools: Artifact, ArtifactComments, ArtifactData, mcp__claude_ai_Claude_Docs` on one line; the Docs connector is denied by its server-level entry; no `tools:` and no `omitClaudeMd` | Issue's list and "named tools, never an allowlist" (issue 425); binary matcher and docs: `mcp__<server>` removes that server's tools; repository frontmatter parser reads single-line fields | Eight `mcp__claude_ai_Claude_Docs__<tool>` names — longer, and a tool the connector adds slips through; adding ArtifactCheck, which Explore and Plan deny — AC1 says exactly the listed tools and it is absent from this session's pool; `mcp__*` — drops the project MCP tools the issue keeps |
| D2 | The definition has no body; it is in no instruction-load profile; the carrier test enrols only definitions with a body, and the frontmatter test pins the body empty; the plan's first task confirms a body-less owner spawns and dispatches, and a failure returns to the caller rather than adding a body | Owner profile slack 4/8/18 bytes on Claude and a listed definition counts whole; the raise label is the user's alone; owner prompts already carry the four clauses and their return schemas; docs: the body becomes the system prompt | A body listed in the owner profiles — breaches three ceilings and needs the label; a body left unlisted — the model under-counts what owners load |
| D3 | Frontmatter pins `model: opus`, `effort: high`; every site keeps its explicit `model`/`effort`, which override; `issue-owner` joins the custom-agent role set with no new validator logic | `implementer.md` precedent (task-implementer overrides at the call); docs: call parameters override frontmatter model and effort | Omitting both — needs a one-file validator exception and changes nothing, since every site passes both |
| D4 | `auto-owner` → {issue-owner}; `issue-owner` and `ship-owner` → {issue-owner, general-purpose}, keeping improve-architecture-scan-owner and ship-release-owner on `general-purpose` | The issue names from-issue and orchestrate-issues only; improve-codebase-architecture is vendored at a pinned upstream revision with its call pinned | Switching the two other sites too — outside the issue and edits a vendored skill; a new role per site — the matrix's roles are tiers, not types |
| D5 | Both new tests live in `test_agent_model_matrix.py`; the site test fixes the five ids literally and also forbids `subagent_type="general-purpose"` in the two skills' files | agent-helpers rule 6 (frontmatter and mirrored `Agent(...)` lines may be pinned); that module already reads every definition's frontmatter and the owner sites' tiers | `test_dispatch_contracts.py` — it pins carrier clauses, not types; deriving the expected set from the matrix alone — no independent expected value |
| D6 | AC3 is measured before activation by one `-p` probe that dispatches a `general-purpose` and an `issue-owner` subagent with one brief, comparing first requests and checking the child dispatch; if the probe's pool has no Artifact, the AC moves to post-merge verification from real owners after the user's `just switch` | Issue's measurement options; CLAUDE.md: switch only when asked; issue 425 D7/D9 sandbox harness and its `-p` finding; one session gives both types the same pool | Measuring only after a switch — holds the issue on the user; two separate sessions — pool and cache differences confound the delta |
| D7 | Plan Task 1 runs the one probe before any code lands, with the definition bytes the plan dictates as the sandbox copy; it is both the feasibility confirmation and the AC3 probe, and Task 2 commits a byte-identical file (sha256 in the record). Task 1 stops BLOCKED only when the body-less `issue-owner` does not spawn, return or dispatch its child, loses a kept tool, or removes none of the listed tools its `general-purpose` control carried; a listed tool the control carried and `issue-owner` kept is reported and the plan continues, never with a launch flag; a background `issue-owner` rides along and is recorded only | Issue: the first task confirms and reports any tool it cannot block; D2's failure route returns before a body; the probe reads only the definition and the pinned binary, so later skill edits cannot move it | Probing after the code tasks — a failure leaves commits to unwind; re-running at the final head — same inputs, double cost |
| D8 | Under `claude -p` the pool has no Artifact tools (observed at planning on 2.1.310, also with `CLAUDE_CODE_EVAL_ARTIFACT_STUB_DIR`), so the Artifact-trio removal and AC3's 11,000-token threshold take D6's post-merge route: after the user's `just switch`, the `just agent-costs --report cache` start-up median (1st write + 1st read) of `issue-owner` subagents since the switch against that of `general-purpose` subagents in the 7 days before it, plus no blocked name in those `issue-owner` transcripts' `deferred_tools_delta`; the issue is held open until it is recorded | D6's fallback; planning scratch runs' init tool lists; the start-up table is issue 421's measure | Driving an interactive session through a pty pre-merge — unbounded TUI automation outside launch-scope; the eval stub — observed not to add Artifact |
| D9 | Phase-5 review tightened Task 1's evidence checks: `child_returned_anis` requires the owner's line to be exactly `CHILD: anis` and its linked Explore child's last line to be `anis`; the Step 6 verifier also fails when the control carried listed tools and the owner kept every one (D7's no-removal stop); the post-merge `agent-costs` after-window passes `--events-before <END>` | Codex plan review R1–R3: `agent_costs.py` rejects `--events-since` without `--events-before`; a substring match accepts `CHILD: none (failed to obtain anis)`; Step 6 claimed to fail on every D7 stop rule but did not check this one | Leaving D7's no-removal stop to Step 4's manual reading — the verifier's stated contract would stay false |
| D10 | Keep the plan's kept-tools loop in `test_issue_owner_blocks_exactly_the_listed_tools` although the exact-list equality above it already implies it (Task 2 review, plan-mandated finding) | AC1 names "does not block Agent, Skill, Bash or the file tools"; the loop states that clause literally beside the list, and it costs nothing at run time | Deleting it per The Bar's tests-that-can-fail rule — leaves AC1's negative clause readable only by inference from the list |
