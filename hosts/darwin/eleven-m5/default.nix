{
  lib,
  pkgs,
  username,
  ...
}:
let
  # Teammates who reach this Studio over the owner's tailnet. Each entry becomes a standard
  # (non-admin) macOS account with no password: SSH with the listed keys is the only way in.
  # Pick a uid above 500 that is unused (`dscl . -list /Users UniqueID`), e.g.
  #   { name = "jdoe"; uid = 600; keys = [ "ssh-ed25519 AAAA... jdoe@laptop" ]; }
  teammates = [
    {
      name = "selo";
      uid = 503;
      keys = [
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP5yoVHIP1/z2Gx7BsvVBq5mOlXHWnz5DaEYfhtICm9i j@elevenyellow.com"
      ];
    }
  ];
  # To revoke someone, move their name from `teammates` to here: nix-darwin then deletes the
  # account and its home, and they are taken out of com.apple.access_ssh.
  formerTeammates = [ ];

  # The owner's key (the sops-managed ~/.ssh/id_ed25519). sshd reads only declared keys.
  ownerKeys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICvwSkG1C56YfXa6z8bnb0z9tkts56ZNmkVjibSsftvP"
  ];
in
{
  imports = [ ./omlx.nix ];

  # mkDarwin sets HostName and LocalHostName; Tailscale names the node after the Computer Name.
  networking.computerName = "eleven-m5";

  system.defaults.dock.persistent-apps = [
    "/Applications/Helium.app"
    "/Applications/Ghostty.app"
  ];

  # Remote Login, key-only, and only with keys declared here: nix-darwin serves them through
  # AuthorizedKeysCommand, and `AuthorizedKeysFile none` ignores ~/.ssh/authorized_keys, so a
  # key someone adds to their own home cannot outlive their entry. nix-darwin writes this into
  # /etc/ssh/sshd_config.d, which macOS includes before its own defaults; the first value wins.
  services.openssh = {
    enable = true;
    extraConfig = ''
      PasswordAuthentication no
      KbdInteractiveAuthentication no
      AuthorizedKeysFile none
    '';
  };

  users.knownUsers = map (t: t.name) teammates ++ formerTeammates;
  users.users =
    lib.listToAttrs (
      map (t: {
        inherit (t) name;
        value = {
          inherit (t) uid;
          home = "/Users/${t.name}";
          createHome = true;
          shell = pkgs.zsh;
          openssh.authorizedKeys.keys = t.keys;
        };
      }) teammates
    )
    // {
      ${username}.openssh.authorizedKeys.keys = ownerKeys;
    };

  # When Remote Login is limited to "Only these users", macOS checks the com.apple.access_ssh
  # group, so a declared teammate would still be refused. Add each one and drop former ones;
  # a no-op when the group does not exist (Remote Login open to all users).
  system.activationScripts.postActivation.text = ''
    if /usr/bin/dscl . -read /Groups/com.apple.access_ssh >/dev/null 2>&1; then
      : # both lists may be empty
      ${lib.concatMapStrings (t: ''
        /usr/sbin/dseditgroup -o edit -a ${t.name} -t user com.apple.access_ssh
      '') teammates}
      ${lib.concatMapStrings (name: ''
        /usr/sbin/dseditgroup -o edit -d ${name} -t user com.apple.access_ssh || true
      '') formerTeammates}
    fi
  '';
}
