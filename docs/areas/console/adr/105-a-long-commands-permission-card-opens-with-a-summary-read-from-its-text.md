# ADR-console-105 — A long command's permission card opens with a summary read from its text

- **Status:** accepted
- **Decided in:** #1621

## Context

On 22 Nov the manager's permission card for one command showed a 15,553-character heredoc verbatim. ADR-console-100 D10 shows the card only the command, so the owner had to read all of it to learn what it wrote, what it ran and whether it reached outside the project. This record adds a reading aid beside the verbatim command; it does not change what Allow once allows (ADR-console-100 D2).

## Decision

The owner bound the first: the console computes the summary and no model is called.

**D1. The summary is computed by the console from the command text alone.** `command_summary.summarize` is pure: no model call, no file system read, no subprocess, no environment. The prompt entry carries it as `summary`, and the guard, the permit, the own-read rule and the hook are unchanged. It decides nothing.

**D2. A long command's card opens with the summary and folds the full text; a short command keeps today's card.** The summary lists the files the command writes, the programs it runs and a plain warning when anything is outside the manager's own worktree. When the text cannot be read, the card says so instead of guessing. A command is long when it has more than 200 characters or more than three lines, and `summary` is None exactly when it is short.

**D3. The root is the project's root.** The manager's worktree is its project root (ADR-console-103 D3), so the service passes `{project_id: root}` from its folded project states and each entry is summarized against its own project's root, or against none when the project has no known root. Relative paths are placed against that root, and a literal `cd <dir>` moves the base for the commands after it. The hook's own `cwd` is never the base, as in ADR-console-103 D3.

**D4. A path the text cannot place counts as outside.** A `$` expansion, a leading `~`, a brace expansion, a base made unknown by `cd` and a missing root each show the path as outside, as written. An absolute path inside a word is found and placed on its own (after the first `=` of an option or `NAME=value` word, glued to a short option, in a `,`- or `:`-separated component, in a quoted word holding a blank).

**D5. The scanner reads simple commands and refuses the rest.** It reads commands joined by `;`, `&&`, `||`, `|`, `|&`, `&` and newlines, with redirections and here-documents. It says it could not read a command or process substitution, a subshell or group, a shell keyword at command position, `eval`, `source` or `.`, an expanded program word, ANSI-C quoting, an unterminated quote or here-document, or an unquoted here-document body holding `$(` or a backtick. It never returns a partial summary.

**D6. Standard input is a script unless a known plain-data reader takes it, and the console does not read it.** One closed allowlist names the readers of data: `cat tee head tail wc sort uniq cut tr grep` (without `-f` or `--file`), `egrep fgrep jq yq less more base64 gzip gunzip zcat bzip2 xz tac rev nl fold fmt column paste comm diff od xxd hexdump md5sum sha1sum sha256sum shasum cksum` and `git`. `xargs`, a wrapper such as `sudo` or `env`, and every other program, named in a table or not, are not on it. Whenever standard input reaches a program off the list from a here-document, a here-string or a pipe, the summary treats that text as a script that program may run (the program word as written, a line count, the paths its text names, which count for the outside warning), whatever options or operands it is given (`pwsh -Command -`, `awk -f -`, `sed -f /dev/stdin`, `gdb -batch -x /dev/stdin`); the summary parses no option to decide otherwise, and a later program found to read code from standard input is answered by this rule, never by a new table. The one exception is a shell given `-c` code and no `s` in any of its short option words. A `-c` or `-e` argument of a known shell or interpreter is also a script. A pipe whose earlier stages show no text (`curl ... | bash`) and a file redirection into a program off the list (`bash < x.sh`) make the console say it could not read the command. Over-warning is accepted; missing a script is not. The body of every here-document and here-string is scanned for paths outside the worktree whoever reads it, so a body that a plain program reads can add an outside path.

**D7. The write list is what the console recognises, not a claim that nothing else is written.** Redirections and a short table of writers fill it. A program outside the table, or behind a wrapper such as `sudo`, adds no write. So the card says "No write the console recognises" when the list is empty and never "writes no file".

## Consequences

- Residuals, not fixed here: a program can write files its arguments do not name; a program outside the writer table, or behind a wrapper such as `sudo`, adds no write though it may write a file it names (its named paths still count for the outside warning); a quoted word naming a path, such as a commit message, counts as touching it; a brace expansion counts as outside, as written; a symlink or a `cd` the text cannot see places a path wrongly; a pipeline's `cd` is read as sequential.
- The entry gains one member, `summary`; every other member is unchanged, and the page reads it.
- A summary is a reading aid: Allow once still allows the whole command.
- Related: ADR-console-100, ADR-console-103.
