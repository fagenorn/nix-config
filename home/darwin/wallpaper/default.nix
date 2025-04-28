{
  lib,
  ...
}:
with lib;
let
  cfg = lib.mkDefault ../../../assets/woah.jpg;
in
{
  options = {
    services.darwin-wallpaper.file = mkOption {
      type = with types; nullOr path;
      default = null;
      description = "Path to image for wallpaper";
    };
  };

  home.activation = {
    setDarwinWallpaper = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      osascript -e 'tell application "Finder" to set desktop picture to "${cfg.file}" as POSIX file'
    '';
  };
}
