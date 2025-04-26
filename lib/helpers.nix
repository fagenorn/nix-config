{
  inputs,
  outputs,
  stateVersion,
  ...
}:
let
  # Use the standard lib from nixpkgs input for the helper function
  lib = inputs.nixpkgs.lib;

  attrs = import ./attrs.nix { inherit lib; };

  # Define scanPaths at this level, making it potentially exportable
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

  myvars = import ../vars;

in
{
  inherit scanPaths;
  mkDarwin =
    {
      hostname,
      username,
      system,
      libx,
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
}
