# Task 3: `forge-claim status`, staleness by server time, owner-action release box

**Files:**
- Modify: `python/agent_tools/forge_claim.py`
- Test: `tests/test_forge_claim.py`

**Interfaces:**
- Consumes: Task 1 `agent_tools.forge_markers` (`server_now()`, `latest_push(slug, branch)`, `latest_pr_event(slug, branch)`, `write`, `end`, `end_body`, `edit`, `with_fields`, `is_live`, `contest`, `list_markers`, `ensure_label`, `add_label`, `remove_label`, `ForgeError`) and `tests/forge_world.py` `host_clock(instant, *modules)`, `ForgeWorld.comment_store`/`stored`/`wait_cursor`; Task 2 `forge_claim` (`main`, the subcommand table, the claim marker, the output object, `IN_PROGRESS`, `OWNER_ACTION`, `OWNER_ACTION_KIND`, `retire_owner_actions`) and the helpers of `tests/test_forge_claim.py` (`Base` with `fresh_world`, `store`, `mutations`, `live`; `run`, `start_cli`, `finish`, `run_cli`, `common`, `claim_body`, `oa_body`, `comment`, `post`, `patch`, `ENSURE`, `ADD`, `REMOVE`, `OA_ENSURE`, `OA_ADD`, `OA_REMOVE`, `ME`, `OTHER`, `SLUG`, `ISSUE`). Extra fake argv: now `["api", "--include", "rate_limit"]`; push `["api", "repos/<slug>/activity?ref=refs/heads/<branch>&activity_type=push&per_page=1"]`; PRs `["api", "repos/<slug>/pulls?state=all&head=<owner>:<branch>&per_page=100"]`.
- Produces:
  - Subcommand `status` with `--repo`, `--issue`, `--holder` (the caller, reported, never compared).
  - Constants `STALE_AFTER = timedelta(hours=24)`, `RELEASE_BOX = "Release this claim"`.
  - Owner-action marker (D6): `render("owner-action", {"issue": str(n), "reason": "stale-claim", "claim": str(claim_id)}, f"The claim of {holder} has had no renewal, push or pull request activity for 24 hours.", f"- [ ] {RELEASE_BOX}")`; contest match: all three fields.
  - `activity_at(slug: str, claim: Marker) -> datetime` — max of `claim.updated_at`, and, only when the claim has a `branch` field, `latest_push` and `latest_pr_event` (D4).
  - `is_stale(activity: datetime, now: datetime) -> bool` — `now - activity >= STALE_AFTER` (D5).
  - `honour_ticks(slug: str, issue: int, markers: list[Marker]) -> tuple[list[Marker], list[int]]` — the markers to continue with and the claim ids released, ascending.
  - `retire_obsolete(slug: str, issue: int, markers: list[Marker], keep: int | None) -> list[int]` (D10) — ends every live `owner-action` of the issue whose `claim` is not `str(keep)`: reason `renewed` when that claim is live in `markers`, else `released`; when it ended at least one and no live `owner-action` remains, `remove_label(owner-action)`. Returns the ended ids.
  - Output additions: `status` and `acquire` objects gain `released_by_owner` (list of int, always present); `status` also `activity_at` (`activity.strftime("%Y-%m-%dT%H:%M:%SZ")` or null), `owner_action_comment_id` (int or null), `owner_action_posted` (bool).

**Invariants:**
- `honour_ticks` (D6): `server_now()` is read at most once per call and only when a ticked box exists. For each live `owner-action` of this issue with `reason=stale-claim` whose body has a line matching `^\s*[-*] \[[xX]\] Release this claim\s*$`, in ascending id: let `claim` be the marker whose id is its `claim` field. Claim live and `is_stale(activity_at(slug, claim), now)` → `end(claim, "owner-action")`, `edit(claim id, with_fields(claim, released="owner-action"))`, `end(marker, "released")`, record the claim id. Claim live and not stale → `end(marker, "renewed")`, nothing else. Claim missing or not live → `end(marker, "released")`. When it ended anything: re-list; `remove_label(in-progress)` when it released a claim and no live claim remains; then `remove_label(owner-action)` when no live `owner-action` of the issue remains; return the re-list. `acquire` and `status` both run it first, on their first listing.
- `status`: no live claim → `free`, `retire_obsolete(keep=None)`, exit 0, no `rate_limit` read. Else on the contest winner: activity = `activity_at`, now = `server_now()`; not stale → `held_by`, `retire_obsolete(keep=None)`; stale → `stale`, `retire_obsolete(keep=winner id)`; both exit 0, `by` = the winner's holder, `comment_id` = the winner's id.
- `stale`: a live owner-action for this claim → report its id, `owner_action_posted: false`, no post. None → `write` it; `owner_action_posted` = `won`; the id is own when won, else the winner's. Then, on every `stale` call, `ensure_label` and `add_label` of `owner-action` (D6: repairs a label call that failed after the post). Never ends, edits or deletes the claim (stale is never stolen).
- `acquire` against a stale claim with an unticked box still returns `held_by`, exit 3, no mutation.
- Verdicts do not depend on the host clock: the rows marked so pass identically under `host_clock` at 1970-01-01 and 2100-01-01 UTC, patched on both modules.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_forge_claim.py` (before the `__main__` guard); add `from datetime import datetime, timezone` and `from pathlib import Path` to its imports and change the world import to `from .forge_world import ForgeWorld, host_clock`.

```python
NOW = ["api", "--include", "rate_limit"]
PUSH = ["api", f"repos/{SLUG}/activity?ref=refs/heads/topic&activity_type=push&per_page=1"]
PRS = ["api", f"repos/{SLUG}/pulls?state=all&head=octo:topic&per_page=100"]
WRONG_CLOCKS = (datetime(1970, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc))
OLD = "2026-11-01T00:00:00Z"  # server now is 2026-11-06T10:00:00Z


class StatusTest(Base):
    def fresh_world(self):
        super().fresh_world()
        self.world.respond("gh", NOW, stdout="HTTP/2.0 200 OK\nDate: Fri, 06 Nov 2026 10:00:00 GMT\n\n{}")

    def under_wrong_clocks(self, *argv):
        results = []
        for instant in WRONG_CLOCKS:
            with host_clock(instant, forge_claim, fm):
                results.append(run(*argv))
        return results

    def comment_posts(self):
        return [a for a in self.world.argvs("gh")
                if a[:4] == ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments"]]

    def test_the_clock_seam_reaches_both_modules(self):
        for instant in WRONG_CLOCKS:
            with host_clock(instant, forge_claim, fm):
                self.assertEqual(forge_claim.datetime.now(timezone.utc), instant)
                self.assertEqual(fm.datetime.now(timezone.utc), instant)

    def test_free(self):
        self.store()
        for code, out in self.under_wrong_clocks(*common("status")):
            self.assertEqual((code, out["verdict"], out["released_by_owner"]), (0, "free", []))
        self.assertNotIn(NOW, self.world.argvs("gh"))

    def test_fresh_claim_is_held_by_whatever_the_host_clock(self):
        self.store(comment(5, claim_body(OTHER), "2026-11-05T10:00:01Z"))
        for code, out in self.under_wrong_clocks(*common("status")):
            self.assertEqual((code, out["verdict"], out["by"], out["comment_id"]), (0, "held_by", OTHER, 5))
        self.assertEqual(self.mutations(), [])

    def test_branch_push_or_pr_event_keeps_a_claim_fresh(self):
        for push, prs in (([{"timestamp": "2026-11-06T09:00:00Z"}], []),
                          ([], [{"updated_at": "2026-11-06T09:00:00Z"}])):
            with self.subTest(push=push, prs=prs):
                self.fresh_world()
                self.store(comment(5, claim_body(OTHER, branch="topic"), OLD))
                self.world.respond_json("gh", PUSH, push)
                self.world.respond_json("gh", PRS, prs)
                for code, out in self.under_wrong_clocks(*common("status")):
                    self.assertEqual((code, out["verdict"], out["activity_at"]),
                                     (0, "held_by", "2026-11-06T09:00:00Z"))

    def test_stale_posts_one_owner_action_across_repeat_calls(self):
        self.store(comment(5, claim_body(OTHER), "2026-11-05T10:00:00Z"), next_id=30)
        results = self.under_wrong_clocks(*common("status"))
        self.assertEqual([(c, o["verdict"], o["by"], o["owner_action_comment_id"], o["owner_action_posted"])
                          for c, o in results],
                         [(0, "stale", OTHER, 30, True), (0, "stale", OTHER, 30, False)])
        self.assertEqual(self.comment_posts(), [post(oa_body(5, OTHER))])
        self.assertEqual(self.mutations().count(OA_ADD), 2)  # reconciled on every stale call (D6)
        self.assertFalse(any("PATCH" in a or "DELETE" in a for a in self.mutations()))
        self.assertEqual([m.fields["holder"] for m in self.live()], [OTHER])

    def test_a_failed_label_call_is_repaired_without_a_second_marker(self):
        self.store(comment(5, claim_body(OTHER), OLD), next_id=30)
        self.world.respond("gh", OA_ADD, exit=1, stderr="gh: Server Error (HTTP 500)")
        code, out = run(*common("status"))
        self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "gh_failed"))
        self.world.respond("gh", OA_ADD)
        code, out = run(*common("status"))
        self.assertEqual((code, out["verdict"], out["owner_action_comment_id"], out["owner_action_posted"]),
                         (0, "stale", 30, False))
        self.assertEqual(self.comment_posts(), [post(oa_body(5, OTHER))])
        self.assertEqual(self.mutations().count(OA_ADD), 2)

    def test_a_fresh_claim_retires_an_obsolete_owner_action(self):
        self.store(comment(5, claim_body(OTHER, renewed="1")), comment(30, oa_body(5, OTHER)))
        code, out = run(*common("status"))
        self.assertEqual((code, out["verdict"]), (0, "held_by"))
        self.assertEqual(self.mutations(), [post(fm.end_body(30, "renewed")), OA_REMOVE])

    def test_a_tick_after_the_holder_renewed_releases_nothing(self):
        self.store(comment(5, claim_body(OTHER), OLD), next_id=30)
        self.assertEqual(run(*common("status"))[1]["verdict"], "stale")
        self.assertEqual(run(*common("renew", holder=OTHER))[1]["verdict"], "renewed")  # ends marker 30
        fm.edit(SLUG, 30, oa_body(5, OTHER, ticked=True))  # the owner ticks the old box afterwards
        code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["by"], out["released_by_owner"]), (3, "held_by", OTHER, []))
        self.assertEqual(self.mutations()[-1], patch(30, oa_body(5, OTHER, ticked=True)))  # acquire mutated nothing
        self.assertEqual([m.fields["holder"] for m in self.live()], [OTHER])
        self.assertEqual(self.live("owner-action"), [])

    def test_a_tick_on_a_claim_that_is_no_longer_stale_releases_nothing(self):
        self.store(comment(5, claim_body(OTHER, branch="topic"), OLD), comment(30, oa_body(5, OTHER, ticked=True)))
        self.world.respond_json("gh", PUSH, [{"timestamp": "2026-11-06T09:00:00Z"}])
        self.world.respond_json("gh", PRS, [])
        with host_clock(WRONG_CLOCKS[1], forge_claim, fm):
            code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["released_by_owner"]), (3, "held_by", []))
        self.assertEqual(self.mutations(), [post(fm.end_body(30, "renewed")), OA_REMOVE])
        self.assertEqual([m.fields["holder"] for m in self.live()], [OTHER])

    def test_acquire_against_an_unticked_stale_claim_is_held_by(self):
        self.store(comment(5, claim_body(OTHER), "2026-10-01T00:00:00Z"), comment(30, oa_body(5, OTHER)))
        for code, out in self.under_wrong_clocks(*common("acquire")):
            self.assertEqual((code, out["verdict"], out["by"]), (3, "held_by", OTHER))
        self.assertEqual(self.mutations(), [])

    def test_ticked_box_releases_and_acquire_proceeds(self):
        self.store(comment(5, claim_body(OTHER), OLD), comment(30, oa_body(5, OTHER, ticked=True)))
        with host_clock(WRONG_CLOCKS[0], forge_claim, fm):
            code, out = run(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["comment_id"], out["released_by_owner"]),
                         (0, "acquired", 42, [5]))
        self.assertEqual(self.mutations(), [
            post(fm.end_body(5, "owner-action")), patch(5, claim_body(OTHER, released="owner-action")),
            post(fm.end_body(30, "released")), REMOVE, OA_REMOVE, post(claim_body(ME)), ENSURE, ADD])
        self.assertEqual([m.fields["holder"] for m in self.live()], [ME])

    def test_ticked_box_makes_status_free(self):
        self.store(comment(5, claim_body(OTHER), OLD), comment(30, oa_body(5, OTHER, ticked=True)))
        code, out = run(*common("status"))
        self.assertEqual((code, out["verdict"], out["released_by_owner"]), (0, "free", [5]))
        self.assertEqual(self.live(), [])

    def test_a_delayed_renewal_cannot_revive_a_claim_released_by_the_box(self):
        # OTHER's renew reads claim 5; ME's acquire honours the tick and acquires; then the PATCH lands.
        self.store(comment(5, claim_body(OTHER), OLD), comment(30, oa_body(5, OTHER, ticked=True)),
                   schedule=["list", "post:agent:end v1 of=5 ", f"post:holder={ME}", "patch:5:renewed=1"])
        renewal = start_cli(*common("renew", holder=OTHER))
        self.world.wait_cursor(1)
        code, out = run_cli(*common("acquire"))
        self.assertEqual((code, out["verdict"], out["released_by_owner"]), (0, "acquired", [5]))
        code, out = finish(renewal)
        self.assertEqual((code, out["verdict"], out["comment_id"]), (3, "not_held", 5))
        self.assertEqual([m.fields["holder"] for m in self.live()], [ME])


class NoHostClockTest(unittest.TestCase):
    def test_cli_reads_no_host_clock(self):
        source = Path(forge_claim.__file__).read_text("utf-8")
        for spelling in ("time.time", ".now(", "utcnow", "date.today", "localtime"):
            self.assertNotIn(spelling, source)
        self.assertIn("from datetime import datetime", source)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `bash -o pipefail -c 'env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_claim.py 2>&1 | tail -5'`
Expected: non-zero exit — the `status` rows report `verdict: "error", error: "usage"` (unknown subcommand) and the ticked-box acquire rows report `held_by`.

- [ ] **Step 3: Write the implementation**

Add `status`, `activity_at`, `is_stale`, `honour_ticks` and `retire_obsolete` to `python/agent_tools/forge_claim.py` per Interfaces and Invariants; call `honour_ticks` at the top of `acquire` on its first listing and use the returned markers; add `released_by_owner` to every `acquire` object. The module binds `datetime` and `timedelta` by `from datetime import datetime, timedelta, timezone` (so `host_clock` reaches it). Docstring gains D4, D5, D6 and D10's residual window.

- [ ] **Step 4: Verify**

Run: `bash -o pipefail -c 'env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_claim.py tests/test_forge_markers.py 2>&1 | tail -5'`
Expected: exit 0, `OK`, 48 tests, no skips.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/forge_claim.py tests/test_forge_claim.py
git commit -m "feat(issue-623): forge-claim status reports stale claims without stealing them

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
