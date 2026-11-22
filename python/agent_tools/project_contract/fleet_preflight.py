"""fleet-preflight: would every registered project still run on this platform? (issue 1451)

Usage: `fleet-preflight --manifest PATH [--json]`. `--manifest` is required and
names the candidate platform manifest, the one a switch is about to install.

The command judges every entry of the host's fleet registry
(`$HOME/.agents/state/fleet/registry.json`) with this checkout's code against
the manifest at PATH, one row per entry ordered by `project_id`, each row
exactly the row `resolve-project platform-status --fleet` publishes. The
installed platform never changes the verdict: the manifest at PATH is the only
one read, and neither `AGENT_PLATFORM_ROOT` nor the manifest under `HOME` is
consulted. An absent registry is the empty fleet.

Text output (stdout):

    fleet preflight: candidate platform <version> from <manifest path>
    compatible <project_id> <root>
    refused <project_id> <root> <reason_code> <repair_id>
    deprecated <project_id> <root> <deprecation id> ...
    fleet preflight: <n> registered project(s) can run on platform <version>

A `deprecated` line is printed after the row of a project whose
`deprecated_uses` is not empty; it never changes the verdict.

A refusal ends with `fleet preflight: <k> of <n> registered projects cannot run
on platform <version>; activation refused.` and the remedy: migrate each refused
project or remove it from the fleet registry. `--json` prints one compact JSON
document instead: `schema_version` (1), `platform_version`, `manifest_path`,
`fleet` (the rows) and `refused` (the `project_id` of each row that is not
compatible, in row order).

Exit codes: 0 when every registered project is compatible (or none is
registered), 1 when at least one project is refused, 2 when the manifest or the
registry will not read. At exit 2 stdout is empty in text mode and carries the
resolver's `{"error": ...}` object under `--json`; stderr names the repair id.

The refusal set is every row whose `compatible` is false: a project whose
interval excludes the candidate, a contract that is structurally invalid or
gone, and a registered project whose contract declares another id.

The command only reads. It starts no child process, writes no file and creates
no directory. It has no force option and no environment override. The switch
recipes run it from the tree's source under `python3 -B` before activation;
the installed `fleet-preflight` launcher is for running it by hand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_tools.project_contract import resolve_project

PREFLIGHT_SCHEMA_VERSION = 1


def judge(manifest_path: Path) -> tuple[dict, list[dict]]:
    """The fleet's report and the registry entries it was judged from, one read.

    The candidate manifest loads first, so a broken candidate surfaces before
    the registry is read. Raises `resolve_project.ContractError` when either
    will not read.
    """
    manifest, resolved = resolve_project.require_platform_manifest(manifest_path)
    entries = resolve_project.require_registry()
    rows = sorted(
        (resolve_project.fleet_row(entry, manifest) for entry in entries),
        key=lambda row: row["project_id"])
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "platform_version": manifest["platform_version"],
        "manifest_path": str(resolved),
        "fleet": rows,
        "refused": [row["project_id"] for row in rows if not row["compatible"]],
    }, entries


def preflight(manifest_path: Path) -> dict:
    """The fleet's verdicts against the manifest at `manifest_path`."""
    return judge(manifest_path)[0]


def exit_code(report: dict) -> int:
    return 1 if report["refused"] else 0


def render_text(report: dict) -> str:
    version = report["platform_version"]
    lines = [f"fleet preflight: candidate platform {version} "
             f"from {report['manifest_path']}"]
    for row in report["fleet"]:
        if row["compatible"]:
            lines.append(f"compatible {row['project_id']} {row['root']}")
        else:
            lines.append(f"refused {row['project_id']} {row['root']} "
                         f"{row['reason_code']} {row['repair_id']}")
        if row.get("deprecated_uses"):
            lines.append(f"deprecated {row['project_id']} {row['root']} "
                         + " ".join(row["deprecated_uses"]))
    total = len(report["fleet"])
    refused = len(report["refused"])
    if refused:
        lines.append(
            f"fleet preflight: {refused} of {total} registered projects cannot "
            f"run on platform {version}; activation refused. Migrate each "
            "refused project or remove it from the fleet registry.")
    else:
        lines.append(f"fleet preflight: {total} registered project(s) can run "
                     f"on platform {version}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fleet-preflight",
        description="Judge every registered project against a candidate "
                    "platform manifest; exit 1 when one would be refused.")
    parser.add_argument("--manifest", required=True,
                        help="the candidate platform manifest")
    parser.add_argument("--json", action="store_true",
                        help="print the report as one JSON document")
    return parser


def _refuse(args: argparse.Namespace, code: str, repair_id: str,
            violations: list[dict], reason_code: str | None = None) -> int:
    if args.json:
        return resolve_project.emit_error(code, repair_id, violations,
                                          reason_code)
    sys.stderr.write(f"fleet preflight: {code} {repair_id}\n")
    for violation in violations:
        sys.stderr.write(f"  {violation['pointer']}: {violation['message']}\n")
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = preflight(Path(args.manifest))
    except resolve_project.ContractError as error:
        return _refuse(args, error.code, error.repair_id, error.violations,
                       error.reason_code)
    except Exception:
        return _refuse(args, "resolver_failure", "resolver.internal",
                       [{"pointer": "",
                         "message": "the resolver failed unexpectedly"}])
    if args.json:
        resolve_project.emit_json(report)
    else:
        sys.stdout.write(render_text(report))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
