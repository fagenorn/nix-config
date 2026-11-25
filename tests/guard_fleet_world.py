"""The guard-policy fleet world: a hermetic fleet plus a cutover candidate on a bare origin.

`build_candidate` builds the candidate once: a bare origin, a pusher and a clone, with the real
`python/` tree and the platform manifest committed on `CANDIDATE_BRANCH` and pushed. It is slow, so
a test class builds it once. `GuardFleetWorld` is copied per test: it copies the three repositories
out of that template into its own directory and points both working copies at its own bare origin,
so no push, commit or fetch made by one test reaches another.
"""
import shutil
from pathlib import Path

from agent_tools.verification import verify_checks

from .guard_policy_world import REPO_ROOT, GuardPolicyWorld

CANDIDATE_BRANCH = "cutover-130-candidate"
REPOSITORIES = ("candidate-origin.git", "candidate-pusher", "candidate-clone")


def build_candidate(directory: Path) -> Path:
    """Build the bare origin, its pusher and a clone under `directory`; return `directory`."""
    git = GuardPolicyWorld.git
    bare = directory / "candidate-origin.git"
    pusher = directory / "candidate-pusher"
    clone = directory / "candidate-clone"
    git(directory, "init", "--quiet", "--bare", "-b", "main", str(bare))
    git(directory, "init", "--quiet", "-b", "main", str(pusher))
    git(pusher, "config", "commit.gpgsign", "false")
    git(pusher, "remote", "add", "origin", str(bare))
    (pusher / "README").write_text("main\n", encoding="utf-8")
    git(pusher, "add", "-A")
    git(pusher, "commit", "--quiet", "-m", "main")
    git(pusher, "push", "--quiet", "origin", "main")
    git(pusher, "checkout", "--quiet", "-b", CANDIDATE_BRANCH)
    shutil.copytree(REPO_ROOT / "python", pusher / "python",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (pusher / verify_checks.MANIFEST_PATH).parent.mkdir(parents=True)
    shutil.copy(REPO_ROOT / verify_checks.MANIFEST_PATH, pusher / verify_checks.MANIFEST_PATH)
    git(pusher, "add", "-A")
    git(pusher, "commit", "--quiet", "-m", "candidate")
    git(pusher, "push", "--quiet", "origin", f"HEAD:refs/heads/{CANDIDATE_BRANCH}")
    git(bare, "repack", "-a", "-d", "-q")
    git(pusher, "repack", "-a", "-d", "-q")
    git(directory, "clone", "--quiet", str(bare), str(clone))
    return directory


class GuardFleetWorld(GuardPolicyWorld):
    """A hermetic fleet plus a clone whose origin carries the cutover candidate: the real
    `python/` tree and platform manifest, committed on `cutover-130-candidate`, copied from
    `template` (the directory `build_candidate` returned) so this world owns its repositories."""

    def __init__(self, test_case, template: Path):
        super().__init__(test_case)
        for name in REPOSITORIES:
            # `copy` keeps the file modes git tracks and skips the per-file timestamp and attribute
            # copying of `copy2`, which dominated the copy; the refresh below re-reads the index.
            shutil.copytree(template / name, self.tmp / name, symlinks=True,
                            copy_function=shutil.copy)
        bare = self.tmp / "candidate-origin.git"
        self.clone = self.tmp / "candidate-clone"
        for working in (self.tmp / "candidate-pusher", self.clone):
            self.git(working, "remote", "set-url", "origin", str(bare))
            self.git(working, "update-index", "-q", "--refresh")

    def fleet(self, registry=None):
        # The host's own PYTHONPATH must not decide whose code derives: the check does.
        environ = {key: value for key, value in self.env.items() if key != "PYTHONPATH"}
        return verify_checks.guard_policy_fleet(
            self.clone, CANDIDATE_BRANCH, environ=environ, registry=registry)

    def lagging_default(self, project_id, slug, *, override):
        """The anis-desktop nodocom entry: `main` is a schema-1 contract, `dev` a schema-2 one,
        and the registry entry carries the `branch_override` only when `override` is true."""
        root = self.project(project_id, slug, integration_branch="dev", register=False)
        self.git(root, "checkout", "--quiet", "main")
        old = self.contract(project_id, slug)
        old["schema_version"] = 1
        self.commit_contract(root, old, "the project's schema-1 default branch", render=False)
        self.publish(root, ["main", "dev"])
        entry = {"project_id": project_id, "root": str(root)}
        if override:
            entry["branch_override"] = {"branch": "dev", "default_branch": "main",
                                        "reason": "default_contract_unresolved"}
        self.register(entry)
