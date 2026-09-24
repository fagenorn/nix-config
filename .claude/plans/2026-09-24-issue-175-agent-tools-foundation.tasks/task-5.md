# Task 5: Installed-layout launcher test

Decisions: D8, D11; parent D9 (seam 2), D13. Spec section "The installed-layout
test (D8)". Work from the worktree root.

**Files:**
- Create: `tests/test_agent_tools_launchers.py`
- Modify: `justfile` (the `agent-installed-skill-tests` recipe)

**Interfaces:**
- Consumes: the built `~/.agents/bin/agent-evidence` launcher from Task 4. Its
  bytes are a `#!` line, then
  `unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE`, then
  `exec <env>/bin/python3 -I -m agent_tools.agent_evidence "$@"`, then the
  trailing newline that `writeShellScript` adds. The recipe's existing
  `AGENT_SKILLS_INSTALLED_HOME` handling also feeds this test.
- Produces: `AgentToolsLauncherTest`, run only by
  `just agent-installed-skill-tests`. It is not added to `agent-workflow-tests`,
  because it has no source-side half (D8).

**Invariants:**
- The command table is read nowhere but the build. The test recognises
  launchers by content: every `.agents/bin` entry whose bytes contain
  `agent_tools` must fully match the launcher template, or the test fails with
  "is not a generated launcher".
- Only `agent-evidence` is required to be in the set. The full set is not
  pinned (D8).
- If the environment variable is unset, the class is skipped with a message
  naming the recipe. If it is set to something other than an absolute
  directory, every test fails (#153 D8, D16).
- Every subprocess has a 60 s timeout. The hostile root is a per-test
  temporary directory that is removed at cleanup.

- [ ] **Step 1: Write the test**

Create `tests/test_agent_tools_launchers.py`:

```python
"""Installed-layout seam for the agent_tools launchers (#175 D8, D11; parent D9).

Run: just agent-installed-skill-tests. That recipe builds first and passes the
built home-manager-files tree as AGENT_SKILLS_INSTALLED_HOME. Every
`.agents/bin` entry that names the package must be a generated launcher, and
each launcher must run its store module even with a fake `agent_tools` on the
`PYTHONPATH`, `NIX_PYTHONPATH` (with a `.pth` file) and working-directory
channels.
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"
INSTALLED_RECIPE = "just agent-installed-skill-tests"
PACKAGE_BYTES = b"agent_tools"
# `writeShellScript` prepends the shebang and appends a newline to the body.
LAUNCHER = re.compile(
    rb"#![^\n]+\n"
    rb"unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE\n"
    rb"exec (?P<python>/nix/store/[^/\s]+/bin/python3)"
    rb' -I -m agent_tools\.(?P<module>[a-z][a-z0-9_]*) "\$@"\n*'
)
MARKER = "HOSTILE agent_tools IMPORTED"
HOSTILE_EXIT = 97
TIMEOUT_SECONDS = 60


class AgentToolsLauncherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get(INSTALLED_HOME_ENV)
        if root is None:
            raise unittest.SkipTest(
                f"{INSTALLED_HOME_ENV} is unset; run `{INSTALLED_RECIPE}` to "
                "check the launchers the Nix build installs"
            )
        cls.root = Path(root)

    def setUp(self):
        self.assertTrue(
            self.root.is_absolute() and self.root.is_dir(),
            f"{INSTALLED_HOME_ENV}={str(self.root)!r} is not an absolute directory",
        )
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.hostile = Path(scratch.name).resolve()
        package = self.hostile / "agent_tools"
        package.mkdir()
        (package / "__init__.py").write_text(
            f"import sys\nsys.stderr.write({MARKER!r} + '\\n')\n"
            f"raise SystemExit({HOSTILE_EXIT})\n",
            encoding="utf-8",
        )
        # A site directory's .pth `import` line runs at startup, so this puts
        # the fake package ahead of the environment's site-packages.
        (self.hostile / "hostile.pth").write_text(
            f"import sys; sys.path.insert(0, {str(self.hostile)!r})\n",
            encoding="utf-8",
        )

    def launchers(self):
        """{command: (environment python, module)} for every entry naming the package."""
        found = {}
        for entry in sorted((self.root / ".agents" / "bin").iterdir()):
            data = entry.read_bytes()
            if PACKAGE_BYTES not in data:
                continue
            match = LAUNCHER.fullmatch(data)
            self.assertIsNotNone(
                match, f"{entry} names agent_tools but is not a generated launcher")
            found[entry.name] = (match["python"].decode(), match["module"].decode())
        return found

    def run_child(self, argv, env, cwd):
        return subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True,
                              timeout=TIMEOUT_SECONDS, check=False)

    def hostile_env(self):
        return dict(os.environ, PYTHONPATH=str(self.hostile),
                    NIX_PYTHONPATH=str(self.hostile))

    def test_the_command_table_generates_agent_evidence(self):
        self.assertIn("agent-evidence", self.launchers())

    def test_each_launcher_is_named_for_its_module(self):
        for name, (_python, module) in self.launchers().items():
            with self.subTest(launcher=name):
                self.assertEqual(name, module.replace("_", "-"))

    def test_a_hostile_agent_tools_on_every_channel_is_ignored(self):
        for name in self.launchers():
            with self.subTest(launcher=name):
                completed = self.run_child(
                    [str(self.root / ".agents" / "bin" / name), "--help"],
                    self.hostile_env(), self.hostile)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(completed.stdout.startswith(f"usage: {name} "),
                                completed.stdout[:200])
                self.assertNotIn(MARKER, completed.stdout + completed.stderr)

    def test_each_hostile_channel_is_live_without_the_launcher(self):
        # Each control opens exactly one channel, so a dead channel cannot hide
        # behind a live one.
        clean = {key: value for key, value in os.environ.items()
                 if key not in ("PYTHONPATH", "NIX_PYTHONPATH")}
        pythonpath_only = dict(clean, PYTHONPATH=str(self.hostile))
        nix_only = dict(clean, NIX_PYTHONPATH=str(self.hostile))
        for name, (python, module) in self.launchers().items():
            plain = [python, "-m", f"agent_tools.{module}", "--help"]
            controls = {
                # (a) PYTHONPATH alone reaches a plain run.
                "not isolated, PYTHONPATH only": (plain, pythonpath_only, self.root),
                # (a') the working directory alone reaches a plain run.
                "not isolated, working directory only": (plain, clean, self.hostile),
                # (b) -I alone leaves NIX_PYTHONPATH open, so the unset line
                # is load-bearing; if nixpkgs stops honouring it, this control
                # and that line go together (D11).
                "isolated, NIX_PYTHONPATH only": (
                    [python, "-I", "-m", f"agent_tools.{module}", "--help"],
                    nix_only, self.root),
            }
            for control, (argv, env, cwd) in controls.items():
                with self.subTest(launcher=name, control=control):
                    completed = self.run_child(argv, env, cwd)
                    self.assertEqual(completed.returncode, HOSTILE_EXIT, completed.stderr)
                    self.assertIn(MARKER, completed.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Show that it can fail**

Launcher and module both exist at the start of this task, so the red run uses
synthetic homes rather than the build:

```bash
T=$(mktemp -d); mkdir -p "$T/empty/.agents/bin" "$T/raw/.agents/bin"
printf '#!/bin/sh\nexec python3 -m agent_tools.agent_evidence "$@"\n' > "$T/raw/.agents/bin/agent-evidence"
AGENT_SKILLS_INSTALLED_HOME="$T/empty" python3 -m unittest tests/test_agent_tools_launchers.py 2>&1 | tail -1
AGENT_SKILLS_INSTALLED_HOME="$T/raw" python3 -m unittest tests/test_agent_tools_launchers.py 2>&1 | grep -c "is not a generated launcher"
AGENT_SKILLS_INSTALLED_HOME=relative/home python3 -m unittest tests/test_agent_tools_launchers.py 2>&1 | grep -c "is not an absolute directory"
python3 -m unittest tests/test_agent_tools_launchers.py 2>&1 | tail -1
rm -rf "$T"
```

Expected, in order:
- `FAILED (failures=1)`: the empty home has no `agent-evidence` launcher, so
  the floor assertion fails.
- A count of at least 1: a raw script that names the package fails as a
  malformed launcher.
- A count of at least 1: a relative path fails.
- `OK (skipped=1)`: without the variable, the class is skipped.

- [ ] **Step 3: Wire the recipe**

In `justfile`'s `agent-installed-skill-tests` body, change the last line,
`      home/common/agent-skills/tests/test_dispatch_contracts.py`, to end in ` \`.
Then add `      tests/test_agent_tools_launchers.py` as the new last line. Add no
`PYTHONPATH` prefix: this recipe runs built launchers, and neither suite imports
the package (D6).

- [ ] **Step 4: Verify (this is the issue's demo)**

Run: `just agent-installed-skill-tests 2>&1 | grep -E "AgentToolsLauncherTest|^Ran |^OK|FAILED"`
Expected: four `AgentToolsLauncherTest` lines ending in `ok`, then `Ran <N> tests`
and `OK`. The hostile run shows the store module answering `usage: agent-evidence …`
with a fake `agent_tools` on `PYTHONPATH`, on `NIX_PYTHONPATH` and in the
working directory. Controls (a), (a′) and (b) each open one channel and show it
is live without the launcher.

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK (skipped=1)`, with the same count as after Task 4.

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_tools_launchers.py justfile
git commit -m "test(agent-tools): prove the installed launchers ignore a hostile agent_tools"
```

The message ends with the trailer lines named in the plan's Global Constraints.
