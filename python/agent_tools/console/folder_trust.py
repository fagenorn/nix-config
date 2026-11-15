"""The console's folder trust: grant the client's workspace trust for a registered folder (#1078).

Why. The Claude Code client asks "do you trust this folder" the first time it runs in a folder, and
records the answer as `projects["<key>"].hasTrustDialogAccepted` in `$CLAUDE_CONFIG_DIR/.claude.json`
(`~/.claude.json` for the default account). Until it is `true`, the client withholds the folder's own
settings and hooks, so an agent started there by the console has no lifecycle guard. Registering a
project the owner approved grants that trust for every account, and nothing else does (no flag, env
var or settings key marks a folder trusted; ADR-console-033).

Key. `trust_key(root)` is the real path (`os.path.realpath`) of the main checkout's git root:
`git -C <root> rev-parse --path-format=absolute --git-common-dir`, its parent when its last segment
is `.git`, so a linked worktree and its main checkout share one key. git runs with no shell, `stdin`
and `stderr` from `DEVNULL` and `GIT_TIMEOUT` seconds; a non-zero exit, an `OSError` or a timeout is
None. It never raises.

Targets. `targets(home, profile_dirs)` lists `(name, file)` pairs: `("default", home/.claude.json)`
first when `home` is not None, then `(name, dir/.claude.json)` for every directory whose
`sessions.account_name` is not None, sorted by name.

Grant. `grant(path, key, *, attempts=ATTEMPTS, before_swap=None)` returns `GRANTED`, `ALREADY` or
`FAILED` (`RESULTS`). Only `projects[key].hasTrustDialogAccepted` changes in the parsed document
(`oauthAccount` and every other member, and every other member of the entry, are kept). A file whose
key already reads `true` is not written (`ALREADY`: inode and mtime unchanged). A file that is not a
JSON object, whose `projects` or entry is not an object, or a symbolic link (`os.lstat`) is never
written (`FAILED`). The mode is kept and a new file is 0600; no `.claude.json.trust-` temporary is
left on any outcome. The whole call runs under one module lock. The text is the parsed document
re-serialised with `json.dumps(indent=2, ensure_ascii=False)`.

No lock is shared with the client (none is documented, and the activation script rewrites
`~/.claude.json` without one), so the replacement is an exchanging rename (`swap`): the temporary
holding the merge and the file trade names in one step, and the document the rename displaced is in
hand. It is compared (bytes and `(st_dev, st_ino)`) with the document the merge was based on; a
different one was written by someone else, so it is merged again, its members kept, and the next
swap must displace this attempt's own merge. This closes the window between the last read and the
replacement that a compare-then-rename leaves open. A file that does not exist is created by an
exclusive `os.link` of the temporary; losing that race re-reads. After the swap the file is read
back: a key not `true` there (a writer replaced the merge) re-reads and retries and counts as an
attempt. `before_swap(attempt)` is a test seam called after the temporary is written and before the
swap.

After `attempts` displacements of a newer document the result is `FAILED` and the newest displaced
document is put back at the path unchanged (one more swap). A displaced foreign document stays in its
own file, never copied, until the next swap has merged it, so every exit that leaves it unmerged puts
it back the same way: a later attempt that refuses it (not JSON, not an object), an `OSError` from
the temporary or a swap, or the exhaustion above. If that put-back displaces a document that is not
the console's own merge, or cannot swap, the document is kept as a sibling `KEPT_PREFIX<n>` file, one
stderr line `folder_trust: kept <file name>` names it, and the result is `FAILED`. Nothing is
unlinked that a writer other than this module wrote, except a displaced document whose content has
been merged into the next write.

`swap(a, b)` is the exchanging rename through `ctypes.CDLL(None, use_errno=True)`: Linux
`renameat2(AT_FDCWD, a, AT_FDCWD, b, RENAME_EXCHANGE)` (Linux 3.15, glibc 2.28), Darwin
`renamex_np(a, b, RENAME_SWAP)` (macOS 10.12). A missing symbol raises `OSError(ENOSYS)`; a non-zero
return raises `OSError(errno)`. A host without it (`ENOSYS`, `EINVAL`, `ENOTSUP`, `EXDEV`) yields
`FAILED` with nothing written: there is no `os.replace` fallback.

Residual. A client that reads the console's interim merge in the instant between two swaps and later
writes from it is not detected (ADR-console-033).

Remove. `remove_entry(path, key, *, attempts=ATTEMPTS)` deletes the whole `projects[key]` entry
through the same protocol and returns `REMOVED`, `ABSENT` (no file, or no entry: nothing written) or
`FAILED`. Its one caller is the host check, restoring the trust its own throwaway root caused.

Row. `granted_row(cause, project, root, results)` is `("trust.granted", None, {"by": "owner",
"cause": cause, "project": project, "root": root, "profiles": [{"profile", "result"}, ...]})`,
one per grant the owner approved; `ValueError` unless `cause` is in `CAUSES`, `project` and `root`
are non-empty strings, every result is in `RESULTS` and every profile is `default` or accepted by
`account_add.refusal`. The kind is not in `KEPT_KINDS`. No file content is logged.
`failures(events, state=None)` folds a copy of `state`: for each valid row (re-validated with
`granted_row`; an invalid one is skipped) a `(root, profile)` with result `failed` is set to
`{"root", "project", "profile", "at"}` and one with `granted` or `already` is removed. An
`account.removal` row of outcome `removed` or `removed_signed_out_already` (`GONE_OUTCOMES`) drops
every pair of that profile, since a profile that no longer exists has no file left to check.

Card. `items(failures)` is the Check again card of every pair `failures` holds, ordered by `(at,
root, profile)`: reason `trust_failed`, key `trust/<profile>/<root>/<at>`, `project_id` null, the
`root`, `name` (the project), `profile`, title `Trust <project>`, headline `headline(project,
profile)` ("Agents cannot start in <project> under <profile> yet"), `why` the `failed_words` of the
pair, `command` the terminal command alone, the one option `CHECK_OPTION` ("Check again") with the
value `CHECK_VALUE` ("check"), `text` false and `waiting_since` the failure's time; no code or
exception word reaches it. `parse_check_request(body)` is the card's answer, exactly `{"root",
"profile"}` of non-empty strings with no control character; `ValueError` otherwise. `NOT_FAILED`
("that folder is not waiting for a trust check") is the service's refusal of a pair no failed row
holds.

Words. `TRUST_SENTENCE` is the sentence the page shows. `command(root, profile)` is
`cd <root> && CLAUDE_ACCOUNT=<profile> claude` (the root through `shlex.quote`) and
`failed_words(root, profile)` is `Run this in a terminal: <command>, then accept the prompt and
type /exit.`

Command. `folder-trust grant-registered --profile <name>` (module `main(argv=None) -> int`) grants
every registered project's trust in the one profile `<name>`, for the launcher's `add` (the
`--profile=<name>` form is used there, because a valid name may begin with `-`). A `<name>` that
`account_add.refusal` refuses prints `folder-trust: <reason>` on stderr and exits 2, as does a
profile directory under `CLAUDE_ACCOUNTS_DIR` (default `$HOME/.claude-accounts`) that does not exist
(`folder-trust: no account <name>`). Only `<that directory>/.claude.json` is written, never
`~/.claude.json` or another profile. The registry is `agent_platform.registry_path()`: absent exits 0
with no output; one that is not a valid registry prints `folder-trust: the project registry cannot be
read` and exits 1. For each project in order the key is `trust_key(root)` (None is `failed` with no
write), else `grant` runs; stdout gets one `<project_id>: <result>` line and, for `failed`, a second
line `  <failed_words(key or root, name)>`. The exit status is 1 when any result is `failed`, else 0.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from agent_tools.console import account_add, event_log, sessions
from agent_tools.project_contract import agent_platform

GRANTED = "granted"
ALREADY = "already"
FAILED = "failed"
RESULTS = (GRANTED, ALREADY, FAILED)
REMOVED = "removed"
ABSENT = "absent"
ATTEMPTS = 5
GIT_TIMEOUT = 10
CAUSES = ("apply", "register", "account", "check")
KEPT_PREFIX = ".claude.json.trust-kept-"
TEMP_PREFIX = ".claude.json.trust-"
CHECK_OPTION = "Check again"
CHECK_VALUE = "check"
GONE_OUTCOMES = ("removed", "removed_signed_out_already")
NOT_FAILED = "that folder is not waiting for a trust check"
TRUST_SENTENCE = "Registering lets agents run in this folder with the folder's own settings and hooks."

_AT_FDCWD = -100
_RENAME_EXCHANGE = 2
_RENAME_SWAP = 2
_NO_SWAP = (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EXDEV)
_LOCK = threading.Lock()


def _git_line(root: str, *args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", "-C", root, "rev-parse", "--path-format=absolute", *args],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT, check=False)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return os.fsdecode(done.stdout).rstrip("\n") or None


def trust_key(root: str) -> str | None:
    """The directory the client keys trust by: the main checkout, as the launcher computes it.

    A common directory named `.git` keys by its parent; any other one (a submodule or a
    `--separate-git-dir` checkout) keys by the checkout's own top level, as `claude-account` does.
    """
    common = _git_line(root, "--git-common-dir")
    if common is None:
        return None
    path = Path(common)
    if path.name == ".git":
        return os.path.realpath(path.parent)
    top = _git_line(root, "--show-toplevel")
    return os.path.realpath(top if top is not None else root)


def targets(home: Path | None, profile_dirs: Iterable[Path]) -> list[tuple[str, Path]]:
    found = []
    for directory in profile_dirs:
        name = sessions.account_name(directory)
        if name is not None:
            found.append((name, directory / ".claude.json"))
    found.sort(key=lambda pair: pair[0])
    if home is not None:
        found.insert(0, ("default", home / ".claude.json"))
    return found


def swap(a: Path, b: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    left, right = os.fsencode(os.fspath(a)), os.fsencode(os.fspath(b))
    if sys.platform == "darwin":
        call = getattr(libc, "renamex_np", None)
        if call is None:
            raise OSError(errno.ENOSYS, "renamex_np is not available")
        call.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        call.restype = ctypes.c_int
        result = call(left, right, _RENAME_SWAP)
    else:
        call = getattr(libc, "renameat2", None)
        if call is None:
            raise OSError(errno.ENOSYS, "renameat2 is not available")
        call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
                         ctypes.c_uint]
        call.restype = ctypes.c_int
        result = call(_AT_FDCWD, left, _AT_FDCWD, right, _RENAME_EXCHANGE)
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


class _Refused(Exception):
    """The document must not be written."""


class _Doc:
    """One read of a file: its bytes, `(st_dev, st_ino)` and permission bits."""

    def __init__(self, data: bytes, ident: tuple[int, int], mode: int):
        self.data = data
        self.ident = ident
        self.mode = mode


def _same(a: _Doc | None, b: _Doc | None) -> bool:
    if a is None or b is None:
        return a is b
    return a.data == b.data and a.ident == b.ident


def _read(path: Path) -> _Doc | None:
    """The file at `path`; None when absent; `_Refused` for a link; `OSError` otherwise."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        raise _Refused("link")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise _Refused("not a file")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    return _Doc(b"".join(chunks), (opened.st_dev, opened.st_ino), stat.S_IMODE(opened.st_mode))


def _parse(doc: _Doc | None, key: str) -> dict:
    if doc is None:
        return {}
    try:
        value = json.loads(doc.data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise _Refused("not JSON") from error
    if not isinstance(value, dict):
        raise _Refused("not an object")
    projects = value.get("projects", {})
    if not isinstance(projects, dict):
        raise _Refused("projects is not an object")
    if key in projects and not isinstance(projects[key], dict):
        raise _Refused("entry is not an object")
    return value


def _trusted(document: dict, key: str) -> bool:
    return document.get("projects", {}).get(key, {}).get("hasTrustDialogAccepted") is True


def _granted(document: dict, key: str) -> dict:
    merged = dict(document)
    projects = dict(merged.get("projects", {}))
    entry = dict(projects.get(key, {}))
    entry["hasTrustDialogAccepted"] = True
    projects[key] = entry
    merged["projects"] = projects
    return merged


def _without(document: dict, key: str) -> dict:
    merged = dict(document)
    projects = dict(merged.get("projects", {}))
    projects.pop(key, None)
    merged["projects"] = projects
    return merged


def _unlink(path: str | Path | None) -> None:
    if path is None:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _temp(directory: Path, data: bytes, mode: int) -> tuple[str, tuple[int, int]]:
    descriptor, name = tempfile.mkstemp(dir=directory, prefix=TEMP_PREFIX)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
            info = os.fstat(handle.fileno())
    except BaseException:
        _unlink(name)
        raise
    return name, (info.st_dev, info.st_ino)


def _keep(name: str, directory: Path) -> None:
    """Keep the document at `name` as a sibling `KEPT_PREFIX<n>` file and say so on stderr."""
    number = 0
    while True:
        kept = directory / f"{KEPT_PREFIX}{number}"
        try:
            os.link(name, kept)
        except FileExistsError:
            number += 1
            continue
        break
    _unlink(name)
    print(f"folder_trust: kept {kept.name}", file=sys.stderr)


def _restore(path: Path, held: str, ours: _Doc | None) -> None:
    """Put the foreign document held in the file `held` back at `path`; keep what it displaces.

    The displaced document is unlinked only when it is `ours`. When the swap cannot run the held
    file is kept as it is. Never raises an `OSError`.
    """
    directory = path.parent
    try:
        try:
            swap(Path(held), path)
        except OSError:
            _keep(held, directory)
            return
        try:
            displaced = _read(Path(held))
        except (_Refused, OSError):
            displaced = None
        if displaced is not None and ours is not None and _same(displaced, ours):
            _unlink(held)
        else:
            _keep(held, directory)
    except OSError:
        pass


def _write(path: Path, key: str, edit: Callable[[dict, str], dict],
           done: Callable[[dict, str], bool], attempts: int,
           before_swap: Callable[[int], None] | None) -> tuple[str, bool]:
    """Merge by `edit` into the file at `path` until `done` reads true there.

    Returns `("unchanged", True)` when it already was, `("changed", True)` once the read-back
    shows it, and `("failed", False)` otherwise. The newest displaced foreign document stays in
    the file `held` until the next swap has merged it; every exit that leaves it unmerged,
    a raised `_Refused` or `OSError` included, puts it back through `_restore`.
    """
    path = Path(path)
    content = expect = _read(path)
    held: str | None = None
    try:
        for attempt in range(attempts):
            document = _parse(content, key)
            if content is expect and done(document, key):
                return "unchanged", True
            merged = edit(document, key)
            text = (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            mode = content.mode if content is not None else 0o600
            name, ident = _temp(path.parent, text, mode)
            try:
                ours = _Doc(text, ident, mode)
                if before_swap is not None:
                    before_swap(attempt)
                if expect is None:
                    try:
                        os.link(name, path)
                    except FileExistsError:
                        content = expect = _read(path)
                        continue
                    displaced = None
                else:
                    try:
                        swap(Path(name), path)
                    except FileNotFoundError:
                        if held is not None:
                            _keep(held, path.parent)
                            held = None
                        content = expect = _read(path)
                        continue
                    try:
                        displaced = _read(Path(name))
                    except (_Refused, OSError):
                        _restore(path, name, ours)
                        name = ""
                        raise
                    if held is not None:
                        _unlink(held)
                        held = None
                    if not _same(displaced, expect):
                        held, name = name, ""
            finally:
                _unlink(name or None)
            if expect is None or _same(displaced, expect):
                back = _read(path)
                if back is not None and _is_done(back, key, done):
                    return "changed", True
                content = expect = back
                continue
            content, expect = displaced, ours
        if held is not None:
            _restore(path, held, expect)
            held = None
        return "failed", False
    except BaseException:
        if held is not None:
            _restore(path, held, expect)
        raise


def _is_done(doc: _Doc, key: str, done: Callable[[dict, str], bool]) -> bool:
    try:
        return done(_parse(doc, key), key)
    except _Refused:
        return False


def _run(path: Path, key: str, edit, done, attempts, before_swap) -> tuple[str, bool]:
    with _LOCK:
        try:
            return _write(path, key, edit, done, attempts, before_swap)
        except (_Refused, OSError):
            return "failed", False


def grant(path: Path, key: str, *, attempts: int = ATTEMPTS,
          before_swap: Callable[[int], None] | None = None) -> str:
    outcome, _ = _run(path, key, _granted, _trusted, attempts, before_swap)
    return {"unchanged": ALREADY, "changed": GRANTED}.get(outcome, FAILED)


def _gone(document: dict, key: str) -> bool:
    return key not in document.get("projects", {})


def remove_entry(path: Path, key: str, *, attempts: int = ATTEMPTS) -> str:
    outcome, _ = _run(path, key, _without, _gone, attempts, None)
    return {"unchanged": ABSENT, "changed": REMOVED}.get(outcome, FAILED)


def granted_row(cause: str, project: str, root: str,
                results: Sequence[tuple[str, str]]) -> tuple[str, None, dict]:
    if cause not in CAUSES:
        raise ValueError(f"not a cause: {cause!r}")
    for name, value in (("project", project), ("root", root)):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")
    profiles = []
    for profile, result in results:
        if result not in RESULTS:
            raise ValueError(f"not a result: {result!r}")
        if not isinstance(profile, str) or (
                profile != "default" and account_add.refusal(profile) is not None):
            raise ValueError(f"not a profile: {profile!r}")
        profiles.append({"profile": profile, "result": result})
    return (event_log.TRUST_GRANTED, None,
            {"by": "owner", "cause": cause, "project": project, "root": root,
             "profiles": profiles})


def failures(events: Iterable[event_log.Event],
             state: dict[tuple[str, str], dict] | None = None) -> dict[tuple[str, str], dict]:
    folded = dict(state or {})
    for event in events:
        if event.kind == event_log.ACCOUNT_REMOVAL:
            profile = event.payload.get("profile")
            if event.payload.get("outcome") in GONE_OUTCOMES and isinstance(profile, str):
                folded = {slot: one for slot, one in folded.items() if slot[1] != profile}
            continue
        if event.kind != event_log.TRUST_GRANTED:
            continue
        payload = event.payload
        try:
            row = granted_row(payload["cause"], payload["project"], payload["root"],
                              [(item["profile"], item["result"]) for item in payload["profiles"]])
        except (TypeError, KeyError, ValueError):
            continue
        if row[2] != payload:
            continue
        for item in row[2]["profiles"]:
            slot = (row[2]["root"], item["profile"])
            if item["result"] == FAILED:
                folded[slot] = {"root": row[2]["root"], "project": row[2]["project"],
                                "profile": item["profile"], "at": event.at}
            else:
                folded.pop(slot, None)
    return folded


def command(root: str, profile: str) -> str:
    return f"cd {shlex.quote(root)} && CLAUDE_ACCOUNT={profile} claude"


def failed_words(root: str, profile: str) -> str:
    return f"Run this in a terminal: {command(root, profile)}, then accept the prompt and type /exit."


def headline(project: str, profile: str) -> str:
    return f"Agents cannot start in {project} under {profile} yet"


def items(failed: dict[tuple[str, str], dict]) -> list[dict]:
    found = []
    for (root, profile), one in sorted(failed.items(), key=lambda pair: (
            pair[1]["at"], pair[0][0], pair[0][1])):
        project, at = one["project"], one["at"]
        ask = headline(project, profile)
        found.append({
            "type": "inbox_item", "reason": "trust_failed", "key": f"trust/{profile}/{root}/{at}",
            "project_id": None, "root": root, "name": project, "profile": profile,
            "title": f"Trust {project}", "plan_id": None, "id": None, "subject": None,
            "headline": ask, "why": failed_words(root, profile), "command": command(root, profile),
            "lines": [], "refusal": None, "more_questions": 0, "text": False,
            "questions": [{"question": ask, "options": [CHECK_OPTION], "chosen": None,
                           "recommended": None, "recommended_index": None}],
            "values": [CHECK_VALUE], "items": [], "answers": [], "answered": False,
            "waiting_since": at})
    return found


def parse_check_request(body: bytes) -> tuple[str, str]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != {"root", "profile"}:
        raise ValueError("wrong members")
    root, profile = value["root"], value["profile"]
    for text in (root, profile):
        if not isinstance(text, str) or not text:
            raise ValueError("wrong types")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
            raise ValueError("control character")
    return root, profile


def _accounts_dir() -> Path:
    configured = os.environ.get("CLAUDE_ACCOUNTS_DIR")
    return Path(configured) if configured else Path(os.environ["HOME"]) / ".claude-accounts"


def _grant_registered(name: str) -> int:
    reason = account_add.refusal(name)
    if reason is not None:
        print(f"folder-trust: {reason}", file=sys.stderr)
        return 2
    profile = _accounts_dir() / "profiles" / name
    if not profile.is_dir():
        print(f"folder-trust: no account {name}", file=sys.stderr)
        return 2
    try:
        projects = agent_platform.read_registry()
    except (agent_platform.PlatformManifestError, OSError, RuntimeError, KeyError):
        print("folder-trust: the project registry cannot be read", file=sys.stderr)
        return 1
    status = 0
    for entry in projects:
        key = trust_key(entry["root"])
        result = FAILED if key is None else grant(profile / ".claude.json", key)
        print(f"{entry['project_id']}: {result}")
        if result == FAILED:
            print(f"  {failed_words(key or entry['root'], name)}")
            status = 1
    return status


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="folder-trust", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    registered = commands.add_parser(
        "grant-registered", help="grant every registered project's folder trust in one profile")
    registered.add_argument("--profile", required=True, metavar="NAME")
    arguments = parser.parse_args(argv)
    return _grant_registered(arguments.profile)


if __name__ == "__main__":
    raise SystemExit(main())
