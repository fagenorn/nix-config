{
  config,
  pkgs,
  lib,
  inputs,
  system,
  hostname,
  username,
  ...
}:
let
  inherit (inputs) nixpkgs nixpkgs-unstable;
in
{
  users.users = {
    "${username}" = {
      home = "/home/anis";
      shell = pkgs.zsh;
      extraGroups = [ "docker" ];
    };
  };

  # === Basic System Settings ===
  time.timeZone = "Europe/Brussels";
  i18n.defaultLocale = "en_US.UTF-8";

  # === Nix Settings ===
  nix = {
    settings = {
      experimental-features = [
        "nix-command"
        "flakes"
      ];
      warn-dirty = false;
    };
    gc = {
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 7d";
    };

    extraOptions = ''
      trusted-users = root anis
    '';

    optimise.automatic = true;
    channel.enable = false;
  };

  nixpkgs = {
    hostPlatform = lib.mkDefault "${system}";
  };

  nix.registry = {
    n.to = {
      type = "path";
      path = inputs.nixpkgs;
    };
    u.to = {
      type = "path";
      path = inputs.nixpkgs-unstable;
    };
  };

  programs.zsh = {
    enable = true;
  };

  wsl = {
    enable = true;
    defaultUser = username;
    useWindowsDriver = true;
    wslConf.network.hostname = hostname;
  };

  services.xserver.videoDrivers = [ "nvidia" ];
  hardware.nvidia.open = true;

  hardware = {
    nvidia-container-toolkit = {
      enable = true;
      mount-nvidia-executables = false;
    };
    graphics = {
      enable = true;
      enable32Bit = true;
    };
  };

  # Native Docker inside the WSL distro (no Docker Desktop). docker_29 because
  # 25.11's default docker_28 is marked insecure (unmaintained). CDI exposes the
  # GPU that nvidia-container-toolkit describes: `--device nvidia.com/gpu=all`.
  virtualisation.docker = {
    enable = true;
    package = pkgs.docker_29;
    daemon.settings.features.cdi = true;
  };

  environment.sessionVariables = {
    LD_LIBRARY_PATH = [
      "/usr/lib/wsl/lib"
    ];
  };

  programs.nix-ld = {
    enable = true;
    package = pkgs.nix-ld;
  };
}
