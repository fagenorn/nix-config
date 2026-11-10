# ADR-guard-001 — Detaching words are refused in the raw text, before any policy loads

- **Status:** accepted
- **Decided in:** #278, issue 656

## Context

A process started with `nohup`, `setsid` or `disown` outlives the tool call that started it, so the harness can neither follow nor stop it. The Bash tool's `run_in_background: true` starts the same long work in a way the harness tracks. Recognising the three words by parsing shell syntax left gaps: quoting, brace expansion and parameter defaults can each spell a word the parser reads differently from the shell.

## Decision

The guard refuses `nohup`, `setsid` and `disown` in every repository, before its policy loads, and names `run_in_background: true` as the route. Since issue 656 it reads no shell syntax for this: a word counts when it appears as a whole word in the raw text, and again in a copy of the text with the characters that glue pieces into one word deleted. Only two read-only forms that hold the word as plain data are admitted, a `grep` or `rg` search pattern and a quoted `gh issue|pr create|comment` title or body.

Reading the raw text trades precision for coverage: a mention that no shell would run is refused as firmly as a command that would.

## Consequences

- A commit message, a heredoc body, a comment or `nohup.out` that names a word is refused, outside the two admitted forms; the author rewords it or uses `git commit -F`.
- Residuals, none seen:
  - a word assembled at run time (`${a}hup`, `$(printf …)`, a variable);
  - a glob (`noh?p`);
  - an ANSI-C escape (`$'\x6eohup'`);
  - a brace expansion with a non-empty other alternative (`{no,x}hup`);
  - a word glued to a letter other than `c`/`s` as an attached option value a program runs.
