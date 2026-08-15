"""Contracts for the ship-release skill's release state machine.

Text-anchor tests in the style of test_workflow_skill_contracts.py, plus two
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


def git_env():
    """A hermetic git environment: no user/system config, no signing."""
    env = dict(os.environ)
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

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertNotEqual(next_position, -1, f"missing anchor: {anchor!r}")
            self.assertGreater(
                next_position, position, f"out-of-order anchor: {anchor!r}"
            )
            position = next_position

    def section(self, text, heading, next_heading):
        start = text.index(heading)
        end = text.index(next_heading, start + len(heading))
        return text[start:end]

    # -- R1: single-branch path keeps the version/changelog prerequisites -----

    def test_single_branch_runs_phases_zero_and_one_then_skips_two_to_four(self):
        bindings = self.section(
            self.skill, "## Project bindings", "## Durable release state"
        )
        self.assert_ordered(
            bindings,
            "run Phases 0 **and** 1",
            "skip Phases 2–4",
            "continue at Phase 4.5",
        )
        self.assertNotIn("skip straight to Phase 4.5", self.skill)
        # kind == none likewise runs the prerequisites before its local merge.
        self.assert_ordered(
            bindings,
            'issueTracker.kind == "none"',
            "run Phases 0–1",
            "git merge --no-ff",
        )
        # CHANGELOG documents the single-branch mining range.
        self.assertIn("Single-branch (`<integration> == <default>`)", self.changelog)
        self.assertIn("drop `--merges`", self.changelog)

    # -- R2: no-PR paths tag the local merge result, never the stale remote ---

    def test_merge_sha_command_targets_local_default_not_remote(self):
        self.assertIn("MERGE_SHA=$(git rev-parse <default>)", self.skill)
        self.assertNotIn("git rev-parse origin/<default>)", self.skill)
        phase_45 = self.section(self.skill, "## Phase 4.5", "## Phase 5")
        self.assert_ordered(
            phase_45,
            "no-PR paths",
            "AFTER any local merge",
            "MERGE_SHA=$(git rev-parse <default>)",
        )
        self.assertIn("stale pre-merge tip", phase_45)

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

    # -- R4: skip-check runs before anything is tagged or created -------------

    def test_existing_release_skip_check_precedes_tag_and_release_creation(self):
        phase_45 = self.section(self.skill, "## Phase 4.5", "## Phase 5")
        self.assert_ordered(
            phase_45,
            "### 4.5a. Resolve the merge SHA",
            "### 4.5b. Skip condition",
            "Don't double-tag",
            "### 4.5e. Tag the merge commit",
            "git tag -a",
            "gh release create",
        )
        # The forge-less variant of the skip-check exists too.
        self.assertIn('git tag --points-at "$MERGE_SHA"', phase_45)

    # -- R3: Phase 0 resumes from durable state and merged PRs ----------------

    def test_phase_zero_consults_state_and_merged_prs_before_stopping(self):
        phase_zero = self.section(self.skill, "## Phase 0", "## Phase 1")
        self.assert_ordered(
            phase_zero,
            "Resume check",
            STATE_PATH,
            "--state merged",
            "mergeCommit",
            "nothing to release",
        )
        self.assertIn("resume at Phase 4.5", phase_zero)
        self.assertIn("jump to Phase 5", phase_zero)
        # The wakeup path re-enters through the same resume check.
        self.assertIn("Phase 0 resume check", self.skill)

    # -- R5: PREV_TAG must be reachable from the released commit --------------

    def test_prev_tag_selection_is_reachability_restricted(self):
        self.assertIn('--merged "$MERGE_SHA"', self.skill)
        phase_zero = self.section(self.skill, "## Phase 0", "## Phase 1")
        self.assertIn(
            "git describe --tags --abbrev=0 origin/<default>",
            phase_zero,
            "pre-flight describe must name an explicit ref, not bare HEAD",
        )
        self.assertNotRegex(
            self.skill,
            r"git tag --list 'v\[0-9\]\*' --sort",
            "an unrestricted repo-wide tag sort must not survive",
        )

    def test_prev_tag_command_ignores_unreachable_tags_in_a_real_repo(self):
        """Execute the skill's exact PREV_TAG command in a repo where a higher
        semver tag exists on an unmerged side branch."""
        match = re.search(r"^PREV_TAG=\$\(git tag --list .*\)$", self.skill, re.M)
        self.assertIsNotNone(match, "PREV_TAG command missing from SKILL.md")
        command = match.group(0)
        self.assertIn('--merged "$MERGE_SHA"', command)

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            sh("git init -q -b main .", repo)
            sh("echo a > file && git add . && git commit -qm a", repo)
            sh("git tag -a v0.1.0 -m v0.1.0", repo)
            sh("git checkout -qb experiment", repo)
            sh("echo x > file && git commit -qam x", repo)
            sh("git tag -a v9.9.9 -m unreachable", repo)
            sh("git checkout -q main", repo)
            sh("echo b >> file && git commit -qam b", repo)
            merge_sha = sh("git rev-parse main", repo)

            prev = sh(
                f'{command} && echo "$PREV_TAG"',
                repo,
                extra_env={"MERGE_SHA": merge_sha},
            )
            self.assertEqual(prev, "v0.1.0")

            # Sanity: without --merged the wrong tag would have won, so the
            # flag is load-bearing rather than decorative.
            repo_wide = sh(
                "git tag --list 'v[0-9]*' --sort=-v:refname | head -1", repo
            )
            self.assertEqual(repo_wide, "v9.9.9")

    # -- R6: exactly one semver rubric ----------------------------------------

    def test_semver_rubric_lives_only_in_changelog(self):
        self.assertIn("## Version bump signals", self.changelog)
        self.assertIn("This table is the only copy of the rubric", self.changelog)
        self.assertIn("CHANGELOG.md#version-bump-signals", self.skill)
        # Rubric bodies must not be duplicated back into SKILL.md.
        for rubric_fragment in (
            "refuses to start without",
            "shifts down one slot",
            "semver.org/#spec-item-4",
        ):
            self.assertNotIn(rubric_fragment, self.skill)
        # The proposal template stays with the workflow.
        self.assertIn("Proposed next version", self.skill)
        # The CHANGELOG anchor targets a heading that actually exists.
        self.assertIn("### 4.5d. Decide MAJOR / MINOR / PATCH", self.skill)
        self.assertIn("#45d-decide-major--minor--patch", self.changelog)

    # -- R7: durable state persisted at each transition ------------------------

    def test_durable_state_is_persisted_at_every_transition(self):
        self.assertIn("## Durable release state", self.skill)
        state_section = self.section(
            self.skill, "## Durable release state", "## The flow"
        )
        for field in ("headSha", '"pr"', "prUrl", "mergeSha", "tag", "releaseUrl", "deployState"):
            self.assertIn(field, state_section)
        self.assertIn("atomically", state_section)
        self.assert_ordered(
            self.skill,
            "Persist `pr` + `prUrl`",  # Phase 2
            "persist `mergeSha`",  # Phase 4, before anything else
            "Persist `tag`",  # 4.5e
            "persist `releaseUrl`",  # 4.5g
            f"Delete `{STATE_PATH}`",  # Phase 6
        )
        phase_four = self.section(self.skill, "## Phase 4 — Merge", "## Phase 4.5")
        self.assert_ordered(
            phase_four, "mergeCommit.oid", "persist `mergeSha`", "before doing anything else"
        )

    # -- R8: evals match the fixture repo and stay non-destructive -------------

    def test_evals_cover_the_fixture_shape_and_never_execute_a_release(self):
        notes = self.evals["notes"]
        for fragment in ("plan-only", "kind=none", "fixture-repo"):
            self.assertIn(fragment, notes)

        evals = self.evals["evals"]
        self.assertTrue(evals)
        for case in evals:
            self.assertNotEqual(
                case.get("mode", "plan-only"),
                "pipeline",
                f"eval {case['id']} must stay plan-only (non-destructive)",
            )
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

        single_branch = [
            case
            for case in evals
            if "kind=none" in case["prompt"] or "single-branch" in case["name"]
        ]
        self.assertTrue(single_branch, "no eval exercises the single-branch/kind=none path")
        expected = single_branch[0]["expected_output"]
        for fragment in (
            "git rev-parse <default>",
            "--merged",
            STATE_PATH,
            "Phases 0 AND 1",
            "double-tag",
        ):
            self.assertIn(fragment, expected)


if __name__ == "__main__":
    unittest.main()
