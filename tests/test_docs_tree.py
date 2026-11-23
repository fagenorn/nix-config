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
        path = "docs/areas/console/adr/076-the-owners-port-answers-only-the-owners-own-processes.md"
        adr008 = "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md"
        admin = ("An administrator (sudo) or root can always act as the owner, and this record "
                 "does not claim to stop one.")
        relay = ("Any relay the owner runs on this host, such as an `ssh -L` or `-D` forward or "
                 "`socat`, admits whoever reaches it, because the console sees only the owner's "
                 "own process holding the connection.")
        shared = ("A descriptor an owner process hands to another user's process, by descriptor "
                  "passing or across a set-user-ID program, is seen only through the owner's "
                  "holder, so it is a relay of the same kind.")
        raw = (REPO_ROOT / path).read_text()
        text = re.sub(r"\s+", " ", raw)
        self.assertEqual(raw.splitlines()[0], "# ADR-console-076 \u2014 The owner's port answers "
                                              "only the owner's own processes")
        for needle in ("- **Status:** accepted", "- **Decided in:** #1294", "ADR-console-008",
                       "ADR-console-066", admin, relay, shared, "sshd-session", "lsof",
                       "/proc/net/tcp", "fails closed", "console: peer_refused",
                       "console-owner-port", "mode-0700"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        d6 = next(re.sub(r"\s+", " ", para) for para in raw.split("\n\n")
                  if para.startswith("**D6."))
        self.assertIn(admin, d6)
        self.assertIsNone(re.search(r"(?i)(stops|prevents|blocks|refuses) (an|any|every) "
                                    r"administrator", text))
        lines = (REPO_ROOT / adr008).read_text().splitlines()
        status = next(row for row in lines if row.startswith("- **Status:**"))
        self.assertEqual(
            status, "- **Status:** accepted; amended by ADR-console-024, ADR-console-025, "
                    "ADR-console-028, ADR-console-029, ADR-console-030, ADR-console-036, "
                    "ADR-console-037, ADR-console-053, ADR-console-058, ADR-system-004, "
                    "ADR-console-076, ADR-console-078, ADR-console-093")
        decided = next(row for row in lines if row.startswith("- **Decided in:**"))
        self.assertTrue(decided.endswith("#1237, #1263, #1294, #1305, #1272"))
        context = (REPO_ROOT / "docs/areas/console/CONTEXT.md").read_text().splitlines()
        console = next(row for row in context if row.startswith("The per-host loopback service"))
        self.assertIn("ADR-console-076", console)

    def test_the_tailscale_serve_boundary_decision_is_recorded(self):
        adr_dir = REPO_ROOT / "docs/areas/console/adr"
        found = sorted(adr_dir.glob("066-*.md"))
        self.assertEqual(len(found), 1, found)
        path = "docs/areas/console/adr/" + found[0].name
        text = (REPO_ROOT / path).read_text()
        self.assertTrue(text.splitlines()[0].startswith("# ADR-console-066 \u2014 "))
        self.assertIn("- **Status:** accepted", text)
        for needle in (
            "#1235", "ADR-console-008", "Tailscale-User-Login", "X-Forwarded-For",
            "mirrored", "guest port", "guest token", "Funnel",
            "Confirming a release", "spend", "project registration", "the access list",
            "every manager route",
            "tailscale.exe", "serve --bg --https=443", "serve status", "--https=443 off",
            "<host>.<tailnet>.ts.net", "<colleague-login>",
        ):
            self.assertIn(needle, text)
        self.assertEqual(tailnet_names_other_than_placeholder(text), [])
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
        for needle in ("first bullet of ADR-console-066 D2", "superseded", "stand unchanged",
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
        status = next(row for row in (adr_dir / "066-a-named-colleague-reaches-the-console-only-"
                                      "through-tailscale-serve-on-a-guest-port.md"
                                      ).read_text().splitlines() if row.startswith("- **Status:**"))
        self.assertTrue(status.startswith(
            "- **Status:** accepted; amended by ADR-console-077, ADR-console-086"), status)

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
        path = ("docs/areas/console/adr/"
                "030-the-owner-approves-a-ready-adoption-and-the-console-opens-its-pull-request.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first,
            "# ADR-console-030 — The owner approves a ready adoption on the page and the console "
            "opens its pull request")
        adr = self.doc(path)
        for needle in ("POST /api/plan-approve", "bad plan approval", "--acknowledge-deletions",
                       "--no-follow-tags", "mergeable_state", "unstable", "find_pull_request",
                       "adoption.step", "adoption.pull_request", "never merges", "ADR-console-008",
                       "ADR-console-029", "ADR-project-contract-004", "#1054"):
            self.assertIn(needle, adr)
        for older, needle in (
                ("docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md",
                 "POST /api/plan-approve"),
                ("docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md",
                 "ADR-console-030"),
                ("docs/areas/console/adr/028-the-owner-registers-a-project-from-the-page.md",
                 "ADR-console-030"),
                ("docs/areas/console/adr/029-the-owner-answers-the-adoptions-questions-on-the-page.md",
                 "ADR-console-030")):
            self.assertIn(needle, self.doc(older))
        self.assertIn("**Approved adoption**", self.doc("docs/areas/console/CONTEXT.md"))

    def test_the_merged_adoption_registration_decision_is_recorded(self):
        adr = self.doc("docs/areas/console/adr/028-the-owner-registers-a-project-from-the-page.md")
        approval = self.doc(
            "docs/areas/console/adr/"
            "030-the-owner-approves-a-ready-adoption-and-the-console-opens-its-pull-request.md")
        writes = self.doc(
            "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md")
        context = self.doc("docs/areas/console/CONTEXT.md")
        for needle in ("**D10.", "**D11.", "#1055", "POST /api/adoption-register",
                       "bad registration retry", "that registration is not waiting for a retry",
                       "adoption.registration", "not_integrated", "ADR-project-contract-005",
                       "Retry", "was registered.", "ADR-console-029", "ADR-console-030", "#1066"):
            self.assertIn(needle, adr)
        self.assertIn("ADR-console-028 D10", approval)
        self.assertNotIn("already merged; register the repository again", approval)
        self.assertIn("POST /api/adoption-register", writes)
        self.assertIn("**Merged adoption**:", context)
        self.assertIn("| Approved adoption | Console |", self.doc("docs/CONTEXT-MAP.md"))

    def test_the_apply_card_decision_is_recorded(self):
        approval = self.doc(
            "docs/areas/console/adr/"
            "030-the-owner-approves-a-ready-adoption-and-the-console-opens-its-pull-request.md")
        answers = self.doc(
            "docs/areas/console/adr/029-the-owner-answers-the-adoptions-questions-on-the-page.md")
        writes = self.doc(
            "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md")
        context = self.doc("docs/areas/console/CONTEXT.md")
        for needle in ("#1073", "**D11.", "Apply this adoption?", "Apply it", "Apply it again",
                       "Try again", "Not now", "POST /api/plan-defer", "bad plan deferral",
                       "that plan is no longer the one shown",
                       "that plan is not waiting for an answer", "adoption.deferred",
                       "without pushing again", "register_apply"):
            self.assertIn(needle, approval)
        for gone in ("shows Approve", "the Approve button"):
            self.assertNotIn(gone, approval)
        self.assertNotIn("Approve button", answers)
        self.assertIn("ADR-console-030 D9", answers)
        self.assertIn("POST /api/plan-defer", writes)
        self.assertIn("ADR-console-030 D11", writes)
        self.assertIn("choosing `Apply it`", context)

    def test_the_console_page_signin_decision_is_recorded(self):
        path = "docs/areas/console/adr/024-the-owner-signs-a-profile-in-from-the-page.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-024 — The owner signs a profile in from the page")
        adr = self.doc(path)
        for needle in ("POST /api/signin", "POST /api/signin-code", "POST /api/signin-cancel",
                       "claude-account run auth login", "BROWSER", "600", "signin.acted",
                       "signin.ended", "attempt", "ADR-console-002", "ADR-console-008",
                       "ADR-console-022", "#1026", "#894", "POST /api/signin-link", "#1035",
                       "Sign in again", "bad link", "changed while waiting for its link"):
            self.assertIn(needle, adr)
        self.assertIn("/api/signin-link", self.doc(
            "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md"))
        self.assertIn("Sign in again", self.doc("docs/areas/console/CONTEXT.md"))
        for older in ("docs/areas/console/adr/002-the-desk-page-design-rules.md",
                      "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md",
                      "docs/areas/console/adr/022-a-profiles-sign-in-is-read-from-the-clients-status-command.md",
                      "docs/areas/console/CONTEXT.md"):
            self.assertIn("ADR-console-024", self.doc(older))
        self.assertNotIn("the command to run in a terminal", self.doc(
            "docs/areas/console/adr/002-the-desk-page-design-rules.md"))
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("Sign in action", context)
        self.assertNotIn("gives the command to sign in again", context)

    def test_the_console_add_account_decision_is_recorded(self):
        path = "docs/areas/console/adr/025-the-owner-adds-an-account-from-the-page.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-025 — The owner adds an account from the page")
        adr = self.doc(path)
        for needle in ("POST /api/account-add", "claude-account add", "account.added",
                       "accounts_added", "409", "bad account", "default", "0700",
                       "ADR-console-002", "ADR-console-008", "ADR-console-022",
                       "ADR-console-024", "ADR-hosts-005", "#1027", "#894", "#1035", "outcome",
                       "ADR-console-024 D1"):
            self.assertIn(needle, adr)
        for older in ("docs/areas/console/adr/002-the-desk-page-design-rules.md",
                      "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md",
                      "docs/areas/console/adr/024-the-owner-signs-a-profile-in-from-the-page.md",
                      "docs/areas/console/CONTEXT.md",
                      "docs/areas/hosts/CONTEXT.md"):
            self.assertIn("ADR-console-025", self.doc(older))
        self.assertIn("claude-account add", self.doc("docs/areas/hosts/CONTEXT.md"))
        self.assertIn("POST /api/account-add", self.doc(
            "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md"))
        both = ("- **Status:** accepted; amended by ADR-console-024, ADR-console-025, "
                "ADR-console-028")
        for older, status in (
                ("docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md",
                 both + ", ADR-console-029, ADR-console-030, ADR-console-036, "
                         "ADR-console-037, ADR-console-053, ADR-console-058, ADR-system-004, "
                         "ADR-console-076, ADR-console-078, ADR-console-093"),
                ("docs/areas/console/adr/002-the-desk-page-design-rules.md",
                 both + ", ADR-console-029, ADR-console-031, ADR-console-032, ADR-console-033, "
                 "ADR-console-035, ADR-console-038, ADR-console-052, ADR-console-056, ADR-console-064, "
                 "ADR-console-086"),
                ("docs/areas/console/adr/024-the-owner-signs-a-profile-in-from-the-page.md",
                 "- **Status:** accepted; amended by ADR-console-025, ADR-console-075, "
                 "ADR-console-080")):
            line = next(row for row in (REPO_ROOT / older).read_text().splitlines()
                        if row.startswith("- **Status:**"))
            self.assertEqual(line, status)

    def test_the_sign_in_route_decision_is_recorded_as_adr_080(self):
        adr_dir = REPO_ROOT / "docs/areas/console/adr"
        adrs = sorted(adr_dir.glob("080-*.md"))
        self.assertEqual(len(adrs), 1)
        numbers = [int(n) for n in re.findall(r"ADR-console-(\d+)",
                                              adrs[0].read_text().splitlines()[0])]
        self.assertEqual(numbers, [80])
        for older in ("024-the-owner-signs-a-profile-in-from-the-page.md",
                      "025-the-owner-adds-an-account-from-the-page.md"):
            status = next(row for row in (adr_dir / older).read_text().splitlines()
                          if row.startswith("- **Status:**"))
            amenders = [int(n) for n in re.findall(r"ADR-console-(\d+)", status)]
            self.assertIn(80, amenders)

    def test_the_register_project_decision_is_recorded(self):
        path = "docs/areas/console/adr/028-the-owner-registers-a-project-from-the-page.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-028 — The owner registers a project from the page")
        adr = self.doc(path)
        for needle in ("POST /api/register-project", "PAGE_WRITES", "bad registration", "409",
                       "204", "registration.ended", "registration", "adopt-project plan",
                       "adopt-project verify --register", "no_change", "migration_required",
                       "repair_required", "draft", "300", "not the top of a git checkout",
                       "already registered", "a registration is already running",
                       "ADR-console-002", "ADR-console-008", "ADR-project-contract-004",
                       "ADR-project-contract-005", "#1052",
                       "it has no agent files or project contract yet",
                       "it has agent files or a contract to bring up to date"):
            self.assertIn(needle, adr)
        self.assertIn("| Registration | Console |", self.doc("docs/CONTEXT-MAP.md"))
        adr008 = "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md"
        adr002 = "docs/areas/console/adr/002-the-desk-page-design-rules.md"
        for older in (adr008, adr002, "docs/areas/console/CONTEXT.md"):
            self.assertIn("ADR-console-028", self.doc(older))
        self.assertIn("POST /api/register-project", self.doc(adr008))
        status = ("- **Status:** accepted; amended by ADR-console-024, ADR-console-025, "
                  "ADR-console-028")
        for older, expected in ((adr008, status + ", ADR-console-029, ADR-console-030, "
                                          "ADR-console-036, ADR-console-037, ADR-console-053, "
                                          "ADR-console-058, ADR-system-004, ADR-console-076, ADR-console-078, "
                                          "ADR-console-093"),
                                (adr002, status + ", ADR-console-029, ADR-console-031, "
                                          "ADR-console-032, ADR-console-033, ADR-console-035, "
                                          "ADR-console-038, ADR-console-052, ADR-console-056, ADR-console-064, "
                                          "ADR-console-086")):
            line = next(row for row in (REPO_ROOT / older).read_text().splitlines()
                        if row.startswith("- **Status:**"))
            self.assertEqual(line, expected)

    def test_the_project_question_decision_is_recorded(self):
        path = ("docs/areas/console/adr/"
                "058-a-question-about-a-project-is-answered-by-a-read-only-session.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-058 \u2014 A question about a project is "
                                "answered by a read-only session")
        adr = self.doc(path)
        for needle in ("#1176", "POST /api/project-question", "PAGE_WRITES",
                       "project_question.asked", "project_question.answered", "timed_out",
                       "--model sonnet", "not enforced", "onFailure", "dontAsk",
                       "--setting-sources", "--tools", "300", "production.read_only.commands",
                       "project_question_hook",
                       "Production cannot be read for this project", "ADR-console-008",
                       "ADR-console-011", "ADR-console-023", "ADR-guard-009"):
            self.assertIn(needle, adr)
        adr008 = self.doc(
            "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md")
        self.assertIn("POST /api/project-question", adr008)
        self.assertIn("ADR-console-058", adr008)
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("**Project question**:", context)
        self.assertIn("ADR-console-058", context)
        self.assertIn("| Project question | Console |", self.doc("docs/CONTEXT-MAP.md"))
        self.assertEqual(len(list((REPO_ROOT / "docs/areas/console/adr").glob("058-*.md"))), 1)

    def test_the_plan_answer_decision_is_recorded(self):
        path = ("docs/areas/console/adr/"
                "029-the-owner-answers-the-adoptions-questions-on-the-page.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first,
                         "# ADR-console-029 — The owner answers the adoption's questions on the page")
        adr = self.doc(path)
        for needle in ("POST /api/plan-answer", "PAGE_WRITES", "bad plan answer", "409", "204",
                       "4096", "300", "registration.ended", "--answer",
                       "adopt.decisions.invalid_answer", "adopt.decisions.unmatched_answer",
                       "The plan refused that answer", "The plan was not made again",
                       "cannot be answered here", "that plan is no longer the one shown",
                       "again with your answer", "adopt-project apply --plan-id",
                       "needs no adoption change and is not registered yet",
                       "console: plan_answer_error", "ADR-console-002", "ADR-console-008",
                       "ADR-console-028", "ADR-project-contract-004", "#1053"):
            self.assertIn(needle, adr)
        adr008 = "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md"
        adr028 = "docs/areas/console/adr/028-the-owner-registers-a-project-from-the-page.md"
        for needle in ("POST /api/plan-answer", "ADR-console-029"):
            self.assertIn(needle, self.doc(adr008))
        self.assertIn("ADR-console-029", self.doc(adr028))
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("ADR-console-029", context)
        self.assertIn("**Plan question**:", context)
        self.assertIn("| Plan question | Console |", self.doc("docs/CONTEXT-MAP.md"))
        for older, expected in (
                (adr008, "- **Status:** accepted; amended by ADR-console-024, ADR-console-025, "
                         "ADR-console-028, ADR-console-029, ADR-console-030, ADR-console-036, "
                         "ADR-console-037, ADR-console-053, ADR-console-058, ADR-system-004, "
                         "ADR-console-076, ADR-console-078, ADR-console-093"),
                (adr028, None)):
            line = next(row for row in (REPO_ROOT / older).read_text().splitlines()
                        if row.startswith("- **Status:**"))
            if expected is not None:
                self.assertEqual(line, expected)
                continue
            lead = "- **Status:** accepted; amended by "
            self.assertTrue(line.startswith(lead))
            amenders = line[len(lead):].split(";")[0].split(", ")
            self.assertIn("ADR-console-029", amenders)

    def test_the_console_answer_decision_is_recorded(self):
        path = "docs/areas/console/adr/010-the-page-answers-a-decision-prompt-by-ticking-it-as-the-owner.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first, "# ADR-console-010 — The page answers a decision prompt by ticking its box as the owner")
        adr = self.doc(path)
        for needle in ("POST /api/answer", "ADR-console-008", "#836", "#838", "#862",
                       "five seconds", "rec=", "nothing is copied"):
            self.assertIn(needle, adr)
        write = self.doc("docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md")
        for needle in ("/api/answer", "4096"):
            self.assertIn(needle, write)

    def test_the_console_goal_decision_is_recorded(self):
        path = "docs/areas/console/adr/011-a-goal-stated-on-the-page-becomes-a-sprint.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-011 — A goal stated on the page becomes a sprint")
        adr = self.doc(path)
        for needle in ("POST /api/goal", "POST /api/withdraw", "ADR-console-008",
                       "ADR-console-009", "#834", "#838", "#886", "2000", "sprint-secrets",
                       "never on the tracker", "indefinitely", "no manager has picked this up",
                       "#911", "removes the refusal"):
            self.assertIn(needle, adr)
        write = self.doc("docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md")
        for needle in ("/api/goal", "/api/withdraw", "16384"):
            self.assertIn(needle, write)
        kept = self.doc("docs/areas/console/adr/009-events-are-kept-for-90-days.md")
        for needle in ("goal.stated", "goal.withdrawn", "schema 4"):
            self.assertIn(needle, kept)
        self.assertIn("except goal rows",
                      self.doc("docs/areas/console/adr/001-the-console-truth-is-an-append-only-event-log.md"))
        context = self.doc("docs/areas/console/CONTEXT.md")
        for needle in ("**Sprint**", "**Goal**"):
            self.assertIn(needle, context)

    def test_the_console_brief_decision_is_recorded(self):
        path = "docs/areas/console/adr/013-a-managers-brief-is-approved-or-redirected-on-the-page.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first, "# ADR-console-013 — A manager's brief is approved or redirected on the page")
        adr = self.doc(path)
        for needle in ("sprint brief", "sprint status", "POST /api/brief", "GET /api/sprint-status",
                       "POST /api/approve", "POST /api/reply", "ADR-console-008",
                       "ADR-console-009", "ADR-console-011", "#834", "#835", "#836", "#887",
                       "#911", "may be empty lists", "secret refused", "five seconds", "starting", "2000"):
            self.assertIn(needle, adr)
        write = self.doc("docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md")
        for needle in ("/api/approve", "/api/reply", "/api/brief"):
            self.assertIn(needle, write)
        kept = self.doc("docs/areas/console/adr/009-events-are-kept-for-90-days.md")
        for needle in ("brief.sent", "schema 4"):
            self.assertIn(needle, kept)
        rules = self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md")
        for needle in ("ADR-console-013", 'its label and "None"'):
            self.assertIn(needle, rules)

    def test_the_console_report_decision_is_recorded(self):
        path = "docs/areas/console/adr/014-a-managers-report-becomes-the-sprints-line.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first, "# ADR-console-014 — A manager's report becomes the sprint's line")
        adr = self.doc(path)
        for needle in ("sprint report", "POST /api/report", "secret refused", "waiting on you",
                       "may be stuck", "fifteen minutes", '"Show the report"', "closed out",
                       "ADR-console-005", "ADR-console-008", "ADR-console-009",
                       "ADR-console-013", "#835", "#837", "#838", "#890", "#1086",
                       "the view's and the digest's", "the status line opens first in"):
            self.assertIn(needle, adr)
        self.assertNotIn('"Detail" fold', adr)
        self.assertIn("as soon as it is found valid and before the phase", adr)
        self.assertNotIn("then a status line that names an issue number", adr)
        self.assertNotIn("only when the reported phase changes", adr)
        self.assertIn("/api/report",
                      self.doc("docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md"))
        kept = self.doc("docs/areas/console/adr/009-events-are-kept-for-90-days.md")
        for needle in ("sprint.reported", "schema 5"):
            self.assertIn(needle, kept)
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

    def test_the_console_message_decision_is_recorded(self):
        path = "docs/areas/console/adr/016-what-the-owner-says-to-a-sprint-reaches-its-manager.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first, "# ADR-console-016 — What the owner says to a sprint reaches its manager")
        adr = self.doc(path)
        for needle in ("sprint inbox", "sprint reply", "POST /api/message", "POST /api/inbox",
                       "POST /api/message-reply", "SendMessage", "--resume", "manager not reachable",
                       "schema 6", "ADR-console-008", "ADR-console-013", "ADR-console-015",
                       "#831", "#835", "#889"):
            self.assertIn(needle, adr)
        write = self.doc("docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md")
        for needle in ("/api/message", "/api/inbox", "/api/message-reply"):
            self.assertIn(needle, write)
        kept = self.doc("docs/areas/console/adr/009-events-are-kept-for-90-days.md")
        for needle in ("sprint.messaged", "schema 6", "questions.asked",
                       "question.answered", "schema 7", "schema 8"):
            self.assertIn(needle, kept)

    def test_the_console_question_decision_is_recorded(self):
        path = "docs/areas/console/adr/019-a-managers-questions-arrive-as-inbox-items.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-019 — A manager's questions arrive as inbox "
                                "items and are answered on the page")
        adr = self.doc(path)
        for needle in ("sprint ask", "POST /api/ask", "POST /api/round-answer",
                       "questions.asked", "question.answered", "schema 8", "blocker",
                       "may I proceed", "ADR-console-008", "ADR-console-016",
                       "#826", "#836", "#891"):
            self.assertIn(needle, adr)
        write = self.doc("docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md")
        for needle in ("/api/round-answer", "/api/ask"):
            self.assertIn(needle, write)

    def test_the_guard_context_separates_the_base_and_the_compiled_policy(self):
        text = self.doc("docs/areas/guard/CONTEXT.md")
        self.assertNotIn("The base policy plus one derived row", text)
        self.assertIn("none of the base policy's members", text)

    def test_the_verification_context_names_every_kind_of_check(self):
        text = self.doc("docs/areas/verification/CONTEXT.md")
        self.assertNotIn("One named, read-only test", text)
        for word in ("built-in probe", "question or action for the owner", "unattended"):
            self.assertIn(word, text)

    def test_adr_console_037_records_the_registration_details(self):
        path = ("docs/areas/console/adr/"
                "037-a-registrations-work-line-is-one-sentence-and-the-owner-can-cancel-it.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first,
            "# ADR-console-037 \u2014 A registration's Work line is one sentence, a failure's way "
            "out is an option, and the owner can cancel a registration")
        adr = self.doc(path)
        for needle in ("#1088", "--discard-retained", "adopt-project discard",
                       "git worktree prune", "POST /api/register-cancel",
                       "registration.cancelled", "Turn signed commits off",
                       "Run just switch on this computer to install them, then choose Try again.",
                       "ADR-console-035", "ADR-console-008"):
            self.assertIn(needle, adr)
        self.assertIn("/api/register-cancel", self.doc(
            "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md"))
        self.assertIn("amended by ADR-console-037", self.doc(
            "docs/areas/console/adr/035-every-registration-failure-is-a-counted-card-and-a-"
            "finished-registration-leaves-only-its-project.md"))

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
            "056": None,
            "057": None,
            "059": "059-a-project-question-is-spent-under-its-project-threaded-in-the-log-and-can-fill-a-goal.md",
            "061": None,
            "062": "062-a-follow-up-carries-its-thread-in-its-prompt-and-continues-only-an-answered-thread.md",
            "064": None,
            "065": "065-a-question-session-reads-the-projects-history-tracker-and-live-state-and-answers-plainly.md",
            "066": None,
            "067": None,
            "068": None,
            "069": None,
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

    def test_adr_console_040_records_taking_back_and_replacing_a_question(self):
        path = ("docs/areas/console/adr/"
                "040-a-manager-takes-back-or-replaces-its-own-open-question.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-040 \u2014 A manager takes back or replaces its own "
                                "open question")
        adr = self.doc(path)
        for needle in ("#1099", "question.withdrawn", "schema 9", "POST /api/withdraw-question",
                       '"replaces"', "the manager took this question back",
                       "this question belongs to another sprint", "counts from 0", "page.html",
                       "ADR-console-015", "ADR-console-019", "ADR-console-009"):
            with self.subTest(needle):
                self.assertIn(needle, adr)
        base = "docs/areas/console/adr/"

        def status(name):
            lines = (REPO_ROOT / base / name).read_text().splitlines()
            return next(r for r in lines if r.startswith("- **Status:**"))
        self.assertEqual(status("019-a-managers-questions-arrive-as-inbox-items.md"),
                         "- **Status:** accepted; amended by ADR-console-038, ADR-console-040, "
                         "ADR-console-072")
        self.assertEqual(status("009-events-are-kept-for-90-days.md"),
                         "- **Status:** accepted; amended by ADR-console-036, ADR-console-040, ADR-console-093")
        retention = self.doc(base + "009-events-are-kept-for-90-days.md")
        self.assertIn("schema 9", retention)
        self.assertIn("question.withdrawn", retention)
        self.assertIn("/api/withdraw-question", self.doc(
            base + "008-only-the-page-writes-with-a-token-and-its-origin.md"))
        context = self.doc("docs/areas/console/CONTEXT.md")
        entry = context.split("**Question round**:", 1)[1].split("_Avoid_:", 1)[0]
        self.assertIn("A manager takes back its own open question with `sprint withdraw-question`, "
                      "or replaces it by naming it in a new round, and the owner then sees only "
                      "the new card; an answer to a question taken back is refused "
                      "(ADR-console-040).", entry)

    def test_the_notice_decision_is_recorded(self):
        path = ("docs/areas/console/adr/"
                "044-a-manager-posts-lists-and-withdraws-short-notices-for-its-project.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-044 \u2014 A manager posts, lists and withdraws "
                                "short notices for its project")
        adr = self.doc(path)
        for needle in ("notice.posted", "notice.withdrawn", "schema 10", "POST /api/notice",
                       "POST /api/notices", "POST /api/withdraw-notice", "280", "200", "140",
                       "never approval", "ADR-console-008", "ADR-console-009",
                       "ADR-console-019", "#1117"):
            with self.subTest(needle):
                self.assertIn(needle, adr)
        base = "docs/areas/console/adr/"
        self.assertIn("POST /api/withdraw-notice", self.doc(
            base + "008-only-the-page-writes-with-a-token-and-its-origin.md"))
        self.assertIn("ADR-console-044", self.doc(
            base + "008-only-the-page-writes-with-a-token-and-its-origin.md"))
        self.assertIn("schema 10", self.doc(base + "009-events-are-kept-for-90-days.md"))
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("**Notice**:", context)
        notice = context.split("**Notice**:", 1)[1].split("_Avoid_:", 1)[0]
        self.assertIn("ADR-console-044", notice)

    def test_the_owner_notice_decision_is_recorded(self):
        base = "docs/areas/console/adr/"
        path = (base + "053-the-owner-posts-and-withdraws-a-notice-to-every-manager-of-a-"
                "project.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-053 \u2014 The owner posts and withdraws a notice "
                                "to every manager of a project")
        adr = self.doc(path)
        for needle in ("#1120", '"poster": "owner"', "POST /api/owner-notice",
                       "POST /api/owner-notice-withdraw", "280", "5",
                       "heads-up from the owner", "notice.nudged", "never approval",
                       "ADR-console-008", "ADR-console-016", "ADR-console-044",
                       "ADR-console-046"):
            with self.subTest(needle):
                self.assertIn(needle, adr)
        adr008 = self.doc(base + "008-only-the-page-writes-with-a-token-and-its-origin.md")
        self.assertIn("POST /api/owner-notice-withdraw", adr008)
        self.assertIn("ADR-console-053", adr008)
        self.assertIn("amended by ADR-console-053", self.doc(
            base + "044-a-manager-posts-lists-and-withdraws-short-notices-for-its-project.md"))
        self.assertIn("amended by ADR-console-053", self.doc(
            base + "046-the-notice-board-shows-each-manager-its-projects-open-notices-and-never-"
            "approves-anything.md"))
        self.assertIn("Post a notice", self.doc(base + "002-the-desk-page-design-rules.md"))
        context = self.doc("docs/areas/console/CONTEXT.md")
        notice = context.split("**Notice**:", 1)[1].split("_Avoid_:", 1)[0]
        self.assertIn("ADR-console-053", notice)

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
