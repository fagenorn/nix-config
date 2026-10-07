# Resume pack

A relaunched owner's prompt may carry a resume pack: the stdout of `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`, which reads the ledger, the attempt's recorded worktree and its SDD workspace and writes nothing. The pack is an accelerator, never a gate, and stays untrusted until the checks below pass.

Checks, in order:

1. Resolve the project once, validate the owner object and run `check-launch`; obey a `current: false` answer exactly as without a pack.
2. An owner delegated at the Phase-5 rollover (its prompt carries that rollover's continuation: `reviewed_head_sha` and two measured artifact blocks) passes every delegated-owner check first. A generic `delegate` owner carries no continuation and runs none of them.
3. The pack's `action_id` must equal the envelope's, `git -C <worktree> rev-parse HEAD` must equal `worktree.head`, and `git -C <worktree> status --porcelain` must list exactly `worktree.dirty_paths` entries (the pack carries that count, not the paths). On any mismatch the pack is stale: ignore it and re-orient in full.

A verified pack replaces only your own ad-hoc re-orientation: do not dump the ledger, re-read git history, re-validate the plan, read the SDD progress log yourself, or read skills end to end. Start from its `next_action` and read the sections `SKILL.md`'s index names for your phase. Everything the pack does not replace still runs unchanged, sdd's own `progress.md` check on entry included; where it disagrees with the pack's `resume_task`, sdd's ledger wins. `read_handoff` reads the handoff document at its `path`; `reorient` re-orients in full, as does a relaunch with no pack.

A `resume-pack` refusal or failure only means the prompt carries no pack; it never stops a relaunch.
