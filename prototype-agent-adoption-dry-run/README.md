# PROTOTYPE — nix-config adoption dry run

This throwaway prototype answers one question:

> Does a read-only `reconcile` dry run against nix-config require any contract
> binding, capability, or agent-development artifact class that the approved
> project-system decisions do not already name?

It inventories tracked agent-development surfaces, explicit targeted ignored
paths, current worktree facts, and relevant dirty paths. It then renders the
proposed `.agents/project.json`, candidate classifications, material-question
frontier, operations, verification, handoff, and gap verdict. It never writes
to the inspected repository.

Run the interactive view against the real checkout:

```sh
just prototype-agent-adoption-dry-run /Users/anis/tmp/nix-config
```

Use `--dump-json` for the strict seven-member machine view:

```sh
just prototype-agent-adoption-dry-run /Users/anis/tmp/nix-config --dump-json
```

The safety boundary is deliberately narrow:

- tracked evidence comes from Git index metadata;
- only known agent-development ignored paths are enumerated;
- `.superpowers/**` and worktree contents are metadata-only runtime evidence;
- only explicitly safe config/artifact inputs may be hashed;
- secret-shaped paths and arbitrary ignored trees are never read.

The code and this worktree are disposable. The eventual answer belongs in
issue #79 and the wayfinder map, not in this prototype branch.
