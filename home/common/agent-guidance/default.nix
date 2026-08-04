{ ... }:
{
  # Canonical global agent instructions. Claude Code references this same file
  # through programs.claude-code.memory; Codex discovers it at AGENTS.md.
  home.file.".codex/AGENTS.md".source = ./AGENTS.md;
}
