# Task 1: Policy-free detaching-word refusal

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Modify: `CLAUDE.md`
- Test: `tests/test_claude_permission_guard.py`

**Interfaces:**
- Consumes (existing, unchanged): `split_segments(command) -> list[str] | None`,
  `tokenize_segment(segment) -> list[tuple[str, bool]] | None` (value, is_operator),
  `COMMAND_KEYWORDS`, `COMMAND_WRAPPERS`, `SHELL_EVALUATORS`, `block(reason) -> 2`.
  The detaching pass walks tokens with its own `detaching_command_flags` scanner
  (spec D7); `command_position_flags` stays the verb pass's alone.
- Produces: `DETACHING_WORDS = ("nohup", "setsid", "disown")`;
  `detaching_word(command: str) -> str | None` — the detaching word the guard refuses, or `None`.

**Invariants:**
- `detaching_word` reads no policy, no cwd and no environment; `main` calls it after
  `command` is validated as a string and before `load_policy` (per D1).
- `"nohup"` is no longer in `COMMAND_WRAPPERS`; the other five wrappers stay (per D1).
- The guarded-verb pass (`guarded_operations`, `SHELL_EVALUATORS` exact-name check) is unchanged (per D6).
- A word in argument position of a parseable, non-evaluator segment never matches, unless its
  token carries `$(` or a backtick (per D3, D4).
- No new import; nothing from `agent_tools`.

- [ ] **Step 1: Write the failing tests**

Append these three methods to `ClaudePermissionGuardTest` in
`tests/test_claude_permission_guard.py`, directly after
`test_shell_equivalent_spellings_are_adjudicated` (inside the adversarial-table block):

```python
    def assert_detaching_refusal(self, result, word, command):
        self.assertEqual(2, result.returncode, (command, result.stderr))
        self.assertIn(
            f"lifecycle guard: detaching command `{word}` refused:", result.stderr,
            command,
        )
        self.assertIn("run_in_background", result.stderr, command)
        self.assertIn("launch-scope exec", result.stderr, command)

    def test_detaching_words_are_refused_globally(self):
        # Every form below makes the shell run a detaching word (or hands it to
        # source the guard cannot parse), so exit 0 means the guard missed it.
        # No cwd: the refusal is global and needs no repository.
        templates = (
            "W x", "W x &", "(W x)", "{ W x; }", "`W x`", "y=$(W x)", "$(W)",
            "case a in a) W x;; esac", "! W x", "time W x",
            "if true; then W x; fi", "for i in a; do W x; done",
            "true && W x", "x & W", '"W" x', "/usr/bin/W x",
            "command W x", "builtin W x", "exec W x", "env W x", "env -i W x",
            "env FOO=bar W x", "sudo W x", "sudo -E W x",
            "eval 'W x'", "sh -c 'W x'", 'bash -c "W x"', "zsh -c 'W x'",
            "dash -c 'W x'", "ksh -c 'W x'", "/bin/sh -c 'W x &'",   # per D6
            'echo "$(W x &)"', 'echo "`W x`"',                     # per D3
            'echo "unterminated ; W x',                              # unparseable
        )
        for word in ("nohup", "setsid", "disown"):
            for template in templates:
                command = template.replace("W", word)
                with self.subTest(command=command):
                    self.assert_detaching_refusal(
                        self.run_guard(command), word, command)
        # The issue's AC1 forms verbatim, and the deliberate over-refusal of D3.
        for command, word in (
            ("nohup x &", "nohup"), ("(setsid x)", "setsid"),
            ("env nohup x", "nohup"), ("$(disown)", "disown"),
            ("sh -c 'nohup x'", "nohup"), ("x & disown", "disown"),
            ("sh -c 'cat nohup.out'", "nohup"),
            ("sh -c 'setsid a; nohup b'", "setsid"),               # earliest, per D6
        ):
            with self.subTest(command=command):
                self.assert_detaching_refusal(self.run_guard(command), word, command)

    def test_detaching_word_mentions_pass(self):
        for command in (
            'echo "nohup"',
            "grep nohup log",
            "rg -n 'setsid|disown' docs/",
            'echo "run nohup x & later"',
            "cat > notes.md <<'EOF'\nnohup x &\nsetsid y\ndisown\nEOF\n",
            "true # nohup x & disown",
            "a & b & wait",
            "sleep 1 &",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_detaching_refusal_precedes_the_push_grammar(self):
        # AC3: still refused, now for detaching rather than as a push.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        result = self.run_guard("nohup git push origin main", cwd=repo)
        self.assert_detaching_refusal(result, "nohup", "nohup git push origin main")
        self.assertNotIn("unsafe push", result.stderr)
        # D1: the check runs before the policy loads. The registered wrapper
        # forwards "$@", so a later --policy overrides the store policy.
        bad_policy = ("--policy", "/nonexistent/lifecycle-guard-policy.json")
        refused = self.invoke_command("setsid x", *bad_policy)
        self.assert_detaching_refusal(refused, "setsid", "setsid x")
        control = self.invoke_command("true", *bad_policy)
        self.assertEqual(2, control.returncode)
        self.assertIn("lifecycle guard: invalid policy:", control.stderr)
```

- [ ] **Step 2: Run them and watch them fail**

The live `~/.claude/settings.json` registers the currently installed guard, which has no
detaching check, so it is the red artifact without a build:

Run: `CLAUDE_SETTINGS_PATH="$HOME/.claude/settings.json" python3 -m unittest tests/test_claude_permission_guard.py -k detaching 2>&1 | tail -6`
Expected: `FAILED` — `test_detaching_words_are_refused_globally` and
`test_detaching_refusal_precedes_the_push_grammar` fail (`2 != 0`, or the prefix is
absent); `test_detaching_word_mentions_pass` may already pass.

- [ ] **Step 3: Implement**

In `home/common/claude-code/lifecycle_guard.py`:

1. Change `COMMAND_WRAPPERS` to `frozenset({"command", "builtin", "exec", "env", "sudo"})`.
2. Next to `SHELL_EVALUATORS`, add `DETACHING_WORDS = ("nohup", "setsid", "disown")` and
   the refusal tail as a constant, worded per D2:
   `DETACHING_ROUTES = "a detached process outlives the task stop; run it with the Bash tool's background mode (run_in_background: true), or wrap a lifecycle launch in launch-scope exec"`.
3. Add, after `guarded_operations`:

```python
def detaching_word(command):
    """The detaching word (`nohup`, `setsid`, `disown`) the shell would run, or None.

    Policy-free and global. A token at a command position matches by value or by
    basename. Where the guard cannot see command positions it matches raw text
    instead and fails closed: an unparseable command, an untokenisable segment, a
    segment whose command-position word (or its basename) is an evaluator, and a
    token carrying `$(` or a backtick. A raw-text match names the word that occurs
    earliest in that text. A word in argument position otherwise passes.
    """
```

   Algorithm (the order is the decision; per D1, D3, D4, D6):
   - `earliest(text)`: among `DETACHING_WORDS` with `text.find(word) >= 0`, return the one
     with the smallest index, else `None`.
   - `segments = split_segments(command)`; if `None`, return `earliest(command)`.
   - For each segment in order: `tokens = tokenize_segment(segment)`; if `None`, a non-`None`
     `earliest(segment)` is the result. Otherwise compute `flags`; let `base(v) = v.rsplit("/", 1)[-1]`.
     If any flagged non-operator token has `base(value) in SHELL_EVALUATORS`, a non-`None`
     `earliest(segment)` is the result, and the segment is done. Otherwise scan tokens in
     order: a flagged non-operator token with `base(value) in DETACHING_WORDS` returns
     `base(value)`; a non-operator token containing `"$("` or `` "`" `` with a non-`None`
     `earliest(value)` returns that.
   - Return `None`.
4. In `main`, immediately after the `isinstance(command, str)` check and before
   `load_policy`:

```python
    word = detaching_word(command)
    if word is not None:
        return block(f"detaching command `{word}` refused: {DETACHING_ROUTES}")
```

In `CLAUDE.md`, in the guard bullet that begins `` - Use `just show-claude-settings` ``,
insert this sentence directly after the sentence ending ``(an argument to `xargs`, `timeout`, …) all block.``:

> Before any of that, and before its policy loads, the hook refuses the detaching words `nohup`, `setsid` and `disown` in every repository (#278): wherever a simple command starts (bare, by path, or behind a wrapper — `nohup` is no longer one), anywhere in evaluator source or an unparseable command, and inside a quoted `$(…)` or backtick substitution, naming the Bash tool's `run_in_background: true` and `launch-scope exec` as the routes; a mention, a heredoc body, a comment and a trailing `&` pass, and a word handed to an argv runner such as `xargs` or `timeout` is an accepted residual.

- [ ] **Step 4: Verify against the built artifact**

`just show-claude-settings` builds first (up to 15 minutes); run it in the foreground with
Bash timeout 1800000, and if the host backgrounds it, wait for the log's `exit=` line in the
same turn:

```bash
s="${TMPDIR:-/tmp}/settings-278.json"; log="${TMPDIR:-/tmp}/settings-278.log"; rc=0
just show-claude-settings > "$s" 2> "$log"; build=$?; echo "exit=$build"; tail -3 "$log"
[ "$build" -eq 0 ] || rc=1
if [ "$rc" -eq 0 ]; then
  CLAUDE_SETTINGS_PATH="$s" python3 -m unittest tests/test_claude_permission_guard.py > "$log" 2>&1 || rc=1
  tail -4 "$log"
fi
if grep -nE '^\s*(from|import)\s+agent_tools' home/common/claude-code/lifecycle_guard.py; then rc=1; fi
if grep -n '"nohup"' home/common/claude-code/lifecycle_guard.py | grep -q COMMAND_WRAPPERS; then rc=1; fi
rm -f "$s" "$log"; echo "verify=$rc"; [ "$rc" -eq 0 ]
```

Expected: `exit=0`, the block ends `verify=0` and exits 0 (any failed build, suite or grep makes it exit non-zero after cleanup); the whole suite reports `OK` including the three new tests
(two failed in Step 2, so this pass is not a no-op); both prohibition greps find nothing.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py CLAUDE.md
launch-commit <Lifecycle worker values> -- -m "feat(claude-code): guard refuses nohup, setsid and disown (#278)" -m "<trailers>"
```
