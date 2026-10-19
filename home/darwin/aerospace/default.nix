{
  lib,
  libx,
  osConfig,
  ...
}:
{
  config = lib.mkIf (libx.hasCask osConfig "nikitabobko/tap/aerospace") {
    home.file.".aerospace.toml".source = ./aerospace.toml;
  };
}
