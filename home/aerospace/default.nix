{ lib, pkgs, ... }:
{
    home.file = lib.mkMerge [
    (lib.mkIf pkgs.stdenv.isDarwin {
      ".aerospace.toml".source = ./aerospace.toml;
    })
  ];
}
