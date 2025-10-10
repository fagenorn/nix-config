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
    ${libx.mergeFilesOrdered {
      dirs = [
        ../data/zshrc/linux
        ../data/zshrc/common
      ];
      sep = "\n";
    }}
  '';

  imports = (libx.scanPaths ./linux) ++ [ ];
}
