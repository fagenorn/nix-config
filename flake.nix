{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
    nixpkgs-unstable.url = "github:nixos/nixpkgs/nixos-unstable";

    nixpkgs-darwin.url = "github:NixOS/nixpkgs/nixpkgs-24.11-darwin";
    nix-darwin.url = "github:lnl7/nix-darwin/nix-darwin-24.11";
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

    home-manager.url = "github:nix-community/home-manager/release-24.11";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";

    catppuccin.url = "github:catppuccin/nix";

    sops-nix.url = "github:Mic92/sops-nix";
    sops-nix.inputs.nixpkgs.follows = "nixpkgs";

    nixos-wsl.url = "github:nix-community/nixos-wsl";
    nixos-wsl.inputs.flake-compat.follows = "";
    nixos-wsl.inputs.nixpkgs.follows = "nixpkgs";

    ghostty.url = "github:ghostty-org/ghostty";
  };

  outputs =
    { ... }@inputs:
    with inputs;
    let
      inherit (self) outputs;

      myvars = import ./vars;
      stateVersion = "24.05";
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
