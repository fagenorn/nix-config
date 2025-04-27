{
  lib,
  myvars,
  config,
  ...
}:
{
  sops = {
    age.sshKeyPaths = [ "${config.home.homeDirectory}/.ssh/id_ed25519" ];
    age.keyFile = "${config.home.homeDirectory}/.config/sops/age/keys.txt";
    defaultSopsFile = myvars.sops.defaultSopsFile;

    secrets = {
      "my_ssh_private_key" = {
        path = "${config.home.homeDirectory}/.ssh/id_ed25519";
      };
      "my_ssh_public_key" = {
        path = "${config.home.homeDirectory}/.ssh/id_ed25519.pub";
      };
      "github_token" = { };
    };
  };

  programs.zsh.initExtra = ''
    export GITHUB_TOKEN="$(cat ${config.sops.secrets.github_token.path})"
  '';
}
