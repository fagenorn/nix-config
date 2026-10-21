{
  lib,
  unstablePkgs,
  username,
  ...
}:
let
  home = "/Users/${username}";

  # Colima (a Docker engine in a Lima VM) from unstable: 25.11's colima depends on lima 1.2.2,
  # which nixpkgs marks insecure (EOL) and refuses to evaluate.
  colima = unstablePkgs.colima;

  # The VM shares the 16 GB oMLX leaves macOS (see omlx.nix's wired limit), hence 8 GiB. It runs
  # on Apple's Virtualization framework with Rosetta for amd64 images. Colima saves these flags to
  # ~/.colima/default/colima.yaml on every start, so a change here takes effect on the next start;
  # the disk can grow but never shrink. The owner's shell reaches the engine through DOCKER_HOST,
  # so Colima does not rewrite ~/.docker/config.json's context.
  start = [
    (lib.getExe colima)
    "start"
    "--foreground"
    "--vm-type=vz"
    "--vz-rosetta"
    "--cpus=8"
    "--memory=8"
    "--disk=200"
    "--activate=false"
  ];
in
{
  environment.systemPackages = [
    colima
    unstablePkgs.docker-client
  ];

  # Started at boot as the owner, like oMLX, and kept alive. Only the owner uses the engine: its
  # socket lives under ~/.colima, and Docker access is root-equivalent inside the VM.
  launchd.daemons.colima.serviceConfig = {
    ProgramArguments = start;
    UserName = username;
    EnvironmentVariables = {
      HOME = home;
      PATH = "${lib.makeBinPath [ colima ]}:/usr/bin:/bin:/usr/sbin:/sbin";
    };
    RunAtLoad = true;
    KeepAlive = true;
    StandardOutPath = "${home}/Library/Logs/colima.log";
    StandardErrorPath = "${home}/Library/Logs/colima.log";
  };

  home-manager.users.${username} = {
    home.sessionVariables.DOCKER_HOST = "unix://${home}/.colima/default/docker.sock";
    # docker-client ships no plugins; the CLI finds them in ~/.docker/cli-plugins.
    home.file.".docker/cli-plugins/docker-compose".source =
      "${unstablePkgs.docker-compose}/libexec/docker/cli-plugins/docker-compose";
    home.file.".docker/cli-plugins/docker-buildx".source =
      "${unstablePkgs.docker-buildx}/libexec/docker/cli-plugins/docker-buildx";
  };
}
