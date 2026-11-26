"""Git for the guard suite's sandbox repositories, isolated from the host.

`SandboxGit(directory)` writes a configuration of its own under `directory` and exposes the
environment that makes `git` read only that: `GIT_CONFIG_GLOBAL` names it, `GIT_CONFIG_NOSYSTEM`
drops the system file, every other `GIT_*` variable and the agent-session marker are removed,
and its `core.hooksPath` is an empty directory. A sandbox push therefore reaches its local bare
remote whatever the host's global hooks path and session are. No test support here is a `TestCase`.
"""
import os
import subprocess
from pathlib import Path

SESSION_VARIABLES = ("CLAUDECODE",)


class SandboxGit:
    def __init__(self, directory):
        directory = Path(directory)
        hooks = directory / "sandbox-hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        config = directory / "sandbox-gitconfig"
        config.write_text(
            f"[core]\n\thooksPath = {hooks}\n"
            "[user]\n\tname = t\n\temail = t@t\n"
            "[commit]\n\tgpgsign = false\n"
            "[tag]\n\tgpgsign = false\n",
            encoding="utf-8",
        )
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("GIT_") and k not in SESSION_VARIABLES}
        env.update(GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM="1")
        self.env = env

    def run(self, argv, cwd=None):
        """Run `argv` (a full command line, `git` first) in the sandbox environment."""
        return subprocess.run(argv, cwd=cwd, env=self.env, check=True,
                              capture_output=True, text=True)

    def git(self, *argv, cwd=None):
        return self.run(["git", *argv], cwd=cwd).stdout

    def push(self, cwd, *argv):
        """`git push` in `cwd`, which reaches its remote whatever the host's hooks say."""
        return self.git("push", "--quiet", *argv, cwd=cwd)
