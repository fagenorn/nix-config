<!--
Layer 1 — stack shard. Project-independent .NET idioms and traps: true for any
project on this stack, so nothing here may name a repo, a service, or a folder.
Loaded only when the diff touches *.cs / *.csproj / *.slnx. Every entry is
version-stamped, because a framework trap that got fixed is a trap no longer.
-->

# .NET

### Concurrency primitives (.NET 8+)

- **`ConcurrentDictionary.GetOrAdd` may run the factory more than once** under contention. One value is published; the losers' values are silently discarded — fatal when the factory allocates a resource (a semaphore, a socket, a client). Wrap the value in `Lazy<T>` with `LazyThreadSafetyMode.ExecutionAndPublication` so the factory runs at most once per key.
- **`_x ??= Build()` is not atomic.** Racing with itself it calls `Build` twice and leaks the loser. Use the same `Lazy<T>` mode, or `Interlocked.CompareExchange`.
- **Publishing a snapshot atomically requires a single reference write.** Three sequential field writes are not atomic and a concurrent reader can observe a partial snapshot. Bundle the state into one immutable `record` and swap the reference with `Volatile.Write`; readers use `Volatile.Read`.
- **`PeriodicTimer.WaitForNextTickAsync` cannot overlap** — calling it again before the previous task completes throws `InvalidOperationException`. Hoist the task outside the loop and advance it only after a tick wins the race.

### Async (.NET 8+)

`Task`/`ValueTask` with a `CancellationToken` on every I/O path; `IAsyncEnumerable<T>` for streams. Never `.Result`, `.Wait()` or `.GetAwaiter().GetResult()` in a production path, and never `Task.Run` to fake async over a sync method. `async void` only in event handlers — everywhere else the caller cannot await it and the exception escapes to the finalizer.

- Reach for the streaming primitive rather than a poll loop: `Channel<T>` for in-process producer/consumer fan-in, `Results.Stream(...)` for SSE, gRPC server streaming across processes.
- **Adding an optional parameter *before* `CancellationToken ct = default` breaks every positional `, ct)` call site.** Migrate those call sites to named `ct: ct` in the same change.

### Errors and dispatch (.NET 8+)

- Catch the specific exception type. `catch (Exception)` "to be safe" hides the diagnosis; let unknowns propagate.
- Closed-set dispatch ends in a throwing arm: `_ => throw new InvalidOperationException(...)` in a `switch` expression, or `ArgumentException` when the discriminator came from request input. Don't extend this to open input domains — an HTTP method string off the wire is not a closed set.
- **Adding a discriminator to a shared exception type means auditing every existing `catch` of it.** A new `bool`, enum or subtype reaches handlers whose recovery is *wrong* for the new class. Grep both `catch (<Type>` and `is <Type>` — a handler that catches a base type and discriminates inside a `when` filter matches only the second — then give each site an explicit filter or a more specific clause ordered ahead of it.

### Logging and telemetry (Microsoft.Extensions.Logging 8+, OpenTelemetry 1.x)

- Every type that can fail takes `ILogger<T>` by constructor injection. There is no "small enough to skip the logger" exception.
- `Console.WriteLine`, `Console.Error.WriteLine`, `Debug.WriteLine` and `Trace.WriteLine` never appear in production code, not even as a temporary probe.
- Log messages are structured templates with named placeholders (`"Agent {NodeId} failed for run {RunId}"`), never interpolated strings — interpolation destroys the structured field at the sink.
- Set `ActivityStatusCode.Error` with a message before throwing; that is how OTel backends filter failed spans. `IChatClient.UseOpenTelemetry()` already emits model, latency and token spans — don't double-instrument them.

### Testing (xUnit v3, RichardSzalay.MockHttp 7.x)

- **Never pass `default` for a `CancellationToken` in an async test.** The xUnit v3 analyzer raises `xUnit1051` and a `-warnaserror` build fails. Use `TestContext.Current.CancellationToken` so the token honours the per-test timeout. It does not exist under xUnit v2 (nor does the analyzer fire there) — `CancellationToken.None` is the v2 form.
- **`MockHttpMessageHandler.VerifyNoOutstandingExpectation()` is not a call-count assertion.** It proves every registered `Expect` was *met*; it never fails because of an *extra* call. On a bare handler the extra call at least throws `MockHttpMatchException` — as an opaque transport error, not the claim the test meant to make — and as soon as the handler has a `When(...)` backend or a `Fallback`, the extra call is served silently and nothing fails. When the count *is* the contract (a fail-fast path that must not retry), register with `When(...)` plus a counting `Respond` callback and assert the count.
- Register test doubles into a test host with the register-if-absent idiom (`if (!services.Any(d => d.ServiceType == typeof(T))) services.AddSingleton(stub)`), so a changed production registration doesn't collide.
- `NullLogger<T>.Instance` for `ILogger<T>` — don't mock the logger.

### EF Core (9.x–10.x)

- **EF InMemory does not change-track entities materialised through a LINQ `join` projection** (`select new { Entity = c }`): a write-back plus `SaveChanges` silently no-ops, so a test that mutates then re-reads in one context sees the stale value. Real providers track it, so the gap bites only in tests. Load rows you intend to mutate directly off the tracked `DbSet`, resolving cross-table filters via a separate id-list query.
- **Long-lived `DbContext` captured by a singleton is a bug.** A singleton that needs data resolves a scope through `IServiceScopeFactory`.
- Prefer the mapping primitives — `OwnsOne`, `IsRowVersion`, `HasQueryFilter`, projected `Select` — over raw SQL or `DbContext` gymnastics. String-concatenated SQL or `LIKE` filters built from user input are never acceptable; parameterize.
- **Owned types load with their parent.** Never `Include` an `OwnsOne`-mapped property — it won't compile and isn't needed.
- **`ApplyConfigurationsFromAssembly` only finds configurations in that assembly.** A third-party entity you pull into your `DbContext` therefore keeps EF's default CLR-type table name. If your schema has a naming convention, write an `IEntityTypeConfiguration<T>` for the foreign entity too.
- **EF Core 10 + Npgsql 10: the change detector cannot tell that a `jsonb` round-trip is a no-op.** Postgres normalises `jsonb` on write — whitespace dropped, keys reordered, duplicates collapsed — so the text read back is never byte-identical to what the serializer produced. Any "recompute the desired state, assign it, let EF diff it" reconciler over a `jsonb` column therefore marks it modified on *every* pass and issues an UPDATE that changes nothing but the row version. Compare semantically (`JsonNode.DeepEquals`) and clear `PropertyEntry.IsModified` before saving; pin the idempotency by asserting the concurrency token is unchanged across a second pass.
- **Disprove a provider limitation on the current version before coding a split around it** (`IsRelational()`, `ProviderName != "…InMemory"`). EF Core 10's InMemory provider *does* evaluate owned-JSON member access inside a `Where`/`CountAsync` predicate, and Npgsql translates the same predicate to a server-side `jsonb` filter — so that shape needs no split on either provider. A stale provider-split comment costs more than no comment: it silently widens or narrows a predicate and reads as a deliberate constraint, so the next reader extends the workaround instead of testing it.

### Raw SQL on Postgres (EF Core 10 + Npgsql 10)

`db.Database.SqlQuery<T>(...)` is the escape hatch for aggregation LINQ can't express (`percentile_cont`, `date_trunc` GROUP BY). Three traps that EF InMemory hides, so verify against a real Postgres container:

- **NULL parameter type inference (`42P18: could not determine data type of parameter`).** Postgres rejects a prepared statement whose `null` parameter has no inferable type. Cast the *parameter hole*, not the column: `({nullableUuid}::uuid IS NULL OR t.business_id = {nullableUuid})`.
- **Column-name casing.** Result columns map to record properties by name, but Postgres lowercases unquoted identifiers, so `AS PausedHitl` arrives as `pausedhitl` and materialisation fails with "the required column … was not present". Quote PascalCase aliases: `AS "PausedHitl"`.
- **Implicit-transaction lifetime.** `SqlQuery<T>(...).ToListAsync()` runs inside Npgsql's implicit single-statement transaction, which commits the moment the result is read. Harmless for a plain SELECT, fatal for a statement with transaction-scoped side effects — `pg_try_advisory_xact_lock(...)`, deferred-constraint setup, `LOCK TABLE` — because the effect is released before any caller-side code depending on it runs. Wrap the call in an explicit `BeginTransactionAsync` + `CommitAsync`.

### System.Text.Json (.NET 10)

- A `JsonElement` borrowed from a `JsonDocument` is invalid once that document is disposed. `.Clone()` before the element escapes the `using`.
- Register enum converters with an explicit naming policy. A bare `new JsonStringEnumConverter()` emits PascalCase and forces every schema on the far side of the wire to compensate locally. Calling `.ToString()` on an enum before it lands in a payload bypasses the converter entirely — lift the destination field to the enum type instead.
- **The MCP C# SDK (ModelContextProtocol 1.2) serialises `UseStructuredContent` tool results through its own options and ignores type-level `[JsonConverter]` attributes.** An enum-typed result field emits the CLR name regardless of the attribute. Type MCP result-record fields as `string` and apply the casing explicitly at the producer.

### Framework seams (Microsoft.Agents.AI 1.11, Microsoft.Extensions.AI 10.x)

**When a framework class stops behaving as expected, read its base class's constructor parameters and defaults before building a mechanism around the symptom.** A base-class default can silently change what an override is handed, with no error and no log, so the subclass looks correct in isolation and the evidence points anywhere but the constructor. Build the `IChatClient` pipeline out of the provided builders (`UseOpenTelemetry`, `UseLogging`, `UseFunctionInvocation`) rather than calling provider SDKs directly.

- The canonical instance: `AIContextProvider`'s `provideInputMessageFilter` defaults to *`External`-sourced messages only*, so session-held chat history never reaches `ProvideAIContextAsync` until you pass the filter explicitly. One constructor argument; no symptom points at it.
- **Decorator override surface.** `ChatClientAgent.RunCoreAsync` invokes `GetStreamingResponseAsync` exclusively — a `DelegatingChatClient` that inspects responses must override **both** `GetResponseAsync` and `GetStreamingResponseAsync` or it silently no-ops on every agent invocation. When subclassing `AIAgent`, override the protected `RunCoreAsync` / `RunCoreStreamingAsync` hooks, not the public `RunAsync` / `RunStreamingAsync`.
- **Workflows have the primitive already.** `Workflow.BindAsExecutor(id, ExecutorOptions?)` wraps a child workflow as a typed executor binding and emits `SubworkflowErrorEvent` / `SubworkflowWarningEvent` on failure — don't hand-roll an executor that drains a streaming run inside a parent superstep. Human-in-the-loop is `RequestInfoEvent` on the parent stream plus `request.CreateResponse(...)` and `handle.SendResponseAsync(...)`. Grep the package's XML doc for the noun before building anything: `~/.nuget/packages/<package>/<version>/lib/net*/<Package>.xml`.
- **An inner executor exception arrives as `ExecutorFailedEvent` on the stream, not as a throw.** Every consumer of the watch stream must log it *and* mark the run failed, or a child failure leaves the run's terminal status `Completed`.
- **Type-boundary edges hang silently.** Agent nodes speak `ChatMessage` / `TurnToken`; typed executors speak POCOs. Wire one straight to the other and nothing throws — the agent never receives a `TurnToken` so it stops mid-turn, or the typed executor never sees a message it recognises and no handler fires. Insert an adapter executor on the boundary edge and emit `new TurnToken(emitEvents: true)` from it.

### `FunctionInvokingChatClient` (Microsoft.Extensions.AI 10.5–10.6)

- `MaximumIterationsPerRequest` defaults to **40**. At the limit the framework silently strips the tools and issues one tool-less wrap-up turn that returns an ordinary `ChatResponse` — no exception, no distinguishing `FinishReason`. A run that hits the cap reads as clean success while the agent never finished the task.
- `FunctionInvocationContext.Iteration` is **0-indexed** for the invoker callback (the loop is `for (int iteration = 0; ; iteration++)`); the XML doc saying "iteration 1" is wrong. A guard testing `>= MaximumIterationsPerRequest` is unreachable — the last invoker-reachable iteration is `cap - 1`.
- `FunctionInvoker` is **null by default**; dispatch is `FunctionInvoker is { } invoker ? invoker(ctx, ct) : ctx.Function.InvokeAsync(ctx.Arguments, ct)`. A wrapper that replaces the delegate must reproduce the null fallback itself.
- **Exceptions do not cross this boundary.** Throws from `FunctionInvoker` are absorbed by `MaximumConsecutiveErrorsPerRequest` (default 3) into `FunctionResultContent` error messages, and setting it to 0 propagates the throw at the cost of every legitimate tool-error retry. Worse, `AIFunction.InvokeAsync` exceptions — `OperationCanceledException` subclasses included — are caught under `when (captureExceptions && !cancellationToken.IsCancellationRequested)` where the token is the *caller's*, so a tool that throws carrying its own cancelled token is still swallowed while the caller's token is live. Typed-exception propagation therefore cannot be made to work here: signal out of band with `ctx.Terminate = true` plus a recorder the caller reads after the call returns.
- **AsyncLocal survives the dispatch only when the slot holds a stable reference.** Re-assigning the slot deeper in the chain (`_current.Value = newContext`) never reaches the parent; setting the slot once to a mutable object and having deep callbacks mutate that object's fields does, and the parent reads the mutation after the await chain returns. Build side-channels the second way.

### Types and values

`DateTimeOffset.UtcNow`, never `DateTime.Now`. `long` for money in minor units and for token counts. Named constants, not magic numbers. `sealed` on leaf types; `record` for immutable transport types; file-scoped namespaces; primary constructors on DI-injected types; collection expressions (`[]`, `[..items]`) for small literals; `required` members for invariants; raw string literals for embedded JSON, YAML or multi-line text; `nameof()` over string literals for member references; pattern matching over chained null checks — where each reduces noise, not as ceremony.
