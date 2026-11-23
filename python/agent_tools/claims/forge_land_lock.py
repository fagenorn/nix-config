"""The cross-host land lock (issue 629): `forge-claim land acquire|release|status|refresh|hold`.

The lock serialises landings on one branch across hosts. Each action takes `--repo <owner/name>`,
`--branch <name>` and `--sha <40 hex>`; `--wait` and `--release` exist on `acquire` only, as does
`--follow-head`, which needs both (a usage error otherwise). `--lease` exists on `acquire` only
and is a usage error with `--release` (D13); `hold` takes `--seconds`.

D1, the lock is the ref `refs/agent-locks/land/<branch>`, whose value is a pull-request head sha:
created by REST `POST git/refs` (HTTP 422 means not created), moved and deleted by the
`updateRefs` compare-and-swap with `beforeOid` and `force: true`. A failed compare-and-swap
answers HTTP 200 with a generic error, so any CAS error counts as not done and the ref is
re-read to classify the outcome: the caller's sha is success, another oid or no ref is a lost
race, and the observed oid unchanged is a forge error carrying the CAS's own code and transport
class (issue 740), never a lost race. REST ref deletion is unconditional and never used.

D2, the holder is derived, not stored, and the head decides: `classify` reads the pull requests
that contain the lock sha (`_on_branch`: the forge's commit lookup `GET commits/<sha>/pulls`, which
for a commit outside the default branch lists open pull requests only, so a squash-merged,
rebase-merged or closed-unmerged holder gets `[]`; plus the closed pull requests headed at the
lock, found by head sha in the closed listing `GET pulls?state=closed&base=<branch>&sort=updated`,
at most 5 pages of 100), and only an open pull request whose head is the lock holds it: the lock
is held while it is the head of an open pull request other than the caller's, and a pull request
that merely contains the lock's sha (a branch stacked on the holder) never holds or moves it.
For a commit on the default branch the commit lookup lists merged pull requests only (issue 905),
so it leaves out an open pull request whose head is already there, as the head of every sync of
the default branch back into the locked branch is. When the lookup lists no pull request headed
at the lock, the open pull requests based on the branch are therefore read before the closed
ones (`GET pulls?state=open&base=<branch>&sort=updated`, at most 5 pages of 100, matched by head
sha), and a same-repository one headed at the lock holds it, whatever closed pull requests share
that head or contain it; the closed listing is read only when none is found. A fork's pull
request is never taken from this listing, and an open one beyond those pages is not seen.
Every fork already has the default branch's commits, so a fork's pull request opened at the
default tip would otherwise hold a lock there, or keep a stale one looking held, without pushing a
commit. The open listing goes before the closed one for two reasons: a waiter polls behind a live
holder every `POLL` seconds while a stale lock is classified once and then taken, so the repeated
path gets the shorter chain; and a closed pull request must never decide a lock that an open one
with the same head holds, as when a sync pull request is closed and opened again from the same
commit.
A release pull request (issue 875) is one whose head is the locked branch itself, in the same
repository, at the lock: `_on_branch` counts it whatever its base, so every caller derives it as
the holder with no flag. The commit lookup lists it while it is open; when no listing above
has a pull request headed at the lock, one the lookup left out, open or closed, is found in `GET
pulls?state=all&head=<owner>:<branch>&sort=updated` (one page of 100), so a live release lock is
never judged by the merged pull requests that contain it. A fork's branch of the same name is
never counted.

D3, staleness follows the owner's option-B decision on issue 629
(https://github.com/fagenorn/nix-config/issues/629#issuecomment-6693579241): no wall clock and no
event is read; a one-shot `status` or `acquire` treats a lock as stale only when `classify` answers
`closed` (the lock of a merged or closed pull request), takes only that over, and never takes over
a `held` lock. A published (merged) or closed release pull request is stale the same way.

D4, the only idle takeover is `wait_acquire`'s, of an oid this process has itself watched
unchanged for `IDLE_AFTER` seconds (45 minutes) of `monotonic()`, counted from its first
observation of that oid; nothing is persisted, so every `--wait` invocation starts a fresh watch.
Every completed ref observation, a lost CAS's re-read and an observed absence included, restarts
the watch when the oid differs, and so does a holder's refresh (D11). A one-shot `acquire` at the
lock's own sha answers `already_held` and changes nothing, so it restarts no watch. A holder runs a one-shot `acquire` with its sha right before the
merge and merges only when its verdict is `already_held` or `moved`, never on exit status alone:
`acquired` also exits 0 and means the lock was lost and taken again, so the base may have moved and
the holder resyncs first. A release holder merges only on `already_held` (ADR-claims-009). A lock
held as a lease (D13) is also taken over by the first waiter in line, sooner than this watch.

D5, a lock moves to the caller's new head (verdict `moved`: the lock sat at an earlier head of the
same pull request) only when every open pull request containing it is the caller's; a branch
merely stacked on the holder's head never moves it. A lock that a pull request headed by the
locked branch contains, in the same repository and whatever its head, never answers `moved`: the
branch itself has reached that sha, so where this rule would move the lock it is taken over as
`closed` instead and the caller, answered `acquired`, resyncs. That covers a published release
whose lock the caller's pull request alone still contains, and a release whose head moved past
its lock, which releases the old lock and acquires again. A following release wait (D6) does that
itself (issue 901): a poll that finds the lock held at `--sha` while the release pull request's
head is another sha sends the D9 delete of `--sha`, exactly what `release --sha` does, and attempts
again in the same poll, competing with every other waiter. It first reads the commit lookup of
`--sha` (and, when that lists no such head, the open listing of D2) and leaves the lock alone when
an open pull request other than the release has its head there: that one holds it. The answer is `acquired` or `already_held`, never `moved`, so nobody
merges on a lock that changed hands without a resync.

D6, `acquire` needs an open pull request whose head is the caller's sha with the branch as its
base before any ref write, and otherwise answers `error` with `no_open_pr` (exit 2). `--wait`
re-checks this before every attempt, the first included: a caller whose pull request no longer has
`--sha` as its head stops with `no_open_pr` and never moves the lock. When the commit lookup of
`--sha` lists no such pull request, the open listing of D2 is read once for a same-repository one
(issue 905: a head on the default branch), so the common path makes no extra call and `no_open_pr`
is answered only after both reads. With `--release` the pull
request needed is instead an open one whose head branch is `--branch` at `--sha`, in the same
repository (never a fork's branch of that name), with the repository's default branch as its base;
the default branch is read once per invocation (`GET repos/<slug>`). With `--follow-head` a
waiting release follows its pull request instead (issue 901), because every landing ahead of it
moves the release head: each poll of `--release --wait --follow-head` reads the open pull requests
headed by `--branch` (`GET pulls?state=open&head=<owner>:<branch>`, one call in place of the commit
lookup), keeps the same-repository one based on the default branch, and attempts the lock at that
pull request's current head. `--sha` is then only the caller's starting belief, and `no_open_pr`
means no such pull request is open. Without the flag nothing follows: a one-shot `--release`, and
a `--release --wait` whose caller is bound to `--sha` (a resumed release), stop with `no_open_pr`
when the head moved.

D7, every call prints one JSON object on one stdout line with `command`, `action`, `repo`,
`branch`, `sha`, `verdict`, `lock_sha`, `pr`, `by`, `took_over` (`null`, `"closed"`, `"idle"`,
`"lapsed"` or `"bound"`, the last two of a lease, D13) and `waited_s`. `sha` is always `--sha` as given and `lock_sha` is where the lock is: a successful
`acquire --release --wait --follow-head` adds `head_moved`, true when it took the lock at a head other than
`--sha`, and the caller continues with `lock_sha` as its commit. `acquire --wait` adds `waited_on`
(issue 913): the pull requests, in ascending order, its polls saw holding the lock while it waited,
on a successful answer and on `land-contended` alike, `[]` when no poll was held off; `by` is derived
only on a refusal, so a wait that succeeds is attributed by these numbers. On the same two answers
`acquire --wait` adds `position` and `ahead` (D12): its place in the waiters' queue as last read
(1 is first in line; `null` when the queue was never read, as for a caller that already holds
the lock, or when its last read failed) and the pull requests ahead of it, oldest first. The `acquire` verdicts are
`acquired`, `already_held` (the lock is already at `--sha`, or at the followed head), `moved`,
`held_by` and `lost_to`. Exit 0 is `acquired`, `already_held`, `moved`,
`released` and every `status` verdict (`free`, `held_by`, `stale`); exit 3 is contention
(`held_by`, `lost_to`, `land-contended`, and `not_held` on `release`); exit 1 a forge error; exit 2
a usage error or `no_open_pr`.

D8, `--wait` attempts at offsets 0, `POLL` (120 s), ... `BOUND` (3000 s), sooner when it is first
in line and sees the lock change (D12), and then answers `land-contended` (exit 3). `BOUND` is 50 minutes so that one invocation ends by itself inside a
60-minute Bash call (issue 941), and stays above `IDLE_AFTER` so that one invocation can still
complete an idle watch; a `gh_failed`/`gh_timeout` poll counts as failed, an unapplied CAS on an
unchanged lock included, and `FAILED_POLLS` in a row exit 1 with that error; only a poll that
completes with a verdict resets the count. Every poll, the first included, reads the caller's
eligible pull requests (D6) inside the poll, so a failed read is a failed poll and a transport
failure there waits for the next poll instead of exiting at once (issue 740). The whole-verb
transport retry of `forge_claim` never wraps `--wait`, whose failed-poll count is its own bound.

D9, `release` is a compare-and-swap delete sent without a prior read, then re-read.

D10, a swap that reported no failure whose read-back still shows the old lock is read again up to
`READBACK_RETRIES` times, `READBACK_DELAY` seconds apart, before it is judged: the git refs API can lag
a write (issue 816), so a ref that reaches the caller's sha answers `moved` or `acquired`, and only a
read-back that stays on the old lock, or names a third sha at once, is `lost_to`.

D11, `refresh` (issue 971) is how a holder whose lock stays at one sha through a long wait keeps a
waiter from taking it over as idle. The lock cannot say so itself: its value is the holder's head,
and a write of the same oid changes nothing. The holder therefore changes a second ref, the beat
`refs/agent-locks/land-beat/<branch>`: `refresh --sha <sha>` answers `not_held` (exit 3, with
`lock_sha`, `pr` and `by`) and writes nothing unless the lock is at `--sha`, and otherwise moves
the beat one step: created at `--sha` when absent, else swapped to the first parent of its value
(deleted when that is a root commit); a swap the forge refuses, as it did on a merge commit (issue 1132), is retried at `--sha` and then as a deletion, and a refresh all three fail, or a creation the forge refuses, names the next step first and then the forge's reason. A beat at `--sha` that had to be deleted is created at that sha's parent, so the next refresh's creation cannot repeat its value. The beat therefore repeats a value only after it has walked
the whole first-parent history down to the root and begun again, so refreshes that fall between
two polls of a waiter do not cancel out; a repeat would cost one refresh a waiter did not see,
nothing more. The lock is read before the beat is written and the two are not one swap: a refresh
that read the lock just before its holder released it still moves the beat, once, which can delay
the idle takeover of the next holder's lock by one refresh and changes nothing else. It answers `refreshed` (exit 0) with `beat`, the new value (`null` when
deleted), also when another refresh changed the beat first; an unapplied swap on an unchanged beat
is a forge error. A waiter reads the beat in every poll that finds the lock held, and a beat that
differs from the one it read before restarts its watch exactly as a changed lock does. No clock is
read (D3): only a change counts, the beat's value means nothing, and the beat holds and releases
nothing, so one that nobody deletes is harmless. A waiter that predates this rule ignores the beat.

`hold --sha <sha> [--seconds N]` (issue 1679) is the lease's own refresh, D13.

D12, waiters queue (issue 1001, ADR-claims-012). The queue decides only who tries: the lock is
still granted by nothing but the create and the compare-and-swap of D1, so no queue state, true
or false, can make two holders. A registration is a ref
`refs/agent-locks/land-wait/<branch>/<since>-<pr>-<beat>` at the waiting head: `<pr>` is the
waiter's pull request, `<since>` and `<beat>` are seconds of the forge's clock (the `Date` header
of a free `rate_limit` call; no host clock is compared between hosts), `<since>` read when the
waiter first asked and `<beat>` at its last refresh. A poll of `--wait` that does not end with
the lock reads the queue once: the clock and the registrations (`GET git/matching-refs`, which
the forge answers whole, unpaginated). One whose beat is more than `QUEUE_LIVE` seconds (390,
three polls and a margin) behind the forge's clock, or more than `QUEUE_SKEW` seconds (60) ahead
of it, is dead: it is skipped and deleted by whoever lists it. A pull request's place is the
smallest `<since>` of its live registrations, ties going to the smaller number; the pull
requests placed before the caller's are ahead of it. Starting at the oldest, one that is not
open (`GET pulls/<n>`, HTTP 404 included) is skipped and its registrations deleted, and the
first open one ends the check, so a poll reads one pull request when somebody is ahead and none
when nobody is. A waiter with a pull request ahead of it creates no free lock until it has
itself watched the lock free for `FREE_GRACE` seconds (60), and takes no closed one over until
it has itself seen it closed for `CLOSED_GRACE` seconds (150); its next poll comes when that
grace ends. A live first waiter takes a free lock within `FAST_POLL` seconds and a closed one
within `FAST_POLL` seconds too (issue 1204: a merge leaves the lock's oid unchanged, so the same
short read also asks whether the holder's pull request is still open); each grace is longer than
that, and bounds what a waiter that died or hangs can cost. The queue is asked
nothing else. `already_held` and `moved` concern only the caller's own lock and are answered
before the queue is read, and the idle takeover of D4 does not depend on the caller's place: its
own 45-minute watch is the bound; only the takeovers of a lapsed or overdue lease (D13) are
asked of the first in line alone. A following release's second attempt, right after it deleted
its own lock (D5), is not queued either, so the lock it gave up is not left free behind a
waiter. A waiter registers only once a poll did not give it the lock, so a wait that finds the
lock free with nobody ahead writes no registration. It refreshes after each poll that did not
give it the lock, at most once in 60 seconds, by creating the ref with the new beat (the clock
that poll read) and then deleting its own old one, and deletes its registration when it ends
with the lock, with `no_open_pr` or with an error. A `land-contended` answer leaves the
registration: the programs ask again at once, and the next `--wait` of that pull request adopts
the `<since>` of a registration still live, so a wait that ran into its bound keeps its place
when it is called again within `QUEUE_LIVE` seconds; left alone the registration dies then. A
process deletes, while it waits, only registrations it created itself, so two waits of one pull
request do not undo each other. While nobody is ahead of it the waiter also reads the lock ref
alone every `FAST_POLL` seconds (20) between two polls and polls at once when it differs from
what the poll saw, or is free, or when the pull request that held it, as the poll saw it, is no
longer open (issue 1204: that is how the first in line notices a merge within `FAST_POLL` seconds
instead of at its next whole poll; the holder's pull request is read once more in each short
read, and a closed holder the poll cannot take over is polled for once, so it costs no more than
the 120-second rate, and a holder whose read fails is not read again by the short reads, which then
see only the lock ref until the poll that follows; issue 1018: a poll whose takeover of a closed lock lost to the
holder's release ends having read the lock free, and a read that only compared would see no
change until a waiter behind had taken the lock at its grace's end). After one failed poll
(D8) a waiter that was first in line keeps reading the lock ref so until its next poll, and
a read that fails then waits for the next one; after a second failed poll in a row it reads
nothing between polls, so a forge that stays down, or a lock that is free and cannot be
written, is polled once early and then at the 120-second rate. A failed queue read or write
(the clock, the listing, the pull request ahead, the registration's create or delete, whatever
the error) never fails the wait and is no failed poll (D8): that poll attempts unordered, as a
client before this rule does, at the 120-second rate, and answers `position` `null`. The
order holds among registered waiters up to the seconds
between a waiter's clock read and its registration being listed: two that arrive that close can
both find themselves first, and then the create decides, as before. A one-shot `acquire` and a
client that predates this rule register nothing and are not ordered: they take a free lock when
they find one, exactly as before, they are never held back by the queue, and a registered
waiter is held back by them only as it always was, by the lock they hold. Against them only the
first in line competes, with a poll six times as fast.

D13, the lease (issue 1679, ADR-claims-005). A delivery whose pull request is green and, when it
needs one, approved holds the lock until its merge, so a landing waits behind nobody's CI. It says
so with `acquire --lease` (not with `--release`): after a holding verdict it writes the lease, the
ref `refs/agent-locks/land-lease/<branch>/<since>-<pr>-<beat>` at the lock's sha, named like a
registration (D12) and read from the forge's clock too. `acquired` creates `<now>-<pr>-<now>` and
deletes the pull request's other leases; `already_held` and `moved` create `<since>-<pr>-<now>`,
keeping the newest `<since>` it can trust (a fresh one when none), and delete the old one. A write
that fails leaves the lock held and the answer's `lease` `null`; otherwise `lease` is `{since,
beat}`. `hold --sha S [--seconds N]` (N from 0 to `HOLD_MAX`, default 0) reads the lock at once and
every `LEASE_BEAT` seconds (60) of `monotonic()`: a lock not at S answers `not_held` (exit 3) at
once, one at S with a lease at S rewrites its `<beat>` to the forge's clock, one at S with none
answers `unleased` (exit 0) and writes nothing; after N seconds it answers `held` with `lease` and
`held_s`, the seconds since `<since>`. The first in line, and only it (a read of this poll's queue
that succeeded and put it first, so neither position 2 or later nor an unordered poll nor a
one-shot `acquire`), takes a lock whose holder's newest lease has a `<beat>` more than
`LEASE_LAPSE` (180) seconds behind the poll's queue clock (`took_over` `"lapsed"`), or a `<since>`
that is `HOLD_BOUND` (1200) seconds old (`"bound"`), by the compare-and-swap of an idle takeover,
and deletes the taken holder's leases. Its next poll comes when the earlier of the two ends. A
holder with no lease ref of its pull request, a release, a train or a client that predates this
rule among them, and one whose lease is more than `QUEUE_SKEW` ahead of the clock, is judged by D4
alone; a failed read of the leases takes nothing over. Both ages use the forge's clock of the
poll's own queue read, never a host clock. The holder that lost the lock asks again with `--wait
--lease` and queues at the forge's clock of that moment, behind every earlier registration
(ADR-claims-012). A lease can be forged: it can cut a hold short, and the holder waits again; it
grants nothing, since the lock is still granted by D1's create and swap only.
"""
import re
import time
from collections.abc import Collection
from typing import Any, Callable, NamedTuple

from agent_tools.claims import forge_markers as fm
from agent_tools.system import forge_api

LOCK_PREFIX = "refs/agent-locks/land/"
BEAT_PREFIX = "refs/agent-locks/land-beat/"
WAIT_PREFIX = "refs/agent-locks/land-wait/"
LEASE_PREFIX = "refs/agent-locks/land-lease/"
WAITER = re.compile(r"(\d+)-(\d+)-(\d+)")  # D12: <since>-<pr>-<beat>, a lease's name too (D13)
CREATE_ROUNDS = 3
READBACK_RETRIES = 3
READBACK_DELAY = 1.0
IDLE_AFTER = 2700
POLL = 120
BOUND = 3000
FAILED_POLLS = 3
FAST_POLL = 20  # D12: the first in line reads the lock ref this often between two polls
QUEUE_LIVE = 3 * POLL + 30  # D12: a registration not refreshed for this long is dead
QUEUE_REFRESH = POLL // 2  # D12: a registration is rewritten at most this often
QUEUE_SKEW = 60  # D12: a registration whose beat is this far ahead of the forge's clock is dead
FREE_GRACE = 60  # D12: a lock watched free this long is tried by a waiter that is not first
CLOSED_GRACE = POLL + 30  # D12: and one seen closed this long; the first in line sees that in a whole poll
HOLD_BOUND = 1200  # D13: a lease held this long is taken over by the first in line
LEASE_BEAT = 60  # D13: `hold` rewrites the beat of its lease this often
LEASE_LAPSE = 180  # D13: a lease whose beat is this far behind the forge's clock has lapsed
HOLD_MAX = BOUND  # D13: the largest `hold --seconds`
ACTIONS = ("acquire", "release", "status", "refresh", "hold")

monotonic = time.monotonic
sleep = time.sleep


def forge_now() -> int:
    """D12: the forge's clock in whole seconds; no host clock orders or expires a waiter."""
    return int(forge_api.server_now().timestamp())


class Attempts:
    """What earlier tries of one retried `acquire` may have written (issue 740).

    `unsure` is true once a try sent a create or a swap that was not refused and then raised, so
    its effect is unknown. A later try that finds the lock at its sha cannot tell its own write
    from a lock already held, and reports `acquired`, which the programs recheck before they
    merge, never `already_held`."""

    def __init__(self) -> None:
        self.wrote = False  # the running try has sent a write not yet known to be refused
        self.unsure = False

    def failed(self) -> None:
        """The running try raised: a write it sent may have taken effect."""
        self.unsure = self.unsure or self.wrote
        self.wrote = False


class Outcome(NamedTuple):
    verdict: str
    lock_sha: str | None
    pr: int | None
    took_over: str | None


def lock_ref(branch: str) -> str:
    return LOCK_PREFIX + branch


def beat_ref(branch: str) -> str:
    return BEAT_PREFIX + branch


def wait_prefix(branch: str) -> str:
    return WAIT_PREFIX + branch + "/"


def lease_prefix(branch: str) -> str:
    return LEASE_PREFIX + branch + "/"


class Waiter(NamedTuple):
    since: int
    pr: int
    beat: int
    ref: str
    oid: str


class Queue:
    """D12: one waiter's view of the waiters of a branch, and its own registration among them."""

    def __init__(self, slug: str, branch: str, node: Callable[[], str]) -> None:
        self.slug, self.prefix, self.node = slug, wait_prefix(branch), node
        self.key: tuple[int, int] | None = None  # (since, pull request): the caller's place
        self.mine: tuple[str, str] | None = None  # the caller's registration: ref and oid
        self.ghosts: list[tuple[str, str]] = []  # its pull request's, found by the first read
        self.sha, self.now, self.beaten = "", 0, 0.0
        self.position: int | None = None
        self.ahead: list[int] = []

    def look(self, pr: int, sha: str) -> None:
        """One poll: read the forge's clock and the registrations, and order them."""
        self.sha, self.now = sha, forge_now()
        listed = []
        for ref, oid in fm.matching_refs(self.slug, self.prefix).items():
            match = WAITER.fullmatch(ref[len(self.prefix):])
            if match:
                listed.append(Waiter(int(match[1]), int(match[2]), int(match[3]), ref, oid))
        live = [w for w in listed if -QUEUE_SKEW <= self.now - w.beat <= QUEUE_LIVE]
        if self.key is None or self.key[1] != pr:
            # The place a wait of this pull request left behind is adopted; what it left is
            # deleted when this wait ends, and until then only what this process created.
            self.key = (min((w.since for w in live if w.pr == pr), default=self.now), pr)
            self.ghosts = [(w.ref, w.oid) for w in listed if w.pr == pr and (self.mine is None or w.ref != self.mine[0])]
        place: dict[int, int] = {}
        for w in listed:
            if w.pr == pr:
                continue
            if w in live:
                place[w.pr] = min(w.since, place.get(w.pr, w.since))
            else:
                self._drop(w.ref, w.oid)
        ahead = sorted((n for n in place if (place[n], n) < self.key), key=lambda n: (place[n], n))
        while ahead and not fm.pull_open(self.slug, ahead[0]):
            for w in listed:
                if w.pr == ahead[0] and w in live:
                    self._drop(w.ref, w.oid)
            ahead.pop(0)
        self.ahead, self.position = ahead, len(ahead) + 1

    def lost(self) -> None:
        """A read of the queue failed: until one succeeds the caller is not ordered."""
        self.ahead, self.position = [], None

    def stay(self) -> None:
        """The poll `look` read did not give the caller the lock: register it, or refresh it."""
        if self.key is None or (self.mine is not None and monotonic() - self.beaten < QUEUE_REFRESH):
            return
        name = f"{self.prefix}{self.key[0]}-{self.key[1]}-{self.now}"
        old = self.mine
        if old is None or old[0] != name:
            fm.create_ref(self.slug, name, self.sha)
            self.mine = (name, self.sha)
            if old is not None:
                self._drop(*old)
        self.beaten = monotonic()

    def _drop(self, ref: str, oid: str) -> None:
        """Delete a registration by compare-and-swap; one that changed or is gone is left alone."""
        fm.cas_ref(self.slug, self.node(), ref, oid, fm.ZERO_OID)

    def leave(self) -> None:
        """Delete the caller's registrations; one that cannot be deleted dies by itself."""
        gone, self.mine, self.ghosts = self.ghosts + ([self.mine] if self.mine else []), None, []
        for ref, oid in gone:
            try:
                self._drop(ref, oid)
            except forge_api.ForgeError:
                pass


def read_leases(slug: str, branch: str) -> list[Waiter]:
    """D13: every lease of `branch` in the forge, as it is named."""
    prefix = lease_prefix(branch)
    found = []
    for ref, oid in fm.matching_refs(slug, prefix).items():
        match = WAITER.fullmatch(ref[len(prefix):])
        if match:
            found.append(Waiter(int(match[1]), int(match[2]), int(match[3]), ref, oid))
    return found


def trusted(leases: list[Waiter], now: int) -> list[Waiter]:
    """D13: the leases whose `<since>` and `<beat>` the forge's clock `now` does not contradict."""
    return [w for w in leases if max(w.since, w.beat) <= now + QUEUE_SKEW]


def drop_leases(slug: str, node: Callable[[], str], leases: Collection[Waiter]) -> None:
    """D13: delete leases by compare-and-swap; one that changed, is gone or fails is left alone."""
    for lease in leases:
        try:
            fm.cas_ref(slug, node(), lease.ref, lease.oid, fm.ZERO_OID)
        except forge_api.ForgeError:
            pass


def write_lease(slug: str, branch: str, node: Callable[[], str], pr: int, sha: str,
                since: int | None, old: list[Waiter], now: int) -> dict[str, int]:
    """D13: a lease of `pr` at `sha` whose beat is `now`, in place of `old`, the pull request's
    leases as they were read; `since` None starts the hold at `now`."""
    since = now if since is None else since
    name = f"{lease_prefix(branch)}{since}-{pr}-{now}"
    if not any(w.ref == name and w.oid == sha for w in old) and not fm.create_ref(slug, name, sha):
        raise forge_api.ForgeError("gh_failed", f"lease {name} not created")
    drop_leases(slug, node, [w for w in old if w.ref != name])
    return {"since": since, "beat": now}


def pick_pr(pulls: list[fm.Pull]) -> int | None:
    """The smallest open number, else the largest closed number, else None."""
    opened = [p.number for p in pulls if p.state == "open"]
    if opened:
        return min(opened)
    closed = [p.number for p in pulls]
    return max(closed) if closed else None


def classify(lock: str, theirs: list[fm.Pull], mine: Collection[int]) -> tuple[str, int | None]:
    """D2: the kind (`held`, `move` or `closed`) and the pull request to report."""
    open_ = [p for p in theirs if p.state == "open"]
    heads = [p.number for p in open_ if p.head_sha == lock and p.number not in mine]
    if heads:
        return "held", min(heads)
    if mine and open_ and all(p.number in mine for p in open_):
        return "move", min(p.number for p in open_)
    closed = [p for p in theirs if p.state != "open"]
    closed_heads = [p.number for p in closed if p.head_sha == lock]
    if (theirs and not any(p.head_sha == lock for p in open_)
            and (len(closed) == len(theirs) or closed_heads)):
        return "closed", max(closed_heads) if closed_heads else max(p.number for p in closed)
    return "held", min(p.number for p in open_) if open_ else None


def holder(slug: str, pr: int | None) -> str | None:
    """The `holder` of the claim winner on the first closing issue of `pr` that has one (D2)."""
    if pr is None:
        return None
    for issue in fm.closing_issues(slug, pr):
        winners = fm.contest(fm.list_markers(slug, issue), "claim", {"issue": str(issue)})
        if winners:
            return winners[0].fields.get("holder")
    return None


def _releases(pull: fm.Pull, branch: str, sha: str) -> bool:
    """`pull` is a release pull request of `branch` at `sha`: its head is that branch itself."""
    return pull.same_repo and pull.head_ref == branch and pull.head_sha == sha


def _from_branch(pull: fm.Pull, branch: str) -> bool:
    """`pull` is headed by `branch` itself, in the same repository, whatever its head sha."""
    return pull.same_repo and pull.head_ref == branch


def _on_branch(slug: str, sha: str, branch: str) -> list[fm.Pull]:
    """The pull requests that contain `sha` and are on `branch` or headed by `branch` (D2, D5),
    plus the ones headed at it that the commit lookup did not list.

    The forge's commit lookup returns only open pull requests for a commit outside the default
    branch and only merged ones for a commit on it, so a holder it left out is found by its head
    sha instead, and only when no pull request already has that head: first among the open pull
    requests on `branch` (a head on the default branch, issue 905), then among the closed ones (a
    squash-merged, rebase-merged or closed holder), then, when none is found there, among the
    pull requests headed by `branch`, open ones included, because the lookup can leave an open
    release pull request out. Each listing is read only when the one before it found none.
    """
    pulls = [p for p in fm.commit_pulls(slug, sha) if p.base_ref == branch or _from_branch(p, branch)]
    if not any(p.head_sha == sha for p in pulls):
        known = {p.number for p in pulls}
        for listing in (fm.open_pulls_headed, fm.closed_pulls_headed, fm.pulls_from):
            headed = [p for p in listing(slug, branch, sha) if p.number not in known]
            if headed:
                return pulls + headed
    return pulls


def _kind(lock: str, theirs: list[fm.Pull], mine: Collection[int], branch: str) -> tuple[str, int | None]:
    """`classify`, except that a lock contained in a pull request headed by `branch` never moves (D5)."""
    kind, pr = classify(lock, theirs, mine)
    reached = [p.number for p in theirs if _from_branch(p, branch)]
    if kind == "move" and reached:
        return "closed", max(reached)
    return kind, pr


def acquire_once(slug: str, branch: str, sha: str, mine: list[fm.Pull],
                 idle: Callable[[str], bool], node: Callable[[], str],
                 seen: Callable[[str | None], None] | None = None,
                 attempts: Attempts | None = None,
                 behind: Callable[[str | None], bool] | None = None,
                 overdue: Callable[[str, int | None], str | None] | None = None) -> Outcome:
    """One acquire attempt (D1, D2, D3, D5); `idle(lock)` lets a `held` lock be taken over.

    `behind`, a waiter's (D12), makes the attempt read the lock before it writes. It is asked
    with None before a free lock is created and with the lock before a closed one is taken
    over; true means another waiter is first, and nothing is written (`queued` for a free lock,
    `held_by` for a closed one). A lock at the caller's own sha or pull request never asks,
    and neither does an idle one. `overdue`, a first-in-line waiter's (D13), is asked with the
    lock and its holder's pull request for a `held` lock `idle` did not take: `"lapsed"` or
    `"bound"` takes it over, None leaves it held."""
    ref = lock_ref(branch)

    def observe() -> str | None:
        oid = fm.read_ref(slug, ref)
        if seen is not None:
            seen(oid)
        return oid

    lock = observe() if behind is not None else None
    if lock is None:
        if behind is not None and behind(None):
            return Outcome("queued", None, None, None)
        for _ in range(CREATE_ROUNDS):
            if attempts is not None:
                attempts.wrote = True
            if fm.create_ref(slug, ref, sha):
                return Outcome("acquired", sha, pick_pr(mine), None)
            if attempts is not None:
                attempts.wrote = False
            lock = observe()
            if lock is not None:
                break
        if lock is None:
            raise forge_api.ForgeError("gh_failed", "ref create refused while the ref is absent")
    if lock == sha:
        verdict = "acquired" if attempts is not None and attempts.unsure else "already_held"
        return Outcome(verdict, sha, pick_pr(mine), None)
    theirs = _on_branch(slug, lock, branch)
    kind, pr = _kind(lock, theirs, {p.number for p in mine}, branch)
    if kind == "held":
        if idle(lock):
            kind = "idle"
        else:
            late = overdue(lock, pr) if overdue is not None else None
            if late is None:
                return Outcome("held_by", lock, pr, None)
            kind = late
    if kind == "closed" and behind is not None and behind(lock):
        return Outcome("held_by", lock, pr, None)
    if attempts is not None:
        attempts.wrote = True
    failure = fm.cas_ref(slug, node(), ref, lock, sha)
    after = observe()
    for _ in range(READBACK_RETRIES):
        if failure or after != lock:
            break
        sleep(READBACK_DELAY)  # an applied swap whose read-back still shows the old sha (issue 816)
        after = observe()
    if after == sha:
        if kind == "move":
            return Outcome("moved", sha, pick_pr(mine), None)
        return Outcome("acquired", sha, pick_pr(mine), kind)
    if after == lock and failure:
        raise forge_api.ForgeError(failure.code, "compare-and-swap not applied and the lock is unchanged",
                            transient=failure.transient)
    return Outcome("lost_to", after, _pr_of(slug, branch, after), None)


def _pr_of(slug: str, branch: str, lock: str | None) -> int | None:
    if lock is None:
        return None
    return classify(lock, _on_branch(slug, lock, branch), ())[1]


def result(args: Any, verdict: str, *, lock_sha: str | None = None, pr: int | None = None,
           by: str | None = None, took_over: str | None = None, waited_s: int | None = None,
           **extra: Any) -> dict[str, Any]:
    return {"command": "land", "action": args.action, "repo": args.repo, "branch": args.branch,
            "sha": args.sha, "verdict": verdict, "lock_sha": lock_sha, "pr": pr, "by": by,
            "took_over": took_over, "waited_s": waited_s, **extra}


def usage_result(argv: list[str], detail: str) -> dict[str, Any]:
    action = argv[1] if len(argv) > 1 and argv[1] in ACTIONS else None
    return {"command": "land", "action": action, "repo": None, "branch": None, "sha": None,
            "verdict": "error", "lock_sha": None, "pr": None, "by": None, "took_over": None,
            "waited_s": None, "error": "usage", "detail": detail}


def wait_acquire(args: Any, node: Callable[[], str],
                 eligible: Callable[[], list[fm.Pull]]) -> tuple[int, dict[str, Any]]:
    """D4, D8: poll `acquire_once` until it succeeds, the bound passes or polls keep failing.

    D6 holds at every attempt: `mine` is read inside every poll, the first included, so a failed
    read is a failed poll (issue 740), and a caller whose pull request no longer has its sha as
    head stops with `no_open_pr`. The attempt is made at the head of `mine`, which is `--sha`
    except for a following release, whose `eligible` follows its pull request (issue 901).

    D12: the attempt asks the waiters' queue before it creates a free lock or takes a closed one
    over, a poll that did not end with the lock reads the queue if its attempt did not, and the
    caller's registration is deleted on every exit but `land-contended`. No failure of the queue
    fails a poll.
    """
    start = monotonic()
    watch: list[Any] = [object(), None]  # [oid or None, first seen]; the sentinel matches nothing
    unread = object()
    beat: list[Any] = [unread]  # D11: the beat as last read, by a poll that found the lock held
    failures = 0
    last: Outcome | None = None
    waited_on: set[int] = set()  # D7: the pull requests seen holding the lock
    queue = Queue(args.repo, args.branch, node)
    keep = False  # D12: a land-contended answer leaves the registration to the next wait
    poll: list[Any] = [None, "", False, 0.0]  # pull request, sha, queue read, grace left when held back
    noticed: set[int] = set()  # issue 1204: holders seen closed by a short read, which polled once for each
    closed: list[Any] = [None, 0.0]  # [a lock seen closed with a waiter ahead, first seen so]
    taken: list[Waiter] = []  # D13: the leases of the holder whose lapsed or overdue lock was taken

    def seen(oid: str | None) -> None:
        if watch[0] != oid:
            watch[0], watch[1] = oid, monotonic()

    def idle(lock: str) -> bool:
        seen(lock)
        now = fm.read_ref(args.repo, beat_ref(args.branch))
        if beat[0] is not unread and beat[0] != now:
            watch[1] = monotonic()  # D11: the holder refreshed its lock
        beat[0] = now
        return monotonic() - watch[1] >= IDLE_AFTER

    def consult() -> None:
        """Read the queue once a poll; a failed read leaves the poll unordered (D12)."""
        if poll[2]:
            return
        poll[2] = True
        try:
            queue.look(poll[0], poll[1])
        except forge_api.ForgeError:
            queue.lost()

    def behind(lock: str | None) -> bool:
        seen(lock)
        consult()
        if not queue.ahead:
            return False
        since, grace = watch[1], FREE_GRACE
        if lock is not None:
            if closed[0] != lock:
                closed[0], closed[1] = lock, monotonic()
            since, grace = closed[1], CLOSED_GRACE
        poll[3] = max(0.0, since + grace - monotonic())
        return poll[3] > 0

    def overdue(lock: str, pr: int | None) -> str | None:
        """D13: `"lapsed"` or `"bound"` for a lock whose holder's lease ran out, asked only of the
        first in line by this poll's own queue read; a read that fails takes nothing over."""
        consult()
        if queue.position != 1 or pr is None:
            return None
        try:
            leases = [w for w in read_leases(args.repo, args.branch) if w.pr == pr]
        except forge_api.ForgeError:
            return None
        live = trusted([w for w in leases if w.oid == lock], queue.now)  # D4: `hold` beats only these
        if not live:
            return None
        lease = max(live, key=lambda w: (w.since, w.beat))
        late = ("lapsed" if queue.now - lease.beat > LEASE_LAPSE
                else "bound" if queue.now - lease.since >= HOLD_BOUND else None)
        if late is not None:
            taken[:] = leases
            return late
        wake = max(1, min(lease.beat + LEASE_LAPSE + 1, lease.since + HOLD_BOUND) - queue.now)
        poll[3] = wake if not poll[3] else min(poll[3], wake)
        return None

    def attempt(sha: str, mine: list[fm.Pull]) -> Outcome:
        return acquire_once(args.repo, args.branch, sha, mine, idle, node, seen, behind=behind, overdue=overdue)

    try:
        first = False
        while True:
            led, first = first, False
            poll[2], poll[3] = False, 0.0
            try:
                mine = eligible()
                if not mine:
                    return _no_open_pr(args)
                sha = mine[0].head_sha
                mine = [p for p in mine if p.head_sha == sha]
                poll[0], poll[1] = min(p.number for p in mine), sha
                outcome = attempt(sha, mine)
                if (outcome.verdict == "held_by" and outcome.lock_sha == args.sha != sha
                        and not _headed_by_another(args, {m.number for m in mine})):
                    # D5: the release's own lock at the head it started from; release it, try again.
                    # D12: unqueued, so the lock just given up is not left free behind a waiter.
                    failure = fm.cas_ref(args.repo, node(), lock_ref(args.branch), args.sha, fm.ZERO_OID)
                    outcome = acquire_once(args.repo, args.branch, sha, mine, idle, node, seen)
                    if failure and outcome.verdict == "held_by" and outcome.lock_sha == args.sha:
                        raise forge_api.ForgeError(failure.code, "compare-and-swap delete not applied and "
                                                   "the lock is unchanged", transient=failure.transient)
            except forge_api.ForgeError as error:
                failures += 1
                if error.code not in ("gh_failed", "gh_timeout") or failures >= FAILED_POLLS:
                    raise
                first = led and failures == 1  # issue 1018: one fast retry, then the 120-second rate (D8)
            else:
                failures = 0
                if outcome.verdict in ("acquired", "already_held", "moved"):
                    if outcome.took_over in ("lapsed", "bound"):
                        drop_leases(args.repo, node, taken)
                    moved = {"head_moved": sha != args.sha} if _follows(args) else {}
                    return 0, result(args, outcome.verdict, lock_sha=outcome.lock_sha, pr=outcome.pr,
                                     took_over=outcome.took_over, waited_s=int(monotonic() - start),
                                     waited_on=sorted(waited_on), position=queue.position,
                                     ahead=queue.ahead, **moved)
                consult()
                try:
                    if queue.position is not None:
                        queue.stay()
                except forge_api.ForgeError:
                    pass  # D12: unregistered or unrefreshed, the wait goes on
                first = queue.position == 1
                if outcome.lock_sha is not None:
                    last = outcome
                if outcome.pr is not None:
                    waited_on.add(outcome.pr)
            if monotonic() - start >= BOUND:
                keep = True
                return 3, result(args, "land-contended", lock_sha=last.lock_sha if last else None,
                                 pr=last.pr if last else None,
                                 by=holder(args.repo, last.pr) if last else None,
                                 waited_s=int(monotonic() - start), waited_on=sorted(waited_on),
                                 position=queue.position, ahead=queue.ahead)
            until = min(monotonic() + (min(POLL, poll[3]) if poll[3] else POLL), start + BOUND)
            while True:  # D12: the first in line reads the lock ref between two polls
                sleep(min(FAST_POLL if first else POLL, until - monotonic()))
                if not first or monotonic() >= until:
                    break
                try:
                    lock = fm.read_ref(args.repo, lock_ref(args.branch))
                    if lock is None or lock != watch[0]:
                        break  # issue 1018: free is reason enough, also when the poll itself left it free
                    if (last is not None and last.pr is not None and last.lock_sha == lock
                            and last.pr not in noticed):
                        try:
                            held = fm.pull_open(args.repo, last.pr)
                        except forge_api.ForgeError:
                            noticed.add(last.pr)  # issue 1204: a failed read is not asked again, and no poll
                            continue
                        if not held:
                            noticed.add(last.pr)  # issue 1204: a merge leaves the lock's oid as it was
                            break
                except forge_api.ForgeError:
                    if failures:
                        continue  # after a failed poll the polls keep their 120-second rate (D8)
                    break  # the poll that follows counts the failure
    finally:
        if not keep:
            queue.leave()


def _headed_by_another(args: Any, mine: Collection[int]) -> bool:
    """D5: an open pull request outside `mine` has its head at `--sha`, so it holds a lock there.

    Read as `_on_branch` reads it: the commit lookup, then the open listing of the branch when
    the lookup lists no such head (a head on the default branch, issue 905)."""
    heads = [p for p in fm.commit_pulls(args.repo, args.sha) if p.state == "open" and p.head_sha == args.sha]
    heads = heads or fm.open_pulls_headed(args.repo, args.branch, args.sha)
    return any(p.number not in mine for p in heads)


def _no_open_pr(args: Any) -> tuple[int, dict[str, Any]]:
    detail = (f"no open pull request on {args.branch} has head {args.sha}" if not args.release
              else f"no open release pull request from {args.branch} into the default branch"
              if _follows(args) else f"no open release pull request from {args.branch} has head {args.sha}")
    return 2, result(args, "error", error="no_open_pr", detail=detail)


def _follows(args: Any) -> bool:
    """D6: `--follow-head`; a caller that builds its own arguments (`release_lock`) never follows."""
    return bool(getattr(args, "follow_head", False))


def _acquire(args: Any, attempts: Attempts | None = None) -> tuple[int, dict[str, Any]]:
    if _follows(args) and not (args.release and args.wait):
        return 2, result(args, "error", error="usage", detail="--follow-head needs --release and --wait")
    if _leases(args) and args.release:
        return 2, result(args, "error", error="usage", detail="--lease cannot be used with --release")
    default: list[str] = []

    def eligible() -> list[fm.Pull]:
        if _follows(args):  # D6: a waiting release follows its pull request's head
            mine = fm.open_pulls_from(args.repo, args.branch)
        else:
            opened = [p for p in fm.commit_pulls(args.repo, args.sha) if p.state == "open"]
            if not args.release:
                mine = [p for p in opened if p.base_ref == args.branch and p.head_sha == args.sha]
                # D6: an open head on the default branch is not in the commit lookup (issue 905).
                return mine or fm.open_pulls_headed(args.repo, args.branch, args.sha)
            mine = [p for p in opened if _releases(p, args.branch, args.sha)]
        if mine and not default:
            default.append(fm.default_branch(args.repo))
        return [p for p in mine if p.base_ref == default[0]]

    cached: list[str] = []

    def node() -> str:
        if not cached:
            cached.append(fm.repo_node_id(args.repo))
        return cached[0]

    if args.wait:
        code, out = wait_acquire(args, node, eligible)
        return code, _lease(args, node, out) if code == 0 and _leases(args) else out
    mine = eligible()
    if not mine:
        return _no_open_pr(args)
    outcome = acquire_once(args.repo, args.branch, args.sha, mine, lambda _: False, node,
                           attempts=attempts)
    if outcome.verdict in ("acquired", "already_held", "moved"):
        out = result(args, outcome.verdict, lock_sha=outcome.lock_sha, pr=outcome.pr,
                     took_over=outcome.took_over)
        return 0, _lease(args, node, out) if _leases(args) else out
    return 3, result(args, outcome.verdict, lock_sha=outcome.lock_sha, pr=outcome.pr,
                     by=holder(args.repo, outcome.pr))


def _leases(args: Any) -> bool:
    """D13: `--lease`; a caller that builds its own arguments (`release_lock`) never leases."""
    return bool(getattr(args, "lease", False))


def _lease(args: Any, node: Callable[[], str], out: dict[str, Any]) -> dict[str, Any]:
    """D13: write the lease of a holding answer and add `lease` to it; a failed write is `null`."""
    try:
        now = forge_now()
        old = [w for w in read_leases(args.repo, args.branch) if w.pr == out["pr"]]
        since = None
        if out["verdict"] != "acquired":
            since = max((w.since for w in trusted(old, now)), default=None)
        out["lease"] = write_lease(args.repo, args.branch, node, out["pr"], out["lock_sha"], since, old, now)
    except forge_api.ForgeError:
        out["lease"] = None
    return out


def _hold(args: Any) -> tuple[int, dict[str, Any]]:
    """D13: keep the lease of the lock at `--sha` beating for `--seconds`."""
    cached: list[str] = []

    def node() -> str:
        if not cached:
            cached.append(fm.repo_node_id(args.repo))
        return cached[0]

    start = monotonic()
    while True:
        lock = fm.read_ref(args.repo, lock_ref(args.branch))
        if lock != args.sha:
            pr = _pr_of(args.repo, args.branch, lock)
            return 3, result(args, "not_held", lock_sha=lock, pr=pr, by=holder(args.repo, pr))
        now = forge_now()
        mine = trusted([w for w in read_leases(args.repo, args.branch) if w.oid == args.sha], now)
        if not mine:
            return 0, result(args, "unleased", lock_sha=lock)
        newest = max(mine, key=lambda w: (w.since, w.beat))
        lease = write_lease(args.repo, args.branch, node, newest.pr, args.sha, newest.since,
                            [w for w in mine if w.pr == newest.pr], now)
        left = args.seconds - (monotonic() - start)
        if left <= 0:
            return 0, result(args, "held", lock_sha=lock, pr=newest.pr, lease=lease,
                             held_s=forge_now() - lease["since"])
        sleep(min(LEASE_BEAT, left))


def _release(args: Any) -> tuple[int, dict[str, Any]]:
    ref = lock_ref(args.branch)
    node_id = fm.repo_node_id(args.repo)
    failure = fm.cas_ref(args.repo, node_id, ref, args.sha, fm.ZERO_OID)
    after = fm.read_ref(args.repo, ref)
    try:  # D13: the leases at the released sha go with the lock
        drop_leases(args.repo, lambda: node_id, [w for w in read_leases(args.repo, args.branch) if w.oid == args.sha])
    except forge_api.ForgeError:
        pass
    if after is None:
        return 0, result(args, "released")
    if after == args.sha:
        raise forge_api.ForgeError(failure.code if failure else "gh_failed",
                            "compare-and-swap delete left the lock at the caller's sha",
                            transient=failure is not None and failure.transient)
    pr = _pr_of(args.repo, args.branch, after)
    return 3, result(args, "not_held", lock_sha=after, pr=pr, by=holder(args.repo, pr))


def _readback(slug: str, ref: str, before: str | None, failure: forge_api.ForgeError | None) -> str | None:
    """The ref after a write; an applied write whose read-back still shows `before` is waited out (issue 816)."""
    after = fm.read_ref(slug, ref)
    for _ in range(READBACK_RETRIES):
        if failure or after != before:
            break
        sleep(READBACK_DELAY)
        after = fm.read_ref(slug, ref)
    return after


def _refresh(args: Any) -> tuple[int, dict[str, Any]]:
    """D11: move the beat one step, only while the lock is at the caller's sha."""
    lock = fm.read_ref(args.repo, lock_ref(args.branch))
    if lock != args.sha:
        pr = _pr_of(args.repo, args.branch, lock)
        return 3, result(args, "not_held", lock_sha=lock, pr=pr, by=holder(args.repo, pr))
    ref = beat_ref(args.branch)
    beat = fm.read_ref(args.repo, ref)
    failure = None
    if beat is None:
        failure = fm.try_create_ref(args.repo, ref, args.sha)
        after = _readback(args.repo, ref, beat, failure)
    else:
        # The first parent is the step (D11). A forge that refuses it, whatever shape the commit has
        # (issue 1132), is asked for the caller's sha, then for the ref's deletion: the beat's value
        # means nothing, only its change counts.
        parent = fm.commit_parent(args.repo, beat)
        steps = [parent or fm.ZERO_OID, args.sha, fm.ZERO_OID]
        for step in dict.fromkeys(s for s in steps if s != beat):
            failure = fm.cas_ref(args.repo, fm.repo_node_id(args.repo), ref, beat, step)
            after = _readback(args.repo, ref, beat, failure)
            if after != beat:
                break
        if after is None and parent and beat == args.sha:
            # A beat at the caller's sha whose step was refused and which was deleted would be created
            # at that sha again by the next refresh, and a waiter polling between the two sees no change
            # (issue 1132); it is created at the parent instead, a value the sha cannot repeat at once.
            if fm.try_create_ref(args.repo, ref, parent) is None:
                after = fm.read_ref(args.repo, ref)
    if after == beat:
        reason = failure.detail if failure else "the forge did not apply it"
        # The guidance comes first: a ForgeError keeps only the first DETAIL_LIMIT characters.
        raise forge_api.ForgeError(failure.code if failure else "gh_failed",
                                   "the beat write was not applied. Run the refresh again; if it keeps failing, "
                                   "`forge-claim land release` the lock and acquire it again. "
                                   f"The forge said: {reason}",
                                   transient=failure is not None and failure.transient)
    return 0, result(args, "refreshed", lock_sha=lock, beat=after)


def _status(args: Any) -> tuple[int, dict[str, Any]]:
    lock = fm.read_ref(args.repo, lock_ref(args.branch))
    if lock is None:
        return 0, result(args, "free")
    kind, pr = classify(lock, _on_branch(args.repo, lock, args.branch), ())
    return 0, result(args, "stale" if kind == "closed" else "held_by", lock_sha=lock, pr=pr,
                     by=holder(args.repo, pr))


def run(args: Any, attempts: Attempts | None = None) -> tuple[int, dict[str, Any]]:
    """Run the parsed action; a caller that retries `acquire` passes the same `attempts` each try."""
    if args.action == "acquire":
        return _acquire(args, attempts)
    return {"release": _release, "status": _status, "refresh": _refresh, "hold": _hold}[args.action](args)
