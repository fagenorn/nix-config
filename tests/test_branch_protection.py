"""Pin the CI required-status-check contract.

The context `.github/branch-protection.json` requires and the job name GitHub
reports are the same string held in two files that GitHub will never reconcile for
us — and once `just protect-main` has been applied, a rename on
either side raises no error anywhere: it leaves `main` waiting forever on a context
that never reports, with nothing in the UI pointing at the cause. These tests are
the only offline place that failure can surface. `ci.yaml` and
`instruction-budget.yaml` share one indentation convention, so every helper reads
either through a trailing `path` parameter that defaults to `ci.yaml`.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "ci.yaml"
BUDGET_WORKFLOW = WORKFLOWS / "instruction-budget.yaml"
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

REQUIRED_PAYLOAD_KEYS = {
    "required_status_checks",
    "enforce_admins",
    "required_pull_request_reviews",
    "restrictions",
}

EXPECTED_WORKFLOW_PERMISSIONS = {"contents": "read"}
BUDGET_COMMAND_RE = re.compile(r"PYTHONPATH=python python3 -m agent_tools\.instruction_load check\b")
BUDGET_INVOCATION = 'PYTHONPATH=python python3 -m agent_tools.instruction_load check "${args[@]}"'
EXPECTED_PROTECTION_PAYLOAD = {
    "required_status_checks": {
        "strict": True,
        "checks": [{"context": "Nix Eval", "app_id": 15368},
                   {"context": "Instruction Budget", "app_id": 15368}],
    },
    "enforce_admins": True,
    "required_pull_request_reviews": None,
    "restrictions": None,
}


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


def summary_shell_body():
    """Extract the advisory summary shell body from the workflow source."""
    lines = job_blocks()["agent-workflow-tests"]
    marker = "      - name: Record advisory observation"
    start = lines.index(marker)
    run = lines.index("        run: |", start)
    body = []
    for line in lines[run + 1:]:
        if line.startswith("      - "):
            break
        if line.startswith("          "):
            body.append(line[10:])
    return "\n".join(body)


def execute_summary(event="pull_request"):
    """Run the checked-in summary with fixture GitHub expression values."""
    substitutions = {
        "${{ github.event_name }}": event,
        "${{ steps.started.outputs.epoch }}": "100",
        "${{ steps.checkout.outcome }}": "success",
        "${{ steps.install_nix.outcome }}": "failure",
        "${{ steps.provision_just.outcome }}": "cancelled",
        "${{ steps.suite.outcome }}": "skipped",
    }
    body = summary_shell_body()
    for expression, value in substitutions.items():
        body = body.replace(expression, value)
    with tempfile.TemporaryDirectory() as directory:
        summary = Path(directory) / "summary"
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", body],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "GITHUB_STEP_SUMMARY": str(summary)},
        )
        return result.stdout, summary.read_text(encoding="utf-8")


def forwards_budget_args(body):
    """Whether the one budget call is the invocation that forwards `args`.

    Without the forwarding, `--base HEAD^1` and `--raise-label` are still built and
    still in the body, yet the check runs with neither.
    """
    calls = [line.strip() for line in body.splitlines() if BUDGET_COMMAND_RE.search(line)]
    return calls == [BUDGET_INVOCATION]


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


def has_measurement_contract(steps, name, step_id):
    """A measurement's continuation belongs to that named step alone."""
    owned = steps.get(name, [])
    return (
        f"        id: {step_id}" in owned
        and "        continue-on-error: true" in owned
    )


def has_summary_always_guard(steps):
    """The evidence writer must run even after an earlier measurement failed."""
    return "        if: always()" in steps.get("Record advisory observation", [])


def payload():
    return json.loads(PROTECTION.read_text(encoding="utf-8"))


def required_contexts():
    # D2 pins one provider-bound check in the exact payload; job assertions use
    # the context list derived from those checks.
    return [check["context"] for check in payload()["required_status_checks"]["checks"]]


class WorkflowShape(unittest.TestCase):
    def test_advisory_job_observes_each_step_and_writes_the_v1_record(self):
        blocks = job_blocks()
        self.assertIn("agent-workflow-tests", blocks)
        self.assertEqual(
            "agent-workflow-tests",
            job_names().get("Agent Workflow Tests (advisory)"),
        )
        body = job_body("agent-workflow-tests")
        self.assertIn("runs-on: ubuntu-24.04", body)
        self.assertIn("timeout-minutes: 45", body)
        self.assertIn("if: github.event_name != 'schedule'", body)
        self.assertNotIn("needs:", body)
        self.assertNotIn("strategy:", body)
        self.assertNotIn("matrix:", body)
        self.assertNotIn("conclusion", summary_shell_body())
        self.assertIn("github.event_name", summary_shell_body())
        self.assertIn("unknown", summary_shell_body())
        self.assertNotRegex(body, re.compile(r"^    continue-on-error:", re.MULTILINE))
        self.assertIn("nix shell --inputs-from . nixpkgs#just --command just --version", body)
        self.assertIn(
            "WORKFLOW_POLICY_SURFACE=source nix shell --inputs-from . nixpkgs#just "
            "--command just agent-workflow-tests",
            body,
        )

        expected_steps = {
            "Checkout": "checkout",
            "Install Nix": "install_nix",
            "Provision just": "provision_just",
            "Run agent workflow tests": "suite",
        }
        steps = step_blocks("agent-workflow-tests")
        for name, step_id in expected_steps.items():
            with self.subTest(step=name):
                self.assertIn(name, steps)
                owned = steps[name]
                self.assertIn(f"        id: {step_id}", owned)
                self.assertIn("        continue-on-error: true", owned)
                self.assertTrue(has_measurement_contract(steps, name, step_id))
                self.assertIn(f"steps.{step_id}.outcome", summary_shell_body())
        without_checkout = dict(steps)
        without_checkout.pop("Checkout", None)
        self.assertFalse(
            has_measurement_contract(without_checkout, "Checkout", "checkout"),
            "another step's continuation must not satisfy missing checkout",
        )
        self.assertTrue(has_summary_always_guard(steps))

        stdout, summary = execute_summary()
        self.assertEqual(stdout, summary)
        marker = "AGENT_WORKFLOW_OBSERVATION_V1="
        self.assertTrue(stdout.startswith(marker))
        record = json.loads(stdout.removeprefix(marker))
        self.assertEqual("agent-workflow-observation/v1", record["schema"])
        self.assertEqual("pull_request", record["trigger"])
        self.assertEqual(
            {
                "checkout": "success",
                "install_nix": "failure",
                "provision_just": "cancelled",
                "suite": "skipped",
            },
            record["raw"],
        )
        self.assertIs(type(record["elapsed_seconds"]), int)
        self.assertGreaterEqual(record["elapsed_seconds"], 0)

    def test_advisory_contract_rejects_step_and_summary_mutations(self):
        """The evidence seam fails closed for each independently owned YAML line."""
        steps = step_blocks("agent-workflow-tests")
        wrong_id = dict(steps)
        wrong_id["Checkout"] = [
            line.replace("id: checkout", "id: checkout_bogus")
            for line in wrong_id["Checkout"]
        ]
        self.assertFalse(has_measurement_contract(wrong_id, "Checkout", "checkout"))

        absent_always = dict(steps)
        absent_always["Record advisory observation"] = [
            line
            for line in absent_always["Record advisory observation"]
            if line.strip() != "if: always()"
        ]
        self.assertFalse(has_summary_always_guard(absent_always))

        misplaced_always = dict(absent_always)
        misplaced_always["Checkout"] = [
            *misplaced_always["Checkout"], "        if: always()"
        ]
        self.assertFalse(has_summary_always_guard(misplaced_always))

    def test_advisory_job_has_the_required_triggers_without_schedule(self):
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
            offenders = [
                line.strip()
                for line in job_blocks(path)[key]
                if GREEN_WITHOUT_WORK_RE.match(line)
            ]
            self.assertEqual(
                [],
                offenders,
                f"job {key!r} in {path.name} backs required context {context!r} and carries "
                f"{offenders}; each of these lets the job conclude success without "
                f"running its evaluation, so the gate would report green on a tree "
                f"nothing checked",
            )

    def test_each_required_job_still_runs_the_evaluation_it_exists_for(self):
        """Steps that run fine and evaluate nothing are the inverse of green-without-work:
        a `run:` body of `true`, another flake attribute, or a budget call that no
        longer forwards the arguments the step builds each leave every other assertion
        here green. Whether the step builds `--base` and `--raise-label` under the right
        event and label is BudgetWorkflowShape's behavioural test, not this one."""
        self.assertEqual(["Nix Eval", "Instruction Budget"], required_contexts())
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


if __name__ == "__main__":
    unittest.main()
