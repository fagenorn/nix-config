"""Contracts for the ship-release skill, a client of the release core.

Checks on the machine-consumed text of the skill: the `release transaction` examples
(each parses against the live parser), the dispatch marker and the cross-file anchors
to CHANGELOG.md. Two executable checks run the skill's previous-tag command against
throwaway local git repositories. Nothing here ever tags, releases, pushes, or deploys
against a real remote: the executable tests build repos under a TemporaryDirectory and
talk to no network.
"""

import json
import os
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[4]
SHIP_RELEASE = REPO_ROOT / "home/common/agent-skills/skills/ship-release/SKILL.md"
CHANGELOG = REPO_ROOT / "home/common/agent-skills/skills/ship-release/CHANGELOG.md"
EVALS = REPO_ROOT / "home/common/agent-skills/skills/ship-release/evals/evals.json"

GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
)


def git_env():
    """A hermetic git environment: no user/system config, no signing.

    Every variable that relocates git's repository, work tree, index or object
    store is dropped, so an invoking session exporting one of them cannot
    redirect this suite's scratch `git init`/`git commit` at an unrelated
    repository (issue 31's D7). The tuple is duplicated from
    test_diff_scope.py rather than imported: the two suites share no helper
    module (issue 31's D10). A blanket GIT_* sweep is rejected because it would
    also drop GIT_EXEC_PATH and GIT_TEMPLATE_DIR, which a Nix-provided git may
    rely on.
    """
    env = dict(os.environ)
    for name in GIT_LOCATION_VARS:
        env.pop(name, None)
    env.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_AUTHOR_NAME": "contract-test",
            "GIT_AUTHOR_EMAIL": "contract-test@example.invalid",
            "GIT_COMMITTER_NAME": "contract-test",
            "GIT_COMMITTER_EMAIL": "contract-test@example.invalid",
            "HOME": env.get("HOME", "/"),
        }
    )
    return env


def sh(command, cwd, extra_env=None):
    env = git_env()
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        ["bash", "-c", command],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"command failed ({completed.returncode}): {command}\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
        )
    return completed.stdout.strip()


class ShipReleaseContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SHIP_RELEASE.read_text(encoding="utf-8")
        cls.changelog = CHANGELOG.read_text(encoding="utf-8")
        cls.evals = json.loads(EVALS.read_text(encoding="utf-8"))

    # -- R5: PREV_TAG must be reachable from the released commit --------------

    def test_prev_tag_selection_is_reachability_restricted(self):
        self.assertIn('--merged "$COMMIT"', self.skill)
        self.assertIn(
            "git describe --tags --abbrev=0 origin/<default>",
            self.skill,
            "pre-flight describe must name an explicit ref, not bare HEAD",
        )
        self.assertNotRegex(
            self.skill,
            r"git tag --list 'v\[0-9\]\*' --sort",
            "an unrestricted repo-wide tag sort must not survive",
        )

    def test_prev_tag_command_ignores_unreachable_tags_in_a_real_repo(self):
        """Execute the skill's exact PREV_TAG command in a repo where a higher semver tag exists on an unmerged side branch. The command prints only PREV_TAG."""
        match = re.search(r"^git for-each-ref --count=1 .*$", self.skill, re.M)
        self.assertIsNotNone(match, "PREV_TAG command missing from SKILL.md")
        command = match.group(0)
        self.assertIn('--merged "$COMMIT"', command)

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            sh("git init -q -b main .", repo)
            sh("echo a > file && git add . && git commit -qm a", repo)
            sh("git tag -a v0.0.9 -m v0.0.9", repo)
            sh("git tag -a v0.1.0 -m v0.1.0", repo)
            sh("git checkout -qb experiment", repo)
            sh("echo x > file && git commit -qam x", repo)
            sh("git tag -a v9.9.9 -m unreachable", repo)
            sh("git checkout -q main", repo)
            sh("echo b >> file && git commit -qam b", repo)
            merge_sha = sh("git rev-parse main", repo)

            prev = sh(command, repo, extra_env={"COMMIT": merge_sha})
            self.assertEqual(prev, "v0.1.0")

            # Sanity: without --merged the wrong tag would have won, so the
            # flag is load-bearing rather than decorative.
            repo_wide = sh(
                "git tag --list 'v[0-9]*' --sort=-v:refname | head -1", repo
            )
            self.assertEqual(repo_wide, "v9.9.9")

    # -- the cross-file anchors between SKILL.md and CHANGELOG.md resolve -------

    def test_cross_file_anchors_resolve(self):
        self.assertIn("CHANGELOG.md#version-bump-signals", self.skill)
        self.assertIn("## Version bump signals", self.changelog)
        self.assertIn("](./SKILL.md#phase-2--version)", self.changelog)
        self.assertIn("\n## Phase 2 — Version\n", self.skill)
        for gone in ("§5d", "#45d-"):
            self.assertNotIn(gone, self.changelog)

    def test_skill_names_no_legacy_state(self):
        # issue 554 D18: the release PR call is reinstated, so "gh pr create" leaves the list.
        for gone in (".superpowers/workflows", "state.json", "headSha", "mergeSha", "prUrl",
                     "releaseUrl", "deployState", "gh pr merge",
                     "gh release create", "git tag -a", "--auto"):
            self.assertNotIn(gone, self.skill)

    def test_a_missing_release_pr_is_opened_with_the_guard_form(self):
        """Issue 554 D1, D9: Phase 3 opens the release PR once, in the guard's pr-create form."""
        phase3 = self.skill.split("## Phase 3", 1)[1].split("\n## ", 1)[0]
        self.assertIn("`release_pr_missing`", phase3)
        self.assertIn('`gh pr create --repo <slug> --base <default> --head <integration> '
                      '--title "<title>" --body "<version>"`', phase3)
        self.assertIn("bindings.tracker.repo_slug", phase3)

    def test_a_two_branch_release_holds_the_land_lock_from_before_the_first_preview(self):
        """Issue 875, ADR-release-011: Phase 3 acquires with a wait before the first preview and
        after the release PR is opened, keeps the lock across the confirmation stop and
        releases it on every other stop; Phase 4 acquires again on a lock refusal. Both forms
        parse against the live `forge-claim` parser."""
        from agent_tools.claims import forge_claim
        phase3 = self.skill.split("## Phase 3", 1)[1].split("\n## ", 1)[0]
        acquire = ("`forge-claim land acquire --repo <slug> --branch <integration> --sha <commit> "
                   "--release --wait`")
        release = "`forge-claim land release --repo <slug> --branch <integration> --sha <commit>`"
        at = 0
        for form in ("Two-branch project: before the first preview, and again after opening the "
                     "release PR, run alone (60-minute timeout) " + acquire,
                     "in resume form, `<commit>` the release's `commit`",
                     "`no_open_pr` goes on to the preview",
                     "Waiting for the confirmation keeps the lock and the run releases it; every "
                     "other stop, a declined confirmation included, first runs " + release,
                     "`release_pr_missing`"):
            with self.subTest(form=form):
                found = phase3.find(form, at)
                self.assertGreaterEqual(found, 0, f"{form} missing or out of order")
                at = found + len(form)
        phase4 = self.skill.split("## Phase 4", 1)[1].split("\n## ", 1)[0]
        self.assertIn("A `confirmation_stale`, `confirmation_required` or, after acquiring again, "
                      "`land_lock_*` refusal is likewise a re-preview.", phase4)
        self.assertIn("land lock, preview", self.skill.split("## Authorization", 1)[1])
        self.assertIn("the run's `sync` and `lock`", self.skill.split("## Phase 5", 1)[1])
        for form in (acquire, release):
            argv = [("octo/widgets" if part == "<slug>" else "dev" if part == "<integration>"
                     else "a" * 40 if part == "<commit>" else part)
                    for part in shlex.split(form.strip("`"))[1:]]
            args = forge_claim.build_parser().parse_args(argv)
            self.assertEqual((args.command, args.branch), ("land", "dev"))
        self.assertTrue(forge_claim.build_parser().parse_args(
            ["land", "acquire", "--repo", "o/r", "--branch", "dev", "--sha", "a" * 40,
             "--release", "--wait"]).release)

    def test_release_examples_parse_and_cover_every_subcommand(self):
        from agent_tools.release import release
        lines = [line for line in self.skill.splitlines()
                 if line.startswith("release transaction ")]
        actions = set()
        for line in lines:
            with self.subTest(line=line):
                args = release.build_parser().parse_args(shlex.split(line)[1:])
                self.assertEqual(args.area, "transaction")
                actions.add(args.action)
        self.assertEqual(actions, {"status", "preview", "run", "abandon"})
        self.assertEqual(len(lines), 6)

    def test_status_is_read_before_nothing_to_release(self):
        phase0 = self.skill.split("## Phase 0", 1)[1].split("\n## ", 1)[0]
        self.assertLess(phase0.index("release transaction status"),
                        phase0.index("git describe --tags --abbrev=0"))

    def test_resume_never_reuses_a_confirmation_and_sync_checks_out_first(self):
        """D30 and D17: tokens rotate on every custody acquisition, so only tokens the user saw
        in that turn are passed; a fast-forward of the local integration branch is preceded by
        its checkout, or in a two-branch project it would move the default branch."""
        self.assertIn("tokens from an earlier yes are never reused", self.skill)
        self.assertIn("a confirmation is never carried across one", self.skill)
        self.assertIn("`git checkout <integration>` and, only if that succeeded, "
                      "`git merge --ff-only origin/<integration>`", self.skill)

    def test_ownership_keeps_the_dispatch_marker_and_one_resolver_call(self):
        marker = ("<!-- agent-dispatch: id=ship-release-owner role=ship-owner model=opus "
                  "effort=high -->")
        self.assertEqual(self.skill.count(marker), 1)
        self.assertEqual(self.skill.count("resolve-project resolve --repo-root <checkout>"), 1)

    # -- R8: evals match the fixture repo and stay non-destructive -------------

    def test_evals_cover_the_fixture_shape_and_release_only_in_the_sandbox(self):
        evals = self.evals["evals"]
        self.assertTrue(evals)
        for case in evals:
            if case.get("mode", "plan-only") == "pipeline":
                self.assertEqual(
                    (case.get("setup") or {}).get("kind"), "release-ready",
                    f"eval {case['id']} is a pipeline case outside the release-ready sandbox",
                )
                continue
            guard = (case["prompt"]).lower()
            self.assertTrue(
                any(
                    marker in guard
                    for marker in (
                        "plan-only",
                        "dry-run",
                        "don't actually",
                        "do not create any tag",
                        "without actually",
                    )
                ),
                f"eval {case['id']} prompt lacks a non-execution guard",
            )
        self.assertTrue(
            any(case.get("mode") == "pipeline" for case in evals),
            "no ship-release pipeline case runs inside the release-ready sandbox",
        )

        self.assertTrue(
            any("kind=none" in case["prompt"] or "single-branch" in case["name"]
                for case in evals),
            "no eval exercises the single-branch/kind=none path",
        )


if __name__ == "__main__":
    unittest.main()
