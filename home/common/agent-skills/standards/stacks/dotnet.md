<!--
Layer 1 — stack shard. Project-independent .NET idioms and traps: true for any
project on this stack, so nothing here may name a repo, a service, or a folder.
Loaded only when the diff touches *.cs / *.csproj / *.slnx. Every entry is
version-stamped, because a framework trap that got fixed is a trap no longer.
The data-access traps are in dotnet-data.md and the AI-framework traps in
dotnet-ai.md.
-->

# .NET

### NET1. Concurrency primitives (.NET 8+)

- **`ConcurrentDictionary.GetOrAdd` may run the factory more than once** under contention. One value is published; the losers' values are silently discarded — fatal when the factory allocates a resource (a semaphore, a socket, a client). Wrap the value in `Lazy<T>` with `LazyThreadSafetyMode.ExecutionAndPublication` so the factory runs at most once per key.
- **`_x ??= Build()` is not atomic.** Racing with itself it calls `Build` twice and leaks the loser. Use the same `Lazy<T>` mode, or `Interlocked.CompareExchange`.
- **Publishing a snapshot atomically requires a single reference write.** Three sequential field writes are not atomic and a concurrent reader can observe a partial snapshot. Bundle the state into one immutable `record` and swap the reference with `Volatile.Write`; readers use `Volatile.Read`.
- **`PeriodicTimer.WaitForNextTickAsync` cannot overlap** — calling it again before the previous task completes throws `InvalidOperationException`. Hoist the task outside the loop and advance it only after a tick wins the race.

### NET2. Async (.NET 8+)

`Task`/`ValueTask` with a `CancellationToken` on every I/O path; `IAsyncEnumerable<T>` for streams. Never `.Result`, `.Wait()` or `.GetAwaiter().GetResult()` in a production path, and never `Task.Run` to fake async over a sync method. `async void` only in event handlers — everywhere else the caller cannot await it and the exception escapes to the finalizer.

- Reach for the streaming primitive rather than a poll loop: `Channel<T>` for in-process producer/consumer fan-in, `Results.Stream(...)` for SSE, gRPC server streaming across processes.
- **Adding an optional parameter *before* `CancellationToken ct = default` breaks every positional `, ct)` call site.** Migrate those call sites to named `ct: ct` in the same change.

### NET3. Errors and dispatch (.NET 8+)

- Catch the specific exception type. `catch (Exception)` "to be safe" hides the diagnosis; let unknowns propagate.
- Closed-set dispatch ends in a throwing arm: `_ => throw new InvalidOperationException(...)` in a `switch` expression, or `ArgumentException` when the discriminator came from request input. Don't extend this to open input domains — an HTTP method string off the wire is not a closed set.
- **Adding a discriminator to a shared exception type means auditing every existing `catch` of it.** A new `bool`, enum or subtype reaches handlers whose recovery is *wrong* for the new class. Grep both `catch (<Type>` and `is <Type>` — a handler that catches a base type and discriminates inside a `when` filter matches only the second — then give each site an explicit filter or a more specific clause ordered ahead of it.

### NET4. Logging and telemetry (Microsoft.Extensions.Logging 8+, OpenTelemetry 1.x)

- Every type that can fail takes `ILogger<T>` by constructor injection. There is no "small enough to skip the logger" exception.
- `Console.WriteLine`, `Console.Error.WriteLine`, `Debug.WriteLine` and `Trace.WriteLine` never appear in production code, not even as a temporary probe.
- Log messages are structured templates with named placeholders (`"Agent {NodeId} failed for run {RunId}"`), never interpolated strings — interpolation destroys the structured field at the sink.
- Set `ActivityStatusCode.Error` with a message before throwing; that is how OTel backends filter failed spans. `IChatClient.UseOpenTelemetry()` already emits model, latency and token spans — don't double-instrument them.

### NET5. Testing (xUnit v3, RichardSzalay.MockHttp 7.x)

- **Never pass `default` for a `CancellationToken` in an async test.** The xUnit v3 analyzer raises `xUnit1051` and a `-warnaserror` build fails. Use `TestContext.Current.CancellationToken` so the token honours the per-test timeout. It does not exist under xUnit v2 (nor does the analyzer fire there) — `CancellationToken.None` is the v2 form.
- **`MockHttpMessageHandler.VerifyNoOutstandingExpectation()` is not a call-count assertion.** It proves every registered `Expect` was *met*; it never fails because of an *extra* call. On a bare handler the extra call at least throws `MockHttpMatchException` — as an opaque transport error, not the claim the test meant to make — and as soon as the handler has a `When(...)` backend or a `Fallback`, the extra call is served silently and nothing fails. When the count *is* the contract (a fail-fast path that must not retry), register with `When(...)` plus a counting `Respond` callback and assert the count.
- Register test doubles into a test host with the register-if-absent idiom (`if (!services.Any(d => d.ServiceType == typeof(T))) services.AddSingleton(stub)`), so a changed production registration doesn't collide.
- `NullLogger<T>.Instance` for `ILogger<T>` — don't mock the logger.

### NET11. Types and values

`DateTimeOffset.UtcNow`, never `DateTime.Now`. `long` for money in minor units and for token counts. Named constants, not magic numbers. `sealed` on leaf types; `record` for immutable transport types; file-scoped namespaces; primary constructors on DI-injected types; collection expressions (`[]`, `[..items]`) for small literals; `required` members for invariants; raw string literals for embedded JSON, YAML or multi-line text; `nameof()` over string literals for member references; pattern matching over chained null checks — where each reduces noise, not as ceremony.
