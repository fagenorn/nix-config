"""forge-claim land (D13): a delivery holds the land lock as a lease that beats, and the first in line takes over one that lapsed."""
import sys
from unittest import mock

from agent_tools.claims import forge_land_lock as land_lock
from agent_tools.claims import forge_markers as fm
from agent_tools.system import forge_api

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
        self.assertGreaterEqual(out["waited_s"], 2400)
        self.assertLess(out["waited_s"], 2400 + land_lock.FAST_POLL + 20)
        self.assertEqual(self.world.refs()[REF], A)
        self.assertEqual([ref for ref in self.leases() if "-12-" in ref], [])

    def test_a_holder_whose_required_check_runs_1740_seconds_is_not_taken_over_at_the_bound(self):
        """The slowest required check of the 26 Nov runs took 1807 s; a holder that beats through a 1740 s check and
        then merges keeps the lock from the first in line, which waits for the release and takes nothing over."""
        self.lease(12, 0, 0)
        hook = self.live_holder(self.release_at(1740, None))
        code, out = self.leased(self.clock(hook))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", None))
        self.assertGreaterEqual(out["waited_s"], 1740)
        self.assertEqual([a for a in self.lock_swaps() if a[-3] == f"before={B}"], [])
        self.assertEqual(self.world.refs()[REF], A)

    def test_a_holder_still_holding_at_1740_seconds_with_beats_stopped_is_taken_over_as_lapsed(self):
        self.lease(12, 0, 0)
        hook = self.live_holder(lease=False)
        code, out = self.leased(self.clock(hook))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "lapsed"))
        self.assertLess(out["waited_s"], 1740)

    def test_a_waiter_that_is_not_first_never_takes_over_a_lease(self):
        self.lease(12, 0, 0)
        hook = self.live_holder(self.release_at(2600))  # beats past the 2400 s bound
        code, out = self.leased(self.clock(hook, alive=-100))
        self.assertEqual((code, out["verdict"], out["took_over"], out["position"]), (0, "acquired", None, 2))
        self.assertEqual([a for a in self.lock_swaps() if a[-3] == f"before={B}"], [])
        self.assertGreaterEqual(out["waited_s"], 2600)

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

    def detach(self, *extra):
        with mock.patch.object(land_lock, "spawn_beater", return_value=4242) as spawn:
            code, out = run(*land("hold", A, "--detach", *extra))
        return code, out, spawn

    def test_hold_detach_beats_once_and_leaves_a_background_beater_for_the_whole_step(self):
        """A step whose own command runs for minutes cannot run `hold --seconds` beside it: it starts the beater and goes on."""
        self.lock(A)
        self.pulls(A, pull(11, sha=A))
        self.lease(11, -30, -30, sha=A)
        code, out, spawn = self.detach()
        self.assertEqual((code, out["verdict"]), (0, "beating"))
        self.assertEqual([int(name.rsplit("-", 1)[1]) - EPOCH for name in self.lease_creates()], [0])
        self.assertEqual(out["lease"], {"since": EPOCH - 30, "beat": EPOCH})
        self.assertEqual(out["seconds"], 3000)
        spawn.assert_called_once()
        self.assertEqual(spawn.call_args.args[1], 3000)
        self.assertEqual(spawn.call_args.args[0].sha, A)

    def test_hold_detach_beats_for_the_seconds_it_is_given(self):
        self.lock(A)
        self.pulls(A, pull(11, sha=A))
        self.lease(11, 0, 0, sha=A)
        code, out, spawn = self.detach("--seconds", "600")
        self.assertEqual((code, out["verdict"], out["seconds"]), (0, "beating", 600))
        self.assertEqual(spawn.call_args.args[1], 600)

    def test_hold_detach_answers_not_held_at_once_and_starts_no_beater(self):
        self.lock(E)
        self.pulls(E, pull(13, sha=E))
        code, out, spawn = self.detach()
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"]), (3, "not_held", E, 13))
        spawn.assert_not_called()
        self.assertEqual(self.lease_creates(), [])

    def test_hold_detach_with_no_lease_answers_unleased_and_starts_no_beater(self):
        self.lock(A)
        self.pulls(A, pull(11, sha=A))
        code, out, spawn = self.detach()
        self.assertEqual((code, out["verdict"]), (0, "unleased"))
        spawn.assert_not_called()

    def test_hold_without_detach_starts_no_beater(self):
        self.lock(A)
        self.pulls(A, pull(11, sha=A))
        self.lease(11, 0, 0, sha=A)
        with mock.patch.object(land_lock, "spawn_beater") as spawn:
            code, out = self.hold(self.clock(), "--seconds", "60")
        self.assertEqual((code, out["verdict"]), (0, "held"))
        spawn.assert_not_called()

    def test_the_beater_is_the_same_hold_in_its_own_session_with_no_streams(self):
        args = mock.Mock(repo=SLUG, branch="main", sha=A)
        with mock.patch.object(land_lock.subprocess, "Popen") as popen:
            land_lock.spawn_beater(args, 900)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[1:], ["-m", "agent_tools.claims.forge_claim", "land", "hold", "--repo", SLUG, "--branch", "main",
                                    "--sha", A, "--seconds", "900"])
        kw = popen.call_args.kwargs
        self.assertIs(kw["start_new_session"], True)
        self.assertEqual((kw["stdin"], kw["stdout"], kw["stderr"]), (land_lock.subprocess.DEVNULL,) * 3)

    def test_the_beater_of_an_isolated_caller_runs_isolated_and_inherits_no_path(self):
        """C4: the child of an installed launcher (python -I) must not import a module from the working directory."""
        args = mock.Mock(repo=SLUG, branch="main", sha=A)
        for isolated, flag in ((1, ["-I"]), (0, [])):
            with self.subTest(isolated=isolated), mock.patch.object(sys, "flags", mock.Mock(isolated=isolated)), \
                    mock.patch.object(land_lock.subprocess, "Popen") as popen:
                land_lock.spawn_beater(args, 900)
            self.assertEqual(popen.call_args.args[0][:3 + len(flag)], [sys.executable, *flag, "-m", "agent_tools.claims.forge_claim"])
            self.assertNotIn("env", popen.call_args.kwargs)

    def test_the_beater_is_told_its_owner(self):
        args = mock.Mock(repo=SLUG, branch="main", sha=A)
        with mock.patch.object(land_lock.subprocess, "Popen") as popen:
            land_lock.spawn_beater(args, 900, (77, "Thu Nov 26 07:28:26 2026"))
        self.assertEqual(popen.call_args.args[0][-4:], ["--owner", "77", "--owner-start", "Thu Nov 26 07:28:26 2026"])

    def test_hold_detach_hands_the_owner_it_found_to_the_beater(self):
        self.lock(A)
        self.pulls(A, pull(11, sha=A))
        self.lease(11, 0, 0, sha=A)
        with mock.patch.object(land_lock, "find_owner", return_value=(77, "T")), \
                mock.patch.object(land_lock, "spawn_beater", return_value=4242) as spawn:
            code, out = run(*land("hold", A, "--detach"))
        self.assertEqual((code, out["verdict"]), (0, "beating"))
        self.assertEqual(spawn.call_args.args[2], (77, "T"))

    def ps(self, table):
        """`ps -o ppid=,lstart=,comm= -p <pid>` answering from `table` {pid: (ppid, command)}."""
        def run_ps(argv, **_):
            pid = int(argv[-1])
            if pid not in table:
                return mock.Mock(returncode=1, stdout="")
            parent, command = table[pid]
            return mock.Mock(returncode=0, stdout=f"{parent:>6} Thu Nov 26 07:28:26 2026 {command}\n")
        return mock.patch.object(land_lock.subprocess, "run", side_effect=run_ps)

    def test_the_owner_is_the_nearest_ancestor_that_is_not_a_shell(self):
        """C2: the lander's session, past the launcher's bash and the tool's zsh, which the next step's shell outlives."""
        table = {300: (200, "/bin/zsh"), 200: (100, "-bash"), 100: (50, "/usr/bin/claude"), 50: (1, "/sbin/launchd")}
        with mock.patch.object(land_lock.os, "getppid", return_value=300), self.ps(table):
            self.assertEqual(land_lock.find_owner(), (100, "Thu Nov 26 07:28:26 2026"))

    def test_there_is_no_owner_when_the_chain_ends_at_init_or_ps_knows_nothing(self):
        with mock.patch.object(land_lock.os, "getppid", return_value=300), self.ps({300: (1, "zsh")}):
            self.assertIsNone(land_lock.find_owner())
        with mock.patch.object(land_lock.os, "getppid", return_value=300), self.ps({}):
            self.assertIsNone(land_lock.find_owner())

    def test_an_owner_is_alive_only_while_its_pid_runs_with_the_same_start(self):
        table = {100: (50, "claude")}
        with mock.patch.object(land_lock.os, "kill"), self.ps(table):
            self.assertTrue(land_lock.owner_alive(100, "Thu Nov 26 07:28:26 2026"))
            self.assertFalse(land_lock.owner_alive(100, "Wed Nov 25 01:00:00 2026"))
        with mock.patch.object(land_lock.os, "kill", side_effect=ProcessLookupError):
            self.assertFalse(land_lock.owner_alive(100, "Thu Nov 26 07:28:26 2026"))

    def test_a_beater_whose_owner_is_gone_stops_beating_and_lets_the_lease_lapse(self):
        """C2: a lander that died with its pull request open must not keep the lock for the 40-minute bound."""
        self.lock(A)
        self.pulls(A, pull(11, sha=A))
        self.lease(11, 0, 0, sha=A)
        with mock.patch.object(land_lock, "owner_alive", side_effect=[True, True, False]) as alive:
            code, out = self.hold(self.clock(), "--seconds", "3000", "--owner", "77", "--owner-start", "T")
        self.assertEqual((code, out["verdict"]), (0, "abandoned"))
        # the lease written at 0 stands; the beat at 60 is the last, and none follows the owner's death at 120
        self.assertEqual([int(name.rsplit("-", 1)[1]) - EPOCH for name in self.lease_creates()], [60])
        self.assertEqual(alive.call_args.args, (77, "T"))

    def test_a_beater_with_a_live_owner_beats_to_its_end(self):
        self.lock(A)
        self.pulls(A, pull(11, sha=A))
        self.lease(11, 0, 0, sha=A)
        with mock.patch.object(land_lock, "owner_alive", return_value=True):
            code, out = self.hold(self.clock(), "--seconds", "120", "--owner", "77", "--owner-start", "T")
        self.assertEqual((code, out["verdict"]), (0, "held"))

    def test_the_lease_timings(self):
        # 2400 s is the slowest required check of the last 48 passing runs on 26 Nov (1807 s) with a margin of a third.
        self.assertEqual((land_lock.HOLD_BOUND, land_lock.LEASE_BEAT, land_lock.LEASE_LAPSE), (2400, 60, 180))
        self.assertGreater(land_lock.HOLD_BOUND, 1807)
        self.assertLess(land_lock.LEASE_LAPSE, land_lock.HOLD_BOUND)
        self.assertLess(land_lock.HOLD_BOUND, land_lock.IDLE_AFTER)
        self.assertLess(land_lock.IDLE_AFTER, land_lock.BOUND)
        self.assertEqual(land_lock.HOLD_MAX, land_lock.BOUND)

    def test_a_holder_whose_beat_repeats_keeps_a_lease_beating_within_its_bound_from_the_idle_takeover(self):
        """The beat reads C at every poll, so the idle watch never restarts; the lease does."""
        self.world.reset()
        self.lock(B, refuse_to=(C, D))
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, sha=B))
        for sha, parent in ((B, C), (C, D), (D, None)):
            self.world.respond_json("gh", ["api", f"repos/{SLUG}/git/commits/{sha}"],
                                    {"sha": sha, "parents": [{"sha": parent}] if parent else []})
        self.world.set_ref(BEAT, C)
        refreshes, beats, holds, state = [], [], [], {"refreshed": None, "held": None, "leased": False}

        def hook(elapsed):
            if state["refreshed"] is None or elapsed - state["refreshed"] >= 60:
                state["refreshed"] = elapsed
                refreshes.extend([run(*land("refresh", B)), run(*land("refresh", B))])
                beats.append(self.world.refs().get(BEAT))
            if elapsed >= 1700 and not state["leased"]:
                state["leased"] = True
                state["held"] = elapsed
                holds.append(run(*land("acquire", B, "--lease")))
            elif state["leased"] and elapsed - state["held"] >= 60:
                state["held"] = elapsed
                holds.append(run(*land("hold", B)))
        code, out = self.leased(self.clock(hook))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "bound"))
        self.assertGreaterEqual(out["waited_s"], 2900)
        self.assertLess(out["waited_s"], 2900 + land_lock.FAST_POLL + 20)
        self.assertEqual([(c, o["verdict"]) for c, o in refreshes], [(0, "refreshed")] * len(refreshes))
        self.assertEqual(set(beats), {C})
        self.assertEqual(self.world.refs()[REF], A)

    def test_a_holder_renewing_only_through_acquire_lease_is_never_taken_over_as_idle(self):
        answers = []

        def hook(elapsed):
            if elapsed >= 1900:
                answers.append(run(*land("acquire", B, "--lease")))
        code, out = self.leased(self.clock(hook, alive=-100))
        self.assertEqual((code, out["verdict"], out["waited_s"], out["pr"], out["position"]),
                         (3, "land-contended", 3000, 12, 2))
        self.assertTrue(answers)
        for answer_code, answer in answers:
            self.assertEqual((answer_code, answer["verdict"]), (0, "already_held"))
            self.assertEqual(answer["lease"]["since"], EPOCH + 1920)
        self.assertEqual(self.world.refs()[REF], B)
        self.assertEqual([a for a in self.lock_swaps() if a[-3] == f"before={B}"], [])

    def test_a_lease_that_lapsed_or_passed_its_bound_does_not_stop_the_idle_takeover(self):
        for name in ("lapsed", "past_bound"):
            with self.subTest(lease=name):
                self.world.reset()
                self.prepare(B)
                self.leased_by = {}
                hook = None
                if name == "lapsed":
                    self.lease(12, 2000, 2000)
                else:
                    def hook(elapsed):
                        if elapsed >= 1000:
                            self.lease(12, 1000, elapsed)
                code, out = self.leased(self.clock(hook, alive=-100))
                self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]),
                                 (0, "acquired", "idle", 2760))

    def test_a_failed_read_at_the_idle_deadline_takes_nothing_over_that_poll(self):
        for name in ("leases", "queue"):
            with self.subTest(failed=name):
                self.world.reset()
                self.prepare(B)
                self.leased_by = {}
                clock, failed = self.clock(alive=-100), []

                def fail_once(real, due=lambda: True):
                    def read(*args):
                        if not failed and due():
                            failed.append(True)
                            raise forge_api.ForgeError("gh_failed", "x")
                        return real(*args)
                    return read
                if name == "leases":
                    patch = mock.patch.object(land_lock, "read_leases", fail_once(land_lock.read_leases))
                else:
                    self.lease(12, 2000, 2000)
                    def due():
                        return clock.monotonic() - clock.start >= 2700
                    look = fail_once(land_lock.Queue.look, due)
                    patch = mock.patch.object(land_lock.Queue, "look", lambda queue, *args: look(queue, *args))
                with patch:
                    code, out = self.leased(clock)
                self.assertEqual(failed, [True])
                self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]),
                                 (0, "acquired", "idle", 2880))

    def test_a_renewal_whose_replaced_lease_cannot_be_deleted_is_not_confirmed(self):
        self.lock(B, refuse_to=(fm.ZERO_OID,))
        self.pulls(B, pull(12, sha=B))
        self.lease(12, 0, 0)
        self.forge_time(100)
        code, out = run(*land("acquire", B, "--lease"))
        self.assertEqual((code, out["verdict"], out["lease"]), (0, "already_held", None))
        self.assertEqual(self.leases(), {f"{LEASE}{EPOCH}-12-{EPOCH}": B, f"{LEASE}{EPOCH}-12-{EPOCH + 100}": B})

    def test_a_move_whose_source_lease_cannot_be_deleted_is_not_confirmed(self):
        self.lock(A, refuse_to=(fm.ZERO_OID,))
        self.pulls(A, pull(11, sha=A))
        self.lease(11, 0, 0, sha=A)
        self.forge_time(100)
        self.pulls(C, pull(11, sha=C))
        self.pulls(A, pull(11, sha=C))
        code, out = run(*land("acquire", C, "--lease"))
        self.assertEqual((code, out["verdict"], out["lease"]), (0, "moved", None))
        self.assertEqual(self.world.refs()[REF], C)
        self.assertEqual(self.leases(), {f"{LEASE}{EPOCH}-11-{EPOCH}": A, f"{LEASE}{EPOCH}-11-{EPOCH + 100}": C})

    def test_a_hold_whose_replaced_lease_cannot_be_deleted_is_a_forge_error(self):
        self.lock(A, refuse_to=(fm.ZERO_OID,))
        self.pulls(A, pull(11, sha=A))
        self.lease(11, -30, -30, sha=A)
        code, out = run(*land("hold", A))
        self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "gh_failed"))
        leases = self.leases()
        for name in (f"{LEASE}{EPOCH - 30}-11-{EPOCH - 30}", f"{LEASE}{EPOCH - 30}-11-{EPOCH}"):
            self.assertEqual(leases.get(name), A)

    def test_hold_renews_the_same_lease_whatever_order_the_forge_lists_them_in(self):
        original = fm.matching_refs
        records = []
        for reverse in (False, True):
            self.lock(A)
            self.pulls(A, pull(11, sha=A))
            self.leased_by = {}
            self.lease(11, 0, 0, sha=A)
            self.lease(13, 0, 0, sha=A)
            self.forge_time(60)

            def listed(*args, reverse=reverse):
                found = original(*args)
                return dict(sorted(found.items(), reverse=reverse))

            with mock.patch.object(fm, "matching_refs", listed):
                code, out = run(*land("hold", A))
            records.append((code, out["verdict"], out["pr"], self.leases()))
        self.assertEqual(records[0], records[1])

    def lock_lost_with_no_lease_left(self, code_out):
        code, out = code_out
        self.assertEqual((code, out["verdict"], out["lease"]), (0, "already_held", None))
        self.assertEqual([ref for ref, sha in self.leases().items() if sha == B], [])
        self.assertEqual(self.world.refs()[REF], A)

    def test_an_acquire_that_loses_the_lock_before_it_lists_leases_reports_lease_null(self):
        self.lease(12, 0, 0)
        self.forge_time(100)
        original = land_lock.read_leases
        staged = []

        def listed(*args):
            if not staged:
                staged.append(True)
                self.world.set_ref(REF, A)
                self.world.set_ref(self.leased_by[12], None)
            return original(*args)

        with mock.patch.object(land_lock, "read_leases", listed):
            self.lock_lost_with_no_lease_left(run(*land("acquire", B, "--lease")))

    def test_an_acquire_that_loses_the_lock_after_its_lease_write_removes_that_lease(self):
        self.lease(12, 0, 0)
        self.forge_time(100)
        original = fm.create_ref

        def created(slug, ref, sha):
            made = original(slug, ref, sha)
            if ref.startswith(LEASE):
                self.world.set_ref(REF, A)
            return made

        with mock.patch.object(fm, "create_ref", created):
            self.lock_lost_with_no_lease_left(run(*land("acquire", B, "--lease")))

    def refusing_deletes(self, refs, times=None):
        """A `cas_ref` that refuses to delete `refs` (the first `times` attempts when given)."""
        real, refused = fm.cas_ref, []

        def cas(slug, node, ref, before, after):
            if after == fm.ZERO_OID and ref in refs and (times is None or len(refused) < times):
                refused.append(ref)
                return forge_api.ForgeError("gh_failed", "refused")
            return real(slug, node, ref, before, after)
        return mock.patch.object(fm, "cas_ref", cas)

    def test_holders_sharing_a_lock_sha_with_tied_leases_agree_on_the_lease_hold_renews(self):
        self.pulls(B, pull(12, sha=B), pull(14, sha=B))
        self.lease(12, 0, 0)
        self.lease(14, 0, 0)
        state = {"held": -60}

        def hook(elapsed):
            if elapsed - state["held"] >= 60:
                state["held"] = elapsed
                code, out = run(*land("hold", B))
                self.assertEqual((code, out["verdict"]), (0, "held"))
        code, out = self.leased(self.clock(hook))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "bound"))
        self.assertGreaterEqual(out["waited_s"], 1200)
        self.assertLess(out["waited_s"], 1200 + land_lock.FAST_POLL + 20)

    def test_a_delayed_acquire_never_prunes_the_lease_of_the_lock_that_moved_on(self):
        self.pulls(B, pull(12, sha=B))
        self.lease(12, 0, 0)
        self.forge_time(100)
        successor = f"{LEASE}{EPOCH}-12-{EPOCH + 90}"
        original, staged = land_lock.read_leases, []

        def listed(*args):
            if not staged:
                staged.append(True)  # the same pull request moves to C and publishes its lease first
                self.world.set_ref(REF, C)
                self.world.set_ref(successor, C)
            return original(*args)

        with mock.patch.object(land_lock, "read_leases", listed):
            code, out = run(*land("acquire", B, "--lease"))
        self.assertEqual((code, out["verdict"], out["lease"]), (0, "already_held", None))
        self.assertEqual(self.world.refs()[REF], C)
        self.assertEqual(self.leases().get(successor), C)
        self.assertEqual(sorted(self.leases().values()), [B, C])
        self.assertEqual(self.lease_creates(), [])

    def lock_lost_after_the_write(self):
        original = fm.create_ref

        def created(slug, ref, sha):
            made = original(slug, ref, sha)
            if ref.startswith(LEASE):
                self.world.set_ref(REF, A)
            return made
        return mock.patch.object(fm, "create_ref", created)

    def test_a_lost_lock_removes_the_new_lease_although_an_older_one_cannot_be_deleted(self):
        self.lease(12, 0, 0)
        self.forge_time(100)
        older = self.leased_by[12]
        with self.lock_lost_after_the_write(), self.refusing_deletes({older}):
            code, out = run(*land("acquire", B, "--lease"))
        self.assertEqual((code, out["verdict"], out["lease"]), (0, "already_held", None))
        self.assertEqual(self.leases(), {older: B})

    def test_a_lost_lock_deletes_its_new_lease_again_when_the_first_deletion_is_refused(self):
        self.lease(12, 0, 0)
        self.forge_time(100)
        newest = f"{LEASE}{EPOCH}-12-{EPOCH + 100}"
        with self.lock_lost_after_the_write(), self.refusing_deletes({newest}, times=1):
            self.lock_lost_with_no_lease_left(run(*land("acquire", B, "--lease")))

    def test_a_failed_lease_read_at_the_idle_deadline_is_not_reread_by_the_first_in_line(self):
        self.lease(12, 0, 0)  # lapsed long ago, but 13 stood ahead of 11 until the idle deadline
        self.register(13, 0, 0)
        failed, real, clock = [], land_lock.read_leases, None

        def hook(elapsed):
            if elapsed >= 2700:
                self.register(13, None, None)

        def read(*args):
            if clock.monotonic() - clock.start >= 2700 and not failed:
                failed.append(True)
                raise forge_api.ForgeError("gh_failed", "x")
            return real(*args)
        clock = self.clock(hook, alive=-100)
        with mock.patch.object(land_lock, "read_leases", read):
            code, out = self.leased(clock)
        self.assertEqual(failed, [True])
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "idle"))
