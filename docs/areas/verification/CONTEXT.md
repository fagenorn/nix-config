---
area: Verification
budget: 200 lines
---

# Verification

Verification is what happens after a merge for an issue whose evidence only the world can give. A held issue carries a machine-readable check that scheduled runs on each host evaluate and, when it passes, close.

## Language

**Check**:
One named, read-only test a verify block asks a host to run against a held issue. A check is either a committed script or an owner-approved command bound by digest.
_Avoid_: assertion

**Held issue**:
An issue kept open after its change merged because an evidence criterion is still unproven. It holds a verify block in its hold comment.
_Avoid_: pending issue

**Owner prompt**:
A comment asking the owner to approve, act on, decide or look at a stale check. Each prompt is an owner-action marker with tick boxes, posted once per identity.

**Probe**:
A read-only observation a check makes of the live system, such as a forge setting or a log window. A probe never changes state.

**Verification pass**:
One scheduled run of the verify-pending runner on a host. It reads the due checks of every held issue in the fleet registry, runs the runnable ones and closes the issues whose checks pass.
_Avoid_: verify run

**Verified tree**:
A tree whose verification result the project records against the exact tree object, so that an unchanged tree needs no second verification. It is addressed by tree, not by commit.
_Avoid_: verified commit

**Verify block**:
The one fenced block with the info string `verify` in a hold comment: a strict, machine-readable list of the checks that decide the held issue. Only a comment by an owner or member carries a block the runner trusts.
_Avoid_: check block
