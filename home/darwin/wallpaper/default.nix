{
  config,
  lib,
  pkgs,
  ...
}:
{
  services.darwin-wallpaper.file = lib.mkDefault ./hearts.png;
}
