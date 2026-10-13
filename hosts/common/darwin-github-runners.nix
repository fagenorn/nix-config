{
  config,
  lib,
  pkgs,
  unstablePkgs,
  hostname,
  ...
}:
let
  # A personal GitHub account has no account-wide runner scope (only orgs do), so
  # each repository gets its own runner registration: one launchd daemon per repo,
  # all sharing the nix-darwin-managed `_github-runner` user. That user cannot read
  # /Users/anis (mode 0750, group staff), and jobs reach tools only through the
  # daemon's Nix-built PATH, so nothing is installed globally.
  repos = [
    "arcwave"
    "argus"
    # Public: a fork PR could run code here. The repo's fork-PR policy is set to
    # require approval for every outside contributor, and the hosted CI jobs stay
    # on ubuntu — only a job that asks for `self-hosted` lands on this Mac.
    "nix-config"
  ];

  # Registration tokens (not PATs) live here, outside the Nix store. They are
  # written by `just register-runners`, which mints a one-hour token per repo
  # through `gh`; a runner reads its token only on first registration (no
  # `.runner` in its state dir yet). A PAT would sit readable by every job, since
  # jobs run as the same user that must read the token file.
  tokenDir = "/var/lib/github-runner-tokens";
in
{
  services.github-runners = lib.listToAttrs (
    map (repo: {
      name = "${hostname}-${repo}";
      value = {
        enable = true;
        # GitHub refuses jobs to a runner more than ~30 days behind the newest
        # release ("Runner version vX is deprecated and cannot receive messages"),
        # and Nix runs it with --disableupdate. The 25.11 channel lags too far, so
        # track unstable and keep `just update` at least monthly.
        package = unstablePkgs.github-runner;
        # Upstream dropped node20; the module's default still lists it.
        nodeRuntimes = [ "node24" ];
        url = "https://github.com/fagenorn/${repo}";
        tokenFile = "${tokenDir}/${repo}.token";
        replace = true;
        extraLabels = [
          "nix"
          hostname
        ];
        extraPackages = with pkgs; [
          curl
          findutils
          gnugrep
          gnused
          jq
          unzip
          xz
        ];
      };
    }) repos
  );

  # Jobs run `nix run github:cachix/devenv/<rev>`; `_github-runner` is untrusted, so
  # a workflow's `--option extra-substituters` is ignored and devenv would build
  # from source. Trust the cache system-wide instead of adding the runner to
  # `trusted-users`, which would hand PR code root-equivalent control of the store.
  nix.settings = {
    extra-substituters = [ "https://devenv.cachix.org" ];
    extra-trusted-public-keys = [
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
    ];
  };

  # Runs after nix-darwin has created `_github-runner` (users activate first).
  system.activationScripts.launchd.text = lib.mkBefore ''
    ${lib.getExe' pkgs.coreutils "install"} -d -m 0750 -o root -g _github-runner ${tokenDir}
  '';
}
