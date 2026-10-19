{ ... }:
{
  imports = [ ../../common/darwin-common-dock.nix ];

  homebrew.brews = [
    "libmsquic"
  ];

  # Added to the shared casks in hosts/common/darwin-common.nix.
  homebrew.casks = [
    # === Communication ===
    "discord" # Chat and VoIP platform
    "whatsapp"
    "slack" # Team communication platform

    # === Development & IT ===
    "nikitabobko/tap/aerospace"
    "insomnia"
    # Code Editors
    "visual-studio-code" # Widely used code editor
    # Containers & Virtualization
    #"docker",            # Docker Desktop (Resource heavy, consider alternatives)
    # AI / Machine Learning Tools
    # "lm-studio"          # UI for running local Large Language Models (LLMs)
    # Codex desktop app (incl. computer use). The standalone Codex.app was renamed
    # into ChatGPT.app in July 2026 and the `codex-app` cask was discontinued with
    # `chatgpt` as its official replacement — do not add `codex-app`. Computer use
    # is a plugin enabled inside the app and needs Screen Recording + Accessibility
    # grants in System Settings (TCC prompts on first use; not settable from nix).
    # Independent of the nix-managed codex CLI (home/common/codex/default.nix).
    "chatgpt"
    # Utilities
    #"wireshark",         # Network protocol analyzer

    # === Multimedia & Creativity ===
    # Audio Production & Playback
    # "audacity"           # Free audio editor and recorder
    # "plexamp"            # Headless Plex music player
    "plex" # Media server and player
    "spotify" # Music streaming service client
    {
      name = "stremio"; # Stable Stremio 5 desktop app
      greedy = true; # Keep Homebrew's auto-updating cask on the latest stable release
    }
    # Rogue Amoeba Audio Tools (Specialized Audio Routing/Recording)
    # "audio-hijack"       # Record audio from any application
    # "farrago"            # Soundboard application
    # "loopback"           # Cable-free audio routing between apps
    # "soundsource"        # System-wide audio control and effects
    # Video Production & Playback
    "obs" # Open Broadcaster Software (Streaming/Recording)
    # "screenflow"         # Screen recording and video editing (Paid)
    # "vlc"                # Versatile cross-platform media player
    # Graphics, 3D Printing & Design
    # darktable replaced Adobe Creative Cloud / Lightroom (2026-09-20). Served from the
    # self-authored fagenorn/palmier tap because the upstream cask is disabled
    # (fails_gatekeeper_check); see homebrew/palmier-tap/Casks/darktable.rb.
    "fagenorn/palmier/darktable" # Raw photo developer (open-source Lightroom replacement)
    # "bambu-studio",       # Slicer software for Bambu Lab 3D printers
    # "prusaslicer",        # Slicer software for Prusa and other 3D printers
    # Screen Capture
    # "cleanshot"          # Advanced screenshot, annotation, and recording tool (Paid)
    # "flameshot"          # Powerful screenshot tool (often used on Linux)

    # === Productivity & Utilities ===
    "microsoft-word"
    # Launchers & Automation
    # "popclip",            # Context menu utility appearing on text selection (Paid)
    # "raycast",            # Extensible launcher and workflow tool (Spotlight replacement)
    # "shortcat",           # Control UI elements via keyboard search
    # System Utilities & Monitoring
    # "alcove",             # Window management / Spacial computing utility (?) - Verify function
    # "istat-menus",        # System monitoring in the menu bar (Paid)
    # "jordanbaird-ice",    # Menu bar icon manager/hider (Open Source)
    # "omnidisksweeper",    # Utility to find and delete large files
    # Notes & Organization
    # "notion",             # All-in-one workspace app (notes, tasks, wikis)
    # "obsidian",           # Powerful Markdown knowledge base and note-taking app
    # File Management
    # "marta",              # Native macOS dual-pane file manager
    # Transcription
    # "macwhisper",         # Local audio transcription using OpenAI Whisper
    # Other Utilities
    # "music-decoy",        # Hides music player info during screen recording (github/FuzzyIdeas/MusicDecoy)
    #"clop",              # Clipboard manager (?) - Verify function and name

    # === Hardware Specific Utilities ===
    # Display/Dock Drivers
    # "displaylink",        # Driver for DisplayLink USB graphics adapters/docks

    # === Networking ===
    # "viscosity",          # Feature-rich OpenVPN client (Paid)

    # === Gaming ===
    "starsector" # Open-world single-player space combat and trading RPG
    # "steam"              # Valve's game distribution platform client

    # === Window Management ===
    "parsec"
    #"nikitabobko/tap/aerospace", # Tiling window manager (Requires custom tap `brew tap nikitabobko/tap`)

    # === OS Image Flashing ===
    #"balenaetcher",      # Tool to flash OS images to SD cards/USB drives

    "jetbrains-toolbox"
    "steam"
    "moonlight"
    "inkscape"

    "android-studio"

    # palmier-pro (AI video editor, macOS 26 / Tahoe only). greedy => every `brew upgrade`
    # (run on each `sudo just` activation) re-pulls the latest PalmierPro.dmg from the
    # self-authored fagenorn/palmier tap. Its embedded MCP server is wired into Claude Code
    # in home/common/claude-code/default.nix.
    {
      name = "fagenorn/palmier/palmier-pro";
      greedy = true;
      # No `no_quarantine` arg: Homebrew 6 removed `--no-quarantine` entirely
      # (Homebrew/brew#23363), and bundle passes unknown args through verbatim, so the
      # install dies with "invalid option". The app stays quarantined: Homebrew stamps
      # com.apple.quarantine on cask apps regardless of the system-wide
      # LSQuarantine = false preference, so Gatekeeper checks each fresh copy on launch.
    }
  ];
}
