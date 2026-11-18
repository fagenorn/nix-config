# ADR-console-072 — Any merged change this host is built from and does not run is the activation line

- **Status:** accepted
- **Decided in:** #1258

## Context

ADR-console-043 D1 and ADR-system-004 D8 tied the activation line to console files, so a merged change to an agent skill, a plugin patch or a Nix module left the line reading "Activated this host at <older commit>" with no Activate. Agent sessions may not switch the host (ADR-system-004), so the change stayed inactive while the owner was told everything is active.

## Decision

**D1. Two comparisons.** Console-built files keep the blob comparison of ADR-console-043 D1 and decide the console wording. Every other path is compared from the host's configuration revision (`nixos-version --configuration-revision`, `darwin-version` on darwin; the flake sets it from `self.rev`, or `dirtyRev` for a dirty tree) to the origin tip, with `git diff-tree -r --name-only -z --no-renames` in the registered checkout. A `-dirty` revision is compared from its commit, so a dirty build's uncommitted edits are not seen. The revision is read on every poll, because a switch that leaves the console unchanged does not restart it. Rejected: a manifest of every file's blob inside the console's build (it would rebuild and restart the console on every commit) and the system revision alone (it changes on every commit, documentation included).

**D2. What the host is built from.** Every path except those under `docs/`, `tests/`, `.github/`, `.agents/`, the root files `README.md`, `CLAUDE.md`, `AGENTS.md`, `justfile`, `.gitignore`, `.sops.yaml`, and the Nix-module documentation `home/common/claude-code/README.md`, `home/common/agent-skills/README.md`, `home/linux/claude-local/README.md`, `hosts/darwin/eleven-m5/README.md`; none of them is read by a host configuration (`tests/` only by flake checks). Prose a host installs still counts: skill files, and the standards directory with its README, which the agent-skills module installs whole; `python/README.md` counts because the package is built from the whole `python/` directory. An unlisted path counts: a needless line costs one Activate, a missed one tells the owner everything is active. Rejected: an inclusion list of the directories Nix reads, which a new directory would silently escape, and excluding every file named `README.md`, which would drop the installed standards README.

**D3. The wording.** A console change reads "A console change merged at <commit> is not active on this host." Otherwise, when every other changed path is under `python/`, `home/common/agent-`, `home/common/claude-code/`, `home/common/codex/`, `patches/agent-plugins/` or `lib/agent-`, the line reads "A change to the agent tooling merged at <commit> and is not active on this host."; else "A change to the host configuration merged at <commit> and is not active on this host.". All three carry the same Activate, which builds the tip (ADR-system-004 D4).

**D4. A failed read keeps the line.** A revision that cannot be read, or one whose commit the checkout lacks, is a failed read as in ADR-console-043 D8: the last line stays and one stderr line is written; it is never "nothing to activate".

**D5. A failed run stays retryable.** The host's configuration revision can reach the commit before switch-to-configuration fails (ADR-system-004 D5), which empties the comparison of D1. So a failed run for the shown commit keeps Activate while the tip is that commit, pending or not; the line's Activate and the page write's `nothing to activate` refusal are decided by the same rule. An activated run is unchanged.

## Consequences

- This amends ADR-console-043 D1 (a change outside the console files now shows the line) and ADR-system-004 D6 and D8 (the line shows for any host-built change; an activation that does not change the console need not restart it, and the run's own scope and recorded exit settle it as before).
- ADR-system-004 D3's guard sentence is unchanged: every wording ends "is not active on this host".
- Related: ADR-console-001, ADR-console-043, ADR-system-004.
