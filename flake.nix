{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

    nixpkgs-darwin.url = "github:NixOS/nixpkgs/nixpkgs-25.11-darwin";
    nix-darwin.url = "github:lnl7/nix-darwin/nix-darwin-25.11";
    nix-darwin.inputs.nixpkgs.follows = "nixpkgs-darwin";

    nix-homebrew.url = "github:zhaofengli-wip/nix-homebrew";
    homebrew-core = {
      url = "github:homebrew/homebrew-core";
      flake = false;
    };
    homebrew-cask = {
      url = "github:homebrew/homebrew-cask";
      flake = false;
    };
    homebrew-bundle = {
      url = "github:homebrew/homebrew-bundle";
      flake = false;
    };

    nikitabobko-tap = {
      url = "github:nikitabobko/homebrew-tap";
      flake = false;
    };

    home-manager.url = "github:nix-community/home-manager/release-25.11";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";

    catppuccin.url = "github:catppuccin/nix/release-25.11";

    sops-nix.url = "github:Mic92/sops-nix";
    sops-nix.inputs.nixpkgs.follows = "nixpkgs";

    nixos-wsl.url = "github:nix-community/nixos-wsl";
    nixos-wsl.inputs.flake-compat.follows = "";
    nixos-wsl.inputs.nixpkgs.follows = "nixpkgs";

    ghostty.url = "github:ghostty-org/ghostty";

    # Latest Claude Code, auto-tracked hourly (within ~30 min of the npm release),
    # official native binary with the autoupdater pre-disabled for the read-only store.
    # Advances on `just update` (nix flake update) + rebuild; binary served from its
    # Cachix cache (configured in hosts/common/darwin-common.nix) so nothing compiles.
    claude-code.url = "github:sadjow/claude-code-nix";
    claude-code.inputs.nixpkgs.follows = "nixpkgs";

    # Latest stable Codex CLI, auto-tracked hourly from OpenAI's native releases.
    # Advances on `just update` + rebuild and is available for both configured hosts.
    codex-cli.url = "github:sadjow/codex-cli-nix";
    codex-cli.inputs.nixpkgs.follows = "nixpkgs";

    # Cross-agent skill sources. These remain pinned by flake.lock and are
    # exposed through each agent's native discovery mechanism.
    codex-plugin-cc = {
      url = "github:openai/codex-plugin-cc/db52e28f4d9ded852ab3942cea316258ae4ef346";
      flake = false;
    };
    ui-ux-pro-max = {
      url = "github:nextlevelbuilder/ui-ux-pro-max-skill";
      flake = false;
    };

    # macOS Spotify patch source. Homebrew still owns the Spotify app itself;
    # this non-flake input only supplies the pinned SpotX-Bash script.
    spotx-bash = {
      url = "github:SpotX-Official/SpotX-Bash";
      flake = false;
    };
  };

  outputs =
    { ... }@inputs:
    with inputs;
    let
      inherit (self) outputs;

      myvars = import ./vars;
      stateVersion = "25.05";
      libx = import ./lib {
        inherit
          inputs
          outputs
          stateVersion
          myvars
          ;
      };
    in
    {

      darwinConfigurations = {
        mbp = libx.mkDarwin {
          hostname = "mbp";
          username = myvars.username;
          system = "aarch64-darwin";
          inherit libx myvars;
        };
      };

      nixosConfigurations = {
        anis-desktop = libx.mkNixos {
          hostname = "anis-desktop";
          username = myvars.username;
          system = "x86_64-linux";
          inherit libx myvars;
        };
      };

    };

}
