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
  home.homeDirectory = "/home/${myvars.username}";

  programs.zsh.initExtra = (builtins.readFile ../data/linux-dot-zshrc);

  imports = (libx.scanPaths ./linux/.) ++ [ ];
}
