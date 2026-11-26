"""The land check's stand-ins for the lifecycle guard suites (test support, not a test file).

`write_land_bin` writes the script `--land-bin` names: it runs the source `forge-claim land permit`
with the guard's arguments, optionally with a stand-in `gh` first on PATH. `write_land_gh` writes that
`gh`; `LAND_GH_SCRIPT` answers only the reads `land permit` makes, from `FAKE_LAND_REFS` (a JSON object
of full ref name to sha) and `FAKE_LAND_NOW` (the forge clock, unix seconds). It carries no ref prefix
of its own: it serves whatever names the test puts in `FAKE_LAND_REFS`. `FAKE_LAND_MODE=fail` answers
every call with an HTTP 500, `hang` writes its pid to `FAKE_LAND_PIDFILE` and sleeps.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

LAND_GH_SCRIPT = '''
import email.utils
import json
import os
import sys
import time

argv = sys.argv[1:]
mode = os.environ.get("FAKE_LAND_MODE", "")
if mode == "fail":
    print("gh: Server Error (HTTP 500)", file=sys.stderr)
    raise SystemExit(1)
if mode == "hang":
    with open(os.environ["FAKE_LAND_PIDFILE"], "w", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    time.sleep(30)
refs = json.loads(os.environ.get("FAKE_LAND_REFS", "{}"))


def entry(name):
    return {"ref": name, "object": {"sha": refs[name]}}


if argv == ["api", "--include", "rate_limit"]:
    now = int(os.environ.get("FAKE_LAND_NOW", time.time()))
    print("HTTP/2.0 200 OK\\ndate: " + email.utils.formatdate(now, usegmt=True) + "\\n\\n{}")
    raise SystemExit(0)
parts = argv[1].split("/") if len(argv) == 2 and argv[0] == "api" else []
if len(parts) > 5 and parts[0] == "repos" and parts[3] == "git":
    name = "refs/" + "/".join(parts[5:])
    if parts[4] == "ref":
        if name not in refs:
            print("gh: Not Found (HTTP 404)", file=sys.stderr)
            raise SystemExit(1)
        print(json.dumps(entry(name)))
        raise SystemExit(0)
    if parts[4] == "matching-refs":
        print(json.dumps([entry(ref) for ref in refs if ref.startswith(name)]))
        raise SystemExit(0)
print("unexpected fake land gh argv: " + repr(argv), file=sys.stderr)
raise SystemExit(64)
'''


def write_land_gh(directory: Path) -> Path:
    """`<directory>/land-gh/gh`, the stand-in `gh`; the directory that holds it is returned."""
    holder = directory / "land-gh"
    holder.mkdir(parents=True, exist_ok=True)
    gh = holder / "gh"
    gh.write_text(f"#!{sys.executable}\n" + LAND_GH_SCRIPT, encoding="utf-8")
    gh.chmod(0o755)
    return holder


def write_land_bin(directory: Path, gh_dir: Path | None = None) -> Path:
    """`<directory>/land-bin`: `forge-claim land permit` from source, one process (it execs), so the
    guard's process group holds it and the `gh` it runs; `gh_dir` is put first on PATH when given."""
    path = directory / "land-bin"
    prepend = (f"os.environ['PATH'] = {str(gh_dir)!r} + os.pathsep + os.environ.get('PATH', '')\n"
               if gh_dir is not None else "")
    path.write_text(
        f"#!{sys.executable}\nimport os\nimport sys\n"
        f"os.environ['PYTHONPATH'] = {str(REPO_ROOT / 'python')!r}\n"
        f"{prepend}"
        "os.execv(sys.executable, [sys.executable, '-m', 'agent_tools.claims.forge_claim',"
        " 'land', 'permit', *sys.argv[1:]])\n", encoding="utf-8")
    path.chmod(0o755)
    return path
