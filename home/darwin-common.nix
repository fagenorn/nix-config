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
    ${libx.mergeFilesOrdered [
      ../data/zshrc/darwin
      ../data/zshrc/common
    ]}
  '';

  imports = (libx.scanPaths ./darwin) ++ [ ];
}
