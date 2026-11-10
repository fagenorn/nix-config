"""fallback-audit: the ladder-absence and removed-fallback trace checks (issue 579 P8).

Run: just agent-workflow-tests
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON = REPO / "python"

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(root, *args):
    subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=root, check=True,
                   capture_output=True, env=dict(os.environ, **GIT_ENV))


def audit(*args, path_prefix=None):
    env = dict(os.environ, PYTHONPATH=str(PYTHON))
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    result = subprocess.run([sys.executable, "-m", "agent_tools.project_contract.fallback_audit", *args],
                            capture_output=True, text=True, env=env, timeout=120)
    return result.returncode, (json.loads(result.stdout) if result.stdout.strip() else None), result.stderr


NIX_CONFIG_CONTRACT = {".agents/project.json": json.dumps(
    {"schema_version": 2, "project": {"id": "fagenorn/nix-config", "name": "nix-config"}})}


class LaddersTest(unittest.TestCase):
    EXEMPT_ONLY = {
        "python/agent_tools/project_contract/adopt_inspection.py": 'X = "skills.config.json"\n',
        "home/common/agent-skills/skills/ship-release/CHANGELOG.md": "bindings.deploy\n",
        "python/agent_tools/verify_checks.py":
            'X = ("bindings.deploy", "skills.config.json", "release deploy inspect")\n',
        "python/agent_tools/project_contract/resolve_project.py": "bindings.deploy\n",
        "python/agent_tools/project_contract/adopt_migrate.py": "bindings.deploy\n",
        "python/agent_tools/release_profile.py": "bindings.deploy\n",
    }

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()

    def make_repo(self, files):
        root = self.tmp / "repo"
        root.mkdir(exist_ok=True)
        git(root, "init", "--quiet")
        for name, text in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "--quiet", "-m", "fixture")
        return root

    def stub(self, body, name="resolve-project"):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        script = bin_dir / name
        script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        script.chmod(0o755)
        return bin_dir

    def ladders(self, root, *extra, stub_body=None):
        prefix = self.stub(stub_body) if stub_body is not None else None
        return audit("ladders", "--repo-root", str(root), *extra, path_prefix=prefix)

    @staticmethod
    def real(findings):
        return [f for f in findings if not f["marker_id"].startswith("stale_exemption:")]

    @staticmethod
    def stale(findings):
        return [f for f in findings if f["marker_id"].startswith("stale_exemption:")]

    def test_a_marker_in_a_skill_is_a_finding(self):
        root = self.make_repo({"home/common/agent-skills/skills/x/SKILL.md":
                               "Use `~/.agents/bin/x` if the bare name does not resolve.\n"})
        code, report, _ = self.ladders(root)
        self.assertEqual(code, 1)
        self.assertEqual([(f["path"], f["line"], f["marker_id"]) for f in self.real(report["findings"])],
                         [("home/common/agent-skills/skills/x/SKILL.md", 1, "bare-name-fallback")])

    def test_records_tests_and_untracked_files_are_not_scanned(self):
        root = self.make_repo({".agents/artifacts/specs/a.md": "skills.config.json\n",
                               "home/common/agent-skills/skills/x/tests/t.py": "release_bridge\n",
                               "home/common/agent-skills/skills/x/evals/e.md": "resolve-bindings\n",
                               "python/agent_tools/project_contract/fallback_audit.py": "resolve-bindings\n"})
        (root / "CLAUDE.md").write_text("resolve-bindings\n")  # untracked
        code, report, _ = self.ladders(root)
        # A fixture tree holds none of the NON_LADDER_SITES, so only stale rows may appear.
        self.assertEqual(self.real(report["findings"]), [])

    def test_a_listed_site_is_exempt_and_reported(self):
        root = self.make_repo({**NIX_CONFIG_CONTRACT,
                               "python/agent_tools/project_contract/adopt_inspection.py":
                               'X = (".claude/skills.config.json",)\n'})
        code, report, _ = self.ladders(root)
        self.assertEqual([(e["path"], e["marker_id"]) for e in report["exempt"]],
                         [("python/agent_tools/project_contract/adopt_inspection.py", "legacy-skills-config")])
        self.assertNotIn("legacy-skills-config", [f["marker_id"] for f in report["findings"]])

    def test_the_same_marker_elsewhere_is_not_exempt(self):
        root = self.make_repo({"python/agent_tools/other.py": 'X = ".claude/skills.config.json"\n'})
        self.assertIn("legacy-skills-config",
                      [f["marker_id"] for f in self.ladders(root)[1]["findings"]])

    def test_an_exemption_with_no_hit_is_stale(self):
        root = self.make_repo({**NIX_CONFIG_CONTRACT, "README.md": "x\n"})
        findings = self.ladders(root)[1]["findings"]
        self.assertIn({"path": "python/agent_tools/project_contract/adopt_inspection.py", "line": None,
                       "marker_id": "stale_exemption:legacy-skills-config"}, findings)

    def test_another_project_has_no_exemptions_and_no_stale_ones(self):
        contract = json.dumps({"schema_version": 2,
                               "project": {"id": "fagenorn/argus", "name": "argus"}})
        root = self.make_repo({".agents/project.json": contract, "README.md": "x\n"})
        code, report, _ = self.ladders(
            root, stub_body="""echo '{"error":{"code":"not_onboarded"}}'; exit 2""")
        self.assertEqual((code, report["findings"], report["exempt"], report["clean"]),
                         (0, [], [], True))

    def test_another_project_gets_no_exemption_for_a_nix_config_path(self):
        contract = json.dumps({"schema_version": 2,
                               "project": {"id": "fagenorn/argus", "name": "argus"}})
        root = self.make_repo({".agents/project.json": contract,
                               "python/agent_tools/project_contract/adopt_inspection.py":
                               'X = ".claude/skills.config.json"\n'})
        report = self.ladders(root)[1]
        self.assertEqual([(f["path"], f["marker_id"]) for f in report["findings"]],
                         [("python/agent_tools/project_contract/adopt_inspection.py", "legacy-skills-config")])
        self.assertEqual(report["exempt"], [])

    def test_a_repository_with_no_readable_contract_has_no_exemptions(self):
        for contract in ("{not json", "[]", '{"project": {"id": 5}}'):
            with self.subTest(contract=contract):
                root = self.make_repo({".agents/project.json": contract, "README.md": "x\n"})
                report = self.ladders(root)[1]
                self.assertEqual(self.stale(report["findings"]), [])

    def test_a_contract_with_a_non_finite_token_owns_no_exemption(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token):
                contract = ('{"schema_version": 2, "project": {"id": "fagenorn/nix-config", '
                            '"name": "nix-config"}, "deploy": {"config": {"x": %s}}}' % token)
                root = self.make_repo({".agents/project.json": contract,
                                       "python/agent_tools/project_contract/adopt_inspection.py":
                                       'X = ".claude/skills.config.json"\n'})
                report = self.ladders(root)[1]
                self.assertEqual(report["exempt"], [])
                self.assertEqual(self.stale(report["findings"]), [])
                self.assertIn("legacy-skills-config",
                              [f["marker_id"] for f in report["findings"]])

    def test_a_manifest_removal_subject_is_a_marker(self):
        manifest = json.loads((REPO / "home/common/agent-skills/platform-manifest.json").read_text("utf-8"))
        manifest["removals"] = [{"id": "r1", "kind": "platform_behavior", "subject": "old verb",
                                 "since": "1.2.0", "successor": "new verb",
                                 "migration": "bindings-deploy.retire"}]
        manifest["deprecations"] = [d for d in manifest["deprecations"] if d["id"] != "r1"]
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        root = self.make_repo({"AGENTS.md": "run old verb\n"})
        code, report, err = self.ladders(root, "--manifest", str(path))
        self.assertEqual(code, 1, err)
        self.assertIn({"path": "AGENTS.md", "line": 1, "marker_id": "r1"}, report["findings"])

    def test_the_fail_closed_probe_reports_a_closed_code(self):
        root = self.make_repo({"README.md": "x\n"})
        _, report, _ = self.ladders(
            root, stub_body="""echo '{"error":{"code":"not_onboarded"}}'; exit 2""")
        self.assertEqual(report["probe"], {"code": "not_onboarded", "exit": 2})

    def test_a_probe_code_outside_the_closed_set_is_not_clean(self):
        root = self.make_repo({**NIX_CONFIG_CONTRACT, **self.EXEMPT_ONLY})
        code, report, _ = self.ladders(
            root, stub_body="""echo '{"error":{"code":"surprise"}}'; exit 2""")
        self.assertEqual((code, report["clean"], report["probe"]),
                         (1, False, {"code": "surprise", "exit": 2}))

    def test_a_probe_that_succeeds_is_not_clean(self):
        root = self.make_repo({"README.md": "x\n"})
        code, report, _ = self.ladders(root, stub_body="echo '{}'; exit 0")
        self.assertFalse(report["clean"])
        self.assertEqual(code, 1)
        self.assertEqual(report["probe"]["exit"], 0)

    @unittest.skipIf(os.geteuid() == 0, "root reads every file")
    def test_an_unreadable_tracked_file_is_a_finding_not_a_clean_scan(self):
        files = {**NIX_CONFIG_CONTRACT, **self.EXEMPT_ONLY}
        files["home/common/agent-skills/skills/ship-release/SKILL.md"] = "resolve-bindings\n"
        root = self.make_repo(files)
        unreadable = root / "home/common/agent-skills/skills/ship-release/SKILL.md"
        unreadable.chmod(0)
        self.addCleanup(unreadable.chmod, 0o644)
        code, report, _ = self.ladders(
            root, stub_body="""echo '{"error":{"code":"not_onboarded"}}'; exit 2""")
        self.assertEqual((code, report["clean"]), (1, False))
        self.assertEqual(
            report["findings"],
            [{"path": "home/common/agent-skills/skills/ship-release/SKILL.md",
              "line": None, "marker_id": "unreadable_input"}])

    def test_a_clean_tree_with_a_closed_probe_exits_zero(self):
        root = self.make_repo({**NIX_CONFIG_CONTRACT, **self.EXEMPT_ONLY})
        code, report, _ = self.ladders(
            root, stub_body="""echo '{"error":{"code":"not_onboarded"}}'; exit 2""")
        self.assertEqual((code, report["findings"], report["clean"]), (0, [], True))
        self.assertEqual(len(report["exempt"]), 8)


def claude_line(timestamp, command, usage=True):
    message = {"id": "m1", "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                        "input": {"command": command}}]}
    if usage:
        message["usage"] = {"input_tokens": 1, "output_tokens": 1}
    return json.dumps({"type": "assistant", "timestamp": timestamp, "message": message})


def codex_line(timestamp, payload):
    return json.dumps({"timestamp": timestamp, "type": "response_item", "payload": payload})


class TracesTest(unittest.TestCase):
    SINCE = "2026-11-08T00:00:00Z"
    AFTER = "2026-11-09T00:00:00Z"
    BEFORE = "2026-11-07T00:00:00Z"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.claude = Path(tmp.name) / "claude"
        self.codex = Path(tmp.name) / "codex"
        self.claude.mkdir()
        self.codex.mkdir()

    def write(self, path, lines):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.utime(path, (4102444800, 4102444800))  # 2100: after every fixture record
        return path

    def traces(self, since=None):
        return audit("traces", "--since", since or self.SINCE,
                     "--claude-root", str(self.claude), "--codex-root", str(self.codex))

    def test_a_claude_bash_call_after_since_is_an_execution(self):
        self.write(self.claude / "p/s.jsonl",
                   [claude_line(self.AFTER, "release deploy inspect --commit abc")])
        code, report, _ = self.traces()
        self.assertEqual(code, 1)
        execution = report["executions"][0]
        self.assertEqual((execution["marker_id"], execution["source"], execution["timestamp"]),
                         ("release-deploy-inspect", "claude", self.AFTER))
        self.assertEqual(execution["excerpt"], "release deploy inspect --commit abc")
        self.assertEqual(report["since"], self.SINCE)

    def test_the_excerpt_is_the_first_200_characters(self):
        command = "release deploy inspect " + "x" * 400
        self.write(self.claude / "p/s.jsonl", [claude_line(self.AFTER, command)])
        self.assertEqual(self.traces()[1]["executions"][0]["excerpt"], command[:200])

    def test_a_subagent_transcript_is_read(self):
        self.write(self.claude / "p/s/subagents/agent-1.jsonl",
                   [claude_line(self.AFTER, "release deploy inspect")])
        self.assertEqual(self.traces()[0], 1)

    def test_a_call_with_no_usage_is_still_read(self):
        self.write(self.claude / "p/s.jsonl",
                   [claude_line(self.AFTER, "release deploy inspect", usage=False)])
        self.assertEqual(self.traces()[0], 1)

    def test_a_call_before_since_is_not(self):
        self.write(self.claude / "p/s.jsonl", [claude_line(self.BEFORE, "release deploy inspect")])
        code, report, _ = self.traces()
        self.assertEqual((code, report["executions"], report["files_read"]), (0, [], 1))

    def test_a_file_older_than_since_is_not_opened(self):
        path = self.write(self.claude / "p/s.jsonl", [claude_line(self.AFTER, "release deploy inspect")])
        os.utime(path, (1, 1))
        code, report, _ = self.traces()
        self.assertEqual((code, report["files_read"]), (0, 0))

    def test_a_codex_shell_call_in_a_dated_directory_is_read(self):
        arguments = json.dumps({"command": ["bash", "-lc", "cat .claude/skills.config.json"]})
        self.write(self.codex / "2026/11/09/rollout-x.jsonl", [codex_line(self.AFTER, {
            "type": "function_call", "name": "shell", "arguments": arguments, "call_id": "c1"})])
        code, report, _ = self.traces()
        self.assertEqual(code, 1)
        self.assertEqual((report["executions"][0]["source"], report["executions"][0]["marker_id"]),
                         ("codex", "legacy-skills-config"))

    def test_a_codex_exec_custom_tool_call_is_read(self):
        self.write(self.codex / "2026/11/09/rollout-x.jsonl", [codex_line(self.AFTER, {
            "type": "custom_tool_call", "name": "exec", "input": "resolve-bindings --x",
            "call_id": "c1"})])
        code, report, _ = self.traces()
        self.assertEqual((code, report["executions"][0]["marker_id"]), (1, "resolve-bindings"))

    def test_a_codex_local_shell_call_is_read(self):
        self.write(self.codex / "2026/11/09/rollout-x.jsonl", [codex_line(self.AFTER, {
            "type": "local_shell_call", "action": {"type": "exec", "command": ["resolve-bindings"]}})])
        self.assertEqual(self.traces()[0], 1)

    def test_a_codex_argv_command_matches_a_multi_word_marker(self):
        arguments = json.dumps({"command": ["release", "deploy", "inspect", "--commit", "abc"]})
        self.write(self.codex / "2026/11/09/rollout-x.jsonl", [
            codex_line(self.AFTER, {"type": "function_call", "name": "shell",
                                    "arguments": arguments, "call_id": "c1"}),
            codex_line(self.AFTER, {"type": "local_shell_call", "action": {
                "type": "exec", "command": ["release", "deploy", "inspect"]}})])
        code, report, _ = self.traces()
        self.assertEqual(code, 1)
        self.assertEqual([e["marker_id"] for e in report["executions"]],
                         ["release-deploy-inspect", "release-deploy-inspect"])

    def test_a_codex_collaboration_call_is_not_a_shell_call(self):
        self.write(self.codex / "2026/11/09/rollout-x.jsonl", [codex_line(self.AFTER, {
            "type": "function_call", "name": "send_message",
            "arguments": json.dumps({"message": "resolve-bindings"}), "call_id": "c1"})])
        self.assertEqual(self.traces()[0], 0)

    def test_malformed_lines_are_counted(self):
        self.write(self.claude / "p/s.jsonl",
                   ["not json", "[1, 2]", claude_line(self.AFTER, "ls")])
        code, report, _ = self.traces()
        self.assertEqual((code, report["skipped_lines"]), (0, 2))

    def test_a_call_with_no_usable_timestamp_is_counted(self):
        record = json.loads(claude_line(self.AFTER, "resolve-bindings"))
        del record["timestamp"]
        bad = json.loads(claude_line("yesterday", "resolve-bindings"))
        self.write(self.claude / "p/s.jsonl", [json.dumps(record), json.dumps(bad)])
        code, report, _ = self.traces()
        self.assertEqual((code, report["skipped_lines"], report["executions"]), (0, 2, []))

    def test_a_since_without_an_offset_is_a_usage_error(self):
        self.assertEqual(self.traces(since="2026-11-08T00:00:00")[0], 2)


class CandidateTreeTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def audit(self):
        shim = self.enterContext(tempfile.TemporaryDirectory())
        # The probe runs the resolve-project on PATH: point it at this tree's own resolver.
        stub = Path(shim) / "resolve-project"
        stub.write_text(f'#!/bin/sh\nPYTHONPATH="{self.ROOT / "python"}" exec "{sys.executable}" '
                        '-m agent_tools.project_contract.resolve_project "$@"\n')
        stub.chmod(0o755)
        proc = subprocess.run(
            [sys.executable, "-m", "agent_tools.project_contract.fallback_audit", "ladders",
             "--repo-root", str(self.ROOT),
             "--manifest", str(self.ROOT / "home/common/agent-skills/platform-manifest.json")],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "PYTHONPATH": str(self.ROOT / "python"),
                 "PATH": f"{shim}:{os.environ['PATH']}"})
        return proc, json.loads(proc.stdout)

    def test_the_candidate_tree_has_no_ladder(self):
        proc, report = self.audit()
        self.assertEqual(report["findings"], [])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_only_the_listed_sites_are_exempt(self):
        _, report = self.audit()
        sys.path.insert(0, str(self.ROOT / "python"))
        try:
            from agent_tools.project_contract.fallback_audit import NON_LADDER_SITES
        finally:
            sys.path.pop(0)
        self.assertEqual(sorted({(e["path"], e["marker_id"]) for e in report["exempt"]}),
                         sorted((path, marker) for path, marker, _ in NON_LADDER_SITES))

    def test_the_removed_deploy_member_is_named_by_its_literal_and_exempted(self):
        # A docstring that describes the removal says `bindings.deploy` itself; the
        # audit exempts it by a row with a reason, never by rewording the literal away.
        _, report = self.audit()
        exempt = {e["path"] for e in report["exempt"] if e["marker_id"] == "bindings-deploy"}
        for path in ("python/agent_tools/project_contract/resolve_project.py",
                     "python/agent_tools/project_contract/adopt_migrate.py",
                     "python/agent_tools/release_profile.py"):
            self.assertIn("bindings.deploy", (self.ROOT / path).read_text("utf-8"), path)
            self.assertIn(path, exempt)

    def test_the_known_ladders_are_deleted_not_reworded(self):
        skill = (self.ROOT / "home/common/agent-skills/skills/research/SKILL.md").read_text("utf-8")
        self.assertNotIn("~/.agents/bin/agent-" "evidence", skill)
        sys.path.insert(0, str(self.ROOT / "python"))
        try:
            self.assertIsNone(importlib.util.find_spec("agent_tools.release_bridge"))
            from agent_tools import release
            with self.assertRaises(SystemExit):
                release.main(["deploy", "inspect", "--commit", "a" * 40])
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
