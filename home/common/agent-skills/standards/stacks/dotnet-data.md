<!--
Layer 1 — stack shard, the data-access part (EF Core, raw SQL on Postgres, System.Text.Json) of the .NET stack. Project-independent .NET idioms
and traps: true for any project on this stack, so nothing here may name a repo,
a service, or a folder. Loaded with dotnet.md only when the project file that
governs a changed path, or a build file it inherits, references a
Microsoft.EntityFrameworkCore or Npgsql package. Every entry is
version-stamped, because a framework trap that got fixed is a trap no longer.
-->

# .NET data access and serialization

### NET6. EF Core (9.x–10.x)

- **EF InMemory does not change-track entities materialised through a LINQ `join` projection** (`select new { Entity = c }`): a write-back plus `SaveChanges` silently no-ops, so a test that mutates then re-reads in one context sees the stale value. Real providers track it, so the gap bites only in tests. Load rows you intend to mutate directly off the tracked `DbSet`, resolving cross-table filters via a separate id-list query.
- **Long-lived `DbContext` captured by a singleton is a bug.** A singleton that needs data resolves a scope through `IServiceScopeFactory`.
- Prefer the mapping primitives — `OwnsOne`, `IsRowVersion`, `HasQueryFilter`, projected `Select` — over raw SQL or `DbContext` gymnastics. String-concatenated SQL or `LIKE` filters built from user input are never acceptable; parameterize.
- **Owned types load with their parent.** Never `Include` an `OwnsOne`-mapped property — it won't compile and isn't needed.
- **`ApplyConfigurationsFromAssembly` only finds configurations in that assembly.** A third-party entity you pull into your `DbContext` therefore keeps EF's default CLR-type table name. If your schema has a naming convention, write an `IEntityTypeConfiguration<T>` for the foreign entity too.
- **EF Core 10 + Npgsql 10: the change detector cannot tell that a `jsonb` round-trip is a no-op.** Postgres normalises `jsonb` on write — whitespace dropped, keys reordered, duplicates collapsed — so the text read back is never byte-identical to what the serializer produced. Any "recompute the desired state, assign it, let EF diff it" reconciler over a `jsonb` column therefore marks it modified on *every* pass and issues an UPDATE that changes nothing but the row version. Compare semantically (`JsonNode.DeepEquals`) and clear `PropertyEntry.IsModified` before saving; pin the idempotency by asserting the concurrency token is unchanged across a second pass.
- **Disprove a provider limitation on the current version before coding a split around it** (`IsRelational()`, `ProviderName != "…InMemory"`). EF Core 10's InMemory provider *does* evaluate owned-JSON member access inside a `Where`/`CountAsync` predicate, and Npgsql translates the same predicate to a server-side `jsonb` filter — so that shape needs no split on either provider. A stale provider-split comment costs more than no comment: it silently widens or narrows a predicate and reads as a deliberate constraint, so the next reader extends the workaround instead of testing it.

### NET7. Raw SQL on Postgres (EF Core 10 + Npgsql 10)

`db.Database.SqlQuery<T>(...)` is the escape hatch for aggregation LINQ can't express (`percentile_cont`, `date_trunc` GROUP BY). Three traps that EF InMemory hides, so verify against a real Postgres container:

- **NULL parameter type inference (`42P18: could not determine data type of parameter`).** Postgres rejects a prepared statement whose `null` parameter has no inferable type. Cast the *parameter hole*, not the column: `({nullableUuid}::uuid IS NULL OR t.business_id = {nullableUuid})`.
- **Column-name casing.** Result columns map to record properties by name, but Postgres lowercases unquoted identifiers, so `AS PausedHitl` arrives as `pausedhitl` and materialisation fails with "the required column … was not present". Quote PascalCase aliases: `AS "PausedHitl"`.
- **Implicit-transaction lifetime.** `SqlQuery<T>(...).ToListAsync()` runs inside Npgsql's implicit single-statement transaction, which commits the moment the result is read. Harmless for a plain SELECT, fatal for a statement with transaction-scoped side effects — `pg_try_advisory_xact_lock(...)`, deferred-constraint setup, `LOCK TABLE` — because the effect is released before any caller-side code depending on it runs. Wrap the call in an explicit `BeginTransactionAsync` + `CommitAsync`.

### NET8. System.Text.Json (.NET 10)

- A `JsonElement` borrowed from a `JsonDocument` is invalid once that document is disposed. `.Clone()` before the element escapes the `using`.
- Register enum converters with an explicit naming policy. A bare `new JsonStringEnumConverter()` emits PascalCase and forces every schema on the far side of the wire to compensate locally. Calling `.ToString()` on an enum before it lands in a payload bypasses the converter entirely — lift the destination field to the enum type instead.
- **The MCP C# SDK (ModelContextProtocol 1.2) serialises `UseStructuredContent` tool results through its own options and ignores type-level `[JsonConverter]` attributes.** An enum-typed result field emits the CLR name regardless of the attribute. Type MCP result-record fields as `string` and apply the casing explicitly at the producer.
