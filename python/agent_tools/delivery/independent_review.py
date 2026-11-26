"""`independent-review`: the configured Codex diff review of a delivery range, as a platform command.

`independent-review code --repo-root <root> --issue <n> --worktree-path <wt> --branch <b>
--integration-branch <int> --acceptance <JSON list> --routed-files <JSON list of paths> --head <sha>` prints one
compact JSON line, keys sorted, `{detail, findings, raw_summary, verdict}`, and exits 0. `verdict` is
`pass`, `findings`, `none` or `unavailable`; `findings` is a list of `{failing_input, file, severity,
summary}` that every reply carries. A usage error is exit 2 and a resolver refusal exit 1, each with
`verdict` `error` and an empty `findings`. The contract is `codex-collaboration`'s SKILL.md ("Direct
configured review") and DIFF-REVIEW.md; the tail model and effort are the skill's, and a test pins them.

Routing reads `capabilities["review.code"]["state"]` of the resolved project: `unsupported` is
`none` and starts no process; `blocked` is `unavailable`, its detail naming the `reason_code`;
`available` selects `bindings.workflow.review.code` and its entry in `bindings.commands`.

The entry's argv must be the companion shape: the basename of `argv[0]` is `codex-companion`,
`argv[1]` is `task`, and the rest is exactly `--reviewer diff-review` plus an optional `--fresh`,
in either order. Otherwise the review is `unavailable` with no process, the detail `binding shape
error: diff-review review_id <id> argv <argv>: expected codex-companion task [--fresh] --reviewer
diff-review; <first failing cause>` (causes in order: executable, subcommand, reviewer,
unsupported token).

`--head` and `--merge-base` are the commits the files were routed for (the router's `head` and
`merge_base`, each a full commit id). The range is `--merge-base` to `--head` in the worktree, and
the review reads no integration ref, so a fetch after routing changes neither end. It is `unavailable`
for a worktree whose `HEAD` is no longer `--head` (a commit landed after routing), the detail `head
moved since routing`, for a merge base that is no commit or is not an ancestor of the head (`merge base
<sha> is not an ancestor of <head>`), before any process starts. `diff-scope` measures it (`product.changed_files` as `M`,
`files[].path`, `files[].changed_lines`). More than `FILE_BUDGET` files (strictly) is cut into
consecutive slices of that many `files[].path` entries in emitted order, each dispatched once, so
every product file is reviewed once; exactly that many, or none, is dispatched whole. No measurement
(a non-zero exit, unparseable output, a selected path holding a newline) dispatches whole with
scope `unmeasured`, never a failure. Slices run at once, one thread each, and a retry runs in its
thread; the reply lists them in slice order.

The packet goes on stdin, with no positional argument and no diff: the operation name, invocation
directory, worktree, branch and shas; the scope; the criteria and issue number (routing context);
the declared verification ids (context only) and the `AGENTS.md`/`CLAUDE.md` that exist at the
worktree root; the routed files (`--routed-files`, required: a JSON list of path strings, written as
`Routed files:` one per line where the standards paths once stood, with no fallback); the read-only
rules; and the reviewer output contract as a requirement. A slice's packet is DIFF-REVIEW.md's
over-budget form: a scoped scope paragraph, the slice's paths with their `changed_lines` and the
per-path `git diff` protocol, and the requirement that the review start with `scoped to <N> of <M>
product files`.

The invocation is `entry["argv"] + ["--model", MODEL, "--effort", EFFORT, "--cwd", <worktree>,
"--json"]` in `entry["cwd"]`, with the entry's declared env names removed, for `ATTEMPT_SECONDS`.
A slice's reply is valid when: exit 0; stdout is one JSON object; `status` is `0`; `touchedFiles`
is `[]`; `runtime.model` and `runtime.reasoningEffort` are `MODEL` and `EFFORT`; and `rawOutput`
is a non-empty string holding the headings `Critical`, `Important` and `Minor`. A failure is
retried once with the same packet; a second is `unavailable` with the detail `<class>: <message>`,
the class `runtime` (a non-zero exit, `status` other than 0, a timeout), `payload` (not one object,
a mismatched field) or `schema` (a heading missing), the message the payload's `error` when it is
a string, else the last non-blank stderr line (a description of the failure when there is neither).

A finding is a bullet (`- ` or `* `) under a heading, continued by the non-bullet lines after it;
a section whose text is `None.` has none; the severity is the heading in lower case; `file` is the
first token shaped `path:line`, else empty.

`findings` is every completed slice's findings in slice order, unmodified. The verdict is
`unavailable` when any slice fails its retry (the first failed slice's detail, the completed
slices' findings kept), else `findings` when a critical or important finding exists, else `pass`.
`raw_summary` is `scope: full`, `scope: unmeasured` or `scope: <K> slices over <M> product files`;
`base <base> head <head>`; for a sliced review one `slice <i>: scoped to <N> of <M> product files;
<assessment>` line per slice; and `failed slices: <i>[, <j>]` when any failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_tools.delivery.issue_setup import REPOSITORY_ENV
from agent_tools.project_contract import resolve_project
from agent_tools.project_contract.agent_platform import PLATFORM_COMMANDS
from agent_tools.system.siblings import sibling_argv

OPERATION = "diff-review"
MODEL = "gpt-6.2-astra"
EFFORT = "high"
FILE_BUDGET = 20
ATTEMPT_SECONDS = 1700
GIT_TIMEOUT = 120
MEASURE_TIMEOUT = 300
COMPANION = "codex-companion"
REVIEWER = PLATFORM_COMMANDS["codex-diff-review"]["argv"][-2]   # the one definition of the flag
EXPECTED_SHAPE = f"expected {COMPANION} task [--fresh] --reviewer {OPERATION}"
HEADINGS = ("Critical", "Important", "Minor")
FILE_TOKEN = re.compile(r"[A-Za-z0-9_./-]+:[0-9]+")
TOKEN_EDGES = "()[]{}<>`'\",.;"

READ_ONLY_RULES = (
    "Remain read-only: do not edit files, mutate Git, create commits, branches or worktrees, "
    "change issues or PRs, install dependencies or ship. Use read-only repository and Git "
    "inspection of live HEAD files, within the assigned scope. A limit of your own sandbox is "
    "never a finding: report what you could not verify as an unreadable artifact or unresolved "
    "unknown. An artifact defect exposed by a failed command is still a finding, anchored in "
    "the artifact with evidence.")
WHOLE_SCOPE = (
    "Review the diff {base}..{head} in the worktree for code correctness (bugs, boundary error "
    "handling, dead branches, assertions that fail to pin the documented contract, DRY against "
    "existing helpers, cross-task integration), and any acceptance criterion below that the diff "
    "leaves unmet.")
SCOPED_SCOPE = (
    "Review the product files listed under `Scoped files` as changed across {base}..{head} in the "
    "worktree for code correctness (bugs, boundary error handling, dead branches, assertions that "
    "fail to pin the documented contract, DRY against existing helpers, cross-task integration), "
    "and any acceptance criterion below that the diff leaves unmet.\n\n"
    "This is a scoped review: {n} of {m} changed product files, one slice of the range. Files "
    "outside the list are not under review in this pass; do not treat their absence from the list "
    "as evidence they are clean. Every finding you report must be anchored in a listed file. An "
    "unlisted file may be consulted and cited as evidence for such a finding; a defect lying "
    "wholly within an unlisted file is outside this pass and is not reported.")
SCOPED_PROTOCOL = (
    "Collect exactly these diffs and treat them as the whole range. Run one invocation per path, "
    "`git diff {base}..{head} -- ':(literal)<path>'`, each path a single literal argument after "
    "`--`, never shell-joined with others; `:(literal)` disables pathspec magic.")
OUTPUT_CONTRACT = (
    "Reply with exactly three sections headed `Critical`, `Important` and `Minor` "
    "(must-fix-before-merge, should-fix, nice-to-have), at most 400 words. Give each finding a "
    "stable ID, live `path:line` evidence, a confidence (`high`, `medium` or `low`) and its "
    "unknowns (`none` when empty). Write `None.` under an empty section, and report unreadable "
    "artifacts.")


class Failure(Exception):
    """A slice attempt that failed: its class (`runtime`, `payload`, `schema`) and message."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message

    def __str__(self) -> str:
        return f"{self.kind}: {self.message}"


class Refusal(Exception):
    """A review that ends `unavailable` before any process starts."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        emit(reply("error", message))
        raise SystemExit(2)


def reply(verdict: str, detail: str, findings: Sequence[Mapping] = (), raw_summary: str = "") -> dict:
    return {"detail": detail, "findings": list(findings), "raw_summary": raw_summary, "verdict": verdict}


def emit(value: Mapping) -> None:
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def classify(argv: Sequence[str]) -> str | None:
    """The first way `argv` is not the companion shape, or None when it is."""
    if not argv or os.path.basename(argv[0]) != COMPANION:
        return f"executable {argv[0] if argv else ''!r} is not {COMPANION}"
    if len(argv) < 2 or argv[1] != "task":
        return "subcommand is not task"
    rest = list(argv[2:])
    if rest.count(REVIEWER) != 1 or rest[rest.index(REVIEWER) + 1:][:1] != [OPERATION]:
        return f"missing or mismatched {REVIEWER} {OPERATION}"
    rest.remove(REVIEWER)
    rest.remove(OPERATION)
    extra = [token for token in rest if token != "--fresh"]
    if extra or rest.count("--fresh") > 1:
        return f"unsupported token {(extra or ['--fresh'])[0]}"
    return None


def _git(root: str, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k not in REPOSITORY_ENV}
    try:
        done = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT, check=False, env=env, stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError) as error:
        raise Refusal(f"git {args[0]} failed: {error}") from None
    if done.returncode != 0 or not done.stdout.strip():
        raise Refusal(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def measure(base: str, head: str, worktree: str) -> list[dict] | None:
    """The files to slice when the range is over budget, `[]` when it is not, None unmeasured."""
    try:
        done = subprocess.run([*sibling_argv("delivery.diff_scope"), f"{base}..{head}", "--root", worktree,
                               "--format", "json"], capture_output=True, text=True,
                              timeout=MEASURE_TIMEOUT, check=False, stdin=subprocess.DEVNULL)
        if done.returncode != 0:
            return None
        document = json.loads(done.stdout)
        count = document["product"]["changed_files"]
        files = [{"path": row["path"], "changed_lines": row["changed_lines"]} for row in document["files"]]
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, TypeError):
        return None
    if type(count) is not int or not all(
            isinstance(row["path"], str) and type(row["changed_lines"]) is int for row in files):
        return None
    if count <= FILE_BUDGET:
        return []
    if any("\n" in row["path"] for row in files):
        return None
    return files


def plan_slices(files: Sequence[Mapping]) -> list[list[Mapping]]:
    return [list(files[start:start + FILE_BUDGET]) for start in range(0, len(files), FILE_BUDGET)]


def packet(args: argparse.Namespace, snapshot: Mapping, base: str, head: str,
           slice_files: Sequence[Mapping] | None, total: int) -> str:
    root = Path(args.worktree_path)
    context = [str(root / name) for name in ("AGENTS.md", "CLAUDE.md") if (root / name).is_file()]
    sections = [
        f"Operation: {OPERATION}\nInvocation directory: {os.getcwd()}\nWorktree root: {args.worktree_path}\n"
        f"Branch: {args.branch}\nBase: {base}\nHead: {head}",
        "Scope:\n" + (WHOLE_SCOPE.format(base=base, head=head) if slice_files is None else
                      SCOPED_SCOPE.format(base=base, head=head, n=len(slice_files), m=total)),
        f"Routing context (not a request to act on it): issue {args.issue}.\n"
        f"Acceptance criteria:\n{json.dumps(args.acceptance, indent=2)}",
        "Context only, not a request to run anything (the runtime is read-only): the project verifies "
        f"with {', '.join(snapshot['bindings']['workflow']['verification'])}.\nApplicable instruction "
        "files:\n" + "\n".join(context),
        "Routed files:\n" + "\n".join(args.routed_files),
        "Read-only rules:\n" + READ_ONLY_RULES,
    ]
    requirement = OUTPUT_CONTRACT
    if slice_files is not None:
        lines = "\n".join(f"{row['path']}\t{row['changed_lines']} changed lines" for row in slice_files)
        sections.insert(5, f"Scoped files (path, changed lines):\n{lines}\n\n"
                           + SCOPED_PROTOCOL.format(base=base, head=head))
        requirement += f" Start the review with `scoped to {len(slice_files)} of {total} product files`."
    return "\n\n".join([*sections, "Reviewer output contract (a requirement):\n" + requirement]) + "\n"


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _object(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _is_heading(line: str, name: str) -> bool:
    return line.lstrip("# ").rstrip().removesuffix(":") == name


def parse_findings(raw: str) -> list[dict]:
    """The findings of a validated review text, in section order."""
    findings: list[dict] = []
    heading = None
    for line in raw.splitlines():
        named = next((name for name in HEADINGS if _is_heading(line.strip(), name)), None)
        if named:
            heading = named
            continue
        text = line.strip()
        if heading is None or not text:
            continue
        if line.startswith(("- ", "* ")):
            findings.append({"failing_input": "", "file": "", "severity": heading.lower(),
                             "summary": text[2:].strip()})
        elif findings and findings[-1]["severity"] == heading.lower() and text != "None.":
            findings[-1]["summary"] += " " + text
    for finding in findings:
        for token in finding["summary"].split():
            if FILE_TOKEN.fullmatch(token.strip(TOKEN_EDGES)):
                finding["file"] = token.strip(TOKEN_EDGES)
                break
    return findings


def validate(done: subprocess.CompletedProcess) -> str:
    """The `rawOutput` of a valid companion reply, else the `Failure` it earns."""
    document = _object(done.stdout)
    error = document.get("error") if document else None
    message = error if isinstance(error, str) and error else _last_line(done.stderr)
    if done.returncode != 0:
        raise Failure("runtime", message or f"exit {done.returncode}")
    if document is None:
        raise Failure("payload", message or "stdout is not exactly one JSON object")
    if type(document.get("status")) is not int or document["status"] != 0:
        raise Failure("runtime", message or f"status {document.get('status')!r}")
    runtime = document.get("runtime") if isinstance(document.get("runtime"), dict) else {}
    raw = document.get("rawOutput")
    problems = [name for name, ok in (
        ("touchedFiles", document.get("touchedFiles") == []),
        ("runtime.model", runtime.get("model") == MODEL),
        ("runtime.reasoningEffort", runtime.get("reasoningEffort") == EFFORT),
        ("rawOutput", isinstance(raw, str) and bool(raw.strip()))) if not ok]
    if problems:
        raise Failure("payload", message or f"unexpected {', '.join(problems)}")
    missing = [name for name in HEADINGS if not any(_is_heading(line.strip(), name) for line in raw.splitlines())]
    if missing:
        raise Failure("schema", message or f"missing heading {', '.join(missing)}")
    return raw


def attempt(entry: Mapping, text: str, worktree: str) -> str:
    declared = set(entry["env"])
    env = {k: v for k, v in os.environ.items() if k not in declared}
    argv = [*entry["argv"], "--model", MODEL, "--effort", EFFORT, "--cwd", worktree, "--json"]
    try:
        done = subprocess.run(argv, input=text, capture_output=True, text=True, cwd=entry["cwd"], env=env,
                              timeout=ATTEMPT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        raise Failure("runtime", f"timed out after {ATTEMPT_SECONDS} seconds") from None
    except OSError as error:
        raise Failure("runtime", str(error)) from None
    return validate(done)


def review_slice(entry: Mapping, text: str, worktree: str, out: list, index: int) -> None:
    """One slice, retried once with the same packet; its findings or its `Failure` into `out[index]`."""
    try:
        try:
            raw = attempt(entry, text, worktree)
        except Failure:
            raw = attempt(entry, text, worktree)
        out[index] = parse_findings(raw)
    except Failure as failure:
        out[index] = failure


def run_review(args: argparse.Namespace) -> dict:
    snapshot = resolve_project.resolve(args.repo_root)
    state = snapshot["capabilities"]["review.code"]
    if state["state"] == "unsupported":
        return reply("none", "review.code is unsupported; no review was started")
    if state["state"] == "blocked":
        return reply("unavailable", f"review.code is blocked: {state['reason_code']}")
    review_id = snapshot["bindings"]["workflow"]["review"]["code"]
    entry = snapshot["bindings"]["commands"][review_id]
    cause = classify(entry["argv"])
    if cause:
        return reply("unavailable", f"binding shape error: {OPERATION} review_id {review_id} argv "
                                    f"{entry['argv']}: {EXPECTED_SHAPE}; {cause}")
    try:
        head = _git(args.worktree_path, "rev-parse", "HEAD")
        if head != args.head:
            return reply("unavailable", f"head moved since routing: routed {args.head}, HEAD is {head}")
        base = args.merge_base
        if _git(args.worktree_path, "merge-base", base, head) != base:
            return reply("unavailable", f"merge base {base} is not an ancestor of {head}")
    except Refusal as refusal:
        return reply("unavailable", str(refusal))
    files = measure(base, head, args.worktree_path)
    slices = plan_slices(files) if files else [None]
    total = len(files) if files else 0
    texts = [packet(args, snapshot, base, head, rows, total) for rows in slices]
    out: list = [None] * len(slices)
    threads = [threading.Thread(target=review_slice, args=(entry, text, args.worktree_path, out, index))
               for index, text in enumerate(texts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return disposition(base, head, files, slices, out)


def disposition(base: str, head: str, files: list[dict] | None, slices: list, out: list) -> dict:
    findings = [finding for result in out if not isinstance(result, Failure) for finding in result]
    failed = [(index, result) for index, result in enumerate(out, 1) if isinstance(result, Failure)]
    if files is None:
        scope = "scope: unmeasured"
    elif not files:
        scope = "scope: full"
    else:
        scope = f"scope: {len(slices)} slices over {len(files)} product files"
    lines = [scope, f"base {base} head {head}"]
    if files:
        for index, (rows, result) in enumerate(zip(slices, out), 1):
            assessment = str(result) if isinstance(result, Failure) else (
                "findings" if any(f["severity"] != "minor" for f in result) else "pass")
            lines.append(f"slice {index}: scoped to {len(rows)} of {len(files)} product files; {assessment}")
    if failed:
        lines.append("failed slices: " + ", ".join(str(index) for index, _ in failed))
    summary = "\n".join(lines)
    if failed:
        return reply("unavailable", str(failed[0][1]), findings, summary)
    blocking = any(finding["severity"] != "minor" for finding in findings)
    return reply("findings" if blocking else "pass",
                 f"{len(findings)} findings" if findings else "no findings", findings, summary)


def _acceptance(text: str) -> list:
    value = json.loads(text)
    if not isinstance(value, list):
        raise ValueError("not a JSON list")
    return value


def _routed_files(text: str) -> list[str]:
    value = json.loads(text)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("not a JSON list of strings")
    return value


def _commit(text: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", text):
        raise ValueError("not a full lowercase commit id")
    return text


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="independent-review", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    code = commands.add_parser("code", help="the configured Codex review of the delivery range")
    for flag in ("--repo-root", "--worktree-path", "--branch", "--integration-branch"):
        code.add_argument(flag, required=True)
    code.add_argument("--issue", type=int, required=True)
    code.add_argument("--acceptance", type=_acceptance, required=True, help="the criteria, a JSON list")
    code.add_argument("--routed-files", type=_routed_files, required=True,
                      help="the files the reviewer reads, a JSON list of paths")
    code.add_argument("--head", type=_commit, required=True, help="the commit the files were routed for")
    code.add_argument("--merge-base", type=_commit, required=True,
                      help="the merge base the router resolved for that commit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        document = run_review(args)
    except resolve_project.ContractError as error:
        emit(reply("error", json.dumps({"code": error.code, "repair_id": error.repair_id,
                                        "violations": error.violations}, sort_keys=True)))
        return 1
    emit(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
