# Task 1: The members' git environment, composed and observed through git

Spec § Decisions (**Composition**, **Failure**), § Test seams item 1. Rests on D2 and D5. After this task `agent_tools.suite_runner` exports `member_environment`, a pure function that appends the suite's git entries to `GIT_CONFIG_PARAMETERS`. Nothing calls it yet: the runner launches members exactly as at base until Task 2.

**Files:**
- Modify: `python/agent_tools/suite_runner.py`
- Test: `tests/test_suite_runner.py`

**Interfaces:**
- Consumes: nothing new.
- Produces, in `agent_tools.suite_runner`:
  - `SUITE_GIT_CONFIG: str`, exactly `'maintenance.auto'='false' 'gc.auto'='0'`.
  - `member_environment(parent: Mapping[str, str]) -> dict[str, str]`.
- Produces, in `tests/test_suite_runner.py`: the module-level `without_command_git_config(environ: Mapping[str, str]) -> dict[str, str]`, which Task 2 reuses.

**Invariants:**
- The result is a new `dict`, and `parent` is unchanged after the call (D5).
- Every key of `parent` but `GIT_CONFIG_PARAMETERS` comes back with its value unchanged, and no key is added but `GIT_CONFIG_PARAMETERS`.
- `GIT_CONFIG_PARAMETERS` is `SUITE_GIT_CONFIG` when `parent` has none or an empty one, and `<inherited> + " " + SUITE_GIT_CONFIG` otherwise. The inherited value is never parsed, stripped or validated (spec § **Failure**, D2).
- No `GIT_CONFIG_COUNT`, `GIT_CONFIG_KEY_*` or `GIT_CONFIG_VALUE_*` is written (D2).

- [ ] **Step 1: Write the failing tests**

In `tests/test_suite_runner.py`:

1. Add `from collections.abc import Mapping` directly after `import unittest`.
2. Directly after the `SUMMARY = re.compile(...)` statement, add:

```python


def without_command_git_config(environ: Mapping[str, str]) -> dict[str, str]:
    """`environ` less every variable that carries command-scope git
    configuration: `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT` and its key and
    value variables. This module runs under the suite runner, which gives it the
    suite's git entries (issue 496); a case that kept them would pass against a
    runner that adds nothing."""
    return {key: value for key, value in environ.items()
            if key not in ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT")
            and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
```

3. Directly before `class RecipeWiringTest(unittest.TestCase):`, add:

```python
class MemberEnvironmentTest(unittest.TestCase):
    """`member_environment` observed through what git reads under its result
    (issue 496). Each case fails for one wrong composition."""

    def setUp(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        self.scratch = Path(raw.name).resolve()
        self.parent = {**without_command_git_config(os.environ),
                       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

    def read(self, environment: Mapping[str, str], key: str) -> str | None:
        """The value git reads for `key` under `environment`, or None when it
        has none. Any other exit, such as 128 for a `GIT_CONFIG_PARAMETERS` git
        cannot parse, fails the case."""
        result = subprocess.run(
            ["git", "config", "--get", key], cwd=self.scratch, env=environment,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
            check=False)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.stdout.strip() if result.returncode == 0 else None

    def compose(self, inherited: str | None) -> dict[str, str]:
        parent = dict(self.parent)
        if inherited is not None:
            parent["GIT_CONFIG_PARAMETERS"] = inherited
        return suite_runner.member_environment(parent)

    def assert_suite_entries(self, environment: Mapping[str, str]) -> None:
        self.assertEqual(self.read(environment, "maintenance.auto"), "false")
        self.assertEqual(self.read(environment, "gc.auto"), "0")

    def test_with_nothing_inherited_git_reads_the_suite_entries(self):
        self.assert_suite_entries(self.compose(None))

    def test_an_inherited_entry_still_reads_beside_the_suite_entries(self):
        environment = self.compose("'user.name'='Inherited'")
        self.assertEqual(self.read(environment, "user.name"), "Inherited")
        self.assert_suite_entries(environment)

    def test_an_empty_inherited_value_still_parses(self):
        self.assert_suite_entries(self.compose(""))

    def test_the_suite_entry_wins_over_an_inherited_entry_for_the_same_key(self):
        environment = self.compose("'maintenance.auto'='true'")
        self.assertEqual(self.read(environment, "maintenance.auto"), "false")

    def test_a_tests_own_config_count_keeps_the_suite_entries(self):
        # As tests/test_review_task7.py does with HOSTILE_GIT_ENV.
        environment = {**self.compose(None), "GIT_CONFIG_COUNT": "1",
                       "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "Counted"}
        self.assertEqual(self.read(environment, "user.name"), "Counted")
        self.assert_suite_entries(environment)

    def test_only_git_config_parameters_changes_and_the_parent_is_untouched(self):
        parent = {**self.parent, "GIT_CONFIG_PARAMETERS": "'user.name'='Inherited'"}
        before = dict(parent)
        environment = suite_runner.member_environment(parent)
        self.assertEqual(parent, before)
        self.assertEqual(set(environment), set(before))
        self.assertEqual({key: value for key, value in environment.items()
                          if key != "GIT_CONFIG_PARAMETERS"},
                         {key: value for key, value in before.items()
                          if key != "GIT_CONFIG_PARAMETERS"})


```

Each case kills one wrong composition: overwriting the inherited value fails the inherited-entry case, always joining with a space fails the empty-value case (git exits 128 on a leading space), prepending fails the same-key case, and writing `GIT_CONFIG_COUNT` slots fails the count case.

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_suite_runner.py -k MemberEnvironmentTest 2>&1 | tail -4'`
Expected: `Ran 6 tests` and `FAILED (errors=6)`, each error `AttributeError: module 'agent_tools.suite_runner' has no attribute 'member_environment'`.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/suite_runner.py`:

1. `from typing import BinaryIO, Sequence` becomes `from typing import BinaryIO, Mapping, Sequence`.
2. Directly after `INTERRUPT_EXIT = 130`, add:

```python
# Appended to every member's GIT_CONFIG_PARAMETERS, in the form `git -c` exports
# (issue 496).
SUITE_GIT_CONFIG = "'maintenance.auto'='false' 'gc.auto'='0'"
```

3. Directly after `member_command`, add the function. The code is given in full because the join is git's own wire format (git appends a `-c` entry after one space only when the inherited value is non-empty, and a leading space makes git exit 128):

```python
def member_environment(parent: Mapping[str, str]) -> dict[str, str]:
    """A copy of `parent` whose `GIT_CONFIG_PARAMETERS` ends with
    `SUITE_GIT_CONFIG`, so every git command run with it reads
    `maintenance.auto=false` and `gc.auto=0` (issue 496).

    The entries are appended as `git -c` appends its own: after one space when
    the inherited value is non-empty, standing alone otherwise. Coming last,
    they win over an inherited entry for the same key, and a test's own
    `GIT_CONFIG_COUNT` entries still apply beside them. The inherited value is
    passed on unparsed: one git cannot parse already fails every git call with
    exit 128. `parent` is not modified, and every other variable is copied
    unchanged.
    """
    environment = dict(parent)
    inherited = environment.get("GIT_CONFIG_PARAMETERS", "")
    environment["GIT_CONFIG_PARAMETERS"] = (
        f"{inherited} {SUITE_GIT_CONFIG}" if inherited else SUITE_GIT_CONFIG)
    return environment
```

Do not import `os` or touch `run_suite`, `_run_serial` or `_run_parallel`: Task 2 wires the function in.

- [ ] **Step 4: Verify**

Run (timeout 300 s): the Step 2 command.
Expected: `Ran 6 tests` and `OK`.

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_suite_runner.py 2>&1 | tail -4'`
Expected: `Ran 22 tests` and `OK` (16 at base plus 6).

Run: `bash -c 'set -e; f=python/agent_tools/suite_runner.py; if grep -nE "env=|os\.environ" "$f"; then exit 1; fi; echo unwired'`
Expected: `unwired` (no launch site passes an environment and nothing reads `os.environ` yet).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/suite_runner.py tests/test_suite_runner.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(suite-runner): compose the members' git environment (issue 496)" -m "<session trailer lines>"
```
