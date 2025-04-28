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
    package =
      if pkgs.stdenv.isDarwin then
        pkgs.hello # pkgs.ghostty is currently broken on darwin
      else
        pkgs.ghostty;
    enableBashIntegration = false;
    installBatSyntax = false;
    settings = {
      font-family = "FiraCode Nerd Font Mono";
      font-size = 13;

      background-opacity = 0.93;

      # only supported on macOS;
      background-blur-radius = 10;
      scrollback-limit = 20000;
    };
  };
}
