# ADR-project-contract-013 — The conformance workflow is a projection the resolver renders

- **Status:** accepted
- **Decided in:** #1452 (per #1413, #1417)

## Context

A pull request to nix-config had no check that ran the conformance engine from the repository's own tree: the verdict came from a host's installed platform, so a tree could pass on one host and fail on another. A workflow that runs the engine from the checkout fixes that, but it must be generated from the contract, not hand-kept, and every host's installed resolver must still read nix-config's contract while the change rolls out.

## Decision

**D1. Two steps.** As ADR-project-contract-010 D5, this change adds the `conformance_workflow` kind, its renderer, the committed workflow, a suite member that renders and compares it, and an interim `ci` check that judges the workflow against the same renderer, so a hand edit turns `Conformance` red and names the workflow. A follow-up, #1602, declares the entry in nix-config's contract once every host runs this platform, and `write-projections` writes the workflow from then on. An installed resolver refuses an unknown projection kind (`contract.projections.invalid_kind`), so declaring the entry now would stop every host that has not switched.

**D2. Member set by kind.** A projection's members depend on its kind: `generated_file` and `managed_import` keep `id, agent, kind, target, source`; `conformance_workflow` has exactly `id, kind, target`, because no agent reads it and its source is the contract itself. A contract declares at most one such entry (one check, one name, one generated workflow). The resolver supports the kind end to end now (validate, render, check, write), so the follow-up is a contract-only change.

**D3. What the workflow runs.** The rendered workflow runs the platform package of the checkout it runs on, `nix shell .#agent-platform --command conformance run --purpose ci`, with no `--repo-root`, on `pull_request` and on `push` to the contract's `bindings.vcs.integration_branch`, with `contents: read`. The package launcher sets `AGENT_PLATFORM_ROOT`, so no lock and no home configuration is read. The locked form for other projects arrives with adoption's lock entry. The branch is written as a double-quoted YAML string, so a name such as `null` or `123` stays a string, and an integration branch that is not a plain ref token (`^[A-Za-z0-9][A-Za-z0-9._/-]*$`) is refused. The entry may name only the target `.github/workflows/conformance.yaml`: the kind has no source, so the resolver's source-collision rule cannot keep it off `.agents/project.json` or an authored file, and the fixed target does.

**D4. A red `ci` run exits 1.** A `ci` run whose outcome is not `passed` prints its report and exits 1. `workflow_entry` keeps 2, every other purpose keeps 0, and refusals keep 2.

**D5. The two lints are verification checks.** The context-map lint and the standards lint are `verification`-domain checks, so `ci` and `doctor` select them and the `adoption` and `fleet` verdicts of other projects do not move. Both run in process, so stdout carries the JSON report, and start no process. A contract `context-map-lint` command replaces the built-in map lint, but the engine never executes a repository-authored command: every child it starts must be read-only and bounded, and `doctor`, including `doctor --offline`, leaves the tree untouched. A declared override therefore makes the map check a `warning` (`context_map_lint_delegated`, which never moves the outcome), and the repository's own CI runs its command. Expected input-read failures (invalid UTF-8, an unreadable file) and a map resolving outside the root are findings of the lint check, never the engine's exit-2 refusal. Facts carry only bounded repo-relative labels, a count and the reason code, never a raw diagnostic.

**D6. The interim check retires with the declaration.** `verification.conformance_workflow.fresh` judges `.github/workflows/conformance.yaml` only when the file exists; an absent file passes, and the job-shape suite member fails then. Follow-up #1602 retires the check together with declaring the entry, after which `repository.projection.fresh` judges the workflow like any other projection.

**D7. Map selection follows the skills.** The context-map check selects the map as `grill-with-docs` and `doc-grounded-questions` do: the authored `paths.context` entries whose basename is exactly `CONTEXT-MAP.md`. None means no lint, so an area `CONTEXT.md` listed beside the map is never linted as a map; several is a `failed` `context_map_ambiguous` finding; one is linted.

## Consequences

- An installed resolver older than this change refuses a contract that declares the kind until its host switches; that is why #1602 waits.
- `doctor` on another project now also reports the two lints, and a project declaring `context-map-lint` sees a delegated warning, never a run of its command.
- `Conformance` is a new status context but not yet a required one; making it required is #1457.
- The standards lint's cited-id check reaches CI when #1442 lands inside `standards_lint.lint`.
- Rejected: declaring the entry in this change, because an installed older resolver would refuse the contract.
- Rejected: running a repository-authored `context-map-lint` command from the engine, because a check run must not execute code the tree supplies.
