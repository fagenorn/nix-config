# Task 1: Preserve Studio runner home

**Files:**
- Modify: `hosts/darwin/eleven-m5/default.nix`

**Interfaces:**
- Consumes: nix-darwin `users.users._github-runner.home` and the existing Studio account.
- Produces: an activation preflight compatible with that existing account.

**Invariants:**
- Only the eleven-m5 home declaration changes, per D1.
- No account mutation, migration, service path change or credential access.

- [ ] **Step 1: Establish the failing boundary.**

Build the baseline with `just build`. Read `result/activate`, extract exactly
the `_github-runner` preflight block starting at `u=$(id -u _github-runner`
and ending before the next `u=$(id -u ` block. Execute it under Nix Bash
with PATH containing `/usr/bin:/bin:/usr/sbin:/sbin` and an `ensurePerms`
function that fails if called. The existing account must take only the
read-only branch. Expected: exit 1 with the reported home mismatch. Keep
the extraction harness and output under ignored runtime, not source tests.

- [ ] **Step 2: Implement.**

Add `_github-runner.home = lib.mkForce "/private/var/lib/github-runners";`
inside the Studio's existing `users.users` attribute set. Explain in a short
comment why the existing account requires the literal canonical path.

- [ ] **Step 3: Verify.**

Run `just build` (timeout 900s); run the same preflight harness on its
generated activation. Expected: exit 0 against the unchanged real account.
Evaluate `.#darwinConfigurations.mbp.config.users.users._github-runner.home`
with `nix eval --raw`; expected `/var/lib/github-runners`.
Evaluate the Studio owner home; expected `/Users/anis`.
Read-only probes must fail if the account is missing rather than permit writes.

- [ ] **Step 4: Commit.**

Commit only the product file with subject `fix: preserve Studio runner account home`
and the configured agent co-author trailer. Report the build and focused
red/green observations; do not run the full workflow suite per task.
