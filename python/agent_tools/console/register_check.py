"""The check of the console's project registration (#1052), Task 3 holding only the fixture builder.

`CONTRACT_SOURCE` is the pinned schema-2 contract, relative to a checkout root.

`adopted_repository(parent, project_id, contract_source, *, environ=None)` builds, at `parent/"repo"`,
a conformant, adopted repository on `main` and returns its resolved root: the contract is
`contract_source` with the project id and name, the artifact paths, the rejections, `release`
unsupported and both review commands `true`, so that no capability depends on the host; the
instruction source and both projections are written by the `resolve-project write-projections`
child (a non-zero exit raises `RuntimeError`); each standards path holds one file; the runtime
`.gitignore` is force-added; the two adoption records are committed as `adopt`. Its `origin` is a
bare `parent/"origin.git"` holding `main`. Every git call ignores the user's and the system's git
configuration, and `environ` (default: the process's) is the resolver child's environment.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from agent_tools.system import siblings

CONTRACT_SOURCE = Path("home/common/agent-skills/tests/fixtures/project-contract-schema-2.json")
DIGEST = "a1" * 32
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _git(root: Path, *arguments: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *arguments], check=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, env={**os.environ, **GIT_ENV})
    return done.stdout


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", message)


def _contract(contract_source: Path, project_id: str) -> dict:
    contract = json.loads(contract_source.read_text("utf-8"))
    contract["project"] = {"id": project_id, "name": project_id.split("/")[-1]}
    contract["bindings"]["paths"]["artifacts"] = {
        "specs": ".agents/artifacts/specs", "plans": ".agents/artifacts/plans"}
    contract["bindings"]["paths"]["rejections"] = [".agents/knowledge/rejections"]
    contract["release"] = "unsupported"
    review = contract["bindings"]["workflow"]["review"]
    for role in ("plan", "code"):
        contract["bindings"]["commands"][review[role]]["argv"] = ["true"]
    contract["bindings"]["tracker"]["cli"] = "gh"
    contract["bindings"]["vcs"]["integration_branch"] = "main"
    return contract


def _scaffold(root: Path, contract: dict, environ: Mapping[str, str]) -> None:
    _write(root, ".agents/instructions/bootstrap.md", "# invariants\n")
    for standards in contract["bindings"]["paths"]["standards"]:
        (root / standards).mkdir(parents=True, exist_ok=True)
    _write(root, ".agents/project.json", json.dumps(contract, indent=2) + "\n")
    done = subprocess.run(
        [*siblings.sibling_argv("project_contract.resolve_project"),
         "write-projections", "--repo-root", str(root)],
        env=dict(environ), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(f"the fixture projections could not be rendered: {done.stdout}")


def _adoption_records(root: Path) -> None:
    migration_map = f".agents/knowledge/archive/path-migrations/{DIGEST}.json"
    _write(root, migration_map, json.dumps({
        "schema_version": 1, "migration_id": f"sha256:{DIGEST}", "moves": []}) + "\n")
    _write(root, f".agents/artifacts/evidence/{DIGEST}.json", json.dumps({
        "schema_version": 1, "plan_id": f"sha256:{DIGEST}", "outcome": "no_change",
        "base_revision": _git(root, "rev-parse", "HEAD").strip(),
        "platform": {"platform_version": "1.0.0", "project_schema_versions": [1],
                     "resolved_schema_version": 1},
        "decisions_accepted": [], "sources": [], "checks": [],
        "path_migration_map": migration_map}) + "\n")


def adopted_repository(parent: Path, project_id: str, contract_source: Path, *,
                       environ: Mapping[str, str] | None = None) -> Path:
    root = parent / "repo"
    root.mkdir(parents=True)
    root = root.resolve()
    _git(root, "init", "--quiet", "-b", "main")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    contract = _contract(contract_source, project_id)
    _scaffold(root, contract, os.environ if environ is None else environ)
    _write(root, ".agents/runtime/.gitignore", "*\n")
    _git(root, "add", "-f", ".agents/runtime/.gitignore")
    for standards in contract["bindings"]["paths"]["standards"]:
        _write(root, f"{standards}/bar.md", "# the bar\n")
    _commit(root, "fixture")
    _adoption_records(root)
    _commit(root, "adopt")
    bare = parent / "origin.git"
    _git(parent, "init", "--quiet", "--bare", "-b", "main", str(bare))
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "push", "--quiet", "origin", "main")
    return root
