{ inputs, pkgs, ... }:
{
  # The hosts install the flake's own platform package, the derivation a project's CI fetches
  # (ADR-system-005). One shared application still keeps consumers from silently diverging
  # (issue 467 D2).
  _module.args.agentTools = inputs.self.packages.${pkgs.stdenv.hostPlatform.system}.agent-platform;
}
