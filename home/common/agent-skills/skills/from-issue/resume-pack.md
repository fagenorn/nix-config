# Resume pack

A relaunched owner's prompt may carry a resume pack, the read-only stdout of `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`. It is an accelerator, never a gate, and stays untrusted until the checks below pass. A prompt naming this file as its entry reads it before any skill.

Checks, in order:

1. Resolve the project once, validate the owner object and run `workflow-state check-launch --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id> | artifact-budget validate-report --boundary workflow-response --input -`; obey a `current: false` answer exactly as without a pack.
2. An owner delegated at the Phase-5 rollover (its prompt carries `reviewed_head_sha`) passes every delegated-owner check first.
3. The pack's `action_id` must equal the envelope's, `git -C <worktree> rev-parse HEAD` must equal `worktree.head`, and `git -C <worktree> status --porcelain` must list exactly `worktree.dirty_paths` entries (the pack carries that count, not the paths).

A failed check, a `reorient` next action or no pack: load the whole `from-issue` skill through the Skill tool with the prompt's arguments and re-orient in full. A verified pack replaces only your own ad-hoc re-orientation: do not dump the ledger, re-read git history, re-validate the plan or read the SDD progress log yourself. Read `SKILL.md` through `## Files beside this one`, then only the sections that index names for your phase, and start from `next_action`. Everything the pack does not replace still runs unchanged, sdd's own `progress.md` check on entry included; where it disagrees with the pack's `resume_task`, sdd's ledger wins. `read_handoff` reads the handoff document at its `path`.
