"""The `suite-test-failures` verify check.

`suite-test-failures --repo R --workflow W --job J --branch B --merge SHA --n N --test NAME`
(`suite_test_failures`), run through the wrapper `home/common/verify-pending/checks/suite-test-failures`
as `python -m agent_tools.verification.suite_test_failures`, is met when no counted run of the first N
from the merge's run on has a failed attempt of job J whose log names the test NAME as failed. The
after runs are the push runs of the workflow on the branch, in (created_at, run id) order from the
merge's run on: a run ordered before the merge's run is skipped (the merge's run is the earliest push run
listed at `--merge`, none: 75; fewer than N counted: 75), no before run is read, and only the log of a
`failure` attempt is read. A log line names the test when, after the leading BOM and the line's
timestamp are dropped, it reads `ERROR: NAME (` or `FAIL: NAME (` with NAME exactly the test (a name
that only starts with it, or a subtest suffix after the parenthesis, is matched on the name alone);
every line counts, including those between `suite-runner: begin` and `suite-runner: end`, and a log
that names the test is a failure with or without a complete summary. A failed attempt that does not
name the test is cleared only when its log has a complete summary (the test ran to its end); without
one the run is listed in `unattributed` and is never passed, unless another failed attempt of that run
names the test, which settles the run as a failure. Exit 0 when neither `failures` nor `unattributed`
is set, 1 when one is, 75 as above, 2 on a forge error. The report is `{"merge_run", "after", "test",
"failures": [run ids], "unattributed": [run ids]}`, one JSON line, each run id at most once and in
after order. A bad `--repo`, an empty `--workflow`, `--job`, `--branch` or `--test`, a `--merge` that
is not 40 lowercase hex characters, or an `--n` that is not a positive integer is a usage error (2).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence

from agent_tools.system import forge_api
from agent_tools.verification.verify_checks import (
    LOG_STAMP, _counted_pages, _issue_number, _merge_sha, _nonempty, _repo, _suite_attempts,
    _suite_log, _suite_run, _suite_runs, suite_results)

TEST_FAILURE = re.compile(r"^(?:ERROR|FAIL): (\S+) \(")


def suite_test_failures(repo: str, workflow: str, job: str, branch: str, merge: str, n: int,
                        test: str) -> tuple[int, dict]:
    """Met when no counted run from the merge's run on has a failed attempt of `job` that names `test`."""
    listing = f"repos/{repo}/actions/workflows/{workflow}/runs?branch={branch}&event=push"
    report: dict = {"merge_run": None, "after": [], "test": test, "failures": [], "unattributed": []}
    at_merge = _suite_runs(forge_api.api_get(f"{listing}&head_sha={merge}&per_page=100"))
    if not at_merge:
        return 75, report
    report["merge_run"] = at_merge[0][1]
    after: list[tuple[int, list[tuple[int, str]]]] = []
    pages = _counted_pages(forge_api.api_pages(f"{listing}&created=>={at_merge[0][3]}&per_page=100"),
                           "workflow_runs", "run listing")
    for run in sorted(_suite_run(entry) for entry in pages):
        if run[:2] < at_merge[0][:2]:
            continue
        pending, counted = _suite_attempts(repo, job, run)
        if pending:
            break
        if counted:
            after.append((run[1], counted))
            if len(after) == n:
                break
    report["after"] = [run_id for run_id, _ in after]
    if len(after) < n:
        return 75, report
    for run_id, counted in after:
        silent = False
        for job_id, conclusion in counted:
            if conclusion != "failure":
                continue
            log = _suite_log(repo, job_id)
            names = (TEST_FAILURE.match(LOG_STAMP.sub("", line, count=1))
                     for line in log.removeprefix("﻿").splitlines())
            if any(found and found[1] == test for found in names):
                report["failures"].append(run_id)
                break
            silent = silent or suite_results(log) is None
        else:
            if silent:
                report["unattributed"].append(run_id)
    return (1 if report["failures"] or report["unattributed"] else 0), report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="suite-test-failures")
    parser.add_argument("--repo", type=_repo, required=True)
    parser.add_argument("--workflow", type=_nonempty, required=True)
    parser.add_argument("--job", type=_nonempty, required=True)
    parser.add_argument("--branch", type=_nonempty, required=True)
    parser.add_argument("--merge", type=_merge_sha, required=True)
    parser.add_argument("--n", type=_issue_number, required=True)  # a positive integer
    parser.add_argument("--test", type=_nonempty, required=True)
    args = parser.parse_args(argv)
    try:
        code, report = suite_test_failures(args.repo, args.workflow, args.job, args.branch,
                                           args.merge, args.n, args.test)
    except forge_api.ForgeError as error:
        print(f"verify-checks: forge_error: {error.code}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
