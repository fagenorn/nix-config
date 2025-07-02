{
  config,
  inputs,
  pkgs,
  lib,
  unstablePkgs,
  libx,
  myvars,
  ...
}:
{
  home.stateVersion = lib.mkDefault "25.05";

  programs.gpg.enable = true;

  programs.gh = {
    enable = true;
    settings = {
      git_protocol = "ssh";
    };
  };

  programs.direnv = {
    enable = true;
    nix-direnv.enable = true;
  };

  programs.lsd = {
    enable = true;
  };

  programs.yazi = {
    enable = true;
    enableZshIntegration = true;
  };

  programs.fzf = {
    enable = true;
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
      init = {
        defaultBranch = "main";
      };
      merge = {
        conflictStyle = "diff3";
        tool = "meld";
      };
      push = {
        autoSetupRemote = true;
      };
      pull = {
        rebase = true;
      };
      gpg = {
        format = "ssh";
      };
    };
    signing = {
      signByDefault = true;
      key = "${config.home.homeDirectory}/.ssh/id_ed25519";
    };
  };

  programs.htop = {
    enable = true;
    settings.show_program_path = true;
  };

  programs.lf.enable = true;

  programs.bash.enable = false;

  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;
    initContent = ''
      source ${pkgs.zsh-vi-mode}/share/zsh-vi-mode/zsh-vi-mode.plugin.zsh
    '';
  };

  programs.atuin = {
    enable = true;
    enableZshIntegration = true;
    flags = [
      "--disable-up-arrow"
    ];
  };

  programs.home-manager.enable = true;
  programs.nix-index.enable = true;
  programs.nix-index.enableZshIntegration = true;
  programs.nix-index.enableBashIntegration = false;
  programs.command-not-found.enable = false;

  programs.bat.enable = true;

  programs.zoxide.enable = true;

  catppuccin = {
    enable = true;
    flavor = "macchiato";
  };

  imports = (libx.scanPaths ./common) ++ [ ];
}
