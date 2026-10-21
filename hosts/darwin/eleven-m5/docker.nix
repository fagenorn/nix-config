{
  lib,
  unstablePkgs,
  username,
  ...
}:
let
  home = "/Users/${username}";

  # Colima (a Docker engine in a Lima VM) rather than the shared OrbStack cask: it runs headless
  # from boot, and OrbStack needs a paid licence for commercial use. From unstable, because
  # 25.11's colima depends on lima 1.2.2, which nixpkgs marks insecure (EOL) and refuses.
  colima = unstablePkgs.colima;
  socket = "${home}/.colima/default/docker.sock";

  # The VM shares the ~16 GB oMLX leaves macOS (see omlx.nix's wired limit), hence 8 GiB. It runs
  # on Apple's Virtualization framework with Rosetta for amd64 images. Colima saves these flags to
  # ~/.colima/default/colima.yaml on every start; CPUs and memory apply on the next start, the
  # disk can grow but never shrink, and the VM type needs `colima delete`. `--activate=false`
  # leaves ~/.docker/config.json alone (Colima still registers a `colima` context).
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
  # Started at boot as the owner, like oMLX, and kept alive. Only the owner can use the engine:
  # Colima creates the socket 0600, and the tools are on the owner's PATH alone. Docker access is
  # owner-level access to the host, since Colima mounts $HOME writable into the VM.
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

  # Tools that ignore DOCKER_HOST (SDKs, Testcontainers, apps launchd starts) look for the
  # default socket. /var/run is emptied at boot, so a boot daemon links it; the link grants no
  # access the 0600 socket does not.
  launchd.daemons.docker-socket.serviceConfig = {
    ProgramArguments = [
      "/bin/ln"
      "-sfn"
      socket
      "/var/run/docker.sock"
    ];
    RunAtLoad = true;
  };

  home-manager.users.${username} = {
    home.packages = [
      colima
      unstablePkgs.docker-client
    ];
    home.sessionVariables.DOCKER_HOST = "unix://${socket}";
    # docker-client ships no plugins; the CLI finds them in ~/.docker/cli-plugins.
    home.file.".docker/cli-plugins/docker-compose".source =
      "${unstablePkgs.docker-compose}/libexec/docker/cli-plugins/docker-compose";
    home.file.".docker/cli-plugins/docker-buildx".source =
      "${unstablePkgs.docker-buildx}/libexec/docker/cli-plugins/docker-buildx";
  };
}
