"""The stand-in `gh` the lifecycle guard suite runs the guard against.

`FAKE_GH_SCRIPT` answers the lookups the guard makes for any slug and any protected branch, so the merge
path can be exercised in every fixture repository: the PR, its protection, the PR body, the PR's commit
pages, an issue and an issue's comments, the last two from FAKE_ISSUES (a JSON object of issue number ->
{"body", "comments"}; an absent number answers an empty issue). FAKE_<STAGE>_MODE injects failures;
FAKE_<STAGE>_JSON overrides the payload. Mode `http_error` replays a failed `gh api` read as gh reports
it: exit 1, the response body on stdout (FAKE_<STAGE>_JSON, else GitHub's plan-gated protection answer)
and `gh: <message> (HTTP <status>)` on stderr, or `gh: HTTP 403` when the body holds no string message
and status. It lives beside the suite to keep both files under the size budget (rule B17).

The rerun check reads four more endpoints, one stage each: `run` (an Actions run), `jobs` (its jobs),
`pull` (a pull request) and `required` (a branch's required status checks), answered from FAKE_RUN_JSON,
FAKE_JOBS_JSON, FAKE_PULL_JSON (FAKE_PULL_<number>_JSON for one pull request) and FAKE_REQUIRED_JSON (the jobs are read with `--paginate --slurp`, so a
JSON object answers as one page and a JSON list as the pages), with FAKE_RUN_MODE, FAKE_JOBS_MODE,
FAKE_PULL_MODE and FAKE_REQUIRED_MODE injecting failures. `run_facts`, `jobs_facts`, `pull_facts` and
`required_facts` build those payloads; each defaults to a pull request check run that passes.
`check_run_forge`, `check_run_accepts`, `check_run_refusals`, `check_run_spellings`, `check_run_reads`,
`check_run_permit`, `rerun_production` and `FAKE_SHELL_SCRIPT` (the shell the guard asks for its host,
answered from FAKE_SHELL_GH_HOST, FAKE_SHELL_MODE) hold the scenarios of that check, beside the
suite to keep it under the size budget.
"""

import json

from agent_tools.console import permit


FAKE_SHELL_SCRIPT = '''
import os
import sys
import time

mode = os.environ.get("FAKE_SHELL_MODE", "")
if mode == "hang":
    time.sleep(30)
if mode == "fail":
    raise SystemExit(1)
if mode == "silent":
    raise SystemExit(0)
if sys.argv[1:4] != ["-l", "-i", "-c"] or len(sys.argv) != 5:
    print("unexpected fake-shell argv: " + repr(sys.argv[1:]), file=sys.stderr)
    raise SystemExit(64)
environment = {k: v for k, v in os.environ.items() if k != "GH_HOST"}
if "FAKE_SHELL_GH_HOST" in environment:
    environment["GH_HOST"] = environment["FAKE_SHELL_GH_HOST"]
os.execve("/bin/sh", ["sh", "-c", sys.argv[4]], environment)
'''


def run_facts(slug, head, event="pull_request", numbers=(7,), head_repo=None, branch="issue-12-x"):
    """The JSON of an Actions run of `slug` at `head`, listing the pull requests `numbers`."""
    return json.dumps({
        "event": event, "head_branch": branch, "head_sha": head,
        "head_repository": {"full_name": head_repo or slug},
        "pull_requests": [{"number": n} for n in numbers]})


def jobs_facts(failed=("Tests",), passed=(), total=None):
    """The JSON of a run's jobs, `failed` ones failing and `passed` ones succeeding."""
    jobs = ([{"name": n, "conclusion": "failure"} for n in failed]
            + [{"name": n, "conclusion": "success"} for n in passed])
    return json.dumps({"total_count": total if total is not None else len(jobs), "jobs": jobs})


def jobs_pages(failed, passed=100, total=101):
    """The JSON list of two pages of a run's jobs: `passed` successful jobs, then the `failed` ones."""
    page = [{"name": f"job-{n}", "conclusion": "success"} for n in range(passed)]
    last = [{"name": n, "conclusion": "failure"} for n in failed]
    return json.dumps([{"total_count": total, "jobs": page}, {"total_count": total, "jobs": last}])


def pull_facts(slug, head, state="open", head_repo=None, base_repo=None, branch="issue-12-x",
               base="main"):
    """The JSON of a pull request of `slug` whose head is `head` on `branch`."""
    return json.dumps({
        "state": state,
        "head": {"sha": head, "ref": branch, "repo": {"full_name": head_repo or slug}},
        "base": {"ref": base, "repo": {"full_name": base_repo or slug}}})


def required_facts(contexts=("Tests",), checks=()):
    """The JSON of a branch's required status checks: bare `contexts` and bound `checks`."""
    return json.dumps({"contexts": list(contexts),
                       "checks": [{"context": c, "app_id": a} for c, a in checks]})


def check_run_forge(slug, head, **changes):
    """The FAKE_* answers of a failed pull request check run of `slug` at `head`, with `changes`."""
    return {"FAKE_RUN_JSON": run_facts(slug, head), "FAKE_JOBS_JSON": jobs_facts(),
            "FAKE_PULL_JSON": pull_facts(slug, head), "FAKE_REQUIRED_JSON": required_facts(), **changes}


def check_run_accepts(slug, head):
    """`(name, command prefix, forge changes)` for each way the exempt rerun is allowed."""
    required = required_facts(contexts=("Lint and tests",))
    return [
        ("plain", "", {}),
        ("unset prefix", "unset GITHUB_TOKEN && ", {}),
        ("env prefix", "env -u GITHUB_TOKEN -u GH_TOKEN ", {}),
        ("tokens set", "", {"GITHUB_TOKEN": "x", "GH_TOKEN": "y"}),
        ("Actions-bound check", "", {"FAKE_REQUIRED_JSON": required_facts(contexts=(), checks=(("Tests", 15368),))}),
        ("any-app check", "", {"FAKE_REQUIRED_JSON": required_facts(contexts=(), checks=(("Tests", -1),))}),
        ("session on github.com", "", {"GH_HOST": "github.com"}),
        ("shell on github.com", "", {"FAKE_SHELL_GH_HOST": "github.com"}),
        ("failed job on page two of 101", "", {"FAKE_JOBS_JSON": jobs_pages(("Tests",))}),
        ("failed job beside the required one", "", {
            "FAKE_JOBS_JSON": jobs_facts(failed=("Tests", "Lint and tests")), "FAKE_REQUIRED_JSON": required}),
    ]


def rerun_production(*rules):
    """A `production` member whose `changes` are the `(id, argv)` pairs `rules`."""
    return {"changes": [{"id": name, "argv": argv} for name, argv in rules], "read_only": [],
            "release_profile": "forge-main"}


def check_run_refusals(slug, head):
    """`(name, forge, row changes, extra guard arguments)` for each answer that leaves the rule in place."""
    def forge(**changes):
        return check_run_forge(slug, head, **changes)

    other = "someone/deployer"
    bound = required_facts(contexts=("Tests",), checks=(("Tests", 999),))
    refusals = [
        ("push", forge(FAKE_RUN_JSON=run_facts(slug, head, "push", ()))),
        ("workflow_dispatch", forge(FAKE_RUN_JSON=run_facts(slug, head, "workflow_dispatch"))),
        ("pull_request_target", forge(FAKE_RUN_JSON=run_facts(slug, head, "pull_request_target"))),
        ("stale head", forge(FAKE_PULL_JSON=pull_facts(slug, "f" * 40))),
        ("closed", forge(FAKE_PULL_JSON=pull_facts(slug, head, "closed"))),
        ("fork pull request", forge(FAKE_PULL_JSON=pull_facts(slug, head, head_repo=other))),
        ("other base repository", forge(FAKE_PULL_JSON=pull_facts(slug, head, base_repo="acme/other"))),
        ("fork run", forge(FAKE_RUN_JSON=run_facts(slug, head, head_repo=other))),
        ("no pull request", forge(FAKE_RUN_JSON=run_facts(slug, head, numbers=()))),
        ("branch mismatch", forge(FAKE_PULL_JSON=pull_facts(slug, head, branch="issue-13-y"))),
        ("other base branch", forge(FAKE_PULL_JSON=pull_facts(slug, head, base="release"))),
        ("from the default branch", forge(FAKE_RUN_JSON=run_facts(slug, head, branch="main"),
                                         FAKE_PULL_JSON=pull_facts(slug, head, branch="main"))),
        ("pull-request deploy run", forge(FAKE_JOBS_JSON=jobs_facts(failed=("deploy-preview",)))),
        ("no failed job", forge(FAKE_JOBS_JSON=jobs_facts(failed=(), passed=("Tests",)))),
        ("truncated jobs", forge(FAKE_JOBS_JSON=jobs_facts(total=101))),
        ("page two missing", forge(FAKE_JOBS_JSON=jobs_pages(("Tests",), total=102))),
        ("pages disagree on the total", forge(FAKE_JOBS_JSON=jobs_pages(("Tests",), total=101).replace(
            '"total_count": 101, "jobs": [{"name": "Tests"', '"total_count": 7, "jobs": [{"name": "Tests"'))),
        ("session on another host", forge(GH_HOST="ghe.example.com")),
        ("shell startup file on another host", forge(FAKE_SHELL_GH_HOST="ghe.example.com")),
        ("shell cannot be started", forge(FAKE_SHELL_MODE="fail")),
        ("shell prints no answer", forge(FAKE_SHELL_MODE="silent")),
        ("no shell named", forge(SHELL="")),
        ("shell that is not a path", forge(SHELL="zsh")),
        ("first pull request malformed beside a qualifying one", forge(
            FAKE_RUN_JSON=run_facts(slug, head, numbers=(7, 8)), FAKE_PULL_7_JSON="{}")),
        ("later pull request malformed beside a qualifying one", forge(
            FAKE_RUN_JSON=run_facts(slug, head, numbers=(7, 8)), FAKE_PULL_8_JSON="{}")),
        ("pull request without a head repository", forge(FAKE_PULL_JSON=json.dumps({
            "state": "open", "head": {"sha": head, "ref": "issue-12-x", "repo": None},
            "base": {"ref": "main", "repo": {"full_name": slug}}}))),
        ("pull request that is not readable beside a qualifying one", forge(
            FAKE_RUN_JSON=run_facts(slug, head, numbers=(7, 8)), FAKE_PULL_8_JSON="[]")),
        ("sibling job with a malformed conclusion", forge(FAKE_JOBS_JSON=json.dumps({"total_count": 2, "jobs": [
            {"name": "Tests", "conclusion": "failure"}, {"name": "Lint", "conclusion": 42}]}))),
        ("run nested past the recursion limit", forge(FAKE_RUN_JSON="[" * 30000 + "]" * 30000)),
        ("not a required check", forge(FAKE_REQUIRED_JSON=required_facts(contexts=("Lint",)))),
        ("check bound to another app", forge(FAKE_REQUIRED_JSON=required_facts(
            contexts=(), checks=(("Tests", 999),)))),
        ("bound context", forge(FAKE_REQUIRED_JSON=bound)),
        ("required nonzero", forge(FAKE_REQUIRED_MODE="nonzero")),
        ("required nonzero with a valid body",
         forge(FAKE_REQUIRED_MODE="http_error", FAKE_REQUIRED_JSON=required_facts())),
        ("required invalid", forge(FAKE_REQUIRED_MODE="invalid")),
        ("required malformed", forge(FAKE_REQUIRED_JSON='{"contexts": "Tests", "checks": []}')),
        ("unprotected integration branch", forge(
            FAKE_REQUIRED_MODE="http_error",
            FAKE_REQUIRED_JSON='{"message":"Branch not protected","status":"404"}')),
        ("run nonzero", forge(FAKE_RUN_MODE="nonzero")),
        ("run invalid", forge(FAKE_RUN_MODE="invalid")),
        ("run malformed", forge(FAKE_RUN_JSON='{"event": "pull_request"}')),
        ("jobs nonzero", forge(FAKE_JOBS_MODE="nonzero")),
        ("jobs invalid", forge(FAKE_JOBS_MODE="invalid")),
        ("pull nonzero", forge(FAKE_PULL_MODE="nonzero")),
        ("pull invalid", forge(FAKE_PULL_MODE="invalid")),
    ]
    return [(name, answers, {}, ()) for name, answers in refusals] + [
        ("release pull request", forge(FAKE_RUN_JSON=run_facts(slug, head, branch="dev"),
                                       FAKE_PULL_JSON=pull_facts(slug, head, branch="dev", base="main")),
         {"integration_branch": "dev"}, ()),
        ("declared by the row only", forge(FAKE_REQUIRED_JSON=required_facts(contexts=("Lint",))),
         {"required_checks": ["Tests"]}, ()),
        ("run timeout", forge(FAKE_RUN_MODE="timeout"), {}, ("--child-timeout-seconds", "0.5")),
        ("shell timeout", forge(FAKE_SHELL_MODE="hang"), {}, ("--child-timeout-seconds", "0.5")),
        ("case-spelled row of another integration branch", forge(), {"integration_branch": "dev", "also": (
            ("Acme/Deployer", {}),)}, ()),
    ]


def check_run_reads(slug, run_id=55, branch="main"):
    """The `gh` arguments the check makes, in order, for run `run_id` of `slug` and its one listed pull request."""
    base = f"repos/{slug}"
    return [["api", f"{base}/actions/runs/{run_id}"], ["api", "--paginate", "--slurp", f"{base}/actions/runs/{run_id}/jobs?per_page=100"],
            ["api", f"{base}/pulls/7"],
            ["api", f"{base}/branches/{branch}/protection/required_status_checks"]]


def check_run_permit(slug, head, root):
    """`(forge, grant)` for the console permit judging a rerun of the check run of `slug` at `head`."""
    run = {"event": "pull_request", "branch": "issue-12-x", "repo": slug, "head": head,
           "prs": [7], "failed": ["Tests"], "pending": False, "members": []}
    forge = permit.Forge(
        lambda s, n: {"branch": "issue-12-x", "repo": slug, "head": head, "base": "main"},
        lambda s, i: run, lambda s, b: frozenset({"Tests"}), lambda *a: None)
    return forge, permit.Grant(slug, root, "merge", True, "issue-<num>-<slug>", frozenset({12}), frozenset())


def check_run_spellings(slug):
    """`(name, command)` for each spelling of the rerun that is not the one exempt form."""
    exempt = f"gh run rerun 55 --failed --repo {slug}"
    host = "GH_HOST=ghe.example.com "
    return [
        ("-R", f"gh run rerun 55 --failed -R {slug}"),
        ("--repo=", f"gh run rerun 55 --failed --repo={slug}"),
        ("flags reordered", f"gh run rerun 55 --repo {slug} --failed"),
        ("no --failed", f"gh run rerun 55 --repo {slug}"),
        ("--failed=false", f"gh run rerun 55 --failed=false --repo {slug}"),
        ("--job", f"gh run rerun 55 --failed --job 9 --repo {slug}"),
        ("consumed --failed", f"gh run rerun 55 --job --failed --repo {slug}"),
        ("leading zero", f"gh run rerun 055 --failed --repo {slug}"),
        ("run id past the digit limit", f"gh run rerun {'1' * 4301} --failed --repo {slug}"),
        ("hosted value", f"gh run rerun 55 --failed --repo github.com/{slug}"),
        (".git value", f"gh run rerun 55 --failed --repo {slug}.git"),
        ("path to gh", f"/usr/bin/{exempt}"),
        ("double space", f"gh run rerun 55  --failed --repo {slug}"),
        ("cd prefix", f"cd /tmp && {exempt}"),
        ("operator after", f"{exempt}; echo done"),
        ("chained", f"{exempt} && gh run rerun 56 --failed --repo {slug}"),
        ("unnamed", "gh run rerun 55 --failed"),
        ("command-local GH_HOST", host + exempt),
        ("env GH_HOST", f"env {host}{exempt}"),
    ]


FAKE_GH_SCRIPT = '''
import base64
import json
import os
import sys
import time

PLAN_GATED_BODY = (
    '{"message":"Upgrade to GitHub Pro or make this repository public to enable this '
    'feature.","documentation_url":"https://docs.github.com/rest/branches/'
    'branch-protection#get-branch-protection","status":"403"}'
)

# The guard must scrub the gh-recognised token variables from its lookups (an
# ambient token, which gh would prefer, may be narrower than the keyring
# credential). Refusing to answer when one is visible makes every merge-path
# test double as that assertion.
for name in ("GITHUB_TOKEN", "GH_TOKEN"):
    if name in os.environ:
        print("fake gh saw " + name + " in its environment", file=sys.stderr)
        raise SystemExit(64)

argv = sys.argv[1:]
log = os.environ.get("FAKE_GH_LOG")
if log:
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(argv) + "\\n")
stage = None
number = ""
slug = ""
branch = ""
key = ""
if (
    len(argv) == 7
    and argv[0:2] == ["pr", "view"]
    and argv[3] == "--repo"
    and argv[5] == "--json"
    and argv[6] == "state,baseRefName,headRefName,headRefOid,mergeStateStatus,url,statusCheckRollup"
):
    stage, number, slug, branch = "pr", argv[2], argv[4], "main"
elif (
    len(argv) == 7
    and argv[0:2] == ["pr", "view"]
    and argv[3] == "--repo"
    and argv[5] == "--json"
    and argv[6] == "title,body,closingIssuesReferences"
):
    stage, number, slug = "body", argv[2], argv[4]
elif len(argv) == 2 and argv[0] == "api":
    parts = argv[1].split("/")
    if (
        len(parts) == 6
        and parts[0] == "repos"
        and parts[3] == "actions"
        and parts[4] == "runs"
    ):
        stage = "run"
        slug = parts[1] + "/" + parts[2]
        number = parts[5]
    elif len(parts) == 5 and parts[0] == "repos" and parts[3] == "pulls":
        stage = "pull"
        slug = parts[1] + "/" + parts[2]
        number = parts[4]
    elif (
        len(parts) == 7
        and parts[0] == "repos"
        and parts[3] == "branches"
        and parts[5] == "protection"
        and parts[6] == "required_status_checks"
    ):
        stage = "required"
        slug = parts[1] + "/" + parts[2]
        branch = parts[4]
    elif (
        len(parts) == 6
        and parts[0] == "repos"
        and parts[3] == "branches"
        and parts[5] == "protection"
    ):
        stage = "protection"
        slug = parts[1] + "/" + parts[2]
        branch = parts[4]
    elif len(parts) == 5 and parts[0] == "repos" and parts[3] == "issues":
        stage = "issue"
        slug = parts[1] + "/" + parts[2]
        number = parts[4]
    elif len(parts) == 5 and parts[0] == "repos" and parts[3] == "branches":
        stage = "branch"
        slug = parts[1] + "/" + parts[2]
        branch = parts[4]
    elif (
        len(parts) == 6
        and parts[0] == "repos"
        and parts[3] == "contents"
        and parts[4] == ".github"
        and "?ref=" in parts[5]
    ):
        stage = "contents"
        slug = parts[1] + "/" + parts[2]
        key = parts[5].split("?ref=")[1]
    elif len(parts) == 5 and parts[0] == "repos" and parts[3] == "compare":
        stage = "compare"
        slug = parts[1] + "/" + parts[2]
        key = parts[4]
elif (
    len(argv) == 4
    and argv[0:3] == ["api", "--paginate", "--slurp"]
):
    parts = argv[3].split("?")[0].split("/")
    if (
        len(parts) == 6
        and parts[0] == "repos"
        and parts[3] == "issues"
        and parts[5] == "comments"
        and argv[3].endswith("?per_page=100")
    ):
        stage = "comments"
        slug = parts[1] + "/" + parts[2]
        number = parts[4]
    elif (
        len(parts) == 6
        and parts[0] == "repos"
        and parts[3] == "pulls"
        and parts[5] == "commits"
        and argv[3].endswith("?per_page=100")
    ):
        stage = "commits"
        slug = parts[1] + "/" + parts[2]
        number = parts[4]
    elif (
        len(parts) == 7
        and parts[0] == "repos"
        and parts[3] == "actions"
        and parts[4] == "runs"
        and parts[6] == "jobs"
        and argv[3].endswith("/jobs?per_page=100")
    ):
        stage = "jobs"
        slug = parts[1] + "/" + parts[2]
        number = parts[5]
if stage is None:
    print("unexpected fake-gh argv: " + repr(argv), file=sys.stderr)
    raise SystemExit(64)

mode = os.environ.get("FAKE_" + stage.upper() + "_MODE", "ok")
if mode == "nonzero":
    print("fake " + stage + " failure", file=sys.stderr)
    raise SystemExit(9)
if mode == "timeout":
    time.sleep(2)
if mode == "invalid":
    print("{")
    raise SystemExit(0)
if mode == "http_error":
    body = os.environ.get("FAKE_" + stage.upper() + "_JSON", PLAN_GATED_BODY)
    try:
        answer = json.loads(body)
        line = "gh: " + answer["message"] + " (HTTP " + answer["status"] + ")"
    except (ValueError, KeyError, TypeError):
        line = "gh: HTTP 403"
    print(body)
    print(line, file=sys.stderr)
    raise SystemExit(1)

if stage == "pr":
    default = (
        '{"state":"OPEN","baseRefName":"' + branch + '",'
        '"headRefName":"issue-' + number + '-topic",'
        '"headRefOid":"d4d9acc0505c73305b3e0ced029db43100bc0e8a",'
        '"mergeStateStatus":"CLEAN",'
        '"url":"https://github.com/' + slug + "/pull/" + number + '",'
        '"statusCheckRollup":[{"__typename":"CheckRun",'
        '"status":"COMPLETED","conclusion":"SUCCESS"}]}'
    )
elif stage == "run":
    default = json.dumps({
        "event": "push", "head_branch": "main", "head_sha": "e" * 40,
        "head_repository": {"full_name": slug}, "pull_requests": []})
elif stage == "jobs":
    default = json.dumps({"total_count": 1, "jobs": [{"name": "Tests", "conclusion": "failure"}]})
elif stage == "pull":
    default = json.dumps({
        "state": "open",
        "head": {"sha": "e" * 40, "ref": "issue-12-x", "repo": {"full_name": slug}},
        "base": {"ref": "main", "repo": {"full_name": slug}}})
elif stage == "required":
    default = json.dumps({"contexts": ["Tests"], "checks": []})
elif stage == "body":
    default = '{"title": "", "body": "", "closingIssuesReferences": []}'
elif stage == "commits":
    default = "[[]]"
elif stage == "issue":
    issue = json.loads(os.environ.get("FAKE_ISSUES", "{}")).get(number, {})
    default = json.dumps({"number": int(number), "body": issue.get("body", "")})
elif stage == "comments":
    issue = json.loads(os.environ.get("FAKE_ISSUES", "{}")).get(number, {})
    default = json.dumps([issue.get("comments", [])])
elif stage == "branch":
    default = json.dumps({"name": branch, "commit": {"sha": os.environ.get("FAKE_BASE_SHA", "b" * 40)}})
elif stage in ("contents", "compare"):
    table = json.loads(os.environ.get("FAKE_LOOK_FILES" if stage == "contents" else "FAKE_COMPARES", "{}"))
    if key not in table:
        print('{"message":"Not Found","status":"404"}')
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        raise SystemExit(1)
    if stage == "contents":
        raw = base64.b64encode(table[key].encode()).decode()
        default = json.dumps({"type": "file", "encoding": "base64", "content": raw})
    else:
        default = json.dumps(table[key])
else:
    default = (
        '{"required_status_checks":{"contexts":["Nix Eval"]},'
        '"enforce_admins":{"enabled":true}}'
    )
answer = os.environ.get("FAKE_" + stage.upper() + "_JSON", default)
if stage == "pull":
    answer = os.environ.get("FAKE_PULL_" + number + "_JSON", answer)
if stage == "jobs" and isinstance(json.loads(answer), dict):
    answer = "[" + answer + "]"
print(answer)
'''
