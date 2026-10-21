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

  mergeFilesOrdered =
    dirs:
    let
      filesInDir =
        dir:
        let
          entries = builtins.readDir dir;
          regulars = lib.filterAttrs (_: t: t == "regular") entries;
          names = builtins.sort (a: b: a < b) (builtins.attrNames regulars);
        in
        map (n: "${toString dir}/${n}") names;
      allFiles = builtins.concatLists (map filesInDir dirs);
      contents = map builtins.readFile allFiles;
    in
    builtins.concatStringsSep "\n" contents;

  # Whether the host's nix-darwin config installs a Homebrew cask, for home modules that only
  # make sense next to their app. Always false on NixOS, which has no `homebrew` option.
  hasCask = osConfig: name: lib.any (c: c.name == name) (osConfig.homebrew.casks or [ ]);
in
{
  inherit scanPaths;

  inherit hasCask;

  inherit mergeFilesOrdered;

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
          hostname
          inputs
          username
          unstablePkgs
          ;
      };

      modules = [
        ../hosts/common/common-packages.nix
        ../hosts/common/darwin-common.nix
        ../hosts/common/darwin-github-runners.nix
        customConf
        inputs.home-manager.darwinModules.home-manager
        {
          networking.hostName = hostname;
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;
          home-manager.extraSpecialArgs = { inherit inputs libx myvars; };

          home-manager.sharedModules = [
            inputs.catppuccin.homeModules.catppuccin
            inputs.sops-nix.homeManagerModules.sops
          ];

          home-manager.users.${username} = {
            imports = [
              ./../home/default.nix
              ./../home/darwin-common.nix
            ];
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
              # Referenced as `jundot/omlx/omlx`; the key carries the `homebrew-` prefix (see below).
              "jundot/homebrew-omlx" = omlx-tap;
              # Referenced as `incoai/tap/splash`.
              "incoai/homebrew-tap" = splash-tap;
              # Local tap carrying the self-authored palmier-pro (auto-updating) and darktable casks
              # (listed in homebrew.casks in hosts/darwin/mbp/default.nix).
              # builtins.path copies the dir to its OWN top-level store path so it satisfies
              # nix-homebrew's `package`-typed taps option (a bare subpath would not).
              # NOTE: nix-homebrew uses the KEY verbatim as the Library/Taps/<...> dir name, so
              # it MUST include the `homebrew-` prefix Homebrew requires; the cask is still
              # referenced by the short tap name `fagenorn/palmier/palmier-pro`.
              "fagenorn/homebrew-palmier" = builtins.path {
                path = ../homebrew/palmier-tap;
                name = "homebrew-palmier";
              };
            };
            # Homebrew 6.0 defaults HOMEBREW_REQUIRE_TAP_TRUST on, and nix-homebrew
            # forces HOMEBREW_NO_INSTALL_FROM_API=1 (casks load from on-disk tap Ruby),
            # so third-party taps must be explicitly trusted or `brew bundle` refuses
            # to load them during activation. `trust` runs `brew trust` (writing
            # ~/.homebrew/trust.json) before the bundle. See https://docs.brew.sh/Tap-Trust.
            trust.formulae = [
              "jundot/omlx/omlx"
              "incoai/tap/splash"
            ];
            trust.casks = [
              "nikitabobko/tap/aerospace"
              "fagenorn/palmier/palmier-pro"
              "fagenorn/palmier/darktable"
            ];
          };
        }
        # Homebrew 7's `brew bundle cleanup --force` (run on every switch) resets the trust store
        # to what the Brewfile declares, which wiped the entries above after each activation and,
        # with them, the dependencies of untrusted tap formulae. Declare the same trust in the
        # Brewfile too, as `tap "<user>/<repo>", trusted: { formulae: [...], casks: [...] }`.
        (
          { config, lib, ... }:
          let
            trust = config.nix-homebrew.trust;
            item =
              kind: full:
              let
                p = lib.splitString "/" full;
              in
              {
                inherit kind;
                tap = "${builtins.elemAt p 0}/${builtins.elemAt p 1}";
                name = builtins.elemAt p 2;
              };
            byTap = lib.groupBy (i: i.tap) (
              map (item "formulae") trust.formulae ++ map (item "casks") trust.casks
            );
            names = kind: is: map (i: i.name) (builtins.filter (i: i.kind == kind) is);
            line =
              tap: is:
              let
                parts =
                  lib.optional (names "formulae" is != [ ]) "formulae: ${builtins.toJSON (names "formulae" is)}"
                  ++ lib.optional (names "casks" is != [ ]) "casks: ${builtins.toJSON (names "casks" is)}";
              in
              ''tap "${tap}", trusted: { ${lib.concatStringsSep ", " parts} }'';
          in
          {
            homebrew.extraConfig = lib.concatStringsSep "\n" (lib.mapAttrsToList line byTap);
          }
        )

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
      # pkgs = inputs.nixpkgs.legacyPackages.${system};
      pkgs = import inputs.nixpkgs {
        inherit system;
        config.allowUnfree = true;
        config.cudaSupport = true;
      };
      unstablePkgs = import inputs.nixpkgs-unstable {
        inherit system;
        config.allowUnfree = true;
        config.cudaSupport = true;
      };
    in
    # Optional: Path to host-specific NixOS config
    # customConfPath = ./../hosts/nixos/${hostname};
    # customConf = if builtins.pathExists customConfPath then (customConfPath + "/default.nix") else {};
    inputs.nixpkgs.lib.nixosSystem {
      specialArgs = {
        inherit
          system
          inputs
          outputs # Pass outputs if needed by modules
          username
          hostname
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
          home-manager.extraSpecialArgs = {
            inherit
              inputs
              libx
              myvars
              pkgs
              ;
          }; # Pass pkgs for conditional logic

          # Shared modules for all users managed by HM on this system
          home-manager.sharedModules = [
            inputs.catppuccin.homeModules.catppuccin
            inputs.sops-nix.homeManagerModules.sops
          ];

          # Specific user's HM configuration
          home-manager.users.${username} = {
            imports = [
              ./../home/default.nix
              ./../home/linux-common.nix
            ];
          };
        }

        # === SOPS Setup (System-wide if needed, often handled by HM) ===
        # inputs.sops-nix.nixosModules.sops # If you need system-level secrets

        # === System State Version ===
        { system.stateVersion = stateVersion; } # Use the global stateVersion
      ];
    };
}
