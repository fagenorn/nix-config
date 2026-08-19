# Task 1: Build the authoritative budget checker and publish its policy

**Files:**
- Create: `home/common/agent-skills/artifact-budget-policy.json`
- Create: `home/common/agent-skills/scripts/artifact-budget`
- Create: `home/common/agent-skills/scripts/artifact_budget.py`
- Create: `home/common/agent-skills/tests/fixtures/artifact-budgets/small-issue.json`
- Create: `home/common/agent-skills/tests/fixtures/artifact-budgets/oversized-issue.json`
- Create/Test: `home/common/agent-skills/tests/test_artifact_budget.py`
- Modify: `home/common/agent-skills/default.nix`
- Modify: `Justfile`

**Interfaces:**
- Consumes: no earlier task; design decisions D1, D2, D7, D8, D11, and D13 are the contract.
- Produces: importable `artifact_budget.load_limits(kind: str, policy_path: Path | None = None) -> ArtifactLimits`; `artifact_budget.check_artifact(kind: str, root: Path, policy_path: Path | None = None) -> CheckResult`; `artifact_budget.validate_producer_report(report: Mapping[str, object], policy_path: Path | None = None) -> None`; `artifact_budget.validate_sdd_report(report: Mapping[str, object], policy_path: Path | None = None) -> None`; `artifact_budget.validate_ship_handoff(report: Mapping[str, object], policy_path: Path | None = None) -> None`; `artifact_budget.validate_ship_summary(report: Mapping[str, object], policy_path: Path | None = None) -> None`; `artifact_budget.main(argv: Sequence[str] | None = None) -> int`; executable wrapper `home/common/agent-skills/scripts/artifact-budget`; installed executable `~/.agents/bin/artifact-budget`; installed import path `~/.agents/lib/python/artifact_budget.py`; default policy `~/.agents/share/artifact-budget-policy.json`.
- `ArtifactLimits` exposes integer `root_max_bytes`, `member_max_bytes`, `max_members`, and `aggregate_max_bytes`. `CheckResult.to_dict()` returns only `interface_version`, `kind`, `status`, `metrics`, and `violations`.

**Invariants:**
- Policy version 1 has exactly `schema_version`, `unit`, `artifacts`, and `phase_reports`; artifact kinds and entry fields are closed; unknown/duplicate/missing keys, booleans, fractions, non-positive roots/aggregates, negative member fields, one-file inconsistencies, and aggregate limits below the root fail before measurement.
- `design-spec` and `handoff` accept one non-symlink regular root and no members. `implementation-plan` discovers contiguous `<stem>.tasks/task-1.md`…`task-N.md`; `review-package` discovers contiguous `<stem>.shards/shard-001.diff`…`shard-NNN.diff`.
- Package roots must reference every discovered member exactly once and no absent/outside member. Plan references are the final Markdown link on each Task-index row. Review manifests use exactly the D8 fields; each `shards` entry has exactly `path` and `bytes`, matches discovery order and actual bytes, `total_diff_bytes` equals the shard-byte sum, and `coverage.complete` is true. Every manifest integer uses `type(value) is int`, so booleans fail.
- Reject a missing member directory, a root/member/directory symlink, non-regular entry, name gap, unknown entry, unreadable file, duplicate resolved member identity, malformed UTF-8 root/manifest, or reference mismatch with exit 2 and no success JSON.
- Metrics are exact encoded bytes: `root_bytes`; `total_bytes = root_bytes + sum(member bytes)`; `file_count = 1 + member count`; `largest_member_bytes = 0` for one-file artifacts and the largest member otherwise.
- Violations are the sorted subset in canonical order `root_bytes`, `member_bytes`, `member_count`, `aggregate_bytes`. Valid measurement always emits one compact deterministic JSON line plus newline; exit 0 means `within_budget`, exit 3 means `over_budget`. Exit 2 writes one concise diagnostic to stderr and nothing to stdout.
- `validate_producer_report` accepts only top-level `state`, `artifact`, and `notes`, applies `phase_reports.notes_max_characters` from the loaded policy, rejects legacy/extra fields, validates exact artifact/status/metrics/violation shapes and all integer types, and rejects every invalid state/status pairing.
- `validate_sdd_report` accepts exactly `state`, `review_state`, `conformance_verdict`, `correctness_verdict`, `verification_state`, `base_sha`, `head_sha`, `report_path`, and `notes`; its state/verdict values are closed enums, SHAs are full lowercase Git object IDs or `null` on failure, the one report path is a repository-relative string or `null`, and notes use the policy-owned limit.
- `validate_ship_handoff` accepts exactly the fixed lifecycle scalars, one spec artifact, one plan artifact, and `notes`: `ledger_repo_root`, `run_id`, `attempt`, `owner`, `owner_worktree`, `issue_number`, `branch`, `worktree_path`, `spec_artifact`, `plan_artifact`, `head_sha`, `review_state`, `auto`, `notes`. Lifecycle identity fields may be `null` only as one group; all integers reject booleans; both artifacts use the same strict root/status/metrics shape; no path or member list is accepted.
- `validate_ship_summary` accepts exactly the fixed lifecycle scalar fields `issue`, `state`, `pr_url`, `merge_sha`, `issue_closed`, `discussion_items`, and `notes`, rejects extra/legacy fields, requires `discussion_items == []`, and applies the same policy-owned notes limit.
- Repository fixtures contain descriptors and repetition metadata, never large padding. Tests materialize every descriptor, invoke the CLI, and compare actual exit/status/metrics/violations with descriptor expectations.
- The committed wrapper is mode `100755` and executes `python3 "$HOME/.agents/lib/python/artifact_budget.py" "$@"`; Home Manager installs that wrapper as the bin command and the module separately.

- [ ] **Step 1: Write the failing CLI contract tests and compact fixture descriptors**

Create descriptors whose exact top-level fields are `schema_version`, `case`, and `artifacts`; each artifact entry has `kind`, `case`, `shape`, `root_bytes`, `member_bytes`, and `expected`, where `expected` has exactly `exit_code`, `status`, `metrics`, `violations`, and `producer_state`. `small-issue.json` covers all four kinds below their limits with exit 0/`within_budget`/`complete`/no violations; `oversized-issue.json` covers spec root +1, plan ninth member, plan member +1, handoff root +1, review member +1, and review aggregate/count pressure with exit 3 and the producer terminal states fixed in the design.

Add the following executable test module; its descriptor materializer uses the exact D8 plan-link and manifest schemas so expected fixture metadata is always checked against CLI behavior:

```python
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[4]
SCRIPT = ROOT / "home/common/agent-skills/scripts/artifact_budget.py"
POLICY = ROOT / "home/common/agent-skills/artifact-budget-policy.json"
FIXTURES = Path(__file__).parent / "fixtures/artifact-budgets"
sys.path.insert(0, str(SCRIPT.parent))
import artifact_budget


class ArtifactBudgetCliTest(unittest.TestCase):
    def run_check(self, kind: str, root: Path, policy: Path = POLICY):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "check", "--kind", kind,
             "--root", str(root), "--policy", str(policy), "--format", "json"],
            text=True, capture_output=True, check=False,
        )

    def test_single_file_exact_boundary_and_unicode_plus_one(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "spec.md"
            path.write_bytes(b"x" * 65_536)
            exact = self.run_check("design-spec", path)
            self.assertEqual(exact.returncode, 0, exact.stderr)
            result = json.loads(exact.stdout)
            self.assertEqual(
                result["metrics"],
                {"root_bytes": 65_536, "total_bytes": 65_536,
                 "file_count": 1, "largest_member_bytes": 0},
            )
            path.write_bytes(b"x" * 65_535 + "é".encode("utf-8"))
            over = self.run_check("design-spec", path)
            self.assertEqual(over.returncode, 3, over.stderr)
            self.assertEqual(json.loads(over.stdout)["violations"], ["root_bytes", "aggregate_bytes"])

    def test_plan_discovers_members_and_rejects_ninth_or_unindexed_member(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "plan.md"
            members = Path(raw) / "plan.tasks"
            members.mkdir()
            rows = []
            for number in range(1, 9):
                member = members / f"task-{number}.md"
                member.write_text(f"# Task {number}\n", encoding="utf-8")
                rows.append(
                    f"Task {number} — T{number} — f{number} — full — "
                    f"[task-{number}.md](plan.tasks/task-{number}.md)"
                )
            root.write_text("## Task index\n\n" + "\n\n".join(rows) + "\n", encoding="utf-8")
            self.assertEqual(self.run_check("implementation-plan", root).returncode, 0)
            (members / "task-9.md").write_text("# Task 9\n", encoding="utf-8")
            ninth = self.run_check("implementation-plan", root)
            self.assertEqual(ninth.returncode, 2)
            self.assertEqual(ninth.stdout, "")

    def test_valid_measurement_is_deterministic_and_violations_are_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "handoff.md"
            path.write_bytes(b"h" * 8_193)
            first = self.run_check("handoff", path)
            second = self.run_check("handoff", path)
            self.assertEqual(first.returncode, 3)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(
                set(json.loads(first.stdout)),
                {"interface_version", "kind", "status", "metrics", "violations"},
            )

    def test_malformed_policy_and_package_shape_fail_without_success_output(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "handoff.md"
            root.write_text("small", encoding="utf-8")
            policy = directory / "bad.json"
            policy.write_text('{"schema_version":true}', encoding="utf-8")
            result = self.run_check("handoff", root, policy)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr.strip())

    def materialize_descriptor(self, item: dict[str, object], directory: Path) -> Path:
        kind = item["kind"]
        root = directory / {"design-spec": "spec.md", "implementation-plan": "plan.md",
                            "handoff": "handoff.md", "review-package": "review.json"}[kind]
        target = item["root_bytes"]
        member_sizes = item["member_bytes"]
        if kind in {"design-spec", "handoff"}:
            root.write_bytes(b"x" * target)
            return root
        if kind == "implementation-plan":
            members = directory / "plan.tasks"
            members.mkdir()
            rows = []
            for number, size in enumerate(member_sizes, 1):
                prefix = f"# Task {number}\n".encode()
                (members / f"task-{number}.md").write_bytes(prefix + b"x" * (size - len(prefix)))
                rows.append(f"Task {number} — T{number} — f — full — "
                            f"[task-{number}.md](plan.tasks/task-{number}.md)")
            prefix = ("## Task index\n\n" + "\n\n".join(rows) + "\n").encode()
            root.write_bytes(prefix + b" " * (target - len(prefix)))
            return root
        members = directory / "review.shards"
        members.mkdir()
        shards = []
        for number, size in enumerate(member_sizes, 1):
            path = members / f"shard-{number:03d}.diff"
            path.write_bytes(b"d" * size)
            shards.append({"path": f"review.shards/{path.name}", "bytes": size})
        manifest = {"interface_version": 1, "kind": "review-package",
                    "range": {"base": "a" * 40, "head": "b" * 40},
                    "commits": [],
                    "stat": {"files_changed": len(shards), "insertions": 0, "deletions": 0},
                    "shards": shards, "total_diff_bytes": sum(member_sizes),
                    "coverage": {"complete": True, "file_diff_count": len(shards)}}
        prefix = json.dumps(manifest, separators=(",", ":")).encode()
        root.write_bytes(prefix + b" " * (target - len(prefix)))
        return root

    def test_repository_descriptors_drive_cli_results(self):
        for fixture_name in ("small-issue.json", "oversized-issue.json"):
            fixture = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
            for item in fixture["artifacts"]:
                with self.subTest(fixture=fixture_name, case=item["case"]), \
                     tempfile.TemporaryDirectory() as raw:
                    root = self.materialize_descriptor(item, Path(raw))
                    result = self.run_check(item["kind"], root)
                    expected = item["expected"]
                    self.assertEqual(result.returncode, expected["exit_code"], result.stderr)
                    measured = json.loads(result.stdout)
                    self.assertEqual(measured["status"], expected["status"])
                    self.assertEqual(measured["metrics"], expected["metrics"])
                    self.assertEqual(measured["violations"], expected["violations"])
                    if result.returncode == 3:
                        self.assertNotEqual(measured["status"], "within_budget")

    def test_report_validator_rejects_legacy_fields_and_policy_over_limit_notes(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        limit = policy["phase_reports"]["notes_max_characters"]
        report = {"state": "complete", "artifact": {"kind": "handoff", "path": "h.md",
                  "metrics": {"root_bytes": 1, "total_bytes": 1, "file_count": 1,
                              "largest_member_bytes": 0},
                  "budget_status": "within_budget"}, "notes": "ok"}
        artifact_budget.validate_producer_report(report, POLICY)
        for forbidden in ("decisions", "open_items", "adr_paths", "summary"):
            with self.subTest(forbidden=forbidden), self.assertRaises(ValueError):
                artifact_budget.validate_producer_report({**report, forbidden: []}, POLICY)
        with self.assertRaises(ValueError):
            artifact_budget.validate_producer_report({**report, "notes": "x" * (limit + 1)}, POLICY)

    def test_ship_summary_validator_rejects_lists_legacy_summary_and_long_notes(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        limit = policy["phase_reports"]["notes_max_characters"]
        summary = {"issue": 49, "state": "merged", "pr_url": "https://example.test/pr/1",
                   "merge_sha": "a" * 40, "issue_closed": True,
                   "discussion_items": [], "notes": "review detail: ledger.md"}
        artifact_budget.validate_ship_summary(summary, POLICY)
        for mutation in ({**summary, "summary": "legacy"},
                         {**summary, "discussion_items": ["unbounded"]},
                         {**summary, "notes": "x" * (limit + 1)}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                artifact_budget.validate_ship_summary(mutation, POLICY)

    def test_sdd_and_ship_handoff_validators_reject_legacy_transport(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        limit = policy["phase_reports"]["notes_max_characters"]
        sdd = {"state": "complete", "review_state": "clean",
               "conformance_verdict": "clean", "correctness_verdict": "clean",
               "verification_state": "passed", "base_sha": "a" * 40,
               "head_sha": "b" * 40, "report_path": ".superpowers/sdd/p/progress.md",
               "notes": "ok"}
        artifact_budget.validate_sdd_report(sdd, POLICY)
        for mutation in ({**sdd, "parked_findings": []},
                         {**sdd, "notes": "x" * (limit + 1)}):
            with self.subTest(kind="sdd", mutation=mutation), self.assertRaises(ValueError):
                artifact_budget.validate_sdd_report(mutation, POLICY)

        artifact = {"path": ".claude/specs/s.md",
                    "metrics": {"root_bytes": 1, "total_bytes": 1,
                                "file_count": 1, "largest_member_bytes": 0},
                    "budget_status": "within_budget"}
        handoff = {"ledger_repo_root": None, "run_id": None, "attempt": None,
                   "owner": None, "owner_worktree": None, "issue_number": 49,
                   "branch": "issue-49", "worktree_path": "/tmp/issue-49",
                   "spec_artifact": {"kind": "design-spec", **artifact},
                   "plan_artifact": {"kind": "implementation-plan", **artifact},
                   "head_sha": "b" * 40, "review_state": "clean", "auto": True,
                   "notes": "ok"}
        artifact_budget.validate_ship_handoff(handoff, POLICY)
        for mutation in ({**handoff, "summary": "legacy"},
                         {**handoff, "adr_paths": []},
                         {**handoff, "notes": "x" * (limit + 1)}):
            with self.subTest(kind="handoff", mutation=mutation), self.assertRaises(ValueError):
                artifact_budget.validate_ship_handoff(mutation, POLICY)

    def test_review_manifest_member_boundary_and_reference_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "review.json"
            members = Path(raw) / "review.shards"
            members.mkdir()
            member = members / "shard-001.diff"
            member.write_bytes(b"d" * 65_536)
            manifest = {
                "interface_version": 1,
                "kind": "review-package",
                "range": {"base": "a" * 40, "head": "b" * 40},
                "commits": [{"sha": "b" * 40, "subject": "fixture"}],
                "stat": {"files_changed": 1, "insertions": 1, "deletions": 0},
                "shards": [{"path": "review.shards/shard-001.diff", "bytes": 65_536}],
                "total_diff_bytes": 65_536,
                "coverage": {"complete": True, "file_diff_count": 1},
            }
            root.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(self.run_check("review-package", root).returncode, 0)
            member.write_bytes(b"d" * 65_537)
            manifest["shards"][0]["bytes"] = 65_537
            manifest["total_diff_bytes"] = 65_537
            root.write_text(json.dumps(manifest), encoding="utf-8")
            over = self.run_check("review-package", root)
            self.assertEqual(over.returncode, 3)
            self.assertIn("member_bytes", json.loads(over.stdout)["violations"])

    def test_review_manifest_rejects_boolean_in_every_integer_family(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "review.json"
            members = directory / "review.shards"
            members.mkdir()
            (members / "shard-001.diff").write_bytes(b"diff")
            valid = {"interface_version": 1, "kind": "review-package",
                     "range": {"base": "a" * 40, "head": "b" * 40}, "commits": [],
                     "stat": {"files_changed": 1, "insertions": 1, "deletions": 0},
                     "shards": [{"path": "review.shards/shard-001.diff", "bytes": 4}],
                     "total_diff_bytes": 4,
                     "coverage": {"complete": True, "file_diff_count": 1}}
            mutations = {
                "interface_version": lambda m: m.__setitem__("interface_version", True),
                "stat.files_changed": lambda m: m["stat"].__setitem__("files_changed", True),
                "stat.insertions": lambda m: m["stat"].__setitem__("insertions", True),
                "stat.deletions": lambda m: m["stat"].__setitem__("deletions", True),
                "shard.bytes": lambda m: m["shards"][0].__setitem__("bytes", True),
                "total_diff_bytes": lambda m: m.__setitem__("total_diff_bytes", True),
                "coverage.file_diff_count": lambda m: m["coverage"].__setitem__("file_diff_count", True),
            }
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    manifest = deepcopy(valid)
                    mutate(manifest)
                    root.write_text(json.dumps(manifest), encoding="utf-8")
                    result = self.run_check("review-package", root)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")

    def test_unknown_or_gapped_package_entries_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "plan.md"
            members = Path(raw) / "plan.tasks"
            members.mkdir()
            (members / "task-2.md").write_text("# Task 2\n", encoding="utf-8")
            root.write_text(
                "## Task index\n\nTask 2 — gap — f — full — "
                "[task-2.md](plan.tasks/task-2.md)\n", encoding="utf-8")
            gap = self.run_check("implementation-plan", root)
            self.assertEqual(gap.returncode, 2)
            self.assertEqual(gap.stdout, "")
            (members / "notes.md").write_text("orphan", encoding="utf-8")
            unknown = self.run_check("implementation-plan", root)
            self.assertEqual(unknown.returncode, 2)
            self.assertEqual(unknown.stdout, "")

    def test_symlinked_root_or_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            target = directory / "real.md"
            target.write_text("content", encoding="utf-8")
            link = directory / "handoff.md"
            link.symlink_to(target)
            result = self.run_check("handoff", link)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")

    def test_duplicate_and_unknown_policy_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = directory / "handoff.md"
            root.write_text("small", encoding="utf-8")
            duplicate = directory / "duplicate.json"
            duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            self.assertEqual(self.run_check("handoff", root, duplicate).returncode, 2)
            policy = json.loads(POLICY.read_text(encoding="utf-8"))
            policy["unexpected"] = 1
            unknown = directory / "unknown.json"
            unknown.write_text(json.dumps(policy), encoding="utf-8")
            self.assertEqual(self.run_check("handoff", root, unknown).returncode, 2)
```

The descriptor rows supply the exact plan aggregate/member/count boundary assertions and canonical violation order. Complete the named fail-closed seam with explicit table cases for the remaining policy scalar classes and directory/unreadable/duplicate-identity entries; each uses the same exit-2/no-stdout assertions as the concrete malformed cases above.

- [ ] **Step 2: Run the focused test and confirm the missing seam**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_artifact_budget.py`

Expected: FAIL because the module, executable wrapper, policy, fixture descriptors, and report validator do not exist at the base commit.

- [ ] **Step 3: Implement the strict module, policy, and Home Manager publication**

Write this exact policy data (pretty-printing is allowed; numeric values and keys are not):

```json
{
  "schema_version": 1,
  "unit": "bytes",
  "artifacts": {
    "design-spec": {"root_max_bytes": 65536, "member_max_bytes": 0, "max_members": 0, "aggregate_max_bytes": 65536},
    "implementation-plan": {"root_max_bytes": 16384, "member_max_bytes": 49152, "max_members": 8, "aggregate_max_bytes": 131072},
    "handoff": {"root_max_bytes": 8192, "member_max_bytes": 0, "max_members": 0, "aggregate_max_bytes": 8192},
    "review-package": {"root_max_bytes": 16384, "member_max_bytes": 65536, "max_members": 8, "aggregate_max_bytes": 524288}
  },
  "phase_reports": {"notes_max_characters": 500}
}
```

Implement `artifact_budget.py` as one import-safe stdlib module with dataclasses for the two public values. `load_limits` loads either the explicit policy or `Path.home() / ".agents/share/artifact-budget-policy.json"`, uses `json.load(..., object_pairs_hook=...)` to reject duplicate keys, validates the complete policy before returning one kind's limits, and never coerces types. `check_artifact` opens and measures the regular root, discovers members from the required sibling directory, validates root/member agreement, and returns a result only after all shape/I/O checks pass. Compare bytes using strict `>` checks so exact ceilings succeed. The four report validators load the same policy, enforce D11's exact per-boundary key sets, closed states/types, and policy-owned notes bound, and use `type(value) is int` for all integer fields. They reject every legacy list/summary transport instead of truncating it and do not introduce another numeric limit.

For plan roots, accept only Task-index rows matching the task-number/member-number/name convention and require the discovered/reference sets and orders to be identical. For review roots, validate the exact D8 manifest types and fields with booleans rejected for every integer, then compare its ordered `shards` entries to discovery and measured bytes. Use `lstat`/no-follow checks before reads and `(st_dev, st_ino)` identities for duplicate-file rejection. Catch expected parse/I/O/validation errors only at `main`, print one diagnostic to stderr, and return 2; unexpected programmer errors must not be translated to success.

Create the exact executable Bash wrapper named above and commit it as mode `100755`. Publish that wrapper at `.agents/bin/artifact-budget`, the Python module at `.agents/lib/python/artifact_budget.py`, and the JSON under `.agents/share/`. Add `test_artifact_budget.py` to `agent-workflow-tests`; do not add CI wiring.

- [ ] **Step 4: Verify focused behavior and the aggregate workflow suite**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_artifact_budget.py`

Expected: PASS with every boundary, discovery, schema, deterministic-output, and fixture case green; any wrong exit code or unclosed output field fails the task.

Run: `just agent-workflow-tests`

Expected: PASS with no failures or errors, proving the new module is included without regressing existing helpers.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/artifact-budget-policy.json \
  home/common/agent-skills/scripts/artifact-budget \
  home/common/agent-skills/scripts/artifact_budget.py \
  home/common/agent-skills/tests/fixtures/artifact-budgets \
  home/common/agent-skills/tests/test_artifact_budget.py \
  home/common/agent-skills/default.nix Justfile
git commit -m "feat(issue-49): add artifact budget checker" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
