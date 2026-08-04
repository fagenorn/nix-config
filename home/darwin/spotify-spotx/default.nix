{
  inputs,
  lib,
  pkgs,
  ...
}:
let
  toolPath = lib.makeBinPath [
    pkgs.bash
    pkgs.perl
    pkgs.zip
    pkgs.unzip
  ];
in
{
  # nix-darwin runs Homebrew activation before the Home Manager user activation,
  # so Spotify has already been installed/upgraded when this helper executes.
  home.activation.spotifySpotx = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    previousPath=$PATH
    export PATH="${toolPath}:/usr/bin:/bin:/usr/sbin:/sbin"

    run ${pkgs.bash}/bin/bash \
      ${./activate.sh} \
      ${inputs.spotx-bash}/spotx.sh \
      /Applications/Spotify.app \
      "$HOME/Library/Application Support/SpotX-Nix" \
      --blockupdates \
      --hide

    export PATH=$previousPath
  '';
}
