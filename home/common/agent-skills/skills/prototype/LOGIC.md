# Logic Prototype

A tiny interactive terminal app that lets the user drive a state model by hand, for questions about **business logic, state transitions or data shape**: the edge case where X then Y, whether a data model can represent a case, what an API should feel like before it is written.

## Process

1. **State the question.** One paragraph naming the state model and the question, in the prototype's README or a top-of-file comment, so the answer can be checked later.
2. **Use the host project's language and tooling.** No new package manager or runtime; if the project has no obvious runtime, ask.
3. **Isolate the logic in a portable, pure module** that could later move into the real codebase. Pick the shape the question needs, not the easiest to wire up:
   - a pure reducer `(state, action) => state` for discrete events on one value;
   - a state machine when "which actions are legal now" is part of the question;
   - pure functions over a plain data type when there is no implicit current state;
   - a class with a clear method surface when the logic owns ongoing state.

   No I/O, terminal code or `console.log` in it; the TUI calls into it, never the reverse.
4. **Build the smallest TUI that exposes the state.** On every action clear the screen (`console.clear()`, `print("\033[2J\033[H")`) and re-render one frame that fits a screen:
   - the current state, one field per line or formatted JSON, field names **bold** (`\x1b[1m`) and lesser context **dim** (`\x1b[2m`, reset `\x1b[0m`);
   - the keyboard shortcuts at the bottom: `[a] add user  [d] delete user  [t] tick clock  [q] quit`.

   Initialise state in memory, render, read one keystroke or line, dispatch to a handler, re-render, loop until quit.
5. **One command to run**: add a script to the existing task runner (`package.json`, `Makefile`, `justfile`, `pyproject.toml`), or put the command atop the README if there is none.
6. **Hand it over** with the run command. The moments that matter are "that shouldn't be possible" and "I assumed X": bugs in the idea. Add actions as asked.
7. **Capture the answer**: ask the user what it taught them, or leave a `NOTES.md` beside the prototype to fill in before it is deleted.

## Anti-patterns

- Tests: a prototype that needs them is no longer a prototype.
- The real database, unless persistence is the question.
- Generalising for "what if we later want X".
- Logic that references `console.log`, prompts or escape codes: it is no longer portable.
- Shipping the TUI shell: only the logic module is worth keeping.
