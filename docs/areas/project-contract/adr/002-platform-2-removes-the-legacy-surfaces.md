# ADR-project-contract-002 — Platform 2.0.0 removes the five deprecated surfaces

- **Status:** accepted
- **Decided in:** issue 579, issue 580

## Context

Platform 1.1.0 and 1.2.0 deprecated five surfaces, each with a successor, so that a project could move before the major bump. The 2.0.0 manifest had to say what was gone without erasing what the project was told to leave.

## Decision

Platform 2.0.0 declares `deprecations: []` and carries the five entries of 1.1.0 and 1.2.0 as `removals`, byte-identical to the entries main declared:

- `legacy-skills-config`: `project_file`, `.claude/skills.config.json`, successor `resolve-project resolve`.
- `legacy-skills-config-writer`: `platform_behavior`, the `adopt-project` legacy binding config rewrite, successor `resolve-project resolve`.
- `bindings-deploy`: `project_schema`, subject `1`, successor `release profile activation`.
- `release-deploy-inspect`: `platform_behavior`, `release deploy inspect`, successor `release profile activation`.
- `release-bridge-planning`: `platform_behavior`, the `adopt-project` `release_bridge` legacy deploy planning, successor release profiles in `.agents/project.json`.

None of the five keeps a code path. A deprecation begins only in a minor, so a removal is never the first announcement of a surface. The one migration kept is `bindings-deploy.retire`, from schema 1 to 2.

## Consequences

- `.claude/skills.config.json` is no longer read or written, project schema 1 is refused as `unsupported_schema`, `release deploy inspect` is no `release` subcommand and `release_bridge` is not a module.
- `removed_uses` still reports a project that holds a removed file or schema, so a project learns what to migrate.
