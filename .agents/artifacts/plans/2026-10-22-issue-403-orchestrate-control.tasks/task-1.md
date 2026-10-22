# Task 1: `start`, the test world and the command row

**Files:**
- Create: `python/agent_tools/orchestrate_control.py`
- Create: `tests/orchestrate_world.py`
- Create: `tests/test_orchestrate_control.py`
- Modify: `lib/agent-tools.nix` (command table), `tests/test_agent_tools_launchers.py` (`LAUNCHER_FLOOR`), `justfile` (`agent-workflow-tests`), `python/README.md` (new section)

**Interfaces:**
- Consumes: `agent_tools.resolve_project.resolve(repo_root: str) -> dict` and `resolve_project.ContractError` (`.code`, `.repair_id`); `agent_tools.canonical.reject_duplicate_keys`, `reject_nonfinite_literal`.
- Produces (module `agent_tools.orchestrate_control`, used by Tasks 2–4):
  - `INVALID = "orchestrate-control: invalid invocation\n"`, `DETAIL_LIMIT = 300`, `TAIL_LIMIT = 120`, `ROUTE = "claude-code"`.
  - `class InvocationError(Exception)`.
  - `class Refusal(Exception)` with `__init__(self, step: str, detail: str, *, response: dict | None = None)` and attributes `step`, `detail`, `response`.
  - `@dataclass(frozen=True) class Bindings`: `project_root: str`, `max_parallel: int`, `attempt_budget_minutes: int`, `tracker_kind: str`, `tracker_cli: str`, `repo_slug: str`, `unset: tuple[str, ...]`, `worktree_root: str` (absolute, normalized), `worktree_prefix: str`.
  - `load_bindings(repo_root: str) -> Bindings`.
  - `strict_json(raw: bytes) -> object` (raises `ValueError`).
  - `run_child(step: str, argv: Sequence[str], *, stdin: bytes | None = None, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess`.
  - `why(done: subprocess.CompletedProcess) -> str`: `": <stderr tail>"` (whitespace collapsed, last `TAIL_LIMIT` characters) or `""`.
  - `validate_bytes(step: str, raw: bytes) -> bytes` and `workflow_response(step: str, *argv: str, stdin: bytes | None = None) -> dict`.
  - `tracker_env(bindings: Bindings) -> dict[str, str]`, `require_github(step: str, bindings: Bindings) -> None`.
  - `start(args: argparse.Namespace, done: list[str]) -> dict`, `main(argv: Sequence[str] | None = None) -> int`.
- Produces (`tests/orchestrate_world.py`): `OrchestrateWorld(case, *, mutate=None, claude_code="supported")` with `root`, `home`, `cwd`, `bin`, `state`, `env`, and methods `run`, `start`, `fault`, `clear_faults`, `listing`, `calls`, `ws`, `git`; constants `ROOT`, `INVALID`, `SLUG`, `TOKENS`.

**Invariants:**
- `start` runs `bindings`, `route`, `issues`, `bootstrap` in that order and stops at the first refusal; `completed_steps` lists exactly the steps that finished.
- An `unsupported` route prints `{"command":"start","outcome":"unsupported","route":<validated host_route>}`, exits 0 and runs no `init-run`.
- Explicit numbers keep the caller's order; a sweep is ascending; `--issue-set` joins the session's numbers with `-` in session order.
- No tracker-CLI child sees a name in `unset_before_invocation`.
- The command writes no file.

- [ ] **Step 1: Write the world**

`tests/orchestrate_world.py` (D26; prior art `tests/forge_world.py`, `tests/guard_policy_world.py`, `tests/test_sdd_gate.py`). Module docstring: what the world is, that shims log every call to `state/calls.jsonl` and consult `state/faults.json`, and that the fake `gh` exits 65 when `GITHUB_TOKEN` or `GH_TOKEN` is visible.

Constants: `ROOT = Path(__file__).resolve().parents[1]`; `SKILLS = ROOT / "home/common/agent-skills"`; `WORKFLOW = SKILLS / "scripts/workflow-state.py"`; `BUDGET = SKILLS / "scripts/artifact_budget.py"`; `POLICY = SKILLS / "artifact-budget-policy.json"`; `MANIFEST = SKILLS / "platform-manifest.json"`; `COMMAND = [sys.executable, "-m", "agent_tools.orchestrate_control"]`; `INVALID = "orchestrate-control: invalid invocation\n"`; `SLUG = "fagenorn/nix-config"`; `TOKENS = ("GITHUB_TOKEN", "GH_TOKEN", "ORCH_TEST_SENTINEL")` — the third name is one no implementation would know, so only honouring the bound `unset_before_invocation` list passes (D30).

The shared shim prelude, written verbatim (it is the fault wire every later task relies on). A shim's text is `PRELUDE.format(...)` followed by one tail; the tails are plain Python, never formatted:

```python
PRELUDE = '''#!{python}
import json, os, subprocess, sys
from pathlib import Path

state = Path({state!r})
tool = {tool!r}
script = {script!r}
argv = sys.argv[1:]
stdin = sys.stdin.buffer.read()
sub = argv[0] if argv else ""
log = state / "calls.jsonl"
earlier = [json.loads(line) for line in log.read_text("utf-8").splitlines()]
ordinal = 1 + sum(1 for c in earlier if c["tool"] == tool and c["argv"][:1] == [sub])
try:
    sent = json.loads(stdin) if stdin else None
except ValueError:
    sent = None
token = any(name in os.environ for name in {tokens!r})
with log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({{"tool": tool, "argv": argv, "stdin": stdin.decode("utf-8", "replace"),
                              "call": ordinal, "token_visible": token}}) + "\\n")

def field(name):
    return sent.get(name) if isinstance(sent, dict) else None

def matches(rule):
    return (rule["tool"] == tool and rule["sub"] == sub
            and rule.get("call", ordinal) == ordinal
            and ("issue" not in rule or rule["issue"] == field("issue"))
            and ("stdin_kind" not in rule or rule["stdin_kind"] == field("kind"))
            and ("argv_has" not in rule or rule["argv_has"] in argv))

rule = next((r for r in json.loads((state / "faults.json").read_text("utf-8")) if matches(r)), None)
if rule is not None and rule.get("passthrough"):
    sys.stdout.write(json.dumps(sent, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\\n")
    sys.exit(0)
if rule is not None:
    sys.stdout.write(rule["stdout"])
    sys.stderr.write(rule["stderr"])
    sys.exit(rule["exit"])
'''

REAL_TAIL = '''done = subprocess.run([sys.executable, script, *argv], input=stdin, capture_output=True)
sys.stdout.buffer.write(done.stdout)
sys.stderr.buffer.write(done.stderr)
sys.exit(done.returncode)
'''

GH_TAIL = '''if token:
    sys.stderr.write("gh: a token variable reached the child\\n")
    sys.exit(65)
world = json.loads((state / "gh.json").read_text("utf-8"))
if argv[:2] == ["issue", "list"]:
    flag = next(a for a in argv if a in ("--label", "--milestone"))
    key = flag + "=" + argv[argv.index(flag) + 1]
    if key in world["listings"]:
        sys.stdout.write(json.dumps([{"number": n} for n in world["listings"][key]]))
        sys.exit(0)
sys.stderr.write("fake gh: unregistered call\\n")
sys.exit(64)
'''
```

`class OrchestrateWorld`:
- `__init__(self, case, *, mutate=None, claude_code="supported")`: one `tempfile.TemporaryDirectory()` cleaned by `case.addCleanup`, resolved (`Path(...).resolve()`, macOS `/private`). Directories `home`, `bin`, `state`, `cwd` (empty; the command's working directory) and `project` (`self.root`). Home: copy `MANIFEST` to `home/.agents/share/platform-manifest.json`, symlink `POLICY` as `home/.agents/share/artifact-budget-policy.json`, write `home/.agents/share/host-declaration.json` = `{"schema_version": 1, "routes": {"claude-code": {"support": claude_code, "agent_slots": 64}, "codex": {"support": "unsupported"}}}` (with `"agent_slots": 64` only when `claude_code == "supported"`; an unsupported route carries only `support`). State: `calls.jsonl` empty, `faults.json` `[]`, `gh.json` `{"listings": {}, "issues": {}, "missing": [], "pulls": [], "forge_truncated": false}`. Shims: `bin/workflow-state` and `bin/artifact-budget` = `PRELUDE.format(python=sys.executable, state=str(state), tool=<name>, script=str(<WORKFLOW or BUDGET>), tokens=TOKENS) + REAL_TAIL`, `bin/gh` = `PRELUDE.format(..., tool="gh", script=None, ...) + GH_TAIL`; mode 0o755. Later tasks extend `GH_TAIL` only. `self.env = {**os.environ, "HOME": home, "PATH": f"{bin}{os.pathsep}{os.environ['PATH']}", "PYTHONPATH": str(ROOT / "python"), "PYTHONDONTWRITEBYTECODE": "1", "GITHUB_TOKEN": "harness-token", "GH_TOKEN": "harness-token", "ORCH_TEST_SENTINEL": "harness-token", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}`.
- The fixture project, as `guard_policy_world.commit_contract` builds one: `contract = json.loads((ROOT / ".agents/project.json").read_text("utf-8"))`; set `contract["bindings"]["tracker"]["credential_env"]["unset_before_invocation"] = list(TOKENS)`; call `mutate(contract)` when given; `git init --quiet -b main`, `git config commit.gpgsign false` (throwaway repo); write the contract, `.agents/instructions/bootstrap.md` (`# invariants\n`), a `keep.md` in every `bindings.paths.standards` and `rejections` entry, a file for every missing `bindings.paths.architecture` entry; run `python -m agent_tools.resolve_project write-projections --repo-root <root>` under `self.env` (raise `AssertionError` with its stdout on a non-zero exit); `git add -A`; `git commit --quiet -m fixture`.
- `run(self, *argv, stdin=None, cwd=None) -> subprocess.CompletedProcess`: `COMMAND + [str(a) for a in argv]`, `input=stdin`, `text=True`, `capture_output=True`, `cwd=cwd or self.cwd`, `env=self.env`, timeout 300.
- `start(self, *argv) -> dict`: `run("start", "--repo-root", self.root, *argv)`, `case.assertEqual(returncode, 0, stdout + stderr)`, return the parsed stdout.
- `fault(self, tool, sub, **rule)`: append `{"tool", "sub", **rule}` to `faults.json`; a rule without `passthrough` defaults `exit=0, stdout="", stderr=""`. `clear_faults(self)`: write `[]`.
- `listing(self, flag, value, numbers)`: set `gh.json["listings"][f"{flag}={value}"] = list(numbers)`.
- `calls(self, tool=None, sub=None) -> list[dict]`: the log entries, filtered.
- `ws(self, *argv, stdin=None) -> subprocess.CompletedProcess`: the source `workflow-state` run directly (`[sys.executable, WORKFLOW, *argv]`, bytes, `env=self.env`, not logged).
- `git(self, *args) -> str`: `git -C <root> <args>` under `self.env`, `check=True`, stdout text.

- [ ] **Step 2: Write the failing tests**

`tests/test_orchestrate_control.py`:

```python
"""`orchestrate-control` run from source (#403, spec seam 1; D26)."""
import json
import unittest

from .orchestrate_world import INVALID, SLUG, OrchestrateWorld


def report(done):
    return json.loads(done.stdout)


class StartTest(unittest.TestCase):
    def test_explicit_numbers_give_a_human_directed_session(self):
        world = OrchestrateWorld(self)
        out = world.start("14", "12")
        session = out["session"]
        self.assertEqual((out["command"], out["outcome"]), ("start", "ready"))
        self.assertEqual(set(out), {"command", "outcome", "session"})
        self.assertEqual(session, {"interface_version": 1, "run_id": session["run_id"],
                                   "issues": [14, 12], "human_directed": True,
                                   "source": {"kind": "explicit_user",
                                              "reference": "invocation:/orchestrate-issues 14 12"}})
        (init,) = world.calls("workflow-state", "init-run")
        self.assertEqual(init["argv"], ["init-run", "--repo-root", str(world.root),
                                        "--issue-set", "14-12"])
        self.assertEqual(world.calls("gh"), [])

    def test_a_label_or_milestone_gives_a_standing_repository_session(self):
        world = OrchestrateWorld(self)
        world.listing("--label", "agent:ready", [30, 12, 14])
        world.listing("--milestone", "v1", [7])
        label = world.start("--label", "agent:ready")["session"]
        milestone = world.start("--milestone", "v1")["session"]
        self.assertEqual((label["issues"], label["human_directed"], label["source"]),
                         ([12, 14, 30], False, {"kind": "standing_repository",
                                                "reference": "sweep:label:agent:ready"}))
        self.assertEqual((milestone["issues"], milestone["source"]["reference"]),
                         ([7], "sweep:milestone:v1"))
        self.assertEqual([c["argv"] for c in world.calls("gh")], [
            ["issue", "list", "--repo", SLUG, "--state", "open", "--label", "agent:ready",
             "--json", "number", "--limit", "1000"],
            ["issue", "list", "--repo", SLUG, "--state", "open", "--milestone", "v1",
             "--json", "number", "--limit", "1000"]])
        self.assertEqual([c["token_visible"] for c in world.calls("gh")], [False, False])

    def test_run_id_re_enters_the_run(self):
        world = OrchestrateWorld(self)
        first = world.start("12", "14")["session"]
        again = world.start("12", "14", "--run-id", first["run_id"])["session"]
        self.assertEqual(again, first)
        self.assertEqual(world.calls("workflow-state", "init-run")[-1]["argv"],
                         ["init-run", "--repo-root", str(world.root), "--run-id", first["run_id"]])

    def test_an_unsupported_route_prints_no_session(self):
        world = OrchestrateWorld(self, claude_code="unsupported")
        done = world.run("start", "--repo-root", world.root, "12")
        self.assertEqual(done.returncode, 0, done.stderr)
        out = report(done)
        self.assertEqual(set(out), {"command", "outcome", "route"})
        self.assertEqual((out["outcome"], out["route"]["kind"], out["route"]["support"]),
                         ("unsupported", "host_route", "unsupported"))
        self.assertEqual(world.calls("workflow-state", "init-run"), [])
        self.assertFalse((world.root / ".superpowers").exists())


class StartRefusalTest(unittest.TestCase):
    def refused(self, done, step, completed):
        self.assertEqual(done.returncode, 2, done.stderr)
        out = report(done)
        self.assertEqual(set(out), {"command", "outcome", "step", "detail",
                                    "completed_steps", "response"})
        self.assertEqual((out["command"], out["outcome"], out["step"], out["completed_steps"],
                          out["response"]), ("start", "refused", step, completed, None))
        self.assertLessEqual(len(out["detail"]), 300)
        self.assertNotIn("\n", out["detail"])
        return out

    def test_an_unresolvable_root_refuses_at_bindings(self):
        world = OrchestrateWorld(self)
        out = self.refused(world.run("start", "--repo-root", world.cwd, "12"), "bindings", [])
        self.assertIn("not_onboarded", out["detail"])
        self.assertIn("onboarding.contract.missing", out["detail"])

    def test_an_empty_or_capped_sweep_refuses_at_issues(self):
        world = OrchestrateWorld(self)
        world.listing("--label", "none", [])
        world.listing("--label", "many", range(1, 1001))
        for label in ("none", "many"):
            with self.subTest(label=label):
                self.refused(world.run("start", "--repo-root", world.root, "--label", label),
                             "issues", ["bindings", "route"])

    def test_duplicate_numbers_refuse_at_issues(self):
        world = OrchestrateWorld(self)
        self.refused(world.run("start", "--repo-root", world.root, "12", "12"),
                     "issues", ["bindings", "route"])

    def test_a_non_github_tracker_refuses_a_sweep_at_issues(self):
        world = OrchestrateWorld(self, mutate=lambda c: c["bindings"]["tracker"]
                                 .__setitem__("kind", "gitlab"))
        self.refused(world.run("start", "--repo-root", world.root, "--label", "x"),
                     "issues", ["bindings", "route"])
        self.assertEqual(world.calls("gh"), [])

    def test_a_set_too_long_for_the_issue_set_key_refuses_at_bootstrap(self):
        world = OrchestrateWorld(self)
        numbers = [str(n) for n in range(1000, 1030)]
        out = self.refused(world.run("start", "--repo-root", world.root, *numbers),
                           "bootstrap", ["bindings", "route", "issues"])
        self.assertTrue(out["detail"].endswith("invalid issue set"), out["detail"])


class StartInvocationTest(unittest.TestCase):
    def test_malformed_argv_is_an_invalid_invocation(self):
        world = OrchestrateWorld(self)
        cases = {"relative root": ["start", "--repo-root", "relative", "12"],
                 "no issues": ["start", "--repo-root", str(world.root)],
                 "numbers and label": ["start", "--repo-root", str(world.root), "12",
                                       "--label", "x"],
                 "label and milestone": ["start", "--repo-root", str(world.root),
                                         "--label", "x", "--milestone", "y"],
                 "not a number": ["start", "--repo-root", str(world.root), "12a"],
                 "zero": ["start", "--repo-root", str(world.root), "0"],
                 "no subcommand": []}
        for name, argv in cases.items():
            with self.subTest(name):
                done = world.run(*argv)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py` (timeout 900 s)
Expected: FAIL/ERROR — every run reports `No module named agent_tools.orchestrate_control`.

- [ ] **Step 4: Write the command**

`python/agent_tools/orchestrate_control.py`. Module docstring: the `start` usage line, its four steps, the ready, unsupported and refusal objects, the invalid-invocation line, that the command resolves the project in process, runs `workflow-state`, `artifact-budget` and the bound tracker CLI by name on `PATH`, removes the bound credential names from every tracker-CLI child, and writes no file.

- `Refusal`, `InvocationError` as in Interfaces. `strict_json` decodes UTF-8 and loads with the two `agent_tools.canonical` hooks.
- `run_child`: `subprocess.run(list(argv), input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL, capture_output=True, check=False, env=…)` (pass `input` only when given); an `OSError` raises `Refusal(step, f"cannot run {argv[0]}: {error}")`.
- `validate_bytes(step, raw)`: `run_child(step, ["artifact-budget", "validate-report", "--boundary", "workflow-response", "--input", "-"], stdin=raw)`; non-zero exit → `Refusal(step, f"validate-report refused (exit {code}){why(done)}")`; returns its stdout bytes.
- `workflow_response(step, *argv, stdin=None)`: `run_child(step, ["workflow-state", *argv], stdin=stdin)`; non-zero → `Refusal(step, f"workflow-state exit {code}{why(done)}")`; then `strict_json(validate_bytes(step, done.stdout))`; a `ValueError` or a non-object → `Refusal(step, "validate-report did not print one JSON object")`. No field of a child's stdout is read before it is validated (D13).
- `load_bindings(repo_root)`: `snapshot = resolve_project.resolve(repo_root)`; a `ContractError` → `Refusal("bindings", f"resolve-project refused: {error.code} {error.repair_id}")`. Read `project.root`, `bindings.workflow.orchestration.{max_parallel, attempt_budget_minutes}`, `bindings.tracker.{kind, cli, repo_slug, credential_env.unset_before_invocation}`, `bindings.vcs.worktree.{root, prefix}`. A missing member or a wrong type refuses at `bindings` naming the pointer (`missing binding /bindings/…`): integers must be `int`, not `bool`, and at least 1; strings non-empty except `prefix` (may be empty); `unset` a list of strings; `repo_slug` must have exactly one `/` with non-empty sides. `worktree_root = os.path.normpath(os.path.join(project_root, root))`. Nothing is defaulted.
- `tracker_env(b)`: `{k: v for k, v in os.environ.items() if k not in b.unset}`. `require_github(step, b)`: `b.tracker_kind != "github"` → `Refusal(step, f"tracker kind {kind} is not supported")` (D7).
- `sweep(b, flag, value) -> list[int]`: `require_github("issues", b)`; argv `[b.tracker_cli, "issue", "list", "--repo", b.repo_slug, "--state", "open", flag, value, "--json", "number", "--limit", "1000"]` with `env=tracker_env(b)`; non-zero → `Refusal("issues", f"{cli} exit {code}{why(done)}")`; the reply must be a JSON list of objects whose `number` is a positive `int` (else refuse at `issues`); exactly 1000 entries refuses (`the listing reached its 1000-issue limit`, D16); return the sorted unique numbers.
- `start(args, done)`: `bindings` → `load_bindings`; `route` → `workflow_response("route", "host-route", "--route", ROUTE)`; `support == "unsupported"` returns `{"command": "start", "outcome": "unsupported", "route": route}`; any value but `supported`/`unsupported` refuses at `route`. `issues` → explicit numbers (a repeated number refuses: `duplicate issue number N`) with `source = {"kind": "explicit_user", "reference": "invocation:/orchestrate-issues " + " ".join(numbers)}` and `human_directed: True`, or `sweep(...)` with `{"kind": "standing_repository", "reference": f"sweep:{'label' if args.label is not None else 'milestone'}:{value}"}` and `False`; an empty set refuses (`the issue set is empty`). `bootstrap` → `workflow_response("bootstrap", "init-run", "--repo-root", args.repo_root, *(["--run-id", args.run_id] if args.run_id else ["--issue-set", "-".join(map(str, issues))]))`; `kind` must be `workflow_bootstrap` and, with `--run-id`, `run_id` must equal it (else refuse at `bootstrap`). Append each step name to `done` after it finishes. Ready: `{"command": "start", "outcome": "ready", "session": {"interface_version": 1, "run_id": reply["run_id"], "issues": issues, "human_directed": …, "source": …}}`.
- Parser: `class _Parser(argparse.ArgumentParser)` whose `error` raises `InvocationError` (as in `sdd_gate`); `prog="orchestrate-control"`; subparsers `dest="command", required=True`; `start`: `--repo-root` (required), positional `numbers` (`nargs="*"`, type accepting `[1-9][0-9]*` only), a mutually exclusive `--label`/`--milestone`, `--run-id`. `_parse` raises `InvocationError` unless `os.path.isabs(repo_root)` and exactly one of numbers, `--label`, `--milestone` is given (D29).
- `main`: invalid invocation → `INVALID` on stderr, return 2; run the subcommand with `done = []`; print the result with `_print`; a `Refusal` prints `{"command", "outcome": "refused", "step", "detail": " ".join(detail.split())[:DETAIL_LIMIT], "completed_steps": list(done), "response": refusal.response}` and returns 2. `if __name__ == "__main__": raise SystemExit(main())`.

- [ ] **Step 5: Wire the command row, launcher floor, recipe and README**

- `lib/agent-tools.nix`: add `"orchestrate-control"` to `commands` between `"launch-scope"` and `"promotion"`.
- `tests/test_agent_tools_launchers.py`: add `"orchestrate-control"` to `LAUNCHER_FLOOR` between `"lane-triage"` and `"replay-retained"`.
- `justfile`: add `    tests/test_orchestrate_control.py \` to `agent-workflow-tests` directly after `    tests/test_sdd_gate.py \`.
- `python/README.md`: a new `## \`orchestrate-control\`` section after the `sdd-gate` section, written from the code at this commit: the `start` usage line (#403), what each of its four steps does, the session and unsupported objects, that `--run-id` re-enters an existing run and never creates one, that a set too long for the issue-set key refuses at `bootstrap` and is minted with `workflow-state init-run --creation-key` and then re-entered with `start --run-id` (D14), the refusal object and the invalid-invocation line, and that the command writes no file.

- [ ] **Step 6: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_orchestrate_control.py` (timeout 900 s)
Expected: OK, 10 tests, no failures, errors or skips.

Run: `git add python/agent_tools/orchestrate_control.py tests/orchestrate_world.py tests/test_orchestrate_control.py lib/agent-tools.nix tests/test_agent_tools_launchers.py justfile python/README.md && just agent-installed-skill-tests` (timeout 3600 s; it builds first and the flake only sees staged files)
Expected: the build succeeds and the run ends `OK`; `test_the_command_table_generates_each_deployed_command` and `test_a_hostile_agent_tools_on_every_channel_is_ignored` pass with `orchestrate-control` (its `--help` prints `usage: orchestrate-control ` and exits 0). A missing row fails the first; a parser without `prog="orchestrate-control"` fails the second.

- [ ] **Step 7: Commit**

```bash
git add python/agent_tools/orchestrate_control.py tests/orchestrate_world.py tests/test_orchestrate_control.py lib/agent-tools.nix tests/test_agent_tools_launchers.py justfile python/README.md
git commit -m "feat(agent-tools): orchestrate-control start (#403)"
```
