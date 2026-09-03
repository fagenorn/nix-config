"""Two boundary invariants of `adopt-project plan` that its main suite's
fixtures cannot reach.

`test_adopt_project.py` is the adoption suite; these cases live beside it
because that file is the review package's binding member and adding them there
would leave no room for the `apply` and `verify` suites still to come. The
fixtures and the temporary-`HOME` isolation are imported from it, so both files
build their repositories the same way; no `TestCase` crosses over, so neither
file collects the other's tests.

The two invariants:

1. The `/platform` violation exemption may only forgive what the planned
   amendment actually writes. `amended_contract` adds the member when it is
   absent and never rewrites an authored interval, so a present-but-wrong one
   is a violation that keeps the plan out of `ready` — not a false `passed`.
2. The projections loop holds the only variable path this planner reads. It
   comes from the authored contract, which is consumed whether or not the
   resolver accepted it, so the containment and secret-marker guards are
   applied there rather than assumed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# The sibling suite is imported as a module, so its directory has to be
# importable however this file was invoked — `python3 <path>` supplies it,
# `python3 -m unittest <path>` does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_adopt_project import (
    commit,
    make_home,
    nix_config_shape_repo,
    run,
    sha256_hash,
    write,
)

CONTRACT = ".agents/project.json"
CONTRACT_GATE = "contract-valid-after-amendment"


class BoundaryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = make_home()

    def plan(self, root: Path) -> dict:
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        return json.loads(out), out

    def contract_of(self, root: Path) -> dict:
        return json.loads((root / CONTRACT).read_text("utf-8"))

    def rewrite_contract(self, root: Path, contract: dict) -> None:
        write(root, CONTRACT, json.dumps(contract, indent=2) + "\n")

    def gate(self, doc: dict, gate_id: str) -> dict:
        for entry in doc["verification"]["ready_gates"]:
            if entry["id"] == gate_id:
                return entry
        raise AssertionError(f"no ready gate {gate_id!r}")


class ContractAmendmentReachTest(BoundaryTestCase):
    """The exemption tracks the amendment, not the pointer prefix."""

    def declaring(self, interval: object) -> Path:
        """`nix_config_shape_repo` with a `platform` member already authored.

        The shipped fixture deletes the member, which is the one shape the
        amendment does reach; every case here starts from a contract that
        already declares one.
        """
        root = nix_config_shape_repo(self.home)
        contract = self.contract_of(root)
        contract["platform"] = interval
        self.rewrite_contract(root, contract)
        commit(root, "declare a platform interval")
        return root

    def assert_blocked(self, root: Path) -> dict:
        doc, _ = self.plan(root)
        self.assertEqual(doc["plan"]["outcome"], "reconcile")
        self.assertEqual(doc["plan"]["state"], "draft")
        gate = self.gate(doc, CONTRACT_GATE)
        self.assertEqual(gate["status"], "failed")
        self.assertEqual(gate["repair_id"],
                         "adopt.contract.unfixable_violations")
        self.assertIn(CONTRACT_GATE,
                      [blocker["id"] for blocker in doc["plan"]["blockers"]])
        return doc

    def test_an_out_of_range_interval_keeps_the_plan_draft(self):
        """The installed platform is 1.0.0, so `[0.1.0, 1.0.0)` excludes it and
        `resolve` refuses `unsupported_schema` at pointer `/platform`."""
        self.assert_blocked(self.declaring(
            {"min_inclusive": "0.1.0", "max_exclusive": "1.0.0"}))

    def test_a_malformed_bound_keeps_the_plan_draft(self):
        for interval in (
                {"min_inclusive": "1.0", "max_exclusive": "2.0.0"},
                {"min_inclusive": "1.0.0", "max_exclusive": "2.0"},
                {"min_inclusive": "2.0.0", "max_exclusive": "2.0.0"},
        ):
            with self.subTest(interval=interval):
                self.setUp()
                self.assert_blocked(self.declaring(interval))

    def test_the_amendment_never_rewrites_an_authored_interval(self):
        authored = {"min_inclusive": "0.1.0", "max_exclusive": "1.0.0"}
        root = self.declaring(authored)
        doc, _ = self.plan(root)
        writes = [op for op in doc["changes"]
                  if op["targets"] == [CONTRACT]]
        self.assertEqual(len(writes), 1)
        expected = self.contract_of(root)
        expected["bindings"]["paths"]["artifacts"] = {
            "specs": ".agents/artifacts/specs",
            "plans": ".agents/artifacts/plans"}
        expected["bindings"]["paths"]["rejections"] = [
            ".agents/knowledge/rejections"]
        self.assertEqual(expected["platform"], authored)
        self.assertEqual(
            writes[0]["after"],
            sha256_hash((json.dumps(expected, indent=2, ensure_ascii=False)
                         + "\n").encode("utf-8")))

    def test_an_absent_member_is_still_forgiven_and_reaches_ready(self):
        """The control: the amendment does write an absent member, so its
        violation is exactly the one the exemption is for."""
        doc, _ = self.plan(nix_config_shape_repo(self.home))
        self.assertNotIn("platform", self.contract_of(
            Path(doc["handoff"]["repo_root"])))
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(self.gate(doc, CONTRACT_GATE)["status"], "passed")


class ProjectionTargetBoundaryTest(BoundaryTestCase):
    """The planner's one variable-path read obeys the inspection boundary."""

    def declaring_projection(self, target: str) -> Path:
        root = nix_config_shape_repo(self.home)
        contract = self.contract_of(root)
        contract["projections"] = contract["projections"] + [{
            "id": "extra.entry", "agent": "codex", "kind": "generated_file",
            "target": target,
            "source": ".agents/instructions/bootstrap.md"}]
        self.rewrite_contract(root, contract)
        return root

    def regeneration(self, doc: dict, target: str) -> dict:
        matches = [op for op in doc["changes"]
                   if op["op"] == "regenerate-projection"
                   and op["targets"] == [target]]
        self.assertEqual(len(matches), 1, target)
        return matches[0]

    def test_a_secret_shaped_target_is_never_read_or_hashed(self):
        target = ".env.production"
        secret = b"API_TOKEN=SUPER-SECRET-VALUE\n"
        root = self.declaring_projection(target)
        (root / target).write_bytes(secret)
        commit(root, "add a secret-shaped projection target")
        doc, out = self.plan(root)
        self.assertIsNone(self.regeneration(doc, target)["before"])
        self.assertNotIn(sha256_hash(secret), out)
        self.assertNotIn("SUPER-SECRET-VALUE", out)

    def test_a_target_resolving_outside_the_root_is_never_followed(self):
        outside = Path(tempfile.mkdtemp()).resolve() / "sibling.md"
        outside.write_bytes(b"# a sibling repository's file\n")
        target = f"../{outside.parent.name}/{outside.name}"
        root = self.declaring_projection(target)
        # The escape is relative to the repository root, whose parent is the
        # temp directory holding both fixtures.
        link = root.parent / outside.parent.name
        if not link.exists():
            link.symlink_to(outside.parent, target_is_directory=True)
        doc, out = self.plan(root)
        self.assertIsNone(self.regeneration(doc, target)["before"])
        self.assertNotIn(sha256_hash(outside.read_bytes()), out)

    def test_a_contained_target_is_still_hashed(self):
        """The control: an ordinary target inside the root keeps its
        `before`, so the guards above refuse the right paths, not all of
        them."""
        doc, _ = self.plan(nix_config_shape_repo(self.home))
        for target in ("AGENTS.md", "CLAUDE.md"):
            with self.subTest(target=target):
                self.assertIsNotNone(self.regeneration(doc, target)["before"])


if __name__ == "__main__":
    unittest.main()
