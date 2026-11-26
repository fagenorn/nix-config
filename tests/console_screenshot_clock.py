"""The one clock reading a screenshot run is shot at.

A run reads one time for every state and width: the seed's event times, the times of the files the
fixture writes, the service's clock and the stamp on every row it writes all come from it, so a page
that did not change is the same picture on any day. `READING` is the default; `--now TIME` sets it.
"""
import os
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path

READING: float = datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc).timestamp()
TIME_ZONE = "UTC"
LOCALE = "en-US"


def reading(text: str | None) -> float:
    """The epoch seconds of an ISO 8601 time with its UTC offset; `READING` for no time."""
    if text is None:
        return READING
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError("a --now time needs its UTC offset")
    return moment.timestamp()


def add_flag(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--now", metavar="TIME",
        help="the clock reading every state is shot at: an ISO 8601 time with its UTC offset "
             "(default 2026-11-20T09:30:00+00:00)")


def parsed_reading(parser: ArgumentParser, text: str | None) -> float:
    try:
        return reading(text)
    except ValueError:
        parser.error(f"--now {text!r} is not an ISO 8601 time with a UTC offset")


def service_clocks(now_s: float) -> dict:
    """The `ConsoleService` keywords that make it read, and stamp its rows with, the reading."""
    stamped = datetime.fromtimestamp(now_s, timezone.utc).isoformat(timespec="microseconds")
    return {"clock": lambda: now_s, "log_clock": lambda: stamped}


def open_page(browser, width: int, height: int, now_s: float):
    """A page in the fixed zone and locale whose clock stands at the reading before it loads anything."""
    page = browser.new_page(viewport={"width": width, "height": height}, timezone_id=TIME_ZONE, locale=LOCALE)
    try:
        page.clock.set_fixed_time(now_s)
    except BaseException:
        page.close()
        raise
    return page


def screenshot(page, path: Path) -> None:
    page.screenshot(path=str(path), full_page=True, animations="disabled")


def stamp(root: Path, at_s: float) -> None:
    """Give every file and folder under `root`, and `root`, the reading as its modified time."""
    os.utime(root, (at_s, at_s))
    for folder, folders, files in os.walk(root):
        for name in folders + files:
            path = os.path.join(folder, name)
            if not os.path.islink(path):
                os.utime(path, (at_s, at_s))
