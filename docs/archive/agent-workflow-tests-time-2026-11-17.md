# Agent Workflow Tests, where the test step's time goes (2026-11-17)

This measures where the time of the `Run agent workflow tests` step of the `Agent Workflow Tests` job goes, over the 24 latest successful jobs that completed at or before 2026-11-17 00:00:00 UTC (they completed from 2026-11-16 18:32:57 to 23:49:14 UTC). It splits the step the [land lock queue measurement](land-lock-queue-2026-11-16.md) found to be almost all of every hold into the time before the suite starts, the time its members spend before their own timer, and the time they spend running tests. Only pull-request runs of `ci.yaml` are read, the ones a land lock holder waits on. Every figure is derived from the forge alone (the workflow runs, their jobs and the job logs); the tables below are the output of the program under Reproduce, pasted verbatim.

## Method

The step's own duration comes from the jobs API; the rest comes from the suite runner's lines in the job log ([ADR-delivery-006](../areas/delivery/adr/006-suite-members-run-in-parallel.md)). A job counts only when it is named `Agent Workflow Tests`, completed with success at or before the cutoff and has a step `Run agent workflow tests`. The window is the first page of 100 `ci.yaml` pull-request runs created before the cutoff, newest first, every attempt of each run read apart; the latest 24 jobs by completion time (then job id) are kept and printed oldest first. Lines inside a member's `suite-runner: begin` to `suite-runner: end` block are never read as the runner's own start, timing or summary lines, because a member's captured output can contain `suite-runner:` text of its own.

- Test step is the step's `completed_at` minus its `started_at`, in whole seconds from the API.
- Realization is the first `suite-runner: start` line minus the line `##[group]Run WORKFLOW_POLICY_SURFACE=` that opens the step: the time `nix shell` and `just` take before the suite launches its first member.
- Start-up is the suite wall's share of the member seconds spent before unittest's own timer: each `.py` member's wall (its timing row) minus its last `Ran N tests in X.XXXs` line, never below zero, summed, divided by the sum of the members' walls and multiplied by the suite wall (the summary's `wall=`). A `.sh` member has no such line and counts as Tests.
- Tests is the suite wall minus Start-up.
- Other is the Test step minus Realization minus the suite wall; it is what the log does not account for.
- Members and Jobs are the summary's `members=` and `jobs=`.
- CPU busy is the summary's CPU seconds over the suite wall times the smaller of Jobs and 4 vCPUs. Slots busy is the sum of the members' walls over the suite wall times Jobs.
- Order saving is the suite wall minus a longest-first schedule of that run's own member walls over Jobs slots (each member, longest first, ties by path, on the least-loaded slot; the schedule's makespan is the largest slot load). It is an estimate, not a bound: it assumes each member's wall does not change with its start order, and a longest-first schedule is not the best possible one, so it bounds nothing.
- Slots saving is the suite wall minus the larger of the longest member's wall and the CPU seconds over 4 vCPUs. It is a maximum: the wall cannot fall below the longest member or the CPU seconds spread over the 4 vCPUs, assuming no member runs faster than it did, so more concurrent members save at most that.
- Slots estimate is the suite wall minus a longest-first schedule of that run's own member walls over 6 slots (`SLOTS`, 1.5 times the 4 vCPUs), with each wall stretched by the larger of 1 and the CPU demand at 6 slots over the 4 vCPUs. The CPU demand at 6 slots is the run's CPU seconds over its suite wall, times 6 over its Jobs. So a member's wall is assumed not to change until the CPUs would be oversubscribed, then to stretch in proportion. It is an estimate, not a bound: it stretches every wall, waiting time included, and it assumes nothing else (memory, disk, the timing of a sensitive member) slows a member down when 6 run at once, which no log here shows.
- Cache saving is the Realization. It is a maximum: it assumes restoring the cache takes no time, which a restore step costs back in part.
- The summary rows are the median (`statistics.median`), the p90 (nearest rank: the `ceil(0.9 n)`th smallest) and the maximum of each column, computed from the printed cells. The run rows also check each log: a `.py` member's block with no `Ran` line, or a different number of timing rows than the summary's `members=`, stops the program with an error instead of printing. The member table lists, for each of the 15 members with the largest median wall, the number of jobs it appears in and the medians of its wall, CPU, start-up and tests seconds.

The known biases: Realization includes `just` and the runner's own start; Other carries the API's whole-second rounding, so it can be a few hundredths of a minute either way; Start-up is the time before unittest's own timer, so it holds the interpreter's start, imports and test collection; the 4 vCPUs are the comment in `ci.yaml`, not read from the log.

## Measurements

| Job | Run/attempt | Issue | Completed (UTC) | Test step (min) | Realization (min) | Start-up (min) | Tests (min) | Other (min) | Members | Jobs | CPU busy (%) | Slots busy (%) | Order saving (min) | Slots saving (min) | Cache saving (min) | Slots estimate (min) |
|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 133513702290 | 43928291880/1 | 1141 | 2026-11-16 18:32:57 | 8.9 | 0.1 | 0.1 | 8.7 | 0.0 | 167 | 4 | 57 | 100 | 0.0 | 3.8 | 0.1 | 2.9 |
| 133530632899 | 43933150827/1 | 1113 | 2026-11-16 18:59:31 | 8.1 | 0.1 | 0.1 | 7.9 | 0.0 | 167 | 4 | 56 | 100 | 0.0 | 3.5 | 0.1 | 2.7 |
| 133541997716 | 43936394560/1 | 1120 | 2026-11-16 19:18:00 | 8.1 | 0.1 | 0.1 | 7.9 | 0.0 | 167 | 4 | 55 | 100 | 0.0 | 3.6 | 0.1 | 2.7 |
| 133552524823 | 43939393803/1 | 1160 | 2026-11-16 19:35:14 | 8.1 | 0.1 | 0.1 | 7.9 | 0.0 | 167 | 4 | 55 | 100 | 0.0 | 3.6 | 0.1 | 2.7 |
| 133555746692 | 43940304816/1 | 1139 | 2026-11-16 19:41:59 | 9.7 | 0.2 | 0.1 | 9.4 | 0.0 | 167 | 4 | 55 | 100 | 0.0 | 4.2 | 0.2 | 3.2 |
| 133565710406 | 43943159392/1 | 1149 | 2026-11-16 19:57:33 | 8.8 | 0.2 | 0.1 | 8.6 | 0.0 | 167 | 4 | 55 | 100 | 0.0 | 3.9 | 0.2 | 2.9 |
| 133575644836 | 43945982712/1 | 1113 | 2026-11-16 20:15:20 | 10.3 | 0.2 | 0.1 | 10.0 | 0.0 | 167 | 4 | 51 | 100 | 0.0 | 4.9 | 0.2 | 3.4 |
| 133586706838 | 43949157656/1 | 1160 | 2026-11-16 20:31:22 | 8.1 | 0.1 | 0.1 | 7.9 | 0.0 | 167 | 4 | 55 | 99 | 0.1 | 3.6 | 0.1 | 2.7 |
| 133593043255 | 43950974002/1 | 1149 | 2026-11-16 20:43:35 | 10.0 | 0.2 | 0.1 | 9.6 | 0.0 | 167 | 4 | 55 | 100 | 0.0 | 4.4 | 0.2 | 3.3 |
| 133601160532 | 43953297109/1 | 1140 | 2026-11-16 20:55:23 | 8.2 | 0.1 | 0.1 | 8.1 | 0.0 | 167 | 4 | 56 | 100 | 0.0 | 3.6 | 0.1 | 2.7 |
| 133610862226 | 43956079273/1 | 1129 | 2026-11-16 21:13:09 | 9.7 | 0.2 | 0.1 | 9.4 | 0.0 | 167 | 4 | 55 | 100 | 0.0 | 4.2 | 0.2 | 3.2 |
| 133617864214 | 43958084836/1 | 1140 | 2026-11-16 21:25:31 | 10.5 | 0.1 | 0.1 | 10.2 | 0.0 | 167 | 4 | 65 | 100 | 0.0 | 3.7 | 0.1 | 3.5 |
| 133626644921 | 43960598195/1 | 1136 | 2026-11-16 21:39:11 | 9.5 | 0.2 | 0.1 | 9.2 | 0.0 | 167 | 4 | 56 | 100 | 0.0 | 4.1 | 0.2 | 3.1 |
| 133628143334 | 43961029020/1 | 1173 | 2026-11-16 21:40:37 | 8.4 | 0.1 | 0.1 | 8.2 | 0.0 | 167 | 4 | 57 | 100 | 0.0 | 3.6 | 0.1 | 2.8 |
| 133633463201 | 43962541317/1 | 1173 | 2026-11-16 21:56:22 | 11.8 | 0.2 | 0.1 | 11.6 | 0.0 | 167 | 4 | 35 | 81 | 2.3 | 5.3 | 0.2 | 5.3 |
| 133644048163 | 43965541126/1 | 1150 | 2026-11-16 22:08:14 | 8.4 | 0.1 | 0.1 | 8.2 | 0.0 | 167 | 4 | 57 | 100 | 0.0 | 3.6 | 0.1 | 2.8 |
| 133650803606 | 43967488767/1 | 1142 | 2026-11-16 22:19:50 | 8.5 | 0.1 | 0.1 | 8.3 | 0.0 | 169 | 4 | 52 | 99 | 0.1 | 4.0 | 0.1 | 2.8 |
| 133657353091 | 43969381103/1 | 1183 | 2026-11-16 22:33:34 | 10.8 | 0.2 | 0.1 | 10.5 | 0.0 | 170 | 4 | 65 | 100 | 0.0 | 3.8 | 0.2 | 3.6 |
| 133665061422 | 43971616527/1 | 1191 | 2026-11-16 22:47:13 | 10.6 | 0.1 | 0.1 | 10.3 | 0.0 | 170 | 4 | 65 | 100 | 0.0 | 3.7 | 0.1 | 3.5 |
| 133685393656 | 43977569866/1 | 1192 | 2026-11-16 23:24:30 | 9.5 | 0.2 | 0.1 | 9.2 | 0.0 | 170 | 4 | 57 | 100 | 0.0 | 4.0 | 0.2 | 3.1 |
| 133689830941 | 43978871596/1 | 1185 | 2026-11-16 23:32:15 | 8.3 | 0.1 | 0.1 | 8.1 | 0.0 | 171 | 4 | 55 | 99 | 0.1 | 3.7 | 0.1 | 2.8 |
| 133693510259 | 43979941207/1 | 1151 | 2026-11-16 23:40:47 | 9.6 | 0.2 | 0.1 | 9.3 | 0.0 | 172 | 4 | 57 | 100 | 0.0 | 4.1 | 0.2 | 3.1 |
| 133698122834 | 43981291243/1 | 1187 | 2026-11-16 23:49:03 | 8.4 | 0.1 | 0.1 | 8.2 | 0.0 | 170 | 4 | 57 | 100 | 0.0 | 3.6 | 0.1 | 2.8 |
| 133697728947 | 43981175227/1 | 1176 | 2026-11-16 23:49:14 | 9.4 | 0.2 | 0.1 | 9.2 | 0.0 | 171 | 4 | 56 | 100 | 0.0 | 4.1 | 0.2 | 3.1 |

| Figure | Median | p90 | Max |
|---|---:|---:|---:|
| Test step (min) | 9.2 | 10.6 | 11.8 |
| Realization (min) | 0.1 | 0.2 | 0.2 |
| Start-up (min) | 0.1 | 0.1 | 0.1 |
| Tests (min) | 8.9 | 10.3 | 11.6 |
| Other (min) | 0.0 | 0.0 | 0.0 |
| Members | 167.0 | 171.0 | 172.0 |
| Jobs | 4.0 | 4.0 | 4.0 |
| CPU busy (%) | 56.0 | 65.0 | 65.0 |
| Slots busy (%) | 100.0 | 100.0 | 100.0 |
| Order saving (min) | 0.0 | 0.1 | 2.3 |
| Slots saving (min) | 3.8 | 4.4 | 5.3 |
| Cache saving (min) | 0.1 | 0.2 | 0.2 |
| Slots estimate (min) | 3.0 | 3.5 | 5.3 |

| Member | Runs | Median wall (s) | Median CPU (s) | Median start-up (s) | Median tests (s) |
|---|---:|---:|---:|---:|---:|
| home/common/agent-skills/tests/test_deliver_standard_program.py | 24 | 138.4 | 133.9 | 0.3 | 138.2 |
| tests/test_forge_land_lock.py | 24 | 134.2 | 131.1 | 0.1 | 134.1 |
| tests/test_console_approve_service.py | 24 | 82.1 | 9.3 | 0.2 | 81.9 |
| tests/test_verify_pending_owner.py | 24 | 70.3 | 54.0 | 0.2 | 70.1 |
| home/common/agent-skills/tests/test_deliver_batch_program.py | 24 | 68.4 | 65.2 | 0.2 | 68.2 |
| tests/test_console_service.py | 24 | 64.7 | 2.8 | 0.2 | 64.5 |
| tests/test_console_manager_service.py | 24 | 53.2 | 5.9 | 0.2 | 53.0 |
| tests/test_verify_pending.py | 24 | 53.0 | 33.9 | 0.2 | 52.8 |
| tests/test_guard_policy.py | 24 | 52.2 | 47.7 | 0.1 | 52.0 |
| tests/test_release_driver.py | 24 | 51.4 | 48.6 | 0.2 | 51.3 |
| tests/test_release_sync.py | 24 | 50.6 | 48.0 | 0.1 | 50.5 |
| tests/test_console_sprint_command.py | 24 | 45.5 | 25.3 | 0.2 | 45.3 |
| tests/test_console_messages.py | 24 | 43.7 | 1.0 | 0.2 | 43.5 |
| tests/test_console_register_service.py | 24 | 43.2 | 5.2 | 0.2 | 43.0 |
| tests/test_console_stops.py | 24 | 43.0 | 2.1 | 0.2 | 42.9 |

Jobs: 24, completed 2026-11-16 18:32:57 to 2026-11-16 23:49:14 (UTC).

Reading the summary: the test step has a median of 9.2 minutes (p90 10.6, maximum 11.8), and almost all of it is the members running tests: a median 8.9 minutes of Tests against 0.1 of Realization and 0.1 of Start-up, with Other at 0.0. The suite runs a median 167 members on 4 jobs; the slots are full (Slots busy 100% at the median) while the CPU is not (CPU busy 56% at the median, 65% at most), so the members wait on something other than the CPU for the rest. The slowest members are `home/common/agent-skills/tests/test_deliver_standard_program.py` (median wall 138.4 s) and `tests/test_forge_land_lock.py` (134.2 s), both CPU-bound, and `tests/test_console_approve_service.py` (82.1 s wall for 9.3 s CPU) leads the members that mostly wait. Order saving has a median of 0.0 minutes (p90 0.1, maximum 2.3), so the members' start order already follows their timings; Slots saving has a median of 3.8 minutes (p90 4.4, maximum 5.3); Cache saving has a median of 0.1 minutes (maximum 0.2). Slots estimate, the saving at 6 jobs under the model above, has a median of 3.0 minutes (p90 3.5, maximum 5.3). The 24 test steps of this window are slower than the 8.5 minutes median of the [land lock queue measurement](land-lock-queue-2026-11-16.md), which covered other landings.


## Reproduce

This needs an authenticated `gh` and `python3`; it prints the Measurements section's tables and its `Jobs:` line exactly. The window and the cutoff are fixed, so a re-run prints the same rows while GitHub keeps the job logs (90 days by default).

```sh
python3 -I - <<'PY'
import json
import math
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone

REPO = "fagenorn/nix-config"
R = "repos/" + REPO
JOB = "Agent Workflow Tests"
STEP = "Run agent workflow tests"
CUTOFF = "2026-11-17T00:00:00Z"
ROWS = 24
TOP = 15
VCPUS = 4
SLOTS = 6
MARK = "##[group]Run WORKFLOW_POLICY_SURFACE="
HEADERS = [
    "Job", "Run/attempt", "Issue", "Completed (UTC)", "Test step (min)", "Realization (min)",
    "Start-up (min)", "Tests (min)", "Other (min)", "Members", "Jobs", "CPU busy (%)",
    "Slots busy (%)", "Order saving (min)", "Slots saving (min)", "Cache saving (min)",
    "Slots estimate (min)",
]
STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.(\d+)Z(?: (.*))?$", re.S)
BEGIN = re.compile(r"^suite-runner: begin (\S+)$")
RAN = re.compile(r"^Ran \d+ tests? in ([0-9.]+)s$")
TIMING = re.compile(r"^suite-runner:\s+([0-9.]+)s wall\s+([0-9.]+)s cpu (passed|failed) (\S+)$")
SUMMARY = re.compile(
    r"^suite-runner: summary members=(\d+) passed=(\d+) failed=(\d+) jobs=(\d+)"
    r" wall=([0-9.]+)s cpu=([0-9.]+)s$"
)


def gh_json(path):
    done = subprocess.run(
        ["gh", "api", path], check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return json.loads(done.stdout)


def gh_text(path):
    done = subprocess.run(
        ["gh", "api", path], check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return done.stdout


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def seconds(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def fmt(value, digits=1):
    text = f"{value:.{digits}f}"
    return text[1:] if text.startswith("-") and float(text) == 0 else text


def parse_log(job_id, text):
    """Mark, first start and summary outside member blocks, the timing rows, each block's last Ran."""
    if text.startswith("\ufeff"):
        text = text[1:]
    mark = start = summary = None
    rows = {}
    ran = {}
    current = None
    for line in text.split("\n"):
        found = STAMP.match(line.rstrip("\r"))
        if not found:
            continue
        # Integer 100 ns ticks keep the differences exact.
        ticks = round(seconds(found[1] + "Z")) * 10**7 + int(found[2].ljust(7, "0")[:7])
        body = found[3] or ""
        if current is not None:
            if body.startswith(f"suite-runner: end {current} "):
                current = None
            elif RAN.match(body):
                ran[current] = float(RAN.match(body)[1])
            continue
        begin = BEGIN.match(body)
        if begin:
            current = begin[1]
            ran[current] = None
        elif mark is None:
            if body.startswith(MARK):
                mark = ticks
        elif start is None and body.startswith("suite-runner: start "):
            start = ticks
        elif TIMING.match(body):
            wall, cpu, _, member = TIMING.match(body).groups()
            rows[member] = (float(wall), float(cpu))
        elif SUMMARY.match(body):
            summary = SUMMARY.match(body).groups()
    if mark is None or start is None or summary is None or not rows:
        fail(f"job {job_id}: the log has no mark, start line, summary or timing rows")
    if len(rows) != int(summary[0]):
        fail(f"job {job_id}: {len(rows)} timing rows but the summary says members={summary[0]}")
    for member in rows:
        if member not in ran:
            fail(f"job {job_id}: no block for member {member}")
        if member.endswith(".py") and ran[member] is None:
            fail(f"job {job_id}: no Ran line in the block of member {member}")
    return (start - mark) / 10**7, summary, rows, ran


def longest_first(walls, slots):
    loads = [0.0] * slots
    for wall in sorted(walls, reverse=True):
        loads[loads.index(min(loads))] += wall
    return max(loads)


def measure(job, run, attempt):
    step = next(s for s in job["steps"] if s["name"] == STEP)
    step_seconds = seconds(step["completed_at"]) - seconds(step["started_at"])
    real, summary, rows, ran = parse_log(job["id"], gh_text(f"{R}/actions/jobs/{job['id']}/logs"))
    members, jobs, wall, cpu = int(summary[0]), int(summary[3]), float(summary[4]), float(summary[5])
    starts = {m: max(0.0, rows[m][0] - ran[m]) for m in rows if ran[m] is not None}
    total_wall = sum(w for w, _ in rows.values())
    startup = wall * sum(starts.values()) / total_wall / 60
    lpt = longest_first([rows[m][0] for m in sorted(rows, key=lambda m: (-rows[m][0], m))], jobs)
    slots = wall - max(max(w for w, _ in rows.values()), cpu / VCPUS)
    stretch = max(1.0, cpu / wall * SLOTS / jobs / VCPUS)
    more = longest_first([w * stretch for w, _ in rows.values()], SLOTS)
    issue = re.search(r"issue-(\d+)-", run["head_branch"] or "")
    cells = [
        str(job["id"]),
        f"{run['id']}/{attempt}",
        issue[1] if issue else "-",
        job["completed_at"].replace("T", " ").rstrip("Z"),
        fmt(step_seconds / 60),
        fmt(real / 60),
        fmt(startup),
        fmt(wall / 60 - startup),
        fmt((step_seconds - real - wall) / 60),
        str(members),
        str(jobs),
        fmt(100 * cpu / (wall * min(jobs, VCPUS)), 0),
        fmt(100 * total_wall / (wall * jobs), 0),
        fmt((wall - lpt) / 60),
        fmt(slots / 60),
        fmt(real / 60),
        fmt((wall - more) / 60),
    ]
    return cells, rows, starts


def main():
    listing = gh_json(
        f"{R}/actions/workflows/ci.yaml/runs?event=pull_request&created=<{CUTOFF}&per_page=100"
    )
    chosen = []
    for run in listing["workflow_runs"]:
        for attempt in range(1, run["run_attempt"] + 1):
            answer = gh_json(f"{R}/actions/runs/{run['id']}/attempts/{attempt}/jobs")
            for job in answer["jobs"]:
                if (
                    job["name"] == JOB
                    and job["status"] == "completed"
                    and job["conclusion"] == "success"
                    and job["completed_at"] <= CUTOFF
                    and any(s["name"] == STEP for s in job["steps"])
                ):
                    chosen.append((job["completed_at"], job["id"], job, run, attempt))
    if len(chosen) < ROWS:
        fail(f"only {len(chosen)} successful {JOB} jobs, need {ROWS}")
    chosen = sorted(chosen, key=lambda c: (c[0], c[1]))[-ROWS:]
    table = []
    members = {}
    for _, _, job, run, attempt in chosen:
        cells, rows, starts = measure(job, run, attempt)
        table.append(cells)
        for member, (wall, cpu) in rows.items():
            entry = members.setdefault(member, {"wall": [], "cpu": [], "start": [], "tests": []})
            entry["wall"].append(wall)
            entry["cpu"].append(cpu)
            if member in starts:
                entry["start"].append(starts[member])
                entry["tests"].append(wall - starts[member])

    def row(cells):
        return "| " + " | ".join(cells) + " |"

    print(row(HEADERS))
    print("|---:|---|---:|---|" + "---:|" * 13)
    for cells in table:
        print(row(cells))
    print()
    print("| Figure | Median | p90 | Max |")
    print("|---|---:|---:|---:|")
    for index in range(4, 17):
        col = [float(cells[index]) for cells in table]
        ranked = sorted(col)
        print(row([
            HEADERS[index],
            fmt(statistics.median(col)),
            fmt(ranked[math.ceil(0.9 * len(col)) - 1]),
            fmt(max(col)),
        ]))
    print()
    print("| Member | Runs | Median wall (s) | Median CPU (s) | Median start-up (s) | Median tests (s) |")
    print("|---|---:|---:|---:|---:|---:|")
    top = sorted(members, key=lambda m: (-statistics.median(members[m]["wall"]), m))[:TOP]
    for member in top:
        entry = members[member]

        def med(name):
            return fmt(statistics.median(entry[name])) if entry[name] else "-"

        print(row([member, str(len(entry["wall"])), med("wall"), med("cpu"), med("start"), med("tests")]))
    print()
    print(f"Jobs: {len(table)}, completed {table[0][3]} to {table[-1][3]} (UTC).")


main()
PY
```

## Proposal

Three speed-ups keep every member of the suite and change no branch protection, and the summary table gives each one a figure. Reordering the members by fresh timings has a median `Order saving (min)` of 0.0 minutes, an estimate. Running more members at once than the runner has vCPUs has a median `Slots saving (min)` of 3.8 minutes, a maximum, and a median `Slots estimate (min)` of 3.0 minutes at 6 jobs, an estimate. Caching the `nix shell` closure has a median `Cache saving (min)` of 0.1 minutes, a maximum. The pick compares two maxima, `Slots saving (min)` and `Cache saving (min)`, with one estimate, `Order saving (min)`: a maximum is the most a change could save, not what it will save. The largest median is 3.8 minutes, so the proposal is to run more members at once than the runner has vCPUs.

**What changes.** The slots are full (Slots busy 100% at the median) while the 4 vCPUs are idle for the rest of the time (CPU busy 56% at the median), because members such as `tests/test_console_approve_service.py` wait on something other than the CPU. A follow-up raises the job count that `.github/workflows/ci.yaml` gives the suite runner through `SUITE_RUNNER_JOBS` to 6, so a waiting member no longer holds a slot that a CPU-bound member could use. It also amends [ADR-delivery-006](../areas/delivery/adr/006-suite-members-run-in-parallel.md) (`docs/areas/delivery/adr/006-suite-members-run-in-parallel.md`), whose Consequence says CI sets 4, the runner's vCPUs; a job count above 4 (6 here) needs its own measurement for the timing-sensitive members, because more concurrent members slow each one down. No member is merged, dropped or made optional, and each still runs in its own process. This document only proposes it; adopting it is a later issue.

**Expected saving per run (a maximum, not an estimate):** at most 3.8 min, the median of `Slots saving (min)`. It is the suite wall minus the larger of its `longest member` and its CPU seconds spread over the `4 vCPUs`: the wall cannot fall below either of them, assuming no member runs faster than it did. The realised saving is smaller, because members run slower when more of them share the CPUs. The saving applies to every run: each queued pull request runs the check again after each landing ahead of it ([land lock queue measurement](land-lock-queue-2026-11-16.md)), so the most it could save applies to every run of a held pull request, and the p90 of the per-run maximum is 4.4 minutes.

**Estimated saving at 6 jobs:** 3.0 min, the median of `Slots estimate (min)` (p90 3.5, maximum 5.3), an estimate. It is the suite wall minus a longest-first schedule of the run's own member walls over 6 slots, each stretched only when 6 members would ask the 4 vCPUs for more than they have, so it is 0.8 min under the maximum. It holds only if no member runs slower than the model says when 6 run at once; the logs of this window all ran 4 at once and cannot show that, so the follow-up measures the real saving by running at 6 before adopting it, and the saving could be smaller, down to none.

**Why every test and the required check stay.** `Nix Eval`, `Agent Workflow Tests` and `Instruction Budget` stay required by `.github/branch-protection.json` with `strict` true, and the check keeps its name and its place in the workflow. Every one of the 171 suite members still runs, in its own process and on the same head, with the same pass condition, so nothing that is tested today goes untested. Dropping, moving or making optional any test or the check would reopen what `.agents/knowledge/rejections/ungated-agent-merges.md` refuses, and this proposal does none of them.

## Alternatives considered

- **Reordering the members by fresh timings, `Order saving (min)`.** Its median is 0.0 min, an estimate, not a bound: it assumes each member's wall does not change with its start order. It changes `python/agent_tools/delivery/suite_timings.json` only, but the members' start order already follows their timings, so there is nothing to gain at the median (p90 0.1, maximum 2.3).
- **Caching the `nix shell` closure, `Cache saving (min)`.** Its median is at most 0.1 min, a maximum that assumes restoring the cache takes no time, which a restore step costs back in part. It changes `.github/workflows/ci.yaml` only, and it is the smallest change, but the realization it removes is already a fraction of a minute.
- **Fewer processes, by merging members, `Start-up (min)`.** Its median is 0.1 min, the time members spend before unittest's own timer, so merging members saves at most that. It is less safe: it contradicts ADR-delivery-006's one process per member, which keeps one member's failure, state and timing from touching another's.
- **A larger runner.** More vCPUs would shrink the CPU-bound members' wall and the CPU seconds bound that `Slots saving (min)` uses, but it is paid, from the owner's money, and the saving is not measured here.
- **Dropping, moving or making optional any test or the check.** Refused by `.agents/knowledge/rejections/ungated-agent-merges.md`: the required check and every test in it are what make a merge safe, so a saving bought this way is not one.
