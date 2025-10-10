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

  programs.zsh.initContent = ''
    ${libx.mergeFilesOrdered {
      dirs = [
        ../data/zshrc/darwin
        ../data/zshrc/common
      ];
      sep = "\n";
    }}
  '';

  imports = (libx.scanPaths ./darwin) ++ [ ];
}
