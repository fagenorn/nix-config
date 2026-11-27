"""The router command: the routed set of one change at one stage, computed with no model."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import router, routing
from agent_tools.delivery.dotnet_solution import SOLUTION_ROOT
from tests.never_rise_world import commit_all, mark_base, repo, write

REPO_ROOT = Path(__file__).resolve().parents[1]
TIER = "integration"

REVISION = {
    "schema_version": 1, "type": "github", "owner": "o", "repo": "r", "rev": "a" * 40,
    "narHash": "sha256-" + "A" * 43 + "=", "lastModified": 1}
PLATFORM_FILES = {
    "the-bar.md": "# The Bar\n\n### B1. Fail loud\n\nbody\n\n### B2. Root causes\n\nbody\n",
    "stacks/python.md": "# Python\n\n### PY1. Use pathlib\n\nbody\n",
    "stacks/node.md": "# Node\n\n### NODE1. ESM\n\nbody\n",
}
WEB = "# Web\n\n### P2. Pages\n\nbody\n### P3. Assets\n\nbody\n"
REPO_FILES = {
    "docs/standards/README.md": (
        "# Project standards\n\n| Shard | governs | Gist |\n|---|---|---|\n"
        "| [helpers.md](helpers.md) | `python/**` | H. |\n"
        "| [web.md](./web.md) | `web/**` | W. |\n"),
    "docs/standards/helpers.md": "# Helpers\n\n### P1. In the package\n\nbody\n",
    "docs/standards/web.md": WEB,
    "docs/CONTEXT-MAP.md": (
        "# Map\n\n## Areas\n\n| Area | Context file | Gist | governs |\n|---|---|---|---|\n"
        "| Alpha | [CONTEXT](./areas/alpha/CONTEXT.md) | A | `tools/**` |\n"
        "| Beta | [CONTEXT](./areas/beta/CONTEXT.md) | B | `beta/**` |\n"),
    "docs/areas/alpha/adr/001-first.md": "# ADR-alpha-001 — First\n\nBody.\n",
    "docs/areas/alpha/adr/002-second.md": "# ADR-alpha-002 — Second\n\nBody.\n",
    "docs/areas/beta/adr/001-other.md": "# ADR-beta-001 — Other\n\nBody.\n",
    ".agents/knowledge/hints/planning.md": "plan hint\n",
    ".agents/knowledge/hints/building.md": "build hint\n",
    "tools/run.py": "# see ADR-beta-001\n",
    "web/page.html": "<p></p>\n",
}


class World(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.root = self.tmp / "root"
        self.platform = self.root / "standards"
        for name, text in PLATFORM_FILES.items():
            write(self.platform, name, text)
        write(self.root, "platform-revision.json", json.dumps(REVISION))
        self.repo = repo(self.tmp)
        for name, text in REPO_FILES.items():
            write(self.repo, name, text)
        commit_all(self.repo, "base")
        self.base = mark_base(self.repo)
        write(self.repo, "tools/run.py", "# see ADR-beta-001\nx = 1\n")
        write(self.repo, "web/page.html", "<p>x</p>\n")
        commit_all(self.repo, "change")

    def route(self, stage, *change, repo_root=None, platform=None):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.router",
             "--repo-root", str(repo_root or self.repo),
             "--platform-standards", str(platform or self.platform),
             "--stage", stage, *change],
            env={**os.environ, "AGENT_PLATFORM_ROOT": str(self.root)},
            capture_output=True, stdin=subprocess.DEVNULL)

    def plan(self):
        return self.route("planning", "--path", "tools/run.py", "--path", "web/page.html")


class RouterTest(World):
    def test_one_extension_and_one_governed_path_route_exactly_the_bar_and_their_two_shards(self):
        done = self.plan()
        self.assertEqual(done.returncode, 0, done.stderr)
        doc = json.loads(done.stdout)
        self.assertEqual(
            [(s["layer"], s["path"]) for s in doc["shards"]],
            [("bar", f"{self.platform}/the-bar.md"),
             ("stack", f"{self.platform}/stacks/python.md"),
             ("project", f"{self.repo}/docs/standards/web.md")])

    def test_a_cited_record_is_must_read_and_the_index_lists_only_the_matching_area(self):
        doc = json.loads(self.plan().stdout)
        record = self.repo / "docs/areas/beta/adr/001-other.md"
        self.assertEqual(
            doc["must_read"],
            [{"id": "ADR-beta-001", "path": str(record), "bytes": record.stat().st_size}])
        self.assertEqual(
            doc["index"],
            [{"area": "Alpha", "records": ["ADR-alpha-001 — First", "ADR-alpha-002 — Second"]}])

    def test_a_plan_call_and_a_diff_call_over_the_same_paths_share_shards_and_take_their_own_hint(self):
        planned = json.loads(self.plan().stdout)
        built = json.loads(self.route("building", "--diff", f"{self.base}..HEAD").stdout)
        self.assertEqual(planned["shards"], built["shards"])
        hints = f"{self.repo}/.agents/knowledge/hints"
        self.assertEqual(planned["hint"]["path"], f"{hints}/planning.md")
        self.assertEqual(built["hint"]["path"], f"{hints}/building.md")
        self.assertEqual(planned["change"]["paths"], ["tools/run.py", "web/page.html"])
        self.assertEqual(built["change"]["paths"], ["tools/run.py", "web/page.html"])
        self.assertEqual(built["change"]["diff"], f"{self.base}..HEAD")

    def test_the_output_lists_rule_ids_the_revision_and_the_summed_size_identically_twice(self):
        first, second = self.plan(), self.plan()
        self.assertEqual(first.stdout, second.stdout)
        doc = json.loads(first.stdout)
        self.assertEqual([s["rules"] for s in doc["shards"]], [["B1", "B2"], ["PY1"], ["P2", "P3"]])
        self.assertEqual(doc["platform_revision"], "a" * 40)
        lines = [line for area in doc["index"] for line in area["records"]]
        self.assertEqual(doc["index_bytes"], sum(len(line.encode()) + 1 for line in lines))
        paths = [s["path"] for s in doc["shards"]] + [doc["hint"]["path"]]
        paths += [m["path"] for m in doc["must_read"]]
        self.assertEqual(
            doc["total_bytes"], sum(os.path.getsize(p) for p in paths) + doc["index_bytes"])

    def test_a_wide_change_over_24_kb_is_listed_whole(self):
        write(self.repo, "docs/standards/web.md", WEB + "x" * (30000 - len(WEB)))
        done = self.plan()
        self.assertEqual(done.returncode, 0, done.stderr)
        doc = json.loads(done.stdout)
        self.assertEqual(len(doc["shards"]), 3)
        self.assertGreater(doc["total_bytes"], 24576)

    def test_a_plan_stage_given_a_diff_and_a_build_stage_given_paths_are_misuse(self):
        for args in (("planning", "--diff", "HEAD~1..HEAD"), ("building", "--path", "tools/run.py")):
            with self.subTest(args=args):
                done = self.route(*args)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, b"")
                self.assertTrue(done.stderr.startswith(b"router: "), done.stderr)

    def test_a_routed_stack_shard_missing_from_the_platform_is_misuse(self):
        done = self.route("planning", "--path", "app/main.ts")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, b"")
        self.assertIn(b"stacks/typescript-react.md", done.stderr)


class SinglePathTest(World):
    def test_single_path_bytes_is_the_bar_shards_and_area_index(self):
        names = [name for name in REPO_FILES
                 if name.startswith("docs/") and not name.startswith("docs/areas/") or "/adr/" in name]
        project = routing.read_project(
            {name: (self.repo / name).read_bytes() for name in names})
        platform = routing.load_platform(self.platform)
        alpha = [area for area in project.areas if area.name == "Alpha"]
        expected = (
            (self.platform / "the-bar.md").stat().st_size
            + (self.platform / "stacks/python.md").stat().st_size
            + routing.index_bytes(alpha))
        self.assertEqual(routing.single_path_bytes(project, platform, "tools/run.py"), expected)


class LiveTreeTest(unittest.TestCase):
    def test_every_stack_table_shard_ships_in_the_platform(self):
        stacks = REPO_ROOT / "home/common/agent-skills/standards/stacks"
        for names in routing.STACK_SHARDS.values():
            for name in names:
                self.assertTrue((stacks / name).is_file(), name)

    def test_a_helper_module_routes_the_bar_the_python_shard_and_the_helper_standards(self):
        standards = REPO_ROOT / "home/common/agent-skills/standards"
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.router",
             "--repo-root", str(REPO_ROOT), "--platform-standards", str(standards),
             "--stage", "planning", "--path", "python/agent_tools/delivery/router.py"],
            capture_output=True, stdin=subprocess.DEVNULL,
            env={**os.environ, "AGENT_PLATFORM_ROOT": str(standards.parent)})
        self.assertEqual(done.returncode, 0, done.stderr)
        paths = [s["path"] for s in json.loads(done.stdout)["shards"]]
        self.assertEqual(len(paths), 4)
        for path, suffix in zip(paths, (
                "the-bar.md", "stacks/python.md", "docs/standards/agent-helpers.md",
                "docs/standards/package-layout.md")):
            self.assertTrue(path.endswith(suffix), (path, suffix))

    def test_a_dotnet_source_loads_the_dotnet_shards_and_its_areas_index(self):
        path = f"{SOLUTION_ROOT}/Delivery/Widget.cs"
        standards = REPO_ROOT / "home/common/agent-skills/standards"
        platform = routing.load_platform(standards)
        project = routing.read_project(router.project_files(REPO_ROOT))
        loaded = routing.single_path_bytes(project, platform, path)
        areas = [a for a in project.areas if any(routing.glob_matches(g, path) for g in a.globs)]
        self.assertIn("dotnet.md", routing.stack_shards(path))
        self.assertEqual([a.name for a in areas], ["Delivery", "System"])
        shards = ("the-bar.md", "stacks/dotnet-ai.md", "stacks/dotnet-data.md", "stacks/dotnet.md")
        self.assertEqual(
            loaded, sum(len(platform.files[k]) for k in shards) + routing.index_bytes(areas))


if __name__ == "__main__":
    unittest.main()
