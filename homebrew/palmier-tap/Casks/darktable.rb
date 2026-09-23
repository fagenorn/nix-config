cask "darktable" do
  # Self-authored copy of the upstream homebrew-cask `darktable` cask, which was
  # `disable!`d on 2026-09-01 (`fails_gatekeeper_check`: the official DMG is signed but
  # not notarized). Homebrew still stamps com.apple.quarantine on the installed app, so
  # home/darwin/darktable/default.nix strips it after every activation; without that step
  # Gatekeeper refuses to open the bundle. Pinned + sha256-checked: bump version and sha together
  # (sha from https://github.com/darktable-org/darktable/releases, the arm64 .dmg).
  version "5.6.1"
  sha256 "155c25a48e06023eeeda3640f6f4fc7848bc1ad8e7384ba1d7b63098986fbeda"

  url "https://github.com/darktable-org/darktable/releases/download/release-#{version}/darktable-#{version}-arm64.dmg",
      verified: "github.com/darktable-org/darktable/"
  name "darktable"
  desc "Photography workflow application and raw developer"
  homepage "https://www.darktable.org/"

  depends_on arch: :arm64
  depends_on macos: :sonoma

  livecheck do
    url :url
    regex(/^release[._-]v?(\d+(?:\.\d+)+)$/i)
    strategy :github_latest
  end

  app "darktable.app"

  uninstall quit: "org.darktable"

  zap trash: [
    "~/.cache/darktable",
    "~/.config/darktable",
    "~/.local/share/darktable",
    "~/Library/Saved Application State/org.darktable.savedState",
  ]
end
