{ myvars, config, ... }:
{
  sops = {
    age.keyFile = myvars.sops.age.keyFile;
    defaultSopsFile = myvars.sops.defaultSopsFile;

    secrets = {
      my_ssh_private_key.path = "${config.home.homeDirectory}/.ssh/id_ed25519";
      my_ssh_public_key.path = "${config.home.homeDirectory}/.ssh/id_ed25519.pub";
    };

    # templates = {
    #   "my_ssh_private_key" = {
    #     content = config.sops.placeholder.my_ssh_private_key;
    #   };
    #   "my_ssh_public_key" = {
    #     content = config.sops.placeholder.my_ssh_public_key;
    #   };
    # };
  };

  # home.file.".ssh/id_ed25519" = {
  #   # enable = true;
  #   source = config.sops.secrets.my_ssh_private_key.path;
  # };

  # home.file.".ssh/id_ed25519.pub" = {
  #   enable = true;
  #   source = config.sops.templates.my_ssh_public_key.path;
  # };
}
