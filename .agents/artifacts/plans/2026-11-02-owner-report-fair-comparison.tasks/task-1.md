# Task 1: Lineage project and start

Spec § Lineage start, settle and report end (*Start*), § Project, § Document (lineage rows) and § Test seams (*Fixture*). Rests on D2, D4, D11 and D13. After this task every lineage row carries its `project` and its `started` instant, and the test fixture writes production-shaped `cwd`s and takes a `--repo-root` value.

**Files:**
- Modify: `python/agent_tools/transcript_calls.py`
- Modify: `python/agent_tools/agent_owner_report.py`
- Modify: `tests/owner_transcripts.py`
- Test: `tests/test_agent_owner_report.py`
- Modify: `python/README.md`

**Interfaces:**
- Consumes (present at base): `agent_costs.repo_root(cwd)` (trims a path at its first dot directory), `agent_costs.project_name(dir_name, root_cwds)` (a `Counter` of cwds, else the directory-name rule), `agent_costs.format_rfc3339_utc(datetime)`. In `agent_owner_report`: `_CallRead`, `_read_invocation`, `scan_owner_transcript`, `_owner_scan`, `_lineage`, `_lineages`, `_lineage_row`, `_launch_order`, `Lineage`, and `collect`'s `homes` (maps `str(path)` to the session's project directory name).
- Produces:
  - `transcript_calls.Transcript.cwds: collections.Counter`, a new last field with `field(default_factory=Counter)`. It counts the string `cwd` of every record `read_transcript` parses.
  - `owner_transcripts.Session(root, project="-Users-me-repo", session="s1", cwd="/Users/me/repo")` stamps `"cwd": self.cwd` on every record that `call`, `result`, `skill_body` and `measured` write, and on no `shape`, `blob` or `request` record (D13).
  - `owner_transcripts.progress(phase, *, action_id="7:1:1", handoff=None, absolute=False, repo_root="/Users/me/repo")`, whose `--repo-root` word is `repo_root` verbatim.
  - Scan key `"first_start"`: epoch seconds of the earliest `call.start` among all the transcript's calls, or `None`. Owner-dict keys `"repo_root"` and `"cwds"` (below).
  - `_lineages(scans, homes)` and `_lineage(run_id, issue, group, child_ends, homes)`.
  - `Lineage.started: float | None = None`, a new last field holding epoch seconds.
  - `_instant(epoch: float | None) -> str | None`, which is `format_rfc3339_utc(datetime.fromtimestamp(epoch, timezone.utc))`, or `None` for `None`. Task 4 reuses it.
  - Two lineage-row keys appended after `absolute_path_calls`, in this order: `"project"` (str) and `"started"` (`_instant` of `Lineage.started`).

**Invariants:**
- A registering invocation is a gate invocation (`sdd-gate`, or `workflow-state progress`/`mark-progress`) that carries `--run-id` and `--action-id`. Every one of them is read for `--repo-root`, not only the first that sets `registration`. A value qualifies when it is a `str` starting with `/`. `"$R"` lexes to `$R` and never qualifies.
- The owner dict's `"repo_root"` is the first qualifying value over the transcript's calls in order, else `None`. Its `"cwds"` is the transcript's `Transcript.cwds`.
- Project (D4, D13): walk the lineage's launches in their sorted `_launch_order`. The first launch whose owner has a `repo_root` gives `os.path.basename(agent_costs.repo_root(value))`. With none, the project is `agent_costs.project_name(homes[<first launch's transcript path>], <the sum of every launch's owner cwds>)`.
- `Lineage.started` is the minimum `first_start` over the group's owner transcripts (`scan is owner_scan`), including any with no counted call, over the owner transcripts the report read (per D14). Start mode reads every transcript (D1), so there it is the lineage's true start. With an event window `collect` still passes the event start as the mtime cutoff, which can drop an earlier launch's transcript, so in event mode `started` is the earliest read owner transcript's start and may be later than the true start; the row is informational there and selects nothing.
- Eval trial rows get `project` and `started` from their first lineage, through `_merge_trial`'s existing `dict(first.facts)`; `_merge_trial` does not change.
- `SCHEMA_VERSION` stays 1; Task 7 moves it.

- [ ] **Step 1: Extend the fixture and write the failing tests**

In `tests/owner_transcripts.py`:
- `progress` gains the keyword `repo_root="/Users/me/repo"`. It replaces the literal `"/Users/me/repo"` after `"--repo-root"` in `words`.
- `Session.__init__` gains `cwd="/Users/me/repo"`, stored as `self.cwd`. Add `"cwd": self.cwd` to the record dicts in `call` (the assistant records), `result` and `skill_body` (user records) and `measured` (the attachment record). `shape`, `blob` and `request` stay as they are.

In `tests/test_agent_owner_report.py`, add these three methods to `OwnerReportTest` after `test_an_event_window_counts_only_the_calls_that_start_inside_it`:

```python
    def test_a_lineage_s_project_is_its_registering_repo_root_and_its_start_its_first_owner_call(self):
        # o1 registers against /Users/me/repo while its records sit in another repository's
        # worktree; the dispatching root is no owner, so the lineage starts at o1's first call,
        # with or without an event window that cuts that call
        session = Session(self.root, cwd="/Users/me/other/.worktrees/worktree-issue-7")
        dispatch = session.call(None, 0, context=10_000, write=10_000, ttl="1h", agent_tool=True)
        session.child("o1", tool_use_id=dispatch)
        session.call("o1", 10, context=20_000, write=20_000)
        g = session.call("o1", 20, context=30_000, write=10_000, bash=progress(3))
        session.result("o1", 21, g, gate_reply("continue"))
        session.write()
        for extra in ((), ("--events-since", at(15), "--events-before", at(1_000))):
            with self.subTest(extra=extra):
                [row] = report(self.root, *extra)["lineages"]
                self.assertEqual((row["project"], row["started"]), ("repo", "2026-10-25T09:00:10Z"))

    def test_an_unexpanded_repo_root_takes_the_project_of_the_records_cwd(self):
        session = Session(self.root, project="-Users-me-other--worktrees-worktree-issue-8",
                          cwd="/Users/me/other/.worktrees/worktree-issue-8")
        g = session.call(None, 0, context=20_000, write=20_000, ttl="1h",
                         bash=progress(3, action_id="8:1:1", repo_root='"$R"'))
        session.result(None, 5, g, gate_reply("continue", issue=8))
        session.write()
        [row] = report(self.root)["lineages"]
        self.assertEqual(row["project"], "other")

    def test_an_eval_trial_row_takes_the_project_and_start_of_its_first_lineage(self):
        # issue 9 starts first, but the trial's first lineage is issue 7 (lineages sort by issue)
        later = Session(self.root, project="-private-tmp-eval-from-issue-8-T1-repo", session="s1")
        g9 = later.call(None, 0, context=20_000, write=20_000, ttl="1h",
                        bash=progress(3, action_id="9:1:1", repo_root="/Users/me/zed"))
        later.result(None, 5, g9, gate_reply("continue", issue=9))
        later.write()
        first = Session(self.root, project="-private-tmp-eval-from-issue-8-T1-repo", session="s2")
        g7 = first.call(None, 30, context=20_000, write=20_000, ttl="1h", bash=progress(6))
        first.result(None, 35, g7, gate_reply("continue"))
        first.write()
        results = self.root / "results.jsonl"
        results.write_text(json.dumps({
            "skill": "from-issue", "id": 8, "trial": 1, "verdict": "PASS",
            "workdir": "/private/tmp/eval-from-issue-8.T1", "tree_rev": "a" * 40, "policy": None,
            "claude_exit": 0}) + "\n", encoding="utf-8")
        [row] = report(self.root, "--eval-results", str(results), "--eval", "from-issue:8")["lineages"]
        self.assertEqual((row["project"], row["started"]), ("repo", "2026-10-25T09:00:30Z"))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Owner tests command with `-k project` (timeout 300 s).
Expected: FAIL, `Ran 3 tests`: each of the new tests errors with `KeyError: 'project'`. A `TypeError` about `cwd` or `repo_root` means Step 1's fixture change is missing.

- [ ] **Step 3: Implement**

`python/agent_tools/transcript_calls.py`: import `Counter` from `collections`. Add the `cwds` field to `Transcript`. In `read_transcript`, right after the `isinstance(value, dict)` check, count `value.get("cwd")` when it is a non-empty `str`, and pass the counter to `Transcript(...)`. Extend the module docstring's list of what one pass returns with "the count of each record's cwd".

`python/agent_tools/agent_owner_report.py`:
- Import `os`, `Counter` (beside `defaultdict`), `datetime` and `timezone`, and `format_rfc3339_utc`, `project_name` and `repo_root` from `agent_tools.agent_costs`.
- `_CallRead` gains `repo_root: str | None = None`. In `_read_invocation`, the `gate and --run-id and --action-id` branch keeps its `registration is None` assignment and also records a qualifying `--repo-root` into `read.repo_root` when that is still `None`.
- `_owner_scan` adds `"repo_root"` and `"cwds"` to the owner dict. `scan_owner_transcript` adds `"first_start"` to the scan.
- `_lineage` sorts launches, extras and their owner scans together by `_launch_order`, then computes the project with a helper `_project(owner_scans, homes)` following the invariant. It computes `started` from the group and passes both to `_lineage_row(..., project=..., started=...)` and `Lineage(..., started=started)`.
- `_lineages` and `collect` pass `homes` through. The eval branch passes the same `homes`.

```python
def _project(owner_scans, homes):
    """The repository holding the lineage's ledger (issue 503 D4): the first absolute registering
    `--repo-root` in launch order, else `project_name` over the owners' record cwds."""
```

- [ ] **Step 4: Verify**

Run the Owner tests command (timeout 300 s). Expected: `Ran 18 tests`, `OK`.
Run the Neighbour tests command (timeout 300 s). Expected: `Ran 48 tests`, `OK`.

- [ ] **Step 5: Update the contract**

In `python/README.md` § agent-costs:
- In the **Per-model pricing (issue 432)** paragraph, the sentence on `agent_tools.transcript_calls` also says that the reader counts each record's `cwd`.
- After *Lineage and descendants.*, add a sub-paragraph *Project and start (issue 503).* It states the `started` rule (earliest call of the owner transcripts, all their calls, whatever the window, as an RFC3339 UTC instant) and the `project` rule with its `project_name` fallback and the `.worktrees` folding, as `_project` implements them. It also says that an eval trial row takes the project and start of its first lineage.
- In *Document.*, the `lineages` key list ends `…, absolute_path_calls, project, started`.

Run: `rg -c 'Project and start \(issue 503\)' python/README.md` — expected `1`.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/transcript_calls.py python/agent_tools/agent_owner_report.py tests/owner_transcripts.py tests/test_agent_owner_report.py python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(agent-costs): give owner lineages a project and a start (issue 503)" -m "<trailer lines>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":10,"boundary":"all","deleted_lines":4,"record_bytes":4096,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1a","last_task":1,"owner":1,"path":"python/agent_tools/transcript_calls.py"},{"bounds":[{"added_lines":70,"boundary":"all","deleted_lines":12,"record_bytes":14336,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":7,"owner":1,"path":"python/agent_tools/agent_owner_report.py"},{"bounds":[{"added_lines":30,"boundary":"all","deleted_lines":8,"record_bytes":6144,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":6,"owner":1,"path":"tests/owner_transcripts.py"},{"bounds":[{"added_lines":110,"boundary":"all","deleted_lines":4,"record_bytes":8192,"support":{"covers":["r1d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1d","last_task":7,"owner":1,"path":"tests/test_agent_owner_report.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":3,"record_bytes":32768,"support":{"covers":["r1e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1e","last_task":7,"owner":1,"path":"python/README.md"}]}}
```
