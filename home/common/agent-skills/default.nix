{
  inputs,
  lib,
  pkgs,
  ...
}:
let
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

  # Home Manager's recursive directory mode creates real directories whose
  # individual files are store symlinks. Codex ignores a skill when SKILL.md
  # itself is a symlink, but supports a symlink to the whole skill directory.
  localSkillSources = lib.filterAttrs (_: type: type == "directory") (builtins.readDir ./skills);
  localSkillNames = builtins.attrNames localSkillSources;
  localSkillFiles = lib.mapAttrs' (
    name: _:
    lib.nameValuePair ".agents/skills/${name}" {
      source = ./skills + "/${name}";
    }
  ) localSkillSources;
in
{
  # Keep ~/.agents/skills writable while linking each complete skill directory.
  # Claude Code consumes the same authored sources through skillsDir below.
  home.file = localSkillFiles // {
    ".agents/skills/ui-ux-pro-max".source = uiUxSkill;

    # Layers 0 and 1 of the standards architecture, machine-global so every
    # project inherits the bar and its stack's trap library. Layer 2 (project
    # deltas) stays in each repo under docs/standards/.
    ".agents/standards".source = ./standards;

    # Stable path project CIs can call without vendoring the script.
    ".agents/bin/context-map-lint" = {
      source = ../../../scripts/context-map-lint.py;
      executable = true;
    };

    ".agents/bin/workflow-state" = {
      source = ./scripts/workflow-state.py;
      executable = true;
    };

    ".agents/bin/resolve-project" = {
      source = ./scripts/resolve-project.py;
      executable = true;
    };

    ".agents/bin/conformance" = {
      source = ./scripts/conformance.py;
      executable = true;
    };

    ".agents/bin/agent-model-matrix" = {
      source = ./scripts/agent-model-matrix.py;
      executable = true;
    };

    ".agents/bin/resolve-bindings" = {
      source = ./scripts/resolve-bindings;
      executable = true;
    };

    ".agents/bin/agent-evidence" = {
      source = ./scripts/agent-evidence.py;
      executable = true;
    };

    ".agents/bin/diff-scope" = {
      source = ./scripts/diff-scope.py;
      executable = true;
    };

    ".agents/bin/artifact-budget" = {
      source = ./scripts/artifact-budget;
      executable = true;
    };

    # ship-issue's Phase-8 delivery-detail producer. It lives in the sdd skill
    # tree, but a consumer outside that skill knows it only by bare name — an
    # agent that goes looking finds every other bare-name helper here, so this
    # one has to be here too (observed: a ship-issue cleanup wrongly retained a
    # worktree after concluding no producer existed on the machine). It resolves
    # its workspace sibling via Path(__file__).with_name, so the two ship
    # together: exposing one without the other breaks diff mode.
    ".agents/bin/review-package" = {
      source = ./skills/sdd/scripts/review-package;
      executable = true;
    };

    ".agents/bin/sdd-workspace" = {
      source = ./skills/sdd/scripts/sdd-workspace;
      executable = true;
    };

    ".agents/lib/python/artifact_budget.py".source = ./scripts/artifact_budget.py;
    ".agents/share/artifact-budget-policy.json".source = ./artifact-budget-policy.json;

    # Claude accepts Home Manager's recursive file links, so its generated
    # multi-file skill can continue to use that layout.
    ".claude/skills/ui-ux-pro-max" = {
      source = uiUxSkill;
      recursive = true;
    };
  };

  # One-time migration from the previous `recursive = true` layout. Those
  # generations leave a real directory at each target, which would collide
  # with the new whole-directory link before Home Manager gets to old-link
  # cleanup. Remove a directory only when every leaf is demonstrably one of
  # Home Manager's old store links; refuse to touch user-authored content.
  home.activation.migrateCodexSkillLinks = lib.hm.dag.entryBefore [ "checkLinkTargets" ] ''
    migrateCodexSkillLink() {
      skillName="$1"
      target="$HOME/.agents/skills/$skillName"

      if [ ! -d "$target" ] || [ -L "$target" ]; then
        return 0
      fi

      while IFS= read -r -d "" entry; do
        if [ -d "$entry" ] && [ ! -L "$entry" ]; then
          continue
        fi

        if [ -L "$entry" ]; then
          linkTarget=$(${pkgs.coreutils}/bin/readlink "$entry")
          case "$linkTarget" in
            /nix/store/*-home-manager-files/.agents/skills/"$skillName"/*)
              continue
              ;;
          esac
        fi

        errorEcho "Refusing to replace $target because it contains content not owned by the previous Home Manager skill layout: $entry"
        return 1
      done < <(${pkgs.findutils}/bin/find "$target" -mindepth 1 -print0)

      verboseEcho "Replacing legacy recursive skill directory $target"
      run ${pkgs.coreutils}/bin/rm -rf -- "$target"
    }

    for skillName in ${lib.escapeShellArgs (localSkillNames ++ [ "ui-ux-pro-max" ])}; do
      migrateCodexSkillLink "$skillName" || exit 1
    done
    unset -f migrateCodexSkillLink
  '';

  # The workflow skills invoke these helpers by bare name (`workflow-state`,
  # `agent-evidence`), so ~/.agents/bin must be on PATH or every spawned agent
  # shell gets exit 127 — the failure codex-companion hit before it was wrapped
  # onto PATH (see home/common/claude-code/default.nix).
  home.sessionPath = [ "$HOME/.agents/bin" ];

  home.packages = [ pkgs.python3 ];
}
