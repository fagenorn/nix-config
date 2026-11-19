# eleven-m5 runs Tailscale as the tailscaled system daemon (services.tailscale), so the console
# reads `serve status --json` and `status --json` from that daemon's own client: the first to show
# whether Serve proxies the tailnet name to the guest socket (#1299, ADR-console-077), the second
# for this host's own tailnet name (ADR-console-078). A Mac without the daemon (the menu-bar app on
# mbp) passes no client, so its guest door shares with nobody and its page says the name cannot be
# read.
{ lib, osConfig, ... }:
{
  agentConsole.tailscale = lib.mkIf (osConfig.services.tailscale.enable or false
  ) "${osConfig.services.tailscale.package}/bin/tailscale";
}
