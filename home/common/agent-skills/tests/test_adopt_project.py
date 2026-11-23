"""Contract tests for `adopt-project` (`agent_tools.project_contract.adopt_project`).

Runs `adopt-project`'s command line under a temporary `HOME` holding a fixture
manifest. The command consumes the resolver only as a child process of its own
interpreter, `agent_tools.project_contract.resolve_project` run through
`agent_tools.system.siblings.sibling_argv` (D26, #177 D5). `run` runs the command in
this process and answers that resolver child in process too (issue 612);
`run_child` runs both as real processes, and `ProcessWiringTest` pins that the
two agree.

Fixture repositories are real `git init` checkouts with a hermetic identity and
`commit.gpgsign=false` in the fixture's own local config; nothing here touches
the developer's git configuration or the machine's `~/.agents`.

Two cases import package modules in process: the generic failure wrapper, which
no subprocess run can drive (D23), and the ambiguous forward step, which the
platform library refuses before the router would see it (#177 D7).
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.project_contract import (adopt_inspection, adopt_links, adopt_planning,
                                          adopt_project)
from agent_tools.system.siblings import sibling_argv

from ._inprocess_cli import run_module
from .test_resolve_project import schema_one

MANIFEST = Path(__file__).resolve().parents[1] / "platform-manifest.json"
REPO_ROOT = Path(__file__).resolve().parents[4]

COMMITTED = object()

ACTIONS = ("move-canonical", "generate-projection", "retain-product", "archive-history",
           "delete-exact-duplicate", "needs-decision", "convert-to-source")
OUTCOMES = ("bootstrap", "reconcile", "no_change", "migration_required",
            "repair_required")
PLAN_STATES = ("draft", "ready", "not_applicable")
OPERATION_KINDS = ("git-mv", "write-file", "delete-file",
                   "regenerate-projection")
PROVENANCES = ("tracked", "targeted-ignored",
               "targeted-ignored-metadata-only", "git-worktree-metadata-only",
               "untracked-explicit-paths")
TOP_LEVEL_MEMBERS = ["changes", "decisions", "evidence", "handoff",
                     "link_rewrites", "path_references", "plan",
                     "reference_formatting", "reference_policies",
                     "schema_version", "verification"]
PLAN_MEMBERS = ["available_migration", "base_revision", "blockers",
                "input_digest", "outcome", "plan_id", "platform",
                "project_id", "state"]
HANDOFF_MEMBERS = ["migration_map", "next_command",
                   "plan_path", "repo_root", "state"]


# --------------------------------------------------------------------------
# Isolation
# --------------------------------------------------------------------------


def install_home(home: Path, manifest: object = COMMITTED) -> Path:
    """Populate `home` with the platform manifest `adopt-project` reads."""
    share = home / ".agents" / "share"
    share.mkdir(parents=True, exist_ok=True)
    target = share / "platform-manifest.json"
    target.unlink(missing_ok=True)
    if manifest is COMMITTED:
        shutil.copy(MANIFEST, target)
    elif manifest is None:
        pass
    elif isinstance(manifest, str):
        target.write_text(manifest, encoding="utf-8")
    else:
        target.write_text(json.dumps(manifest), encoding="utf-8")
    return home


def make_home(manifest: object = COMMITTED) -> Path:
    return install_home(Path(tempfile.mkdtemp()).resolve(), manifest)


def install_registry(home: Path, entries: list[dict]) -> None:
    path = home / ".agents" / "state" / "fleet" / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "projects": entries}),
        encoding="utf-8")


_SUBPROCESS_RUN = subprocess.run


def _resolver_in_process(argv, *args, **kwargs):
    """`subprocess.run`, except that the resolver child `run_resolver` starts runs
    in this process, with the caller's environment and the same captured bytes."""
    prefix = sibling_argv("project_contract.resolve_project")
    if list(argv[:len(prefix)]) != prefix:
        return _SUBPROCESS_RUN(argv, *args, **kwargs)
    done = run_module("agent_tools.project_contract.resolve_project", argv[len(prefix):],
                      env=dict(os.environ), text=False)
    return subprocess.CompletedProcess(list(argv), done.returncode, done.stdout, done.stderr)


def run(*args: str, home: Path) -> tuple[int, str, str]:
    """`adopt-project`'s command line in this process, its resolver child too (issue 612)."""
    with mock.patch.object(adopt_project.subprocess, "run", _resolver_in_process):
        proc = run_module("agent_tools.project_contract.adopt_project", args,
                          env={**os.environ, "HOME": str(home)})
    return proc.returncode, proc.stdout, proc.stderr


def run_child(*args: str, home: Path) -> tuple[int, str, str]:
    """`adopt-project` as a real child process, with its real resolver child."""
    proc = subprocess.run(
        [sys.executable, "-m", "agent_tools.project_contract.adopt_project", *args],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "HOME": str(home)},
    )
    return proc.returncode, proc.stdout, proc.stderr


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, timeout=120, check=True,
        env=dict(
            os.environ,
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
        ),
    )
    return proc.stdout


def tree_snapshot(root: Path) -> list[tuple[str, str, int | None]]:
    """Every path under `root` outside `.git`, with its type and file mtime."""
    out = []
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        kind = "d" if path.is_dir() else "f"
        out.append((
            str(path.relative_to(root)), kind,
            None if kind == "d" else path.stat().st_mtime_ns,
        ))
    return out


def sha256_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# Fixture repositories
# --------------------------------------------------------------------------


# P11: the pinned schema-2 contract, not this repository's own live contract.
SCHEMA_TWO_FIXTURE = (Path(__file__).resolve().parent / "fixtures"
                      / "project-contract-schema-2.json")


def source_contract() -> dict:
    return json.loads(SCHEMA_TWO_FIXTURE.read_text("utf-8"))


# Built fixture repositories, each kept once per process (issue 612, the #500 pattern).
_TEMPLATES: dict[tuple, Path] = {}
_TEMPLATE_ROOT = tempfile.TemporaryDirectory()


def templated(build):
    """`build`, run once per process for each set of arguments; every later call gets
    a copy of that first result at a fresh temporary root (issue 612).

    A `Path` argument, the `home` every builder takes, is not part of the key: what
    a builder writes does not depend on it. Only builders whose tree holds no
    absolute path, git worktree or link out of the checkout may be templated.
    """
    @functools.wraps(build)
    def copy(*args, **kwargs):
        key = (build.__name__, tuple(a for a in args if not isinstance(a, Path)),
               tuple(sorted(kwargs.items())))
        template = _TEMPLATES.get(key)
        if template is None:
            built = build(*args, **kwargs)
            template = Path(_TEMPLATE_ROOT.name) / str(len(_TEMPLATES))
            shutil.copytree(built, template, symlinks=True)
            _TEMPLATES[key] = template
            return built
        root = Path(tempfile.mkdtemp()).resolve()
        shutil.copytree(template, root, symlinks=True, dirs_exist_ok=True)
        return root
    return copy


@templated
def init_repo() -> Path:
    # `.resolve()` because the platform temp dir is reached through a symlink
    # on macOS; the tool always reports the physical path.
    root = Path(tempfile.mkdtemp()).resolve()
    git(root, "init", "--quiet", "-b", "main")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    return root


def commit(root: Path, message: str = "fixture") -> None:
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", message)


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def fixture_contract(**overrides: object) -> dict:
    """A valid contract in the highest supported project schema, derived from the
    pinned schema-2 contract.

    Derived rather than authored so that the fixture cannot drift out of
    validity as the contract's shape evolves; only the members a case is about
    are overridden.
    """
    contract = source_contract()
    contract["project"] = {"id": "fixture/target", "name": "target"}
    contract["bindings"]["paths"]["artifacts"] = {
        "specs": ".agents/artifacts/specs", "plans": ".agents/artifacts/plans"}
    contract["bindings"]["paths"]["rejections"] = [
        ".agents/knowledge/rejections"]
    for key, value in overrides.items():
        contract[key] = value
    return contract


def host_independent(contract: dict) -> dict:
    """`contract`, changed in place so that no capability depends on the host.

    This repository's GitHub release profile derives a `blocked` release
    capability on any host without the forge adapter's executables on `PATH`,
    and the platform's review commands run `codex-companion`, which the
    hosted CI runner lacks. No fixture built on this is about release or
    review, so release is opted out and each review command is replaced by an
    authored `true` entry under its id, which every host resolves: the verdicts
    are the same everywhere.
    """
    contract["release"] = "unsupported"
    review = contract["bindings"]["workflow"]["review"]
    for role in ("plan", "code"):
        if review[role] is None:
            continue  # an unsupported role names no command id
        contract["bindings"]["commands"][review[role]] = {
            "argv": ["true"], "cwd": ".", "env": []}
    return contract


def scaffold(root: Path, contract: dict, home: Path) -> None:
    """Write `contract`, its instruction source and both rendered projections.

    The projections are rendered by the resolver itself rather than by a
    literal copied out of it, so this fixture cannot disagree with the tool
    about what "in sync" means.
    """
    write(root, ".agents/instructions/bootstrap.md", "# invariants\n")
    # Every standards path the contract declares, not a literal copy of one:
    # the contract is this repository's own, so a path it gains exists here too.
    for standards in contract["bindings"]["paths"]["standards"]:
        (root / standards).mkdir(parents=True, exist_ok=True)
    write(root, ".agents/project.json", json.dumps(contract, indent=2) + "\n")
    proc = run_module("agent_tools.project_contract.resolve_project",
                      ("write-projections", "--repo-root", str(root)),
                      env={**os.environ, "HOME": str(home)})
    if proc.returncode != 0:
        raise AssertionError(
            f"fixture projections could not be rendered: {proc.stdout}")


@templated
def bootstrap_repo(home: Path, *, remotes: tuple[str, ...] = ()) -> Path:
    """One unrelated tracked file: no `.agents/`, no `.claude/`."""
    root = init_repo()
    write(root, "README.md", "# unrelated\n")
    for index, url in enumerate(remotes):
        git(root, "remote", "add", "origin" if index == 0 else f"r{index}", url)
    commit(root)
    return root


@templated
def reconcile_repo(home: Path, *,
                   remotes: tuple[str, ...] = (
                       "git@github.com:fixture/reconcile.git",)) -> Path:
    """Legacy artifact trees and no contract at all."""
    root = init_repo()
    write(root, ".out-of-scope/a.md", "# rejected a\n")
    write(root, ".out-of-scope/b.md", "# rejected b\n")
    for index, url in enumerate(remotes):
        git(root, "remote", "add", "origin" if index == 0 else f"r{index}", url)
    commit(root)
    return root


def commit_adoption(root: Path, project_id: str = "fixture/target",
                    digest: str = "a1" * 32) -> str:
    """The commit an adoption makes, as `apply` makes it, and its id.

    Authored here rather than produced by a run, so a fixture that must
    already *be* adopted needs no apply: `verify` finds the adoption by the
    subject of a commit in the history and by nothing in the tree.
    """
    write(root, f".agents/knowledge/archive/path-migrations/{digest}.json",
          json.dumps({"schema_version": 1, "migration_id": f"sha256:{digest}",
                      "moves": []}) + "\n")
    commit(root, adopt_inspection.adoption_subject(project_id, digest))
    return git(root, "rev-parse", "HEAD").strip()


@templated
def adopted_repo(home: Path, *, adoption: bool = True, schema: int = 2) -> Path:
    """A conformant checkout: valid contract, sentinel present, nothing legacy.

    The adoption commit a real apply makes is present by default, on top of
    the fixture commit: without it the checkout carries no commit with the
    adoption subject for `verify` to find, so it cannot legitimately verify
    as adopted. `adoption=False` is the fixture the discovery negatives
    start from.
    """
    root = init_repo()
    contract = host_independent(fixture_contract())
    scaffold(root, contract, home)
    if schema == 1:
        # Platform 2.0.0 refuses a schema-1 contract, so its projections are rendered
        # from the schema-2 form and the authored contract is then put back to schema 1:
        # the checkout a project still at schema 1 holds.
        write(root, ".agents/project.json", json.dumps(schema_one(contract), indent=2) + "\n")
    write(root, ".agents/runtime/.gitignore", "*\n")
    git(root, "add", "-f", ".agents/runtime/.gitignore")
    git(root, "remote", "add", "origin",
        "https://github.com/fixture/target.git")
    commit(root)
    if adoption:
        commit_adoption(root)
    return root


@templated
def nix_config_shape_repo(home: Path) -> Path:
    """This repository's shape at base: a valid schema-1 contract without
    `platform`, legacy `.claude/specs`, `.claude/plans` and `.out-of-scope`
    trees, a `.claude/skills.config.json`, and no runtime sentinel."""
    root = init_repo()
    contract = fixture_contract()
    contract["bindings"]["paths"]["artifacts"] = {
        "specs": ".claude/specs", "plans": ".claude/plans"}
    contract["bindings"]["paths"]["rejections"] = [".out-of-scope"]
    scaffold(root, contract, home)
    # The projections are rendered from a contract that still declares
    # `platform`; dropping the member afterwards leaves them in sync, because
    # a projection is a pure function of the instruction source, its id and the
    # project schema.
    without_platform = json.loads(
        (root / ".agents" / "project.json").read_text("utf-8"))
    del without_platform["platform"]
    write(root, ".agents/project.json",
          json.dumps(without_platform, indent=2) + "\n")
    write(root, ".claude/specs/x.md", "# spec x\n")
    write(root, ".claude/plans/y.md", "# plan y\n")
    write(root, ".out-of-scope/z.md", "# rejected z\n")
    write(root, ".claude/skills.config.json", json.dumps(
        {"orchestration": {"agentBudgetMinutes": 180, "maxParallel": 2}},
        indent=2) + "\n")
    write(root, ".gitignore", GITIGNORE_WITH_COMMENT)
    git(root, "remote", "add", "origin",
        "https://github.com/fixture/target.git")
    commit(root)
    return root


@templated
def record_trees_repo(home: Path) -> Path:
    """`nix_config_shape_repo` plus one tracked record under each of
    `.claude/handoffs`, `.claude/notes` and `.claude/research` (#340)."""
    root = nix_config_shape_repo(home)
    write(root, ".claude/handoffs/h.md", "# handoff h\n")
    write(root, ".claude/notes/n.md", "# note n\n")
    write(root, ".claude/research/r.md", "# research r\n")
    commit(root, "add agent records")
    return root


LINK_README_BEFORE = (
    "# readme\n"
    "\n"
    "See [rejected z](.out-of-scope/z.md#intro) and "
    "[rejections](./.out-of-scope/).\n"
    "Image: ![diagram](<.out-of-scope/z.md> \"Rejected z\") and "
    "[rejected w][w].\n"
    "Broken: [gone](.out-of-scope/missing.md). "
    "Web: [site](https://example.com/.out-of-scope/z.md).\n"
    "Self: [me](README.md). Code: `[c](.out-of-scope/z.md)`.\n"
    "\n"
    "~~~\n"
    "[fenced](.out-of-scope/z.md)\n"
    "~~~\n"
    "\n"
    "[w]: .out-of-scope/w.md \"Rejected w\"\n")
LINK_README_AFTER = (
    "# readme\n"
    "\n"
    "See [rejected z](.agents/knowledge/rejections/z.md#intro) and "
    "[rejections](./.agents/knowledge/rejections/).\n"
    "Image: ![diagram](<.agents/knowledge/rejections/z.md> "
    "\"Rejected z\") and [rejected w][w].\n"
    "Broken: [gone](.out-of-scope/missing.md). "
    "Web: [site](https://example.com/.out-of-scope/z.md).\n"
    "Self: [me](README.md). Code: `[c](.out-of-scope/z.md)`.\n"
    "\n"
    "~~~\n"
    "[fenced](.out-of-scope/z.md)\n"
    "~~~\n"
    "\n"
    "[w]: .agents/knowledge/rejections/w.md \"Rejected w\"\n")

# Base path -> base text, and path after the moves -> rewritten text (#345).
LINKED_BASE = {
    "README.md": LINK_README_BEFORE,
    ".claude/rules/r.md": "# rule r\n\nFollow [rejected z](../../.out-of-scope/z.md).\n",
    ".out-of-scope/z.md": (
        "# rejected z\n\nBack to [readme](../README.md), "
        "[rejected w](w.md) and "
        "[config](../.claude/skills.config.json).\n"),
    ".out-of-scope/w.md": "# rejected w\n",
}
LINKED_AFTER = {
    "README.md": LINK_README_AFTER,
    ".claude/rules/r.md": (
        "# rule r\n\n"
        "Follow [rejected z](../../.agents/knowledge/rejections/z.md).\n"),
    ".agents/knowledge/rejections/z.md": (
        "# rejected z\n\nBack to [readme](../../../README.md), "
        "[rejected w](w.md) and "
        "[config](../../../.claude/skills.config.json).\n"),
}
LINKED_SOURCES = {"README.md": "README.md",
                  ".claude/rules/r.md": ".claude/rules/r.md",
                  ".agents/knowledge/rejections/z.md": ".out-of-scope/z.md"}
LINKED_SUMMARY = {
    "inbound": {"links": 5, "files": [".claude/rules/r.md", "README.md"]},
    "outbound": {"links": 2, "files": [".agents/knowledge/rejections/z.md"]},
    "unrewritable": [],
    "already_broken": 1,
}


def write_linked_tree(root: Path) -> None:
    """Inbound links from a root file and a retained `.claude/` file, and
    outbound links from a moved file, over any fixture carrying
    `.out-of-scope/z.md`."""
    for path, text in LINKED_BASE.items():
        write(root, path, text)
    commit(root, "link the agent trees")


@templated
def linked_repo(home: Path) -> Path:
    root = nix_config_shape_repo(home)
    write_linked_tree(root)
    return root


CHECK_LINKS = "tools/check_links.py"
UNRELATED_SCRIPT = "tools/list_docs.py"
# A repository's own link check (#350): it exempts `.claude/`, where the
# already-broken link of `REFERENCE_TREE` lives. Line 7 holds the one path
# reference; every other token names nothing the plan moves.
CHECK_LINKS_SCRIPT = r'''#!/usr/bin/env python3
# Fail when a Markdown file outside the exempt trees has a broken relative link.
import os
import re
import sys

EXEMPT = ("docs/archive/", ".claude/")
LINK = re.compile(r"\]\(([^)#\s]+)")


def main(root):
    broken = []
    for folder, _, names in sorted(os.walk(root)):
        for name in sorted(names):
            path = os.path.relpath(os.path.join(folder, name), root)
            if not path.endswith(".md") or path.startswith(EXEMPT):
                continue
            with open(os.path.join(root, path), encoding="utf-8") as handle:
                text = handle.read()
            for target in LINK.findall(text):
                if "://" not in target and not os.path.exists(
                        os.path.join(root, os.path.dirname(path), target)):
                    broken.append(f"{path}: {target}")
    print("\n".join(broken) or "ok")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
'''
CHECK_LINKS_EXTENDED = CHECK_LINKS_SCRIPT.replace(
    '".claude/")', '".claude/", ".agents/knowledge/hints/")')
REFERENCE_SUBJECT = f"{CHECK_LINKS}:7:29"
REFERENCE_ROW = {
    "subject": REFERENCE_SUBJECT, "path": CHECK_LINKS, "line": 7,
    "column": 29, "literal": ".claude/", "answers": ["extend", "retain"],
    "answer": None,
    "additions": [".agents/knowledge/hints/"],
    "replacement": None, "target": CHECK_LINKS, "policy": None,
    "decided_by": None}
REFERENCE_TREE = {
    "README.md": "# readme\n\nSee [rejected z](.out-of-scope/z.md).\n",
    ".claude/hints/h.md": "# hint h\n\nGone: [gone](missing.md).\n",
    ".claude/rules/r.md": "# rule r\n",
    UNRELATED_SCRIPT: 'ROOTS = ("docs/standards/", "home/")\nprint(ROOTS)\n',
}


def write_reference_tree(root: Path, *, script: bool = True) -> None:
    """An inbound link, an already-broken link inside a moved hint, retained
    `.claude/` content, an unrelated script and, with `script`, the link
    check, over any fixture carrying `.out-of-scope/z.md`."""
    for path, text in REFERENCE_TREE.items():
        write(root, path, text)
    if script:
        write(root, CHECK_LINKS, CHECK_LINKS_SCRIPT)
    commit(root, "reference the agent trees")


@templated
def referenced_repo(home: Path, *, script: bool = True) -> Path:
    root = nix_config_shape_repo(home)
    write_reference_tree(root, script=script)
    return root


MOVED_TOOL = ".out-of-scope/tool.py"
MOVED_TOOL_NEW = ".agents/knowledge/rejections/tool.py"
MOVED_TOOL_TEXT = 'SPEC = ".out-of-scope/z.md"\n'
MOVED_TOOL_AFTER = 'SPEC = ".agents/knowledge/rejections/z.md"\n'
MOVED_TOOL_SUBJECT = f"{MOVED_TOOL}:1:9"


def write_moved_tool(root: Path) -> None:
    """One script inside a moved tree that names a file of another."""
    write(root, MOVED_TOOL, MOVED_TOOL_TEXT)
    commit(root, "add a script to a moved tree")


POLICY_DIR = ".out-of-scope/study"
POLICY_NEW = ".agents/knowledge/rejections/study"
RUN_REPORT = "tools/run_report.py"
LINT_TOML = "tools/lint.toml"
SETTINGS = ".claude/settings.json"
# The Markdown of the policy fixture: one outbound link the move changes.
POLICY_MARKDOWN = {
    f"{POLICY_DIR}/README.md":
        "# study\n\nIgnored: [ignore](../../.gitignore).\n",
}
# Two scripts, a Nix module and a JSON record inside `.out-of-scope` that each
# name a path under a moved tree; a script outside it that runs one of them by
# path; a TOML list with a regex-form exclude; a tracked native settings file.
POLICY_CODE = {
    f"{POLICY_DIR}/report.py": (
        "import json\n\n"
        f'RECORD = "{POLICY_DIR}/record.json"\n'
        'print(json.load(open(RECORD))["title"])\n'),
    f"{POLICY_DIR}/paths.py": (
        'TREES = ".out-of-scope"\nPLAN = ".out-of-scope/z.md"\n'),
    f"{POLICY_DIR}/devenv.nix": (
        "{ ... }:\n{\n" f'  env.STUDY_HOME = "{POLICY_DIR}";\n' "}\n"),
    f"{POLICY_DIR}/record.json": (
        '{"title": "study", "source": ".out-of-scope/z.md"}\n'),
    RUN_REPORT: (
        "import subprocess\nimport sys\n\nsys.exit(subprocess.run(\n"
        f'    [sys.executable, "{POLICY_DIR}/report.py"]).returncode)\n'),
    LINT_TOML: (
        "[tool.check]\n"
        r'exclude = ["^var/", "^\\.claude/", "^\\.worktrees/"]' "\n"),
    SETTINGS: '{"hooks": {}}\n',
}
# What each edited file holds, at the path it has after the moves, once every
# policy and outside occurrence is answered as in `POLICY_READY_ANSWERS`.
POLICY_REWRITTEN = {
    f"{POLICY_NEW}/report.py":
        POLICY_CODE[f"{POLICY_DIR}/report.py"].replace(POLICY_DIR, POLICY_NEW),
    f"{POLICY_NEW}/paths.py": (
        'TREES = ".agents/knowledge/rejections"\n'
        'PLAN = ".agents/knowledge/rejections/z.md"\n'),
    f"{POLICY_NEW}/devenv.nix":
        POLICY_CODE[f"{POLICY_DIR}/devenv.nix"].replace(POLICY_DIR,
                                                        POLICY_NEW),
    RUN_REPORT: POLICY_CODE[RUN_REPORT].replace(POLICY_DIR, POLICY_NEW),
    LINT_TOML: (
        "[tool.check]\n"
        r'exclude = ["^var/", "^\\.claude/", '
        r'"^\\.agents/knowledge/hints/", "^\\.worktrees/"]' "\n"),
}
JSON_POLICY = ".out-of-scope:.json"
NIX_POLICY = ".out-of-scope:.nix"
PY_POLICY = ".out-of-scope:.py"
RUN_SUBJECT = f"{RUN_REPORT}:5:23"
LINT_SUBJECT = f"{LINT_TOML}:2:22"
POLICY_READY_ANSWERS = (
    ("reference-policy", JSON_POLICY, "retain"),
    ("reference-policy", NIX_POLICY, "rewrite"),
    ("reference-policy", PY_POLICY, "rewrite"),
    ("path-reference", LINT_SUBJECT, "extend"),
    ("path-reference", RUN_SUBJECT, "rewrite"),
)
# `(subject, answers, target, policy)` of every row, in row order.
POLICY_ROWS = [
    (f"{POLICY_DIR}/devenv.nix:3:21", ["rewrite", "retain"],
     f"{POLICY_NEW}/devenv.nix", NIX_POLICY),
    (f"{POLICY_DIR}/paths.py:1:10", ["rewrite", "retain"],
     f"{POLICY_NEW}/paths.py", PY_POLICY),
    (f"{POLICY_DIR}/paths.py:2:9", ["rewrite", "retain"],
     f"{POLICY_NEW}/paths.py", PY_POLICY),
    (f"{POLICY_DIR}/record.json:1:31", ["rewrite", "retain"],
     f"{POLICY_NEW}/record.json", JSON_POLICY),
    (f"{POLICY_DIR}/report.py:3:11", ["rewrite", "retain"],
     f"{POLICY_NEW}/report.py", PY_POLICY),
    (LINT_SUBJECT, ["extend", "retain"], LINT_TOML, None),
    (RUN_SUBJECT, ["extend", "rewrite", "retain"], RUN_REPORT, None),
]
MAKEFILE = ".out-of-scope/Makefile"
MAKEFILE_NEW = ".agents/knowledge/rejections/Makefile"
MAKEFILE_TEXT = 'SKIP = (".claude",)\nSPEC = ".out-of-scope/z.md"\n'
MAKEFILE_AFTER = (
    'SKIP = (".claude", ".agents/knowledge/hints",)\n'
    'SPEC = ".agents/knowledge/rejections/z.md"\n')


POLICY_HINT = ".claude/hints/h.md"


def write_policy_tree(root: Path, *, code: bool = True) -> None:
    """The policy fixture's files, over any fixture carrying `.out-of-scope/z.md`
    and a tracked `.gitignore`; without `code`, only its Markdown."""
    for path, text in {**POLICY_MARKDOWN,
                       **(POLICY_CODE if code else {})}.items():
        write(root, path, text)
    if code:
        # The tracked hint makes `.claude/` a retained ancestor of a moved tree.
        write(root, POLICY_HINT, "# hint h\n")
    commit(root, "add a moved tree that holds working code")


@templated
def policy_repo(home: Path, *, code: bool = True) -> Path:
    root = nix_config_shape_repo(home)
    write_policy_tree(root, code=code)
    return root


JOBS_DIR = ".out-of-scope/jobs"
JOBS_NEW = ".agents/knowledge/rejections/jobs"
JOBS_SCRIPT = f"{JOBS_DIR}/run.sh"
COLLECT = "tools/collect"
SH_POLICY = ".out-of-scope:.sh"
SH_VARIABLE_POLICY = ".out-of-scope:.sh/variable"
JOBS_LITERAL = f"{JOBS_SCRIPT}:3:6"
JOBS_VARIABLE = f"{JOBS_SCRIPT}:4:6"
COLLECT_SUBJECT = f"{COLLECT}.sh:2:6"
VARIABLE_REWRITE_ANSWERS = (
    ("path-reference", COLLECT_SUBJECT, "rewrite"),
    ("reference-policy", SH_POLICY, "rewrite"),
    ("reference-policy", SH_VARIABLE_POLICY, "rewrite"),
)
VARIABLE_RETAIN_ANSWERS = tuple(
    (question, subject, "retain")
    for question, subject, _ in VARIABLE_REWRITE_ANSWERS)


def variable_code(suffix: str = ".sh") -> dict[str, str]:
    """#376: a moved script with one literal and one `$root/`-joined path
    into its own tree, the file both name, and an unmoved script with one
    `${ROOT}/`-joined path into it; `suffix` is both scripts' class."""
    return {
        f"{JOBS_DIR}/run{suffix}": (
            "#!/bin/sh\n"
            'root="$1"\n'
            f'cat "{JOBS_DIR}/data.txt"\n'
            f'cat "$root/{JOBS_DIR}/data.txt"\n'),
        f"{JOBS_DIR}/data.txt": "jobs\n",
        f"{COLLECT}{suffix}": (
            "#!/bin/sh\n"
            f'cat "${{ROOT}}/{JOBS_DIR}/data.txt"\n'),
    }


def write_variable_tree(root: Path, suffix: str = ".sh") -> None:
    for path, text in variable_code(suffix).items():
        write(root, path, text)
    commit(root, "add shell scripts that join paths to a variable")


def answer_args(*triples: tuple[str, str, str]) -> list[str]:
    return [token for triple in triples for token in ("--answer", *triple)]


def policy_row(subject: str, recommended: str | None, files: int,
               occurrences: int, **changed: object) -> dict:
    tree, _, file_class = subject.partition(":")
    return {"subject": subject, "tree": tree, "class": file_class,
            "recommended": recommended, "answer": None, "files": files,
            "occurrences": occurrences, "rewritable": occurrences,
            "rewritten": 0, "retained": 0, "extended": 0,
            "open": occurrences, "overridden": 0, **changed}


# #380: an `.out-of-scope` tree two levels shallower than its destination,
# whose tooling climbs to the repository root (D1-D3, D6).
DEPTH_DIR = ".out-of-scope/tool"
DEPTH_NEW = ".agents/knowledge/rejections/tool"
DEPTH_CODE = {
    f"{DEPTH_DIR}/run.py": (
        "from pathlib import Path\n"
        "\n"
        "HERE = Path(__file__).resolve().parent\n"
        "ROOT = HERE.parents[1]\n"
        "NOTES = HERE.parent\n"
        'DATA = "../data/x"\n'),
    f"{DEPTH_DIR}/pyproject.toml": (
        "[tool.uv.sources]\n"
        'lib = { path = "../../vendor/lib" }\n'),
    f"{DEPTH_DIR}/uv.lock": (
        "[[package]]\n"
        'name = "lib"\n'
        'source = { editable = "../../vendor/lib" }\n'),
    "vendor/lib/__init__.py": "",
}
DEPTH_POLICIES = (".out-of-scope:.lock/depth", ".out-of-scope:.py/depth",
                  ".out-of-scope:.toml/depth")
DEPTH_ROWS = (
    (f"{DEPTH_DIR}/pyproject.toml:2:17", "../../vendor/lib",
     "../../../../vendor/lib", ".out-of-scope:.toml/depth"),
    (f"{DEPTH_DIR}/run.py:4:12", ".parents[1]", ".parents[3]",
     ".out-of-scope:.py/depth"),
    (f"{DEPTH_DIR}/uv.lock:3:24", "../../vendor/lib",
     "../../../../vendor/lib", ".out-of-scope:.lock/depth"))
DEPTH_REWRITE_ANSWERS = tuple(("reference-policy", subject, "rewrite")
                              for subject in DEPTH_POLICIES)
DEPTH_RETAIN_ANSWERS = tuple(("reference-policy", subject, "retain")
                             for subject in DEPTH_POLICIES)


def write_depth_tree(root: Path) -> None:
    for path, text in DEPTH_CODE.items():
        write(root, path, text)
    commit(root, "add tooling that climbs to the repository root")


@templated
def candidate_repo(home: Path, *paths: str) -> Path:
    """`nix_config_shape_repo` plus tracked agent paths no row classifies."""
    root = nix_config_shape_repo(home)
    for path in paths:
        write(root, path, f"# {path}\n")
    commit(root, "add unclassified agent paths")
    return root


def ignored_symlink_repo(home: Path) -> Path:
    """`nix_config_shape_repo` plus an ignored `.claude/settings.local.json`
    that is a symlink out of the checkout: the one way an ignored candidate
    stays `needs-decision`."""
    root = nix_config_shape_repo(home)
    outside = Path(tempfile.mkdtemp()).resolve() / "settings.json"
    outside.write_text("{}\n", encoding="utf-8")
    with (root / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write(".claude/settings.local.json\n")
    (root / ".claude" / "settings.local.json").symlink_to(outside)
    commit(root, "ignore an escaping local settings link")
    return root


def tracked_symlink_repo(home: Path) -> Path:
    """`nix_config_shape_repo` plus a tracked `.claude/link.md` that is a
    symlink out of the checkout: an unclassified candidate `apply` could
    never move, because its stored operation would name an uncontained
    path."""
    root = nix_config_shape_repo(home)
    outside = Path(tempfile.mkdtemp()).resolve() / "elsewhere.md"
    outside.write_text("# outside the repository\n", encoding="utf-8")
    (root / ".claude" / "link.md").symlink_to(outside)
    commit(root, "track an escaping agent link")
    return root


LINK = ".claude/link.md"


ODD = ".claude/odd.md"
ARCHIVED = ".agents/knowledge/archive/adopted/.claude/odd.md"


GITIGNORE_WITH_COMMENT = (
    "result\n"
    "__pycache__/\n"
    "\n"
    "# The lazily created runtime bucket of the .agents/ taxonomy.\n"
    "# It is never tracked.\n"
    ".agents/runtime/\n"
)


class AdoptTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = make_home()

    def plan(self, root: Path, *extra: str,
             home: Path | None = None) -> tuple[int, object, str]:
        code, out, err = run("plan", "--repo-root", str(root), *extra,
                             home=home or self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def ready_plan(self, root: Path) -> object:
        code, doc, err = self.plan(root)
        self.assertEqual(code, 0, err)
        return doc

    def assert_read_only(self, root: Path, expected_code: int,
                         *args: str) -> None:
        """Three independent witnesses that `args` wrote nothing under `root`.

        `git status --porcelain` catches a tracked-content or index change, the
        recursive path/type set catches a created directory, and the mtimes
        catch a rewrite with identical bytes (D21).
        """
        before_status = git(root, "status", "--porcelain")
        before_tree = tree_snapshot(root)
        code, _, err = run(*args, home=self.home)
        self.assertEqual(code, expected_code, err)
        self.assertEqual(git(root, "status", "--porcelain"), before_status)
        self.assertEqual(tree_snapshot(root), before_tree)


# --------------------------------------------------------------------------
# Outcome routing — one case per ordered rule
# --------------------------------------------------------------------------


def manifest_with(versions: list[int], migrations: list[dict],
                  platform_version: str = "1.0.0") -> dict:
    return {
        "schema_version": 1,
        "platform_version": platform_version,
        "project_schema_versions": versions,
        "resolved_schema_version": 1,
        "migrations": migrations,
        "deprecations": [],
        "removals": [],
    }


def offering_manifest() -> dict:
    """Schema 3 is readable and a 2->3 step exists, as the platform will ship it.

    The committed version keeps the pinned contract's interval satisfied, so a
    repository adopted against it resolves.
    """
    return manifest_with(
        [2, 3],
        [{"id": "bindings-deploy.retire", "from_schema": 1, "to_schema": 2},
         {"id": "platform-constants.retire", "from_schema": 2,
          "to_schema": 3}],
        platform_version=json.loads(MANIFEST.read_text())["platform_version"])


class OutcomeRoutingTest(AdoptTestCase):
    def offered_home_and_root(self, **kwargs) -> tuple[Path, Path]:
        home = make_home(offering_manifest())
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        root = adopted_repo(home, **kwargs)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return home, root

    def test_a_schema_two_plan_keeps_its_outcome_and_names_the_offered_step(self):
        home, root = self.offered_home_and_root()
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["outcome"], "no_change")
        self.assertEqual(doc["plan"]["available_migration"],
                         "platform-constants.retire")
        self.assertIn("verify --register", doc["handoff"]["next_command"])

    def test_a_schema_one_plan_names_no_offered_step(self):
        home, root = self.offered_home_and_root(schema=1)
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["outcome"], "migration_required")
        self.assertIsNone(doc["plan"]["available_migration"])
        self.assertIn("bindings-deploy.retire", doc["handoff"]["next_command"])

    def test_the_human_view_names_the_offered_step(self):
        home, root = self.offered_home_and_root()
        code, out, err = run("plan", "--repo-root", str(root),
                             "--format", "human", home=home)
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        index = lines.index("available: migrate platform-constants.retire")
        self.assertTrue(lines[index + 1].startswith("next: "), lines)

    def test_a_drifted_schema_two_checkout_reconciles_and_names_the_offered_step(self):
        home, root = self.offered_home_and_root()
        write(root, "AGENTS.md", (root / "AGENTS.md").read_text() + "hand-edited\n")
        commit(root, "drift a projection")
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["outcome"], "reconcile")
        self.assertEqual(doc["plan"]["available_migration"],
                         "platform-constants.retire")

    def test_an_invalid_schema_two_contract_needs_repair_and_names_the_offered_step(self):
        home, root = self.offered_home_and_root()
        contract = json.loads(
            (root / ".agents" / "project.json").read_text("utf-8"))
        del contract["project"]["name"]
        write(root, ".agents/project.json",
              json.dumps(contract, indent=2) + "\n")
        commit(root, "break the contract")
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["outcome"], "repair_required")
        self.assertEqual(doc["plan"]["available_migration"],
                         "platform-constants.retire")

    def test_rule_1_no_contract_and_no_agent_surface_is_bootstrap(self):
        doc = self.ready_plan(bootstrap_repo(self.home))
        self.assertEqual(doc["plan"]["outcome"], "bootstrap")

    def test_rule_2_no_contract_with_legacy_surface_is_reconcile(self):
        doc = self.ready_plan(reconcile_repo(self.home))
        self.assertEqual(doc["plan"]["outcome"], "reconcile")

    def test_the_committed_manifest_routes_schema_one_forward_and_schema_two_to_no_change_offering_schema_three(self):
        # P3: platform 1.2.0 makes schema 2 the highest supported schema.
        root = adopted_repo(self.home, schema=1)
        code, doc, err = self.plan(root, home=self.home)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["outcome"], "migration_required")
        self.assertIn("bindings-deploy.retire", doc["handoff"]["next_command"])
        doc = self.ready_plan(adopted_repo(self.home))
        self.assertEqual(doc["plan"]["outcome"], "no_change")
        self.assertEqual(doc["plan"]["available_migration"], "platform-constants.retire")

    # P3: the schema-1 project below is the one a synthetic manifest routes forward.
    def test_rule_3_supported_but_not_highest_schema_is_migration_required(self):
        home = make_home(manifest_with(
            [1, 2], [{"id": "project-1-to-2", "from_schema": 1,
                      "to_schema": 2}]))
        root = adopted_repo(home, schema=1)
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["outcome"], "migration_required")
        self.assertEqual(doc["plan"]["state"], "not_applicable")
        self.assertEqual(doc["changes"], [])
        self.assertIn("project-1-to-2", doc["handoff"]["next_command"])

    def test_rule_4_unsupported_schema_with_forward_step_migrates(self):
        home = make_home(manifest_with(
            [2], [{"id": "project-1-to-2", "from_schema": 1, "to_schema": 2}]))
        root = adopted_repo(self.home, schema=1)
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["outcome"], "migration_required")
        self.assertIn("project-1-to-2", doc["handoff"]["next_command"])

    def test_rule_4_unsupported_schema_without_forward_step_needs_repair(self):
        home = make_home(manifest_with([2], []))
        root = adopted_repo(self.home, schema=1)
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["outcome"], "repair_required")
        self.assertEqual(doc["plan"]["state"], "not_applicable")
        self.assertEqual(doc["changes"], [])

    def test_rule_5_nix_config_shape_is_reconcile(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertEqual(doc["plan"]["outcome"], "reconcile")

    def test_rule_6_conformant_checkout_is_no_change(self):
        doc = self.ready_plan(adopted_repo(self.home))
        self.assertEqual(doc["plan"]["outcome"], "no_change")
        self.assertEqual(doc["plan"]["state"], "not_applicable")
        self.assertEqual(doc["changes"], [])
        self.assertIn("verify --register", doc["handoff"]["next_command"])

    def test_a_drifted_projection_is_reconcilable_rather_than_a_blocker(self):
        root = adopted_repo(self.home)
        write(root, "AGENTS.md", (root / "AGENTS.md").read_text() + "hand-edited\n")
        commit(root, "drift a projection")
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["outcome"], "reconcile")
        self.assertEqual(doc["plan"]["available_migration"], "platform-constants.retire")
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"]["blockers"])
        self.assertEqual(
            [op["targets"][0] for op in doc["changes"]
             if op["op"] == "regenerate-projection"],
            ["AGENTS.md", "CLAUDE.md"])

    def test_rule_7_current_schema_invalid_with_nothing_to_reconcile(self):
        root = adopted_repo(self.home)
        contract = json.loads(
            (root / ".agents" / "project.json").read_text("utf-8"))
        del contract["project"]["name"]
        write(root, ".agents/project.json", json.dumps(contract, indent=2) + "\n")
        commit(root, "break the contract")
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["outcome"], "repair_required")
        self.assertEqual(doc["plan"]["available_migration"], "platform-constants.retire")
        self.assertEqual(doc["plan"]["state"], "not_applicable")
        self.assertEqual(doc["changes"], [])
        self.assertIn("contract.", doc["handoff"]["next_command"])


class AdoptionSchemaTest(unittest.TestCase):
    def committed(self) -> dict:
        return json.loads(MANIFEST.read_text())

    def test_the_adoption_schema_is_the_highest_schema_a_required_migration_reaches(self):
        def step(name, source, target):
            return {"id": name, "from_schema": source, "to_schema": target}

        rows = (
            ([2, 3], [step("a", 1, 2)], 2),
            # 2->3 starts from a schema the platform still reads: offered.
            ([2, 3], [step("a", 1, 2), step("b", 2, 3)], 2),
            ([2], [], 2),
            ([1, 2], [], 2),
            # No required migration, so the old rule applies.
            ([1, 2], [step("a", 1, 2)], 2),
            ([1, 2, 3], [step("a", 1, 2)], 2),
            ([2, 3, 4], [step("a", 1, 2), step("b", 2, 3),
                         step("c", 3, 4)], 2),
            # 2->3 is required because schema 2 is unsupported.
            ([3, 4], [step("a", 1, 2), step("b", 2, 3), step("c", 3, 4)], 3),
        )
        for versions, migrations, expected in rows:
            with self.subTest(versions=versions, migrations=migrations):
                manifest = manifest_with(versions, migrations)
                self.assertEqual(adopt_planning.current_schema(manifest),
                                 expected)

    def test_a_resolvable_schema_two_contract_routes_no_change_under_the_committed_manifest(self):
        self.assertEqual(
            adopt_planning.route_outcome(
                self.committed(), {"schema_version": 2}, True, True, False),
            ("no_change", None))

    def test_the_offered_step_is_named_only_for_the_schema_adoption_writes(self):
        manifest = offering_manifest()
        for source, expected in (
                ({"schema_version": 2}, "platform-constants.retire"),
                ({"schema_version": 1}, None),
                ({"schema_version": 3}, None),
                ({"schema_version": True}, None),
                ({"schema_version": 2.0}, None),
                (None, None)):
            with self.subTest(source=source):
                self.assertEqual(
                    adopt_planning.offered_migration(manifest, source),
                    expected)
        unsupported_target = manifest_with(
            [2], [{"id": "x", "from_schema": 2, "to_schema": 3}])
        self.assertIsNone(adopt_planning.offered_migration(
            unsupported_target, {"schema_version": 2}))

    def test_a_schema_two_contract_routes_no_change_while_schema_three_is_offered(self):
        self.assertEqual(
            adopt_planning.route_outcome(
                offering_manifest(), {"schema_version": 2}, True, True, False),
            ("no_change", None))

    def test_a_schema_three_contract_is_refused_while_adoption_writes_schema_two(self):
        for manifest in (self.committed(), offering_manifest()):
            with self.subTest(version=manifest["platform_version"]):
                with self.assertRaises(adopt_planning.AdoptError) as caught:
                    adopt_planning.route_outcome(
                        manifest, {"schema_version": 3}, True, True, False)
                self.assertEqual(caught.exception.repair_id,
                                 "adopt.manifest.forward_step_missing")


class ForwardStepRefusalTest(AdoptTestCase):
    def test_absent_forward_step_is_adopt_failure(self):
        home = make_home(manifest_with([1, 2], []))
        root = adopted_repo(self.home, schema=1)
        code, doc, err = self.plan(root, home=home)
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["code"], "adopt_failure")
        self.assertEqual(doc["error"]["repair_id"],
                         "adopt.manifest.forward_step_missing")
        self.assertTrue(doc["error"]["violations"])

    def test_ambiguous_forward_step_is_adopt_failure(self):
        # The platform library refuses two records for one `from_schema`, so
        # the router's own refusal is reached at the module seam (#177 D7).
        manifest = manifest_with([1, 2], [
            {"id": "a", "from_schema": 1, "to_schema": 2},
            {"id": "b", "from_schema": 1, "to_schema": 2},
        ])
        with self.assertRaises(adopt_planning.AdoptError) as caught:
            adopt_planning.select_forward_step(manifest, 1)
        self.assertEqual(caught.exception.code, "adopt_failure")
        self.assertEqual(caught.exception.repair_id,
                         "adopt.manifest.forward_step_ambiguous")


# --------------------------------------------------------------------------
# Project identity (D35)
# --------------------------------------------------------------------------


class ProjectIdentityTest(AdoptTestCase):
    def assert_recommended(self, root: Path, expected: str) -> object:
        doc = self.ready_plan(root)
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(len(doc["decisions"]["recommended"]), 1)
        entry = doc["decisions"]["recommended"][0]
        self.assertEqual(sorted(entry), ["basis", "id", "value"])
        self.assertEqual(entry["id"], "project-id")
        self.assertEqual(entry["value"], expected)
        self.assertEqual(doc["plan"]["project_id"], expected)
        return doc

    def test_single_ssh_remote_is_normalized(self):
        root = reconcile_repo(
            self.home, remotes=("git@github.com:fixture/reconcile.git",))
        self.assert_recommended(root, "fixture/reconcile")

    def test_single_https_remote_is_normalized(self):
        root = reconcile_repo(
            self.home, remotes=("https://github.com/fixture/reconcile.git",))
        self.assert_recommended(root, "fixture/reconcile")

    def test_recommendation_is_byte_identical_across_runs(self):
        root = reconcile_repo(self.home)
        first = run("plan", "--repo-root", str(root), home=self.home)
        # A child, so the two runs differ in hash seed as well (issue 612).
        second = run_child("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(first[0], 0, first[2])
        self.assertEqual(first[1], second[1])

    def assert_open_question(self, root: Path) -> object:
        doc = self.ready_plan(root)
        self.assertEqual(len(doc["decisions"]["open"]), 1)
        entry = doc["decisions"]["open"][0]
        self.assertEqual(
            sorted(entry),
            ["basis", "id", "impact", "recommendation", "value"])
        self.assertEqual(entry["id"], "project-id")
        self.assertEqual(doc["plan"]["state"], "draft")
        return doc

    def test_zero_remotes_opens_the_question(self):
        self.assert_open_question(reconcile_repo(self.home, remotes=()))

    def test_two_remotes_open_the_question(self):
        self.assert_open_question(reconcile_repo(self.home, remotes=(
            "git@github.com:fixture/one.git", "git@github.com:fixture/two.git")))

    def test_unnormalizable_remote_opens_the_question(self):
        self.assert_open_question(
            reconcile_repo(self.home, remotes=("weird-remote",)))

    def test_fleet_collision_at_another_root_opens_the_question(self):
        root = reconcile_repo(self.home)
        install_registry(self.home, [
            {"project_id": "fixture/reconcile", "root": "/elsewhere/checkout"}])
        self.assert_open_question(root)

    def test_fleet_entry_at_the_same_root_does_not_open_the_question(self):
        root = reconcile_repo(self.home)
        install_registry(self.home, [
            {"project_id": "fixture/reconcile", "root": str(root)}])
        self.assert_recommended(root, "fixture/reconcile")

    def test_a_valid_contract_supplies_the_id_without_a_question(self):
        doc = self.ready_plan(adopted_repo(self.home))
        self.assertEqual(doc["plan"]["project_id"], "fixture/target")
        self.assertEqual(doc["decisions"]["recommended"], [])
        self.assertEqual(doc["decisions"]["open"], [])


# --------------------------------------------------------------------------
# Document shape
# --------------------------------------------------------------------------


class DocumentShapeTest(AdoptTestCase):
    def test_exactly_eleven_top_level_members(self):
        for name, build in (("bootstrap", bootstrap_repo),
                            ("reconcile", reconcile_repo),
                            ("adopted", adopted_repo),
                            ("nix-config", nix_config_shape_repo)):
            with self.subTest(fixture=name):
                doc = self.ready_plan(build(self.home))
                self.assertEqual(sorted(doc), TOP_LEVEL_MEMBERS)
                self.assertEqual(sorted(doc["link_rewrites"]),
                                 ["already_broken", "inbound", "outbound",
                                  "unrewritable"])
                self.assertEqual(doc["schema_version"], 1)
                self.assertEqual(sorted(doc["plan"]), PLAN_MEMBERS)
                self.assertEqual(sorted(doc["handoff"]), HANDOFF_MEMBERS)
                self.assertEqual(sorted(doc["decisions"]),
                                 ["answered", "open", "recommended"])
                self.assertEqual(doc["decisions"]["answered"], [])
                self.assertEqual(sorted(doc["verification"]),
                                 ["commit_gates", "ready_gates"])
                self.assertIn(doc["plan"]["state"], PLAN_STATES)
                self.assertIn(doc["plan"]["outcome"], OUTCOMES)

    def test_every_evidence_entry_carries_exactly_one_action(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertTrue(doc["evidence"])
        for entry in doc["evidence"]:
            with self.subTest(path=entry["path"]):
                self.assertEqual(
                    sorted(entry),
                    ["action", "count", "fingerprint", "lifecycle_class",
                     "note", "path", "provenance", "target"])
                self.assertIn(entry["action"], ACTIONS)
                self.assertIn(entry["provenance"], PROVENANCES)
        paths = [entry["path"] for entry in doc["evidence"]]
        self.assertEqual(paths, sorted(paths))

    def test_every_operation_carries_the_typed_shape(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertTrue(doc["changes"])
        for op in doc["changes"]:
            with self.subTest(op=op["op"]):
                self.assertEqual(
                    sorted(op),
                    ["after", "approval_class", "before", "op", "sources",
                     "targets"])
                self.assertIn(op["op"], OPERATION_KINDS)
                self.assertEqual(
                    op["approval_class"],
                    "destructive" if op["op"] == "delete-file" else "normal")

    def test_commit_gates_are_all_not_run_at_plan_time(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertTrue(doc["verification"]["commit_gates"])
        for gate in doc["verification"]["commit_gates"]:
            with self.subTest(gate=gate["id"]):
                self.assertEqual(sorted(gate), ["id", "repair_id", "status"])
                self.assertEqual(gate["status"], "not_run")
                self.assertIsNone(gate["repair_id"])

    def test_a_ready_plan_has_no_needs_decision_and_no_open_question(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertEqual(doc["plan"]["state"], "ready", doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(doc["plan"]["blockers"], [])
        for entry in doc["evidence"]:
            self.assertNotEqual(entry["action"], "needs-decision")
        for gate in doc["verification"]["ready_gates"]:
            self.assertEqual(gate["status"], "passed", gate["id"])

    def test_the_checkout_path_appears_only_in_handoff(self):
        root = nix_config_shape_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc["handoff"]["repo_root"], str(root))
        for member in ("plan", "evidence", "changes", "decisions",
                       "verification"):
            self.assertNotIn(
                str(root),
                json.dumps(doc[member], sort_keys=True), member)

    def test_stdout_is_compact_sorted_json_with_a_trailing_newline(self):
        code, out, err = run("plan", "--repo-root",
                             str(reconcile_repo(self.home)), home=self.home)
        self.assertEqual(code, 0, err)
        self.assertTrue(out.endswith("\n"))
        self.assertNotIn("\n", out[:-1])
        self.assertEqual(out, json.dumps(
            json.loads(out), sort_keys=True, separators=(",", ":")) + "\n")


# --------------------------------------------------------------------------
# `plan_id`
# --------------------------------------------------------------------------


def documented_plan_id(doc: object) -> str:
    """D15's digest, recomputed here from the document's own inputs.

    The formula is the spec's, not the implementation's: the ten named
    members, canonical JSON, SHA-256. Nothing is pasted from a previous
    run.
    """
    source = {
        "adopt_schema_version": doc["schema_version"],
        "project_id": doc["plan"]["project_id"],
        "base_revision": doc["plan"]["base_revision"],
        "platform": doc["plan"]["platform"],
        "evidence": doc["evidence"],
        "decisions_answered": doc["decisions"]["answered"],
        "link_rewrites": doc["link_rewrites"],
        "path_references": doc["path_references"],
        "reference_policies": doc["reference_policies"],
        "reference_formatting": doc["reference_formatting"],
    }
    if "contract_draft" in doc["plan"]:
        source["contract_draft"] = doc["plan"]["contract_draft"]
    source.update({key: doc["plan"][key] for key in ("commit_environment", "conformance")
                   if key in doc["plan"]})
    payload = json.dumps(source, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class PlanIdentityTest(AdoptTestCase):
    def test_plan_id_is_the_documented_digest_and_equals_input_digest(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))
        self.assertEqual(doc["plan"]["input_digest"], doc["plan"]["plan_id"])

    def test_platform_block_is_the_three_reproducible_manifest_values(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        manifest = json.loads(MANIFEST.read_text("utf-8"))
        self.assertEqual(
            doc["plan"]["platform"],
            {name: manifest[name] for name in (
                "platform_version", "project_schema_versions",
                "resolved_schema_version")})

    def test_two_runs_on_an_unchanged_fixture_are_byte_identical(self):
        root = nix_config_shape_repo(self.home)
        first = run("plan", "--repo-root", str(root), home=self.home)
        # A child, so the two runs differ in hash seed as well (issue 612).
        second = run_child("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(first[0], 0, first[2])
        self.assertEqual(first[1], second[1])

    def test_a_second_checkout_yields_the_same_id_at_a_different_root(self):
        """D15: the id is a property of the repository, not of the machine.

        The copy is planned under a user scope of its own, because a stored
        plan stays bound to the one checkout it was derived from and the
        second checkout's plan is refused rather than allowed to re-point it
        (`test_adopt_project_boundaries.PlanClaimTest`). The two ids are equal
        all the same, which is the property D15 is about.
        """
        root = nix_config_shape_repo(self.home)
        other = Path(tempfile.mkdtemp()).resolve() / "copy"
        shutil.copytree(root, other)
        first = self.ready_plan(root)
        code, second, err = self.plan(other, home=make_home())
        self.assertEqual(code, 0, err)
        self.assertEqual(first["plan"]["plan_id"], second["plan"]["plan_id"])
        self.assertNotEqual(first["handoff"]["repo_root"],
                            second["handoff"]["repo_root"])

    def test_one_changed_tracked_byte_yields_a_different_id(self):
        root = nix_config_shape_repo(self.home)
        before = self.ready_plan(root)["plan"]["plan_id"]
        write(root, ".claude/specs/x.md", "# spec X\n")
        commit(root, "edit one byte")
        self.assertNotEqual(before, self.ready_plan(root)["plan"]["plan_id"])

    def test_a_different_platform_version_yields_a_different_id(self):
        root = nix_config_shape_repo(self.home)
        before = self.ready_plan(root)["plan"]["plan_id"]
        major, minor, _ = json.loads(MANIFEST.read_text("utf-8"))[
            "platform_version"].split(".")
        other = make_home(manifest_with(
            [1], [], platform_version=f"{major}.{int(minor) + 1}.0"))
        code, doc, err = self.plan(root, home=other)
        self.assertEqual(code, 0, err)
        self.assertNotEqual(before, doc["plan"]["plan_id"])

    def test_the_document_is_stored_under_user_scope_state(self):
        root = nix_config_shape_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        stored = (self.home / ".agents" / "state" / "adopt" / "plans"
                  / (doc["plan"]["plan_id"].split(":", 1)[1] + ".json"))
        self.assertTrue(stored.is_file(), stored)
        self.assertEqual(json.loads(stored.read_text("utf-8")), doc)
        self.assertEqual(doc["handoff"]["plan_path"], str(stored))

    def test_human_format_prints_a_view_and_stores_the_same_document(self):
        root = nix_config_shape_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        stored = (self.home / ".agents" / "state" / "adopt" / "plans"
                  / (doc["plan"]["plan_id"].split(":", 1)[1] + ".json"))
        before = stored.read_bytes()
        stored.unlink()
        code, human, err = run("plan", "--repo-root", str(root),
                               "--format", "human", home=self.home)
        self.assertEqual(code, 0, err)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(human)
        self.assertIn(doc["plan"]["outcome"], human)
        self.assertEqual(stored.read_bytes(), before)


# --------------------------------------------------------------------------
# Inspection boundary
# --------------------------------------------------------------------------


def drafted_contract() -> dict:
    """A contract that is valid and self-contained for a README-only checkout.

    Every commit gate of `apply` passes on any host: the commands run `true`,
    no standards path is declared, the architecture is the tracked README, the
    tracker is opted out (`cli: gh` derives a missing-cli state on a host
    without it) and the commit is not signed (the sandbox has no key).
    """
    draft = host_independent(fixture_contract())
    draft["projections"] = []
    del draft["platform"]
    for command in draft["bindings"]["commands"].values():
        command["argv"] = ["true"]
    draft["bindings"]["paths"]["standards"] = []
    draft["capabilities"]["knowledge.standards"] = {"support": "unsupported"}
    draft["bindings"]["paths"]["architecture"] = ["README.md"]
    draft["capabilities"]["tracker"] = {"support": "unsupported"}
    draft["bindings"]["vcs"]["commit"]["signed"] = False
    return draft


class ContractDraftTest(AdoptTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.draft = drafted_contract()
        self.version = json.loads(MANIFEST.read_text())["platform_version"]
        self.scratch = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def draft_file(self, draft: object = None, name: str = "draft.json") -> str:
        path = self.scratch / name
        path.write_text(json.dumps(self.draft if draft is None else draft),
                        encoding="utf-8")
        return str(path)

    def stored_plans(self) -> list[str]:
        directory = self.home / ".agents/state/adopt/plans"
        return sorted(path.name for path in directory.glob("*")) \
            if directory.exists() else []

    def written(self) -> bytes:
        # The plan keeps the draft in canonical (sorted) key order, the only
        # order its stored form has, and appends the interval it adds.
        return adopt_inspection.authored_bytes(
            {**json.loads(json.dumps(self.draft, sort_keys=True)),
             "platform": adopt_planning.derived_interval(self.version)})

    def test_a_draft_plans_the_contract_write_and_reaches_ready(self):
        root = bootstrap_repo(self.home)
        path = self.draft_file()
        self.assert_read_only(root, 0, "plan", "--repo-root", str(root),
                              "--contract-draft", path, "--format", "json")
        code, doc, err = self.plan(root, "--contract-draft", path)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["state"], "ready")
        self.assertEqual(doc["plan"]["outcome"], "bootstrap")
        self.assertEqual(doc["plan"]["blockers"], [])
        self.assertEqual(doc["plan"]["contract_draft"], self.draft)
        self.assertEqual(doc["plan"]["project_id"], "fixture/target")
        self.assertEqual(doc["changes"][0], {
            "op": "write-file", "sources": [".agents/project.json"],
            "targets": [".agents/project.json"], "before": None,
            "after": sha256_hash(self.written()),
            "approval_class": adopt_inspection.approval_class_for(
                "write-file")})
        self.assertEqual(doc["decisions"]["open"], [])

    def test_a_draft_plan_names_no_offered_step(self):
        install_home(self.home, offering_manifest())
        root = bootstrap_repo(self.home)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        path = self.draft_file()
        code, doc, err = self.plan(root, "--contract-draft", path)
        self.assertEqual(code, 0, err)
        self.assertIsNone(doc["plan"]["available_migration"])

    def test_every_resolver_check_runs_on_the_draft(self):
        def outside(draft):
            draft["bindings"]["paths"]["architecture"] = ["../outside"]

        def range_refused(draft):
            draft["platform"] = {"min_inclusive": "99.0.0",
                                 "max_exclusive": "100.0.0"}

        def malformed(draft):
            draft["bindings"]["paths"]["artifacts"]["specs"] = []

        for name, mutate in (("a", outside), ("b", range_refused),
                             ("c", malformed)):
            with self.subTest(name):
                root = bootstrap_repo(self.home)
                draft = drafted_contract()
                mutate(draft)
                before = self.stored_plans()
                code, doc, err = self.plan(
                    root, "--contract-draft", self.draft_file(draft))
                self.assertEqual(code, 2, err)
                self.assertEqual(doc["error"]["repair_id"],
                                 "adopt.draft.invalid")
                violations = doc["error"]["violations"]
                if name == "a":
                    self.assertIn(
                        {"pointer": "/bindings/paths/architecture/0",
                         "message": "must be a non-empty repository-relative "
                                    "path with no '..' segment"}, violations)
                elif name == "b":
                    self.assertTrue(any(v["pointer"] == "/platform"
                                        for v in violations), violations)
                else:
                    self.assertTrue(any(
                        v["pointer"].startswith(
                            "/bindings/paths/artifacts/specs")
                        for v in violations), violations)
                self.assertEqual(self.stored_plans(), before)

    def test_a_draft_below_the_adoption_schema_is_refused(self):
        root = bootstrap_repo(self.home)
        before = self.stored_plans()
        with mock.patch.object(adopt_planning, "current_schema",
                               return_value=3):
            code, doc, err = self.plan(root, "--contract-draft",
                                       self.draft_file(drafted_contract()))
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["repair_id"], "adopt.draft.invalid")
        self.assertEqual([v["pointer"] for v in doc["error"]["violations"]],
                         ["/schema_version"])
        self.assertEqual(self.stored_plans(), before)

    def test_a_checkout_with_a_contract_refuses_a_draft(self):
        root = adopted_repo(self.home)
        code, doc, err = self.plan(root, "--contract-draft",
                                   self.draft_file())
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["repair_id"],
                         "adopt.draft.contract_present")

    def test_an_unreadable_or_inside_draft_is_refused(self):
        root = bootstrap_repo(self.home)
        (self.scratch / "array.json").write_text("[1]", encoding="utf-8")
        (self.scratch / "text.json").write_text("not json", encoding="utf-8")
        for path in (str(self.scratch / "missing.json"),
                     str(self.scratch / "array.json"),
                     str(self.scratch / "text.json")):
            with self.subTest(path):
                code, doc, err = self.plan(root, "--contract-draft", path)
                self.assertEqual(code, 2, err)
                self.assertEqual(doc["error"]["repair_id"],
                                 "adopt.draft.unreadable")
        inside = root / "draft.json"
        inside.write_text(json.dumps(self.draft), encoding="utf-8")
        before = git(root, "status", "--porcelain")
        snapshot = tree_snapshot(root)
        code, out, err = run("plan", "--repo-root", str(root),
                             "--contract-draft", str(inside),
                             home=self.home)
        self.assertEqual(code, 2, err)
        self.assertEqual(json.loads(out)["error"]["repair_id"],
                         "adopt.draft.inside_checkout")
        self.assertEqual(git(root, "status", "--porcelain"), before)
        self.assertEqual(tree_snapshot(root), snapshot)

    def test_the_draft_enters_the_plan_id(self):
        root = bootstrap_repo(self.home)
        path = self.draft_file()
        _, first, _ = self.plan(root, "--contract-draft", path)
        _, again, _ = self.plan(root, "--contract-draft", path)
        other = drafted_contract()
        other["project"]["name"] = "other"
        _, changed, _ = self.plan(
            root, "--contract-draft", self.draft_file(other, "other.json"))
        self.assertEqual(first["plan"]["plan_id"], again["plan"]["plan_id"])
        self.assertNotEqual(first["plan"]["plan_id"],
                            changed["plan"]["plan_id"])
        for doc in (first, changed):
            self.assertEqual(documented_plan_id(doc), doc["plan"]["plan_id"])

    def test_a_plan_without_a_draft_is_unchanged(self):
        root = bootstrap_repo(
            self.home, remotes=("https://github.com/fixture/target.git",))
        code, doc, err = self.plan(root)
        self.assertEqual(code, 0, err)
        self.assertNotIn("contract_draft", doc["plan"])
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(doc["plan"]["blockers"], [{
            "id": "contract-valid-after-amendment",
            "message": "the contract is absent, or carries violations the "
                       "planned amendment does not address"}])
        self.assertEqual(documented_plan_id(doc), doc["plan"]["plan_id"])

    def test_apply_writes_the_drafted_contract_in_its_worktree(self):
        root = bootstrap_repo(self.home)
        code, doc, err = self.plan(root, "--contract-draft",
                                   self.draft_file())
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["state"], "ready")
        code, out, err = run("apply", "--plan-id", doc["plan"]["plan_id"],
                             home=self.home)
        self.assertEqual(code, 0, err)
        branch = json.loads(out)["branch"]
        self.assertEqual(git(root, "show", f"{branch}:.agents/project.json"),
                         self.written().decode("utf-8"))
        self.assertFalse((root / ".agents/project.json").exists())

    def test_a_changed_stored_draft_refuses_apply(self):
        root = bootstrap_repo(self.home)
        _, doc, _ = self.plan(root, "--contract-draft", self.draft_file())
        digest = doc["plan"]["plan_id"].split(":", 1)[1]
        stored = self.home / ".agents/state/adopt/plans" / (digest + ".json")
        document = json.loads(stored.read_text(encoding="utf-8"))
        document["plan"]["contract_draft"]["project"]["name"] = "tampered"
        stored.write_text(json.dumps(document), encoding="utf-8")
        code, out, err = run("apply", "--plan-id", doc["plan"]["plan_id"],
                             home=self.home)
        self.assertEqual(code, 2, err)
        self.assertEqual(json.loads(out)["error"]["repair_id"],
                         "adopt.plan.inputs_changed")

    def test_a_drafted_id_registered_for_another_checkout_is_refused(self):
        root = bootstrap_repo(self.home)
        other = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        install_registry(self.home, [{"project_id": "fixture/target",
                                      "root": str(other)}])
        before = self.stored_plans()
        code, doc, err = self.plan(root, "--contract-draft",
                                   self.draft_file())
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["repair_id"], "adopt.draft.id_taken")
        self.assertEqual(doc["error"]["violations"], [{
            "pointer": "/project/id",
            "message": "the project id is already registered for another "
                       "checkout"}])
        self.assertEqual(self.stored_plans(), before)
        install_registry(self.home, [{"project_id": "fixture/target",
                                      "root": str(root)}])
        code, doc, err = self.plan(root, "--contract-draft",
                                   self.draft_file())
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["state"], "ready")


class CommitEnvironmentPlanTest(AdoptTestCase):
    """`plan --commit-environment` adds the environment to a contract that
    names none (ADR-project-contract-009)."""

    COMMAND = "devenv shell --"
    ARGV = ["devenv", "shell", "--"]

    def stored_plans(self) -> list[str]:
        directory = self.home / ".agents/state/adopt/plans"
        return sorted(path.name for path in directory.glob("*")) \
            if directory.exists() else []

    def authored(self, mutate, **kwargs) -> Path:
        """An adopted checkout whose committed contract `mutate` rewrote, its
        projections re-rendered so that it still plans `no_change`."""
        root = adopted_repo(self.home, **kwargs)
        contract = json.loads((root / ".agents/project.json").read_text("utf-8"))
        mutate(contract)
        # `apply` commits and runs every verification command, so the commit
        # asks for no signature and each command is one any host has.
        contract["bindings"]["vcs"]["commit"]["signed"] = False
        for command_id in contract["bindings"]["workflow"]["verification"]:
            contract["bindings"]["commands"][command_id]["argv"] = ["true"]
        scaffold(root, contract, self.home)
        # Git keeps no empty directory, and a cold export of the commit, which
        # `apply` resolves in, needs every declared standards path.
        for standards in contract["bindings"]["paths"]["standards"]:
            write(root, f"{standards}/bar.md", "# the bar\n")
        commit(root, "author the contract")
        return root

    def contract_after(self, root: Path, doc: dict) -> dict:
        """The contract the plan's one write of `.agents/project.json` makes."""
        writes = [change for change in doc["changes"]
                  if change["targets"] == [".agents/project.json"]]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["op"], "write-file")
        return writes[0]

    def expected(self, root: Path, *, id: str = "commit-environment",
                 argv: list[str] | None = None, add_command: bool = True):
        contract = json.loads((root / ".agents/project.json").read_text("utf-8"))
        contract.setdefault("platform", adopt_planning.derived_interval(
            json.loads(MANIFEST.read_text())["platform_version"]))
        contract["bindings"]["vcs"]["commit"]["environment"] = id
        if add_command:
            contract["bindings"]["commands"][id] = {
                "argv": self.ARGV if argv is None else argv,
                "cwd": ".", "env": []}
        return contract

    def test_a_contract_naming_no_environment_plans_the_command_and_its_binding(
            self):
        root = adopted_repo(self.home)
        _, plain, _ = self.plan(root)
        code, doc, err = self.plan(root, "--commit-environment", self.COMMAND)
        self.assertEqual(code, 0, err)
        self.assertEqual(plain["plan"]["outcome"], "no_change")
        self.assertEqual(doc["plan"]["outcome"], "reconcile")
        self.assertEqual(doc["plan"]["state"], "ready")
        self.assertEqual(doc["plan"]["commit_environment"], self.ARGV)
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))
        self.assertNotEqual(doc["plan"]["plan_id"], plain["plan"]["plan_id"])
        write = self.contract_after(root, doc)
        self.assertEqual(write["after"], sha256_hash(
            adopt_inspection.authored_bytes(self.expected(root))))

    def test_a_contract_naming_its_own_environment_is_left_alone(self):
        def own(contract):
            contract["bindings"]["commands"]["dev-shell"] = {
                "argv": ["true"], "cwd": ".", "env": []}
            contract["bindings"]["vcs"]["commit"]["environment"] = "dev-shell"

        arrangements = {
            "bound": lambda: self.authored(own),
            "no contract": lambda: bootstrap_repo(self.home),
            "schema 1": lambda: adopted_repo(self.home, schema=1),
        }
        for name, arrange in arrangements.items():
            with self.subTest(name):
                root = arrange()
                code, plain, err = self.plan(root)
                self.assertEqual(code, 0, err)
                code, doc, err = self.plan(
                    root, "--commit-environment", self.COMMAND)
                self.assertEqual(code, 0, err)
                self.assertEqual(doc["plan"]["plan_id"],
                                 plain["plan"]["plan_id"])
                self.assertEqual(doc["changes"], plain["changes"])
                self.assertEqual(doc["plan"]["outcome"],
                                 plain["plan"]["outcome"])
                self.assertNotIn("commit_environment", doc["plan"])

    def test_an_unreadable_command_is_refused_and_stores_nothing(self):
        root = adopted_repo(self.home)
        for command in ("devenv 'shell", "", "''"):
            with self.subTest(command):
                before = self.stored_plans()
                code, doc, err = self.plan(
                    root, "--commit-environment", command)
                self.assertEqual(code, 2, err)
                self.assertEqual(doc["error"]["repair_id"],
                                 "adopt.environment.unreadable")
                self.assertEqual(self.stored_plans(), before)

    def test_a_drafted_contract_takes_no_commit_environment(self):
        root = bootstrap_repo(self.home)
        scratch = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        path = scratch / "draft.json"
        path.write_text(json.dumps(drafted_contract()), encoding="utf-8")
        before = self.stored_plans()
        code, doc, err = self.plan(root, "--contract-draft", str(path),
                                   "--commit-environment", self.COMMAND)
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["repair_id"],
                         "adopt.environment.drafted")
        self.assertEqual(self.stored_plans(), before)

    def tampered_apply(self, value: object) -> dict:
        # A home of its own: a stored plan binds its id to one checkout.
        home = make_home()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        root = adopted_repo(home)
        _, doc, _ = self.plan(root, "--commit-environment", self.COMMAND,
                              home=home)
        plan_id = doc["plan"]["plan_id"]
        digest = plan_id.split(":", 1)[1]
        path = home / ".agents/state/adopt/plans" / (digest + ".json")
        document = json.loads(path.read_text(encoding="utf-8"))
        document["plan"]["commit_environment"] = value
        path.write_text(json.dumps(document), encoding="utf-8")
        code, out, err = run("apply", "--plan-id", plan_id,
                             "--acknowledge-deletions", home=home)
        self.assertEqual(code, 2, err)
        return json.loads(out)["error"]

    def test_apply_rederives_with_the_stored_command_and_refuses_a_changed_one(
            self):
        error = self.tampered_apply(["other", "shell"])
        self.assertEqual(error["repair_id"], "adopt.plan.inputs_changed")

    def test_apply_refuses_an_added_commit_environment_on_a_plan_whose_contract_binds_one(
            self):
        def own(contract):
            contract["bindings"]["commands"]["dev-shell"] = {
                "argv": ["true"], "cwd": ".", "env": []}
            contract["bindings"]["vcs"]["commit"]["environment"] = "dev-shell"

        root = self.authored(own)
        # a drifted projection gives the plan work to do
        write(root, "AGENTS.md", (root / "AGENTS.md").read_text() + "hand-edited\n")
        commit(root, "drift a projection")
        _, doc, _ = self.plan(root)
        self.assertEqual(doc["plan"]["state"], "ready")
        plan_id = doc["plan"]["plan_id"]
        path = (self.home / ".agents/state/adopt/plans"
                / (plan_id.split(":", 1)[1] + ".json"))
        document = json.loads(path.read_text(encoding="utf-8"))
        document["plan"]["commit_environment"] = ["other", "shell"]
        path.write_text(json.dumps(document), encoding="utf-8")
        code, out, err = run("apply", "--plan-id", plan_id,
                             "--acknowledge-deletions", home=self.home)
        self.assertEqual(code, 2, out + err)
        self.assertEqual(json.loads(out)["error"]["repair_id"],
                         "adopt.plan.inputs_changed")

    def test_only_an_integer_schema_version_of_the_current_schema_is_amended(self):
        def contract(version):
            return {"schema_version": version,
                    "bindings": {"commands": {}, "vcs": {"commit": {}}}}

        argv = ["devenv", "shell", "--"]
        self.assertEqual(adopt_planning.commit_environment_amendment(
            contract(2), argv, 2), ("commit-environment", argv))
        for version in (2.0, True, "2", None):
            with self.subTest(version=version):
                self.assertIsNone(adopt_planning.commit_environment_amendment(
                    contract(version), argv, 2 if version is not True else 1))

    def test_apply_refuses_a_malformed_stored_commit_environment(self):
        for value in ("devenv shell --", [], ["devenv", ""]):
            with self.subTest(value):
                error = self.tampered_apply(value)
                self.assertEqual(error["repair_id"], "adopt.plan.malformed")
                self.assertEqual(error["violations"][0]["pointer"],
                                 "/plan/commit_environment")

    def test_an_authored_but_unbound_command_equal_to_the_proposal_is_bound_and_apply_commits_through_it(
            self):
        scratch = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        marker = scratch / "marker"
        argv = ["sh", "-c",
                f"printf 'ran\\n' >> {shlex.quote(str(marker))} && exec \"$@\"",
                "commit-environment"]
        entry = {"argv": argv, "cwd": ".", "env": []}

        def author(contract):
            contract["bindings"]["commands"]["commit-environment"] = entry

        root = self.authored(author)
        code, doc, err = self.plan(root, "--commit-environment",
                                   shlex.join(argv))
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["commit_environment"], argv)
        write = self.contract_after(root, doc)
        self.assertEqual(write["after"], sha256_hash(
            adopt_inspection.authored_bytes(self.expected(
                root, argv=argv, add_command=False))))
        code, out, err = run("apply", "--plan-id", doc["plan"]["plan_id"],
                             "--acknowledge-deletions", home=self.home)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(marker.read_text(encoding="utf-8"), "ran\n")
        branch = json.loads(out)["branch"]
        committed = json.loads(git(root, "show", f"{branch}:.agents/project.json"))
        self.assertEqual(
            committed["bindings"]["vcs"]["commit"]["environment"],
            "commit-environment")
        self.assertEqual(committed["bindings"]["commands"]["commit-environment"],
                         entry)

    def test_a_different_authored_commit_environment_command_is_kept_and_the_proposal_takes_a_free_id(
            self):
        authored = {"argv": ["true"], "cwd": ".", "env": []}

        def author(contract):
            contract["bindings"]["commands"]["commit-environment"] = authored

        root = self.authored(author)
        code, doc, err = self.plan(root, "--commit-environment", self.COMMAND)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["commit_environment"], self.ARGV)
        expected = self.expected(root, id="commit-environment-2")
        self.assertEqual(expected["bindings"]["commands"]["commit-environment"],
                         authored)
        write = self.contract_after(root, doc)
        self.assertEqual(write["after"], sha256_hash(
            adopt_inspection.authored_bytes(expected)))


class InspectionBoundaryTest(AdoptTestCase):
    def entry(self, doc: object, path: str) -> dict:
        for candidate in doc["evidence"]:
            if candidate["path"] == path:
                return candidate
        raise AssertionError(
            f"{path!r} is not in {[e['path'] for e in doc['evidence']]}")

    def test_a_secret_shaped_path_is_named_but_never_read(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".claude/specs/secrets/leak.md", "SUPER-SECRET-VALUE\n")
        commit(root, "add a secret-shaped path")
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        entry = self.entry(doc, ".claude/specs/secrets/leak.md")
        self.assertIsNone(entry["fingerprint"])
        self.assertEqual(entry["action"], "retain-product")
        self.assertIsNone(entry["target"])
        self.assertNotIn("SUPER-SECRET-VALUE", out)
        for op in doc["changes"]:
            self.assertNotIn(".claude/specs/secrets/leak.md",
                             op["sources"] + op["targets"])

    def test_untracked_overlap_keeps_the_plan_draft_with_a_named_blocker(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".out-of-scope/draft.md", "# untracked\n")
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "draft")
        blocked = [b["id"] for b in doc["plan"]["blockers"]]
        self.assertIn("no-untracked-overlap", blocked)
        entry = self.entry(doc, ".out-of-scope/draft.md")
        self.assertEqual(entry["provenance"], "untracked-explicit-paths")

    def test_superpowers_and_worktrees_are_metadata_only(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".gitignore",
              GITIGNORE_WITH_COMMENT + ".superpowers/\n.worktrees/\n")
        commit(root, "ignore the residue trees")
        write(root, ".superpowers/sdd/notes.md", "RESIDUE-CONTENT\n")
        write(root, ".worktrees/wt-a/file.md", "WORKTREE-CONTENT\n")
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        for path in (".superpowers", ".worktrees"):
            with self.subTest(path=path):
                entry = self.entry(doc, path)
                self.assertEqual(entry["provenance"],
                                 "targeted-ignored-metadata-only")
                self.assertIsNone(entry["fingerprint"])
                self.assertEqual(entry["action"], "retain-product")
                self.assertGreaterEqual(entry["count"], 1)
        self.assertNotIn("RESIDUE-CONTENT", out)
        self.assertNotIn("WORKTREE-CONTENT", out)

    def test_registered_worktrees_are_metadata_only(self):
        root = nix_config_shape_repo(self.home)
        linked = Path(tempfile.mkdtemp()).resolve() / "wt-linked"
        git(root, "worktree", "add", "--quiet", str(linked), "-b", "linked")
        doc = self.ready_plan(root)
        entry = self.entry(doc, ".git/worktrees")
        self.assertEqual(entry["provenance"], "git-worktree-metadata-only")
        self.assertIsNone(entry["fingerprint"])
        self.assertEqual(entry["count"], 1)

    def test_read_only_on_a_succeeding_run(self):
        root = nix_config_shape_repo(self.home)
        self.assert_read_only(root, 0, "plan", "--repo-root", str(root))

    def test_read_only_on_a_refusing_run(self):
        home = make_home(manifest_with([1, 2], []))
        root = adopted_repo(self.home, schema=1)
        before_status = git(root, "status", "--porcelain")
        before_tree = tree_snapshot(root)
        code, _, err = run("plan", "--repo-root", str(root), home=home)
        self.assertEqual(code, 2, err)
        self.assertEqual(git(root, "status", "--porcelain"), before_status)
        self.assertEqual(tree_snapshot(root), before_tree)


# --------------------------------------------------------------------------
# Typed operations
# --------------------------------------------------------------------------


class TypedOperationTest(AdoptTestCase):
    def ops(self, doc: object, kind: str) -> list[dict]:
        return [op for op in doc["changes"] if op["op"] == kind]

    def only_write(self, doc: object, target: str) -> dict:
        matches = [op for op in doc["changes"]
                   if op["op"] == "write-file" and op["targets"] == [target]]
        self.assertEqual(len(matches), 1, target)
        return matches[0]

    def test_moves_are_git_mv_sorted_by_old_path(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        moves = self.ops(doc, "git-mv")
        pairs = [(op["sources"][0], op["targets"][0]) for op in moves]
        self.assertEqual([p[0] for p in pairs], sorted(p[0] for p in pairs))
        self.assertIn((".out-of-scope/z.md",
                       ".agents/knowledge/rejections/z.md"), pairs)
        # The legacy record trees stay where they are (#1456).
        self.assertEqual(
            [pair for pair in pairs if pair[0].startswith(".claude/")], [])
        self.assertEqual(
            [pair for pair in pairs
             if pair[1].startswith(".agents/artifacts")], [])

    def test_the_contract_amendment_adds_platform_and_repoints_paths(self):
        root = nix_config_shape_repo(self.home)
        doc = self.ready_plan(root)
        op = self.only_write(doc, ".agents/project.json")
        contract = json.loads(
            (root / ".agents" / "project.json").read_text("utf-8"))
        version = json.loads(MANIFEST.read_text("utf-8"))["platform_version"]
        contract["platform"] = {
            "min_inclusive": version,
            "max_exclusive": f"{int(version.split('.')[0]) + 1}.0.0"}
        contract["bindings"]["paths"]["rejections"] = [
            ".agents/knowledge/rejections"]
        expected = json.dumps(contract, indent=2, ensure_ascii=False) + "\n"
        self.assertEqual(op["after"], sha256_hash(expected.encode("utf-8")))

    def test_the_runtime_sentinel_is_exactly_two_bytes(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        op = self.only_write(doc, ".agents/runtime/.gitignore")
        self.assertIsNone(op["before"])
        self.assertEqual(op["after"], sha256_hash(b"*\n"))

    def test_the_migration_map_is_named_by_plan_id_and_is_the_only_bookkeeping_write(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        digest = doc["plan"]["plan_id"].split(":", 1)[1]
        self.assertEqual(
            doc["handoff"]["migration_map"],
            f".agents/knowledge/archive/path-migrations/{digest}.json")
        self.only_write(doc, doc["handoff"]["migration_map"])
        self.assertEqual(
            [target for op in doc["changes"] for target in op["targets"]
             if target.startswith((".agents/artifacts/",
                                   ".agents/knowledge/archive/path-migrations/"))
             and op["op"] == "write-file"],
            [doc["handoff"]["migration_map"]])

    def test_projections_are_regenerated_last(self):
        doc = self.ready_plan(nix_config_shape_repo(self.home))
        kinds = [op["op"] for op in doc["changes"]]
        regenerations = self.ops(doc, "regenerate-projection")
        self.assertEqual(len(regenerations), 2)
        self.assertEqual(kinds[-2:], ["regenerate-projection"] * 2)
        self.assertEqual(
            sorted(op["targets"][0] for op in regenerations),
            ["AGENTS.md", "CLAUDE.md"])

    def test_a_declared_conformance_workflow_is_regenerated_from_the_contract(self):
        root = nix_config_shape_repo(self.home)
        contract = json.loads(
            (root / ".agents" / "project.json").read_text("utf-8"))
        contract["projections"].append({
            "id": "conformance.workflow", "kind": "conformance_workflow",
            "target": ".github/workflows/conformance.yaml"})
        write(root, ".agents/project.json", json.dumps(contract, indent=2) + "\n")
        commit(root, "declare the conformance workflow")
        doc = self.ready_plan(root)
        workflow = [op for op in self.ops(doc, "regenerate-projection")
                    if op["targets"] == [".github/workflows/conformance.yaml"]]
        self.assertEqual(len(workflow), 1)
        self.assertEqual(workflow[0]["sources"], [".agents/project.json"])
        self.assertIsNone(workflow[0]["before"])
        self.assertEqual(
            [op["op"] for op in doc["changes"]][-3:],
            ["regenerate-projection"] * 3)

    def test_no_operation_targets_a_file_outside_the_planned_set(self):
        root = nix_config_shape_repo(self.home)
        write(root, "home/common/agent-skills/skills/writing-plans/SKILL.md",
              "Plans live in `.claude/plans` unless the contract says otherwise.\n")
        commit(root, "add a skill mentioning the legacy path")
        doc = self.ready_plan(root)
        skill = "home/common/agent-skills/skills/writing-plans/SKILL.md"
        for op in doc["changes"]:
            self.assertNotIn(skill, op["sources"] + op["targets"])
        self.assertEqual(
            (root / skill).read_text("utf-8"),
            "Plans live in `.claude/plans` unless the contract says otherwise.\n")

    def test_the_legacy_binding_config_is_never_written(self):
        # The legacy writer is removed (platform 2.0.0): `plan` leaves
        # `.claude/skills.config.json` as it finds it.
        root = nix_config_shape_repo(self.home)
        before = (root / ".claude" / "skills.config.json").read_bytes()
        doc = self.ready_plan(root)
        for op in doc["changes"]:
            self.assertNotIn(".claude/skills.config.json", op["targets"])
        self.assertEqual((root / ".claude" / "skills.config.json").read_bytes(), before)

    def test_only_the_declared_legacy_binding_config_is_rewritten(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".claude/other.config.json", json.dumps({"specDir": "x"}))
        commit(root, "add a second config")
        doc = self.ready_plan(root)
        for op in doc["changes"]:
            self.assertNotIn(".claude/other.config.json", op["targets"])


class RecordTreeClassificationTest(AdoptTestCase):
    """#340 AC1: the record trees are classified centrally; adoption leaves
    the legacy ones in place (#1456)."""

    def test_the_five_record_trees_plan_to_ready_and_stay_in_place(self):
        doc = self.ready_plan(record_trees_repo(self.home))
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        pairs = [(op["sources"][0], op["targets"][0])
                 for op in doc["changes"] if op["op"] == "git-mv"]
        self.assertEqual(
            [pair for pair in pairs if pair[0].startswith(".claude/")], [])
        entries = {entry["path"]: entry for entry in doc["evidence"]}
        for group in (".claude/specs", ".claude/plans", ".claude/handoffs",
                      ".claude/notes", ".claude/research"):
            with self.subTest(group=group):
                entry = entries[group]
                self.assertEqual(
                    (entry["provenance"], entry["lifecycle_class"],
                     entry["action"], entry["target"]),
                    ("tracked", "durable-artifact", "retain-product", None))

    def test_an_occupied_destination_fails_the_destination_gate(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".agents/knowledge/rejections/z.md", "# occupied\n")
        commit(root, "occupy .out-of-scope/z.md's destination")
        doc = self.ready_plan(root)
        gate = next(gate for gate in doc["verification"]["ready_gates"]
                    if gate["id"] == "no-existing-destination")
        self.assertEqual(gate, {"id": "no-existing-destination",
                                "status": "failed",
                                "repair_id": "adopt.destination.occupied"})
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertIn("no-existing-destination",
                      [blocker["id"] for blocker in doc["plan"]["blockers"]])

    def test_a_destination_under_an_existing_file_fails_the_gate(self):
        root = nix_config_shape_repo(self.home)
        write(root, ".agents/knowledge/rejections", "a file, not a directory\n")
        write(root, ".out-of-scope/n.md", "# note n\n")
        commit(root, "put a file where a destination's parent goes")
        self.assert_destination_gate_fails(self.ready_plan(root))

    def test_a_dangling_symlink_destination_parent_fails_the_gate(self):
        root = nix_config_shape_repo(self.home)
        (root / ".agents" / "knowledge").mkdir(parents=True, exist_ok=True)
        (root / ".agents" / "knowledge" / "rejections").symlink_to("missing")
        write(root, ".out-of-scope/n.md", "# note n\n")
        commit(root, "put a dangling link where a destination's parent goes")
        self.assert_destination_gate_fails(self.ready_plan(root))

    def test_a_dangling_symlink_at_a_destination_fails_the_gate(self):
        root = nix_config_shape_repo(self.home)
        rejections = root / ".agents" / "knowledge" / "rejections"
        rejections.mkdir(parents=True, exist_ok=True)
        (rejections / "n.md").symlink_to("missing")
        write(root, ".out-of-scope/n.md", "# note n\n")
        commit(root, "put a dangling link where a destination goes")
        self.assert_destination_gate_fails(self.ready_plan(root))

    def test_a_symlinked_directory_destination_parent_fails_the_gate(self):
        """A link to a real directory is still a link, not a directory the
        move can create its destination in."""
        root = nix_config_shape_repo(self.home)
        write(root, "elsewhere/keep.md", "# keep\n")
        (root / ".agents" / "knowledge").mkdir(parents=True, exist_ok=True)
        (root / ".agents" / "knowledge" / "rejections").symlink_to(
            "../../elsewhere", target_is_directory=True)
        write(root, ".out-of-scope/n.md", "# note n\n")
        commit(root, "put a directory link where a destination's parent goes")
        self.assert_destination_gate_fails(self.ready_plan(root))

    def assert_destination_gate_fails(self, doc: object) -> None:
        gate = next(gate for gate in doc["verification"]["ready_gates"]
                    if gate["id"] == "no-existing-destination")
        self.assertEqual(gate["status"], "failed", gate)
        self.assertEqual(doc["plan"]["state"], "draft")


class NativeSettingsTest(AdoptTestCase):
    """#372 D7: a tracked `.claude/settings.json` is retained by its row."""

    PATH = ".claude/settings.json"

    def test_a_tracked_settings_file_is_retained_without_a_question(self):
        root = nix_config_shape_repo(self.home)
        write(root, self.PATH, '{"hooks": {}}\n')
        commit(root, "track the native settings file")
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(
            [op for op in doc["changes"]
             if self.PATH in op["sources"] + op["targets"]], [])
        (entry,) = [entry for entry in doc["evidence"]
                    if entry["path"] == self.PATH]
        self.assertEqual(
            (entry["provenance"], entry["lifecycle_class"], entry["action"],
             entry["target"], entry["count"]),
            ("tracked", "legacy-native-store", "retain-product", None, 1))
        self.assertIsNotNone(entry["fingerprint"])


class CandidateQuestionTest(AdoptTestCase):
    """#340 AC2: every undecided candidate carries a stable question."""

    OPEN_MEMBERS = ["basis", "id", "impact", "recommendation", "subject",
                    "value"]

    def only_open(self, doc: object) -> dict:
        self.assertEqual(len(doc["decisions"]["open"]), 1,
                         doc["decisions"]["open"])
        entry = doc["decisions"]["open"][0]
        self.assertEqual(sorted(entry), self.OPEN_MEMBERS)
        self.assertEqual(entry["id"], "candidate-class")
        return entry

    def test_a_tracked_candidate_opens_one_archive_question(self):
        doc = self.ready_plan(candidate_repo(self.home, ".claude/odd.md"))
        entry = self.only_open(doc)
        self.assertEqual((entry["subject"], entry["value"]),
                         (".claude/odd.md", "archive-history"))
        for member in ("basis", "impact", "recommendation"):
            self.assertNotIn(".claude/odd.md", entry[member])
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            sorted(blocker["id"] for blocker in doc["plan"]["blockers"]),
            ["no-needs-decision", "no-open-decisions"])

    def test_the_prose_is_fixed_across_candidates(self):
        doc = self.ready_plan(candidate_repo(
            self.home, ".claude/zeta/b.md", ".claude/a.md"))
        entries = doc["decisions"]["open"]
        self.assertEqual([entry["subject"] for entry in entries],
                         [".claude/a.md", ".claude/zeta/b.md"])
        for member in ("basis", "impact", "recommendation"):
            self.assertEqual(entries[0][member], entries[1][member])

    def test_a_secret_shaped_candidate_has_no_answer(self):
        doc = self.ready_plan(candidate_repo(
            self.home, ".claude/secrets/key.md"))
        entry = self.only_open(doc)
        self.assertEqual(entry["subject"], ".claude/secrets/key.md")
        self.assertIsNone(entry["value"])

    def test_a_tracked_symlink_out_of_the_repository_has_no_answer(self):
        doc = self.ready_plan(tracked_symlink_repo(self.home))
        entry = self.only_open(doc)
        self.assertEqual((entry["subject"], entry["value"]), (LINK, None))

    def test_an_ignored_candidate_is_offered_retention(self):
        doc = self.ready_plan(ignored_symlink_repo(self.home))
        entry = self.only_open(doc)
        self.assertEqual((entry["subject"], entry["value"]),
                         (".claude/settings.local.json", "retain-product"))

    def test_project_id_sorts_before_candidate_questions(self):
        root = reconcile_repo(self.home, remotes=())
        write(root, ".claude/odd.md", "# odd\n")
        commit(root, "add an unclassified agent path")
        doc = self.ready_plan(root)
        self.assertEqual([entry["id"] for entry in doc["decisions"]["open"]],
                         ["project-id", "candidate-class"])
        self.assertEqual(sorted(doc["decisions"]["open"][0]),
                         ["basis", "id", "impact", "recommendation", "value"])

    def test_the_human_view_names_each_subject_and_its_answer(self):
        root = candidate_repo(self.home, ".claude/odd.md",
                              ".claude/secrets/key.md")
        code, human, err = run("plan", "--repo-root", str(root),
                               "--format", "human", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("open candidate-class .claude/odd.md "
                      "(answer: archive-history): ", human)
        self.assertIn("open candidate-class .claude/secrets/key.md "
                      "(answer: none): ", human)

    def test_the_question_set_is_closed(self):
        self.assertEqual(adopt_inspection.QUESTION_IDS,
                         ("project-id", "candidate-class", "path-reference",
                          "reference-policy"))
        for function in (adopt_inspection.question_impact,
                         adopt_inspection.question_recommendation):
            with self.subTest(function=function.__name__):
                with self.assertRaises(ValueError):
                    function("candidate-class:.claude/odd.md")
        with self.assertRaises(ValueError):
            adopt_inspection.candidate_answer("untracked-explicit-paths",
                                              ".claude/odd.md", True)


class CandidateAnswerTest(AdoptTestCase):
    """#340 AC2: answering a candidate is reflected in the plan id."""

    def answered(self, root: Path, *triples: tuple[str, str, str]):
        args = [token for triple in triples
                for token in ("--answer", *triple)]
        return self.plan(root, *args)

    def stored_plans(self) -> list[str]:
        store = self.home / ".agents" / "state" / "adopt" / "plans"
        return sorted(path.name for path in store.iterdir()) \
            if store.is_dir() else []

    def refused(self, root: Path, repair_id: str,
                *triples: tuple[str, str, str]) -> None:
        before = self.stored_plans()
        code, payload, err = self.answered(root, *triples)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["code"], "adopt_failure")
        self.assertEqual(payload["error"]["repair_id"], repair_id)
        self.assertEqual(payload["error"]["violations"][0]["pointer"],
                         "/decisions/answered")
        self.assertEqual(self.stored_plans(), before)

    def first_violation(self, root: Path, *triples) -> tuple[str, dict]:
        code, payload, err = self.answered(root, *triples)
        self.assertEqual(code, 2, err or payload)
        return (payload["error"]["repair_id"],
                payload["error"]["violations"][0])

    def test_answering_reaches_ready_and_changes_the_plan_id(self):
        root = candidate_repo(self.home, ODD)
        draft = self.ready_plan(root)
        code, doc, err = self.answered(
            root, ("candidate-class", ODD, "archive-history"))
        self.assertEqual(code, 0, err)
        self.assertNotEqual(doc["plan"]["plan_id"], draft["plan"]["plan_id"])
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(doc["decisions"]["answered"], [
            {"id": "candidate-class", "subject": ODD,
             "value": "archive-history"}])
        # The independent oracle, with every other digest input held
        # constant: the id covers the non-empty answers, and the same
        # document with no answers digests differently.
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))
        unanswered = {**doc, "decisions": {**doc["decisions"],
                                           "answered": []}}
        self.assertNotEqual(doc["plan"]["plan_id"],
                            documented_plan_id(unanswered))
        entry = next(e for e in doc["evidence"] if e["path"] == ODD)
        self.assertEqual(
            (entry["lifecycle_class"], entry["action"], entry["target"]),
            ("unclassified", "archive-history", ARCHIVED))
        pairs = [(op["sources"][0], op["targets"][0])
                 for op in doc["changes"] if op["op"] == "git-mv"]
        self.assertIn((ODD, ARCHIVED), pairs)

    def test_an_answered_ignored_candidate_is_retained_without_an_operation(self):
        path = ".claude/settings.local.json"
        code, doc, err = self.answered(
            ignored_symlink_repo(self.home),
            ("candidate-class", path, "retain-product"))
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        entry = next(e for e in doc["evidence"] if e["path"] == path)
        self.assertEqual((entry["action"], entry["target"]),
                         ("retain-product", None))
        for op in doc["changes"]:
            self.assertNotIn(path, op["sources"] + op["targets"])

    def test_a_non_candidate_question_id_is_an_invalid_answer(self):
        self.refused(candidate_repo(self.home, ODD),
                     "adopt.decisions.invalid_answer",
                     ("project-id", ODD, "archive-history"))

    def test_a_value_the_question_does_not_offer_is_an_invalid_answer(self):
        self.refused(candidate_repo(self.home, ODD),
                     "adopt.decisions.invalid_answer",
                     ("candidate-class", ODD, "retain-product"))

    def test_every_answer_to_a_secret_shaped_candidate_is_invalid(self):
        root = candidate_repo(self.home, ".claude/secrets/key.md")
        for value in ("archive-history", "retain-product"):
            with self.subTest(value=value):
                self.refused(root, "adopt.decisions.invalid_answer",
                             ("candidate-class", ".claude/secrets/key.md",
                              value))

    def test_archiving_a_tracked_symlink_out_of_the_repository_is_invalid(self):
        root = tracked_symlink_repo(self.home)
        for value in ("archive-history", "retain-product"):
            with self.subTest(value=value):
                self.refused(root, "adopt.decisions.invalid_answer",
                             ("candidate-class", LINK, value))

    def test_one_subject_answered_twice_is_an_invalid_answer(self):
        self.refused(candidate_repo(self.home, ODD),
                     "adopt.decisions.invalid_answer",
                     ("candidate-class", ODD, "archive-history"),
                     ("candidate-class", ODD, "archive-history"))

    def test_a_subject_that_is_not_an_undecided_candidate_is_unmatched(self):
        root = candidate_repo(self.home, ODD)
        for subject in (".claude/missing.md", ".claude/specs/x.md"):
            with self.subTest(subject=subject):
                self.refused(root, "adopt.decisions.unmatched_answer",
                             ("candidate-class", subject, "archive-history"))

    def test_the_human_view_prints_the_answer(self):
        root = candidate_repo(self.home, ODD)
        code, human, err = run(
            "plan", "--repo-root", str(root), "--format", "human",
            "--answer", "candidate-class", ODD, "archive-history",
            home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn(f"answered candidate-class {ODD}: archive-history\n",
                      human)

    def test_answer_order_on_the_command_line_does_not_matter(self):
        root = candidate_repo(self.home, ODD, ".claude/a.md")
        first = ("candidate-class", ".claude/a.md", "archive-history")
        second = ("candidate-class", ODD, "archive-history")
        forward = run("plan", "--repo-root", str(root), "--answer", *first,
                      "--answer", *second, home=self.home)
        # A child, so the two runs differ in hash seed as well (issue 612).
        backward = run_child("plan", "--repo-root", str(root), "--answer", *second,
                             "--answer", *first, home=self.home)
        self.assertEqual(forward[0], 0, forward[2])
        self.assertEqual(forward[1], backward[1])

    def test_competing_violations_report_the_sorted_first_one(self):
        root = candidate_repo(self.home, ODD)
        bad_id = ("project-id", ODD, "archive-history")
        unmatched = ("candidate-class", ".claude/missing.md",
                     "archive-history")
        expected = ("adopt.decisions.unmatched_answer",
                    {"pointer": "/decisions/answered",
                     "message": "the answered subject is not an undecided "
                                "candidate of this inspection"})
        for triples in ((bad_id, unmatched), (unmatched, bad_id)):
            with self.subTest(triples=triples):
                self.assertEqual(self.first_violation(root, *triples),
                                 expected)

    def test_a_duplicate_subject_is_reported_before_its_value(self):
        root = candidate_repo(self.home, ODD)
        good = ("candidate-class", ODD, "archive-history")
        bad = ("candidate-class", ODD, "retain-product")
        expected = ("adopt.decisions.invalid_answer",
                    {"pointer": "/decisions/answered",
                     "message": "a candidate is answered more than once"})
        for triples in ((good, bad), (bad, good)):
            with self.subTest(triples=triples):
                self.assertEqual(self.first_violation(root, *triples),
                                 expected)

    def test_the_recommendation_names_the_answer_flag(self):
        self.assertIn("plan --answer candidate-class <subject> <value>",
                      adopt_inspection.question_recommendation(
                          "candidate-class"))

    def test_archive_history_relocates(self):
        self.assertTrue(adopt_inspection.action_relocates("archive-history"))


class LinkRewritePlanTest(AdoptTestCase):
    """#345: `plan` rewrites relative Markdown links across the moves."""

    def link_writes(self, doc: object) -> list[dict]:
        return [op for op in doc["changes"] if op["op"] == "write-file"
                and op["targets"][0] in LINKED_AFTER]

    def test_the_linked_fixture_plans_to_ready_with_the_rewrites(self):
        doc = self.ready_plan(linked_repo(self.home))
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        writes = self.link_writes(doc)
        self.assertEqual([op["targets"] for op in writes],
                         [[".agents/knowledge/rejections/z.md"],
                          [".claude/rules/r.md"], ["README.md"]])
        for op in writes:
            target = op["targets"][0]
            self.assertEqual(op["sources"], [target])
            self.assertEqual(op["before"], sha256_hash(
                LINKED_BASE[LINKED_SOURCES[target]].encode("utf-8")))
            self.assertEqual(op["after"], sha256_hash(
                LINKED_AFTER[target].encode("utf-8")))
        order = [(op["op"], op["targets"][0] if op["targets"] else None)
                 for op in doc["changes"]]
        self.assertNotIn(("write-file", ".claude/skills.config.json"), order)
        first = order.index(
            ("write-file", ".agents/knowledge/rejections/z.md"))
        projections = [index for index, (kind, _) in enumerate(order)
                       if kind == "regenerate-projection"]
        self.assertTrue(projections)
        self.assertLess(first + 2, min(projections))

    def test_anchors_titles_and_reference_definitions_survive_and_urls_stay(self):
        doc = self.ready_plan(linked_repo(self.home))
        readme = next(op for op in self.link_writes(doc)
                      if op["targets"] == ["README.md"])
        self.assertEqual(readme["after"], sha256_hash(
            LINK_README_AFTER.encode("utf-8")))
        before = [link.target
                  for link in adopt_links.links(LINK_README_BEFORE)]
        after = [link.target for link in adopt_links.links(LINK_README_AFTER)]
        self.assertEqual(list(zip(before, after)), [
            (".out-of-scope/z.md#intro",
             ".agents/knowledge/rejections/z.md#intro"),
            ("./.out-of-scope/", "./.agents/knowledge/rejections/"),
            (".out-of-scope/z.md", ".agents/knowledge/rejections/z.md"),
            (".out-of-scope/missing.md", ".out-of-scope/missing.md"),
            ("https://example.com/.out-of-scope/z.md",
             "https://example.com/.out-of-scope/z.md"),
            ("README.md", "README.md"),
            (".out-of-scope/w.md", ".agents/knowledge/rejections/w.md"),
        ])

    def test_the_summary_is_published_and_enters_the_plan_id(self):
        doc = self.ready_plan(linked_repo(self.home))
        self.assertEqual(doc["link_rewrites"], LINKED_SUMMARY)
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_a_different_rewrite_set_is_a_different_plan_id(self):
        doc = self.ready_plan(linked_repo(self.home))
        inputs = (doc["plan"]["project_id"], doc["plan"]["base_revision"],
                  doc["plan"]["platform"], doc["evidence"],
                  doc["decisions"]["answered"])
        self.assertEqual(
            adopt_planning.compute_plan_id(*inputs, doc["link_rewrites"],
                                           doc["path_references"],
                                           doc["reference_policies"],
                                           doc["reference_formatting"]),
            doc["plan"]["plan_id"])
        other = json.loads(json.dumps(LINKED_SUMMARY))
        other["inbound"] = {"links": 4, "files": ["README.md"]}
        self.assertNotEqual(
            adopt_planning.compute_plan_id(*inputs, other,
                                           doc["path_references"],
                                           doc["reference_policies"],
                                           doc["reference_formatting"]),
            doc["plan"]["plan_id"])

    def test_the_human_view_prints_one_link_line(self):
        code, out, err = run("plan", "--repo-root",
                             str(linked_repo(self.home)), "--format", "human",
                             home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nlinks: inbound 5 in 2 files, outbound 2 in 1 files, "
                      "unrewritable 0, already broken 1\n", out)

    def test_the_conformance_gate_is_the_last_ready_gate(self):
        self.assertEqual(adopt_inspection.READY_GATES[-1], "conformance-plannable")

    def test_a_markdown_file_any_other_operation_names_is_a_derivation_bug(self):
        op = adopt_planning.operation
        link = op("write-file", ["README.md"], ["README.md"],
                  "sha256:" + "0" * 64, "sha256:" + "1" * 64)
        adopt_planning.check_markdown_writes([link], {"README.md"})
        delete = op("delete-file", ["notes.md"], [],
                    "git-object:" + "0" * 40, None)
        for changes, targets in (([link], set()),
                                 ([link, link], {"README.md"}),
                                 ([], {"README.md"}),
                                 ([delete], set())):
            with self.subTest(changes=changes, targets=targets):
                with self.assertRaises(ValueError):
                    adopt_planning.check_markdown_writes(changes, targets)


class PathReferencePlanTest(AdoptTestCase):
    """#350: `plan` asks about every path literal naming a moved tree."""

    def answered(self, root: Path, value: str,
                 subject: str = REFERENCE_SUBJECT) -> object:
        code, doc, err = self.plan(root, "--answer", "path-reference",
                                   subject, value)
        self.assertEqual(code, 0, err or doc)
        return doc

    def stored_plans(self) -> list[str]:
        store = self.home / ".agents" / "state" / "adopt" / "plans"
        return sorted(path.name for path in store.iterdir()) \
            if store.is_dir() else []

    def naming(self, doc: object, path: str) -> list[dict]:
        return [op for op in doc["changes"]
                if path in op["sources"] + op["targets"]]

    def test_an_open_reference_keeps_the_plan_draft_with_a_stable_question(self):
        root = referenced_repo(self.home)
        doc = self.ready_plan(root)
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            [gate["id"] for gate in doc["verification"]["ready_gates"]
             if gate["status"] != "passed"], ["no-open-decisions"])
        (question,) = [entry for entry in doc["decisions"]["open"]
                       if entry["id"] == "path-reference"]
        self.assertEqual(sorted(question), ["answers", "basis", "id", "impact",
                                            "recommendation", "subject"])
        self.assertEqual(question["subject"], REFERENCE_SUBJECT)
        self.assertEqual(question["answers"], ["extend", "retain"])
        for member in ("basis", "impact", "recommendation"):
            self.assertNotIn("tools/", question[member])
        self.assertEqual(doc["path_references"], [REFERENCE_ROW])
        self.assertEqual(self.naming(doc, CHECK_LINKS), [])
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))
        again = self.ready_plan(root)
        self.assertEqual(again["decisions"]["open"], doc["decisions"]["open"])
        self.assertEqual(again["plan"]["plan_id"], doc["plan"]["plan_id"])

    def test_answering_extend_reaches_ready_with_one_write(self):
        doc = self.answered(referenced_repo(self.home), "extend")
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(doc["decisions"]["answered"],
                         [{"id": "path-reference",
                           "subject": REFERENCE_SUBJECT, "value": "extend"}])
        self.assertEqual(doc["path_references"],
                         [{**REFERENCE_ROW, "answer": "extend",
                           "decided_by": "occurrence"}])
        (write_op,) = self.naming(doc, CHECK_LINKS)
        self.assertEqual(write_op["op"], "write-file")
        self.assertEqual(write_op["sources"], [CHECK_LINKS])
        self.assertEqual(write_op["targets"], [CHECK_LINKS])
        self.assertEqual(write_op["before"],
                         sha256_hash(CHECK_LINKS_SCRIPT.encode("utf-8")))
        self.assertEqual(write_op["after"],
                         sha256_hash(CHECK_LINKS_EXTENDED.encode("utf-8")))
        order = [(op["op"], op["targets"][0] if op["targets"] else None)
                 for op in doc["changes"]]
        script = order.index(("write-file", CHECK_LINKS))
        self.assertLess(order.index(("write-file", "README.md")), script)
        self.assertLess(script, min(
            index for index, (kind, _) in enumerate(order)
            if kind == "regenerate-projection"))
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_retain_reaches_ready_and_writes_nothing(self):
        doc = self.answered(referenced_repo(self.home), "retain")
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["path_references"],
                         [{**REFERENCE_ROW, "answer": "retain",
                           "decided_by": "occurrence"}])
        self.assertEqual(self.naming(doc, CHECK_LINKS), [])

    def test_the_answer_is_covered_by_the_plan_id(self):
        root = referenced_repo(self.home)
        opened = self.ready_plan(root)
        extended = self.answered(root, "extend")
        retained = self.answered(root, "retain")
        self.assertEqual(len({doc["plan"]["plan_id"]
                              for doc in (opened, extended, retained)}), 3)
        inputs = (extended["plan"]["project_id"],
                  extended["plan"]["base_revision"],
                  extended["plan"]["platform"], extended["evidence"],
                  extended["decisions"]["answered"],
                  extended["link_rewrites"])
        self.assertEqual(
            adopt_planning.compute_plan_id(*inputs,
                                           extended["path_references"],
                                           extended["reference_policies"],
                                           extended["reference_formatting"]),
            extended["plan"]["plan_id"])
        other = [{**extended["path_references"][0],
                  "additions": [".agents/knowledge/other/"]}]
        self.assertNotEqual(
            adopt_planning.compute_plan_id(*inputs, other,
                                           extended["reference_policies"],
                                           extended["reference_formatting"]),
            extended["plan"]["plan_id"])

    def test_markdown_rewriting_is_unchanged_and_other_files_are_untouched(self):
        def markdown_writes(doc: object) -> list[tuple]:
            return [(op["targets"], op["before"], op["after"])
                    for op in doc["changes"] if op["op"] == "write-file"
                    and adopt_links.is_markdown_path(op["targets"][0])]

        with_script = self.answered(referenced_repo(self.home), "extend")
        without = self.ready_plan(referenced_repo(self.home, script=False))
        self.assertEqual(without["plan"]["state"], "ready",
                         without["plan"]["blockers"])
        self.assertEqual(without["path_references"], [])
        self.assertTrue(markdown_writes(without))
        self.assertEqual(markdown_writes(with_script),
                         markdown_writes(without))
        self.assertEqual(with_script["link_rewrites"],
                         without["link_rewrites"])
        self.assertEqual(self.naming(with_script, UNRELATED_SCRIPT), [])
        self.assertEqual(
            [op["targets"] for op in with_script["changes"]
             if op["op"] == "write-file"
             and op["targets"][0].startswith("tools/")], [[CHECK_LINKS]])

    def test_invalid_reference_answers_refuse_and_store_nothing(self):
        root = referenced_repo(self.home)
        ok = ("path-reference", REFERENCE_SUBJECT, "extend")
        for triples, repair_id in (
                ((("path-reference", f"{CHECK_LINKS}:1:1", "retain"),),
                 "adopt.decisions.unmatched_answer"),
                ((("path-reference", REFERENCE_SUBJECT, "rewrite"),),
                 "adopt.decisions.invalid_answer"),
                ((ok, ("path-reference", REFERENCE_SUBJECT, "retain")),
                 "adopt.decisions.invalid_answer"),
                ((ok, ("path-ref", REFERENCE_SUBJECT, "retain")),
                 "adopt.decisions.invalid_answer")):
            with self.subTest(triples=triples):
                before = self.stored_plans()
                code, payload, err = self.plan(root, *[
                    token for triple in triples
                    for token in ("--answer", *triple)])
                self.assertEqual(code, 2, err or payload)
                self.assertEqual(payload["error"]["code"], "adopt_failure")
                self.assertEqual(payload["error"]["repair_id"], repair_id)
                self.assertEqual(
                    payload["error"]["violations"][0]["pointer"],
                    "/decisions/answered")
                self.assertEqual(self.stored_plans(), before)

    def test_the_human_view_prints_the_references(self):
        root = referenced_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), "--format",
                             "human", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nreferences: 1 occurrences, extended 0, rewritten 0, "
                      "retained 0, open 1\n", out)
        self.assertIn(f"\nopen path-reference {REFERENCE_SUBJECT} "
                      "(answers: extend|retain): ", out)
        code, out, err = run("plan", "--repo-root", str(root), "--format",
                             "human", "--answer", "path-reference",
                             REFERENCE_SUBJECT, "extend", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nreferences: 1 occurrences, extended 1, rewritten 0, "
                      "retained 0, open 0\n", out)

    def test_a_reference_to_an_answered_candidate_is_asked_in_either_answer_order(self):
        # Line 1 of the file holds `PATHS = [".claude/odd.md"]`: the quote
        # opens in column 10, so the literal starts in column 11.
        naming_file = "tools/odd_paths.py"
        subject = f"{naming_file}:1:11"
        root = candidate_repo(self.home, ODD)
        write(root, naming_file, f'PATHS = ["{ODD}"]\n')
        commit(root, "name the candidate")
        candidate = ("candidate-class", ODD, "archive-history")
        reference = ("path-reference", subject, "rewrite")

        def questions(doc: object, question_id: str) -> list[dict]:
            return [entry for entry in doc["decisions"]["open"]
                    if entry["id"] == question_id]

        unanswered = self.ready_plan(root)
        self.assertEqual(len(questions(unanswered, "candidate-class")), 1)
        self.assertEqual(questions(unanswered, "path-reference"), [])
        self.assertEqual(unanswered["path_references"], [])

        code, archived, err = self.plan(root, "--answer", *candidate)
        self.assertEqual(code, 0, err or archived)
        self.assertEqual(archived["plan"]["state"], "draft")
        (question,) = questions(archived, "path-reference")
        self.assertEqual(question["subject"], subject)
        self.assertEqual(question["answers"],
                         ["extend", "rewrite", "retain"])
        self.assertEqual(len(archived["decisions"]["open"]), 1)
        (row,) = archived["path_references"]
        self.assertEqual((row["subject"], row["literal"], row["answer"]),
                         (subject, ODD, None))

        results = []
        for triples in ((candidate, reference), (reference, candidate)):
            code, doc, err = self.plan(root, *[
                token for triple in triples
                for token in ("--answer", *triple)])
            self.assertEqual(code, 0, err or doc)
            self.assertEqual(doc["plan"]["state"], "ready",
                             doc["plan"]["blockers"])
            results.append(doc)
        first, second = results
        self.assertEqual(first["path_references"], second["path_references"])
        self.assertEqual(first["path_references"][0]["answer"], "rewrite")
        self.assertEqual(first["plan"]["plan_id"], second["plan"]["plan_id"])
        (write_op,) = self.naming(first, naming_file)
        self.assertEqual(write_op["after"], sha256_hash(
            f'PATHS = ["{ARCHIVED}"]\n'.encode("utf-8")))

    def test_a_reference_target_any_other_operation_names_is_a_derivation_bug(self):
        op = adopt_planning.operation
        target = "tools/check_links.py"
        write_op = op("write-file", [target], [target],
                      "sha256:" + "0" * 64, "sha256:" + "1" * 64)
        adopt_planning.check_reference_writes([write_op], {target})
        delete = op("delete-file", [target], [],
                    "git-object:" + "0" * 40, None)
        move = op("git-mv", [target], ["tools/moved.py"],
                  "git-object:" + "0" * 40, "git-object:" + "0" * 40)
        different = op("write-file", ["tools/other.py"], [target],
                       "sha256:" + "0" * 64, "sha256:" + "1" * 64)
        for changes in ([], [write_op, write_op], [write_op, delete],
                        [write_op, move], [different]):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    adopt_planning.check_reference_writes(changes, {target})

    def test_a_projection_reading_a_reference_target_is_not_a_second_writer(self):
        op = adopt_planning.operation
        target = "tools/agents.tmpl"
        write_op = op("write-file", [target], [target],
                      "sha256:" + "0" * 64, "sha256:" + "1" * 64)
        reads = op("regenerate-projection", [target], ["AGENTS.md"],
                   "sha256:" + "2" * 64, None)
        adopt_planning.check_reference_writes([write_op, reads], {target})
        adopt_planning.check_reference_writes([reads, write_op, reads],
                                              {target})
        regenerates = op("regenerate-projection", ["tools/other.tmpl"],
                         [target], "sha256:" + "0" * 64, None)
        for changes in ([reads], [write_op, regenerates],
                        [write_op, reads, write_op]):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    adopt_planning.check_reference_writes(changes, {target})


class MovedFileReferencePlanTest(AdoptTestCase):
    """#372 D1: a moved file is read, and written where the move leaves it."""

    def repo(self) -> Path:
        root = nix_config_shape_repo(self.home)
        write_moved_tool(root)
        return root

    def test_a_moved_file_is_read_and_its_row_names_the_destination(self):
        doc = self.ready_plan(self.repo())
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(doc["path_references"], [{
            "subject": MOVED_TOOL_SUBJECT, "path": MOVED_TOOL, "line": 1,
            "column": 9, "literal": ".out-of-scope/z.md",
            "answers": ["rewrite", "retain"], "answer": None,
            "additions": [],
            "replacement": ".agents/knowledge/rejections/z.md",
            "target": MOVED_TOOL_NEW, "policy": ".out-of-scope:.py",
            "decided_by": None}])
        self.assertEqual(
            [op["op"] for op in doc["changes"]
             if MOVED_TOOL_NEW in op["targets"]], ["git-mv"])

    def test_an_answered_moved_file_is_written_once_at_its_destination(self):
        code, doc, err = self.plan(self.repo(), "--answer", "path-reference",
                                   MOVED_TOOL_SUBJECT, "rewrite")
        self.assertEqual(code, 0, err or doc)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        (row,) = doc["path_references"]
        self.assertEqual((row["answer"], row["decided_by"]),
                         ("rewrite", "occurrence"))
        move, write_op = [op for op in doc["changes"]
                          if MOVED_TOOL_NEW in op["sources"] + op["targets"]]
        self.assertEqual((move["op"], move["sources"], move["targets"]),
                         ("git-mv", [MOVED_TOOL], [MOVED_TOOL_NEW]))
        self.assertEqual(
            (write_op["op"], write_op["sources"], write_op["targets"]),
            ("write-file", [MOVED_TOOL_NEW], [MOVED_TOOL_NEW]))
        self.assertEqual(write_op["before"],
                         sha256_hash(MOVED_TOOL_TEXT.encode("utf-8")))
        self.assertEqual(write_op["after"],
                         sha256_hash(MOVED_TOOL_AFTER.encode("utf-8")))
        self.assertEqual(
            [op["op"] for op in doc["changes"]
             if MOVED_TOOL in op["sources"] + op["targets"]], ["git-mv"])
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_a_reference_target_may_be_one_move_destination(self):
        op = adopt_planning.operation
        blob = "git-object:" + "0" * 40
        write_op = op("write-file", [MOVED_TOOL_NEW], [MOVED_TOOL_NEW],
                      "sha256:" + "0" * 64, "sha256:" + "1" * 64)
        move = op("git-mv", [MOVED_TOOL], [MOVED_TOOL_NEW], blob, blob)
        adopt_planning.check_reference_writes([move, write_op],
                                              {MOVED_TOOL_NEW})
        second = op("git-mv", ["tools/other.py"], [MOVED_TOOL_NEW], blob,
                    blob)
        away = op("git-mv", [MOVED_TOOL_NEW], ["tools/moved.py"], blob, blob)
        for changes in ([move], [move, write_op, write_op],
                        [move, second, write_op], [move, write_op, away]):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    adopt_planning.check_reference_writes(
                        changes, {MOVED_TOOL_NEW})


class ReferencePolicyPlanTest(AdoptTestCase):
    """#372: one answer per (moved tree, file class), overridable per
    occurrence, reported before `ready`."""

    def answered(self, root: Path, *triples: tuple[str, str, str]) -> object:
        code, doc, err = self.plan(root, *answer_args(*triples))
        self.assertEqual(code, 0, err or doc)
        return doc

    def opened(self, doc: object) -> list[tuple[str, str]]:
        return [(entry["id"], entry["subject"])
                for entry in doc["decisions"]["open"]]

    def decided(self, doc: object) -> list[tuple]:
        return [(row["subject"], row["answer"], row["decided_by"])
                for row in doc["path_references"]]

    def code_writes(self, doc: object) -> dict[str, dict]:
        """The non-Markdown `write-file` operations under the moved study
        tree and `tools/`, by target."""
        return {op["targets"][0]: op for op in doc["changes"]
                if op["op"] == "write-file"
                and op["targets"][0].startswith((POLICY_NEW, "tools/"))
                and not adopt_links.is_markdown_path(op["targets"][0])}

    def stored_plans(self) -> list[str]:
        store = self.home / ".agents" / "state" / "adopt" / "plans"
        return sorted(path.name for path in store.iterdir()) \
            if store.is_dir() else []

    def makefile_repo(self) -> Path:
        root = nix_config_shape_repo(self.home)
        write(root, MAKEFILE, MAKEFILE_TEXT)
        write(root, POLICY_HINT, "# hint h\n")
        commit(root, "add a file of no known class to a moved tree")
        return root

    def test_moved_files_open_one_question_per_class(self):
        doc = self.ready_plan(policy_repo(self.home))
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            [gate["id"] for gate in doc["verification"]["ready_gates"]
             if gate["status"] != "passed"], ["no-open-decisions"])
        self.assertEqual(self.opened(doc), [
            ("path-reference", LINT_SUBJECT), ("path-reference", RUN_SUBJECT),
            ("reference-policy", JSON_POLICY),
            ("reference-policy", NIX_POLICY),
            ("reference-policy", PY_POLICY)])
        policies = [entry for entry in doc["decisions"]["open"]
                    if entry["id"] == "reference-policy"]
        for entry in policies:
            self.assertEqual(sorted(entry), [
                "answers", "basis", "id", "impact", "recommendation",
                "subject", "value"])
            self.assertEqual(entry["answers"], ["rewrite", "retain"])
            for member in ("basis", "impact", "recommendation"):
                self.assertNotIn(".out-of-scope", entry[member])
                self.assertEqual(entry[member], policies[0][member])
        self.assertEqual([entry["value"] for entry in policies],
                         ["retain", "rewrite", "rewrite"])
        self.assertEqual(
            [(row["subject"], row["answers"], row["target"], row["policy"])
             for row in doc["path_references"]], POLICY_ROWS)
        self.assertEqual(self.decided(doc),
                         [(subject, None, None)
                          for subject, _, _, _ in POLICY_ROWS])
        lint = doc["path_references"][5]
        self.assertEqual(
            (lint["literal"], lint["additions"], lint["replacement"]),
            (r"^\\.claude/", [r"^\\.agents/knowledge/hints/"], None))
        self.assertEqual(doc["reference_policies"], [
            policy_row(JSON_POLICY, "retain", 1, 1),
            policy_row(NIX_POLICY, "rewrite", 1, 1),
            policy_row(PY_POLICY, "rewrite", 2, 3)])
        self.assertEqual(self.code_writes(doc), {})
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_one_policy_answer_decides_both_scripts(self):
        doc = self.answered(policy_repo(self.home),
                            ("reference-policy", PY_POLICY, "rewrite"))
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(self.opened(doc), [
            ("path-reference", LINT_SUBJECT), ("path-reference", RUN_SUBJECT),
            ("reference-policy", JSON_POLICY),
            ("reference-policy", NIX_POLICY)])
        self.assertEqual(
            [(subject, answer, by) for subject, answer, by
             in self.decided(doc) if subject.endswith(
                 ("paths.py:1:10", "paths.py:2:9", "report.py:3:11"))],
            [(f"{POLICY_DIR}/paths.py:1:10", "rewrite", "policy"),
             (f"{POLICY_DIR}/paths.py:2:9", "rewrite", "policy"),
             (f"{POLICY_DIR}/report.py:3:11", "rewrite", "policy")])
        self.assertEqual(doc["reference_policies"][2], policy_row(
            PY_POLICY, "rewrite", 2, 3, answer="rewrite", rewritten=3,
            open=0))

    def test_answering_every_policy_and_outside_occurrence_reaches_ready(self):
        doc = self.answered(policy_repo(self.home), *POLICY_READY_ANSWERS)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertEqual(
            doc["decisions"]["answered"],
            [{"id": question, "subject": subject, "value": value}
             for question, subject, value in sorted(POLICY_READY_ANSWERS)])
        self.assertEqual(self.decided(doc), [
            (f"{POLICY_DIR}/devenv.nix:3:21", "rewrite", "policy"),
            (f"{POLICY_DIR}/paths.py:1:10", "rewrite", "policy"),
            (f"{POLICY_DIR}/paths.py:2:9", "rewrite", "policy"),
            (f"{POLICY_DIR}/record.json:1:31", "retain", "policy"),
            (f"{POLICY_DIR}/report.py:3:11", "rewrite", "policy"),
            (LINT_SUBJECT, "extend", "occurrence"),
            (RUN_SUBJECT, "rewrite", "occurrence")])
        writes = self.code_writes(doc)
        self.assertEqual(sorted(writes), sorted(POLICY_REWRITTEN))
        for target, text in POLICY_REWRITTEN.items():
            with self.subTest(target=target):
                op = writes[target]
                self.assertEqual(op["sources"], [target])
                self.assertEqual(op["after"],
                                 sha256_hash(text.encode("utf-8")))
        order = [(op["op"], op["targets"][0] if op["targets"] else None)
                 for op in doc["changes"]]
        report = f"{POLICY_NEW}/report.py"
        self.assertLess(order.index(("git-mv", report)),
                        order.index(("write-file", report)))
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_an_occurrence_answer_overrides_its_policy(self):
        override = f"{POLICY_DIR}/paths.py:2:9"
        doc = self.answered(
            policy_repo(self.home), *POLICY_READY_ANSWERS,
            ("path-reference", override, "retain"))
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(
            [(subject, answer, by) for subject, answer, by
             in self.decided(doc) if answer == "rewrite"],
            [(f"{POLICY_DIR}/devenv.nix:3:21", "rewrite", "policy"),
             (f"{POLICY_DIR}/paths.py:1:10", "rewrite", "policy"),
             (f"{POLICY_DIR}/report.py:3:11", "rewrite", "policy"),
             (RUN_SUBJECT, "rewrite", "occurrence")])
        self.assertIn((override, "retain", "occurrence"), self.decided(doc))
        self.assertIn((f"{POLICY_DIR}/record.json:1:31", "retain", "policy"),
                      self.decided(doc))
        self.assertEqual(doc["reference_policies"], [
            policy_row(JSON_POLICY, "retain", 1, 1, answer="retain",
                       retained=1, open=0),
            policy_row(NIX_POLICY, "rewrite", 1, 1, answer="rewrite",
                       rewritten=1, open=0),
            policy_row(PY_POLICY, "rewrite", 2, 3, answer="rewrite",
                       rewritten=2, retained=1, open=0, overridden=1)])
        writes = self.code_writes(doc)
        self.assertEqual(sorted(writes), sorted(POLICY_REWRITTEN))
        self.assertEqual(
            writes[f"{POLICY_NEW}/paths.py"]["after"], sha256_hash((
                'TREES = ".agents/knowledge/rejections"\n'
                'PLAN = ".out-of-scope/z.md"\n').encode("utf-8")))

    def test_markdown_rewriting_is_unchanged(self):
        def markdown_writes(doc: object) -> list[tuple]:
            return [(op["targets"], op["before"], op["after"])
                    for op in doc["changes"] if op["op"] == "write-file"
                    and adopt_links.is_markdown_path(op["targets"][0])]

        with_code = self.answered(policy_repo(self.home),
                                  *POLICY_READY_ANSWERS)
        without = self.ready_plan(policy_repo(self.home, code=False))
        self.assertEqual(without["path_references"], [])
        self.assertEqual(without["reference_policies"], [])
        self.assertTrue(markdown_writes(without))
        self.assertEqual(markdown_writes(with_code), markdown_writes(without))
        self.assertEqual(with_code["link_rewrites"], without["link_rewrites"])

    def test_the_policy_answer_is_covered_by_the_plan_id(self):
        root = policy_repo(self.home)
        others = [triple for triple in POLICY_READY_ANSWERS
                  if triple[1] != PY_POLICY]
        rewritten = self.answered(root, *POLICY_READY_ANSWERS)
        retained = self.answered(
            root, *others, ("reference-policy", PY_POLICY, "retain"))
        self.assertEqual(retained["plan"]["state"], "ready",
                         retained["plan"]["blockers"])
        self.assertNotEqual(rewritten["plan"]["plan_id"],
                            retained["plan"]["plan_id"])
        inputs = (rewritten["plan"]["project_id"],
                  rewritten["plan"]["base_revision"],
                  rewritten["plan"]["platform"], rewritten["evidence"],
                  rewritten["decisions"]["answered"],
                  rewritten["link_rewrites"], rewritten["path_references"])
        self.assertEqual(
            adopt_planning.compute_plan_id(
                *inputs, rewritten["reference_policies"],
                rewritten["reference_formatting"]),
            rewritten["plan"]["plan_id"])
        other = [dict(row) for row in rewritten["reference_policies"]]
        other[2]["rewritable"] += 1
        self.assertNotEqual(
            adopt_planning.compute_plan_id(
                *inputs, other, rewritten["reference_formatting"]),
            rewritten["plan"]["plan_id"])

    def test_invalid_policy_answers_refuse_and_store_nothing(self):
        root = policy_repo(self.home)
        ok = ("reference-policy", PY_POLICY, "rewrite")
        for triples, repair_id in (
                ((("reference-policy", ".out-of-scope:.md", "retain"),),
                 "adopt.decisions.unmatched_answer"),
                ((("reference-policy", ".claude/specs:.py", "retain"),),
                 "adopt.decisions.unmatched_answer"),
                ((("reference-policy", RUN_SUBJECT, "retain"),),
                 "adopt.decisions.unmatched_answer"),
                ((("reference-policy", PY_POLICY, "extend"),),
                 "adopt.decisions.invalid_answer"),
                ((ok, ("reference-policy", PY_POLICY, "retain")),
                 "adopt.decisions.invalid_answer"),
                ((ok, ("reference-policies", PY_POLICY, "retain")),
                 "adopt.decisions.invalid_answer")):
            with self.subTest(triples=triples):
                before = self.stored_plans()
                code, payload, err = self.plan(root, *answer_args(*triples))
                self.assertEqual(code, 2, err or payload)
                self.assertEqual(payload["error"]["code"], "adopt_failure")
                self.assertEqual(payload["error"]["repair_id"], repair_id)
                self.assertEqual(
                    payload["error"]["violations"][0]["pointer"],
                    "/decisions/answered")
                self.assertEqual(self.stored_plans(), before)

    def test_a_class_outside_the_table_keeps_what_it_cannot_rewrite_open(self):
        root = self.makefile_repo()
        policy = ".out-of-scope:-"
        skip = f"{MAKEFILE}:1:10"
        doc = self.ready_plan(root)
        self.assertEqual(self.opened(doc), [("reference-policy", policy)])
        self.assertIsNone(doc["decisions"]["open"][0]["value"])
        self.assertEqual(doc["reference_policies"],
                         [policy_row(policy, None, 1, 2, rewritable=1)])
        answered = self.answered(root, ("reference-policy", policy,
                                        "rewrite"))
        self.assertEqual(answered["plan"]["state"], "draft")
        self.assertEqual(self.opened(answered), [("path-reference", skip)])
        self.assertEqual(self.decided(answered), [
            (skip, None, None), (f"{MAKEFILE}:2:9", "rewrite", "policy")])
        self.assertEqual(answered["reference_policies"], [policy_row(
            policy, None, 1, 2, rewritable=1, answer="rewrite", rewritten=1,
            open=1)])
        both = self.answered(root, ("reference-policy", policy, "rewrite"),
                             ("path-reference", skip, "extend"))
        self.assertEqual(both["plan"]["state"], "ready",
                         both["plan"]["blockers"])
        self.assertEqual(both["reference_policies"], [policy_row(
            policy, None, 1, 2, rewritable=1, answer="rewrite", rewritten=1,
            extended=1, open=0, overridden=1)])
        (write_op,) = [op for op in both["changes"]
                       if op["op"] == "write-file"
                       and op["targets"] == [MAKEFILE_NEW]]
        self.assertEqual(write_op["after"],
                         sha256_hash(MAKEFILE_AFTER.encode("utf-8")))
        only = self.answered(root, ("path-reference", skip, "extend"),
                             ("path-reference", f"{MAKEFILE}:2:9", "retain"))
        self.assertEqual(only["plan"]["state"], "ready",
                         only["plan"]["blockers"])
        self.assertEqual(only["reference_policies"], [policy_row(
            policy, None, 1, 2, rewritable=1, retained=1, extended=1,
            open=0, overridden=2)])

    def test_the_human_view_prints_each_policy(self):
        root = policy_repo(self.home)
        code, out, err = run("plan", "--repo-root", str(root), "--format",
                             "human", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nreferences: 7 occurrences, extended 0, rewritten 0, "
                      "retained 0, open 7\n", out)
        self.assertIn(f"\npolicy {PY_POLICY}: 2 files, 3 occurrences, "
                      "rewritable 3, rewritten 0, retained 0, extended 0, "
                      "open 3\n", out)
        self.assertIn(f"\nopen reference-policy {JSON_POLICY} "
                      "(answers: rewrite|retain, recommended: retain): ", out)
        self.assertNotIn(f"open path-reference {POLICY_DIR}", out)
        code, out, err = run("plan", "--repo-root", str(root), "--format",
                             "human", *answer_args(*POLICY_READY_ANSWERS),
                             home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn(f"\npolicy {PY_POLICY}: 2 files, 3 occurrences, "
                      "rewritable 3, rewritten 3, retained 0, extended 0, "
                      "open 0\n", out)
        self.assertNotIn("open reference-policy", out)
        code, out, err = run("plan", "--repo-root", str(self.makefile_repo()),
                             "--format", "human", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nopen reference-policy .out-of-scope:- "
                      "(answers: rewrite|retain, recommended: none): ", out)


class VariablePolicyPlanTest(AdoptTestCase):
    """#376 D7, D8, D10: variable-joined paths in shell files are asked
    about under their own policy, never with `extend`."""

    def answered(self, root: Path, *triples: tuple[str, str, str]) -> object:
        code, doc, err = self.plan(root, *answer_args(*triples))
        self.assertEqual(code, 0, err or doc)
        return doc

    def variable_repo(self, suffix: str = ".sh") -> Path:
        root = nix_config_shape_repo(self.home)
        write_variable_tree(root, suffix)
        return root

    def opened(self, doc: object) -> list[tuple]:
        return [(entry["id"], entry["subject"], entry.get("value"))
                for entry in doc["decisions"]["open"]]

    def test_variable_paths_open_their_own_policy(self):
        doc = self.answered(self.variable_repo())
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            [(row["subject"], row["answers"], row["replacement"],
              row["target"], row["policy"]) for row in doc["path_references"]],
            [(JOBS_LITERAL, ["rewrite", "retain"], f"{JOBS_NEW}/data.txt",
              f"{JOBS_NEW}/run.sh", SH_POLICY),
             (JOBS_VARIABLE, ["rewrite", "retain"],
              f"$root/{JOBS_NEW}/data.txt", f"{JOBS_NEW}/run.sh",
              SH_VARIABLE_POLICY),
             (COLLECT_SUBJECT, ["rewrite", "retain"],
              f"${{ROOT}}/{JOBS_NEW}/data.txt", f"{COLLECT}.sh", None)])
        self.assertEqual(self.opened(doc), [
            ("path-reference", COLLECT_SUBJECT, None),
            ("reference-policy", SH_POLICY, "rewrite"),
            ("reference-policy", SH_VARIABLE_POLICY, None)])
        self.assertEqual(doc["reference_policies"], [
            policy_row(SH_POLICY, "rewrite", 1, 1),
            policy_row(SH_VARIABLE_POLICY, None, 1, 1)])

    def test_the_literal_policy_never_decides_a_variable_occurrence(self):
        doc = self.answered(self.variable_repo(),
                            ("reference-policy", SH_POLICY, "rewrite"))
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(self.opened(doc), [
            ("path-reference", COLLECT_SUBJECT, None),
            ("reference-policy", SH_VARIABLE_POLICY, None)])
        self.assertEqual(
            [(row["subject"], row["answer"], row["decided_by"])
             for row in doc["path_references"]],
            [(JOBS_LITERAL, "rewrite", "policy"), (JOBS_VARIABLE, None, None),
             (COLLECT_SUBJECT, None, None)])

    def test_every_answer_reaches_ready_with_one_write_per_script(self):
        doc = self.answered(self.variable_repo(), *VARIABLE_REWRITE_ANSWERS)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        code = variable_code()
        for target, text in (
                (f"{JOBS_NEW}/run.sh",
                 code[JOBS_SCRIPT].replace(JOBS_DIR, JOBS_NEW)),
                (f"{COLLECT}.sh",
                 code[f"{COLLECT}.sh"].replace(JOBS_DIR, JOBS_NEW))):
            with self.subTest(target=target):
                (op,) = [op for op in doc["changes"]
                         if op["op"] == "write-file"
                         and op["targets"] == [target]]
                self.assertEqual(op["after"],
                                 sha256_hash(text.encode("utf-8")))

    def test_a_non_shell_class_reads_no_variable(self):
        doc = self.answered(self.variable_repo(".py"))
        self.assertEqual(
            [(row["subject"], row["policy"])
             for row in doc["path_references"]],
            [(f"{JOBS_DIR}/run.py:3:6", ".out-of-scope:.py")])


class DepthPolicyPlanTest(AdoptTestCase):
    """#380 AC1, AC2: climbs out of a moved tree are asked about under the
    `<tree>:<class>/depth` policies, with no recommendation."""

    def test_climbs_to_the_root_open_their_own_policies(self):
        root = nix_config_shape_repo(self.home)
        write_depth_tree(root)
        code, doc, err = self.plan(root)
        self.assertEqual(code, 0, err or doc)
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            [(row["subject"], row["literal"], row["replacement"],
              row["policy"], row["answers"])
             for row in doc["path_references"]],
            [(*row, ["rewrite", "retain"]) for row in DEPTH_ROWS])
        self.assertEqual(
            [(entry["id"], entry["subject"], entry["value"])
             for entry in doc["decisions"]["open"]],
            [("reference-policy", subject, None)
             for subject in DEPTH_POLICIES])
        self.assertEqual(doc["reference_policies"],
                         [policy_row(subject, None, 1, 1)
                          for subject in DEPTH_POLICIES])

    def test_answering_the_depth_policies_reaches_ready(self):
        root = nix_config_shape_repo(self.home)
        write_depth_tree(root)
        code, doc, err = self.plan(root, *answer_args(*DEPTH_REWRITE_ANSWERS))
        self.assertEqual(code, 0, err or doc)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(
            [(row["subject"], row["answer"], row["decided_by"])
             for row in doc["path_references"]],
            [(row[0], "rewrite", "policy") for row in DEPTH_ROWS])
        self.assertEqual(
            [(row["class"], row["files"])
             for row in doc["reference_formatting"]],
            [(".lock", [f"{DEPTH_NEW}/uv.lock"]),
             (".py", [f"{DEPTH_NEW}/run.py"]),
             (".toml", [f"{DEPTH_NEW}/pyproject.toml"])])


# What `POLICY_READY_ANSWERS` edits, by class, before any format answer.
FORMAT_ROWS = [
    {"class": ".nix", "command": None,
     "files": [f"{POLICY_NEW}/devenv.nix"]},
    {"class": ".py", "command": None,
     "files": [f"{POLICY_NEW}/paths.py", f"{POLICY_NEW}/report.py",
               RUN_REPORT]},
    {"class": ".toml", "command": None, "files": [LINT_TOML]},
]


class ReferenceFormattingPlanTest(AdoptTestCase):
    """#376 D2, D3, D11: a formatter is declared per edited class by an
    answer, never asked for, and published in `reference_formatting`."""

    def answered(self, root: Path, *triples: tuple[str, str, str]) -> object:
        code, doc, err = self.plan(root, *answer_args(*triples))
        self.assertEqual(code, 0, err or doc)
        return doc

    def command(self, root: Path) -> str:
        """A command id the fixture's contract declares; `plan` never runs
        it, and any declared id is accepted (D2)."""
        contract = json.loads(
            (root / ".agents" / "project.json").read_text("utf-8"))
        return sorted(contract["bindings"]["commands"])[0]

    def stored_plans(self) -> list[str]:
        store = self.home / ".agents" / "state" / "adopt" / "plans"
        return sorted(path.name for path in store.iterdir()) \
            if store.is_dir() else []

    def test_rows_list_every_edited_class_without_a_command(self):
        self.assertEqual(
            self.answered(nix_config_shape_repo(self.home))
            ["reference_formatting"], [])
        doc = self.answered(policy_repo(self.home), *POLICY_READY_ANSWERS)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["reference_formatting"], FORMAT_ROWS)

    def test_a_format_answer_names_the_command_and_changes_the_id(self):
        root = policy_repo(self.home)
        command = self.command(root)
        without = self.answered(root, *POLICY_READY_ANSWERS)
        doc = self.answered(root, *POLICY_READY_ANSWERS,
                            ("reference-format", ".py", command))
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertIn(
            {"id": "reference-format", "subject": ".py", "value": command},
            doc["decisions"]["answered"])
        self.assertEqual(doc["reference_formatting"], [
            FORMAT_ROWS[0], {**FORMAT_ROWS[1], "command": command},
            FORMAT_ROWS[2]])
        self.assertNotEqual(doc["plan"]["plan_id"],
                            without["plan"]["plan_id"])
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

        def code_writes(document: object) -> dict[str, str]:
            return {op["targets"][0]: op["after"]
                    for op in document["changes"]
                    if op["op"] == "write-file"
                    and op["targets"][0].startswith((POLICY_NEW, "tools/"))}
        self.assertEqual(code_writes(doc), code_writes(without))

    def test_compute_plan_id_covers_the_rows(self):
        root = policy_repo(self.home)
        doc = self.answered(root, *POLICY_READY_ANSWERS,
                            ("reference-format", ".py", self.command(root)))
        inputs = (doc["plan"]["project_id"], doc["plan"]["base_revision"],
                  doc["plan"]["platform"], doc["evidence"],
                  doc["decisions"]["answered"], doc["link_rewrites"],
                  doc["path_references"], doc["reference_policies"])
        self.assertEqual(
            adopt_planning.compute_plan_id(*inputs,
                                           doc["reference_formatting"]),
            doc["plan"]["plan_id"])
        other = json.loads(json.dumps(doc["reference_formatting"]))
        other[1]["files"] = other[1]["files"][:-1]
        self.assertNotEqual(adopt_planning.compute_plan_id(*inputs, other),
                            doc["plan"]["plan_id"])

    def test_invalid_format_answers_refuse_and_store_nothing(self):
        root = policy_repo(self.home)
        command = self.command(root)
        no_python_edit = tuple(
            triple for triple in POLICY_READY_ANSWERS
            if triple[1] not in (PY_POLICY, RUN_SUBJECT)) + (
            ("reference-policy", PY_POLICY, "retain"),
            ("path-reference", RUN_SUBJECT, "retain"))
        unmatched = "adopt.decisions.unmatched_answer"
        invalid = "adopt.decisions.invalid_answer"
        for triples, repair_id in (
                ((*POLICY_READY_ANSWERS,
                  ("reference-format", ".md", command)), unmatched),
                ((*POLICY_READY_ANSWERS,
                  ("reference-format", ".json", command)), unmatched),
                ((*no_python_edit,
                  ("reference-format", ".py", command)), unmatched),
                ((*POLICY_READY_ANSWERS,
                  ("reference-format", ".py", "no-such-command")), invalid),
                ((*POLICY_READY_ANSWERS,
                  ("reference-format", ".py", command),
                  ("reference-format", ".py", "zz-other")), invalid),
                # Validated after the other ids, though it sorts first: the
                # format answer alone is unmatched, the policy one invalid.
                ((("reference-policy", PY_POLICY, "extend"),
                  ("reference-format", ".md", command)),
                 invalid)):
            with self.subTest(triples=triples):
                before = self.stored_plans()
                code, payload, err = self.plan(root, *answer_args(*triples))
                self.assertEqual(code, 2, err or payload)
                self.assertEqual(payload["error"]["code"], "adopt_failure")
                self.assertEqual(payload["error"]["repair_id"], repair_id)
                self.assertEqual(
                    payload["error"]["violations"][0]["pointer"],
                    "/decisions/answered")
                self.assertEqual(self.stored_plans(), before)

    def test_the_human_view_prints_each_format_row(self):
        root = policy_repo(self.home)
        command = self.command(root)
        code, out, err = run(
            "plan", "--repo-root", str(root), "--format", "human",
            *answer_args(*POLICY_READY_ANSWERS,
                         ("reference-format", ".py", command)),
            home=self.home)
        self.assertEqual(code, 0, err)
        for line in ("format .nix: 1 files, command none",
                     f"format .py: 3 files, command {command}",
                     "format .toml: 1 files, command none"):
            with self.subTest(line=line):
                self.assertIn(f"\n{line}\n", out)
        self.assertLess(out.rindex("\npolicy "), out.index("\nformat "))


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


class RefusalTest(AdoptTestCase):
    def test_a_plain_directory_is_not_a_repository(self):
        plain = Path(tempfile.mkdtemp()).resolve()
        code, doc, err = self.plan(plain)
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["code"], "not_a_repository")
        self.assertEqual(sorted(doc["error"]),
                         ["code", "repair_id", "violations"])
        self.assertTrue(doc["error"]["violations"])

    def test_an_absent_directory_is_not_a_repository(self):
        missing = Path(tempfile.mkdtemp()).resolve() / "absent"
        code, doc, err = self.plan(missing)
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["code"], "not_a_repository")

    def test_violations_are_sorted_by_pointer(self):
        code, doc, _ = self.plan(Path(tempfile.mkdtemp()).resolve())
        self.assertEqual(code, 2)
        pointers = [v["pointer"] for v in doc["error"]["violations"]]
        self.assertEqual(pointers, sorted(pointers))

    def test_a_broken_manifest_is_adopt_failure_not_resolver_failure(self):
        home = make_home("{ not json")
        code, doc, err = self.plan(bootstrap_repo(self.home), home=home)
        self.assertEqual(code, 2, err)
        self.assertEqual(doc["error"]["code"], "adopt_failure")
        self.assertEqual(doc["error"]["repair_id"], "adopt.manifest.invalid")

    def test_an_unknown_subcommand_is_an_argparse_usage_error(self):
        code, out, _ = run_child("register", "--plan-id", "x", home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_the_parser_exposes_the_five_verbs_and_nothing_else(self):
        code, out, err = run("--help", home=self.home)
        self.assertEqual(code, 0, err)
        choices = re.search(r"usage: adopt-project \[-h\] \{([^}]*)\}", out)
        self.assertEqual(choices.group(1), "plan,apply,discard,verify,migrate")


if __name__ == "__main__":
    unittest.main()
