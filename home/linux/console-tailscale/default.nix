# anis-desktop is WSL in mirrored networking: Tailscale Serve runs in the Windows client,
# never Tailscale inside WSL (#1235), so the console reads both `serve status --json` and
# `status --json` from the Windows client's executable (#1237), the second for this host's own
# tailnet name (ADR-console-078). The Windows client cannot proxy to the WSL guest
# socket, so this host reads `not_proxying` (#1299).
{ ... }:
{
  agentConsole.tailscale = "/mnt/c/Program Files/Tailscale/tailscale.exe";
}
