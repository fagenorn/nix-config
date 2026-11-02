# Task 1: Verification source seam and the `revision` report member

Spec: `.agents/artifacts/specs/2026-10-09-issue-341-register-against-remote-integration-branch-design.md` (D1, D8, D10). Plain `verify` keeps today's answers; it gains `revision` and reports `schema_version: 2`. `--register` is not moved yet: it keeps today's ancestry check against the contract's branch name until Task 2.

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py`
- Modify: `python/agent_tools/adopt_verify.py`
- Modify: `python/agent_tools/adopt_project.py` (`command_verify` only)
- Test: `home/common/agent-skills/tests/test_adopt_verify.py`

**Interfaces:**
- Consumes: `adopt_inspection.run_git`, `git_or_fail`, `split_nul`, `is_evidence_record_path`, `tracked_inventory`, `EVIDENCE_RECORD_DIR` (unchanged).
- Produces, in `adopt_inspection` (per D10, these *replace* the old names; delete `blob_at_head` and `tracked_evidence_records`, and change `introducing_commit`'s signature — `adopt_verify` is their only caller):
  - `blob_at(root: Path, revision: str, relative: str) -> bytes | None` — `git show <revision>:<relative>`; `None` on non-zero exit.
  - `evidence_records_at(root: Path, revision: str) -> list[str]` — `git_or_fail(root, "ls-tree", "-r", "--name-only", "-z", revision, "--", EVIDENCE_RECORD_DIR)`, filtered by `is_evidence_record_path`, sorted.
  - `introducing_commit(root: Path, revision: str, relative: str) -> str | None` — `git log --diff-filter=A --format=%H -1 <revision> -- <relative>`.
- Produces, in `adopt_verify`:
  - `@dataclass(frozen=True) class VerificationSource` with fields `ref: str`, `commit: str`, `resolver_root: Path`, `inventory: list[tuple[str, str]]`, `branch: str | None = None`. `ref` is the report's label, `commit` the 40-hex id every record is read at, `resolver_root` the directory `run_resolver` is called on, `inventory` the `(path, object id)` pairs the unclassified-path check reads, `branch` the fetched branch (always `None` for `HEAD`; Task 2 sets it).
  - `head_source(root: Path) -> VerificationSource` — `ref="HEAD"`, `commit` = `git_or_fail(root, "rev-parse", "--verify", "HEAD^{commit}")` decoded and stripped, `resolver_root=root`, `inventory=tracked_inventory(root)`, `branch=None`.
  - `verify_repository(root: Path, source: VerificationSource, run_resolver: Resolver) -> Verification` (new middle parameter).
  - `Verification.__init__(self, report: dict, resolve_payload: object, source: VerificationSource, evidence_candidates: list[str])`, keeping the two existing attributes and adding `source` and `evidence_candidates` (the `evidence_records_at` list, which Task 2's integration gate reads).
  - `VERIFY_SCHEMA_VERSION = 2`; the report gains `"revision": {"ref": source.ref, "commit": source.commit}`.

**Invariants:**
- Every resolver call in `verify_repository` uses `source.resolver_root`; every git read of a record, map or introducing commit uses `source.commit`; `no-unclassified-agent-path` reads `source.inventory`. `root` is used only for `git -C` and for the report's `root` member.
- The six checks, their order, their details and the result policy are unchanged; the report's other members keep their meaning.
- An unborn `HEAD` still refuses `adopt_failure`/`adopt.git.failed` (the `git_or_fail` refusal plain `verify` printed before).
- `register_project` is not edited in this task.

- [ ] **Step 1: Write the failing test**

In `test_adopt_verify.py`, set `VERIFY_MEMBERS` to include `"revision"` (sorted list: `["adoption_commit", "blockers", "checks", "evidence_record", "migration_map", "project_id", "registered", "result", "revision", "root", "schema_version"]`). In `VerifyReadOnlyTest.test_a_conformant_checkout_is_adopted_and_writes_nothing`, replace `self.assertEqual(report["schema_version"], 1)` with:

```python
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["revision"], {
            "ref": "HEAD",
            "commit": git(root, "rev-parse", "HEAD").strip(),
        })
```

and add to `VerifyReadOnlyTest`:

```python
    def test_plain_verify_reads_the_committed_head_not_the_index(self):
        root = adopted_repo(self.home)
        head = git(root, "rev-parse", "HEAD").strip()
        record = f".agents/artifacts/evidence/{'a1' * 32}.json"
        git(root, "rm", "--quiet", "--cached", record)
        report = self.report(root)
        self.assertEqual(report["revision"]["commit"], head)
        self.assertEqual(report["evidence_record"], record)
        self.assertEqual(
            self.check(report, "adoption-evidence-record")["status"], "passed")
```

(The second test passes at base too; it pins that records stay read from the commit while the inventory stays the index.)

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py -k test_a_conformant_checkout_is_adopted_and_writes_nothing`
Expected: FAIL — the member list lacks `revision` (or `schema_version` is 1).

- [ ] **Step 3: Write the minimal implementation**

1. `adopt_inspection.py`: replace `blob_at_head` with `blob_at`, `tracked_evidence_records` with `evidence_records_at`, and add the `revision` parameter to `introducing_commit`, as specified above. Each docstring states that it reads the commit named by `revision`, never the working tree, and keeps the existing reason (an untracked file must not answer for a record history does not carry; #148 D34).
2. `adopt_verify.py`: add `from dataclasses import dataclass`, `VerificationSource`, `head_source`, the new `Verification` constructor, and thread `source` through `verify_repository` per the invariants. Update the `from agent_tools.adopt_inspection import (...)` list to the new names (add `git_or_fail`). Set `VERIFY_SCHEMA_VERSION = 2` and add the `revision` member to the report dict.
3. `adopt_project.py` `command_verify`: call `adopt_verify.verify_repository(root, adopt_verify.head_source(root), run_resolver)`; the `--register` branch is otherwise unchanged in this task.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_verify.py`
Expected: PASS, 22 tests (21 at base plus the new one).

Run: `if grep -nE 'blob_at_head|tracked_evidence_records' python/agent_tools/*.py; then exit 1; fi`
Expected: no output, exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_inspection.py python/agent_tools/adopt_verify.py python/agent_tools/adopt_project.py home/common/agent-skills/tests/test_adopt_verify.py
git commit -m "feat(adopt): read verify through a pinned verification source (#341)"
```
