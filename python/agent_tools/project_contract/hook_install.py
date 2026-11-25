"""Installing a project's missing dev-shell hooks during `adopt-project apply`.

A host that manages a global `core.hooksPath` hands every repository the managed
shims, and the devenv git-hooks installer, run on every shell entry, refuses to
install into a repository while any hooks path is visible. So the hooks a
project declares in `devenv.nix` never land in `<git-common-dir>/hooks`, and the
adoption commit that goes through the dev shell runs without them.

When this runs. Only when the contract names a commit environment, the
adoption worktree's `HEAD` tracks a `devenv.nix` that declares devenv git hooks
(`declares_hooks`), the repository's local configuration sets no
`core.hooksPath`, and `<git-common-dir>/hooks` holds none of `COMMIT_HOOKS`
(`left_alone`). Anything else leaves the repository as it is, with no process
run: a project that sets its own hooks path or already has a hook installed is
never changed, and a dev shell that declares no hooks is never entered for it.

The command. `install` runs the commit environment's own argv followed by
`INSTALL_COMMAND`, so the shell is entered and exits at once, in the same
adoption worktree and through the same environment as the commit that follows
it, which keeps the installer's per-worktree link current for that commit. Its
environment is apply's, plus `MASK`: `GIT_CONFIG_GLOBAL` set to the null device
for this one command, which hides the managed hooks path from the installer
alone. System configuration is left visible; no other command of apply gets the
mask, so the commit itself still runs under the managed hooks.

On every outcome of the install run, a success, a non-zero exit, a timeout and a
launch failure, the installer's own write of a local `core.hooksPath` is
removed in a `finally`, because a local hooks path would take the managed hooks,
the pre-push guard included, out of the repository. A hooks path that cannot be
removed fails the install. A failed install is refused `adopt.commit.failed`
with `commit_output` `{"hook": None, "exit": None, "lines": [...]}`, retained
like a failed commit, and apply does not commit. `local_hooks_paths` and
`restore_hooks_paths` let apply put the repository's local values back after
the commit, whichever way the commit ended, since the commit's own shell entry
may write one.

The limit. The hook this install puts in place is installed under the
installer's link in the adoption worktree. A later dev-shell entry that runs
unmasked in a worktree whose untracked `.pre-commit-config.yaml` link is missing
or stale (any other worktree of the repository, the owner's checkout included)
will uninstall that hook again. It also writes a local hooks path, which takes
the managed hooks, the pre-push guard included, out of the repository. For a
left-alone project whose hook a pre-commit tool installed, the adoption commit's
own shell entry in the fresh adoption worktree is such an entry: apply puts the
hooks path back, but the removed hook stays removed.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from agent_tools.project_contract import adopt_apply, adopt_inspection

COMMIT_HOOKS: tuple[str, ...] = ("pre-commit", "prepare-commit-msg", "commit-msg")
MASK: dict[str, str] = {"GIT_CONFIG_GLOBAL": os.devnull}
INSTALL_COMMAND: tuple[str, ...] = ("true",)
TEXT_LIMIT: int = 1 << 20

TOKEN = re.compile(r"""[\w'-]+|"_*"|==|[{}()\[\];=:@.?,]|\S""")
OPENERS, CLOSERS = "({[", ")}]"
NAME = re.compile(r"""[\w'-]+|"_*\"""")
MODULE_LEAD = (None, ":", "@", "in", "rec", ";")
HOOKS_PATH = "core.hooksPath"
ROOTS = ("git-hooks", "pre-commit")
DEEPEST = 5  # `config.<root>.hooks.<name>.enable`, the longest path `_switch` reads
BEYOND = ("",) * (DEEPEST + 1)  # stands for any path longer than `DEEPEST`


def installed(hooks_dir: Path) -> list[str]:
    """The `COMMIT_HOOKS` names that are executable regular files in `hooks_dir`."""
    return [name for name in COMMIT_HOOKS
            if (hooks_dir / name).is_file()
            and os.access(hooks_dir / name, os.X_OK)]


def left_alone(local_hooks_path: str | None, hooks_dir: Path) -> bool:
    """Whether the repository already decides its own hooks."""
    return local_hooks_path is not None or bool(installed(hooks_dir))


def _code(text: str) -> str:
    """`text` with each comment a space and each string literal's inside `_` characters.

    Nix strings (`"..."` and `''...''`, with `${...}`) are strings, so a `/*` or a `#`
    inside one starts no comment and a setting named inside one is no setting.
    """
    out: list[str] = []
    strings: list[tuple[str, int]] = []  # (opening quote, brace depth of the code around it)
    in_string, depth, i, n = False, 0, 0, len(text)
    while i < n:
        char = text[i]
        if not in_string:
            if char == "#":
                end = text.find("\n", i)
                i = n if end < 0 else end
                out.append(" ")
            elif text.startswith("/*", i):
                end = text.find("*/", i + 2)
                i = n if end < 0 else end + 2
                out.append(" ")
            elif char == '"' or text.startswith("''", i):
                quote = '"' if char == '"' else "''"
                strings.append((quote, depth))
                in_string, depth = True, 0
                out.append(quote)
                i += len(quote)
            else:
                if char == "{":
                    depth += 1
                elif char == "}" and depth == 0 and strings:
                    in_string = True  # the end of a `${...}` interpolation
                    i += 1
                    continue
                elif char == "}":
                    depth = max(depth - 1, 0)
                out.append(char)
                i += 1
            continue
        quote = strings[-1][0]
        if text.startswith("${", i):
            in_string, depth = False, 0
            out.append("_")
            i += 2
        elif quote == '"' and char == "\\":
            out.append("__")
            i += 2
        elif quote == '"' and char == '"':
            in_string, depth = False, strings.pop()[1]
            out.append('"')
            i += 1
        elif quote != '"' and text.startswith(("'''", "''$", "''\\"), i):
            out.append("___")
            i += 3
        elif quote != '"' and text.startswith("''", i):
            in_string, depth = False, strings.pop()[1]
            out.append("''")
            i += 2
        else:
            out.append("_" if char != "\n" else "\n")
            i += 1
    return "".join(out)


def _group_end(tokens: list[str], pos: int) -> int:
    """The index after the bracketed group that opens at `pos`, or the end of `tokens`."""
    depth = 0
    for i in range(pos, len(tokens)):
        depth += tokens[i] in OPENERS
        depth -= tokens[i] in CLOSERS
        if depth <= 0:
            return i + 1
    return len(tokens)


def _value_end(tokens: list[str], pos: int) -> int:
    """The index of the `;` that ends the value at `pos`, or of the `}` that closes its set.

    A bracketed group and a `let ... in` are part of the value, whatever they hold.
    """
    depth = lets = 0
    for i in range(pos, len(tokens)):
        token = tokens[i]
        if token in OPENERS:
            depth += 1
        elif token in CLOSERS:
            if depth == 0:
                return i
            depth -= 1
        elif token == "let":
            lets += 1
        elif token == "in":
            lets = max(lets - 1, 0)
        elif token == ";" and depth == 0 and lets == 0:
            return i
    return len(tokens)


def _let_end(tokens: list[str], pos: int) -> int:
    """The index after the `in` that ends the `let` whose keyword sits before `pos`."""
    lets = 1
    for i in range(pos, len(tokens)):
        lets += tokens[i] == "let"
        lets -= tokens[i] == "in"
        if lets == 0:
            return i + 1
    return len(tokens)


def _path(tokens: list[str], pos: int) -> tuple[tuple[str, ...], int]:
    """The dotted attribute path at `pos` (empty when there is none) and the index after it."""
    names: list[str] = []
    while pos < len(tokens) and NAME.fullmatch(tokens[pos]):
        names.append(tokens[pos])
        pos += 1
        if pos < len(tokens) and tokens[pos] == ".":
            pos += 1
        else:
            return tuple(names), pos
    return (), pos


def _switch(path: tuple[str, ...]) -> bool:
    """Whether `path` is `<root>.hooks.<name>.enable`, a leading `config` aside."""
    path = path[1:] if path[:1] == ("config",) else path
    return len(path) == 4 and path[0] in ROOTS and path[1] == "hooks" and path[3] == "enable"


def declares_hooks(text: str) -> bool:
    """Whether a `devenv.nix` text explicitly switches a devenv git hook on.

    Reads only `git-hooks.hooks.<name>.enable = true;` (or `pre-commit`), dotted or nested, in the top
    set (also under `config`); all else reads as no hooks, as a false positive promises a missing install.
    """
    if not any(root in text for root in ROOTS):
        return False
    tokens = TOKEN.findall(_code(text))
    n, i = len(tokens), 0
    sets: list[tuple[str, ...]] = []  # the attribute path of each open set
    previous: str | None = None
    while i < n:
        token = tokens[i]
        if not sets:
            if token == "let":
                i, previous = _let_end(tokens, i + 1), "in"
            elif token == "{" and previous in MODULE_LEAD:
                sets.append(())
                i, previous = i + 1, "{"
            elif token in OPENERS:
                i = _group_end(tokens, i)
                previous = tokens[i - 1]
            else:
                i, previous = i + 1, token
            continue
        if token == "}":
            sets.pop()
            previous = "}"
            i += 1
            continue
        names, after = _path(tokens, i)
        if names and tokens[after:after + 1] == ["="]:
            path, value = (*sets[-1], *names), after + 1
            if len(path) > DEEPEST:
                path = BEYOND  # no switch lies below it, and a nested set stores no ancestor copy
            if tokens[value:value + 1] == ["{"]:
                sets.append(path)
                i = value + 1
                continue
            if tokens[value:value + 2] == ["true", ";"] and _switch(path):
                return True
        start = i
        i = _value_end(tokens, i)
        if i < n and tokens[i] == ";":
            i += 1
        elif i == start:
            i += 1
    return False


def declared(worktree: Path) -> bool:
    """Whether `HEAD` of `worktree` tracks a `devenv.nix` that declares hooks."""
    code, kind = adopt_inspection.run_git(worktree, "cat-file", "-t",
                                          "HEAD:devenv.nix")
    if code != 0 or kind.strip() != b"blob":
        return False
    code, size = adopt_inspection.run_git(worktree, "cat-file", "-s",
                                          "HEAD:devenv.nix")
    if code != 0 or not size.strip().isdigit() or int(size) > TEXT_LIMIT:
        return False
    code, text = adopt_inspection.run_git(worktree, "cat-file", "blob",
                                          "HEAD:devenv.nix")
    return code == 0 and declares_hooks(text.decode("utf-8", "replace"))


def local_hooks_paths(root: Path) -> list[str] | None:
    """The repository's local `core.hooksPath` values; None when git cannot say."""
    code, out = adopt_inspection.run_git(
        root, "config", "--local", "--get-all", HOOKS_PATH)
    if code == 1:
        return []
    if code != 0:
        return None
    return out.decode("utf-8", "replace").splitlines()


def restore_hooks_paths(root: Path, before: list[str]) -> None:
    """Put the repository's local `core.hooksPath` values back to `before`."""
    if local_hooks_paths(root) == before:
        return
    code, _ = adopt_inspection.run_git(
        root, "config", "--local", "--unset-all", HOOKS_PATH)
    failed = code not in (0, 5)
    for value in before:
        if failed:
            break
        code, _ = adopt_inspection.run_git(
            root, "config", "--local", "--add", HOOKS_PATH, value)
        failed = code != 0
    if failed:
        raise adopt_apply.environment_failure([
            "the commit environment left a hooks path in the repository's "
            "configuration that could not be put back"])


def withdrawn(root: Path) -> adopt_inspection.AdoptError | None:
    """Remove any local hooks path; the refusal when one could not be removed."""
    code, _ = adopt_inspection.run_git(
        root, "config", "--local", "--get-all", HOOKS_PATH)
    if code == 1:
        return None
    if code == 0:
        code, _ = adopt_inspection.run_git(
            root, "config", "--local", "--unset-all", HOOKS_PATH)
        if code == 0:
            return None
    return adopt_apply.environment_failure([
        "the hook install left a hooks path in the repository's "
        "configuration that could not be removed"])


def hooks_directory(root: Path) -> Path | None:
    """`<git-common-dir>/hooks`, or None when git does not print it."""
    code, out = adopt_inspection.run_git(
        root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    printed = out.decode("utf-8", "replace").strip()
    return Path(printed) / "hooks" if code == 0 and printed else None


def install(root: Path, worktree: Path, environment: dict) -> list[str] | None:
    """Install the missing hooks with the global hooks path masked, returning the `COMMIT_HOOKS` installed.

    None, with no process run, when the repository is left alone, git cannot answer, or the
    worktree's `devenv.nix` declares no hooks; an `AdoptError` on a failed run.
    """
    code, _ = adopt_inspection.run_git(root, "config", "--local",
                                       "--get-all", HOOKS_PATH)
    if code != 1:
        return None
    hooks_dir = hooks_directory(root)
    if hooks_dir is None or left_alone(None, hooks_dir) \
            or not declared(worktree):
        return None
    name = environment["id"]
    argv = environment["argv"]
    failure = None
    try:
        with tempfile.TemporaryFile() as output:
            try:
                status = adopt_apply.run_leashed(
                    [*argv, *INSTALL_COMMAND], cwd=environment["cwd"],
                    env={**adopt_apply.environment_env(), **MASK},
                    stdout=output,
                    timeout=adopt_apply.ENVIRONMENT_TIMEOUT_SECONDS)
                reason = (f"exited {status}" if status != 0 else None)
            except subprocess.TimeoutExpired:
                reason = ("did not finish within "
                          f"{adopt_apply.ENVIRONMENT_TIMEOUT_SECONDS} seconds")
            except FileNotFoundError:
                reason = f"could not be started: {argv[0]} was not found"
            except OSError as error:
                reason = ("could not be started: "
                          f"{error.strerror or 'an error'}")
            except ValueError:
                reason = ("could not be started: an argument contains a NUL "
                          "character")
            if reason is not None:
                failure = adopt_apply.environment_failure([
                    f"the hook install through the commit environment command "
                    f"{name} {reason}",
                    *adopt_apply.commit_output_lines(
                        *adopt_apply.read_tail(output))])
    finally:
        removal = withdrawn(root)
        if removal is not None:
            raise removal from failure
    if failure is not None:
        raise failure
    return installed(hooks_dir)
