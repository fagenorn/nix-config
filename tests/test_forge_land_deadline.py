"""forge-claim land --wait: a deadline that passes mid-poll ends the wait, whatever the lock does in the gap."""
from unittest import mock

from agent_tools.claims import forge_land_lock as land_lock

from .test_forge_land_lock import A, B, C, REF, Base, land, pull, run

TIER = "fast"


class ReadingClock:
    """`monotonic` and `sleep` for forge_land_lock, scripted by the number of readings taken.

    The reading numbered `jump_at` (from 1) finds the clock `late` seconds past the bound and runs
    `on_jump`; `before_sleep` lists, for every sleep, the number of readings taken so far."""

    def __init__(self, jump_at=None, on_jump=None, late=5, on_sleep=None):
        self.start = self.now = 1000.0
        self.on_sleep = on_sleep
        self.reads, self.before_sleep, self.slept = 0, [], []
        self.jump_at, self.on_jump, self.late = jump_at, on_jump, late

    def monotonic(self):
        self.reads += 1
        if self.reads == self.jump_at:
            self.now = self.start + land_lock.BOUND + self.late
            if self.on_jump:
                self.on_jump()
        return self.now

    def sleep(self, seconds):
        if seconds < 0:
            raise ValueError("sleep length must be non-negative")
        self.before_sleep.append(self.reads)
        self.slept.append(seconds)
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(self.now - self.start)


class DeadlineTest(Base):
    def prepare(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, sha=B))
        self.pulls(C, pull(12, sha=C))

    def holder_moves(self):
        """The holder moves its lock at 2400 seconds, so no idle takeover fires before the bound."""
        done = []

        def on_sleep(elapsed):
            if elapsed >= 2400 and not done:
                done.append(True)
                self.world.set_ref(REF, C)
        return on_sleep

    def wait(self, clock):
        with mock.patch.object(land_lock, "monotonic", clock.monotonic), \
                mock.patch.object(land_lock, "sleep", clock.sleep):
            return run(*land("acquire", A, "--wait"))

    def test_a_deadline_that_passes_between_the_check_and_the_sleep_times_out_without_a_late_poll(self):
        self.prepare()
        calibration = ReadingClock(on_sleep=self.holder_moves())  # no jump: where its last sleep falls
        self.assertEqual(self.wait(calibration)[0], 3)
        reading_before_last_sleep = calibration.before_sleep[-1]  # the reading that sizes that sleep

        self.prepare()
        clock = ReadingClock(jump_at=reading_before_last_sleep, on_sleep=self.holder_moves(),
                             on_jump=lambda: self.world.set_ref(REF, None))  # the holder lets go in the gap
        code, out = self.wait(clock)
        self.assertTrue(clock.now - clock.start > land_lock.BOUND)  # the jump fell before the last sleep
        self.assertEqual((code, out["verdict"], out["waited_s"]), (3, "land-contended", land_lock.BOUND + 5))
        self.assertEqual(self.attempts(), [])  # no create of the free lock after the bound
        self.assertEqual(self.cas_calls(), [])
        self.assertIsNone(self.world.refs().get(REF))
