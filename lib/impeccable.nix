{
  inputs,
  lib,
  pkgs,
}:
let
  # One engine record per pinned skill tag (#238 D1, D2). A bump edits the
  # `impeccable` input's tag, this version and both hashes in one commit. The
  # hashes are the release's `.sha256` sidecars converted to SRI.
  engine = {
    version = "0.1.11";
    hashes = {
      aarch64-darwin = "sha256-dCeRjW51UHQBobe2ke7+WKfAGi/GO3EgFv/FoKwcBeY=";
      x86_64-linux = "sha256-AiFgfh9TWvk36iZ8NHsfkCM7hdwlY8vS7u/fQuDlxZQ=";
    };
  };
  # Nix system -> the launcher's `<os>-<arch>` slot, which is also the asset suffix.
  slots = {
    aarch64-darwin = "darwin-arm64";
    x86_64-linux = "linux-x64";
  };

  system = pkgs.stdenv.hostPlatform.system;
  slot =
    slots.${system} or (throw "impeccable: no pinned engine for system ${system} (supported: ${lib.concatStringsSep ", " (builtins.attrNames slots)})");

  upstreamTree = "${inputs.impeccable}/.claude/skills/impeccable";
  treeVersion = lib.trim (builtins.readFile "${upstreamTree}/scripts/VERSION");

  # Flat fetch: `executable = true` would hash the NAR, not the sidecar's file hash.
  engineBinary = pkgs.fetchurl {
    url = "https://github.com/pbakaus/impeccable/releases/download/engine-v${engine.version}/impeccable-${slot}";
    hash = engine.hashes.${system};
  };

  # Upstream's tree unchanged, plus the engine in the launcher's sibling slot,
  # which it tries before any cache or download path (#238 D3).
  skill =
    assert lib.assertMsg (treeVersion == engine.version)
      "impeccable: engine record ${engine.version} does not match the pinned skill's scripts/VERSION ${treeVersion}";
    pkgs.runCommand "impeccable-skill-engine-${engine.version}" { } ''
      mkdir -p "$out"
      cp -R ${upstreamTree}/. "$out/"
      chmod -R u+w "$out"
      install -Dm755 ${engineBinary} "$out/scripts/bin/${slot}/impeccable"
    '';

  # Exec by store path: the launcher resolves its skill dir from `dirname "$0"` (#238 D4).
  launcher = pkgs.writeShellScript "impeccable" ''
    exec ${skill}/scripts/impeccable "$@"
  '';
in
{
  inherit skill launcher;
  engineVersion = engine.version;
}
