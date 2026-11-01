{
  lib,
  libx,
  osConfig,
  ...
}:
{
  # Starsector ships unsigned (why the upstream homebrew-cask entry is disabled with
  # `fails_gatekeeper_check`); it is installed from the self-authored fagenorn/palmier tap
  # (homebrew/palmier-tap/Casks/starsector.rb). As with darktable, Homebrew stamps
  # com.apple.quarantine on the app and Gatekeeper then refuses to open it, so this step,
  # ordered after the nix-darwin `brew bundle`, strips it after every (re)install.
  # Idempotent: a no-op when the app is absent or already clean.
  config = lib.mkIf (libx.hasCask osConfig "fagenorn/palmier/starsector") {
    home.activation.starsectorDequarantine = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      if [ -d /Applications/Starsector.app ] \
        && /usr/bin/xattr -p com.apple.quarantine /Applications/Starsector.app >/dev/null 2>&1; then
        run /usr/bin/xattr -dr com.apple.quarantine /Applications/Starsector.app
      fi
    '';
  };
}
