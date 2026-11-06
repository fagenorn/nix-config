# Task 1: Marker grammar, forge reads and writes, race-settled write

**Files:**
- Create: `python/agent_tools/forge_markers.py`
- Modify: `tests/forge_world.py`
- Test: `tests/test_forge_markers.py`

**Interfaces:**
- Consumes: `tests/forge_world.py` `ForgeWorld` (`respond`, `respond_json`, `argvs`, `not_found`).
- Produces (`agent_tools.forge_markers`, standard library only, imports no other `agent_tools` module):
  - `class ForgeError(Exception)` with attributes `code: str` (`gh_missing`, `gh_failed`, `gh_timeout`, `payload_invalid`) and `detail: str` (stderr, at most 240 chars).
  - `@dataclass(frozen=True) class Marker`: `comment_id: int`, `kind: str`, `fields: dict[str, str]` (first-line order), `body: str`, `updated_at: datetime` (aware, UTC).
  - `render(kind: str, fields: Mapping[str, str], sentence: str, extra: str = "") -> str` — `"<!-- agent:{kind} v1 k=v ... -->\n{sentence}"` plus `"\n" + extra` when `extra` is non-empty; `ValueError` for a kind, key or value outside D1's grammar, or a sentence that is empty or holds a newline.
  - `parse(comment: Mapping[str, Any]) -> Marker | None` — from a REST comment object (`id`, `body`, `updated_at`).
  - `with_fields(marker: Marker, **updates: str) -> str` — the body with the first line re-rendered: existing keys keep their position and take the new value, new keys append in argument order; every other line unchanged.
  - `is_live(marker) -> bool` — no `released` and no `resolved` field.
  - `contest(markers, kind: str, match: Mapping[str, str]) -> list[Marker]` — live markers of `kind` whose fields contain every `match` pair, ascending `comment_id`.
  - `list_markers(slug: str, issue: int) -> list[Marker]` — every parseable marker on the issue, ascending `comment_id`.
  - `@dataclass(frozen=True) class WriteResult`: `won: bool`, `own_id: int`, `winner: Marker | None` (`None` only when the re-read lacks every contested marker, own included).
  - `write(slug, issue, kind, fields, sentence, match, extra="") -> WriteResult`.
  - `edit(slug: str, comment_id: int, body: str) -> None`, `delete(slug: str, comment_id: int) -> None`.
  - `server_now() -> datetime` (D5).
  - `ensure_label(slug, name, color) -> None`, `add_label(slug, issue, name) -> None`, `remove_label(slug, issue, name) -> None` (D7).
  - `latest_push(slug, branch) -> datetime | None`, `latest_pr_event(slug, branch) -> datetime | None` (D4).
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
- `write` (D2): post; `list_markers`; `contest` over the re-read plus own id (own counted even when the re-read omits it); winner = smallest id. If own id is the winner → `won=True`, no delete. Else delete own and return `won=False` with the winner. Exactly one post per call, at most one delete, never a retry.
- No host clock call in the module (Global Constraints).

- [ ] **Step 1: Add `respond_sequence` to `ForgeWorld`**

In `tests/forge_world.py`, the stored response may be a list. In `SCRIPT`, after the lookup: when `response` is a list, take `response[0]`, and when the list has more than one entry write `responses[key] = response[1:]` back to `responses.json` before answering (the last entry repeats). Add

```python
    def respond_sequence(self, tool: str, argv: list[str], answers: list[dict]) -> None:
        """Answer successive identical calls in order; the last answer repeats. Each answer
        is a dict of `exit`, `stdout`, `stderr`, `sleep` (missing keys default to 0/"")."""
        path = self.state / "responses.json"
        responses = json.loads(path.read_text("utf-8"))
        responses[json.dumps([tool, *argv])] = [
            {"exit": 0, "stdout": "", "stderr": "", "sleep": 0, **answer} for answer in answers]
        path.write_text(json.dumps(responses), encoding="utf-8")
```

and one docstring sentence in the module docstring naming it. Existing single responses behave as before.

- [ ] **Step 2: Write the failing tests** — `tests/test_forge_markers.py`

```python
"""forge_markers (issue 623): grammar, reads and writes against the fake gh, and the race table."""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools import forge_markers as fm
from .forge_world import ForgeWorld

SLUG, ISSUE = "octo/widgets", 7
LIST = ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{ISSUE}/comments?per_page=100"]
T0 = "2026-11-06T10:00:00Z"


def comment(cid, body, updated_at=T0):
    return {"id": cid, "body": body, "updated_at": updated_at, "created_at": updated_at}


def claim_body(holder, **extra):
    return fm.render("claim", {"issue": str(ISSUE), "holder": holder, **extra},
                     f"Claimed by {holder}.")


def post_argv(body):
    return ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments", "-f", f"body={body}"]


def delete_argv(cid):
    return ["api", "-X", "DELETE", f"repos/{SLUG}/issues/comments/{cid}"]


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
        self.assertEqual(fm.with_fields(marker, holder="m5/t", released="done"),
                         "<!-- agent:claim v1 issue=7 holder=m5/t released=done -->\nClaimed by mbp/s.\nrest")

    def test_liveness_and_contest(self):
        markers = [fm.parse(comment(3, claim_body("a/x"))),
                   fm.parse(comment(1, claim_body("b/y", released="done"))),
                   fm.parse(comment(2, claim_body("c/z")))]
        self.assertEqual([m.comment_id for m in fm.contest(markers, "claim", {"issue": "7"})], [2, 3])
        self.assertEqual(fm.contest(markers, "claim", {"issue": "8"}), [])


class ReadWriteTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def test_list_flattens_pages_and_drops_non_markers(self):
        self.world.respond_json("gh", LIST, [[comment(2, claim_body("a/x")), comment(1, "hello")],
                                             [comment(4, claim_body("b/y"))]])
        self.assertEqual([m.comment_id for m in fm.list_markers(SLUG, ISSUE)], [2, 4])

    def test_server_now_reads_the_date_header(self):
        self.world.respond("gh", ["api", "--include", "rate_limit"],
                           stdout="HTTP/2.0 200 OK\ndate: Fri, 06 Nov 2026 12:00:00 GMT\n\n{}")
        with mock.patch("time.time", return_value=0.0):
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


A, B = "mbp/session-a", "eleven-m5/session-b"
# Each row: ids the server assigns to A's and B's posts, then what the two re-reads return in the
# order the calls run in-process (A's write first), as the interleaving left them: a re-read lists
# every comment created, and not yet deleted, before it started. `A`/`B` name the live claims visible to that re-read.
RACES = [
    ("A post, A read, B post, B read", {A: 101, B: 102}, [[A], [A, B]], A),
    ("A post, B post, A read, B read", {A: 101, B: 102}, [[A, B], [A, B]], A),
    ("B post, A post, A read, B read", {A: 102, B: 101}, [[A, B], [B]], B),
    ("B post, A post, B read, A read", {A: 102, B: 101}, [[A, B], [A, B]], B),
]


class RaceTest(unittest.TestCase):
    def test_two_writers_converge_to_one_live_claim(self):
        for name, ids, reads, expected in RACES:
            with self.subTest(name):
                world = ForgeWorld(self)
                bodies = {holder: claim_body(holder) for holder in (A, B)}
                for holder, cid in ids.items():
                    world.respond_json("gh", post_argv(bodies[holder]), comment(cid, bodies[holder]))
                    world.respond("gh", delete_argv(cid))
                world.respond_sequence("gh", LIST, [
                    {"stdout": json.dumps([[comment(ids[h], bodies[h]) for h in read]])} for read in reads])
                results = {holder: fm.write(SLUG, ISSUE, "claim", {"issue": str(ISSUE), "holder": holder},
                                            f"Claimed by {holder}.", {"issue": str(ISSUE)})
                           for holder in (A, B)}
                loser = B if expected == A else A
                self.assertTrue(results[expected].won)
                self.assertFalse(results[loser].won)
                self.assertEqual(results[loser].winner.fields["holder"], expected)
                deletes = [argv for argv in world.argvs("gh") if "DELETE" in argv]
                self.assertEqual(deletes, [delete_argv(ids[loser])])
                posted = {argv[-1] for argv in world.argvs("gh") if "POST" in argv}
                self.assertEqual(len(posted), 2)

    def test_released_claim_does_not_win(self):
        world = ForgeWorld(self)
        old = claim_body(B, released="done")
        mine = claim_body(A)
        world.respond_json("gh", post_argv(mine), comment(101, mine))
        world.respond_json("gh", LIST, [[comment(90, old), comment(101, mine)]])
        result = fm.write(SLUG, ISSUE, "claim", {"issue": str(ISSUE), "holder": A},
                          f"Claimed by {A}.", {"issue": str(ISSUE)})
        self.assertTrue(result.won)
        self.assertFalse(any("DELETE" in argv for argv in world.argvs("gh")))


class NoHostClockTest(unittest.TestCase):
    def test_module_reads_no_host_clock(self):
        source = Path(fm.__file__).read_text("utf-8")
        for spelling in ("time.time", ".now(", "utcnow", "date.today", "localtime"):
            self.assertNotIn(spelling, source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_markers.py 2>&1 | tail -5`
Expected: FAIL — `ImportError: cannot import name 'forge_markers'`.

- [ ] **Step 4: Write the implementation**

`python/agent_tools/forge_markers.py` with the Interfaces above and a module docstring stating D1 and D2 (cite issue 623). Grammar: `MARKER = re.compile(r"<!-- agent:(?P<kind>[a-z][a-z0-9-]*) v1(?P<fields>(?: [a-z][a-z0-9_]*=[A-Za-z0-9._:/@+-]+)*) -->")`, `KIND = r"[a-z][a-z0-9-]*"`, `KEY = r"[a-z][a-z0-9_]*"`, `VALUE = r"[A-Za-z0-9._:/@+-]+"`. Timestamps via `datetime.fromisoformat` (`Z` accepted), forced to UTC. One private `_gh(argv, allow=()) -> tuple[int, str]` (returncode-or-0, stdout) carries the child rules; `_json(argv, allow=())` parses. `write`: after the delete of a lost write, the returned `winner` is the smallest contested marker that is not own.

- [ ] **Step 5: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_markers.py 2>&1 | tail -5`
Expected: `OK`, 13 tests, no skips.
Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_verification.py 2>&1 | tail -3` (an existing `ForgeWorld` user)
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/forge_markers.py tests/forge_world.py tests/test_forge_markers.py
git commit -m "feat(issue-623): race-safe forge markers on issue comments

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
