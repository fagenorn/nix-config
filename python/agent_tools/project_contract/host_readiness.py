"""The readiness core: run every check that a registered project is ready on this host.

The checks, the refusal gate, the shared budget and the leashed child runner.
`run_checks` takes the resolved project and three injected seams (a child
runner, a PATH lookup and a clock) and returns ordered `Check` rows; nothing
here reads the fleet registry or prints.

The readiness checks
--------------------

Check ids, in the order `run_checks` returns them:

1. `checkout`: a clean clone of the integration branch from the project's
   `origin`, made in the scratch directory.
2. `verification <id>` for each id of the workflow's verification list, run in
   the clone.
3. `commit-hook`: one empty probe commit in the clone, under the registered
   checkout's commit hooks.
4. The release rows, by the release capability's state: `unsupported` gives one
   passing `release` row; `blocked` gives a failing `release` row naming the
   reason, then the rows below; `available` gives the rows below. They are
   `release-command` (the command is on PATH), then for each release profile
   `release-profile <p>` (inspection, admissibility and adapter executables),
   `release-preview <p>` (a read-only preview with no candidate),
   `release-login <p> <handle>` (one per credential handle) and
   `release-link <p> <node>` (one per railway node).

Every check runs even after an earlier one fails. A check that needs the clone
fails with `no clean checkout of <branch>` when the clone failed.

`render` writes one line per check: `pass <id>`, `pass <id>: <detail>` or
`fail <id>: <detail>`. `exit_code` is 0 when nothing failed, 3 when every
failed check was ended by the budget, and 1 otherwise.

Limits. The clone has 600 s, a verification command 3600 s, the probe commit
120 s, a release child 120 s and a probe child 30 s. An optional budget gives
every child one shared deadline: a child's limit is the smaller of its own and
the time left, and a child ended by the budget, a child the budget left no time
for, and a check that failed only because the clone failed that way are marked
`spent`.

What is refused. Every child passes `refusal` before it starts. A child whose
argv would run a declared production command (a read-only command that properly
extends it lifts the match, as the lifecycle guard lifts it), or a
`release transaction` verb other than `status` and a `--read-only` `preview`,
is not run, and its check fails with `<reason>; not run`. A word of shell text
is split into commands and read the same way; text that cannot be read is
refused whole.

The probe commit proves itself: after the commit the clone's HEAD must have the
old HEAD as its parent and the probe subject (D6). The release preview carries
`--read-only` and no candidate, so it never takes the land lock (D7). A child
runs leashed, so its whole process tree ends at its limit, with no forge token
and no Git repository redirect in its environment (D10).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple, Sequence

from agent_tools.project_contract import adopt_apply, adopt_inspection
from agent_tools.release import codesigned_artifact_adapter, railway_deploy_adapter
from agent_tools.system.siblings import sibling_argv

CLONE_LIMIT_SECONDS = 600
VERIFICATION_LIMIT_SECONDS = 3600
COMMIT_HOOK_LIMIT_SECONDS = 120
RELEASE_LIMIT_SECONDS = 120
PROBE_LIMIT_SECONDS = 30

COMMIT_PROBE_MESSAGE = "host-readiness probe"
COMMIT_HOOKS = ("pre-commit", "prepare-commit-msg", "commit-msg")

TOKEN_ENV = ("GH_TOKEN", "GITHUB_TOKEN")
GIT_REDIRECT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                    "GIT_NAMESPACE", "GIT_PREFIX")
STRIPPED_ENV = TOKEN_ENV + GIT_REDIRECT_ENV

SHELL_CHARACTERS = frozenset(";&|()<>$`")
OPERATOR_CHARACTERS = frozenset(";&|()")
BUDGET_EXIT = 3
READ_DEPTH = 4
UNREADABLE = "would run shell text it cannot read"
DETAIL_LIMIT = 200


class Completed(NamedTuple):
    """One finished child. `returncode` is None when the limit ended it."""

    returncode: int | None
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], Path, float], Completed]


class Check(NamedTuple):
    """One line of the report. A fail always has a detail."""

    id: str
    passed: bool
    detail: str | None
    spent: bool = False


class LoginProbe(NamedTuple):
    """The command that shows a credential class is logged in, and its optional judge."""

    argv: tuple[str, ...]
    cause: str
    judge: Callable[[str, Sequence[Mapping[str, Any]]], str | None] | None


def _signing_judge(stdout: str, configs: Sequence[Mapping[str, Any]]) -> str | None:
    """The code-signing adapter's own identity rule, applied to each node's configuration."""
    for config in configs:
        problem = codesigned_artifact_adapter.identity_choice(stdout, config, os.environ)[1]
        if problem is not None:
            return problem
    return None


LOGIN_PROBES: Mapping[str, LoginProbe] = {
    "gh_keyring": LoginProbe(
        ("gh", "auth", "status", "--hostname", "github.com"),
        "gh is not logged in to github.com; run gh auth login", None),
    "gh_cli": LoginProbe(
        ("gh", "auth", "status", "--hostname", "github.com"),
        "gh is not logged in to github.com; run gh auth login", None),
    "railway_cli": LoginProbe(
        ("railway", "whoami"),
        "railway is not logged in; run railway login in the project's dev shell", None),
    "codesigning_identity": LoginProbe(
        ("security", "find-identity", "-v", "-p", "codesigning"),
        "the code-signing identities could not be listed", _signing_judge),
    "gui_session": LoginProbe(
        ("launchctl", "print", f"gui/{os.getuid()}"),
        "this user has no GUI session", None),
}


def _basename(word: str) -> str:
    return os.path.basename(word)


def _split_shell_text(text: str) -> list[list[str]] | None:
    """The commands of shell text split at its operators, or None when it cannot be read."""
    if "$(" in text or "`" in text:
        return None
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    commands: list[list[str]] = [[]]
    for token in tokens:
        if set(token) <= OPERATOR_CHARACTERS:
            commands.append([])
        else:
            commands[-1].append(token)
    return [command for command in commands if command]


def _is_shell_text(word: str) -> bool:
    return any(c.isspace() or c in SHELL_CHARACTERS for c in word)


def _commands(argv: Sequence[str], depth: int) -> list[list[str]] | None:
    """`argv` and the commands of every shell-text word in it, or None when one is unreadable."""
    found = [list(argv)]
    for word in argv:
        if not _is_shell_text(word):
            continue
        if depth >= READ_DEPTH:
            return None
        parts = _split_shell_text(word)
        if parts is None:
            return None
        for part in parts:
            inner = _commands(part, depth + 1)
            if inner is None:
                return None
            found.extend(inner)
    return found


def _verb(argv: Sequence[str]) -> list[str]:
    return [_basename(argv[0]), *argv[1:]]


def _occurs_in_order(words: Sequence[str], needed: Sequence[str]) -> bool:
    position = 0
    for word in words:
        if position < len(needed) and word == needed[position]:
            position += 1
    return position == len(needed)


def _lifted(run: Sequence[str], verb: Sequence[str], read_only: Sequence[Sequence[str]]) -> bool:
    """True when a read-only verb that properly extends `verb` begins `run` (the guard's rule)."""
    return any(
        len(each) > len(verb) and list(each[:len(verb)]) == list(verb)
        and len(run) >= len(each) and _basename(run[0]) == each[0]
        and list(run[1:len(each)]) == list(each[1:])
        for each in read_only)


def _production_reason(words: Sequence[str], snapshot: Mapping, commands: Sequence[list[str]]) -> str | None:
    production = snapshot.get("production") or {}
    if production.get("status") != "declared":
        return None
    bound = snapshot["bindings"]["commands"]
    read_only = [_verb(bound[name]["argv"])
                 for name in production["read_only"]["commands"] if name in bound]
    for name in production["changes"]["commands"]:
        if name not in bound:
            continue
        verb = _verb(bound[name]["argv"])
        for each in commands:
            for i, word in enumerate(each):
                if (_basename(word) == verb[0] and _occurs_in_order(each[i + 1:], verb[1:])
                        and not _lifted([_basename(each[i]), *each[i + 1:]], verb, read_only)):
                    return f"would run production command {name}"
    return None


def _release_reason(commands: Sequence[list[str]]) -> str | None:
    for each in commands:
        for i, word in enumerate(each):
            if _basename(word) != "release" and word != "agent_tools.release.release":
                continue
            for j in range(i + 1, len(each)):
                if each[j] != "transaction":
                    continue
                verb = each[j + 1] if j + 1 < len(each) else None
                if verb == "status":
                    break
                if verb == "preview":
                    if "--read-only" in each[j + 2:]:
                        break
                    return "would run release transaction preview without --read-only"
                return f"would run release transaction {verb or 'nothing'}"
    return None


def refusal(argv: Sequence[str], snapshot: Mapping) -> str | None:
    """Why `argv` must not run: a declared production command, a release run, or shell text
    that cannot be read. None when it may run."""
    commands = _commands(argv, 0)
    if commands is None:
        return UNREADABLE
    commands = [[_basename(w) if i == 0 else w for i, w in enumerate(each)] for each in commands]
    return _production_reason(commands[0], snapshot, commands) or _release_reason(commands)


def render(checks: Sequence[Check]) -> str:
    """One line per check."""
    lines = []
    for check in checks:
        if not check.passed:
            lines.append(f"fail {check.id}: {check.detail}\n")
        elif check.detail:
            lines.append(f"pass {check.id}: {check.detail}\n")
        else:
            lines.append(f"pass {check.id}\n")
    return "".join(lines)


def exit_code(checks: Sequence[Check]) -> int:
    """0 when nothing failed, `BUDGET_EXIT` when only the budget failed, else 1."""
    failed = [check for check in checks if not check.passed]
    if not failed:
        return 0
    return BUDGET_EXIT if all(check.spent for check in failed) else 1


def leashed_run(argv: Sequence[str], cwd: Path, timeout: float) -> Completed:
    """Run `argv` leashed, with no forge token and no Git redirect in its environment."""
    env = {name: value for name, value in os.environ.items() if name not in STRIPPED_ENV}
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            code: int | None = adopt_apply.run_leashed(
                list(argv), cwd=str(cwd), env=env, stdout=out, stderr=err, timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
        except OSError as error:
            return Completed(127, "", f"{argv[0]} cannot start: {error.strerror or error}")
        out.seek(0)
        err.seek(0)
        return Completed(code, out.read().decode("utf-8", errors="replace"),
                         err.read().decode("utf-8", errors="replace"))


class _Failure(NamedTuple):
    detail: str
    spent: bool = False


def _last_line(done: Completed) -> str:
    for text in (done.stderr, done.stdout):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return lines[-1][:DETAIL_LIMIT]
    return ""


def _exited(what: str, done: Completed) -> str:
    last = _last_line(done)
    return f"{what} exited {done.returncode}" + (f": {last}" if last else "")


def _refused(stdout: str) -> tuple[str, str] | None:
    """The code and detail of a refusal printed as JSON, in either of its two shapes."""
    try:
        document = json.loads(stdout)
    except ValueError:
        return None
    error = document.get("error") if isinstance(document, dict) else None
    if not isinstance(error, dict) or not isinstance(error.get("code"), str):
        return None
    if isinstance(error.get("detail"), str):
        return error["code"], error["detail"]
    violations = error.get("violations")
    if isinstance(violations, list):
        return error["code"], "; ".join(
            v["message"] for v in violations
            if isinstance(v, dict) and isinstance(v.get("message"), str))
    return None


def _document(stdout: str) -> Any:
    try:
        return json.loads(stdout)
    except ValueError:
        return None


class _Run:
    """One readiness run: the snapshot, the seams and the budget's deadline."""

    def __init__(self, snapshot: Mapping, scratch: Path, run: Runner,
                 on_path: Callable[[str], bool], clock: Callable[[], float],
                 budget: float | None) -> None:
        self.snapshot = snapshot
        self.scratch = scratch
        self.run = run
        self.on_path = on_path
        self.clock = clock
        self.budget = budget
        self.deadline = clock() + budget if budget is not None else 0.0
        self.root = Path(snapshot["project"]["root"])
        self.clone = scratch / "checkout"
        self.commands = snapshot["bindings"]["commands"]
        self.vcs = snapshot["bindings"]["vcs"]
        self.branch = self.vcs["integration_branch"]
        self.checkout_failure: _Failure | None = None

    def child(self, argv: Sequence[str], cwd: Path, limit: float,
              what: str | None = None) -> Completed | _Failure:
        """Run one child through the refusal gate and the budget."""
        reason = refusal(argv, self.snapshot)
        if reason is not None:
            return _Failure(f"{reason}; not run")
        effective, limited = limit, False
        if self.budget is not None:
            left = self.deadline - self.clock()
            if left <= 0:
                return _Failure(f"the run's budget of {int(self.budget)} s is spent; not run", True)
            if left < limit:
                effective, limited = left, True
        done = self.run(argv, cwd, effective)
        if done.returncode is None:
            name = what or shlex.join(argv)
            if limited:
                return _Failure(
                    f"{name} did not finish within the run's budget of {int(self.budget)} s", True)
            return _Failure(f"{name} did not finish within {int(limit)} s")
        return done

    def rows(self) -> list[Check]:
        checks = [self.checkout()]
        for name in self.snapshot["bindings"]["workflow"]["verification"]:
            checks.append(self.verification(name))
        checks.append(self.commit_hook())
        checks.extend(self.release_rows())
        return checks

    # -- the clean checkout ------------------------------------------------

    def checkout(self) -> Check:
        failure = self._clone()
        self.checkout_failure = failure
        if failure is None:
            return Check("checkout", True, None)
        return Check("checkout", False, failure.detail, failure.spent)

    def _clone(self) -> _Failure | None:
        url = self.child(["git", "-C", str(self.root), "remote", "get-url", "origin"],
                         self.root, PROBE_LIMIT_SECONDS)
        if isinstance(url, _Failure):
            return url
        if url.returncode != 0 or not url.stdout.strip():
            return _Failure("the project has no origin remote")
        what = f"git clone of {self.branch}"
        done = self.child(
            ["git", "clone", "--quiet", "--no-tags", "--single-branch", "--branch", self.branch,
             "--", url.stdout.strip(), str(self.clone)],
            self.scratch, CLONE_LIMIT_SECONDS, what)
        if isinstance(done, _Failure):
            return done
        if done.returncode != 0:
            return _Failure(_exited(what, done))
        return None

    def _no_checkout(self, check_id: str) -> Check:
        return Check(check_id, False, f"no clean checkout of {self.branch}",
                     self.checkout_failure.spent)

    def _contained(self, directory: str) -> tuple[Path | None, str]:
        """The clone's counterpart of a registered directory, and its relative name."""
        try:
            relative = Path(directory).relative_to(self.root)
        except ValueError:
            return None, directory
        return adopt_inspection.contained_path(self.clone, str(relative)), str(relative)

    # -- verification ------------------------------------------------------

    def verification(self, name: str) -> Check:
        check_id = f"verification {name}"
        if self.checkout_failure is not None:
            return self._no_checkout(check_id)
        entry = self.commands[name]
        cwd, relative = self._contained(entry["cwd"])
        if cwd is None:
            return Check(check_id, False,
                         f"its directory {relative} is not inside the clean checkout; not run")
        done = self.child(entry["argv"], cwd, VERIFICATION_LIMIT_SECONDS)
        if isinstance(done, _Failure):
            return Check(check_id, False, done.detail, done.spent)
        if done.returncode != 0:
            return Check(check_id, False, _exited(shlex.join(entry["argv"]), done))
        return Check(check_id, True, None)

    # -- the commit hooks --------------------------------------------------

    def commit_hook(self) -> Check:
        check_id = "commit-hook"
        if self.checkout_failure is not None:
            return self._no_checkout(check_id)
        problem = self._carry_hooks()
        if problem is not None:
            return Check(check_id, False,
                         f"the commit hooks of {self.root} could not be read: {problem.detail}",
                         problem.spent)
        head = self.child(["git", "-C", str(self.clone), "rev-parse", "HEAD"],
                          self.clone, PROBE_LIMIT_SECONDS)
        if isinstance(head, _Failure):
            return Check(check_id, False, head.detail, head.spent)
        if head.returncode != 0:
            return Check(check_id, False, _exited("git rev-parse HEAD", head))
        base = head.stdout.strip()
        failure = self._probe_commit()
        if failure is not None:
            return Check(check_id, False, failure.detail, failure.spent)
        proof = self.child(["git", "-C", str(self.clone), "log", "-1", "--format=%P%n%s"],
                           self.clone, PROBE_LIMIT_SECONDS)
        if isinstance(proof, _Failure):
            return Check(check_id, False, proof.detail, proof.spent)
        if proof.returncode != 0 or proof.stdout.splitlines() != [base, COMMIT_PROBE_MESSAGE]:
            return Check(check_id, False, "the probe commit exited 0 but made no commit")
        return Check(check_id, True, None)

    def _carry_hooks(self) -> _Failure | None:
        """Give the clone the registered checkout's commit hooks."""
        read = ["git", "-C", str(self.root), "config", "--local", "--get", "core.hooksPath"]
        configured = self.child(read, self.root, PROBE_LIMIT_SECONDS)
        if isinstance(configured, _Failure):
            return configured
        if configured.returncode == 0:
            path = configured.stdout.strip()
            done = self.child(
                ["git", "-C", str(self.clone), "config", "--local", "core.hooksPath", path],
                self.clone, PROBE_LIMIT_SECONDS)
            if isinstance(done, _Failure):
                return done
            return None if done.returncode == 0 else _Failure(_exited(
                f"git config core.hooksPath {path}", done))
        if configured.returncode != 1:
            return _Failure(_exited(shlex.join(read), configured))
        common = self.child(
            ["git", "-C", str(self.root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            self.root, PROBE_LIMIT_SECONDS)
        if isinstance(common, _Failure):
            return common
        if common.returncode != 0:
            return _Failure(_exited("git rev-parse --git-common-dir", common))
        hooks = Path(common.stdout.strip()) / "hooks"
        try:
            for name in COMMIT_HOOKS:
                source = hooks / name
                if source.is_file() and os.access(source, os.X_OK):
                    target = self.clone / ".git" / "hooks" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        except OSError as error:
            return _Failure(f"{error.strerror or error}")
        return None

    def _probe_commit(self) -> _Failure | None:
        environment = self.vcs.get("commit", {}).get("environment")
        prefix: list[str] = []
        cwd = self.clone
        if environment:
            entry = self.commands[environment]
            prefix = list(entry["argv"])
            found, relative = self._contained(entry["cwd"])
            if found is None:
                return _Failure(f"the commit environment's directory {relative} "
                                "is not inside the clean checkout; not run")
            cwd = found
        argv = [*prefix, "git", "-C", str(self.clone), "commit", "--allow-empty", "--quiet",
                "-m", COMMIT_PROBE_MESSAGE]
        done = self.child(argv, cwd, COMMIT_HOOK_LIMIT_SECONDS, "the probe commit")
        if isinstance(done, _Failure):
            return done
        if done.returncode != 0:
            return _Failure(_exited("the probe commit", done))
        return None

    # -- the release rows --------------------------------------------------

    def release_rows(self) -> list[Check]:
        release = self.snapshot["capabilities"]["release"]
        state = release["state"]
        if state == "unsupported":
            return [Check("release", True, "the project declares no release profile")]
        rows: list[Check] = []
        if state == "blocked":
            rows.append(Check("release", False,
                              f"the release capability is blocked: {release['reason_code']}"))
        if self.on_path("release"):
            rows.append(Check("release-command", True, None))
        else:
            rows.append(Check("release-command", False, "the release command is not on PATH"))
        for profile in sorted({t["profile"] for t in self.snapshot["release"]["targets"]}):
            rows.extend(self.profile_rows(profile))
        return rows

    def _release_child(self, argv: Sequence[str]) -> Completed | _Failure:
        return self.child([*sibling_argv("release.release"), *argv], self.root, RELEASE_LIMIT_SECONDS)

    def profile_rows(self, profile: str) -> list[Check]:
        check, inspection = self.release_profile(profile)
        rows = [check, self.release_preview(profile)]
        if inspection is not None:
            bindings = inspection["bindings"]
            for handle in sorted(bindings["credentials"]):
                rows.append(self.release_login(profile, handle, inspection))
            for alias in sorted(bindings["adapters"]):
                if bindings["adapters"][alias]["adapter"] != "railway-deploy":
                    continue
                for node in sorted(bindings["adapters"][alias]["config"]):
                    rows.append(self.release_link(profile, node,
                                                  bindings["adapters"][alias]["config"][node]))
        return rows

    def release_profile(self, profile: str) -> tuple[Check, Mapping | None]:
        check_id = f"release-profile {profile}"
        argv = [*sibling_argv("release.release"), "profile", "inspect", profile,
                "--repo-root", str(self.root)]
        done = self.child(argv, self.root, RELEASE_LIMIT_SECONDS)
        if isinstance(done, _Failure):
            return Check(check_id, False, done.detail, done.spent), None
        if done.returncode != 0:
            refused = _refused(done.stdout)
            if refused is None:
                return Check(check_id, False, _exited(shlex.join(argv), done)), None
            code, detail = refused
            return Check(check_id, False, f"release profile inspect refused {code}"
                         + (f": {detail}" if detail else "")), None
        inspection = _document(done.stdout)
        if not isinstance(inspection, dict):
            return Check(check_id, False, f"{shlex.join(argv)} printed no readable inspection"), None
        conformance = inspection["conformance"]
        if not inspection["profile"]["admissible"]:
            reasons = ", ".join(sorted({f["reason"] for f in conformance["findings"]}))
            return Check(check_id, False, f"the profile is not admissible: {reasons}"), inspection
        missing = [f"adapter {alias} needs {name}, which is not on PATH"
                   for alias in sorted(conformance["adapters"])
                   for name, found in sorted(conformance["adapters"][alias]["executables"].items())
                   if found is False]
        if missing:
            return Check(check_id, False, "; ".join(missing)), inspection
        return Check(check_id, True, None), inspection

    def release_preview(self, profile: str) -> Check:
        check_id = f"release-preview {profile}"
        argv = [*sibling_argv("release.release"), "transaction", "preview", "--profile", profile,
                "--repo-root", str(self.root), "--read-only"]
        done = self.child(argv, self.root, RELEASE_LIMIT_SECONDS)
        if isinstance(done, _Failure):
            return Check(check_id, False, done.detail, done.spent)
        document = _document(done.stdout)
        if done.returncode == 0:
            resumed = isinstance(document, dict) and document.get("mode") == "resume"
            return Check(check_id, True, "a release is in flight; it was previewed read-only, "
                         "with no lock" if resumed else None)
        refused = _refused(done.stdout)
        if refused is None and done.returncode == 3 and isinstance(document, dict):
            refusal_object = document.get("refusal")
            if (isinstance(refusal_object, dict) and isinstance(refusal_object.get("code"), str)
                    and isinstance(refusal_object.get("detail"), str)):
                refused = refusal_object["code"], refusal_object["detail"]
        if refused is None:
            return Check(check_id, False, _exited(shlex.join(argv), done))
        code, detail = refused
        if code == "candidate_required":
            return Check(check_id, True, None)
        return Check(check_id, False, f"release transaction preview refused {code}"
                     + (f": {detail}" if detail else ""))

    def release_login(self, profile: str, handle: str, inspection: Mapping) -> Check:
        check_id = f"release-login {profile} {handle}"
        credential = inspection["bindings"]["credentials"][handle]
        klass = credential["class"]
        probe = LOGIN_PROBES.get(klass)
        if probe is None:
            return Check(check_id, False, f"no login check is defined for credential class {klass}")
        done = self.child(probe.argv, self.root, PROBE_LIMIT_SECONDS)
        if isinstance(done, _Failure):
            return Check(check_id, False, probe.cause if not done.spent else done.detail, done.spent)
        if done.returncode != 0:
            return Check(check_id, False, probe.cause)
        if probe.judge is None:
            return Check(check_id, True, None)
        nodes = inspection["bindings"]["adapters"][credential["adapter"]]["config"]
        problem = probe.judge(done.stdout, [nodes[node] for node in sorted(nodes)])
        return Check(check_id, problem is None, problem)

    def release_link(self, profile: str, node: str, config: Mapping[str, Any]) -> Check:
        check_id = f"release-link {profile} {node}"
        done = self.child(["railway", "status", "--json"], self.root, PROBE_LIMIT_SECONDS)
        if isinstance(done, _Failure):
            return Check(check_id, False, done.detail, done.spent)
        if done.returncode != 0:
            return Check(check_id, False, _exited("railway status --json", done))
        problem = railway_deploy_adapter.linkage_problem(_document(done.stdout), config)
        return Check(check_id, problem is None, problem)


def run_checks(snapshot: Mapping, scratch: Path, *, run: Runner, on_path: Callable[[str], bool],
               clock: Callable[[], float] = time.monotonic,
               budget: float | None = None) -> list[Check]:
    """Every readiness check for the resolved project, in order, whatever fails."""
    return _Run(snapshot, scratch, run, on_path, clock, budget).rows()
