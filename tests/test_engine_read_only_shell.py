"""Contract tests for the read-only engine roles' shell: the planner and the two reviewers run read pipelines
and command lists of the preapproved read shapes, and are denied every write, redirect and host write.

The client's rules are modelled by tests/engine_permission_model.py; CI runs no client, so these cases pin the
words each launch passes against that model, with the host's own allow rules in force.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from dataclasses import replace

from agent_tools.delivery import engine_session
from agent_tools.delivery.engine_session import launch_argv, read_role
from tests.engine_guards import GUARD_SOURCE
from tests.engine_permission_model import HOST_SETTINGS, REPO_ROOT, client_admits, host_allowed
from tests.test_engine_session import SCHEMA, SESSION, SYSTEM

TIER = "fast"

AGENTS = REPO_ROOT / "home/common/claude-code/agents"
READ_ONLY_ROLES = ("planner", "reviewer", "reviewer-lite")
HOST = host_allowed(HOST_SETTINGS.read_text(encoding="utf-8"))
HOST_READS = ("git status", "git log", "git diff", "git worktree list", "gh pr view", "gh pr list",
              "gh pr checks", "gh issue view", "gh issue list", "artifact-budget",
              "~/.agents/bin/artifact-budget")
DENIED_1740 = REPO_ROOT / "tests/fixtures/engine-session/result-denied-1740.json"


def _load_guard():
    spec = importlib.util.spec_from_file_location("lifecycle_guard_source", GUARD_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = _load_guard()


def words_after(argv: tuple[str, ...], flag: str) -> list[str]:
    return argv[argv.index(flag) + 1].split(",") if flag in argv else []


def launch_words(name: str) -> tuple[list[str], list[str]]:
    """The allow words of the role's launch with the host's allow rules, and its deny words."""
    argv = launch_argv(read_role(AGENTS, name), SCHEMA, SESSION, SYSTEM)
    return [*words_after(argv, "--allowedTools"), *HOST], words_after(argv, "--disallowedTools")


def read_only_admits(command: str, allowed: list[str], denied: list[str]) -> bool:
    return client_admits(command, allowed, denied) and GUARD.detaching_word(command) is None


class ReadOnlyShellTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert "Bash(git push:*)" in HOST and len(HOST) >= 10, HOST

    def test_the_recorded_applies_call_is_admitted_by_each_read_only_role(self):
        denials = json.loads(DENIED_1740.read_text(encoding="utf-8"))["permission_denials"]
        self.assertEqual(len(denials), 1)
        command = denials[0]["tool_input"]["command"]

        for name in READ_ONLY_ROLES:
            with self.subTest(name):
                self.assertTrue(read_only_admits(command, *launch_words(name)))

    def test_read_pipelines_and_command_lists_are_admitted(self):
        admitted = [
            "git log --oneline -5 | head",
            "git ls-tree -r HEAD --name-only | grep -i -E 'engine|guard' | head -30",
            "git show HEAD:python/x.py | head -80",
            "git diff origin/main...HEAD --stat",
            "git log --oneline -5 && git status --short",
            "git rev-parse HEAD || git status",
            "grep -rn 'def launch' python | head -20",
            'grep -n "a|b" python/x.py',
            "ls python/agent_tools; wc -l python/x.py",
            "cat README.md | head -40",
            "tail -n 20 python/x.py",
            "head -n 40 python/x.py",
            "git blame -L 1,10 python/x.py",
            "git ls-files | wc -l",
            "git merge-base HEAD origin/main",
            "git show --cc 0123abcd",
            "git diff --check 0123abcd 4567ef01",
            "head",
        ]
        for name in READ_ONLY_ROLES:
            words = launch_words(name)
            for command in admitted:
                with self.subTest(role=name, command=command):
                    self.assertTrue(read_only_admits(command, *words))

    def test_writes_pushes_checkouts_resets_redirections_and_detaching_are_refused(self):
        refused = [
            "git commit -m x", "git add f.py", "rm -rf build", "touch f", "mv a b", "cp a b",
            "git log | tee out.txt", "sed -i s/a/b/ f.py", "sed -n -ni '' 1p python/x.py",
            "sed -n '1w out.txt' python/x.py", "sed -n 1,40p python/x.py", "git log --output=log.txt",
            "git diff --output=d.patch", "git show --output=s.txt HEAD", "git fetch origin",
            "git push origin b", "git log -1 && git push origin b", "git worktree add ../x b",
            "git worktree remove ../x", "git worktree prune", "git branch -d b",
            "gh pr create --title t --body b", "gh pr merge 1 --merge", "gh release create v1",
            "forge-issue create --title t", "~/.agents/bin/forge-issue create --title t",
            "git checkout main", "git checkout -- f.py", "git reset --hard HEAD", "git reset HEAD f.py",
            "git log > log.txt", "cat a.txt >> b.txt", "git show HEAD:f.py > f.py",
            "git log --oneline | head > top.txt", "git log 2>/dev/null", "nohup git log", "setsid git log",
            "git log & disown", "git log $(rm x)", "git show `touch x`", 'grep -rn "$(rm -rf x)" python',
            "git -c core.pager=sh log", "sh -c 'git log'", "python3 -c 'print(1)'",
        ]
        for name in READ_ONLY_ROLES:
            words = launch_words(name)
            for command in refused:
                with self.subTest(role=name, command=command):
                    self.assertFalse(read_only_admits(command, *words))

    def test_every_host_write_allowance_is_refused_to_each_read_only_role(self):
        prefixes = [rule[len("Bash("):-len(":*)")] for rule in HOST
                    if rule.startswith("Bash(") and rule.endswith(":*)")]
        writes = [prefix for prefix in prefixes if prefix not in HOST_READS]
        self.assertIn("git worktree add", writes)

        for name in READ_ONLY_ROLES:
            words = launch_words(name)
            for prefix in writes:
                with self.subTest(role=name, prefix=prefix):
                    self.assertFalse(read_only_admits(f"{prefix} x", *words))

    def test_the_guard_alone_refuses_a_detaching_word_the_client_strips(self):
        for name in READ_ONLY_ROLES:
            with self.subTest(name):
                self.assertTrue(client_admits("nohup git log", *launch_words(name)))
        self.assertEqual(GUARD.detaching_word("nohup git log"), "nohup")

    def test_the_rule_model_splits_compound_commands_and_strips_wrappers(self):
        log, grep = ["Bash(git log:*)"], ["Bash(grep:*)"]
        cases = [
            ("git log | head", log, [], False),
            ("git log | head", [*log, "Bash(head:*)"], [], True),
            ("grep 'a|b' f", grep, [], True),
            ('grep "a|b" f', grep, [], True),
            ("grep '$(rm x)' f", grep, [], True),
            ('grep "$(rm x)" f', grep, [], False),
            ('grep "`rm x`" f', grep, [], False),
            ("nohup git log", log, [], True),
            ("git log && ", log, [], False),
            ("xargs grep x", grep, [], True),
            ("xargs -n1 grep x", grep, [], False),
            ("git log $(x)", ["Bash"], [], False),
            ("git log; rm x", ["Bash"], ["Bash(rm *)"], False),
            ("FOO=1 rm x", ["Bash"], ["Bash(rm *)"], False),
            ("FOO=1 git log", log, [], False),
            ("git push o b", ["Bash(git push:*)"], ["Bash(git push:*)"], False),
        ]
        for command, allowed, denied, expected in cases:
            with self.subTest(command=command, allowed=allowed, denied=denied):
                self.assertEqual(client_admits(command, allowed, denied), expected)

    def test_shell_rules_are_the_bash_words_of_each_launch(self):
        def bash_words(argv, flag):
            return tuple(word for word in words_after(argv, flag) if word == "Bash" or word.startswith("Bash("))

        roles = [read_role(AGENTS, name) for name in (*READ_ONLY_ROLES, "implementer")]
        roles.append(replace(read_role(AGENTS, "implementer"), whole_shell=True))
        for role in roles:
            with self.subTest(role=role.name, whole_shell=role.whole_shell):
                argv = launch_argv(role, SCHEMA, SESSION, SYSTEM)
                self.assertEqual(engine_session.shell_rules(role), (bash_words(argv, "--allowedTools"),
                                                                    bash_words(argv, "--disallowedTools")))
        self.assertEqual(engine_session.shell_rules(read_role(AGENTS, "implementer")), ((), ()))


if __name__ == "__main__":
    unittest.main()
