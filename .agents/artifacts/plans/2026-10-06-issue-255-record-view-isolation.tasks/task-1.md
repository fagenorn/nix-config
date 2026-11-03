# Task 1: Isolated record runner and CORE record tests

**Files:**
- Modify: `python/agent_tools/review_actual.py` (add `record_git`, `commit_subject`; route `git_diff` and `_commits`)
- Modify: `python/agent_tools/review_projection.py` (reconstruction subject via `commit_subject`)
- Create: `tests/hostile_git_test_support.py`
- Create: `tests/test_review_record_view.py`
- Modify: `justfile` (register the new suite in `agent-workflow-tests`)

**Interfaces:**
- Consumes: `review_actual._run_git(repo, *args, binary=False)`, `GenerationError`, `RECORD_POLICY`, `actual_inputs`, `select_candidate`; test helpers `commit_files`, `git`, `init_repo` from `tests/retained_review_test_support.py`.
- Produces:
  - `review_actual.record_git(repo: Path, *args: str) -> bytes` — Task 2 calls it for issue 100's recipe.
  - `review_actual.commit_subject(repo: Path, sha: str) -> str`.
  - `tests.hostile_git_test_support.hostile_git_env(owned, base: Mapping[str, str], repos: Iterable[Path] = ()) -> dict[str, str]` and `NO_DIFF = "* -diff\n"` — Tasks 2 and 3 use them.

**Invariants:**
- `git_diff`'s argv is unchanged; `RECORD_POLICY_SHA256` and `PACKING_POLICY_SHA256` keep their values (D2).
- For each source in the spec's § *Treatment of each source*, CORE's candidates and selected package are byte-identical to the clean run (D1, D3).
- Every record call leaves no directory behind, on success and on failure; failures raise `GenerationError("git command failed")`.
- Under every hostile source, `record_git` sees exactly two `local` configuration entries and no attribute (D7).
- A subject that is not UTF-8 raises `GenerationError("commit metadata is not UTF-8")` from both callers (D10).

- [ ] **Step 1: Write the support module**

Create `tests/hostile_git_test_support.py` exactly:

```python
"""Hostile Git record-view sources for the issue-255 tiers (D6, D8).

Standard library only, so the installed tier imports it without `agent_tools`.
It declares no TestCase, so it is support rather than a suite and is not listed
as one.
"""
import os
import subprocess
from pathlib import Path

NO_DIFF = "* -diff\n"


def _write(path, text) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def hostile_git_env(owned, base, repos=()) -> dict:
    """`base` without any `GIT_*` variable or `XDG_CONFIG_HOME`, under every record-shaping source a test can
    own, and those sources written into `owned` and into each repository in `repos`.

    Each repository gets `NO_DIFF` as its common `info/attributes` and as a working-tree `.gitattributes`, and a
    repository `diff.orderFile`. The environment adds a global configuration file naming `core.attributesFile`
    and `diff.orderFile`, an `XDG_CONFIG_HOME` holding `git/attributes`, four command-line settings
    (`diff.orderFile`, `diff.suppressBlankEmpty`, `core.bigFileThreshold`, `i18n.logOutputEncoding`),
    `GIT_DIFF_OPTS` and `GIT_CONFIG_NOSYSTEM=1`. `HOME` stays `base`'s, which the caller owns."""
    owned = Path(owned)
    attributes, order = _write(owned / "attributes", NO_DIFF), _write(owned / "order", "*.md\n*\n")
    env = {k: v for k, v in base.items() if not k.startswith("GIT_") and k != "XDG_CONFIG_HOME"}
    _write(owned / "xdg/git/attributes", NO_DIFF)
    command = (("diff.orderFile", order), ("diff.suppressBlankEmpty", "true"),
               ("core.bigFileThreshold", "1k"), ("i18n.logOutputEncoding", "UTF-7"))
    env.update(XDG_CONFIG_HOME=str(owned / "xdg"), GIT_CONFIG_NOSYSTEM="1", GIT_DIFF_OPTS="--unified=1",
               GIT_CONFIG_GLOBAL=_write(owned / "global.gitconfig",
                                        f"[core]\n\tattributesFile = {attributes}\n[diff]\n\torderFile = {order}\n"),
               GIT_CONFIG_COUNT=str(len(command)))
    for n, (key, value) in enumerate(command):
        env[f"GIT_CONFIG_KEY_{n}"], env[f"GIT_CONFIG_VALUE_{n}"] = key, value
    for repo in repos:
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1"),
                                  check=True, capture_output=True, text=True).stdout.strip()
        _write(Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "info/attributes", NO_DIFF)
        if git("rev-parse", "--is-bare-repository") == "false":
            _write(Path(git("rev-parse", "--show-toplevel")) / ".gitattributes", NO_DIFF)
        git("config", "diff.orderFile", order)
    return env
```

- [ ] **Step 2: Write the failing CORE suite**

Create `tests/test_review_record_view.py` exactly. The tests import `record_git` and `commit_subject` inside their bodies, so at the base the hostile-source cases run and fail on the isolation assertion. That is the issue's red state: the records differ and nothing refuses.

```python
"""CORE's isolated Git record view (issue 255; D1, D3, D6, D7, D9).

Every hostile case runs in its own copy of one fixture repository, with a
test-owned `HOME`, `XDG_CONFIG_HOME` and `GIT_CONFIG_GLOBAL` and with
`GIT_CONFIG_NOSYSTEM=1`, so no host file leaks in. Each case pairs a control,
raw source Git rendering differently under that source, with the isolation
assertion: CORE's candidates and selected package equal the clean run's.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_tools.review_actual import RECORD_POLICY, actual_inputs, select_candidate
from agent_tools.review_pack import ReviewLimits

from .hostile_git_test_support import hostile_git_env
from .retained_review_test_support import commit_files, git, init_repo

LIMITS = ReviewLimits(16384, 65536, 8, 524288)
VIEWS = (("--numstat", "-z"), ("--name-only", "-z"), ("--name-status", "-z"),
         ("--binary", "-U10"), ("--binary", "-U0"))
BODY = b"".join(b"line %d\n" % n for n in range(40))
BIG = b"".join(b"big %d\n" % n for n in range(3000))
NO_DIFF = "*.c -diff\n"
ORDER = "z.txt\n*\n"


def write(path, text) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


class RecordViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="record-view-test-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp)
        repo = init_repo(cls.tmp / "fixture")
        cls.base = commit_files(repo, {"src/a.c": b"int a;\n\nint b;\n" + BODY, "z.txt": b"z\n" + BODY,
                                       "old.txt": b"moved\n" + BODY, "big.txt": BIG}, "base")
        cls.head = commit_files(repo, {"src/a.c": b"int a;\n\nint c;\n" + BODY + b"x\n", "z.txt": b"z2\n" + BODY,
                                       "old.txt": None, "new.txt": b"moved\n" + BODY, "big.txt": BIG + b"tail\n"},
                                "café subject")
        # A side branch whose tree carries the hostile `.gitattributes`, for `GIT_ATTR_SOURCE` and `attr.tree`.
        git(repo, "checkout", "-q", "-b", "attributes")
        cls.attributes = commit_files(repo, {".gitattributes": NO_DIFF.encode()}, "attributes")
        git(repo, "checkout", "-q", "main")
        cls.trees = tuple(git(repo, "rev-parse", f"{c}^{{tree}}") for c in (cls.base, cls.head))
        cls.fixture = repo
        cls.clean = cls.core(repo, cls.environment(cls.tmp / "clean"))
        cls.clean_raw = cls.raw(repo, cls.environment(cls.tmp / "clean"))

    @staticmethod
    def environment(owned, **changed):
        """The process environment of one case: the host's, minus `XDG_CONFIG_HOME`, under test-owned files."""
        owned = Path(owned)
        (owned / "home").mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "XDG_CONFIG_HOME"}
        env.update(HOME=str(owned / "home"), XDG_CONFIG_HOME=str(owned / "xdg"),
                   GIT_CONFIG_GLOBAL=write(owned / "global.gitconfig", ""), GIT_CONFIG_NOSYSTEM="1")
        env.update(changed)
        return env

    @classmethod
    def core(cls, repo, env):
        """Every candidate CORE generates for the fixture range, and the package it selects."""
        with patch.dict(os.environ, env, clear=True):
            inputs = list(actual_inputs(repo, cls.base, cls.head, "review.json", LIMITS))
            selected = select_candidate(iter(inputs), LIMITS)
        return inputs, selected.manifest, selected.shards

    @classmethod
    def raw(cls, repo, env):
        """The control: every record view and the head subject, rendered by Git directly in the source."""
        def run(*args):
            return subprocess.run(["git", "-C", str(repo), *args], env=env, check=True,
                                  capture_output=True).stdout
        views = tuple(run(*RECORD_POLICY["git_config"], "diff", *RECORD_POLICY["diff_args"], *view, *cls.trees)
                      for view in VIEWS)
        return views, run("show", "-s", "--format=%s", cls.head)

    def case(self, name):
        """A fresh copy of the fixture and the owned directory for case `name`."""
        owned = self.tmp / name
        repo = Path(shutil.copytree(self.fixture, owned / "repo", symlinks=True))
        return repo, owned

    def assert_isolated(self, repo, env, *, control=True):
        if control:
            self.assertNotEqual(self.raw(repo, env), self.clean_raw, "the hostile source never bit")
        self.assertEqual(self.core(repo, env), self.clean)

    def hostile_cases(self):
        """`name -> setup(repo, owned) -> env`: one record-shaping source each, as the spec's table lists them."""
        def repo_config(key, value, extra=()):
            def setup(repo, owned):
                for k, v in ((key, value), *extra):
                    git(repo, "config", k, v)
                return self.environment(owned)
            return setup

        def info(rule, extra=()):
            def setup(repo, owned):
                write(repo / ".git/info/attributes", rule)
                for k, v in extra:
                    git(repo, "config", k, v)
                return self.environment(owned)
            return setup

        def global_config(text):
            def setup(repo, owned):
                env = self.environment(owned)
                write(env["GIT_CONFIG_GLOBAL"], text)
                return env
            return setup

        def command_line(key, value):
            def setup(repo, owned):
                return self.environment(owned, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0=key, GIT_CONFIG_VALUE_0=value)
            return setup

        def xdg(repo, owned):
            env = self.environment(owned)
            write(Path(env["XDG_CONFIG_HOME"]) / "git/attributes", NO_DIFF)
            return env

        def home_default(repo, owned):
            env = self.environment(owned)
            del env["XDG_CONFIG_HOME"]
            write(Path(env["HOME"]) / ".config/git/attributes", NO_DIFF)
            return env

        def worktree_file(repo, owned):
            write(repo / ".gitattributes", NO_DIFF)
            return self.environment(owned)

        def parameters(repo, owned):
            order = write(owned / "order", ORDER)
            return self.environment(owned, GIT_CONFIG_PARAMETERS=f"'diff.orderfile={order}'")

        attributes_file = lambda owned: write(owned / "attributes", NO_DIFF)
        order_file = lambda owned: write(owned / "order", ORDER)
        return {
            "info/attributes -diff": info(NO_DIFF),
            "info/attributes binary": info("*.c binary\n"),
            "info/attributes diff=driver binary": info("*.c diff=bin\n", (("diff.bin.binary", "true"),)),
            "core.attributesFile repository": lambda r, o: repo_config("core.attributesFile", attributes_file(o))(r, o),
            "core.attributesFile global": lambda r, o: global_config(
                f"[core]\n\tattributesFile = {attributes_file(o)}\n")(r, o),
            "core.attributesFile command line": lambda r, o: command_line("core.attributesFile",
                                                                        attributes_file(o))(r, o),
            "XDG_CONFIG_HOME attributes": xdg,
            "HOME default attributes": home_default,
            "working-tree .gitattributes": worktree_file,
            "GIT_ATTR_SOURCE": lambda r, o: self.environment(o, GIT_ATTR_SOURCE=self.attributes),
            "attr.tree": repo_config("attr.tree", self.attributes),
            "diff.orderFile repository": lambda r, o: repo_config("diff.orderFile", order_file(o))(r, o),
            "diff.orderFile global": lambda r, o: global_config(f"[diff]\n\torderFile = {order_file(o)}\n")(r, o),
            "diff.orderFile command line": lambda r, o: command_line("diff.orderFile", order_file(o))(r, o),
            "diff.orderFile GIT_CONFIG_PARAMETERS": parameters,
            "diff.suppressBlankEmpty": repo_config("diff.suppressBlankEmpty", "true"),
            "core.bigFileThreshold": repo_config("core.bigFileThreshold", "1k"),
            "GIT_DIFF_OPTS": lambda r, o: self.environment(o, GIT_DIFF_OPTS="--unified=1"),
            "i18n.logOutputEncoding": repo_config("i18n.logOutputEncoding", "UTF-7"),
        }

    def test_each_hostile_source_bites_raw_git_and_never_core(self):
        for name, setup in self.hostile_cases().items():
            with self.subTest(source=name):
                repo, owned = self.case(name.replace("/", "-").replace(" ", "-"))
                self.assert_isolated(repo, setup(repo, owned))

    def test_every_hostile_source_at_once(self):
        repo, owned = self.case("combined")
        self.assert_isolated(repo, hostile_git_env(owned, self.environment(owned), [repo]))

    def test_the_view_reaches_no_configuration_or_attribute_source(self):
        """D7: under every hostile source, `record_git` sees only the view's own two `local` settings and no
        attribute at all, while raw Git in the source sees the hostile scopes and attributes."""
        from agent_tools.review_actual import record_git
        repo, owned = self.case("inventory")
        env = hostile_git_env(owned, self.environment(owned), [repo])
        raw = lambda *args: subprocess.run(["git", "-C", str(repo), *args], env=env, check=True,
                                           capture_output=True, text=True).stdout
        scopes = {line.split("\t")[0] for line in raw("config", "--list", "--show-scope").splitlines()}
        self.assertTrue({"local", "global", "command"} <= scopes, scopes)
        self.assertIn("diff: unset", raw("check-attr", "-a", "--", "src/a.c"))
        with patch.dict(os.environ, env, clear=True):
            listed = record_git(repo, "config", "--list", "--show-origin", "--show-scope").decode()
            attributes = record_git(repo, "check-attr", "-a", "--", "src/a.c", "z.txt")
        rows = [line.split("\t") for line in listed.splitlines()]
        self.assertEqual([(scope, entry) for scope, _, entry in rows],
                         [("local", "core.repositoryformatversion=0"), ("local", "core.bare=true")])
        self.assertTrue(all(origin.startswith("file:") and origin.endswith("/config") for _, origin, _ in rows))
        self.assertEqual(attributes, b"")

    def test_the_view_is_removed_on_success_and_failure(self):
        from agent_tools.review_actual import GenerationError, record_git
        scratch = Path(tempfile.mkdtemp(dir=self.tmp, prefix="scratch-"))
        with patch.object(tempfile, "tempdir", str(scratch)):
            self.assertEqual(record_git(self.fixture, "cat-file", "-t", self.head), b"commit\n")
            with self.assertRaises(GenerationError) as caught:
                record_git(self.fixture, "cat-file", "-t", "0" * 40)
        self.assertEqual(str(caught.exception), "git command failed")
        self.assertEqual(list(scratch.iterdir()), [])

    def test_subjects_come_from_one_isolated_reader(self):
        from agent_tools.review_actual import GenerationError, commit_subject, record_git
        self.assertEqual(commit_subject(self.fixture, self.head), "caf\u00e9 subject")
        tree = git(self.fixture, "rev-parse", f"{self.head}^{{tree}}")
        raw = (f"tree {tree}\nauthor F <f@e.t> 0 +0000\ncommitter F <f@e.t> 0 +0000\n\ncaf\xe9\n").encode("latin-1")
        latin = subprocess.run(["git", "-C", str(self.fixture), "hash-object", "-t", "commit", "-w", "--stdin"],
                               input=raw, check=True, capture_output=True).stdout.decode().strip()
        with self.assertRaises(GenerationError) as caught:
            commit_subject(self.fixture, latin)
        self.assertEqual(str(caught.exception), "commit metadata is not UTF-8")
        sha256 = self.tmp / "sha256"
        sha256.mkdir()
        git(sha256, "init", "-q", "--object-format=sha256")
        git(sha256, "config", "commit.gpgsign", "false")
        commit = commit_files(sha256, {"a.txt": b"a\n"}, "sha256 subject")
        self.assertEqual((len(commit), record_git(sha256, "cat-file", "-t", commit)), (64, b"commit\n"))
        self.assertEqual(commit_subject(sha256, commit), "sha256 subject")

    def test_linked_worktree_reads_the_common_info_attributes_only_raw(self):
        repo, owned = self.case("linked")
        write(repo / ".git/info/attributes", NO_DIFF)
        linked = owned / "linked"
        git(repo, "worktree", "add", "-q", "--detach", str(linked), self.head)
        self.assert_isolated(linked, self.environment(owned))

    def test_index_and_head_gitattributes_are_ignored(self):
        """D9: Git 2.51.2 does not read an index or `HEAD` copy for a tree-to-tree diff, so this source has no
        biting control; `GIT_ATTR_SOURCE` and `attr.tree` above show the same committed file would bite."""
        repo, owned = self.case("index-head")
        git(repo, "checkout", "-q", "attributes")
        (repo / ".gitattributes").unlink()
        self.assert_isolated(repo, self.environment(owned), control=False)

    def test_gitattributes_committed_inside_the_range_are_ignored(self):
        """D3, D11: a `.gitattributes` the reviewed range itself commits is not applied to its records."""
        # TODO(execute): write this test from the implemented code. From a fresh `self.case("in-range")`,
        # commit on top of `self.head` one commit that adds `.gitattributes` (`NO_DIFF`) and changes
        # `src/a.c`; generate CORE's candidates for `self.head..<that commit>` under `self.environment(owned)`,
        # once with that commit checked out and once after `git checkout -q main`. Assert that both runs are
        # equal and that every candidate's `src/a.c` record carries a textual `@@` hunk and no
        # `Binary files` line. No biting control (D9 applies to committed content too).


if __name__ == "__main__":
    unittest.main()
```

Register it in the `justfile`'s `agent-workflow-tests` list on the line after `tests/test_review_history.py \`:

```
    tests/test_review_record_view.py \
```

- [ ] **Step 3: Run it and watch it fail**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest tests.test_review_record_view 2>&1 | tail -3`
Expected: `FAILED (failures=21, errors=3)`, plus whatever the in-range test (D11) observes at base; record the observed counts here, and confirm any added failure is that test's assertion. The 21 failures are the isolation assertions (`Tuples differ`), never `the hostile source never bit`. The 3 errors are `ImportError` for `record_git` / `commit_subject`.

- [ ] **Step 4: Implement `record_git` and `commit_subject`**

In `python/agent_tools/review_actual.py`, add `import os` and `import tempfile` to the standard imports. Add these two functions directly after `git_diff`. The code is given in full because the view layout and the environment are the decision (D1, D7):

```python
def record_git(repo: Path, *args: str) -> bytes:
    """Run `git <args>` for a record in a fresh view of `repo`'s objects, isolated from every attribute and
    configuration source (issue 255; D1, D7).

    The view is a new bare Git directory made without `git init`, so no template applies. It holds an unborn
    `HEAD`, an empty `refs/`, a `config` that declares only the repository format, and an absolute alternate
    to `repo`'s object directory. Git runs there under the caller's environment without any `GIT_*` variable
    or `XDG_CONFIG_HOME`, with `HOME` set to the view and system configuration and attributes off. No
    working tree, index, attributes file or configuration beyond Git's defaults and the argv's own `-c`
    reaches the output. The view is removed on every outcome.
    """
    found = _run_git(repo, "rev-parse", "--path-format=absolute", "--git-path", "objects",
                     "--show-object-format")
    lines = found.split("\n")
    if len(lines) != 3 or lines[2] or not os.path.isabs(lines[0]) or lines[1] not in ("sha1", "sha256"):
        raise GenerationError("git command failed")
    objects, object_format = lines[0], lines[1]
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_") and key != "XDG_CONFIG_HOME"}
    try:
        with tempfile.TemporaryDirectory(prefix="record-view-") as name:
            view = Path(name)
            (view / "refs").mkdir()
            (view / "objects/info").mkdir(parents=True)
            (view / "HEAD").write_text("ref: refs/heads/record-view\n", encoding="utf-8")
            config = ("[core]\n\trepositoryformatversion = "
                      f"{0 if object_format == 'sha1' else 1}\n\tbare = true\n")
            if object_format != "sha1":
                config += f"[extensions]\n\tobjectFormat = {object_format}\n"
            (view / "config").write_text(config, encoding="utf-8")
            (view / "objects/info/alternates").write_text(objects + "\n", encoding="utf-8")
            env.update(HOME=str(view), GIT_CONFIG_NOSYSTEM="1", GIT_ATTR_NOSYSTEM="1")
            return subprocess.run(["git", f"--git-dir={view}", *args], cwd=view, env=env,
                                  check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GenerationError("git command failed") from exc


def commit_subject(repo: Path, sha: str) -> str:
    """`sha`'s subject line through `record_git`, strictly UTF-8, without its trailing newline (D10)."""
    raw = record_git(repo, "show", "-s", "--format=%s", sha).removesuffix(b"\n")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise GenerationError("commit metadata is not UTF-8") from exc
```

Discovery runs through `_run_git` in the caller's environment on purpose: routing and `safe.directory` behave exactly as today, and the history authority's routing refusal still guards the callers (spec § *Solution*, step 1).

- [ ] **Step 5: Route the callers**

1. `git_diff`: keep both checks and the argv, and replace the `_run_git(..., binary=True)` call and its `assert` with `return record_git(repo, *RECORD_POLICY["git_config"], "diff", *RECORD_POLICY["diff_args"], *view, base_tree, head_tree)`.
2. `_commits`: keep the `original_range` block and the `SHA_RE` check; build each row as `{"sha": sha, "subject": commit_subject(repo, sha)}` and delete the inline `show -s` call, the newline strip, the decode and the `UnicodeDecodeError` handler.
3. `review_projection.reconstruct_owned`: import `commit_subject` from `agent_tools.review_actual` and replace the two lines that run `show -s --format=%s` and decode it with `commits.append({"sha": commit, "subject": commit_subject(repo, commit)})`. Leave the scratch `init`, `read-tree`, `apply --cached` and `write-tree` calls on `_run_git` (spec § *What stays outside the runner*).

Do not change any other `_run_git` caller.

- [ ] **Step 6: Verify**

Run each and check the observation:
- `PYTHONPATH=python timeout 900 python3 -m unittest tests.test_review_record_view 2>&1 | tail -3` → `OK`, 7 tests.
- `PYTHONPATH=python python3 -c 'from agent_tools.review_actual import RECORD_POLICY_SHA256 as r, PACKING_POLICY_SHA256 as p; print(r, p)'` prints the same two digests as the same command run at the task's start commit (record them before Step 4).
- `git diff --stat <start>..HEAD -- tests/fixtures/retained-review-evidence tests/retained_evidence_test_support.py` → empty.
- `test "$(cat python/agent_tools/review_actual.py python/agent_tools/review_projection.py | grep -c '"show", "-s"')" -eq 1` → exit 0: the one remaining subject read is `commit_subject`'s (at the start commit the count is 2).
- `timeout 7200 just agent-workflow-tests 2>&1 | tail -3` → `OK`; no failure or error in any existing review suite.

- [ ] **Step 7: Commit**

```bash
git add python/agent_tools/review_actual.py python/agent_tools/review_projection.py \
  tests/hostile_git_test_support.py tests/test_review_record_view.py justfile
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-255-256-259 --worker-id <worker> -- \
  -m "feat(review): render CORE records in an isolated Git view (#255)" -m "<session trailer lines>"
```
