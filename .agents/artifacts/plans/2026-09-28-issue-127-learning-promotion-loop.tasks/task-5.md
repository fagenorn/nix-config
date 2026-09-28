# Task 5: Deployment, `superseded`, P2 feasibility

**Files:**
- Modify: `python/agent_tools/promotion_lifecycle.py` (two edges, `verify_deployment`)
- Modify: `python/agent_tools/promotion.py` (`--superseded-by` shape `type`)
- Create: `tests/test_promotion_deployment.py`
- Modify: `justfile` (`tests/test_promotion_deployment.py \` joins `agent-workflow-tests` after `tests/test_promotion_lifecycle.py \`)

Read the spec's "Deployment" paragraph and the `authorized → promoted` / `promoted →
superseded` rows. D9, D24, D26, D29 and D32 govern this task.

**Interfaces:**
- Consumes (Task 4): `TRANSITIONS`, `ARGUMENT_TARGETS`, `Arguments`, `advance`,
  `authorization_gates`, `anchor_line_present`, `write_in_place`; support `LifecycleFixture`
  (`capture`, `advance`, `step`, `walk`, `assert_refused`, `BUNDLE`), `write_bundle`,
  `write_json`, `draft`, `duplicate`, `NULL_DIGEST`. (Task 1): `symlinked_component`,
  `is_safe_relative_path`, `PROJECT_ONLY_RESIDUE`, `Refusal`, `violation`.
- Produces in `promotion_lifecycle.py`:

```python
# added to TRANSITIONS:
# ("authorized", "promoted"): "promote"    ("promoted", "superseded"): "supersede"
def verify_deployment(candidate: dict, root: Path, here: str) -> dict
    # {"verified_repository": here, "removed": [...], "retained": [...],
    #  "deferred_repositories": [...]}  or Refusal
```

**Invariants:**
- `promote` edge, in order (D24, D29): `authorization_gates(candidate, root)` (so a hand-edited
  `authorized` candidate gains nothing); then `anchor_line_present` on the destination, else
  `destination_missing`; then `verify_deployment`. The result sets `deployment`; history actor
  and rationale are `None`.
- `verify_deployment` walks `local_duplicates` in order: `disposition ==
  PROJECT_ONLY_RESIDUE` → `retained` gets the path; else `repository != here` →
  `deferred_repositories` gets the repository (first occurrence only); else when the path's
  `symlinked_component` is `None` and nothing exists at it (`os.path.lexists` false) →
  `removed`; else a regular non-symlink file whose `hashlib.sha256(bytes).hexdigest()` equals
  a non-null `sha256` → `duplicate_present`; anything else (other bytes, null digest, a
  directory, a symlink at any depth, an unreadable file) → `promotion_reconciliation_required`.
  First refusal wins; pointer `/local_duplicates/<index>/path` (D9).
- The module deletes, moves and rewrites nothing on disk except the candidate file itself.
- `supersede` edge: `--superseded-by` is required by argparse whenever `--to superseded`
  (`parser.error` if absent) and its argparse `type` accepts only `sha256:` + 64 lowercase hex.
  The history entry's rationale is `f"superseded by {value}"`; nothing else changes (D32).
- `promoted` has exactly one outgoing edge; every other target from `promoted` refuses
  `transition_not_permitted`.

- [ ] **Step 1: Write the failing suite `tests/test_promotion_deployment.py`**

```python
"""Seam 1 for deployment verification and `superseded` (#127 D9, D24, D26, D32)."""

import hashlib
import json
import unittest

from .promotion_test_support import (NULL_DIGEST, LifecycleFixture, draft, duplicate,
                                     write_bundle, write_json)

HERE = "fagenorn/nix-config"
DESTINATION = "home/common/agent-skills/standards/the-bar.md"
HEADING = "### Investigate before changing"
LEFTOVER = b"Investigate before changing.\n"


class DeploymentTest(LifecycleFixture, unittest.TestCase):
    def authorized(self, duplicates, name="c.json", with_destination=True):
        path = self.capture(draft(local_duplicates=duplicates), name=name)
        self.walk(path, "authorized", "approved")
        if with_destination:
            target = self.root / DESTINATION
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"# The bar\n{HEADING}\n", encoding="utf-8")
        return path

    def put(self, relative, data=LEFTOVER):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def test_promotion_records_removed_retained_and_deferred(self):
        self.put("docs/keep.md")
        path = self.authorized([
            duplicate(HERE, "docs/lesson.md", hashlib.sha256(LEFTOVER).hexdigest()),
            duplicate(HERE, "docs/keep.md", disposition="project_only_residue"),
            duplicate("fagenorn/argus", "AGENTS.md"),
            duplicate("fagenorn/argus", "CLAUDE.md")])
        after = self.step(path, "promoted")
        self.assertEqual(after["deployment"], {
            "verified_repository": HERE, "removed": ["docs/lesson.md"],
            "retained": ["docs/keep.md"], "deferred_repositories": ["fagenorn/argus"]})
        self.assertEqual([after["state"], after["history"][-1]["actor"]], ["promoted", None])
        self.assertTrue((self.root / "docs/keep.md").exists())

    def test_the_destination_is_checked_before_any_duplicate(self):
        self.put("docs/lesson.md")
        path = self.authorized([duplicate(HERE, "docs/lesson.md",
                                          hashlib.sha256(LEFTOVER).hexdigest())],
                               with_destination=False)
        self.assert_refused(path, "promoted", "destination_missing")
        (self.root / DESTINATION).parent.mkdir(parents=True)
        (self.root / DESTINATION).write_text(HEADING + " code\n", encoding="utf-8")
        self.assert_refused(path, "promoted", "destination_missing")

    def test_an_unchanged_leftover_is_duplicate_present(self):
        self.put("docs/lesson.md")
        path = self.authorized([duplicate(HERE, "docs/lesson.md",
                                          hashlib.sha256(LEFTOVER).hexdigest())])
        payload = self.assert_refused(path, "promoted", "duplicate_present")
        self.assertEqual(payload["error"]["violations"][0]["pointer"],
                         "/local_duplicates/0/path")
        self.assertTrue((self.root / "docs/lesson.md").exists())

    def test_anything_but_absent_or_identical_needs_reconciliation(self):
        digest = hashlib.sha256(LEFTOVER).hexdigest()
        real = self.put("real/lesson.md")
        cases = {
            "drifted": lambda: self.put("docs/lesson.md", b"edited\n"),
            "null_digest": lambda: self.put("docs/lesson.md"),
            "directory": lambda: (self.root / "docs/lesson.md").mkdir(parents=True),
            "leaf_link": lambda: ((self.root / "docs").mkdir(),
                                  (self.root / "docs/lesson.md").symlink_to(real)),
            "parent_link": lambda: (self.root / "docs").symlink_to(
                real.parent, target_is_directory=True),
        }
        for index, (name, make) in enumerate(cases.items()):
            with self.subTest(case=name):
                for leftover in ("docs/lesson.md", "docs"):
                    target = self.root / leftover
                    if target.is_symlink() or target.is_file():
                        target.unlink()
                    elif target.is_dir():
                        target.rmdir()
                sha = NULL_DIGEST if name == "null_digest" else digest
                path = self.authorized([duplicate(HERE, "docs/lesson.md", sha)],
                                       name=f"{index}.json")
                make()
                self.assert_refused(path, "promoted", "promotion_reconciliation_required")

    def test_a_null_digest_with_the_file_gone_is_removed(self):
        path = self.authorized([duplicate(HERE, "docs/lesson.md", NULL_DIGEST)])
        self.assertEqual(self.step(path, "promoted")["deployment"]["removed"],
                         ["docs/lesson.md"])

    def test_a_hand_edited_authorized_candidate_gains_nothing(self):
        path = self.capture()
        document = json.loads(path.read_text(encoding="utf-8"))
        classification = {"rule": 4, "rule_id": "standard_layer",
                          "declared_layer": "standard_layer", "overridden_by_rule_1": False}
        write_json(path, dict(document, state="authorized", classification=classification))
        self.assert_refused(path, "promoted", "evidence_unresolvable")
        bundle = json.loads(write_bundle(self.root, self.BUNDLE, "unmeasured")
                            .read_text(encoding="utf-8"))
        write_json(path, dict(document, state="authorized", classification=classification,
                              evidence={"bundle_path": self.BUNDLE,
                                        "bundle_id": bundle["bundle_id"],
                                        "state": "approved", "gate_contract": "issue-70",
                                        "gate_version": 1}))
        self.assert_refused(path, "promoted", "evidence_unmeasured")

    def test_a_rule_one_candidate_passes_the_same_gates(self):
        """D26: a duplicate-of-platform lesson earns no evidence exemption."""
        (self.root / DESTINATION).parent.mkdir(parents=True)
        (self.root / DESTINATION).write_text(HEADING + "\n", encoding="utf-8")
        path = self.capture(draft(local_duplicates=[]))
        self.walk(path, "decision_ready", "unmeasured")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["classification"]["rule"], 1)
        self.assert_refused(path, "authorized", "evidence_unmeasured",
                            "--authorized-by", "fagenorn")


class SupersededTest(LifecycleFixture, unittest.TestCase):
    NEW = "sha256:" + "a" * 64

    def promoted(self):
        path = self.capture(draft(local_duplicates=[]))
        self.walk(path, "authorized", "approved")
        target = self.root / DESTINATION
        target.parent.mkdir(parents=True)
        target.write_text(HEADING + "\n", encoding="utf-8")
        self.step(path, "promoted")
        return path

    def test_superseded_is_the_only_edge_out_of_promoted(self):
        path = self.promoted()
        for target, flags in (("rejected", ("--rationale", "x")), ("evaluating", ()),
                              ("withdrawn", ("--rationale", "x"))):
            with self.subTest(target=target):
                self.assert_refused(path, target, "transition_not_permitted", *flags)
        self.assert_refused(path, "superseded", None, exit_code=2)
        self.assert_refused(path, "superseded", None, "--superseded-by", "sha256:xyz",
                            exit_code=2)
        after = self.step(path, "superseded", "--superseded-by", self.NEW)
        self.assertEqual([after["state"], after["history"][-1]["rationale"]],
                         ["superseded", f"superseded by {self.NEW}"])
        self.assert_refused(path, "promoted", "transition_not_permitted")

    def test_authorized_can_still_be_rejected(self):
        path = self.capture()
        self.walk(path, "authorized", "approved")
        after = self.step(path, "rejected", "--rationale", "drift incorporated elsewhere")
        self.assertEqual(after["state"], "rejected")
```

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_promotion_deployment.py 2>&1 | tail -3`
Expected: FAILED — `transition_not_permitted` where `promoted` is expected.

- [ ] **Step 3: Implement** the two edges and `verify_deployment` per the invariants.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_promotion_deployment.py tests/test_promotion_lifecycle.py tests/test_promotion_documents.py tests/test_agent_gate_bundle.py 2>&1 | tail -3`
Expected: `OK`, no failures (9 new tests in this task).
Run: `just build 2>&1 | tail -3` — success.

- [ ] **Step 5: Commit** — `git add` the four files; subject
  `feat(issue-127/T5): promotion deployment verification and superseded`, with the trailers.

- [ ] **Step 6: P2 feasibility (package P2 = Tasks 3–5, D20, D28)**

```bash
set -euo pipefail
BASE="$(git log --reverse --format=%H -F --grep='feat(issue-127/T3):' | head -1)"
test -n "$BASE"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/rp-XXXXXX")/review.json"
review-package .agents/artifacts/plans/2026-09-28-issue-127-learning-promotion-loop.md \
  "$(git rev-parse "$BASE^")" "$(git rev-parse HEAD)" "$OUT" > "$OUT.report"
grep -q '"state":"complete"' "$OUT.report"
```

Expected: exit 0; otherwise split the offending file before continuing. Nothing to commit.
