{
  inputs,
  pkgs,
  ...
}:
let
  codexPackage = inputs.codex-cli.packages.${pkgs.system}.default;
in
{
  # Native Codex CLI from the hourly-updated flake. The flake lock keeps each
  # deployed generation reproducible; `just update` advances it to the latest release.
  # Codex runs only as the reviewer behind `codex-companion` (see
  # home/common/claude-code/default.nix), so Nix installs the binary and nothing
  # else: no skills, guidance or config splice for Codex.
  home.packages = [ codexPackage ];
}
