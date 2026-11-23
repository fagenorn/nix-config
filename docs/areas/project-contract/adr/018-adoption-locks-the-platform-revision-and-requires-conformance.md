# ADR-project-contract-018 — Adoption locks the platform revision and requires Conformance

- **Status:** accepted; D11 amended in place by #1485
- **Decided in:** #1454 (per #1413, #1415, #1430)

## Context

Adoption stopped at the contract: it moved files, rewrote links and generated projections, but the adopted project's CI still had no way to run the platform it was adopted onto. ADR-project-contract-014 derives the platform's revision from the project's `devenv.lock` and says adoption writes the lock entry and keeps the protection file in step with the forge. ADR-project-contract-015 D3 renders the conformance workflow for the platform's own tree only and defers the locked form for other projects to adoption's lock entry. This decision makes adoption write the lock entry, the input declaration and the workflow, and require the `Conformance` check on the integration branch, all three or none.

## Decision

**D1. A project without a `devenv.lock` gets none of it (O2).** A repository whose base commit has no `devenv.lock` adopts exactly as before and gets the lock entry, the workflow and the required check when it is adopted again after adding devenv.

**D2. The input is declared in `devenv.yaml` (O1).** Adoption also declares `agent-platform` as a non-flake input pointing at the platform repository, so devenv keeps the locked node and a later lock bump moves it forward.

**D3. An unprotected branch refuses before anything is committed (O3).** Apply refuses, naming the branch, when the integration branch has no protection or requires no status checks (`adopt.required_check.unprotected`); the owner turns on required status checks once and adopts again. Adoption never creates, widens, narrows or removes a protection: it reads `GET repos/<repo>/branches/<branch>/protection/required_status_checks` and, after the commit is proved, sends one `POST` to `.../required_status_checks/contexts` with `contexts[]=Conformance`. An unreadable or malformed answer is `adopt.required_check.unreadable`.

**D4. The package names its revision (P1).** `$out/share/agent-platform/platform-revision.json` holds `{schema_version, type, owner, repo, rev, narHash, lastModified}` from the flake's `self` (`rev` null for a dirty tree), hosts link it to `~/.agents/share/platform-revision.json`, and `agent_platform.platform_revision()` reads it under the root, else under `HOME`, never both. `valid_revision()` is the one shape rule for a revision, used for the record and for a lock node.

**D5. The platform's own tree plans none of it (P2).** A base commit holding the platform manifest runs from its own tree with no lock (ADR-project-contract-014 D3, ADR-project-contract-015 D3); its required check is #1457.

**D6. Adoption never moves a lock, and the pin must be the installed revision (P3).** An existing `agent-platform` root input is kept only when it names a well-formed github node (`flake: false`, `original` naming the same owner and repository), and an existing `devenv.yaml` declaration only when it is exactly `url: github:<owner>/<repo>` and `flake: false`; any other entry is a repair, never replaced. A kept pin whose `rev` or `narHash` differs from the installed revision fails the gate (`adopt.conformance.pin_incompatible`): CI runs the pinned platform's renderer while apply renders with the installed one, so only equal revisions guarantee the committed workflow is fresh. The owner bumps the lock, then plans again.

**D7. Lock bytes (P4).** The lock is rewritten as `json.dumps(indent=2, sort_keys=True, ensure_ascii=False)` with the trailing newline kept as found.

**D8. The locked workflow reads the lock at CI time (P5).** The locked form reads `devenv.lock` with `jq`, so its bytes do not depend on the revision and a lock bump needs no regeneration. The resolver picks the form from the tree (own-tree form in the platform's tree, locked form elsewhere), so the platform marker is a projection input, exported with the contract wherever a `conformance_workflow` entry is declared.

**D9. Forge order and outcomes (P6).** Before any mutation apply checks the origin (D13) and reads `required_status_checks`: a 404, or a readable answer listing no context, refuses (D3); `Conformance` already present means no request (`already_required`), unless it is bound to a GitHub App other than Actions, which the generated job cannot satisfy (`adopt.required_check.app_mismatch`). After the commit, the byte proof (D16), the branch proof and the worktree removal, apply writes a pending record and makes the one `POST`. On a failed `POST` it re-reads once: present is success (`added`); a readable answer without the context (an empty list or a 404 included) is a confirmed absence, so apply deletes the adoption branch with a compare-and-delete whose result it reads back and refuses `adopt.required_check.refused` (`adopt.required_check.rollback_failed` when the branch could not be deleted, naming the branch and the commit); a re-read that raises is an unknown outcome, so apply keeps the branch and the record and refuses `adopt.required_check.unknown`. The context is added without an app binding, the shape of the contexts endpoint.

**D10. One ready gate, `conformance-plannable` (P7).** Last in `READY_GATES`, it keeps a plan `draft` when a repository with a `devenv.lock` cannot take the writes. The first failing cause, in order: `adopt.conformance.revision_unknown`, `tracker_unnamed`, `origin_mismatch`, `projection_collides`, `lock_unreadable`, `lock_entry_incompatible`, `pin_incompatible`, `input_undeclarable`, `input_incompatible`, `protection_file_unrequired`, then `contract_refused` from the final contract's scratch resolution (D15).

**D11. Forge names (P8).** The request targets the authored schema-2 `bindings.tracker.repo_slug`, or for a schema-3 contract the slug derived from the checkout's origin remote (tracker kind `github`) and `bindings.vcs.integration_branch` of the contract the plan writes.

**D12. Plan member and identity (P9).** The plan gains `plan.conformance` only when the writes are plannable, and it is the plan id's last input only then; the evidence record gains the `conformance` member and the gate row only for a repository the writes are planned for, so every existing plan id, document shape and evidence-record hash is unchanged.

**D13. The origin must be the forge target (P13).** The planned `repo_slug` must equal the remote slug of the checkout, which is where apply's branch is pushed. Apply's re-check reads both effective URLs of `origin` (fetch and push) and requires each to name that repository on `github.com`. Planning fails the gate on a mismatch and apply re-checks it before its first forge request (`adopt.required_check.origin_mismatch`, no `gh` call).

**D14. The protection file is kept in step (P10).** A tracked `.github/branch-protection.json` in the resolver's shape gains `{"context": "Conformance"}` (and `"Conformance"` in a `contexts` list the file also holds), existing entries and app bindings kept; any other shape fails the gate rather than being normalised or widened.

**D15. Inputs come from the planned base commit, and the final contract is validated as written (P11, P14).** Eligibility and the bytes of `devenv.lock`, `devenv.yaml` and the protection file are read as regular blobs of the plan's base revision, never from the working tree; uncommitted changes to the targets are the dirty-overlap refusal's. The plan resolves exactly the contract bytes it will write and fails the gate on a refusal.

**D16. The commit's conformance bytes are proved before the forge write (P16).** After the commit, each conformance `write-file` target's committed blob must hash to its operation's `after`, the amended contract's committed blob must hash to its operation's `after`, `devenv.yaml` (which an approved reference formatter may reformat) must still carry the planned declaration, and the resolver's `check-projections` must pass in the clean worktree with the workflow it renders being the blob the commit holds; a failure is `adopt.commit.conformance_unproved`, retains the worktree and makes no forge request.

**D17. Outstanding conformance work routes (P12).** A repository the writes are planned for has conformance work outstanding unless its base commit holds exactly one evidence record whose `conformance` member equals the one planned now and the plan writes none of the three files; outstanding work counts as pending work in outcome routing, so a repair is never routed to `no_change`.

**D18. One write per file (P15).** When an answered path-reference rewrite also edits a conformance target, the conformance edit is applied to the rewritten text and the file keeps its one `write-file` operation.

**D19. The requirement outlives a closed adoption (P17).** Once apply has succeeded, `Conformance` is required on the integration branch before the adoption branch is pushed or merged: until the adoption pull request merges, every other pull request to that branch is blocked, and when the push fails, the pull request is closed or abandoned (ADR-console-030 D5, D7), or the adoption's own Conformance run fails, the requirement stays. Adoption never removes or narrows protection (D3), so the owner removes `Conformance` from the branch's required checks, or merges a fresh adoption.

**D20. A pending record makes a repeated apply a reconciliation.** The pending record is `<worktrees>/<digest>.required-check.json` with `{plan_id, branch, commit, repo, integration_branch, result}`. Applying the same plan id while it exists skips planning, the worktree and the commit: the branch must still be the recorded commit (`adopt.required_check.pending_mismatch`), then the origin check, the state read and the settlement of D9 run, so a request that landed is never repeated and one that did not is made again. `--discard-retained` does not remove it, and the `discard` verb (the console's Cancel included) refuses `adopt.required_check.pending` while it exists, so the branch and the record are kept or removed together. The record must belong to the plan (its plan id, branch `adopt-<digest[:12]>`, repository and integration branch are the plan's, and its commit carries the plan's evidence record), else `pending_mismatch`. A record whose branch was deleted by hand, as `rollback_failed` instructs, is stale: apply and `discard` drop it and go on. Apply and `discard` of one plan hold one lock; a second holder is refused `adopt.required_check.pending`.

## Consequences

- The package changes on every commit because it records `self.rev`.
- A dirty build cannot adopt a devenv project: it has no revision (`adopt.conformance.revision_unknown`).
- A project pinned to another revision bumps its lock before it is adopted (D6).
- An older installed resolver refuses a contract declaring the `conformance_workflow` kind until its host switches.
- The requirement outlives a closed adoption (D19): until the adoption pull request merges, every other pull request to the integration branch is blocked, and a failed push, a closed or abandoned pull request (ADR-console-030 D5, D7) or a failing Conformance run leaves the requirement, which the owner removes.
- A console `Apply it again` after an unknown outcome reconciles through the pending record (D20).
- Registered projects get this through a later lock bump; nix-config's own required check stays #1457.
- Rejected: creating or widening a branch protection from adoption, because an owner's protection is theirs to configure (D3).
- Rejected: treating an unreadable re-read as an absence, because deleting the branch while the forge requires the check strands the requirement.
