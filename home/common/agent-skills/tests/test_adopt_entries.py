"""The guard and edge cases of adoption's hint move and entry-file conversion (#1468).

The issue-named cases sit in `test_adopt_apply.py`; the fixtures and the
test-free bases are imported from it, never a class with tests, so neither file
collects the other's tests.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_tools.project_contract import adopt_conformance, adopt_inspection, adopt_links, resolve_project

from .test_adopt_apply import (
    BOOTSTRAP,
    CONTRACT,
    ENTRY_AGENTS,
    MANAGED_LINE,
    CleanApplyTestCase,
    apply_repo,
    entry_apply_repo,
    hinted_apply_repo,
)
from .test_adopt_conformance import conformance_failure
from .test_adopt_conformance_apply import locked_apply_repo
from .test_adopt_project import PLAN_MEMBERS, commit, drafted_contract, git, init_repo, run, write

TIER = "integration"  # every plan case runs a real git repository

HINT_LINK = "# invariants\n\nSee [planning](../../.claude/hints/planning.md).\n"


class HintMoveGuardTest(CleanApplyTestCase):
    def test_a_hints_binding_follows_the_move_as_a_directory_and_as_a_file(self):
        root = self.owned(hinted_apply_repo(self.home))
        document = self.ready_plan(root)
        result = self.succeed(root, document["plan"]["plan_id"])
        contract = json.loads(git(
            root, "show", f"{result['branch']}:.agents/project.json"))
        self.assertEqual(
            contract["bindings"]["paths"]["hints"],
            [".agents/knowledge/hints", ".agents/knowledge/hints/planning.md"])

    def test_a_plan_with_no_hints_has_no_open_items_member(self):
        root = self.owned(apply_repo(self.home))
        document = self.ready_plan(root)
        self.assertEqual(sorted(document["plan"]), PLAN_MEMBERS)


class EntryConversionGuardTest(CleanApplyTestCase):
    def plan(self, root: Path, *extra: str) -> tuple[int, dict]:
        code, out, err = run("plan", "--repo-root", str(root), *extra, home=self.home)
        return code, json.loads(out) if out.strip() else {"stderr": err}

    def actions(self, document: dict) -> dict[str, str]:
        return {entry["path"]: entry["action"] for entry in document["evidence"]}

    def writes(self, document: dict, target: str) -> list[dict]:
        return [op for op in document["changes"]
                if op["op"] == "write-file" and op["targets"] == [target]]

    def regenerated(self, document: dict) -> list[str]:
        return [op["targets"][0] for op in document["changes"]
                if op["op"] == "regenerate-projection"]

    def adopt(self, root: Path) -> tuple[dict, dict]:
        document = self.ready_plan(root)
        return document, self.succeed(root, document["plan"]["plan_id"])

    def contract(self, root: Path) -> dict:
        return json.loads((root / CONTRACT).read_text("utf-8"))

    def set_projections(self, root: Path, rows: list[dict]) -> None:
        contract = self.contract(root)
        contract["projections"] = rows
        write(root, CONTRACT, json.dumps(contract, indent=2) + "\n")

    def test_agents_md_is_rendered_and_claude_md_is_the_managed_line(self):
        root = self.owned(entry_apply_repo(self.home))
        _, result = self.adopt(root)
        branch = result["branch"]
        committed = json.loads(git(root, "show", f"{branch}:{CONTRACT}"))
        rendered = resolve_project.render_projection(
            dict(adopt_inspection.ENTRY_PROJECTIONS[0]),
            git(root, "show", f"{branch}:{BOOTSTRAP}").encode(),
            committed["schema_version"]).decode()
        self.assertEqual(git(root, "show", f"{branch}:AGENTS.md"), rendered)
        self.assertEqual(git(root, "show", f"{branch}:CLAUDE.md"), MANAGED_LINE)
        for row in adopt_inspection.ENTRY_PROJECTIONS:
            self.assertIn(dict(row), committed["projections"])

    def test_generated_entry_files_plan_no_conversion(self):
        root = self.owned(apply_repo(self.home))
        document = self.ready_plan(root)
        self.assertNotIn("convert-to-source", self.actions(document).values())
        for target in (BOOTSTRAP, "CLAUDE.md"):
            self.assertEqual(self.writes(document, target), [])

    def test_a_stale_generated_agents_md_is_regenerated_not_converted(self):
        root = self.owned(apply_repo(self.home))
        write(root, "AGENTS.md", (root / "AGENTS.md").read_text() + "hand-edited\n")
        commit(root, "drift a projection")
        document = self.ready_plan(root)
        self.assertNotIn("convert-to-source", self.actions(document).values())
        self.assertIn("AGENTS.md", self.regenerated(document))

    def test_an_existing_source_keeps_its_text_first(self):
        root = self.owned(entry_apply_repo(
            self.home, source="# invariants\n", declared=True, claude=MANAGED_LINE))
        document, result = self.adopt(root)
        self.assertEqual(
            self.show(root, f"{result['branch']}:{BOOTSTRAP}"),
            "# invariants\n\n<!-- adopted from AGENTS.md -->\n" + ENTRY_AGENTS)
        self.assertEqual(self.actions(document)["CLAUDE.md"], "generate-projection")

    def test_identical_entry_texts_join_the_source_once(self):
        root = self.owned(entry_apply_repo(self.home, claude=ENTRY_AGENTS))
        _, result = self.adopt(root)
        self.assertEqual(self.show(root, f"{result['branch']}:{BOOTSTRAP}"),
                         "<!-- adopted from AGENTS.md -->\n" + ENTRY_AGENTS)

    def test_a_source_that_already_holds_the_text_is_not_rewritten(self):
        root = self.owned(entry_apply_repo(
            self.home, source=ENTRY_AGENTS, declared=True, claude=MANAGED_LINE))
        document, result = self.adopt(root)
        self.assertEqual(self.writes(document, BOOTSTRAP), [])
        self.assertEqual(self.actions(document)["AGENTS.md"], "convert-to-source")
        branch = result["branch"]
        self.assertEqual(self.show(root, f"{branch}:{BOOTSTRAP}"), ENTRY_AGENTS)
        entry = next(row for row in self.contract(root)["projections"]
                     if row["id"] == "codex.entry")
        self.assertEqual(
            self.show(root, f"{branch}:AGENTS.md"),
            resolve_project.render_projection(
                entry, ENTRY_AGENTS.encode(), self.contract(root)["schema_version"]).decode())

    def test_a_relative_link_in_entry_text_keeps_the_plan_draft(self):
        root = self.owned(entry_apply_repo(
            self.home, agents=ENTRY_AGENTS + "See [the bar](docs/standards/bar.md).\n"))
        code, document = self.plan(root)
        self.assertEqual(code, 0, document)
        self.assertEqual(document["plan"]["state"], "draft")
        self.assertIn({"path": "AGENTS.md", "target": "docs/standards/bar.md"},
                      document["link_rewrites"]["unrewritable"])
        self.assertIn("no-unrewritable-link",
                      [blocker["id"] for blocker in document["plan"]["blockers"]])

    def test_a_link_in_the_source_keeps_the_plan_draft_when_only_claude_md_converts(self):
        root = self.owned(entry_apply_repo(
            self.home, agents=None,
            source="# invariants\n\nSee [the bar](../../docs/standards/bar.md).\n"))
        code, document = self.plan(root)
        self.assertEqual(code, 0, document)
        self.assertEqual(document["plan"]["state"], "draft")
        self.assertIn({"path": BOOTSTRAP, "target": "../../docs/standards/bar.md"},
                      document["link_rewrites"]["unrewritable"])

    def test_a_relative_claude_import_keeps_the_plan_draft(self):
        root = self.owned(entry_apply_repo(
            self.home, claude="# Claude\n\nSee @docs/notes.md and `@not/this.md`.\n"
            + MANAGED_LINE))
        code, document = self.plan(root)
        self.assertEqual(code, 0, document)
        rows = document["link_rewrites"]["unrewritable"]
        self.assertEqual(document["plan"]["state"], "draft")
        self.assertIn({"path": "CLAUDE.md", "target": "docs/notes.md"}, rows)
        self.assertNotIn("not/this.md", [row["target"] for row in rows])

    def test_a_source_the_moves_rewrite_is_written_once(self):
        root = self.owned(hinted_apply_repo(self.home))
        write(root, BOOTSTRAP, HINT_LINK)
        write(root, "AGENTS.md", ENTRY_AGENTS)
        commit(root, "hand-write the entry file")
        code, document = self.plan(root)
        self.assertEqual(code, 0, document)
        self.assertEqual(len(self.writes(document, BOOTSTRAP)), 1)
        self.assertEqual(document["plan"]["state"], "draft")
        self.assertIn({"path": BOOTSTRAP, "target": "../knowledge/hints/planning.md"},
                      document["link_rewrites"]["unrewritable"])

    def test_a_hint_only_adoption_keeps_the_source_link_write(self):
        root = self.owned(hinted_apply_repo(self.home))
        write(root, BOOTSTRAP, HINT_LINK)
        entry = next(row for row in self.contract(root)["projections"]
                     if row["id"] == "codex.entry")
        write(root, "AGENTS.md", resolve_project.render_projection(
            entry, HINT_LINK.encode(), self.contract(root)["schema_version"]).decode())
        commit(root, "regenerate the entry file")
        document = self.ready_plan(root)
        after = adopt_inspection.sha256_hash(
            b"# invariants\n\nSee [planning](../knowledge/hints/planning.md).\n")
        self.assertEqual([op["after"] for op in self.writes(document, BOOTSTRAP)], [after])
        self.assertNotIn("convert-to-source", self.actions(document).values())

    def test_an_undecodable_entry_file_refuses_the_plan(self):
        root = self.owned(entry_apply_repo(self.home, agents=b"\xff\xfe\n"))
        code, document = self.plan(root)
        self.assertEqual(code, 2, document)
        self.assertEqual(document["error"]["repair_id"], "adopt.entry.undecodable")

    def test_a_non_utf8_source_does_not_refuse_a_plan_that_converts_nothing(self):
        root = self.owned(apply_repo(self.home))
        source = b"# caf\xe9\n"
        (root / BOOTSTRAP).write_bytes(source)
        entry = next(row for row in self.contract(root)["projections"]
                     if row["id"] == "codex.entry")
        (root / "AGENTS.md").write_bytes(resolve_project.render_projection(
            entry, source, self.contract(root)["schema_version"]))
        commit(root, "a source that is not UTF-8")
        code, document = self.plan(root)
        self.assertEqual(code, 0, document)
        self.assertNotIn("convert-to-source", self.actions(document).values())

    def test_a_symlinked_entry_file_is_not_converted(self):
        root = self.owned(entry_apply_repo(self.home))
        (root / "AGENTS.md").unlink()
        os.symlink("docs/standards/bar.md", root / "AGENTS.md")
        commit(root, "link the entry file")
        code, document = self.plan(root)
        self.assertEqual(code, 0, document)
        self.assertNotEqual(self.actions(document)["AGENTS.md"], "convert-to-source")

    def test_a_checkout_without_a_contract_converts_nothing(self):
        root = self.owned(init_repo())
        write(root, "AGENTS.md", ENTRY_AGENTS)
        write(root, "README.md", "# readme\n")
        commit(root, "hand-write the entry file")
        code, document = self.plan(root)
        self.assertEqual(code, 0, document)
        self.assertNotIn("convert-to-source", self.actions(document).values())
        self.assertEqual(self.writes(document, BOOTSTRAP), [])

    def test_a_drafted_checkout_without_a_source_converts(self):
        root = self.owned(init_repo())
        write(root, "README.md", "# readme\n")
        write(root, "AGENTS.md", ENTRY_AGENTS)
        commit(root, "hand-write the entry file")
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        draft = Path(scratch.name) / "draft.json"
        draft.write_text(json.dumps(drafted_contract()), encoding="utf-8")
        code, document = self.plan(root, "--contract-draft", str(draft))
        self.assertEqual(code, 0, document)
        self.assertEqual([op["before"] for op in self.writes(document, BOOTSTRAP)], [None])
        self.assertEqual(self.actions(document)["AGENTS.md"], "convert-to-source")

    def test_a_locked_checkout_without_a_source_keeps_its_conformance_member(self):
        root = self.owned(locked_apply_repo(self.home))
        self.set_projections(root, [])
        (root / BOOTSTRAP).unlink()
        write(root, "AGENTS.md", ENTRY_AGENTS)
        write(root, "CLAUDE.md", "# Claude\n\nPrefer small commits.\n" + MANAGED_LINE)
        commit(root, "hand-write the entry files")
        document = self.ready_plan(root)
        self.assertIn("conformance", document["plan"])
        self.assertNotIn(conformance_failure(document, adopt_conformance.CONTRACT_REFUSED),
                         document["verification"]["ready_gates"])

    def test_an_entry_projection_with_another_source_refuses_the_plan(self):
        root = self.owned(entry_apply_repo(self.home))
        self.set_projections(root, [{
            "id": "codex.entry", "agent": "codex", "kind": "generated_file",
            "target": "AGENTS.md", "source": "docs/agents.md"}])
        write(root, "docs/agents.md", "# other\n")
        commit(root, "declare another source")
        code, document = self.plan(root)
        self.assertEqual(code, 2, document)
        error = document["error"]
        self.assertEqual(error["repair_id"], "adopt.entry.projection_conflict")
        self.assertEqual(error["violations"][0]["pointer"], "/projections/0")

    def test_an_entry_projection_id_clash_refuses_the_plan(self):
        root = self.owned(entry_apply_repo(self.home))
        self.set_projections(root, [{
            "id": "claude.entry", "agent": "claude", "kind": "managed_import",
            "target": "tools/CLAUDE.md", "source": BOOTSTRAP}])
        write(root, BOOTSTRAP, "# invariants\n")
        write(root, "tools/CLAUDE.md", MANAGED_LINE)
        commit(root, "declare a clashing id")
        code, document = self.plan(root)
        self.assertEqual(code, 2, document)
        self.assertEqual(document["error"]["repair_id"], "adopt.entry.projection_conflict")

    def test_a_staged_entry_deletion_refuses_the_plan(self):
        root = self.owned(entry_apply_repo(self.home))
        git(root, "rm", "--cached", "--quiet", "AGENTS.md")
        code, document = self.plan(root)
        self.assertEqual(code, 2, document)
        self.assertEqual(document["error"]["code"], "dirty_worktree")
        self.assertEqual(document["error"]["repair_id"], "adopt.worktree.dirty")

    def test_a_hook_that_drops_a_source_line_fails_the_apply(self):
        root = self.owned(entry_apply_repo(self.home))
        hook = root / ".git" / "hooks" / "pre-commit"
        hook.write_text(
            "#!/bin/sh\npython3 -c \"import pathlib; "
            f"p = pathlib.Path('{BOOTSTRAP}'); "
            "p.write_text(''.join(p.read_text().splitlines(True)[:-1]))\" "
            f"&& git add {BOOTSTRAP}\n", encoding="utf-8")
        hook.chmod(0o755)
        plan_id = self.ready_plan(root)["plan"]["plan_id"]
        code, payload, err = self.apply(plan_id)
        self.assertEqual(code, 2, err or payload)
        self.assertEqual(payload["error"]["code"], "verification_failed")
        self.assertEqual(payload["error"]["repair_id"], "adopt.commit.conversion_unproved")
        self.assertTrue(self.worktree(plan_id).is_dir())


class PointInTimeRecordTest(unittest.TestCase):
    def test_a_point_in_time_record_is_never_an_inbound_rewrite(self):
        texts = {"docs/adr/001.md": "[a](../../a.md)\n",
                 ".agents/artifacts/plans/p.md": "[a](../../../a.md)\n",
                 "docs/g.md": "[a](../a.md)\n"}
        paths = set(texts) | {"a.md"}
        result = adopt_links.plan_link_rewrites(
            texts, paths, [("a.md", "b/a.md")], [])
        self.assertEqual(sorted(result.files), ["docs/g.md"])
        self.assertEqual(result.summary["unrewritable"], [])
        self.assertEqual(result.summary["already_broken"], 0)


if __name__ == "__main__":
    unittest.main()
