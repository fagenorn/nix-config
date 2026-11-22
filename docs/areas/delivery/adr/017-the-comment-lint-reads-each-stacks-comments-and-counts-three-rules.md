# ADR-delivery-017 — The comment lint reads each stack's comments and counts three rules

- **Status:** accepted
- **Decided in:** #1461 (per #1420, #1414, #1412)

## Context

The bar held one sentence about comments, "Comments say why; the code already says what.", and nothing checked it. Comments named issues, ran long and carried `TODO` markers with no gate, while the size rule already had a never-rise check that compares a rule's count with the merge base (ADR-project-contract-017).

## Decision

**D1. Three ids, split from B8 and B2.** B18 holds the content rule, whose enforcer is the reference check; B19 holds the five-line and 120-character cap with the header exemption; B20 bans `TODO` and `FIXME`. B8 drops its comment sentence and B2 drops its `TODO` and `FIXME` clause, so each rule has one home and an enforcer cites the id it counts.

**D2. Stacks by file name.** Suffixes `.py .pyi` are Python; `.js .mjs .cjs .jsx .ts .mts .cts .tsx` JavaScript and TypeScript; `.cs .csx` C#; `.nix` Nix; `.sh .bash .zsh .ksh` shell; `.yaml .yml` YAML; the names `justfile`, `Justfile`, `.justfile` and the suffix `.just` the justfile; an extensionless file whose first line is a Python or shell shebang. Every other file is not read, because a comment syntax must be known to count it.

**D3. Python docstrings are comment blocks.** Module, class and function docstrings are blocks; the module docstring belongs to the file header. Only module docstrings and file headers are exempt from the length cap, so a long function docstring counts under B19.

**D4. Block, header and width.** A block is a maximal run of consecutive lines each holding only a line comment, or one block comment, or one docstring; a comment after code on its line is a one-line block. A docstring's text is bounded by its string literal's columns, so code sharing a line with it is neither in its text nor hidden from code detection. The file header is every block that ends before the file's first line of code; a line-1 shebang is neither comment nor code. A line's width is the physical line without trailing whitespace, in characters.

**D5. What a reference is.** Whole URLs in the comment text are classified first: a link to the repository's own issues or pulls is a reference, any other URL passes and is blanked out before the shorthand forms are matched, so a `GH-<n>` or `#<n>` inside an upstream URL is not a reference. In the remaining text a bare `#<n>`, `issue <n>`, `pull request <n>`, `PR <n>` and `GH-<n>` are references, and, when the repository is known, so are a link to its issues or pulls and `<owner>/<repo>#<n>`. The repository is the contract's `bindings.tracker.repo_slug` in the conformance check and `--repository` on the command.

**D6. One violation per line per rule, three count rules.** B18 and B20 report each matching comment line once; B19 reports a block over five lines at its first line and each line over 120 characters, deduplicated by rule, path and line, because the never-rise comparison counts list entries. Each is a count enforcer under its own id, so a removed reference cannot hide a new `TODO`.

**D7. Strings are not comments.** Text inside a string literal is never a comment, including scripts embedded in Nix strings and YAML block scalars. A Python file that does not tokenize or parse is read by a hash-line fallback. Each lexer tells a string's start from the same character used elsewhere: a YAML quote opens a scalar only where a scalar starts, a shell `<<` inside arithmetic is a shift and not a heredoc, a JavaScript `/` right after `<` is a JSX closing tag and not a regular expression, and a C# interpolated string's holes are lexed as code.

**D8. Fixtures carry a `.fixture` suffix.** The per-stack fixtures live under `tests/fixtures/comment-lint/` as `<target name>.fixture`, a suffix no stack covers, so the repository's own never-rise run does not count their deliberate violations.

**D9. One command preamble.** `never_rise.command_snapshot` holds the root and revision checks that both registered never-rise commands share. `comment-lint` is a registered command, and the gate is the never-rise conformance check, not the command's exit (ADR-project-contract-017 D9).

## Considered options

- **Stripping issue numbers mechanically.** Rejected: a comment that leans on its number would be left with a dangling sentence, so each is rewritten by hand.
- **A committed baseline.** Rejected by ADR-project-contract-017: the baseline is computed from the branch's own history on every run.

## Consequences

- Existing comments are carried by the merge base; cleaning them up is comment-only follow-up work.
- Scripts embedded in strings are not read.
- A long function docstring now fails B19.
- A shell fragment with no suffix and no shebang is not read, so this repository's sourced zsh fragments stay outside the lint until a change renames them to `.zsh` and rewrites their comments in the same commit, because a rename alone would count their existing comments as new.
- JSX element text reads as code.
- The tracker link form is judged from the authored `bindings.tracker.repo_slug`, so a contract that leaves the slug to derivation counts only the bare and worded forms.
