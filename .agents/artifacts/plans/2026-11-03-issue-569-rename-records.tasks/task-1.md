# Task 1: Freeze record policy v1 and bind the retained domain to it

The living policy keeps its v1 content in this task, so every measured byte is unchanged. The task adds the frozen v1 objects, makes each measurement entry point take the record policy as a keyword, and moves every retained call site and identity pin onto v1 (spec § Two record domains; D2, D3, D14, D16). Task 2 flips the living policy.

Run every long command from the worktree root, in the foreground, as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with the timeout shown. `BASE` is `3be26be2878da02e4aa9417719f3388f08f0298c`.

**Files:**
- Modify: `python/agent_tools/review_actual.py`
- Modify: `python/agent_tools/review_forecast.py` (`edge_facts` signature and its two `git_diff` calls only)
- Modify: `python/agent_tools/review_projection.py` (`reconstruct_owned` signature and its `edge_facts`/`git_diff` calls only)
- Modify: `python/agent_tools/review_issue100.py`, `python/agent_tools/review_issue121.py`, `python/agent_tools/review_task7.py`, `python/agent_tools/review_derivation.py`, `python/agent_tools/review_witness.py`
- Modify: `python/README.md` (§ Retained review evidence, one sentence)
- Test: `tests/test_review_feasibility.py` (new class `RecordPolicyDomainTest`, placed directly before `class SourceProjectionFixture:`)
- Test: `tests/retained_review_test_support.py`, `tests/test_review_derivation.py`, `tests/test_review_witness.py`, `tests/test_review_issue100.py` (names only)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, in `agent_tools.review_actual`:
  - `RECORD_POLICY_V1: dict`, `RECORD_POLICY_V1_SHA256 = telemetry_digest(RECORD_POLICY_V1)`, `PACKING_POLICY_V1: dict`, `PACKING_POLICY_V1_SHA256 = telemetry_digest(PACKING_POLICY_V1)`.
  - `_policies(record_policy: Mapping) -> Mapping`: the packing policy that binds `record_policy`.
  - `_packing_choices(record_policy: Mapping = RECORD_POLICY) -> tuple[dict, ...]`.
  - `git_diff(repo, base_tree, head_tree, *view, record_policy: Mapping = RECORD_POLICY) -> bytes`.
  - `actual_inputs(repo, base, head, package_name, limits, *, record_policy: Mapping = RECORD_POLICY)`.
  - `actual_inputs_from_trees(repo, base_tree, head_tree, *, base, head, commits, package_name, limits, record_policy: Mapping = RECORD_POLICY)`.
- Produces in `agent_tools.review_forecast`: `edge_facts(repo, parent, commit, ordinal, *, record_policy: Mapping = RECORD_POLICY) -> dict`.
- Produces in `agent_tools.review_projection`: `reconstruct_owned(repo, prerequisite_commit, owned_commits, *, record_policy: Mapping = RECORD_POLICY) -> Reconstruction`.
- Unchanged signatures: `select_candidate`, `pack_input`, `measure_input`, `_build_candidate` (spec D2: both packing variants choose the same candidates).

**Invariants:**
- `RECORD_POLICY_V1` is today's `RECORD_POLICY` literal, moved byte for byte: its digest is `sha256:73cc5609e8a395d33a210b20f413a72179300475b2f6d1c55fed097c7f6ee63b`. `PACKING_POLICY_V1` is today's `PACKING_POLICY` literal with `"record_policy_sha256": RECORD_POLICY_V1_SHA256`: its digest is `sha256:fbb7b821b21015c5e56a4829c0c33dd2e7233a09a5826287cc563634098b43bf`. Both are their own literals (D14), never spreads of the living objects.
- In this task the living `RECORD_POLICY` and `PACKING_POLICY` keep their v1 content but stay separate objects, so `RECORD_POLICY_SHA256 == RECORD_POLICY_V1_SHA256` here.
- The policy set is closed, by object identity. `_policies(p)` returns `PACKING_POLICY` when `p is RECORD_POLICY` and `PACKING_POLICY_V1` when `p is RECORD_POLICY_V1`. Before returning, it recomputes both digests of the matched pair. Every other argument, an equal copy included, raises `GenerationError("unsupported record policy")`. A matched record policy whose digest moved raises `GenerationError("unsupported record policy")`; a matched packing policy whose digest moved raises `GenerationError("unsupported packing policy")`.
- `git_diff` resolves `_packing_choices(record_policy)` before it validates the view or runs Git, so a refused policy never reaches a repository. It runs `record_git(repo, *record_policy["git_config"], "diff", *record_policy["diff_args"], *view, base_tree, head_tree)`.
- `actual_inputs` passes its `record_policy` to `actual_inputs_from_trees`. That function passes it to its four `git_diff` views and iterates `_packing_choices(record_policy)`. `edge_facts` passes it to both of its `git_diff` calls. `reconstruct_owned` passes it to its `edge_facts` calls and its patch `git_diff`.
- Retained domain (spec § Two record domains): each of these 12 calls in `review_issue100`, `review_issue121` and `review_task7` passes `record_policy=RECORD_POLICY_V1`: `review_issue100.fresh_records` (`actual_inputs_from_trees`) and `model_100` (`edge_facts`); `review_issue121.contribution_edges` (`edge_facts`, `git_diff`), `_boundary` (`reconstruct_owned` twice, `actual_inputs_from_trees`) and `_model` (`actual_inputs`, the future-only `actual_inputs_from_trees`); and `review_task7._numstat` (`git_diff`), `_measure` (`actual_inputs_from_trees`) and `compose` (the `--name-status` `git_diff`).
- Every retained identity pin uses the v1 names:
  - `review_issue100`: the fresh `Domain` in `ISSUE_100_PINS` and the `_checked` policy list (`RECORD_POLICY_V1["kind"]`, `RECORD_POLICY_V1_SHA256`).
  - `review_issue121`: `_POLICY`, `_measured`'s and the validator's `packing_policy_sha256` (`PACKING_POLICY_V1_SHA256`).
  - `review_task7`: the identities' `record_policy_sha256` (`RECORD_POLICY_V1_SHA256`), its `packing_policy_sha256` (`PACKING_POLICY_V1_SHA256`) and the context list read from `PACKING_POLICY_V1`.
  - `review_derivation`'s tool group and `review_witness._components` (`PACKING_POLICY_V1_SHA256`, `RECORD_POLICY_V1_SHA256`).
  No retained module imports a living name (`RECORD_POLICY`, `RECORD_POLICY_SHA256`, `PACKING_POLICY`, `PACKING_POLICY_SHA256`).
- The committed bundle, `tests/retained_evidence_test_support.py` and `home/common/agent-skills/artifact-budget-policy.json` are byte-unchanged.

- [ ] **Step 1: Write the failing test**

Add this class to `tests/test_review_feasibility.py`, directly before `class SourceProjectionFixture:` (D17 keeps it apart from #559's hunks):

```python
class RecordPolicyDomainTest(unittest.TestCase):
    """Issue 569: the retained domain's record policy v1 is frozen beside the living policy."""

    def test_frozen_v1_identities_and_the_closed_policy_set(self):
        from agent_tools.canonical import telemetry_digest
        from agent_tools.review_actual import (PACKING_POLICY, PACKING_POLICY_V1, PACKING_POLICY_V1_SHA256,
            RECORD_POLICY, RECORD_POLICY_V1, RECORD_POLICY_V1_SHA256, GenerationError, git_diff)
        self.assertEqual(RECORD_POLICY_V1_SHA256,
                         'sha256:73cc5609e8a395d33a210b20f413a72179300475b2f6d1c55fed097c7f6ee63b')
        self.assertEqual(PACKING_POLICY_V1_SHA256,
                         'sha256:fbb7b821b21015c5e56a4829c0c33dd2e7233a09a5826287cc563634098b43bf')
        self.assertEqual(telemetry_digest(RECORD_POLICY_V1), RECORD_POLICY_V1_SHA256)
        self.assertEqual(telemetry_digest(PACKING_POLICY_V1), PACKING_POLICY_V1_SHA256)
        self.assertEqual(PACKING_POLICY_V1['record_policy_sha256'], RECORD_POLICY_V1_SHA256)
        self.assertEqual({k: v for k, v in PACKING_POLICY_V1.items() if k != 'record_policy_sha256'},
                         {k: v for k, v in PACKING_POLICY.items() if k != 'record_policy_sha256'})
        self.assertIsNot(RECORD_POLICY_V1, RECORD_POLICY)
        empty = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'  # refused before any repository read
        for policy in (dict(RECORD_POLICY), dict(RECORD_POLICY_V1), {}):
            with self.subTest(policy=policy.get('kind')), \
                    self.assertRaisesRegex(GenerationError, 'unsupported record policy'):
                git_diff(Path('.'), empty, empty, '--name-only', '-z', record_policy=policy)
        for group, key, label in ((RECORD_POLICY_V1, 'kind', 'unsupported record policy'),
                                  (PACKING_POLICY_V1, 'fallback', 'unsupported packing policy')):
            previous = group[key]
            try:
                group[key] = 'mutated'
                with self.subTest(key=key), self.assertRaisesRegex(GenerationError, label):
                    git_diff(Path('.'), empty, empty, '--name-only', '-z', record_policy=RECORD_POLICY_V1)
            finally:
                group[key] = previous
```

The module already imports `unittest` and `Path` at module level.

- [ ] **Step 2: Run the test and watch it fail**

Run: `env PYTHONPATH=python timeout 300 python3 -m unittest tests.test_review_feasibility.RecordPolicyDomainTest 2>&1 | tail -3`
Expected: `FAILED (errors=1)`, an `ImportError` naming `PACKING_POLICY_V1`.

- [ ] **Step 3: Implement**

1. `review_actual.py`. Directly after `PACKING_POLICY_SHA256`, add `RECORD_POLICY_V1` and `PACKING_POLICY_V1` as copies of the two literals above them, as the invariants say, then their digests. Precede them with the comment `# The retained review evidence's record domain (issue 569): frozen, never the living policy.` Add `_policies` and the `record_policy` parameter to `_packing_choices`, `git_diff`, `actual_inputs` and `actual_inputs_from_trees`. `git_diff`'s docstring becomes `"""Every measurement view of one record domain uses that domain's explicit record policy."""`. `_build_candidate` and `select_candidate` keep calling `_packing_choices()` with its default.
2. `review_forecast.py`: import `RECORD_POLICY` (`Mapping` is already imported), add the keyword to `edge_facts` and pass it to both `git_diff` calls. Its `--name-status` parsing is Task 2's.
3. `review_projection.py`: import `RECORD_POLICY`, and `Mapping` beside `Sequence`, add the keyword to `reconstruct_owned` and pass it to `edge_facts(..., record_policy=record_policy)` and the patch `git_diff(..., record_policy=record_policy)`.
4. The five retained modules: replace the living imports with the v1 names and apply the invariants' 12 calls and pins. In `review_task7`, `telemetry_digest(RECORD_POLICY)` becomes `RECORD_POLICY_V1_SHA256`.
5. Tests:
   - `tests/retained_review_test_support.py` imports `RECORD_POLICY_V1`, and its fresh-domain argv reads `RECORD_POLICY_V1["git_config"]` and `RECORD_POLICY_V1["diff_args"]`.
   - `tests/test_review_derivation.py` (both imports, the hostile-control argv, the expected tool group) and `tests/test_review_witness.py` (import, tool group) use `RECORD_POLICY_V1`, `PACKING_POLICY_V1_SHA256` and `RECORD_POLICY_V1_SHA256`.
   - `tests/test_review_issue100.py` imports `RECORD_POLICY_V1_SHA256` for its real-pins domain row.
   - `tests/test_review_record_view.py` and `tests/test_review_task7.py` keep the living names: they test the living view and the unchanged packing contexts.
6. `python/README.md`: append to the § Retained review evidence paragraph: ` The retained domain measures and replays under the frozen record policy \`review-git-records/v1\` and its packing digest (\`RECORD_POLICY_V1\`, \`PACKING_POLICY_V1\` in \`review_actual\`), never the living policy, so the committed bundle, its anchor digest and its tool commit stay as they are when the living policy moves (#569).`

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH=python timeout 300 python3 -m unittest tests.test_review_feasibility.RecordPolicyDomainTest tests.test_review_feasibility.SharedPackingPolicyTest 2>&1 | tail -1`
Expected: `OK` (2 tests).

Run: `env PYTHONPATH=python timeout 1800 python3 -m agent_tools.suite_runner --jobs 4 tests/test_review_evidence.py tests/test_review_witness.py tests/test_review_derivation.py tests/test_review_issue100.py tests/test_review_issue121.py tests/test_review_task7.py tests/test_review_compact100.py tests/test_review_compact121.py tests/test_review_replay.py home/common/agent-skills/tests/test_review_package.py tests/test_review_record_view.py tests/test_review_feasibility.py tests/test_review_projection_cases.py tests/test_review_history.py 2>&1 | grep -E 'suite-runner: (failed|summary)'`
Expected: one line, `suite-runner: summary members=14 passed=14 failed=0 …`; about 6 min at `--jobs 4`. The committed-bundle replay (`test_review_evidence.py`) passing is AC7's fast check.

The retained call sites (a scratch check; the script is not committed):

```bash
env PYTHONPATH=python python3 - <<'EOF'
import ast, sys
from pathlib import Path
MEASURE = {"git_diff", "actual_inputs", "actual_inputs_from_trees", "edge_facts", "reconstruct_owned"}
calls, bad = 0, []
for name in ("review_issue100", "review_issue121", "review_task7"):
    path = Path("python/agent_tools") / f"{name}.py"
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) in MEASURE:
            calls += 1
            if not any(k.arg == "record_policy" and getattr(k.value, "id", None) == "RECORD_POLICY_V1"
                       for k in node.keywords):
                bad.append(f"{path}:{node.lineno}")
print(f"{calls} measurement calls; not on RECORD_POLICY_V1: {bad}")
sys.exit(1 if bad or calls != 12 else 0)
EOF
```

Expected: `12 measurement calls; not on RECORD_POLICY_V1: []`, exit 0 (at `BASE` it lists all 12 and exits 1).

```bash
if git grep -n -w -e RECORD_POLICY -e RECORD_POLICY_SHA256 -e PACKING_POLICY -e PACKING_POLICY_SHA256 -- python/agent_tools/review_issue100.py python/agent_tools/review_issue121.py python/agent_tools/review_task7.py python/agent_tools/review_derivation.py python/agent_tools/review_witness.py; then exit 1; fi
git diff --quiet 3be26be2878da02e4aa9417719f3388f08f0298c -- tests/fixtures/retained-review-evidence tests/retained_evidence_test_support.py home/common/agent-skills/artifact-budget-policy.json
```

Expected: no output, exit 0.

- [ ] **Step 5: Commit**

Stage exactly the Files above, then `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(review): freeze record policy v1 for retained evidence" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"a9ee8cf5f0b67dd524b8ff791badcbae46fe6ce5","head":"54c87eafd1c3e671f0a3262076625e8cdc8f8d16"}],"commit_subject_bytes":[64,64,64],"id":1,"records":[{"bounds":[{"added_lines":60,"boundary":"all","deleted_lines":15,"record_bytes":14336,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1a","last_task":2,"owner":1,"path":"python/agent_tools/review_actual.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":3,"record_bytes":5120,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":3,"owner":1,"path":"python/agent_tools/review_forecast.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":3,"record_bytes":6144,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":3,"owner":1,"path":"python/agent_tools/review_projection.py"},{"bounds":[{"added_lines":10,"boundary":"all","deleted_lines":7,"record_bytes":11264,"support":{"covers":["r1d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1d","last_task":1,"owner":1,"path":"python/agent_tools/review_issue100.py"},{"bounds":[{"added_lines":22,"boundary":"all","deleted_lines":14,"record_bytes":20480,"support":{"covers":["r1e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1e","last_task":1,"owner":1,"path":"python/agent_tools/review_issue121.py"},{"bounds":[{"added_lines":14,"boundary":"all","deleted_lines":10,"record_bytes":12288,"support":{"covers":["r1f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1f","last_task":1,"owner":1,"path":"python/agent_tools/review_task7.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":4,"record_bytes":5120,"support":{"covers":["r1g"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1g","last_task":1,"owner":1,"path":"python/agent_tools/review_derivation.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":4,"record_bytes":5120,"support":{"covers":["r1h"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1h","last_task":1,"owner":1,"path":"python/agent_tools/review_witness.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":1,"record_bytes":9216,"support":{"covers":["r1i"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1i","last_task":3,"owner":1,"path":"python/README.md"},{"bounds":[{"added_lines":36,"boundary":"all","deleted_lines":0,"record_bytes":7168,"support":{"covers":["r1j"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1j","last_task":3,"owner":1,"path":"tests/test_review_feasibility.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":4096,"support":{"covers":["r1k"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1k","last_task":2,"owner":1,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":6,"record_bytes":7168,"support":{"covers":["r1l"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1l","last_task":1,"owner":1,"path":"tests/test_review_derivation.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":5120,"support":{"covers":["r1m"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1m","last_task":1,"owner":1,"path":"tests/test_review_witness.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":4096,"support":{"covers":["r1n"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1n","last_task":2,"owner":1,"path":"tests/test_review_issue100.py"}]}}
```
