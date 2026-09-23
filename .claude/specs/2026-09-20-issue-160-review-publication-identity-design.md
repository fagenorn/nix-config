# Review-package directory identity — issue 160

## Problem

Review-package publication must refuse a replaced destination member directory and preserve competitors during refusal. Three original Ubuntu runs at `d1094c968ea16818de8073889d25ea9f99bd8deb` failed the existing `directory-before-first` assertion: removing and recreating the empty directory did not raise `PublicationError`. Darwin passes that fixture. The observed producer and test blobs are unchanged at investigation head `e48ea8d7f37a2fea69a9ddf6ff5535eac56fcc78`.

The producer records `(st_dev, st_ino)` after exclusive directory creation but retains no reference to that directory. Reuse of the removed directory's inode could therefore make a replacement appear unchanged. That mechanism is plausible, not yet demonstrated on Linux. The original [issue 37 cohort](https://github.com/fagenorn/nix-config/issues/37) remains historical evidence, not a replaceable verification sample.

A separate bounded Darwin experiment confirmed a cleanup defect: at the manifest callback, rename the member directory aside, create a replacement, and put a hardlink to a staged shard inside it. Publication refuses the changed directory, but pathname cleanup deletes the competitor's hardlink and leaves the invocation's original shard in the renamed directory. Distinct competitor bytes survive. This proves that file identity alone does not establish ownership of an entry reached through a replaced directory.

## Solution

Retain a no-follow descriptor for the created member directory for the entire publication and cleanup lifetime. Verify its named identity at the existing boundaries, but address member links, member checks, and member deletion relative to the retained directory. This combines a live directory identity with exclusive leaf creation and prevents member operations from following a replacement directory.

Keep the current CLI, producer report, callback labels, manifest-last protocol, artifact limits, full changed-file coverage, and parent-chain validation. Change only the publication lifetime and its focused tests. The design and autonomous grill are complete; Linux diagnosis and implementation verification remain delivery gates.

## Decisions

### Acquisition and lifetime

The publication operation owns the member descriptor; the optional final-parent descriptor remains borrowed. Keep existing parent pinning and verification semantics. After successful exclusive `mkdir`, obtain a no-follow directory stat, open the directory with `O_DIRECTORY | O_NOFOLLOW`, and compare descriptor identity and directory type with that observation and the current no-follow named entry before proceeding. Retain the descriptor until all publication checks and any cleanup finish. Do not invoke a member mutation callback before this acquisition completes.

Failure to open, stat, or establish matching identities raises `PublicationError` before linking members or manifest. Close any descriptor already acquired. Without an established retained identity, leave the uncertain directory alone rather than deleting an object whose ownership cannot be established. An empty directory may remain after this failure; safe refusal takes priority over reclamation.

This sequence is not atomic creation-and-open. A same-user replacement between `mkdir` and the first identity observation can be adopted, and replacement/reuse before the open can defeat a snapshot comparison. The current primitives do not prove creation provenance across that interval. The guaranteed lifetime begins at successful acquisition; the existing first-member fixture mutates after it. Do not describe the repair as solving that earlier race.

### Publication and cleanup

After each member or manifest callback, revalidate the final-parent chain when supplied, then the no-follow named member directory against the retained identity. The earlier directory-creation callback still precedes parent verification and exclusive creation. Verify all previously linked members against staged-file identities using relative leaf names and the retained member descriptor. Keep the checks after each member link and before the manifest link. Missing entries, changed types or identities, symlinks, and syscall failures refuse publication.

Create each member using exclusive `os.link` with `dst_dir_fd` set to the retained member descriptor and a leaf destination name, preserving `follow_symlinks=False`. A rename or replacement after a check cannot redirect that member operation into a competitor directory. Post-link verification still detects the changed named directory. The manifest retains exclusive publication, existing final-parent anchoring when supplied, and its position last; no replacement rename, overwrite, or whole-directory transaction is introduced.

On failure, inspect and unlink only recorded member leaf names relative to the retained directory, and only when their no-follow identities match the staged files. Cleanup may reclaim owned links in a renamed original directory; it must not inspect or remove members inside the replacement. A competitor hardlink to the same staged inode in the replacement directory is preserved. Remove the final member-directory name only when it still names the retained directory and is empty; a mismatched name is left untouched. Retain the descriptor through this cleanup, including the final removal decision.

Descriptor ownership must survive every error branch, including `fstat`, callback, link, cleanup, cwd restoration, and close failures. Attempt release of every locally owned descriptor even when another release/restoration fails; never close the borrowed parent. Do not retry a failed close on a possibly recycled fd number. Preserve the original publication failure as the raised `PublicationError` and its cause; attach each secondary cleanup/release failure as an exception note. Without a publication failure, raise `PublicationError` from the first release/restoration failure and note any later failures. A close failure after manifest publication leaves the completed package intact and reports failure; it does not trigger deletion through a released descriptor. This is scoped to descriptors owned by this operation, not a refactor of every descriptor user.

Python documents the required [directory-relative link and filesystem APIs](https://docs.python.org/3/library/os.html#os.link). Linux documents a directory fd as a [stable reference across rename](https://man7.org/linux/man-pages/man2/open.2.html) and explains why [failed close must not be retried blindly](https://man7.org/linux/man-pages/man2/close.2.html).

### Honest concurrency boundary

These checks are observations, not a lock. `mkdir`/open provenance, named-directory check/`rmdir`, member identity check/`unlink`, and the final checks/manifest link remain separate syscalls. The protocol cannot guarantee an immutable completed package against arbitrary concurrent same-user mutation, nor distinguish same-inode hardlink reinsertion within the original directory. Preserve the existing mutation-boundary guarantees and improve directory redirection safety without claiming atomic conditional unlink or snapshot publication. No sleeps, inode-timestamp heuristic, global lock, or platform-specific rename syscall is an acceptable substitute for the retained lifetime.

## Test seams

Agree two existing seams: `publish_package` with its `before_mutation` callback for publication and cleanup behavior, and the review-package CLI for unchanged output/report and integration behavior. OS fault injection may drive errors through these seams; assertions concern errors, directory entries, bytes, descriptor usability and cwd restoration, not private helper calls or counts.

- Preserve every existing collision, directory/member replacement, parent-symlink, cleanup, cap, and coverage assertion. Extend replacement coverage between members and before manifest. Competitor bytes and entries survive; these collision/replacement refusals leave no new manifest.
- Add the discriminating portable cleanup regression from the confirmed probe: rename the original directory at a callback after at least one member exists, recreate the destination, and install a same-inode competitor hardlink plus a distinct sentinel. Require refusal and preservation of both replacement entries. Require cleanup of this invocation's links in the renamed original. The current producer fails these observable assertions without relying on inode allocator behavior.
- Exercise a replacement at the actual member-link syscall boundary, after its preceding check, using a narrow OS wrapper that delegates the real link. The replacement directory, including a symlink-to-outside variant, receives no new shard and retains competitor entries. Require refusal after the operation and safe cleanup in the original directory. This distinguishes descriptor-relative mutations from merely retaining an otherwise unused fd.
- Exercise both sides of the acquisition handshake with a narrow real-`os.open` wrapper: replace the directory before delegating to open, and open the original before renaming/recreating the named directory. Both variants refuse before any member callback/link, preserve the replacement, leave no manifest, and close an acquired descriptor. Keep open/fstat error coverage too.
- Exercise locally owned descriptor release on success and publication failure both with the optional parent descriptor and with `final_parent_fd=None`, matching `_publish_candidate`'s live call shape. Inject restoration failure and require the saved cwd descriptor still to close. Combine a publication failure with a post-real-close failure and require the publication error/cause to remain primary while the release failure is visible in exception notes. Assert the borrowed parent remains usable. Do not claim an artificial close failure proves every kernel's interrupted-close behavior.

### Linux evidence gate

Before accepting a root cause or delivery, run the original producer on actual Ubuntu with the existing empty-directory replacement fixture, adding bounded failure diagnostics for no-follow `(st_dev, st_ino)` immediately before removal and after recreation. A test-first, independently reviewed commit can use the existing advisory workflow on the authorized issue branch; no workflow or protection change is required. Capture source/blob identity, runner/filesystem context, assertion result, and the observed identity pair. The diagnostics must preserve the fixture's refusal assertion and competitor writes.

An observed equal identity pair with the old producer's unexpected success establishes the reuse mechanism; a bounded comparison with a retained descriptor or the corrected producer must reject the replacement and preserve competitors. Allow at most 128 attempts per diagnostic variant; absence of reuse is inconclusive, not proof. If Ubuntu instead demonstrates another cause, revise this design before treating the lifetime repair as the diagnosed solution. Do not manufacture equal identity tuples or count Darwin evidence as a Linux reproduction.

For context only, the local Darwin probe tried 128 replacements without a retained fd and 128 with one; both observed zero reuse. Preserve that negative result without generalizing it. Retain new Ubuntu diagnostics separately from the original three-run cohort. After implementation, require the ordinary suite on Darwin and the actual Ubuntu advisory job, plus independent review of acquisition, mutation, cleanup and release before merge. A successful advisory job alone does not override a failed raw suite result.

## Out of scope

No branch-protection promotion, issue 37 evidence rewriting, host activation, new Linux execution service, artifact-format/policy change, diff-generation change, broad descriptor utility rewrite, crash recovery, hostile-filesystem support, or stronger multi-path atomic publication. No new glossary or ADR: the resolved terms already exist, and this local resource-lifetime repair creates no irreversible domain decision.

## Decision ledger

Scoped recommendations were adopted under the caller's explicit autonomous authorization; the grill challenged acquisition provenance, redirected operations, cleanup ownership, close failures, and evidence sufficiency.

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Pin the member directory from verified acquisition through publication and cleanup. | Issue 160; existing artifact-budget D16; parent-chain precedent. | Snapshot-only inode checks permit reuse after removal; timestamps are not ownership. |
| D2 | Use the retained directory for member link/stat/unlink while keeping named checks and manifest-last exclusion. | Confirmed replacement-hardlink cleanup defect; D16; defense in depth. | Retain an unused fd but keep pathname mutation/cleanup, which still redirects operations. |
| D3 | Leave uncertain acquisition objects untouched; release every locally owned descriptor and report release failures. | No-clobber acceptance; truthful terminal states; borrowed parent contract. | Delete after unproven acquisition, mask release failure, or retry a recycled descriptor. |
| D4 | Bound guarantees to verified lifetime and existing mutation boundaries, explicitly documenting remaining syscall gaps. | Actual mkdir/open and conditional cleanup primitives; root-cause standard. | Claim atomic provenance or arbitrary-concurrency safety the mechanism cannot provide; broaden into a new transaction system. |
| D5 | Test observable behavior at publication/callback and CLI seams, including the portable competitor-hardlink regression. | Existing race fixtures; tests-that-can-fail standard; direct Darwin probe. | Assert fd helper call counts or replace the failing fixture with a weaker allocator-dependent test. |
| D6 | Require actual Ubuntu identity diagnostics before claiming Linux cause, followed by Darwin/Ubuntu verification and independent mutation review. | Issue acceptance; three historical failures lack inode observations; caller's reviewed publication authorization. | Treat inode reuse as already proven, synthetic aliasing as Linux evidence, or advisory job success as suite success. |
| D7 | Pin both named-stat/open handshake boundaries and every owned-release call shape; keep an original publication failure primary and expose secondary cleanup/release failures as exception notes. | Phase 5 P5-S1/P5-S2; live `_publish_candidate` calls `publish_package` without `final_parent_fd`; D1, D3, D5. | Error-only acquisition tests, parent-only lifetime tests, or a release error that masks the publication cause. |
