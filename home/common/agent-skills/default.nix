{
  inputs,
  lib,
  pkgs,
  agentTools,
  ...
}:
let
  impeccable = import ../../../lib/impeccable.nix { inherit inputs lib pkgs; };

  # Skills this config used to install. Home Manager's own old-generation
  # cleanup removes their links on switch (#238 D6). The step below only
  # reports a retired directory that is still present, because whatever is
  # left in it is not Home Manager's to delete.
  retiredSkillNames = [ "ui-ux-pro-max" "orchestrate-issues" ];

  # Each command-table row of lib/agent-tools.nix becomes ~/.agents/bin/<name>.
  # It enters home.file as a separate definition, so a leftover hand-written
  # entry for the same command is a conflicting definition, not a silent win.
  agentToolFiles = lib.mapAttrs' (
    name: launcher: lib.nameValuePair ".agents/bin/${name}" { source = launcher; }
  ) agentTools.launchers;
in
{
  # Claude Code consumes the authored skill sources through skillsDir
  # (home/common/claude-code); nothing here installs a skill view for Codex.
  home.file = lib.mkMerge [ {
    ".agents/bin/impeccable".source = impeccable.launcher;

    # Layers 0 and 1 of the standards architecture, machine-global so every
    # project inherits the bar and its stack's trap library. Layer 2 (project
    # deltas) stays in each repo under docs/standards/.
    ".agents/standards".source = ./standards;

    ".agents/bin/workflow-state".source =
      agentTools.scriptLauncher "workflow-state" ./scripts/workflow-state.py;

    ".agents/bin/artifact-budget" = {
      source = ./scripts/artifact-budget;
      executable = true;
    };

    ".agents/bin/sdd-workspace" = {
      source = ./skills/sdd/scripts/sdd-workspace;
      executable = true;
    };

    ".agents/bin/task-brief" = {
      source = ./skills/sdd/scripts/task-brief;
      executable = true;
    };

    # The artifact-budget module. The `artifact-budget` wrapper runs it, and
    # `workflow-state` loads the store file this link resolves to into its own
    # process (issue 498 D2, D7).
    ".agents/lib/python/artifact_budget.py".source = ./scripts/artifact_budget.py;
    # The `workflow-state` command, which its entry point imports (issue 612).
    ".agents/lib/python/workflow_state.py".source = ./scripts/workflow_state.py;
    ".agents/lib/python/workflow_delivery.py".source = ./scripts/workflow_delivery.py;
    ".agents/lib/python/workflow_delivery_wire.py".source = ./scripts/workflow_delivery_wire.py;
    ".agents/lib/python/workflow_delivery_build.py".source = ./scripts/workflow_delivery_build.py;
    ".agents/lib/python/delivery_model" = {
      source = ./scripts/delivery_model;
      recursive = false;
    };
    ".agents/share/artifact-budget-policy.json".source = ./artifact-budget-policy.json;
    ".agents/share/ship-delivery.md".source = ../../../python/ship-delivery.md;

    # The platform manifest: authored data with nothing templated, so this
    # store copy is byte-identical to the repository's (D1).
    ".agents/share/platform-manifest.json".source = ./platform-manifest.json;

    # The host admission library and the host declaration it reads. The
    # declaration is authored host policy -- per route, whether it is supported
    # and how many agent slots one root session may hold -- read by
    # `workflow-state` and the conformance check through that library (D2, D18).
    # The library lives in the agent_tools package; this copy serves only
    # `workflow-state`'s transitional installed-layout load, and #178 deletes it
    # (#177 D6).
    ".agents/lib/python/host_admission.py".source = ../../../python/agent_tools/host_admission.py;
    ".agents/share/host-declaration.json".source = ./host-declaration.json;

    # Claude accepts Home Manager's recursive file links, so its view of the
    # multi-file Impeccable skill uses that layout.
    ".claude/skills/impeccable" = {
      source = impeccable.skill;
      recursive = true;
    };
  } agentToolFiles ];

  # Nix owns the Impeccable version, and the store is read-only (#238 D5).
  home.sessionVariables.IMPECCABLE_NO_UPDATE_CHECK = "1";

  home.activation.reportRetiredSkills = lib.hm.dag.entryAfter [ "linkGeneration" ] ''
    for skillRoot in "$HOME/.claude/skills"; do
      for skillName in ${lib.escapeShellArgs retiredSkillNames}; do
        target="$skillRoot/$skillName"
        if [ ! -e "$target" ] && [ ! -L "$target" ]; then
          continue
        fi
        if ! ${pkgs.findutils}/bin/find "$target" >/dev/null; then
          warnEcho "Retired skill $target is still present but could not be fully inspected (see the find errors above). Check it by hand."
          continue
        fi
        foreign=""
        while IFS= read -r -d "" entry; do
          if [ -d "$entry" ] && [ ! -L "$entry" ]; then
            continue
          fi
          if [ -L "$entry" ]; then
            case "$(${pkgs.coreutils}/bin/readlink "$entry" || true)" in
              /nix/store/*-home-manager-files/*) continue ;;
            esac
          fi
          foreign="$entry"
          break
        done < <(${pkgs.findutils}/bin/find "$target" -print0 2>/dev/null || true)
        if [ -n "$foreign" ]; then
          warnEcho "Retired skill $target is still present: $foreign is not a Home Manager link, so it was left in place. Remove it by hand."
        else
          warnEcho "Retired skill $target is still present but holds only empty directories or Home Manager links."
        fi
      done
    done
    unset skillRoot skillName target foreign entry
  '';

  # Installed agent modules are links into the store, where every file has
  # modification time 1, so bytecode cached beside a link could outlive a
  # same-size edit. Once the links are updated, every activation removes the
  # library's bytecode cache; a failure is reported and the switch goes on
  # (issue 567; README § Installed module library).
  home.activation.clearAgentModuleBytecode = lib.hm.dag.entryAfter [ "linkGeneration" ] ''
    run ${pkgs.runtimeShell} ${./scripts/clear-library-bytecode} "$HOME/.agents/lib/python" \
      || errorEcho "Clearing $HOME/.agents/lib/python/__pycache__ failed (see the error above). While it remains, an installed agent module may run stale bytecode: remove it and any .pycache-clear.* directory beside it by hand."
  '';

  # The workflow skills invoke these helpers by bare name (`workflow-state`,
  # `agent-evidence`), so ~/.agents/bin must be on PATH or every spawned agent
  # shell gets exit 127 — the failure codex-companion hit before it was wrapped
  # onto PATH (see home/common/claude-code/default.nix).
  home.sessionPath = [ "$HOME/.agents/bin" ];

  home.packages = [ pkgs.python3 ];
}
