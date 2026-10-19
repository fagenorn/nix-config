{
  lib,
  pkgs,
  ...
}:
let
  # Teammates who reach this Studio over the owner's tailnet. Each entry becomes a standard
  # (non-admin) macOS account with no password: SSH with the listed keys is the only way in.
  # Pick a uid above 500 that is unused (`dscl . -list /Users UniqueID`), e.g.
  #   { name = "jdoe"; uid = 600; keys = [ "ssh-ed25519 AAAA... jdoe@laptop" ]; }
  teammates = [ ];
in
{
  # mkDarwin sets HostName and LocalHostName; Tailscale names the node after the Computer Name.
  networking.computerName = "eleven-m5";

  system.defaults.dock.persistent-apps = [
    "/Applications/Helium.app"
    "/Applications/Google Chrome.app"
    "/Applications/Ghostty.app"
  ];

  # Remote Login, key-only. nix-darwin writes this into /etc/ssh/sshd_config.d, which macOS
  # includes before its own defaults, so the first value wins.
  services.openssh = {
    enable = true;
    extraConfig = ''
      PasswordAuthentication no
      KbdInteractiveAuthentication no
    '';
  };

  users.knownUsers = map (t: t.name) teammates;
  users.users = lib.listToAttrs (
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
  );

  # When Remote Login is limited to "Only these users", macOS checks the com.apple.access_ssh
  # group, so a declared teammate would still be refused. Add each one; a no-op when the
  # group does not exist (Remote Login open to all users).
  system.activationScripts.postActivation.text = lib.concatMapStrings (t: ''
    if /usr/bin/dscl . -read /Groups/com.apple.access_ssh >/dev/null 2>&1; then
      /usr/sbin/dseditgroup -o edit -a ${t.name} -t user com.apple.access_ssh
    fi
  '') teammates;
}
