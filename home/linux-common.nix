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

  programs.zsh.initContent = ''
    ${libx.mergeFilesOrdered [
      ../data/zshrc/linux
      ../data/zshrc/common
    ]}
  '';

  imports = (libx.scanPaths ./linux) ++ [ ];
}
