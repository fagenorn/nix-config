{
  inputs,
  outputs,
  stateVersion,
  myvars,
  ...
}:
let
  lib = inputs.nixpkgs.lib;
  attrs = import ./attrs.nix { inherit lib; };
  scanPaths =
    path:
    builtins.map (f: path + "/${f}") (
      builtins.attrNames (
        lib.attrsets.filterAttrs (
          name: type:
          (type == "directory") # include directories
          || (
            (name != "default.nix") # ignore default.nix
            && (lib.strings.hasSuffix ".nix" name) # include .nix files
          )
        ) (builtins.readDir path)
      )
    );
in
{
  inherit scanPaths;

  mkDarwin =
    {
      hostname,
      username,
      system,
      libx,
      myvars,
    }:
    let
      unstablePkgs = inputs.nixpkgs-unstable.legacyPackages.${system};
      customConfPath = ./../hosts/darwin/${hostname};
      customConf =
        if builtins.pathExists (customConfPath) then
          (customConfPath + "/default.nix")
        else
          ./../hosts/common/darwin-common-dock.nix;
    in
    inputs.nix-darwin.lib.darwinSystem {
      specialArgs = {
        inherit
          system
          inputs
          username
          unstablePkgs
          ;
      };

      modules = [
        ../hosts/common/common-packages.nix
        ../hosts/common/darwin-common.nix
        customConf
        inputs.home-manager.darwinModules.home-manager
        {
          networking.hostName = hostname;
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;
          home-manager.extraSpecialArgs = { inherit inputs libx myvars; };

          home-manager.sharedModules = [
            inputs.sops-nix.homeManagerModules.sops
          ];

          home-manager.users.${username} = {
            imports = [ ./../home/default.nix ];
          };
        }
        inputs.nix-homebrew.darwinModules.nix-homebrew
        {
          nix-homebrew = {
            enable = true;
            enableRosetta = true;
            autoMigrate = true;
            mutableTaps = true;
            user = "${username}";
            taps = with inputs; {
              "homebrew/homebrew-core" = homebrew-core;
              "homebrew/homebrew-cask" = homebrew-cask;
              "homebrew/homebrew-bundle" = homebrew-bundle;
              "nikitabobko/tap" = nikitabobko-tap;
            };
          };
        }

      ];
      # ] ++ lib.optionals (builtins.pathExists ./../hosts/darwin/${hostname}/default.nix) [
      #     (import ./../hosts/darwin/${hostname}/default.nix)
      #   ];
    };

    mkNixos =
    {
     hostname,
     username,
     system,
     libx,
     myvars,
    }:
    let
      pkgs = inputs.nixpkgs.legacyPackages.${system};
      unstablePkgs = inputs.nixpkgs-unstable.legacyPackages.${system};
      # Optional: Path to host-specific NixOS config
      # customConfPath = ./../hosts/nixos/${hostname};
      # customConf = if builtins.pathExists customConfPath then (customConfPath + "/default.nix") else {};
    in
    inputs.nixpkgs.lib.nixosSystem {
      specialArgs = {
        inherit
          system
          inputs
          outputs # Pass outputs if needed by modules
          username
          unstablePkgs
          myvars # Pass myvars
          libx # Pass libx if needed by modules
          ;
      };
      modules = [
        # === Core NixOS/WSL Setup ===
        inputs.nixos-wsl.nixosModules.wsl # Use the nixos-wsl module
        ./../hosts/common/linux-common.nix # Your common Linux settings
        # customConf # Include host-specific config if it exists

        # === Common Packages ===
        ./../hosts/common/common-packages.nix

        # === Home Manager Setup ===
        inputs.home-manager.nixosModules.home-manager
        {
          # Basic NixOS config for the user
        #   users.users.${username}.isNormalUser = true;
        #   users.users.${username}.home = "/home/${username}"; # Standard Linux home
        #   users.users.${username}.extraGroups = [ "wheel" "networkmanager" "docker" ]; # Adjust as needed, 'wheel' for sudo

          # Configure Home Manager
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;
          home-manager.extraSpecialArgs = { inherit inputs libx myvars pkgs; }; # Pass pkgs for conditional logic

          # Shared modules for all users managed by HM on this system
          home-manager.sharedModules = [
            inputs.sops-nix.homeManagerModules.sops
            # Add other shared HM modules if any
          ];

          # Specific user's HM configuration
          home-manager.users.${username} = {
            imports = [ ./../home/default.nix ]; # Import the main home config
            # Add user-specific overrides for this host if needed
          };
        }

        # === SOPS Setup (System-wide if needed, often handled by HM) ===
        # inputs.sops-nix.nixosModules.sops # If you need system-level secrets

        # === System State Version ===
        { system.stateVersion = stateVersion; } # Use the global stateVersion
      ];
    };
}
