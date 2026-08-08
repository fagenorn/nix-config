<!--
Layer 1 — stack shard. Project-independent Python idioms and traps: true for
any project in this language, so nothing here may name a repo or a module.
Loaded only when the diff touches *.py / pyproject.toml. Version-stamped.
Thinnest of the four shards — neither reference project is Python, so this
carries language-level traps only until E4 harvests real project material.
-->

# Python

### Default arguments are evaluated once, at definition (all versions)

`def f(items=[])` shares one list across every call that omits the argument, and the same holds for `{}`, `set()` and any call in a default expression. Use `None` as the sentinel and build the value inside the body. In a `dataclass` the equivalent is `field(default_factory=list)` — a mutable default raises at class creation, so the trap there is reaching for a tuple to silence it rather than fixing the intent.

### `asyncio.gather` hides failures when you ask it to (3.8+)

`return_exceptions=True` turns every raised exception into a value in the results list. If nothing inspects the results for exception instances, a failed task presents as a successful batch — the Layer-0 truthful-terminal-states rule, in the shape it most often gets broken. Default to `return_exceptions=False`, or check the results explicitly. `asyncio.TaskGroup` (3.11+) is the better primitive: it cancels siblings and re-raises.

### Blocking calls in a coroutine stall the whole loop

A synchronous file read, `requests` call, or CPU-bound loop inside `async def` blocks every other task on that loop, and the symptom is unrelated latency somewhere else. Use the async client, or hand the work to `asyncio.to_thread` / a process pool.

### `if __name__ == "__main__":` is required for `multiprocessing` on spawn platforms

macOS and Windows spawn rather than fork, so the child re-imports the parent module. Without the guard, module-level work — including spawning more children — runs again in every child. Same reason a module's import side effects must stay free of anything that starts a process, timer or socket.

### The environment is declared, never installed ad hoc

Dependencies and their pins live in `pyproject.toml` plus a lockfile; interpreters and system tools live in the environment definition. Nothing is `pip install`ed into a shared or global interpreter, and no code path depends on a tool that the environment does not declare.
