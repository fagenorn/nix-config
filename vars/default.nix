{
  username = "anis";

  sops = {
    age = {
      keyFile = "~/.config/sops/age/keys.txt";
    };
    defaultSopsFile = ../secrets/secrets.yaml;
  };
}
