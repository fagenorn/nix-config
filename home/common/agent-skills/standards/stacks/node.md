<!--
Layer 1 — stack shard. Project-independent Node/ESM idioms and traps: true for
any project on this runtime, so nothing here may name a repo or a module.
Loaded only when the diff touches *.js / *.mjs / package.json, or *.ts in a
Node (non-browser) project. Version-stamped. Seed set — E4 harvests the rest.
-->

# Node (ESM)

### ESM only (Node 20+)

`"type": "module"`, `import`/`export`, never `require`. Plain `.mjs` survives only in leaf glue — a spawned supervisor script, a fixture. Anything non-trivial is TypeScript.

### Keep the domain core runtime-agnostic

The core imports Node builtins and nothing else — no framework SDK, no plugin host, no schema runtime — so it runs under plain `node --test` with no loader and no harness. Only the entry point touches the host API. This is what keeps the test loop fast enough to be a real feedback loop.

### Public API through a barrel; internals import each other directly

A core directory exposes one `index.ts` that only re-exports. Consumers outside the directory import the barrel and nothing else, so internals can move freely; modules inside import each other directly, never through the barrel, or you get cycles. Un-exported is internal by definition.

### Test isolation rides on process-per-file (Node test runner, Vitest)

Each test file is a fresh process, so a module that memoizes state at import — a database handle, a cached client — is re-imported clean per file but shared across every test *within* a file. Set the environment the module reads before the first import in that file, and keep a file's fixtures self-contained. Two files can safely differ; two tests in one file cannot.

### Prefer the standard library and CLIs to new dependencies

Node's stdlib plus a shell command covers most of what a small dependency would; every added package is supply chain, lockfile churn and a version to keep current. Reach for a dependency when it clearly earns its place. System tools belong in the environment definition, never installed globally on the host.
