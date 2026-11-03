# Acceptance record — issue #467

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|---|---|---|---|---|---|---|---|
| AC1 | claude-guard-row-check --repository elevenyellow/jarbird returns derived for a project bound to github-actions-health with release profile forge-main. | human | Reporter runs `claude-guard-row-check --repository elevenyellow/jarbird` after switching their generation. | — | — | — | human_pending |
| AC2 | Every installed agent_tools wrapper resolves the same agent_tools store path, with a check that pins this. | code | `python3 -m unittest -v tests.test_agent_tools_launchers.AgentToolsLauncherTest -k system_closure` | Conformance reviewer ran all three named closure tests: passed, no skips. | 36cf57fd1004983a4c541de823d1a7d8a9f211e3 | Built Linux system result; AGENT_SKILLS_INSTALLED_HOME and AGENT_TOOLS_SYSTEM_RESULT set. | met |
| AC3 | gh pr create --repo elevenyellow/jarbird --base main --head dev passes the lifecycle guard. | human | Reporter runs `gh pr create --repo elevenyellow/jarbird --base main --head dev` in a new Claude Code session after switching their generation. | — | — | — | human_pending |
