"""Read-only stand-in for `gh`, installed by the tracked-issue eval setup.

Usage: gh.py --repo <sandbox repo> --log <calls log> <gh argv...>

It answers the GitHub calls a lifecycle owner makes about the fixture's seeded issue
(`issues/<nnn>-*.md`: open, no labels, no comments, no blockers) and refuses everything
that would publish, so a run ends at the forge boundary. Every call appends
`{"argv": [...], "exit": n}` to the log.
"""

import glob
import json
import os
import subprocess
import sys

FORGE_URL = "https://github.com/fixture/tinytask/issues/%d"
FIELDS = ("number", "title", "body", "state", "labels", "comments", "url", "assignees", "milestone")


class ShimError(Exception):
    """A call the shim refuses; the message is printed to stderr and the call exits 1."""


def flag_value(args, *names):
    """The value after the first of `names` in `args`, or None; the pair is removed from `args`."""
    for index, argument in enumerate(args):
        if argument in names:
            if index + 1 >= len(args):
                raise ShimError("gh shim: %s needs a value" % argument)
            value = args[index + 1]
            del args[index:index + 2]
            return value
    return None


def emit(value, jq_expression):
    """Print `value` as compact JSON, or through `jq -r <expression>` when one was given."""
    text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if jq_expression is None:
        print(text)
        return
    try:
        done = subprocess.run(["jq", "-r", jq_expression], input=text, capture_output=True, text=True)
    except FileNotFoundError:
        raise ShimError("gh shim: jq is required for --jq and is not on PATH")
    if done.returncode != 0:
        raise ShimError("gh shim: jq failed: " + done.stderr.strip())
    sys.stdout.write(done.stdout)


def load_issue(repo, number):
    matches = sorted(glob.glob(os.path.join(repo, "issues", "%03d-*.md" % number)))
    if not matches:
        raise ShimError("gh shim: no issue %d in this sandbox" % number)
    with open(matches[0], encoding="utf-8") as handle:
        first, _, rest = handle.read().partition("\n")
    title = first[2:] if first.startswith("# ") else first
    return {
        "number": number, "title": title, "body": rest.lstrip("\n"), "state": "OPEN",
        "labels": [], "comments": [], "url": FORGE_URL % number, "assignees": [], "milestone": None,
    }


def issue_view(repo, args):
    flag_value(args, "--repo", "-R")
    fields = flag_value(args, "--json")
    jq_expression = flag_value(args, "--jq", "-q")
    if len(args) != 1 or not args[0].isdigit():
        raise ShimError("gh shim: issue view takes one issue number")
    issue = load_issue(repo, int(args[0]))
    if fields is None:
        if jq_expression is not None:
            raise ShimError("gh shim: --jq needs --json")
        print("title:\t%s\nstate:\tOPEN\n--\n%s" % (issue["title"], issue["body"]))
        return
    wanted = fields.split(",")
    unknown = [name for name in wanted if name not in FIELDS]
    if unknown:
        raise ShimError("gh shim: unknown JSON field: %s" % ",".join(unknown))
    emit({name: issue[name] for name in wanted}, jq_expression)


def run(repo, args):
    """Answer one call; return its exit code."""
    verb = args[:2]
    if verb == ["issue", "view"]:
        issue_view(repo, args[2:])
    elif args[:1] == ["api"] and any("sub_issues" in a or "dependencies" in a for a in args):
        emit([], flag_value(list(args), "--jq", "-q"))
    elif verb == ["pr", "list"]:
        emit([], flag_value(list(args), "--jq", "-q"))
    elif verb == ["pr", "view"]:
        raise ShimError("no pull requests found for branch")
    elif verb not in (["auth", "status"], ["issue", "comment"], ["issue", "edit"]):
        words = [argument for argument in args if not argument.startswith("-")][:2]
        raise ShimError("gh shim: %s is not available in this sandbox" % (" ".join(words) or "this command"))
    return 0


def main(argv):
    if len(argv) < 4 or argv[0] != "--repo" or argv[2] != "--log":
        print("usage: gh.py --repo <repo> --log <log> <gh argv...>", file=sys.stderr)
        return 2
    repo, log, args = argv[1], argv[3], argv[4:]
    try:
        code = run(repo, args)
    except ShimError as error:
        print(error, file=sys.stderr)
        code = 1
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": args, "exit": code}) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
