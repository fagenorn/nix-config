{
  lib,
  pkgs,
  inputs,
  myvars,
  config,
  ...
}:
{
  sops = {
    # sops-nix tracks its default branch (no release channel) and its go.mod
    # now requires Go >= 1.26, while nixpkgs 25.11's default `buildGoModule` is
    # still Go 1.25. Build sops-install-secrets with the 1.26 toolchain that
    # 25.11 also ships, so `just update` keeps working without pinning the input.
    package =
      (pkgs.callPackage inputs.sops-nix { }).sops-install-secrets.override {
        buildGoModule = pkgs.buildGo126Module;
        go = pkgs.go_1_26;
      };

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
      "hf_token" = { };
    };
  };

  programs.zsh.initContent = ''
    export GITHUB_TOKEN="$(cat ${config.sops.secrets.github_token.path})"
    export HF_TOKEN="$(cat ${config.sops.secrets.hf_token.path})"
  '';
}
