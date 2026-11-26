"""The eleven-m5 watcher's reactive oMLX restart: trigger, episode, gaps, restart state, records and alert.

`step` runs once per `omlx-memory-watch sample` when `--restart-command` is given. The figure is the
fresh census's unowned bytes plus the reading's compressor bytes. A sample over the trigger adds one to
the streak; a sample at or under it ends the episode; a sample without a fresh census zeroes the streak
and keeps the episode. An attempt is due once the streak reaches the sample count and the episode has
not already restarted oMLX. Available memory under the room, or a restart less than the minimum gap
ago (measured from when the gate returned), defers the attempt; otherwise the gate `<command> --reactive`
runs: exit 0 restarted, 75 deferred (the reason is in its last `oMLX: restart deferred (...)` line),
anything else failed. A restarted or interrupted outcome ends the episode and alerts once; a deferred or
failed one is only recorded, and the next due sample tries again.

The state is `DIR/omlx-restart.json`, apart from the watcher's own state. It is saved with the attempt
before the gate runs, so a run stopped after the gate may have signalled becomes an `interrupted`
outcome and never signals twice. The outcome, the episode and its record and alert are saved in one
replace (the outbox); the record goes to `DIR/omlx-restarts.jsonl` (one line per attempt, skipped when
its id is already there), then the alert is delivered and the entry dropped. An alert that is not sent
stays in the outbox and is retried on the next sample.
"""

import json
import os
import signal
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

GIB = 1024**3
PROG = "omlx-memory-watch"
RESTART_STATE_NAME = "omlx-restart.json"
RESTARTS_NAME = "omlx-restarts.jsonl"
GATE_TIMEOUT_SECONDS = 120
REAP_SECONDS = 5
DEFERRED_PREFIX = "oMLX: restart deferred ("
ALERT_KIND = "omlx_restarted"
SEE = "See hosts/darwin/eleven-m5/README.md, Reactive restart."


@dataclass(frozen=True)
class Limits:
    command: str
    trigger_bytes: int
    samples: int
    room_bytes: int
    min_interval: timedelta


@dataclass(frozen=True)
class Gate:
    outcome: str
    reason: str


def figure(census: dict | None, reading: dict) -> int | None:
    """Unowned plus compressor bytes, or None without a fresh census."""
    if census is None:
        return None
    return census["unowned_bytes"] + reading["compressor_bytes"]


def _deferral(stderr: str) -> str:
    fallback = "omlx-restart deferred"
    lines = [line for line in (stderr or "").splitlines() if line.startswith(DEFERRED_PREFIX)]
    if not lines:
        return fallback
    end = lines[-1].rfind(")")
    reason = lines[-1][len(DEFERRED_PREFIX):end].strip() if end >= len(DEFERRED_PREFIX) else ""
    return reason or fallback


def run_gate(argv: list[str], timeout: float) -> Gate:
    """Run the restart command in its own session; a gate past `timeout` is killed with its whole group."""
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True)
    except OSError as error:
        return Gate("failed", f"omlx-restart could not run ({type(error).__name__})")
    try:
        _, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=REAP_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        return Gate("failed", "omlx-restart timed out")
    if proc.returncode == 0:
        return Gate("restarted", "omlx-restart restarted oMLX")
    if proc.returncode == 75:
        return Gate("deferred", _deferral(stderr))
    return Gate("failed", f"omlx-restart exited {proc.returncode}")


def _save(path: Path, document: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(json.dumps(document, indent=2) + "\n")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _defaults(now: datetime) -> dict:
    return {
        "since_at": now.isoformat(), "limits": None, "streak": 0, "episode_done": False,
        "last_restart_at": None, "attempt": None, "outbox": [],
    }


def _load(path: Path, now: datetime) -> dict:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return _defaults(now)
    found = json.loads(text)
    if not isinstance(found, dict):
        raise ValueError("the restart state is not an object")
    document = {**_defaults(now), **found}
    if not (isinstance(document["streak"], int) and isinstance(document["episode_done"], bool)
            and isinstance(document["outbox"], list) and isinstance(document["since_at"], str)
            and (document["attempt"] is None or isinstance(document["attempt"], dict))):
        raise ValueError("the restart state has a wrong field")
    if document["last_restart_at"] is not None:
        datetime.fromisoformat(document["last_restart_at"])
    for entry in document["outbox"]:
        entry["record"]["id"], entry["alert"], entry["recorded"], entry["logged"]
    if document["attempt"] is not None:
        document["attempt"]["id"], document["attempt"]["at"], document["attempt"]["started_at"]
    return document


def _gib(value: int) -> str:
    return f"{value / GIB:.1f}"


def _figures_text(facts: dict, limits: Limits) -> str:
    return (
        f"unowned plus compressor {_gib(facts['figure_bytes'])} GiB stayed over {limits.trigger_bytes / GIB:g} GiB "
        f"for {facts['streak']} samples (unowned {_gib(facts['unowned_bytes'])} GiB, "
        f"compressor {_gib(facts['compressor_bytes'])} GiB, available {_gib(facts['available_bytes'])} GiB). {SEE}")


def _alert(host: str, outcome: str, facts: dict, limits: Limits) -> str | None:
    if outcome == "restarted":
        return f"{host}: oMLX was restarted while it served no request: {_figures_text(facts, limits)}"
    if outcome == "interrupted":
        return (f"{host}: oMLX may have been restarted: the watcher stopped during its restart attempt at "
                f"{facts['at']}: {_figures_text(facts, limits)}")
    return None


_FACT_KEYS = ("id", "at", "available_bytes", "unowned_bytes", "compressor_bytes", "figure_bytes", "streak")


def _queue(document: dict, facts: dict, outcome: str, reason: str, host: str, limits: Limits) -> None:
    record = {
        "id": facts["id"], "at": facts["at"], "outcome": outcome, "reason": reason,
        **{key: facts[key] for key in _FACT_KEYS[2:]},
    }
    document["outbox"].append(
        {"record": record, "alert": _alert(host, outcome, facts, limits), "recorded": False, "logged": False})


def _interrupt(document: dict, host: str, limits: Limits) -> None:
    attempt = document["attempt"]
    facts = {key: attempt[key] for key in _FACT_KEYS}
    _queue(document, facts, "interrupted", "the watcher stopped during the restart attempt", host, limits)
    document["episode_done"] = True
    document["last_restart_at"] = attempt["started_at"]
    document["attempt"] = None


def _has_record(path: Path, identity: str) -> bool:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return False
    for line in text.splitlines():
        try:
            if json.loads(line).get("id") == identity:
                return True
        except (ValueError, AttributeError):
            continue
    return False


def _append_record(path: Path, record: dict) -> bool:
    if _has_record(path, record["id"]):
        return False
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, (json.dumps(record) + "\n").encode())
    finally:
        os.close(descriptor)
    return True


def _log_line(record: dict) -> str:
    return (
        f"{record['at']} omlx_restart outcome={record['outcome']} available_gib={_gib(record['available_bytes'])} "
        f"unowned_gib={_gib(record['unowned_bytes'])} compressor_gib={_gib(record['compressor_bytes'])} "
        f"reason={json.dumps(record['reason'])}")


def _flush(directory: Path, document: dict, deliver: Callable[[str, str, bool], str]) -> bool:
    path = directory / RESTART_STATE_NAME
    failed = False
    for entry in list(document["outbox"]):
        if not entry["recorded"]:
            if _append_record(directory / RESTARTS_NAME, entry["record"]):
                print(_log_line(entry["record"]), flush=True)
            entry["recorded"] = True
            _save(path, document)
        if entry["alert"] is not None and deliver(ALERT_KIND, entry["alert"], entry["logged"]) == "failed":
            entry["logged"] = True
            failed = True
        else:
            document["outbox"].remove(entry)
        _save(path, document)
    return failed


def _fold(document: dict, value: int | None, limits: Limits) -> None:
    if value is None or value <= limits.trigger_bytes:
        document["streak"] = 0
        if value is not None:
            document["episode_done"] = False
    else:
        document["streak"] += 1


def _limits_document(limits: Limits) -> dict:
    return {
        "trigger_bytes": limits.trigger_bytes, "samples": limits.samples, "room_bytes": limits.room_bytes,
        "min_interval_seconds": int(limits.min_interval.total_seconds()),
    }


def _deferral_reason(document: dict, reading: dict, now: datetime, limits: Limits, elapsed) -> str | None:
    if reading["available_bytes"] < limits.room_bytes:
        return (f"available {_gib(reading['available_bytes'])} GiB is under the "
                f"{limits.room_bytes / GIB:g} GiB restart room")
    if document["last_restart_at"] is not None:
        since = now + elapsed() - datetime.fromisoformat(document["last_restart_at"])
        if since < limits.min_interval:
            return (f"the last reactive restart was {round(since.total_seconds() / 60)} minutes ago, "
                    f"under {limits.min_interval.total_seconds() / 60:g}")
    return None


def _attempt(directory, document, facts, reading, now, limits, elapsed, gate) -> None:
    path = directory / RESTART_STATE_NAME
    host = reading["host"]
    reason = _deferral_reason(document, reading, now, limits, elapsed)
    if reason is not None:
        _queue(document, facts, "deferred", reason, host, limits)
        return
    document["attempt"] = {**facts, "started_at": (now + elapsed()).isoformat()}
    _save(path, document)
    found = gate([limits.command, "--reactive"])
    document["attempt"] = None
    if found.outcome == "restarted":
        document["episode_done"] = True
        document["last_restart_at"] = (now + elapsed()).isoformat()
    _queue(document, facts, found.outcome, found.reason, host, limits)


def step(
    directory: Path,
    census: dict | None,
    reading: dict,
    now: datetime,
    limits: Limits,
    *,
    elapsed: Callable[[], timedelta],
    gate: Callable[[list[str]], Gate],
    deliver: Callable[[str, str, bool], str],
) -> bool:
    """Fold one sample into the restart state, attempt a due restart and send its alert; True when one was not sent."""
    path = directory / RESTART_STATE_NAME
    try:
        document = _load(path, now)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"{PROG}: the restart state is unreadable ({type(error).__name__}); "
              "no reactive restart this sample", file=sys.stderr)
        return True
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if document["attempt"] is not None:
        _interrupt(document, reading["host"], limits)
        _save(path, document)
    document["limits"] = _limits_document(limits)
    value = figure(census, reading)
    _fold(document, value, limits)
    if value is not None and document["streak"] >= limits.samples and not document["episode_done"]:
        facts = {
            "id": uuid.uuid4().hex, "at": now.isoformat(), "available_bytes": reading["available_bytes"],
            "unowned_bytes": census["unowned_bytes"], "compressor_bytes": reading["compressor_bytes"],
            "figure_bytes": value, "streak": document["streak"],
        }
        _attempt(directory, document, facts, reading, now, limits, elapsed, gate)
    _save(path, document)
    return _flush(directory, document, deliver)
