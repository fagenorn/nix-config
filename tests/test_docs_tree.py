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
                     "Message", "Nudge", "Question round"):
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
        both = "- **Status:** accepted; amended by ADR-console-024, ADR-console-025"
        for older, status in (
                ("docs/areas/console/adr/008-only-the-page-writes-with-a-token-and-its-origin.md", both),
                ("docs/areas/console/adr/002-the-desk-page-design-rules.md", both),
                ("docs/areas/console/adr/024-the-owner-signs-a-profile-in-from-the-page.md",
                 "- **Status:** accepted; amended by ADR-console-025")):
            line = next(row for row in (REPO_ROOT / older).read_text().splitlines()
                        if row.startswith("- **Status:**"))
            self.assertEqual(line, status)

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
        for needle in ('a closed "More" fold holding "Withdraw"', "a typed draft keeps it open"):
            self.assertIn(needle, rules)
        self.assertNotIn('withdraw, messages and "Tell the manager" stay under the two lines', rules)
        message = self.doc(
            "docs/areas/console/adr/016-what-the-owner-says-to-a-sprint-reaches-its-manager.md")
        for needle in ("opens its field on demand", 'the rest in its "Detail" fold'):
            self.assertIn(needle, message)

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
                       "may be stuck", "fifteen minutes", "Detail", "closed out",
                       "ADR-console-005", "ADR-console-008", "ADR-console-009",
                       "ADR-console-013", "#835", "#837", "#838", "#890"):
            self.assertIn(needle, adr)
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

    def test_the_release_result_adr_limits_one_mutation_to_the_forge_adapter(self):
        text = self.doc("docs/areas/release/adr/005-adapters-never-claim-success.md")
        self.assertNotIn("An adapter makes at most one mutation", text)
        self.assertIn("The forge adapter makes at most one mutation", text)
        self.assertIn("launchd adapter", text)

    def test_the_goal_field_focus_is_recorded(self):
        text = self.doc("docs/areas/console/adr/002-the-desk-page-design-rules.md")
        self.assertIn("In focus the field shows one border", text)


if __name__ == "__main__":
    unittest.main()
