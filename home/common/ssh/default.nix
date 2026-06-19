{ lib, config, ... }:
{
  programs.ssh = {
    enable = true;
    # home-manager 25.11 moved the per-host settings into matchBlocks and
    # deprecated the implicit "*" defaults. Opt out and declare the one we
    # actually want (addKeysToAgent) under matchBlocks."*"; the rest of the old
    # defaults just restated OpenSSH's own defaults, so dropping them is a no-op.
    enableDefaultConfig = false;
    extraConfig = ''
      StrictHostKeyChecking no
    '';
    matchBlocks = {
      "*" = {
        user = "root";
        identityFile = "~/.ssh/id_ed25519";
        addKeysToAgent = "yes";
      };

      "github.com" = lib.hm.dag.entryBefore [ "*" ] {
        hostname = "ssh.github.com";
        port = 443;
      };

      "anis-desktop" = lib.hm.dag.entryBefore [ "*" ] {
        hostname = "anis-desktop.mink-fort.ts.net";
        user = "anis";
        port = 48521;
        identityFile = "~/.ssh/id_ed25519";
      };

      "vibes" = lib.hm.dag.entryBefore [ "*" ] {
        hostname = "209.195.17.17";
        user = "vibes";
        identityFile = "~/.ssh/svs_ed25519";
      };

      # # jb
      # "core" = {
      #   hostname = "demo.selfhosted.show";
      #   user = "ironicbadger";
      #   port = 53142;
      # };
      # "status" = {
      #   hostname = "hc.ktz.cloud";
      #   user = "ironicbadger";
      #   port = 53142;
      # };
    };
  };
}
