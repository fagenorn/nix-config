import json
import math
import os
import re
import statistics
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

LAND_QUEUE_DOC = "docs/archive/land-lock-queue-2026-11-16.md"
LAND_QUEUE_HEADER = (
    "| PR | Issue | Merged (UTC) | Ask to merge (min) | Wait (min) | Hold (min) | Handoff (min) |"
    " CI runs | Nix Eval (min) | Agent Workflow Tests (min) | AWT before test step (min) |"
    " AWT test step (min) | Instruction Budget (min) | Final-head CI wall (min) | Green to merge (min) |"
)
LAND_QUEUE_SEPARATOR = "|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
LAND_QUEUE_PROVENANCE_HEADER = (
    "| PR | Head | Nix Eval check run | Agent Workflow Tests check run |"
    " Instruction Budget check run | CI run attempts |"
)
LAND_QUEUE_FENCE = re.compile(r"^```sh\n(.*?)^```$", re.S | re.M)


def land_queue_section(text: str, name: str) -> str:
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

AWT_TIME_DOC = "docs/archive/agent-workflow-tests-time-2026-11-17.md"
AWT_TIME_HEADER = (
    "| Job | Run/attempt | Issue | Completed (UTC) | Test step (min) | Realization (min) |"
    " Start-up (min) | Tests (min) | Other (min) | Members | Jobs | CPU busy (%) | Slots busy (%) |"
    " Order saving (min) | Slots saving (min) | Cache saving (min) | Slots estimate (min) |"
)
AWT_TIME_SEPARATOR = "|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
AWT_SUMMARY_HEADER = "| Figure | Median | p90 | Max |"
AWT_SUMMARY_SEPARATOR = "|---|---:|---:|---:|"
AWT_MEMBERS_HEADER = (
    "| Member | Runs | Median wall (s) | Median CPU (s) | Median start-up (s) | Median tests (s) |"
)
AWT_MEMBERS_SEPARATOR = "|---|---:|---:|---:|---:|---:|"


def awt_tables(text: str) -> tuple[list[list[str]], dict[str, list[str]], list[list[str]]]:
    """The run rows' cells, the summary as {figure: [median, p90, max]} and the member rows' cells."""
    lines = land_queue_section(text, "Measurements").splitlines()

    def rows_after(header):
        at = lines.index(header)
        rows = []
        for line in lines[at + 2 :]:
            if not line.startswith("|"):
                break
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        return rows

    summary = {row[0]: row[1:] for row in rows_after(AWT_SUMMARY_HEADER)}
    return rows_after(AWT_TIME_HEADER), summary, rows_after(AWT_MEMBERS_HEADER)


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
            [sys.executable, "-m", "agent_tools.delivery.context_map_lint",
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
        rows = [("python/README.md", "forge-claim", "contract", ("python/agent_tools/claims/forge_claim.py",))]
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
        rows = [("python/README.md", "forge-claim", "decision", ("python/agent_tools/claims/forge_claim.py",))]
        audited = frozenset({("python/README.md", "forge-claim", "decision")})
        base = {"python/README.md": ["forge-claim"]}
        self.assertEqual(
            section_map_problems(rows, audited, base, lambda path: True),
            ["python/README.md: forge-claim: decision destination python/agent_tools/claims/forge_claim.py is not an allowed home"],
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

        source = (REPO_ROOT / "python/agent_tools/release/codesigned_artifact_adapter.py").read_text()
        docstring = " ".join((ast.get_docstring(ast.parse(source)) or "").split())
        self.assertNotIn("cannot prove", docstring)

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

    def test_the_console_session_decision_is_recorded(self):
        path = "docs/areas/console/adr/004-sessions-arrive-by-hooks-and-a-registry-poll.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-004 — Sessions arrive by hooks and a five-second registry poll")
        adr = self.doc(path)
        for needle in ("POST /api/hooks", "ADR-console-001", "procStart", "#837"):
            self.assertIn(needle, adr)
        context = self.doc("docs/areas/console/CONTEXT.md")
        for needle in (
            "A registered project with no open work, no live session and no open sprint",
            "A session waiting in its terminal is not one",
        ):
            self.assertIn(needle, context)

    def test_the_wait_signals_decision_is_recorded(self):
        path = ("docs/areas/console/adr/050-a-sprint-waiting-on-ci-a-committing-delivery-"
                "or-a-release-step-reads-what-it-waits-for.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-050 — A sprint waiting on CI, a committing "
                                "delivery or a release step reads what it waits for")
        adr = self.doc(path)
        for needle in ("#1110", "ADR-console-042", "ADR-console-032",
                       "waiting for CI on its pull request", "a delivery is committing",
                       "waiting for a release step", "attention_required", "ADR-console-048",
                       "movement_release_invalid"):
            self.assertIn(needle, adr)
        status = [line for line in (REPO_ROOT / "docs/areas/console/adr/042-a-sprint-reads-stuck-"
                                    "only-when-nothing-it-reads-has-moved.md").read_text().splitlines()
                  if line.startswith("- **Status:**")]
        self.assertEqual(status, ["- **Status:** accepted; amended by ADR-console-050, ADR-console-057"])
        context = self.doc("docs/areas/console/CONTEXT.md")
        for needle in ("a delivery committing or a release step moves it", "ADR-console-050"):
            self.assertIn(needle, context)
        sprint_entry = next(
            line for line in (REPO_ROOT / "docs/areas/console/CONTEXT.md").read_text().splitlines()
            if line.startswith("One goal, later its issues"))
        self.assertTrue(sprint_entry.endswith(
            "ADR-console-042, ADR-console-050, ADR-console-051, ADR-console-057)."))
        self.assertNotIn("ADR-console-046", sprint_entry)
        self.assertEqual(len(list((REPO_ROOT / "docs/areas/console/adr").glob("050-*.md"))), 1)

    def test_the_session_movement_decision_is_recorded(self):
        found = sorted((REPO_ROOT / "docs/areas/console/adr").glob("057-*.md"))
        self.assertEqual(len(found), 1)
        path = found[0].relative_to(REPO_ROOT).as_posix()
        first = found[0].read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-057 — Session output and a running check "
                                "move a sprint")
        adr = self.doc(path)
        for needle in ("#1185", "ADR-console-005", "ADR-console-020", "ADR-console-042",
                       "ADR-console-050", "/proc", "subagents", "one second",
                       "movement_sessions_failed", "nudge", "read_at"):
            self.assertIn(needle, adr)
        self.assertNotIn("reads stalled", adr)
        sprint_entry = next(
            line for line in (REPO_ROOT / "docs/areas/console/CONTEXT.md").read_text().splitlines()
            if line.startswith("One goal, later its issues"))
        for needle in ("session output", "a running check", "ADR-console-057"):
            self.assertIn(needle, sprint_entry)

    def test_the_owner_check_pictures_decision_is_recorded(self):
        adr = self.doc(
            "docs/areas/console/adr/045-an-owner-check-card-shows-the-pictures-and-the-reading-its-prompt-names.md"
        )
        for needle in (
            "#1112", "--screenshots", "agentConsole.screenshotDirs", "Reading:",
            "was not found on this host.", "1440", "480", "ADR-console-036", "ADR-console-038",
        ):
            self.assertIn(needle, adr)
        for path in (
            "docs/areas/console/adr/036-the-console-keeps-a-managers-pictures-and-serves-them-only-to-the-page.md",
            "docs/areas/console/adr/038-a-managers-question-shows-its-pictures-on-the-card-and-full-size-in-a-viewer.md",
            "docs/areas/console/CONTEXT.md",
        ):
            self.assertIn("ADR-console-045", self.doc(path))

    def test_the_owner_check_caption_decision_is_recorded(self):
        adr = self.doc(
            "docs/areas/console/adr/047-an-owner-check-card-captions-its-pictures-and-reads-its-reading-under-the-question.md"
        )
        for needle in (
            "#1131", "Before, 1440 px", "Owner check viewer, 480 px", "OWNER-CHECK-VIEWER-480.png",
            "sentence case", "Picture", "Reading:", "note box", "full file name",
            "ADR-console-038", "ADR-console-045", "1440", "480",
        ):
            self.assertIn(needle, adr)
        self.assertIn(
            "ADR-console-047",
            self.doc("docs/areas/console/adr/045-an-owner-check-card-shows-the-pictures-and-the-reading-its-prompt-names.md"),
        )

    def test_the_spend_decision_is_recorded_under_its_own_number(self):
        path = "docs/areas/console/adr/049-spend-is-read-from-transcripts-into-memory-and-never-logged.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first, "# ADR-console-049 — Spend is read from transcripts into memory and never logged")
        self.assertIn("ADR-console-049", self.doc("docs/areas/console/CONTEXT.md"))

    def test_the_spend_page_decision_is_recorded(self):
        path = "docs/areas/console/adr/052-the-spend-page-is-a-second-read-only-page-of-the-console.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first, "# ADR-console-052 — The Spend page is a second, read-only page of the console")
        adr = self.doc(path)
        for needle in ("#1135", "/spend", "/api/stream", "ADR-console-001",
                       "ADR-console-002", "ADR-console-008", "ADR-console-049",
                       "Estimated at API list prices", "unattributed", "1440",
                       "480", "PAGE_WRITES"):
            self.assertIn(needle, adr)
        self.assertNotIn("no endpoint changes anything", adr)
        self.assertNotIn("owner approved", adr)
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("**Spend page**:", context)
        self.assertIn("ADR-console-052", context)
        self.assertNotIn("its one page", context)
        entry = context.split("**Console**:", 1)[1].split("_Avoid_", 1)[0]
        self.assertIn("Spend page", entry)
        for other in ("docs/areas/console/adr/001-the-console-truth-is-an-append-only-event-log.md",
                      "docs/areas/console/adr/002-the-desk-page-design-rules.md"):
            self.assertIn("ADR-console-052", self.doc(other))
        self.assertIn('a quiet "Spend" link to the Spend page (ADR-console-052)',
                      self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md"))

    def test_the_control_system_is_recorded(self):
        adr = self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md")
        for needle in ("**Controls.**", "#1137", "btn-primary", "btn-quiet",
                       "btn-danger", "btn-option", "field-line", "field-area",
                       "field-code", "btn-bare", "field-bare", "32px", "4.5:1",
                       "aria-busy", "aria-disabled", "aria-pressed",
                       "Lavender ring", "Ask box"):
            self.assertIn(needle, adr)
        decided = next(
            line for line in (REPO_ROOT / "docs/areas/console/adr/002-the-desk-page-design-rules.md")
            .read_text().splitlines() if line.startswith("- **Decided in:**"))
        self.assertTrue(decided.endswith("#1136, #1137, #1177"), decided)

    def test_the_desk_spend_figure_decision_is_recorded(self):
        adr_dir = REPO_ROOT / "docs/areas/console/adr"
        found = sorted(adr_dir.glob("056-*.md"))
        self.assertEqual(len(found), 1, found)
        path = "docs/areas/console/adr/" + found[0].name
        adr = self.doc(path)
        self.assertEqual(
            (REPO_ROOT / path).read_text().splitlines()[0],
            "# ADR-console-056 \u2014 A sprint block, a delivery run line and a finished sprint line show their spend")
        for needle in ("#1136", "/spend#sprint=", "/spend#run=", "sprint_phase",
                       "run_phase", "Overlay 2", "Estimated at API list prices",
                       "summary", "1440", "480", "ADR-console-002",
                       "ADR-console-049", "ADR-console-052"):
            self.assertIn(needle, adr)
        self.assertNotIn("owner approved", adr)
        desk = self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md")
        lines = (REPO_ROOT / "docs/areas/console/adr/002-the-desk-page-design-rules.md"
                 ).read_text().splitlines()
        status = next(line for line in lines if line.startswith("- **Status:**"))
        decided = next(line for line in lines if line.startswith("- **Decided in:**"))
        self.assertTrue(status.endswith("ADR-console-052, ADR-console-056"), status)
        self.assertTrue(decided.endswith("#1136, #1137, #1177"), decided)
        self.assertIn("ADR-console-056", desk)
        spend = self.doc("docs/areas/console/adr/052-the-spend-page-is-a-second-read-only-page-of-the-console.md")
        self.assertIn("- **Status:** accepted; amended by ADR-console-056", spend)
        self.assertIn("ADR-console-056", spend.split("**D5. Breakdowns.**", 1)[1].split("**D6.", 1)[0])
        context = self.doc("docs/areas/console/CONTEXT.md")
        entry = context.split("**Spend page**:", 1)[1].split("_Avoid_", 1)[0]
        self.assertIn("ADR-console-056", entry)

    def test_the_held_review_decision_is_recorded(self):
        path = ("docs/areas/console/adr/054-a-held-issue-whose-only-open-criterion-is-an-owner-"
                "review-gets-an-owner-check-card.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first,
            "# ADR-console-054 \u2014 A held issue whose only open criterion is an owner review "
            "gets an owner check card")
        adr = self.doc(path)
        for needle in (
            "#1113", "needs-verification", "[human]", "[note]", "POST /api/check-answer",
            "Approve", "Not yet", "OWNER", "MEMBER", "Acceptance criteria",
            "ADR-console-003", "ADR-console-010", "ADR-console-012", "ADR-console-045",
            "1440", "480",
        ):
            self.assertIn(needle, adr)
        for older, status in (
            ("003-the-inbox-is-read-from-the-tracker.md",
             "- **Status:** accepted; amended by ADR-console-054"),
            ("012-the-page-answers-owner-prompts-through-the-runners-owner-path.md",
             "- **Status:** accepted; amended by ADR-console-032, ADR-console-054"),
        ):
            line = next(row for row in (REPO_ROOT / "docs/areas/console/adr" / older)
                        .read_text().splitlines() if row.startswith("- **Status:**"))
            self.assertEqual(line, status)
        entry = self.doc("docs/areas/console/CONTEXT.md").split("**Inbox item**:")[1].split("_Avoid_:")[0]
        self.assertIn("ADR-console-054", entry)

    def test_the_console_signin_decision_is_recorded(self):
        path = "docs/areas/console/adr/022-a-profiles-sign-in-is-read-from-the-clients-status-command.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first, "# ADR-console-022 — A profile's sign-in is read from the client's status command")
        adr = self.doc(path)
        for needle in ("auth status --json", "loginExpiresAt", "three days",
                       "CLAUDE_ACCOUNT=<profile> claude", "ADR-console-006", "ADR-console-015",
                       "launch choice", "#1010"):
            self.assertIn(needle, adr)
        self.assertIn("**Sign-in state**:", self.doc("docs/areas/console/CONTEXT.md"))
        self.assertIn("ADR-console-022", self.doc(
            "docs/areas/console/adr/006-capacity-readings-arrive-from-the-proxy.md"))

    def test_the_console_merge_refusal_decision_is_recorded(self):
        path = "docs/areas/console/adr/048-a-merge-refused-by-the-guard-shows-once-in-the-sprints-line.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first,
            "# ADR-console-048 — A merge refused by the guard shows once in the sprint's line, "
            "never as a question")
        adr = self.doc(path)
        for needle in ("#1115", "merge refused: <reason>", "status line", "`sprint ask`", "inbox",
                       "last seen", "digest", "A merge in <title> was refused: <reason>",
                       "closed out", "ADR-console-014", "ADR-console-019", "ADR-console-042",
                       "docs/areas/guard/adr/"):
            with self.subTest(needle):
                self.assertIn(needle, adr)
        self.assertNotIn("stalled", adr)
        raw = (REPO_ROOT / "docs/areas/console/CONTEXT.md").read_text()
        entry = raw[raw.index("**Report**:"):].split("\n\n")[0]
        for needle in ("ADR-console-048", "merge refused"):
            with self.subTest(needle):
                self.assertIn(needle, entry)

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

    def test_the_console_profile_choice_decision_is_recorded(self):
        path = "docs/areas/console/adr/023-a-new-sessions-profile-is-the-consoles-choice.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first,
            "# ADR-console-023 — A new session's profile is the console's choice, on a route and in a file")
        adr = self.doc(path)
        for needle in ("GET /api/profile", "chosen-profile", "bindings.tsv", "most recently used",
                       "null", "ADR-console-015", "ADR-console-020", "ADR-console-022", "#1011"):
            self.assertIn(needle, adr)
        for older in ("docs/areas/console/adr/015-a-stated-goal-starts-a-manager.md",
                      "docs/areas/console/adr/022-a-profiles-sign-in-is-read-from-the-clients-status-command.md"):
            self.assertIn("ADR-console-023", self.doc(older))
        self.assertNotIn("Skipping signed-out profiles at launch is a later change", self.doc(
            "docs/areas/console/adr/022-a-profiles-sign-in-is-read-from-the-clients-status-command.md"))
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("ADR-console-023", context)
        self.assertIn("binding", context)

    def test_the_profile_exclusion_decision_is_recorded(self):
        adr = self.doc("docs/areas/console/adr/023-a-new-sessions-profile-is-the-consoles-choice.md")
        context = self.doc("docs/areas/console/CONTEXT.md")
        for needle in ("#1028", "POST /api/exclusion", "profile.exclusion", "ADR-console-008", "excluded"):
            self.assertIn(needle, adr)
        self.assertNotIn("Pins and exclusions are later inputs", adr)
        self.assertIn("**Excluded profile**:", context)
        entry = context[context.index("**Excluded profile**:"):].split("\n\n")[0]
        self.assertIn("ADR-console-023", entry)

    def test_the_profile_pin_decision_is_recorded(self):
        adr = self.doc("docs/areas/console/adr/023-a-new-sessions-profile-is-the-consoles-choice.md")
        for needle in ("#1029", "POST /api/pin", "profile.pin", "not in effect", "include it first",
                       "unpin it first", "CLAUDE_ACCOUNT"):
            self.assertIn(needle, adr)
        self.assertNotIn("Pins are a later input", adr)
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("**Pinned profile**:", context)
        entry = context[context.index("**Pinned profile**:"):].split("\n\n")[0]
        self.assertIn("ADR-console-023", entry)
        self.assertIn("not in effect", entry)
        self.assertIn("| Pinned profile | Console |", self.doc("docs/CONTEXT-MAP.md"))

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
                      "docs/areas/hosts/CONTEXT.md",
                      "docs/areas/hosts/adr/005-account-profiles-link-shared-config.md"):
            self.assertIn("ADR-console-025", self.doc(older))
        self.assertIn("claude-account add", self.doc("docs/areas/hosts/CONTEXT.md"))
        self.assertIn("POST /api/account-add", self.doc(
            "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md"))
        both = ("- **Status:** accepted; amended by ADR-console-024, ADR-console-025, "
                "ADR-console-028")
        for older, status in (
                ("docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md",
                 both + ", ADR-console-029, ADR-console-030, ADR-console-036, "
                         "ADR-console-037, ADR-console-053, ADR-console-058, ADR-system-004"),
                ("docs/areas/console/adr/002-the-desk-page-design-rules.md",
                 both + ", ADR-console-029, ADR-console-031, ADR-console-032, ADR-console-033, "
                 "ADR-console-035, ADR-console-038, ADR-console-052, ADR-console-056"),
                ("docs/areas/console/adr/024-the-owner-signs-a-profile-in-from-the-page.md",
                 "- **Status:** accepted; amended by ADR-console-025")):
            line = next(row for row in (REPO_ROOT / older).read_text().splitlines()
                        if row.startswith("- **Status:**"))
            self.assertEqual(line, status)

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
                                          "ADR-console-058, ADR-system-004"),
                                (adr002, status + ", ADR-console-029, ADR-console-031, "
                                          "ADR-console-032, ADR-console-033, ADR-console-035, "
                                          "ADR-console-038, ADR-console-052, ADR-console-056")):
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
                       "ADR-console-011", "ADR-console-023", "ADR-guard-011"):
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

    def test_the_question_milestone_decisions_are_recorded(self):
        adr_dir = REPO_ROOT / "docs/areas/console/adr"
        found = sorted(adr_dir.glob("059-*.md"))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].name, "059-a-project-question-is-spent-under-its-project-"
                                        "threaded-in-the-log-and-can-fill-a-goal.md")
        self.assertEqual(found[0].read_text().splitlines()[0],
                         "# ADR-console-059 \u2014 A project question is spent under its "
                         "project, threaded in the log and can fill a goal")
        adr = " ".join(found[0].read_text().split())
        for needle in ("- **Decided in:** #1180", "--session-id", "session_id",
                       "project_question.asked", "questions", "Questions (n)",
                       "Make it a goal", "#1177", "#1178", "#1179", "ADR-console-001",
                       "ADR-console-002", "ADR-console-011", "ADR-console-049",
                       "ADR-console-052", "ADR-console-058"):
            self.assertIn(needle, adr)
        amended = (
            ("058-a-question-about-a-project-is-answered-by-a-read-only-session.md",
             "accepted; amended by ADR-console-059", "**D2.", "**D3.", ("--session-id",)),
            ("049-spend-is-read-from-transcripts-into-memory-and-never-logged.md",
             "accepted; amended by ADR-console-059", "**D3.", "**D4.",
             ("project_question.asked",)),
            ("052-the-spend-page-is-a-second-read-only-page-of-the-console.md",
             "accepted; amended by ADR-console-056, ADR-console-059", "**D5.", "**D6.",
             ("Questions",)),
        )
        for name, status, start, end, needles in amended:
            raw = (adr_dir / name).read_text()
            line = next(row for row in raw.splitlines() if row.startswith("- **Status:**"))
            self.assertEqual(line, "- **Status:** " + status)
            text = self.doc("docs/areas/console/adr/" + name)
            decision = text[text.index(start):text.index(end)]
            self.assertIn("ADR-console-059", decision)
            for needle in needles:
                self.assertIn(needle, decision)
        context = self.doc("docs/areas/console/CONTEXT.md")
        question = context[context.index("**Project question**:"):]
        self.assertIn("ADR-console-059", question[:question.index("_Avoid_")])
        thread = context[context.index("**Question thread**:"):]
        thread = thread[:thread.index("_Avoid_")]
        self.assertIn("ADR-console-059", thread)
        self.assertIn("Questions (n)", thread)
        self.assertIn("| Question thread | Console |", self.doc("docs/CONTEXT-MAP.md"))

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
                         "ADR-console-037, ADR-console-053, ADR-console-058, ADR-system-004"),
                (adr028, "- **Status:** accepted; amended by ADR-console-029, "
                         "ADR-console-030, ADR-console-031, ADR-console-034, ADR-console-035; "
                         "extended by #1055 (D10, D11)")):
            line = next(row for row in (REPO_ROOT / older).read_text().splitlines()
                        if row.startswith("- **Status:**"))
            self.assertEqual(line, expected)

    def test_the_drafted_contract_decision_is_recorded(self):
        path = ("docs/areas/console/adr/"
                "031-a-repository-with-no-contract-is-registered-with-a-drafted-contract.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-031 \u2014 A repository with no contract is "
                                "registered with a drafted contract")
        adr = self.doc(path)
        for needle in ("#1067", "contract-draft", "POST /api/plan-answer", "--contract-draft",
                       "writes the project contract",
                       "a project id is two names joined by one slash, like owner/name, "
                       "with no spaces",
                       "is already registered for another checkout", "The plan refused the",
                       "the command could not be read", "the console's starting value",
                       "adopt.draft.id_taken", "ADR-console-028", "ADR-console-029",
                       "ADR-project-contract-006"):
            self.assertIn(needle, adr)
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("**Drafted contract**:", context)
        self.assertIn("ADR-console-031", context)
        self.assertIn("| Drafted contract | Console |", self.doc("docs/CONTEXT-MAP.md"))
        module = self.doc("python/agent_tools/console/contract_draft.py")
        self.assertIn("Decided in ADR-console-031.", module)
        self.assertNotIn("ADR-console-030", module)
        for older, expected in (
                ("docs/areas/console/adr/028-the-owner-registers-a-project-from-the-page.md",
                 "- **Status:** accepted; amended by ADR-console-029, ADR-console-030, "
                 "ADR-console-031, ADR-console-034, ADR-console-035; extended by #1055 (D10, D11)"),
                ("docs/areas/console/adr/"
                 "029-the-owner-answers-the-adoptions-questions-on-the-page.md",
                 "- **Status:** accepted; amended by ADR-console-030, ADR-console-031, "
                 "ADR-console-033, ADR-console-034"),
                ("docs/areas/console/adr/002-the-desk-page-design-rules.md",
                 "- **Status:** accepted; amended by ADR-console-024, ADR-console-025, "
                 "ADR-console-028, ADR-console-029, ADR-console-031, ADR-console-032, "
                 "ADR-console-033, ADR-console-035, ADR-console-038, ADR-console-052, ADR-console-056"),
                ("docs/areas/console/adr/"
                 "031-a-repository-with-no-contract-is-registered-with-a-drafted-contract.md",
                 "- **Status:** accepted; amended by ADR-console-033")):
            line = next(row for row in (REPO_ROOT / older).read_text().splitlines()
                        if row.startswith("- **Status:**"))
            self.assertEqual(line, expected)

    def test_the_plain_draft_and_cards_decision_is_recorded(self):
        path = ("docs/areas/console/adr/033-the-drafted-contract-and-the-question-cards-"
                "read-plainly-and-fit-the-screen.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-033 \u2014 The drafted contract and the question "
                                "cards read plainly and fit the screen")
        adr = self.doc(path)
        for needle in ("#1079", "and 20 more settings at their usual values",
                       "of them set by you", "work branches are named after their issue",
                       "It has no remote, so the console cannot tell", "owner/name",
                       "the build command", "sends what you typed", "sends this answer",
                       "This is the only thing the adoption can do with this file.", "1.25rem",
                       "ADR-console-002", "ADR-console-029", "ADR-console-031", "#1073"):
            self.assertIn(needle, adr)
        self.assertIn("ADR-console-033", self.doc("docs/areas/console/CONTEXT.md"))
        module = self.doc("python/agent_tools/console/contract_draft.py")
        self.assertIn("Decided in ADR-console-031.", module)
        self.assertIn("ADR-console-033", module)

    def test_the_contract_draft_seam_is_recorded(self):
        path = ("docs/areas/project-contract/adr/"
                "006-a-drafted-contract-enters-the-plan-as-a-file-it-writes.md")
        text = (REPO_ROOT / path).read_text()
        self.assertEqual(
            text.splitlines()[0],
            "# ADR-project-contract-006 \u2014 A drafted contract enters the "
            "adoption plan as a file it writes")
        for needle in ("--contract-draft", "adopt.draft.invalid",
                       "adopt.draft.contract_present", "adopt.draft.id_taken",
                       "plan_id", "apply", "ADR-project-contract-004",
                       "ADR-project-contract-005", "#1067"):
            self.assertIn(needle, text)

    def test_the_accounts_panel_decision_is_recorded(self):
        base = "docs/areas/console/adr/"
        adr2 = self.doc(base + "002-the-desk-page-design-rules.md")
        context = self.doc("docs/areas/console/CONTEXT.md")

        def entry(term):
            return context[context.index("**" + term + "**:"):].split("_Avoid_")[0]

        for needle in ("#1039", "accounts panel", "one line", "Escape", "the tightest account",
                       "no button"):
            self.assertIn(needle, adr2)
        for needle in ("never shrinks", "ending in an ellipsis"):
            self.assertIn(needle, adr2)
        self.assertNotIn("clips instead", adr2)
        for words in ("signed in, ends in N days", "signed in, ends today"):
            self.assertIn(words, adr2)
        for gone in ("sign-in ends in N days", "sign-in ends today", "a signed-in profile carries none"):
            self.assertNotIn(gone, adr2)
        for gone in ("Beside each listed profile sits its sign-in", "Then one time:"):
            self.assertNotIn(gone, adr2)
        panel = entry("Accounts panel")
        for needle in ("ADR-console-002", "Escape", "Remove"):
            self.assertIn(needle, panel)
        strip = entry("Capacity strip")
        self.assertIn("one line", strip)
        self.assertNotIn("carries Remove", strip)
        for term in ("Pinned profile", "Excluded profile"):
            self.assertIn("accounts panel", entry(term))
            self.assertNotIn("on its capacity strip entry", entry(term))
        adr23 = self.doc(base + "023-a-new-sessions-profile-is-the-consoles-choice.md")
        adr24 = self.doc(base + "024-the-owner-signs-a-profile-in-from-the-page.md")
        adr25 = self.doc(base + "025-the-owner-adds-an-account-from-the-page.md")
        adr26 = self.doc(base + "026-the-owner-removes-an-account-from-the-page.md")
        for adr in (adr23, adr24, adr26):
            self.assertIn("accounts panel", adr)
        self.assertIn("#1039", adr23)
        self.assertNotIn("The page's header carries an Add account control", adr25)
        self.assertNotIn("Each capacity strip entry carries a Remove control", adr26)
        self.assertIn("| Accounts panel | Console |", self.doc("docs/CONTEXT-MAP.md"))

    def test_the_same_account_decision_is_recorded(self):
        base = "docs/areas/console/adr/"
        adr22 = self.doc(base + "022-a-profiles-sign-in-is-read-from-the-clients-status-command.md")
        adr23 = self.doc(base + "023-a-new-sessions-profile-is-the-consoles-choice.md")
        adr2 = self.doc(base + "002-the-desk-page-design-rules.md")
        context = self.doc("docs/areas/console/CONTEXT.md")

        def entry(term):
            return context[context.index("**" + term + "**:"):].split("_Avoid_")[0]

        for needle in ("#1036", "email", "`account`", "`account_seq`", "accounts panel"):
            self.assertIn(needle, adr22)
        self.assertNotIn("The address, organisation and plan the client also prints are dropped", adr22)
        for needle in ("#1036", "same account", "counted once", "newest reading", "earlier account"):
            self.assertIn(needle, adr23)
        for needle in ("#1036", "dimmed", "same account as"):
            self.assertIn(needle, adr2)
        for needle in ("counted once", "dimmed"):
            self.assertIn(needle, entry("Capacity strip"))
        for needle in ("same account as", "ADR-console-023"):
            self.assertIn(needle, entry("Sign-in state"))
        self.assertIn("account it is signed in to", entry("Accounts panel"))

    def test_the_launch_choice_decision_is_recorded(self):
        path = "docs/areas/hosts/adr/008-claude-starts-under-the-consoles-profile-choice.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first,
            "# ADR-hosts-008 — `claude` starts under the console's profile choice, not the project's binding")
        adr = self.doc(path)
        for needle in ("GET /api/profile", "chosen-profile", "bindings.tsv", "one second",
                       "most recently used", "oauthAccount", "CLAUDE_ACCOUNT", "default",
                       "ADR-hosts-005", "ADR-console-023", "#1012"):
            self.assertIn(needle, adr)
        context = self.doc("docs/areas/hosts/CONTEXT.md")
        self.assertIn("ADR-hosts-008", context)
        self.assertNotIn("`claude` reads it at launch to pick the profile directory.", context)

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

    def test_the_tracker_write_retry_decision_is_recorded(self):
        path = ("docs/areas/console/adr/032-a-tracker-write-rides-out-a-short-network-drop-"
                "and-fails-in-plain-words.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first, "# ADR-console-032 \u2014 A tracker write rides out a short network drop "
                   "and fails in plain words")
        adr = self.doc(path)
        for needle in ("ADR-console-010", "ADR-console-012", "ADR-console-002", "#1075",
                       "transient", "30 seconds", "1, 2, 4, 8 and 10 seconds", "5 seconds",
                       "deadline", "Sending\u2026", "this computer could not reach GitHub",
                       "the console did not say why", "answer_tick_failed",
                       "answer_tick_retry", "Try again", "a note", "already carries"):
            self.assertIn(needle, adr)
        for older, status in (
            ("docs/areas/console/adr/010-the-page-answers-a-decision-prompt-by-ticking-it-as-the-owner.md",
             "- **Status:** accepted; amended by ADR-console-032"),
            ("docs/areas/console/adr/012-the-page-answers-owner-prompts-through-the-runners-owner-path.md",
             "- **Status:** accepted; amended by ADR-console-032, ADR-console-054"),
        ):
            line = next(row for row in (REPO_ROOT / older).read_text().splitlines()
                        if row.startswith("- **Status:**"))
            self.assertEqual(line, status)
        self.assertIn("ADR-console-032",
                      self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md"))

    def test_the_console_owner_prompt_decision_is_recorded(self):
        path = "docs/areas/console/adr/012-the-page-answers-owner-prompts-through-the-runners-owner-path.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first, "# ADR-console-012 — The page answers owner prompts through the runner's owner path")
        adr = self.doc(path)
        for needle in ("POST /api/check-answer", "ADR-console-010", "ADR-verification-009", "#836",
                       "#837", "#863", "typed confirmation", "no multi-item action", "kept"):
            self.assertIn(needle, adr)
        self.assertNotIn(
            "Nothing is typed",
            self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md"))

    def test_console_adr_018_records_how_a_sprint_ends(self):
        path = "docs/areas/console/adr/018-a-sprint-ends-with-a-closing-report-or-the-owners-stop.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(
            first, "# ADR-console-018 — A sprint ends with a closing report or the owner's stop")
        adr = self.doc(path)
        for needle in ("POST /api/close", "POST /api/stop", "ADR-console-014", "ADR-console-016",
                       "#834", "#928", "ten minutes", "schema 7", "manager.stopped"):
            self.assertIn(needle, adr)
        for needle in ("#980", "A closing report stops the manager's session", "two minutes",
                       "ADR-console-016"):
            self.assertIn(needle, adr)
        self.assertNotIn("A plain closing report does not stop the manager's session", adr)

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

    def test_the_desk_finish_is_recorded(self):
        rules = self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md")
        goal = self.doc("docs/areas/console/adr/011-a-goal-stated-on-the-page-becomes-a-sprint.md")
        context = self.doc("docs/areas/console/CONTEXT.md")
        for needle in ("#922", "Tell a manager what you want next\u2026", "fine, tight or out",
                       "never Peach", "resumes <weekday time>", "the age, then the sentence",
                       "A session named for a sprint adds no line",
                       "one shared style, 600 .9375rem/1.4"):
            self.assertIn(needle, rules)
        self.assertNotIn("State a goal", goal)
        self.assertIn("#922", goal)
        for needle in ("fine, tight or out", "A session named for a sprint adds no line"):
            self.assertIn(needle, context)

    def test_the_check_heading_is_recorded(self):
        rules = self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md")
        for needle in ("#1046", "a manual check's heading is the first sentence of its ask",
                       "its check id a small label after the kind words"):
            self.assertIn(needle, rules)

    def test_later_open_items_as_rows_are_recorded(self) -> None:
        rules = self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md")
        for needle in (
            "#944", "a waiting brief included", "Or say what to change\u2026",
            "closing it keeps a typed reply", "the owner may close it again",
        ):
            self.assertIn(needle, rules)
        self.assertNotIn("keeps its own unraised brief block", rules)

    def test_sprint_controls_on_demand_are_recorded(self) -> None:
        rules = self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md")
        for needle in ('a closed "End the sprint" fold', "a typed draft keeps it open",
                       '"Show the report"', "holds the report's status line",
                       "never the report's status line", "is not drawn", "at most two lines",
                       "the manager's own line", '"Stop and report"', '"Drop the sprint"',
                       '"goal set <age>"', '"You: <words>"', '"Manager: <reply>"',
                       '"Next time: <text>"', "the hint right under the field"):
            self.assertIn(needle, rules)
        self.assertNotIn('"Stop or withdraw"', rules)
        self.assertNotIn('"More" fold', rules)
        self.assertNotIn('withdraw, messages and "Tell the manager" stay under the two lines', rules)
        message = self.doc(
            "docs/areas/console/adr/016-what-the-owner-says-to-a-sprint-reaches-its-manager.md")
        for needle in ("opens its field on demand", 'under a closed "Earlier messages (n)" fold',
                       'no "End the sprint" fold', "once the manager has picked it up",
                       "drop the sprint"):
            self.assertIn(needle, message)
        self.assertNotIn("nudge it", message)
        self.assertNotIn("withdraw the sprint", message)

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

    def test_the_console_manager_session_decision_is_recorded(self):
        path = "docs/areas/console/adr/021-a-managers-session-runs-with-isolation-off-and-permission-prompts-refused.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-021 — A manager's session runs with the background "
                                "isolation guard off and permission prompts refused")
        adr = self.doc(path)
        for needle in ("bgIsolation", "PermissionRequest", "sprint ask", "settings file",
                       "ADR-console-004", "ADR-console-015", "ADR-console-017", "#835", "#973"):
            self.assertIn(needle, adr)
        manager = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("ADR-console-021", manager)

    def test_the_console_probe_decision_is_recorded(self):
        path = "docs/areas/console/adr/006-capacity-readings-arrive-from-the-proxy.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-006 — Capacity readings arrive from the proxy "
                                "and are kept per profile")
        adr = self.doc(path)
        for needle in ("#1009", "--session-id", "--no-session-persistence",
                       "CLAUDE_CACHE_PROXY=required", "10 minutes", "30 seconds", "429", "256",
                       "ADR-hosts-007", "ADR-console-015", "unless it is a console probe"):
            self.assertIn(needle, adr)
        self.assertNotIn("is attributed only by an account already paired with one.", adr)
        hosts = self.doc("docs/areas/hosts/adr/004-claude-routes-through-the-proxy-by-default.md")
        self.assertIn("CLAUDE_CACHE_PROXY=required", hosts)
        self.assertIn("#1009", hosts)
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertIn("every 10 minutes", context)
        self.assertIn("idle profiles are read too", context)

    def test_the_console_delivery_decision_is_recorded(self):
        path = "docs/areas/console/adr/005-in-flight-delivery-stage-is-read-from-run-journals.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-005 — In-flight delivery stage is read from run journals")
        adr = self.doc(path)
        for needle in ("journal.jsonl", "ADR-console-001", "#830", "#837",
                       "quiet for N min", "working", "delivery.seen"):
            self.assertIn(needle, adr)
        self.assertIn("**Delivery run**", self.doc("docs/areas/console/CONTEXT.md"))

    def test_the_build_provenance_limitation_is_in_a_release_adr_and_the_map(self):
        adrs = [
            path for path in (REPO_ROOT / "docs/areas/release/adr").glob("*.md")
            if "cannot prove the bundle was built from that commit"
            in " ".join(path.read_text().split())
        ]
        self.assertEqual(len(adrs), 1)
        relative = adrs[0].relative_to(REPO_ROOT).as_posix()
        self.assertIn("## Consequences", adrs[0].read_text())
        self.assertIn("issue 547 D9", adrs[0].read_text())
        row = next(
            line for line in (REPO_ROOT / "docs/archive/readme-section-map.md").read_text().splitlines()
            if line.startswith("| `python/README.md` | Release adapters | decision |")
        )
        self.assertIn(relative, row)

    def test_the_guard_context_separates_the_base_and_the_compiled_policy(self):
        text = self.doc("docs/areas/guard/CONTEXT.md")
        self.assertNotIn("The base policy plus one derived row", text)
        self.assertIn("none of the base policy's members", text)

    def test_the_verification_context_names_every_kind_of_check(self):
        text = self.doc("docs/areas/verification/CONTEXT.md")
        self.assertNotIn("One named, read-only test", text)
        for word in ("built-in probe", "question or action for the owner", "unattended"):
            self.assertIn(word, text)

    def test_the_guard_adr_keeps_the_loader_and_the_compiler_apart(self):
        text = self.doc("docs/areas/guard/adr/006-two-policy-files-one-trust-rule-each.md")
        self.assertNotIn("costs that project its row, not the whole file", text)
        self.assertIn("empties the whole compiled policy", text)

    def test_the_verification_adr_names_the_command_that_never_reaches_the_owner(self):
        text = self.doc("docs/areas/verification/adr/003-only-verification-commands-run-unattended.md")
        self.assertNotIn("Everything else reaches the owner through an owner prompt", text)
        self.assertIn("raises no owner prompt", text)

    def test_the_registration_adr_follows_the_contract_branch(self):
        text = self.doc("docs/areas/project-contract/adr/005-registration-reads-the-remote.md")
        self.assertNotIn("changes nothing unless", text)
        self.assertIn("integration branch the default contract names", text)
        self.assertIn("conflicting `--integration-branch` operand refuses", text)

    def test_the_trust_adr_records_the_owners_conditions(self):
        adr = self.doc("docs/areas/console/adr/"
                       "034-registering-a-project-grants-it-folder-trust-in-every-profile.md")
        for needle in ("hasTrustDialogAccepted",
                       "Registering lets agents run in this folder with the folder's own "
                       "settings and hooks.",
                       "CLAUDE_CODE_SANDBOXED", "trust.granted", "CLAUDE_ACCOUNT=<profile> claude",
                       "RENAME_EXCHANGE", "CLAUDE_ACCOUNT_SKIP_FOLDER_TRUST"):
            self.assertIn(needle, adr)
        self.assertTrue(adr.startswith("# ADR-console-034 \u2014 Registering a project grants "
                                       "it folder trust in every profile"))
        self.assertIn("ADR-console-034",
                      self.doc("docs/areas/hosts/adr/005-account-profiles-link-shared-config.md"))
        context = self.doc("docs/areas/console/CONTEXT.md")
        self.assertRegex(context, r"\*\*Folder trust\*\*:.*?\(ADR-console-034\)\. _Avoid_")
        line = next(row for row in (REPO_ROOT / "docs/areas/console/adr/030-the-owner-approves-"
                                    "a-ready-adoption-and-the-console-opens-its-pull-request.md"
                                    ).read_text().splitlines()
                    if row.startswith("- **Status:**"))
        self.assertEqual(line, "- **Status:** accepted; amended by ADR-console-028 D10, "
                               "ADR-console-034, ADR-console-035, ADR-console-037")

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

    def test_adr_console_039_records_the_look_question_rule(self):
        path = "docs/areas/console/adr/039-a-question-about-look-or-layout-carries-its-pictures.md"
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-039 \u2014 A question about look or layout carries "
                                "its pictures")
        adr = self.doc(path)
        for needle in ("#1092", "screenshot", ".png", "`screenshots` segment", "no picture",
                       "attach the pictures with pictures, or reword it", "ADR-console-015",
                       "ADR-console-019", "ADR-console-038"):
            self.assertIn(needle, adr)
        context = self.doc("docs/areas/console/CONTEXT.md")
        entry = context.split("**Question round**:", 1)[1].split("_Avoid_:", 1)[0]
        self.assertIn("A question whose ask or context names screenshots, a `.png` file or a "
                      "screenshots folder must carry a picture, or the round is refused with "
                      "the question named (ADR-console-039).", entry)

    def test_an_adr_number_is_used_once_within_its_area(self):
        for area in sorted((REPO_ROOT / "docs/areas").iterdir()):
            seen: dict[str, str] = {}
            for adr in sorted((area / "adr").glob("[0-9][0-9][0-9]-*.md")):
                number = adr.name[:3]
                with self.subTest(area=area.name, number=number):
                    self.assertNotIn(number, seen, f"{seen.get(number)} and {adr.name}")
                seen[number] = adr.name

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
                         "- **Status:** accepted; amended by ADR-console-038, ADR-console-040")
        self.assertEqual(status("009-events-are-kept-for-90-days.md"),
                         "- **Status:** accepted; amended by ADR-console-036, ADR-console-040")
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

    def test_the_notice_board_decision_is_recorded(self):
        path = ("docs/areas/console/adr/"
                "046-the-notice-board-shows-each-manager-its-projects-open-notices-and-never-"
                "approves-anything.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-console-046 \u2014 The notice board shows each manager its "
                                "project's open notices and never approves anything")
        adr = self.doc(path)
        for needle in ("#1118", "ADR-console-044", "ADR-console-015", "ADR-console-019",
                       "only in the console's log", "never approval", "first prompt",
                       "sprint inbox", "sprint status", "for you", "question card",
                       "POST /api/notices", "not on a line beginning with"):
            with self.subTest(needle):
                self.assertIn(needle, adr)
        context = self.doc("docs/areas/console/CONTEXT.md")
        notice = context.split("**Notice**:", 1)[1].split("_Avoid_:", 1)[0]
        self.assertIn("ADR-console-046", notice)
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

    def test_the_host_activation_decision_is_recorded(self):
        path = ("docs/areas/system/adr/004-host-activation-runs-only-through-the-consoles-"
                "activate.md")
        first = (REPO_ROOT / path).read_text().splitlines()[0]
        self.assertEqual(first, "# ADR-system-004 \u2014 Host activation runs only through the "
                                "console's Activate")
        adr = self.doc(path)
        for needle in ("#1193", "POST /api/activate", "bad activation", "nothing to activate",
                       "an activation is already running",
                       "that commit is no longer the tip of origin's integration branch",
                       "the tip of origin's integration branch could not be read",
                       "so it runs only through the console's Activate, on the line that says "
                       "a console change is not active on this host."):
            with self.subTest(needle):
                self.assertIn(needle, adr)
        for older in ("docs/areas/console/adr/043-a-merged-console-change-not-active-on-this-"
                      "host-is-one-line-in-the-work-column.md",
                      "docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-"
                      "origin.md",
                      "docs/areas/guard/adr/011-the-guard-refuses-a-projects-production-commands-"
                      "outside-its-release-path.md",
                      "docs/areas/project-contract/adr/007-a-contract-declares-its-production-"
                      "rules-or-that-it-has-none.md"):
            line = next(row for row in (REPO_ROOT / older).read_text().splitlines()
                        if row.startswith("- **Status:**"))
            with self.subTest(older):
                self.assertIn("ADR-system-004", line)
        for context in ("console", "guard", "project-contract"):
            with self.subTest(context):
                self.assertIn("ADR-system-004", self.doc(f"docs/areas/{context}/CONTEXT.md"))
        self.assertNotIn("naming `just switch`", self.doc("docs/areas/console/CONTEXT.md"))

    def test_the_notices_fold_is_recorded(self):
        adr = self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md")
        self.assertIn('"Notices (n)"', adr)
        self.assertIn("it never counts in the statement (#1119)", adr)
        raw = (REPO_ROOT / "docs/areas/console/adr/002-the-desk-page-design-rules.md").read_text()
        decided = next(line for line in raw.splitlines() if line.startswith("- **Decided in:**"))
        self.assertTrue(decided.endswith(", #1135, #1136, #1137, #1177"))
        self.assertIn('the same disclosure arrow as "Show the report" and "Finished sprints"', adr)
        self.assertIn('"Hand-off for you, from <title>"', adr)
        self.assertIn("its paths in the code style", adr)
        self.assertIn("cut with an ellipsis, its whole text in its title (#1133)", adr)
        self.assertNotIn("each open notice is one plain Overlay 2 line", adr)
        context = self.doc("docs/areas/console/CONTEXT.md")
        notice = context.split("**Notice**:", 1)[1].split("_Avoid_:", 1)[0]
        self.assertIn('"Notices (n)" fold', notice)
        self.assertIn("ADR-console-002", notice)

    def test_the_guard_coverage_decision_is_recorded(self):
        path = "docs/areas/guard/adr/009-the-guard-covers-bash-only-and-production-rules-live-in-the-contract.md"
        adr = self.doc(path)
        self.assertTrue(adr.startswith(
            "# ADR-guard-009 \u2014 The guard covers the Bash tool only, and production rules live in the project contract"))
        for needle in ("bypassPermissions", "2.1.322", "mcp__", "Edit", "Write", "just", "residual gap",
                       "ADR-guard-005", "ADR-guard-006", "ADR-console-021", "detaching word",
                       "raise label", "production rule", "read-only route", "approved release path",
                       "2026-11-16", "anis-desktop", "outside standing authorization", "ADR-guard-011"):
            self.assertIn(needle, adr)
        self.assertIn("- **Status:** accepted; amended by ADR-guard-011, ADR-guard-012",
                      (REPO_ROOT / path).read_text().splitlines())
        eleven = "docs/areas/guard/adr/011-the-guard-refuses-a-projects-production-commands-outside-its-release-path.md"
        self.assertIn("- **Status:** accepted; amended by ADR-guard-012, ADR-system-004",
                      (REPO_ROOT / eleven).read_text().splitlines())
        twelve = ("docs/areas/guard/adr/012-the-guard-refuses-declared-production-mcp-tools-"
                  "and-key-file-writes.md")
        adr12 = self.doc(twelve)
        self.assertTrue(adr12.startswith(
            "# ADR-guard-012 \u2014 The guard refuses declared production MCP tools and key file writes"))
        self.assertIn("- **Status:** accepted", (REPO_ROOT / twelve).read_text().splitlines())
        for needle in ("Edit|Write|MultiEdit|NotebookEdit", "^mcp__", "fnmatchcase",
                       "ADR-guard-009", "ADR-guard-011"):
            self.assertIn(needle, adr12)
        context = self.doc("docs/areas/guard/CONTEXT.md")
        for term in ("Production rule", "Read-only route", "Approved release path"):
            self.assertIn("**" + term + "**:", context)
            self.assertIn("| " + term + " | Guard |", self.doc("docs/CONTEXT-MAP.md"))
        self.assertIn("ADR-guard-009", context)
        raw = (REPO_ROOT / "docs/areas/guard/CONTEXT.md").read_text()
        for term in ("Production rule", "Read-only route", "Approved release path", "Derived row"):
            definition = " ".join(raw.split("**" + term + "**:", 1)[1].split("\n\n", 1)[0].split())
            if term != "Derived row":
                self.assertNotIn("Planned:", definition)
            self.assertIn("ADR-guard-011", definition)
            if term == "Production rule":
                self.assertIn("ADR-guard-012", definition)
                self.assertNotIn("not yet enforced", definition)
        self.assertIn("ADR-guard-004", adr)
        self.assertIn("CLAUDECODE", adr)
        self.assertIn("`pre-push`", adr)

    def test_the_production_rule_enforcement_is_recorded(self):
        path = ("docs/areas/guard/adr/011-the-guard-refuses-a-projects-production-commands-"
                "outside-its-release-path.md")
        adr = self.doc(path)
        self.assertTrue(adr.startswith(
            "# ADR-guard-011 \u2014 The guard refuses a project's production commands outside its release path"))
        for needle in ("#1149", "ADR-guard-006", "ADR-guard-007", "ADR-guard-009",
                       "ADR-project-contract-007", "row check", "read-only route",
                       "release transaction run", "cd", "xargs", "schema", "just switch",
                       "command position", "--title",
                       "can remove a project's production refusals"):
            self.assertIn(needle, adr)
        adr_006 = "docs/areas/guard/adr/006-two-policy-files-one-trust-rule-each.md"
        for amended in (adr_006, "docs/areas/guard/adr/007-derived-rows-rechecked-at-use.md"):
            status = [line for line in (REPO_ROOT / amended).read_text().splitlines()
                      if line.startswith("- **Status:**")]
            self.assertEqual(status, ["- **Status:** accepted; amended by ADR-guard-011"])
            self.assertIn("ADR-guard-011", self.doc(amended))
        self.assertNotIn("Rewriting the compiled policy alone gains nothing", self.doc(adr_006))
        self.assertIn("can remove a project's production refusals", self.doc(adr_006))

    def test_the_release_result_adr_limits_one_mutation_to_the_forge_adapter(self):
        text = self.doc("docs/areas/release/adr/005-adapters-never-claim-success.md")
        self.assertNotIn("An adapter makes at most one mutation", text)
        self.assertIn("The forge adapter makes at most one mutation", text)
        self.assertIn("launchd adapter", text)

    def test_the_goal_field_focus_is_recorded(self):
        text = self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md")
        self.assertIn("In focus the field shows one border", text)


    def test_the_land_queue_measurement_holds_thirty_landings(self):
        path = REPO_ROOT / LAND_QUEUE_DOC
        text = path.read_text(encoding="utf-8")
        lines = land_queue_section(text, "Measurements").splitlines()

        def cells(row):
            return [c.strip() for c in row.strip().strip("|").split("|")]

        def rows_after(header):
            at = lines.index(header)
            self.assertLess(at + 1, len(lines))
            rows = []
            for line in lines[at + 2 :]:
                if not line.startswith("|"):
                    break
                if line.startswith("| #"):
                    rows.append(line)
            return at, rows

        self.assertIn(LAND_QUEUE_HEADER, lines)
        at, rows = rows_after(LAND_QUEUE_HEADER)
        self.assertEqual(lines[at + 1], LAND_QUEUE_SEPARATOR)
        self.assertGreaterEqual(len(rows), 30)
        for row in rows:
            self.assertEqual(len(cells(row)), 15, row)
        firsts = [cells(row)[0] for row in rows]
        self.assertEqual(len(set(firsts)), len(firsts))
        for row in rows:
            for index in (6, 14):
                value = cells(row)[index]
                self.assertTrue(value == "-" or float(value) >= 0, row)
        self.assertIn(LAND_QUEUE_PROVENANCE_HEADER, lines)
        pat, provenance = rows_after(LAND_QUEUE_PROVENANCE_HEADER)
        self.assertEqual(lines[pat + 1], "|---:|---|---:|---:|---:|---|")
        self.assertEqual([cells(row)[0] for row in provenance], firsts)
        fences = LAND_QUEUE_FENCE.findall(land_queue_section(text, "Reproduce"))
        self.assertEqual(len(fences), 1)
        self.assertIn('["gh", ', fences[0])
        self.assertIn("python3 -I -", fences[0])

    def test_the_land_queue_program_measures_only_the_landing_interval(self):
        text = (REPO_ROOT / LAND_QUEUE_DOC).read_text(encoding="utf-8")
        fences = LAND_QUEUE_FENCE.findall(land_queue_section(text, "Reproduce"))
        self.assertEqual(len(fences), 1)
        fence = fences[0]
        repo = "repos/fagenorn/nix-config"

        def stamp(base, minutes):
            from datetime import datetime, timedelta, timezone

            value = datetime.strptime(base, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            return (value + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

        pulls = []
        merged = {1000: "2026-11-16T07:00:00Z", 1042: "2026-11-16T23:00:00Z"}
        for step, number in enumerate(range(1001, 1042)):
            merged[number] = stamp("2026-11-16T08:00:00Z", 20 * step)
        self.assertEqual(merged[1041], "2026-11-16T21:20:00Z")
        for number in sorted(merged):
            head = {1040: "release-v1", 1041: "issue-77-x"}.get(number, f"issue-{number}-x")
            pulls.append(
                {
                    "number": number,
                    "createdAt": stamp(merged[number], -60),
                    "mergedAt": merged[number],
                    "headRefName": head,
                    "headRefOid": "a" * 40 if number == 1041 else f"{number:040d}",
                    "mergeCommit": {"oid": f"{number + 5000:040d}"},
                }
            )
        # An indirect merge: the forge marks it merged because its own head reached main
        # inside another landing, so its merge commit is its head and it held no lock cycle.
        pulls.append(
            {
                "number": 1500,
                "createdAt": "2026-11-16T13:30:00Z",
                "mergedAt": "2026-11-16T14:30:00Z",
                "headRefName": "issue-1500-x",
                "headRefOid": f"{1500:040d}",
                "mergeCommit": {"oid": f"{1500:040d}"},
            }
        )
        fixture = {
            "pr list --repo fagenorn/nix-config --state merged --base main --search"
            " merged:2026-11-13..2026-11-16 --limit 300"
            " --json number,createdAt,mergedAt,headRefName,headRefOid,mergeCommit": pulls
        }
        for pull in pulls:
            if not 1002 <= pull["number"] <= 1040:
                continue
            fixture[
                f"api {repo}/actions/workflows/ci.yaml/runs?branch={pull['headRefName']}"
                "&event=pull_request&per_page=100"
            ] = {"total_count": 0, "workflow_runs": []}
            fixture[f"api {repo}/commits/{pull['headRefOid']}/check-runs?per_page=100&filter=all"] = {
                "total_count": 0,
                "check_runs": [],
            }
        day = "2026-11-16T"
        fixture[
            f"api {repo}/actions/workflows/ci.yaml/runs?branch=issue-77-x&event=pull_request&per_page=100"
        ] = {
            "total_count": 2,
            "workflow_runs": [
                {"id": 500, "run_attempt": 1, "run_started_at": "2026-11-15T19:20:00Z"},
                {"id": 501, "run_attempt": 2, "run_started_at": day + "21:50:00Z"},
            ],
        }
        fixture[f"api {repo}/actions/runs/501/attempts/1"] = {"run_attempt": 1, "run_started_at": day + "21:02:00Z"}
        fixture[f"api {repo}/actions/runs/501/attempts/2"] = {"run_attempt": 2, "run_started_at": day + "21:50:00Z"}

        def check(ident, name, conclusion, start, end, app=15368):
            return {
                "id": ident,
                "name": name,
                "status": "completed",
                "conclusion": conclusion,
                "started_at": day + start + "Z",
                "completed_at": day + end + "Z",
                "app": {"id": app},
            }

        fixture[f"api {repo}/commits/{'a' * 40}/check-runs?per_page=100&filter=all"] = {
            "total_count": 7,
            "check_runs": [
                check(9001, "Agent Workflow Tests", "success", "21:03:00", "21:11:00"),
                check(9002, "Agent Workflow Tests", "success", "21:51:00", "21:59:00"),
                check(9003, "Nix Eval", "success", "21:03:00", "21:04:00"),
                check(9004, "Instruction Budget", "success", "21:03:00", "21:03:06"),
                check(9005, "Nix Eval", "failure", "21:05:00", "21:05:30"),
                check(9006, "Flake Checker", "success", "21:00:30", "21:12:00"),
                check(9007, "Agent Workflow Tests", "success", "21:12:00", "21:13:00", app=99),
            ],
        }
        fixture[f"api {repo}/actions/jobs/9001"] = {
            "id": 9001,
            "started_at": day + "21:03:00Z",
            "steps": [
                {"name": "Set up job", "started_at": day + "21:03:00Z", "completed_at": day + "21:03:05Z"},
                {
                    "name": "Run agent workflow tests",
                    "started_at": day + "21:03:30Z",
                    "completed_at": day + "21:11:00Z",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "python3").symlink_to(sys.executable)
            fixture_path = root / "fixture.json"
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            gh = bin_dir / "gh"
            gh.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "key = ' '.join(sys.argv[1:])\n"
                "data = json.load(open(os.environ['FAKE_GH_FIXTURE']))\n"
                "if key not in data:\n"
                "    sys.stderr.write('unexpected gh call: ' + key + '\\n')\n"
                "    sys.exit(1)\n"
                "print(json.dumps(data[key]))\n",
                encoding="utf-8",
            )
            gh.chmod(0o755)
            result = subprocess.run(
                ["bash", "-c", fence],
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "FAKE_GH_FIXTURE": str(fixture_path),
                },
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.splitlines()
        for expected in (
            "| #1041 | 77 | 2026-11-16 21:20:00 | 60.0 | 40.0 | 20.0 | 2.0 | 1 | 1.0 | 8.0 | 0.5 | 7.5 | 0.1 | 8.0 | 9.0 |",
            "| #1041 | aaaaaaaaaaaa | 9003 | 9001 | 9004 | 501/1 |",
            "| Hold (min) | 20.0 | 20.0 | 20.0 | 780.0 |",
            "| CI runs | 0.0 | 0.0 | 1.0 | 1.0 |",
            "| Green to merge (min) | 9.0 | 9.0 | 9.0 | 9.0 |",
            "Landings: 39, merged 2026-11-16 08:40:00 to 2026-11-16 21:20:00 (UTC).",
        ):
            self.assertIn(expected, out)
        self.assertTrue(any(line.startswith("| #1040 | - | 2026-11-16 21:00:00 |") for line in out))
        self.assertTrue(
            any(line.startswith("| #1021 | 1021 | 2026-11-16 14:40:00 | 60.0 | 40.0 | 20.0 |") for line in out),
            "an indirect merge must not be the predecessor of the landing after it",
        )
        self.assertIn(
            "Indirect merges (no lock cycle of their own): #1500 merged 2026-11-16 14:30:00 (UTC).", out
        )
        for number in (1000, 1001, 1002, 1042, 1500):
            self.assertFalse(any(line.startswith(f"| #{number} ") for line in out), number)
        self.assertEqual(sum(1 for line in out if line.startswith("| #")), 78)


    def test_the_land_queue_proposal_keeps_every_required_check(self):
        protection = json.loads((REPO_ROOT / ".github/branch-protection.json").read_text(encoding="utf-8"))
        contexts = [c["context"] for c in protection["required_status_checks"]["checks"]]
        text = (REPO_ROOT / LAND_QUEUE_DOC).read_text(encoding="utf-8")
        lines = land_queue_section(text, "Measurements").splitlines()
        at = lines.index("| Figure | Median | p90 | Max | Sum |")
        summary = {}
        for line in lines[at + 2 :]:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            summary[cells[0]] = cells[1]
        self.assertIn("\n## Proposal\n", text)
        self.assertIn("\n## Alternatives considered\n", text)
        proposal = land_queue_section(text, "Proposal")
        alternatives = land_queue_section(text, "Alternatives considered")
        m = re.search(
            r"(?m)^\*\*Expected saving per queued pull request \(an assumed scenario, not a bound\):\*\*"
            r" assume (\d+\.\d) min per landing ahead of it \(the median of `([^`]+)`\)",
            proposal,
        )
        self.assertEqual(len(contexts), 3)
        for context in contexts:
            self.assertIn(context, proposal)
        self.assertIn("`strict`", proposal)
        self.assertIn("`.github/branch-protection.json`", proposal)
        self.assertIsNotNone(m)
        self.assertIn(m[2], ("AWT before test step (min)", "Green to merge (min)", "Handoff (min)"))
        self.assertEqual(m[1], summary[m[2]])
        if m[2] == "Handoff (min)":
            self.assertIn("its own hold is unchanged", proposal)
            saving = next(p for p in proposal.split("\n\n") if p.startswith("**Expected saving"))
            self.assertNotIn("at most", saving)
            self.assertNotIn("upper bound", saving)
            self.assertIn("does not bound", saving)
            self.assertIn("sync push", saving)
            self.assertIn("removable polling delay is unknown", saving)
            self.assertNotRegex(alternatives + proposal.split("**Expected saving")[0], r"[Ss]aving at most")
            self.assertIn("`python/agent_tools/claims/forge_land_lock.py`", proposal)
        else:
            self.assertIn(f"its own hold is at most {m[1]} min shorter", proposal)
            self.assertIn("`forge-claim land` is unchanged", proposal)
        self.assertGreaterEqual(len(re.findall(r"(?m)^- \*\*", alternatives)), 3)


    def _awt_fixture(self):
        from datetime import datetime, timedelta

        repo = "repos/fagenorn/nix-config"
        job_log = (
            "\ufeff2026-11-16T21:03:20.0000000Z ##[group]Run actions/checkout@v4\n"
            "2026-11-16T21:03:30.2500000Z ##[group]Run WORKFLOW_POLICY_SURFACE=source nix shell"
            " --inputs-from . nixpkgs#just nixpkgs#nodejs --command just agent-workflow-tests\n"
            "2026-11-16T21:03:35.0000000Z copying path '/nix/store/x-just' from 'https://cache.nixos.org'...\n"
            "2026-11-16T21:03:42.2500000Z suite-runner: start tests/a.py\n"
            "2026-11-16T21:03:42.2600000Z suite-runner: start tests/b.py\n"
            "2026-11-16T21:04:42.0000000Z suite-runner: begin tests/b.py\n"
            "2026-11-16T21:04:42.0000000Z suite-runner:     5.0s wall     1.0s cpu passed tests/fake.py\n"
            "2026-11-16T21:04:42.0000000Z suite-runner: summary members=1 passed=1 failed=0 jobs=1 wall=5.0s cpu=1.0s\n"
            "2026-11-16T21:04:42.0000000Z Ran 1 test in 0.001s\n"
            "2026-11-16T21:04:42.0000000Z Ran 3 tests in 30.000s\n"
            "2026-11-16T21:04:42.0000000Z suite-runner: end tests/b.py passed exit=0 60.0s\n"
            "2026-11-16T21:04:42.1000000Z suite-runner: start tests/c.sh\n"
            "2026-11-16T21:05:22.0000000Z suite-runner: begin tests/a.py\n"
            "2026-11-16T21:05:22.0000000Z Ran 10 tests in 80.000s\n"
            "2026-11-16T21:05:22.0000000Z suite-runner: end tests/a.py passed exit=0 100.0s\n"
            "2026-11-16T21:05:42.0000000Z suite-runner: begin tests/c.sh\n"
            "2026-11-16T21:05:42.0000000Z ok\n"
            "2026-11-16T21:05:42.0000000Z suite-runner: end tests/c.sh passed exit=0 60.0s\n"
            "2026-11-16T21:06:12.0000000Z suite-runner: timings, slowest first\n"
            "2026-11-16T21:06:12.0000000Z suite-runner:   100.0s wall    90.0s cpu passed tests/a.py\n"
            "2026-11-16T21:06:12.0000000Z suite-runner:    60.0s wall    30.0s cpu passed tests/b.py\n"
            "2026-11-16T21:06:12.0000000Z suite-runner:    60.0s wall    60.0s cpu passed tests/c.sh\n"
            "2026-11-16T21:06:12.0000000Z suite-runner: summary members=3 passed=3 failed=0 jobs=2 wall=150.0s cpu=220.0s\n"
        )

        def shifted(seconds):
            out = []
            for index, line in enumerate(job_log.splitlines(keepends=True)):
                if index >= 2:
                    stamp, rest = line.split(" ", 1)
                    when = datetime.strptime(stamp[:26], "%Y-%m-%dT%H:%M:%S.%f") + timedelta(seconds=seconds)
                    line = when.strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z " + rest
                out.append(line)
            return "".join(out)

        def stamp(base, delta):
            return (datetime.strptime(base, "%Y-%m-%dT%H:%M:%SZ") + timedelta(seconds=delta)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        def job(job_id, conclusion, completed, realization=None, steps=True, name="Agent Workflow Tests"):
            record = {
                "id": job_id,
                "name": name,
                "status": "completed",
                "conclusion": conclusion,
                "started_at": stamp(completed, -1000),
                "completed_at": completed,
                "steps": [],
            }
            if steps:
                record["steps"] = [
                    {
                        "name": "Run agent workflow tests",
                        "started_at": stamp(completed, -8 - (realization + 150)),
                        "completed_at": stamp(completed, -8),
                    }
                ]
            return record

        def run(run_id, branch, attempts=1):
            return {"id": run_id, "run_attempt": attempts, "head_branch": branch}

        listing = [run(601, "issue-77-x", 2)]
        fixture = {}
        fixture[f"api {repo}/actions/runs/601/attempts/1/jobs"] = {
            "total_count": 2,
            "jobs": [
                {
                    "id": 7001,
                    "name": "Agent Workflow Tests",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "2026-11-16T21:00:00Z",
                    "completed_at": "2026-11-16T21:06:20Z",
                    "steps": [
                        {
                            "name": "Run agent workflow tests",
                            "started_at": "2026-11-16T21:03:30Z",
                            "completed_at": "2026-11-16T21:06:12Z",
                        }
                    ],
                },
                {
                    "id": 7101,
                    "name": "Nix Eval",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "2026-11-16T21:00:00Z",
                    "completed_at": "2026-11-16T21:02:00Z",
                    "steps": [],
                },
            ],
        }
        fixture[f"api {repo}/actions/runs/601/attempts/2/jobs"] = {
            "total_count": 1,
            "jobs": [job(7002, "success", "2026-11-17T00:10:00Z", 12)],
        }
        fixture[f"api {repo}/actions/jobs/7001/logs"] = job_log
        for run_id in range(602, 626):
            j = run_id - 603
            if run_id == 602:
                r = 12
            elif j < 20:
                r = 12 * (j + 1)
            else:
                r = {623: 360, 624: 480, 625: 720}[run_id]
            completed = stamp("2026-11-16T12:00:00Z", 20 * 60 * (run_id - 602))
            listing.append(run(run_id, f"issue-{run_id}-x"))
            fixture[f"api {repo}/actions/runs/{run_id}/attempts/1/jobs"] = {
                "total_count": 1,
                "jobs": [job(7000 + run_id, "success", completed, r)],
            }
            if run_id >= 603:
                fixture[f"api {repo}/actions/jobs/{7000 + run_id}/logs"] = shifted(r - 12)
        for run_id, job_id, conclusion, completed, name in (
            (626, 7626, "cancelled", "2026-11-16T20:00:00Z", "Agent Workflow Tests"),
            (627, 7627, "failure", "2026-11-16T20:10:00Z", "Agent Workflow Tests"),
            (628, 7628, "success", "2026-11-17T00:00:01Z", "Agent Workflow Tests"),
            (629, 7629, "success", "2026-11-16T20:20:00Z", "Nix Eval"),
        ):
            listing.append(run(run_id, f"issue-{run_id}-x"))
            fixture[f"api {repo}/actions/runs/{run_id}/attempts/1/jobs"] = {
                "total_count": 1,
                "jobs": [job(job_id, conclusion, completed, 12, steps=name == "Agent Workflow Tests", name=name)],
            }
        fixture[
            f"api {repo}/actions/workflows/ci.yaml/runs?event=pull_request&created=<2026-11-17T00:00:00Z&per_page=100"
        ] = {"total_count": 29, "workflow_runs": listing}
        return fixture

    def _run_awt_fence(self, fixture):
        text = (REPO_ROOT / AWT_TIME_DOC).read_text(encoding="utf-8")
        fences = LAND_QUEUE_FENCE.findall(land_queue_section(text, "Reproduce"))
        self.assertEqual(len(fences), 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "python3").symlink_to(sys.executable)
            fixture_path = root / "fixture.json"
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            gh = bin_dir / "gh"
            gh.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "key = ' '.join(sys.argv[1:])\n"
                "data = json.load(open(os.environ['FAKE_GH_FIXTURE'], encoding='utf-8'))\n"
                "if key not in data:\n"
                "    sys.stderr.write('unexpected gh call: ' + key + '\\n')\n"
                "    sys.exit(1)\n"
                "value = data[key]\n"
                "if isinstance(value, str):\n"
                "    sys.stdout.write(value)\n"
                "else:\n"
                "    print(json.dumps(value))\n",
                encoding="utf-8",
            )
            gh.chmod(0o755)
            return subprocess.run(
                ["bash", "-c", fences[0]],
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "FAKE_GH_FIXTURE": str(fixture_path),
                    "PYTHONIOENCODING": "utf-8",
                },
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )

    def test_the_test_job_program_splits_the_step_from_the_runner_log(self):
        result = self._run_awt_fence(self._awt_fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.splitlines()
        for expected in (
            "| 7001 | 601/1 | 77 | 2026-11-16 21:06:20 | 2.7 | 0.2 | 0.6 | 1.9 | 0.0 | 3 | 2 | 73 | 73 | 0.5 | 0.8 | 0.2 | 0.7 |",
            "| 7625 | 625/1 | 625 | 2026-11-16 19:40:00 | 14.5 | 12.0 | 0.6 | 1.9 | 0.0 | 3 | 2 | 73 | 73 | 0.5 | 0.8 | 12.0 | 0.7 |",
            "| Order saving (min) | 0.5 | 0.5 | 0.5 |",
            "| Slots saving (min) | 0.8 | 0.8 | 0.8 |",
            "| Test step (min) | 4.8 | 8.5 | 14.5 |",
            "| Realization (min) | 2.3 | 6.0 | 12.0 |",
            "| Cache saving (min) | 2.3 | 6.0 | 12.0 |",
            "| Slots estimate (min) | 0.7 | 0.7 | 0.7 |",
            "Jobs: 24, completed 2026-11-16 12:20:00 to 2026-11-16 21:06:20 (UTC).",
        ):
            self.assertIn(expected, out)
        job_rows = [line for line in out if line.startswith("| 7")]
        self.assertEqual(len(job_rows), 24)
        self.assertTrue(job_rows[0].startswith("| 7603 | 603/1 | 603 | 2026-11-16 12:20:00 | 2.7 | 0.2 |"), job_rows[0])
        for absent in ("7002", "7602", "7626", "7627", "7628", "7629", "7101"):
            self.assertFalse(any(line.startswith(f"| {absent} ") for line in out), absent)
        members = [
            "| tests/a.py | 24 | 100.0 | 90.0 | 20.0 | 80.0 |",
            "| tests/b.py | 24 | 60.0 | 30.0 | 30.0 | 30.0 |",
            "| tests/c.sh | 24 | 60.0 | 60.0 | - | - |",
        ]
        at = [out.index(line) for line in members]
        self.assertEqual(at, sorted(at))
        self.assertFalse(any("tests/fake.py" in line for line in out))

    def test_the_test_job_program_refuses_a_short_window(self):
        fixture = self._awt_fixture()
        key = "api repos/fagenorn/nix-config/actions/workflows/ci.yaml/runs?event=pull_request&created=<2026-11-17T00:00:00Z&per_page=100"
        fixture[key]["workflow_runs"] = [r for r in fixture[key]["workflow_runs"] if r["id"] not in (602, 603)]
        result = self._run_awt_fence(fixture)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("23", result.stderr)

    def test_the_test_job_program_refuses_a_log_without_a_summary(self):
        fixture = self._awt_fixture()
        log_key = "api repos/fagenorn/nix-config/actions/jobs/7001/logs"
        fixture[log_key] = "".join(fixture[log_key].splitlines(keepends=True)[:-1])
        result = self._run_awt_fence(fixture)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("7001", result.stderr)

    def test_the_test_job_program_refuses_a_python_member_without_a_ran_line(self):
        fixture = self._awt_fixture()
        log_key = "api repos/fagenorn/nix-config/actions/jobs/7001/logs"
        fixture[log_key] = "".join(
            line for line in fixture[log_key].splitlines(keepends=True) if "Ran 10 tests in 80.000s" not in line
        )
        result = self._run_awt_fence(fixture)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("7001", result.stderr)
        self.assertIn("tests/a.py", result.stderr)

    def test_the_test_job_program_refuses_timing_rows_that_disagree_with_the_summary(self):
        fixture = self._awt_fixture()
        log_key = "api repos/fagenorn/nix-config/actions/jobs/7001/logs"
        fixture[log_key] = "".join(
            line
            for line in fixture[log_key].splitlines(keepends=True)
            if "60.0s wall    60.0s cpu passed tests/c.sh" not in line
        )
        result = self._run_awt_fence(fixture)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("7001", result.stderr)
        self.assertIn("members=3", result.stderr)

    def test_the_test_job_measurement_holds_twenty_four_runs(self):
        text = (REPO_ROOT / AWT_TIME_DOC).read_text(encoding="utf-8")
        readme = (REPO_ROOT / "docs/README.md").read_text(encoding="utf-8")
        self.assertIn("| A measurement or other retained evidence | `archive/` |", readme.splitlines())
        section = land_queue_section(text, "Measurements")
        lines = section.splitlines()
        rows, summary, members = awt_tables(text)
        for header, separator in (
            (AWT_TIME_HEADER, AWT_TIME_SEPARATOR),
            (AWT_SUMMARY_HEADER, AWT_SUMMARY_SEPARATOR),
            (AWT_MEMBERS_HEADER, AWT_MEMBERS_SEPARATOR),
        ):
            self.assertEqual(lines[lines.index(header) + 1], separator)
        self.assertEqual(len(rows), 24)
        for row in rows:
            self.assertEqual(len(row), 17, row)
        self.assertEqual(len({row[0] for row in rows}), 24)
        completed = [row[3] for row in rows]
        self.assertEqual(completed, sorted(completed))
        jobs_lines = re.findall(
            r"(?m)^Jobs: (\d+), completed (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) to (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \(UTC\)\.$",
            section,
        )
        self.assertEqual(len(jobs_lines), 1)
        self.assertEqual(jobs_lines[0][0], str(len(rows)))
        self.assertEqual(jobs_lines[0][0], "24")
        self.assertEqual(jobs_lines[0][1], rows[0][3])
        self.assertEqual(jobs_lines[0][2], rows[-1][3])
        for row in rows:
            parts = sum(float(row[i]) for i in (5, 6, 7, 8))
            self.assertLessEqual(abs(parts - float(row[4])), 0.25, row)
        headers = [c.strip() for c in AWT_TIME_HEADER.strip().strip("|").split("|")]
        self.assertEqual(list(summary), headers[4:17])
        for index, figure in enumerate(headers):
            if index < 4:
                continue
            col = [float(row[index]) for row in rows]
            self.assertEqual(
                summary[figure],
                [f"{statistics.median(col):.1f}", f"{sorted(col)[math.ceil(0.9 * len(col)) - 1]:.1f}", f"{max(col):.1f}"],
                figure,
            )
        self.assertGreaterEqual(len(members), 10)
        for row in members:
            self.assertEqual(len(row), 6, row)
        fences = LAND_QUEUE_FENCE.findall(land_queue_section(text, "Reproduce"))
        self.assertEqual(len(fences), 1)
        for needle in ("python3 -I - <<'PY'", 'CUTOFF = "2026-11-17T00:00:00Z"', "ROWS = 24", "VCPUS = 4", "SLOTS = 6"):
            self.assertIn(needle, fences[0])


    def test_the_test_job_proposal_keeps_every_test_and_the_required_check(self):
        text = (REPO_ROOT / AWT_TIME_DOC).read_text(encoding="utf-8")
        rows, summary, _members = awt_tables(text)
        protection = json.loads((REPO_ROOT / ".github/branch-protection.json").read_text(encoding="utf-8"))
        contexts = [c["context"] for c in protection["required_status_checks"]["checks"]]
        proposal = land_queue_section(text, "Proposal")
        alternatives = land_queue_section(text, "Alternatives considered")
        maxima = ("Slots saving (min)", "Cache saving (min)")
        tie_order = ("Cache saving (min)", "Order saving (min)", "Slots saving (min)")
        m = re.search(
            r"(?m)^\*\*Expected saving per run \((an estimate, not a bound|a maximum, not an estimate)\):\*\* "
            r"(at most )?(\d+\.\d) min, the median of `([^`]+)`\.",
            proposal,
        )
        best = max(tie_order, key=lambda f: float(summary[f][0]))
        saving = next((p for p in proposal.split("\n\n") if p.startswith("**Expected saving per run")), "")
        opening = proposal.split("**What changes.**")[0]
        self.assertIn("\n## Proposal\n", text)
        self.assertIn("\n## Alternatives considered\n", text)
        self.assertGreater(text.index("\n## Proposal\n"), text.index("\n## Reproduce\n"))
        self.assertIsNotNone(m)
        self.assertEqual(m[4], best)
        self.assertEqual(m[3], summary[best][0])
        estimate = re.search(
            r"(?m)^\*\*Estimated saving at (\d+) jobs:\*\* (\d+\.\d) min, the median of `Slots estimate \(min\)`"
            r" \(p90 (\d+\.\d), maximum (\d+\.\d)\), an estimate\.",
            proposal,
        )
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate[1], "6")
        self.assertEqual(list(estimate.groups()[1:]), summary["Slots estimate (min)"])
        self.assertIn("SLOTS = 6", text)
        self.assertIn("could be smaller, down to none", proposal)
        self.assertIn(
            "The pick compares two maxima, `Slots saving (min)` and `Cache saving (min)`, with one estimate,"
            " `Order saving (min)`: a maximum is the most a change could save, not what it will save.",
            opening,
        )
        if best in maxima:
            self.assertEqual(m[1], "a maximum, not an estimate")
            self.assertEqual(m[2], "at most ")
            if best == "Slots saving (min)":
                self.assertIn("longest member", saving)
                self.assertIn("4 vCPUs", saving)
            else:
                self.assertIn("restoring the cache takes no time", saving)
        else:
            self.assertEqual(m[1], "an estimate, not a bound")
            self.assertIsNone(m[2])
            self.assertIn("so it bounds nothing", saving)
        self.assertEqual(len(contexts), 3)
        for context in contexts:
            self.assertIn(context, proposal)
        for needle in (
            "`strict`",
            "`.github/branch-protection.json`",
            "`.agents/knowledge/rejections/ungated-agent-merges.md`",
            "This document only proposes it; adopting it is a later issue.",
            f"Every one of the {rows[-1][9]} suite members still runs",
        ):
            self.assertIn(needle, proposal)
        required = {
            "Order saving (min)": ("`python/agent_tools/delivery/suite_timings.json`",),
            "Slots saving (min)": (
                "`.github/workflows/ci.yaml`",
                "`SUITE_RUNNER_JOBS`",
                "`docs/areas/delivery/adr/006-suite-members-run-in-parallel.md`",
            ),
            "Cache saving (min)": ("`.github/workflows/ci.yaml`",),
        }[best]
        for needle in required:
            self.assertIn(needle, proposal)
        bullets = [line for line in alternatives.splitlines() if line.startswith("- **")]
        for candidate in tie_order:
            if candidate == best:
                continue
            named = [line for line in bullets if f"`{candidate}`" in line]
            self.assertEqual(len(named), 1, candidate)
            if candidate in maxima:
                self.assertIn(f"at most {summary[candidate][0]} min", named[0])
            else:
                self.assertIn(f"{summary[candidate][0]} min", named[0])
                self.assertIn("estimate", named[0])
        for needle in ("`Start-up (min)`", "larger runner", "ungated-agent-merges.md"):
            self.assertIn(needle, alternatives)
        self.assertGreaterEqual(len(re.findall(r"(?m)^- \*\*", alternatives)), 5)


if __name__ == "__main__":
    unittest.main()
