"""Contract tests for `adopt-project apply` on a project with a devenv lock.

Adopting such a project writes the lock entry, the rendered conformance workflow and the
`Conformance` required check on the forge, all three or none (ADR-project-contract-018). The
cases live beside `test_adopt_apply.py` because that file is over its size limit and may not
grow; the apply fixtures and the case base are imported from it, and a stub `gh` stands in for
the forge.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.project_contract import adopt_conformance, adopt_inspection, resolve_project

from . import _inprocess_cli
from .test_adopt_apply import ApplyTestCase, apply_repo, write_hooks
from .test_adopt_conformance import FIXTURE_REVISION, install_platform_revision, write_devenv
from .test_adopt_project import commit, git, make_home, run

TIER = "integration"  # every case applies a plan in a real git repository


def locked_apply_repo(home: Path) -> Path:
    """`apply_repo` plus a devenv lock and the installed platform revision."""
    install_platform_revision(home)
    root = apply_repo(home)
    write_devenv(root)
    return root


DEFAULT_PROTECTION = {"strict": True,
                      "checks": [{"context": "Nix Eval", "app_id": 15368}],
                      "contexts": ["Nix Eval"]}

STUB_GH = """#!__PYTHON__
import json
import sys

STATE = __STATE__
LOG = __LOG__
with open(LOG, "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": sys.argv[1:]}) + "\\n")
with open(STATE, encoding="utf-8") as handle:
    state = json.load(handle)


def save():
    with open(STATE, "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def land():
    protection = state.get("protection")
    if isinstance(protection, dict):
        protection.setdefault("contexts", []).append("Conformance")
        protection.setdefault("checks", []).append(
            {"context": "Conformance", "app_id": None})


if "--method" in sys.argv and "POST" in sys.argv:
    mode = state.get("post", "ok")
    if mode == "ok":
        land()
        state["posted"] = True
        save()
        print(json.dumps(["Conformance"]))
        sys.exit(0)
    if state.get("post_lands"):
        land()
    state["posted"] = True
    save()
    if mode == "refuse":
        print("gh: Resource not accessible by integration (HTTP 403)", file=sys.stderr)
    else:
        print("gh: connection reset by peer", file=sys.stderr)
    sys.exit(1)
if state.get("empty_after_post") and state.get("posted"):
    print(json.dumps({"strict": True, "checks": [], "contexts": []}))
    sys.exit(0)
if state.get("read_fails") or (state.get("read_fails_after_post") and state.get("posted")):
    print("gh: HTTP 502 (HTTP 502)", file=sys.stderr)
    sys.exit(1)
if state.get("protection") is None:
    print("gh: Branch not protected (HTTP 404)", file=sys.stderr)
    sys.exit(1)
print(json.dumps(state["protection"]))
"""


def stub_forge(directory: Path, state: dict) -> tuple[str, Path, Path]:
    """A `gh` that logs each call and answers from a state file (see the cases)."""
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "gh.log"
    state_path = directory / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    script = directory / "gh"
    script.write_text(
        STUB_GH.replace("__PYTHON__", sys.executable)
        .replace("__STATE__", repr(str(state_path)))
        .replace("__LOG__", repr(str(log_path))), encoding="utf-8")
    script.chmod(0o755)
    return str(directory), log_path, state_path


def posts(log: Path) -> list[list[str]]:
    """The argv of every logged call that was a POST."""
    if not log.exists():
        return []
    calls = [json.loads(line)["argv"]
             for line in log.read_text("utf-8").splitlines()]
    return [argv for argv in calls if "--method" in argv and "POST" in argv]


def rewrite_state(state_path: Path, **changes: object) -> None:
    state = json.loads(state_path.read_text("utf-8"))
    state.update(changes)
    state_path.write_text(json.dumps(state), encoding="utf-8")


class CommitHookConformanceTest(ApplyTestCase):
    def test_a_commit_hook_that_changes_a_planned_conformance_file_is_refused(self):
        """`prove_commit_content` compares path names only, and a hook can
        change the bytes of a path the plan already writes."""
        hooks = {
            "the lock": "printf ' ' >> devenv.lock\ngit add devenv.lock\n",
            "the workflow": ("printf '# x\\n' >> .github/workflows/conformance.yaml\n"
                             "git add .github/workflows/conformance.yaml\n"),
        }
        for name, body in hooks.items():
            with self.subTest(name):
                home = make_home()
                self.home = home
                root = locked_apply_repo(home)
                bin_dir, log, _ = stub_forge(
                    Path(tempfile.mkdtemp()), {"protection": DEFAULT_PROTECTION})
                plan_id = self.ready_plan(root)["plan"]["plan_id"]
                hook = root / ".git" / "hooks" / "pre-commit"
                hook.write_text("#!/bin/sh\n" + body, encoding="utf-8")
                hook.chmod(0o755)
                path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
                with mock.patch.dict(os.environ, {"PATH": path}):
                    code, payload, err = self.apply(plan_id)
                self.assertEqual(code, 2, err or payload)
                self.assertEqual(payload["error"]["code"], "verification_failed")
                self.assertEqual(payload["error"]["repair_id"],
                                 "adopt.commit.conformance_unproved")
                self.assertTrue(self.worktree(plan_id).is_dir())
                self.assertEqual(posts(log), [])
                hook.unlink()


# --------------------------------------------------------------------------
# Adopting a project with a devenv lock: the lock entry, the workflow and the
# required check on the forge, all three or none
# --------------------------------------------------------------------------


class ConformanceAdoptionApplyTest(ApplyTestCase):
    BRANCH = "main"

    def forge(self, **state: object) -> tuple[Path, Path]:
        """A stub `gh` first on `PATH` for this case; returns its log and state."""
        state.setdefault("protection", DEFAULT_PROTECTION)
        bin_dir, log, state_path = stub_forge(Path(tempfile.mkdtemp()), state)
        patch = mock.patch.dict(
            os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        patch.start()
        self.addCleanup(patch.stop)
        return log, state_path

    def pending(self, plan_id: str) -> Path:
        return self.state("adopt", "worktrees",
                          self.digest(plan_id) + ".required-check.json")

    def adopt_branch(self, plan_id: str) -> str:
        return f"adopt-{self.digest(plan_id)[:12]}"

    def failing(self, root: Path, plan_id: str, repair_id: str) -> dict:
        payload = self.refuse(root, plan_id, "adopt_failure")
        self.assertEqual(payload["error"]["repair_id"], repair_id)
        self.assertEqual(self.pending(plan_id).exists(), False)
        return payload

    def test_apply_locks_the_revision_writes_the_rendered_workflow_and_requests_conformance_once(self):
        root = locked_apply_repo(self.home)
        log, _ = self.forge()
        document = self.ready_plan(root)
        result = self.succeed(root, document["plan"]["plan_id"])
        branch = result["branch"]
        lock = json.loads(git(root, "show", f"{branch}:devenv.lock"))
        node = lock["nodes"][lock["nodes"]["root"]["inputs"]["agent-platform"]]
        self.assertEqual(node, {
            "flake": False, "locked": FIXTURE_REVISION,
            "original": {"owner": "fixture", "repo": "platform", "type": "github"}})
        self.assertEqual(node["locked"]["rev"],
                         document["plan"]["conformance"]["revision"]["rev"])
        workflow = subprocess.run(
            ["git", "-C", str(root), "show",
             f"{branch}:.github/workflows/conformance.yaml"],
            capture_output=True, check=True).stdout
        self.assertEqual(workflow,
                         resolve_project.render_conformance_workflow("main", 2, locked=True))
        self.assertEqual(posts(log), [[
            "api", "--method", "POST",
            "repos/fixture/target/branches/main/protection/required_status_checks/contexts",
            "-f", "contexts[]=Conformance"]])
        self.assertEqual(result["required_check"], {
            "repo": "fixture/target", "branch": "main",
            "context": "Conformance", "state": "added"})
        self.assertFalse(self.pending(document["plan"]["plan_id"]).exists())

    def test_a_hand_edited_workflow_fails_the_projection_freshness_check_of_a_ci_run(self):
        root = locked_apply_repo(self.home)
        self.forge()
        result = self.succeed(root, self.ready_plan(root)["plan"]["plan_id"])
        git(root, "merge", "--ff-only", "--quiet", result["branch"])

        def ci_run() -> tuple[int, dict]:
            done = _inprocess_cli.run_module(
                "agent_tools.project_contract.conformance",
                ("run", "--purpose", "ci", "--repo-root", str(root)),
                env={**os.environ, "HOME": str(self.home)})
            return done.returncode, json.loads(done.stdout)

        def fresh(report: dict) -> str:
            (check,) = [check for check in report["checks"]
                        if check["id"] == "repository.projection.fresh"]
            return check["status"]

        _, report = ci_run()
        self.assertEqual(fresh(report), "passed", report)
        workflow = root / ".github" / "workflows" / "conformance.yaml"
        workflow.write_text(workflow.read_text("utf-8") + "# hand edit\n",
                            encoding="utf-8")
        commit(root, "hand edit the workflow")
        code, report = ci_run()
        self.assertEqual(code, 1)
        self.assertEqual(report["outcome"]["status"], "failed")
        self.assertEqual(fresh(report), "failed")

    def test_a_refused_required_check_request_leaves_no_lock_entry_and_no_workflow_committed(self):
        root = locked_apply_repo(self.home)
        log, _ = self.forge(post="refuse")
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        before = git(root, "rev-list", "--all")
        payload = self.refuse(root, plan_id, "adopt_failure")
        self.assertEqual(payload["error"]["repair_id"], "adopt.required_check.refused")
        self.assertEqual(git(root, "rev-list", "--all"), before)
        self.assertEqual(git(root, "for-each-ref", "refs/heads/adopt-"), "")
        self.assertFalse(self.pending(plan_id).exists())
        self.assertEqual(len(posts(log)), 1)

    def test_an_unknown_outcome_keeps_the_branch_and_a_later_apply_settles_it(self):
        root = locked_apply_repo(self.home)
        log, state = self.forge(post="lost", post_lands=True, read_fails_after_post=True)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        code, payload, err = self.apply(plan_id)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["repair_id"], "adopt.required_check.unknown")
        branch = self.adopt_branch(plan_id)
        self.assertIn("devenv.lock", self.branch_files(root, branch))
        self.assertIn("agent-platform", git(root, "show", f"{branch}:devenv.lock"))
        self.assertTrue(self.pending(plan_id).is_file())
        rewrite_state(state, read_fails_after_post=False)
        result = self.succeed(root, plan_id)
        self.assertEqual(result["required_check"]["state"], "added")
        self.assertEqual(result["commit"], git(root, "rev-parse", branch).strip())
        self.assertEqual(len(posts(log)), 1)
        self.assertFalse(self.pending(plan_id).exists())

    def test_discard_keeps_the_branch_and_the_record_together_while_an_outcome_is_unknown(self):
        """P6: a `discard` (the console's Cancel calls it) must not delete the branch
        and leave the pending record, or the plan could never be applied again."""
        root = locked_apply_repo(self.home)
        log, state = self.forge(post="lost", post_lands=True, read_fails_after_post=True)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        code, payload, err = self.apply(plan_id)
        self.assertEqual(payload["error"]["repair_id"], "adopt.required_check.unknown")
        branch = self.adopt_branch(plan_id)
        code, out, err = run("discard", "--plan-id", plan_id, home=self.home)
        self.assertEqual(code, 2, err or out)
        self.assertEqual(json.loads(out)["error"]["repair_id"],
                         "adopt.required_check.pending")
        self.assertIn(branch, git(root, "branch", "--list"))
        self.assertTrue(self.pending(plan_id).is_file())
        code, payload, err = self.apply(plan_id, "--discard-retained")
        self.assertEqual(payload["error"]["repair_id"], "adopt.required_check.unreadable")
        self.assertIn(branch, git(root, "branch", "--list"))
        self.assertTrue(self.pending(plan_id).is_file())
        rewrite_state(state, read_fails_after_post=False)
        result = self.succeed(root, plan_id)
        self.assertEqual(result["required_check"]["state"], "added")
        self.assertEqual(len(posts(log)), 1)
        self.assertFalse(self.pending(plan_id).exists())

    def test_an_unknown_outcome_that_did_not_land_is_requested_again(self):
        root = locked_apply_repo(self.home)
        log, state = self.forge(post="lost", post_lands=False, read_fails_after_post=True)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        code, payload, err = self.apply(plan_id)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["repair_id"], "adopt.required_check.unknown")
        rewrite_state(state, post="ok", read_fails_after_post=False)
        result = self.succeed(root, plan_id)
        self.assertEqual(result["required_check"]["state"], "added")
        self.assertEqual(len(posts(log)), 2)
        self.assertFalse(self.pending(plan_id).exists())

    def test_a_rollback_that_cannot_delete_the_branch_says_so(self):
        root = locked_apply_repo(self.home)
        self.forge(post="refuse")
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        hook = root / ".git" / "hooks" / "reference-transaction"
        hook.write_text(
            "#!/bin/sh\n"
            '[ "$1" = prepared ] || exit 0\n'
            "while read old new ref; do\n"
            '  case "$ref" in\n'
            "    refs/heads/adopt-*)\n"
            '      case "$new" in *[!0]*) ;; *) exit 1 ;; esac ;;\n'
            "  esac\n"
            "done\n"
            "exit 0\n", encoding="utf-8")
        hook.chmod(0o755)
        code, payload, err = self.apply(plan_id)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["repair_id"], "adopt.required_check.rollback_failed")
        self.assertIn(self.adopt_branch(plan_id), git(root, "branch", "--list"))
        self.assertTrue(self.pending(plan_id).is_file())

    def hook_running(self, root: Path, source: str, *, add: str) -> None:
        """A pre-commit hook that runs the Python `source` and stages `add`."""
        git(root, "config", "core.hooksPath", str(write_hooks(
            pre_commit=f"#!/bin/sh\n{shlex.quote(sys.executable)} -c {shlex.quote(source)}\n"
                       f"git add {shlex.quote(add)}\n")))

    def environment_repo(self) -> Path:
        install_platform_revision(self.home)
        root = apply_repo(self.home, commit_environment="dev-shell",
                          commands={"dev-shell": ["sh", "-c", 'exec "$@"', "dev-shell"]})
        write_devenv(root)
        return root

    def test_a_refused_request_followed_by_an_empty_read_is_a_confirmed_absence(self):
        root = locked_apply_repo(self.home)
        log, _ = self.forge(post="refuse", empty_after_post=True)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        code, payload, err = self.apply(plan_id)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["repair_id"], "adopt.required_check.refused")
        self.assertEqual(git(root, "for-each-ref", "refs/heads/adopt-"), "")
        self.assertFalse(self.pending(plan_id).exists())
        self.assertEqual(len(posts(log)), 1)

    def block_branch_deletion(self, root: Path) -> Path:
        hook = root / ".git" / "hooks" / "reference-transaction"
        hook.write_text(
            "#!/bin/sh\n"
            '[ "$1" = prepared ] || exit 0\n'
            "while read old new ref; do\n"
            '  case "$ref" in\n'
            "    refs/heads/adopt-*)\n"
            '      case "$new" in *[!0]*) ;; *) exit 1 ;; esac ;;\n'
            "  esac\n"
            "done\n"
            "exit 0\n", encoding="utf-8")
        hook.chmod(0o755)
        return hook

    def test_deleting_the_branch_by_hand_after_a_failed_rollback_frees_the_plan(self):
        for way in ("apply again", "discard", "apply and discard retained"):
            with self.subTest(way):
                self.home = make_home()
                root = locked_apply_repo(self.home)
                _, state = self.forge(post="refuse")
                plan_id = self.ready_plan(root)["plan"]["plan_id"]
                hook = self.block_branch_deletion(root)
                code, payload, err = self.apply(plan_id)
                self.assertEqual(payload["error"]["repair_id"],
                                 "adopt.required_check.rollback_failed", err or payload)
                hook.unlink()
                git(root, "branch", "-D", self.adopt_branch(plan_id))
                if way == "discard":
                    code, out, err = run("discard", "--plan-id", plan_id, home=self.home)
                    self.assertEqual(code, 0, err or out)
                    self.assertFalse(self.pending(plan_id).exists())
                    continue
                rewrite_state(state, post="ok")
                extra = ("--discard-retained",) if way != "apply again" else ()
                result = self.succeed(root, plan_id, *extra)
                self.assertEqual(result["required_check"]["state"], "added")
                self.assertFalse(self.pending(plan_id).exists())

    def test_a_pending_record_that_does_not_belong_to_the_plan_deletes_no_branch(self):
        root = locked_apply_repo(self.home)
        log, state = self.forge(post="lost", read_fails_after_post=True)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        code, payload, err = self.apply(plan_id)
        self.assertEqual(payload["error"]["repair_id"], "adopt.required_check.unknown")
        branch = self.adopt_branch(plan_id)
        original = json.loads(self.pending(plan_id).read_text("utf-8"))
        base = git(root, "rev-parse", "main").strip()
        git(root, "branch", "other-work", original["commit"])
        # A settlement that reads a confirmed absence would roll the recorded branch back.
        rewrite_state(state, post="refuse", read_fails_after_post=False)
        foreign = {**original, "commit": base, "result": {**original["result"], "commit": base}}
        variants = {
            "another branch": {**original, "branch": "other-work"},
            "another repository": {**original, "repo": "fixture/elsewhere"},
            "another integration branch": {**original, "integration_branch": "release"},
            "another plan id": {**original, "plan_id": "sha256:" + "0" * 64},
            "a result of another commit": {
                **original, "result": {**original["result"], "commit": base}},
            "a commit with no evidence of the plan": foreign,
        }
        for name, record in variants.items():
            with self.subTest(name):
                git(root, "branch", "-f", branch,
                    base if record is foreign else original["commit"])
                self.pending(plan_id).write_text(json.dumps(record), encoding="utf-8")
                code, payload, err = self.apply(plan_id)
                self.assertEqual(code, 2, err or payload)
                self.assertEqual(payload["error"]["repair_id"],
                                 "adopt.required_check.pending_mismatch")
                branches = git(root, "branch", "--list")
                self.assertIn("other-work", branches)
                self.assertIn(branch, branches)
                self.assertTrue(self.pending(plan_id).is_file())
        self.assertEqual(len(posts(log)), 1)

    def test_an_origin_on_another_host_or_with_another_push_url_refuses_before_any_forge_request(self):
        root = locked_apply_repo(self.home)
        log, _ = self.forge()
        cases = {
            "another host": ("set-url", "origin", "https://example.com/fixture/target.git"),
            "another push url": ("set-url", "--push", "origin",
                                 "https://github.com/fixture/other.git"),
            "a push url on another host": ("set-url", "--push", "origin",
                                           "https://example.com/fixture/target.git"),
        }
        for name, change in cases.items():
            with self.subTest(name):
                git(root, "remote", *change)
                with self.assertRaises(adopt_inspection.AdoptError) as raised:
                    adopt_conformance.preflight(root, "fixture/target", "main")
                self.assertEqual(raised.exception.repair_id,
                                 "adopt.required_check.origin_mismatch")
                self.assertFalse(log.exists() and log.read_text("utf-8"))
                git(root, "remote", "set-url", "origin", "https://github.com/fixture/target.git")
                subprocess.run(["git", "-C", str(root), "config", "--unset-all", "remote.origin.pushurl"],
                               capture_output=True)

    def test_a_workflow_a_commit_environment_leaves_untracked_is_not_carried_by_the_commit(self):
        root = self.environment_repo()
        log, _ = self.forge()
        git(root, "config", "core.hooksPath", str(write_hooks(
            pre_commit="#!/bin/sh\ngit rm --cached -q --ignore-unmatch "
                       ".github/workflows/conformance.yaml\n")))
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        code, payload, err = self.apply(plan_id)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["repair_id"], "adopt.commit.conformance_unproved")
        self.assertTrue(self.worktree(plan_id).is_dir())
        self.assertEqual(posts(log), [])

    def test_a_hook_that_drops_the_workflow_projection_from_the_contract_is_refused(self):
        root = locked_apply_repo(self.home)
        log, _ = self.forge()
        self.hook_running(
            root,
            'import json; p = ".agents/project.json"; d = json.load(open(p)); '
            'd["projections"] = [e for e in d["projections"] if e.get("kind") != '
            '"conformance_workflow"]; json.dump(d, open(p, "w"), indent=2)',
            add=".agents/project.json")
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        code, payload, err = self.apply(plan_id)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["repair_id"], "adopt.commit.conformance_unproved")
        self.assertTrue(self.worktree(plan_id).is_dir())
        self.assertEqual(posts(log), [])

    def test_a_formatter_that_changes_the_whitespace_of_the_declaration_is_accepted_and_one_that_removes_it_is_not(self):
        reformat = ('p = "devenv.yaml"; t = open(p).read(); open(p, "w").write('
                    't.replace("    url", "      url").replace("    flake", "      flake"))')
        remove = ('p = "devenv.yaml"; t = open(p).read(); '
                  'open(p, "w").write(t.replace("github:fixture/platform", "github:other/platform"))')
        for name, source, accepted in (("reformatted", reformat, True), ("redeclared elsewhere", remove, False)):
            with self.subTest(name):
                self.home = make_home()
                root = locked_apply_repo(self.home)
                log, _ = self.forge()
                self.hook_running(root, source, add="devenv.yaml")
                plan_id = self.ready_plan(root)["plan"]["plan_id"]
                code, payload, err = self.apply(plan_id)
                if accepted:
                    self.assertEqual(code, 0, err or payload)
                    self.assertEqual(len(posts(log)), 1)
                else:
                    self.assertEqual(code, 2, err or payload)
                    self.assertEqual(payload["error"]["repair_id"],
                                     "adopt.commit.conformance_unproved")
                    self.assertEqual(posts(log), [])

    def test_a_check_required_from_another_app_is_refused_and_one_from_actions_or_any_is_not(self):
        for app_id, accepted in ((999, False), (15368, True), (-1, True), (None, True)):
            with self.subTest(app_id=app_id):
                self.home = make_home()
                root = locked_apply_repo(self.home)
                protection = {**DEFAULT_PROTECTION, "checks": [
                    *DEFAULT_PROTECTION["checks"], {"context": "Conformance", "app_id": app_id}]}
                log, _ = self.forge(protection=protection)
                plan_id = self.ready_plan(root)["plan"]["plan_id"]
                if accepted:
                    result = self.succeed(root, plan_id)
                    self.assertEqual(result["required_check"]["state"], "already_required")
                else:
                    payload = self.refuse(root, plan_id, "adopt_failure")
                    self.assertEqual(payload["error"]["repair_id"],
                                     "adopt.required_check.app_mismatch")
                self.assertEqual(posts(log), [])

    def test_an_apply_or_discard_of_a_plan_another_holds_the_lock_of_is_refused_and_changes_nothing(self):
        root = locked_apply_repo(self.home)
        log, _ = self.forge()
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        before = git(root, "branch", "--list")
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            with adopt_conformance.plan_lock(self.digest(plan_id)):
                code, payload, err = self.apply(plan_id)
                self.assertEqual(code, 2, err or payload)
                self.assertEqual(payload["error"]["repair_id"], "adopt.required_check.pending")
                code, out, err = run("discard", "--plan-id", plan_id, home=self.home)
                self.assertEqual(code, 2, err or out)
                self.assertEqual(json.loads(out)["error"]["repair_id"],
                                 "adopt.required_check.pending")
        self.assertEqual(git(root, "branch", "--list"), before)
        self.assertEqual(posts(log), [])
        self.assertEqual(self.succeed(root, plan_id)["required_check"]["state"], "added")

    def test_an_unprotected_integration_branch_refuses_before_anything_is_committed(self):
        root = locked_apply_repo(self.home)
        log, state = self.forge(protection=None)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        payload = self.failing(root, plan_id, "adopt.required_check.unprotected")
        self.assertIn("main", payload["error"]["violations"][0]["message"])
        self.assertEqual(posts(log), [])
        rewrite_state(state, protection=DEFAULT_PROTECTION)
        result = self.succeed(root, plan_id)
        self.assertEqual(result["required_check"]["state"], "added")

    def test_a_branch_requiring_no_checks_is_unprotected(self):
        for protection in ({"strict": True, "checks": [], "contexts": []},
                           {"strict": True, "contexts": []}):
            with self.subTest(protection=protection):
                self.home = make_home()
                root = locked_apply_repo(self.home)
                log, _ = self.forge(protection=protection)
                plan_id = self.ready_plan(root)["plan"]["plan_id"]
                self.failing(root, plan_id, "adopt.required_check.unprotected")
                self.assertEqual(posts(log), [])

    def test_a_malformed_or_unreadable_protection_refuses_before_anything_is_committed(self):
        cases = ({"read_fails": True}, {"protection": {"contexts": "Nix Eval"}},
                 {"protection": {"checks": [{"app_id": 1}], "contexts": []}},
                 {"protection": {"strict": True}}, {"protection": []})
        for state in cases:
            with self.subTest(state=state):
                self.home = make_home()
                root = locked_apply_repo(self.home)
                log, _ = self.forge(**state)
                plan_id = self.ready_plan(root)["plan"]["plan_id"]
                self.failing(root, plan_id, "adopt.required_check.unreadable")
                self.assertEqual(posts(log), [])

    def test_an_origin_that_is_not_the_forge_target_refuses_before_any_forge_request(self):
        """P13. Re-planning already sees a moved origin, so a first apply is stale
        before its own origin check; the check is the one a reconciliation and the
        window between planning and the forge read rely on."""
        root = locked_apply_repo(self.home)
        log, state = self.forge(post="lost", read_fails_after_post=True)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        with self.subTest("a first apply"):
            git(root, "remote", "set-url", "origin", "https://github.com/fixture/other.git")
            self.refuse(root, plan_id, "plan_stale")
            self.assertFalse(log.exists() and log.read_text("utf-8"))
            git(root, "remote", "set-url", "origin", "https://github.com/fixture/target.git")
        with self.subTest("the check itself"):
            git(root, "remote", "set-url", "origin", "https://github.com/fixture/other.git")
            with self.assertRaises(adopt_inspection.AdoptError) as raised:
                adopt_conformance.preflight(root, "fixture/target", "main")
            self.assertEqual(raised.exception.repair_id, "adopt.required_check.origin_mismatch")
            self.assertEqual(raised.exception.violations[0]["pointer"],
                             "/plan/conformance/required_check/repo")
            self.assertFalse(log.exists() and log.read_text("utf-8"))
            git(root, "remote", "set-url", "origin", "https://github.com/fixture/target.git")
        with self.subTest("a reconciliation"):
            code, payload, err = self.apply(plan_id)
            self.assertEqual(payload["error"]["repair_id"], "adopt.required_check.unknown")
            calls = log.read_text("utf-8")
            git(root, "remote", "set-url", "origin", "https://github.com/fixture/other.git")
            code, payload, err = self.apply(plan_id)
            self.assertEqual(code, 2, err or payload)
            self.assertEqual(payload["error"]["repair_id"], "adopt.required_check.origin_mismatch")
            self.assertEqual(log.read_text("utf-8"), calls)
            self.assertTrue(self.pending(plan_id).is_file())

    def test_a_check_already_required_is_not_requested_again(self):
        root = locked_apply_repo(self.home)
        protection = {**DEFAULT_PROTECTION, "checks": [
            *DEFAULT_PROTECTION["checks"], {"context": "Conformance", "app_id": None}]}
        log, _ = self.forge(protection=protection)
        result = self.succeed(root, self.ready_plan(root)["plan"]["plan_id"])
        self.assertEqual(result["required_check"]["state"], "already_required")
        self.assertEqual(posts(log), [])
        files = self.branch_files(root, result["branch"])
        self.assertIn(".github/workflows/conformance.yaml", files)
        self.assertIn("agent-platform", git(root, "show", f"{result['branch']}:devenv.lock"))

    def test_a_request_whose_answer_is_lost_but_landed_succeeds(self):
        root = locked_apply_repo(self.home)
        self.forge(post="refuse", post_lands=True)
        result = self.succeed(root, self.ready_plan(root)["plan"]["plan_id"])
        self.assertEqual(result["required_check"]["state"], "added")
        self.assertIn(result["branch"], git(root, "branch", "--list"))

    def test_an_uncommitted_edit_to_the_lock_refuses_as_dirty(self):
        root = locked_apply_repo(self.home)
        log, _ = self.forge()
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        with (root / "devenv.lock").open("a", encoding="utf-8") as handle:
            handle.write(" ")
        self.refuse(root, plan_id, "dirty_worktree")
        self.assertFalse(log.exists() and log.read_text("utf-8"))

    def test_an_adoption_without_a_devenv_lock_makes_no_forge_request(self):
        root = apply_repo(self.home)
        log, _ = self.forge()
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        result = self.succeed(root, plan_id)
        self.assertNotIn("required_check", result)
        self.assertFalse(log.exists() and log.read_text("utf-8"))
        self.assertFalse(self.pending(plan_id).exists())

    def test_an_adoption_without_a_devenv_lock_keeps_its_evidence_record(self):
        root = apply_repo(self.home)
        result = self.succeed(root, self.ready_plan(root)["plan"]["plan_id"])
        record = json.loads(git(
            root, "show", f"{result['branch']}:{result['evidence_record']}"))
        self.assertEqual([check["id"] for check in record["checks"]],
                         list(adopt_inspection.READY_GATES[:-1]))
        self.assertNotIn("conformance", record)


if __name__ == "__main__":
    unittest.main()
