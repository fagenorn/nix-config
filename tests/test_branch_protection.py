"""Pin the CI required-status-check contract.

The context `.github/branch-protection.json` requires and the job name GitHub
reports are the same string held in two files that GitHub will never reconcile for
us — and once `just protect-main` has been applied, a rename on
either side raises no error anywhere: it leaves `main` waiting forever on a context
that never reports, with nothing in the UI pointing at the cause. These tests are
the only offline place that failure can surface.
"""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yaml"
PROTECTION = REPO_ROOT / ".github" / "branch-protection.json"

# ci.yaml's indentation convention: workflow name at column 0, job keys at two
# spaces, job attributes at four, step attributes at six or more. PyYAML is not a
# guaranteed dependency on this host, so the convention is the parser.
JOB_KEY_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
JOB_NAME_RE = re.compile(r"^    name:\s*(\S.*?)\s*$")
JOB_IF_RE = re.compile(r"^    if:\s*(\S.*?)\s*$")
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


def workflow_lines():
    return WORKFLOW.read_text(encoding="utf-8").splitlines()


def _top_level_block(key):
    """Lines under a column-0 `key:`, up to the next column-0 key."""
    lines = workflow_lines()
    header = f"{key}:"
    if header not in lines:
        raise AssertionError(f"{WORKFLOW} has no top-level `{header}`")
    out = []
    for line in lines[lines.index(header) + 1:]:
        if TOP_LEVEL_KEY_RE.match(line):
            break
        out.append(line)
    return out


def job_blocks():
    """Map each job key in `jobs:` to the lines of its block."""
    blocks = {}
    current = None
    for line in _top_level_block("jobs"):
        match = JOB_KEY_RE.match(line)
        if match:
            current = match.group(1)
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return blocks


def job_body(key):
    """The job's block with comment lines dropped.

    A `#`-leading line is a YAML comment at job level and a shell comment inside a
    `run: |` body — under neither reading is it something the runner executes, so a
    comment quoting the evaluation must not satisfy an assertion that the job still
    runs it.
    """
    return "\n".join(
        line for line in job_blocks()[key] if not line.lstrip().startswith("#")
    )


def job_names():
    """Map each job's reported check-run name to its job key."""
    names = {}
    for key, block in job_blocks().items():
        for line in block:
            match = JOB_NAME_RE.match(line)
            if match:
                names[match.group(1)] = key
                break
    return names


def trigger_block(name):
    """Lines under `  <name>:` inside the `on:` block, or None if absent."""
    block = _top_level_block("on")
    header = f"  {name}:"
    if header not in block:
        return None
    out = []
    for line in block[block.index(header) + 1:]:
        if re.match(r"^  \S", line):
            break
        out.append(line)
    return out


def trigger_branches(name):
    """The `branches:` list of a trigger, or None if the trigger or the key is absent.

    Scoped to the `branches:` subtree on purpose: a bare `- main` anywhere under the
    trigger would also satisfy a `paths:` or `paths-ignore:` list, which gates nothing.
    """
    block = trigger_block(name)
    if block is None or "    branches:" not in block:
        return None
    out = []
    for line in block[block.index("    branches:") + 1:]:
        if not re.match(r"^      - ", line):
            break
        out.append(line.strip()[2:].strip())
    return out


def job_if_expression(key):
    """The job's four-space `if:` expression, or None when it has none."""
    for line in job_blocks()[key]:
        match = JOB_IF_RE.match(line)
        if match:
            return match.group(1)
    return None


def payload():
    return json.loads(PROTECTION.read_text(encoding="utf-8"))


def required_contexts():
    return payload()["required_status_checks"]["contexts"]


class WorkflowShape(unittest.TestCase):
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
        names = job_names()
        for context in contexts:
            self.assertIn(context, names)
            expression = job_if_expression(names[context])
            self.assertIn(
                expression,
                (None, "github.event_name != 'schedule'"),
                f"job {names[context]!r} backs required context {context!r} and "
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
        names = job_names()
        blocks = job_blocks()
        for context in contexts:
            self.assertIn(context, names)
            key = names[context]
            offenders = [
                line.strip()
                for line in blocks[key]
                if GREEN_WITHOUT_WORK_RE.match(line)
            ]
            self.assertEqual(
                [],
                offenders,
                f"job {key!r} backs required context {context!r} and carries "
                f"{offenders}; each of these lets the job conclude success without "
                f"running its evaluation, so the gate would report green on a tree "
                f"nothing checked",
            )

    def test_required_job_still_runs_the_evaluation_it_exists_for(self):
        """The pin above catches a job that concludes success without running its
        steps. This catches the inverse of *that*: steps that run fine and evaluate
        nothing. Replacing the step's `run:` body with `true` — or pointing it at a
        different flake attribute — leaves every other assertion in this file green
        while `Nix Eval` keeps certifying a tree it never looked at."""
        contexts = required_contexts()
        # Ties this assertion to the required context rather than to a job that
        # merely happens to be named this. D2 pins `contexts` to exactly this one;
        # if that ever widens, this test must be rewritten rather than extended,
        # because a second required context would not be a Nix evaluation.
        self.assertEqual(["Nix Eval"], contexts)
        names = job_names()
        self.assertIn("Nix Eval", names)
        body = job_body(names["Nix Eval"])
        self.assertRegex(
            body,
            NIX_EVAL_COMMAND_RE,
            f"job {names['Nix Eval']!r} backs the required context 'Nix Eval' but "
            f"runs no `nix eval`; the gate would report green without evaluating "
            f"anything",
        )
        self.assertIn(
            EVALUATED_ATTRIBUTE,
            body,
            f"job {names['Nix Eval']!r} no longer evaluates "
            f"{EVALUATED_ATTRIBUTE!r}; whatever it evaluates instead, a PR that "
            f"breaks the NixOS host config would still merge green",
        )


class RequiredContexts(unittest.TestCase):
    def test_every_required_context_is_a_job_name(self):
        contexts = required_contexts()
        self.assertTrue(contexts, "branch protection requires at least one context")
        names = job_names()
        for context in contexts:
            self.assertIn(
                context,
                names,
                f"required context {context!r} in {PROTECTION.name} matches no job "
                f"`name:` in {WORKFLOW.name} (found {sorted(names)}); merges to main "
                f"would block forever waiting for it",
            )

    def test_required_jobs_are_plain_jobs(self):
        """A matrix job reports as `name (value)` and a reusable workflow as
        `caller / callee`; either decouples the reported check-run name from the
        required context while a pure string comparison still passes."""
        contexts = required_contexts()
        self.assertTrue(contexts, "branch protection requires at least one context")
        names = job_names()
        blocks = job_blocks()
        for context in contexts:
            self.assertIn(
                context,
                names,
                f"required context {context!r} matches no job `name:` in "
                f"{WORKFLOW.name} (found {sorted(names)})",
            )
            key = names[context]
            offenders = [
                line.strip() for line in blocks[key] if RENAMING_KEY_RE.match(line)
            ]
            self.assertEqual(
                [],
                offenders,
                f"job {key!r} backs required context {context!r} and must stay a "
                f"plain job; found {offenders}",
            )


class ProtectionPayload(unittest.TestCase):
    def test_payload_carries_every_key_the_api_requires(self):
        """The API rejects a body missing any of the four keys with a 422 at apply
        time — long after the hand-edit that dropped one."""
        data = payload()
        self.assertEqual(REQUIRED_PAYLOAD_KEYS, set(data))
        self.assertIs(True, data["enforce_admins"])
        self.assertIs(False, data["required_status_checks"]["strict"])
        # D2: exactly one required context. A second one doubles the brick surface.
        self.assertEqual(["Nix Eval"], data["required_status_checks"]["contexts"])
        # D10: present and explicitly null. A non-null value here would block every
        # solo and unattended merge, which is the opposite of the issue's ask.
        self.assertIsNone(data["required_pull_request_reviews"])
        self.assertIsNone(data["restrictions"])


if __name__ == "__main__":
    unittest.main()
