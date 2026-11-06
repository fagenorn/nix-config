# Task 1: Marker grammar, end markers, forge reads and writes, race-settled write

**Files:**
- Create: `python/agent_tools/forge_markers.py`
- Modify: `tests/forge_world.py`
- Test: `tests/test_forge_markers.py`

**Interfaces:**
- Consumes: `tests/forge_world.py` `ForgeWorld` (`respond`, `respond_json`, `argvs`, `calls`, `not_found`, `reset`).
- Produces (`agent_tools.forge_markers`, standard library only, imports no `agent_tools` module):
  - `class ForgeError(Exception)` with attributes `code: str` (`gh_missing`, `gh_failed`, `gh_timeout`, `payload_invalid`) and `detail: str` (stderr, at most 240 chars).
  - `@dataclass(frozen=True) class Marker`: `comment_id: int`, `kind: str`, `fields: dict[str, str]` (first-line order), `body: str`, `updated_at: datetime` (aware, UTC).
  - `END_KIND = "end"`.
  - `render(kind: str, fields: Mapping[str, str], sentence: str, extra: str = "") -> str` — `"<!-- agent:{kind} v1 k=v ... -->\n{sentence}"` plus `"\n" + extra` when `extra` is non-empty; `ValueError` for a kind, key or value outside D1's grammar, or a sentence that is empty or holds a newline.
  - `end_body(of: int, reason: str) -> str` — exactly `render("end", {"of": str(of), "reason": reason}, f"Ends marker comment {of} ({reason}).")` (D9).
  - `parse(comment: Mapping[str, Any]) -> Marker | None` — from a REST comment object (`id`, `body`, `updated_at`).
  - `with_fields(marker: Marker, **updates: str) -> str` — the body with the first line re-rendered: existing keys keep their position and take the new value, new keys append in argument order; every other line unchanged.
  - `ended(markers: Iterable[Marker]) -> set[int]` — the `of` ids (as int) of every `end` marker.
  - `is_live(marker: Marker, markers: Iterable[Marker]) -> bool` — D9: `marker.kind != "end"`, no `released` field, and `marker.comment_id not in ended(markers)`.
  - `contest(markers, kind: str, match: Mapping[str, str]) -> list[Marker]` — markers of `kind` live within `markers` whose fields contain every `match` pair, ascending `comment_id`.
  - `list_markers(slug: str, issue: int) -> list[Marker]` — every parseable marker on the issue, ascending `comment_id`.
  - `post(slug: str, issue: int, body: str) -> int` — the new comment's id.
  - `end(slug: str, issue: int, of: int, reason: str) -> int` — `post(slug, issue, end_body(of, reason))`; never edits or deletes the target.
  - `@dataclass(frozen=True) class WriteResult`: `won: bool`, `own_id: int`, `winner: Marker | None` (`None` only when the re-read lacks every contested marker, own included).
  - `write(slug, issue, kind, fields, sentence, match, extra="") -> WriteResult`.
  - `edit(slug: str, comment_id: int, body: str) -> None`, `delete(slug: str, comment_id: int) -> None`.
  - `server_now() -> datetime` (D5).
  - `ensure_label(slug, name, color) -> None`, `add_label(slug, issue, name) -> None`, `remove_label(slug, issue, name) -> None` (D7).
  - `latest_push(slug, branch) -> datetime | None`, `latest_pr_event(slug, branch) -> datetime | None` (D4).
- Produces (`tests/forge_world.py`): `ForgeWorld.comment_store`, `ForgeWorld.stored`, `ForgeWorld.wait_cursor` and module-level `host_clock` (Step 1).
- Exact `gh` argv (the fake keys on them; later tasks register the same):
  - list: `["api", "--paginate", "--slurp", "repos/<slug>/issues/<n>/comments?per_page=100"]` → array of pages, each an array of comments.
  - post: `["api", "-X", "POST", "repos/<slug>/issues/<n>/comments", "-f", "body=<body>"]` → the comment object (`id`).
  - edit: `["api", "-X", "PATCH", "repos/<slug>/issues/comments/<id>", "-f", "body=<body>"]`.
  - delete: `["api", "-X", "DELETE", "repos/<slug>/issues/comments/<id>"]` (HTTP 404 is success: already gone).
  - now: `["api", "--include", "rate_limit"]` → status line, headers, blank line, JSON; the `Date` header (any case) parsed with `email.utils.parsedate_to_datetime`.
  - ensure label: `["api", "-X", "POST", "repos/<slug>/labels", "-f", "name=<name>", "-f", "color=<color>"]` (HTTP 422 is success).
  - add label: `["api", "-X", "POST", "repos/<slug>/issues/<n>/labels", "-f", "labels[]=<name>"]`.
  - remove label: `["api", "-X", "DELETE", "repos/<slug>/issues/<n>/labels/<name>"]` (HTTP 404 is success).
  - push: `["api", "repos/<slug>/activity?ref=refs/heads/<branch>&activity_type=push&per_page=1"]` → array; first item's `timestamp`, `None` when empty or HTTP 404.
  - PR events: `["api", "repos/<slug>/pulls?state=all&head=<owner>:<branch>&per_page=100"]` → array; max `updated_at`, `None` when empty.

**Invariants:**
- Every child: `subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=30, stdin=DEVNULL, env=<os.environ without GITHUB_TOKEN and GH_TOKEN>)`. A non-zero exit whose stderr's `(HTTP nnn)` is in the call's allowed set returns normally; any other is `ForgeError("gh_failed")`; `OSError` is `gh_missing`; timeout `gh_timeout`; unparseable JSON or a missing `Date` header `payload_invalid`.
- `parse` returns `None` for a non-marker first line, a repeated key, or a body that is not a string; a CR before the first newline is ignored.
- `write` (D2): `post` first, then `list_markers`, never a listing before the post; `contest` over the re-read plus own id (own counted even when the re-read omits it); winner = smallest id. If own id is the winner → `won=True`, no delete. Else delete own and return `won=False` with the smallest contested marker that is not own. Exactly one post per call, at most one delete, never a retry.
- Ending is append-only (D9): no function edits or deletes an `end` marker; `delete` is called by `write` only, on its own just-posted comment.
- The module binds `from datetime import datetime, timezone` (plus what else it needs from that module) and reads no host clock (Global Constraints).

- [ ] **Step 1: Extend `tests/forge_world.py`**

Add, without changing any existing response's behaviour:

1. **Stateful comment store.** A plain (non-`format`) string constant `STORE_HANDLER` holding Python source, spliced into each tool script by building it as `SCRIPT.format(python=sys.executable).replace("# store handler\n", STORE_HANDLER)`, where `SCRIPT` gains the line `# store handler` directly after the `gh` token check (so calls are still logged and token leaks still exit 65). The handler runs only for `tool == "gh"` when `state / "store.json"` exists, and only for these argv shapes, with `S` the store's slug and `N` its issue:
   - `list`: `["api", "--paginate", "--slurp", f"repos/{S}/issues/{N}/comments?per_page=100"]` → stdout `json.dumps([comments sorted by id])`, exit 0.
   - `post:<first line of body>`: `["api", "-X", "POST", f"repos/{S}/issues/{N}/comments", "-f", "body=<b>"]` → appends `{"id": next_id, "body": b, "created_at": clock, "updated_at": clock}`, `next_id += 1`, stdout the new comment.
   - `patch:<id>`: `["api", "-X", "PATCH", f"repos/{S}/issues/comments/<id>", "-f", "body=<b>"]` → replaces the body, sets `updated_at = clock`, stdout the comment; a missing id → stderr `gh: Not Found (HTTP 404)`, exit 1.
   - `delete:<id>`: `["api", "-X", "DELETE", f"repos/{S}/issues/comments/<id>"]` → removes it, exit 0; a missing id → the same 404.
   Every other argv falls through to the registered responses. Each operation holds an exclusive `fcntl.flock` on `state / "store.lock"` while it reads and rewrites `store.json`.
   **Schedule.** `store.json` carries `schedule` (a list of entries) and `cursor` (int). An entry matches an operation when: `"list"` ↔ a list; `"post:<s>"` ↔ a post whose body's first line contains `<s>`; `"patch:<id>"` ↔ a PATCH of that id, `"patch:<id>:<s>"` ↔ a PATCH of that id whose new body's first line contains `<s>`; `"delete:<id>"` ↔ a delete of that id. Under the lock, find the first index `i >= cursor` whose entry matches. None → run the operation unscheduled. `i == cursor` → run it and set `cursor = i + 1`. `i > cursor` → release the lock, sleep 0.01 s and retry; after 10 s, stderr `fake gh: schedule entry <i> never reached`, exit 66.
2. Methods on `ForgeWorld`:

```python
    def comment_store(self, slug: str, issue: int, comments=(), *, next_id: int = 100,
                      clock: str = "2026-11-06T10:00:00Z", schedule=()) -> None:
        """Serve one issue's comments from shared state (see STORE_HANDLER)."""
        (self.state / "store.json").write_text(json.dumps({
            "slug": slug, "issue": issue, "comments": list(comments), "next_id": next_id,
            "clock": clock, "schedule": list(schedule), "cursor": 0}), encoding="utf-8")

    def stored(self) -> list[dict]:
        """The store's comments now, ascending id."""
        store = json.loads((self.state / "store.json").read_text("utf-8"))
        return sorted(store["comments"], key=lambda c: c["id"])

    def wait_cursor(self, at_least: int, timeout: float = 10.0) -> None:
        """Block until `at_least` schedule entries have run; AssertionError after `timeout`."""
```

   `wait_cursor` polls `store.json`'s `cursor` every 0.01 s. `reset()` also unlinks `store.json` and `store.lock` when present.
3. A module-level context manager (add `import contextlib`, `from datetime import datetime, timezone`):

```python
@contextlib.contextmanager
def host_clock(instant: datetime, *modules):
    """Make every host-clock read return `instant`: `time.time`, and `now`/`utcnow`/`today`
    on the `datetime` name of each module in `modules` (issue 623 D5)."""
    class WrongClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return instant.astimezone(timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.now()

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch("time.time", return_value=instant.timestamp()))
        for module in modules:
            stack.enter_context(mock.patch.object(module, "datetime", WrongClock))
        yield
```

Add one module-docstring paragraph naming `comment_store` (with its schedule rule) and `host_clock` (issue 623).

- [ ] **Step 2: Write the failing tests** — `tests/test_forge_markers.py`

```python
"""forge_markers (issue 623): grammar, reads and writes against the fake gh, and the race table."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from agent_tools import forge_markers as fm
from .forge_world import ForgeWorld, host_clock

SLUG, ISSUE = "octo/widgets", 7
LIST = ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{ISSUE}/comments?per_page=100"]
T0 = "2026-11-06T10:00:00Z"
A, B = "mbp/session-a", "eleven-m5/session-b"
MATCH = {"issue": str(ISSUE)}


def comment(cid, body, updated_at=T0):
    return {"id": cid, "body": body, "updated_at": updated_at, "created_at": updated_at}


def claim_body(holder, **extra):
    return fm.render("claim", {"issue": str(ISSUE), "holder": holder, **extra}, f"Claimed by {holder}.")


class GrammarTest(unittest.TestCase):
    def test_render_then_parse_round_trips(self):
        body = fm.render("claim", {"issue": "7", "holder": "mbp/session-a"}, "Claimed.", "- [ ] x")
        self.assertEqual(body, "<!-- agent:claim v1 issue=7 holder=mbp/session-a -->\nClaimed.\n- [ ] x")
        marker = fm.parse(comment(5, body))
        self.assertEqual((marker.comment_id, marker.kind, marker.fields),
                         (5, "claim", {"issue": "7", "holder": "mbp/session-a"}))
        self.assertEqual(marker.updated_at, datetime(2026, 11, 6, 10, tzinfo=timezone.utc))

    def test_non_markers_parse_to_none(self):
        for body in ("plain text", "<!-- agent:claim v2 issue=7 -->\nx",
                     "<!-- agent:claim v1 issue=7 issue=8 -->\nx", "<!-- agent:Claim v1 -->\nx",
                     "x\n<!-- agent:claim v1 issue=7 -->", None):
            with self.subTest(body=body):
                self.assertIsNone(fm.parse(comment(1, body)))

    def test_render_refuses_bad_values(self):
        for kind, fields, sentence in (("claim", {"holder": "a b"}, "x"), ("claim", {"Bad": "1"}, "x"),
                                       ("claim", {"k": "v-->"}, "x"), ("claim", {}, "two\nlines"),
                                       ("claim", {}, ""), ("Claim", {}, "x")):
            with self.subTest(fields=fields, sentence=sentence), self.assertRaises(ValueError):
                fm.render(kind, fields, sentence)

    def test_with_fields_keeps_order_and_appends(self):
        marker = fm.parse(comment(1, claim_body("mbp/s") + "\nrest"))
        self.assertEqual(fm.with_fields(marker, holder="m5/t", renewed="1"),
                         "<!-- agent:claim v1 issue=7 holder=m5/t renewed=1 -->\nClaimed by mbp/s.\nrest")

    def test_end_markers_and_released_fields_end_claims(self):
        self.assertEqual(fm.end_body(1, "done"),
                         "<!-- agent:end v1 of=1 reason=done -->\nEnds marker comment 1 (done).")
        markers = [fm.parse(comment(cid, body)) for cid, body in (
            (1, claim_body("b/y")), (2, claim_body("c/z")), (3, claim_body("a/x")),
            (4, fm.end_body(1, "done")), (5, claim_body("d/w", released="done")))]
        self.assertEqual(fm.ended(markers), {1})
        self.assertEqual([fm.is_live(m, markers) for m in markers], [False, True, True, False, False])
        self.assertEqual([m.comment_id for m in fm.contest(markers, "claim", MATCH)], [2, 3])
        self.assertEqual(fm.contest(markers, "claim", {"issue": "8"}), [])


class ReadWriteTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def test_list_flattens_pages_and_drops_non_markers(self):
        self.world.respond_json("gh", LIST, [[comment(2, claim_body("a/x")), comment(1, "hello")],
                                             [comment(4, claim_body("b/y"))]])
        self.assertEqual([m.comment_id for m in fm.list_markers(SLUG, ISSUE)], [2, 4])

    def test_server_now_reads_the_date_header_not_the_host_clock(self):
        self.world.respond("gh", ["api", "--include", "rate_limit"],
                           stdout="HTTP/2.0 200 OK\ndate: Fri, 06 Nov 2026 12:00:00 GMT\n\n{}")
        for instant in (datetime(1970, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc)):
            with self.subTest(instant=instant), host_clock(instant, fm):
                self.assertEqual(fm.datetime.now(timezone.utc), instant)  # the seam reaches the module
                self.assertEqual(fm.server_now(), datetime(2026, 11, 6, 12, tzinfo=timezone.utc))

    def test_tolerated_statuses(self):
        self.world.respond("gh", ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=x",
                                  "-f", "color=FBCA04"], exit=1, stderr="gh: Validation Failed (HTTP 422)")
        self.world.not_found("gh", ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/x"])
        fm.ensure_label(SLUG, "x", "FBCA04")
        fm.remove_label(SLUG, ISSUE, "x")
        self.world.respond("gh", LIST, exit=1, stderr="gh: Server Error (HTTP 500)")
        with self.assertRaises(fm.ForgeError) as raised:
            fm.list_markers(SLUG, ISSUE)
        self.assertEqual(raised.exception.code, "gh_failed")

    def test_branch_activity(self):
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/activity?ref=refs/heads/topic"
                                       "&activity_type=push&per_page=1"], [{"timestamp": T0}])
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/pulls?state=all&head=octo:topic&per_page=100"],
                                [{"updated_at": "2026-11-05T00:00:00Z"}, {"updated_at": T0}])
        t0 = datetime(2026, 11, 6, 10, tzinfo=timezone.utc)
        self.assertEqual((fm.latest_push(SLUG, "topic"), fm.latest_pr_event(SLUG, "topic")), (t0, t0))

    def test_token_never_reaches_gh(self):
        self.world.respond_json("gh", LIST, [[]])
        fm.list_markers(SLUG, ISSUE)
        self.assertFalse(any(call["token_visible"] for call in self.world.calls()))

    def test_a_later_edit_cannot_revive_an_ended_marker(self):
        self.world.comment_store(SLUG, ISSUE, [comment(5, claim_body(A, released="done"))], next_id=9)
        self.assertEqual(fm.end(SLUG, ISSUE, 5, "done"), 9)
        fm.edit(SLUG, 5, claim_body(A, renewed="1"))  # a stale rewrite drops `released`
        markers = fm.list_markers(SLUG, ISSUE)
        self.assertEqual([m.comment_id for m in markers], [5, 9])
        self.assertFalse(fm.is_live(markers[0], markers))
        self.assertEqual(fm.contest(markers, "claim", MATCH), [])


def live_claims(world):
    markers = [m for m in (fm.parse(c) for c in world.stored()) if m]
    return fm.contest(markers, "claim", MATCH)


def write_claim(holder):
    return fm.write(SLUG, ISSUE, "claim", {"issue": str(ISSUE), "holder": holder},
                    f"Claimed by {holder}.", MATCH)


def post_of(holder):
    return f"post:holder={holder}"


def race(writer):
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {holder: pool.submit(writer, holder) for holder in (A, B)}
    return {holder: future.result() for holder, future in futures.items()}


# Each row forces one interleaving of the two writers' post and re-read on the shared store; the
# server assigns ids in post order, so the first poster wins. A writer that lists before it posts
# never reaches its first scheduled entry and fails with the fake's exit 66.
SCHEDULES = [
    ("A post, A read, B post, B read", [post_of(A), "list", post_of(B), "list"], A),
    ("A post, B post, both read", [post_of(A), post_of(B), "list", "list"], A),
    ("B post, A post, both read", [post_of(B), post_of(A), "list", "list"], B),
    ("B post, B read, A post, A read", [post_of(B), "list", post_of(A), "list"], B),
]


class RaceTest(unittest.TestCase):
    def test_two_writers_converge_to_one_live_claim(self):
        for name, schedule, winner in SCHEDULES:
            with self.subTest(name):
                world = ForgeWorld(self)
                world.comment_store(SLUG, ISSUE, next_id=101, schedule=schedule)
                results = race(write_claim)
                loser = B if winner == A else A
                self.assertTrue(results[winner].won)
                self.assertFalse(results[loser].won)
                self.assertEqual(results[loser].winner.comment_id, results[winner].own_id)
                self.assertEqual(results[loser].winner.fields["holder"], winner)
                self.assertEqual([m.fields["holder"] for m in live_claims(world)], [winner])
                self.assertNotIn(results[loser].own_id, [c["id"] for c in world.stored()])
                comment_posts = [a for a in world.argvs("gh")
                                 if a[:4] == ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments"]]
                self.assertEqual(len(comment_posts), 2)
                self.assertEqual([a for a in world.argvs("gh") if "DELETE" in a],
                                 [["api", "-X", "DELETE", f"repos/{SLUG}/issues/comments/{results[loser].own_id}"]])

    def test_the_table_catches_a_writer_that_reads_before_posting(self):
        def check_then_post(holder):
            if not fm.contest(fm.list_markers(SLUG, ISSUE), "claim", MATCH):
                fm.post(SLUG, ISSUE, claim_body(holder))

        world = ForgeWorld(self)
        world.comment_store(SLUG, ISSUE, next_id=101, schedule=["list", "list", post_of(A), post_of(B)])
        race(check_then_post)
        self.assertEqual(len(live_claims(world)), 2)  # the final-state check above would reject it

    def test_an_ended_claim_does_not_win(self):
        world = ForgeWorld(self)
        world.comment_store(SLUG, ISSUE, [comment(90, claim_body(B)), comment(91, fm.end_body(90, "done"))],
                            next_id=101)
        result = write_claim(A)
        self.assertEqual((result.won, result.own_id), (True, 101))
        self.assertFalse(any("DELETE" in argv for argv in world.argvs("gh")))


class NoHostClockTest(unittest.TestCase):
    def test_module_reads_no_host_clock(self):
        source = Path(fm.__file__).read_text("utf-8")
        for spelling in ("time.time", ".now(", "utcnow", "date.today", "localtime"):
            self.assertNotIn(spelling, source)
        self.assertIn("from datetime import datetime", source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `bash -o pipefail -c 'env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_markers.py 2>&1 | tail -5'`
Expected: non-zero exit — `ImportError: cannot import name 'forge_markers'`.

- [ ] **Step 4: Write the implementation**

`python/agent_tools/forge_markers.py` with the Interfaces above and a module docstring stating D1, D2 and D9 (cite issue 623). Grammar: `MARKER = re.compile(r"<!-- agent:(?P<kind>[a-z][a-z0-9-]*) v1(?P<fields>(?: [a-z][a-z0-9_]*=[A-Za-z0-9._:/@+-]+)*) -->")`, `KIND = r"[a-z][a-z0-9-]*"`, `KEY = r"[a-z][a-z0-9_]*"`, `VALUE = r"[A-Za-z0-9._:/@+-]+"`. Timestamps via `datetime.fromisoformat` (`Z` accepted), forced to UTC. One private `_gh(argv, allow=()) -> tuple[int, str]` (returncode-or-0, stdout) carries the child rules; `_json(argv, allow=())` parses. `ended` ignores an `end` marker whose `of` is not an integer.

- [ ] **Step 5: Verify**

Run: `bash -o pipefail -c 'env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_markers.py 2>&1 | tail -5'`
Expected: exit 0, `OK`, 15 tests, no skips.
Run: `bash -o pipefail -c 'env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_verification.py 2>&1 | tail -3'` (an existing `ForgeWorld` user)
Expected: exit 0, `OK`.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/forge_markers.py tests/forge_world.py tests/test_forge_markers.py
git commit -m "feat(issue-623): race-safe forge markers on issue comments

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
