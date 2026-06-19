cask "palmier-pro" do
  # `version :latest` + `sha256 :no_check` aimed at the stable "latest" release URL means
  # every greedy `brew upgrade` (run on each `darwin-rebuild switch`) re-fetches the newest
  # PalmierPro.dmg. This is intentionally unpinned: the goal is always-latest, not reproducible.
  version :latest
  sha256 :no_check

  url "https://github.com/palmier-io/palmier-pro/releases/latest/download/PalmierPro.dmg",
      verified: "github.com/palmier-io/palmier-pro/"
  name "Palmier Pro"
  desc "AI-native macOS video editor with an embedded HTTP MCP server (127.0.0.1:19789)"
  homepage "https://github.com/palmier-io/palmier-pro"

  # The app hard-requires macOS 26 (Tahoe); LSMinimumSystemVersion in the bundle is 26.0.
  # Activation is gated upstream by myvars.enablePalmierPro, so this cask only installs once
  # you're on Tahoe — no brew-version-specific `depends_on macos:` symbol needed here.

  app "PalmierPro.app"

  zap trash: [
    "~/Library/Application Support/io.palmier.pro",
    "~/Library/Caches/io.palmier.pro",
    "~/Library/HTTPStorages/io.palmier.pro",
    "~/Library/Preferences/io.palmier.pro.plist",
    "~/Library/Saved Application State/io.palmier.pro.savedState",
  ]
end
