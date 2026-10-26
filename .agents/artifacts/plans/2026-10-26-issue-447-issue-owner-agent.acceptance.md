# Acceptance record — issue 447

Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/447).

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] `issue-owner.md` exists, blocks exactly the listed tools, and does not block Agent, Skill, Bash or the file tools. Measured by: a frontmatter test in `just agent-workflow-tests`. | code | `home/common/agent-skills/tests/test_agent_model_matrix.py::AgentModelMatrixTest::test_issue_owner_blocks_exactly_the_listed_tools` (`disallowedTools` is exactly `Artifact, ArtifactComments, ArtifactData, mcp__claude_ai_Claude_Docs`, no Agent, Skill, Bash or file tool among them, frontmatter fields exactly `name, description, model, effort, disallowedTools`, empty body), run by `just agent-workflow-tests` in sdd's final gate. | in final verification | — | — | — |
| AC2 | [code] Every owner dispatch site in from-issue and orchestrate-issues uses `issue-owner`, and none uses `general-purpose`. Measured by: a dispatch-site contract test. `just agent-instruction-budget` (no raise label) and `just build` pass. | code | `home/common/agent-skills/tests/test_agent_model_matrix.py::AgentModelMatrixTest::test_from_issue_and_orchestration_owner_sites_launch_issue_owner` (the five owner site ids, each call `Agent(subagent_type="issue-owner", …`, no `subagent_type="general-purpose"` in either skill directory) and `::test_executable_subagent_type_mapping_is_exhaustive`, run by `just agent-workflow-tests`; plus `just agent-instruction-budget` ending `check: pass` with no `--raise-label` and `just build` exit 0 on the final head; anis-desktop by the PR's `Nix Eval`. | in final verification | — | — | — |
| AC3 | [evidence] An `issue-owner` first request is at least 11k tokens smaller than a `general-purpose` owner's, and it can still dispatch a subagent. Measured by: `just agent-costs` start-up overhead, or a one-agent probe on mbp. | evidence | Pre-merge, on mbp with no activation: the Task 1 probe (`claude -p`, one brief to a `general-purpose` control and a foreground `issue-owner`), first request = input + cache write + cache read of each subagent's first call; threshold: control minus `issue-owner` ≥ 11,000 tokens and the `issue-owner`'s Explore child returned `anis`. If the probe's root pool has no `Artifact` (expected, D8), the row records the probe's delta and dispatch and stays pending on the post-merge check written into the record: after the user's `just switch`, `just agent-costs --report cache` start-up median (1st write + 1st read) of `issue-owner` since the switch at least 11,000 below `general-purpose` in the 7 days before it, and no blocked name in those `issue-owner` transcripts' `deferred_tools_delta` (D6, D8). Acceptance-record row `AC3`. | probe: general-purpose 21,346 → issue-owner 19,965 tokens (first request), smaller by 1,381; issue-owner child: returned anis; root pool Artifact: absent; threshold 11,000: pending post-merge (D8) | `320930e0` | host `mbp`; ACCOUNT `p1`; claude `/nix/store/c2mrilcnzz6i10a1c5rbwmlg3aiffx7v-claude-code-with-accounts-2.1.310/bin/claude` `2.1.310 (Claude Code)`; definition sha256 `02f2999e7eccfb3eec026aa843452f04b16273f975b48fb8f6cbc91f7254ae56` (248 bytes); probe: sandbox clone at `ca6ba1ae2b37e56c1361a8656c29af1f39b89348` with `.claude/agents/issue-owner.md` git-excluded, `claude -p <prompt> --model sonnet --dangerously-skip-permissions --output-format stream-json --verbose --max-budget-usd 8`, `CLAUDE_ACCOUNT=p1`, `ENABLE_CLAUDEAI_MCP_SERVERS`, `CLAUDE_CODE_PLUGIN_DIRS`, `CLAUDE_ACCOUNT_LAUNCHER` unset; window 2026-10-26T09:39:43Z 2026-10-26T09:40:06Z; session `d82f2e18-db88-4ea2-af77-4e9a784868ba`; cost $0.6101 (final result line; the stream carries two result lines, the first at $0.6036); no retry; the transcript copy at the end of `probe.sh` was repeated by hand because the two result lines made its session-id lookup match nothing; not tuned | — |

## Feasibility

| Tool | general-purpose control | issue-owner foreground | issue-owner background |
|---|---|---|---|
| `Artifact` | not in pool | not in pool | not in pool |
| `ArtifactComments` | not in pool | not in pool | not in pool |
| `ArtifactData` | not in pool | not in pool | not in pool |
| `mcp__claude_ai_Claude_Docs` | present | removed | removed |

A tool `not in pool` in the control is confirmed by the post-merge check.

- spawned and returned: yes
- child returned anis: yes
- kept tools (Agent/Task, Skill, Bash, Read, Edit, Write, ToolSearch): all kept; lost: none
- tools the control carried and the `issue-owner` kept by frontmatter: none
- tools the control carried: `mcp__claude_ai_Claude_Docs`; the `issue-owner` removed each of them, foreground and background

## Probe output

```text
Subagent start-up (first request's cache write and read; characters of each start-up attachment sent before the second request; medians over the subagents that carried it):

agent type       subagents  1st write  1st read  skill listing  instructions  MCP instructions  deferred tools  agent listing  environment
---------------  ---------  ---------  --------  -------------  ------------  ----------------  --------------  -------------  -----------
Explore                  3          0    12.62k         14.22k             -             2.05k             773              -          811
issue-owner              2     12.70k         0         14.22k        15.39k             2.05k             373          2.98k          811
general-purpose          1     21.34k         0         14.22k        15.39k             2.05k             786          2.98k          811

Pricing: https://platform.claude.com/docs/en/about-claude/pricing (2026-10-25); 0 calls priced approximately
```

```json
{
  "checks": {
    "ac3": "pending post-merge (D8)",
    "child_returned_anis": true,
    "control_carried": [
      "mcp__claude_ai_Claude_Docs"
    ],
    "first_request_total": {
      "general-purpose": 21346,
      "issue-owner": 19965,
      "issue-owner-background": 18702
    },
    "kept_listed": [],
    "kept_tools": true,
    "lost_tools": [],
    "per_tool": {
      "Artifact": {
        "background": "not in pool",
        "control": "not in pool",
        "foreground": "not in pool"
      },
      "ArtifactComments": {
        "background": "not in pool",
        "control": "not in pool",
        "foreground": "not in pool"
      },
      "ArtifactData": {
        "background": "not in pool",
        "control": "not in pool",
        "foreground": "not in pool"
      },
      "mcp__claude_ai_Claude_Docs": {
        "background": "removed",
        "control": "present",
        "foreground": "removed"
      }
    },
    "root_pool_artifact": false,
    "smaller_by": 1381,
    "spawned_and_returned": true
  },
  "cost_usd": 0.6036469000000001,
  "dispatches": [
    {
      "background": false,
      "error": false,
      "subagent_type": "general-purpose"
    },
    {
      "background": false,
      "error": false,
      "subagent_type": "issue-owner"
    },
    {
      "background": true,
      "error": false,
      "subagent_type": "issue-owner"
    }
  ],
  "root_tools": [
    "Bash",
    "CronCreate",
    "CronDelete",
    "CronList",
    "DesignSync",
    "Edit",
    "EnterWorktree",
    "ExitWorktree",
    "ListAgents",
    "Monitor",
    "NotebookEdit",
    "PushNotification",
    "Read",
    "RemoteTrigger",
    "ReportFindings",
    "ScheduleWakeup",
    "SendMessage",
    "Skill",
    "Task",
    "TaskStop",
    "ToolSearch",
    "WebFetch",
    "WebSearch",
    "Workflow",
    "Write"
  ],
  "rows": [
    {
      "agent_type": "issue-owner",
      "background": false,
      "child_line": "CHILD: anis",
      "deferred_added": [
        "CronCreate",
        "CronDelete",
        "CronList",
        "DesignSync",
        "EnterWorktree",
        "ExitWorktree",
        "Monitor",
        "NotebookEdit",
        "PushNotification",
        "RemoteTrigger",
        "SendMessage",
        "TaskStop",
        "WebFetch",
        "WebSearch"
      ],
      "description": "Probe issue-owner",
      "first_request": {
        "input": 2,
        "read": 7268,
        "total": 19965,
        "write": 12695
      },
      "id": "a045db2c4fd44f672",
      "last_line": "CHILD: anis",
      "listed": {
        "Artifact": false,
        "ArtifactComments": false,
        "ArtifactData": false,
        "mcp__claude_ai_Claude_Docs": false
      },
      "names": [
        "Agent",
        "Bash",
        "CronCreate",
        "CronDelete",
        "CronList",
        "DesignSync",
        "Edit",
        "EnterWorktree",
        "ExitWorktree",
        "ListAgents",
        "Monitor",
        "NotebookEdit",
        "PushNotification",
        "Read",
        "RemoteTrigger",
        "ReportFindings",
        "SendMessage",
        "Skill",
        "TaskStop",
        "ToolSearch",
        "WebFetch",
        "WebSearch",
        "Write"
      ],
      "parent": null,
      "tools_line": "TOOLS: Agent, Bash, Edit, ListAgents, Read, ReportFindings, Skill, ToolSearch, Write, CronCreate, CronDelete, CronList, DesignSync, EnterWorktree, ExitWorktree, Monitor, NotebookEdit, PushNotification, RemoteTrigger, SendMessage, TaskStop, WebFetch, WebSearch"
    },
    {
      "agent_type": "issue-owner",
      "background": true,
      "child_line": "CHILD: anis",
      "deferred_added": [
        "EnterWorktree",
        "ExitWorktree",
        "Monitor",
        "NotebookEdit",
        "SendMessage",
        "TaskStop",
        "WebFetch",
        "WebSearch"
      ],
      "description": "Probe issue-owner background",
      "first_request": {
        "input": 2,
        "read": 0,
        "total": 18702,
        "write": 18700
      },
      "id": "a2603dda05c378af5",
      "last_line": "CHILD: anis",
      "listed": {
        "Artifact": false,
        "ArtifactComments": false,
        "ArtifactData": false,
        "mcp__claude_ai_Claude_Docs": false
      },
      "names": [
        "Agent",
        "Bash",
        "Edit",
        "EnterWorktree",
        "ExitWorktree",
        "Monitor",
        "NotebookEdit",
        "Read",
        "SendMessage",
        "Skill",
        "TaskStop",
        "ToolSearch",
        "WebFetch",
        "WebSearch",
        "Write"
      ],
      "parent": null,
      "tools_line": "TOOLS: Agent, Bash, Edit, Read, Skill, ToolSearch, Write, EnterWorktree, ExitWorktree, Monitor, NotebookEdit, SendMessage, TaskStop, WebFetch, WebSearch"
    },
    {
      "agent_type": "Explore",
      "background": false,
      "child_line": null,
      "deferred_added": [
        "CronCreate",
        "CronDelete",
        "CronList",
        "DesignSync",
        "EnterWorktree",
        "ExitWorktree",
        "Monitor",
        "PushNotification",
        "RemoteTrigger",
        "SendMessage",
        "TaskStop",
        "WebFetch",
        "WebSearch",
        "mcp__claude_ai_Claude_Docs__batch",
        "mcp__claude_ai_Claude_Docs__create",
        "mcp__claude_ai_Claude_Docs__delete",
        "mcp__claude_ai_Claude_Docs__export",
        "mcp__claude_ai_Claude_Docs__guide",
        "mcp__claude_ai_Claude_Docs__query",
        "mcp__claude_ai_Claude_Docs__read",
        "mcp__claude_ai_Claude_Docs__update"
      ],
      "description": "Read vars username",
      "first_request": {
        "input": 2,
        "read": 12619,
        "total": 12621,
        "write": 0
      },
      "id": "a2c85267adbec3503",
      "last_line": "anis",
      "listed": {
        "Artifact": false,
        "ArtifactComments": false,
        "ArtifactData": false,
        "mcp__claude_ai_Claude_Docs": true
      },
      "names": [
        "CronCreate",
        "CronDelete",
        "CronList",
        "DesignSync",
        "EnterWorktree",
        "ExitWorktree",
        "Monitor",
        "PushNotification",
        "RemoteTrigger",
        "SendMessage",
        "TaskStop",
        "WebFetch",
        "WebSearch",
        "mcp__claude_ai_Claude_Docs__batch",
        "mcp__claude_ai_Claude_Docs__create",
        "mcp__claude_ai_Claude_Docs__delete",
        "mcp__claude_ai_Claude_Docs__export",
        "mcp__claude_ai_Claude_Docs__guide",
        "mcp__claude_ai_Claude_Docs__query",
        "mcp__claude_ai_Claude_Docs__read",
        "mcp__claude_ai_Claude_Docs__update"
      ],
      "parent": "a045db2c4fd44f672",
      "tools_line": null
    },
    {
      "agent_type": "Explore",
      "background": false,
      "child_line": null,
      "deferred_added": [
        "CronCreate",
        "CronDelete",
        "CronList",
        "DesignSync",
        "EnterWorktree",
        "ExitWorktree",
        "Monitor",
        "PushNotification",
        "RemoteTrigger",
        "SendMessage",
        "TaskStop",
        "WebFetch",
        "WebSearch",
        "mcp__claude_ai_Claude_Docs__batch",
        "mcp__claude_ai_Claude_Docs__create",
        "mcp__claude_ai_Claude_Docs__delete",
        "mcp__claude_ai_Claude_Docs__export",
        "mcp__claude_ai_Claude_Docs__guide",
        "mcp__claude_ai_Claude_Docs__query",
        "mcp__claude_ai_Claude_Docs__read",
        "mcp__claude_ai_Claude_Docs__update"
      ],
      "description": "Read vars username",
      "first_request": {
        "input": 2,
        "read": 0,
        "total": 12621,
        "write": 12619
      },
      "id": "a4793853319c3bece",
      "last_line": "anis",
      "listed": {
        "Artifact": false,
        "ArtifactComments": false,
        "ArtifactData": false,
        "mcp__claude_ai_Claude_Docs": true
      },
      "names": [
        "CronCreate",
        "CronDelete",
        "CronList",
        "DesignSync",
        "EnterWorktree",
        "ExitWorktree",
        "Monitor",
        "PushNotification",
        "RemoteTrigger",
        "SendMessage",
        "TaskStop",
        "WebFetch",
        "WebSearch",
        "mcp__claude_ai_Claude_Docs__batch",
        "mcp__claude_ai_Claude_Docs__create",
        "mcp__claude_ai_Claude_Docs__delete",
        "mcp__claude_ai_Claude_Docs__export",
        "mcp__claude_ai_Claude_Docs__guide",
        "mcp__claude_ai_Claude_Docs__query",
        "mcp__claude_ai_Claude_Docs__read",
        "mcp__claude_ai_Claude_Docs__update"
      ],
      "parent": "a58a3890e88018c62",
      "tools_line": null
    },
    {
      "agent_type": "general-purpose",
      "background": false,
      "child_line": "CHILD: anis",
      "deferred_added": [
        "CronCreate",
        "CronDelete",
        "CronList",
        "DesignSync",
        "EnterWorktree",
        "ExitWorktree",
        "Monitor",
        "NotebookEdit",
        "PushNotification",
        "RemoteTrigger",
        "SendMessage",
        "TaskStop",
        "WebFetch",
        "WebSearch",
        "mcp__claude_ai_Claude_Docs__batch",
        "mcp__claude_ai_Claude_Docs__create",
        "mcp__claude_ai_Claude_Docs__delete",
        "mcp__claude_ai_Claude_Docs__export",
        "mcp__claude_ai_Claude_Docs__guide",
        "mcp__claude_ai_Claude_Docs__query",
        "mcp__claude_ai_Claude_Docs__read",
        "mcp__claude_ai_Claude_Docs__update"
      ],
      "description": "Probe general-purpose",
      "first_request": {
        "input": 2,
        "read": 0,
        "total": 21346,
        "write": 21344
      },
      "id": "a58a3890e88018c62",
      "last_line": "CHILD: anis",
      "listed": {
        "Artifact": false,
        "ArtifactComments": false,
        "ArtifactData": false,
        "mcp__claude_ai_Claude_Docs": true
      },
      "names": [
        "Agent",
        "Bash",
        "CronCreate",
        "CronDelete",
        "CronList",
        "DesignSync",
        "Edit",
        "EnterWorktree",
        "ExitWorktree",
        "ListAgents",
        "Monitor",
        "NotebookEdit",
        "PushNotification",
        "Read",
        "RemoteTrigger",
        "ReportFindings",
        "SendMessage",
        "Skill",
        "TaskStop",
        "ToolSearch",
        "WebFetch",
        "WebSearch",
        "Write",
        "mcp__claude_ai_Claude_Docs__batch",
        "mcp__claude_ai_Claude_Docs__create",
        "mcp__claude_ai_Claude_Docs__delete",
        "mcp__claude_ai_Claude_Docs__export",
        "mcp__claude_ai_Claude_Docs__guide",
        "mcp__claude_ai_Claude_Docs__query",
        "mcp__claude_ai_Claude_Docs__read",
        "mcp__claude_ai_Claude_Docs__update"
      ],
      "parent": null,
      "tools_line": "TOOLS: Agent, Bash, Edit, ListAgents, Read, ReportFindings, Skill, ToolSearch, Write, mcp__claude_ai_Claude_Docs__batch, mcp__claude_ai_Claude_Docs__guide, mcp__claude_ai_Claude_Docs__update, CronCreate, CronDelete, CronList, DesignSync, EnterWorktree, ExitWorktree, Monitor, NotebookEdit, PushNotification, RemoteTrigger, SendMessage, TaskStop, WebFetch, WebSearch, mcp__claude_ai_Claude_Docs__create, mcp__claude_ai_Claude_Docs__delete, mcp__claude_ai_Claude_Docs__export, mcp__claude_ai_Claude_Docs__query, mcp__claude_ai_Claude_Docs__read"
    },
    {
      "agent_type": "Explore",
      "background": false,
      "child_line": null,
      "deferred_added": [
        "CronCreate",
        "CronDelete",
        "CronList",
        "DesignSync",
        "EnterWorktree",
        "ExitWorktree",
        "Monitor",
        "PushNotification",
        "RemoteTrigger",
        "SendMessage",
        "TaskStop",
        "WebFetch",
        "WebSearch",
        "mcp__claude_ai_Claude_Docs__batch",
        "mcp__claude_ai_Claude_Docs__create",
        "mcp__claude_ai_Claude_Docs__delete",
        "mcp__claude_ai_Claude_Docs__export",
        "mcp__claude_ai_Claude_Docs__guide",
        "mcp__claude_ai_Claude_Docs__query",
        "mcp__claude_ai_Claude_Docs__read",
        "mcp__claude_ai_Claude_Docs__update"
      ],
      "description": "Read vars username",
      "first_request": {
        "input": 2,
        "read": 12619,
        "total": 12621,
        "write": 0
      },
      "id": "a7fc05fbe170f4fe0",
      "last_line": "anis",
      "listed": {
        "Artifact": false,
        "ArtifactComments": false,
        "ArtifactData": false,
        "mcp__claude_ai_Claude_Docs": true
      },
      "names": [
        "CronCreate",
        "CronDelete",
        "CronList",
        "DesignSync",
        "EnterWorktree",
        "ExitWorktree",
        "Monitor",
        "PushNotification",
        "RemoteTrigger",
        "SendMessage",
        "TaskStop",
        "WebFetch",
        "WebSearch",
        "mcp__claude_ai_Claude_Docs__batch",
        "mcp__claude_ai_Claude_Docs__create",
        "mcp__claude_ai_Claude_Docs__delete",
        "mcp__claude_ai_Claude_Docs__export",
        "mcp__claude_ai_Claude_Docs__guide",
        "mcp__claude_ai_Claude_Docs__query",
        "mcp__claude_ai_Claude_Docs__read",
        "mcp__claude_ai_Claude_Docs__update"
      ],
      "parent": "a2603dda05c378af5",
      "tools_line": null
    }
  ],
  "session_id": "d82f2e18-db88-4ea2-af77-4e9a784868ba",
  "void": []
}
```

## Post-merge check (AC3)

Run after the user's `just switch`, with `<SWITCH>` and `<END>` in UTC (`%Y-%m-%dT%H:%M:%SZ`); `<END>` is the instant the check runs, and `agent-costs` requires both bounds together.

```text
just agent-costs --report cache --events-since <SWITCH> --events-before <END>              # after: issue-owner row
just agent-costs --report cache --events-since <SWITCH minus 7 days> --events-before <SWITCH>  # before: general-purpose row
```

Met when the before table's `general-purpose` (1st write + 1st read) minus the after table's `issue-owner` (1st write + 1st read) is at least 11,000 tokens, and `jq -r 'select(.type == "attachment" and .attachment.type == "deferred_tools_delta") | .attachment.addedNames[]'` over every subagent transcript whose `meta.json` `agentType` is `issue-owner` since `<SWITCH>` prints no `Artifact`, `ArtifactComments`, `ArtifactData` or `mcp__claude_ai_Claude_Docs__*` name. Record the two rows, `<SWITCH>`, `<END>`, the difference and the verdict in row `AC3`; until then the issue is held open (D8).
