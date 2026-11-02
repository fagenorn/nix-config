# Task 1: The runner gives a run's members one bytecode cache

Spec § Decisions (**The per-run cache**, **Sharing**, **Reach and limits**, **The README contract**), § Test seams items 1 and 2. Rests on D1, D2, D6, D8 and D9. After this task every member `agent_tools.suite_runner` launches, and every process that inherits its environment, writes and reads bytecode in one temporary directory per run, which the runner removes when the run ends.

**Files:**
- Modify: `python/agent_tools/suite_runner.py`
- Modify: `python/README.md`
- Test: `tests/test_suite_runner.py`

**Interfaces:**
- Consumes: `member_environment(parent: Mapping[str, str]) -> dict[str, str]` and `SUITE_GIT_CONFIG` as at base (issue 496).
- Produces, in `agent_tools.suite_runner`: `member_environment(parent: Mapping[str, str], cache: str) -> dict[str, str]`. `run_suite(members, *, jobs, out) -> int` and `main(argv=None) -> int` keep their signatures.
- Produces, in `tests/test_suite_runner.py`: the module-level fixture `CACHE_MEMBER` and the class `BytecodeCacheTest(RunnerCase)`.

**Invariants:**
- `member_environment(parent, cache)` returns a new `dict` and leaves `parent` unchanged.
- In the result, `PYTHONPYCACHEPREFIX` is exactly `cache`, whatever `parent` held, and `PYTHONDONTWRITEBYTECODE` is absent, whatever `parent` held (D1).
- `GIT_CONFIG_PARAMETERS` is composed exactly as at base (issue 496). Every key of `parent` other than `GIT_CONFIG_PARAMETERS`, `PYTHONPYCACHEPREFIX` and `PYTHONDONTWRITEBYTECODE` comes back with its value unchanged, and no other key is added.
- `run_suite` creates exactly one cache directory per call, named with the prefix `suite-runner-pycache-` in the default temporary directory, before the first member launches. It computes `member_environment(os.environ, cache)` once and hands that one mapping to `_run_serial` or `_run_parallel` (#496 D1).
- The directory is removed however `run_suite` ends: after the report, after an interrupt has waited for the running members, or when it raises. A removal error propagates: no `ignore_cleanup_errors`, no `try`/`except` around the cleanup (D1, D8).

- [ ] **Step 1: Write the failing tests**

In `tests/test_suite_runner.py`:

1. In the module docstring, replace `members' git environment cases (issue 496)` with `members' environment cases (issues 496 and 499)`, rewrapping the paragraph if a line grows past its neighbours.
2. Directly after the `SLEEP_MEMBER = textwrap.dedent(...)` statement, before `RUNNER_LINE = re.compile(...)`, add:

```python
# A unittest module that records, from inside its run, the bytecode cache it
# sees: the prefix, whether its own module's bytecode exists at the path CPython
# derives for it there, whether bytecode writing is enabled, and whether a
# `__pycache__` directory exists beside its source (issue 499).
CACHE_MEMBER = textwrap.dedent('''\
    import importlib.util
    import json
    import os
    import sys
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])
    NAME = Path(__file__).name


    class Member(unittest.TestCase):
        def test_member(self):
            (BARRIER / "seen" / NAME).write_text(json.dumps({
                "prefix": sys.pycache_prefix,
                "cached": Path(importlib.util.cache_from_source(__file__)).is_file(),
                "writing": not sys.dont_write_bytecode,
                "beside": (Path(__file__).parent / "__pycache__").exists()}))
''')
```

3. In `class MemberEnvironmentTest`:
   - Its docstring becomes the block below, indented as a class-body statement (four spaces):

```python
    """`member_environment` observed through what git reads under its result
    (issue 496) and through its bytecode variables (issue 499). Each case
    fails for one wrong composition."""
```

   - In `setUp`, after the `self.parent = …` statement, add `self.cache = str(self.scratch / "run-cache")`.
   - In `compose`, `return suite_runner.member_environment(parent)` becomes `return suite_runner.member_environment(parent, self.cache)`.
   - Replace the whole method `test_only_git_config_parameters_changes_and_the_parent_is_untouched` with these three:

```python
    def test_the_run_cache_replaces_an_inherited_prefix(self):
        parent = {**self.parent, "PYTHONPYCACHEPREFIX": str(self.scratch / "foreign")}
        environment = suite_runner.member_environment(parent, self.cache)
        self.assertEqual(environment["PYTHONPYCACHEPREFIX"], self.cache)

    def test_an_inherited_dont_write_bytecode_is_dropped(self):
        parent = {**self.parent, "PYTHONDONTWRITEBYTECODE": "1"}
        environment = suite_runner.member_environment(parent, self.cache)
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", environment)

    def test_only_the_git_and_bytecode_variables_change_and_the_parent_is_untouched(self):
        parent = {**self.parent, "GIT_CONFIG_PARAMETERS": "'user.name'='Inherited'",
                  "PYTHONPYCACHEPREFIX": str(self.scratch / "foreign"),
                  "PYTHONDONTWRITEBYTECODE": "1"}
        before = dict(parent)
        environment = suite_runner.member_environment(parent, self.cache)
        self.assertEqual(parent, before)
        changed = ("GIT_CONFIG_PARAMETERS", "PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE")
        self.assertEqual({key: value for key, value in environment.items() if key not in changed},
                         {key: value for key, value in before.items() if key not in changed})
```

4. Directly before `class RecipeWiringTest(unittest.TestCase):`, add:

```python
class BytecodeCacheTest(RunnerCase):
    """The members of a run share one bytecode cache that the runner creates and
    removes, at both launch sites (issue 499). This module runs under the suite
    runner, so each case hands the inner runner a sentinel `PYTHONPYCACHEPREFIX`
    and `PYTHONDONTWRITEBYTECODE=1` of its own: a case that kept the outer run's
    cache would pass against a runner that sets nothing."""

    def setUp(self) -> None:
        super().setUp()
        self.sentinel = self.work.parent / "sentinel-pycache"
        self.sentinel.mkdir()

    def environment(self, cap: int, total: int, extra: dict) -> dict:
        return {**super().environment(cap, total, extra),
                "PYTHONPYCACHEPREFIX": str(self.sentinel), "PYTHONDONTWRITEBYTECODE": "1"}

    def assert_members_share_one_removed_cache(self, jobs: str) -> None:
        members = [self.member(name, CACHE_MEMBER)
                   for name in ("test_cache_a.py", "test_cache_b.py")]
        result = self.run_suite("--jobs", jobs, *members)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        seen = {path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in (self.barrier / "seen").iterdir()}
        self.assertEqual(sorted(seen), members)
        prefixes = {record["prefix"] for record in seen.values()}
        self.assertEqual(len(prefixes), 1, seen)
        prefix = prefixes.pop()
        self.assertIsNotNone(prefix, seen)
        self.assertNotEqual(Path(prefix).resolve(), self.sentinel, seen)
        self.assertEqual(seen, {member: {"prefix": prefix, "cached": True, "writing": True,
                                         "beside": False} for member in members})
        self.assertFalse(Path(prefix).exists(), prefix)

    def test_serial_members_share_one_cache_the_run_removes(self):
        self.assert_members_share_one_removed_cache("1")

    def test_parallel_members_share_one_cache_the_run_removes(self):
        self.assert_members_share_one_removed_cache("2")


```

Each case kills one wrong runner: passing the inherited prefix through fails `assertNotEqual` against the sentinel; keeping `PYTHONDONTWRITEBYTECODE` leaves `writing` false and `cached` false; one directory per member fails the single-prefix check; setting the cache at one launch site only fails the other mode's case; leaving the directory behind fails the last assertion. The sentinel is written as `"PYTHONDONTWRITEBYTECODE": "1"` exactly, which the harness check in the plan root counts.

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 300 s): the runner-module command from the plan root's Global Constraints, with `-k MemberEnvironmentTest -k BytecodeCacheTest`.
Expected: `Ran 10 tests` and `FAILED (failures=2, errors=8)`. Each error is `TypeError: member_environment() takes 1 positional argument but 2 were given`; each failure is the `assertNotEqual` on the sentinel (today's runner passes the sentinel through with writing off, as a probe while planning confirmed).

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/suite_runner.py`:

1. Add `import tempfile` between `import sys` and `import threading`.
2. Replace `member_environment` with:

```python
def member_environment(parent: Mapping[str, str], cache: str) -> dict[str, str]:
    """A copy of `parent` whose `GIT_CONFIG_PARAMETERS` ends with
    `SUITE_GIT_CONFIG`, so every git command run with it reads
    `maintenance.auto=false` and `gc.auto=0` (issue 496), and whose Python
    processes share the bytecode cache `cache` (issue 499).

    The entries are appended as `git -c` appends its own: after one space when
    the inherited value is non-empty, standing alone otherwise. Coming last,
    they win over an inherited entry for the same key, and a test's own
    `GIT_CONFIG_COUNT` entries still apply beside them. The inherited value is
    passed on unparsed: one git cannot parse already fails every git call with
    exit 128.

    `PYTHONPYCACHEPREFIX` is set to `cache`, replacing an inherited value, and
    an inherited `PYTHONDONTWRITEBYTECODE` is dropped, so a Python process run
    with the copy writes its bytecode under `cache` and reads what an earlier
    one wrote there. `parent` is not modified, and every other variable is
    copied unchanged.
    """
    environment = dict(parent)
    inherited = environment.get("GIT_CONFIG_PARAMETERS", "")
    environment["GIT_CONFIG_PARAMETERS"] = (
        f"{inherited} {SUITE_GIT_CONFIG}" if inherited else SUITE_GIT_CONFIG)
    environment["PYTHONPYCACHEPREFIX"] = cache
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    return environment
```

3. Replace `run_suite` with the following. The code is given in full because the extent of the `with` block is the decision (per D8): it must enclose everything from computing the environment to writing the report, so every exit, the `KeyboardInterrupt` that the launch sites re-raise after waiting for their members and the `RuntimeError` for a missing result included, removes the directory and lets a removal error propagate.

```python
def run_suite(members: Sequence[str], *, jobs: int, out: BinaryIO) -> int:
    """Run every member and write the report; 0 when all passed, else 1.

    A KeyboardInterrupt propagates after the running members have finished and
    written their blocks. Must be called from the main thread: the runner holds
    SIGINT while it launches or reaps a serial member or starts its parallel workers.
    Every member runs with `member_environment(os.environ, cache)`, computed
    once, where `cache` is the run's bytecode cache: a temporary directory
    created before the first launch and removed however this call ends, a
    removal error propagating (issue 499).
    """
    output = _Output(out)
    with tempfile.TemporaryDirectory(prefix="suite-runner-pycache-") as cache:
        environment = member_environment(os.environ, cache)
        started = time.monotonic()
        if jobs == 1:
            results = _run_serial(members, environment, output)
        else:
            results = _run_parallel(members, jobs, environment, output)
        missing = [member for member, result in zip(members, results) if result is None]
        if missing:
            raise RuntimeError(f"members left without a result: {', '.join(missing)}")
        report = report_lines(results, jobs=jobs, wall_seconds=time.monotonic() - started)
        output.write(b"".join(_line(line) for line in report))
        return 0 if all(result.passed for result in results) else 1
```

Do not touch `_run_serial`, `_run_parallel`, `main` or the parser.

In `python/README.md`, in the `## \`agent-workflow-tests\` runner` paragraph:

1. In the sentence that begins `The runner runs each member in its own process`, replace `with the recipe's environment plus two git configuration entries:` with `with the recipe's environment plus two git configuration entries and the run's bytecode cache:`.
2. Directly after the sentence that ends `so that receiving repository still runs automatic maintenance.`, insert, in the same paragraph:

> The bytecode cache (issue 499) is one directory per run. Before the first member starts, the runner creates a `suite-runner-pycache-*` directory in the default temporary directory, sets `PYTHONPYCACHEPREFIX` to it, replacing an inherited value, and drops an inherited `PYTHONDONTWRITEBYTECODE` (`member_environment`). Every Python process that inherits a member's environment, at any depth, writes the bytecode of the source modules it imports there, under each source's absolute path, and reads what an earlier process of the same run wrote instead of compiling again. Parallel writers need no coordination: CPython writes each file under a temporary name and renames it into place, and skips a write it cannot make. The prefix redirects every bytecode lookup, the standard library's included, so a run compiles the standard-library source modules its processes import instead of reading the interpreter's own bytecode, and its later processes read that result. A script run as a main file, such as `workflow-state`, is compiled on every start. The runner removes the directory when the run ends, after the report, after an interrupted run has waited for its members, or on an error, and a failure to remove it is raised, never ignored. The cache does not reach a process started with an environment built from scratch, nor one run with `-I` or `-E`, which ignores both variables and keeps Python's default bytecode behaviour, and a descendant still running after the run ends may recreate part of the removed directory. CPython takes a cached file as current while its source's modification time, in whole seconds, and its size match, so a test that rewrites an importable source in place to the same size within one second and then imports it in a new process gives that process its own `PYTHONPYCACHEPREFIX` directory.

Check each clause against the code you wrote before committing; a clause the code does not bear out is a defect in the code per D1 and D2, not licence to reword the contract.

- [ ] **Step 4: Verify**

Run (timeout 300 s): the Step 2 command.
Expected: `Ran 10 tests` and `OK`.

Run (timeout 300 s): the runner-module command from the plan root.
Expected: `Ran 33 tests` and `OK` (29 at base, plus 2 composition cases and 2 cache cases).

Run (timeout 300 s): `bash -c 'set -e; f=python/agent_tools/suite_runner.py; if grep -n "ignore_cleanup_errors\|mkdtemp\|rmtree" "$f"; then exit 1; fi; grep -c "environment = member_environment(os.environ, cache)" "$f"'`
Expected: `1` (one composition, inside the cache context; no hand-rolled or muted removal).

Run (timeout 3600 s): `just build`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/suite_runner.py python/README.md tests/test_suite_runner.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(suite-runner): give a run's members one bytecode cache (issue 499)" -m "<session trailer lines>"
```
