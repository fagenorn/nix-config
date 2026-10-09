# Deepening

How to deepen a cluster of shallow modules safely, given its dependencies. Uses the vocabulary in [SKILL.md](SKILL.md).

## Dependency categories

Classify the candidate's dependencies; the category decides how the deepened module is tested across its seam.

1. **In-process**: pure computation and in-memory state, no I/O. Always deepenable: merge the modules and test through the new interface. No adapter.
2. **Local-substitutable**: dependencies with a local test stand-in (PGLite for Postgres, an in-memory filesystem). Deepenable when the stand-in exists; tests run it. The seam is internal, with no port at the external interface.
3. **Remote but owned (ports & adapters)**: your own services across a network. Define a **port** at the seam; the deep module owns the logic and the transport is an injected **adapter**: in-memory in tests, HTTP/gRPC/queue in production. Recommendation shape: *"Define a port at the seam, implement an HTTP adapter for production and an in-memory adapter for testing, so the logic sits in one deep module even though it's deployed across a network."*
4. **True external (mock)**: third-party services (Stripe, Twilio). The module takes the dependency as an injected port; tests supply a mock adapter.

## Seam discipline

- Introduce a port only when at least two adapters are justified (typically production and test); a single-adapter seam is just indirection.
- Never expose internal seams through the interface because tests use them.

## Testing: replace, don't layer

- Once tests exist at the deepened module's interface, delete the old unit tests on the shallow modules.
- Test observable outcomes through the interface, never internal state; a test that must change when the implementation changes is testing past the interface.
