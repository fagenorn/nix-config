# ADR-system-001 — Standard library only, runtime and tests

- **Status:** accepted

tinytask has to run from a bare `python3` on any machine someone drops it on, so it
takes no third-party dependency in the runtime or in the tests — `pytest` and a schema
library were the obvious alternative and buy convenience this project cannot spend,
because a dependency in a single-file tool is a dependency for everyone who runs it.
The standard library and `unittest` are the whole toolbox; a change that needs a
package needs its own ADR first.
