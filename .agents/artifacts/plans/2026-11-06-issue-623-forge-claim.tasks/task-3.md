# Task 3: `forge-claim status`, staleness by server time, owner-action release box

**Files:**
- Modify: `python/agent_tools/forge_claim.py`
- Test: `tests/test_forge_claim.py`

**Interfaces:**
- Consumes: Task 1 `agent_tools.forge_markers` (`server_now()`, `latest_push(slug, branch)`, `latest_pr_event(slug, branch)`, `write`, `edit`, `with_fields`, `contest`, `list_markers`, `ensure_label`, `add_label`, `remove_label`, `ForgeError`); Task 2 `forge_claim` (`main`, the subcommand table, the claim marker, the output object, `IN_PROGRESS`) and the helpers of `tests/test_forge_claim.py` (`Base`, `run`, `common`, `claim_body`, `comment`, `listing`, `patch`, `post`, `LIST`, `ENSURE`, `ADD`, `REMOVE`, `ME`, `OTHER`). Extra fake argv: now `["api", "--include", "rate_limit"]`; push `["api", "repos/<slug>/activity?ref=refs/heads/<branch>&activity_type=push&per_page=1"]`; PRs `["api", "repos/<slug>/pulls?state=all&head=<owner>:<branch>&per_page=100"]`.
- Produces:
  - Subcommand `status` with `--repo`, `--issue`, `--holder` (the caller, reported, never compared).
  - Constants `STALE_AFTER = timedelta(hours=24)`, `OWNER_ACTION = ("owner-action", "D93F0B")`, `RELEASE_BOX = "Release this claim"`.
  - Owner-action marker (D6): `render("owner-action", {"issue": str(n), "reason": "stale-claim", "claim": str(claim_id)}, f"The claim of {holder} has had no renewal, push or pull request activity for 24 hours.", f"- [ ] {RELEASE_BOX}")`; contest match: all three fields.
  - Output additions: `status` and `acquire` objects gain `released_by_owner` (ascending claim ids released by ticked boxes in this call); `status` also `activity_at` (ISO-8601 `Z` string or null), `owner_action_comment_id` (int or null), `owner_action_posted` (bool).
  - `honour_ticks(slug, issue, markers) -> tuple[list[Marker], list[int]]`.

**Invariants:**
- `honour_ticks`: for each live `owner-action` marker with `reason=stale-claim` and this issue whose body has a line matching `^\s*[-*] \[[xX]\] Release this claim\s*$`: PATCH the claim it names (when still live) with `released=owner-action`, then PATCH the marker with `resolved=released`. When any was honoured: re-list; `remove_label(in-progress)` when no live claim remains; `remove_label(owner-action)` when no live `owner-action` marker of this issue remains. `acquire` and `status` both run it first, on their first listing.
- `status`: no live claim → `free`, exit 0, no `rate_limit` read. Else, on the winner: activity = max(winner `updated_at`, `latest_push`, `latest_pr_event`), the last two read only when the claim has a `branch` field; now = `server_now()`. `now - activity >= STALE_AFTER` → `stale`, else `held_by`; both exit 0, `by` = the winner's holder.
- `stale`: an existing live owner-action for this claim → report its id, no post, no label call. None → `write` it; `owner_action_posted` = `won`; on `won`, `ensure_label` and `add_label` of `owner-action`. Never edits, releases or deletes the claim (stale is never stolen).
- `acquire` against a stale claim with an unticked box still returns `held_by`, exit 3.
- Verdicts do not depend on the host clock: the rows below pass with `time.time` patched to 0 and to 4102444800.0.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_forge_claim.py` (before the `__main__` guard); add `from datetime import datetime, timezone` and `from pathlib import Path` and `from unittest import mock` to its imports.

```python
NOW = ["api", "--include", "rate_limit"]
PUSH = ["api", f"repos/{SLUG}/activity?ref=refs/heads/topic&activity_type=push&per_page=1"]
PRS = ["api", f"repos/{SLUG}/pulls?state=all&head=octo:topic&per_page=100"]
OA_ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=owner-action", "-f", "color=D93F0B"]
OA_ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=owner-action"]
OA_REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/owner-action"]
WRONG_CLOCKS = (0.0, 4102444800.0)


def oa_body(claim_id, holder, ticked=False, **extra):
    return fm.render("owner-action", {"issue": str(ISSUE), "reason": "stale-claim", "claim": str(claim_id), **extra},
                     f"The claim of {holder} has had no renewal, push or pull request activity for 24 hours.",
                     f"- [{'x' if ticked else ' '}] Release this claim")


class StatusTest(Base):
    def setUp(self):
        super().setUp()
        for argv in (OA_ENSURE, OA_ADD, OA_REMOVE):
            self.world.respond("gh", argv)
        self.world.respond("gh", NOW, stdout="HTTP/2.0 200 OK\nDate: Fri, 06 Nov 2026 10:00:00 GMT\n\n{}")

    def status(self, clock):
        with mock.patch("time.time", return_value=clock):
            return run(*common("status"))

    def test_free(self):
        self.world.respond_json("gh", LIST, [[]])
        code, out = run(*common("status"))
        self.assertEqual((code, out["verdict"]), (0, "free"))
        self.assertNotIn(NOW, self.world.argvs("gh"))

    def test_fresh_claim_is_held_by_whatever_the_host_clock(self):
        self.world.respond_json("gh", LIST, [[comment(5, claim_body(OTHER), "2026-11-05T10:00:01Z")]])
        for clock in WRONG_CLOCKS:
            code, out = self.status(clock)
            self.assertEqual((code, out["verdict"], out["by"]), (0, "held_by", OTHER))
        self.assertEqual(self.mutations(), [])

    def test_branch_push_or_pr_event_keeps_a_claim_fresh(self):
        old = comment(5, claim_body(OTHER, branch="topic"), "2026-11-01T00:00:00Z")
        for push, prs in (([{"timestamp": "2026-11-06T09:00:00Z"}], []),
                          ([], [{"updated_at": "2026-11-06T09:00:00Z"}])):
            with self.subTest(push=push, prs=prs):
                self.world.respond_json("gh", LIST, [[old]])
                self.world.respond_json("gh", PUSH, push)
                self.world.respond_json("gh", PRS, prs)
                code, out = self.status(0.0)
                self.assertEqual((out["verdict"], out["activity_at"]), ("held_by", "2026-11-06T09:00:00Z"))

    def test_stale_posts_one_owner_action_across_repeat_calls(self):
        stale = comment(5, claim_body(OTHER), "2026-11-05T10:00:00Z")
        mine = oa_body(5, OTHER)
        self.world.respond_json("gh", post(mine), comment(30, mine))
        self.world.respond_sequence("gh", LIST, [listing(stale), listing(stale, comment(30, mine))])
        for clock in WRONG_CLOCKS:
            code, out = self.status(clock)
            self.assertEqual((code, out["verdict"], out["by"], out["owner_action_comment_id"]),
                             (0, "stale", OTHER, 30))
        posts = [argv for argv in self.world.argvs("gh") if argv[:3] == ["api", "-X", "POST"]
                 and argv[3].endswith("/comments")]
        self.assertEqual(posts, [post(mine)])
        self.assertEqual(self.mutations().count(OA_ADD), 1)
        self.assertFalse(any("PATCH" in argv or "DELETE" in argv for argv in self.mutations()))

    def test_acquire_against_an_unticked_stale_claim_is_held_by(self):
        self.world.respond_json("gh", LIST, [[comment(5, claim_body(OTHER), "2026-10-01T00:00:00Z"),
                                              comment(30, oa_body(5, OTHER))]])
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["by"]), (3, "held_by", OTHER))
        self.assertEqual(self.mutations(), [])

    def test_ticked_box_releases_and_acquire_proceeds(self):
        claim, box = claim_body(OTHER), oa_body(5, OTHER, ticked=True)
        released = claim_body(OTHER, released="owner-action")
        resolved = fm.with_fields(fm.parse(comment(30, box)), resolved="released")
        mine = claim_body(ME)
        for argv in (patch(5, released), patch(30, resolved)):
            self.world.respond("gh", argv)
        self.world.respond_json("gh", post(mine), comment(31, mine))
        after = [comment(5, released), comment(30, resolved)]
        self.world.respond_sequence("gh", LIST, [listing(comment(5, claim), comment(30, box)),
                                                 listing(*after), listing(*after, comment(31, mine))])
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["released_by_owner"]), (0, "acquired", [5]))
        self.assertEqual(self.mutations()[:4], [patch(5, released), patch(30, resolved), REMOVE, OA_REMOVE])

    def test_ticked_box_makes_status_free(self):
        claim, box = claim_body(OTHER), oa_body(5, OTHER, ticked=True)
        released = claim_body(OTHER, released="owner-action")
        resolved = fm.with_fields(fm.parse(comment(30, box)), resolved="released")
        for argv in (patch(5, released), patch(30, resolved)):
            self.world.respond("gh", argv)
        self.world.respond_sequence("gh", LIST, [listing(comment(5, claim), comment(30, box)),
                                                 listing(comment(5, released), comment(30, resolved))])
        code, out = run(*common("status"))
        self.assertEqual((code, out["verdict"], out["released_by_owner"]), (0, "free", [5]))


class NoHostClockTest(unittest.TestCase):
    def test_cli_reads_no_host_clock(self):
        source = Path(forge_claim.__file__).read_text("utf-8")
        for spelling in ("time.time", ".now(", "utcnow", "date.today", "localtime"):
            self.assertNotIn(spelling, source)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_claim.py 2>&1 | tail -5`
Expected: FAIL — `status` is an invalid argparse choice (SystemExit 2) and the ticked-box acquire row reports `held_by`.

- [ ] **Step 3: Write the implementation**

Add `status` and `honour_ticks` to `python/agent_tools/forge_claim.py` per Interfaces and Invariants; call `honour_ticks` at the top of `acquire` on its first listing and use the returned markers. Docstring gains D4, D5, D6. `activity_at` is `activity.strftime("%Y-%m-%dT%H:%M:%SZ")`.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_claim.py tests/test_forge_markers.py 2>&1 | tail -5`
Expected: `OK`, 33 tests, no skips.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/forge_claim.py tests/test_forge_claim.py
git commit -m "feat(issue-623): forge-claim status reports stale claims without stealing them

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
