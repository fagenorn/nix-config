# Issue 1290: the owner's services on a host nobody logs in to at the screen.
#
# A launchd user agent loads in the owner's gui/<uid> domain, which exists only while the
# owner is logged in at the console. eleven-m5 is reached over SSH with automatic login
# off, so nobody is ever logged in there as the owner and its login-session agents never
# load. A "boot host" sets `ownerServices.atBoot = true`: the console and verify-pending
# (and, from the secrets and cache-proxy work of the same issue, their dependencies) are
# then launchd daemons that run as the owner from boot, and launchd restarts them on exit.
# A login host (the laptop) keeps its user agents.
{ lib, ... }:
{
  options.ownerServices.atBoot = lib.mkOption {
    type = lib.types.bool;
    default = false;
    description = "Run the owner's services (console, secrets decryption, cache proxy, verify-pending) as boot-time launchd daemons of the owner instead of login-session agents, for a Mac the owner reaches only over SSH (issue 1290).";
  };
}
