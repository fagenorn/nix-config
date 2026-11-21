"""`release_card`: the release card, outside any sprint, and its poster (#1401, D2, P2-P5).

A release card asks the owner to approve one release candidate, the pair (`commit`, `version`),
before the release command may run it. It is two rows of the console's event log and a fold over
them; nothing else stores it, and no sprint, manager or project owns it.

Rows. `event_log.RELEASE_CARD_POSTED` carries exactly `{commit, version}` with a null project;
`event_log.RELEASE_CARD_ANSWERED` carries exactly `{card, answer}`, `card` being the posted row's
`seq` and `answer` one of `ANSWERS`. The pair is valid exactly when the release driver accepts it:
`valid_pair` uses `release_profile.COMMIT_PATTERN` and `VERSION_PATTERN` and has no regex of its
own. `posted_row`, `answered_row`, `parse_post` and `parse_answer` build and read those shapes and
raise `ValueError` for anything else; the parsers decode strict JSON (a repeated key, NaN and a
non-object are refused).

Fold (`cards`). A posted row counts only when its payload is exactly `{commit, version}` and
`valid_pair` holds; it adds `Card(seq, commit, version, at, OPEN)`. An answered row counts only
when its payload is exactly `{card, answer}` (a row with a `by` member counts for nothing, so a
guest's answer approves nothing), `card` names a folded card whose state is `OPEN` and `answer` is
in `ANSWERS`; it sets that card to `APPROVED` or `DECLINED`. Every other row, and a second answer,
changes nothing. `cards` never mutates the mapping it is given. `live(cards, now)` keeps the cards
posted not before `cutoff(now)`, the string `now - event_log.RETENTION` that `EventLog.retain`
compares, which is the card a release run may rely on: the console uses it when it posts, answers
and lists, so a card past the cutoff takes no answer, is never returned for a repost and is not
listed. `standing` is the newest card of a pair that is `OPEN` or `APPROVED`; `approved` is true
only for a card of exactly that commit and
version whose state is `APPROVED`. `inbox_entries` lists one `inbox_item` of reason `release` per
`OPEN` card in `card_id` order, keyed `release/<card_id>`, headed `Approve release <version> at
<first 12 of the commit>`, with the `card`, `commit`, `version`, a null `project_id`, `answered`
False and `waiting_since` the card's `at`.

Host store. `host_store()` is `.agents/state/console/events.sqlite3` under the home the password
database names for this user, never the caller's `$HOME`: the console's launchd job runs with that
home, so a release run from any sandboxed or redirected home still reads the host console's store.
`store_cards(store, now)` opens it read-only (`file:` URI, `mode=ro`, `PRAGMA query_only = ON`),
never creates a missing store, refuses a `PRAGMA user_version` other than `event_log.SCHEMA_VERSION`
(an older store is unmigrated and a newer one, left by a later console build, is not read by this
one), selects only the two card kinds whose `at` is not before `cutoff(now)`, in `seq` order, skips
a payload that is not a JSON object, and turns a
missing file, `sqlite3.Error` and `OSError` into `Unreadable`. A row retention would remove never
counts, even when the console has not run its retention pass.

Command. `release-card post --commit C --version V [--port N]` validates the pair first (an invalid
pair is exit 2 and nothing is sent), then sends `POST /api/release-card` to `127.0.0.1:N` (default
`DEFAULT_PORT`, 0-65535) as JSON with no `Origin` and the body `{"commit", "version"}`. A 200
`{"card": n, "state": s}` prints `release-card: card <n> is <s>` and exits 0; another status is
stderr `release-card: refused <status>: <text>`, exit 1; no connection is stderr
`release-card: console unreachable on 127.0.0.1:<port>: <error>`, exit 1. A flag abbreviation is
refused (exit 2).

Imports. This module imports only `canonical`, `console.event_log` and `release.release_profile`,
so the release command can import it cheaply.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import pwd
import sqlite3
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import event_log
from agent_tools.console.event_log import Event
from agent_tools.release import release_profile

PATH = "/api/release-card"
ANSWER_PATH = "/api/release-answer"
DEFAULT_PORT = 27184
HOST = "127.0.0.1"
TIMEOUT_SECONDS = 10

APPROVE = "approve"
DECLINE = "decline"
ANSWERS = (APPROVE, DECLINE)
OPEN = "open"
APPROVED = "approved"
DECLINED = "declined"

NOT_OPEN = "This release card is not open, so it takes no answer."


class Refused(Exception):
    """The service's 409 words."""


class Unreadable(Exception):
    """The store could not be read; `str()` is the reason."""


@dataclass(frozen=True)
class Card:
    card_id: int
    commit: str
    version: str
    at: str
    state: str


def valid_pair(commit: object, version: object) -> bool:
    return (isinstance(commit, str) and isinstance(version, str)
            and release_profile.COMMIT_PATTERN.fullmatch(commit) is not None
            and release_profile.VERSION_PATTERN.fullmatch(version) is not None)


def _card_number(value: object) -> bool:
    return type(value) is int and value >= 1


def posted_row(commit: str, version: str) -> tuple[str, None, dict]:
    if not valid_pair(commit, version):
        raise ValueError("a release card names a 40-hex commit and a vMAJOR.MINOR.PATCH version")
    return event_log.RELEASE_CARD_POSTED, None, {"commit": commit, "version": version}


def answered_row(card_id: int, answer: str) -> tuple[str, None, dict]:
    if not _card_number(card_id) or answer not in ANSWERS:
        raise ValueError("an answer names a card number of 1 or more and approve or decline")
    return event_log.RELEASE_CARD_ANSWERED, None, {"card": card_id, "answer": answer}


def _decoded(body: bytes, keys: set[str]) -> dict:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"the body must be an object of exactly {', '.join(sorted(keys))}")
    return value


def parse_post(body: bytes) -> tuple[str, str]:
    value = _decoded(body, {"commit", "version"})
    if not valid_pair(value["commit"], value["version"]):
        raise ValueError("the commit or the version is not a release candidate's")
    return value["commit"], value["version"]


def parse_answer(body: bytes) -> tuple[int, str]:
    value = _decoded(body, {"card", "answer"})
    if not _card_number(value["card"]) or value["answer"] not in ANSWERS:
        raise ValueError("the card or the answer is not valid")
    return value["card"], value["answer"]


def cards(events: Iterable[Event], state: Mapping[int, Card] | None = None) -> dict[int, Card]:
    """The cards after `events` are folded onto `state`; `state` itself is never changed."""
    folded = dict(state or {})
    for event in events:
        payload = event.payload
        if event.kind == event_log.RELEASE_CARD_POSTED:
            if (isinstance(payload, dict) and set(payload) == {"commit", "version"}
                    and valid_pair(payload["commit"], payload["version"])):
                folded[event.seq] = Card(event.seq, payload["commit"], payload["version"],
                                         event.at, OPEN)
        elif event.kind == event_log.RELEASE_CARD_ANSWERED:
            if not isinstance(payload, dict) or set(payload) != {"card", "answer"}:
                continue
            number, answer = payload["card"], payload["answer"]
            if not _card_number(number) or answer not in ANSWERS:
                continue
            card = folded.get(number)
            if card is not None and card.state == OPEN:
                folded[number] = replace(card, state=APPROVED if answer == APPROVE else DECLINED)
    return folded


def standing(cards: Mapping[int, Card], commit: str, version: str) -> Card | None:
    """The newest card of this pair that is open or approved."""
    found = [card for card in cards.values()
             if card.commit == commit and card.version == version
             and card.state in (OPEN, APPROVED)]
    return max(found, key=lambda card: card.card_id, default=None)


def approved(cards: Mapping[int, Card], commit: str, version: str) -> bool:
    return any(card.commit == commit and card.version == version and card.state == APPROVED
               for card in cards.values())


def inbox_entries(cards: Mapping[int, Card]) -> list[dict]:
    """One `inbox_item` of reason `release` per open card, in card order; nothing else is listed."""
    return [{"type": "inbox_item", "reason": "release", "key": f"release/{card.card_id}",
             "project_id": None, "card": card.card_id, "commit": card.commit,
             "version": card.version,
             "headline": f"Approve release {card.version} at {card.commit[:12]}",
             "answered": False, "waiting_since": card.at}
            for card in sorted(cards.values(), key=lambda card: card.card_id)
            if card.state == OPEN]


def cutoff(now: datetime) -> str:
    """The `at` string before which a row is past retention, as `EventLog.retain` compares it."""
    return (now - event_log.RETENTION).astimezone(timezone.utc).isoformat(timespec="microseconds")


def live(cards: Mapping[int, Card], now: datetime) -> dict[int, Card]:
    """The cards posted inside the retention window ending at `now`."""
    oldest = cutoff(now)
    return {number: card for number, card in cards.items() if card.at >= oldest}


def host_store() -> Path:
    """The host console's event store, under the password database's home and never `$HOME`."""
    return (Path(pwd.getpwuid(os.getuid()).pw_dir) / ".agents" / "state" / "console"
            / "events.sqlite3")


def store_cards(store: Path, now: datetime | None = None) -> dict[int, Card]:
    """The cards the store holds inside the retention window; `Unreadable` when it cannot be read."""
    now = now or datetime.now(timezone.utc)
    try:
        connection = sqlite3.connect(f"{Path(store).resolve().as_uri()}?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != event_log.SCHEMA_VERSION:
                raise sqlite3.DatabaseError(
                    f"store schema is {version}, this build reads {event_log.SCHEMA_VERSION}")
            found = connection.execute(
                "SELECT seq, at, kind, project, payload FROM events "
                "WHERE kind IN (?, ?) AND at >= ? ORDER BY seq",
                (event_log.RELEASE_CARD_POSTED, event_log.RELEASE_CARD_ANSWERED, cutoff(now))
            ).fetchall()
        finally:
            connection.close()
    except (sqlite3.Error, OSError) as error:
        raise Unreadable(" ".join(f"{store}: {error}".split())) from error
    events = []
    for seq, at, kind, project, text in found:
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            events.append(Event(seq, at, kind, project, payload))
    return cards(events)


def _port(text: str) -> int:
    try:
        port = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a port") from None
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"{text!r} is not a port from 0 to 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="release-card", allow_abbrev=False,
                                     description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    post = commands.add_parser("post", allow_abbrev=False,
                               help="post the release card of one candidate")
    post.add_argument("--commit", required=True)
    post.add_argument("--version", required=True)
    post.add_argument("--port", type=_port, default=DEFAULT_PORT)
    return parser


def _post(args: argparse.Namespace) -> int:
    if not valid_pair(args.commit, args.version):
        print("release-card: the commit must be 40 lowercase hex digits and the version "
              "vMAJOR.MINOR.PATCH", file=sys.stderr)
        return 2
    body = json.dumps({"commit": args.commit, "version": args.version}).encode("utf-8")
    connection = http.client.HTTPConnection(HOST, args.port, timeout=TIMEOUT_SECONDS)
    try:
        connection.request("POST", PATH, body=body,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        text = response.read().decode("utf-8", "replace").strip()
    except (OSError, http.client.HTTPException) as error:
        print(f"release-card: console unreachable on {HOST}:{args.port}: {error}",
              file=sys.stderr)
        return 1
    finally:
        connection.close()
    if response.status != 200:
        print(f"release-card: refused {response.status}: {text}", file=sys.stderr)
        return 1
    try:
        answer = json.loads(text)
        print(f"release-card: card {answer['card']} is {answer['state']}")
    except (ValueError, KeyError, TypeError):
        print(f"release-card: refused {response.status}: {text}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _post(args)


if __name__ == "__main__":
    sys.exit(main())
