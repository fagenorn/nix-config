{
  inputs,
  pkgs,
}:
let
  patchRevision = 1;
  shortRevision = revision: builtins.substring 0 8 revision;

  superpowersRevision = inputs.superpowers.rev or "44c9b2d6e889982ac18c27d05a19fefe335194e1";
  superpowersUpstreamVersion =
    (builtins.fromJSON (builtins.readFile (inputs.superpowers + "/.claude-plugin/plugin.json"))).version;
  superpowersVersion =
    "${superpowersUpstreamVersion}-nix.${shortRevision superpowersRevision}.p${toString patchRevision}";

  codexRevision = inputs.codex-plugin-cc.rev or "db52e28f4d9ded852ab3942cea316258ae4ef346";
  codexUpstreamVersion =
    (builtins.fromJSON (builtins.readFile (inputs.codex-plugin-cc + "/plugins/codex/.claude-plugin/plugin.json"))).version;
  codexVersion = "${codexUpstreamVersion}-nix.${shortRevision codexRevision}.p${toString patchRevision}";

  buildMarketplace =
    {
      name,
      source,
      patch,
      version,
      marketplaceName,
      pluginManifest,
    }:
    pkgs.runCommand name
      {
        nativeBuildInputs = [
          pkgs.gnupatch
          pkgs.jq
        ];
      }
      ''
        mkdir -p "$out"
        cp -R ${source}/. "$out/"
        chmod -R u+w "$out"
        cd "$out"
        patch -p1 < ${patch}

        tmp=".claude-plugin/marketplace.json.tmp"
        jq --arg marketplace "${marketplaceName}" --arg version "${version}" \
          '.name = $marketplace | .metadata.version = $version | .plugins[0].version = $version' \
          .claude-plugin/marketplace.json > "$tmp"
        mv "$tmp" .claude-plugin/marketplace.json

        tmp="${pluginManifest}.tmp"
        jq --arg version "${version}" '.version = $version' ${pluginManifest} > "$tmp"
        mv "$tmp" ${pluginManifest}
      '';
in
{
  inherit patchRevision;

  superpowers = buildMarketplace {
    name = "superpowers-plugin-${superpowersVersion}";
    source = inputs.superpowers;
    patch = ../patches/agent-plugins/superpowers-control-flow.patch;
    version = superpowersVersion;
    marketplaceName = "nix-superpowers";
    pluginManifest = ".claude-plugin/plugin.json";
  };
  superpowersMetadata = {
    revision = superpowersRevision;
    upstreamVersion = superpowersUpstreamVersion;
    version = superpowersVersion;
  };

  codex = buildMarketplace {
    name = "codex-plugin-cc-${codexVersion}";
    source = inputs.codex-plugin-cc;
    patch = ../patches/agent-plugins/codex-plugin-cc.patch;
    version = codexVersion;
    marketplaceName = "nix-codex";
    pluginManifest = "plugins/codex/.claude-plugin/plugin.json";
  };
  codexMetadata = {
    revision = codexRevision;
    upstreamVersion = codexUpstreamVersion;
    version = codexVersion;
  };
}
