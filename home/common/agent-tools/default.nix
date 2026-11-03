{ pkgs, ... }:
{
  # One shared application keeps consumers from silently diverging (issue 467 D2).
  _module.args.agentTools = import ../../../lib/agent-tools.nix { inherit pkgs; };
}
