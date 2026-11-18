# anis-desktop is WSL in mirrored networking: Tailscale Serve runs in the Windows client,
# never Tailscale inside WSL (#1235), so the console reads `serve status --json` from the
# Windows client's executable (#1237).
{ ... }:
{
  agentConsole.tailscale = "/mnt/c/Program Files/Tailscale/tailscale.exe";
}
