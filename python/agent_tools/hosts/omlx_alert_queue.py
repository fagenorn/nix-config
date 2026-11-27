"""The memory watcher's pending alert queue: its bound and its summary.

A pending entry is `{kind, text, logged}`, plus `at` (when it was queued, ISO 8601), `count` (the alerts
it stands for, default 1) and `held` (it was kept because the host has no alert settings file).

`compact(pending, now)` answers `(kept, expired)` for the `held` entries alone (tried, and kept for want of a
settings file). Every other entry passes through whole, in order, the untried last, so several alerts of one
sample all go out and an alert lost to a Telegram outage or a refused settings file is retried without end:
- a held entry older than `MAX_AGE` (24 hours, strictly), or with no readable `at`, is expired;
- of the rest, the newest of each kind per calendar day of its `at` is kept, with the `count` of the entries
  it replaced added to its own.
`expiry_line(expired)` is the one summary line for the log: how many were dropped and per kind.

`summarize(pending, host, now)` replaces the `held` entries by one `alert_backlog` entry once they stand for
more than one alert: the counts per kind and the time of the oldest kept, never the backlog itself.
"""

from datetime import datetime, timedelta

MAX_AGE = timedelta(hours=24)
SUMMARY_KIND = "alert_backlog"


def _count(entry: dict) -> int:
    count = entry.get("count", 1)
    return count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 1


def _at(entry: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(entry["at"])
    except (KeyError, TypeError, ValueError):
        return None


def _per_kind(entries: list[dict]) -> str:
    totals: dict[str, int] = {}
    for entry in entries:
        totals[entry["kind"]] = totals.get(entry["kind"], 0) + _count(entry)
    return ", ".join(f"{kind} x{total}" for kind, total in sorted(totals.items()))


def compact(pending: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    held, others, expired, newest = [], [], [], {}
    for entry in pending:
        (held if entry["logged"] and entry.get("held") else others).append(entry)
    for entry in held:
        at = _at(entry)
        try:
            old = at is None or now - at > MAX_AGE
        except TypeError:
            old = True
        if old:
            expired.append(entry)
            continue
        key = (entry["kind"], at.date())
        earlier = newest.get(key)
        if earlier is None:
            newest[key] = entry
        else:
            kept, other = (entry, earlier) if at >= _at(earlier) else (earlier, entry)
            newest[key] = {**kept, "count": _count(kept) + _count(other)}
    kept = sorted(newest.values(), key=lambda entry: _at(entry))
    # Entries tried and refused or lost to an outage are neither bounded nor expired; an untried one goes last.
    tried = [entry for entry in others if entry["logged"]]
    return kept + tried + [entry for entry in others if not entry["logged"]], expired


def expiry_line(expired: list[dict]) -> str:
    total = sum(_count(entry) for entry in expired)
    return f"dropped {total} pending alerts older than 24 hours ({_per_kind(expired)})"


def summarize(pending: list[dict], host: str, now: datetime) -> list[dict]:
    held = [entry for entry in pending if entry.get("held")]
    if sum(_count(entry) for entry in held) < 2:
        return pending
    oldest = min(entry["at"] for entry in held)
    text = (f"{host}: {sum(_count(entry) for entry in held)} alerts were held while host alerts were not "
            f"configured, since {oldest}: {_per_kind(held)}.")
    summary = {"kind": SUMMARY_KIND, "text": text, "logged": False, "at": now.isoformat()}
    return [summary] + [entry for entry in pending if not entry.get("held")]
