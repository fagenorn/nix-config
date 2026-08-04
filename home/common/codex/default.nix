{
  inputs,
  lib,
  pkgs,
  ...
}:
let
  agentPlugins = import ../../../lib/agent-plugins.nix { inherit inputs pkgs; };
  codexPackage = inputs.codex-cli.packages.${pkgs.system}.default;

  personalMarketplace = (pkgs.formats.json { }).generate "codex-personal-marketplace.json" {
    name = "personal";
    interface.displayName = "Personal";
    plugins = [
      {
        name = "superpowers";
        source = {
          source = "local";
          path = "./plugins/superpowers";
        };
        policy = {
          installation = "AVAILABLE";
          authentication = "ON_INSTALL";
        };
        category = "Developer Tools";
      }
    ];
  };
in
{
  # Native Codex CLI from the hourly-updated flake. The flake lock keeps each
  # deployed generation reproducible; `just update` advances it to the latest release.
  home.packages = [ codexPackage ];

  # Superpowers is a multi-skill bundle whose internal calls use qualified
  # names such as `superpowers:brainstorming`. Installing it as a native plugin
  # preserves that namespace; exposing it as standalone skills would not.
  home.file."plugins/superpowers".source = agentPlugins.superpowersCodex;
  home.file.".agents/plugins/marketplace.json".source = personalMarketplace;

  # Keep Codex's runtime-managed config writable (plugins and marketplaces also
  # use it), while declaratively enforcing the global default reasoning effort.
  home.activation.codexConfig = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    cfg="$HOME/.codex/config.toml"
    run mkdir -p "$HOME/.codex"
    tmp="$cfg.hm-tmp.$$"
    input=/dev/null
    [ -f "$cfg" ] && input="$cfg"

    ${pkgs.gawk}/bin/awk '
      BEGIN {
        print "model_reasoning_effort = \"xhigh\""
        in_top_level = 1
      }
      /^[[:space:]]*\[/ { in_top_level = 0 }
      in_top_level && /^[[:space:]]*model_reasoning_effort[[:space:]]*=/ { next }
      { print }
    ' "$input" > "$tmp"

    chmod 600 "$tmp"
    mv -f "$tmp" "$cfg"
  '';

  # Local plugins are loaded from Codex's mutable install cache, not directly
  # from the marketplace source. Reinstalling is idempotent and refreshes that
  # cache whenever the pinned source or repo-owned patch changes.
  home.activation.codexSuperpowersPlugin =
    lib.hm.dag.entryAfter
      [
        "codexConfig"
        "linkGeneration"
      ]
      ''
        run ${codexPackage}/bin/codex plugin add superpowers@personal --json
      '';
}
