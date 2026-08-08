<!--
Layer 1 — stack shard. Project-independent TypeScript/React idioms and traps:
true for any project on this stack, so nothing here may name a repo, a route,
or a component. Loaded only when the diff touches *.ts / *.tsx. Every entry is
version-stamped. Seed set — E4 harvests the full trap library later.
-->

# TypeScript + React

### `vi.mock` must spread `importOriginal` (Vitest 1.x–3.x)

The destructive form `vi.mock('mod', () => ({ X: stub }))` silently drops every other export. It passes today because the file under test imports only `X`, and breaks confusingly the moment a future change imports something else. Use:

```ts
vi.mock('some-module', async (importOriginal) => {
  const actual = await importOriginal<typeof import('some-module')>()
  return { ...actual, X: stub }
})
```

**Escape hatch for genuine full replacement:** declare `void importOriginal` in the factory body without calling it. Required when the mocked module also exports a `vi.hoisted` spy — spreading the real namespace re-introduces the live binding and shadows the spy.

### Route guards belong in the router, not an effect (TanStack Router 1.x)

Auth and redirect guards run in the route's `beforeLoad` and `throw redirect(...)`. An effect keyed on the location re-fires while the redirect target lazy-loads its code-split chunk — the router updates location state eagerly at navigation start while the old match stays mounted until commit — so each render wraps the current URL in another `?redirect=` layer. The failure is production-only, because dev chunks resolve instantly, and it terminates in a URL long enough for the proxy to reject with 414.

### Read typed search params through the route API

Take the route handle once at module scope (`const route = getRouteApi('/path')`) and call `route.useSearch()` inside the component, rather than passing the route id as a string literal to a bare `useSearch({ from })` at every call site. The handle survives a route move; the literals do not. Tests stub the route handle, not the hook.

### `assertUnreachable` at every closed-set dispatch

Exhaustive `switch` over a union ends in a default that takes the value as `never` and throws. This is the Layer-0 fail-loud rule with a compiler attached: the type error appears the moment a variant is added, and the throw catches whatever reached runtime anyway.

### Zod: `.optional()` alone still admits the empty string (zod 3.x)

`z.string().optional()` accepts `""`, which is almost never what a form means. Write `z.string().min(1).optional()` for "absent or meaningful". The same applies to `.nullish()`.
