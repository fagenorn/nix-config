"""The stand-in `gh` of the permission guard's table as the source of a Python script."""
# Stand-in for `gh`. Answers the lookups the guard makes for any slug and
# any protected branch, so the merge path can be exercised in every fixture
# repository: the PR, its protection, and the PR body, an issue and
# an issue's comments, the last two from FAKE_ISSUES (a JSON object of issue
# number -> {"body", "comments"}; an absent number answers an empty issue).
# FAKE_<STAGE>_MODE injects failures; FAKE_<STAGE>_JSON overrides
# the payload. Mode `http_error` replays a failed `gh api` read as gh reports
# it: exit 1, the response body on stdout (FAKE_<STAGE>_JSON, else
# GitHub's plan-gated protection answer) and `gh: <message> (HTTP <status>)` on
# stderr, or `gh: HTTP 403` when the body holds no string message and status.
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
    and argv[6] == "title,body,commits,closingIssuesReferences"
):
    stage, number, slug = "body", argv[2], argv[4]
elif len(argv) == 2 and argv[0] == "api":
    parts = argv[1].split("/")
    if (
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
elif stage == "body":
    default = '{"title": "", "body": "", "commits": [], "closingIssuesReferences": []}'
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
print(os.environ.get("FAKE_" + stage.upper() + "_JSON", default))
'''
