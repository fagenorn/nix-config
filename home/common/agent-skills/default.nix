{
  inputs,
  pkgs,
  ...
}:
let
  agentPlugins = import ../../../lib/agent-plugins.nix { inherit inputs pkgs; };

  uiUxSkill = pkgs.runCommand "ui-ux-pro-max-skill" { } ''
    mkdir -p "$out"
    {
      printf '%s\n' \
        '---' \
        'name: ui-ux-pro-max' \
        'description: Comprehensive design intelligence for web, mobile, and desktop UI/UX work. Use when designing, building, reviewing, or improving interfaces, design systems, accessibility, typography, colors, layouts, interactions, animations, or data visualizations.' \
        '---'
      sed \
        -e 's/{{TITLE}}/UI\/UX Pro Max/g' \
        -e 's/{{DESCRIPTION}}/Searchable UI\/UX design guidance with priority-based recommendations across 22 technology stacks./g' \
        -e 's/{{QUICK_REFERENCE}}//g' \
        -e 's/{{SKILL_OR_WORKFLOW}}/Skill/g' \
        -e 's#python3 skills/ui-ux-pro-max/#python3 ~/.agents/skills/ui-ux-pro-max/#g' \
        ${inputs.ui-ux-pro-max}/cli/assets/templates/base/skill-content.md
    } > "$out/SKILL.md"
    cp -R ${inputs.ui-ux-pro-max}/cli/assets/data "$out/data"
    cp -R ${inputs.ui-ux-pro-max}/cli/assets/scripts "$out/scripts"
  '';
in
{
  # Canonical cross-agent skill library. Claude Code consumes the same source
  # via programs.claude-code.skillsDir; Codex discovers global skills here.
  # `recursive` keeps ~/.agents/skills as a real directory containing links,
  # rather than making the whole directory an immutable store symlink.
  home.file.".agents/skills" = {
    source = ./skills;
    recursive = true;
  };

  # Claude's local Superpowers plugin and Codex both consume this exact patched
  # skill tree, so the two agents cannot drift in workflow composition.
  home.file.".agents/skills/superpowers" = {
    source = agentPlugins.superpowers + "/skills";
    recursive = true;
  };

  # UI/UX Pro Max uses one generated universal skill for both agents. This
  # replaces its Claude-only marketplace plugin and avoids maintaining copies.
  home.file.".agents/skills/ui-ux-pro-max" = {
    source = uiUxSkill;
    recursive = true;
  };
  home.file.".claude/skills/ui-ux-pro-max" = {
    source = uiUxSkill;
    recursive = true;
  };

  home.packages = [ pkgs.python3 ];
}
