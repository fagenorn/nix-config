"""A fake provider world for the forge adapter suites (#124 D12, D22).

`ForgeWorld(test_case)` writes executable `gh`, `git` and `claude-bash-lifecycle-guard`
scripts into a temporary `bin/` and patches `os.environ` until the test's cleanup: `PATH` is
that `bin/` alone, `GITHUB_TOKEN` is a harness token, and `FORGE_WORLD` names the state
directory. Each script logs `{tool, argv, stdin, token_visible}` to `calls.jsonl` and answers
from `responses.json`, keyed by `json.dumps([tool, *argv])`. An unregistered call exits 64,
and a `gh` that sees a token variable exits 65, so a leaked credential fails loudly.

The standard responses are built from the shared spelling fixture, never from copied
literals, so the world and the guard suite cannot disagree about a provider spelling.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/forge-adapter-spellings.json").read_text("utf-8"))
CANONICAL = FIXTURE["canonical"]
ROWS = {row["id"]: row for row in FIXTURE["rows"]}
TOOLS = ("gh", "git", "claude-bash-lifecycle-guard")
CLASS_BRANCHES = {"elevenyellow/nodocom": "dev"}

SCRIPT = """#!{python}
import json, os, sys, time
from pathlib import Path

state = Path(os.environ["FORGE_WORLD"])
tool = Path(sys.argv[0]).name
argv = sys.argv[1:]
token = bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
stdin = sys.stdin.read() if tool == "claude-bash-lifecycle-guard" else ""
with open(state / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({{"tool": tool, "argv": argv, "stdin": stdin,
                          "token_visible": token}}) + "\\n")
if tool == "gh" and token:
    sys.stderr.write("gh: a token variable reached the child\\n")
    sys.exit(65)
responses = json.loads((state / "responses.json").read_text("utf-8"))
response = responses.get(json.dumps([tool, *argv]))
if response is None:
    sys.stderr.write("fake " + tool + ": unregistered call\\n")
    sys.exit(64)
time.sleep(response["sleep"])
sys.stdout.write(response["stdout"])
sys.stderr.write(response["stderr"])
sys.exit(response["exit"])
"""


class ForgeWorld:
    def __init__(self, test_case: unittest.TestCase) -> None:
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.state, self.bin = root / "state", root / "bin"
        self.state.mkdir()
        self.bin.mkdir()
        for tool in TOOLS:
            path = self.bin / tool
            path.write_text(SCRIPT.format(python=sys.executable), encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        patch = mock.patch.dict(os.environ, {"PATH": str(self.bin), "GITHUB_TOKEN": "harness-token",
                                             "FORGE_WORLD": str(self.state)})
        patch.start()
        test_case.addCleanup(patch.stop)
        self.reset()

    def env(self) -> dict[str, str]:
        """The child environment that reaches this world: its `bin/` as `PATH`, and its state."""
        return {"PATH": str(self.bin), "FORGE_WORLD": str(self.state)}

    def reset(self) -> None:
        """Forget every registered response and every logged call."""
        (self.state / "responses.json").write_text("{}", encoding="utf-8")
        (self.state / "calls.jsonl").write_text("", encoding="utf-8")

    def respond(self, tool: str, argv: list[str], *, exit: int = 0, stdout: str = "",
                stderr: str = "", sleep: float = 0) -> None:
        path = self.state / "responses.json"
        responses = json.loads(path.read_text("utf-8"))
        responses[json.dumps([tool, *argv])] = {
            "exit": exit, "stdout": stdout, "stderr": stderr, "sleep": sleep}
        path.write_text(json.dumps(responses), encoding="utf-8")

    def respond_json(self, tool: str, argv: list[str], value: object, **kwargs) -> None:
        self.respond(tool, argv, stdout=json.dumps(value), **kwargs)

    def not_found(self, tool: str, argv: list[str]) -> None:
        self.respond(tool, argv, exit=1, stderr="gh: Not Found (HTTP 404)")

    def forbidden(self, tool: str, argv: list[str]) -> None:
        self.respond(tool, argv, exit=1, stderr="gh: Forbidden (HTTP 403)")

    def calls(self) -> list[dict]:
        text = (self.state / "calls.jsonl").read_text("utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def argvs(self, tool: str) -> list[list[str]]:
        return [call["argv"] for call in self.calls() if call["tool"] == tool]

    def canonical(self, slug: str = CANONICAL["slug"], **overrides: object) -> None:
        """Register the happy-path responses for the fixture's canonical values, with `slug`
        (and, for a repository class that has one, its branch) substituted. `overrides` name
        canonical values to replace: branch, tag, commit, tag_object, pr, head, base_tip,
        merge_commit."""
        values = {**CANONICAL, "slug": slug,
                  "branch": CLASS_BRANCHES.get(slug, CANONICAL["branch"]), **overrides}

        def argv(row_id: str) -> list[str]:
            swaps = [(CANONICAL["slug"], values["slug"]), (CANONICAL["tag"], values["tag"]),
                     (CANONICAL["tag_object"], values["tag_object"]),
                     (CANONICAL["merge_commit"], values["merge_commit"]),
                     ("/heads/" + CANONICAL["branch"], "/heads/" + values["branch"]),
                     ("/branches/" + CANONICAL["branch"] + "/", "/branches/" + values["branch"] + "/")]
            out = []
            for part in ROWS[row_id]["argv"][1:]:
                for old, new in swaps:
                    part = part.replace(old, new)
                out.append(str(values["pr"]) if part == str(CANONICAL["pr"]) else part)
            return out

        url = f"https://github.com/{values['slug']}"
        self.respond_json("gh", argv("tag.ref"),
                          {"object": {"type": "tag", "sha": values["tag_object"]}})
        self.respond_json("gh", argv("tag.object"),
                          {"object": {"type": "commit", "sha": values["commit"]}})
        self.respond_json("gh", argv("release.view"), {
            "tag_name": values["tag"], "draft": False, "html_url": f"{url}/releases/tag/{values['tag']}"})
        self.respond_json("gh", argv("pr_merge.view"), {
            "state": "MERGED", "baseRefName": values["branch"], "headRefName": "topic",
            "headRefOid": values["head"], "mergeCommit": {"oid": values["merge_commit"]},
            "url": f"{url}/pull/{values['pr']}", "statusCheckRollup": []})
        self.respond_json("gh", argv("pr_merge.base_ref"), {"object": {"sha": values["base_tip"]}})
        self.respond_json("gh", argv("pr_merge.merge_commit"),
                          {"parents": [{"sha": values["base_tip"]}, {"sha": values["head"]}]})
        self.respond_json("gh", argv("pr_merge.protection"), {
            "required_status_checks": {"contexts": ["Nix Eval"]}, "enforce_admins": {"enabled": True}})
