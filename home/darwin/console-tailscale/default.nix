# eleven-m5 runs Tailscale as the tailscaled system daemon (services.tailscale), so the console
# reads `serve status --json` from that daemon's own client to show whether Serve proxies the
# tailnet name to the guest socket (#1299, ADR-console-077). A Mac without the daemon (the
# menu-bar app on mbp) passes no client, and the page shows the Serve state as unchecked.
{ lib, osConfig, ... }:
{
  agentConsole.tailscale = lib.mkIf (osConfig.services.tailscale.enable or false
  ) "${osConfig.services.tailscale.package}/bin/tailscale";
}
