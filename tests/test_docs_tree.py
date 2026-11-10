import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = "58908955a256f53b09ff27702d3e9847ba030708"
SOURCES = (
    "python/README.md",
    "home/common/claude-code/README.md",
    "home/common/agent-skills/README.md",
)
SECTION_MAP_REL = "docs/archive/readme-section-map.md"
SECTION_MAP = REPO_ROOT / SECTION_MAP_REL
KINDS = frozenset({"contract", "decision", "evidence", "how-to", "overview", "superseded"})
ADR_PATH_RE = re.compile(r"docs/areas/[a-z0-9-]+/adr/\d{3}-[a-z0-9-]+\.md")
# The [E] and [l] classes match the same text as the letters; they keep this
# line from matching its own pattern, so a grep for the phrases skips this file.
ROUTING_RE = re.compile(r"python/READM[E].*goes there|new detai[l][^.;]*python/README|home is python/READM[E]")
SECTION_CITE_RE = re.compile(r"python/README\.md\S*\s*§")

# The audited (source, section, kind) classification of every README section
# this issue moves text out of; each task adds exactly the triples of its rows.
AUDITED: frozenset[tuple[str, str, str]] = frozenset({
    ("python/README.md", "`verified-tree`", "contract"),
    ("python/README.md", "`verified-tree`", "decision"),
    ("python/README.md", "verify-pending", "contract"),
    ("python/README.md", "verify-pending", "decision"),
    ("python/README.md", "forge-claim", "contract"),
    ("python/README.md", "forge-claim", "decision"),
    ("python/README.md", "forge-claim land", "contract"),
    ("python/README.md", "forge-claim land", "decision"),
    ("python/README.md", "forge-claim owner-action", "contract"),
    ("python/README.md", "forge-claim owner-action", "decision"),
    ("python/README.md", "forge-issue", "contract"),
    ("python/README.md", "forge-issue", "decision"),
    ("python/README.md", "owner-actions", "contract"),
    ("python/README.md", "owner-actions", "decision"),
    ("python/README.md", "Transaction core", "contract"),
    ("python/README.md", "Transaction core", "superseded"),
    ("python/README.md", "Transaction core", "decision"),
    ("python/README.md", "Release profiles", "contract"),
    ("python/README.md", "Release profiles", "decision"),
    ("python/README.md", "Release adapters", "contract"),
    ("python/README.md", "Release adapters", "decision"),
    ("python/README.md", "Release driver", "contract"),
    ("python/README.md", "Release driver", "decision"),
    ("python/README.md", "adopt-project", "contract"),
    ("python/README.md", "adopt-project", "decision"),
    ("python/README.md", "Platform deprecations", "contract"),
    ("python/README.md", "Platform deprecations", "decision"),
    ("python/README.md", "Platform deprecations", "how-to"),
    ("python/README.md", "Project schema 2", "contract"),
    ("python/README.md", "Project schema 2", "decision"),
    ("python/README.md", "fallback-audit", "contract"),
    ("home/common/claude-code/README.md", "Allow surface and lifecycle guard", "contract"),
    ("home/common/claude-code/README.md", "Detaching words", "contract"),
    ("home/common/claude-code/README.md", "Detaching words", "decision"),
    ("home/common/claude-code/README.md", "Transmitting git invocations", "contract"),
    ("home/common/claude-code/README.md", "Transmitting git invocations", "decision"),
    ("home/common/claude-code/README.md", "Adjudicated verbs", "contract"),
    ("home/common/claude-code/README.md", "Adjudicated verbs", "decision"),
    ("home/common/claude-code/README.md", "Pre-push hook", "contract"),
    ("home/common/claude-code/README.md", "Pre-push hook", "decision"),
    ("home/common/claude-code/README.md", "The raise label", "contract"),
    ("home/common/claude-code/README.md", "The raise label", "decision"),
    ("home/common/claude-code/README.md", "Guard policy", "contract"),
    ("home/common/claude-code/README.md", "Guard policy", "decision"),
    ("home/common/claude-code/README.md", "Guard policy", "evidence"),
    ("home/common/claude-code/README.md", "Guard policy", "how-to"),
    ("home/common/claude-code/README.md", "Guard/core decision", "decision"),
    ("python/README.md", "guard-policy", "contract"),
    ("python/README.md", "guard-policy", "decision"),
    ("python/README.md", "`cache-proxy`", "contract"),
    ("python/README.md", "`cache-proxy`", "decision"),
    ("home/common/claude-code/README.md", "Cache proxy", "decision"),
    ("home/common/claude-code/README.md", "Accounts", "decision"),
    ("home/common/claude-code/README.md", "Plugins", "decision"),
    ("python/README.md", "Package and launchers", "overview"),
    ("python/README.md", "Package and launchers", "decision"),
    ("python/README.md", "artifact-budget", "contract"),
    ("python/README.md", "issue-branch", "contract"),
    ("python/README.md", "`lane-triage`", "contract"),
    ("python/README.md", "`lane-triage`", "decision"),
    ("python/README.md", "`agent-workflow-tests` runner", "contract"),
    ("python/README.md", "`agent-workflow-tests` runner", "decision"),
    ("python/README.md", "`agent-workflow-tests` runner", "evidence"),
    ("python/README.md", "agent-run-profile", "contract"),
    ("home/common/agent-skills/README.md", "Global guidance and skill sources", "decision"),
    ("home/common/agent-skills/README.md", "Claude-only skills", "decision"),
    ("home/common/agent-skills/README.md", "Vendored skills", "decision"),
    ("home/common/agent-skills/README.md", "Code map", "decision"),
    ("home/common/agent-skills/README.md", "Host admission", "contract"),
})

# The base sections no text leaves.
KEPT: frozenset[tuple[str, str]] = frozenset({
    ("home/common/claude-code/README.md", "Settings"),
    ("home/common/claude-code/README.md", "Editing the codex-plugin-cc patch"),
    ("home/common/agent-skills/README.md", "The `bindings.paths.hints` binding"),
    ("home/common/agent-skills/README.md", "Onboarding a new project"),
    ("home/common/agent-skills/README.md", "Impeccable"),
    ("home/common/agent-skills/README.md", "Retired skills"),
    ("home/common/agent-skills/README.md", ".superpowers paths"),
})

Row = tuple[str, str, str, tuple[str, ...]]

_HEADING_RE = re.compile(r"^#{2,4} (.*)$")
_SEPARATOR = "|---|---|---|---|"


def headings(text: str) -> list[str]:
    found: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = _HEADING_RE.match(line)
        if match:
            found.append(match.group(1).rstrip())
    return found


def base_text(source: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{BASE}:{source}"],
        check=True, capture_output=True, text=True,
    ).stdout


def tracked_text(exclude: tuple[str, ...]) -> list[tuple[str, list[str]]]:
    listing = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        check=True, capture_output=True,
    ).stdout.decode("utf-8")
    found: list[tuple[str, list[str]]] = []
    for path in listing.split("\0"):
        if not path or path.startswith(exclude):
            continue
        full = REPO_ROOT / path
        if full.is_symlink() or not full.is_file():
            continue
        try:
            text = full.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        found.append((path, text.splitlines()))
    return found


def parse_section_map(text: str) -> tuple[list[Row], list[str]]:
    rows: list[Row] = []
    problems: list[str] = []
    in_table = False
    for number, line in enumerate(text.splitlines(), start=1):
        if not in_table:
            in_table = line.strip() == _SEPARATOR
            continue
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            problems.append(f"section map line {number}: expected 4 cells, got {len(cells)}")
            continue
        source, section, kind, destination = cells
        rows.append((
            source.replace("`", ""), section, kind,
            tuple(re.findall(r"`([^`]+)`", destination)),
        ))
    return rows, problems


def destination_exists(path: str, root: Path = REPO_ROOT) -> bool:
    if (root / path).exists():
        return True
    last = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%H", "--", SECTION_MAP_REL],
        capture_output=True, text=True,
    ).stdout.strip()
    if not last:
        return False
    return subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{last}:{path}"],
        capture_output=True,
    ).returncode == 0


def _is_allowed_home(kind: str, path: str) -> bool:
    if kind in ("decision", "superseded"):
        return bool(ADR_PATH_RE.fullmatch(path)) or path.startswith("docs/archive/")
    if kind == "evidence":
        return path.startswith(("docs/archive/", "docs/spikes/"))
    if kind == "how-to":
        return path.startswith("docs/guides/")
    if kind == "contract":
        return path.endswith((".py", ".nix"))
    if kind == "overview":
        return path == "python/README.md"
    return False


def section_map_problems(
    rows: list[Row],
    audited: frozenset[tuple[str, str, str]],
    base_headings: dict[str, list[str]],
    exists: Callable[[str], bool],
) -> list[str]:
    problems: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for source, section, kind, destinations in rows:
        if source not in SOURCES:
            problems.append(f"{source}: not a dissolved README")
            continue
        if kind not in KINDS:
            problems.append(f"{source}: {section}: unknown kind {kind}")
        if section not in base_headings.get(source, []):
            problems.append(f"{source}: {section}: not a heading at the base commit")
        if not destinations:
            problems.append(f"{source}: {section}: {kind} row names no destination")
        for path in destinations:
            if not _is_allowed_home(kind, path):
                problems.append(f"{source}: {section}: {kind} destination {path} is not an allowed home")
        for path in destinations:
            if not exists(path):
                problems.append(f"{source}: {section}: {path} does not exist")
        triple = (source, section, kind)
        if triple in seen:
            problems.append(f"{source}: {section}: duplicate {kind} row")
        seen.add(triple)
        if triple not in audited:
            problems.append(f"{source}: {section}: {kind} row is not in the audit")
    for source, section, kind in sorted(audited):
        if (source, section, kind) not in seen:
            problems.append(f"{source}: {section}: audited {kind} row missing")
    return problems


class DocsTreeTest(unittest.TestCase):
    def test_the_docs_tree_passes_the_context_map_lint(self):
        map_path = REPO_ROOT / "docs/CONTEXT-MAP.md"
        result = subprocess.run(
            [sys.executable, "-m", "agent_tools.context_map_lint",
             "--repo-root", str(REPO_ROOT), "--context-map", str(map_path)],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_dissolved_readme_section_is_mapped(self):
        rows, problems = parse_section_map(SECTION_MAP.read_text(encoding="utf-8"))
        base_headings = {source: headings(base_text(source)) for source in SOURCES}
        problems += section_map_problems(rows, AUDITED, base_headings, destination_exists)
        self.assertEqual(problems, [])

    def test_a_dropped_decision_row_is_reported(self):
        rows = [("python/README.md", "forge-claim", "contract", ("python/agent_tools/forge_claim.py",))]
        audited = frozenset({
            ("python/README.md", "forge-claim", "contract"),
            ("python/README.md", "forge-claim", "decision"),
        })
        base = {"python/README.md": ["forge-claim"]}
        self.assertEqual(
            section_map_problems(rows, audited, base, lambda path: True),
            ["python/README.md: forge-claim: audited decision row missing"],
        )

    def test_a_decision_row_outside_an_adr_or_the_archive_is_reported(self):
        rows = [("python/README.md", "forge-claim", "decision", ("python/agent_tools/forge_claim.py",))]
        audited = frozenset({("python/README.md", "forge-claim", "decision")})
        base = {"python/README.md": ["forge-claim"]}
        self.assertEqual(
            section_map_problems(rows, audited, base, lambda path: True),
            ["python/README.md: forge-claim: decision destination python/agent_tools/forge_claim.py is not an allowed home"],
        )

    def test_a_destination_moved_after_the_map_commit_still_exists(self):
        env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def git(*args: str) -> None:
                subprocess.run(
                    ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                     "-c", "commit.gpgsign=false", *args],
                    check=True, env=env, capture_output=True,
                )

            git("init", "-q")
            (root / "a.py").write_text("x = 1\n")
            (root / "docs/archive").mkdir(parents=True)
            (root / SECTION_MAP_REL).write_text("map\n")
            git("add", "-A")
            git("commit", "-qm", "map")
            git("mv", "a.py", "b.py")
            git("commit", "-qm", "move")
            self.assertEqual(
                (destination_exists("a.py", root), destination_exists("b.py", root),
                 destination_exists("never.py", root)),
                (True, True, False),
            )

    def test_dissolved_readmes_fit_150_lines(self):
        too_long = []
        for path in SOURCES:
            count = len((REPO_ROOT / path).read_text(encoding="utf-8").splitlines())
            if count > 150:
                too_long.append(f"{path}: {count} lines")
        self.assertEqual(too_long, [])

    def test_no_living_file_routes_new_detail_to_python_readme(self):
        hits = [
            f"{path}:{number}"
            for path, lines in tracked_text((".agents/artifacts/", "docs/archive/"))
            for number, line in enumerate(lines, start=1)
            if ROUTING_RE.search(line)
        ]
        self.assertEqual(hits, [])

    def test_no_living_file_cites_a_python_readme_section(self):
        hits = [
            f"{path}:{number}"
            for path, lines in tracked_text((".agents/artifacts/", "docs/archive/", "docs/spikes/"))
            for number, line in enumerate(lines, start=1)
            if SECTION_CITE_RE.search(line)
        ]
        self.assertEqual(hits, [])

    def test_every_area_holds_an_adr(self):
        empty = sorted(
            d.name for d in (REPO_ROOT / "docs/areas").iterdir()
            if d.is_dir() and not list((d / "adr").glob("*.md"))
        )
        self.assertEqual(empty, [])

    def test_every_base_section_is_audited_or_kept(self):
        problems = []
        for source in SOURCES:
            base = headings(base_text(source))
            audited = {section for s, section, _ in AUDITED if s == source}
            kept = {section for s, section in KEPT if s == source}
            for heading in base:
                if heading not in audited and heading not in kept:
                    problems.append(f"{source}: {heading}: neither audited nor kept")
                if heading in audited and heading in kept:
                    problems.append(f"{source}: {heading}: both audited and kept")
            for heading in sorted(kept - set(base)):
                problems.append(f"{source}: {heading}: kept but not a base heading")
        self.assertEqual(problems, [])

    def test_the_codesigned_artifact_docstring_states_no_limitation(self):
        import ast

        source = (REPO_ROOT / "python/agent_tools/codesigned_artifact_adapter.py").read_text()
        docstring = " ".join((ast.get_docstring(ast.parse(source)) or "").split())
        self.assertNotIn("cannot prove", docstring)


if __name__ == "__main__":
    unittest.main()
