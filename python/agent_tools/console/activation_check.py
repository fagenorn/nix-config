"""`activation_check`: the verify script that this host runs the commit the console's Activate activated (#1193, AC4).

`python -m agent_tools.console.activation_check --merge SHA [--store PATH] [--repo-root PATH]`
reads the console's event store and reports whether the last page activation that succeeded
contains the merge commit SHA and is the configuration this host runs. The default store is
`service.default_store()`; the default repository root is the working directory.

Evidence. Let C be the commit of the last `activation.finished` row with `ok: true`, in `seq` order,
whatever its commit. Only that one row is judged, so an older success that contains the merge never
counts once a newer success exists (a later activation of an older commit, a rollback, ends the
evidence). `contains(merge, C)` is `git merge-base --is-ancestor merge C` in the repository root,
and merge equal to C counts as contained. A commit the repository lacks is fetched once, objects
only (`git fetch --no-tags --refmap= origin refs/heads/main`), and asked again; a containment still
undecided is not yet. The host's revision is `activation_run.host_revision()`: it must equal C.

Read-only. The store is opened `mode=ro` with `PRAGMA query_only = ON`, never through `EventLog`, so
a missing store is not created and an older-schema store is not migrated. A store whose
`PRAGMA user_version` is below `event_log.SCHEMA_VERSION` is unreadable: it has not been migrated
to the schema this build knows. A store at a newer schema is read normally, because the console
only migrates a store forward and a later merge may have bumped the version past the one this
check runs at; the query names `events(seq, kind, payload)` alone. The only write is the
objects-only fetch.

Output and exits, one JSON line with sorted keys. 0 met `{"commit": C, "revision": C, "status":
"met"}`; 1 not met `{"commit": C, "revision": <read or null>, "status": "not_met"}` (the last
success contains the merge, and the host runs another revision or none could be read); 75 not yet
`{"status": "waiting"}` (no success, or the last success does not contain the merge, or
containment could not be decided); 2 the store is absent or older than the current schema
(`{"reason", "status": "unreadable"}`). `verdict` is the pure core.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from agent_tools.console import activation_run, event_log, manager_check, service

NOT_YET = manager_check.NOT_YET
UNREADABLE = 2
_GIT_SECONDS = 120


def verdict(merge: str, rows: list[Mapping], revision: str | None,
            contains: Callable[[str, str], bool | None]) -> tuple[int, dict]:
    """The verdict on `activation.finished` payloads in `seq` order; see the module docstring."""
    last = None
    for payload in rows:
        if payload.get("ok") is True and isinstance(payload.get("commit"), str):
            last = payload["commit"]
    if last is None:
        return NOT_YET, {"status": "waiting"}
    if merge != last and not contains(merge, last):
        return NOT_YET, {"status": "waiting"}
    if revision == last:
        return 0, {"status": "met", "commit": last, "revision": revision}
    return 1, {"status": "not_met", "commit": last, "revision": revision}


def _ancestor(root: Path, merge: str, commit: str) -> bool | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", merge, commit],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=_GIT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(done.returncode)


def git_contains(root: Path) -> Callable[[str, str], bool | None]:
    """`merge-base --is-ancestor` in `root`, fetching the objects once when one is missing."""
    fetched = []

    def contains(merge: str, commit: str) -> bool | None:
        if merge == commit:
            return True
        answer = _ancestor(root, merge, commit)
        if answer is None and not fetched:
            fetched.append(True)
            try:
                subprocess.run(
                    ["git", "-C", str(root), "fetch", "--no-tags", "--refmap=", "origin",
                     "refs/heads/main"], stdin=subprocess.DEVNULL, capture_output=True,
                    timeout=_GIT_SECONDS, check=False)
            except (OSError, subprocess.SubprocessError):
                return None
            answer = _ancestor(root, merge, commit)
        return answer

    return contains


def read_rows(store: Path) -> list[dict]:
    """The `activation.finished` payloads in `seq` order; `sqlite3.Error` when unreadable."""
    return [payload for _, payload in read_stamped(store)]


def read_stamped(store: Path) -> list[tuple[str, dict]]:
    """The (`at`, payload) of every `activation.finished` row in `seq` order; `sqlite3.Error` when unreadable."""
    connection = sqlite3.connect(f"{store.resolve().as_uri()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version < event_log.SCHEMA_VERSION:
            raise sqlite3.DatabaseError(
                f"store schema is {version}, this build reads {event_log.SCHEMA_VERSION}")
        found = connection.execute(
            "SELECT at, payload FROM events WHERE kind = 'activation.finished' "
            "ORDER BY seq").fetchall()
    finally:
        connection.close()
    rows = []
    for at, text in found:
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and isinstance(at, str):
            rows.append((at, payload))
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="activation_check", description=__doc__.splitlines()[0])
    parser.add_argument("--merge", required=True, help="the merge commit the activation must contain")
    parser.add_argument("--store", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    return parser


def main(argv=None, *, revision=activation_run.host_revision) -> int:
    args = build_parser().parse_args(argv)
    store = args.store or service.default_store()
    try:
        rows = read_rows(store)
    except (sqlite3.Error, OSError) as error:
        manager_check._print({"reason": str(error), "status": "unreadable"})
        return UNREADABLE
    root = args.repo_root or Path.cwd()
    code, document = verdict(args.merge, rows, revision(), git_contains(root))
    manager_check._print(document)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
