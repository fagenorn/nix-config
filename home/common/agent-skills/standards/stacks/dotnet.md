<!--
Layer 1 — stack shard. Project-independent .NET idioms and traps: true for any
project on this stack, so nothing here may name a repo, a service, or a folder.
Loaded only when the diff touches *.cs / *.csproj / *.slnx. Every entry is
version-stamped, because a framework trap that got fixed is a trap no longer.
Seed set — E4 harvests the full trap library out of the project standards docs.
-->

# .NET

### Concurrency primitives (.NET 8+)

- **`ConcurrentDictionary.GetOrAdd` may run the factory more than once** under contention. One value is published; the losers' values are silently discarded — fatal when the factory allocates a resource (a semaphore, a socket, a client). Wrap the value in `Lazy<T>` with `LazyThreadSafetyMode.ExecutionAndPublication` so the factory runs at most once per key.
- **`_x ??= Build()` is not atomic.** Racing with itself it calls `Build` twice and leaks the loser. Use the same `Lazy<T>` mode, or `Interlocked.CompareExchange`.
- **Publishing a snapshot atomically requires a single reference write.** Three sequential field writes are not atomic and a concurrent reader can observe a partial snapshot. Bundle the state into one immutable `record` and swap the reference with `Volatile.Write`; readers use `Volatile.Read`.
- **`PeriodicTimer.WaitForNextTickAsync` cannot overlap** — calling it again before the previous task completes throws `InvalidOperationException`. Hoist the task outside the loop and advance it only after a tick wins the race.

### Async (.NET 8+)

`Task`/`ValueTask` with a `CancellationToken` on every I/O path; `IAsyncEnumerable<T>` for streams. Never `.Result`, `.Wait()` or `.GetAwaiter().GetResult()` in a production path, and never `Task.Run` to fake async over a sync method. `async void` only in event handlers — everywhere else the caller cannot await it and the exception escapes to the finalizer.

### EF Core (9.x)

- **EF InMemory does not change-track entities materialised through a LINQ `join` projection** (`select new { Entity = c }`): a write-back plus `SaveChanges` silently no-ops, so a test that mutates then re-reads in one context sees the stale value. Real providers track it, so the gap bites only in tests. Load rows you intend to mutate directly off the tracked `DbSet`, resolving cross-table filters via a separate id-list query.
- **Long-lived `DbContext` captured by a singleton is a bug.** A singleton that needs data resolves a scope through `IServiceScopeFactory`.
- Prefer the mapping primitives — `OwnsOne`, `IsRowVersion`, `HasQueryFilter`, projected `Select` — over raw SQL or `DbContext` gymnastics. String-concatenated SQL or `LIKE` filters built from user input are never acceptable; parameterize.

### Framework seams (Microsoft.Extensions.AI 9.x, Microsoft.Agents.AI.Workflows)

**When a framework class stops behaving as expected, read its base class's constructor parameters and defaults before building a mechanism around the symptom.** A base-class default can silently change what an override is handed, with no error and no log, so the subclass looks correct in isolation and the evidence points anywhere but the constructor. Build the `IChatClient` pipeline out of the provided builders (`UseOpenTelemetry`, `UseLogging`, `UseFunctionInvocation`) rather than calling provider SDKs directly.

### Types and values

`DateTimeOffset.UtcNow`, never `DateTime.Now`. `long` for money in minor units and for token counts. Named constants, not magic numbers. `sealed` on leaf types; `record` for immutable transport types; file-scoped namespaces; pattern matching over chained null checks — where each reduces noise, not as ceremony.
