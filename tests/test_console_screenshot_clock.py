"""The screenshot set's fixed clock reading, page and fixture root.

Run: just agent-workflow-tests
"""
import contextlib
import errno
import http.client
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console.event_log import EventLog

from . import console_screenshots as shots
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "integration"  # it serves fixture consoles and drives Chromium

JANUARY = datetime(2026, 1, 9, 9, 30, tzinfo=timezone.utc).timestamp()
FUTURE = datetime(2030, 1, 4, 9, 30, tzinfo=timezone.utc).timestamp()
DEFAULT = datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc).timestamp()
TUESDAY = datetime(2026, 1, 6, 15, 45, tzinfo=timezone.utc).timestamp()
LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]
PAGE_TIMES = """() => ({
  now: Date.now(),
  zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  language: navigator.language,
  resets: Object.fromEntries([...document.querySelectorAll('.acct-row')].map(
    r => [r.dataset.profile, r.querySelector('.acct-reset time')?.textContent ?? null])),
  reported: [...document.querySelectorAll('.status-age time')].map(t => t.textContent),
  agos: [...document.querySelectorAll('time[data-form="ago"]')].map(t => t.textContent),
})"""


def own_tempdir(test: unittest.TestCase) -> Path:
    """A temporary location of the test's own, which `tempfile` hands out until the test ends."""
    path = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, path, True)
    patch = mock.patch.object(tempfile, "tempdir", str(path))
    patch.start()
    test.addCleanup(patch.stop)
    return path


def chromium_or_skip(test: unittest.TestCase) -> None:
    """Skip the test unless Playwright is installed and can launch a Chromium."""
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        test.skipTest("playwright is not installed")
    with sync_playwright() as pw:
        try:
            pw.chromium.launch(args=LAUNCH_ARGS).close()
        except Error as err:
            test.skipTest(f"no Chromium to launch: {err}")


def browser_zone() -> str:
    """The zone a bare Chromium page reports, with the browser closed again before it returns."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=LAUNCH_ARGS)
        try:
            return browser.new_page().evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
        finally:
            browser.close()


def read_before_shots(test: unittest.TestCase) -> list:
    """The page's times and the screenshot options, read just before each picture is taken."""
    from playwright.sync_api import Page

    real = Page.screenshot
    seen: list = []

    def record(page, **kwargs):
        seen.append((page.evaluate(PAGE_TIMES), kwargs))
        return real(page, **kwargs)

    patch = mock.patch.object(Page, "screenshot", autospec=True, side_effect=record)
    patch.start()
    test.addCleanup(patch.stop)
    return seen


def stub_playwright():
    """`playwright.sync_api` as a browser that launches and closes, shot by a patched `_shoot`."""
    class Browser:
        def close(self):
            pass

    class Playwright:
        chromium = types.SimpleNamespace(launch=lambda args=None: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    api = types.ModuleType("playwright.sync_api")
    api.Error = type("Error", (Exception,), {})
    api.sync_playwright = Playwright
    return mock.patch.dict(sys.modules, {"playwright": types.ModuleType("playwright"),
                                         "playwright.sync_api": api})


def state_of(url: str) -> dict:
    host, port = url.split("//")[1].split("/")[0].split(":")
    connection = http.client.HTTPConnection(host, int(port))
    try:
        connection.request("GET", "/api/state")
        return json.loads(connection.getresponse().read())
    finally:
        connection.close()


class FixedReadingTest(unittest.TestCase):
    def test_the_service_counts_capacity_from_the_fixed_reading(self) -> None:
        fixture = shots.build_fixture(own_tempdir(self) / "fixture", "accounts-panel", JANUARY)
        service = shots.start_service(fixture, JANUARY)
        try:
            view = json.loads(service.view_bytes)
        finally:
            service.close()
        resets = {p["profile"]: p["next_reset"] and datetime.fromisoformat(p["next_reset"]).timestamp()
                  for p in view["capacity"]["profiles"]}
        self.assertEqual(resets, {"work-main": JANUARY + 86400, "work-spare": JANUARY + 86400})

    def test_an_event_written_through_the_service_carries_the_fixed_reading(self) -> None:
        fixture = shots.build_fixture(own_tempdir(self) / "fixture", "live-several", JANUARY)
        service = shots.start_service(fixture, JANUARY)
        try:
            written = service.ingest_hook(support.hook_body("session start", cwd=str(fixture.projects[0])))
        finally:
            service.close()
        log = EventLog(fixture.store)
        try:
            last = log.events()[-1]
        finally:
            log.close()
        self.assertTrue(written)
        self.assertEqual({e.at for e in written}, {"2026-01-09T09:30:00.000000+00:00"})
        self.assertEqual((last.seq, last.at), (written[-1].seq, "2026-01-09T09:30:00.000000+00:00"))

    def test_a_reading_after_the_real_date_still_shows_the_fixture_spend(self) -> None:
        fixture = shots.build_fixture(own_tempdir(self) / "fixture", "spend-page", FUTURE)
        mtimes = {os.lstat(Path(d) / n).st_mtime for d, ds, fs in os.walk(fixture.root) for n in ds + fs}
        service = shots.start_service(fixture, FUTURE)
        try:
            days = json.loads(service.view_bytes)["spend"]["days"]
        finally:
            service.close()
        self.assertEqual(mtimes, {FUTURE})
        self.assertEqual([d["day"] for d in days if d["total"]["input"] > 0],
                         ["2029-12-29", "2029-12-30", "2029-12-31", "2030-01-01", "2030-01-02", "2030-01-03",
                          "2030-01-04"])

    def test_capture_serves_every_width_from_the_one_reading_it_is_given(self) -> None:
        out = own_tempdir(self) / "out"
        seen = []

        def fake(browser, url, state, width, out, **kwargs):
            seen.append((width, {p["profile"]: datetime.fromisoformat(p["next_reset"]).timestamp()
                                 for p in state_of(url)["capacity"]["profiles"]}))

        with stub_playwright(), mock.patch.object(shots, "_shoot", side_effect=fake):
            shots.capture(out, states=("accounts-panel",), now=JANUARY)
            first, seen[:] = list(seen), []
            shots.capture(out, states=("accounts-panel",))
        for got, reading in ((first, JANUARY), (seen, DEFAULT)):
            reset = {"work-main": reading + 86400, "work-spare": reading + 86400}
            self.assertEqual(got, [(width, reset) for width in shots.WIDTHS])

    def test_the_now_flag_reads_an_offset_time_and_refuses_a_naive_one(self) -> None:
        from . import console_screenshot_clock as shot_clock

        out = own_tempdir(self) / "out"
        self.assertEqual(shot_clock.reading(None), shot_clock.READING)
        self.assertEqual(shot_clock.READING, DEFAULT)
        self.assertEqual(shot_clock.reading("2026-01-09T10:30:00+01:00"), JANUARY)
        with self.assertRaises(ValueError):
            shot_clock.reading("2026-01-09T09:30:00")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), \
                mock.patch.object(shots, "capture", side_effect=lambda *a, **k: self.fail("capture was called")), \
                self.assertRaises(SystemExit) as raised:
            shots.main(["--out", str(out), "--now", "2026-01-09T09:30:00"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--now '2026-01-09T09:30:00' is not an ISO 8601 time with a UTC offset", stderr.getvalue())

    def test_main_passes_the_now_flag_to_capture(self) -> None:
        out = own_tempdir(self) / "out"
        answer = out.parent / "answer.txt"
        answer.write_text("A", encoding="utf-8")
        readings = []

        def record(out, **kw):
            readings.append(kw["now"])
            return []

        runs = (["--now", "2026-01-09T10:30:00+01:00"], [],
                ["--question", "Q?", "--answer-file", str(answer), "--now", "2026-01-09T09:30:00+00:00"])
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(shots, "capture", side_effect=record):
            codes = [shots.main(["--out", str(out), *extra]) for extra in runs]
        self.assertEqual(codes, [0, 0, 0])
        self.assertEqual(readings, [JANUARY, DEFAULT, JANUARY])


class FixedPageTest(unittest.TestCase):
    def test_a_picture_shows_its_times_from_the_fixed_reading(self) -> None:
        chromium_or_skip(self)
        out = own_tempdir(self) / "out"
        seen = read_before_shots(self)
        shots.capture(out, states=("owner-accounts",), widths=(1440,))
        ((times, _),) = seen
        self.assertEqual(times["resets"], {"work-main": "Fri 11:30", "colleague-1": "Fri 12:30",
                                           "work-spare": "Fri 13:30"})
        self.assertIn("6 min ago", times["reported"])
        self.assertEqual([t for t in times["agos"] if t.endswith("days ago") or t == "yesterday"], [])
        self.assertEqual(times["now"], DEFAULT * 1000)
        self.assertEqual(times["zone"], "UTC")
        self.assertEqual(times["language"], "en-US")

    def test_the_now_override_moves_every_picture_time_with_it_in_utc_on_a_far_zone_host(self) -> None:
        chromium_or_skip(self)
        out = own_tempdir(self) / "out"
        seen = read_before_shots(self)
        patch = mock.patch.dict(os.environ, {"TZ": "Pacific/Kiritimati"})
        patch.start()
        self.addCleanup(patch.stop)
        self.assertEqual(browser_zone(), "Pacific/Kiritimati")
        shots.capture(out, states=("owner-accounts",), widths=(1440,), now=TUESDAY)
        ((times, kwargs),) = seen
        self.assertEqual(times["resets"], {"work-main": "Tue 17:45", "colleague-1": "Tue 18:45",
                                           "work-spare": "Tue 19:45"})
        self.assertIn("6 min ago", times["reported"])
        self.assertEqual(times["now"], TUESDAY * 1000)
        self.assertEqual(times["zone"], "UTC")
        self.assertEqual((kwargs["full_page"], kwargs.get("animations")), (True, "disabled"))


class FixedPicturesTest(unittest.TestCase):
    def test_two_captures_at_different_real_times_write_the_same_bytes(self) -> None:
        chromium_or_skip(self)
        base = own_tempdir(self)
        a, b = base / "a", base / "b"
        shots.capture(a)
        shots.capture(b)
        names = sorted(f"{s}-{w}.png" for s in shots.STATES for w in shots.WIDTHS)
        self.assertEqual(sorted(p.name for p in a.iterdir()), names)
        self.assertEqual(sorted(p.name for p in b.iterdir()), names)
        self.assertEqual([n for n in names if (a / n).read_bytes() != (b / n).read_bytes()], [])

    def test_every_entry_yields_the_same_empty_private_root(self) -> None:
        from . import console_screenshot_clock as shot_clock

        home = own_tempdir(self) / "home"
        for entry in range(2):
            with shot_clock.fixture_dirs(home) as root:
                self.assertEqual(root, home / "root")
                self.assertEqual(os.listdir(root), [])
                self.assertEqual([stat.S_IMODE(os.lstat(p).st_mode) for p in (home, root)], [0o700, 0o700])
                (root / "inside.txt").write_text("inside", encoding="utf-8")
            self.assertFalse((home / "root").exists())
            self.assertTrue(home.is_dir() and (home / "lock").exists())
            if entry == 0:
                os.mkdir(home / "root", 0o700)
                (home / "root" / "stale.txt").write_text("stale", encoding="utf-8")

    def test_a_waiter_acquires_the_root_once_the_holder_leaves(self) -> None:
        from . import console_screenshot_clock as shot_clock

        home = own_tempdir(self) / "home"
        wait = mock.patch.object(shot_clock, "FIXTURE_WAIT_SECONDS", 5.0)
        wait.start()
        self.addCleanup(wait.stop)
        entered, release, blocked = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        order, errors = [], []
        real_sleep = time.sleep
        sleeping = mock.patch.object(shot_clock.time, "sleep", side_effect=lambda s: (blocked.set(), real_sleep(s)))
        sleeping.start()
        self.addCleanup(sleeping.stop)

        def hold():
            with shot_clock.fixture_dirs(home):
                order.append("holder in")
                entered.set()
                release.wait(5)
                order.append("holder out")

        def wait_for_it():
            try:
                with shot_clock.fixture_dirs(home) as root:
                    order.append(("waiter in", root.is_dir(), os.listdir(root)))
            except BaseException as error:
                errors.append(error)

        holder = threading.Thread(target=hold, daemon=True)
        waiter = threading.Thread(target=wait_for_it, daemon=True)
        holder.start()
        self.assertTrue(entered.wait(5))
        waiter.start()
        self.assertTrue(blocked.wait(5))
        release.set()
        holder.join(5)
        waiter.join(5)
        self.assertFalse(holder.is_alive() or waiter.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(order, ["holder in", "holder out", ("waiter in", True, [])])

    def test_a_waiter_gives_up_at_the_bound_and_leaves_the_holder_root(self) -> None:
        from . import console_screenshot_clock as shot_clock

        home = own_tempdir(self) / "home"
        wait = mock.patch.object(shot_clock, "FIXTURE_WAIT_SECONDS", 0.3)
        wait.start()
        self.addCleanup(wait.stop)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        root = stack.enter_context(shot_clock.fixture_dirs(home))
        (root / "mine.txt").write_text("mine", encoding="utf-8")
        errors = []

        def wait_for_it():
            try:
                with shot_clock.fixture_dirs(home):
                    pass
            except BaseException as error:
                errors.append(error)

        waiter = threading.Thread(target=wait_for_it, daemon=True)
        waiter.start()
        waiter.join(5)
        self.assertFalse(waiter.is_alive())
        self.assertEqual([type(e) for e in errors], [TimeoutError])
        self.assertIn(str(home / "lock"), str(errors[0]))
        self.assertEqual((root / "mine.txt").read_text(encoding="utf-8"), "mine")

    def test_a_failed_entry_body_or_cleanup_releases_the_lock(self) -> None:
        from . import console_screenshot_clock as shot_clock

        home = own_tempdir(self) / "home"
        wait = mock.patch.object(shot_clock, "FIXTURE_WAIT_SECONDS", 0.3)
        wait.start()
        self.addCleanup(wait.stop)
        os.mkdir(home, 0o700)
        (home / "root").write_text("a file", encoding="utf-8")
        with self.assertRaises(FileExistsError), shot_clock.fixture_dirs(home):
            pass
        self.assertTrue((home / "root").is_file())
        (home / "root").unlink()
        with shot_clock.fixture_dirs(home):
            pass
        with self.assertRaises(RuntimeError), shot_clock.fixture_dirs(home):
            raise RuntimeError("body")
        self.assertFalse((home / "root").exists())
        with shot_clock.fixture_dirs(home):
            pass
        def cannot_remove(path, ignore_errors=False, **kwargs):
            if not ignore_errors:
                raise OSError("cannot remove")

        failing = mock.patch.object(shot_clock.shutil, "rmtree", side_effect=cannot_remove)
        with self.assertRaises(OSError) as raised, failing, shot_clock.fixture_dirs(home) as root:
            (root / "x").write_text("x", encoding="utf-8")
        self.assertIn("cannot remove", str(raised.exception))
        self.assertTrue((home / "root" / "x").exists())
        with shot_clock.fixture_dirs(home) as root:
            self.assertEqual(os.listdir(root), [])

    def test_an_out_inside_the_fixture_folder_is_refused_before_anything_is_made(self) -> None:
        from . import console_screenshot_clock as shot_clock

        base = own_tempdir(self)
        home = shot_clock.shots_home()
        (home / "root").mkdir(parents=True)
        (home / "root" / "mine.txt").write_text("mine", encoding="utf-8")
        link = base / "link"
        os.symlink(home / "root", link)
        with stub_playwright(), mock.patch.object(shots, "_shoot", return_value=None):
            for out in (home / "root" / "shots", home, link / "shots"):
                with self.subTest(out=out), self.assertRaises(ValueError) as raised:
                    shots.capture(out, states=("nothing-running",))
                self.assertIn(str(home), str(raised.exception))
        self.assertEqual((home / "root" / "mine.txt").read_text(encoding="utf-8"), "mine")
        self.assertFalse((home / "root" / "shots").exists())

    def test_a_planted_link_or_a_wrong_or_foreign_home_is_refused_and_left_alone(self) -> None:
        from . import console_screenshot_clock as shot_clock

        base = own_tempdir(self)
        victim = base / "victim"
        victim.mkdir()
        (victim / "keep").write_text("mine", encoding="utf-8")
        home = base / "home"
        os.symlink(victim, home)
        with self.assertRaises(PermissionError) as raised, shot_clock.fixture_dirs(home):
            pass
        self.assertIn(str(home), str(raised.exception))
        self.assertEqual(sorted(os.listdir(victim)), ["keep"])
        home.unlink()
        os.mkdir(home, 0o700)
        os.symlink(victim / "keep", home / "lock")
        with self.assertRaises(OSError) as raised, shot_clock.fixture_dirs(home):
            pass
        self.assertEqual(raised.exception.errno, errno.ELOOP)
        self.assertEqual((victim / "keep").read_text(encoding="utf-8"), "mine")
        self.assertFalse((home / "root").exists())
        for name, setup in (("wrong", lambda h: (os.mkdir(h), os.chmod(h, 0o755))),
                            ("foreign", lambda h: os.mkdir(h, 0o700)),
                            ("owner-only", lambda h: (os.mkdir(h, 0o700), os.chmod(h, 0o300)))):
            fresh = base / name
            setup(fresh)
            foreign = mock.patch.object(shot_clock.os, "getuid", return_value=os.getuid() + (name == "foreign"))
            with self.subTest(name), foreign, self.assertRaises(PermissionError) as raised, \
                    shot_clock.fixture_dirs(fresh):
                pass
            self.assertIn(str(fresh), str(raised.exception))
            os.chmod(fresh, 0o700)
            self.assertEqual(os.listdir(fresh), [])

    def test_capture_holds_its_fixture_in_the_home_it_is_given(self) -> None:
        from . import console_screenshot_clock as shot_clock

        base = own_tempdir(self)
        home = base / "given"
        seen = []

        def fake(browser, url, state, width, out, **kwargs):
            seen.append(sorted(os.listdir(home / "root")))

        with stub_playwright(), mock.patch.object(shots, "_shoot", side_effect=fake):
            shots.capture(base / "out", states=("nothing-running",), widths=(1440,), home=home)
            self.assertEqual(len(seen), 1)
            self.assertIn("projects", seen[0])
            self.assertTrue((home / "lock").exists())
            self.assertFalse((home / "root").exists())
            self.assertFalse(shot_clock.shots_home().exists())
            with self.assertRaises(ValueError):
                shots.capture(home / "root" / "shots", states=("nothing-running",), home=home)
        self.assertFalse((home / "root" / "shots").exists())


if __name__ == "__main__":
    unittest.main()
