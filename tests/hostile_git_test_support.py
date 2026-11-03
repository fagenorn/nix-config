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
    `GIT_DIFF_OPTS` and `GIT_CONFIG_NOSYSTEM=1`. `HOME` stays `base`'s, which the caller owns.

    The setup's own Git runs under `base` without any `GIT_*` variable, with `GIT_CONFIG_NOSYSTEM=1` and
    `GIT_CONFIG_GLOBAL` set to the null device, so no inherited routing variable or host configuration can
    point its writes at another repository."""
    owned = Path(owned)
    attributes, order = _write(owned / "attributes", NO_DIFF), _write(owned / "order", "*.md\n*\n")
    env = {k: v for k, v in base.items() if not k.startswith("GIT_") and k != "XDG_CONFIG_HOME"}
    setup = dict(env, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
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
            return subprocess.run(["git", "-C", str(repo), *args], env=setup,
                                  check=True, capture_output=True, text=True).stdout.strip()
        _write(Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "info/attributes", NO_DIFF)
        if git("rev-parse", "--is-bare-repository") == "false":
            _write(Path(git("rev-parse", "--show-toplevel")) / ".gitattributes", NO_DIFF)
        git("config", "diff.orderFile", order)
    return env
