# Task 1: Extent-aware read keys

**Files:**
- Modify: `python/agent_tools/agent_boot_report.py`
- Modify: `python/README.md`
- Test: `tests/test_agent_boot_report.py`

**Interfaces:**
- Consumes: `agent_tools.context_meter_commands.lex` and `SEPARATORS`, unchanged. `(`, `)` and the backtick are separators. A digit glued to a `>` operator lexes as one operator token (`1>>`, `2>`). The boot report strips heredoc operators and bodies (`_command_text`) before it calls `lex`.
- Produces:
  - `read_keys(name: str, tool_input: dict) -> list[tuple[str, object]]`, the `(path, extent)` keys of one tool call (per D5). The extent is `_WHOLE` for a whole-file read, the tuple `(offset, limit, pages)` for any other `Read`, and the tuple of its command's words for any other reader operand.
  - `_simple_commands(tokens) -> list[tuple[list[str], bool]]`: for each simple command, its words (redirections and their targets dropped, as today) and whether its standard output reaches the tool result.
  - Test helpers in `tests/test_agent_boot_report.py` that Task 2 reuses: `bash(command)`, `read(path, **extent)` and `stepped_boot(session, agent, seconds, steps, *, issue=7)`.

**Invariants:**
- `_classify`'s rule order is unchanged. So are the `saved to:` read-back rule (a `Read` of a path an earlier result named takes that result's bucket) and every bucket other than `rereads` (D5).
- Path identity is unchanged. `_reader_operands` still expands in-command `NAME=value` and joins to the in-command `cd`. A `~` operand, or a relative one with no `cd`, is compared as written.
- Every existing test passes unchanged. In `test_read_backs_rereads_and_resume_content_take_their_buckets`, the whole `cat /r/src/app.py` after two ranged `Read`s of that file stays `other_reads`.

- [ ] **Step 1: Write the failing test**

In `tests/test_agent_boot_report.py`, add the helpers after `two_call_boot`:

```python
def bash(command):
    return ("Bash", {"command": command})


def read(path, **extent):
    return ("Read", {"file_path": path, **extent})


def stepped_boot(session, agent, seconds, steps, *, issue=7):
    """A fresh owner (launch 2, phase 6) booting from 20,000 in one call per `(tool, size)` step.
    The step's result holds `size` characters, so the next call grows by `size` plus the 40
    output tokens of the step's call. The last call registers."""
    session.child(agent, tool_use_id=dispatch(session, seconds))
    opening(session, agent)
    context, previous = 20_000, 0
    for index, (tool, size) in enumerate(steps):
        tool_id = session.call(agent, seconds + 10 * index + 10, context=context,
                               write=context - previous, tool=tool)
        session.result(agent, seconds + 10 * index + 11, tool_id, "x" * size)
        previous, context = context, context + size + 40
    gate = session.call(agent, seconds + 10 * len(steps) + 10, context=context,
                        write=context - previous, bash=progress(6, action_id=f"{issue}:1:2"))
    session.result(agent, seconds + 10 * len(steps) + 11, gate,
                   gate_reply("continue", issue=issue, launch=2))
```

Add this test to `BootReportTest`, after `test_a_shrinking_segment_still_records_its_reads`:

```python
    def test_a_whole_read_covers_every_later_read_of_its_file(self):
        src = "/r/src/a.py"
        cases = (  # (first read, second read, whether the second is a reread)
            (bash(f"cat {src}"), read(src), True),
            (read(src), bash(f"cat {src}"), True),
            (read(src), read(src, offset=10, limit=20), True),
            (bash("cd /r/src && cat a.py 2>/dev/null"), read(src), True),
            (read(src, offset=1, limit=50), read(src), False),
            (read(src, offset=1, limit=50), read(src, offset=51, limit=50), False),
            (read("/r/docs/a.pdf", pages="1-2"), read("/r/docs/a.pdf", pages="3-4"), False),
            (bash(f"cat {src} | head -n 5"), read(src), False),
            (bash(f'V=$(cat {src}); echo "$V"'), read(src), False),
            (bash(f"echo `cat {src}`"), read(src), False),
            (bash(f"cat {src} > /tmp/a.txt"), read(src), False),
            (bash(f"cat {src} 1>>/tmp/a.txt"), read(src), False),
            (bash(f"cat {src} $(true) | head -n 5"), read(src), False),
        )
        for index, (first, second, reread) in enumerate(cases):
            with self.subTest(first=first, second=second):
                root = self.root / f"case-{index}"
                session = Session(root)
                stepped_boot(session, "o1", 0, [(first, 1_000), (second, 2_000)])
                session.write()
                [row] = report(root)["boots"]
                self.assertEqual((row["buckets"]["other_reads"], row["buckets"]["rereads"]),
                                 (1_000, 2_000) if reread else (3_000, 0))
```

Planning ran these fixtures through the base report. Every boot is `b` 23,080 with `tool_schemas` 19,800, `harness` 100, `prompt` 100 and `assistant` 80, and the two results are 1,000 and 2,000 tokens.

- [ ] **Step 2: Run the test and watch it fail**

Run the Boot tests (Global Constraints) with `-k whole_read_covers`.
Expected: FAIL in 5 sub-tests. The first four pairs give `(3000, 0)` instead of `(1000, 2000)`. The `pages` pair gives `(1000, 2000)` instead of `(3000, 0)`, because today's `Read` key is `(path, offset, limit)` and ignores `pages`.

- [ ] **Step 3: Write the minimal implementation**

All changes are in `python/agent_tools/agent_boot_report.py`, § read keys and `_classify`.

1. Add constants:
   - `_WHOLE = "whole"`: the extent of a whole-file read. It is a string, so it never equals a tuple extent.
   - `_STDOUT_TO_FILE = frozenset({">", ">>", ">|", "&>", "&>>", "1>", "1>>", "1>|"})`.
2. `_simple_commands(tokens)` returns `(words, shown)` pairs. It walks the tokens as today, keeping a paren depth (starting at 0), an in-backtick flag and a to-file flag per command. When it meets a separator token (`token.value in SEPARATORS`), it closes the current command:
   - `shown = depth == 0 and not in_backtick and not to_file and token.value not in ("|", "|&", "(", ")", "`")`, so a command cut by a substitution among its words (`cat X $(true) | head`) is never shown, since its later pipe or redirection is not yet seen (D12);
   - it resets `words`, `skip` and `to_file`;
   - then a `(` adds 1 to the depth, a `)` takes 1 away but never below 0 (a `case` pattern's lone `)`), and a backtick flips the in-backtick flag.

   Any other operator sets `skip` as today and sets `to_file` when its value is in `_STDOUT_TO_FILE`. The final command closes after the loop with no separator, so it is `shown` when its depth is 0, it is outside backticks and it has no stdout-to-file redirection. Docstring: "The simple commands of `tokens` as `(words, shown)`: the words with redirections and their targets dropped, and whether the command's standard output reaches the tool result, that is, it is outside every `(`…`)` and backtick pair, is not cut short by a `(`, `)` or backtick, is not followed by `|` or `|&`, and has no `>`, `>>`, `>|`, `&>` or `&>>` redirection, with or without a leading `1` (issue 504 D5)."
3. `_bash_keys(command)` iterates `(words, shown)`. It strips the leading assignments into `env` and applies `cd` as today. For a reader, the extent is `_WHOLE` when `shown and posixpath.basename(words[0]) == "cat"`, else `tuple(words)` (the words after the assignments, as today). It returns `[(path, extent) for path in _reader_operands(words, env, cwd)]`.
4. `read_keys`: for a `Read` with a string `file_path`, `extent = tuple(tool_input.get(field) for field in ("offset", "limit", "pages"))`. Return `[(file_path, _WHOLE if extent == (None, None, None) else extent)]`, so a field that is absent or null counts as none. `Bash` and every other tool behave as today. Docstring: "The `(path, extent)` keys a tool call reads (issue 504 D5); empty for every tool but Read and Bash."
5. Add `_covered(key, seen)`, which returns `key in seen or (key[0], _WHOLE) in seen`. In `_classify`, the reread rule becomes `elif keys and all(_covered(key, seen) for key in keys):`. `seen.update(keys)` and every other line stay as they are.

In `python/README.md`, *Buckets.* paragraph (the line starting `*Buckets.*`):
- Replace `a call with read keys, every one read before, is \`rereads\`` with `a call with read keys, each covered by an earlier read, is \`rereads\``.
- Replace the last sentence, which starts `A read key is a \`Read\`'s \`(path, offset, limit)\``, with:

  > A read key is a path and an extent (issue 504 D5). A `Read`'s path is its `file_path`. Its extent is whole when `offset`, `limit` and `pages` are each absent or null, else `(offset, limit, pages)`. For a `Bash` command that `lex` accepts, heredoc bodies and redirections are dropped and `NAME=value` and `cd` are applied first. Then each file operand of `cat`, `sed`, `head`, `tail`, `nl`, `awk`, `jq` or `less` is a path. A file operand is a word other than an option, a `head`/`tail` `-n`/`-c` value or the program of `sed`, `awk` or `jq`, that holds a `/` or ends in an extension. A relative operand is joined to the `cd` directory when the command has one; an absolute or `~` operand is compared as written. A `cat` operand's extent is whole when the `cat`'s standard output reaches the result. That holds when the `cat` is outside every `(`…`)` and backtick pair, is not cut short by a `(`, `)` or backtick, is not followed by `|` or `|&`, and has none of the redirections `>`, `>>`, `>|`, `&>` or `&>>`, with or without a leading `1`. Any other operand's extent is the words of its command. An earlier read covers a key when it read the same path whole, or the same path with the same extent. So a `cat` then a `Read` of one file, the reverse, and a ranged `Read` after a whole read are rereads. A whole read after ranged ones, or one range after another, is not.

Check each README clause against the code you wrote, and correct the README wherever they differ.

- [ ] **Step 4: Verify**

Run the Boot tests (Global Constraints), whole module.
Expected: `Ran 15 tests`, `OK`. The read-backs test still asserts `other_reads=3_000, rereads=1_000`.

Run: `if grep -q "every one read before" python/README.md; then exit 1; fi`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_boot_report.py python/README.md tests/test_agent_boot_report.py
launch-commit --repo-root <ledger repo root> --run-id <run id> --worker-id <worker id> -- \
  -m "feat(boot-report): count a whole-file read as covering later reads" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"65e822d7b6ec3fda3ea0eee33dad0ae5e4c504f3","head":"dc9482fc6460b98c82dfa5e0a55354ec91358cd6"}],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":45,"boundary":"all","deleted_lines":15,"record_bytes":12288,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1a","last_task":4,"owner":1,"path":"python/agent_tools/agent_boot_report.py"},{"bounds":[{"added_lines":60,"boundary":"all","deleted_lines":0,"record_bytes":8192,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":4,"owner":1,"path":"tests/test_agent_boot_report.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":16384,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":4,"owner":1,"path":"python/README.md"}]}}
```
