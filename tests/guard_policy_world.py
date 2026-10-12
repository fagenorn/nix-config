"""A hermetic fleet for the guard-policy suites (issue 126 D10).

`GuardPolicyWorld(test_case)` builds a temporary `HOME` holding the platform manifest, a base
policy file, and a `bin/` with `git` and `gh` shims that is first on the `PATH` of `env`.
`project(...)` commits a conformant contract derived from this repository's own, publishes it
to a local bare `origin` and returns the checkout; `register(...)` writes the fleet registry.

The `git` shim answers only `remote get-url origin` and `remote get-url --push --all origin`,
from `identities.json` keyed by its working directory, and hands every other call to the real
`git`; with no entry for the directory it hands those two over as well. The `gh` shim answers
`api repos/<slug> --jq .full_name` from `providers.json`, exits 64 for any other call and 65
when a token variable reaches it. Nothing contacts a network remote or reads the host registry.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
PUBLICATION_FREE = REPO_ROOT / "tests/fixtures/release/publication-free-profile.json"
OWN_SLUG = "fagenorn/nix-config"
REAL_GIT = shutil.which("git")

GIT_SHIM = """#!{python}
import json, os, sys
argv = sys.argv[1:]
answers = json.loads(open({state!r} + "/identities.json", encoding="utf-8").read())
answer = answers.get(os.path.realpath(os.getcwd()))
if answer is not None and argv == ["remote", "get-url", "origin"]:
    print(answer["origin"])
elif answer is not None and argv == ["remote", "get-url", "--push", "--all", "origin"]:
    print("\\n".join(answer["pushes"]))
else:
    os.execv({git!r}, [{git!r}, *argv])
"""

GH_SHIM = """#!{python}
import json, os, sys
argv = sys.argv[1:]
if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
    sys.stderr.write("gh: a token variable reached the child\\n")
    sys.exit(65)
answers = json.loads(open({state!r} + "/providers.json", encoding="utf-8").read())
if len(argv) == 4 and argv[0] == "api" and argv[2:] == ["--jq", ".full_name"] \\
        and argv[1] in answers:
    answer = answers[argv[1]]
    sys.stdout.write(answer["stdout"])
    sys.exit(answer["exit"])
sys.stderr.write("fake gh: unregistered call\\n")
sys.exit(64)
"""


class GuardPolicyWorld:
    def __init__(self, test_case: unittest.TestCase) -> None:
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.home, self.bin, self.state = (self.tmp / name for name in ("home", "bin", "state"))
        for directory in (self.home / ".agents/share", self.bin, self.state):
            directory.mkdir(parents=True)
        shutil.copy(MANIFEST, self.home / ".agents/share/platform-manifest.json")
        for name, text in (("git", GIT_SHIM), ("gh", GH_SHIM)):
            shim = self.bin / name
            shim.write_text(text.format(python=sys.executable, state=str(self.state),
                                        git=REAL_GIT), encoding="utf-8")
            shim.chmod(0o755)
        self.identities: dict[str, dict] = {}
        self.providers: dict[str, dict] = {}
        self._save()
        self.entries: list[dict] = []
        self.base = self.tmp / "base-policy.json"
        self.output = self.home / ".agents/state/guard/policy.json"
        self.write_base()
        # GITHUB_TOKEN is set on purpose: the compiler must scrub it before `gh` (D7).
        self.env = {**os.environ, "HOME": str(self.home), "GITHUB_TOKEN": "harness-token",
                    "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                    "PYTHONPATH": str(REPO_ROOT / "python"),
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

    def _save(self) -> None:
        (self.state / "identities.json").write_text(json.dumps(self.identities), "utf-8")
        (self.state / "providers.json").write_text(json.dumps(self.providers), "utf-8")

    def write_base(self, **members: object) -> dict:
        document = {"authorized_owners": ["fagenorn"],
                    "integration_bases": {"fagenorn/arcwave": "dev"},
                    "git_bin": "/usr/bin/git", "gh_bin": "/usr/bin/gh", "jq_bin": "/usr/bin/jq",
                    "derived_repositories": {}, "derivation": None, **members}
        self.base.write_text(json.dumps(document), encoding="utf-8")
        return document

    def git(self, root: Path, *args: str) -> str:
        return subprocess.run(
            [REAL_GIT, "-C", str(root), *args], capture_output=True, text=True, timeout=120,
            check=True, env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
                             "GIT_CONFIG_SYSTEM": os.devnull,
                             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                             "GIT_COMMITTER_NAME": "t",
                             "GIT_COMMITTER_EMAIL": "t@example.invalid"}).stdout

    def contract(self, project_id: str, slug: str, *, integration_branch: str = "main",
                 publication_free: bool = False) -> dict:
        """This repository's own contract, renamed to `slug` (so it stays grammar-valid)."""
        text = (REPO_ROOT / ".agents/project.json").read_text("utf-8")
        contract = json.loads(text.replace(OWN_SLUG, slug))
        contract["project"] = {"id": project_id, "name": project_id.split("/")[-1]}
        contract["bindings"]["vcs"]["integration_branch"] = integration_branch
        if publication_free:
            profile = PUBLICATION_FREE.read_text("utf-8").replace(OWN_SLUG, slug)
            contract["release"] = {"profiles": {"forge-main": json.loads(profile)}}
        return contract

    def commit_contract(self, root: Path, contract: dict, message: str = "contract", *,
                        render: bool = True) -> None:
        """Write `contract`, render its projections with the resolver unless `render` is
        false (a contract the resolver refuses cannot be rendered), and commit everything."""
        path = root / ".agents/project.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        (root / ".agents/instructions").mkdir(exist_ok=True)
        (root / ".agents/instructions/bootstrap.md").write_text("# invariants\n", "utf-8")
        for name in ("standards", "rejections"):
            for relative in contract["bindings"]["paths"][name]:
                (root / relative).mkdir(parents=True, exist_ok=True)
                (root / relative / "keep.md").write_text("# keep\n", "utf-8")
        for relative in contract["bindings"]["paths"]["architecture"]:
            if not (root / relative).exists():
                (root / relative).write_text("# architecture\n", "utf-8")
        if render:
            done = subprocess.run(
                [sys.executable, "-m", "agent_tools.resolve_project", "write-projections",
                 "--repo-root", str(root)],
                capture_output=True, text=True, timeout=120, env=self.env)
            if done.returncode != 0:
                raise AssertionError(f"fixture projections could not be rendered: {done.stdout}")
        self.git(root, "add", "-A")
        self.git(root, "commit", "--quiet", "-m", message)

    def project(self, project_id: str, slug: str, *, integration_branch: str = "main",
                publication_free: bool = False, register: bool = True,
                override: bool = False, mutate=None) -> Path:
        """A published, conformant checkout for `slug`; its registry entry unless `register`
        is false. With another `integration_branch` than `main`, `origin` also gets that
        branch; `override=True` makes `main`'s contract unresolvable and records the override."""
        root = self.tmp / "projects" / project_id.replace("/", "-")
        root.mkdir(parents=True)
        self.git(root, "init", "--quiet", "-b", "main")
        self.git(root, "config", "commit.gpgsign", "false")
        contract = self.contract(project_id, slug, integration_branch=integration_branch,
                                 publication_free=publication_free)
        if mutate is not None:
            mutate(contract)
        self.commit_contract(root, contract)
        refs = ["main"]
        if integration_branch != "main":
            self.git(root, "branch", integration_branch)
            refs.append(integration_branch)
        if override:
            broken = dict(contract)
            del broken["release"]
            self.commit_contract(root, broken, "a default branch that lags", render=False)
        self.publish(root, refs)
        self.identity(root, f"git@github.com:{slug}.git")
        self.provider(slug)
        entry = {"project_id": project_id, "root": str(root)}
        if override:
            entry["branch_override"] = {"branch": integration_branch, "default_branch": "main",
                                        "reason": "default_contract_unresolved"}
        if register:
            self.register(entry)
        return root

    def publish(self, root: Path, refs: list[str], *, default: str = "main") -> Path:
        """Push `refs` to a new local bare repository and make it `origin`."""
        bare = Path(tempfile.mkdtemp(dir=self.tmp)) / "origin.git"
        self.git(self.tmp, "init", "--quiet", "--bare", "-b", default, str(bare))
        verb = "set-url" if "origin" in self.git(root, "remote").split() else "add"
        self.git(root, "remote", verb, "origin", str(bare))
        self.git(root, "push", "--quiet", "--force", "origin",
                 *(f"{ref}:refs/heads/{ref}" for ref in refs))
        return bare

    def identity(self, root: Path, origin: str | None, pushes: list[str] | None = None) -> None:
        """What the `git` shim reports as `root`'s origin urls; `None` restores the real ones."""
        key = os.path.realpath(root)
        if origin is None:
            self.identities.pop(key, None)
        else:
            self.identities[key] = {"origin": origin,
                                    "pushes": [origin] if pushes is None else pushes}
        self._save()

    def provider(self, slug: str, full_name: str | None = None, exit: int = 0) -> None:
        self.providers[f"repos/{slug}"] = {"stdout": (full_name or slug) + "\n", "exit": exit}
        self._save()

    def register(self, *entries: dict) -> None:
        self.entries.extend(entries)
        self.write_registry({"schema_version": 1, "projects": self.entries})

    def write_registry(self, document: object) -> Path:
        path = self.home / ".agents/state/fleet/registry.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document if isinstance(document, str) else json.dumps(document), "utf-8")
        return path

    def compile(self, *, base: Path | None = None, output: Path | None = None,
                env: dict | None = None) -> tuple[int, dict, str]:
        """Run the command from source: `(exit status, parsed report, stderr)`."""
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.guard_policy", "compile",
             "--base", str(base or self.base), "--output", str(output or self.output)],
            capture_output=True, text=True, timeout=300, env=env or self.env, cwd=self.tmp)
        return done.returncode, json.loads(done.stdout), done.stderr

    def derive(self, repository: str, *, env: dict | None = None) -> tuple[int, dict, str]:
        """Run `derive` from source: `(exit status, parsed report, stderr)`."""
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.guard_policy", "derive",
             "--repository", repository],
            capture_output=True, text=True, timeout=300, env=env or self.env, cwd=self.tmp)
        return done.returncode, json.loads(done.stdout), done.stderr

    def policy(self) -> dict:
        return json.loads(self.output.read_text("utf-8"))
