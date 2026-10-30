{
  lib,
  pkgs,
  config,
  ...
}:
let
  inherit (config.catppuccin) sources;

  cfg = config.catppuccin.ghostty;
  themeName = "catppuccin-${cfg.flavor}";
in
{
  #   xdg.configFile = {
  #     "ghostty/themes/${themeName}".source = "${sources.ghostty}/${themeName}.conf";
  #   };

  programs.ghostty = {
    enable = true;
    # pkgs.ghostty is broken on darwin, where the Homebrew cask provides the app. A null package
    # also drops home-manager's `+validate-config` onChange hook, which otherwise aborts the
    # activation (before launchd agents and sops-nix) whenever the config file changes.
    package = if pkgs.stdenv.isDarwin then null else pkgs.ghostty;
    enableBashIntegration = false;
    installBatSyntax = false;
    settings = {
      font-family = "GeistMono Nerd Font Mono";
      font-size = 13;

      background-opacity = 0.93;

      # only supported on macOS;
      background-blur-radius = 10;
      scrollback-limit = 20000;
    };
  };
}
