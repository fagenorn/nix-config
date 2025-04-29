{ lib, config, ... }:
{
  programs.ssh = {
    enable = true;
    addKeysToAgent = "yes";
    extraConfig = ''
      StrictHostKeyChecking no
    '';
    matchBlocks = {
      "*" = {
        user = "root";
        identityFile = "~/.ssh/id_ed25519";
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
