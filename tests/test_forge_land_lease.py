"""forge-claim land (D13): a delivery holds the land lock as a lease that beats, and the first in line takes over one that lapsed."""
from unittest import mock

from agent_tools.claims import forge_land_lock as land_lock

from . import test_forge_land_lock as base
from .test_forge_land_lock import (
    A,
    B,
    BEAT,
    C,
    D,
    DEFAULT,
    DEFAULT_READ,
    E,
    EPOCH,
    REF,
    SLUG,
    land,
    pull,
    release_pull,
    run,
)

TIER = "fast"

LEASE = "refs/agent-locks/land-lease/main/"


class LeaseTest(base.QueueTest):
    """D13: a delivery holds the lock as a lease that beats; the first in line takes
    over one whose beats stopped or that has held past its bound. The waiter under test is 11
    at A; 12 holds the lock at B and 13 waits at D."""

    def setUp(self):
        super().setUp()
        self.leased_by = {}

    def lease(self, pr, since, beat, sha=B):
        """Write the lease of `pr` at forge seconds `since` and `beat` after EPOCH, in place of the
        one this helper wrote before."""
        if pr in self.leased_by:
            self.world.set_ref(self.leased_by.pop(pr), None)
        self.leased_by[pr] = f"{LEASE}{EPOCH + int(since)}-{pr}-{EPOCH + int(beat)}"
        self.world.set_ref(self.leased_by[pr], sha)

    def leases(self):
        return {ref: sha for ref, sha in self.world.refs().items() if ref.startswith(LEASE)}

    def lease_creates(self):
        return [a[5][4:] for a in self.world.argvs("gh") if a[:4] == ["api", "-X", "POST", f"repos/{SLUG}/git/refs"]
                and a[5].startswith(f"ref={LEASE}")]

    def lock_swaps(self):
        return [a for a in self.cas_calls() if a[7] == f"name={REF}"]

    def live_holder(self, then=None, lease=True):
        """A hook for a holder that is alive: it moves the beat ref at every step and, when
        `lease`, rewrites the beat of its lease every 60 seconds."""
        state = {"steps": 0, "last": 0}

        def hook(elapsed):
            state["steps"] += 1
            self.world.set_ref(BEAT, f"{state['steps']:040x}")
            if lease and elapsed - state["last"] >= 60:
                state["last"] = elapsed
                self.lease(12, 0, elapsed)
            if then:
                then(elapsed)
        return hook

    def release_at(self, seconds, sha=None):
        """A hook step that frees the lock once, when `seconds` have passed."""
        done = []

        def step(elapsed):
            if elapsed >= seconds and not done:
                done.append(True)
                self.world.set_ref(REF, sha)
        return step

    def leased(self, clock, sha=A):
        with mock.patch.object(land_lock, "monotonic", clock.monotonic), \
                mock.patch.object(land_lock, "sleep", clock.sleep):
            return run(*land("acquire", sha, "--wait", "--lease"))

    def test_the_first_in_line_takes_over_a_lease_whose_beats_stopped_for_three_minutes(self):
        clock = self.clock()
        self.lease(12, 0, 0)
        code, out = self.leased(clock)
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "lapsed"))
        self.assertEqual(self.world.refs()[REF], A)
        self.assertGreaterEqual(out["waited_s"], 180)
        self.assertLess(out["waited_s"], 180 + land_lock.FAST_POLL + 20)
        self.assertEqual([ref for ref in self.leases() if "-12-" in ref], [])
        self.assertEqual([(ref.split("/")[-1].split("-")[1], sha) for ref, sha in self.leases().items()],
                         [("11", A)])

    def test_the_first_in_line_takes_over_a_lease_held_past_the_bound(self):
        self.lease(12, 0, 0)
        code, out = self.leased(self.clock(self.live_holder()))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "bound"))
        self.assertGreaterEqual(out["waited_s"], 1200)
        self.assertLess(out["waited_s"], 1200 + land_lock.FAST_POLL + 20)
        self.assertEqual(self.world.refs()[REF], A)
        self.assertEqual([ref for ref in self.leases() if "-12-" in ref], [])

    def test_a_waiter_that_is_not_first_never_takes_over_a_lease(self):
        self.lease(12, 0, 0)
        hook = self.live_holder(self.release_at(2000))
        code, out = self.leased(self.clock(hook, alive=-100))
        self.assertEqual((code, out["verdict"], out["took_over"], out["position"]), (0, "acquired", None, 2))
        self.assertEqual([a for a in self.lock_swaps() if a[-3] == f"before={B}"], [])
        self.assertGreaterEqual(out["waited_s"], 2000)

    def test_a_holder_with_no_lease_keeps_the_idle_takeover_only(self):
        code, out = self.leased(self.clock(self.live_holder(self.release_at(2000), lease=False)))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", None))
        self.assertGreaterEqual(out["waited_s"], 2000)
        self.assertEqual(self.lock_swaps(), [])

    def test_a_lease_left_at_an_older_sha_never_lapses_the_lock_that_moved_past_it(self):
        self.lease(12, 0, 0, sha=E)  # the moved lock's lease create failed, so this one stayed behind
        code, out = self.leased(self.clock(self.live_holder(self.release_at(2000), lease=False)))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", None))
        self.assertGreaterEqual(out["waited_s"], 2000)
        self.assertEqual([a for a in self.lock_swaps() if a[-3] == f"before={B}"], [])

    def test_a_release_holder_is_never_taken_over_by_the_lapse_or_the_bound(self):
        self.world.respond("gh", DEFAULT_READ, stdout=DEFAULT + "\n")
        self.pulls(B, release_pull(20, sha=B))
        code, out = self.leased(self.clock(self.live_holder(self.release_at(2000), lease=False)))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", None))
        self.assertGreaterEqual(out["waited_s"], 2000)
        self.assertEqual([a for a in self.lock_swaps() if a[-3] == f"before={B}"], [])

    def test_a_holder_that_lost_its_lease_waits_again_behind_the_earlier_waiter(self):
        self.lease(12, 0, 0)
        code, out = self.leased(self.clock(self.live_holder(), alive=50))
        self.assertEqual((code, out["took_over"]), (0, "bound"))
        now = out["waited_s"]
        self.pulls(C, pull(12, sha=C))
        seen, real_look, taken = [], land_lock.Queue.look, []

        def look(queue, pr, sha):
            real_look(queue, pr, sha)
            seen.append((pr, queue.position, list(queue.ahead)))

        def hook(elapsed):
            if elapsed >= 300 and not taken:
                taken.append(elapsed)  # the holder merges and its lock is released
                self.pulls(A, pull(11, state="closed", merged=True, sha=A))
                self.world.set_ref(REF, None)
            elif taken and len(taken) == 1 and elapsed >= taken[0] + 60:
                taken.append(elapsed)  # the first in line takes the lock
                self.register(13, None, None)
                self.world.set_ref(REF, D)
            elif len(taken) == 2 and elapsed >= taken[1] + 300:
                taken.append(elapsed)  # and merges
                self.pulls(D, pull(13, state="closed", merged=True, sha=D))
                self.world.set_ref(REF, None)
        clock = self.clock(hook, offset=now, alive=50)
        with mock.patch.object(land_lock.Queue, "look", look):
            code, out = self.leased(clock, sha=C)
        self.assertEqual(seen[0], (12, 2, [13]))
        self.assertEqual((code, out["verdict"], out["took_over"], out["lock_sha"]), (0, "acquired", None, C))
        self.assertEqual(len(taken), 3)
        self.assertGreaterEqual(out["waited_s"], taken[2])
        self.assertEqual(self.world.refs()[REF], C)

    def test_a_lease_dated_ahead_of_the_forge_clock_is_ignored(self):
        self.lease(12, 0, 5000)  # still ahead by more than QUEUE_SKEW when the lock is freed at 1500
        code, out = self.leased(self.clock(self.live_holder(self.release_at(1500), lease=False)))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", None))
        self.assertGreaterEqual(out["waited_s"], 1500)

    def test_lease_with_release_is_a_usage_error(self):
        code, out = run(*land("acquire", A, "--release", "--lease"))
        self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "usage"))
        self.assertEqual(self.world.argvs("gh"), [])

    def test_an_acquired_lease_is_written_moved_and_released(self):
        self.lock()
        self.pulls(A, pull(11, sha=A))
        code, out = run(*land("acquire", A, "--lease"))
        self.assertEqual((code, out["verdict"], out["lease"]), (0, "acquired", {"since": EPOCH, "beat": EPOCH}))
        self.assertEqual(self.leases(), {f"{LEASE}{EPOCH}-11-{EPOCH}": A})
        self.forge_time(100)
        self.pulls(C, pull(11, sha=C))
        self.pulls(A, pull(11, sha=C))
        code, out = run(*land("acquire", C, "--lease"))
        self.assertEqual((code, out["verdict"], out["lease"]), (0, "moved", {"since": EPOCH, "beat": EPOCH + 100}))
        self.assertEqual(self.leases(), {f"{LEASE}{EPOCH}-11-{EPOCH + 100}": C})
        code, out = run(*land("release", C))
        self.assertEqual((code, out["verdict"]), (0, "released"))
        self.assertEqual(self.world.refs(), {})

    def hold(self, clock, *extra):
        with mock.patch.object(land_lock, "monotonic", clock.monotonic), \
                mock.patch.object(land_lock, "sleep", clock.sleep):
            return run(*land("hold", A, *extra))

    def test_hold_beats_every_sixty_seconds_while_the_lock_is_at_its_sha(self):
        self.lock(A)
        self.pulls(A, pull(11, sha=A))
        self.lease(11, -30, -30, sha=A)
        code, out = self.hold(self.clock(), "--seconds", "180")
        self.assertEqual((code, out["verdict"]), (0, "held"))
        self.assertEqual([int(name.rsplit("-", 1)[1]) - EPOCH for name in self.lease_creates()], [0, 60, 120, 180])
        self.assertTrue(all(name.startswith(f"{LEASE}{EPOCH - 30}-11-") for name in self.lease_creates()))
        self.assertEqual(out["lease"], {"since": -30 + EPOCH, "beat": EPOCH + 180})
        self.assertEqual(out["held_s"], 210)
        self.assertEqual(self.leases(), {f"{LEASE}{EPOCH - 30}-11-{EPOCH + 180}": A})

    def test_hold_answers_not_held_once_the_lock_moved(self):
        self.lock(A)
        self.pulls(A, pull(11, sha=A))
        self.pulls(E, pull(13, sha=E))
        self.lease(11, 0, 0, sha=A)
        code, out = self.hold(self.clock(self.release_at(70, E)), "--seconds", "300")
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"]), (3, "not_held", E, 13))
        self.assertEqual([int(name.rsplit("-", 1)[1]) - EPOCH for name in self.lease_creates()], [60])

    def test_hold_with_no_lease_answers_unleased_and_writes_nothing(self):
        self.lock(A)
        self.pulls(A, pull(11, sha=A))
        code, out = self.hold(self.clock(), "--seconds", "60")
        self.assertEqual((code, out["verdict"]), (0, "unleased"))
        self.assertEqual(self.lease_creates(), [])

    def test_the_lease_timings(self):
        self.assertEqual((land_lock.HOLD_BOUND, land_lock.LEASE_BEAT, land_lock.LEASE_LAPSE), (1200, 60, 180))
        self.assertLess(land_lock.LEASE_LAPSE, land_lock.HOLD_BOUND)
        self.assertLess(land_lock.HOLD_BOUND, land_lock.IDLE_AFTER)
        self.assertLess(land_lock.IDLE_AFTER, land_lock.BOUND)
        self.assertEqual(land_lock.HOLD_MAX, land_lock.BOUND)
