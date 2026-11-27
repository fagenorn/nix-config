"""Contract tests for the read-only engine roles' shell: the planner and the two reviewers run read pipelines
and command lists of the preapproved read shapes, and are denied every write, redirect and host write.

The client's rules are modelled by tests/engine_permission_model.py; CI runs no client, so these cases pin the
words each launch passes against that model, with the host's own allow rules in force.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from agent_tools.delivery import engine_session
from agent_tools.delivery.engine_session import launch_argv, read_role
from tests.engine_guards import GUARD_SOURCE, real_guard
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
    """The client's rules, then the guard's detaching check and its read-only-shell check (the session's switch)."""
    return (client_admits(command, allowed, denied) and GUARD.detaching_word(command) is None
            and not GUARD.read_only_shell_problem(command))


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

    def test_arguments_fed_on_stdin_to_a_git_read_are_refused_to_each_read_only_role(self):
        fed = [
            "cat args.txt | xargs git diff",
            "grep -h output args.txt | xargs git log",
            "ls | xargs git show --stat",
            "xargs git diff < args.txt",
            "head -1 args.txt | time xargs git diff",
            'cat args.txt | x""args git diff',
            "cat args.txt | XARGS git diff",
        ]
        for name in READ_ONLY_ROLES:
            words = launch_words(name)
            for command in fed:
                with self.subTest(role=name, command=command):
                    self.assertFalse(read_only_admits(command, *words))
        for command in fed[:3]:  # the client alone strips the bare xargs, so no rule words refuse these
            with self.subTest(client_alone=command):
                self.assertTrue(client_admits(command, *launch_words("reviewer")))

    def test_a_git_output_option_the_shell_rebuilds_is_refused_to_each_read_only_role(self):
        rebuilt = [
            'git diff --out""put=d.patch HEAD~1',
            "git log --outp\\ut=l.txt -1",
            "git show --out''put=s.txt HEAD",
            "git diff --out{,}put=d.patch HEAD~1",
            "git diff --{output=d.patch,} HEAD~1",
            'git diff "--output=d.patch" HEAD~1',
            "git log -1 --OUTPUT=l.txt",
            "git diff --output d.patch",
        ]
        for name in READ_ONLY_ROLES:
            words = launch_words(name)
            for command in rebuilt:
                with self.subTest(role=name, command=command):
                    self.assertFalse(read_only_admits(command, *words))
            with self.subTest(role=name, admitted="a search for the text"):
                self.assertTrue(read_only_admits("grep -rn -e '--output' python", *words))
        for command in rebuilt[:3]:  # the client's rule words read the literal text only
            with self.subTest(client_alone=command):
                self.assertTrue(client_admits(command, *launch_words("reviewer")))

    def test_the_guard_refuses_a_git_output_option_only_in_a_read_only_shell_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapper = real_guard(Path(tmp) / "guard")
            for switched in (True, False):
                env = {key: value for key, value in os.environ.items() if key != engine_session.READ_ONLY_SHELL_SWITCH}
                if switched:
                    env[engine_session.READ_ONLY_SHELL_SWITCH] = "1"
                payload = json.dumps({"tool_name": "Bash",
                                      "tool_input": {"command": 'git diff --out""put=d.patch HEAD~1'}})
                done = subprocess.run([str(wrapper)], input=payload, env=env, capture_output=True, text=True,
                                      cwd=tmp, timeout=60, check=False)
                with self.subTest(switched=switched):
                    self.assertEqual("refused in a read-only shell session" in done.stderr, switched)
                    if switched:
                        self.assertEqual(done.returncode, 2, done.stderr)

    def test_the_guard_refuses_xargs_only_in_a_read_only_shell_session(self):
        def refusal(command: str, switched: bool) -> subprocess.CompletedProcess:
            env = {key: value for key, value in os.environ.items() if key != engine_session.READ_ONLY_SHELL_SWITCH}
            if switched:
                env[engine_session.READ_ONLY_SHELL_SWITCH] = "1"
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
            return subprocess.run([str(wrapper)], input=payload, env=env, capture_output=True, text=True,
                                  cwd=tmp, timeout=60, check=False)

        with tempfile.TemporaryDirectory() as tmp:
            wrapper = real_guard(Path(tmp) / "guard")
            self.assertEqual(GUARD.READ_ONLY_SHELL_ENV, engine_session.READ_ONLY_SHELL_SWITCH)
            refused = refusal("cat args.txt | xargs git diff", True)
            self.assertEqual(refused.returncode, 2, refused.stderr)
            self.assertIn("`xargs` and git `--output` refused in a read-only shell session", refused.stderr)
            self.assertNotIn("refused in a read-only", refusal("cat args.txt | xargs git diff", False).stderr)
            self.assertEqual(refusal("git log --oneline -3 | head", True).returncode, 0)

    def test_only_a_read_only_shell_role_gets_the_switch(self):
        planner = read_role(AGENTS, "planner")
        implementer = read_role(AGENTS, "implementer")
        cases = [(planner, True), (read_role(AGENTS, "reviewer"), True), (read_role(AGENTS, "reviewer-lite"), True),
                 (implementer, False), (replace(implementer, whole_shell=True), False)]
        for role, expected in cases:
            with self.subTest(role=role.name, whole_shell=role.whole_shell):
                self.assertEqual(engine_session.read_only_shell(role), expected)
            with self.subTest(environment=role.name, whole_shell=role.whole_shell):
                for inherited in ({"PATH": "/bin"}, {engine_session.READ_ONLY_SHELL_SWITCH: "1", "PATH": "/bin"}):
                    env = engine_session.role_environment(inherited, role)
                    self.assertEqual(env.get(engine_session.READ_ONLY_SHELL_SWITCH), "1" if expected else None)
                    self.assertEqual(env["PATH"], "/bin")

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

    def test_the_denial_prompt_tells_each_role_what_its_own_launch_allows(self):
        implementer = read_role(AGENTS, "implementer")
        whole = replace(implementer, whole_shell=True)
        calls = ["rm x"]
        read_only = engine_session.denial_prompt(read_role(AGENTS, "reviewer"), calls)
        plain = engine_session.denial_prompt(implementer, calls)
        whole_shell = engine_session.denial_prompt(whole, calls)

        self.assertIn("Shell rules allowing a command: Bash(git diff:*)", read_only)
        self.assertIn("No `>` redirection runs.", read_only)
        self.assertNotIn("host", read_only)
        self.assertIn("host settings' own allow rules", plain)
        self.assertNotIn("allowing a command: none", plain)
        self.assertNotIn("redirection", plain)
        self.assertIn("Every shell command is allowed, redirection included", whole_shell)
        self.assertNotIn("No `>` redirection", whole_shell)
        for rule in engine_session.shell_rules(whole)[1]:
            self.assertIn(rule, whole_shell)


PROCEDURES = REPO_ROOT / "python/agent_tools/delivery/procedures"


def read_only_steps():
    for path in sorted(PROCEDURES.glob("*.json")):
        steps = json.loads(path.read_text(encoding="utf-8")).get("steps")
        for step in steps if isinstance(steps, list) else []:
            if step.get("kind") == "agent" and step.get("role") in READ_ONLY_ROLES:
                yield path.name, step["id"], step["role"], PROCEDURES / step["prompt"], step.get("in", [])


class ReadOnlyPromptsTest(unittest.TestCase):
    def test_no_read_only_step_prompt_asks_for_git_dash_c(self):
        steps = list(read_only_steps())
        self.assertTrue(steps)
        for file, step, role, prompt, _ in steps:
            with self.subTest(file=file, step=step, role=role):
                self.assertNotIn("git -C", prompt.read_text(encoding="utf-8"))

    def test_the_git_reads_the_review_prompts_name_are_admitted_for_their_role(self):
        rows = [
            ("verify-fix-review.md", "reviewer", "git diff {{round.head}}..{{preflight.branch}}"),
            ("land-ci-review.md", "reviewer", "git diff {{ci-fix.start_head}}..{{ci-fix.commit}}"),
            ("land-sync-review.md", "reviewer", "git show --cc {{merge-of.merge_commit}}"),
            ("land-sync-review.md", "reviewer", "git diff {{merge-of.merge_commit}}..{{merge-of.head}}"),
            ("land-sync-review.md", "reviewer", "git diff --check {{merge-of.merge_commit}} {{merge-of.head}}"),
            ("land-sync-rereview.md", "reviewer", "git diff {{merge-fix.start_head}}..{{merge-fix.commit}}"),
            ("land-sync-rereview.md", "reviewer", "git show --cc {{merge-of.merge_commit}}"),
            ("direct-review.md", "reviewer",
             "git diff origin/{{preflight.integration_branch}}...{{preflight.branch}}"),
        ]
        for prompt, role, command in rows:
            with self.subTest(prompt=prompt, command=command):
                text = (PROCEDURES / prompt).read_text(encoding="utf-8")
                self.assertIn(command, text)
                filled = re.sub(r"\{\{[^}]*\}\}", "0123abcd", command)
                self.assertTrue(read_only_admits(filled, *launch_words(role)), filled)

    def test_the_fix_review_steps_read_the_branch(self):
        verify = json.loads((PROCEDURES / "verify.json").read_text(encoding="utf-8"))
        steps = {step["id"]: step for step in verify["steps"]}
        for name in ("fix-review", "fix-review-again"):
            with self.subTest(step=name):
                self.assertIn("preflight.branch", steps[name]["in"])


if __name__ == "__main__":
    unittest.main()
