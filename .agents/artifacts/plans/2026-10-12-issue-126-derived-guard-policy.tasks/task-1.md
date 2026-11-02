# Task 1: Reuse seams — the shared slug rule, bounded network git children, the source's remote default

Per D9 and D13. Three additive changes let Task 2's compiler call registration's own branch rule, pinned fetch and slug rule. No existing caller changes behaviour: every new parameter defaults to today's value.

**Files:**
- Create: `python/agent_tools/github_remote.py`
- Modify: `python/agent_tools/forge_adapter.py` (drop `GITHUB_REMOTE` and `_github_slug`, import `github_slug`)
- Modify: `python/agent_tools/adopt_inspection.py` (`GIT_TIMEOUT_SECONDS`, `run_git`, `remote_heads`, `fetch_pinned`)
- Modify: `python/agent_tools/adopt_verify.py` (`VerificationSource`, `remote_source`, `pin_integration_branch`)
- Test: `tests/test_forge_adapter.py`, `home/common/agent-skills/tests/test_adopt_verify.py`

**Interfaces:**
- Consumes: nothing from another task.
- Produces (Task 2 relies on every name):
  - `agent_tools.github_remote.github_slug(url: str) -> str | None` and the pattern `GITHUB_REMOTE`, moved unchanged from `forge_adapter`.
  - `adopt_inspection.GIT_TIMEOUT_SECONDS = 300`; `run_git(root, *args, network=False, input=None, timeout: float = GIT_TIMEOUT_SECONDS)`; `remote_heads(root: Path, timeout: float = GIT_TIMEOUT_SECONDS) -> RemoteHeads`; `fetch_pinned(root: Path, branch: str, timeout: float = GIT_TIMEOUT_SECONDS) -> str`.
  - `adopt_verify.VerificationSource.remote_default: str | None = None` (the last field); `remote_source(root, run_resolver, operand=None, *, network_timeout: float = GIT_TIMEOUT_SECONDS)`; `pin_integration_branch(root, run_resolver, branch, destination, unconfirmed, network_timeout: float = GIT_TIMEOUT_SECONDS)`.

**Invariants:**
- `forge_adapter` keeps exactly three public functions of its own (`PublicSurfaceTest.test_exactly_three_public_operations`): the slug rule is imported, never defined or re-exported under a new adapter-owned name.
- One definition of the slug rule exists in `python/agent_tools/`: `forge_adapter` has no `_github_slug` and no `GITHUB_REMOTE`.
- A call that passes no bound behaves as before: 300 s for every git child. A passed bound applies to the `ls-remote` child of `remote_heads` and the `fetch` child of `fetch_pinned` only; `fetch_pinned`'s `rev-parse` read-back, `has_remote` and `export_commit` keep the default.
- `remote_source` threads `network_timeout` to its `remote_heads` call, its `fetch_pinned` call and both `pin_integration_branch` calls, and sets `remote_default` to the branch `origin`'s `HEAD` names on every source it yields. `head_source` leaves it `None`.
- A bounded child that times out raises the existing `AdoptError` with repair id `adopt.git.unavailable` (the `subprocess.SubprocessError` arm `run_git` already has); no new error code.
- The fleet registry, the `verify` report and every `adopt-project` exit code are unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/test_forge_adapter.py`, add `github_remote` to the `from agent_tools import ...` line and add this class immediately above `class PublicSurfaceTest`:

```python
class GithubRemoteTest(unittest.TestCase):
    """The slug rule has one home, which the adapter imports (issue 126 D9)."""

    def test_only_the_three_github_spellings_name_a_repository(self):
        for url in ("git@github.com:fagenorn/nix-config.git", "git@github.com:fagenorn/nix-config",
                    "https://github.com/fagenorn/nix-config.git",
                    "ssh://git@github.com/fagenorn/nix-config\n"):
            with self.subTest(url=url):
                self.assertEqual(github_remote.github_slug(url), "fagenorn/nix-config")
        for url in ("git@gitlab.com:fagenorn/nix-config.git", "/srv/git/nix-config.git", "",
                    "https://github.com.evil.example/fagenorn/nix-config.git",
                    "http://github.com/fagenorn/nix-config", "git@github.com:fagenorn/..",
                    "https://github.com/fagenorn/nix-config/extra"):
            with self.subTest(url=url):
                self.assertIsNone(github_remote.github_slug(url))

    def test_the_adapter_uses_that_rule_and_keeps_no_copy(self):
        self.assertIs(forge_adapter.github_slug, github_remote.github_slug)
        for name in ("_github_slug", "GITHUB_REMOTE"):
            self.assertFalse(hasattr(forge_adapter, name), name)
```

In `home/common/agent-skills/tests/test_adopt_verify.py`, add `import shutil` and `import time` to the standard-library imports, add `from agent_tools import adopt_inspection` and `from agent_tools import adopt_project` beside the existing `agent_tools` imports, and add this block immediately above `class RegisterProjectInnerCheckTest`:

```python
SLOW_GIT = """#!{python}
import os, sys, time
if "ls-remote" in sys.argv or "fetch" in sys.argv:
    time.sleep(30)
os.execv({git!r}, [{git!r}, *sys.argv[1:]])
"""


class RemoteSourceSeamTest(VerifyTestCase):
    """What a caller other than registration reads from `remote_source` (issue 126 D13)."""

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def slow_git(self) -> None:
        """Put a `git` first on PATH whose `ls-remote` and `fetch` outlast any test bound."""
        shims = Path(tempfile.mkdtemp())
        shim = shims / "git"
        shim.write_text(SLOW_GIT.format(python=sys.executable, git=shutil.which("git")),
                        encoding="utf-8")
        shim.chmod(0o755)
        patcher = mock.patch.dict(
            os.environ, {"PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_source_names_the_remote_default_branch(self):
        root = verifiable_repo(self.home, integration_branch="dev")
        git(root, "branch", "dev")
        publish(root, ("main", "dev"))
        with adopt_verify.remote_source(root, adopt_project.run_resolver) as source:
            self.assertEqual((source.branch, source.remote_default), ("dev", "main"))
        single = verifiable_repo(self.home, project_id="fixture/single")
        publish(single)
        with adopt_verify.remote_source(single, adopt_project.run_resolver) as source:
            self.assertEqual((source.branch, source.remote_default), ("main", "main"))
        self.assertIsNone(adopt_verify.head_source(single).remote_default)

    def test_a_network_child_is_bounded_by_the_caller(self):
        self.assertEqual(adopt_inspection.GIT_TIMEOUT_SECONDS, 300)
        root = verifiable_repo(self.home)
        publish(root)
        self.slow_git()
        calls = (
            lambda: adopt_inspection.remote_heads(root, 0.5),
            lambda: adopt_inspection.fetch_pinned(root, "main", 0.5),
            lambda: adopt_verify.remote_source(
                root, adopt_project.run_resolver, network_timeout=0.5).__enter__(),
        )
        for index, call in enumerate(calls):
            with self.subTest(call=index):
                started = time.monotonic()
                with self.assertRaises(AdoptError) as caught:
                    call()
                self.assertLess(time.monotonic() - started, 10)
                self.assertEqual(caught.exception.repair_id, "adopt.git.unavailable")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_adapter.py home/common/agent-skills/tests/test_adopt_verify.py -k GithubRemote -k RemoteSourceSeam 2>&1 | tail -6`
Expected: FAIL — `ImportError: cannot import name 'github_remote' from 'agent_tools'` for the first module; once that import exists, `AttributeError` on `remote_default` and `GIT_TIMEOUT_SECONDS` and `TypeError` on the extra positional bound.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/github_remote.py` is the moved rule, complete (the regular expression and the function body are today's `forge_adapter` text; only the home changes):

```python
"""The one rule for naming a GitHub repository from a remote URL (#124; issue 126 D9)."""

import re

GITHUB_REMOTE = re.compile(r"(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)"
                           r"(?P<slug>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?")


def github_slug(url: str) -> str | None:
    """`owner/name` of a remote URL on the host `github.com` exactly, else None.

    Only the three GitHub spellings are recognised (`git@github.com:`, `https://github.com/`
    and `ssh://git@github.com/`): a URL on any other host, a lookalike host included, names
    no GitHub repository however its path reads.
    """
    match = GITHUB_REMOTE.fullmatch(url.strip())
    return None if match is None or ".." in match["slug"] else match["slug"]
```

`forge_adapter.py`: delete `GITHUB_REMOTE` and `_github_slug`, add `from agent_tools.github_remote import github_slug` after the standard-library imports, and replace the three `_github_slug(` calls in `_same_repository` with `github_slug(`. Keep `SLUG`, which `_target_problem` uses.

`adopt_inspection.py`: define `GIT_TIMEOUT_SECONDS = 300` beside `REMOTE` with a comment saying it is the bound of one git child unless a caller passes a tighter one; give `run_git` the keyword `timeout: float = GIT_TIMEOUT_SECONDS` and pass it to `subprocess.run` in place of the literal `300`; give `remote_heads` and `fetch_pinned` the trailing parameter `timeout: float = GIT_TIMEOUT_SECONDS`, passed to their one `network=True` call. Extend the three docstrings with the sentence that is then true of each.

`adopt_verify.py`: import `GIT_TIMEOUT_SECONDS` in the existing `from agent_tools.adopt_inspection import (...)` list; add the `remote_default` field after `default_contract_resolved` and one sentence for it to the `VerificationSource` docstring; add the keyword-only `network_timeout` to `remote_source` and the trailing `network_timeout` to `pin_integration_branch`, threaded as the invariants say; pass `remote_default=default` where `remote_source` builds its `VerificationSource`.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_adapter.py tests/test_release_adapter_core.py home/common/agent-skills/tests/test_adopt_verify.py 2>&1 | tail -4`
Expected: `OK` (95 tests: the 91 at base plus the 4 added), no failure or error.

Run, as one script:

```bash
set -e
if grep -rn "_github_slug\|^GITHUB_REMOTE" python/agent_tools/forge_adapter.py; then exit 1; fi
if [ "$(grep -rln "def github_slug" python/agent_tools | wc -l | tr -d ' ')" != 1 ]; then exit 1; fi
git add python/agent_tools/github_remote.py && just build >/dev/null
git diff --stat 450f1de3627b -- python/agent_tools/github_remote.py python/agent_tools/forge_adapter.py python/agent_tools/adopt_inspection.py python/agent_tools/adopt_verify.py tests/test_forge_adapter.py home/common/agent-skills/tests/test_adopt_verify.py | tail -1
```

Expected: exit 0 (`just build` runs the package's import check over the new module) and `6 files changed`. At the task's starting commit the first `grep` matches, so the script exits 1.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/github_remote.py python/agent_tools/forge_adapter.py python/agent_tools/adopt_inspection.py python/agent_tools/adopt_verify.py tests/test_forge_adapter.py home/common/agent-skills/tests/test_adopt_verify.py
```

Commit through `launch-commit` with the message `refactor(agent-tools): share the slug rule and bound registration's network reads (issue 126)`.
