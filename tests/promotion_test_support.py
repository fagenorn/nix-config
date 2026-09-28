"""Shared support for the promotion suites (#127 D16 seam 1, D28).

The hermetic runner, the stub resolver and the document builders. It declares
no TestCase, so it is support rather than a suite and is not listed as one.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from agent_tools.canonical import telemetry_digest

# An authored `null` sha256. Fixtures pass this sentinel, never `digest or computed` (D16).
NULL_DIGEST = object()


def resolved_project(root, project_id="fagenorn/nix-config", slug="fagenorn/nix-config",
                     kind="github"):
    """A ResolvedProject with the real resolver's member shape for `root`."""
    return {"schema_version": 1,
            "project": {"id": project_id, "name": "fixture", "root": str(root)},
            "bindings": {"tracker": {"cli": "gh", "kind": kind, "repo_slug": slug,
                                     "credential_env": {"unset_before_invocation": []}}},
            "capabilities": {}}


def make_env(tmp: Path, resolved=None, *, resolver_exit=0, resolver_stdout=None):
    """An env whose PATH holds only a `resolve-project` stub. The stub appends its
    argv to `tmp/resolver-argv.jsonl`, prints `resolved` (or `resolver_stdout`
    verbatim) and exits `resolver_exit`."""
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    payload = tmp / "resolver-stdout.txt"
    payload.write_text(resolver_stdout if resolver_stdout is not None
                       else json.dumps(resolved), encoding="utf-8")
    stub = bin_dir / "resolve-project"
    stub.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"open({str(tmp / 'resolver-argv.jsonl')!r}, 'a').write("
        "json.dumps(sys.argv[1:]) + '\\n')\n"
        f"sys.stdout.write(open({str(payload)!r}).read())\n"
        f"raise SystemExit({resolver_exit})\n", encoding="utf-8")
    stub.chmod(0o755)
    # Absolute, so a run with its own `cwd` still imports the package under test.
    package_path = os.pathsep.join(os.path.abspath(entry) for entry
                                   in os.environ["PYTHONPATH"].split(os.pathsep))
    return {"PATH": str(bin_dir), "PYTHONPATH": package_path,
            "HOME": str(tmp), "TMPDIR": str(tmp), "LANG": "C"}


def run(env, *args, cwd=None):
    """One `python -m agent_tools.promotion` run: (exit, parsed stdout or None, stderr)."""
    proc = subprocess.run([sys.executable, "-m", "agent_tools.promotion", *args],
                          capture_output=True, text=True, timeout=60, env=env,
                          cwd=None if cwd is None else str(cwd), check=False)
    return (proc.returncode, json.loads(proc.stdout) if proc.stdout.strip() else None,
            proc.stderr)


def write_json(path: Path, document) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def citation(repository="fagenorn/argus", path="AGENTS.md", anchor="## How we collaborate"):
    return {"repository": repository, "path": path, "revision": None, "anchor": anchor}


def duplicate(repository="fagenorn/argus", path="AGENTS.md", sha256=NULL_DIGEST,
              disposition="remove"):
    return {"repository": repository, "path": path,
            "sha256": None if sha256 is NULL_DIGEST else sha256, "disposition": disposition}


def draft(**overrides):
    document = {
        "schema_version": 1, "kind": "promotion-candidate-draft",
        "lesson": {"title": "Investigate before changing",
                   "statement": "Read what already governs the code before changing it.",
                   "source": citation()},
        "destination": {"layer": "standard_layer", "owner": "standards", "name": "the-bar",
                        "path": "home/common/agent-skills/standards/the-bar.md",
                        "anchor": "### Investigate before changing"},
        "corroboration": {"repositories": [citation(),
                                           citation("elevenyellow/nodocom", "CLAUDE.md")],
                          "platform_governance": None},
        "local_duplicates": [duplicate()],
        "native_admission": None,
    }
    document.update(overrides)
    return document


AUTHORED = ("lesson", "destination", "corroboration", "local_duplicates", "native_admission")


def candidate_document(**overrides):
    body = draft()
    authored = {member: body[member] for member in AUTHORED}
    document = {"schema_version": 1, "kind": "promotion-candidate",
                "candidate_id": telemetry_digest(authored), "state": "captured", **authored,
                "classification": None, "evidence": None, "deployment": None,
                "tracker": {"ref": None, "label": "promotion-candidate",
                            "create_command": ["gh", "issue", "create"]},
                "history": [{"from": None, "to": "captured", "actor": None,
                             "rationale": None}]}
    document.update(overrides)
    return document


def evaluation_document(**overrides):
    document = {"schema_version": 1, "kind": "promotion-evaluation",
                "evaluation_id": "sha256:" + "c" * 64,
                "scope": {"repository": "fagenorn/nix-config", "revision": None},
                "commands": ["rg -n Investigate ."], "candidates": [], "outcome": "empty"}
    document.update(overrides)
    return document
