<!--
Layer 1 — stack shard, the AI-framework part (Microsoft.Agents.AI, Microsoft.Extensions.AI) of the .NET stack. Project-independent .NET idioms
and traps: true for any project on this stack, so nothing here may name a repo,
a service, or a folder. Loaded with dotnet.md only when the project file that
governs a changed path, or a build file it inherits, references a
Microsoft.Agents.AI or Microsoft.Extensions.AI package. Every entry is
version-stamped, because a framework trap that got fixed is a trap no longer.
-->

# .NET AI framework seams

### NET9. Framework seams (Microsoft.Agents.AI 1.11, Microsoft.Extensions.AI 10.x)

**When a framework class stops behaving as expected, read its base class's constructor parameters and defaults before building a mechanism around the symptom.** A base-class default can silently change what an override is handed, with no error and no log, so the subclass looks correct in isolation and the evidence points anywhere but the constructor. Build the `IChatClient` pipeline out of the provided builders (`UseOpenTelemetry`, `UseLogging`, `UseFunctionInvocation`) rather than calling provider SDKs directly.

- The canonical instance: `AIContextProvider`'s `provideInputMessageFilter` defaults to *`External`-sourced messages only*, so session-held chat history never reaches `ProvideAIContextAsync` until you pass the filter explicitly. One constructor argument; no symptom points at it.
- **Decorator override surface.** `ChatClientAgent.RunCoreAsync` invokes `GetStreamingResponseAsync` exclusively — a `DelegatingChatClient` that inspects responses must override **both** `GetResponseAsync` and `GetStreamingResponseAsync` or it silently no-ops on every agent invocation. When subclassing `AIAgent`, override the protected `RunCoreAsync` / `RunCoreStreamingAsync` hooks, not the public `RunAsync` / `RunStreamingAsync`.
- **Workflows have the primitive already.** `Workflow.BindAsExecutor(id, ExecutorOptions?)` wraps a child workflow as a typed executor binding and emits `SubworkflowErrorEvent` / `SubworkflowWarningEvent` on failure — don't hand-roll an executor that drains a streaming run inside a parent superstep. Human-in-the-loop is `RequestInfoEvent` on the parent stream plus `request.CreateResponse(...)` and `handle.SendResponseAsync(...)`. Grep the package's XML doc for the noun before building anything: `~/.nuget/packages/<package>/<version>/lib/net*/<Package>.xml`.
- **An inner executor exception arrives as `ExecutorFailedEvent` on the stream, not as a throw.** Every consumer of the watch stream must log it *and* mark the run failed, or a child failure leaves the run's terminal status `Completed`.
- **Type-boundary edges hang silently.** Agent nodes speak `ChatMessage` / `TurnToken`; typed executors speak POCOs. Wire one straight to the other and nothing throws — the agent never receives a `TurnToken` so it stops mid-turn, or the typed executor never sees a message it recognises and no handler fires. Insert an adapter executor on the boundary edge and emit `new TurnToken(emitEvents: true)` from it.

### NET10. `FunctionInvokingChatClient` (Microsoft.Extensions.AI 10.5–10.6)

- `MaximumIterationsPerRequest` defaults to **40**. At the limit the framework silently strips the tools and issues one tool-less wrap-up turn that returns an ordinary `ChatResponse` — no exception, no distinguishing `FinishReason`. A run that hits the cap reads as clean success while the agent never finished the task.
- `FunctionInvocationContext.Iteration` is **0-indexed** for the invoker callback (the loop is `for (int iteration = 0; ; iteration++)`); the XML doc saying "iteration 1" is wrong. A guard testing `>= MaximumIterationsPerRequest` is unreachable — the last invoker-reachable iteration is `cap - 1`.
- `FunctionInvoker` is **null by default**; dispatch is `FunctionInvoker is { } invoker ? invoker(ctx, ct) : ctx.Function.InvokeAsync(ctx.Arguments, ct)`. A wrapper that replaces the delegate must reproduce the null fallback itself.
- **Exceptions do not cross this boundary.** Throws from `FunctionInvoker` are absorbed by `MaximumConsecutiveErrorsPerRequest` (default 3) into `FunctionResultContent` error messages, and setting it to 0 propagates the throw at the cost of every legitimate tool-error retry. Worse, `AIFunction.InvokeAsync` exceptions — `OperationCanceledException` subclasses included — are caught under `when (captureExceptions && !cancellationToken.IsCancellationRequested)` where the token is the *caller's*, so a tool that throws carrying its own cancelled token is still swallowed while the caller's token is live. Typed-exception propagation therefore cannot be made to work here: signal out of band with `ctx.Terminate = true` plus a recorder the caller reads after the call returns.
- **AsyncLocal survives the dispatch only when the slot holds a stable reference.** Re-assigning the slot deeper in the chain (`_current.Value = newContext`) never reaches the parent; setting the slot once to a mutable object and having deep callbacks mutate that object's fields does, and the parent reads the mutation after the await chain returns. Build side-channels the second way.
