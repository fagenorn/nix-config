"""The one clock reading a screenshot run is shot at.

A run reads one time for every state and width: the seed's event times, the times of the files the
fixture writes, the service's clock and the stamp on every row it writes all come from it, so a page
that did not change is the same picture on any day. `READING` is the default; `--now TIME` sets it.
"""
import contextlib
import fcntl
import os
import shutil
import stat
import tempfile
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path

READING: float = datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc).timestamp()
TIME_ZONE = "UTC"
LOCALE = "en-US"
FIXTURE_WAIT_SECONDS = 600.0
# Partial raster draws an edge pixel over the tile's earlier pixels, so a button's corner varies with page history.
LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-partial-raster"]


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


PICTURES_LOADED = """async () => {
  const waiting = () => [...document.querySelectorAll('img.pic-img')].some(
    (img) => !img.hidden && (!img.getAttribute('src') || !img.complete));
  for (let tries = 0; tries < 100 && waiting(); tries++) await new Promise((done) => setTimeout(done, 50));
}"""


def screenshot(page, path: Path) -> None:
    """Take the picture with the pointer off the page and its pictures loaded, waiting for them at most 5 s."""
    page.mouse.move(0, 0)
    page.evaluate(PICTURES_LOADED)
    page.screenshot(path=str(path), full_page=True, animations="disabled")


def stamp(root: Path, at_s: float) -> None:
    """Give every file and folder under `root`, and `root`, the reading as its modified time."""
    os.utime(root, (at_s, at_s))
    for folder, folders, files in os.walk(root):
        for name in folders + files:
            path = os.path.join(folder, name)
            if not os.path.islink(path):
                os.utime(path, (at_s, at_s))


def shots_home() -> Path:
    """The private folder, one per user under the temporary folder, that holds the fixture root and its lock."""
    return Path(tempfile.gettempdir()) / f"console-shots-{os.getuid()}"


def refuse_inside(out: Path, home: Path) -> None:
    """Refuse an output folder at or inside the fixture folder, which each run empties."""
    resolved = Path(out).resolve()
    folder = Path(home).resolve()
    if resolved == folder or folder in resolved.parents:
        raise ValueError(
            f"the output folder {out} lies in the screenshot fixture folder {home}, which each run empties")


@contextlib.contextmanager
def fixture_dirs(home: Path):
    """Yield the fixed, empty, private fixture root `home/root`, held by this run alone until the block ends."""
    try:
        os.mkdir(home, 0o700)
    except FileExistsError:
        pass
    found = os.lstat(home)
    if not (stat.S_ISDIR(found.st_mode) and found.st_uid == os.getuid() and stat.S_IMODE(found.st_mode) == 0o700):
        raise PermissionError(f"{home} is not a private folder of this user")
    fd = os.open(home / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        give_up = time.monotonic() + FIXTURE_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > give_up:
                    raise TimeoutError(
                        f"another screenshot run holds {home / 'lock'} for over {FIXTURE_WAIT_SECONDS:g} s") from None
                time.sleep(0.1)
        root = home / "root"
        try:
            leftover = os.lstat(root)
        except FileNotFoundError:
            leftover = None
        if leftover is not None and stat.S_ISDIR(leftover.st_mode):
            shutil.rmtree(root)
        os.mkdir(root, 0o700)
        try:
            yield root
        finally:
            if os.path.lexists(root):
                shutil.rmtree(root)
    finally:
        os.close(fd)
