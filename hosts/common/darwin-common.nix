{
  inputs,
  outputs,
  config,
  lib,
  hostname,
  system,
  username,
  pkgs,
  unstablePkgs,
  ...
}:
let
  inherit (inputs) nixpkgs nixpkgs-unstable;
in
{
  users.users = {
    "${username}" = {
      home = "/Users/anis";
      shell = pkgs.zsh;
    };
  };

  nix = {
    settings = {
      experimental-features = [
        "nix-command"
        "flakes"
      ];
      warn-dirty = false;
      # Cachix cache for sadjow/claude-code-nix so the latest Claude Code binary is
      # substituted pre-built instead of compiled locally. `extra-` appends, leaving
      # the default cache.nixos.org substituter intact.
      extra-substituters = [ "https://claude-code.cachix.org" ];
      extra-trusted-public-keys = [
        "claude-code.cachix.org-1:YeXf2aNu7UTX8Vwrze0za1WEDS+4DuI2kVeWEE4fsRk="
      ];
    };
    channel.enable = false;

    extraOptions = ''
      trusted-users = root anis
    '';
  };

  system.primaryUser = "anis";
  system.stateVersion = 5;

  nixpkgs = {
    hostPlatform = lib.mkDefault "${system}";
  };

  # pins to stable as unstable updates very often
  nix.registry = {
    n.to = {
      type = "path";
      path = inputs.nixpkgs;
    };
    u.to = {
      type = "path";
      path = inputs.nixpkgs-unstable;
    };
  };

  programs.zsh = {
    enable = true;
  };

  fonts.packages = [
    pkgs.fira-code
    pkgs.nerd-fonts.fira-code
  ];

  homebrew = {
    enable = true;
    onActivation = {
      # Homebrew 7 removed `brew bundle install --cleanup` ("Calling the `--cleanup`
      # switch is disabled"), but nix-darwin 25.11 still emits `--cleanup --zap` for
      # cleanup = "zap". nix-darwin master fixed this on 2026-06-01 (bb9c29c1: it now
      # passes `--zap --force-cleanup`) and it was never backported to 25.11. Keep the
      # zap semantics by passing Homebrew 7's spelling through extraFlags instead;
      # drop this shim once nix-darwin is bumped past that commit.
      cleanup = "none";
      extraFlags = [ "--zap" "--force-cleanup" ];
      autoUpdate = true;
      upgrade = true;
    };
    global.autoUpdate = true;

    brews = [
      #"bitwarden-cli"
      #"borders"
    ];
    taps = [
      # Every tap nix-homebrew lays on disk MUST also be declared here so it lands in
      # the generated Brewfile: since Homebrew 6, `brew bundle` cleanup UNTAPS any tap
      # missing from the Brewfile, and `brew untap` now UNINSTALLS every cask installed
      # from that tap first (one y/n keystroke on a TTY). An undeclared homebrew/cask
      # is exactly how all casks got wiped on 2026-08-02.
      "homebrew/bundle"
      "homebrew/cask"
      "homebrew/core"
      "nikitabobko/tap"
      "fagenorn/palmier"
      #"FelixKratz/formulae" #sketchybar
    ];
    # Shared by every Mac. Host-specific apps are added in hosts/darwin/<hostname>/default.nix.
    casks = [
      "google-chrome"
      "helium-browser" # imputnet privacy Chromium browser -> /Applications/Helium.app (bundle net.imput.helium); replaced microsoft-edge
      "ghostty" # Modern GPU terminal
      "orbstack" # Fast Docker Desktop alternative & Linux VMs
      "tailscale-app" # Mesh VPN client
    ];
    masApps = {
      # === Productivity & Utilities ===
      # "Amphetamine" = 937984704;        # Keep your Mac awake
      # "AutoMounter" = 1160435653;       # Automatically mount network shares
      # "Bitwarden" = 1352778147;         # Password manager
      # "Fantastical" = 975937182; # Calendar application
      # "Perplexity" = 6714467650;        # AI Search / Assistant app
      # "Resize Master" = 102530679;      # Batch image resizing tool
      # "rCmd" = 1596283165;              # Use Right Command for app switching/shortcuts
      # "Snippety" = 1530751461;          # Snippet manager (?) - Verify function
      # "The Unarchiver" = 425424353;     # Versatile file archive extractor
      # "Todoist" = 585829637;          # Task management and to-do list app

      # === Development & IT ===
      # "Disk Speed Test" = 425264550;    # Blackmagic Disk Speed Test utility
      # "Microsoft Remote Desktop" = 1295203466; # RDP client
      # "UTM" = 1538878817;             # Virtual machine host (QEMU frontend)
      # "Xcode" = 497799835; # Apple's IDE for macOS/iOS development

      # === Communication ===
      # "Ivory for Mastodon by Tapbots" = 6444602274; # Mastodon client
      # "Telegram" = 747648890;         # Messaging application

      # === Networking & Home Automation ===
      # "Home Assistant Companion" = 1099568401; # Client for Home Assistant
      #"Tailscale" = 1475387142;       # Mesh VPN client (also available as cask, choose one)
      # "Wireguard" = 1451685025;        # WireGuard VPN client

      # === Multimedia & Creativity ===
      # "Creator's Best Friend" = 1524172135; # YouTube management tool (?) - Verify function
      # "DaVinci Resolve" = 571213070;    # Professional video editing suite
      # "Final Cut Pro" = 424389933;     # Professional video editing suite (Apple)

      # === Apple Productivity Suite ===
      # "Keynote" = 409183694;
      # "Numbers" = 409203825;
      # "Pages" = 409201541;

      # === Region/Account Restricted Apps (Example: UK Apple ID needed) ===
      # (Keep these grouped if they share specific account requirements)
      #"Logic Pro" = 634148309;       # Professional audio workstation (Apple)
      #"MainStage" = 634159523;       # Live performance audio tool (Apple)
      #"Garageband" = 682658836;      # Consumer audio workstation (Apple)
      #"ShutterCount" = 720123827;    # Reads camera shutter actuations
      #"Teleprompter" = 1533078079;   # Teleprompter application
    };
  };

  # Homebrew 7 made `brew bundle` upgrade `auto_updates` casks (WhatsApp, Chrome, Slack, ...)
  # by default: it quits the running app, swaps the bundle, then `open -b`s the new,
  # quarantined copy mid-activation. On 2026-09-23 that reopen raised a Gatekeeper prompt
  # and one click on it moved the fresh WhatsApp.app to the Trash. These apps update
  # themselves, so leave them to it, and never quit/reopen a running app from a switch.
  # Read by every `brew` invocation, including the activation's `brew bundle`.
  environment.etc."homebrew/brew.env".text = ''
    HOMEBREW_NO_UPGRADE_AUTO_UPDATES_CASKS=1
    HOMEBREW_NO_UPGRADE_QUIT_CASKS=1
  '';

  # `brew bundle` trusts the Caskroom record, not /Applications: once an app is trashed or
  # deleted out from under Homebrew, the cask stays "installed" and no switch restores it.
  # Every installed app cask keeps a Caskroom/<token>/<version>/<App>.app symlink to its
  # target, so a dangling one means the app is gone. Forget those casks so the bundle step
  # that follows reinstalls them. Ordered after nix-homebrew's prefix setup (mkBefore) and
  # before nix-darwin's bundle (default priority); never fails the activation.
  system.activationScripts.homebrew.text = lib.mkOrder 750 ''
    if [ -x ${config.homebrew.brewPrefix}/brew ] && [ -d ${dirOf config.homebrew.brewPrefix}/Caskroom ]; then
      for link in ${dirOf config.homebrew.brewPrefix}/Caskroom/*/*/*.app; do
        [ -L "$link" ] && [ ! -e "$link" ] || continue
        token=$(basename "$(dirname "$(dirname "$link")")")
        echo >&2 "Homebrew: $token is installed but $(readlink "$link") is missing; reinstalling"
        sudo --user=${lib.escapeShellArg config.homebrew.user} --set-home \
          ${config.homebrew.brewPrefix}/brew uninstall --cask --force "$token" \
          || echo >&2 "Homebrew: could not reset $token; reinstall it by hand"
      done
    fi
  '';

  # Keyboard
  system.keyboard.enableKeyMapping = true;
  system.keyboard.remapCapsLockToEscape = false;

  # Add ability to used TouchID for sudo authentication
  security.pam.services.sudo_local.touchIdAuth = true;

  # macOS configuration
  # system.activationScripts.postUserActivation.text = ''
  #   # Following line should allow us to avoid a logout/login cycle
  #   /System/Library/PrivateFrameworks/SystemAdministration.framework/Resources/activateSettings -u
  # '';
  system.defaults = {
    NSGlobalDomain.AppleShowAllExtensions = true;
    NSGlobalDomain.AppleShowScrollBars = "Always";
    NSGlobalDomain.NSUseAnimatedFocusRing = false;
    NSGlobalDomain.NSNavPanelExpandedStateForSaveMode = true;
    NSGlobalDomain.NSNavPanelExpandedStateForSaveMode2 = true;
    NSGlobalDomain.PMPrintingExpandedStateForPrint = true;
    NSGlobalDomain.PMPrintingExpandedStateForPrint2 = true;
    NSGlobalDomain.NSDocumentSaveNewDocumentsToCloud = false;
    NSGlobalDomain.ApplePressAndHoldEnabled = false;
    NSGlobalDomain.InitialKeyRepeat = 25;
    NSGlobalDomain.KeyRepeat = 2;
    NSGlobalDomain."com.apple.mouse.tapBehavior" = 1;
    NSGlobalDomain.NSWindowShouldDragOnGesture = true;
    NSGlobalDomain.NSAutomaticSpellingCorrectionEnabled = false;
    LaunchServices.LSQuarantine = false; # disables "Are you sure?" for new apps
    loginwindow.GuestEnabled = false;
    finder.FXPreferredViewStyle = "Nlsv";
    NSGlobalDomain."com.apple.trackpad.enableSecondaryClick" = true;
  };

  system.defaults.CustomUserPreferences = {
    "com.apple.finder" = {
      ShowExternalHardDrivesOnDesktop = true;
      ShowHardDrivesOnDesktop = false;
      ShowMountedServersOnDesktop = false;
      ShowRemovableMediaOnDesktop = true;
      _FXSortFoldersFirst = true;
      # When performing a search, search the current folder by default
      FXDefaultSearchScope = "SCcf";
      DisableAllAnimations = true;
      NewWindowTarget = "PfDe";
      NewWindowTargetPath = "file://\${HOME}/Desktop/";
      AppleShowAllExtensions = true;
      FXEnableExtensionChangeWarning = false;
      ShowStatusBar = true;
      ShowPathbar = true;
      WarnOnEmptyTrash = false;
    };
    "com.apple.desktopservices" = {
      # Avoid creating .DS_Store files on network or USB volumes
      DSDontWriteNetworkStores = true;
      DSDontWriteUSBStores = true;
    };
    "com.apple.WindowManager" = {
      EnableStandardClickToShowDesktop = 0; # Click wallpaper to reveal desktop
      StandardHideDesktopIcons = 0; # Show items on desktop
      HideDesktop = 0; # Do not hide items on desktop & stage manager
      StageManagerHideWidgets = 0;
      StandardHideWidgets = 0;
    };
    "com.apple.dock" = {
      autohide = false;
      launchanim = false;
      static-only = false;
      show-recents = false;
      show-process-indicators = true;
      orientation = "left";
      tilesize = 36;
      minimize-to-application = true;
      mineffect = "scale";
      enable-window-tool = false;
    };
    "com.apple.ActivityMonitor" = {
      OpenMainWindow = true;
      IconType = 5;
      SortColumn = "CPUUsage";
      SortDirection = 0;
    };
    "com.apple.AdLib" = {
      allowApplePersonalizedAdvertising = false;
    };
    "com.apple.SoftwareUpdate" = {
      AutomaticCheckEnabled = true;
      # Check for software updates daily, not just once per week
      ScheduleFrequency = 1;
      # Download newly available updates in background
      AutomaticDownload = 1;
      # Install System data files & security updates
      CriticalUpdateInstall = 1;
    };
    "com.apple.TimeMachine".DoNotOfferNewDisksForBackup = true;
    # Prevent Photos from opening automatically when devices are plugged in
    "com.apple.ImageCapture".disableHotPlug = true;
    # Turn on app auto-update
    "com.apple.commerce".AutoUpdate = true;
    #   "com.googlecode.iterm2".PromptOnQuit = false;
    #   "com.google.Chrome" = {
    #     AppleEnableSwipeNavigateWithScrolls = true;
    #     DisablePrintPreview = true;
    #     PMPrintingExpandedStateForPrint2 = true;
    #   };
  };
}
