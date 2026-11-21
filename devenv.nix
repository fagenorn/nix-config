# The shell nix-config's commit-time and verification commands run in
# (`just build`, `just agent-workflow-tests`, the adoption commit named in the
# project contract).
#
# It deliberately enables no devenv git-hooks module, sets no shell hook, and
# provides no signer and no home or git-config override: commits are signed
# with the key in the user's home by the host's `ssh-keygen` and take their
# hooks from the host-wide hooks directory.
{ pkgs, ... }:
{
  packages = [
    pkgs.git
    pkgs.just
    pkgs.python3
    pkgs.nodejs
    pkgs.jq
  ];
}
