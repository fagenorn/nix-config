"""Legacy ship-release state at the cutover to the release driver (#128 spec §6, D8).

The previous ship-release kept one file, `.superpowers/workflows/ship-release/state.json`.
`classify` reads it as untrusted input and puts it in one of four classes without importing
a field: nothing of it reaches the release store. `absent` and `completed` let a new release
start; `in_flight` and `unreadable` stop it (`legacy_release_in_flight`), because the driver
cannot tell a half-finished release from a damaged file. `retire` removes only a `completed`
file. Removing an in-flight or unreadable file is a human action, never the driver's: the
person decides that the old release is abandoned.

`classify` reads the file without following a symlink. It is `absent` when the file is
missing; `unreadable` when it is a symlink or not a regular file, larger than 65536 bytes, not
valid UTF-8 JSON (duplicate keys and non-finite constants included), not an object, or its keys
are not exactly `headSha`, `pr`, `prUrl`, `mergeSha`, `tag`, `releaseUrl`, `deployState`, or a
field has another type than the previous schema's (`headSha` and `deployState` strings, `pr`
null or an integer, the other four null or strings); `completed` when `releaseUrl` is set, or
`tag` is set with `pr` null, and `deployState` is `done` or `none`; and `in_flight` otherwise.

The release driver's `preview` and `run` refuse `legacy_release_in_flight` (repair
`release.legacy.finish`) for `in_flight` and `unreadable`, before any shape gate; the detail
names the class and path. `status` reports the `{class, path}` dict as its `legacy` member and
never refuses; `abandon` is not gated. In mode `new` only, `run` calls `retire` after the
confirmation checks and the store is made, immediately before `create`, which unlinks a
`completed` file (any other class raises `ValueError`), and its document gains `legacy:
"deleted"`; otherwise `legacy` is null. A resumed `run` never retires.
"""

import json
import os
import stat
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

LEGACY_PATH = ".superpowers/workflows/ship-release/state.json"
LEGACY_KEYS = frozenset(("headSha", "pr", "prUrl", "mergeSha", "tag", "releaseUrl",
                         "deployState"))
CLASSES = ("absent", "completed", "in_flight", "unreadable")
MAX_BYTES = 65536
FINISHED_DEPLOY_STATES = ("done", "none")
OPTIONAL_TEXTS = ("prUrl", "mergeSha", "tag", "releaseUrl")


def _typed(state: dict) -> bool:
    """Whether every field has the previous schema's type: `headSha` and `deployState`
    strings, `pr` null or an integer, the rest null or strings."""
    return (isinstance(state["headSha"], str) and isinstance(state["deployState"], str)
            and (state["pr"] is None or (type(state["pr"]) is int))
            and all(state[key] is None or isinstance(state[key], str)
                    for key in OPTIONAL_TEXTS))


def _read(path: Path) -> object:
    """The parsed file, or ValueError for anything that is not a plain, small JSON file."""
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("not a regular file")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
    except OSError as error:
        raise ValueError(f"cannot read: {error}") from error
    if len(raw) > MAX_BYTES:
        raise ValueError("file is larger than the limit")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("JSON nests too deeply") from error


def _classify_state(state: dict) -> str:
    published = state["releaseUrl"] is not None or (
        state["tag"] is not None and state["pr"] is None)
    if published and state["deployState"] in FINISHED_DEPLOY_STATES:
        return "completed"
    return "in_flight"


def classify(repo_root: Path) -> dict[str, str]:
    """`{"class": <one of CLASSES>, "path": <absolute path>}`; never follows a symlink."""
    path = repo_root / LEGACY_PATH
    try:
        path.lstat()
    except FileNotFoundError:
        return {"class": "absent", "path": str(path)}
    except OSError:
        return {"class": "unreadable", "path": str(path)}
    try:
        state = _read(path)
    except ValueError:
        return {"class": "unreadable", "path": str(path)}
    if not isinstance(state, dict) or set(state) != LEGACY_KEYS or not _typed(state):
        return {"class": "unreadable", "path": str(path)}
    return {"class": _classify_state(state), "path": str(path)}


def retire(repo_root: Path) -> None:
    """Delete a `completed` legacy file; any other class raises ValueError, touching nothing."""
    found = classify(repo_root)
    if found["class"] != "completed":
        raise ValueError(f"the legacy state at {found['path']} is {found['class']}, "
                         "not completed")
    Path(found["path"]).unlink()
