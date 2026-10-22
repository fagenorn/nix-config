import concurrent.futures
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from .guard_policy_world import GuardPolicyWorld


SETTINGS_PATH = Path(os.environ["CLAUDE_SETTINGS_PATH"])
BASE_POLICY_PATH = Path(os.environ["CLAUDE_GUARD_BASE_POLICY_PATH"])
NODO = "elevenyellow/nodocom"
NODO_ROW = {"default_branch": "main", "integration_branch": "dev", "evidence": {}}
ABSENT = object()
EXPECTED_ALLOW = [
    "Bash(git fetch:*)", "Bash(git status:*)", "Bash(git log:*)",
    "Bash(git diff:*)", "Bash(gh pr view:*)", "Bash(gh pr list:*)",
    "Bash(gh pr checks:*)", "Bash(gh issue view:*)", "Bash(gh issue list:*)",
    "Bash(git worktree add:*)", "Bash(git worktree list:*)",
    "Bash(git worktree remove:*)", "Bash(git worktree prune:*)",
    "Bash(git push:*)", "Bash(gh pr create:*)",
    "Bash(git branch -d:*)", "Bash(gh pr merge:*)",
    "Bash(workflow-state:*)", "Bash(~/.agents/bin/workflow-state:*)",
    "Bash(artifact-budget:*)", "Bash(~/.agents/bin/artifact-budget:*)", "Agent",
]

# Stand-in for `gh`. Answers the two lookups the guard makes for any slug and
# any protected branch, so the merge path can be exercised in every fixture
# repository. FAKE_<STAGE>_MODE injects failures; FAKE_<STAGE>_JSON overrides
# the payload.
FAKE_GH_SCRIPT = '''
import os
import sys
import time

# The guard must scrub the gh-recognised token variables from its lookups (the
# harness token is narrower than the keyring credential). Refusing to answer
# when one is visible makes every merge-path test double as that assertion.
for name in ("GITHUB_TOKEN", "GH_TOKEN"):
    if name in os.environ:
        print("fake gh saw " + name + " in its environment", file=sys.stderr)
        raise SystemExit(64)

argv = sys.argv[1:]
stage = None
number = ""
slug = ""
branch = ""
if (
    len(argv) == 7
    and argv[0:2] == ["pr", "view"]
    and argv[3] == "--repo"
    and argv[5] == "--json"
    and argv[6] == "state,baseRefName,headRefName,url,statusCheckRollup"
):
    stage, number, slug, branch = "pr", argv[2], argv[4], "main"
elif len(argv) == 2 and argv[0] == "api":
    parts = argv[1].split("/")
    if (
        len(parts) == 6
        and parts[0] == "repos"
        and parts[3] == "branches"
        and parts[5] == "protection"
    ):
        stage = "protection"
        slug = parts[1] + "/" + parts[2]
        branch = parts[4]
if stage is None:
    print("unexpected fake-gh argv: " + repr(argv), file=sys.stderr)
    raise SystemExit(64)

mode = os.environ.get("FAKE_" + stage.upper() + "_MODE", "ok")
if mode == "nonzero":
    print("fake " + stage + " failure", file=sys.stderr)
    raise SystemExit(9)
if mode == "timeout":
    time.sleep(2)
if mode == "invalid":
    print("{")
    raise SystemExit(0)

if stage == "pr":
    default = (
        '{"state":"OPEN","baseRefName":"' + branch + '",'
        '"headRefName":"issue-' + number + '-topic",'
        '"url":"https://github.com/' + slug + "/pull/" + number + '",'
        '"statusCheckRollup":[{"__typename":"CheckRun",'
        '"status":"COMPLETED","conclusion":"SUCCESS"}]}'
    )
else:
    default = (
        '{"required_status_checks":{"contexts":["Nix Eval"]},'
        '"enforce_admins":{"enabled":true}}'
    )
print(os.environ.get("FAKE_" + stage.upper() + "_JSON", default))
'''

# Stand-in for the row check (`guard-policy derive`). Answers from a JSON object
# of slug -> row: FAKE_DERIVE_ROWS names one, else the class default (Nodo's row).
# FAKE_DERIVE_MODE: rows (default), refused_code, unavailable, garbage, hang, and
# slow (sleeps until the time.time() instant FAKE_DERIVE_UNTIL, then answers as rows).
# FAKE_DERIVE_LOG appends each slug asked; FAKE_DERIVE_PIDFILE receives the pid
# of the grandchild `hang` leaves behind.
FAKE_DERIVE_SCRIPT = '''
import json
import os
import subprocess
import sys
import time

argv = sys.argv[1:]
if len(argv) != 2 or argv[0] != "--repository":
    print("unexpected fake-derive argv: " + repr(argv), file=sys.stderr)
    raise SystemExit(64)
slug = argv[1]
log = os.environ.get("FAKE_DERIVE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(slug + "\\n")
mode = os.environ.get("FAKE_DERIVE_MODE", "rows")
if mode == "hang":
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    with open(os.environ["FAKE_DERIVE_PIDFILE"], "w", encoding="utf-8") as stream:
        stream.write(str(sleeper.pid))
    time.sleep(600)
if mode == "slow":
    time.sleep(max(0.0, float(os.environ["FAKE_DERIVE_UNTIL"]) - time.time()))
if mode == "garbage":
    print("{")
    raise SystemExit(0)
report = {"schema_version": 1, "repository": slug, "row": None, "refused": [], "cause": None}
if mode == "unavailable":
    report.update(outcome="unavailable", cause={"reason_code": "registry_invalid", "detail": "x"})
    print(json.dumps(report))
    raise SystemExit(2)
if mode == "refused_code":
    report.update(outcome="refused", refused=[
        {"project_id": "p", "root": "/p", "reason_code": "fetch_failed", "detail": "x"}])
    print(json.dumps(report))
    raise SystemExit(1)
with open(os.environ.get("FAKE_DERIVE_ROWS", @ROWS@), encoding="utf-8") as stream:
    rows = json.load(stream)
if slug in rows:
    report.update(outcome="derived", row=rows[slug])
    print(json.dumps(report))
    raise SystemExit(0)
report.update(outcome="refused")
print(json.dumps(report))
raise SystemExit(1)
'''


class ClaudePermissionGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        cls.settings = settings
        matches = [
            entry
            for entry in settings.get("hooks", {}).get("PreToolUse", [])
            if entry.get("matcher") == "Bash"
        ]
        if len(matches) != 1:
            raise AssertionError(f"expected one Bash PreToolUse matcher, found {len(matches)}")
        command_hooks = [
            hook
            for hook in matches[0].get("hooks", [])
            if hook.get("type") == "command"
        ]
        if len(command_hooks) != 1:
            raise AssertionError(f"expected one command hook, found {command_hooks!r}")
        command_hook = command_hooks[0]
        if command_hook.get("timeout") != 30:
            raise AssertionError(f"expected hook timeout 30, found {command_hook.get('timeout')!r}")
        if command_hook.get("args", []) != []:
            raise AssertionError(f"registered hook must pass no args: {command_hook.get('args')!r}")
        command = command_hook.get("command")
        if not isinstance(command, str) or " " in command:
            raise AssertionError(f"registered command must be one argument-free path: {command!r}")
        override_flags = ("--git-bin", "--gh-bin", "--jq-bin", "--child-timeout-seconds",
                          "--derive-timeout-seconds")
        if any(flag in command for flag in override_flags):
            raise AssertionError(f"registered command contains a test override: {command!r}")
        cls.guard = Path(command)
        if not cls.guard.is_absolute() or not os.access(cls.guard, os.X_OK):
            raise AssertionError(f"guard is not an executable absolute path: {cls.guard}")

        cls.fixture_dir = tempfile.TemporaryDirectory()
        cls.fake_gh = Path(cls.fixture_dir.name) / "fake-gh"
        cls.fake_gh.write_text(f"#!{sys.executable}\n" + FAKE_GH_SCRIPT, encoding="utf-8")
        cls.fake_gh.chmod(0o755)
        rows_path = Path(cls.fixture_dir.name) / "derive-rows.json"
        rows_path.write_text(json.dumps({NODO: NODO_ROW}), encoding="utf-8")
        cls.fake_derive = Path(cls.fixture_dir.name) / "fake-derive"
        cls.fake_derive.write_text(
            f"#!{sys.executable}\n" + FAKE_DERIVE_SCRIPT.replace("@ROWS@", repr(str(rows_path))),
            encoding="utf-8")
        cls.fake_derive.chmod(0o755)
        # The registered wrapper names the store base policy and the compiled policy
        # of this host, which no test may read: every invocation passes the built base
        # policy and a fixture compiled policy (`cls.policy`, one row for Nodo) as later
        # arguments.
        cls.base_policy = json.loads(BASE_POLICY_PATH.read_text(encoding="utf-8"))
        cls.policy = cls.write_policy(derived_repositories={NODO: NODO_ROW}, derivation={})

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    @classmethod
    def write_policy(cls, **members):
        """A compiled policy file: no rows and a null derivation, `members` replaced
        (ABSENT removes one)."""
        return cls._write_fixture({"derived_repositories": {}, "derivation": None, **members})

    @classmethod
    def write_base(cls, **members):
        """A base policy file: the built base policy with `members` replaced (ABSENT removes one)."""
        return cls._write_fixture({**cls.base_policy, **members})

    @classmethod
    def _write_fixture(cls, document):
        document = {key: value for key, value in document.items() if value is not ABSENT}
        handle, name = tempfile.mkstemp(dir=cls.fixture_dir.name, suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream)
        return Path(name)

    def invoke_raw(self, raw, *guard_args, env=None, timeout=5):
        if "--base-policy" not in guard_args:
            guard_args = (*guard_args, "--base-policy", str(BASE_POLICY_PATH))
        if "--policy" not in guard_args:
            guard_args = (*guard_args, "--policy", str(self.policy))
        if "--derive-bin" not in guard_args:
            guard_args = (*guard_args, "--derive-bin", str(self.fake_derive))
        child_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
        child_env.update(env or {})
        return subprocess.run(
            [self.guard, *guard_args], input=raw, text=True, capture_output=True,
            timeout=timeout, check=False, env=child_env,
        )

    def invoke_command(self, command, *guard_args, env=None):
        return self.invoke_raw(
            json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
            *guard_args, env=env,
        )

    def invoke_command_in(self, command, cwd, *guard_args, env=None):
        return self.invoke_raw(
            json.dumps({
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(cwd),
            }),
            *guard_args, env=env,
        )

    def run_guard(self, command, cwd=None, env=None, guard_args=None, timeout=5):
        """Invoke the guard with the fake `gh` wired in by default."""
        if guard_args is None:
            guard_args = ("--gh-bin", str(self.fake_gh))
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        if cwd is not None:
            payload["cwd"] = str(cwd)
        return self.invoke_raw(json.dumps(payload), *guard_args, env=env, timeout=timeout)

    def rows_env(self, rows):
        """Env making the stub row check answer from `rows` (slug -> row)."""
        handle, name = tempfile.mkstemp(dir=self.fixture_dir.name, suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(rows, stream)
        return {"FAKE_DERIVE_ROWS": name}

    def assert_row_check_killed(self, pidfile):
        pid = int(pidfile.read_text(encoding="utf-8"))
        give_up = time.monotonic() + 5
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            if time.monotonic() > give_up:
                self.fail(f"row-check grandchild {pid} outlived the verdict")
            time.sleep(0.1)

    def make_repo(self, origin, default_branch="main"):
        """A throwaway git repo whose origin remote is `origin`.

        `default_branch` becomes origin/HEAD, which is what the guard reads to
        learn the integration branch; pass None to leave it unresolvable.
        """
        root = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        argv_list = [
            ["git", "init", "--quiet"],
            ["git", "remote", "add", "origin", origin],
        ]
        if default_branch is not None:
            argv_list.append([
                "git", "symbolic-ref", "refs/remotes/origin/HEAD",
                f"refs/remotes/origin/{default_branch}",
            ])
        for argv in argv_list:
            subprocess.run(argv, cwd=root, check=True, capture_output=True)
        return root

    def test_generated_allow_surface_is_exact_and_ordered(self):
        self.assertEqual(EXPECTED_ALLOW, self.settings["permissions"]["allow"])

    def test_bash_timeout_ceiling_is_raised_and_the_default_left_alone(self):
        # #261 D2: an explicit foreground timeout must be able to cover the
        # longest verification command; the 120 s default stays the host's.
        env = self.settings.get("env", {})
        self.assertEqual(env.get("BASH_MAX_TIMEOUT_MS"), "3600000")
        self.assertGreaterEqual(int(env["BASH_MAX_TIMEOUT_MS"]), 30 * 60 * 1000)
        self.assertNotIn("BASH_DEFAULT_TIMEOUT_MS", env)
        self.assertEqual(env.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"), "1")

    def test_unrelated_bash_and_exact_branch_delete_pass(self):
        for command in ("git status --short", "git branch -d issue-30-safe"):
            with self.subTest(command=command):
                result = self.invoke_command(command)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_single_command_lifecycle_calls_pass_the_guard(self):
        for command in (
            "workflow-state control --repo-root /r --run-id run --request-file - <<'JSON' "
            "| artifact-budget validate-report --boundary workflow-response --input -\n"
            '{"interface_version": 2}\nJSON',
            "artifact-budget validate-report --boundary ship-summary --input - <<'JSON' "
            "| ~/.agents/bin/workflow-state finish --repo-root /r --run-id run "
            "--now 2026-09-24T00:00:00Z --summary-file -\n{}\nJSON",
        ):
            with self.subTest(command=command.split()[0]):
                result = self.invoke_command(command)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_malformed_hook_input_fails_closed(self):
        cases = (
            "not-json", "[]", "{}",
            json.dumps({"tool_name": "Read", "tool_input": {"command": "git branch -d x"}}),
            json.dumps({"tool_name": "Bash", "tool_input": {"command": 3}}),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                result = self.invoke_raw(raw)
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: invalid hook input:", result.stderr)

    def test_unsafe_branch_delete_shapes_fail_closed(self):
        cases = (
            "git branch -d -f topic", "git branch -d --force topic",
            "git branch -d one two", "git branch -d -bad",
            "git branch -d topic && true", "git branch -d topic; true",
            "git branch -d $(printf topic)", "git branch -d topic*",
            "command git branch -d topic", "git branch -d topic\ntrue",
        )
        for command in cases:
            with self.subTest(command=command):
                result = self.invoke_command(command)
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe branch deletion:", result.stderr)

    def test_heredoc_and_quoted_mentions_pass_in_own_repo(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "cat > notes.md <<'EOF'\nrun gh pr merge 5 later\ngit push origin main\nEOF\n",
            'echo "docs say gh pr create --repo x"',
            "true # gh pr merge 9 --repo fagenorn/nix-config --merge --delete-branch",
            "workflow-state finish --notes 'blocked, cannot gh pr merge yet'",
            "rg -n 'git branch -d' docs/",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_raise_label_mentions_pass(self):
        for command in (
            'echo "gh pr edit 1 --add-label instruction-budget-raise"',
            "cat > notes.md <<'EOF'\ngh pr edit 1 --add-label instruction-budget-raise\nEOF\n",
            "git commit -m 'docs: explain the instruction-budget-raise label'",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    # ------------------------------------------------------------------
    # Adversarial table. Each case is one class of "the guard's parser and
    # the shell disagree". Every command below really runs a guarded verb, so
    # none of them may exit 0 unless its grammar legitimately passes.
    # ------------------------------------------------------------------

    def test_heredoc_declared_before_a_separator_guards_the_rest_of_the_line(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            ": <<EOF; git push --force origin main\nEOF\n",
            ": <<EOF && git push --force origin main\nEOF\n",
            ": <<EOF | git push --force origin main\nEOF\n",
            "cat <<EOF; gh pr merge 107 --repo someoneelse/tool --merge --delete-branch\nEOF\n",
            ": <<EOF; git branch -d main\nEOF\n",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, (command, result.stdout))
        # The body itself is still inert: here the verb is genuinely inside it.
        inert = self.run_guard(
            "cat <<EOF; true\ngit push --force origin main\nEOF\n", cwd=repo)
        self.assertEqual(0, inert.returncode, inert.stderr)

    def test_namespaced_ref_spellings_of_the_default_branch_block(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "git push origin refs/heads/main",
            "git push -u origin refs/heads/main",
            "git push origin heads/main",
            "git push origin remotes/origin/main",
            "git push origin tags/v1",
            "git push origin HEAD",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn("lifecycle guard: unsafe push:", result.stderr)
        ok = self.run_guard("git push -u origin issue-101-topic", cwd=repo)
        self.assertEqual(0, ok.returncode, ok.stderr)

    def test_shell_equivalent_spellings_are_adjudicated(self):
        # Every command here pushes the default branch, so a legitimate pass is
        # impossible: exit 0 would mean the guard simply failed to see the verb.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "(git push origin main)",                             # subshell
            "{ git push origin main; }",                          # group
            "if true; then git push origin main; fi",             # then
            "for x in a; do git push origin main; done",          # do
            "while true; do git push origin main; done",          # while/do
            "case x in a) git push origin main;; esac",           # case arm
            "! git push origin main",                             # negation
            "time git push origin main",                          # time keyword
            "git  push origin main",                              # double space
            "git\tpush origin main",                              # tab
            '"git" push origin main',                             # quoted word
            "x=$(git push origin main)",                          # substitution
            "`git push origin main`",                             # backticks
            "xargs git push origin main",                         # argv runner
            "timeout 5 git push origin main",                     # argv runner
            "nice git push origin main",                          # argv runner
            "env -i git push origin main",                        # env options
            "env FOO=bar git push origin main",                   # env assignment
            "sudo -u anis git push origin main",                  # sudo options
            "eval 'git push origin main'",                        # evaluator
            "sh -c 'git push origin main'",                       # evaluator
            "bash -c 'gh pr merge 1 --repo someoneelse/tool --merge --delete-branch'",
            'echo "unterminated ; git push origin main',           # unparseable
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)

    LABEL_REFUSAL_PREFIX = (
        "lifecycle guard: unsafe instruction-budget-raise label edit:")
    DIRECT_ADD_REASON = (
        "only the user applies this label (Instruction Budget raise control)")
    EVALUATOR_REASON = "shell source passed to an evaluator cannot be validated"
    SPLIT_STRING_REASON = "command text handed to env -S cannot be validated"
    # The existing fail-closed reasons the label rows reuse.
    UNPARSED_REASON = "the command could not be parsed"
    UNTOKENISED_REASON = "the segment could not be tokenised"
    QUOTED_SUBSTITUTION_REASON = (
        "a command substitution inside a quoted word cannot be validated")

    def test_raise_label_additions_are_refused_in_every_spelling(self):
        # Every command here adds the instruction-budget-raise label, so exit 0
        # would mean the guard failed to see it. No cwd: the rule is global.
        for command in (
            "gh pr edit 1 --add-label instruction-budget-raise",
            "gh issue edit 23 --add-label instruction-budget-raise",
            "gh pr edit 1 --add-label=instruction-budget-raise",
            "gh pr edit 1 --add-label bug,instruction-budget-raise",
            'gh pr edit 1 --add-label "bug, instruction-budget-raise"',
            "gh pr edit 1 --add-label 'instruction-budget-raise'",
            "gh pr edit 1 --add-label '\"bug\",\"instruction-budget-raise\"'",
            "gh pr edit 1 --add-label INSTRUCTION-BUDGET-RAISE",
            "gh pr edit 1 --add-label bug --add-label instruction-budget-raise",
            "gh pr edit 1 --add-label instruction\\-budget\\-raise",
            '"gh" pr edit 1 --add-label instruction-budget-raise',
            "gh  pr edit 1 --add-label instruction-budget-raise",
            "gh pr\tedit 1 --add-label instruction-budget-raise",
            "(gh pr edit 1 --add-label instruction-budget-raise)",
            "{ gh pr edit 1 --add-label instruction-budget-raise; }",
            "x=$(gh pr edit 1 --add-label instruction-budget-raise)",
            "`gh pr edit 1 --add-label instruction-budget-raise`",
            "true && gh pr edit 1 --add-label instruction-budget-raise",
            "if true; then gh pr edit 1 --add-label instruction-budget-raise; fi",
            "command gh pr edit 1 --add-label instruction-budget-raise",
            "env -i gh pr edit 1 --add-label instruction-budget-raise",
            "env FOO=bar gh pr edit 1 --add-label instruction-budget-raise",
            "sudo -u anis gh pr edit 1 --add-label instruction-budget-raise",
            "GH_REPO=fagenorn/nix-config gh pr edit 1 --add-label instruction-budget-raise",
            "gh pr -R fagenorn/nix-config edit 1 --add-label instruction-budget-raise",
            "gh issue --repo=a/b edit 1 --add-label instruction-budget-raise",
            "/opt/homebrew/bin/gh pr edit 1 --add-label instruction-budget-raise",
            "xargs gh pr edit 1 --add-label instruction-budget-raise",
            "timeout 5 gh pr edit 1 --add-label instruction-budget-raise",
            "eval 'gh pr edit 1 --add-label instruction-budget-raise'",
            "sh -c 'gh pr edit 1 --add-label instruction-budget-raise'",
            "gh pr edit 1 --add-label 'instruction-budget-raise",  # unterminated
            # split_segments takes `<<"a\"` as a heredoc delimiter, while the
            # tokeniser reads `\"` as an escaped quote and never closes it.
            'gh pr edit 1 --add-label instruction-budget-raise <<"a\\"\nbody\na\\\n',
            "gh pr edit $(gh pr view --json number --jq .number) "
            "--add-label instruction-budget-raise",
            "gh pr edit `echo 1` --add-label instruction-budget-raise",
            # A separator inside the substitution splits `gh` from its label.
            "gh pr edit $(gh pr view --json number | jq -r .number) "
            "--add-label instruction-budget-raise",
            "gh pr edit `gh pr view --json number | jq -r .number` "
            "--add-label instruction-budget-raise",
            "gh pr edit $(true; echo 1) --add-label instruction-budget-raise",
            # The `gh` word sits in an evaluator segment, its label in the next.
            "gh pr edit $(sh -c 'printf 1'; true) --add-label instruction-budget-raise",
            # A quoted substitution still runs.
            'result="$(gh pr edit 1 --add-label instruction-budget-raise)"',
            'echo "`gh pr edit 1 --add-label instruction-budget-raise`"',
        ):
            # Every row except the fail-closed rows names the direct-add reason.
            reason = {
                "eval 'gh pr edit 1 --add-label instruction-budget-raise'": self.EVALUATOR_REASON,
                "sh -c 'gh pr edit 1 --add-label instruction-budget-raise'": self.EVALUATOR_REASON,
                "gh pr edit 1 --add-label 'instruction-budget-raise": self.UNPARSED_REASON,
                'gh pr edit 1 --add-label instruction-budget-raise <<"a\\"\nbody\na\\\n':
                    self.UNTOKENISED_REASON,
                'result="$(gh pr edit 1 --add-label instruction-budget-raise)"':
                    self.QUOTED_SUBSTITUTION_REASON,
                'echo "`gh pr edit 1 --add-label instruction-budget-raise`"':
                    self.QUOTED_SUBSTITUTION_REASON,
            }.get(command, self.DIRECT_ADD_REASON)
            with self.subTest(command=command):
                result = self.run_guard(command)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn(f"{self.LABEL_REFUSAL_PREFIX} {reason}", result.stderr)
        elsewhere = self.make_repo("https://github.com/someoneelse/tool.git")
        result = self.invoke_command_in(
            "gh pr edit 1 --add-label instruction-budget-raise", elsewhere)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn(f"{self.LABEL_REFUSAL_PREFIX} {self.DIRECT_ADD_REASON}", result.stderr)

    def test_raise_label_refusal_precedes_every_other_verb(self):
        # The push alone would be refused as a push; the label wins, so the
        # label rule is judged before any repository-bound verb.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        result = self.run_guard(
            "git push origin main; gh pr edit 1 --add-label instruction-budget-raise",
            cwd=repo)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn(f"{self.LABEL_REFUSAL_PREFIX} {self.DIRECT_ADD_REASON}", result.stderr)
        self.assertNotIn("unsafe push", result.stderr)

    def test_other_label_edits_and_mentions_pass(self):
        for command in (
            "gh pr edit 1 --add-label bug",
            'gh issue edit 23 34 --add-label "bug,help wanted"',
            "gh pr edit 1 --remove-label instruction-budget-raise",
            "gh pr edit 1 --body 'the user may add instruction-budget-raise'",
            "xargs gh pr edit 1 --add-label bug",
            "sh -c 'gh pr edit 1 --add-label bug'",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def assert_detaching_refusal(self, result, word, command):
        self.assertEqual(2, result.returncode, (command, result.stderr))
        self.assertIn(
            f"lifecycle guard: detaching command `{word}` refused:", result.stderr,
            command,
        )
        self.assertIn("run_in_background", result.stderr, command)
        self.assertIn("launch-scope exec", result.stderr, command)

    def test_detaching_words_are_refused_globally(self):
        # Every form below makes the shell run a detaching word (or hands it to
        # source the guard cannot parse), so exit 0 means the guard missed it.
        # No cwd: the refusal is global and needs no repository.
        templates = (
            "W x", "W x &", "(W x)", "{ W x; }", "`W x`", "y=$(W x)", "$(W)",
            "case a in a) W x;; esac", "! W x", "time W x",
            "if true; then W x; fi", "for i in a; do W x; done",
            "true && W x", "x & W", '"W" x', "/usr/bin/W x",
            "command W x", "builtin W x", "exec W x", "env W x", "env -i W x",
            "env FOO=bar W x", "sudo W x", "sudo -E W x",
            "eval 'W x'", "sh -c 'W x'", 'bash -c "W x"', "zsh -c 'W x'",
            "dash -c 'W x'", "ksh -c 'W x'", "/bin/sh -c 'W x &'",   # per D6
            'echo "$(W x &)"', 'echo "`W x`"',                     # per D3
            'echo "unterminated ; W x',                              # unparseable
            ">log 2>&1 W x &", "2>&1 W x", "</dev/null W x", "> log W x",
            ">> log 2>&1 W x", "&>log W x", "FOO=bar >log W x",       # redirections
            "sudo -u anis W x", "sudo -g wheel W x", "sudo -u anis -E W x",
            "exec -a foo W x", "env -u FOO W x", "env -C /tmp W x",
            "env -S -i W x", "sudo -E -u anis env -u FOO W x",         # option args
            "W>/dev/null sleep 60 &", "W</dev/null x", "W>&2", "W>log x",
            "W>>log x", "sudo>/dev/null W x", "sudo -u >log anis W x",  # attached
            "env -u || W x", "sudo -u; W x", "exec -a && W x",          # separators
            "env -u FOO 2>&1 W x",
            "env -S 'W x'", "env --split-string='W x'", 'env -S"W x"',
            "env --split-string 'W x'", "env -iS 'W x'",                # split-string
            "X='>' W x &", "exec -a 'worker>' W x", "X=1> out W x",
            "X='>' sh -c 'W x'", "sudo -u 'a>' W x",                    # quoted `>`
        )
        for word in ("nohup", "setsid", "disown"):
            for template in templates:
                command = template.replace("W", word)
                with self.subTest(command=command):
                    self.assert_detaching_refusal(
                        self.run_guard(command), word, command)
        # The issue's AC1 forms verbatim, and the deliberate over-refusal of D3.
        for command, word in (
            ("nohup x &", "nohup"), ("(setsid x)", "setsid"),
            ("env nohup x", "nohup"), ("$(disown)", "disown"),
            ("sh -c 'nohup x'", "nohup"), ("x & disown", "disown"),
            ("sh -c 'cat nohup.out'", "nohup"),
            ("sh -c 'setsid a; nohup b'", "setsid"),               # earliest, per D6
        ):
            with self.subTest(command=command):
                self.assert_detaching_refusal(self.run_guard(command), word, command)

    def test_detaching_word_mentions_pass(self):
        for command in (
            'echo "nohup"',
            "grep nohup log",
            "rg -n 'setsid|disown' docs/",
            'echo "run nohup x & later"',
            "cat > notes.md <<'EOF'\nnohup x &\nsetsid y\ndisown\nEOF\n",
            "true # nohup x & disown",
            "a & b & wait",
            "sleep 1 &",
            "make > nohup.out 2>&1",
            "tail -f nohup.out",
            "sudo -u anis ls nohup.out",
            "sudo -u >log anis ls nohup",
            "make 2>&1 >nohup.out",
            "ls >nohup.out",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_detaching_refusal_precedes_the_push_grammar(self):
        # AC3: still refused, now for detaching rather than as a push.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        result = self.run_guard("nohup git push origin main", cwd=repo)
        self.assert_detaching_refusal(result, "nohup", "nohup git push origin main")
        self.assertNotIn("unsafe push", result.stderr)
        # D1: the check runs before the base policy loads. The registered wrapper
        # forwards "$@", so a later --base-policy overrides the store base policy.
        bad_policy = ("--base-policy", "/nonexistent/lifecycle-guard-base-policy.json")
        refused = self.invoke_command("setsid x", *bad_policy)
        self.assert_detaching_refusal(refused, "setsid", "setsid x")
        control = self.invoke_command("true", *bad_policy)
        self.assertEqual(2, control.returncode)
        self.assertIn("lifecycle guard: invalid policy:", control.stderr)

    def test_whitespace_normalisation_still_accepts_a_valid_push(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in ("git  push -u origin topic", "git\tpush origin topic"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_push_grammar_accepts_only_plain_nondefault_branch(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        ok = self.run_guard("git push -u origin worktree-issue-101-quota", cwd=repo)
        self.assertEqual(0, ok.returncode, ok.stderr)
        self.assertEqual(0, self.run_guard("git push origin topic", cwd=repo).returncode)
        for bad in (
            "git push origin main",                       # default branch
            "git push --force origin topic",              # force
            "git push origin :topic",                     # delete refspec
            "git push origin +topic",                     # force refspec
            "git push upstream topic",                    # foreign remote
            "git push --mirror origin",                   # mirror
            "git push origin --delete topic",             # branch deletion
            "git push origin --tags",                     # tags
            "git push -u origin topic extra",             # extra refspec
            "git push origin $(evil)",                    # command substitution
            "git push",                                   # implicit remote
            "git push -u origin topic && rm -rf /",       # chained second command is fine BUT
        ):
            with self.subTest(command=bad):
                result = self.run_guard(bad, cwd=repo)
                if bad.endswith("rm -rf /"):
                    self.assertEqual(0, result.returncode, result.stderr)
                else:
                    self.assertEqual(2, result.returncode, bad)
                    self.assertIn("lifecycle guard: unsafe push:", result.stderr)

    def test_push_outside_fagenorn_blocks(self):
        repo = self.make_repo("git@github.com:someoneelse/tool.git")
        result = self.run_guard("git push -u origin topic", cwd=repo)
        self.assertEqual(2, result.returncode)
        self.assertIn("outside standing authorization", result.stderr)

    def test_push_fails_closed_without_a_resolvable_default_branch(self):
        repo = self.make_repo("git@github.com:fagenorn/argus.git", default_branch=None)
        result = self.run_guard("git push -u origin topic", cwd=repo)
        self.assertEqual(2, result.returncode)
        self.assertIn("default branch", result.stderr)

    def test_pr_create_grammar_and_base_check(self):
        repo = self.make_repo("https://github.com/fagenorn/argus.git")
        ok = self.run_guard(
            'gh pr create --repo fagenorn/argus --base main --head issue-7-fix '
            '--title "fix: guard" --body "Closes #7"', cwd=repo)
        self.assertEqual(0, ok.returncode, ok.stderr)
        for bad in (
            # wrong repo
            'gh pr create --repo fagenorn/nix-config --base main --head t --title "x" --body "y"',
            # wrong base
            'gh pr create --repo fagenorn/argus --base release --head t --title "x" --body "y"',
            # unsafe title
            'gh pr create --repo fagenorn/argus --base main --head t --title "$(pwn)" --body "y"',
            # unsafe body
            'gh pr create --repo fagenorn/argus --base main --head t --title "x" --body "`id`"',
            # head is the base
            'gh pr create --repo fagenorn/argus --base main --head main --title "x" --body "y"',
            # wrong shape
            'gh pr create --repo fagenorn/argus --base main --head t --fill',
            # extra flag
            'gh pr create --repo fagenorn/argus --base main --head t --title "x" --body "y" --draft',
            # flag order
            'gh pr create --base main --repo fagenorn/argus --head t --title "x" --body "y"',
        ):
            with self.subTest(command=bad):
                result = self.run_guard(bad, cwd=repo)
                self.assertEqual(2, result.returncode, bad)
                self.assertIn("lifecycle guard: unsafe PR creation:", result.stderr)

    def test_pr_create_outside_fagenorn_blocks(self):
        repo = self.make_repo("git@github.com:someoneelse/tool.git")
        result = self.run_guard(
            'gh pr create --repo someoneelse/tool --base main --head t '
            '--title "x" --body "y"', cwd=repo)
        self.assertEqual(2, result.returncode)
        self.assertIn("outside standing authorization", result.stderr)

    def test_merge_validates_in_every_fagenorn_repo_and_blocks_elsewhere(self):
        argus = self.make_repo("git@github.com:fagenorn/argus.git")
        merge = "gh pr merge 107 --repo fagenorn/argus --merge --delete-branch"
        good = self.run_guard(merge, cwd=argus)
        self.assertEqual(0, good.returncode, good.stderr)
        foreign = self.make_repo("git@github.com:someoneelse/tool.git")
        blocked = self.run_guard(
            "gh pr merge 1 --repo someoneelse/tool --merge --delete-branch", cwd=foreign)
        self.assertEqual(2, blocked.returncode)
        self.assertIn("outside standing authorization", blocked.stderr)

    def test_merge_guard_validates_other_fagenorn_repos(self):
        # The merge grammar is templated on the detected repository, so a
        # fagenorn-owned repo other than nix-config is validated, not deferred.
        elsewhere = self.make_repo("https://github.com/fagenorn/argus.git")
        allowed = self.run_guard(
            "gh pr merge 107 --repo fagenorn/argus --merge --delete-branch", cwd=elsewhere)
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        for command in (
            "gh pr merge 107 --repo fagenorn/argus --squash",
            "gh pr merge 107 --repo fagenorn/nix-config --merge --delete-branch",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=elsewhere)
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_merge_guard_still_blocks_inside_its_own_repository(self):
        for origin in (
            "https://github.com/fagenorn/nix-config.git",
            "git@github.com:fagenorn/nix-config.git",
        ):
            with self.subTest(origin=origin):
                result = self.run_guard(
                    "gh pr merge 1 --repo someone/else --merge --delete-branch",
                    cwd=self.make_repo(origin),
                )
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_merge_guard_fails_closed_when_repository_is_unknown(self):
        plain = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        for cwd in (plain, self.make_repo("https://example.invalid/x/y.git")):
            with self.subTest(cwd=str(cwd)):
                result = self.run_guard(
                    "gh pr merge 1 --repo someone/else --merge --delete-branch", cwd=cwd
                )
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_merge_guard_fails_closed_without_a_cwd(self):
        result = self.run_guard(
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch")
        self.assertEqual(2, result.returncode)
        self.assertIn("outside standing authorization", result.stderr)

    def test_branch_delete_guard_stays_global(self):
        elsewhere = self.make_repo("https://github.com/fagenorn/argus.git")
        blocked = self.invoke_command_in("git branch -d topic; true", elsewhere)
        self.assertEqual(2, blocked.returncode)
        self.assertIn("lifecycle guard: unsafe branch deletion:", blocked.stderr)
        allowed = self.invoke_command_in("git branch -d issue-30-safe", elsewhere)
        self.assertEqual(0, allowed.returncode, allowed.stderr)

    def test_unsafe_merge_shapes_fail_before_network(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        cases = (
            "gh pr merge --repo fagenorn/nix-config --merge --delete-branch",
            "gh pr merge topic --repo fagenorn/nix-config --merge --delete-branch",
            "gh pr merge https://github.com/fagenorn/nix-config/pull/1 --repo fagenorn/nix-config --merge --delete-branch",
            "gh pr merge 1 --repo someone/else --merge --delete-branch",
            "gh pr merge 1 -R fagenorn/nix-config --merge --delete-branch",
            "gh pr merge 1 --repo fagenorn/nix-config --admin --merge --delete-branch",
            "gh pr merge 1 --repo fagenorn/nix-config --squash --delete-branch",
            "gh pr merge 1 --repo fagenorn/nix-config --rebase --delete-branch",
            "gh pr merge 1 --repo fagenorn/nix-config --merge",
            "gh pr merge 1 --merge --repo fagenorn/nix-config --delete-branch",
            "gh pr merge $PR --repo fagenorn/nix-config --merge --delete-branch",
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch | true",
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "bad $HOME" --delete-branch',
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "bad `id`" --delete-branch',
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "bad\\path" --delete-branch',
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "bad "quote"" --delete-branch',
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "bad\nline" --delete-branch',
        )
        for command in cases:
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_merge_dependency_and_predicate_failures_block(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        command = (
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch"
        )
        guard_args = (
            "--gh-bin", str(self.fake_gh), "--child-timeout-seconds", "0.5",
        )
        cases = (
            ({"FAKE_PR_MODE": "nonzero"}, "PR lookup", "fake pr failure"),
            ({"FAKE_PR_MODE": "timeout"}, "PR lookup", None),
            ({"FAKE_PR_MODE": "invalid"}, "PR predicate", "parse error"),
            ({"FAKE_PR_JSON": '{"state":"OPEN","baseRefName":"main","url":"https://github.com/other/repo/pull/1"}'}, "PR predicate", None),
            ({"FAKE_PR_JSON": '{"state":"OPEN","baseRefName":"dev","url":"https://github.com/fagenorn/nix-config/pull/1"}'}, "PR predicate", None),
            ({"FAKE_PR_JSON": '{"state":"CLOSED","baseRefName":"main","url":"https://github.com/fagenorn/nix-config/pull/1"}'}, "PR predicate", None),
            ({"FAKE_PROTECTION_MODE": "nonzero"}, "protection lookup", "fake protection failure"),
            ({"FAKE_PROTECTION_MODE": "timeout"}, "protection lookup", None),
            ({"FAKE_PROTECTION_MODE": "invalid"}, "protection predicate", "parse error"),
            ({"FAKE_PROTECTION_JSON": '{"required_status_checks":{"contexts":[]},"enforce_admins":{"enabled":true}}'}, "protection predicate", None),
            ({"FAKE_PROTECTION_JSON": '{"required_status_checks":{"contexts":["Nix Eval"]},"enforce_admins":{"enabled":false}}'}, "protection predicate", None),
        )
        for env, reason, diagnostic in cases:
            with self.subTest(env=env):
                result = self.run_guard(command, cwd=repo, env=env, guard_args=guard_args)
                self.assertEqual(2, result.returncode)
                self.assertIn(f"lifecycle guard: {reason}", result.stderr)
                if diagnostic is not None:
                    self.assertIn(diagnostic, result.stderr)

    def test_merge_dependency_fixture_can_reach_acceptance(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        result = self.run_guard(
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch",
            cwd=repo,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_merge_accepts_the_exact_unset_token_prefix(self):
        # A resolved exhaustive credential-name list yields the merge prefix
        # `unset GITHUB_TOKEN && gh pr merge ...` so gh falls back to the
        # keyring credential; exactly that literal prefix is grammatical.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "unset GITHUB_TOKEN && gh pr merge 1 --repo fagenorn/nix-config "
            "--merge --delete-branch",
            "unset GITHUB_TOKEN && gh pr merge 1 --repo fagenorn/nix-config "
            '--merge --subject "feature (#30)" --delete-branch',
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_prefixed_merge_reaches_acceptance_on_the_integration_base(self):
        # The real-world shape that motivated the prefix: a nodocom ship-issue
        # merge onto the declared integration branch `dev`. The integration
        # base is exempt from the protection demand, so the protection stage is
        # poisoned here to prove the guard never even consults it.
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        result = self.run_guard(
            "unset GITHUB_TOKEN && gh pr merge 42 --repo elevenyellow/nodocom "
            "--merge --delete-branch",
            cwd=repo,
            env={"FAKE_PR_JSON":
                 '{"state":"OPEN","baseRefName":"dev","headRefName":"issue-42-topic",'
                 '"url":"https://github.com/elevenyellow/nodocom/pull/42"}',
                 "FAKE_PROTECTION_MODE": "nonzero"},
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_merge_protection_demand_follows_the_base_branch(self):
        # In a repository with a declared integration base, a PR into that base
        # merges without forge protection, while a PR into the default branch
        # still demands it — the exemption follows the base, not the repo.
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 7 --repo elevenyellow/nodocom --merge --delete-branch"
        dev_pr = {
            "FAKE_PROTECTION_MODE": "nonzero",
            "FAKE_PR_JSON": '{"state":"OPEN","baseRefName":"dev","headRefName":"issue-7-topic",'
                            '"url":"https://github.com/elevenyellow/nodocom/pull/7"}',
        }
        allowed = self.run_guard(merge, cwd=repo, env=dev_pr)
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        main_pr = {
            "FAKE_PROTECTION_MODE": "nonzero",
            "FAKE_PR_JSON": '{"state":"OPEN","baseRefName":"main","headRefName":"issue-7-topic",'
                            '"url":"https://github.com/elevenyellow/nodocom/pull/7"}',
        }
        blocked = self.run_guard(merge, cwd=repo, env=main_pr)
        self.assertEqual(2, blocked.returncode)
        self.assertIn("protection lookup failed", blocked.stderr)

    # ------------------------------------------------------------------
    # Release arm: the declared integration branch promoted into the default
    # branch. Its head is permanent, so the merge omits `--delete-branch`, and
    # the guard demands exactly that PR shape plus a fully green rollup.
    # ------------------------------------------------------------------

    RELEASE_PR = {
        "state": "OPEN",
        "baseRefName": "main",
        "headRefName": "dev",
        "url": "https://github.com/elevenyellow/nodocom/pull/1484",
        "statusCheckRollup": [
            {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SKIPPED"},
            {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "NEUTRAL"},
            {"__typename": "StatusContext", "state": "SUCCESS"},
        ],
    }

    def release_env(self, **overrides):
        pr = dict(self.RELEASE_PR)
        pr.update(overrides)
        # Protection is poisoned on purpose: the release arm must never consult it.
        return {"FAKE_PR_JSON": json.dumps(pr), "FAKE_PROTECTION_MODE": "nonzero"}

    def test_release_merge_omits_delete_branch_for_integration_into_default(self):
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        for command in (
            "gh pr merge 1484 --repo elevenyellow/nodocom --merge",
            "unset GITHUB_TOKEN && gh pr merge 1484 --repo elevenyellow/nodocom --merge",
            "unset GITHUB_TOKEN && gh pr merge 1484 --repo elevenyellow/nodocom --merge "
            '--subject "merge: dev — showcases, engine roll (dev → main)"',
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo, env=self.release_env())
                self.assertEqual(0, result.returncode, result.stderr)

    def test_release_merge_arm_requires_exactly_integration_into_default(self):
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 7 --repo elevenyellow/nodocom --merge"
        for head, base in (
            ("issue-7-topic", "main"),   # a feature branch into the default branch
            ("issue-7-topic", "dev"),    # a feature branch into the integration branch
            ("main", "dev"),             # the wrong way round
        ):
            with self.subTest(head=head, base=base):
                result = self.run_guard(
                    merge, cwd=repo, env=self.release_env(headRefName=head, baseRefName=base))
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn(
                    "--delete-branch may be omitted only when merging dev into main",
                    result.stderr,
                )
        # The feature arm is untouched: the same feature PR still merges into
        # the integration branch when it says --delete-branch.
        allowed = self.run_guard(
            merge + " --delete-branch", cwd=repo,
            env=self.release_env(headRefName="issue-7-topic", baseRefName="dev"))
        self.assertEqual(0, allowed.returncode, allowed.stderr)

    def test_release_merge_arm_needs_a_declared_integration_base(self):
        # Without a declared integration branch there is no permanent head to
        # spare; the arm is refused before any forge lookup (poisoned to prove it).
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "gh pr merge 1 --repo fagenorn/nix-config --merge",
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "x"',
            "unset GITHUB_TOKEN && gh pr merge 1 --repo fagenorn/nix-config --merge",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo, env={"FAKE_PR_MODE": "nonzero"})
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)
                self.assertIn("declared integration branch", result.stderr)

    def test_release_merge_arm_blocks_unless_every_check_is_green(self):
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 1484 --repo elevenyellow/nodocom --merge"
        green = self.RELEASE_PR["statusCheckRollup"]
        for rollup in (
            [],
            None,
            "green",
            [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}],
            [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "CANCELLED"}],
            [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "TIMED_OUT"}],
            [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}],
            [{"__typename": "StatusContext", "state": "PENDING"}],
            [{"__typename": "StatusContext", "state": "FAILURE"}],
            green + [{"__typename": "CheckRun", "status": "QUEUED", "conclusion": None}],
        ):
            with self.subTest(rollup=rollup):
                result = self.run_guard(
                    merge, cwd=repo, env=self.release_env(statusCheckRollup=rollup))
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("check rollup is not entirely green", result.stderr)
        absent = dict(self.RELEASE_PR)
        del absent["statusCheckRollup"]
        result = self.run_guard(
            merge, cwd=repo,
            env={"FAKE_PR_JSON": json.dumps(absent), "FAKE_PROTECTION_MODE": "nonzero"})
        self.assertEqual(2, result.returncode)
        self.assertIn("check rollup is not entirely green", result.stderr)

    def test_release_merge_arm_keeps_the_open_pr_predicate(self):
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 1484 --repo elevenyellow/nodocom --merge"
        for overrides in (
            {"state": "MERGED"},
            {"url": "https://github.com/other/repo/pull/1484"},
        ):
            with self.subTest(overrides=overrides):
                result = self.run_guard(merge, cwd=repo, env=self.release_env(**overrides))
                self.assertEqual(2, result.returncode)
                self.assertIn("PR predicate failed", result.stderr)

    def test_prefixed_merge_near_misses_fail_closed(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        merge = "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch"
        for command in (
            f"unset PATH && {merge}",                               # wrong variable
            f"unset GITHUB_TOKEN; {merge}",                         # wrong separator
            f"unset GITHUB_TOKEN &&{merge}",                        # missing space
            f"unset  GITHUB_TOKEN && {merge}",                      # doubled space
            f"unset GITHUB_TOKEN && unset GITHUB_TOKEN && {merge}", # doubled prefix
            f"unset GITHUB_TOKEN && {merge} && true",               # trailing chain
            f"true && unset GITHUB_TOKEN && {merge}",               # leading chain
            f"FOO=bar unset GITHUB_TOKEN && {merge}",               # leading assignment
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_credential_scrub_prefix_forms_and_wrapper_near_misses(self):
        """Issue 400 AC1, D1, D13: either scrub-prefix spelling reaches every verb's
        grammar; any other wrapper reaches the grammar too and is refused there."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        push = "git push origin issue-400-topic"
        merge = "gh pr merge 2342 --repo fagenorn/nix-config --merge --delete-branch"
        create = ('gh pr create --repo fagenorn/nix-config --base main '
                  '--head issue-400-topic --title "x" --body "y"')
        release = ('gh release create v1.2.3 --repo fagenorn/nix-config --verify-tag '
                   '--title "v1.2.3" --notes-file /tmp/n.md')
        for command in (
            f"env -u GITHUB_TOKEN {push}",
            "unset GH_TOKEN && git push -u origin issue-400-topic",
            f"env -u GITHUB_TOKEN {merge}",
            f"env -u GH_TOKEN {merge}",
            f"env -u GITHUB_TOKEN -u GH_TOKEN {merge}",
            f"unset GITHUB_TOKEN GH_TOKEN && {merge}",
            f"unset GH_TOKEN GITHUB_TOKEN && {merge}",
            f"env -u GH_TOKEN -u GITHUB_TOKEN {push}",
            f"true && env -u GH_TOKEN {push}",
            f"env -u GITHUB_TOKEN {create}",
            f"env -u GITHUB_TOKEN {release}",
            f"unset GH_TOKEN && {release}",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        push_grammar = "unsafe push: expected exactly git push [-u] origin <branch>"
        merge_grammar = "unsafe merge: command does not match the guarded merge grammar"
        for command, reason in (
            (f"env -u PATH {push}", push_grammar),
            (f"env FOO=1 {push}", push_grammar),
            (f"env -i {push}", push_grammar),
            (f"env -u GITHUB_TOKEN -i {push}", push_grammar),
            (f"env --unset=GITHUB_TOKEN {push}", push_grammar),
            (f"sudo -u x {push}", push_grammar),
            (f"env -u GITHUB_TOKEN -u GITHUB_TOKEN {push}", push_grammar),   # repeated name
            (f"env -uGITHUB_TOKEN {push}", push_grammar),                    # attached
            (f"env -u GITHUB_TOKEN -- {push}", push_grammar),
            (f"env env -u GITHUB_TOKEN {push}", push_grammar),               # second env
            (f"env -u GITHUB_TOKEN env {push}", push_grammar),
            (f"env -u GITHUB_TOKEN  {push}", push_grammar),                  # double space
            (f"env -u GITHUB_TOKEN {merge}; echo x", merge_grammar),
            (f"env -u GITHUB_TOKEN -u GITHUB_TOKEN {merge}", merge_grammar),
            (f"unset GITHUB_TOKEN GITHUB_TOKEN && {merge}", merge_grammar),
            (f"env  -u GITHUB_TOKEN {merge}", merge_grammar),
            (f"env -u GITHUB_TOKEN  {merge}", merge_grammar),
            ("env -u GITHUB_TOKEN git branch -d issue-400-topic",
             "unsafe branch deletion: expected exactly git branch -d <branch>"),
            ("unset GITHUB_TOKEN && git branch -d issue-400-topic",
             "unsafe branch deletion: forbidden raw command character"),
            # The wrapper's option argument is consumed, so `sh` is the command word.
            ("sudo -u root sh -c 'git push origin issue-400-topic'",
             "unsafe push: shell source passed to an evaluator cannot be validated"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: {reason}", result.stderr)

    def test_merge_lookups_drop_env_github_tokens(self):
        # Deterministic version of the fake gh's env check: inject both tokens
        # into the guard's own environment and require acceptance anyway.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        result = self.run_guard(
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch",
            cwd=repo,
            env={"GITHUB_TOKEN": "github_pat_fake", "GH_TOKEN": "gho_fake"},
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_safe_rendered_subject_can_reach_acceptance(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for subject in ("feature (#30) [guarded]*?~", "git branch -d"):
            with self.subTest(subject=subject):
                result = self.run_guard(
                    "gh pr merge 1 --repo fagenorn/nix-config --merge "
                    f'--subject "{subject}" --delete-branch',
                    cwd=repo,
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_unexpected_dependency_exception_blocks(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        missing_jq = Path(self.fixture_dir.name) / "missing-jq"
        result = self.run_guard(
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch",
            cwd=repo,
            guard_args=(
                "--gh-bin", str(self.fake_gh), "--jq-bin", str(missing_jq),
                "--child-timeout-seconds", "0.5",
            ),
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("lifecycle guard: unexpected failure:", result.stderr)

    # ------------------------------------------------------------------
    # Forge adapter arms (#124): the tag push and the release creation the
    # github-release profile invokes, plus the permanent-branch repair (#116 D5).
    # ------------------------------------------------------------------

    SPELLINGS = json.loads((Path(__file__).parent / "fixtures/forge-adapter-spellings.json")
                           .read_text(encoding="utf-8"))
    CANONICAL_SLUG = SPELLINGS["canonical"]["slug"]
    REPOSITORY_CLASSES = (  # (class, slug, authorized, env), D22
        ("default-only", "fagenorn/nix-config", True, {}),
        ("distinct-integration", "elevenyellow/nodocom", True, {}),
        ("protection-inaccessible", "fagenorn/nix-config", True, {"FAKE_PROTECTION_MODE": "nonzero"}),
        ("other-owner", "someone-else/nix-config", False, {}),
    )

    def tagged_repo(self, slug, tag="v1.2.3", annotated=True):
        repo = self.make_repo(f"git@github.com:{slug}.git")
        # Signing is switched off: a host's tag.gpgsign would turn the lightweight tag
        # into a signed annotated one and demand a message.
        identity = ["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
        subprocess.run([*identity, "commit", "--quiet", "--allow-empty", "-m", "init"],
                       cwd=repo, check=True, capture_output=True)
        argv = [*identity, "tag"]
        argv += ["-a", tag, "-m", "release"] if annotated else [tag]
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
        return repo

    def test_every_adapter_spelling_is_an_allowed_row(self):
        """AC4, D12: one fixture drives the adapter suite and this table."""
        for name, slug, authorized, env in self.REPOSITORY_CLASSES:
            repo = self.tagged_repo(slug)
            for row in self.SPELLINGS["rows"]:
                raw = row["raw"].replace(self.CANONICAL_SLUG, slug)
                with self.subTest(repository=name, row=row["id"]):
                    result = self.run_guard(raw, cwd=repo, env=env)
                    expect_allowed = authorized or row["kind"] == "read"
                    self.assertEqual(0 if expect_allowed else 2, result.returncode, result.stderr)

    # Guarded command shapes (#351): the forms ship-issue spells and the dressed
    # shapes agents reach for, from the fixture the shell-example suite also reads.
    SHAPES = json.loads((Path(__file__).parent / "fixtures/guarded-command-shapes.json")
                        .read_text(encoding="utf-8"))
    TOKEN_PREFIX = "unset GITHUB_TOKEN && "
    ENV_TOKEN_PREFIX = "env -u GITHUB_TOKEN "

    def shape_command(self, template):
        for placeholder, value in self.SHAPES["values"].items():
            template = template.replace(placeholder, value)
        return template

    def assert_shape_verdict(self, command, repo, label, verdict):
        result = self.run_guard(command, cwd=repo)
        self.assertEqual(verdict["exit"], result.returncode, (command, result.stderr))
        if verdict["exit"] == 2:
            self.assertIn(f"lifecycle guard: unsafe {label}:", result.stderr)
            self.assertIn(verdict["reason"], result.stderr)

    def test_every_guarded_command_shape_gets_its_verdict(self):
        """#351 AC3, D6: the skill's literal forms and the refused dressed shapes."""
        slug = self.SHAPES["values"]["<resolved-repository>"]
        repo = self.make_repo(f"git@github.com:{slug}.git")
        forms = {form["id"]: form for form in self.SHAPES["skill_forms"]}
        for form in forms.values():
            command = self.shape_command(form["template"])
            for variant, text in (("bare", command), ("prefixed", self.TOKEN_PREFIX + command),
                                  ("env_prefixed", self.ENV_TOKEN_PREFIX + command)):
                with self.subTest(form=form["id"], variant=variant):
                    self.assert_shape_verdict(text, repo, form["label"], form[variant])
        for shape in self.SHAPES["refused_shapes"]:
            command = (shape["before"] + self.shape_command(forms[shape["form"]]["template"])
                       + shape["after"])
            with self.subTest(shape=shape["id"]):
                self.assert_shape_verdict(
                    command, repo, shape["label"], {"exit": 2, "reason": shape["reason"]})

    def test_every_invocation_shape_gets_its_verdict(self):
        """Issue 400 D10: the guard-only invocation shapes, read from their one home."""
        slug = self.SHAPES["values"]["<resolved-repository>"]
        repo = self.make_repo(f"git@github.com:{slug}.git")
        for shape in self.SHAPES["invocation_shapes"]:
            command = self.shape_command(shape["template"]).replace(
                "<repository-root>", str(repo))
            with self.subTest(shape=shape["id"]):
                self.assert_shape_verdict(command, repo, shape["label"], shape["verdict"])

    def test_raw_text_sites_match_verb_words_in_order(self):
        """Issue 400 D5, D12: text the guard cannot tokenise as a command is refused
        when a verb's words occur in it in order, the first matched by basename."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command, label, reason in (
            ("sh -c 'git -C /tmp/x push origin issue-400-topic'", "push",
             self.EVALUATOR_REASON),
            ("eval git\\ push origin issue-400-topic", "push", self.EVALUATOR_REASON),
            ("bash -c 'gh --repo fagenorn/nix-config pr merge 1'", "merge",
             self.EVALUATOR_REASON),
            ('echo "unterminated ; git -C /tmp/x push origin issue-400-topic', "push",
             self.UNPARSED_REASON),
            ("env -S git push origin issue-400-topic", "push", self.SPLIT_STRING_REASON),
            ("env -u FOO -S 'gh release create v1.2.3'", "release creation",
             self.SPLIT_STRING_REASON),
            ("sh -c \"g''it push origin issue-400-topic\"", "push", self.EVALUATOR_REASON),
            ("eval g\\it push origin issue-400-topic", "push", self.EVALUATOR_REASON),
            ('env -S "gi\\t push origin issue-400-topic"', "push",
             self.SPLIT_STRING_REASON),
            # D5 accepts that words in order are enough, adjacent or not.
            ('sh -c "git log; echo push"', "push", self.EVALUATOR_REASON),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: unsafe {label}: {reason}", result.stderr)
        for command in ("sh -c 'git log --oneline'", "env -S 'git status'",
                        "eval 'git fetch origin'"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_tag_push_near_misses_are_refused(self):
        repo = self.tagged_repo("fagenorn/nix-config")
        lightweight = self.tagged_repo("fagenorn/nix-config", tag="v2.0.0", annotated=False)
        for command, cwd in (
                ("git push origin refs/tags/v2.0.0", lightweight),
                ("git push origin refs/tags/v1.2", repo),
                ("git push origin refs/tags/release-1", repo),
                ("git push origin refs/heads/v1.2.3", repo),
                ("git push origin +refs/tags/v1.2.3", repo),
                ("git push origin refs/tags/v1.2.3 extra", repo),
                ("git push --force origin refs/tags/v1.2.3", repo),
                ("git push origin refs/tags/v9.9.9", repo)):
            with self.subTest(command=command):
                self.assertEqual(2, self.run_guard(command, cwd=cwd).returncode)
        other = self.tagged_repo("someone-else/nix-config")
        self.assertEqual(2, self.run_guard("git push origin refs/tags/v1.2.3", cwd=other).returncode)

    def test_release_create_near_misses_are_refused(self):
        repo = self.tagged_repo("fagenorn/nix-config")
        base = 'gh release create v1.2.3 --repo fagenorn/nix-config --verify-tag --title "v1.2.3 — r" --notes-file /tmp/n.md'
        self.assertEqual(0, self.run_guard(base, cwd=repo).returncode)
        self.assertEqual(0, self.run_guard("unset GITHUB_TOKEN && " + base, cwd=repo).returncode)
        for command in (
                base.replace(" --verify-tag", ""),
                base.replace("--verify-tag --title", "--title").replace("/tmp/n.md", "/tmp/n.md --verify-tag"),
                base.replace("--verify-tag", "--target main"),
                base.replace("--repo fagenorn/nix-config", "--repo fagenorn/other"),
                base.replace('"v1.2.3 — r"', '"v1.2.3 $(id)"'),
                base.replace("/tmp/n.md", "notes.md"),
                base + "; true",
                "true; " + base,
                base + " && true",
                base.replace("create v1.2.3", "create 1.2.3"),
                # `gh release new` is gh's alias of `create`
                "gh release new v1.2.3 --repo someone-else/x --target main --draft",
                base.replace("release create", "release new")):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)

    def test_feature_arm_never_deletes_a_permanent_branch(self):
        """#116 D5: dev -> main and main -> dev both refuse --delete-branch."""
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 7 --repo elevenyellow/nodocom --merge --delete-branch"
        for head, base in (("dev", "main"), ("main", "dev")):
            with self.subTest(head=head, base=base):
                env = {"FAKE_PR_JSON": json.dumps({
                    "state": "OPEN", "baseRefName": base, "headRefName": head,
                    "url": "https://github.com/elevenyellow/nodocom/pull/7",
                    "statusCheckRollup": []})}
                result = self.run_guard(merge, cwd=repo, env=env)
                self.assertEqual(2, result.returncode)
                self.assertIn("permanent branch", result.stderr)

    def test_feature_arm_refuses_an_uncertain_head(self):
        """The head is the thing --delete-branch deletes: unreadable means refused."""
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 7 --repo elevenyellow/nodocom --merge --delete-branch"
        base = {"state": "OPEN", "baseRefName": "dev",
                "url": "https://github.com/elevenyellow/nodocom/pull/7", "statusCheckRollup": []}
        for label, extra in (("missing", {}), ("null", {"headRefName": None}),
                             ("empty", {"headRefName": ""}), ("number", {"headRefName": 7})):
            with self.subTest(head=label):
                env = {"FAKE_PR_JSON": json.dumps({**base, **extra}),
                       "FAKE_PROTECTION_MODE": "nonzero"}
                result = self.run_guard(merge, cwd=repo, env=env)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("cannot read the PR head branch", result.stderr)

    # ------------------------------------------------------------------
    # Policy trust split (issue 377) and derived rows (issue 126): the base
    # policy, the compiled file the hook reads, and the rows a registered
    # project is judged by.
    # ------------------------------------------------------------------

    COMPILED_ROW_SHAPES = {
        "derived_repositories is a list": {"derived_repositories": []},
        "derived key is not a slug": {"derived_repositories": {"nodocom": NODO_ROW}},
        "row is not an object": {"derived_repositories": {NODO: "dev"}},
        "row lacks evidence": {"derived_repositories": {
            NODO: {"default_branch": "main", "integration_branch": "dev"}}},
        "row has an extra member": {"derived_repositories": {NODO: {**NODO_ROW, "owner": "x"}}},
        "empty branch": {"derived_repositories": {NODO: {**NODO_ROW, "integration_branch": ""}}},
        "branch is not a ref name": {
            "derived_repositories": {NODO: {**NODO_ROW, "default_branch": "main; true"}}},
        "branch is not a string": {"derived_repositories": {NODO: {**NODO_ROW, "default_branch": None}}},
        "evidence is not an object": {"derived_repositories": {NODO: {**NODO_ROW, "evidence": []}}},
        "derivation is a list": {"derived_repositories": {NODO: NODO_ROW}, "derivation": []},
        "missing derivation": {"derived_repositories": {NODO: NODO_ROW}, "derivation": ABSENT},
        "an extra member": {"derived_repositories": {NODO: NODO_ROW}, "grants": []},
    }

    def test_built_base_policy_holds_exactly_the_five_trusted_members(self):
        """Issue 377 R1, R5; issue 384 D3: the store file holds the trusted members and no
        literal integration row, since every repository with one is a registered project."""
        self.assertEqual({"authorized_owners", "integration_bases", "git_bin", "gh_bin", "jq_bin"},
                         set(self.base_policy))
        self.assertEqual(["fagenorn"], self.base_policy["authorized_owners"])
        self.assertEqual({}, self.base_policy["integration_bases"])
        for member, name in (("git_bin", "git"), ("gh_bin", "gh"), ("jq_bin", "jq")):
            self.assertRegex(self.base_policy[member], rf"^/nix/store/[^/]+/bin/{name}$")
        source = Path(__file__).resolve().parents[1] / "home/common/claude-code/default.nix"
        text = source.read_text(encoding="utf-8")
        self.assertEqual([], [name for name in ("elevenyellow", "fagenorn/arcwave")
                              if name in text])

    def test_registered_hook_names_the_base_policy_compiled_policy_and_row_check(self):
        wrapper = self.guard.read_text(encoding="utf-8")
        self.assertRegex(wrapper, r'--base-policy /nix/store/\S+-claude-bash-lifecycle-guard-'
                                  r'base-policy\.json --policy /\S+/\.agents/state/guard/'
                                  r'policy\.json --derive-bin /nix/store/\S+-claude-guard-'
                                  r'row-check "\$@"\n')
        self.assertIn(f"--base-policy {BASE_POLICY_PATH} ", wrapper)
        row_check = Path(wrapper.split("--derive-bin ", 1)[1].split(" ", 1)[0])
        script = row_check.read_text(encoding="utf-8")
        self.assertRegex(script, r'\A#!/nix/store/\S+/bin/\S+ -p\nunset BASH_ENV ENV\n')
        self.assertRegex(script, r'export PATH="/nix/store/\S+-git-[^:"]+/bin:')
        self.assertRegex(script, r'exec /nix/store/\S+-agent-tools-guard-policy derive "\$@"\n')
        launcher = Path(script.split("exec ", 1)[1].split(" ", 1)[0])
        self.assertRegex(launcher.read_text(encoding="utf-8"), r'\A#!/nix/store/\S+/bin/\S+ -p\n')

    def test_a_compiled_policy_cannot_add_an_owner(self):
        """Issue 377 criterion 1, R1: an owner in the compiled policy grants nothing."""
        repo = self.make_repo("git@github.com:intruder/tool.git")
        for name, policy in (
            ("beside the rows", self.write_policy(authorized_owners=["intruder"])),
            ("as the seven-member shape", self.write_policy(
                **{**self.base_policy, "authorized_owners": ["fagenorn", "intruder"]})),
        ):
            args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
            for label, command in (
                ("push", "git push -u origin topic"),
                ("PR creation", 'gh pr create --repo intruder/tool --base main --head t '
                                '--title "x" --body "y"'),
                ("merge", "gh pr merge 7 --repo intruder/tool --merge --delete-branch"),
                ("release creation", 'gh release create v1.2.3 --repo intruder/tool '
                                     '--verify-tag --title "v1.2.3" --notes-file notes.md'),
            ):
                with self.subTest(policy=name, verb=label):
                    result = self.run_guard(command, cwd=repo, guard_args=args)
                    self.assertEqual(2, result.returncode, command)
                    self.assertIn(f"lifecycle guard: unsafe {label}: repository intruder/tool "
                                  "is outside standing authorization", result.stderr)

    def test_a_compiled_policy_cannot_substitute_the_tools(self):
        """Issue 377 criterion 2, R1: no program the compiled policy names is ever run.

        The fake `gh` comes from a fixture base policy, never `--gh-bin`: an override
        takes precedence over every policy value, so it would hide a guard that took
        `gh_bin` from the compiled policy."""
        base = self.write_base(gh_bin=str(self.fake_gh))
        markers = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        tools = {}
        for member in ("git_bin", "gh_bin", "jq_bin"):
            tool = markers / member
            tool.write_text(f"#!/bin/sh\ntouch {markers / (member + '.ran')}\nexit 0\n",
                            encoding="utf-8")
            tool.chmod(0o755)
            tools[member] = str(tool)
        tampered = self.write_policy(derived_repositories={NODO: NODO_ROW}, derivation={},
                                     **tools)
        repo = self.make_repo("git@github.com:fagenorn/tool.git")
        for command in ("git push -u origin topic",
                        "gh pr merge 7 --repo fagenorn/tool --merge --delete-branch"):
            with self.subTest(command=command):
                untampered = self.run_guard(command, cwd=repo,
                                            guard_args=("--base-policy", str(base)))
                self.assertEqual(0, untampered.returncode, untampered.stderr)
                result = self.run_guard(command, cwd=repo, guard_args=(
                    "--base-policy", str(base), "--policy", str(tampered)))
                self.assertEqual((0, untampered.stderr), (result.returncode, result.stderr))
        self.assertEqual([], sorted(path.name for path in markers.glob("*.ran")))

    def test_a_row_beside_a_literal_integration_base_is_refused(self):
        """Issue 377 D5: the compiled policy cannot recast a literal repository."""
        slug = "fagenorn/literal-fixture"
        base = self.write_base(integration_bases={slug: "dev"})
        policy = self.write_policy(derivation={}, derived_repositories={
            slug: {"default_branch": "trunk", "integration_branch": "release", "evidence": {}}})
        args = ("--gh-bin", str(self.fake_gh), "--base-policy", str(base),
                "--policy", str(policy))
        repo = self.make_repo(f"git@github.com:{slug}.git")
        for label, command in (
            ("push", "git push -u origin topic"),
            ("PR creation", f'gh pr create --repo {slug} --base release --head t '
                            '--title "x" --body "y"'),
            ("merge", f"gh pr merge 7 --repo {slug} --merge --delete-branch"),
        ):
            with self.subTest(verb=label):
                result = self.run_guard(command, cwd=repo, guard_args=args)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(
                    f"lifecycle guard: unsafe {label}: repository {slug} has both a literal "
                    "integration base and a derived policy row; repair: run claude-guard-policy",
                    result.stderr)
        literal_only = self.run_guard("git push -u origin topic", cwd=repo, guard_args=(
            "--gh-bin", str(self.fake_gh), "--base-policy", str(base)))
        self.assertEqual(0, literal_only.returncode, literal_only.stderr)

    def test_a_bad_compiled_policy_contributes_no_row(self):
        """Issue 377 D4, R4: the whole file is dropped and nothing the base allows is blocked."""
        fixtures = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        (fixtures / "directory").mkdir()
        (fixtures / "not-json.json").write_text("{", encoding="utf-8")
        unreadable = self.write_policy(derived_repositories={NODO: NODO_ROW}, derivation={})
        unreadable.chmod(0)
        # A FIFO with no writer would block a plain open, and /dev/zero never ends, so
        # each must be refused by its file type before a read; the oversized file is a
        # valid policy for Nodo padded past the 1 MiB cap with trailing whitespace.
        os.mkfifo(fixtures / "fifo.json")
        (fixtures / "zero.json").symlink_to("/dev/zero")
        oversized = self.write_policy(derived_repositories={NODO: NODO_ROW}, derivation={})
        with oversized.open("a", encoding="utf-8") as stream:
            stream.write(" " * (1 << 20))
        shapes = {
            "missing": fixtures / "absent.json",
            "a directory": fixtures / "directory",
            "unreadable": unreadable,
            "not JSON": fixtures / "not-json.json",
            "a FIFO": fixtures / "fifo.json",
            "a link to /dev/zero": fixtures / "zero.json",
            "over the size cap": oversized,
            "the seven-member shape": self.write_policy(
                **{**self.base_policy, "derived_repositories": {NODO: NODO_ROW},
                   "derivation": {}}),
            **{name: self.write_policy(**members)
               for name, members in self.COMPILED_ROW_SHAPES.items()},
        }
        literal = self.make_repo("git@github.com:fagenorn/tool.git")
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        for name, path in shapes.items():
            with self.subTest(policy=name):
                args = ("--gh-bin", str(self.fake_gh), "--policy", str(path))
                self.assertEqual(0, self.invoke_command("true", *args).returncode)
                allowed = self.run_guard("git push -u origin topic", cwd=literal, guard_args=args)
                self.assertEqual(0, allowed.returncode, allowed.stderr)
                refused = self.run_guard("git push -u origin topic", cwd=nodo, guard_args=args)
                self.assertEqual(2, refused.returncode)
                self.assertIn(f"lifecycle guard: unsafe push: repository {NODO} is outside "
                              "standing authorization; the compiled policy contributed no row: ",
                              refused.stderr)
                self.assertIn("; repair: run claude-guard-policy", refused.stderr)
        control = self.run_guard("git push -u origin topic", cwd=nodo)
        self.assertEqual(0, control.returncode, control.stderr)

    def test_a_bad_base_policy_blocks_every_call(self):
        """Issue 377 R4: the store file is an installation defect, so even `true` is refused."""
        fixtures = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        (fixtures / "not-json.json").write_text("{", encoding="utf-8")
        unreadable = self.write_base()
        unreadable.chmod(0)
        shapes = {
            "missing": fixtures / "absent.json",
            "a directory": fixtures,
            "unreadable": unreadable,
            "not JSON": fixtures / "not-json.json",
            "a missing member": self.write_base(jq_bin=ABSENT),
            "an extra member": self.write_base(grants=[]),
            "the #375 seven-member shape": self.write_base(derived_repositories={},
                                                           derivation=None),
            "owners is not a list": self.write_base(authorized_owners="fagenorn"),
            "an empty integration base": self.write_base(integration_bases={"a/b": ""}),
            "a relative tool": self.write_base(git_bin="git"),
        }
        for name, path in shapes.items():
            with self.subTest(base=name):
                result = self.invoke_command("true", "--base-policy", str(path))
                self.assertEqual(2, result.returncode, name)
                self.assertIn("lifecycle guard: invalid policy:", result.stderr)
        control = self.invoke_command("true", "--base-policy", str(self.write_base()))
        self.assertEqual(0, control.returncode, control.stderr)

    def test_a_command_with_no_repository_bound_verb_never_opens_the_compiled_policy(self):
        """Issue 377 section 4. The compiled path is a FIFO whose writer waits in `open`,
        which returns once any reader opens the FIFO, so an open by the guard shows as that
        `open` returning. The push is the control: a repository-bound verb opens it."""
        repo = self.make_repo("https://github.com/fagenorn/argus.git")
        for command, status, opens in (("true", 0, False),
                                       ("git branch -d issue-30-safe", 0, False),
                                       ("setsid x", 2, False),
                                       ("git push -u origin topic", 0, True)):
            with self.subTest(command=command):
                fifo = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "policy.json"
                os.mkfifo(fifo)
                opened = threading.Event()

                def wait_for_a_reader(fifo=fifo, opened=opened):
                    os.close(os.open(fifo, os.O_WRONLY))
                    opened.set()

                writer = threading.Thread(target=wait_for_a_reader, daemon=True)
                writer.start()
                try:
                    result = self.invoke_command_in(command, repo, "--gh-bin", str(self.fake_gh),
                                                    "--policy", str(fifo))
                    self.assertEqual(status, result.returncode, result.stderr)
                    self.assertEqual(opens, opened.wait(1))
                finally:
                    release = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
                    writer.join(5)
                    os.close(release)

    def test_base_policy_alone_loads_and_authorizes_no_nodo_verb(self):
        base = ("--gh-bin", str(self.fake_gh), "--policy", str(self.write_policy()))
        self.assertEqual(0, self.invoke_command("true", *base).returncode)
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        refused = self.run_guard("git push -u origin topic", cwd=repo, guard_args=base)
        self.assertEqual(2, refused.returncode)
        self.assertIn(f"repository {NODO} is outside standing authorization", refused.stderr)
        allowed = self.run_guard("git push -u origin topic", cwd=repo)
        self.assertEqual(0, allowed.returncode, allowed.stderr)

    def test_derived_row_never_authorizes_its_owner_s_other_repositories(self):
        """R2, D3: the row is keyed by the exact repository."""
        sibling = self.make_repo("git@github.com:elevenyellow/other.git")
        for label, command in (
            ("push", "git push -u origin topic"),
            ("PR creation", 'gh pr create --repo elevenyellow/other --base main --head t '
                            '--title "x" --body "y"'),
            ("merge", "gh pr merge 7 --repo elevenyellow/other --merge --delete-branch"),
            ("release creation", 'gh release create v1.2.3 --repo elevenyellow/other '
                                 '--verify-tag --title "v1.2.3" --notes-file notes.md'),
        ):
            with self.subTest(verb=label):
                result = self.run_guard(command, cwd=sibling)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: unsafe {label}: repository elevenyellow/other "
                              "is outside standing authorization", result.stderr)

    def test_derived_repository_is_refused_when_origin_head_differs_from_its_row(self):
        """R6, D8: every repository-bound verb, with a reason naming both branches."""
        for live, named in (("trunk", "trunk"), (None, "no branch")):
            repo = self.make_repo(f"git@github.com:{NODO}.git", default_branch=live)
            for label, command in (
                ("push", "git push -u origin topic"),
                ("PR creation", f'gh pr create --repo {NODO} --base dev --head t '
                                '--title "x" --body "y"'),
                ("merge", f"gh pr merge 7 --repo {NODO} --merge --delete-branch"),
                ("release creation", f'gh release create v1.2.3 --repo {NODO} '
                                     '--verify-tag --title "v1.2.3" --notes-file notes.md'),
            ):
                with self.subTest(origin_head=live, verb=label):
                    result = self.run_guard(command, cwd=repo)
                    self.assertEqual(2, result.returncode, command)
                    self.assertIn(
                        f"lifecycle guard: unsafe {label}: repository {NODO}: origin/HEAD "
                        f"names {named}, its derived policy row names main", result.stderr)
            # Branch deletion is not repository-bound and stays judged on its grammar.
            self.assertEqual(0, self.run_guard("git branch -d topic", cwd=repo).returncode)

    def test_literal_owner_does_not_bypass_the_derived_row_check(self):
        """R6, D8: a derived row is checked even when the owner is a literal authorized owner."""
        slug = "fagenorn/nix-config"
        policy = self.write_policy(derivation={}, derived_repositories={
            slug: {"default_branch": "main", "integration_branch": "main", "evidence": {}}})
        self.assertIn("fagenorn", self.base_policy["authorized_owners"])
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
        repo = self.make_repo(f"git@github.com:{slug}.git", default_branch="trunk")
        for label, command in (
            ("push", "git push -u origin topic"),
            ("PR creation", f'gh pr create --repo {slug} --base trunk --head t '
                            '--title "x" --body "y"'),
            ("merge", f"gh pr merge 7 --repo {slug} --merge --delete-branch"),
        ):
            with self.subTest(verb=label):
                result = self.run_guard(command, cwd=repo, guard_args=args)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(
                    f"lifecycle guard: unsafe {label}: repository {slug}: origin/HEAD "
                    "names trunk, its derived policy row names main", result.stderr)

    def test_single_branch_derived_row_keeps_the_default_branch_only_rule(self):
        policy = self.write_policy(derivation={}, derived_repositories={
            "acme/tool": {"default_branch": "main", "integration_branch": "main",
                          "evidence": {}}})
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
        env = self.rows_env({"acme/tool": {"default_branch": "main",
                                           "integration_branch": "main", "evidence": {}}})
        repo = self.make_repo("git@github.com:acme/tool.git")
        create = 'gh pr create --repo acme/tool --base {} --head t --title "x" --body "y"'
        self.assertEqual(
            0, self.run_guard(create.format("main"), cwd=repo, guard_args=args,
                              env=env).returncode)
        self.assertEqual(
            2, self.run_guard(create.format("dev"), cwd=repo, guard_args=args,
                              env=env).returncode)
        release_arm = self.run_guard(
            "gh pr merge 1 --repo acme/tool --merge", cwd=repo, guard_args=args,
            env={**env, "FAKE_PR_MODE": "nonzero"})
        self.assertEqual(2, release_arm.returncode)
        self.assertIn("declared integration branch", release_arm.stderr)

    def test_a_compiled_policy_round_trips_through_the_guard(self):
        """D10: the compiler's file is the guard's input, so the schema cannot drift."""
        world = GuardPolicyWorld(self)
        world.project("nodocom", NODO, integration_branch="dev", publication_free=True,
                      override=True)
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((0, [NODO]), (code, report["derived"]), stderr)
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output),
                "--derive-bin", str(world.row_check()), "--derive-timeout-seconds", "25")
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        allowed = self.run_guard(
            f'gh pr create --repo {NODO} --base dev --head issue-7-topic '
            '--title "x" --body "y"', cwd=repo, guard_args=args, timeout=60)
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        sibling = self.make_repo("git@github.com:elevenyellow/other.git")
        refused = self.run_guard("git push -u origin topic", cwd=sibling, guard_args=args,
                                 timeout=60)
        self.assertEqual(2, refused.returncode)
        self.assertIn("outside standing authorization", refused.stderr)
        forged = json.loads(world.output.read_text(encoding="utf-8"))
        forged["derived_repositories"]["acme/forged"] = {
            "default_branch": "main", "integration_branch": "main", "evidence": {}}
        forged_args = (*args, "--policy", str(self.write_policy(**forged)))
        forged_repo = self.make_repo("git@github.com:acme/forged.git")
        refused = self.run_guard("git push -u origin topic", cwd=forged_repo,
                                 guard_args=forged_args, timeout=60)
        self.assertEqual(2, refused.returncode)
        self.assertIn("repository acme/forged: the row check did not confirm its derived policy "
                      "row: refused (no registered project derives it); repair: run "
                      "claude-guard-policy", refused.stderr)

    def test_an_arcwave_shaped_project_is_judged_by_its_compiled_row(self):
        """Issue 384 D4: a registered project with integration branch `dev` needs no literal.
        Compiled against the built base policy it is derived, not refused, and the guard
        adjudicates its feature and release arms through the confirmed row."""
        slug = "fagenorn/arcwave"
        world = GuardPolicyWorld(self)
        world.project("arcwave", slug, integration_branch="dev", publication_free=True)
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((0, [slug], []), (code, report["derived"], report["refused"]), stderr)
        row = world.policy()["derived_repositories"][slug]
        self.assertEqual(("main", "dev"), (row["default_branch"], row["integration_branch"]))
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output),
                "--derive-bin", str(world.row_check()), "--derive-timeout-seconds", "25")
        repo = self.make_repo(f"git@github.com:{slug}.git")
        create = self.run_guard(
            f'gh pr create --repo {slug} --base dev --head issue-7-topic '
            '--title "x" --body "y"', cwd=repo, guard_args=args, timeout=60)
        self.assertEqual(0, create.returncode, create.stderr)
        feature_pr = json.dumps({"state": "OPEN", "baseRefName": "dev",
                                 "headRefName": "issue-7-topic",
                                 "url": f"https://github.com/{slug}/pull/7"})
        feature = self.run_guard(
            f"gh pr merge 7 --repo {slug} --merge --delete-branch", cwd=repo, guard_args=args,
            env={"FAKE_PR_JSON": feature_pr, "FAKE_PROTECTION_MODE": "nonzero"}, timeout=60)
        self.assertEqual(0, feature.returncode, feature.stderr)
        release = f"gh pr merge 1 --repo {slug} --merge"
        url = f"https://github.com/{slug}/pull/1"
        green = self.run_guard(release, cwd=repo, guard_args=args, timeout=60,
                               env=self.release_env(url=url))
        self.assertEqual(0, green.returncode, green.stderr)
        red = self.run_guard(release, cwd=repo, guard_args=args, timeout=60,
                             env=self.release_env(url=url, statusCheckRollup=[
                                 {"__typename": "CheckRun", "status": "COMPLETED",
                                  "conclusion": "FAILURE"}]))
        self.assertEqual(2, red.returncode, red.stderr)
        self.assertIn("check rollup is not entirely green", red.stderr)
        unrelated = self.make_repo("git@github.com:acme/unrelated.git")
        refused = self.run_guard("git push -u origin topic", cwd=unrelated, guard_args=args,
                                 timeout=60)
        self.assertEqual(2, refused.returncode)
        self.assertIn("repository acme/unrelated is outside standing authorization",
                      refused.stderr)

    def test_a_compiled_policy_loads_whatever_branch_names_the_fleet_carries(self):
        """The compiler and the loader agree on names: one the loader refuses costs its
        project a row, and every row the compiler does write loads."""
        world = GuardPolicyWorld(self)
        world.project("nodocom", NODO, integration_branch="dev", publication_free=True,
                      override=True)
        world.project("fixture/wide", "acme/wide_1.x", integration_branch="release/1.x_y-z")
        world.project("fixture/plus", "acme/plus", integration_branch="dev+ci")
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((1, ["acme/wide_1.x", NODO]), (code, report["derived"]), stderr)
        self.assertEqual([("fixture/plus", "name_unsupported")],
                         [(r["project_id"], r["reason_code"]) for r in report["refused"]])
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output),
                "--derive-bin", str(world.row_check()), "--derive-timeout-seconds", "25")
        loaded = self.invoke_command("true", "--policy", str(world.output))
        self.assertEqual(0, loaded.returncode, loaded.stderr)
        wide = self.make_repo("git@github.com:acme/wide_1.x.git")
        allowed = self.run_guard(
            'gh pr create --repo acme/wide_1.x --base release/1.x_y-z --head issue-7-topic '
            '--title "x" --body "y"', cwd=wide, guard_args=args, timeout=60)
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        plus = self.make_repo("git@github.com:acme/plus.git")
        refused = self.run_guard("git push -u origin topic", cwd=plus, guard_args=args,
                                 timeout=60)
        self.assertEqual(2, refused.returncode)
        self.assertIn("repository acme/plus is outside standing authorization", refused.stderr)

    FOUR_VERBS = (
        ("push", "git push -u origin topic"),
        ("PR creation", 'gh pr create --repo {slug} --base {base} --head t '
                        '--title "x" --body "y"'),
        ("merge", "gh pr merge 7 --repo {slug} --merge --delete-branch"),
        ("release creation", 'gh release create v1.2.3 --repo {slug} --verify-tag '
                             '--title "v1.2.3" --notes-file notes.md'),
    )

    def assert_unconfirmed(self, slug, why, base="main", exact=True, **run):
        """Every repository-bound verb on `slug` is refused for `why`; `exact=False` checks
        only the text up to `why`, for a reason that ends in an OS message."""
        repo = self.make_repo(f"git@github.com:{slug}.git")
        for label, template in self.FOUR_VERBS:
            with self.subTest(slug=slug, verb=label):
                result = self.run_guard(template.format(slug=slug, base=base), cwd=repo, **run)
                self.assertEqual(2, result.returncode, result.stderr)
                expected = (f"lifecycle guard: unsafe {label}: repository {slug}: the row check "
                            f"did not confirm its derived policy row: {why}")
                if exact:
                    expected += "; repair: run claude-guard-policy"
                self.assertIn(expected, result.stderr)

    def test_a_row_for_an_unregistered_repository_is_refused_at_use(self):
        """Issue 377 criterion 3, R2, R3."""
        slug = "acme/forged"
        policy = self.write_policy(derivation={}, derived_repositories={
            NODO: NODO_ROW,
            slug: {"default_branch": "main", "integration_branch": "main", "evidence": {}}})
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
        self.assert_unconfirmed(slug, "refused (no registered project derives it)",
                                guard_args=args)
        self.assert_unconfirmed(slug, "refused (fetch_failed)", guard_args=args,
                                env={"FAKE_DERIVE_MODE": "refused_code"})

    def test_a_row_whose_branches_differ_from_the_derivation_is_refused(self):
        """Issue 377 R3, D2: a forged integration branch never widens a target."""
        forged = self.write_policy(derivation={}, derived_repositories={
            NODO: {**NODO_ROW, "integration_branch": "evil"}})
        self.assert_unconfirmed(
            NODO, "it derives main and dev, the row names main and evil", base="evil",
            guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(forged)))
        literal = "fagenorn/tool"
        widened = self.write_policy(derivation={}, derived_repositories={
            literal: {"default_branch": "main", "integration_branch": "dev", "evidence": {}}})
        self.assert_unconfirmed(
            literal, "it derives main and main, the row names main and dev", base="dev",
            guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(widened)),
            env=self.rows_env({literal: {"default_branch": "main", "integration_branch": "main",
                                         "evidence": {}}}))

    def test_a_failing_row_check_refuses_with_no_fallback(self):
        """Issue 377 R2, D3."""
        for mode, why in (("unavailable", "unavailable (registry_invalid)"),
                          ("garbage", "unreadable report (exit 0)")):
            self.assert_unconfirmed(NODO, why, env={"FAKE_DERIVE_MODE": mode})
        absent = Path(self.fixture_dir.name) / "absent-row-check"
        self.assert_unconfirmed(NODO, "could not start (", exact=False, guard_args=(
            "--gh-bin", str(self.fake_gh), "--derive-bin", str(absent)))

    def test_a_row_check_past_its_bound_is_killed_with_its_process_group(self):
        """Issue 377 D6: a grandchild of the row check never outlives the verdict."""
        pidfile = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "pid"
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        result = self.run_guard(
            "git push -u origin topic", cwd=repo,
            guard_args=("--gh-bin", str(self.fake_gh), "--derive-timeout-seconds", "2"),
            env={"FAKE_DERIVE_MODE": "hang", "FAKE_DERIVE_PIDFILE": str(pidfile)})
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("the row check did not confirm its derived policy row: timed out",
                      result.stderr)
        self.assert_row_check_killed(pidfile)

    def test_the_invocation_deadline_bounds_the_row_check_and_every_later_child(self):
        """Issue 377 R6, D10, D12 (slow by design; the two cases share one 27 s wait).

        `hung`: a row check that outlives a 60-second bound is killed inside 27 s.
        `exhausted`: a row check that confirms Nodo's row 25 s in leaves less than one
        5-second child bound, so the first chained push is refused before its first
        child and the second is never judged."""
        pidfile = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "pid"
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        args = ("--gh-bin", str(self.fake_gh), "--derive-timeout-seconds", "60")
        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            hung = pool.submit(
                self.run_guard, "git push -u origin topic", cwd=repo, timeout=40,
                guard_args=args,
                env={"FAKE_DERIVE_MODE": "hang", "FAKE_DERIVE_PIDFILE": str(pidfile)})
            exhausted = pool.submit(
                self.run_guard, "git push -u origin topic-a && git push -u origin topic-b",
                cwd=repo, timeout=40, guard_args=args,
                env={"FAKE_DERIVE_MODE": "slow", "FAKE_DERIVE_UNTIL": str(time.time() + 25)})
            hung, exhausted = hung.result(), exhausted.result()
        elapsed = time.monotonic() - started
        self.assertEqual(2, hung.returncode, hung.stderr)
        self.assertIn("the row check did not confirm its derived policy row: timed out",
                      hung.stderr)
        self.assertEqual(2, exhausted.returncode, exhausted.stderr)
        self.assertIn("lifecycle guard: unsafe push: the 27-second invocation deadline leaves "
                      "too little time for the next check, so it was not started",
                      exhausted.stderr)
        self.assertEqual(1, exhausted.stderr.count("lifecycle guard:"), exhausted.stderr)
        self.assertGreater(elapsed, 20)
        self.assertLess(elapsed, 29)
        self.assert_row_check_killed(pidfile)

    def test_the_row_check_runs_once_and_only_for_a_repository_with_a_row(self):
        """Issue 377 section 3: no row, no check and no network read."""
        log = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "derive.log"
        env = {"FAKE_DERIVE_LOG": str(log)}
        literal = self.make_repo("git@github.com:fagenorn/tool.git")
        self.assertEqual(0, self.run_guard("git push -u origin topic", cwd=literal,
                                           env=env).returncode)
        self.assertFalse(log.exists())
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        result = self.run_guard("git push -u origin topic-a && git push -u origin topic-b",
                                cwd=nodo, env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"{NODO}\n", log.read_text(encoding="utf-8"))

    def test_hostile_interpreter_environment_is_ignored(self):
        # Each plant exits 0 before the guard can judge: a BASH_ENV file that the
        # wrapper's bash would source, a `json` package reached through PYTHONPATH,
        # and a .pth line reached through NIX_PYTHONPATH, which nixpkgs'
        # sitecustomize honours even under -I. Seeing any one would turn a refusal
        # into an allow, so the registered hook must ignore all three.
        hostile = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        (hostile / "bash_env").write_text("exit 0\n", encoding="utf-8")
        (hostile / "json").mkdir()
        (hostile / "json" / "__init__.py").write_text(
            "import os\nos._exit(0)\n", encoding="utf-8"
        )
        (hostile / "hostile.pth").write_text("import os; os._exit(0)\n", encoding="utf-8")
        result = self.invoke_command(
            "git branch -d -f topic",
            env={
                "BASH_ENV": str(hostile / "bash_env"),
                "PYTHONPATH": str(hostile),
                "NIX_PYTHONPATH": str(hostile),
            },
        )
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("lifecycle guard: unsafe branch deletion:", result.stderr)

    def test_the_row_check_never_sees_a_hostile_shell_environment(self):
        """Issue 377: a BASH_ENV file or an exported bash function that prints a forged
        `derived` report must not confirm a forged row. `built` is the store row check run
        over an empty fixture fleet; `plain bash` is a bash row check that would honour
        both, so it shows that the guard drops them from the row check's environment."""
        world = GuardPolicyWorld(self)
        wrapper = self.guard.read_text(encoding="utf-8")
        built = Path(wrapper.split("--derive-bin ", 1)[1].split(" ", 1)[0])
        bash = built.read_text(encoding="utf-8").splitlines()[0][2:].split()[0]
        plain = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "plain-bash-row-check"
        plain.write_text(f'#!{bash}\nexec {self.fake_derive} "$@"\n', encoding="utf-8")
        plain.chmod(0o755)
        slug = "acme/forged"
        row = {"default_branch": "main", "integration_branch": "main", "evidence": {}}
        report = json.dumps({"schema_version": 1, "repository": slug, "outcome": "derived",
                             "row": row, "refused": [], "cause": None})
        forge = f"printf '%s\\n' {shlex.quote(report)}; builtin exit 0"
        bash_env = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "bash_env"
        bash_env.write_text(forge + "\n", encoding="utf-8")
        policy = self.write_policy(derived_repositories={slug: row}, derivation={})
        repo = self.make_repo(f"git@github.com:{slug}.git")
        fleet = {name: world.env[name] for name in ("HOME", "GIT_CONFIG_GLOBAL",
                                                     "GIT_CONFIG_SYSTEM")}
        for name, derive_bin, env in (("built", built, fleet), ("plain bash", plain, {})):
            for plant in ({"BASH_ENV": str(bash_env)},
                          {"BASH_FUNC_exec%%": f"() {{ {forge}; }}"},
                          {"BASH_FUNC_unset%%": f"() {{ {forge}; }}"}):
                with self.subTest(row_check=name, plant=sorted(plant)[0]):
                    result = self.run_guard(
                        "git push -u origin topic", cwd=repo, env={**env, **plant}, timeout=60,
                        guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(policy),
                                    "--derive-bin", str(derive_bin),
                                    "--derive-timeout-seconds", "25"))
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn(f"lifecycle guard: unsafe push: repository {slug}: the row "
                                  "check did not confirm its derived policy row: ",
                                  result.stderr)


if __name__ == "__main__":
    unittest.main()
