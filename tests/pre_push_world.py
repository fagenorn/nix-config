"""A hermetic world for the managed pre-push hook (issue 672).

`PrePushWorld(test_case, ...)` builds a temporary directory holding a base policy, a
compiled policy, a row check, a `hooks/pre-push` that runs the guard source in its pre-push
mode, and an empty "user global config" that stands for the caller's own. `fixture(slug)`
returns an `agent_tools.guard.push_fixture.PushFixture` whose global git configuration sets only
`core.hooksPath` to this world's hooks directory. No test support here is a `TestCase`.
"""
import json
import os
import shlex
import shutil
import sys
import tempfile
import unittest
from collections.abc import Iterable
from itertools import count
from pathlib import Path

from agent_tools.guard.push_fixture import PushFixture, make_push_fixture

GUARD_SOURCE = Path(__file__).resolve().parents[1] / "home/common/claude-code/lifecycle_guard.py"
CHAIN_HOOK = Path(__file__).resolve().parents[1] / "home/common/claude-code/git-hooks/chain-hook"
REAL_GIT = shutil.which("git")

FAKE_DERIVE = """#!{python}
import json
import sys

argv = sys.argv[1:]
if len(argv) != 2 or argv[0] != "--repository":
    sys.stderr.write("unexpected fake-derive argv: " + repr(argv) + "\\n")
    sys.exit(64)
slug = argv[1]
rows = json.loads({rows!r})
report = {{"schema_version": 1, "repository": slug, "row": None, "refused": [],
          "cause": None, "outcome": "refused"}}
if slug in rows:
    report.update(row=rows[slug], outcome="derived")
print(json.dumps(report))
sys.exit(0 if slug in rows else 1)
"""


class PrePushWorld:
    def __init__(self, test_case: unittest.TestCase, *, owners=("fagenorn",), rows=None,
                 policy=None, derive_bin=None, derive_timeout=None, lfs_bin=None) -> None:
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.git_bin = REAL_GIT
        self.hooks = self.tmp / "hooks"
        self.hooks.mkdir()
        (self.tmp / "home").mkdir()
        self.base_policy = self.tmp / "base-policy.json"
        self.base_policy.write_text(json.dumps({
            "authorized_owners": list(owners), "integration_bases": {},
            "git_bin": REAL_GIT, "gh_bin": REAL_GIT, "jq_bin": REAL_GIT}), encoding="utf-8")
        if policy is None:
            policy = self.tmp / "policy.json"
            policy.write_text(json.dumps(
                {"derived_repositories": rows or {}, "derivation": None}), encoding="utf-8")
        self.policy = Path(policy)
        if derive_bin is None:
            derive_bin = self.tmp / "fake-derive"
            derive_bin.write_text(
                FAKE_DERIVE.format(python=sys.executable, rows=json.dumps(rows or {})),
                encoding="utf-8")
            derive_bin.chmod(0o755)
        self.derive_bin = Path(derive_bin)
        self.derive_timeout = derive_timeout
        self.lfs_bin = lfs_bin
        user_config = self.tmp / "user-gitconfig"
        user_config.write_text("", encoding="utf-8")
        self.env = {name: value for name, value in os.environ.items()
                    if not name.startswith("GIT_") and name not in ("CLAUDECODE",
                                                                    "XDG_CONFIG_HOME")}
        self.env.update(HOME=str(self.tmp / "home"), GIT_CONFIG_GLOBAL=str(user_config),
                        GIT_CONFIG_NOSYSTEM="1")
        self._fixtures = count()
        self.write_hook()

    def write_hook(self) -> Path:
        """Rewrite `hooks/pre-push` from the current attributes."""
        words = [shlex.quote(sys.executable), "-I", shlex.quote(str(GUARD_SOURCE)),
                 "--base-policy", shlex.quote(str(self.base_policy)),
                 "--policy", shlex.quote(str(self.policy)),
                 "--derive-bin", shlex.quote(str(self.derive_bin))]
        if self.derive_timeout is not None:
            words += ["--derive-timeout-seconds", shlex.quote(str(self.derive_timeout))]
        words += ["--mode", "pre-push"]
        if self.lfs_bin is not None:
            words += ["--git-lfs-bin", shlex.quote(str(self.lfs_bin))]
        hook = self.hooks / "pre-push"
        hook.write_text(f'#!/bin/sh\nexec {" ".join(words)} -- "$@"\n', encoding="utf-8")
        hook.chmod(0o755)
        return hook

    def fixture(self, slug: str) -> PushFixture:
        return make_push_fixture(self.tmp / f"fixture-{next(self._fixtures)}", slug,
                                 git_bin=REAL_GIT, env=self.env, hooks_path=self.hooks)

    def install_chain_shims(self, names: Iterable[str], lfs_bin: str = "") -> None:
        """Copy the chain shim into `hooks/<name>` for each name, placeholders filled."""
        source = CHAIN_HOOK.read_text(encoding="utf-8")
        source = source.replace("@git@", REAL_GIT).replace("@gitlfs@", lfs_bin)
        for name in names:
            shim = self.hooks / name
            shim.write_text(source, encoding="utf-8")
            shim.chmod(0o755)

    def lfs_recorder(self) -> Path:
        """Write a fake git-lfs that records its arguments and stdin; point the hook at it."""
        recorder = self.tmp / "fake-git-lfs"
        recorder.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> {shlex.quote(str(self.tmp / 'lfs.calls'))}\n"
            f"cat > {shlex.quote(str(self.tmp / 'lfs.stdin'))}\n", encoding="utf-8")
        recorder.chmod(0o755)
        self.lfs_bin = str(recorder)
        self.write_hook()
        return recorder
