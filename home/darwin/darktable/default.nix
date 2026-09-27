{ lib, pkgs, config, ... }:
let
  # photo-import: card -> ~/Pictures/darktable/Travel/<year>/<trip>, geotag from a Google Maps
  # Timeline export, open darktable. The whole "sync location data" chore from the Lightroom days.
  photoImport = pkgs.writeShellApplication {
    name = "photo-import";
    runtimeInputs = [ pkgs.python3 pkgs.exiftool ];
    text = ''exec python3 ${./photo-import.py} "$@"'';
  };
  # timeline-to-gpx: the converter on its own, for darktable's map view "apply GPX file" route.
  timelineToGpx = pkgs.writeShellApplication {
    name = "timeline-to-gpx";
    runtimeInputs = [ pkgs.python3 ];
    text = ''
      [ $# -eq 2 ] || { echo "usage: timeline-to-gpx Timeline.json out.gpx" >&2; exit 2; }
      python3 - "$1" "$2" <<'EOF'
      import sys, runpy
      m = runpy.run_path("${./photo-import.py}", run_name="lib")
      print(m["timeline_to_gpx"](sys.argv[1], sys.argv[2]), "track points written")
      EOF
    '';
  };
  photosImportExports = pkgs.writeShellApplication {
    name = "photos-import-exports";
    runtimeInputs = [ pkgs.coreutils pkgs.findutils ];
    text = builtins.readFile ./photos-import-exports.sh;
  };
in
{
  home.packages = [ pkgs.exiftool photoImport timelineToGpx photosImportExports ];

  # darktable ships as an unnotarized DMG (which is why the upstream homebrew-cask entry is
  # disabled with `fails_gatekeeper_check`); it is installed from the self-authored
  # fagenorn/palmier tap (homebrew/palmier-tap/Casks/darktable.rb). Homebrew stamps
  # com.apple.quarantine on every cask app it installs regardless of the system-wide
  # LSQuarantine=false default, and Gatekeeper then refuses to open the unnotarized bundle
  # ("Apple could not verify ..."). This home-manager step runs after the nix-darwin
  # `brew bundle` (home-manager activation is ordered after it in the system activation
  # script), so the attribute is stripped again after every (re)install. Idempotent: a
  # no-op when the app is absent or already clean.
  home.activation.darktableDequarantine = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    if [ -d /Applications/darktable.app ] \
      && /usr/bin/xattr -p com.apple.quarantine /Applications/darktable.app >/dev/null 2>&1; then
      run /usr/bin/xattr -dr com.apple.quarantine /Applications/darktable.app
    fi
  '';

  # darktable rewrites darktablerc/shortcutsrc itself on every exit, so they cannot be store
  # symlinks. Instead the Lightroom-style settings (import layout, sidecars, export target,
  # G/E/X/P/6-9 shortcuts) are merged into the live files at activation; see the script for the
  # exact keys. Skipped while darktable runs (it would clobber the change on exit).
  home.activation.darktableSettings = lib.hm.dag.entryAfter [ "darktableDequarantine" ] ''
    run env DARKTABLE_STYLES_DIR=${./styles} DARKTABLE_STYLE_IMPORTER=${./import-dtstyles.py} \
      ${pkgs.python3}/bin/python3 ${./darktable-settings.py}
  '';

  # ~/Pictures/exports -> Photos (iCloud). darktable's export module targets that folder; every
  # JPEG that lands there is imported into Photos and moved to exports/.imported/. WatchPaths
  # fires on any change to the folder; the hourly interval catches files written while the
  # agent was busy. Photos asks for Automation permission the first time (System Settings ->
  # Privacy & Security -> Automation -> photos-import-exports).
  launchd.agents.photos-import-exports = {
    enable = true;
    config = {
      ProgramArguments = [ "${photosImportExports}/bin/photos-import-exports" ];
      WatchPaths = [ "${config.home.homeDirectory}/Pictures/exports" ];
      StartInterval = 3600;
      RunAtLoad = false;
      StandardErrorPath = "${config.home.homeDirectory}/Library/Logs/photos-import-exports.err";
    };
  };
}
