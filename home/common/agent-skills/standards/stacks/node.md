<!--
Layer 1 — stack shard. Project-independent Node/ESM idioms and traps: true for
any project on this runtime, so nothing here may name a repo or a module.
Loaded only when the diff touches *.js / *.mjs / package.json, or *.ts in a
Node (non-browser) project. Version-stamped. Seed set — E4 harvests the rest.
-->

# Node (ESM)

### ESM only (Node 20+)

`"type": "module"`, `import`/`export`, never `require`. Plain `.mjs` survives only in leaf glue — a spawned supervisor script, a fixture. Anything non-trivial is TypeScript.

### No side effects at import or factory time

A module that starts a timer, opens a socket or spawns a watcher when it is imported has no off switch: every consumer pays for it, every test inherits it, and a plugin host that imports a module merely to inspect it is already running your code. Do that work in an explicit lifecycle hook the caller invokes. Background work that must continue with no live caller is a separate process, not an import.

### Keep the domain core runtime-agnostic

The core imports Node builtins and nothing else — no framework SDK, no plugin host, no schema runtime — so it runs under plain `node --test` with no loader and no harness. Only the entry point touches the host API. This is what keeps the test loop fast enough to be a real feedback loop.

### Public API through a barrel; internals import each other directly

A core directory exposes one `index.ts` that only re-exports. Consumers outside the directory import the barrel and nothing else, so internals can move freely; modules inside import each other directly, never through the barrel, or you get cycles. Un-exported is internal by definition.

### A directory per unit, never a filename prefix

`<name>/index.ts` plus its internals, not a flat pile of `<name>-*.ts`. Prefixes read fine for the first unit and stop scaling at the second, while a directory keeps the entry point, the core and any human-facing CLI visibly separate and lets the whole unit move as one.

### Throw at a host boundary; never return an error shape

Plugin and tool protocols surface a *thrown* error to their caller and accept an error-shaped return value as a successful result. Returning `{ error: … }` where the host expects a throw hides the failure from the one place equipped to report it. Same for any callback the host awaits.

### Honour `AbortSignal` on anything long-running

Accept a signal, pass it down, and check it around awaits. Work that cannot be cancelled outlives the request that wanted it, so the caller's timeout guards nothing and the process keeps paying for a result nobody will read.

### Test isolation rides on process-per-file (Node test runner, Vitest)

Each test file is a fresh process, so a module that memoizes state at import — a database handle, a cached client — is re-imported clean per file but shared across every test *within* a file. Set the environment the module reads before the first import in that file, and keep a file's fixtures self-contained. Two files can safely differ; two tests in one file cannot.

### One test file per module or behaviour, named for the behaviour

`projection-empty-archive.test.ts`, never `task-3.test.ts`. A failing file should name the broken area by itself, before anyone opens it — and a file named for a step in a plan is unreadable the moment that plan is done.

### Prefer the standard library and CLIs to new dependencies

Node's stdlib plus a shell command covers most of what a small dependency would; every added package is supply chain, lockfile churn and a version to keep current. Reach for a dependency when it clearly earns its place. Runtime dependencies are declared in the manifest and pinned by the committed lockfile; system tools belong in the environment definition, never installed globally on the host.
