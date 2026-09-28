# Task 3: Pin the installed floor and the hostile platform import

Decisions: D9, D12, D13; parent D9; #175 D8. Spec section "The
installed-layout test and the helper's test (D9)". Work from the worktree root.

**Files:**
- Modify: `tests/test_agent_tools_launchers.py`

**Interfaces:**
- Consumes: Task 2's command table, which has eight rows including
  `adopt-project`, `conformance` and `resolve-project`, and Task 2's
  `NOT_LAUNCHERS = ("workflow-state",)`.
- Produces:
  `LAUNCHER_FLOOR = ("adopt-project", "agent-evidence", "agent-model-matrix", "conformance", "context-map-lint", "diff-scope", "resolve-project")`.
  `setUp` also writes `<hostile>/agent_platform.py`.

**Invariants:**
- The floor is the set #175, #179 and #177 accepted as launchers. It is a
  floor, not the full set: the command table owns that, so `promotion` is not
  listed (#175 D8).
- The hostile `agent_platform.py` has exactly the fake package `__init__`'s
  behaviour: it writes `MARKER` to stderr and exits `HOSTILE_EXIT`. The
  existing assertion that `MARKER` is in neither stream of a launcher run then
  also covers a bare-name platform import. No new assertion method is added.
- The controls still open one channel each, and each still sees the fake
  package first, because `-m agent_tools.<module>` imports `agent_tools`
  before any module can reach `agent_platform`.

- [ ] **Step 0: Record the starting commit**

Run: `START=$(git rev-parse HEAD); B=$(mktemp -d); echo "$START $B"`.
Substitute both printed values literally wherever later steps write `${START}`
or `$B`.

- [ ] **Step 1: Extend the floor and the hostile directory**

In `tests/test_agent_tools_launchers.py`:
- Replace the floor comment and constant with:

```python
# The commands #175, #179 and #177 accepted as launchers: a floor, not the full
# set, which the command table in lib/agent-tools.nix owns (#175 D8).
LAUNCHER_FLOOR = ("adopt-project", "agent-evidence", "agent-model-matrix", "conformance",
                  "context-map-lint", "diff-scope", "resolve-project")
```

- In `setUp`, directly after the `(package / "__init__.py").write_text(…)`
  call, add:

```python
        # A bare `import agent_platform` was the old resolver bootstrap's
        # adversary; a launcher must never reach this one (#177 D9).
        (self.hostile / "agent_platform.py").write_text(
            f"import sys\nsys.stderr.write({MARKER!r} + '\\n')\n"
            f"raise SystemExit({HOSTILE_EXIT})\n",
            encoding="utf-8",
        )
```

- In the module docstring, `each launcher must run its store module even with
  a fake \`agent_tools\` on the` becomes `each launcher must run its store
  module even with a fake \`agent_tools\` and a fake\ntop-level
  \`agent_platform\` on the`. Here `\`` is a literal backtick and `\n` a line
  break, as in Task 2. Also, `(#175 D8, D11; #179 D8; parent D9)` becomes
  `(#175 D8, D11; #179 D8; #177 D9; parent D9)`.

- [ ] **Step 2: Show the floor fails without a row, then restore**

Delete the line `    "resolve-project"` from `commands` in
`lib/agent-tools.nix`, and do not commit that change. Then run:

```bash
just agent-installed-skill-tests > "$B/floor.log" 2>&1; echo "exit=$?"
grep -E "^FAIL:|AssertionError" "$B/floor.log" | head -4
git checkout -- lib/agent-tools.nix
```

Expected: a non-zero `exit=`. The failures are
`FAIL: test_the_command_table_generates_each_deployed_command … (launcher='resolve-project')`,
with `AssertionError: 'resolve-project' not found in {…}`.

- [ ] **Step 3: Show the hostile module is live**

Run the three-line probe below. A plain, non-isolated interpreter with the
hostile directory on `PYTHONPATH` must reach the fake `agent_platform`:

```bash
D=$(mktemp -d); printf 'import sys\nsys.stderr.write("HOSTILE agent_tools IMPORTED\\n")\nraise SystemExit(97)\n' > "$D/agent_platform.py"
PYTHONPATH="$D" python3 -c "import agent_platform"; echo "exit=$?"
```

Expected: `HOSTILE agent_tools IMPORTED` on stderr, then `exit=97`. This is
the channel the launcher run must not open.

- [ ] **Step 4: Verify and commit**

Run: `just agent-installed-skill-tests 2>&1 | grep -E "^Ran |^OK|FAILED"`
Expected: `OK`. At `$START` the floor lacks the three commands, and the hostile
directory has no `agent_platform.py`:
`git show "${START}:tests/test_agent_tools_launchers.py" | grep -c 'agent_platform'`
prints `0`.

Run: `grep -c '"resolve-project"' tests/test_agent_tools_launchers.py`
Expected: `1`.

```bash
git add tests/test_agent_tools_launchers.py
git commit -m "test(agent-tools): pin the resolver family launchers and a hostile agent_platform"
```

The message ends with the plan's trailer lines. Run: `git status --porcelain`.
Expected: no output.
