"""The screenshot set's fixed clock reading, page and fixture root.

Run: just agent-workflow-tests
"""
import contextlib
import http.client
import io
import json
import os
import shutil
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
