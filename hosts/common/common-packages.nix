{
  inputs,
  pkgs,
  unstablePkgs,
  ...
}:
let
  inherit (inputs) nixpkgs nixpkgs-unstable;
in
{
  nixpkgs.config.allowUnfree = true;
  environment.systemPackages =
    with pkgs;
    [
      # === Core System & File Utilities ===
      coreutils # Standard GNU utilities (ls, cp, mv, rm, etc.)
      tree # Display directory contents as a tree
      unzip # Utility for extracting ZIP archives

      # === Enhanced CLI Utilities & Replacements ===
      # File Searching & Navigation
      fd # Fast, user-friendly alternative to `find`
      ripgrep # Very fast recursive file search (grep alternative) (`rg`)
      zoxide # Smarter `cd` - remembers frequent directories

      # File Comparison & Manipulation
      difftastic # Structural diff tool (syntax-aware)
      jq # Command-line JSON processor

      # Disk Usage Analyzers
      dust # Modern `du` replacement (`dust`)
      # dua             # Alternative interactive disk usage analyzer
      duf # Modern `df` (disk free) replacement

      # Process/Task Automation & Monitoring
      entr # Run command when files change (for auto-reloads/tests)
      watch # Standard utility to run a command repeatedly

      # === System Monitoring & Information ===
      btop # Comprehensive terminal resource monitor
      fastfetch # Fast, customizable system information tool
      smartmontools # Disk health monitoring via S.M.A.R.T. (`smartctl`)

      # === Development, DevOps & Virtualization ===
      # Version Control & Collaboration
      gh # GitHub official CLI

      # Build & Automation
      hugo # Static site generator
      just # Handy command runner (simpler `make`)

      # Containers & Cloud Native
      # kubectl           # Kubernetes CLI tool
      # skopeo            # Tool for working with container images & registries

      # Infrastructure & Virtualization
      # terraform         # Infrastructure as Code tool
      # qemu              # Machine emulator and virtualizer

      # === Networking Tools ===
      iperf3 # Network bandwidth testing tool
      mosh # Mobile Shell (robust replacement for SSH sessions)
      nmap # Network scanner and security auditor
      wget # Non-interactive web downloader (HTTP, HTTPS, FTP)
      wireguard-tools # Tools to manage WireGuard VPN connections (`wg`, `wg-quick`)

      # === Multimedia & Graphics ===
      ffmpeg # Command-line multimedia framework (convert, stream, record)
      figurine # Utility for creating FIGlet-style text banners/ASCII art
      # television        # Application for watching TV streams (e.g., IPTV) - Verify exact function
      immich-go

      # === Fonts ===
      # Install specific fonts you use. NerdFonts provides patched fonts with icons.
      fira-code # Monospaced font with programming ligatures
      nerd-fonts.fira-code # Fira Code patched with Nerd Font icons
      fira-mono # Standard Fira monospaced font

      nixfmt-rfc-style
      nil
      sops
      devenv

      # === Packages from nixpkgs-unstable ===
      # Ensure 'nixpkgs-unstable' is defined as an input (e.g., in your flake.nix)
      # Using legacyPackages as per your original example
      # (nixpkgs-unstable.legacyPackages.${pkgs.system}.beszel)   # CLI for Beszel API (Talos ecosystem)
      # (nixpkgs-unstable.legacyPackages.${pkgs.system}.talosctl)  # CLI for Talos Linux cluster management
    ]
    ++ [
      # Add the working devenv from nixpkgs-unstable
      # unstablePkgs.devenv
      unstablePkgs.spicetify-cli
    ];
}
