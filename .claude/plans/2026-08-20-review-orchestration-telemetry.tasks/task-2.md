# Task 2: Attribute Transcript Telemetry and Add Ordered Pool Fallback

**Files:**
- Modify: `scripts/agent-costs.py`
- Modify: `tests/test_agent_costs.py`

**Interfaces:**
- Consumes: the ordered `(session_index, is_root, transcript_path)` jobs from `find_sessions`; top-level transcript `agentId`, assistant `cwd`, initial sidechain user envelope, and existing `attributionSkill`; existing additive scan-result fields and report tables.
- Produces: `scan_paths(paths, executor_factory=ProcessPoolExecutor) -> list[dict | None]`, preserving input order and performing all-or-nothing sequential fallback with one stderr line; injected executors make the successful and fallback paths deterministic under test (D8).
- Produces: `owner_issue(result) -> str | None`, returning an issue only when one owner-shaped `agent_id` agrees with exactly one own-cwd issue.
- Produces: `fold_scan_totals(results) -> dict`, folding `SUM_FIELDS` once in supplied order for global tokens/turns/cost.
- Produces: `build_groups(sessions, per_session, project_filter=None) -> (groups, retained_results, kept_sessions, kept_files)`, partitioning already-scanned results without rescanning or duplication.
- Produces: `main(argv=None, *, executor_factory=ProcessPoolExecutor)`, keeping the CLI unchanged while allowing focused injected-executor tests.
- Produces in each scan result: `agent_id: str | None` and `review_operation: "plan-review" | "diff-review" | None`; qualifying assistant turns remain in existing `attr_turns` under `codex-collaboration/<operation>`.

**Invariants:**
- Every non-`None` scan result has one destination. Proven owner transcripts move all additive/counter/list/peak fields together to their issue; root and every other transcript remain in the root group (D3).
- Owner identity must full-match `^aissue-([1-9][0-9]*)-owner-([1-9][0-9]*)-(.+)$`; cwd evidence must contain exactly one issue number and equal the identity number (D3).
- Each non-root transcript increments `subagents` only in its destination. Session count, root outcome, and intervention semantics remain in the root group (D3).
- Two or more distinct proven owner issue numbers force only the root group to `(multi-issue)`; zero/one owner retains the existing root directory/cwd issue resolution (D3).
- The initial operation envelope must be a sidechain root user record with `parentUuid: null`, first line `WORKTREE_ROOT: <absolute path>`, and second line exactly `REVIEW_OPERATION: plan-review` or `REVIEW_OPERATION: diff-review`. No other word occurrence qualifies attribution (D4).
- The cheap user-record prefilter admits a large valid envelope. It does not widen ordinary long-user scanning beyond the exact envelope marker (D4).
- Parallel values are fully materialized inside the protected boundary. A construction, map, iteration, or context-manager teardown exception discards the attempt and sequentially scans every path once in original order; sequential errors propagate (D5).
- Global `fresh`, `cache_create`, `cache_read`, `output`, `turns`, and `cost` are folded directly from retained raw results in stable order before group partitioning (D5).
- The successful-executor and forced-fallback report bytes are identical, the successful executor emits no stderr, and the six-transcript fixture's raw cost matches literal `0.0113625` to 12 decimal places before group totals are compared (D8).
- The module counting-rule prose describes the live partition: proven issue-owner transcripts follow their issue worktree, while rooted helper/reviewer overhead remains with root (D8).
- Pricing, model mapping, report headings/layout, and root-overhead cost policy remain unchanged.

- [ ] **Step 1: Write scanner-evidence and fallback tests**

Replace the `assistant` helper in `tests/test_agent_costs.py` with this exact production-shaped extension, then add `envelope_user`:

```python
def assistant(msg_id, usage=None, content=None, model="claude-opus-5",
              effort="xhigh", stop_reason="tool_use", cwd="/Users/me/repo",
              agent_id=None, attribution_skill=None, sidechain=False):
    return record({
        "type": "assistant",
        "cwd": cwd,
        "effort": effort,
        "agentId": agent_id,
        "attributionSkill": attribution_skill,
        "isSidechain": sidechain,
        "message": {
            "id": msg_id,
            "model": model,
            "stop_reason": stop_reason,
            "usage": usage,
            "content": content or [],
        },
    })


def envelope_user(agent_id, cwd, operation, *, packet="review packet", parent_uuid=None):
    return record({
        "type": "user",
        "isSidechain": True,
        "agentId": agent_id,
        "cwd": cwd,
        "parentUuid": parent_uuid,
        "message": {
            "role": "user",
            "content": (
                f"WORKTREE_ROOT: {cwd}\n"
                f"REVIEW_OPERATION: {operation}\n"
                f"{packet}"
            ),
        },
    })
```

Add these complete scanner contracts to `ScanFileTest`:

```python
    def test_owner_identity_and_own_cwd_evidence_must_agree(self):
        issue_7 = "/Users/me/repo/.claude/worktrees/worktree-issue-7-widget"
        issue_8 = "/Users/me/repo/.claude/worktrees/worktree-issue-8-other"
        cases = [
            ("aissue-7-owner-2-deadbeef", [issue_7], "7"),
            ("aissue-7-owner-2-deadbeef", [issue_8], None),
            ("aissue-7-owner-2-deadbeef", [issue_7, issue_8], None),
            ("areviewer-7-deadbeef", [issue_7], None),
            ("aissue-7-owner-0-deadbeef", [issue_7], None),
        ]
        for agent_id, cwds, expected in cases:
            with self.subTest(agent_id=agent_id, cwds=cwds):
                lines = [
                    assistant(f"m{index}", usage=USAGE_1, cwd=cwd, agent_id=agent_id, sidechain=True)
                    for index, cwd in enumerate(cwds)
                ]
                self.assertEqual(agent_costs.owner_issue(self.scan(lines)), expected)

    def test_exact_initial_envelope_qualifies_codex_skill_attribution(self):
        cwd = "/Users/me/repo/.claude/worktrees/worktree-issue-7-widget"
        for operation in ("plan-review", "diff-review"):
            with self.subTest(operation=operation):
                packet = "x" * 5000
                result = self.scan([
                    envelope_user("acodex-reviewer-7-deadbeef", cwd, operation, packet=packet),
                    assistant(
                        "m1",
                        usage=USAGE_1,
                        cwd=cwd,
                        agent_id="acodex-reviewer-7-deadbeef",
                        attribution_skill="codex-collaboration",
                        sidechain=True,
                    ),
                ])
                self.assertEqual(result["review_operation"], operation)
                self.assertEqual(result["attr_turns"], {f"codex-collaboration/{operation}": 1})

    def test_operation_words_outside_exact_root_envelope_are_not_evidence(self):
        cwd = "/Users/me/repo/.claude/worktrees/worktree-issue-7-widget"
        malformed = [
            record({
                "type": "user", "isSidechain": True, "agentId": "ahelper", "parentUuid": None,
                "message": {"role": "user", "content": "Discuss diff-review in prose"},
            }),
            envelope_user("ahelper", cwd, "plan-review", parent_uuid="not-root"),
            record({
                "type": "user", "isSidechain": True, "agentId": "ahelper", "parentUuid": None,
                "message": {"role": "user", "content": f"REVIEW_OPERATION: plan-review\nWORKTREE_ROOT: {cwd}\npacket"},
            }),
        ]
        for index, first_record in enumerate(malformed):
            with self.subTest(index=index):
                result = self.scan([
                    first_record,
                    assistant(
                        "m1", usage=USAGE_1, cwd=cwd, agent_id="ahelper",
                        attribution_skill="codex-collaboration", sidechain=True,
                    ),
                ])
                self.assertIsNone(result["review_operation"])
                self.assertEqual(result["attr_turns"], {"codex-collaboration": 1})
```

Add `import contextlib`, `import io`, and `from unittest import mock`, then add `ExecutorFallbackTest`; no external dependency is allowed.

```python
class ExecutorFallbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = []
        for index, usage in enumerate((USAGE_1, USAGE_2)):
            path = Path(self.tmp.name) / f"{index}.jsonl"
            path.write_text(assistant(f"m{index}", usage=usage), encoding="utf-8")
            self.paths.append(path)

    def assert_fallback(self, executor_factory, exception_name):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            actual = agent_costs.scan_paths(self.paths, executor_factory=executor_factory)
        expected = [agent_costs.scan_file(path) for path in self.paths]
        self.assertEqual(actual, expected)
        self.assertEqual(
            stderr.getvalue(),
            f"Process pool unavailable ({exception_name}); scanning sequentially.\n",
        )

    def test_pool_construction_failure_falls_back_in_order(self):
        class ConstructionFailure:
            def __init__(self, **_kwargs):
                raise PermissionError("semaphores denied")

        self.assert_fallback(ConstructionFailure, "PermissionError")

    def test_partial_iteration_failure_discards_prefix_and_rescans_all(self):
        class IterationFailure:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def map(self, function, paths, chunksize):
                del chunksize
                paths = list(paths)

                def values():
                    yield function(paths[0])
                    raise RuntimeError("worker stream failed")

                return values()

        self.assert_fallback(IterationFailure, "RuntimeError")

    def test_sequential_scanner_failure_is_not_swallowed(self):
        class ConstructionFailure:
            def __init__(self, **_kwargs):
                raise PermissionError("semaphores denied")

        with mock.patch.object(agent_costs, "scan_file", side_effect=ValueError("bad transcript")):
            with self.assertRaisesRegex(ValueError, "bad transcript"):
                agent_costs.scan_paths(self.paths, executor_factory=ConstructionFailure)
```

- [ ] **Step 2: Write the synthetic multi-issue report and stdout-equivalence test**

Replace `EndToEndTest.setUp` with this production-shaped single dispatcher session:

```python
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        project = root / "-Users-me-repo"
        project.mkdir()
        issue_7 = "/Users/me/repo/.claude/worktrees/worktree-issue-7-widget"
        issue_8 = "/Users/me/repo/.claude/worktrees/worktree-issue-8-other"
        (project / "sess1.jsonl").write_text(
            assistant(
                "root-1",
                usage=USAGE_1,
                cwd="/Users/me/repo",
                content=[{"type": "text", "text": "Dispatcher completed."}],
                stop_reason="end_turn",
            ),
            encoding="utf-8",
        )
        subdir = project / "sess1" / "subagents"
        subdir.mkdir(parents=True)
        (subdir / "owner-7.jsonl").write_text(
            assistant(
                "owner-7-1", usage=USAGE_1, cwd=issue_7,
                agent_id="aissue-7-owner-1-owner7", sidechain=True,
            ),
            encoding="utf-8",
        )
        (subdir / "owner-8.jsonl").write_text(
            assistant(
                "owner-8-1", usage=USAGE_1, cwd=issue_8,
                agent_id="aissue-8-owner-2-owner8", sidechain=True,
            ),
            encoding="utf-8",
        )
        (subdir / "helper.jsonl").write_text(
            assistant(
                "helper-1", usage=USAGE_1, cwd=issue_7,
                model="claude-helper-root-only", agent_id="ahelper-7-helper",
                sidechain=True,
            ),
            encoding="utf-8",
        )
        for operation, cwd in (("plan-review", issue_7), ("diff-review", issue_8)):
            agent_id = f"acodex-{operation}-transport"
            (subdir / f"{operation}.jsonl").write_text(
                "".join([
                    envelope_user(agent_id, cwd, operation),
                    assistant(
                        f"{operation}-1", usage=USAGE_1, cwd=cwd,
                        agent_id=agent_id, attribution_skill="codex-collaboration",
                        sidechain=True,
                    ),
                ]),
                encoding="utf-8",
            )
        self.projects = str(root)
```

Add this helper and test to `EndToEndTest`:

```python
    class DeterministicExecutor:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def map(self, function, paths, chunksize):
            del chunksize
            return [function(path) for path in paths]

    def run_main(self, executor_factory):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            agent_costs.main(
                ["--projects-dir", self.projects, "--days", "0"],
                executor_factory=executor_factory,
            )
        return stdout.getvalue(), stderr.getvalue()

    def test_dispatcher_owners_reviews_and_forced_fallback_are_truthful(self):
        class ConstructionFailure:
            def __init__(self, **_kwargs):
                raise PermissionError("semaphores denied")

        successful_stdout, successful_stderr = self.run_main(self.DeterministicExecutor)
        fallback_stdout, fallback_stderr = self.run_main(ConstructionFailure)
        self.assertEqual(successful_stderr, "")
        self.assertEqual(fallback_stdout, successful_stdout)
        self.assertEqual(
            fallback_stderr,
            "Process pool unavailable (PermissionError); scanning sequentially.\n",
        )

        self.assertRegex(successful_stdout, r"(?m)^#7\s+repo\s+")
        self.assertRegex(successful_stdout, r"(?m)^#8\s+repo\s+")
        self.assertRegex(successful_stdout, r"(?m)^\(multi-issue\)\s+repo\s+")
        self.assertIn("codex-collaboration/plan-review 1", successful_stdout)
        self.assertIn("codex-collaboration/diff-review 1", successful_stdout)
        self.assertIn("6 transcripts", successful_stdout)
        self.assertIn("5 subagents", successful_stdout)

        sessions = list(agent_costs.find_sessions(Path(self.projects), None))
        jobs = [
            (index, is_root, path)
            for index, (_home, roots, subs) in enumerate(sessions)
            for is_root, path in [(True, path) for path in roots] + [(False, path) for path in subs]
        ]
        ordered_results = [agent_costs.scan_file(path) for _index, _is_root, path in jobs]
        direct = agent_costs.fold_scan_totals([result for result in ordered_results if result])
        self.assertEqual(direct["turns"], 6)
        self.assertEqual(direct["fresh"], 60)
        self.assertEqual(direct["output"], 120)
        self.assertEqual(direct["cache_create"], 30)
        self.assertEqual(direct["cache_read"], 600)
        self.assertAlmostEqual(direct["cost"], 0.0113625, places=12)
        self.assertIn("6 turns", successful_stdout)
        self.assertIn("fresh 60", successful_stdout)
        self.assertIn("cache_create 30", successful_stdout)
        self.assertIn("cache_read 600", successful_stdout)
        self.assertIn("output 120", successful_stdout)

        per_session = agent_costs.defaultdict(list)
        for (session_index, is_root, _path), result in zip(jobs, ordered_results):
            if result:
                per_session[session_index].append((is_root, result))
        groups, retained, kept_sessions, kept_files = agent_costs.build_groups(sessions, per_session)
        root_group = groups[("repo", agent_costs.MULTI_ISSUE)]
        self.assertEqual(root_group["models"]["claude-helper-root-only"], 1)
        self.assertNotIn("claude-helper-root-only", groups[("repo", "7")]["models"])
        self.assertEqual(root_group["sessions"], 1)
        self.assertEqual(groups[("repo", "7")]["sessions"], 0)
        self.assertEqual(groups[("repo", "8")]["sessions"], 0)
        self.assertEqual(sum(group["subagents"] for group in groups.values()), 5)
        self.assertEqual(sum(group["turns"] for group in groups.values()), direct["turns"])
        for field in agent_costs.TOKEN_FIELDS:
            self.assertEqual(sum(group[field] for group in groups.values()), direct[field])
        self.assertAlmostEqual(sum(group["cost"] for group in groups.values()), direct["cost"], places=12)
        self.assertEqual(len(retained), 6)
        self.assertEqual(kept_sessions, 1)
        self.assertEqual(kept_files, 6)

    def test_default_executor_degrades_concisely_when_environment_restricts_it(self):
        expected_stdout, expected_stderr = self.run_main(self.DeterministicExecutor)
        stdout, stderr = self.run_main(agent_costs.ProcessPoolExecutor)
        self.assertEqual(expected_stderr, "")
        self.assertEqual(stdout, expected_stdout)
        if stderr:
            self.assertRegex(
                stderr,
                r"\AProcess pool unavailable \([A-Za-z_][A-Za-z0-9_]*\); "
                r"scanning sequentially\.\n\Z",
            )
```

The helper's cwd names issue 7 while its `agentId` is not owner-shaped. The unique-model and simultaneous raw/group equalities above prove it stayed in root overhead and that partitioning neither copied nor omitted a transcript.

- [ ] **Step 3: Run the focused suite and observe the base failure**

Run:

```bash
python3 -m unittest -v tests/test_agent_costs.py
```

Expected at starting commit `e15909b`: FAIL. The observed base failure is the existing `EndToEndTest` subprocess exiting 1 at `ProcessPoolExecutor(...)` construction with `PermissionError: [Errno 1] Operation not permitted`; after adding the new tests, `scan_paths`, `owner_issue`, `fold_scan_totals`, injected `main`, identity evidence, operation qualification, and partitioned rows are also absent. All other 14 baseline telemetry tests pass.

- [ ] **Step 4: Implement transcript evidence extraction**

In `scripts/agent-costs.py`:

- Rewrite the module counting-rule prose to describe the post-implementation behavior: proven issue-owner transcripts follow their agreeing issue worktree; rooted helper, reviewer, ambiguous, and other non-owner transcripts remain root-session overhead. This is live behavior after the code change, not a historical or prospective claim (D8).
- Add `OWNER_AGENT_RE` as the exact full-match regex in the invariants. While scanning parsed records, collect non-empty top-level `agentId` values; return a single value only when all observed identities agree, otherwise `None`.
- Add an exact initial-envelope parser. It accepts only `type == "user"`, `isSidechain is True`, `parentUuid is None`, string content, absolute `WORKTREE_ROOT:` first line, and one closed-set `REVIEW_OPERATION:` second line. Record at most one `review_operation`; conflicting valid root envelopes yield `None` rather than guessing.
- Change the cheap user prefilter so a long line containing the exact `REVIEW_OPERATION:` marker is parsed even without `agentType`; retain the 4096-byte fast path for unrelated user records.
- Accumulate assistant attribution into a temporary raw counter. After the entire file has resolved one unambiguous initial operation (or `None`), qualify only raw `codex-collaboration` turns as `codex-collaboration/<operation>`; preserve every other key exactly. This prevents a later conflicting root envelope from leaving an already-qualified prefix.
- Implement `owner_issue(result)` from `result["agent_id"]` and the set of issue numbers found in `result["cwds"]`. Require one cwd issue and exact equality with the regex capture.

Do not infer identity from filenames, directories, prompt prose, skill attribution, or reviewer names.

- [ ] **Step 5: Implement all-or-nothing ordered scanning and raw totals**

Implement `scan_paths` so the entire `list(pool.map(...))` and context-manager exit are inside one `try`. Catch `Exception`, print the exact one-line disclosure with `type(error).__name__`, and return a fresh sequential list comprehension over every original path. Do not catch `BaseException`; do not wrap the sequential retry.

Refactor `main(argv=None, *, executor_factory=ProcessPoolExecutor)` to parse `argv`, call `scan_paths` once, and zip the returned list with `jobs` only after the boundary returns. Implement `fold_scan_totals` as an explicit in-order loop over `SUM_FIELDS`; do not use group subtotals or reorder cost terms.

Extract the session partition into `build_groups(sessions, per_session, project_filter=None)` returning `(groups, retained_results, kept_sessions, kept_files)`, with this algorithm:

1. Determine root cwd/project and apply `--project` filtering exactly as today.
2. Determine every non-root result's `owner_issue`; collect distinct proven owner issues.
3. Choose the root key: `(multi-issue)` for two or more distinct owners, otherwise the existing `issue_key(dir_name, root_cwds)` result.
4. Send roots and unproven non-roots to the root key; send each proven owner result to its issue key.
5. Merge every result's `SUM_FIELDS`, `COUNTER_FIELDS`, `LIST_FIELDS`, `skills`, `agents_killed`, and `peak_ctx` only into that destination. Increment `subagents` once for a non-root result in its destination.
6. Add `sessions`, root-only `interventions`, and root-only classified outcome only to the root group. Compute skill loads/repeats separately per destination within the session so moved owner skill data travels with the owner.
7. Return groups plus the retained ordered raw results/counters needed by `main`. Use `fold_scan_totals` over those retained results for displayed global turns/token buckets/cost; keep existing report format and group sorting.

No transcript may be copied into both root and owner groups. Peak context remains a max within the selected destination.

- [ ] **Step 6: Verify focused, workflow, and repository gates**

Run:

```bash
python3 -m unittest -v tests/test_agent_costs.py
just agent-workflow-tests
just build
git diff --check -- scripts/agent-costs.py tests/test_agent_costs.py
```

Expected: telemetry tests PASS including construction and partial-iteration fallback; all workflow tests PASS (the base's sole `ProcessPoolExecutor` failure is gone); Nix evaluation/build PASS; `git diff --check` exits 0 with no output. Any changed TOTAL token bucket/turn/cost, missing `(multi-issue)` root row, helper leakage into issue 7, unqualified operation, duplicate assignment, swallowed sequential error, or extra stderr line is incomplete.

- [ ] **Step 7: Commit**

```bash
git add scripts/agent-costs.py tests/test_agent_costs.py
git commit -m "feat(issue-48): attribute orchestration telemetry" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Expected: signed commit succeeds. `git diff --stat HEAD~2..HEAD -- patches/agent-plugins/codex-plugin-cc.patch lib/agent-plugins.nix home/common/claude-code/skills/codex-collaboration/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py scripts/agent-costs.py tests/test_agent_costs.py` names only the six implementation-owned repository files and summarizes both vertical slices; unrelated branch commits are outside this scoped path list.
