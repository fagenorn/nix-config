{ config, inputs, pkgs, lib, unstablePkgs, libx, ... }: {
  home.stateVersion = "23.11";

  # list of programs
  # https://mipmip.github.io/home-manager-option-search

  #   programs.aerospace = {
  #     enable = true;
  #   };

  #   home.file = lib.mkMerge [
  #     (lib.mkIf pkgs.stdenv.isDarwin {
  #       ".config/aerospace/aerospace.toml".text = builtins.readFile ./aerospace/aerospace.toml;
  #     })
  #   ];

  programs.gpg.enable = true;

  programs.direnv = {
    enable = true;
    nix-direnv.enable = true;
  };

  programs.eza = {
    enable = true;
    enableZshIntegration = true;
    icons = "auto";
    git = true;
    extraOptions = [ "--group-directories-first" "--header" "--color=auto" ];
  };

  programs.fzf = {
    enable = true;
    enableBashIntegration = true;
    enableZshIntegration = true;
    tmux.enableShellIntegration = true;
    defaultOptions = [ "--no-mouse" ];
  };

  programs.git = {
    enable = true;
    userEmail = "anisanissakkaf@gmail.com";
    userName = "Anis Sakkaf";
    diff-so-fancy.enable = true;
    lfs.enable = true;
    extraConfig = {
      init = { defaultBranch = "main"; };
      merge = {
        conflictStyle = "diff3";
        tool = "meld";
      };
      push = { autoSetupRemote = true; };
      pull = { rebase = true; };
    };
  };

  programs.htop = {
    enable = true;
    settings.show_program_path = true;
  };

  programs.lf.enable = true;

  programs.bash.enable = true;

  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestion.enable = true;
    #initExtra = (builtins.readFile ../mac-dot-zshrc);
  };

  programs.home-manager.enable = true;
  programs.nix-index.enable = true;

  #   imports = [
  #     catppuccin.homeManagerModules.catppuccin
  #   ];

  #   catppuccin = {
  #     enable = true;
  #     flavor = "mocha";
  #   };

  programs.bat.enable = true;
  programs.bat.config.theme = "Nord";
  #programs.zsh.shellAliases.cat = "${pkgs.bat}/bin/bat";

  programs.zoxide.enable = true;

  imports = (libx.scanPaths ./.) ++ [ ];
}
