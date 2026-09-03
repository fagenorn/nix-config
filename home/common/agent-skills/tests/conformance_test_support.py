"""Shared support for the conformance suites.

Holds the fixture builders, the hermetic subprocess runner, the stub-`PATH`
bin, the shared report assertion, the rebinding cleanup and the S3 module
loader that `test_conformance`, `test_conformance_checks` and
`test_conformance_registry` all reach for (D40). It declares no TestCase, so
it is support rather than a suite and is not listed as one.

Every run is environment-hermetic (D35): the child never inherits the caller's
environment, so no test can reach the network, the caller's credentials or a
tool the fixture did not place. HERMETIC_ENV points PATH at a stub bin holding
one exit-0 script per tool the contract names; a case that needs a different
tool outcome builds its own bin with make_stub_bin and overrides PATH.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "conformance.py"
REPO_ROOT = Path(__file__).resolve().parents[4]
STUB_TOOLS = ("codex", "gh", "git", "just")


def make_stub_bin(directory: Path, exits: dict | None = None) -> str:
    """A bin directory holding one executable stub per STUB_TOOLS.

    Each stub prints nothing and exits 0 unless `exits` names a different code
    for it, so a fixture decides every tool outcome the engine can observe.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for tool in STUB_TOOLS:
        stub = directory / tool
        stub.write_text(f"#!/bin/sh\nexit {(exits or {}).get(tool, 0)}\n",
                        encoding="utf-8")
        stub.chmod(0o755)
    return str(directory)


_HERMETIC_HOME = tempfile.mkdtemp(prefix="conformance-home-")
HERMETIC_ENV = {
    "PATH": make_stub_bin(Path(tempfile.mkdtemp(prefix="conformance-bin-"))),
    "HOME": _HERMETIC_HOME,
    "TMPDIR": _HERMETIC_HOME,
    "LANG": "C",
}


def run(*args: str, env: dict | None = None,
        cwd: str | Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=60,
        env=HERMETIC_ENV if env is None else env, cwd=None if cwd is None else str(cwd),
    )
    return proc.returncode, proc.stdout, proc.stderr


@contextlib.contextmanager
def fixture():
    """A temporary directory, as a Path."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def doctor(case, root, *extra: str, env: dict | None = None) -> tuple[dict, dict]:
    """One `doctor` run: asserts exit 0, returns (report, {check id: check}).

    Tasks 2-7 read every check through this, so no case re-spells the run, the
    exit assertion or the id index.
    """
    code, out, err = run("run", "--purpose", "doctor", "--repo-root", str(root),
                         *extra, env=env)
    case.assertEqual(code, 0, err)
    report = json.loads(out)
    return report, {c["id"]: c for c in report["checks"]}


def make_root(tmp: Path) -> Path:
    """A temporary project root a clean `doctor` run passes on.

    The committed contract, its instruction source and both projection targets
    are copied byte-for-byte, every directory a knowledge path names is
    created, and the root ignore file covers `.agents/runtime/`, so a fixture
    refuses only for the mutation a case applies to it.
    """
    root = tmp / "project"
    (root / ".agents" / "instructions").mkdir(parents=True)
    for relative in (".agents/project.json", ".agents/instructions/bootstrap.md",
                     "AGENTS.md", "CLAUDE.md"):
        shutil.copy2(REPO_ROOT / relative, root / relative)
    paths = json.loads(
        (root / ".agents/project.json").read_text(encoding="utf-8")
    )["bindings"]["paths"]
    for member in ("context", "standards", "architecture", "operations",
                   "hints", "rejections"):
        for entry in paths[member]:
            target = root / entry
            if not target.exists():  # `architecture` names CLAUDE.md, already copied
                target.mkdir(parents=True)
    (root / ".gitignore").write_text(".agents/runtime/\n", encoding="utf-8")
    return root


def load_module():
    """The engine as an imported module, loaded by path (its name is hyphenated).

    Registered under its spec name before exec_module: the module uses
    postponed annotations, and dataclass construction resolves them through
    sys.modules, so an unregistered module fails to import at all (D36).
    """
    import importlib.util
    from importlib.machinery import SourceFileLoader

    fullname = "conformance_engine"
    spec = importlib.util.spec_from_loader(
        fullname, SourceFileLoader(fullname, str(SCRIPT)))
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(fullname, None)
        raise
    return module


class ReportAssertions:
    """One assertion both report suites share: the engine's own output, judged
    by the very schema every consumer checks a report against."""

    def assert_validates(self, report: dict) -> None:
        with fixture() as tmp:
            path = tmp / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            code, out, _ = run("validate-report", "--input", str(path))
            self.assertEqual(code, 0, out)


class Rebinding:
    """Restore every module attribute a case replaces, so none leaks forward."""

    def rebind(self, owner, name, value):
        original = getattr(owner, name)
        self.addCleanup(setattr, owner, name, original)
        setattr(owner, name, value)
