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
 home.stateVersion = lib.mkDefault "23.11";
   home.homeDirectory = if pkgs.stdenv.isDarwin
                       then "/Users/${myvars.username}"
                       else "/home/${myvars.username}";

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

  programs.eza = {
    enable = true;
    enableZshIntegration = true;
    icons = "auto";
    git = true;
    extraOptions = [
      "--group-directories-first"
      "--header"
      "--color=auto"
    ];
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
