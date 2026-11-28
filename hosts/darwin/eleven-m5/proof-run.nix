{
  config,
  inputs,
  lib,
  pkgs,
  username,
  ...
}:
let
  home = "/Users/${username}";
  launcher =
    inputs.self.packages.${pkgs.stdenv.hostPlatform.system}.agent-platform.launchers.proof-run;
  log = "${home}/Library/Logs/proof-run.log";
  # The same search path as the verify-pending host job: gh and git for the forge and the fixture
  # checkout, the home profile for nix, then the system tools.
  path = lib.concatStringsSep ":" [
    (lib.makeBinPath [
      pkgs.gh
      pkgs.git
      pkgs.coreutils
    ])
    "${config.home-manager.users.${username}.home.profileDirectory}/bin"
    "/run/current-system/sw/bin"
    "/nix/var/nix/profiles/default/bin"
    "/usr/bin"
    "/bin"
    "/usr/sbin"
    "/sbin"
  ];
in
{
  # The console bumps the same fixture this daemon proves on to each revision it proves.
  home-manager.users.${username}.agentConsole.lockBump = {
    project = "fagenorn/engine-fixture";
    branch = "main";
    platformRepo = "fagenorn/nix-config";
  };

  # Proves the delivery engine on the fixture project once a day at 06:00, as the owner: it
  # delivers one fixed issue with the real model from the tip of the platform repository's main
  # branch, unless that revision is already proven. Only the calendar entry starts it, so a
  # switch never spends a real-model run; `proof-run now ...` (see README.md) starts one at once.
  # It sets `command`, which nix-darwin runs after the Nix volume is mounted.
  launchd.daemons.proof-run = {
    command = "${launcher} daily --platform-repo fagenorn/nix-config --branch main --fixture fagenorn/engine-fixture --fixture-branch main";
    serviceConfig = {
      Label = "org.nixos.proof-run";
      UserName = username;
      StartCalendarInterval = [
        {
          Hour = 6;
          Minute = 0;
        }
      ];
      EnvironmentVariables = {
        HOME = home;
        PATH = path;
      };
      StandardOutPath = log;
      StandardErrorPath = log;
    };
  };
}
