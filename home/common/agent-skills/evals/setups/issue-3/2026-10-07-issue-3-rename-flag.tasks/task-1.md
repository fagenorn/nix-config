# Task 1: Rename the flag

**Files:**
- Modify: `tinytask/cli.py`
- Modify: `README.md`
- Modify: `tests/test_cli.py`

**Invariants:**
- Behaviour is unchanged: `list --include-done` prints exactly what `list --all` printed, and bare `list` still hides done tasks.
- The option keeps its help text, `include done tasks`.
- No test names the old flag. The spec's criterion 4 bans the old name anywhere in the repo, so the old-flag check is a command in Verification and is not committed.

- [ ] **Step 1: Write the failing test**

In `tests/test_cli.py`, rename `test_list_all_includes_done_tasks` and change its `list` call:

```python
    def test_list_include_done_includes_done_tasks(self):
        self.add("write the spec")
        run("--file", self.path, "done", "1")
        _, lines = run("--file", self.path, "list", "--include-done")
        self.assertEqual(lines, ["1\tdone\twrite the spec"])
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python3 -m unittest tests.test_cli 2>&1 | tail -n 5`
Expected: `FAILED`. argparse rejects `--include-done` as an unrecognised argument.

- [ ] **Step 3: Rename the option**

In `tinytask/cli.py`, make the `list` option `--include-done` with help `include done tasks`, and read `args.include_done` where `list` filters. In `README.md`, change the example line to `python3 -m tinytask list --include-done`.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest discover 2>&1 | tail -n 3`
Expected: `OK`.

Run, from outside the committed tree: `python3 -m tinytask --file "$(mktemp -d)/t.json" list --all; echo "exit=$?"`
Expected: an argparse usage error, then `exit=2` (criterion 2).

Run: `git grep -n -- '--all' -- tinytask tests README.md`
Expected: no output (criterion 4). The `issues/` fixtures quote the old name and are not the tool's code or docs.

- [ ] **Step 5: Commit**

Commit the three files with the message `feat: rename list --all to --include-done (#3)`.
