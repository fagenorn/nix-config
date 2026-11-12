# ADR-delivery-008 — The delivery programs run from copies in the checkout

- **Status:** accepted; amended by ADR-delivery-009
- **Decided in:** issue 912

## Context

The lead started `deliver-batch.js` and its `deliver-standard.js` children by their skill-directory paths, which reach the Nix store through links (ADR-delivery-002). An activation during a three-hour batch replaced what those links resolve to, the next child could not be loaded, the row read `child-<n> returned nothing`, and the Workflow tool then refused the skill path as a script path ("scriptPath must be a script path this tool returned, or a file you can already read").

## Decision

- The lead runs `program-copies --repo-root <checkout> --from <the deliver-standard skill dir>` and starts both programs from the printed copies under `<checkout>/.program-copies/<skill dir name>/`.
- `--repo-root` must be the checkout's top level, so the copies are inside the checkout the lead runs in.
- A `.gitignore` of `*` makes that directory ignore itself.
- A copy is replaced atomically only when the installed program changed.
- A child call that throws logs its original error and gives its row `child program could not be loaded or threw: <first line> (<child_script>)`, with the first line shortened so the reason keeps the path within the 300-character row bound.

## Considered options

- **Copies under the git common dir.** Rejected: a linked worktree's common dir and git dir are outside its working directory, so the Workflow tool would refuse the copies with the same error the issue reports.
- **Content-addressed copies per run.** Rejected: they grow without bound, and pruning could delete a running batch's copy.
- **Copying inside `deliver-batch.js`.** Rejected: the program has no filesystem access.
- **Copies in the working tree without an ignore file.** Rejected: they would show as untracked files and could be committed.

## Consequences

- A running batch reads the newer child after another lead in the same checkout places newer programs, as the store link did.
- Each checkout, main or linked worktree, holds its own copies, ignored by git and never committed.
- The batch cannot tell a load failure from a throw, so the reason names both.
