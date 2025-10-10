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
    ${
      let
        dir = ../data/zshrc/darwin;
        entries = builtins.readDir dir;
        files = builtins.attrNames (lib.filterAttrs (_: t: t == "regular") entries);
        contents = map (name: builtins.readFile "${dir}/${name}") files;
      in
      builtins.concatStringsSep "\n" contents
    }
  '';

  imports = (libx.scanPaths ./darwin) ++ [ ];
}
