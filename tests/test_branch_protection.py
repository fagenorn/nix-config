"""Pin the CI required-status-check contract.

The context `.github/branch-protection.json` requires and the job name GitHub
reports are the same string held in two files that GitHub will never reconcile for
us — and once `just protect-main` has been applied, a rename on
either side raises no error anywhere: it leaves `main` waiting forever on a context
that never reports, with nothing in the UI pointing at the cause. These tests are
the only offline place that failure can surface. `ci.yaml`,
`instruction-budget.yaml` and the generated `conformance.yaml` share one indentation
convention, so every helper reads any of them through a trailing `path` parameter that
defaults to `ci.yaml`.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "ci.yaml"
BUDGET_WORKFLOW = WORKFLOWS / "instruction-budget.yaml"
CONFORMANCE_WORKFLOW = WORKFLOWS / "conformance.yaml"
CLEANUP_WORKFLOW = WORKFLOWS / "cleanup-issue.yaml"
LINT_TIME_WORKFLOW = WORKFLOWS / "lint-time.yaml"
PROTECTION = REPO_ROOT / ".github" / "branch-protection.json"

# The indentation convention that ci.yaml and instruction-budget.yaml share:
# workflow name at column 0, job keys at two spaces, job attributes at four, step
# attributes at six or more. PyYAML is not a guaranteed dependency on this host, so
# the convention is the parser.
JOB_KEY_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
JOB_NAME_RE = re.compile(
    r"^    name:\s*(?:\"([^\"]*)\"|'([^']*)'|(\S.*?))\s*$"
)
JOB_IF_RE = re.compile(r"^    if:\s*(\S.*?)\s*$")
JOB_PERMISSIONS_RE = re.compile(
    r'''^    (?:"permissions"|'permissions'|permissions)\s*:(?:\s|$)'''
)
RENAMING_KEY_RE = re.compile(r"^    (strategy|uses):")
# Keys that let a required job report success without its steps having run. A
# step-level `if:` sits at six or eight spaces (`      - if:` as a step's first key,
# `        if:` after one); `continue-on-error:` and `needs:` are checked at every
# depth inside the job. Shell never writes `if:` with a colon, so `run:` bodies do
# not collide, and a false positive here fails loudly rather than passing silently.
GREEN_WITHOUT_WORK_RE = re.compile(
    r"^(?:\s{6,}(?:- )?if:\s|\s{4,}(?:- )?continue-on-error:\s|    needs:)"
)
TOP_LEVEL_KEY_RE = re.compile(r"^[A-Za-z]")

# The evaluation `Nix Eval` exists to perform. The keys above all let the job
# conclude success without its steps running; this is the other road to the same
# place — steps that run fine but no longer evaluate anything. Pinned as the
# command plus the attribute it resolves, because evaluating some *other* flake
# attribute is as green and as worthless as evaluating none.
NIX_EVAL_COMMAND_RE = re.compile(r"\bnix\s+eval\b")
EVALUATED_ATTRIBUTE = (
    ".#nixosConfigurations.anis-desktop.config.system.build.toplevel.drvPath"
)

# The steps `Nix Eval` runs for the platform package (#1439): each is a name and one
# single-line `run:`, with no `|| true`, `if:` or `continue-on-error:` to make it pass empty.
PLATFORM_PACKAGE_STEPS = (
    ("Build the platform package", "nix build --no-link '.#packages.x86_64-linux.agent-platform'"),
    ("Evaluate the macOS platform package",
     "nix eval --raw '.#packages.aarch64-darwin.agent-platform.drvPath'"),
    ("Check the platform package runs with no home configuration",
     "nix build --no-link '.#checks.x86_64-linux.agent-platform'"),
)

# The run `Agent Workflow Tests` exists to perform (issue 608): the whole suite on the
# source surface, at the job count the hosted 4-vCPU runner has always used, with node
# for the deliver-standard program scenarios (issue 618).
SUITE_INVOCATION = ("WORKFLOW_POLICY_SURFACE=source nix shell --inputs-from . nixpkgs#just "
                    "nixpkgs#nodejs --command just agent-workflow-tests")

# The one step `if:` a required job may carry (ADR-delivery-015 D8): an upload after the
# step that runs the evaluation. It runs after the evaluation, so it cannot skip it, and
# a failed evaluation keeps the job red. EVALUATION_RUNS names, for each required context
# whose evaluating step is one `run:` line, the line an earlier step must hold.
UPLOAD_AFTER_EVALUATION_IF = "        if: ${{ !cancelled() }}"
UPLOAD_ACTION = "        uses: actions/upload-artifact@v4"
EVALUATION_RUNS = {"Agent Workflow Tests": SUITE_INVOCATION}

# The step that compares a pull request's suite timing report with main's baseline.
COMPARE = ('PYTHONPATH=python python3 -m agent_tools.delivery.suite_timing compare '
           '--head suite-timing/head/suite-timing.json --base suite-timing/base/suite-timing.json '
           '--base-label "$BASE_REF" >> "$GITHUB_STEP_SUMMARY"')

REQUIRED_PAYLOAD_KEYS = {
    "required_status_checks",
    "enforce_admins",
    "required_pull_request_reviews",
    "restrictions",
}

EXPECTED_WORKFLOW_PERMISSIONS = {"contents": "read"}
# The one command the Conformance job exists to run, and the whole of its step: the
# non-blank lines of the step are exactly these, so no `shell:`, `env:`,
# `working-directory:` or `if:` can ride on it. The second step reads the head's contract
# with the platform built at the base, and is pinned the same way.
CONFORMANCE_INVOCATION = "nix shell .#agent-platform --command conformance run --purpose ci --lint-times"
CONFORMANCE_STEP = ["      - name: Run conformance",
                    f"        run: {CONFORMANCE_INVOCATION}"]
BASE_PLATFORM_STEP_NAME = "Read the contract with the base platform"
BASE_PLATFORM_STEP = [
    f"      - name: {BASE_PLATFORM_STEP_NAME}",
    "        run: |",
    '          base="git+file://$GITHUB_WORKSPACE?rev=${{ github.event.pull_request.base.sha || github.event.before }}"',
    '          nix build "$base#agent-platform" --out-link "$RUNNER_TEMP/base-platform"',
    '          "$RUNNER_TEMP/base-platform/bin/resolve-project" platform-status --repo-root . '
    '>"$RUNNER_TEMP/base-status.json" 2>"$RUNNER_TEMP/base-warnings.txt" '
    '|| { cat "$RUNNER_TEMP/base-status.json"; exit 1; }',
    "          sed 's/^/::warning::/' \"$RUNNER_TEMP/base-warnings.txt\"",
    "          jq -e '.compatibility.compatible' \"$RUNNER_TEMP/base-status.json\"",
]
CONFORMANCE_CHECKOUT_REF = "          ref: ${{ github.event.pull_request.head.sha || github.sha }}"
BUDGET_COMMAND_RE = re.compile(r"PYTHONPATH=python python3 -m agent_tools\.instruction_load check\b")
BUDGET_INVOCATION = 'PYTHONPATH=python python3 -m agent_tools.instruction_load check "${args[@]}"'
REQUIRED_CONTEXTS = ("Nix Eval", "Instruction Budget", "Agent Workflow Tests", "Conformance")
EXPECTED_PROTECTION_PAYLOAD = {
    "required_status_checks": {
        "strict": True,
        "checks": [{"context": context, "app_id": 15368} for context in REQUIRED_CONTEXTS],
    },
    "enforce_admins": True,
    "required_pull_request_reviews": None,
    "restrictions": None,
}
INSTRUCTIONS = REPO_ROOT / "CLAUDE.md"
PROTECTION_SENTENCE = "**`.github/branch-protection.json` makes "
COUNT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight")


def workflow_lines(path=WORKFLOW):
    return path.read_text(encoding="utf-8").splitlines()


def _top_level_block(key, path=WORKFLOW):
    """Lines under a column-0 `key:`, up to the next column-0 key."""
    lines = workflow_lines(path)
    header = f"{key}:"
    if header not in lines:
        raise AssertionError(f"{path} has no top-level `{header}`")
    out = []
    for line in lines[lines.index(header) + 1:]:
        if TOP_LEVEL_KEY_RE.match(line):
            break
        out.append(line)
    return out


def job_blocks(path=WORKFLOW):
    """Map each job key in `jobs:` to the lines of its block."""
    blocks = {}
    current = None
    for line in _top_level_block("jobs", path):
        match = JOB_KEY_RE.match(line)
        if match:
            current = match.group(1)
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return blocks


def _mapping_entry(line, indentation, scope):
    """Return one constrained YAML mapping entry or reject an unknown one.

    The workflow shape makes a full YAML parser unnecessary, but silently
    ignoring a valid alternative spelling would turn this assertion into a
    bypass.  This accepts the spellings used for permission and job keys, then
    fails loudly when a non-comment entry at the guarded indentation falls
    outside that constrained grammar.
    """
    prefix = " " * indentation
    if not line.startswith(prefix) or line.startswith(prefix + " "):
        return None
    entry = line[indentation:]
    if not entry or entry.startswith("#"):
        return None
    match = re.fullmatch(
        r'''(?:"(?P<double>[^"]+)"|'(?P<single>[^']+)'|(?P<bare>[A-Za-z0-9_-]+))
            \s*:\s*(?P<value>.*?)''',
        entry,
        re.VERBOSE,
    )
    if not match:
        raise AssertionError(
            f"cannot classify {scope} entry {line!r}; refusing to ignore it"
        )
    if match.group("double") is not None and "\\" in match.group("double"):
        raise AssertionError(
            f"cannot classify {scope} entry {line!r}; refusing to ignore it"
        )
    key = next(value for value in match.group("double", "single", "bare") if value)
    return key, match.group("value")


def workflow_permissions(path=WORKFLOW):
    """Return the two-space token permissions declared at workflow scope."""
    permissions = {}
    for line in _top_level_block("permissions", path):
        entry = _mapping_entry(line, 2, "workflow permission")
        if entry is not None:
            key, value = entry
            permissions[key] = value
    return permissions


def job_permission_lines(block):
    """Return job-level permission entries after validating job attributes."""
    permissions = []
    for line in block:
        entry = _mapping_entry(line, 4, "job attribute")
        if entry is not None and entry[0] == "permissions":
            # Keep the spelling pin close to the parser so the assertion is
            # explicit about the job-level override it rejects.
            if not JOB_PERMISSIONS_RE.match(line):
                raise AssertionError(
                    f"cannot classify job permission entry {line!r}; refusing to ignore it"
                )
            permissions.append(line.strip())
    return permissions


def job_body(key, path=WORKFLOW):
    """The job's block with comment lines dropped.

    A `#`-leading line is a YAML comment at job level and a shell comment inside a
    `run: |` body — under neither reading is it something the runner executes, so a
    comment quoting the evaluation must not satisfy an assertion that the job still
    runs it.
    """
    return "\n".join(
        line for line in job_blocks(path)[key] if not line.lstrip().startswith("#")
    )


def job_names(path=WORKFLOW):
    """Map each job's reported check-run name to its job key."""
    names = {}
    for key, block in job_blocks(path).items():
        for line in block:
            name = job_name(line)
            if name is not None:
                if name in names:
                    raise AssertionError(f"job name {name!r} is defined twice in {path.name}")
                names[name] = key
                break
    return names


def all_workflows():
    return sorted(WORKFLOWS.glob("*.yaml")) + sorted(WORKFLOWS.glob("*.yml"))


def required_jobs():
    """Map each job name in any workflow to its `(workflow path, job key)`.

    A name defined in two workflows is refused: GitHub would report both under the
    one required context, and a passing duplicate could stand in for a failing gate.
    """
    found = {}
    for path in all_workflows():
        for name, key in job_names(path).items():
            if name in found:
                raise AssertionError(f"job name {name!r} is defined in {found[name][0].name} "
                                     f"and {path.name}")
            found[name] = (path, key)
    return found


def job_name(line):
    """Extract a job name scalar from a four-space YAML `name:` line."""
    match = JOB_NAME_RE.match(line)
    if not match:
        return None
    return next(value for value in match.groups() if value is not None)


def trigger_block(name, path=WORKFLOW):
    """Lines under `  <name>:` inside the `on:` block, or None if absent."""
    block = _top_level_block("on", path)
    header = f"  {name}:"
    if header not in block:
        return None
    out = []
    for line in block[block.index(header) + 1:]:
        if re.match(r"^  \S", line):
            break
        out.append(line)
    return out


def trigger_branches(name, path=WORKFLOW):
    """The `branches:` list of a trigger, or None if the trigger or the key is absent.

    Scoped to the `branches:` subtree on purpose: a bare `- main` anywhere under the
    trigger would also satisfy a `paths:` or `paths-ignore:` list, which gates nothing.
    """
    block = trigger_block(name, path)
    if block is None or "    branches:" not in block:
        return None
    out = []
    for line in block[block.index("    branches:") + 1:]:
        if not re.match(r"^      - ", line):
            break
        out.append(line.strip()[2:].strip())
    return out


def pull_request_trigger_problems(path=WORKFLOW):
    """Why a required context's workflow would not report on a pull request to `main`.

    A required context on a workflow that skips a pull request never reports, and that
    pull request can never merge.
    """
    block = trigger_block("pull_request", path)
    if block is None:
        return ["no pull_request trigger"]
    problems = []
    branches = [item.strip("\"'") if item[:1] == item[-1:] and item[:1] in "\"'" else item
                for item in trigger_branches("pull_request", path) or []]
    if branches != ["main"]:
        problems.append(f"branches are {branches}, not ['main']")
    for line in block:
        if line.startswith(("    paths", "    branches-ignore")):
            problems.append(f"filter under pull_request: {line.strip()}")
        if line.startswith("    types:"):
            listed = re.findall(r"[a-z_]+", line.split(":", 1)[1])
            missing = [t for t in ("opened", "synchronize", "reopened") if t not in listed]
            if missing:
                problems.append(f"types lacks {missing}")
    return problems


def job_if_expression(key, path=WORKFLOW):
    """The job's four-space `if:` expression, or None when it has none."""
    for line in job_blocks(path)[key]:
        match = JOB_IF_RE.match(line)
        if match:
            return match.group(1)
    return None


def step_blocks(key, path=WORKFLOW):
    """Return the named steps in a job, including each step's owned lines."""
    steps = {}
    current = None
    for line in job_blocks(path)[key]:
        match = re.match(r"^      - name: (.+)$", line)
        if match:
            current = match.group(1)
            steps[current] = [line]
        elif current is not None:
            steps[current].append(line)
    return steps


def forwards_budget_args(body):
    """Whether the one budget call is the invocation that forwards `args`.

    Without the forwarding, `--base HEAD^1` and `--raise-label` are still built and
    still in the body, yet the check runs with neither.
    """
    calls = [line.strip() for line in body.splitlines() if BUDGET_COMMAND_RE.search(line)]
    return calls == [BUDGET_INVOCATION]


def conformance_job_problems(path=CONFORMANCE_WORKFLOW):
    """Why the Conformance job could report green without running its command, or [].

    Beyond the keys `green_without_work` finds, the job must keep its four steps, the
    exact command step, the exact base platform step, the runner's default shell (a `defaults:` block anywhere would
    swap the interpreter that reads the command line) and its one job name. The
    never-rise check needs the merge base and the branch head, so the checkout keeps
    full history and the pull request's head commit.
    """
    problems = []
    if job_names(path) != {"Conformance": "conformance"}:
        problems.append(f"job names are {job_names(path)}, not Conformance only")
    steps = step_blocks("conformance", path)
    if list(steps) != ["Checkout", "Install Nix", "Run conformance", BASE_PLATFORM_STEP_NAME]:
        problems.append(f"steps are {list(steps)}")
    elif [line for line in steps["Run conformance"] if line.strip()] != CONFORMANCE_STEP:
        problems.append(f"the command step is {steps['Run conformance']}")
    elif [line for line in steps[BASE_PLATFORM_STEP_NAME] if line.strip()] != BASE_PLATFORM_STEP:
        problems.append(f"the base platform step is {steps[BASE_PLATFORM_STEP_NAME]}")
    else:
        if "          fetch-depth: 0" not in steps["Checkout"]:
            problems.append("the checkout does not fetch the full history")
        if CONFORMANCE_CHECKOUT_REF not in steps["Checkout"]:
            problems.append("the checkout does not judge the pull request's head")
    if any(re.match(r"^defaults:", line) for line in workflow_lines(path)):
        problems.append("a workflow-level defaults: block")
    job = job_blocks(path)["conformance"]
    if any(re.match(r"^    defaults:", line) for line in job):
        problems.append("a job-level defaults: block")
    offenders = green_without_work(job, None)
    if offenders:
        problems.append(f"green without work: {offenders}")
    if job_if_expression("conformance", path) is not None:
        problems.append("a job-level if:")
    if any(RENAMING_KEY_RE.match(line) for line in job):
        problems.append("a job-level strategy: or uses:")
    return problems


BUDGET_STEP = "Check the instruction budget"
# The budget step's whole `env:` mapping: the event name and the payload-derived label.
BUDGET_ENV = [
    "EVENT_NAME: ${{ github.event_name }}",
    "RAISE_LABEL: ${{ github.event_name == 'pull_request' && "
    "contains(github.event.pull_request.labels.*.name, 'instruction-budget-raise') }}",
]
# The arguments `check` must receive for each event and label value (D14: the head
# runs its own workflow, so losing raise control here would be permanent).
BUDGET_CASES = (
    ("pull_request", "true", ["--base", "HEAD^1", "--raise-label"]),
    ("pull_request", "false", ["--base", "HEAD^1"]),
    ("push", "false", []),
)


def budget_step(path=BUDGET_WORKFLOW):
    """The lines of the budget job's checking step."""
    return step_blocks("instruction-budget", path)[BUDGET_STEP]


def green_without_work(lines, evaluation_run):
    """The stripped lines of a job that let it conclude success without its steps running.

    One line is allowed: `UPLOAD_AFTER_EVALUATION_IF` on an upload step that follows a
    step running `evaluation_run`. Without an `evaluation_run`, nothing is allowed.
    """
    steps = [[]]
    for line in lines:
        if line.startswith("      - name:"):
            steps.append([])
        steps[-1].append(line)
    offenders = []
    for index, step in enumerate(steps):
        runs_before = evaluation_run is not None and any(
            f"        run: {evaluation_run}" in earlier for earlier in steps[:index]
        )
        for line in step:
            if not GREEN_WITHOUT_WORK_RE.match(line):
                continue
            if line == UPLOAD_AFTER_EVALUATION_IF and runs_before and UPLOAD_ACTION in step:
                continue
            offenders.append(line.strip())
    return offenders


def with_value(step, key):
    """The value of the step's single `with:` input `key`."""
    prefix = f"          {key}: "
    values = [line[len(prefix):] for line in step if line.startswith(prefix)]
    if len(values) != 1:
        raise AssertionError(f"step {step[:1]} has {len(values)} `with:` inputs {key!r}")
    return values[0]


def step_env(step):
    """The stripped `key: value` lines of a step's `env:` mapping, or None without one."""
    if "        env:" not in step:
        return None
    out = []
    for line in step[step.index("        env:") + 1:]:
        if not line.startswith("          "):
            break
        out.append(line.strip())
    return out


def step_script(step):
    """The shell body of a step's `run: |` block, dedented."""
    body = []
    for line in step[step.index("        run: |") + 1:]:
        if line.strip() and not line.startswith("          "):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


def execute_budget_script(script, event, label):
    """Run `script` with `python3` stubbed to print its argv; exit code, argv, stderr.

    The stub is a shell function, not an executable on PATH: a function shadows every
    PATH entry, so a host that refuses to exec a freshly written file cannot make bash
    fall through to the real interpreter.
    """
    stub = "python3() { printf '%s\\n' \"$@\"; }\n"
    with tempfile.TemporaryDirectory() as directory:
        result = subprocess.run(
            [shutil.which("bash"), "-c", stub + script], cwd=directory, capture_output=True,
            text=True, check=False,
            env={"PATH": os.environ["PATH"], "EVENT_NAME": event, "RAISE_LABEL": label},
        )
    return result.returncode, result.stdout.splitlines(), result.stderr


def budget_step_problems(step):
    """Each way the step fails to pass `check` the base and the label it should."""
    problems = []
    env = step_env(step)
    if env != BUDGET_ENV:
        problems.append(f"env is {env!r}, not {BUDGET_ENV!r}")
    script = step_script(step)
    for event, label, extra in BUDGET_CASES:
        expected = (0, ["-m", "agent_tools.instruction_load", "check", *extra])
        code, argv, stderr = execute_budget_script(script, event, label)
        if (code, argv) != expected:
            problems.append(f"{event} with label {label}: ran {(code, argv)!r}, not "
                            f"{expected!r}; stderr {stderr!r}")
    return problems


def payload():
    return json.loads(PROTECTION.read_text(encoding="utf-8"))


def required_contexts():
    # D2 pins one provider-bound check in the exact payload; job assertions use
    # the context list derived from those checks.
    return [check["context"] for check in payload()["required_status_checks"]["checks"]]


class WorkflowShape(unittest.TestCase):
    def test_agent_workflow_tests_job_runs_the_whole_suite_and_fails_with_it(self):
        """Issue 608: the suite gates merges, so its job must fail when a test fails."""
        self.assertEqual("agent-workflow-tests", job_names().get("Agent Workflow Tests"))
        body = job_body("agent-workflow-tests")
        self.assertIn("runs-on: ubuntu-24.04", body)
        self.assertIn("timeout-minutes: 45", body)
        self.assertNotIn("continue-on-error", body)
        steps = step_blocks("agent-workflow-tests")
        self.assertEqual(
            ["Checkout", "Install Nix", "Run agent workflow tests", "Upload suite timing"],
            list(steps),
        )
        # Issue 436: suite modules build fixtures from pinned ancestor commits and
        # refuse to skip, so the checkout fetches history.
        self.assertIn("          fetch-depth: 0", steps["Checkout"])
        suite = steps["Run agent workflow tests"]
        self.assertIn(f"        run: {SUITE_INVOCATION}", suite)
        self.assertEqual(
            ['SUITE_RUNNER_JOBS: "4"', "SUITE_RUNNER_REPORT: suite-timing/suite-timing.json"],
            step_env(suite),
        )
        self.assertEqual([], [line for line in suite if line.startswith("        if:")])
        upload = steps["Upload suite timing"]
        self.assertIn(UPLOAD_AFTER_EVALUATION_IF, upload)
        self.assertIn(UPLOAD_ACTION, upload)
        self.assertIn("          if-no-files-found: error", upload)
        self.assertEqual("suite-timing", with_value(upload, "name"))
        self.assertEqual(
            step_env(suite)[1].removeprefix("SUITE_RUNNER_REPORT: "),
            with_value(upload, "path"),
        )

    def test_only_an_upload_after_the_evaluation_may_run_when_it_failed(self):
        """ADR-delivery-015 D8: the one step `if:` a required job may carry."""
        base = [
            "    name: Job",
            "      - name: Checkout",
            "        uses: actions/checkout@v4",
            "      - name: Suite",
            "        run: S",
            "      - name: Upload",
            UPLOAD_ACTION,
            UPLOAD_AFTER_EVALUATION_IF,
        ]
        moved_onto_suite = [line for line in base if line != UPLOAD_AFTER_EVALUATION_IF]
        moved_onto_suite.insert(base.index("        run: S"), UPLOAD_AFTER_EVALUATION_IF)
        upload_first = [base[0], *base[1:3], *base[5:], *base[3:5]]
        always = [*base[:-1], "        if: always()"]
        on_echo = [*base, "      - name: Echo", "        run: echo", UPLOAD_AFTER_EVALUATION_IF]
        failure_ignored = [*base, "        continue-on-error: true"]
        needing = [*base, "    needs: other"]
        cases = (
            ("the upload after the evaluation", base, "S", []),
            ("the if moved onto the evaluation", moved_onto_suite, "S",
             ["if: ${{ !cancelled() }}"]),
            ("the upload before the evaluation", upload_first, "S", ["if: ${{ !cancelled() }}"]),
            ("a different condition", always, "S", ["if: always()"]),
            ("an echo step after the evaluation", on_echo, "S", ["if: ${{ !cancelled() }}"]),
            ("a failure ignored", failure_ignored, "S", ["continue-on-error: true"]),
            ("no evaluation run", base, None, ["if: ${{ !cancelled() }}"]),
            ("a needs", needing, "S", ["needs: other"]),
        )
        for label, lines, evaluation_run, expected in cases:
            with self.subTest(case=label):
                self.assertEqual(expected, green_without_work(lines, evaluation_run))

    def test_suite_timing_jobs_keep_and_compare_the_report(self):
        """Issue 1385: the report the suite job uploads reaches the baseline and the
        comparison through the paths the consumers read."""
        names = job_names()
        self.assertEqual("suite-timing", names["Suite Timing"])
        self.assertEqual("suite-timing-baseline", names["Suite Timing Baseline"])
        for context in ("Suite Timing", "Suite Timing Baseline"):
            self.assertNotIn(context, required_contexts())
        self.assertEqual("${{ !cancelled() && github.event_name == 'pull_request' }}",
                         job_if_expression("suite-timing"))
        self.assertEqual("github.event_name == 'push'", job_if_expression("suite-timing-baseline"))
        for key in ("suite-timing", "suite-timing-baseline"):
            self.assertIn("    needs: agent-workflow-tests", job_body(key))
        baseline = step_blocks("suite-timing-baseline")
        self.assertEqual(["Download this run's suite timing", "Keep it as the baseline"],
                         list(baseline))
        pull_request = step_blocks("suite-timing")
        self.assertEqual(["Checkout", "Download this run's suite timing", "Restore the baseline",
                          "Compare with the baseline"], list(pull_request))
        upload = step_blocks("agent-workflow-tests")["Upload suite timing"]
        name = PurePosixPath(with_value(upload, "path")).name
        self.assertEqual("suite-timing.json", name)
        base_download = baseline["Download this run's suite timing"]
        save = baseline["Keep it as the baseline"]
        self.assertEqual("suite-timing", with_value(base_download, "name"))
        self.assertEqual(f"{with_value(base_download, 'path')}/{name}", with_value(save, "path"))
        self.assertIn("          key: suite-timing-${{ github.sha }}", save)
        head_download = pull_request["Download this run's suite timing"]
        restore = pull_request["Restore the baseline"]
        compare = pull_request["Compare with the baseline"]
        restore_path = with_value(restore, "path")
        self.assertEqual("suite-timing", with_value(head_download, "name"))
        self.assertIn(f"--head {with_value(head_download, 'path')}/{name} ", COMPARE)
        self.assertEqual(with_value(save, "path"), restore_path)
        self.assertIn(f"--base {restore_path} ", COMPARE)
        self.assertIn("          key: suite-timing-${{ github.event.pull_request.base.sha }}",
                      restore)
        self.assertIn("          restore-keys: suite-timing-", restore)
        self.assertIn("        run: " + COMPARE, compare)
        self.assertEqual(["BASE_REF: ${{ github.base_ref }}"], step_env(compare))
        # No step carries an `if:` or a `continue-on-error:`, so the comparison runs whenever the
        # job does, and the job's own condition covers every pull request (checked above). The
        # job's `needs:` is the one line of `green_without_work` left.
        for key in ("suite-timing", "suite-timing-baseline"):
            with self.subTest(job=key):
                self.assertEqual(["needs: agent-workflow-tests"],
                                 green_without_work(job_body(key).splitlines(), None))

    def test_agent_workflow_tests_job_has_the_required_triggers_without_schedule(self):
        self.assertIsNotNone(trigger_block("pull_request"))
        self.assertEqual(["main"], trigger_branches("pull_request"))
        self.assertEqual(["main"], trigger_branches("push"))
        self.assertIsNotNone(trigger_block("workflow_dispatch"))
        self.assertIsNotNone(trigger_block("schedule"))
        for trigger in ("pull_request", "push"):
            self.assertFalse(
                any(line.startswith("    paths") for line in trigger_block(trigger))
            )
        self.assertEqual("github.event_name != 'schedule'", job_if_expression("agent-workflow-tests"))

    def test_workflow_uses_only_minimum_permissions(self):
        self.assertEqual(EXPECTED_WORKFLOW_PERMISSIONS, workflow_permissions())

    def test_jobs_do_not_override_workflow_permissions(self):
        offenders = {
            key: job_permission_lines(block)
            for key, block in job_blocks().items()
        }
        self.assertEqual({}, {key: lines for key, lines in offenders.items() if lines})

    def test_permission_guards_recognize_quoted_keys_and_space_before_colons(self):
        for source in ('  "issues": write', "  issues : write"):
            with self.subTest(source=source):
                with mock.patch(f"{__name__}.workflow_lines", return_value=[
                    "permissions:",
                    "  contents: read",
                    source,
                    "jobs:",
                ]):
                    self.assertEqual(
                        {"contents": "read", "issues": "write"},
                        workflow_permissions(),
                    )

        for source in ('    "permissions": write-all', "    permissions : write-all"):
            with self.subTest(source=source):
                self.assertEqual([source.strip()], job_permission_lines([source]))

    def test_permission_guards_reject_unclassified_entries(self):
        with mock.patch(f"{__name__}.workflow_lines", return_value=[
            "permissions:",
            "  contents: read",
            "  [issues]: write",
            "jobs:",
        ]):
            with self.assertRaisesRegex(
                AssertionError, "cannot classify workflow permission"
            ):
                workflow_permissions()
        with self.assertRaisesRegex(AssertionError, "cannot classify job attribute"):
            job_permission_lines(["    [permissions]: write-all"])
        with self.assertRaisesRegex(AssertionError, "cannot classify job attribute"):
            job_permission_lines([r'    "permissio\u006es": write-all'])

    def test_job_name_extraction_removes_yaml_quotes(self):
        for source in (
            "    name: Nix Eval",
            '    name: "Nix Eval"',
            "    name: 'Nix Eval'",
        ):
            with self.subTest(source=source):
                self.assertEqual("Nix Eval", job_name(source))
        self.assertIsNone(job_name("      - name: step name"))

    def test_job_names_are_extractable(self):
        """Guards every other test here: an extractor that matches nothing would
        make the context/job-name comparisons pass vacuously."""
        names = job_names()
        self.assertTrue(
            names,
            f"no four-space `name:` job names found in {WORKFLOW}; the file's "
            f"indentation convention changed and every other assertion in this "
            f"suite is now vacuous",
        )
        self.assertIn("Nix Eval", names)
        self.assertIn("Flake Checker", names)
        self.assertIn("Instruction Budget", job_names(BUDGET_WORKFLOW))

    def test_pull_request_on_main_is_a_trigger(self):
        """Without this trigger a PR head carries zero check runs and the required
        context can never report."""
        self.assertIsNotNone(
            trigger_block("pull_request"), f"{WORKFLOW} has no `pull_request:` trigger"
        )
        branches = trigger_branches("pull_request")
        self.assertIsNotNone(
            branches, f"{WORKFLOW}'s `pull_request:` trigger has no `branches:` list"
        )
        self.assertEqual(["main"], branches)
        block = trigger_block("pull_request")
        # Matched by prefix rather than by whole line: `paths: ['**.nix']` and
        # `types: [opened, synchronize]` are both legal inline YAML, and an
        # exact-line comparison would wave either of them through.
        def narrowing_lines(key):
            return [line for line in block if line.startswith(key)]

        # A `paths:` or `paths-ignore:` filter makes the workflow skip pull
        # requests that touch no matching file. The required context then never
        # reports on those PRs and they can never merge, with nothing in the UI
        # naming the cause.
        for narrowing in ("    paths:", "    paths-ignore:"):
            self.assertEqual(
                [],
                narrowing_lines(narrowing),
                f"{WORKFLOW.name}'s `pull_request:` trigger carries "
                f"`{narrowing.strip()}`, so a PR touching nothing it matches "
                f"gets no {WORKFLOW.name} run and can never satisfy the "
                f"required context",
            )
        # No `types:` key means GitHub's default set applies, and `reopened` is
        # in it. The rollout unblocks a stranded PR with close+reopen, which
        # re-fires the workflow only while that default holds.
        self.assertEqual(
            [],
            narrowing_lines("    types:"),
            f"{WORKFLOW.name}'s `pull_request:` trigger carries an explicit "
            f"`types:` list; the default set (which includes `reopened`) no "
            f"longer applies and close+reopen may not re-fire the workflow",
        )

    def test_required_jobs_are_not_gated_off_pull_requests(self):
        """A job-level `if:` decides whether the required check reports at all.
        Pinned by value: the expression is as load-bearing as the job name, so a
        change to it has to be made deliberately here as well as in the workflow."""
        contexts = required_contexts()
        self.assertTrue(contexts, "branch protection requires at least one context")
        jobs = required_jobs()
        for context in contexts:
            self.assertIn(context, jobs)
            path, key = jobs[context]
            expression = job_if_expression(key, path)
            self.assertIn(
                expression,
                (None, "github.event_name != 'schedule'"),
                f"job {key!r} in {path.name} backs required context {context!r} and "
                f"carries an unreviewed `if:` ({expression!r}); if it can skip a "
                f"pull request, that PR blocks forever on a context that never "
                f"reports",
            )


    def test_required_jobs_cannot_report_green_without_evaluating(self):
        """The job-name and job-`if:` pins both catch a context that stops
        reporting. This catches the inverse, which is worse: a context that keeps
        reporting *success* while the evaluation it exists to run was skipped. A
        `needs:` on a failed job, a `continue-on-error:`, or an `if:` on the
        evaluating step each produce exactly that, and each leaves every other
        assertion in this file green."""
        contexts = required_contexts()
        self.assertTrue(contexts, "branch protection requires at least one context")
        jobs = required_jobs()
        for context in contexts:
            self.assertIn(context, jobs)
            path, key = jobs[context]
            offenders = green_without_work(job_blocks(path)[key], EVALUATION_RUNS.get(context))
            self.assertEqual(
                [],
                offenders,
                f"job {key!r} in {path.name} backs required context {context!r} and carries "
                f"{offenders}; each of these lets the job conclude success without "
                f"running its evaluation, so the gate would report green on a tree "
                f"nothing checked",
            )

    def test_nix_eval_builds_and_checks_the_platform_package(self):
        nix_path, nix_key = required_jobs()["Nix Eval"]
        steps = step_blocks(nix_key, nix_path)
        for name, run in PLATFORM_PACKAGE_STEPS:
            with self.subTest(step=name):
                self.assertIn(name, steps)
                self.assertEqual([line for line in steps[name] if line.strip()],
                                 [f"      - name: {name}", f"        run: {run}"])

    def test_each_required_job_still_runs_the_evaluation_it_exists_for(self):
        """Steps that run fine and evaluate nothing are the inverse of green-without-work:
        a `run:` body of `true`, another flake attribute, or a budget call that no
        longer forwards the arguments the step builds each leave every other assertion
        here green. Whether the step builds `--base` and `--raise-label` under the right
        event and label is BudgetWorkflowShape's behavioural test, not this one."""
        self.assertEqual(list(REQUIRED_CONTEXTS), required_contexts())
        jobs = required_jobs()
        nix_path, nix_key = jobs["Nix Eval"]
        nix_body = job_body(nix_key, nix_path)
        self.assertRegex(nix_body, NIX_EVAL_COMMAND_RE)
        self.assertIn(EVALUATED_ATTRIBUTE, nix_body)
        budget_path, budget_key = jobs["Instruction Budget"]
        self.assertEqual(BUDGET_WORKFLOW, budget_path)
        budget_body = job_body(budget_key, budget_path)
        self.assertRegex(budget_body, BUDGET_COMMAND_RE)
        self.assertTrue(forwards_budget_args(budget_body), budget_body)
        self.assertIn("--base HEAD^1", budget_body)
        self.assertIn("--raise-label", budget_body)
        suite_path, suite_key = jobs["Agent Workflow Tests"]
        self.assertEqual(WORKFLOW, suite_path)
        self.assertIn(SUITE_INVOCATION, job_body(suite_key, suite_path))
        conformance_path, conformance_key = jobs["Conformance"]
        self.assertEqual(CONFORMANCE_WORKFLOW, conformance_path)
        self.assertEqual("conformance", conformance_key)
        self.assertEqual([], conformance_job_problems(conformance_path))

    def test_the_budget_forwarding_rejects_mutations(self):
        body = job_body("instruction-budget", BUDGET_WORKFLOW)
        self.assertTrue(forwards_budget_args(body))
        self.assertFalse(forwards_budget_args(body + "\n" + BUDGET_INVOCATION))
        for mutated in ("check", "check --base HEAD^1 --raise-label", 'check "${args[*]}"'):
            with self.subTest(invocation=mutated):
                self.assertFalse(forwards_budget_args(body.replace('check "${args[@]}"', mutated)))


class BudgetWorkflowShape(unittest.TestCase):
    LABEL_EXPRESSION = ("contains(github.event.pull_request.labels.*.name, "
                        "'instruction-budget-raise')")

    def test_label_events_and_push_are_the_triggers(self):
        block = trigger_block("pull_request", BUDGET_WORKFLOW)
        self.assertIsNotNone(block)
        self.assertEqual(["main"], trigger_branches("pull_request", BUDGET_WORKFLOW))
        self.assertIn("    types: [opened, synchronize, reopened, labeled, unlabeled]", block)
        self.assertEqual(["main"], trigger_branches("push", BUDGET_WORKFLOW))
        for absent in ("schedule", "workflow_dispatch", "pull_request_target"):
            self.assertIsNone(trigger_block(absent, BUDGET_WORKFLOW), absent)
        for trigger in ("pull_request", "push"):
            self.assertFalse([line for line in trigger_block(trigger, BUDGET_WORKFLOW)
                              if line.startswith("    paths")])

    def test_minimum_permissions_and_no_job_override(self):
        self.assertEqual(EXPECTED_WORKFLOW_PERMISSIONS, workflow_permissions(BUDGET_WORKFLOW))
        for key, block in job_blocks(BUDGET_WORKFLOW).items():
            self.assertEqual([], job_permission_lines(block), key)

    def test_full_history_and_a_payload_derived_label(self):
        names = job_names(BUDGET_WORKFLOW)
        self.assertEqual({"Instruction Budget": "instruction-budget"}, names)
        body = job_body("instruction-budget", BUDGET_WORKFLOW)
        self.assertIn("          fetch-depth: 0", body.splitlines())
        self.assertIn(self.LABEL_EXPRESSION, body)
        for forbidden in ("secrets.", "GITHUB_TOKEN", "GH_TOKEN", "gh api", "gh pr"):
            self.assertNotIn(forbidden, body)


    def test_the_budget_step_passes_the_base_and_label_per_event(self):
        self.assertEqual([], budget_step_problems(budget_step()))

    def test_the_budget_step_rejects_raise_control_mutations(self):
        text = "\n".join(budget_step())
        guard = 'if [ "$EVENT_NAME" = pull_request ]; then'
        condition = ('            if [ "$RAISE_LABEL" = true ]; then\n'
                     "              args+=(--raise-label)\n"
                     "            fi")
        label_expression = BUDGET_ENV[1].split(": ", 1)[1]
        mutations = {
            "event name pinned": ("EVENT_NAME: ${{ github.event_name }}", "EVENT_NAME: push"),
            "label not payload-derived": (label_expression, "true"),
            "label not limited to pull requests": (
                "github.event_name == 'pull_request' && ", ""),
            "guard never matches": (guard, 'if [ "$EVENT_NAME" = pull-request ]; then'),
            "guard always matches": (guard, "if true; then"),
            "condition removed": (condition, "            args+=(--raise-label)"),
            "condition inverted": ('[ "$RAISE_LABEL" = true ]', '[ "$RAISE_LABEL" != true ]'),
            "env dropped": ("        env:\n", ""),
        }
        for label, (old, new) in mutations.items():
            with self.subTest(mutation=label):
                self.assertIn(old, text)
                mutated = text.replace(old, new, 1)
                if label == "env dropped":
                    mutated = "\n".join(line for line in mutated.splitlines()
                                        if not line.startswith(("          EVENT_NAME:",
                                                                "          RAISE_LABEL:")))
                self.assertNotEqual([], budget_step_problems(mutated.splitlines()))


class ConformanceWorkflowShape(unittest.TestCase):
    def test_the_conformance_job_reads_the_contract_with_the_base_platform(self):
        steps = step_blocks("conformance", CONFORMANCE_WORKFLOW)
        self.assertEqual(
            ["Checkout", "Install Nix", "Run conformance", BASE_PLATFORM_STEP_NAME], list(steps))
        self.assertEqual(
            BASE_PLATFORM_STEP, [line for line in steps[BASE_PLATFORM_STEP_NAME] if line.strip()])

    def test_the_conformance_job_runs_the_command_and_cannot_report_green_without_it(self):
        self.assertEqual([], conformance_job_problems())

    def test_a_mutated_job_is_caught(self):
        lines = workflow_lines(CONFORMANCE_WORKFLOW)
        name = "    name: Conformance"
        run = f"        run: {CONFORMANCE_INVOCATION}"
        step = "      - name: Run conformance"
        shell = "        shell: python {0}"
        base_name = BASE_PLATFORM_STEP[0]
        base_check = BASE_PLATFORM_STEP[-1]
        mutations = {
            "job if": (name, [name, "    if: false"]),
            "needs": (name, [name, "    needs: other"]),
            "continue-on-error": (name, [name, "    continue-on-error: true"]),
            "step if": (step, [step, "        if: always()"]),
            "run replaced": (run, ["        run: true"]),
            "job renamed": (name, ["    name: Conformance check"]),
            "step shell": (run, [run, shell]),
            "workflow defaults": ("jobs:", ["defaults:", "  run:", "    shell: python {0}", "jobs:"]),
            "job defaults": (name, [name, "    defaults:", "      run:", shell]),
            "shallow checkout": ("          fetch-depth: 0", []),
            "merge-commit checkout": (CONFORMANCE_CHECKOUT_REF, []),
            "base step if": (base_name, [base_name, "        if: false"]),
            "base check weakened": (base_check, ["          true"]),
        }
        for label, (anchor, replacement) in mutations.items():
            with self.subTest(mutation=label):
                index = lines.index(anchor)
                mutated = lines[:index] + replacement + lines[index + 1:]
                with mock.patch(f"{__name__}.workflow_lines", lambda path=None: mutated):
                    self.assertNotEqual([], conformance_job_problems())
        with self.subTest(mutation="base step dropped"):
            index = lines.index(base_name)
            mutated = lines[:index] + lines[index + len(BASE_PLATFORM_STEP):]
            with mock.patch(f"{__name__}.workflow_lines", lambda path=None: mutated):
                self.assertNotEqual([], conformance_job_problems())

    def test_pull_request_and_push_to_main_are_its_triggers(self):
        for trigger in ("pull_request", "push"):
            with self.subTest(trigger=trigger):
                self.assertEqual(['"main"'], trigger_branches(trigger, CONFORMANCE_WORKFLOW))
                for line in trigger_block(trigger, CONFORMANCE_WORKFLOW):
                    self.assertFalse(line.startswith(("    paths", "    branches-ignore",
                                                      "    types")), line)
        keys = [line.strip()[:-1] for line in _top_level_block("on", CONFORMANCE_WORKFLOW)
                if re.match(r"^  \S", line)]
        self.assertEqual(["pull_request", "push"], keys)

    def test_minimum_permissions_and_no_job_override(self):
        self.assertEqual(EXPECTED_WORKFLOW_PERMISSIONS, workflow_permissions(CONFORMANCE_WORKFLOW))
        self.assertEqual(
            [], job_permission_lines(job_blocks(CONFORMANCE_WORKFLOW)["conformance"]))


class RequiredContexts(unittest.TestCase):
    def test_every_required_context_is_a_job_name(self):
        contexts = required_contexts()
        self.assertTrue(contexts, "branch protection requires at least one context")
        jobs = required_jobs()
        for context in contexts:
            self.assertIn(
                context,
                jobs,
                f"required context {context!r} in {PROTECTION.name} matches no job "
                f"`name:` in any workflow under {WORKFLOWS.name} (found {sorted(jobs)}); "
                f"merges to main would block forever waiting for it",
            )

    def test_every_required_context_runs_on_pull_requests_to_main(self):
        contexts = required_contexts()
        jobs = required_jobs()
        self.assertIn("Conformance", contexts)
        for context in contexts:
            with self.subTest(context=context):
                self.assertEqual([], pull_request_trigger_problems(jobs[context][0]))

    def test_a_required_workflow_that_skips_pull_requests_is_caught(self):
        lines = workflow_lines(CONFORMANCE_WORKFLOW)
        header = lines.index("  pull_request:")
        branches = lines.index("    branches:", header)
        main = lines.index('      - "main"')
        mutations = {
            "no pull_request trigger": lines[:header] + lines[main + 1:],
            "another branch": lines[:main] + ['      - "release"'] + lines[main + 1:],
            "paths filter": lines[:header + 1] + ['    paths: ["**.nix"]'] + lines[header + 1:],
            "branches-ignore": lines[:header + 1] + ["    branches-ignore: [main]"] + lines[header + 1:],
            "types without synchronize": lines[:header + 1] + ["    types: [opened, reopened]"]
            + lines[header + 1:],
        }
        self.assertLess(header, branches)
        self.assertEqual([], pull_request_trigger_problems(CONFORMANCE_WORKFLOW))
        for label, mutated in mutations.items():
            with self.subTest(mutation=label):
                with mock.patch(f"{__name__}.workflow_lines", lambda path=None, mutated=mutated: mutated):
                    self.assertNotEqual([], pull_request_trigger_problems(CONFORMANCE_WORKFLOW))

    def test_job_names_refuses_a_name_twice_in_one_workflow(self):
        path = Path("twice.yaml")
        lines = ["jobs:", "  a:", "    name: Twin", "  b:", "    name: Twin"]
        with mock.patch(f"{__name__}.workflow_lines", lambda p=WORKFLOW: lines):
            with self.assertRaisesRegex(AssertionError, "defined twice in"):
                job_names(path)

    def test_required_jobs_refuses_a_name_in_two_workflows(self):
        paths = [Path("a.yaml"), Path("b.yaml")]
        by_path = {p: ["jobs:", f"  job-{p.stem}:", "    name: Twin"] for p in paths}
        with mock.patch(f"{__name__}.all_workflows", lambda: paths), \
                mock.patch(f"{__name__}.workflow_lines", lambda p=WORKFLOW: by_path[p]):
            with self.assertRaisesRegex(AssertionError, "defined in a.yaml and b.yaml"):
                required_jobs()

    def test_required_jobs_are_plain_jobs(self):
        """A matrix job reports as `name (value)` and a reusable workflow as
        `caller / callee`; either decouples the reported check-run name from the
        required context while a pure string comparison still passes."""
        contexts = required_contexts()
        self.assertTrue(contexts, "branch protection requires at least one context")
        jobs = required_jobs()
        for context in contexts:
            self.assertIn(
                context,
                jobs,
                f"required context {context!r} matches no job `name:` in any "
                f"workflow under {WORKFLOWS.name} (found {sorted(jobs)})",
            )
            path, key = jobs[context]
            offenders = [
                line.strip()
                for line in job_blocks(path)[key]
                if RENAMING_KEY_RE.match(line)
            ]
            self.assertEqual(
                [],
                offenders,
                f"job {key!r} in {path.name} backs required context {context!r} and must stay a "
                f"plain job; found {offenders}",
            )


class ProtectionPayload(unittest.TestCase):
    def test_payload_is_the_exact_replacement_contract(self):
        self.assertEqual(EXPECTED_PROTECTION_PAYLOAD, payload())

    def test_payload_carries_every_key_the_api_requires(self):
        """The API rejects a body missing any of the four keys with a 422 at apply
        time — long after the hand-edit that dropped one."""
        data = payload()
        self.assertEqual(REQUIRED_PAYLOAD_KEYS, set(data))
        self.assertIs(True, data["enforce_admins"])
        # strict: two PRs that each pass on their own base cannot merge into a breach (program D5).
        self.assertIs(True, data["required_status_checks"]["strict"])
        # D10: present and explicitly null. A non-null value here would block every
        # solo and unattended merge, which is the opposite of the issue's ask.
        self.assertIsNone(data["required_pull_request_reviews"])
        self.assertIsNone(data["restrictions"])


def required_context_sentence_problems(text):
    parts = text.split(PROTECTION_SENTENCE)
    if len(parts) != 2:
        return [f"the protection sentence occurs {len(parts) - 1} times, not once"]
    span = parts[1].split("**", 1)[0]
    problems = []
    count_phrase = f"{COUNT_WORDS[len(REQUIRED_CONTEXTS)]} contexts required on `main`: "
    if not span.startswith(count_phrase):
        problems.append(f"the sentence does not continue with {count_phrase!r}")
    problems += [f"`{context}` is not named" for context in REQUIRED_CONTEXTS if f"`{context}`" not in span]
    return problems


class ProjectInstructions(unittest.TestCase):
    def test_the_instructions_name_every_required_context(self):
        text = INSTRUCTIONS.read_text(encoding="utf-8")
        self.assertEqual([], required_context_sentence_problems(text))

    def test_a_stale_sentence_is_caught(self):
        text = INSTRUCTIONS.read_text(encoding="utf-8")
        mutations = {
            "stale count": text.replace("four contexts", "three contexts"),
            "unbackticked context": text.replace("`Conformance`", "Conformance"),
            "sentence twice": text + PROTECTION_SENTENCE,
            "sentence removed": text.replace(PROTECTION_SENTENCE, ""),
        }
        for label, mutated in mutations.items():
            with self.subTest(mutation=label):
                self.assertNotEqual(text, mutated)
                self.assertNotEqual([], required_context_sentence_problems(mutated))


class CleanupIssueWorkflowTest(unittest.TestCase):
    """The push-to-main job that files cleanup issues (ADR-delivery-017)."""

    def test_runs_on_push_to_main_only_with_issue_write_and_no_other_write(self):
        triggers = [
            line for line in _top_level_block("on", CLEANUP_WORKFLOW) if re.match(r"^  \S", line)
        ]
        self.assertEqual(["  push:"], triggers)
        self.assertEqual(
            ["    branches:", "      - main"],
            [line for line in trigger_block("push", CLEANUP_WORKFLOW) if line.strip()],
        )
        self.assertEqual(["main"], trigger_branches("push", CLEANUP_WORKFLOW))
        self.assertIsNone(job_if_expression("cleanup-issue", CLEANUP_WORKFLOW))
        self.assertEqual(
            {"contents": "read", "issues": "write", "pull-requests": "read"},
            workflow_permissions(CLEANUP_WORKFLOW),
        )
        overrides = {
            key: job_permission_lines(block)
            for key, block in job_blocks(CLEANUP_WORKFLOW).items()
            if job_permission_lines(block)
        }
        self.assertEqual({}, overrides)

    def test_pushes_run_one_after_another(self):
        self.assertEqual(
            ["  group: cleanup-issue", "  cancel-in-progress: false", "  queue: max"],
            [line for line in _top_level_block("concurrency", CLEANUP_WORKFLOW) if line.strip()],
        )

    def test_the_job_stores_the_token_then_files_through_the_command(self):
        self.assertEqual({"Cleanup Issue": "cleanup-issue"}, job_names(CLEANUP_WORKFLOW))
        steps = step_blocks("cleanup-issue", CLEANUP_WORKFLOW)
        self.assertEqual(
            ["Checkout", "Install Nix", "Store the workflow token for gh",
             "File the next cleanup issue"],
            list(steps),
        )
        self.assertEqual(
            ["      - name: Install Nix", "        uses: DeterminateSystems/nix-installer-action@v4"],
            [line for line in steps["Install Nix"] if line.strip()],
        )
        # Each step is exactly its lines: an added `shell:`, `if:`, `working-directory:`
        # or `continue-on-error:` would change what the command does or whether it runs.
        token_step = steps["Store the workflow token for gh"]
        self.assertEqual(
            [
                "      - name: Store the workflow token for gh",
                "        env:",
                "          TOKEN: ${{ github.token }}",
                "        run: printf '%s\\n' \"$TOKEN\" | gh auth login --with-token --insecure-storage",
            ],
            [line for line in token_step if line.strip()],
        )
        file_step = steps["File the next cleanup issue"]
        self.assertEqual(
            [
                "      - name: File the next cleanup issue",
                "        run: |",
                "          tools=\"$(nix build --no-link --print-out-paths '.#agent-platform.tools')\"",
                "          test -n \"$tools\"",
                "          AGENT_PLATFORM_TOOLS=\"$tools/bin\" PYTHONPATH=python python3 -m"
                " agent_tools.delivery.cleanup_issue file"
                " --repo-root \"$GITHUB_WORKSPACE\" --repo \"$GITHUB_REPOSITORY\""
                " --branch \"$GITHUB_REF_NAME\"",
            ],
            [line for line in file_step if line.strip()],
        )
        # No `env:` on the filing step: no token reaches the command.
        self.assertIsNone(step_env(file_step))
        # No default shell, working directory or job-level condition changes the commands.
        text = CLEANUP_WORKFLOW.read_text(encoding="utf-8")
        for key in ("defaults:", "shell:", "working-directory:", "continue-on-error:"):
            self.assertNotIn(key, text)
        self.assertEqual(
            ["    name: Cleanup Issue", "    runs-on: ubuntu-24.04", "    timeout-minutes: 10",
             "    steps:"],
            [line for line in job_blocks(CLEANUP_WORKFLOW)["cleanup-issue"]
             if line.startswith("    ") and not line.startswith("     ")],
        )
        self.assertEqual([], green_without_work(job_blocks(CLEANUP_WORKFLOW)["cleanup-issue"], None))

    def test_the_job_is_not_a_required_context(self):
        self.assertNotIn("Cleanup Issue", required_contexts())
        self.assertEqual(CLEANUP_WORKFLOW, required_jobs()["Cleanup Issue"][0])


class LintTimeWorkflowTest(unittest.TestCase):
    """The push-to-main job that files the lint-time issue (ADR-delivery-020)."""

    def test_runs_on_push_to_main_only_with_issue_write_and_no_other_write(self):
        triggers = [
            line for line in _top_level_block("on", LINT_TIME_WORKFLOW) if re.match(r"^  \S", line)
        ]
        self.assertEqual(["  push:"], triggers)
        self.assertEqual(["main"], trigger_branches("push", LINT_TIME_WORKFLOW))
        self.assertIsNone(job_if_expression("lint-time", LINT_TIME_WORKFLOW))
        self.assertEqual(
            {"actions": "read", "contents": "read", "issues": "write"},
            workflow_permissions(LINT_TIME_WORKFLOW),
        )
        overrides = {
            key: job_permission_lines(block)
            for key, block in job_blocks(LINT_TIME_WORKFLOW).items()
            if job_permission_lines(block)
        }
        self.assertEqual({}, overrides)

    def test_pushes_run_one_after_another(self):
        self.assertEqual(
            ["  group: lint-time", "  cancel-in-progress: false", "  queue: max"],
            [line for line in _top_level_block("concurrency", LINT_TIME_WORKFLOW) if line.strip()],
        )

    def test_the_job_stores_the_token_then_reads_the_lint_times_through_the_command(self):
        self.assertEqual({"Lint Time": "lint-time"}, job_names(LINT_TIME_WORKFLOW))
        steps = step_blocks("lint-time", LINT_TIME_WORKFLOW)
        self.assertEqual(
            ["Checkout", "Store the workflow token for gh", "Read the lint times"], list(steps)
        )
        cleanup_token = step_blocks("cleanup-issue", CLEANUP_WORKFLOW)[
            "Store the workflow token for gh"
        ]
        token_step = steps["Store the workflow token for gh"]
        self.assertEqual(
            [line for line in cleanup_token if line.strip()],
            [line for line in token_step if line.strip()],
        )
        read_step = steps["Read the lint times"]
        self.assertEqual(
            [
                "      - name: Read the lint times",
                "        run: PYTHONPATH=python python3 -m agent_tools.delivery.lint_time file"
                " --repo \"$GITHUB_REPOSITORY\" --branch \"$GITHUB_REF_NAME\"",
            ],
            [line for line in read_step if line.strip()],
        )
        # No `env:` on the command step: no token reaches the command.
        self.assertIsNone(step_env(read_step))
        text = LINT_TIME_WORKFLOW.read_text(encoding="utf-8")
        for key in ("defaults:", "shell:", "working-directory:", "continue-on-error:"):
            self.assertNotIn(key, text)
        self.assertEqual(
            ["    name: Lint Time", "    runs-on: ubuntu-24.04", "    timeout-minutes: 10",
             "    steps:"],
            [line for line in job_blocks(LINT_TIME_WORKFLOW)["lint-time"]
             if line.startswith("    ") and not line.startswith("     ")],
        )
        self.assertEqual([], green_without_work(job_blocks(LINT_TIME_WORKFLOW)["lint-time"], None))

    def test_the_job_is_not_a_required_context(self):
        self.assertNotIn("Lint Time", required_contexts())
        self.assertEqual(LINT_TIME_WORKFLOW, required_jobs()["Lint Time"][0])


if __name__ == "__main__":
    unittest.main()
