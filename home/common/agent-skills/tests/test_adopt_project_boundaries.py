"""Boundary and installation invariants of `adopt-project` that its main
suite's fixtures cannot reach.

`test_adopt_project.py` is the adoption suite; these cases live beside it
because that file is the review package's binding member and adding them there
would leave no room for the `apply` and `verify` suites. The fixtures and the
temporary-`HOME` isolation are imported from it, so both files build their
repositories the same way; no `TestCase` crosses over, so neither file collects
the other's tests.

The invariants:

1. The `/platform` violation exemption may only forgive what the planned
   amendment actually writes. `amended_contract` adds the member when it is
   absent and never rewrites an authored interval, so a present-but-wrong one
   is a violation that keeps the plan out of `ready` — not a false `passed`.
2. The projections loop holds the only variable path this planner reads. It
   comes from the authored contract, which is consumed whether or not the
   resolver accepted it, so the containment and secret-marker guards are
   applied there rather than assumed.
3. A stored plan is bound to the checkout it was derived from. The content
   address excludes the absolute path on purpose (D15), so two checkouts of
   one revision share an id and therefore a stored document; the binding is
   what stops an approval given for one from being applied to the other.
4. A git path is a byte string. One that is not UTF-8 is still a path this
   planner classifies, fingerprints and moves, not an internal failure.
5. The library guard is only as wide as its member tuple and only as strict as
   what it checks about the module it found.
6. An authored JSON file is rewritten only when its value changes. A contract
   or a legacy binding config that already holds the amended value, in any
   formatting, is not work: counting it as work would make `no_change`
   unreachable for every hand-formatted checkout.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# The sibling suite is imported as a module, so its directory has to be
# importable however this file was invoked — `python3 <path>` supplies it,
# `python3 -m unittest <path>` does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_adopt_project import (
    ADOPT_LIBRARIES,
    LIBRARY,
    SCRIPT,
    adopted_repo,
    bootstrap_repo,
    commit,
    declared_members,
    git,
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


class PlanClaimTest(BoundaryTestCase):
    """A stored plan stays bound to the checkout it was derived from.

    D15 keeps the absolute checkout path out of the content address on
    purpose, so two checkouts of one revision hash to one `plan_id` and name
    one stored document at one path. `apply` takes nothing but that id (D16)
    and reads its target out of that document, so letting a second checkout
    overwrite `handoff.repo_root` would carry an approval given for the first
    one out against the second, with nothing on screen to say so.
    """

    def copy_of(self, root: Path) -> Path:
        other = Path(tempfile.mkdtemp()).resolve() / "copy"
        shutil.copytree(root, other)
        return other

    def stored(self, plan_id: str) -> dict:
        path = (self.home / ".agents" / "state" / "adopt" / "plans"
                / (plan_id.split(":", 1)[1] + ".json"))
        return json.loads(path.read_text("utf-8"))

    def test_a_second_checkout_is_refused_and_never_repoints_the_plan(self):
        root = nix_config_shape_repo(self.home)
        first, _ = self.plan(root)
        other = self.copy_of(root)
        code, out, err = run("plan", "--repo-root", str(other), home=self.home)
        self.assertEqual(code, 2, err or out)
        error = json.loads(out)["error"]
        self.assertEqual(error["code"], "adopt_failure")
        self.assertEqual(error["repair_id"], "adopt.plan.repo_root_claimed")
        self.assertTrue(error["violations"])
        # The refusal is the point only if the first plan survived it intact.
        self.assertEqual(self.stored(first["plan"]["plan_id"]), first)

    def test_replanning_the_one_checkout_stays_idempotent(self):
        """The control: the claim is about a second checkout, not about a
        second run."""
        root = nix_config_shape_repo(self.home)
        _, first = self.plan(root)
        _, second = self.plan(root)
        self.assertEqual(first, second)


class SemanticRewriteTest(BoundaryTestCase):
    """A rewrite is planned for a changed value, never for formatting alone."""

    def assert_no_change(self, root: Path) -> None:
        doc, _ = self.plan(root)
        self.assertEqual(doc["plan"]["outcome"], "no_change", doc["changes"])
        self.assertEqual(doc["plan"]["state"], "not_applicable")
        self.assertEqual(doc["changes"], [])

    def test_a_reformatted_conformant_contract_is_no_change(self):
        root = adopted_repo(self.home)
        write(root, CONTRACT,
              json.dumps(self.contract_of(root), indent=4) + "\n")
        commit(root, "reformat the contract")
        self.assert_no_change(root)

    def test_a_reformatted_legacy_config_in_agreement_is_no_change(self):
        root = adopted_repo(self.home)
        paths = self.contract_of(root)["bindings"]["paths"]
        write(root, ".claude/skills.config.json", json.dumps({
            "specDir": paths["artifacts"]["specs"],
            "planDir": paths["artifacts"]["plans"],
            "rejectionsDir": paths["rejections"][0],
        }) + "\n")
        commit(root, "a legacy config already in agreement")
        self.assert_no_change(root)


class UndecodablePathTest(BoundaryTestCase):
    """A git path is a byte string, and this platform cannot always decode it.

    Every path reaches classification decoded `surrogateescape`, so a valid
    non-UTF-8 filename arrives as a string carrying lone surrogates. It has to
    be classified, fingerprinted, written into the migration map and moved like
    any other path: a strict encode anywhere on that route raises, and the
    raise reaches the caller as `adopt.internal` rather than as anything anyone
    decided.

    The paths are staged into the index rather than created on disk, because
    APFS rejects a filename that is not valid UTF-8 — and the index is where
    the inspection reads tracked paths from in any case (R4.2).
    """

    UNDECODABLE = "\udcff"

    def stage(self, root: Path, relative: str, content: bytes) -> None:
        blob = subprocess.run(
            ["git", "-C", str(root), "hash-object", "-w", "--stdin"],
            input=content, capture_output=True, check=True,
            timeout=60).stdout.decode("ascii").strip()
        subprocess.run(
            ["git", "-C", str(root), "update-index", "--add", "--cacheinfo",
             f"100644,{blob},{relative}"],
            capture_output=True, check=True, timeout=60)

    def entry(self, doc: dict, path: str) -> dict:
        for candidate in doc["evidence"]:
            if candidate["path"] == path:
                return candidate
        raise AssertionError(f"no evidence entry for {path!r}")

    def test_an_undecodable_path_is_classified_hashed_and_moved(self):
        root = nix_config_shape_repo(self.home)
        moved = f".claude/specs/{self.UNDECODABLE}.md"
        secret = f".claude/specs/secrets/{self.UNDECODABLE}.md"
        self.stage(root, moved, b"# an undecodable spec\n")
        self.stage(root, secret, b"API_TOKEN=nope\n")
        # Not `commit()`: `git add -A` would drop both index entries again,
        # since neither path can exist in the working tree.
        git(root, "commit", "--quiet", "-m", "two undecodable paths")
        doc, out = self.plan(root)
        moves = [op for op in doc["changes"]
                 if op["op"] == "git-mv" and op["sources"] == [moved]]
        self.assertEqual(len(moves), 1, doc["changes"])
        self.assertEqual(moves[0]["targets"],
                         [f".agents/artifacts/specs/{self.UNDECODABLE}.md"])
        # The group it belongs to is still fingerprinted over its members.
        self.assertTrue(
            self.entry(doc, ".claude/specs")["fingerprint"].startswith(
                "sha256:"))
        # And the secret-shaped rule still lifts it out, unread and unhashed.
        record = self.entry(doc, secret)
        self.assertEqual(record["lifecycle_class"], "secret-shaped")
        self.assertIsNone(record["fingerprint"])
        self.assertNotIn("API_TOKEN", out)
        self.assertNotIn(secret, [op["sources"][0] for op in doc["changes"]
                                  if op["op"] == "git-mv"])


class LibraryBindingTest(unittest.TestCase):
    """The member guard is only as wide as its tuple and only as strict as
    what it checks about the module the import found.

    Both cases run a copy of the binary from `$HOME/.agents/bin`, the deployed
    layout, because in the repository checkout every library is the script's
    own sibling and a run from `scripts/` imports them whatever `HOME` says.
    """

    def run_deployed(self, home: Path, root: Path,
                     pythonpath: str | None = None) -> tuple[int, str, str]:
        binary = home / ".agents" / "bin" / "adopt-project"
        binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SCRIPT, binary)
        env = {**os.environ, "HOME": str(home)}
        # The runner's own `PYTHONPATH` is not the deployed machine's; each
        # case states the one it means to present.
        env.pop("PYTHONPATH", None)
        if pythonpath is not None:
            env["PYTHONPATH"] = pythonpath
        proc = subprocess.run(
            [sys.executable, str(binary), "plan", "--repo-root", str(root)],
            capture_output=True, text=True, timeout=300, cwd=str(home),
            env=env)
        return proc.returncode, proc.stdout, proc.stderr

    def uninstall(self, home: Path, names: tuple[str, ...]) -> Path:
        """Move the named libraries out of the installed directory, and return
        the importable directory they were moved to."""
        elsewhere = Path(tempfile.mkdtemp()).resolve()
        installed = home / ".agents" / "lib" / "python"
        for name in names:
            shutil.move(str(installed / f"{name}.py"),
                        str(elsewhere / f"{name}.py"))
        return elsewhere

    def assert_refusal(self, code: int, out: str, err: str,
                       repair_id: str) -> None:
        self.assertEqual(code, 2, err or out)
        self.assertEqual(err, "")
        error = json.loads(out)["error"]
        self.assertEqual(sorted(error), ["code", "repair_id", "violations"])
        self.assertEqual(error["code"], "adopt_failure")
        self.assertEqual(error["repair_id"], repair_id)
        self.assertTrue(error["violations"])

    def test_the_platform_tuple_is_exactly_the_members_the_five_files_use(self):
        """`resolve-project.py` pins its own tuple this way; the adoption
        binary declares one for itself and its four libraries, every one of
        which imports `agent_platform` directly."""
        used: set[str] = set()
        for path in (SCRIPT, *ADOPT_LIBRARIES.values()):
            used |= set(re.findall(
                r"\bagent_platform\.([A-Za-z_][A-Za-z0-9_]*)",
                path.read_text("utf-8")))
        # The library's file name appears in the refusal message, not as an
        # attribute read.
        used.discard("py")
        self.assertEqual(sorted(declared_members("PLATFORM_LIBRARY_MEMBERS")),
                         sorted(used))

    def test_an_importable_platform_library_is_not_an_installed_one(self):
        """Nothing is installed at the one path, and an `agent_platform` the
        interpreter can still reach must not answer in its place."""
        home = make_home()
        root = bootstrap_repo(home)
        elsewhere = self.uninstall(home, ("agent_platform",))
        self.assert_refusal(
            *self.run_deployed(home, root, pythonpath=str(elsewhere)),
            repair_id="platform.library.missing")

    def test_importable_adoption_libraries_are_not_installed_ones(self):
        """The same for the four, with the platform library left installed so
        only their own half of the guard can refuse."""
        home = make_home()
        root = bootstrap_repo(home)
        elsewhere = self.uninstall(home, tuple(ADOPT_LIBRARIES))
        self.assert_refusal(
            *self.run_deployed(home, root, pythonpath=str(elsewhere)),
            repair_id="adopt.library.missing")

    def test_the_installed_libraries_still_answer(self):
        """The control: the same run with everything installed, and the
        importable copies still on `PYTHONPATH` behind them."""
        home = make_home()
        root = bootstrap_repo(home)
        elsewhere = Path(tempfile.mkdtemp()).resolve()
        for name, source in (("agent_platform", LIBRARY),
                             *ADOPT_LIBRARIES.items()):
            shutil.copy(source, elsewhere / f"{name}.py")
        code, out, err = self.run_deployed(home, root,
                                           pythonpath=str(elsewhere))
        self.assertEqual(code, 0, err or out)
        self.assertEqual(json.loads(out)["plan"]["outcome"], "bootstrap")



if __name__ == "__main__":
    unittest.main()
