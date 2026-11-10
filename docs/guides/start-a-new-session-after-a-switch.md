# Start a new session after a switch

A process started before a switch can keep old store paths, so start a new Claude Code session after switching an agent_tools change. `/hooks` shows that session's loaded hook command, and `just show-claude-settings` shows the generation's registered path. A host that has not switched to a generation containing an adapter still runs the previous code throughout.
