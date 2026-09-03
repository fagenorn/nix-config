"""Contract tests for `adopt-project apply`.

`apply` is the destructive-adjacent verb: it creates a worktree, relocates
tracked files, writes generated records and produces one commit. Every refusal
in it is a safety property, so almost every case here is a refusal proved
against the three read-only witnesses of `test_adopt_project.py`.

The cases live beside that suite rather than inside it because it is the
review package's binding member; the fixtures, the temporary-`HOME` isolation
and the git helper are imported from it, and no `TestCase` crosses over, so
neither file collects the other's tests (the pattern
`test_adopt_project_boundaries.py` established).

The fixture repository is this repository's shape with two substitutions the
suite cannot do without: its `workflow.verification` names a trivial command
rather than `just build`, because the commit gates run every declared command
in full and refuse to be skipped; and one tracked file lives under the
declared standards path, so the cold-clone export — which carries tracked
content only — still resolves.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

# The sibling suite is imported as a module, so its directory has to be
# importable however this file was invoked — `python3 <path>` supplies it,
# `python3 -m unittest <path>` does not.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_adopt_project import (
    GITIGNORE_WITH_COMMENT,
    commit,
    fixture_contract,
    git,
    init_repo,
    make_home,
    run,
    scaffold,
    tree_snapshot,
    write,
)

CONTRACT = ".agents/project.json"
MOVED = {
    ".claude/specs/x.md": ".agents/artifacts/specs/x.md",
    ".claude/plans/y.md": ".agents/artifacts/plans/y.md",
    ".claude/plans/y.tasks/t1.md": ".agents/artifacts/plans/y.tasks/t1.md",
    ".out-of-scope/z.md": ".agents/knowledge/rejections/z.md",
}


def apply_repo(home: Path, *, verification: tuple[str, ...] = ("true",),
               signed: bool = False) -> Path:
    """This repository's shape at base, with cheap verification commands.

    A valid schema-1 contract without `platform`, the three legacy artifact
    trees, a `.claude/skills.config.json`, a `.gitignore` still carrying the
    runtime pattern, and no runtime sentinel — the `reconcile` shape whose plan
    reaches `ready`.
    """
    root = init_repo()
    contract = fixture_contract()
    contract["bindings"]["paths"]["artifacts"] = {
        "specs": ".claude/specs", "plans": ".claude/plans"}
    contract["bindings"]["paths"]["rejections"] = [".out-of-scope"]
    contract["bindings"]["commands"] = {
        "verify": {"argv": list(verification), "cwd": ".", "env": []},
        "review": {"argv": ["true"], "cwd": ".", "env": []},
    }
    contract["bindings"]["workflow"]["verification"] = ["verify"]
    contract["bindings"]["workflow"]["review"] = {
        "plan": "review", "code": "review"}
    contract["bindings"]["vcs"]["commit"] = {
        "co_authored_by": True, "signed": signed}
    scaffold(root, contract, home)
    # The projections were rendered from a contract that still declared
    # `platform`; dropping the member afterwards leaves them in sync, because a
    # projection is a pure function of its source, its id and the schema.
    without_platform = json.loads((root / CONTRACT).read_text("utf-8"))
    del without_platform["platform"]
    write(root, CONTRACT, json.dumps(without_platform, indent=2) + "\n")
    write(root, "home/common/agent-skills/standards/bar.md", "# the bar\n")
    for old in MOVED:
        write(root, old, f"# {old}\n")
    write(root, ".claude/skills.config.json", json.dumps(
        {"orchestration": {"agentBudgetMinutes": 180, "maxParallel": 2}},
        indent=2) + "\n")
    write(root, ".gitignore", GITIGNORE_WITH_COMMENT)
    git(root, "remote", "add", "origin",
        "https://github.com/fixture/target.git")
    commit(root)
    return root


class ApplyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = make_home()

    # -- planning ---------------------------------------------------------

    def ready_plan(self, root: Path) -> dict:
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err or out)
        document = json.loads(out)
        self.assertEqual(document["plan"]["state"], "ready",
                         document["plan"]["blockers"])
        return document

    # -- user-scope state -------------------------------------------------

    def digest(self, plan_id: str) -> str:
        return plan_id.split(":", 1)[1]

    def state(self, *parts: str) -> Path:
        return self.home.joinpath(".agents", "state", *parts)

    def stored_plan(self, plan_id: str) -> Path:
        return self.state("adopt", "plans", self.digest(plan_id) + ".json")

    def worktree(self, plan_id: str) -> Path:
        return self.state("adopt", "worktrees", self.digest(plan_id))

    def worktree_names(self) -> list[str]:
        """Every retained adoption worktree, however it was named.

        Asked this way rather than by plan id so a refusal over an id that is
        not a digest is held to the same standard: no worktree at all.
        """
        home = self.state("adopt", "worktrees")
        return sorted(entry.name for entry in home.iterdir()) \
            if home.is_dir() else []

    def rewrite_stored_plan(self, plan_id: str, document: dict) -> None:
        self.stored_plan(plan_id).write_text(
            json.dumps(document), encoding="utf-8")

    # -- running ----------------------------------------------------------

    def apply(self, plan_id: str, *extra: str) -> tuple[int, object, str]:
        code, out, err = run("apply", "--plan-id", plan_id, *extra,
                             home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def refuse(self, root: Path, plan_id: str, code: str,
               *extra: str) -> dict:
        """`apply` refuses with `code` and leaves the target byte-identical.

        The three independent witnesses of the resolver suite: the porcelain
        status bytes, the recursive path-and-type set outside `.git`, and the
        file mtimes. A branch or a retained worktree would also be a mutation,
        so both are asserted absent here.
        """
        before_status = git(root, "status", "--porcelain")
        before_tree = tree_snapshot(root)
        before_head = git(root, "rev-parse", "HEAD")
        before_branches = git(root, "branch", "--list")
        exit_code, payload, err = self.apply(plan_id, *extra)
        self.assertEqual(exit_code, 2, err or payload)
        self.assertEqual(payload["error"]["code"], code, payload)
        self.assertTrue(payload["error"]["violations"])
        self.assertEqual(git(root, "status", "--porcelain"), before_status)
        self.assertEqual(tree_snapshot(root), before_tree)
        self.assertEqual(git(root, "rev-parse", "HEAD"), before_head)
        self.assertEqual(git(root, "branch", "--list"), before_branches)
        self.assertEqual(self.worktree_names(), [])
        return payload

    def succeed(self, root: Path, plan_id: str, *extra: str) -> dict:
        exit_code, payload, err = self.apply(plan_id, *extra)
        self.assertEqual(exit_code, 0, err or payload)
        return payload

    def branch_files(self, root: Path, branch: str) -> list[str]:
        return git(root, "ls-tree", "-r", "--name-only", branch).split()

    def show(self, root: Path, revision: str) -> str:
        return git(root, "show", revision)


# --------------------------------------------------------------------------
# The successful adoption
# --------------------------------------------------------------------------


class ApplySuccessTest(ApplyTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = apply_repo(self.home)
        self.document = self.ready_plan(self.root)
        self.plan_id = self.document["plan"]["plan_id"]
        self.base = git(self.root, "rev-parse", "HEAD").strip()
        self.result = self.succeed(self.root, self.plan_id)
        self.branch = self.result["branch"]

    def test_the_result_names_the_branch_commit_plan_and_two_records(self):
        self.assertEqual(sorted(self.result),
                         ["branch", "commit", "evidence_record",
                          "migration_map", "plan_id"])
        self.assertEqual(self.result["plan_id"], self.plan_id)
        self.assertEqual(self.branch, f"adopt-{self.digest(self.plan_id)[:12]}")
        self.assertEqual(
            self.result["evidence_record"],
            self.document["handoff"]["evidence_record"])
        self.assertEqual(
            self.result["migration_map"],
            self.document["handoff"]["migration_map"])

    def test_exactly_one_commit_on_a_new_branch(self):
        self.assertEqual(
            git(self.root, "rev-parse", self.branch).strip(),
            self.result["commit"])
        self.assertEqual(
            git(self.root, "rev-list", "--count",
                f"{self.base}..{self.branch}").strip(), "1")

    def test_the_target_branch_never_moved(self):
        self.assertEqual(git(self.root, "rev-parse", "HEAD").strip(), self.base)
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_the_commit_message_is_the_fixed_derivation_with_no_co_author(self):
        message = git(self.root, "log", "-1", "--format=%B",
                      self.result["commit"])
        subject = message.splitlines()[0]
        self.assertEqual(
            subject,
            "chore(adopt): adopt fixture/target at plan "
            f"{self.digest(self.plan_id)[:12]}")
        self.assertIn(self.document["handoff"]["migration_map"], message)
        self.assertIn(self.document["handoff"]["evidence_record"], message)
        self.assertNotIn("Co-Authored-By", message)
        self.assertNotIn("Co-authored-by", message)

    def test_every_move_keeps_its_history_and_leaves_no_old_path(self):
        tracked = self.branch_files(self.root, self.branch)
        for old, new in MOVED.items():
            with self.subTest(old=old):
                self.assertIn(new, tracked)
                self.assertNotIn(old, tracked)
                history = git(self.root, "log", "--follow", "--format=%H",
                              self.branch, "--", new).split()
                self.assertEqual(len(history), 2, history)
                self.assertEqual(history[1], self.base)

    def test_the_commit_reports_renames_rather_than_add_plus_delete(self):
        status = git(self.root, "show", "--name-status", "-M",
                     "--format=", self.result["commit"])
        renamed = {line.split("\t")[1]: line.split("\t")[2]
                   for line in status.splitlines()
                   if line.startswith("R")}
        self.assertEqual({old: renamed[old] for old in MOVED}, dict(MOVED))

    def test_the_migration_map_lists_every_move_sorted_by_old_path(self):
        record = json.loads(git(
            self.root, "show",
            f"{self.branch}:{self.result['migration_map']}"))
        self.assertEqual(record["migration_id"], self.plan_id)
        self.assertEqual(
            record["moves"],
            [{"old_path": old, "new_path": MOVED[old]}
             for old in sorted(MOVED)])

    def test_the_evidence_record_is_committed_and_names_the_map(self):
        record = json.loads(git(
            self.root, "show",
            f"{self.branch}:{self.result['evidence_record']}"))
        self.assertEqual(record["plan_id"], self.plan_id)
        self.assertEqual(record["outcome"], "reconcile")
        self.assertEqual(record["base_revision"], self.base)
        self.assertEqual(record["path_migration_map"],
                         self.result["migration_map"])

    def test_the_committed_contract_declares_the_platform_and_new_homes(self):
        contract = json.loads(git(
            self.root, "show", f"{self.branch}:{CONTRACT}"))
        self.assertEqual(contract["platform"],
                         {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"})
        self.assertEqual(contract["bindings"]["paths"]["artifacts"],
                         {"specs": ".agents/artifacts/specs",
                          "plans": ".agents/artifacts/plans"})
        self.assertEqual(contract["bindings"]["paths"]["rejections"],
                         [".agents/knowledge/rejections"])

    def test_the_runtime_sentinel_is_committed_and_the_pattern_is_gone(self):
        self.assertEqual(
            git(self.root, "show",
                f"{self.branch}:.agents/runtime/.gitignore"), "*\n")
        self.assertNotIn(
            ".agents/runtime/",
            git(self.root, "show", f"{self.branch}:.gitignore"))

    def test_the_worktree_is_removed_after_the_ref_is_proved(self):
        self.assertFalse(self.worktree(self.plan_id).exists())
        self.assertNotIn(self.digest(self.plan_id),
                         git(self.root, "worktree", "list", "--porcelain"))

    def test_every_commit_gate_is_recorded_passed_in_the_stored_plan(self):
        stored = json.loads(self.stored_plan(self.plan_id).read_text("utf-8"))
        gates = stored["verification"]["commit_gates"]
        self.assertEqual([gate["id"] for gate in gates],
                         [gate["id"] for gate
                          in self.document["verification"]["commit_gates"]])
        self.assertEqual({gate["status"] for gate in gates}, {"passed"})

    def test_apply_never_writes_the_fleet_registry(self):
        self.assertFalse(self.state("fleet", "registry.json").exists())
        self.assertFalse(self.state("fleet").exists())


# --------------------------------------------------------------------------
# Refusals — every one of them mutates nothing
# --------------------------------------------------------------------------


class ApplyRefusalTest(ApplyTestCase):
    def test_an_unknown_plan_id_is_plan_not_found(self):
        root = apply_repo(self.home)
        self.ready_plan(root)
        self.refuse(root, "sha256:" + "0" * 64, "plan_not_found")

    def test_a_plan_id_that_is_not_a_digest_is_plan_not_found(self):
        root = apply_repo(self.home)
        self.ready_plan(root)
        self.refuse(root, "../../../etc/passwd", "plan_not_found")

    def test_a_not_applicable_plan_is_not_ready(self):
        root = apply_repo(self.home)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        document = json.loads(self.stored_plan(plan_id).read_text("utf-8"))
        document["plan"]["state"] = "not_applicable"
        self.rewrite_stored_plan(plan_id, document)
        self.refuse(root, plan_id, "not_ready")

    def test_a_bootstrap_plan_is_never_ready_and_apply_refuses_it(self):
        """A `bootstrap` plan has no contract to amend, so its first ready
        gate always fails; `apply` accepts only `ready`."""
        root = init_repo()
        write(root, "README.md", "# unrelated\n")
        git(root, "remote", "add", "origin",
            "https://github.com/fixture/bootstrap.git")
        commit(root)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err or out)
        document = json.loads(out)
        self.assertEqual(document["plan"]["outcome"], "bootstrap")
        self.assertEqual(document["plan"]["state"], "draft")
        self.refuse(root, document["plan"]["plan_id"], "not_ready")

    def test_a_moved_head_is_plan_stale(self):
        root = apply_repo(self.home)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        write(root, "README.md", "# unrelated\n")
        commit(root, "an unrelated commit")
        self.refuse(root, plan_id, "plan_stale")

    def test_an_unstaged_edit_to_a_move_source_is_a_dirty_worktree(self):
        """The index still holds the planned object, so the plan is not stale;
        the working tree carries an edit `git mv` would carry along."""
        root = apply_repo(self.home)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        write(root, ".claude/specs/x.md", "# edited, never committed\n")
        self.refuse(root, plan_id, "dirty_worktree")

    def test_an_untracked_file_in_an_inspected_source_is_refused(self):
        """It joins the evidence the plan id is taken over, so the refusal is
        staleness rather than dirt — either way nothing is touched."""
        root = apply_repo(self.home)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        write(root, ".claude/specs/untracked.md", "# not committed\n")
        self.refuse(root, plan_id, "plan_stale")

    def test_an_unrelated_unstaged_edit_is_not_a_dirty_worktree(self):
        """The control: the gate is about work colliding with uncommitted
        content, not about a pristine checkout."""
        root = apply_repo(self.home)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        write(root, "home/common/agent-skills/standards/bar.md", "# edited\n")
        self.succeed(root, plan_id)

    def test_a_retained_worktree_refuses_and_is_never_deleted(self):
        root = apply_repo(self.home)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        retained = self.worktree(plan_id)
        retained.mkdir(parents=True)
        (retained / "evidence.txt").write_text("kept", encoding="utf-8")
        before_status = git(root, "status", "--porcelain")
        before_tree = tree_snapshot(root)
        code, payload, err = self.apply(plan_id)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["code"], "adopt_failure")
        self.assertEqual(payload["error"]["repair_id"],
                         "adopt.worktree.retained")
        self.assertEqual((retained / "evidence.txt").read_text("utf-8"), "kept")
        self.assertEqual(git(root, "status", "--porcelain"), before_status)
        self.assertEqual(tree_snapshot(root), before_tree)


# --------------------------------------------------------------------------
# Tampering with the stored document (D33)
# --------------------------------------------------------------------------


class StoredPlanTamperingTest(ApplyTestCase):
    """The digest authenticates the plan's inputs; only re-derivation
    authenticates its operations. Each case edits the stored JSON and leaves
    the repository untouched, so the digest still matches and only the
    re-derivation can refuse."""

    def tampered(self, edit) -> tuple[Path, str]:
        root = apply_repo(self.home)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        document = json.loads(self.stored_plan(plan_id).read_text("utf-8"))
        edit(document["changes"])
        self.rewrite_stored_plan(plan_id, document)
        return root, plan_id

    def first(self, changes: list[dict], kind: str) -> dict:
        return next(op for op in changes if op["op"] == kind)

    def test_an_edited_operation_target_is_plan_stale(self):
        def edit(changes):
            self.first(changes, "git-mv")["targets"] = [".agents/elsewhere.md"]
        self.refuse(*self.tampered(edit), "plan_stale")

    def test_an_edited_operation_kind_is_plan_stale(self):
        def edit(changes):
            self.first(changes, "git-mv")["op"] = "write-file"
        self.refuse(*self.tampered(edit), "plan_stale")

    def test_a_reordered_change_list_is_plan_stale(self):
        def edit(changes):
            changes.reverse()
        self.refuse(*self.tampered(edit), "plan_stale")

    def test_an_edited_after_hash_is_plan_stale(self):
        def edit(changes):
            self.first(changes, "write-file")["after"] = "sha256:" + "0" * 64
        self.refuse(*self.tampered(edit), "plan_stale")

    def test_an_absolute_operation_path_refuses_before_anything_runs(self):
        def edit(changes):
            self.first(changes, "git-mv")["targets"] = ["/etc/passwd"]
        payload = self.refuse(*self.tampered(edit), "adopt_failure")
        self.assertEqual(payload["error"]["repair_id"],
                         "adopt.operation.uncontained_path")

    def test_a_dot_dot_operation_path_refuses_before_anything_runs(self):
        def edit(changes):
            self.first(changes, "git-mv")["targets"] = ["../escaped.md"]
        payload = self.refuse(*self.tampered(edit), "adopt_failure")
        self.assertEqual(payload["error"]["repair_id"],
                         "adopt.operation.uncontained_path")

    def test_an_unknown_operation_kind_refuses_before_anything_runs(self):
        def edit(changes):
            self.first(changes, "git-mv")["op"] = "chmod"
        payload = self.refuse(*self.tampered(edit), "adopt_failure")
        self.assertEqual(payload["error"]["repair_id"],
                         "adopt.operation.unknown_kind")


# --------------------------------------------------------------------------
# The deletion acknowledgement (D16)
# --------------------------------------------------------------------------


class DeletionAcknowledgementTest(ApplyTestCase):
    def planted(self) -> tuple[Path, str]:
        """A stored plan carrying a `delete-file` operation.

        No generator emits one, so the only way to present one to `apply` is
        to plant it; the re-derivation then refuses the edited document, which
        is exactly how far the acknowledgement lets it get.
        """
        root = apply_repo(self.home)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        document = json.loads(self.stored_plan(plan_id).read_text("utf-8"))
        document["changes"].append({
            "op": "delete-file", "sources": [".claude/skills.config.json"],
            "targets": [], "before": "sha256:" + "0" * 64, "after": None,
            "approval_class": "destructive"})
        self.rewrite_stored_plan(plan_id, document)
        return root, plan_id

    def test_a_deletion_without_the_flag_refuses_unacknowledged(self):
        self.refuse(*self.planted(), "unacknowledged_deletion")

    def test_the_flag_carries_the_plan_past_the_acknowledgement(self):
        root, plan_id = self.planted()
        self.refuse(root, plan_id, "plan_stale", "--acknowledge-deletions")

    def test_the_flag_is_accepted_by_a_plan_with_no_deletion(self):
        root = apply_repo(self.home)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        self.succeed(root, plan_id, "--acknowledge-deletions")


# --------------------------------------------------------------------------
# Commit gates
# --------------------------------------------------------------------------


class CommitGateTest(ApplyTestCase):
    def assert_retained(self, root: Path, plan_id: str, base: str,
                        repair_id: str) -> None:
        code, payload, err = self.apply(plan_id)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["code"], "verification_failed")
        self.assertEqual(payload["error"]["repair_id"], repair_id)
        self.assertTrue(self.worktree(plan_id).is_dir())
        evidence = self.state(
            "adopt", "worktrees", self.digest(plan_id) + ".failure.json")
        self.assertTrue(evidence.is_file())
        record = json.loads(evidence.read_text("utf-8"))
        self.assertEqual(record["plan_id"], plan_id)
        self.assertEqual(record["repair_id"], repair_id)
        # The target branch never moved and the target holds no new commit.
        self.assertEqual(git(root, "rev-parse", "HEAD").strip(), base)
        self.assertEqual(git(root, "status", "--porcelain"), "")
        self.assertEqual(
            git(root, "rev-list", "--count",
                f"{base}..adopt-{self.digest(plan_id)[:12]}").strip(), "0")

    def test_a_failing_verification_command_leaves_no_commit(self):
        root = apply_repo(self.home, verification=("false",))
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        base = git(root, "rev-parse", "HEAD").strip()
        self.assert_retained(root, plan_id, base,
                             "adopt.gate.workflow-verification-commands")
        record = json.loads(self.state(
            "adopt", "worktrees",
            self.digest(plan_id) + ".failure.json").read_text("utf-8"))
        failed = [gate["id"] for gate in record["gates"]
                  if gate["status"] == "failed"]
        self.assertEqual(failed, ["workflow-verification-commands"])
        stored = json.loads(self.stored_plan(plan_id).read_text("utf-8"))
        self.assertEqual(
            [gate["status"] for gate
             in stored["verification"]["commit_gates"]
             if gate["id"] == "workflow-verification-commands"],
            ["failed"])

    def test_a_signing_failure_is_verification_failed(self):
        """`-S` is passed exactly when the contract asks for it, and a signer
        that cannot run is surfaced rather than retried unsigned."""
        root = apply_repo(self.home, signed=True)
        git(root, "config", "gpg.format", "openpgp")
        git(root, "config", "gpg.program",
            str(root / "no-such-signing-program"))
        git(root, "config", "user.signingkey", "DEADBEEF")
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        base = git(root, "rev-parse", "HEAD").strip()
        self.assert_retained(root, plan_id, base, "adopt.commit.failed")

    def test_a_second_apply_over_the_retained_worktree_refuses(self):
        root = apply_repo(self.home, verification=("false",))
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        base = git(root, "rev-parse", "HEAD").strip()
        self.assert_retained(root, plan_id, base,
                             "adopt.gate.workflow-verification-commands")
        code, payload, err = self.apply(plan_id)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["repair_id"],
                         "adopt.worktree.retained")
        self.assertTrue(self.worktree(plan_id).is_dir())


# --------------------------------------------------------------------------
# What the commit itself carries
# --------------------------------------------------------------------------


class CommitContentTest(ApplyTestCase):
    """The commit changes exactly the paths the plan's operations declare.

    The gates judge the worktree *before* the commit, and they are ordered:
    the status gate runs first, the one that executes every declared
    verification command runs last, and a `pre-commit` hook runs after all six
    have passed. Whatever either of those stages is in the index `git commit`
    reads, so it lands in the commit — while the ref proofs stay true of it,
    because the branch still adds exactly one commit and the worktree is clean
    once that commit has swallowed the extra content.

    Both cases smuggle one file in and prove the refusal names it.
    """

    SMUGGLED = "smuggled.txt"

    def assert_refused(self, root: Path, plan_id: str, base: str) -> None:
        """The refusal, the untouched target, and the retained evidence.

        The commit exists — it is what was judged — so unlike a failed gate
        this leaves a branch carrying it, retained beside its worktree for the
        operator to inspect rather than amended or reset away (D17).
        """
        code, payload, err = self.apply(plan_id)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["code"], "verification_failed")
        self.assertEqual(payload["error"]["repair_id"],
                         "adopt.commit.unplanned_content")
        self.assertTrue(payload["error"]["violations"])
        self.assertEqual(git(root, "rev-parse", "HEAD").strip(), base)
        self.assertEqual(git(root, "status", "--porcelain"), "")
        self.assertTrue(self.worktree(plan_id).is_dir())
        evidence = self.state(
            "adopt", "worktrees", self.digest(plan_id) + ".failure.json")
        self.assertEqual(
            json.loads(evidence.read_text("utf-8"))["repair_id"],
            "adopt.commit.unplanned_content")
        # The file the plan never named is exactly what the commit carries
        # beyond it, which is what the proof read.
        branch = f"adopt-{self.digest(plan_id)[:12]}"
        self.assertIn(self.SMUGGLED, git(
            root, "show", "--name-only", "--format=", branch).split())

    def staging_command(self) -> tuple[str, ...]:
        return ("sh", "-c",
                f"printf x > {self.SMUGGLED} && git add {self.SMUGGLED}")

    def test_a_verification_command_that_stages_content_is_refused(self):
        """The last gate runs project commands in the worktree; the first gate
        checked the status before any of them ran."""
        root = apply_repo(self.home, verification=self.staging_command())
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        self.assert_refused(root, plan_id,
                            git(root, "rev-parse", "HEAD").strip())

    def test_a_pre_commit_hook_that_stages_content_is_refused(self):
        """Nothing at all runs between the last gate and this hook, so no
        pre-commit check can see what it adds."""
        root = apply_repo(self.home)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        # Hooks live in the common directory, which the adoption worktree
        # shares with the repository it was added from.
        hook = root / ".git" / "hooks" / "pre-commit"
        hook.write_text(
            f"#!/bin/sh\nprintf x > {self.SMUGGLED}\n"
            f"git add {self.SMUGGLED}\n", encoding="utf-8")
        hook.chmod(0o755)
        self.assert_refused(root, plan_id,
                            git(root, "rev-parse", "HEAD").strip())

    def test_the_planned_commit_changes_exactly_the_planned_paths(self):
        """The control: with nothing smuggled in, the proof passes and the set
        of changed paths is the operations' own."""
        root = apply_repo(self.home)
        document = self.ready_plan(root)
        result = self.succeed(root, document["plan"]["plan_id"])
        # `--no-renames`, because a move is two paths here: the operation
        # names both, and a rename-detected view would show only the new one.
        changed = set(git(root, "show", "--no-renames", "--name-only",
                          "--format=", result["commit"]).split())
        required, optional = set(), set()
        for operation in document["changes"]:
            if operation["op"] == "regenerate-projection":
                optional.update(operation["targets"])
            else:
                required.update(operation["sources"] + operation["targets"])
        self.assertTrue(required)
        self.assertTrue(required <= changed, required - changed)
        self.assertTrue(changed <= required | optional, changed - required)


# --------------------------------------------------------------------------
# The parser
# --------------------------------------------------------------------------


class ApplyParserTest(ApplyTestCase):
    def test_apply_takes_exactly_two_flags(self):
        code, out, err = run("apply", "--help", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("--plan-id", out)
        self.assertIn("--acknowledge-deletions", out)
        for absent in ("--approve", "--message", "--branch"):
            self.assertNotIn(absent, out)

    def test_a_missing_plan_id_is_an_argparse_usage_error(self):
        code, out, _ = run("apply", home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
