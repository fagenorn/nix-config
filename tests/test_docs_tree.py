import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery.record_lint import record_violations
from agent_tools.project_contract.adopt_links import links


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "python/README.md",
    "home/common/claude-code/README.md",
    "home/common/agent-skills/README.md",
)


TAILNET_PLACEHOLDER = "<host>.<tailnet>.ts.net"
INVENTED_TAILNET = "invented-tailnet.ts.net"
TAILNET_NAME = re.compile(r"[^\s/()\[\]`\"'<>]*(?:<[^<>\s]*>[^\s/()\[\]`\"'<>]*)*\.ts\.net")


def tailnet_names_other_than_placeholder(text: str) -> list:
    """Every tailnet hostname in `text` that is not exactly the placeholder, each checked alone."""
    return [name for name in TAILNET_NAME.findall(text) if name != TAILNET_PLACEHOLDER]


LOGIN_LIKE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*")


def logins_in(text: str) -> list:
    """Every email-style login in `text`; the `<colleague-login>` placeholder is not one."""
    return LOGIN_LIKE.findall(text)


def markdown_section(text: str, name: str) -> str:
    """The text after the line `## <name>` up to the next `## ` line; "" when absent."""
    lines = text.splitlines(keepends=True)
    if f"## {name}\n" not in lines:
        return ""
    start = lines.index(f"## {name}\n") + 1
    out = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        out.append(line)
    return "".join(out)


# The [E] and [l] classes match the same text as the letters; they keep this
# line from matching its own pattern, so a grep for the phrases skips this file.
ROUTING_RE = re.compile(r"python/READM[E].*goes there|new detai[l][^.;]*python/README|home is python/READM[E]")
SECTION_CITE_RE = re.compile(r"python/README\.md\S*\s*§")


PIN = "6b06a4e277ab8885d02cca9cec38e85a6de5dc55"
WORKING_ARTIFACT_DIRS = (".agents/artifacts", "docs/archive", "docs/spikes")
PATH_EXCLUDED = r"\s\"'`()<>\[\]{}#,;|*\\?"
PATH_CHAR = "[^" + PATH_EXCLUDED + "]"
SEGMENT_CHAR = "[^" + PATH_EXCLUDED + "/]"
# A file under one of the three roots, whatever its name or depth: the root, then a subdirectory and a child
# or a name with an extension. A bare directory name, which the project contract still carries, is not one.
DESCENDANT = "(?=" + SEGMENT_CHAR + r"+/[\w-]|" + SEGMENT_CHAR + r"*\.[A-Za-z0-9])"
WORKING_ARTIFACT_RE = re.compile(r"\.agents/artifacts/" + DESCENDANT + "|docs/(?:archive|spikes)/" + DESCENDANT)
PINNED_LINK_RE = re.compile(r"https://github\.com/fagenorn/nix-config/blob/([0-9a-f]{40})/\Z")
URL_BEFORE_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'`()<>]*\Z")
PATH_TAIL_RE = re.compile(PATH_CHAR + "*")
TEST_TREES = ("tests/", "home/common/agent-skills/tests/")

MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
REMOVED_ARCHITECTURE_RE = re.compile(
    r"CLAUDE\.md#architecture"
    r"|Architecture`?\s+(?:section|heading)\s+(?:of|in)\s+(?:the\s+)?`?CLAUDE\.md"
    r"|CLAUDE\.md`?(?:['\u2019]s)?\s*(?:>|\u203a|\u00a7|->|\u2192)?\s*`?(?:##\s*)?Architecture\s+(?:section|heading)"
    r"|CLAUDE\.md`?\s*(?:>|\u203a|\u00a7|->|\u2192)\s*Architecture",
    re.IGNORECASE,
)


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


def archived_files() -> frozenset[str]:
    """The files the three working-artifact directories held at PIN."""
    listing = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-tree", "-r", "--name-only", "-z", PIN, "--", *WORKING_ARTIFACT_DIRS],
        check=True, capture_output=True,
    ).stdout.decode("utf-8")
    return frozenset(name for name in listing.split("\0") if name)


def held_at(commit: str, token: str) -> bool:
    """Whether `commit` exists and holds `token` as a file."""
    done = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-t", f"{commit}:{token}"],
        capture_output=True, text=True,
    )
    return done.returncode == 0 and done.stdout.strip() == "blob"


def link_targets(line: str) -> list[str]:
    """Each markdown link destination on `line`, as the repository's own link parser reads it."""
    return [link.target for link in links(line)]


def working_artifact_hits(path: str, lines: list[str], archived: frozenset[str], holds=held_at) -> list[str]:
    """`path:line` for each line that names a working artifact other than through a live pinned link.

    A match preceded by a commit-pinned blob URL is admitted only when `holds(sha, path)` finds the path
    as a file at the cited commit. Any other match inside a URL is a hit. A match outside a URL is admitted
    only inside the test trees and only when it names no file PIN held. In a markdown file a relative link
    into a working-artifact directory is a hit, titled or not.
    """
    in_tests = path.startswith(TEST_TREES)
    hits = []
    for number, line in enumerate(lines, 1):
        bad = False
        for m in WORKING_ARTIFACT_RE.finditer(line):
            token = (m.group(0) + PATH_TAIL_RE.match(line, m.end()).group(0)).rstrip(".:")
            before = line[: m.start()]
            pin = PINNED_LINK_RE.search(before)
            if pin is not None:
                bad = bad or not holds(pin.group(1), token)
            elif URL_BEFORE_RE.search(before) is not None:
                bad = True
            else:
                names_archived = token in archived or any(
                    a.startswith(token.rstrip("/") + "/") for a in archived
                )
                bad = bad or not in_tests or names_archived
        if not bad and path.endswith(".md"):
            for target in link_targets(line):
                if "://" in target or target.startswith(("#", "mailto:")):
                    continue
                resolved = posixpath.normpath(
                    posixpath.join(posixpath.dirname(path), target.split("#", 1)[0].split("?", 1)[0])
                )
                if any(resolved.startswith(d + "/") for d in WORKING_ARTIFACT_DIRS):
                    bad = True
        if bad:
            hits.append(f"{path}:{number}")
    return hits


def index_destinations(text: str) -> list[str]:
    """Each repo-relative destination the docs index (the first table of `docs/README.md`) links to.

    The index is the first run of consecutive lines starting with `|`; its header and separator rows are
    skipped, only the first cell of a row is read, and a URL is not a destination.
    """
    rows: list[str] = []
    for line in text.splitlines():
        if line.startswith("|"):
            rows.append(line)
        elif rows:
            break
    found = []
    for row in rows[2:]:
        for target in link_targets(row.split("|")[1]):
            if "://" not in target:
                found.append(posixpath.normpath(posixpath.join("docs", target.split("#", 1)[0].split("?", 1)[0])))
    return found


def scanned_files(archived_dirs: tuple[str, ...] = ()) -> list[tuple[str, list[str]]]:
    """Every tracked text file the working-artifact scan reads."""
    return tracked_text(archived_dirs)


RETIRED_DELIVERY_RECORDS = (2, 9, 10, 11)
RETIRED_CONSOLE_RECORDS = (2, 9, 25, 39, 40, 41, 53, 55, 56, 57, 61, 64, 69)
LATER_THAN_076 = re.compile(r"^docs/areas/console/adr/(?:07[7-9]|0[89]\d|[1-9]\d\d)-")
SUB_DECISION_027_TO_051 = re.compile(
    r"\bADR-console-(0(?:2[7-9]|[34]\d|5[01]))(?:'s)? \(?(?:D\d|Consequences)")
SUB_DECISION_052_TO_076 = re.compile(
    r"\bADR-console-(0(?:5[2-9]|6\d|7[0-6]))(?:'s)? \(?(?:D\d|Consequences)")


def console_records(numbers) -> list[Path]:
    return sorted(
        p for p in (REPO_ROOT / "docs/areas/console/adr").glob("[0-9][0-9][0-9]-*.md")
        if int(p.name[:3]) in numbers)


def console_form_findings(numbers) -> list[tuple[str, str, int]]:
    return [
        (p.name, v.rule, v.line)
        for p in console_records(numbers)
        for v in record_violations(f"docs/areas/console/adr/{p.name}", p.read_bytes())
    ]


def sub_decision_hits(
        numbers, pattern=SUB_DECISION_027_TO_051, later=LATER_THAN_076) -> list[str]:
    return [
        f"{path}:{number}"
        for path, lines in tracked_text(())
        if not later.match(path)
        for number, line in enumerate(lines, start=1)
        if any(int(m.group(1)) in numbers for m in pattern.finditer(line))
    ]


class DocsTreeTest(unittest.TestCase):
    def test_the_index_routes_each_working_artifact_off_the_tree(self):
        lines = (REPO_ROOT / "docs/README.md").read_text(encoding="utf-8").splitlines()
        start = lines.index("**Where new knowledge goes**")
        first = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("|"))
        table = []
        for line in lines[first:]:
            if not line.startswith("|"):
                break
            table.append(line)
        self.assertTrue(table)
        for row in (
            "| A spec | The body of its parent issue, never the tree |",
            "| A plan and its task files | The worktree's git directory, never the tree |",
            "| A measurement, spike or other evidence | A comment or attachment on the pull request"
            " or issue it proves, never `docs/` |",
        ):
            self.assertIn(row, table)
        for line in table:
            self.assertNotIn(".agents/artifacts/", line)
            self.assertNotIn("archive/", line)

    def test_no_file_is_tracked_under_a_working_artifact_directory(self):
        listing = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", *WORKING_ARTIFACT_DIRS],
            check=True, capture_output=True,
        )
        paths = [p for p in listing.stdout.decode("utf-8").split("\0") if p]
        self.assertEqual(paths, [])

    def test_the_index_has_no_archive_or_spikes_entry(self):
        text = (REPO_ROOT / "docs/README.md").read_text(encoding="utf-8")
        hits = [
            d for d in index_destinations(text)
            if any(d == w or d.startswith(w + "/") for w in ("docs/archive", "docs/spikes"))
        ]
        self.assertEqual(hits, [])

    def test_index_destinations_resolve_each_entry_relative_to_the_index(self):
        text = (
            "# x\n\n| Entry | What |\n|---|---|\n| [Past reports](archive/) | old |\n"
            "| [g](./guides/#top) | g |\n| [w](https://example.invalid/) | w |\n\n**Where**\n\n"
            "| K | H |\n|---|---|\n| [s](./spikes/) | s |\n"
        )
        self.assertEqual(index_destinations(text), ["docs/archive", "docs/guides"])
        titled = "| K | H |\n|---|---|\n| [Past reports](./archive/ \"History\") | old |\n"
        self.assertEqual(index_destinations(titled), ["docs/archive"])

    def test_the_docs_tree_passes_the_context_map_lint(self):
        map_path = REPO_ROOT / "docs/CONTEXT-MAP.md"
        result = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.context_map_lint",
             "--repo-root", str(REPO_ROOT), "--context-map", str(map_path)],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_project_contract_records_001_to_009_keep_the_record_form(self):
        paths = sorted((REPO_ROOT / "docs/areas/project-contract/adr").glob("00[1-9]-*.md"))
        self.assertTrue(paths)
        breaches = {}
        for path in paths:
            relative = path.relative_to(REPO_ROOT).as_posix()
            found = [violation.text() for violation in
                     record_violations(relative, path.read_bytes())]
            if found:
                breaches[relative] = found
        self.assertEqual(breaches, {})

    def test_no_tracked_file_cites_a_retired_project_contract_record(self):
        # The patterns are built here so this file holds no citation they match.
        numbers = ("001", "002", "003", "006", "009")
        retired = ("ADR-project-contract-(" + "|".join(numbers) + ")([^0-9]|$)"
                   + "|project-contract/adr/(" + "|".join(numbers) + ")-")
        sub = "ADR-project-contract-" + "00[1-9] D[0-9]"
        for pattern in (retired, sub):
            result = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "grep", "-n", "-E", pattern],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertEqual(result.stdout, "")
        for number in numbers:
            found = sorted((REPO_ROOT / "docs/areas/project-contract/adr").glob(f"{number}-*.md"))
            self.assertEqual(found, [])

    def test_every_hosts_record_keeps_the_record_form(self):
        paths = sorted((REPO_ROOT / "docs/areas/hosts/adr").glob("*.md"))
        self.assertTrue(paths)
        breaches = {}
        for path in paths:
            relative = path.relative_to(REPO_ROOT).as_posix()
            found = record_violations(relative, path.read_bytes())
            if found:
                breaches[relative] = [violation.text() for violation in found]
        self.assertEqual(breaches, {})

    def test_no_tracked_file_cites_a_retired_hosts_record(self):
        numbers = ("001", "002", "003", "004")
        pattern = "ADR-hosts-(" + "|".join(numbers) + ")([^0-9]|$)"
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "grep", "-n", "-E", pattern],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(result.stdout, "")
        for number in numbers:
            self.assertEqual(sorted((REPO_ROOT / "docs/areas/hosts/adr").glob(f"{number}-*.md")), [])

    def test_every_guard_record_keeps_the_record_form(self):
        paths = sorted((REPO_ROOT / "docs/areas/guard/adr").glob("*.md"))
        self.assertTrue(paths)
        breaches = {}
        for path in paths:
            relative = path.relative_to(REPO_ROOT).as_posix()
            found = record_violations(relative, path.read_bytes())
            if found:
                breaches[relative] = [violation.rule for violation in found]
        self.assertEqual(breaches, {})

    def test_no_living_file_names_a_working_artifact_outside_a_pinned_link(self):
        archived = archived_files()
        hits = [hit for path, lines in scanned_files() for hit in working_artifact_hits(path, lines, archived)]
        self.assertEqual(hits, [])

    def test_the_working_artifact_scan_admits_only_pinned_links_and_synthetic_test_paths(self):
        archived_doc = "docs/" + "archive/x.md"
        spec = ".agents/" + "artifacts/specs/x.md"
        real = ".agents/" + "artifacts/evidence/real.json"
        pinned = "https://github.com/fagenorn/nix-config/blob/" + PIN + "/"
        other = "https://github.com/fagenorn/nix-config/blob/" + "a" * 40 + "/"
        archived = frozenset({real})
        adr = "docs/areas/a/adr/001-x.md"

        def holds(sha, token):
            return sha == PIN and token in archived

        cases = {
            "bare path": (adr, ["see `" + archived_doc + "`"], [adr + ":1"]),
            "pinned link": (adr, ["[x](" + pinned + real + ")"], []),
            "pinned link to a path the pin does not hold": (
                adr, ["[x](" + pinned + archived_doc + ")"], [adr + ":1"]),
            "pinned link at another commit": (adr, ["[x](" + other + real + ")"], [adr + ":1"]),
            "branch link": (
                adr, ["[x](https://github.com/fagenorn/nix-config/blob/main/" + real + ")"], [adr + ":1"]),
            "pinned link then bare path": (
                adr, ["[x](" + pinned + real + ") and `" + spec + "`"], [adr + ":1"]),
            "test tree pinned link to a path the pin does not hold": (
                "tests/test_x.py", ['"""Kept at ' + pinned + spec + '."""'], ["tests/test_x.py:1"]),
            "test tree pinned link": ("tests/test_x.py", ['"""Kept at ' + pinned + real + '."""'], []),
            "relative link into the archive": (
                adr, ["[x](../../../" + "archive/x.md#h)"], [adr + ":1"]),
            "relative link elsewhere": (adr, ["[x](../../../guides/x.md)"], []),
            "relative link to the directory itself": (
                "docs/README.md", ["| [old](./" + "archive/) | x |"], []),
            "test tree synthetic path": ("tests/test_x.py", ["p = '" + spec + "'"], []),
            "test tree real file": (
                "tests/test_x.py", ["p = ROOT / '" + real + "'"], ["tests/test_x.py:1"]),
            "test tree branch link to a real file with a query": (
                "tests/test_x.py", ["u = 'https://github.com/fagenorn/nix-config/blob/main/" + archived_doc
                                    + "?plain=1'"], ["tests/test_x.py:1"]),
            "test tree branch link to a synthetic path": (
                "tests/test_x.py", ["u = 'https://example.invalid/" + spec + "'"], ["tests/test_x.py:1"]),
            "test tree pinned link with a query": (
                "tests/test_x.py", ["u = '" + pinned + real + "?plain=1'"], []),
            "titled relative link into the archive": (
                adr, ["[x](../../../" + "archive/x.md \"History\")"], [adr + ":1"]),
            "uppercase archive descendant": (adr, ["see `docs/" + "archive/README.md`"], [adr + ":1"]),
            "other artifacts directory": (adr, ["see `.agents/" + "artifacts/notes/a.md`"], [adr + ":1"]),
            "module path": ("python/agent_tools/m.py", ["# see " + spec], ["python/agent_tools/m.py:1"]),
        }
        for label, (path, lines, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(working_artifact_hits(path, lines, archived, holds), expected)

    def test_a_pin_is_checked_at_the_commit_it_cites(self):
        commit = "7343c8fedee64a6154dd0d611231bec6cf4bed43"
        plan = ".agents/" + "artifacts/plans/2026-08-12-broker-reaping.md"
        adr = "docs/areas/a/adr/001-x.md"
        base = "https://github.com/fagenorn/nix-config/blob/"
        for label, sha, name, expected in (
            ("a path the cited commit holds", commit, plan, []),
            ("a path the cited commit lacks", commit, plan + "x", [adr + ":1"]),
            ("a commit that does not exist", "a" * 40, plan, [adr + ":1"]),
        ):
            with self.subTest(label):
                self.assertEqual(
                    working_artifact_hits(adr, ["[x](" + base + sha + "/" + name + ")"], frozenset()), expected)

    def test_the_delivery_glossary_defines_the_engine_terms(self):
        area = (REPO_ROOT / "docs/areas/delivery/CONTEXT.md").read_text(encoding="utf-8")
        context_map = self.doc("docs/CONTEXT-MAP.md")
        for term in ("Engine", "Grader", "Outcome", "Procedure", "Step", "Stop"):
            with self.subTest(term=term):
                self.assertIsNotNone(re.search(rf"^\*\*{term}\*\*:", area, re.M))
                self.assertIn(f"| {term} | Delivery |", context_map)

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

    def test_the_architecture_guide_holds_the_flake_layout_and_the_helper_package(self):
        text = (REPO_ROOT / "docs/guides/architecture.md").read_text(encoding="utf-8")
        for name in (
            "mkDarwin", "mkNixos", "scanPaths", "mergeFilesOrdered", "agent_tools",
            "hosts/common/common-packages.nix", "hosts/common/{darwin,linux}-common.nix",
            "home/default.nix", "home/{darwin,linux}-common.nix",
        ):
            self.assertIn(name, text)

    def test_every_relative_link_in_the_architecture_guide_resolves(self):
        guide = REPO_ROOT / "docs/guides/architecture.md"
        targets = [t for t in MD_LINK_RE.findall(guide.read_text(encoding="utf-8")) if "://" not in t]
        self.assertTrue(targets)
        missing = [t for t in targets if not (guide.parent / t.split("#")[0]).exists()]
        self.assertEqual(missing, [])

    def test_claude_md_links_the_architecture_guide_once_and_has_no_architecture_section(self):
        text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        guide = (REPO_ROOT / "docs/guides/architecture.md").resolve()
        links = [
            t for t in MD_LINK_RE.findall(text)
            if "://" not in t and (REPO_ROOT / t.split("#")[0]).resolve() == guide
        ]
        self.assertEqual(len(links), 1, links)
        self.assertEqual([line for line in text.splitlines() if re.match(r"#+\s+Architecture\b", line)], [])

    def test_the_repository_contract_resolves_one_architecture_path_the_guide(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(home, ignore_errors=True))
        (home / ".agents" / "share").mkdir(parents=True)
        manifest = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
        (home / ".agents" / "share" / "platform-manifest.json").write_bytes(manifest.read_bytes())
        env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(REPO_ROOT / "python")}
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.project_contract.resolve_project", "resolve",
             "--repo-root", str(REPO_ROOT)],
            env=env, text=True, stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        architecture = json.loads(done.stdout)["bindings"]["paths"]["architecture"]
        self.assertEqual(architecture, [str(REPO_ROOT / "docs/guides/architecture.md")])

    def test_the_docs_routing_table_routes_an_architecture_description_to_the_guide(self):
        rows = [
            line for line in (REPO_ROOT / "docs/README.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("| The architecture description")
        ]
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("(./guides/architecture.md)", rows[0])
        guides_line = [
            line for line in (REPO_ROOT / "docs/README.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("| [guides/]")
        ]
        self.assertEqual(len(guides_line), 1)
        self.assertNotIn("procedures only", guides_line[0].lower())

    def test_the_removed_section_pattern_matches_references_and_not_prose(self):
        for reference in (
            "see CLAUDE.md#architecture", "the Architecture section of CLAUDE.md",
            "CLAUDE.md's Architecture section", "CLAUDE.md > Architecture", "CLAUDE.md § Architecture",
            "the `## Architecture` section in `CLAUDE.md`",
        ):
            self.assertRegex(reference, REMOVED_ARCHITECTURE_RE)
        for prose in (
            "CLAUDE.md links to the Architecture guide", "the Architecture guide, linked from CLAUDE.md",
        ):
            self.assertNotRegex(prose, REMOVED_ARCHITECTURE_RE)

    def test_no_living_file_links_the_removed_architecture_section(self):
        hits = [
            f"{path}:{number}"
            for path, lines in tracked_text((
                ".agents/artifacts/", "docs/archive/", "docs/spikes/",
                ".agents/knowledge/archive/", ".agents/knowledge/rejections/",
            ))
            if path != "tests/test_docs_tree.py"  # holds the pattern's own examples
            for number, line in enumerate(lines, start=1)
            if REMOVED_ARCHITECTURE_RE.search(line)
        ]
        self.assertEqual(hits, [])

    def test_the_light_lane_record_and_glossary_entry_are_retired(self):
        self.assertFalse(
            (REPO_ROOT / "docs/areas/delivery/adr/005-the-light-lane-runs-in-shadow.md").exists())
        context = (REPO_ROOT / "docs/areas/delivery/CONTEXT.md").read_text().splitlines()
        self.assertEqual([line for line in context if re.match(r"^\*\*Light lane\*\*:", line)], [])
        context_map = (REPO_ROOT / "docs/CONTEXT-MAP.md").read_text().splitlines()
        self.assertEqual([line for line in context_map if re.match(r"^\|\s*Light lane\s*\|", line)], [])
        self.assertEqual([line for line in context if re.match(r"^\*\*Triage record\*\*:", line)], [])
        self.assertEqual([line for line in context if "triage" in line.lower()], [])
        self.assertEqual([line for line in context_map if re.match(r"^\|\s*Triage record\s*\|", line)], [])
        hits = [
            f"{path}:{number}"
            for path, lines in tracked_text((".agents/artifacts/", "docs/archive/"))
            if path != "tests/test_docs_tree.py"  # holds the literal
            for number, line in enumerate(lines, start=1)
            if "ADR-delivery-005" in line
        ]
        self.assertEqual(hits, [])

    def test_the_delivery_records_001_to_011_keep_the_record_form(self):
        records = [
            p for p in sorted((REPO_ROOT / "docs/areas/delivery/adr").glob("[0-9][0-9][0-9]-*.md"))
            if 1 <= int(p.name[:3]) <= 11
        ]
        found = [
            (p.name, v.rule, v.line)
            for p in records
            for v in record_violations(f"docs/areas/delivery/adr/{p.name}", p.read_bytes())
        ]
        self.assertTrue(records)
        self.assertEqual(found, [])

    def test_the_console_records_001_to_026_keep_the_record_form(self):
        records = [
            p for p in sorted((REPO_ROOT / "docs/areas/console/adr").glob("[0-9][0-9][0-9]-*.md"))
            if 1 <= int(p.name[:3]) <= 26
        ]
        found = [
            (p.name, v.rule, v.line)
            for p in records
            for v in record_violations(f"docs/areas/console/adr/{p.name}", p.read_bytes())
        ]
        self.assertEqual(
            [int(p.name[:3]) for p in records],
            [1, 3, 4, 5, 6, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 26])
        self.assertEqual(found, [])

    def test_the_console_registration_records_are_cut_and_cited_whole(self):
        numbers = (28, 29, 30, 31, 33, 34, 35, 37)
        self.assertEqual(
            [int(p.name[:3]) for p in console_records(numbers)], [28, 29, 30, 31, 33, 34, 35, 37])
        self.assertEqual(console_form_findings(numbers), [])
        self.assertEqual(sub_decision_hits(numbers), [])

    def test_the_console_sprint_reading_records_are_cut_and_cited_whole(self):
        numbers = (42, 48, 50, 51)
        self.assertEqual([int(p.name[:3]) for p in console_records(numbers)], [42, 48, 50, 51])
        self.assertEqual(console_form_findings(numbers), [])
        self.assertEqual(sub_decision_hits(numbers), [])

    def test_the_console_picture_records_are_cut_and_cited_whole(self):
        numbers = (36, 38, 45, 47)
        self.assertEqual([int(p.name[:3]) for p in console_records(numbers)], [36, 38, 45, 47])
        self.assertEqual(console_form_findings(numbers), [])
        self.assertEqual(sub_decision_hits(numbers), [])

    def test_the_console_manager_records_are_cut_and_cited_whole(self):
        numbers = (27, 32, 43, 44, 46, 49)
        self.assertEqual([int(p.name[:3]) for p in console_records(numbers)], [27, 32, 43, 44, 46, 49])
        self.assertEqual(console_form_findings(numbers), [])
        self.assertEqual(sub_decision_hits(numbers), [])

    def test_the_console_spend_record_is_cut_and_cited_whole(self):
        numbers = (52,)
        self.assertEqual([int(p.name[:3]) for p in console_records(numbers)], [52])
        self.assertEqual(console_form_findings(numbers), [])
        self.assertEqual(sub_decision_hits(numbers, SUB_DECISION_052_TO_076, LATER_THAN_076), [])

    def test_the_console_manager_and_guest_records_are_cut_and_cited_whole(self):
        numbers = (60, 63, 66, 68, 75, 76)
        self.assertEqual(
            [int(p.name[:3]) for p in console_records(numbers)], [60, 63, 66, 68, 75, 76])
        self.assertEqual(console_form_findings(numbers), [])
        self.assertEqual(sub_decision_hits(numbers, SUB_DECISION_052_TO_076, LATER_THAN_076), [])

    def test_the_console_question_records_are_cut_and_cited_whole(self):
        numbers = (58, 59, 62, 65, 67)
        self.assertEqual([int(p.name[:3]) for p in console_records(numbers)], [58, 59, 62, 65, 67])
        self.assertEqual(console_form_findings(numbers), [])
        self.assertEqual(sub_decision_hits(numbers, SUB_DECISION_052_TO_076, LATER_THAN_076), [])

    def test_the_console_card_and_registration_records_are_cut_and_cited_whole(self):
        numbers = (54, 70, 71, 72, 73, 74)
        self.assertEqual(
            [int(p.name[:3]) for p in console_records(numbers)], [54, 70, 71, 72, 73, 74])
        self.assertEqual(console_form_findings(numbers), [])
        self.assertEqual(sub_decision_hits(numbers, SUB_DECISION_052_TO_076, LATER_THAN_076), [])

    def test_the_console_records_052_to_076_are_the_kept_ones(self):
        records = [
            p for p in sorted((REPO_ROOT / "docs/areas/console/adr").glob("[0-9][0-9][0-9]-*.md"))
            if 52 <= int(p.name[:3]) <= 76]
        found = [
            (p.name, v.rule, v.line)
            for p in records
            for v in record_violations(f"docs/areas/console/adr/{p.name}", p.read_bytes())
        ]
        self.assertEqual(
            [int(p.name[:3]) for p in records],
            [52, 54, 58, 59, 60, 62, 63, 65, 66, 67, 68, 70, 71, 72, 73, 74, 75, 76])
        self.assertEqual(found, [])

    def test_the_console_records_027_to_051_are_the_kept_ones(self):
        records = [
            p for p in sorted((REPO_ROOT / "docs/areas/console/adr").glob("[0-9][0-9][0-9]-*.md"))
            if 27 <= int(p.name[:3]) <= 51]
        found = [
            (p.name, v.rule, v.line)
            for p in records
            for v in record_violations(f"docs/areas/console/adr/{p.name}", p.read_bytes())
        ]
        self.assertEqual(
            [int(p.name[:3]) for p in records],
            [27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51])
        self.assertEqual(found, [])

    def test_the_sub_decision_pattern_finds_a_cited_sub_decision(self):
        self.assertIsNotNone(SUB_DECISION_027_TO_051.search("ADR-console-0" + "28 D10"))
        self.assertIsNotNone(SUB_DECISION_027_TO_051.search("ADR-console-0" + "34's Consequences"))
        self.assertIsNotNone(SUB_DECISION_027_TO_051.search("ADR-console-0" + "30 (D5"))
        self.assertIsNone(SUB_DECISION_027_TO_051.search("ADR-console-0" + "52 D1"))
        self.assertIsNone(SUB_DECISION_027_TO_051.search("ADR-console-0" + "28 was"))
        self.assertIsNotNone(SUB_DECISION_052_TO_076.search("ADR-console-0" + "60 D6"))
        self.assertIsNotNone(SUB_DECISION_052_TO_076.search("ADR-console-0" + "54's Consequences"))
        self.assertIsNotNone(SUB_DECISION_052_TO_076.search("ADR-console-0" + "74 (D10"))
        self.assertIsNone(SUB_DECISION_052_TO_076.search("ADR-console-0" + "77 D1"))
        self.assertIsNone(SUB_DECISION_052_TO_076.search("ADR-console-0" + "51 D1"))
        self.assertIsNone(SUB_DECISION_052_TO_076.search("ADR-console-0" + "60 was"))
        self.assertIsNotNone(LATER_THAN_076.match("docs/areas/console/adr/0" + "77-x.md"))
        self.assertIsNone(LATER_THAN_076.match("docs/areas/console/adr/0" + "76-x.md"))

    def test_the_retired_console_records_are_gone_and_cited_nowhere(self):
        for n in RETIRED_CONSOLE_RECORDS:
            with self.subTest(number=n):
                pattern = re.compile(rf"\bADR-console-{n:03d}(?!\d)|console/adr/{n:03d}-")
                files = sorted(
                    p.name for p in (REPO_ROOT / "docs/areas/console/adr").glob(f"{n:03d}-*.md"))
                hits = [
                    f"{path}:{number}"
                    for path, lines in tracked_text(())
                    for number, line in enumerate(lines, start=1)
                    if pattern.search(line)
                ]
                self.assertEqual(files, [])
                self.assertEqual(hits, [])

    def test_no_tracked_file_cites_a_sub_decision_of_a_cut_console_record(self):
        pattern = re.compile(r"\bADR-console-0(?:0[1-9]|1\d|2[0-6])(?:'s)? \(?(?:D\d|Consequences)")
        self.assertIsNotNone(pattern.search("ADR-console-0" + "26 (D6 and its Consequences)"))
        self.assertIsNotNone(pattern.search("ADR-console-0" + "23 D1"))
        self.assertIsNotNone(pattern.search("ADR-console-0" + "17's Consequences"))
        hits = [
            f"{path}:{number}"
            for path, lines in tracked_text(())
            for number, line in enumerate(lines, start=1)
            if pattern.search(line)
        ]
        self.assertEqual(hits, [])

    def test_the_retired_delivery_records_are_gone_and_cited_nowhere(self):
        for n in RETIRED_DELIVERY_RECORDS:
            with self.subTest(number=n):
                pattern = re.compile(rf"\bADR-delivery-{n:03d}(?!\d)|delivery/adr/{n:03d}-")
                files = sorted(
                    p.name for p in (REPO_ROOT / "docs/areas/delivery/adr").glob(f"{n:03d}-*.md"))
                hits = [
                    f"{path}:{number}"
                    for path, lines in tracked_text(())
                    for number, line in enumerate(lines, start=1)
                    if pattern.search(line)
                ]
                self.assertEqual(files, [])
                self.assertEqual(hits, [])

    def test_no_area_numbers_two_adrs_alike(self):
        shared = []
        for adr_dir in sorted((REPO_ROOT / "docs/areas").glob("*/adr")):
            seen = {}
            for path in sorted(adr_dir.glob("*.md")):
                seen.setdefault(path.name[:3], []).append(path.name)
            shared += [f"{adr_dir.parent.name}/{n}: {names}" for n, names in seen.items() if len(names) > 1]
        self.assertEqual(shared, [])

    def test_the_console_area_owns_its_terms(self):
        text = (REPO_ROOT / "docs/CONTEXT-MAP.md").read_text()
        cells = [[c.strip() for c in line.strip().strip("|").split("|")]
                 for line in text.splitlines() if line.startswith("|")]
        areas = [row for row in cells if row[0] == "Console" and len(row) == 4]
        self.assertEqual(len(areas), 1)
        self.assertIn("(./areas/console/CONTEXT.md)", areas[0][1])
        self.assertIn("`python/agent_tools/console/**`", areas[0][3])
        for term in ("Console", "Inbox item", "Quiet project", "Answered item",
                     "Held work", "Waiting since", "Session", "Outside sprints",
                     "Not yet managed", "Delivery run", "Goal", "Sprint", "Brief",
                     "Message", "Nudge", "Question round", "Notice", "Spend page",
                     "Project question", "Question thread"):
            self.assertIn([term, "Console"], cells)
        self.assertIn("- **Console → Claims**:", text)

    def doc(self, path):
        return " ".join((REPO_ROOT / path).read_text().split())

    def test_every_verification_record_keeps_the_record_form(self):
        paths = sorted((REPO_ROOT / "docs/areas/verification/adr").glob("*.md"))
        self.assertTrue(paths)
        breaches = {}
        for path in paths:
            relative = path.relative_to(REPO_ROOT).as_posix()
            found = record_violations(relative, path.read_bytes())
            if found:
                breaches[relative] = [v.text() for v in found]
        self.assertEqual(breaches, {})

    def test_no_tracked_file_cites_a_deleted_verification_record(self):
        numbers = ("001", "005", "006", "007")
        # The pattern is built at run time so this file holds no deleted citation itself.
        pattern = "ADR-verification-(" + "|".join(numbers) + ")([^0-9]|$)"
        result = subprocess.run(["git", "-C", str(REPO_ROOT), "grep", "-n", "-E", pattern],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(result.stdout, "")
        for number in numbers:
            with self.subTest(number):
                self.assertEqual(
                    sorted((REPO_ROOT / "docs/areas/verification/adr").glob(f"{number}-*.md")), [])

    def test_the_cache_proxy_readme_names_the_boot_daemon(self):
        doc = self.doc("home/common/claude-code/README.md")
        self.assertIn("org.nixos.claude-cache-proxy", doc)
        self.assertIn("ownerServices.atBoot", doc)

    def test_the_claude_code_readme_names_the_settings_switch_as_the_one_source_of_attribution(self):
        path = "home/common/claude-code/README.md"
        doc = self.doc(path)
        raw = (REPO_ROOT / path).read_text(encoding="utf-8")
        self.assertIn("Attribution has one source: the generated settings' `attribution`", doc)
        self.assertIn("nothing reads the contract's retired co-author member (#1449)", doc)
        self.assertNotIn("co_authored_by", raw)
        settings = markdown_section(raw, "Settings")
        self.assertIn("Attribution has one source: the generated settings' `attribution`", settings)
        self.assertIn("`attribution` is the one configuration setting for Claude Code's automatic "
                      "attribution", re.sub(r"\s+", " ", settings))
        self.assertIn("The two delivery programs tell their agents separately to omit commit "
                      "trailers", re.sub(r"\s+", " ", settings))
        self.assertNotIn("delivery program decides it", doc)

    def test_the_owner_port_peer_decision_is_recorded(self):
        context = (REPO_ROOT / "docs/areas/console/CONTEXT.md").read_text().splitlines()
        console = next(row for row in context if row.startswith("The per-host loopback service"))
        self.assertIn("ADR-console-076", console)
    def test_the_guest_door_and_owner_port_records_name_no_private_host_data(self):
        adr_dir = REPO_ROOT / "docs/areas/console/adr"
        for pattern in ("066-*.md", "076-*.md"):
            with self.subTest(pattern=pattern):
                found = sorted(adr_dir.glob(pattern))
                self.assertEqual(len(found), 1, found)
                raw = found[0].read_text()
                self.assertEqual(tailnet_names_other_than_placeholder(raw), [])
                self.assertEqual(logins_in(raw), [])
                self.assertEqual(
                    re.findall(r"\buid[ =:]*\d+|/(?:Users|home)/[\w.-]+", raw), [])
        context = self.doc("docs/areas/console/CONTEXT.md")
        for term in ("**Console**:", "**Guest**:"):
            entry = context.split(term, 1)[1].split("_Avoid_", 1)[0]
            self.assertIn("ADR-console-066", entry)

    def test_the_guest_socket_amendment_is_recorded_as_adr_077(self):
        adr_dir = REPO_ROOT / "docs/areas/console/adr"
        found = sorted(adr_dir.glob("077-*.md"))
        self.assertEqual(len(found), 1, found)
        raw = found[0].read_text()
        text = re.sub(r"\s+", " ", raw)
        self.assertTrue(raw.splitlines()[0].startswith("# ADR-console-077 \u2014 "))
        for needle in (
            "- **Status:** accepted", "- **Decided in:** #1298, #1299", "ADR-console-066",
            "ADR-console-076",
            "eleven-m5", "Unix socket", "mode-0700", "peer user", "second line", "administrator",
            "sudo tailscale serve --bg --https=443 unix:<socket-path>", "tailscale serve status",
            "sudo tailscale serve --https=443 off", "<host>.<tailnet>.ts.net", "<colleague-login>",
            "tailscaled", "console-guest-door", "Funnel", "D2", "tailscale.exe",
        ):
            with self.subTest(needle):
                self.assertIn(needle, text)
        self.assertEqual(tailnet_names_other_than_placeholder(text), [])
        self.assertEqual(logins_in(text), [])
        d2 = text.split("**D2.", 1)[1].split("**D3.", 1)[0]
        for needle in ("admits only root", "the owner's own user",
                       "Any other peer is refused before a request is read"):
            with self.subTest(d2=needle):
                self.assertIn(needle, d2)
        d4 = text.split("**D4.", 1)[1].split("**D5.", 1)[0]
        for needle in ("first bullet of ADR-console-0" "66 D2", "superseded", "stand unchanged",
                       "19 Nov", "exactly `localhost`", "exactly one `X-Forwarded-Host`",
                       "no port form", "the login check stays as it is", "mode 0600", "wider",
                       "fail closed"):
            with self.subTest(d4=needle):
                self.assertIn(needle, d4)
        context = self.doc("docs/areas/console/CONTEXT.md")
        guest = context.split("**Guest**:", 1)[1].split("_Avoid_", 1)[0]
        self.assertNotIn("not yet built", guest)
        self.assertIn("ADR-console-077", guest)
        console = context.split("**Console**:", 1)[1].split("_Avoid_", 1)[0]
        self.assertIn("ADR-console-077", console)
        self.assertNotIn("guest port", console)

    def test_the_tailnet_name_source_is_recorded_as_adr_078(self):
        adr_dir = REPO_ROOT / "docs/areas/console/adr"
        found = sorted(adr_dir.glob("078-*.md"))
        self.assertEqual(len(found), 1, found)
        raw = found[0].read_text()
        text = re.sub(r"\s+", " ", raw)
        self.assertTrue(raw.splitlines()[0].startswith("# ADR-console-078 \u2014 "))
        for needle in (
            "- **Status:** accepted", "- **Decided in:** #1305", "ADR-console-066",
            "ADR-console-077", "D4", "tailscale status --json", "Self", "DNSName",
            "trailing dot", "lowercased", "one-minute", "in memory", "never in the log",
            "fail closed", "name_unread", '{"shared": true}', "bad sharing", "sharing.tailnet",
            "never used for admission", "<host>.<tailnet>.ts.net", "19 Nov",
        ):
            with self.subTest(needle):
                self.assertIn(needle, text)
        self.assertEqual(tailnet_names_other_than_placeholder(text), [])
        self.assertEqual(logins_in(text), [])
        d3 = text.split("**D3.", 1)[1].split("**D4.", 1)[0]
        for needle in ("refuses every request", "fail closed"):
            with self.subTest(d3=needle):
                self.assertIn(needle, d3)
        d2 = text.split("**D2.", 1)[1].split("**D3.", 1)[0]
        self.assertIn("amends ADR-console-077 D4", d2)
        row = next(r for r in (adr_dir / "077-the-guest-door-on-eleven-m5-is-a-unix-socket-only-"
                               "serve-and-the-owner-can-open.md").read_text().splitlines()
                   if r.startswith("- **Status:**"))
        self.assertEqual(row, "- **Status:** accepted; amended by ADR-console-078, ADR-console-079")
        context = self.doc("docs/areas/console/CONTEXT.md")
        guest = context.split("**Guest**:", 1)[1].split("_Avoid_", 1)[0]
        self.assertIn("ADR-console-078", guest)
        self.assertIn("read from this host's Tailscale client", guest)

    def test_the_access_rule_amendment_is_recorded_as_adr_079(self):
        adr_dir = REPO_ROOT / "docs/areas/console/adr"
        found = sorted(adr_dir.glob("079-*.md"))
        self.assertEqual(len(found), 1, found)
        raw = found[0].read_text()
        self.assertEqual(tailnet_names_other_than_placeholder(raw), [])
        self.assertEqual(logins_in(raw), [])
        self.assertEqual(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", raw), [])
        self.assertEqual(
            re.findall(r"(?<![\w:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])", raw), [])

    def test_sharing_sources_and_fixtures_name_only_placeholder_tailnets_and_logins(self):
        sources = sorted({
            *(REPO_ROOT / "tests").glob("test_console_guest*.py"),
            REPO_ROOT / "tests/console_screenshots.py",
            REPO_ROOT / "tests/test_console_screenshots.py",
            REPO_ROOT / "tests/test_console_serve_probe_check.py",
            REPO_ROOT / "python/agent_tools/console/guest.py",
            REPO_ROOT / "python/agent_tools/console/serve_probe_check.py"})
        self.assertGreaterEqual(len(sources), 6, sources)
        for source in sources:
            text = source.read_text()
            with self.subTest(source=source.name):
                self.assertEqual(
                    [name for name in tailnet_names_other_than_placeholder(text)
                     if name not in (INVENTED_TAILNET, ".ts.net")
                     and not name.endswith("." + INVENTED_TAILNET)], [])
                self.assertEqual(
                    [login for login in logins_in(text) if not login.lower().endswith(".invalid")],
                    [])

    def test_the_tailnet_name_check_flags_a_real_name_behind_a_placeholder_label(self):
        self.assertEqual(
            tailnet_names_other_than_placeholder(
                "[<host>.<tailnet>.ts.net](https://box.tail1234.ts.net/) and `<host>.<tailnet>.ts.net`"),
            ["box.tail1234.ts.net"])
        self.assertEqual(
            tailnet_names_other_than_placeholder("at https://<host>.<tailnet>.ts.net/ only"), [])
        self.assertEqual(tailnet_names_other_than_placeholder("see box.tail1234.ts.net."),
                         ["box.tail1234.ts.net"])

    def test_the_login_check_flags_a_literal_login_beside_the_placeholder(self):
        self.assertEqual(logins_in("names a listed colleague (`<colleague-login>`) only"), [])
        self.assertEqual(
            logins_in("names `<colleague-login>`, for example Jane.Doe@example.com, only"),
            ["Jane.Doe@example.com"])

    def test_the_console_approval_decision_is_recorded(self):
        self.assertIn("**Approved adoption**", self.doc("docs/areas/console/CONTEXT.md"))
    def test_the_merged_adoption_registration_decision_is_recorded(self):
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("**Merged adoption**:", context)
        self.assertIn("| Approved adoption | Console |", self.doc("docs/CONTEXT-MAP.md"))
    def test_the_apply_card_decision_is_recorded(self):
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("choosing `Apply it`", context)
    def test_the_console_page_signin_decision_is_recorded(self):
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("Sign in again", context)
        self.assertIn("ADR-console-024", context)
        self.assertIn("Sign in action", context)
        self.assertNotIn("gives the command to sign in again", context)
    def test_the_console_add_account_decision_is_recorded(self):
        self.assertIn("claude-account add", self.doc("docs/areas/hosts/CONTEXT.md"))
    def test_the_sign_in_route_decision_is_recorded_as_adr_080(self):
        adr_dir = REPO_ROOT / "docs/areas/console/adr"
        adrs = sorted(adr_dir.glob("080-*.md"))
        self.assertEqual(len(adrs), 1)
        numbers = [int(n) for n in re.findall(r"ADR-console-(\d+)",
                                              adrs[0].read_text().splitlines()[0])]
        self.assertEqual(numbers, [80])

    def test_the_register_project_decision_is_recorded(self):
        self.assertIn("| Registration | Console |", self.doc("docs/CONTEXT-MAP.md"))
        self.assertIn("ADR-console-028", self.doc("docs/areas/console/CONTEXT.md"))
    def test_the_project_question_decision_is_recorded(self):
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("**Project question**:", context)
        self.assertIn("ADR-console-058", context)
        self.assertIn("| Project question | Console |", self.doc("docs/CONTEXT-MAP.md"))
        self.assertEqual(len(list((REPO_ROOT / "docs/areas/console/adr").glob("058-*.md"))), 1)
    def test_the_plan_answer_decision_is_recorded(self):
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("ADR-console-029", context)
        self.assertIn("**Plan question**:", context)
        self.assertIn("| Plan question | Console |", self.doc("docs/CONTEXT-MAP.md"))
    def test_the_console_goal_decision_is_recorded(self):
        context = self.doc("docs/areas/console/CONTEXT.md")
        for needle in ("**Sprint**", "**Goal**"):
            self.assertIn(needle, context)
    def test_the_console_report_decision_is_recorded(self):
        context = self.doc("docs/areas/console/CONTEXT.md")
        for needle in ("**Manager**", "**Report**"):
            self.assertIn(needle, context)
        context_map = self.doc("docs/CONTEXT-MAP.md")
        for needle in ("| Manager | Console |", "| Report | Console |"):
            self.assertIn(needle, context_map)
    def test_the_console_glossary_names_the_message_life(self):
        context = self.doc("docs/areas/console/CONTEXT.md")
        for needle in ("A brief approval shows only until the manager picks it up",
                       "as the manager's own line, with no approval line above it",
                       "built from its report's milestone and its issues' stages",
                       "its status line first"):
            self.assertIn(needle, context)

    def test_the_guard_context_separates_the_base_and_the_compiled_policy(self):
        text = self.doc("docs/areas/guard/CONTEXT.md")
        self.assertNotIn("The base policy plus one derived row", text)
        self.assertIn("none of the base policy's members", text)

    def test_the_verification_context_names_every_kind_of_check(self):
        text = self.doc("docs/areas/verification/CONTEXT.md")
        self.assertNotIn("One named, read-only test", text)
        for word in ("built-in probe", "question or action for the owner", "unattended"):
            self.assertIn(word, text)

    def test_an_adr_number_is_used_once_within_its_area(self):
        for area in sorted((REPO_ROOT / "docs/areas").iterdir()):
            seen: dict[str, str] = {}
            for adr in sorted((area / "adr").glob("[0-9][0-9][0-9]-*.md")):
                number = adr.name[:3]
                with self.subTest(area=area.name, number=number):
                    self.assertNotIn(number, seen, f"{seen.get(number)} and {adr.name}")
                seen[number] = adr.name

    def test_each_formerly_pinned_record_number_names_one_file(self):
        adr_dir = REPO_ROOT / "docs/areas/console/adr"
        pinned = {
            "050": None,
            "059": "059-a-project-question-is-spent-under-its-project-threaded-in-the-log-and-can-fill-a-goal.md",
            "062": "062-a-follow-up-carries-its-thread-in-its-prompt-and-continues-only-an-answered-thread.md",
            "065": "065-a-question-session-reads-the-projects-history-tracker-and-live-state-and-answers-plainly.md",
            "066": None,
            "067": None,
            "068": None,
            "070": None,
            "073": None,
            "075": None,
        }
        for number, name in pinned.items():
            with self.subTest(number):
                found = sorted(adr_dir.glob(f"{number}-*.md"))
                self.assertEqual(len(found), 1, found)
                if name is not None:
                    self.assertEqual(found[0].name, name)

    def test_every_release_record_keeps_the_record_form(self):
        paths = sorted((REPO_ROOT / "docs/areas/release/adr").glob("*.md"))

        breaches = {}
        for path in paths:
            relative = path.relative_to(REPO_ROOT).as_posix()
            found = record_violations(relative, path.read_bytes())
            if found:
                breaches[relative] = [violation.rule for violation in found]

        self.assertEqual(
            [path.name[:3] for path in paths],
            ["002", "003", "005", "006", "007", "008", "010", "011", "012", "013", "015", "016"],
        )
        self.assertEqual(breaches, {})

    def test_no_tracked_file_cites_a_retired_release_record(self):
        numbers = ("001", "004", "009", "014")
        # Built at run time so this file holds no retired citation itself.
        pattern = "ADR-release-(" + "|".join(numbers) + ")([^0-9]|$)"

        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "grep", "-n", "-E", pattern],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(result.stdout, "")
        for number in numbers:
            with self.subTest(number):
                found = sorted((REPO_ROOT / "docs/areas/release/adr").glob(f"{number}-*.md"))
                self.assertEqual(found, [])

    def test_the_question_round_names_taking_back_and_replacing_a_question(self):
        context = self.doc("docs/areas/console/CONTEXT.md")
        entry = context.split("**Question round**:", 1)[1].split("_Avoid_:", 1)[0]
        self.assertIn("A manager takes back its own open question with `sprint withdraw-question`, "
                      "or replaces it by naming it in a new round, and the owner then sees only "
                      "the new card; an answer to a question taken back is refused "
                      "(ADR-console-019).", entry)
    def test_the_notice_decision_is_recorded(self):
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("**Notice**:", context)
        notice = context.split("**Notice**:", 1)[1].split("_Avoid_:", 1)[0]
        self.assertIn("ADR-console-044", notice)

    def test_no_tracked_file_cites_a_retired_guard_record(self):
        # The pattern is built at run time, so this file holds no retired citation itself.
        numbers = ("005", "011", "012")
        pattern = "ADR-guard-(" + "|".join(numbers) + ")([^0-9]|$)"
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "grep", "-n", "-E", pattern],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(result.stdout, "")
        for number in numbers:
            with self.subTest(number):
                self.assertEqual(sorted((REPO_ROOT / "docs/areas/guard/adr").glob(f"{number}-*.md")), [])


if __name__ == "__main__":
    unittest.main()
