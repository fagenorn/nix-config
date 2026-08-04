{
  inputs,
  lib,
  pkgs,
  ...
}:
{
  # Native Codex CLI from the hourly-updated flake. The flake lock keeps each
  # deployed generation reproducible; `just update` advances it to the latest release.
  home.packages = [ inputs.codex-cli.packages.${pkgs.system}.default ];

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
}
