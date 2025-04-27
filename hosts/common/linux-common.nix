{ config, pkgs, lib, inputs, username, ... }:

{
  # === Basic System Settings ===
  time.timeZone = "Europe/Brussels"; # Set your timezone
  i18n.defaultLocale = "en_US.UTF-8";


  # === Nix Settings ===
  nix = {
    package = pkgs.nixFlakes;
    extraOptions = ''
      experimental-features = nix-command flakes
      warn-dirty = false
    '';

    gc = {
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 7d";
    };
    settings.auto-optimise-store = true;
  };

    # === Networking (Basic for WSL) ===
  networking.hostName = config.networking.hostName; # Set in mkNixos call
  networking.networkmanager.enable = true; # Usually good for desktop/WSL

    # === WSL Specific Configuration (using nixos-wsl) ===
  wsl = {
    enable = true;
    defaultUser = username; # Set default user for WSL session
    # Enable integration with Windows (mounting drives, interop)
    interop.enable = true;
    # Optional: Enable systemd support (Requires setup in .wslconfig on Windows)
    # systemd.enable = true;
  };

    # === Environment ===
    # environment.pathsToLink = [ "/share/zsh" ]; # Example if needed

  # === Programs ===
  programs.zsh.enable = true; # Enable Zsh globally
  # Note: Zsh prompt/config often better handled by Home Manager

  # === Bootloader (Not needed for WSL) ===
#   boot.loader.systemd-boot.enable = false;
#   boot.loader.grub.enable = false;

  # === Security ===
#   security.rtkit.enable = true; # RealtimeKit - often useful for audio/pipewire
#   services.pipewire = {
#     enable = true;
#     alsa.enable = true;
#     alsa.support32Bit = true;
#     pulse.enable = true;
    # If using nixos-wsl, wireplumber might conflict, check documentation
    # wireplumber.enable = true; # Use instead of media-session if preferred
    # jack.enable = true; # If JACK audio support is needed
#   };
  # Allow users in 'wheel' group to use sudo
#   security.sudo.wheelNeedsPassword = false; # Or true if you want password prompts

  # === Fonts (if managing system-wide, otherwise use Home Manager) ===
  # fonts.packages = with pkgs; [ fira-code fira-code-nerdfont ];
}