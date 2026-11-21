"""Read-only stand-in for `gh`, installed by the tracked-issue eval setup.

Usage: gh.py --repo <sandbox repo> --log <calls log> [--pulls <pulls.json>] <gh argv...>

It answers the GitHub calls a lifecycle owner makes about the fixture's seeded issue
(`issues/<nnn>-*.md`: open, no labels, no comments, no blockers) and refuses everything
that would publish, so a run ends at the forge boundary. With `--pulls` it also answers
reads of the pull requests in that JSON file (`pr list`, `pr view`), and `api` reads of an
issue and its comments. `pr checks` answers only for a pull request whose entry carries
`checks`; `api` writes, `pr create` and `pr merge` stay refused.
Every call appends `{"argv": [...], "exit": n}` to the log.
"""

import glob
import json
import os
import re
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


def flag_present(args, *names):
    """True when any of `names` is in `args`; each is removed from `args`."""
    found = False
    while any(argument in names for argument in args):
        args.remove(next(argument for argument in args if argument in names))
        found = True
    return found


def keep_fields(pull, fields):
    wanted = fields.split(",")
    unknown = [name for name in wanted if name not in pull]
    if unknown:
        raise ShimError("gh shim: unknown JSON field: %s" % ",".join(unknown))
    return {name: pull[name] for name in wanted}


def pr_list(pulls, args):
    args = list(args)
    flag_value(args, "--repo", "-R")
    flag_value(args, "--search", "-S")
    flag_value(args, "--limit", "-L")
    state = flag_value(args, "--state", "-s") or "open"
    head = flag_value(args, "--head", "-H")
    fields = flag_value(args, "--json")
    jq_expression = flag_value(args, "--jq", "-q")
    found = [pull for pull in pulls
             if (state == "all" or pull["state"] == state.upper())
             and (head is None or pull["headRefName"] == head)]
    if fields is not None:
        found = [keep_fields(pull, fields) for pull in found]
    emit(found, jq_expression)


def pr_view(pulls, args):
    args = list(args)
    flag_value(args, "--repo", "-R")
    fields = flag_value(args, "--json")
    jq_expression = flag_value(args, "--jq", "-q")
    if len(args) != 1:
        raise ShimError("gh shim: pr view takes one pull request number or branch")
    found = [pull for pull in pulls if args[0] in (str(pull["number"]), pull["headRefName"])]
    if not found:
        raise ShimError("no pull requests found for branch")
    pull = found[0]
    if fields is None:
        if jq_expression is not None:
            raise ShimError("gh shim: --jq needs --json")
        print("title:\t%s\nstate:\t%s\nurl:\t%s\n--\n%s" % (pull["title"], pull["state"], pull["url"], pull["body"]))
        return
    emit(keep_fields(pull, fields), jq_expression)


def pr_checks(pulls, args):
    """Answer `pr checks <n>` from the `checks` of the pull request, as `gh` does."""
    args = list(args)
    flag_value(args, "--repo", "-R")
    flag_present(args, "--watch")
    if flag_present(args, "--required"):
        raise ShimError("gh shim: pr checks --required is not available in this sandbox")
    fields = flag_value(args, "--json")
    jq_expression = flag_value(args, "--jq", "-q")
    numbers = [argument for argument in args if not argument.startswith("-")]
    found = [pull for pull in pulls if numbers[:1] == [str(pull["number"])] and "checks" in pull]
    if not found:
        raise ShimError("gh shim: pr checks is not available in this sandbox")
    checks = found[0]["checks"]
    if fields is not None:
        emit([keep_fields(check, fields) for check in checks], jq_expression)
    elif jq_expression is not None:
        raise ShimError("gh shim: --jq needs --json")
    else:
        for check in checks:
            print("%s\t%s" % (check["name"], check["bucket"]))
    return 0 if all(check["bucket"] == "pass" for check in checks) else 1


def api_read(repo, args):
    """Answer a read of one issue or its comments; refuse every write and any other path."""
    for index, argument in enumerate(args):
        method = None
        if argument in ("-X", "--method") and index + 1 < len(args):
            method = args[index + 1]
        elif argument.startswith("--method="):
            method = argument[len("--method="):]
        elif argument.startswith("-X") and len(argument) > 2:
            method = argument[2:]
        writes = argument in ("-f", "-F", "--field", "--raw-field", "--input") or argument.startswith(
            ("--field=", "--raw-field=", "--input="))
        if writes or (method is not None and method.upper() != "GET"):
            raise ShimError("gh shim: api writes are not available in this sandbox")
    words = list(args[1:])
    flag_present(words, "--paginate")
    slurp = flag_present(words, "--slurp")
    jq_expression = flag_value(words, "--jq", "-q")
    while flag_value(words, "-H", "--header") is not None:
        pass
    flag_value(words, "-X", "--method")
    path = words[0].partition("?")[0] if len(words) == 1 else ""
    issue = re.fullmatch(r"repos/[^/]+/[^/]+/issues/(\d+)", path)
    comments = re.fullmatch(r"repos/[^/]+/[^/]+/issues/(\d+)/comments", path)
    if issue:
        found = load_issue(repo, int(issue.group(1)))
        emit({"number": found["number"], "title": found["title"], "body": found["body"],
              "state": "open", "labels": [], "user": {"login": "owner"}}, jq_expression)
    elif comments:
        emit([[]] if slurp else [], jq_expression)
    elif re.fullmatch(r"repos/[^/]+/[^/]+/rules/branches/.+", path):
        emit([], jq_expression)
    elif re.fullmatch(r"repos/[^/]+/[^/]+/branches/.+/protection", path):
        raise ShimError("gh shim: Branch not protected (HTTP 404)")
    else:
        raise ShimError("gh shim: api %s is not available in this sandbox" % (path or "this call"))


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


def run(repo, args, pulls=None):
    """Answer one call; return its exit code. `pulls` is the pull request list, or None."""
    verb = args[:2]
    if verb == ["issue", "view"]:
        issue_view(repo, args[2:])
    elif args[:1] == ["api"] and any("sub_issues" in a or "dependencies" in a for a in args):
        emit([], flag_value(list(args), "--jq", "-q"))
    elif args[:1] == ["api"] and pulls is not None:
        api_read(repo, args)
    elif verb == ["pr", "list"] and pulls is not None:
        pr_list(pulls, args[2:])
    elif verb == ["pr", "list"]:
        emit([], flag_value(list(args), "--jq", "-q"))
    elif verb == ["pr", "view"] and pulls is not None:
        pr_view(pulls, args[2:])
    elif verb == ["pr", "checks"] and pulls is not None:
        return pr_checks(pulls, args[2:])
    elif verb == ["pr", "view"]:
        raise ShimError("no pull requests found for branch")
    elif verb not in (["auth", "status"], ["issue", "comment"], ["issue", "edit"]):
        words = [argument for argument in args if not argument.startswith("-")][:2]
        raise ShimError("gh shim: %s is not available in this sandbox" % (" ".join(words) or "this command"))
    return 0


def main(argv):
    if len(argv) < 4 or argv[0] != "--repo" or argv[2] != "--log":
        print("usage: gh.py --repo <repo> --log <log> [--pulls <file>] <gh argv...>", file=sys.stderr)
        return 2
    repo, log, args = argv[1], argv[3], argv[4:]
    pulls = None
    if args[:1] == ["--pulls"] and len(args) >= 2:
        with open(args[1], encoding="utf-8") as handle:
            pulls = json.load(handle)
        args = args[2:]
    try:
        code = run(repo, args, pulls)
    except ShimError as error:
        print(error, file=sys.stderr)
        code = 1
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": args, "exit": code}) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
