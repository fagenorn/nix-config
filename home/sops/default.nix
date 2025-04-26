{
  sops = {
    age = {
      keyFile = "/var/lib/private/sops/age/keys.txt";
      generateKey = false;
    };
      defaultSopsFile = ../../secrets/secrets.yaml;
      secrets = {
        "ssh/my".path = "~/.ssh/id_ed25519";
        "ssh/my.pub".path = "~/.ssh/id_ed25519.pub";
      }
  }
}