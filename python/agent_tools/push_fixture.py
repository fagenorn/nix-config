"""A hermetic git push fixture over a fake ssh transport (issue 672 D9).

`make_push_fixture` builds a work tree whose `origin` is `git@github.com:<slug>.git`. A
repository-local `core.sshCommand` carries every ssh transport to a local bare repository
under `<root>/remotes/<slug>.git`, so no push ever leaves the machine. The fixture alone
decides the configuration of every git process it runs: the stored environment drops each
`GIT_*` variable and `CLAUDECODE` of the caller, points `GIT_CONFIG_GLOBAL` at a file holding
only `core.hooksPath`, ignores the system configuration and allows only the `ssh` and `file`
transports, so no URL rewrite in the caller's own configuration can apply. Standard library
only.
"""
import os
import shlex
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

ZERO_SHA = "0" * 40
GIT_TIMEOUT_SECONDS = 120

FAKE_SSH_SOURCE = """#!{python} -I
import os
import shlex
import sys

GIT = {git!r}
REMOTES = {remotes!r}

words = shlex.split(sys.argv[-1]) if len(sys.argv) > 1 else []
if len(words) != 2 or words[0] not in ("git-receive-pack", "git-upload-pack"):
    sys.stderr.write("fake ssh: unsupported command " + repr(sys.argv[1:]) + "\\n")
    sys.exit(64)
program, path = words
os.execv(GIT, [GIT, program[len("git-"):], os.path.join(REMOTES, path.lstrip("/"))])
"""


class PushFixture:
    def __init__(self, root: Path, work: Path, slug: str, git_bin: str,
                 env: dict[str, str]) -> None:
        self.root = root
        self.work = work
        self.slug = slug
        self.git_bin = git_bin
        self.env = env

    def git(self, *args: str, extra_env: Mapping[str, str] | None = None,
            input: str | None = None,
            cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run git in the work tree (or `cwd`) under the fixture environment."""
        return subprocess.run(
            [self.git_bin, *args], cwd=cwd or self.work, env={**self.env, **(extra_env or {})},
            input=input, capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS,
            check=False)

    def _checked(self, *args: str, cwd: Path | None = None) -> str:
        done = self.git(*args, cwd=cwd)
        if done.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr}")
        return done.stdout

    def add_remote(self, slug: str) -> Path:
        """Create the bare remote for `slug` from the work tree's current `main`."""
        bare = self.root / "remotes" / f"{slug}.git"
        bare.parent.mkdir(parents=True, exist_ok=True)
        self._checked("clone", "-q", "--bare", "--single-branch", "--branch", "main",
                      f"file://{self.work}", str(bare))
        return bare

    def commit(self, message: str) -> str:
        """Make an empty commit on the current branch and return its sha."""
        self._checked("commit", "--allow-empty", "-q", "-m", message)
        return self._checked("rev-parse", "HEAD").strip()

    def remote_ref(self, slug: str, ref: str) -> str | None:
        """The sha `ref` names in `slug`'s bare repository, or None."""
        bare = self.root / "remotes" / f"{slug}.git"
        done = self.git("--git-dir", str(bare), "rev-parse", "--verify", "--quiet", ref)
        return done.stdout.strip() if done.returncode == 0 else None


def make_push_fixture(root: Path, slug: str, *, git_bin: str, env: Mapping[str, str],
                      hooks_path: Path) -> PushFixture:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    gitconfig = root / "gitconfig"
    gitconfig.write_text(f"[core]\n\thooksPath = {hooks_path}\n", encoding="utf-8")
    fixture_env = {name: value for name, value in env.items()
                   if not name.startswith("GIT_") and name != "CLAUDECODE"}
    fixture_env.update(GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1",
                       GIT_ALLOW_PROTOCOL="ssh:file")
    work = root / "work"
    fake_ssh = root / "fake-ssh"
    fake_ssh.write_text(
        FAKE_SSH_SOURCE.format(python=sys.executable, git=git_bin,
                               remotes=str(root / "remotes")), encoding="utf-8")
    fake_ssh.chmod(0o755)
    fixture = PushFixture(root, work, slug, git_bin, fixture_env)
    fixture._checked("init", "-q", "-b", "main", str(work), cwd=root)
    for key, value in (("user.name", "fixture"), ("user.email", "fixture@example.invalid"),
                       ("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                       ("core.sshCommand", shlex.quote(str(fake_ssh)))):
        fixture._checked("config", key, value)
    fixture.commit("initial")
    fixture.add_remote(slug)
    fixture._checked("remote", "add", "origin", f"git@github.com:{slug}.git")
    fixture._checked("fetch", "-q", "origin")
    fixture._checked("remote", "set-head", "origin", "main")
    fixture._checked("branch", "-q", "--set-upstream-to=origin/main", "main")
    return fixture
