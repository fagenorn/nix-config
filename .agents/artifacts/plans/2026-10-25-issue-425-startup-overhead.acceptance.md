# Acceptance record — issue 425

Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/425).

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] The reviewer-lite and mechanic agent definitions declare `omitClaudeMd: true`, and implementer and reviewer do not — measured: a frontmatter test in the skill/agent tests run by `just agent-workflow-tests` | code | `home/common/agent-skills/tests/test_agent_model_matrix.py::AgentModelMatrixTest::test_only_the_brief_driven_agents_omit_claude_md` (`omitClaudeMd` is `true` for `mechanic` and `reviewer-lite`, absent for `implementer` and `reviewer`), run by `just agent-workflow-tests` in sdd's final gate. | in final verification | — | — | met |
| AC2 | [code] The generated settings hide exactly the listed skills, and the orchestration launcher sets `ENABLE_CLAUDEAI_MCP_SERVERS=false` while the plain `claude` wrapper does not — measured: `just show-claude-settings` asserted in a test, plus a launcher test; `just build mbp` and the anis-desktop `nix eval` succeed | code | `tests/test_claude_code_installed.py`: `ClaudeSettingsInstalledTest::test_skill_overrides_hide_exactly_the_listed_skills` (the artifact `just show-claude-settings` prints), `ClaudeLaunchersInstalledTest::test_claude_orchestrate_turns_claude_ai_connectors_off` and `::test_plain_claude_leaves_claude_ai_connectors_alone`, run by `just agent-installed-skill-tests`, which builds mbp first; the anis-desktop evaluation is the PR's required `Nix Eval` job (D10). | `just agent-installed-skill-tests` (builds mbp first): `Ran 233 tests in 21.710s`, `OK (skipped=1)`, with `ClaudeSettingsInstalledTest::test_skill_overrides_hide_exactly_the_listed_skills`, `ClaudeLaunchersInstalledTest::test_claude_orchestrate_turns_claude_ai_connectors_off` and `::test_plain_claude_leaves_claude_ai_connectors_alone` passing (`ok`) within it; `just build mbp`: exit 0; anis-desktop nix eval: not evaluable on mbp (eval-time x86_64-linux build of catppuccin-starship, D10); verified by the PR's required Nix Eval check, a merge precondition on main | a9d25c99 (code equal to b337f3f2's) | host mbp; `bash -c 'set -o pipefail; just agent-installed-skill-tests 2>&1 \| grep -E "^(FAIL\|ERROR):\|^Ran \|^OK\|^FAILED\|expected exactly" \| tail -15'` run from the worktree root, exit 0, finished 2026-10-25T03:41:54Z; then `just build mbp`, exit 0, finished 2026-10-25T03:42:13Z; local anis-desktop evaluation `nix eval --raw .#nixosConfigurations.anis-desktop.config.system.build.toplevel.drvPath` fails with `Cannot build '/nix/store/2fcwq5hr44g54bmphnq1dffka559f7a3-catppuccin-starship-0-unstable-2025-08-01.drv'` (re-observed by the controller at a9d25c99) | unverified |
| AC3 | [evidence] A reviewer-lite first request is at least 2.5k tokens smaller than before; the skill-listing attachment shrinks by at least 30 %; an orchestration-launch subagent carries no claude.ai MCP instructions — measured: `just agent-costs` start-up overhead table before and after, on mbp | evidence | On mbp at the final code head, no activation: the Task 4 harness run before (deployed `claude`, deployed settings, base agents) and after (built `claude-orchestrate`, `--settings` the built file, branch agents), each read with `just agent-costs --report cache --projects-dir <that run's isolated copy> --events-since <start> --events-before <end>` and `scan_transcript`; thresholds: `reviewer-lite` first-request write+read at least 2,500 tokens smaller, `mechanic` `skill_listing` at least 30 % smaller, zero `claude.ai …` names in the after run's `mcp_instructions_delta` records. Acceptance-record row `AC3`; a void run is no measurement and nothing is tuned (D7, D9). | reviewer-lite first request 10,069 → 4,252 tokens, smaller by 5,817 (threshold 2,500: met); mechanic skill listing 20,888 → 14,183 characters, smaller by 32.1 % (threshold 30 %: met); after-run subagent claude.ai MCP servers: none (threshold none: met); after-run hidden_listed: {"reviewer-lite": [], "mechanic": []}; claude_ai_tools: {"reviewer-lite": 0, "mechanic": 0} | b337f3f2 | host mbp; ACCOUNT p1; CLAUDE_CONFIG_DIR /Users/anis/.claude-accounts/profiles/p1; deployed claude /nix/store/m2sa26z24fa5ashnimq0k62g7fvqqv7s-claude-code-with-accounts-2.1.302/bin/claude, --version 2.1.302 (Claude Code); built /nix/store/nradwrr9kzq9ip4qlfrsyl22pw0f2slm-claude-code-with-accounts-2.1.302/bin/claude --version 2.1.302 (Claude Code); PKG /nix/store/nradwrr9kzq9ip4qlfrsyl22pw0f2slm-claude-code-with-accounts-2.1.302; SETTINGS /nix/store/sgs618vwa18z30icwjflqqv03awnkar9-claude-code-settings.json; settings keys differing from the deployed file: hooks, inputNeededNotifEnabled, skillOverrides; before: `harness.sh before <worktree> <ac3> p1` (deployed claude, deployed settings, base agents), window 2026-10-25T03:13:26Z 2026-10-25T03:13:42Z, session 4c32e102-b463-4363-85fe-ba2f2c3e1f2f, cost $0.2352, claude_ai_servers ["claude.ai Claude Docs"]; after: `harness.sh after <worktree> <ac3> p1 /nix/store/nradwrr9kzq9ip4qlfrsyl22pw0f2slm-claude-code-with-accounts-2.1.302 /nix/store/sgs618vwa18z30icwjflqqv03awnkar9-claude-code-settings.json` (claude-orchestrate --settings built file, branch agents), window 2026-10-25T03:13:47Z 2026-10-25T03:14:02Z, session 011dd10f-6907-4913-a9f3-4453ef2b076e, cost $0.1047; transcripts found under $HOME/.claude/projects; no retry; not tuned (D7) | met |
| AC4 | [evidence] No regression: `just evals from-issue 1` passes with the trimmed settings and `ENABLE_CLAUDEAI_MCP_SERVERS=false` in its environment — measured: eval verdict on mbp | evidence | On mbp at the final code head: `CLAUDE_ACCOUNT=<the caller's account> EVAL_TREE=<worktree> EVAL_SETTINGS=<built settings> ENABLE_CLAUDEAI_MCP_SERVERS=false just evals from-issue 1`; threshold: `VERDICT: PASS` and exit 0. Acceptance-record row `AC4` (D7). | `VERDICT: PASS (9/9 asserts)`; 9 PASS / 0 FAIL asserts; no FAIL asserts; threshold VERDICT: PASS: met | 0095074c | host mbp; ACCOUNT p1; `CLAUDE_ACCOUNT=p1 EVAL_TREE=/Users/anis/tmp/nix-config/.worktrees/worktree-issue-425-orchestrated EVAL_SETTINGS=/nix/store/sgs618vwa18z30icwjflqqv03awnkar9-claude-code-settings.json ENABLE_CLAUDEAI_MCP_SERVERS=false just evals from-issue 1` run from the worktree root (default model, default EVAL_TIMEOUT, one trial); finished 2026-10-25T03:35:15Z, exit 0 after 1139 seconds; results row ts 2026-10-25T03:35:15Z, wall_s 1136, cost_usd 3.6777; `claude exited 0 after 1136s`; tree_rev 0095074cb3979b2518d0a95e8013da2519bed6d8, tree_dirty false; one trial, not rerun (D7) | met |

## AC3 run output

### Before

```text
Subagent start-up (first request's cache write and read; characters of each start-up attachment sent before the second request; medians over the subagents that carried it):

agent type     subagents  1st write  1st read  skill listing  instructions  MCP instructions  deferred tools  agent listing  environment
-------------  ---------  ---------  --------  -------------  ------------  ----------------  --------------  -------------  -----------
mechanic               1     22.93k         0         20.89k        15.11k             2.05k             786          2.77k          808
reviewer-lite          1     10.07k         0              -        15.11k             2.05k               -              -          808

NOTE: cache reads measure logical context re-processing (tokens the model
```

### After

```text
Subagent start-up (first request's cache write and read; characters of each start-up attachment sent before the second request; medians over the subagents that carried it):

agent type     subagents  1st write  1st read  skill listing  instructions  MCP instructions  deferred tools  agent listing  environment
-------------  ---------  ---------  --------  -------------  ------------  ----------------  --------------  -------------  -----------
mechanic               1      6.75k     7.16k         14.18k             -                 -             446          2.77k          807
reviewer-lite          1      2.02k     2.23k              -             -                 -               -              -          807

NOTE: cache reads measure logical context re-processing (tokens the model
```

### Measurement

```json
{
  "after": {
    "cost_usd": 0.1047175,
    "rows": [
      {
        "agent_type": "main",
        "claude_ai_servers": [],
        "claude_ai_tools": 0,
        "hidden_listed": [],
        "startup": null
      },
      {
        "agent_type": "reviewer-lite",
        "claude_ai_servers": [],
        "claude_ai_tools": 0,
        "hidden_listed": [],
        "startup": {
          "attachments": {
            "environment": 807
          },
          "read": 2231,
          "write": 2021
        }
      },
      {
        "agent_type": "mechanic",
        "claude_ai_servers": [],
        "claude_ai_tools": 0,
        "hidden_listed": [],
        "startup": {
          "attachments": {
            "agent_listing_delta": 2767,
            "deferred_tools_delta": 446,
            "environment": 807,
            "skill_listing": 14183
          },
          "read": 7162,
          "write": 6753
        }
      }
    ],
    "session_id": "011dd10f-6907-4913-a9f3-4453ef2b076e",
    "void": []
  },
  "before": {
    "cost_usd": 0.2351591,
    "rows": [
      {
        "agent_type": "main",
        "claude_ai_servers": [
          "claude.ai Claude Docs"
        ],
        "claude_ai_tools": 8,
        "hidden_listed": [
          "anthropic-skills:docx",
          "anthropic-skills:google-workspace",
          "anthropic-skills:import-memory",
          "anthropic-skills:morning",
          "anthropic-skills:pdf",
          "anthropic-skills:pptx",
          "anthropic-skills:skill-creator",
          "anthropic-skills:xlsx",
          "dataviz"
        ],
        "startup": null
      },
      {
        "agent_type": "reviewer-lite",
        "claude_ai_servers": [
          "claude.ai Claude Docs"
        ],
        "claude_ai_tools": 0,
        "hidden_listed": [],
        "startup": {
          "attachments": {
            "environment": 808,
            "instructions": 15108,
            "mcp_instructions_delta": 2053
          },
          "read": 0,
          "write": 10069
        }
      },
      {
        "agent_type": "mechanic",
        "claude_ai_servers": [
          "claude.ai Claude Docs"
        ],
        "claude_ai_tools": 8,
        "hidden_listed": [
          "anthropic-skills:docx",
          "anthropic-skills:google-workspace",
          "anthropic-skills:import-memory",
          "anthropic-skills:morning",
          "anthropic-skills:pdf",
          "anthropic-skills:pptx",
          "anthropic-skills:skill-creator",
          "anthropic-skills:xlsx",
          "dataviz"
        ],
        "startup": {
          "attachments": {
            "agent_listing_delta": 2767,
            "deferred_tools_delta": 786,
            "environment": 808,
            "instructions": 15108,
            "mcp_instructions_delta": 2053,
            "skill_listing": 20888
          },
          "read": 0,
          "write": 22933
        }
      }
    ],
    "session_id": "4c32e102-b463-4363-85fe-ba2f2c3e1f2f",
    "void": []
  },
  "thresholds": {
    "after_subagent_claude_ai_servers": [],
    "mechanic_listing_smaller_by": 0.321,
    "met_2500": true,
    "met_30pct": true,
    "met_none": true,
    "reviewer_lite_first_request_smaller_by": 5817
  }
}
```

## AC4 eval output

```text
claude exited 0 after 1136s
PASS  a worktree was created
PASS  spec file exists under the retained specifications directory
PASS  spec logs at least one decision (ledger row or legacy auto-resolved entry)
PASS  plan file exists under the retained plans directory
PASS  every plan task has a falsifiable verification line
PASS  the plan's acceptance map has one row per issue criterion
PASS  spec and plan commits landed in the worktree
PASS  the base branch carries no spec or plan commits
PASS  the implementation was not executed
VERDICT: PASS (9/9 asserts)
```

```json
{"ts":"2026-10-25T03:35:15Z","skill":"from-issue","id":1,"name":"well-specified-through-phase-5","mode":"pipeline","model":"sonnet","trial":1,"trials":1,"verdict":"PASS","passed":9,"failed":0,"total":9,"wall_s":1136,"claude_exit":0,"workdir":"/private/var/folders/t4/b5y8ggd92zb044029__7wr9w0000gp/T/eval-from-issue-1.6O87Is","eval_max_usd":null,"asserts":[{"name":"a worktree was created","pass":true},{"name":"spec file exists under the retained specifications directory","pass":true},{"name":"spec logs at least one decision (ledger row or legacy auto-resolved entry)","pass":true},{"name":"plan file exists under the retained plans directory","pass":true},{"name":"every plan task has a falsifiable verification line","pass":true},{"name":"the plan's acceptance map has one row per issue criterion","pass":true},{"name":"spec and plan commits landed in the worktree","pass":true},{"name":"the base branch carries no spec or plan commits","pass":true},{"name":"the implementation was not executed","pass":true}],"tree":"/Users/anis/tmp/nix-config/.worktrees/worktree-issue-425-orchestrated","tree_rev":"0095074cb3979b2518d0a95e8013da2519bed6d8","tree_dirty":false,"tree_mode":"project-skills","input_tokens":10804444,"uncached_input_tokens":188,"cache_read_input_tokens":10551904,"cache_creation_input_tokens":252352,"output_tokens":135044,"cost_usd":3.677653200000001,"num_turns":132,"models":["claude-opus-5-5","claude-sonnet-5-5"]}
```
