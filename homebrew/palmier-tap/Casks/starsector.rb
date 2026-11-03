cask "starsector" do
  # Self-authored copy of the upstream homebrew-cask `starsector` cask, which was
  # `disable!`d on 2026-09-01 (`fails_gatekeeper_check`: the app bundle is unsigned) and
  # later gained a `zap :not_required` stanza the pinned Homebrew rejects. Homebrew still
  # stamps com.apple.quarantine on the installed app, so home/darwin/starsector/default.nix
  # strips it after every activation. Pinned + sha256-checked: bump version and sha together
  # (the release zip is linked from https://fractalsoftworks.com/preorder/).
  version "0.98a-RC8"
  sha256 "3bc6df1e31188155594b4f4314b7dfa4154781c5848b7a9b494cc915ac935c1a"

  url "https://f005.backblazeb2.com/file/fractalsoftworks/release/starsector_mac-#{version}.zip"
  name "Starsector"
  desc "Open-world single-player space combat and trading RPG"
  homepage "https://fractalsoftworks.com/"

  # The preorder page sits behind Cloudflare, so new versions are checked manually.
  livecheck do
    skip "Cannot be fetched due to Cloudflare protections"
  end

  depends_on :macos

  app "Starsector.app"
end
