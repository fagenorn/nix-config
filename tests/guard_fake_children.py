"""The stand-in row check and the stand-in git of the lifecycle guard suite.

`FAKE_DERIVE_SCRIPT` stands in for `guard-policy derive` and `FAKE_GIT_SCRIPT` for git. They live beside
the suite to hold it under the size budget (rule B17).
"""

# Stand-in for the row check (`guard-policy derive`). Answers from a JSON object
# of slug -> row: FAKE_DERIVE_ROWS names one, else the class default (Nodo's row).
# FAKE_DERIVE_MODE: rows (default), refused_code (its refusals are FAKE_DERIVE_REFUSED,
# a JSON list, else one fetch_failed), unavailable, garbage, hang, and
# slow (sleeps until the time.time() instant FAKE_DERIVE_UNTIL, then answers as rows).
# FAKE_DERIVE_LOG appends each slug asked; FAKE_DERIVE_PIDFILE receives the pid
# of the grandchild `hang` leaves behind.
FAKE_DERIVE_SCRIPT = '''
import json
import os
import subprocess
import sys
import time

argv = sys.argv[1:]
if len(argv) != 2 or argv[0] != "--repository":
    print("unexpected fake-derive argv: " + repr(argv), file=sys.stderr)
    raise SystemExit(64)
slug = argv[1]
log = os.environ.get("FAKE_DERIVE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(slug + "\\n")
mode = os.environ.get("FAKE_DERIVE_MODE", "rows")
if mode == "hang":
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    with open(os.environ["FAKE_DERIVE_PIDFILE"], "w", encoding="utf-8") as stream:
        stream.write(str(sleeper.pid))
    time.sleep(600)
if mode == "slow":
    time.sleep(max(0.0, float(os.environ["FAKE_DERIVE_UNTIL"]) - time.time()))
if mode == "garbage":
    print("{")
    raise SystemExit(0)
report = {"schema_version": 1, "repository": slug, "row": None, "refused": [], "cause": None}
if mode == "unavailable":
    report.update(outcome="unavailable", cause={"reason_code": "registry_invalid", "detail": "x"})
    print(json.dumps(report))
    raise SystemExit(2)
if mode == "refused_code":
    report.update(outcome="refused", refused=json.loads(os.environ.get(
        "FAKE_DERIVE_REFUSED", '[{"project_id": "p", "root": "/p", '
        '"reason_code": "fetch_failed", "detail": "x"}]')))
    print(json.dumps(report))
    raise SystemExit(1)
with open(os.environ.get("FAKE_DERIVE_ROWS", @ROWS@), encoding="utf-8") as stream:
    rows = json.load(stream)
if slug in rows:
    report.update(outcome="derived", row=rows[slug])
    print(json.dumps(report))
    raise SystemExit(0)
report.update(outcome="refused")
print(json.dumps(report))
raise SystemExit(1)
'''

FAKE_GIT_SCRIPT = '''
import os
import sys
import time

REAL = @GIT@
LOOKUP = ["remote", "get-url", "--push", "--all", "origin"]
mode = os.environ.get("FAKE_PUSH_URL_MODE")
if mode and sys.argv[-len(LOOKUP):] == LOOKUP:
    if mode == "timeout":
        time.sleep(5)
    elif mode == "nonzero":
        print("git@github.com:fagenorn/nix-config.git")
        print("fake push URL failure", file=sys.stderr)
        raise SystemExit(1)
    elif mode == "empty":
        raise SystemExit(0)
os.execv(REAL, [REAL, *sys.argv[1:]])
'''
