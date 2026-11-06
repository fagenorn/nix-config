# Task 2: `forge-claim acquire`, `renew`, `release`

**Files:**
- Create: `python/agent_tools/forge_claim.py`
- Test: `tests/test_forge_claim.py`

**Interfaces:**
- Consumes (Task 1, `agent_tools.forge_markers`): `ForgeError(code, detail)`, `Marker`, `render`, `end_body`, `with_fields`, `is_live`, `contest`, `list_markers(slug, issue)`, `post`, `end(slug, issue, of, reason) -> int`, `write(slug, issue, kind, fields, sentence, match, extra="") -> WriteResult(won, own_id, winner)`, `edit(slug, comment_id, body)`, `ensure_label(slug, name, color)`, `add_label(slug, issue, name)`, `remove_label(slug, issue, name)`. Task 1's `tests/forge_world.py`: `ForgeWorld.comment_store(slug, issue, comments=(), *, next_id, clock, schedule)`, `stored()`, `wait_cursor(n)`; label argv: ensure `["api", "-X", "POST", "repos/<slug>/labels", "-f", "name=<l>", "-f", "color=<c>"]`, add `["api", "-X", "POST", "repos/<slug>/issues/<n>/labels", "-f", "labels[]=<l>"]`, remove `["api", "-X", "DELETE", "repos/<slug>/issues/<n>/labels/<l>"]`.
- Produces (`agent_tools.forge_claim`, imports the standard library and `agent_tools.forge_markers` only):
  - `main(argv: list[str] | None = None) -> int`; `if __name__ == "__main__": sys.exit(main())`.
  - `build_parser() -> argparse.ArgumentParser` (prog `forge-claim`) with subcommands `acquire`, `renew`, `release`, each taking `--repo` (`[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+`), `--issue` (int ≥ 1), `--holder` (`[A-Za-z0-9][A-Za-z0-9.-]*/[A-Za-z0-9][A-Za-z0-9._-]*`: `<host>/<batch_id>` or `<host>/session-<id>`); `acquire` and `renew` take optional `--branch` (`[A-Za-z0-9_][A-Za-z0-9_./-]*`, D4); `release` takes `--reason` (`[A-Za-z0-9._:/@+-]+`, default `done`). The parser's `error(message)` raises a private `UsageError(message)` instead of exiting; a subcommand is required.
  - Claim marker: `render("claim", {"issue": str(n), "holder": h[, "branch": b]}, f"Claimed by {h}.")`; contest match `{"issue": str(n)}`. Constants `CLAIM_KIND = "claim"`, `IN_PROGRESS = ("in-progress", "FBCA04")`, `OWNER_ACTION = ("owner-action", "D93F0B")`, `OWNER_ACTION_KIND = "owner-action"`.
  - `retire_owner_actions(slug: str, issue: int, markers: list[Marker], claim_id: int | None, reason: str) -> list[int]` (D10): `end`s every live `owner-action` marker of this issue whose `claim` field is `str(claim_id)` (every one when `claim_id` is None), with `reason`; when it ended at least one and no live `owner-action` of the issue remains (judged on `markers` plus the ids it ended), `remove_label(owner-action)`. Returns the ended marker ids, ascending.
  - Output (D8): exactly one JSON object on stdout, one line (`json.dumps(result, sort_keys=True)`), keys `command`, `repo`, `issue` (int), `holder`, `verdict`, `comment_id` (int or null), `by` (holder string or null); `release` adds `label_removed` (bool); a forge error is `verdict: "error"` with `error` (the `ForgeError` code) and `detail`, exit 1; a usage error is `{"command": <subcommand or null>, "repo": null, "issue": null, "holder": null, "verdict": "error", "comment_id": null, "by": null, "error": "usage", "detail": <message>}`, exit 2.

**Invariants:**
- `acquire`: list; contest. A winner with the same holder → `already_held` (its id), ensure and add `in-progress`, exit 0, no post. A winner with another holder → `held_by`, `by` = it, exit 3, no post and no label call (stale is never stolen). No winner → `write`; won → `acquired` (own id), ensure and add `in-progress`, exit 0; lost to the same holder → `already_held` (winner id), exit 0; lost to another → `lost_to`, `by` = winner, exit 3 (the delete happened inside `write`).
- `renew` (D3, D10): list; the contest winner must have this holder, else `not_held` (`by` = the winner's holder or null), exit 3, no PATCH. PATCH that comment with `with_fields(winner, renewed=str(prev + 1)[, branch=b])` where `prev` is the `renewed` field or 0. Re-list: when the claim is no longer live (an `end` names it) → `not_held`, `comment_id` = the claim id, `by` = null, exit 3, nothing further. Else `retire_owner_actions(..., claim_id, "renewed")` on the re-list → `renewed`, exit 0. Never a POST of a claim.
- `release` (D9, D10): the first live claim with this holder (ascending id) is ended — first `end(slug, issue, id, reason)`, then `edit(slug, id, with_fields(claim, released=reason))` — then `retire_owner_actions(..., id, "released")` on the first listing; then re-list; when `contest` is empty → `remove_label(in-progress)` and `label_removed: true`, else no in-progress label call and `false`; verdict `released`, exit 0. No live claim of this holder → `not_held`, exit 3, no mutation.
- A delayed `renew` PATCH can never make a released claim live again (D9): the `end` stays.
- Usage errors print the JSON object above and nothing else on stdout.

- [ ] **Step 1: Write the failing tests** — `tests/test_forge_claim.py`

```python
"""forge-claim (issue 623): acquire, renew and release against the fake gh."""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest

from agent_tools import forge_claim
from agent_tools import forge_markers as fm
from .forge_world import ForgeWorld

SLUG, ISSUE = "octo/widgets", 7
ME, OTHER = "mbp/session-a", "eleven-m5/session-b"
T0 = "2026-11-06T10:00:00Z"
MATCH = {"issue": str(ISSUE)}
LIST = ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{ISSUE}/comments?per_page=100"]
ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=in-progress", "-f", "color=FBCA04"]
ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=in-progress"]
REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/in-progress"]
OA_ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=owner-action", "-f", "color=D93F0B"]
OA_ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=owner-action"]
OA_REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/owner-action"]


def claim_body(holder, **extra):
    return fm.render("claim", {"issue": str(ISSUE), "holder": holder, **extra}, f"Claimed by {holder}.")


def oa_body(claim_id, holder, ticked=False):
    return fm.render("owner-action", {"issue": str(ISSUE), "reason": "stale-claim", "claim": str(claim_id)},
                     f"The claim of {holder} has had no renewal, push or pull request activity for 24 hours.",
                     f"- [{'x' if ticked else ' '}] Release this claim")


def comment(cid, body, updated_at=T0):
    return {"id": cid, "body": body, "updated_at": updated_at, "created_at": updated_at}


def post(body):
    return ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments", "-f", f"body={body}"]


def patch(cid, body):
    return ["api", "-X", "PATCH", f"repos/{SLUG}/issues/comments/{cid}", "-f", f"body={body}"]


def common(command, holder=ME):
    return [command, "--repo", SLUG, "--issue", str(ISSUE), "--holder", holder]


def run(*argv):
    """In-process: policy and clock rows."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = forge_claim.main(list(argv))
    return code, json.loads(out.getvalue())


def start_cli(*argv):
    """A child `python -m agent_tools.forge_claim` in the current (fake) world."""
    return subprocess.Popen([sys.executable, "-m", "agent_tools.forge_claim", *argv], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=dict(os.environ))


def finish(proc):
    stdout, _ = proc.communicate(timeout=120)
    lines = stdout.splitlines()
    assert len(lines) == 1, stdout  # exactly one JSON object, one line (D8)
    return proc.returncode, json.loads(lines[0])


def run_cli(*argv):
    return finish(start_cli(*argv))


class Base(unittest.TestCase):
    def setUp(self):
        self.fresh_world()

    def fresh_world(self):
        self.world = ForgeWorld(self)
        for argv in (ENSURE, ADD, REMOVE, OA_ENSURE, OA_ADD, OA_REMOVE):
            self.world.respond("gh", argv)

    def store(self, *comments, next_id=40, schedule=()):
        self.world.comment_store(SLUG, ISSUE, list(comments), next_id=next_id, schedule=schedule)

    def mutations(self):
        return [argv for argv in self.world.argvs("gh") if "-X" in argv]

    def live(self, kind="claim"):
        markers = [m for m in (fm.parse(c) for c in self.world.stored()) if m]
        return [m for m in markers if m.kind == kind and fm.is_live(m, markers)]


class AcquireTest(Base):
    def test_free_issue_is_acquired_and_labelled(self):
        self.store(next_id=11)
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["comment_id"], out["by"]), (0, "acquired", 11, None))
        self.assertEqual(self.mutations(), [post(claim_body(ME)), ENSURE, ADD])
        self.assertEqual([m.fields["holder"] for m in self.live()], [ME])

    def test_branch_is_recorded(self):
        self.store(next_id=11)
        code, out = run(*common("acquire"), "--branch", "issue-7-x")
        self.assertEqual((code, out["verdict"]), (0, "acquired"))
        self.assertEqual(self.live()[0].fields["branch"], "issue-7-x")

    def test_own_claim_resumes(self):
        self.store(comment(5, claim_body(ME)))
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_held", 5))
        self.assertEqual(self.mutations(), [ENSURE, ADD])

    def test_other_claim_is_held_by_and_untouched(self):
        self.store(comment(5, claim_body(OTHER)))
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["by"]), (3, "held_by", OTHER))
        self.assertEqual(self.mutations(), [])

    def test_forge_error_is_exit_1(self):
        self.world.respond("gh", LIST, exit=1, stderr="gh: Server Error (HTTP 500)")
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "gh_failed"))

    def test_usage_errors_are_json_exit_2(self):
        for argv in (common("acquire", holder="no-slash"), ["steal", "--repo", SLUG], []):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    code, out = run(*argv)
                self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "usage"))
                self.assertTrue(out["detail"])
        self.assertEqual(self.world.argvs("gh"), [])


class CliTest(Base):
    """`python -m agent_tools.forge_claim` as a child process (docs/standards/agent-helpers.md rule 5)."""

    def test_acquire_exit_0_one_json_line(self):
        self.store(next_id=11)
        code, out = run_cli(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "acquired", 11))

    def test_held_by_exit_3(self):
        self.store(comment(5, claim_body(OTHER)))
        code, out = run_cli(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["by"]), (3, "held_by", OTHER))

    def test_forge_error_exit_1(self):
        self.world.respond("gh", LIST, exit=1, stderr="gh: Server Error (HTTP 500)")
        code, out = run_cli(*common("acquire"))
        self.assertEqual((code, out["error"]), (1, "gh_failed"))

    def test_usage_error_exit_2(self):
        code, out = run_cli(*common("acquire", holder="no-slash"))
        self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "usage"))

    def test_racing_acquires_leave_one_claim(self):
        self.store(next_id=101, schedule=["list", "list", f"post:holder={ME}", f"post:holder={OTHER}",
                                          "list", "list"])
        mine, theirs = start_cli(*common("acquire")), start_cli(*common("acquire", holder=OTHER))
        (my_code, my_out), (their_code, their_out) = finish(mine), finish(theirs)
        self.assertEqual((my_code, my_out["verdict"], my_out["comment_id"]), (0, "acquired", 101))
        self.assertEqual((their_code, their_out["verdict"], their_out["by"]), (3, "lost_to", ME))
        self.assertEqual([m.fields["holder"] for m in self.live()], [ME])
        self.assertNotIn(102, [c["id"] for c in self.world.stored()])


class ReleaseRenewTest(Base):
    def test_renew_edits_the_same_comment(self):
        for before, after in (({}, "1"), ({"renewed": "1"}, "2")):
            with self.subTest(before=before):
                self.fresh_world()
                self.store(comment(5, claim_body(ME, **before)))
                code, out = run(*common("renew"))
                self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "renewed", 5))
                self.assertEqual(self.mutations(), [patch(5, claim_body(ME, renewed=after))])
                self.assertEqual([c["id"] for c in self.world.stored()], [5])

    def test_renew_by_another_holder_is_not_held(self):
        self.store(comment(5, claim_body(OTHER)))
        code, out = run(*common("renew"))
        self.assertEqual((code, out["verdict"], out["by"]), (3, "not_held", OTHER))
        self.assertEqual(self.mutations(), [])

    def test_renew_retires_the_owner_action_on_its_claim(self):
        self.store(comment(5, claim_body(ME)), comment(30, oa_body(5, ME)))
        code, out = run(*common("renew"))
        self.assertEqual((code, out["verdict"]), (0, "renewed"))
        self.assertEqual(self.mutations(), [patch(5, claim_body(ME, renewed="1")),
                                            post(fm.end_body(30, "renewed")), OA_REMOVE])
        self.assertEqual(self.live("owner-action"), [])

    def test_release_removes_the_label_when_no_live_claim_remains(self):
        self.store(comment(5, claim_body(ME)))
        code, out = run(*common("release"))
        self.assertEqual((code, out["verdict"], out["comment_id"], out["label_removed"]),
                         (0, "released", 5, True))
        self.assertEqual(self.mutations(), [post(fm.end_body(5, "done")),
                                            patch(5, claim_body(ME, released="done")), REMOVE])
        self.assertEqual(self.live(), [])

    def test_release_keeps_the_label_while_another_live_claim_remains(self):
        self.store(comment(5, claim_body(ME)), comment(9, claim_body(OTHER)))
        code, out = run(*common("release"), "--reason", "merged")
        self.assertEqual((code, out["verdict"], out["label_removed"]), (0, "released", False))
        self.assertEqual(self.mutations(), [post(fm.end_body(5, "merged")),
                                            patch(5, claim_body(ME, released="merged"))])

    def test_release_retires_the_owner_action_and_its_label(self):
        self.store(comment(5, claim_body(ME)), comment(30, oa_body(5, ME)))
        code, out = run(*common("release"))
        self.assertEqual((code, out["verdict"]), (0, "released"))
        self.assertEqual(self.mutations(), [post(fm.end_body(5, "done")), patch(5, claim_body(ME, released="done")),
                                            post(fm.end_body(30, "released")), OA_REMOVE, REMOVE])
        self.assertEqual(self.live("owner-action"), [])

    def test_release_without_a_claim_is_not_held(self):
        self.store()
        code, out = run(*common("release"))
        self.assertEqual((code, out["verdict"]), (3, "not_held"))
        self.assertEqual(self.mutations(), [])

    def test_a_delayed_renewal_cannot_revive_a_released_claim(self):
        # renew reads claim 5; release ends it; OTHER acquires; only then does renew's PATCH land.
        self.store(comment(5, claim_body(ME)),
                   schedule=["list", "post:agent:end v1 of=5 ", f"post:holder={OTHER}", "patch:5:renewed=1"])
        renewal = start_cli(*common("renew"))
        self.world.wait_cursor(1)
        code, out = run_cli(*common("release"))
        self.assertEqual((code, out["verdict"]), (0, "released"))
        code, out = run_cli(*common("acquire", holder=OTHER))
        self.assertEqual((code, out["verdict"]), (0, "acquired"))
        code, out = finish(renewal)
        self.assertEqual((code, out["verdict"], out["comment_id"]), (3, "not_held", 5))
        claim5 = next(c["body"] for c in self.world.stored() if c["id"] == 5)
        self.assertEqual(claim5, claim_body(ME, renewed="1"))  # the stale PATCH dropped `released` ...
        self.assertEqual([m.fields["holder"] for m in self.live()], [OTHER])  # ... and the end still holds


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `bash -o pipefail -c 'env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_claim.py 2>&1 | tail -5'`
Expected: non-zero exit — `ImportError: cannot import name 'forge_claim'`.

- [ ] **Step 3: Write the implementation**

`python/agent_tools/forge_claim.py` per Interfaces and Invariants, with a module docstring naming issue 623, D2, D3, D7, D8, D9, D10. Each subcommand is one function `(args) -> tuple[int, dict]`; `main` parses `argv` (an explicit `[]` is parsed as given; only `None` reads `sys.argv`), catching `UsageError` from the parser or its subparsers (argparse builds subparsers with the parent's class, so the overridden `error` applies) into the usage object with `command` = the first argv item when it names a subcommand, else null, exit 2; dispatches through a `{name: function}` table (Task 3 adds `status`), catches `forge_markers.ForgeError` into the error object, prints the one line once, returns the code. `-h`/`--help` keeps argparse's help-and-exit-0 behaviour (D8).

- [ ] **Step 4: Verify**

Run: `bash -o pipefail -c 'env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_claim.py tests/test_forge_markers.py 2>&1 | tail -5'`
Expected: exit 0, `OK`, 34 tests, no skips.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/forge_claim.py tests/test_forge_claim.py
git commit -m "feat(issue-623): forge-claim acquire, renew and release

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
