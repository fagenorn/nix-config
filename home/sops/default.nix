{ myvars, ... }:
{
  sops = {
    enable = true;
    # Use the paths defined in myvars
    age.keyFile = myvars.sops.age.keyFile;
    defaultSopsFile = myvars.sops.defaultSopsFile;

    # Define the secrets you want to manage within home-manager
    secrets = {
      # "my_ssh_private_key" is the *logical name* you'll use in Nix.
      "my_ssh_private_key" = {
        # By default, sops-nix looks for a key named "my_ssh_private_key"
        # inside your `defaultSopsFile` (secrets.yaml).
        # If the key in secrets.yaml is different (e.g., "ssh_id_ed25519_anis"), specify it:
        # key = "ssh_id_ed25519_anis";

        # No 'path' needed here; sops-nix manages the file placement.
        # You can set ownership and permissions if needed, but defaults are usually fine.
        # mode = "0600";
        # owner = config.home.username;
      };

      # Define the public key similarly if it's also encrypted in secrets.yaml
      "my_ssh_public_key" = {
        # key = "ssh_id_ed25519_anis_pub"; # Example if key name differs in yaml
        # mode = "0644";
        # owner = config.home.username;
      };

      # Example of another secret
      # "api_token" = {
      #   key = "some_service_api_token"; # Key name in secrets.yaml
      # };
    };
  };
}
