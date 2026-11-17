# ADR-console-063 — A bypass proof runs on a throwaway repository it registers and removes

- **Status:** accepted
- **Decided in:** #1152

## Context

A manager started in `bypassPermissions` mode (ADR-console-060) relies on the guard alone to refuse what could reach production. The proof that it does must attempt each forbidden action for real, against a repository whose loss costs nothing, and must leave nothing behind: not the repository, not a fleet entry, not a compiled policy row. The guard's policy compiler reads the fleet registry, so the throwaway has to be registered while the proof runs.

## Decision

**D1. Only the owner starts it, and an agent session refuses.** `bypass-proof github` exits 2 before any step when `CLAUDECODE` is set. The owner runs one line from their own terminal after a switch: `gh auth refresh -h github.com -s delete_repo && bypass-proof github --owner <owner> --template .agents/project.json`. The delivery builds the scripted proof and tests it against fakes; the GitHub run is the owner's.

**D2. The throwaway registers itself.** The proof adds `{project_id, root}` for its own `bypass-proof/<name>` id to the fleet registry through `agent_platform.registry_transaction()` and removes it at teardown, instead of a full adoption: the compiler needs only the registry entry and a resolvable contract. Removal refuses any id outside `bypass-proof/`, so the proof can never drop a real project. The registry comment in `agent_platform.py` names this second writer.

**D3. Teardown always runs and is reported.** Unregister, recompile, delete the repository and remove the checkout run in that order after any outcome, each attempted even when an earlier one failed. A failed step is recorded with the command that finishes it by hand and makes the exit 1. Deletion is keyed to `gh repo create` having returned, not to the whole setup succeeding, so a failed push or pull request still deletes the repository. Recompilation counts as done only when the compiled policy no longer holds the throwaway's slug: `claude-guard-policy` exits 1 both for a policy written with refusals and for a kept previous policy, and the latter keeps the old row byte for byte.

**D4. The throwaway is private, so the guard itself judges its required check.** On a private repository whose plan cannot protect `main`, the guard falls to its own floor and refuses a merge while the declared required check is not green. On a plan that can protect it, the guard refuses with a failed protection lookup instead; the proof then records the merge as `wrong_refusal` and fails, rather than counting a refusal for another reason.

**D5. The record is the evidence.** The report, the outcome, the reason and the teardown entries are printed and written atomically, mode 0600, to `~/.agents/state/console/bypass-proof.json`. A later check recomputes the verdict from the seven attempts and the four teardown steps and does not trust the stored outcome.

## Consequences

- A run leaves a record in the owner's state directory, overwritten by the next run.
- The owner's token needs the `delete_repo` scope; without it the deletion step fails and the record names `gh repo delete <slug> --yes`.
- A manager the console would not run in bypass (production rules not in the guard's policy) makes the proof `refused` without starting a session.
- The registry has a second writer; it touches only `bypass-proof/` entries.
- A wake step, `bypass-proof wakes` (ADR-console-068), proves on a local throwaway repository that a bypass manager receives the console's relays; it needs no GitHub.
