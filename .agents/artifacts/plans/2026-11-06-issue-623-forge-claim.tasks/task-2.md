# Task 2: `forge-claim acquire`, `renew`, `release`

**Files:**
- Create: `python/agent_tools/forge_claim.py`
- Test: `tests/test_forge_claim.py`

**Interfaces:**
- Consumes (Task 1, `agent_tools.forge_markers`): `ForgeError(code, detail)`, `Marker`, `render`, `with_fields`, `contest`, `list_markers(slug, issue)`, `write(slug, issue, kind, fields, sentence, match, extra="") -> WriteResult(won, own_id, winner)`, `edit(slug, comment_id, body)`, `ensure_label(slug, name, color)`, `add_label(slug, issue, name)`, `remove_label(slug, issue, name)`; `ForgeWorld.respond_sequence` in `tests/forge_world.py`. The fake keys on exact argv:
  - list `["api", "--paginate", "--slurp", "repos/<slug>/issues/<n>/comments?per_page=100"]`; post `["api", "-X", "POST", "repos/<slug>/issues/<n>/comments", "-f", "body=<body>"]`; edit `["api", "-X", "PATCH", "repos/<slug>/issues/comments/<id>", "-f", "body=<body>"]`; delete `["api", "-X", "DELETE", "repos/<slug>/issues/comments/<id>"]`; ensure label `["api", "-X", "POST", "repos/<slug>/labels", "-f", "name=<l>", "-f", "color=<c>"]`; add label `["api", "-X", "POST", "repos/<slug>/issues/<n>/labels", "-f", "labels[]=<l>"]`; remove label `["api", "-X", "DELETE", "repos/<slug>/issues/<n>/labels/<l>"]`.
- Produces (`agent_tools.forge_claim`, imports only the standard library and `agent_tools.forge_markers`):
  - `main(argv: list[str] | None = None) -> int`; `if __name__ == "__main__": sys.exit(main())`.
  - `build_parser() -> argparse.ArgumentParser` (prog `forge-claim`) with subcommands `acquire`, `renew`, `release`, each taking `--repo` (`[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+`), `--issue` (int ≥ 1), `--holder` (`[A-Za-z0-9][A-Za-z0-9.-]*/[A-Za-z0-9][A-Za-z0-9._-]*`: `<host>/<batch_id>` or `<host>/session-<id>`); `acquire` and `renew` take optional `--branch` (`[A-Za-z0-9_][A-Za-z0-9_./-]*`, D4); `release` takes `--reason` (`[A-Za-z0-9._:/@+-]+`, default `done`). A value failing its pattern is an argparse error (exit 2, no JSON).
  - Claim marker: `render("claim", {"issue": str(n), "holder": h[, "branch": b]}, f"Claimed by {h}.")`; contest match `{"issue": str(n)}`. Constants `CLAIM_KIND = "claim"`, `IN_PROGRESS = ("in-progress", "FBCA04")`.
  - Output: exactly one JSON object on stdout, one line, keys `command`, `repo`, `issue` (int), `holder`, `verdict`, `comment_id` (int or null), `by` (holder string or null); `release` adds `label_removed` (bool); an error is `verdict: "error"` with `error` (the `ForgeError` code) and `detail`, exit 1 (D8).

**Invariants:**
- `acquire`: list; contest. A winner with the same holder → `already_held` (its id), ensure and add `in-progress`, exit 0, no post. A winner with another holder → `held_by`, `by` = it, exit 3, no post and no label call (stale is never stolen). No winner → `write`; won → `acquired` (own id), ensure and add `in-progress`, exit 0; lost to the same holder → `already_held` (winner id), exit 0; lost to another → `lost_to`, `by` = winner, exit 3 (the delete happened inside `write`).
- `renew` (D3): the contest winner must have this holder, else `not_held` (`by` = the winner's holder or null), exit 3, no PATCH. It PATCHes that comment with `with_fields(winner, renewed=str(prev + 1)[, branch=b])` where `prev` is the `renewed` field or 0 → `renewed`, exit 0. Never a POST.
- `release`: the first live claim with this holder (ascending id) gets `with_fields(own, released=reason)`; then re-list; when `contest` is empty → `remove_label(in-progress)` and `label_removed: true`, else no label call and `false`; verdict `released`, exit 0. No live claim of this holder → `not_held`, exit 3.

- [ ] **Step 1: Write the failing tests** — `tests/test_forge_claim.py`

```python
"""forge-claim (issue 623): acquire, renew and release against the fake gh."""
import contextlib
import io
import json
import unittest

from agent_tools import forge_claim
from agent_tools import forge_markers as fm
from .forge_world import ForgeWorld

SLUG, ISSUE = "octo/widgets", 7
ME, OTHER = "mbp/session-a", "eleven-m5/session-b"
T0 = "2026-11-06T10:00:00Z"
LIST = ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{ISSUE}/comments?per_page=100"]
ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=in-progress", "-f", "color=FBCA04"]
ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=in-progress"]
REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/in-progress"]


def claim_body(holder, **extra):
    return fm.render("claim", {"issue": str(ISSUE), "holder": holder, **extra}, f"Claimed by {holder}.")


def comment(cid, body, updated_at=T0):
    return {"id": cid, "body": body, "updated_at": updated_at, "created_at": updated_at}


def listing(*comments):
    return {"stdout": json.dumps([list(comments)])}


def post(body):
    return ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments", "-f", f"body={body}"]


def patch(cid, body):
    return ["api", "-X", "PATCH", f"repos/{SLUG}/issues/comments/{cid}", "-f", f"body={body}"]


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = forge_claim.main(list(argv))
    return code, json.loads(out.getvalue())


def common(command, holder=ME):
    return [command, "--repo", SLUG, "--issue", str(ISSUE), "--holder", holder]


class Base(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        for argv in (ENSURE, ADD, REMOVE):
            self.world.respond("gh", argv)

    def mutations(self):
        return [argv for argv in self.world.argvs("gh") if "-X" in argv]


class AcquireTest(Base):
    def test_free_issue_is_acquired_and_labelled(self):
        mine = claim_body(ME)
        self.world.respond_json("gh", post(mine), comment(11, mine))
        self.world.respond_sequence("gh", LIST, [listing(), listing(comment(11, mine))])
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["comment_id"], out["by"]), (0, "acquired", 11, None))
        self.assertEqual(self.mutations(), [post(mine), ENSURE, ADD])

    def test_branch_is_recorded(self):
        mine = claim_body(ME, branch="issue-7-x")
        self.world.respond_json("gh", post(mine), comment(11, mine))
        self.world.respond_sequence("gh", LIST, [listing(), listing(comment(11, mine))])
        code, out = run(*common("acquire"), "--branch", "issue-7-x")
        self.assertEqual((code, out["verdict"]), (0, "acquired"))

    def test_own_claim_resumes(self):
        self.world.respond_json("gh", LIST, [[comment(5, claim_body(ME))]])
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
        self.assertNotIn(post(claim_body(ME)), self.world.argvs("gh"))

    def test_other_claim_is_held_by_and_untouched(self):
        self.world.respond_json("gh", LIST, [[comment(5, claim_body(OTHER))]])
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["by"]), (3, "held_by", OTHER))
        self.assertEqual(self.mutations(), [])

    def test_lost_race_reports_lost_to_and_deletes(self):
        mine, theirs = claim_body(ME), claim_body(OTHER)
        self.world.respond_json("gh", post(mine), comment(12, mine))
        self.world.respond("gh", ["api", "-X", "DELETE", f"repos/{SLUG}/issues/comments/12"])
        self.world.respond_sequence("gh", LIST, [listing(), listing(comment(11, theirs), comment(12, mine))])
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["by"]), (3, "lost_to", OTHER))
        self.assertIn(["api", "-X", "DELETE", f"repos/{SLUG}/issues/comments/12"], self.mutations())
        self.assertNotIn(ADD, self.mutations())

    def test_forge_error_is_exit_1(self):
        self.world.respond("gh", LIST, exit=1, stderr="gh: Server Error (HTTP 500)")
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "gh_failed"))

    def test_bad_holder_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            forge_claim.main(common("acquire", holder="no-slash"))
        self.assertEqual(raised.exception.code, 2)


class ReleaseRenewTest(Base):
    def test_renew_edits_the_same_comment(self):
        for before, after in (({}, "1"), ({"renewed": "1"}, "2")):
            with self.subTest(before=before):
                self.world.reset()
                body = claim_body(ME, **before)
                self.world.respond_json("gh", LIST, [[comment(5, body)]])
                expected = patch(5, claim_body(ME, renewed=after))
                self.world.respond("gh", expected)
                code, out = run(*common("renew"))
                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "renewed", 5))
                self.assertEqual(self.mutations(), [expected])

    def test_renew_by_another_holder_is_not_held(self):
        self.world.respond_json("gh", LIST, [[comment(5, claim_body(OTHER))]])
        code, out = run(*common("renew"))
        self.assertEqual((code, out["verdict"], out["by"]), (3, "not_held", OTHER))
        self.assertEqual(self.mutations(), [])

    def test_release_removes_the_label_when_no_live_claim_remains(self):
        released = patch(5, claim_body(ME, released="done"))
        self.world.respond("gh", released)
        self.world.respond_sequence("gh", LIST, [listing(comment(5, claim_body(ME))),
                                                 listing(comment(5, claim_body(ME, released="done")))])
        code, out = run(*common("release"))
        self.assertEqual((code, out["verdict"], out["label_removed"]), (0, "released", True))
        self.assertEqual(self.mutations(), [released, REMOVE])

    def test_release_keeps_the_label_while_another_live_claim_remains(self):
        released = patch(5, claim_body(ME, released="merged"))
        self.world.respond("gh", released)
        other = comment(9, claim_body(OTHER))
        self.world.respond_sequence("gh", LIST, [
            listing(comment(5, claim_body(ME)), other),
            listing(comment(5, claim_body(ME, released="merged")), other)])
        code, out = run(*common("release"), "--reason", "merged")
        self.assertEqual((code, out["verdict"], out["label_removed"]), (0, "released", False))
        self.assertEqual(self.mutations(), [released])

    def test_release_without_a_claim_is_not_held(self):
        self.world.respond_json("gh", LIST, [[]])
        code, out = run(*common("release"))
        self.assertEqual((code, out["verdict"]), (3, "not_held"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_claim.py 2>&1 | tail -5`
Expected: FAIL — `ImportError: cannot import name 'forge_claim'`.

- [ ] **Step 3: Write the implementation**

`python/agent_tools/forge_claim.py` per Interfaces and Invariants, with a module docstring naming issue 623, D2, D3, D7, D8. Each subcommand is one function `(args) -> tuple[int, dict]`; `main` parses, dispatches, catches `forge_markers.ForgeError` into the error object, prints `json.dumps(result, sort_keys=True)` once, returns the code. Leave room for Task 3: dispatch through a `{name: function}` table.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_claim.py tests/test_forge_markers.py 2>&1 | tail -5`
Expected: `OK`, 25 tests, no skips.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/forge_claim.py tests/test_forge_claim.py
git commit -m "feat(issue-623): forge-claim acquire, renew and release

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
