{
  config,
  inputs,
  pkgs,
  lib,
  unstablePkgs,
  libx,
  myvars,
  ...
}:
{
  home.homeDirectory = "/Users/${myvars.username}";

  programs.zsh.initExtra = (builtins.readFile ../data/mac-dot-zshrc);

  imports = (libx.scanPaths ./darwin) ++ [ ];
}
