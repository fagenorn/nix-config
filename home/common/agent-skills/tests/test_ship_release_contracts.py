"""Contracts for the ship-release skill's release state machine.

Checks on the machine-consumed text of the skill (its commands, state-file
fields and cross-file anchors; #291 D6 deletes guidance-prose pins), plus two
executable checks that run the skill's exact commands against throwaway local
git repositories. Nothing here ever tags, releases, pushes, or deploys against
a real remote: the executable tests build repos under a TemporaryDirectory and
talk to no network.
"""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[4]
SHIP_RELEASE = REPO_ROOT / "home/common/agent-skills/skills/ship-release/SKILL.md"
CHANGELOG = REPO_ROOT / "home/common/agent-skills/skills/ship-release/CHANGELOG.md"
EVALS = REPO_ROOT / "home/common/agent-skills/skills/ship-release/evals/evals.json"

STATE_PATH = ".superpowers/workflows/ship-release/state.json"


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

    def section(self, text, heading, next_heading):
        start = text.index(heading)
        end = text.index(next_heading, start + len(heading))
        return text[start:end]

    # -- R2: no-PR paths tag the local merge result, never the stale remote ---

    def test_merge_sha_command_targets_local_default_not_remote(self):
        self.assertIn("MERGE_SHA=$(git rev-parse <default>)", self.skill)
        self.assertNotIn("git rev-parse origin/<default>)", self.skill)

    def test_merge_sha_command_resolves_local_merge_in_a_real_repo(self):
        """Execute the skill's exact no-PR MERGE_SHA command after a local
        --no-ff merge with a deliberately stale origin/<default>."""
        match = re.search(
            r"^MERGE_SHA=\$\(git rev-parse <default>\)$", self.skill, re.M
        )
        self.assertIsNotNone(match, "no-PR MERGE_SHA command missing from SKILL.md")
        command = match.group(0).replace("<default>", "main")

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            sh("git init -q -b main .", repo)
            sh("echo base > file && git add . && git commit -qm base", repo)
            # Freeze the remote-tracking ref at the pre-merge tip.
            sh("git update-ref refs/remotes/origin/main HEAD", repo)
            sh("git checkout -qb integration", repo)
            sh("echo feature > file && git commit -qam feature", repo)
            sh("git checkout -q main", repo)
            sh("git merge -q --no-ff integration -m 'merge: release'", repo)

            resolved = sh(f'{command} && echo "$MERGE_SHA"', repo)
            local_tip = sh("git rev-parse main", repo)
            stale_remote = sh("git rev-parse origin/main", repo)

            self.assertEqual(resolved, local_tip)
            self.assertNotEqual(
                resolved,
                stale_remote,
                "the skill's command must not resolve the stale remote tip",
            )

    # -- R4: the forge-less skip-check command ---------------------------------

    def test_forge_less_skip_check_reads_the_tags_at_the_merge_sha(self):
        self.assertIn('git tag --points-at "$MERGE_SHA"', self.skill)

    # -- R3: Phase 0 resumes from durable state and merged PRs ----------------

    def test_phase_zero_reads_the_state_file_and_merged_prs(self):
        for argv in (STATE_PATH, "--state merged", "mergeCommit"):
            self.assertIn(argv, self.skill)

    # -- R5: PREV_TAG must be reachable from the released commit --------------

    def test_prev_tag_selection_is_reachability_restricted(self):
        self.assertIn('--merged "$MERGE_SHA"', self.skill)
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
        self.assertIn('--merged "$MERGE_SHA"', command)

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

            prev = sh(command, repo, extra_env={"MERGE_SHA": merge_sha})
            self.assertEqual(prev, "v0.1.0")

            # Sanity: without --merged the wrong tag would have won, so the
            # flag is load-bearing rather than decorative.
            repo_wide = sh(
                "git tag --list 'v[0-9]*' --sort=-v:refname | head -1", repo
            )
            self.assertEqual(repo_wide, "v9.9.9")

    # -- R6: the cross-file anchors between SKILL.md and CHANGELOG.md resolve --

    def test_cross_file_anchors_resolve(self):
        self.assertIn("CHANGELOG.md#version-bump-signals", self.skill)
        self.assertIn("## Version bump signals", self.changelog)
        self.assertIn("#45d-decide-major--minor--patch", self.changelog)
        self.assertIn("### 4.5d. Decide MAJOR / MINOR / PATCH", self.skill)

    # -- R7: the durable state file's fields ----------------------------------

    def test_durable_state_names_every_field(self):
        state_section = self.section(
            self.skill, "## Durable release state", "## The flow"
        )
        for field in ("headSha", '"pr"', "prUrl", "mergeSha", "tag", "releaseUrl", "deployState"):
            self.assertIn(field, state_section)

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
