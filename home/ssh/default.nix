{ config, ... }:
{
  # sops.secrets."ssh/m1pro-darwin".path =
  #   "${config.home.homeDirectory}/.ssh/id_ed25519";
  # home.file.".ssh/id_ed25519.pub".text = keys.ssh.m1pro-darwin.public;

  home.file.".ssh/id_ed25519" = {
    # Reference the secret by the logical name defined in home.nix sops config
    source = config.sops.secrets.my_ssh_private_key.path;
    # Set permissions securely
    mode = "0600";
  };

  home.file.".ssh/id_ed25519.pub" = {
    source = config.sops.secrets.my_ssh_public_key.path;
    mode = "0644";
  };

  programs.ssh = {
    enable = true;
    extraConfig = ''
      StrictHostKeyChecking no
    '';
    matchBlocks = {
      # ~/.ssh/config
      "github.com" = {
        hostname = "ssh.github.com";
        port = 443;
      };
      "*" = {
        user = "root";
      };
      # wd

      # lancs
      # "e elrond" = {
      #   hostname = "100.117.223.78";
      #   user = "alexktz";
      # };
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
