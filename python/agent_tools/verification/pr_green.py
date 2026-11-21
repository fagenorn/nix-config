"""`pr-green`: whether a pull request's head is green, and since when (#1433).

`pr-green --repo OWNER/NAME --pr N` applies one green rule to the head of pull request N and prints
one JSON line, the report of `verify_checks.pr_green_state` plus `"state"`:
`{"pr", "head", "base", "green_at", "failing", "pending", "missing", "state"}`.

Usage. `--repo` is `<owner>/<name>` of `[A-Za-z0-9_.-]` and `--pr` a positive integer; anything else
is a usage error (exit 2) before any read.

Records read. The pull request (`head.sha`, `base.ref`), the base branch's required status checks,
and the head's check runs and commit statuses, across every page, only through `forge_api`.

The rule. `failed` when a completed check run concluded outside success, neutral and skipped, or the
latest status (by `updated_at`) of a context is failure or error; `failing` names them. Otherwise
`pending` when a check run is not completed, the latest status of a context is pending, a required
check (from the protection of `base`, each from the app it binds) is not met at the head, which is
`missing`, or the head has no check run and no status at all. Otherwise `green`, and `green_at` is
the latest of every check run's `completed_at` and every context's latest status `updated_at`, as an
RFC 3339 UTC string with no time rounded. `green_at` is null when the state is not green.

Exit codes. 0 green, 1 failed, 75 pending, 2 a usage error or a forge error (one stderr line).
"""
import argparse
import json
import sys
from collections.abc import Sequence

from agent_tools.system import forge_api
from agent_tools.verification import verify_checks

EXITS = {"green": 0, "failed": 1, "pending": 75}


def _repo(value: str) -> str:
    if not verify_checks.REPO.match(value):
        raise argparse.ArgumentTypeError("must be OWNER/NAME")
    return value


def _pr(value: str) -> int:
    if not value.isascii() or not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr-green", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=_repo, required=True)
    parser.add_argument("--pr", type=_pr, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        state, report = verify_checks.pr_green_state(args.repo, args.pr)
    except forge_api.ForgeError as error:
        print(f"pr-green: forge_error: {error.code}", file=sys.stderr)
        return 2
    print(json.dumps({**report, "state": state}, sort_keys=True))
    return EXITS[state]


if __name__ == "__main__":
    sys.exit(main())
