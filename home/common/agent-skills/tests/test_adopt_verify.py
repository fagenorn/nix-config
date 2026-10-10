"""Contract tests for `adopt-project verify` and the fleet registry.

`verify` is the read-only conformance verb and, with `--register`, the one
writer of `~/.agents/state/fleet/registry.json`. The cases below are therefore
two suites in one: the conformance report and its evidence-record discovery
(D34), and the locked registration transaction whose far side is
`resolve-project platform-status --fleet` (D18, D19).

They live beside `test_adopt_project.py` rather than inside it because that
file is the review package's binding member; the fixtures, the
temporary-`HOME` isolation and the git helper are imported from it and from
`test_adopt_apply.py`, and no `TestCase` crosses over, so no file collects
another's tests (the pattern `test_adopt_project_boundaries.py` established).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools import adopt_verify
from agent_tools.adopt_inspection import AdoptError

from .test_adopt_project import (
    EVIDENCE_RECORD_MEMBERS,
    commit,
    adopted_repo,
    fixture_contract,
    git,
    init_repo,
    make_home,
    reconcile_repo,
    run,
    scaffold,
    tree_snapshot,
    write,
    write_adoption_records,
)
from .test_adopt_apply import apply_repo, readoption_repo

VERIFY_MEMBERS = ["adoption_commit", "blockers", "checks", "evidence_record",
                  "migration_map", "project_id", "registered", "result",
                  "revision", "root", "schema_version"]
CHECK_IDS = ["contract-resolves", "projections-in-sync",
             "no-unclassified-agent-path", "adoption-evidence-record",
             "adoption-commit-derived", "path-migration-map"]


def verifiable_repo(home: Path, *, project_id: str = "fixture/target",
                    tracker_cli: str = "gh",
                    integration_branch: str = "main") -> Path:
    """A conformant checkout carrying the two adoption records, on `main`.

    The identity, the tracker binary and the declared integration branch are
    the knobs the cases below need: distinct ids for the registry, a tracker
    CLI that cannot resolve for the `adopted_with_blockers` verdict, and a
    contract that names a branch other than the remote default.
    """
    root = init_repo()
    contract = fixture_contract()
    contract["project"] = {"id": project_id, "name": project_id.split("/")[-1]}
    contract["bindings"]["tracker"]["cli"] = tracker_cli
    contract["bindings"]["vcs"]["integration_branch"] = integration_branch
    # This repository's GitHub release profile derives a `blocked` release
    # capability on any host without the forge adapter's executables on PATH;
    # no verify case is about release, so the fixture opts out of it to keep the
    # verdicts host-independent.
    contract["release"] = "unsupported"
    scaffold(root, contract, home)
    write(root, ".agents/runtime/.gitignore", "*\n")
    git(root, "add", "-f", ".agents/runtime/.gitignore")
    # A cold export carries tracked files only: an empty standards directory
    # would read as a missing knowledge path under `--register`.
    for standards in contract["bindings"]["paths"]["standards"]:
        write(root, f"{standards}/bar.md", "# the bar\n")
    commit(root)
    write_adoption_records(root)
    commit(root, "adopt")
    return root


def publish(root: Path, refs: tuple[str, ...] = ("main",), *,
            default: str = "main") -> Path:
    """A local bare `origin` holding `refs`, its `HEAD` naming `default`.

    Each entry is `src` (pushed to the same-named branch) or `src:branch`,
    where `src` is any local revision. `origin` is re-pointed when it exists:
    plan identity derives from the GitHub URL the fixtures add (#148 D35), so
    it is re-pointed only after `plan`/`apply`.
    """
    bare = Path(tempfile.mkdtemp()).resolve() / "origin.git"
    git(bare.parent, "init", "--quiet", "--bare", "-b", default, str(bare))
    verb = "set-url" if "origin" in git(root, "remote").split() else "add"
    git(root, "remote", verb, "origin", str(bare))
    specs = []
    for ref in refs:
        src, _, branch = ref.partition(":")
        specs.append(f"{src}:refs/heads/{branch or src}")
    git(root, "push", "--quiet", "origin", *specs)
    return bare


class VerifyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = make_home()

    # -- running ----------------------------------------------------------

    def verify(self, root: Path, *extra: str) -> tuple[int, object, str]:
        code, out, err = run("verify", "--repo-root", str(root), *extra,
                             home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def report(self, root: Path, *extra: str) -> dict:
        code, payload, err = self.verify(root, *extra)
        self.assertEqual(code, 0, err or payload)
        return payload

    def refuse(self, root: Path, code: str, *extra: str) -> dict:
        exit_code, payload, err = self.verify(root, *extra)
        self.assertEqual(exit_code, 2, err or payload)
        self.assertEqual(payload["error"]["code"], code, payload)
        self.assertTrue(payload["error"]["violations"])
        return payload

    def check(self, report: dict, check_id: str) -> dict:
        found = [entry for entry in report["checks"]
                 if entry["id"] == check_id]
        self.assertEqual(len(found), 1, report["checks"])
        return found[0]

    # -- the registry -----------------------------------------------------

    def registry_path(self) -> Path:
        return self.home / ".agents" / "state" / "fleet" / "registry.json"

    def registry(self) -> object:
        return json.loads(self.registry_path().read_text("utf-8"))

    def fleet(self) -> list[dict]:
        proc = subprocess.run(
            [sys.executable, "-m", "agent_tools.resolve_project", "platform-status", "--fleet"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(proc.returncode, 0, proc.stdout)
        return json.loads(proc.stdout)["fleet"]


# --------------------------------------------------------------------------
# The read-only report
# --------------------------------------------------------------------------


class VerifyReadOnlyTest(VerifyTestCase):
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

    def test_a_conformant_checkout_is_adopted_and_writes_nothing(self):
        root = adopted_repo(self.home)
        before_status = git(root, "status", "--porcelain")
        before_tree = tree_snapshot(root)
        report = self.report(root)
        self.assertEqual(report["result"], "adopted", report)
        self.assertEqual(sorted(report), VERIFY_MEMBERS)
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["revision"], {
            "ref": "HEAD",
            "commit": git(root, "rev-parse", "HEAD").strip(),
        })
        self.assertEqual(report["project_id"], "fixture/target")
        self.assertEqual(report["root"], str(root))
        self.assertEqual(report["blockers"], [])
        self.assertIs(report["registered"], False)
        self.assertEqual([entry["id"] for entry in report["checks"]],
                         CHECK_IDS)
        self.assertEqual(
            sorted({entry["status"] for entry in report["checks"]}),
            ["passed"])
        # The three independent witnesses of D21, plus the registry: read-only
        # `verify` stores no snapshot and creates no fleet file.
        self.assertEqual(git(root, "status", "--porcelain"), before_status)
        self.assertEqual(tree_snapshot(root), before_tree)
        self.assertFalse(self.registry_path().exists())

    def test_the_adoption_commit_is_the_commit_that_added_the_record(self):
        root = adopted_repo(self.home)
        introduced = git(root, "rev-parse", "HEAD").strip()
        write(root, "later.md", "# later\n")
        commit(root, "unrelated")
        report = self.report(root)
        self.assertEqual(report["adoption_commit"], introduced)
        self.assertNotEqual(report["adoption_commit"],
                            git(root, "rev-parse", "HEAD").strip())
        self.assertEqual(report["evidence_record"],
                         f".agents/artifacts/evidence/{'a1' * 32}.json")
        self.assertEqual(
            report["migration_map"],
            f".agents/knowledge/archive/path-migrations/{'a1' * 32}.json")

    def test_a_drifted_projection_is_not_conformant_and_names_it(self):
        root = adopted_repo(self.home)
        write(root, "AGENTS.md", "hand-edited\n")
        report = self.report(root)
        self.assertEqual(report["result"], "not_conformant", report)
        drift = self.check(report, "projections-in-sync")
        self.assertEqual(drift["status"], "failed")
        self.assertIn("codex.entry", drift["detail"])
        self.assertIs(report["registered"], False)

    def test_a_blocked_capability_is_adopted_with_blockers(self):
        root = verifiable_repo(self.home, tracker_cli="no-such-tracker-cli")
        report = self.report(root)
        self.assertEqual(report["result"], "adopted_with_blockers", report)
        self.assertEqual(report["blockers"], [{
            "capability": "tracker",
            "repair_id": "capability.tracker.tracker_cli_missing",
        }])
        self.assertEqual(
            sorted({entry["status"] for entry in report["checks"]}),
            ["passed"])

    def test_a_repository_without_a_contract_is_not_conformant(self):
        root = reconcile_repo(self.home)
        report = self.report(root)
        self.assertEqual(report["result"], "not_conformant", report)
        contract = self.check(report, "contract-resolves")
        self.assertEqual(contract["status"], "failed")
        self.assertIn("not_onboarded", contract["detail"])
        # A refusal that is not about projections must not be reported as
        # drift: `not_onboarded` carries one empty violation pointer, which
        # once read as a drift list produced a dangling, false claim.
        projections = self.check(report, "projections-in-sync")
        self.assertEqual(projections["status"], "failed")
        self.assertNotIn("drifted", projections["detail"])
        self.assertIn("not_onboarded", projections["detail"])
        self.assertIsNone(report["project_id"])

    def test_a_plain_directory_is_not_a_repository(self):
        self.refuse(Path(tempfile.mkdtemp()), "not_a_repository")


# --------------------------------------------------------------------------
# Evidence-record discovery (D34)
# --------------------------------------------------------------------------


class EvidenceDiscoveryTest(VerifyTestCase):
    def not_conformant(self, root: Path) -> dict:
        report = self.report(root)
        self.assertEqual(report["result"], "not_conformant", report)
        return report

    def test_no_record_at_all_names_the_absence(self):
        report = self.not_conformant(adopted_repo(self.home, records=False))
        entry = self.check(report, "adoption-evidence-record")
        self.assertEqual(entry["status"], "failed")
        self.assertIn("no adoption evidence record", entry["detail"])
        self.assertIsNone(report["adoption_commit"])
        self.assertEqual(
            self.check(report, "adoption-commit-derived")["status"], "not_run")

    def test_a_record_that_is_not_valid_json_is_not_conformant(self):
        root = adopted_repo(self.home, records=False)
        write(root, ".agents/artifacts/evidence/broken.json", "{not json")
        commit(root, "broken record")
        report = self.not_conformant(root)
        self.assertIn("does not parse",
                      self.check(report, "adoption-evidence-record")["detail"])

    def test_a_record_missing_a_required_member_is_not_conformant(self):
        root = adopted_repo(self.home, records=False)
        record = {name: None for name in EVIDENCE_RECORD_MEMBERS}
        del record["path_migration_map"]
        write(root, ".agents/artifacts/evidence/partial.json",
              json.dumps(record) + "\n")
        commit(root, "partial record")
        report = self.not_conformant(root)
        self.assertIn("does not parse",
                      self.check(report, "adoption-evidence-record")["detail"])

    def test_two_committed_records_name_the_ambiguity(self):
        root = adopted_repo(self.home)
        write_adoption_records(root, digest="b2" * 32)
        commit(root, "a second adoption record")
        report = self.not_conformant(root)
        entry = self.check(report, "adoption-evidence-record")
        self.assertIn("more than one", entry["detail"])
        self.assertIsNone(report["adoption_commit"])

    def test_an_untracked_record_is_not_the_adoption_record(self):
        root = adopted_repo(self.home, records=False)
        write_adoption_records(root)
        report = self.not_conformant(root)
        self.assertIn("no adoption evidence record",
                      self.check(report, "adoption-evidence-record")["detail"])

    def test_a_record_naming_an_absent_migration_map_is_not_conformant(self):
        root = adopted_repo(self.home, records=False)
        write_adoption_records(root)
        (root / ".agents" / "knowledge" / "archive" / "path-migrations"
         / f"{'a1' * 32}.json").unlink()
        commit(root, "record without its map")
        report = self.not_conformant(root)
        entry = self.check(report, "path-migration-map")
        self.assertEqual(entry["status"], "failed")
        self.assertIn("path migration map", entry["detail"])


class AnsweredCandidateVerifyTest(VerifyTestCase):
    def test_an_archived_candidate_verifies_as_adopted(self):
        root = apply_repo(self.home)
        write(root, ".claude/odd.md", "# odd\n")
        commit(root, "add an unclassified agent path")
        code, out, err = run("plan", "--repo-root", str(root), "--answer",
                             "candidate-class", ".claude/odd.md",
                             "archive-history", home=self.home)
        self.assertEqual(code, 0, err or out)
        plan_id = json.loads(out)["plan"]["plan_id"]
        code, out, err = run("apply", "--plan-id", plan_id, home=self.home)
        self.assertEqual(code, 0, err or out)
        git(root, "merge", "--ff-only", "--quiet", json.loads(out)["branch"])
        report = self.report(root)
        self.assertEqual(report["result"], "adopted", report["checks"])
        self.assertEqual(
            self.check(report, "no-unclassified-agent-path")["status"],
            "passed")


# --------------------------------------------------------------------------
# Registration (D19, D18)
# --------------------------------------------------------------------------


class RegistrationTest(VerifyTestCase):
    def test_registration_after_the_merge_writes_exactly_two_members(self):
        root = apply_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err or out)
        plan_id = json.loads(out)["plan"]["plan_id"]
        code, out, err = run("apply", "--plan-id", plan_id, home=self.home)
        self.assertEqual(code, 0, err or out)
        git(root, "merge", "--ff-only", "--quiet", json.loads(out)["branch"])
        publish(root)
        report = self.report(root, "--register")
        self.assertEqual(report["result"], "adopted", report)
        self.assertEqual(report["revision"]["ref"], "refs/remotes/origin/main")
        self.assertIs(report["registered"], True)
        self.assertEqual(self.registry(), {
            "schema_version": 1,
            "projects": [{"project_id": "fixture/target", "root": str(root)}],
        })

    def test_a_merged_readoption_is_still_adopted_and_registers(self):
        """A second adoption supersedes the first record rather than adding a
        second one, so D34's exactly-one discovery still answers."""
        root, first = readoption_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err or out)
        plan_id = json.loads(out)["plan"]["plan_id"]
        code, out, err = run("apply", "--plan-id", plan_id,
                             "--acknowledge-deletions", home=self.home)
        self.assertEqual(code, 0, err or out)
        second = json.loads(out)
        git(root, "merge", "--ff-only", "--quiet", second["branch"])
        publish(root)
        report = self.report(root, "--register")
        self.assertEqual(report["result"], "adopted", report["checks"])
        self.assertEqual(report["evidence_record"], second["evidence_record"])
        self.assertNotEqual(report["evidence_record"],
                            first["evidence_record"])
        self.assertEqual(report["adoption_commit"], second["commit"])
        self.assertIs(report["registered"], True)

    def test_a_second_identical_registration_is_byte_identical(self):
        root = verifiable_repo(self.home)
        publish(root)
        self.report(root, "--register")
        first = self.registry_path().read_bytes()
        self.report(root, "--register")
        self.assertEqual(self.registry_path().read_bytes(), first)

    def test_the_same_id_at_another_root_refuses_and_changes_nothing(self):
        root = verifiable_repo(self.home)
        publish(root)
        self.report(root, "--register")
        before = self.registry_path().read_bytes()
        other = verifiable_repo(self.home)
        publish(other)
        self.refuse(other, "duplicate_project_id", "--register")
        self.assertEqual(self.registry_path().read_bytes(), before)

    def test_registration_needs_a_conformant_checkout(self):
        root = verifiable_repo(self.home)
        write(root, "AGENTS.md", "hand-edited\n")
        commit(root, "drift a projection")
        publish(root)
        report = self.report(root, "--register")
        self.assertEqual(report["result"], "not_conformant", report)
        self.assertIs(report["registered"], False)
        self.assertFalse(self.registry_path().exists())

    def test_two_projects_are_stored_ordered_by_project_id(self):
        beta = verifiable_repo(self.home, project_id="fixture/beta")
        publish(beta)
        alpha = verifiable_repo(self.home, project_id="fixture/alpha")
        publish(alpha)
        self.report(beta, "--register")
        self.report(alpha, "--register")
        self.assertEqual(
            [entry["project_id"] for entry in self.registry()["projects"]],
            ["fixture/alpha", "fixture/beta"])

    def test_two_concurrent_registrations_both_survive(self):
        alpha = verifiable_repo(self.home, project_id="fixture/alpha")
        publish(alpha)
        beta = verifiable_repo(self.home, project_id="fixture/beta")
        publish(beta)
        environment = {**os.environ, "HOME": str(self.home)}
        processes = [
            subprocess.Popen(
                [sys.executable, "-m", "agent_tools.adopt_project",
                 "verify", "--repo-root", str(root), "--register"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=environment)
            for root in (alpha, beta)
        ]
        results = [process.communicate() for process in processes]
        for process, (out, err) in zip(processes, results):
            self.assertEqual(process.returncode, 0, err or out)
            self.assertIs(json.loads(out)["registered"], True)
        self.assertEqual(self.registry(), {
            "schema_version": 1,
            "projects": [
                {"project_id": "fixture/alpha", "root": str(alpha)},
                {"project_id": "fixture/beta", "root": str(beta)},
            ],
        })

    def test_the_resolver_lists_the_registered_project_as_compatible(self):
        root = verifiable_repo(self.home)
        publish(root)
        self.report(root, "--register")
        self.assertEqual(self.fleet(), [{
            "project_id": "fixture/target",
            "root": str(root),
            "project_schema_version": 1,
            "platform_interval": {"min_inclusive": "1.0.0",
                                  "max_exclusive": "2.0.0"},
            "compatible": True,
            "reason_code": None,
            "repair_id": None,
        }])


class RemoteRegistrationTest(VerifyTestCase):
    def refuse_with(self, root: Path, code: str, repair_id: str) -> None:
        payload = self.refuse(root, code, "--register")
        self.assertEqual(payload["error"]["repair_id"], repair_id, payload)
        self.assertFalse(self.registry_path().exists())

    def test_registration_follows_the_contracts_integration_branch(self):
        root = verifiable_repo(self.home, integration_branch="dev")
        adoption = git(root, "rev-parse", "HEAD").strip()
        # The remote default carries the contract (naming `dev`) but not the
        # adoption; `dev` carries both.
        publish(root, ("HEAD~1:main", "main:dev"))
        report = self.report(root, "--register")
        self.assertEqual(report["result"], "adopted", report["checks"])
        self.assertIs(report["registered"], True)
        self.assertEqual(report["revision"], {
            "ref": "refs/remotes/origin/dev", "commit": adoption})
        self.assertEqual(
            git(root, "rev-parse", "refs/remotes/origin/dev").strip(), adoption)
        self.assertEqual(self.registry()["projects"], [
            {"project_id": "fixture/target", "root": str(root)}])

    def test_an_integration_branch_missing_on_origin_refuses(self):
        root = verifiable_repo(self.home, integration_branch="dev")
        publish(root, ("HEAD~1:main",))
        self.refuse_with(root, "not_integrated",
                         "adopt.registration.integration_branch_unresolved")

    def test_a_second_branch_mismatch_refuses(self):
        root = verifiable_repo(self.home, integration_branch="dev")
        contract = json.loads(
            (root / ".agents" / "project.json").read_text("utf-8"))
        contract["bindings"]["vcs"]["integration_branch"] = "release"
        write(root, ".agents/project.json", json.dumps(contract, indent=2) + "\n")
        commit(root, "contract names release")
        # origin/main names dev; origin/dev names release: no second hop.
        publish(root, ("HEAD~2:main", "HEAD:dev", "HEAD:release"))
        self.refuse_with(root, "not_integrated",
                         "adopt.registration.integration_branch_unresolved")

    def test_a_diverged_local_branch_registers_from_the_remote(self):
        root = init_repo()
        write(root, "README.md", "# before adoption\n")
        commit(root, "base")
        base = git(root, "rev-parse", "HEAD").strip()
        contract = fixture_contract()
        # Opt out of the host-dependent release profile, as `verifiable_repo` does.
        contract["release"] = "unsupported"
        scaffold(root, contract, self.home)
        for standards in contract["bindings"]["paths"]["standards"]:
            write(root, f"{standards}/bar.md", "# the bar\n")
        write(root, ".agents/runtime/.gitignore", "*\n")
        git(root, "add", "-f", ".agents/runtime/.gitignore")
        commit(root, "contract")
        write_adoption_records(root)
        commit(root, "adopt")
        adoption = git(root, "rev-parse", "HEAD").strip()
        # Freshness (PR-02): origin first holds only `base`, pushed from this
        # checkout, so its `refs/remotes/origin/main` is stale; the adoption
        # then advances on origin itself, never through a push that updates
        # `root`'s remote-tracking ref.
        bare = publish(root, ("HEAD~2:main",))
        stale = git(root, "rev-parse", "refs/remotes/origin/main").strip()
        git(root, "push", "--quiet", "origin", f"{adoption}:refs/staging/adopt")
        git(bare, "update-ref", "refs/heads/main", adoption)
        self.assertNotEqual(stale, adoption)
        # Diverge: local main falls behind the adoption (no contract at all),
        # gains unpushed work, an unstaged edit and an untracked file.
        git(root, "reset", "--quiet", "--hard", base)
        write(root, "user-work.md", "# unpushed\n")
        commit(root, "unpushed user work")
        write(root, "README.md", "# unstaged edit\n")
        untracked = write(root, "scratch.txt", "untracked bytes\n")
        local_main = git(root, "rev-parse", "refs/heads/main").strip()
        status = git(root, "status", "--porcelain")
        snapshot = tree_snapshot(root)

        report = self.report(root, "--register")

        self.assertEqual(report["result"], "adopted", report["checks"])
        self.assertIs(report["registered"], True)
        self.assertEqual(report["revision"], {
            "ref": "refs/remotes/origin/main", "commit": adoption})
        self.assertEqual(report["adoption_commit"], adoption)
        self.assertEqual(report["evidence_record"],
                         f".agents/artifacts/evidence/{'a1' * 32}.json")
        self.assertEqual(report["root"], str(root))
        self.assertEqual(self.registry()["projects"], [
            {"project_id": "fixture/target", "root": str(root)}])
        self.assertEqual(git(root, "rev-parse", "refs/heads/main").strip(),
                         local_main)
        self.assertEqual(git(root, "status", "--porcelain"), status)
        self.assertEqual(tree_snapshot(root), snapshot)
        self.assertEqual(untracked.read_text("utf-8"), "untracked bytes\n")
        self.assertFalse((root / ".git" / "FETCH_HEAD").exists())
        self.assertEqual(
            git(root, "rev-parse", "refs/remotes/origin/main").strip(), adoption)
        plain = self.report(root)
        self.assertEqual(plain["result"], "not_conformant", plain)
        self.assertEqual(plain["revision"]["ref"], "HEAD")

    def test_an_unpushed_adoption_refuses_not_integrated(self):
        root = verifiable_repo(self.home)
        publish(root, ("HEAD~1:main",))
        self.assertEqual(self.report(root)["result"], "adopted")
        self.refuse_with(root, "not_integrated",
                         "adopt.registration.not_integrated")

    def test_an_adoption_only_on_its_apply_branch_refuses_not_integrated(self):
        root = apply_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err or out)
        plan_id = json.loads(out)["plan"]["plan_id"]
        code, out, err = run("apply", "--plan-id", plan_id, home=self.home)
        self.assertEqual(code, 0, err or out)
        branch = json.loads(out)["branch"]
        publish(root)
        git(root, "checkout", "--quiet", branch)
        self.assertEqual(self.report(root)["result"], "adopted")
        self.refuse_with(root, "not_integrated",
                         "adopt.registration.not_integrated")

    def test_a_configured_fetch_mapping_cannot_move_a_local_branch(self):
        # PR-01: `--refmap=` disables configured `remote.origin.fetch`
        # mappings, so even one aimed at a local branch is not applied.
        root = verifiable_repo(self.home)
        publish(root)
        git(root, "branch", "keep", "HEAD~1")
        keep = git(root, "rev-parse", "refs/heads/keep").strip()
        git(root, "config", "--add", "remote.origin.fetch",
            "+refs/heads/main:refs/heads/keep")
        report = self.report(root, "--register")
        self.assertIs(report["registered"], True)
        self.assertEqual(git(root, "rev-parse", "refs/heads/keep").strip(), keep)

    def test_no_origin_refuses_not_integrated(self):
        self.refuse_with(verifiable_repo(self.home), "not_integrated",
                         "adopt.registration.no_remote")

    def test_an_origin_without_a_default_branch_refuses_not_integrated(self):
        root = verifiable_repo(self.home)
        bare = Path(tempfile.mkdtemp()).resolve() / "empty.git"
        git(bare.parent, "init", "--quiet", "--bare", "-b", "main", str(bare))
        git(root, "remote", "add", "origin", str(bare))
        self.refuse_with(root, "not_integrated",
                         "adopt.registration.remote_default_unknown")

    def test_an_unreachable_origin_refuses_adopt_failure(self):
        root = verifiable_repo(self.home)
        git(root, "remote", "add", "origin",
            str(Path(tempfile.mkdtemp()).resolve() / "missing.git"))
        self.refuse_with(root, "adopt_failure", "adopt.git.remote_unreachable")


class RegisterProjectInnerCheckTest(VerifyTestCase):
    """The inner checks of D7, which no CLI path reaches: walking from the
    pinned commit already makes them hold for every CLI registration."""

    def attempt(self, root: Path, adoption: str, contract_branch: str,
                pinned: str) -> AdoptError:
        source = adopt_verify.VerificationSource(
            ref="refs/remotes/origin/main", commit=pinned,
            resolver_root=root, inventory=[], branch="main")
        verification = adopt_verify.Verification(
            {"project_id": "fixture/target", "adoption_commit": adoption,
             "registered": False},
            {"bindings": {"vcs": {"integration_branch": contract_branch}}},
            source, [f".agents/artifacts/evidence/{'a1' * 32}.json"])
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            with self.assertRaises(AdoptError) as caught:
                adopt_verify.register_project(root, verification)
        self.assertFalse(self.registry_path().exists())
        return caught.exception

    def test_an_adoption_commit_off_the_pinned_commit_refuses(self):
        root = verifiable_repo(self.home)
        pinned = git(root, "rev-parse", "HEAD").strip()
        git(root, "checkout", "--quiet", "-b", "side", "HEAD~1")
        write(root, "side.md", "# side\n")
        commit(root, "side")
        side = git(root, "rev-parse", "HEAD").strip()
        error = self.attempt(root, side, "main", pinned)
        self.assertEqual((error.code, error.repair_id),
                         ("not_integrated", "adopt.registration.not_integrated"))

    def test_a_contract_naming_another_branch_refuses(self):
        root = verifiable_repo(self.home)
        pinned = git(root, "rev-parse", "HEAD").strip()
        error = self.attempt(root, pinned, "dev", pinned)
        self.assertEqual(
            (error.code, error.repair_id),
            ("not_integrated", "adopt.registration.integration_branch_unresolved"))


if __name__ == "__main__":
    unittest.main()
