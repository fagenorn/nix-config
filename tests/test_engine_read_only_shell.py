"""Contract tests for the read-only engine roles' shell: the planner and the two reviewers run one plain read per
Bash call and are denied every pipeline, command list, write, redirect and host write.

The client's rules are modelled by tests/engine_permission_model.py; CI runs no client, so these cases pin the
words each launch passes against that model, with the host's own allow rules in force, and the lifecycle guard's
read-only check on top of them.
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
ADMITTED = [
    "git log --oneline -5", "git show HEAD:python/x.py", "git diff origin/main...HEAD --stat",
    "git diff --check 0123abcd 4567ef01", "git show --cc 0123abcd", "git status --short", "git rev-parse HEAD",
    "git merge-base HEAD origin/main", "git ls-files python", "git ls-tree -r HEAD --name-only",
    "git log --grep='a$' -1", "git log --format=%H -3", "git log -S '[{]' -- python", "git diff 'HEAD~1'",
    "grep -rn 'def launch' python", 'grep -n "a|b" python/x.py', "grep -rn -e '--output' python",
    "ls python/agent_tools", "wc -l python/x.py", "cat README.md", "head -n 40 python/x.py",
    "tail -n 20 python/x.py", "head", "sed -n 1,40p python/x.py", "sed -n '10,$p' python/x.py",
    "git log origin/main --oneline -i --grep='question box'",
]


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
    """The client's rules, then the guard's detaching check and its one-plain-read check (the session's switch)."""
    return (client_admits(command, allowed, denied) and GUARD.detaching_word(command) is None
            and GUARD.read_only_plain(command))


class ReadOnlyShellTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert "Bash(git push:*)" in HOST and len(HOST) >= 10, HOST

    def test_the_recorded_applies_reads_run_one_plain_command_each_and_the_whole_call_is_refused(self):
        denials = json.loads(DENIED_1740.read_text(encoding="utf-8"))["permission_denials"]
        self.assertEqual(len(denials), 1)
        command = denials[0]["tool_input"]["command"]
        segments = [
            "git log origin/main --oneline -i --grep='question box'",
            "head",
            "git ls-tree -r origin/main --name-only",
            "grep -i -E 'console|ask'",
            "head -30",
        ]
        for segment in segments:
            self.assertIn(segment, command)

        self.assertFalse(GUARD.read_only_plain(command))
        for name in READ_ONLY_ROLES:
            words = launch_words(name)
            with self.subTest(role=name, whole=True):
                self.assertFalse(read_only_admits(command, *words))
            for segment in segments:
                with self.subTest(role=name, segment=segment):
                    self.assertTrue(read_only_admits(segment, *words))

    def test_the_guard_reads_one_plain_read_only_command_and_nothing_else(self):
        refused = [
            "git log | head", "git log; git status", "git log -1 && git status", "git rev-parse HEAD || git status",
            "git log &", "git log > l.txt", "cat < f", "git log 2>&1", "git log $(rm x)", "git show `touch x`",
            "cat $HOME/x", 'cat "$HOME"', 'grep x "!x"', "cat ${x}", "cat *.py", "cat f?", "ls [ab]",
            "cat python/{a,b}.py", "ls ~", "git diff HEAD~1", "git log ^x", "git log # x", "grep 'a\\.b' f",
            "git log\ngit status", "nohup git log", "timeout 5 git log", "env git log", "command git log",
            "time git log", "xargs git log", "x=1 git log", "=git log", "cat =ls", "/usr/bin/git log", "sh -c 'git log'",
            "git blame f", "git -C . log", "git -c core.pager=sh log", "git --no-pager log", "git checkout main",
            "git log 'x", "git log --output=l.txt", "git diff --output d.patch", "git diff --outp=d.patch",
            "git log --o=x", "git log -1 --OUTPUT=l.txt", "sed 1p f", "sed -n -i 1p f", "sed -n 1w f",
            "sed -n 1p f -i", "sed -n 'e x' f", "sed -n s/a/b/p f", "git", "sed", "sed -n", "sed -n 1p", "",
        ]
        for command in ADMITTED:
            with self.subTest(admitted=command):
                self.assertIs(GUARD.read_only_plain(command), True)
        for command in refused:
            with self.subTest(refused=command):
                self.assertIs(GUARD.read_only_plain(command), False)

    def test_plain_reads_are_admitted_to_each_read_only_role(self):
        for name in READ_ONLY_ROLES:
            words = launch_words(name)
            for command in ADMITTED:
                with self.subTest(role=name, command=command):
                    self.assertTrue(read_only_admits(command, *words))

    def test_writes_pushes_checkouts_resets_redirections_lists_and_detaching_are_refused(self):
        refused = [
            "git commit -m x", "git add f.py", "rm -rf build", "touch f", "mv a b", "cp a b",
            "git log | tee out.txt", "sed -i s/a/b/ f.py", "sed -n -ni '' 1p python/x.py",
            "sed -n '1w out.txt' python/x.py", "git log --output=log.txt",
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
            "git log --oneline -5 | head", "git log -1; git status", "git blame -L 1,10 python/x.py",
            "cat README.md | head -40",
        ]
        for name in READ_ONLY_ROLES:
            words = launch_words(name)
            for command in refused:
                with self.subTest(role=name, command=command):
                    self.assertFalse(read_only_admits(command, *words))

    def test_every_earlier_rebuilt_or_fed_output_spelling_is_refused(self):
        fed = [
            "cat args.txt | xargs git diff",
            "grep -h output args.txt | xargs git log",
            "ls | xargs git show --stat",
            "xargs git diff < args.txt",
            "head -1 args.txt | time xargs git diff",
            'cat args.txt | x""args git diff',
            "cat args.txt | XARGS git diff",
        ]
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
        expanded = [  # the shell builds the name from an alternative, an escape or an expansion the deletion copy keeps
            "git diff --out{p,p}ut=d.patch HEAD~1",
            "git diff --{output,output}=d.patch HEAD~1",
            "git log --outp{u,u}t=l.txt -1",
            "git diff --$'\\157'utput=d.patch HEAD~1",
            "git diff --out$@put=d.patch HEAD~1",
            "git diff --${x:-output}=d.patch HEAD~1",
            "git diff $'\\055\\055output=d.patch' HEAD~1",
            'git diff "${x:--}${x:--}output=d.patch" HEAD~1',
            "git diff -${x:--}output=d.patch HEAD~1",
            "git diff --out${x}put=d.patch HEAD~1",
            'git diff -"-"out{p,p}ut=d.patch HEAD~1',  # a quote or a backslash between the two dashes
            "git diff -\\-out{p,p}ut=d.patch HEAD~1",
            'git diff "-"-out$@put=d.patch HEAD~1',
            "git diff -'-'out$@put=d.patch HEAD~1",
            "git diff -\\-$'\\157'utput=d.patch HEAD~1",
            'git diff -"-"out${x}put=d.patch HEAD~1',
            "git log -\\-outp{u,u}t=l.txt -1",
            "git diff${IFS}-\\-out{p,p}ut=d.patch HEAD~1",  # joined to the word before it
        ]
        isolated = [  # a plain revision and exactly one refusing construct, so one rule's removal turns one red
            'git diff --out""put=d.patch 0123abcd',  # the literal text is `--output`: the `--output` rule
            "git diff --out{p,p}ut=d.patch 0123abcd",  # brace
            "git diff --{output,output}=d.patch 0123abcd",  # brace
            "git diff 0123abcd$IFS--output=d.patch",  # unquoted `$`, the `$IFS` spelling
            'git diff "0123abcd${IFS}--output=d.patch"',  # `$` inside double quotes, the `${IFS}` spelling
            "git diff --$'o'utput=d.patch 0123abcd",  # unquoted `$`, the `$'...'` spelling
            "git diff --out$@put=d.patch 0123abcd",  # unquoted `$`, the `$@` spelling
            'git diff "--out$*put=d.patch" 0123abcd',  # `$` inside double quotes, the `$*` spelling
            'git diff "--${x:-output}=d.patch" 0123abcd',  # `$` inside double quotes, the `${...}` spelling
        ]
        for command in fed + rebuilt + expanded + isolated:
            with self.subTest(guard_alone=command):
                self.assertIs(GUARD.read_only_plain(command), False)
        for name in READ_ONLY_ROLES:
            words = launch_words(name)
            for command in fed + rebuilt + expanded + isolated:
                with self.subTest(role=name, command=command):
                    self.assertFalse(read_only_admits(command, *words))

    def test_the_guard_refuses_anything_but_one_plain_read_in_a_read_only_shell_session(self):
        def run(command: str, switched: bool) -> subprocess.CompletedProcess:
            env = {key: value for key, value in os.environ.items() if key != engine_session.READ_ONLY_SHELL_SWITCH}
            if switched:
                env[engine_session.READ_ONLY_SHELL_SWITCH] = "1"
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
            return subprocess.run([str(wrapper)], input=payload, env=env, capture_output=True, text=True,
                                  cwd=tmp, timeout=60, check=False)

        with tempfile.TemporaryDirectory() as tmp:
            wrapper = real_guard(Path(tmp) / "guard")
            self.assertEqual(GUARD.READ_ONLY_SHELL_ENV, engine_session.READ_ONLY_SHELL_SWITCH)
            refused = run("git log --oneline -3 | head", True)
            self.assertEqual(refused.returncode, 2, refused.stderr)
            self.assertIn(GUARD.READ_ONLY_SHELL_REFUSAL, refused.stderr)
            self.assertNotIn("one plain command per Bash call", run("git log --oneline -3 | head", False).stderr)
            self.assertEqual(run("git log --oneline -3", True).returncode, 0)
            short = run("git", True)  # a raise would exit 1 and let the call run
            self.assertEqual(short.returncode, 2, short.stderr)
            self.assertIn(GUARD.READ_ONLY_SHELL_REFUSAL, short.stderr)
            detaching = run("nohup git log", True)
            self.assertEqual(detaching.returncode, 2, detaching.stderr)
            self.assertIn(GUARD.READ_ONLY_SHELL_REFUSAL, detaching.stderr)
            self.assertNotIn("background mode", detaching.stderr)
            unswitched = run("nohup git log", False)
            self.assertEqual(unswitched.returncode, 2, unswitched.stderr)
            self.assertIn("background mode", unswitched.stderr)

    def test_the_guard_and_the_launch_hold_one_allow_list(self):
        self.assertEqual(engine_session.READ_ONLY_PROGRAMS, GUARD.READ_ONLY_PROGRAMS)
        self.assertEqual(engine_session.READ_ONLY_BASH,
                         tuple(f"Bash({program}:*)" for program in GUARD.READ_ONLY_PROGRAMS))

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

        self.assertIn("Shell rules allowing a command: "
                      + ", ".join(engine_session.shell_rules(read_role(AGENTS, "reviewer"))[0]), read_only)
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
