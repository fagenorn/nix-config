"""The `promotion` command: capture, evaluate and validate promotion documents (#127).

`promotion capture` turns an authored draft into a `captured` candidate and
prints the labelled `gh issue create` argv inside it as data; the tracker is
never touched (D1). `promotion evaluate` records a sweep's commands verbatim and
runs none of them (D19). Both resolve the project through `resolve-project` on
`PATH` (D5) and create `--output` exclusively under `project.root` (D14, D25).
`promotion validate --input <path>` reads one document, judges its shape with
`promotion_schema.validate_document` and prints `{"valid":true}`. It resolves
nothing and writes nothing.

Every printed document is one canonical JSON line. Exit 0 is a document; 3 is
a gate refusal and 2 a tool or structural failure, each printing exactly one
`error` object; an argparse usage error exits 2 with no JSON. `main` is the one
exception boundary (D12). Policy lives in `promotion_schema`, not here (D2).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from agent_tools.promotion_schema import (COMMAND_NAME, DRAFT_KIND, INTERNAL_FAILURE_MESSAGE,
                                          Refusal, load_strict, mint_candidate,
                                          mint_evaluation, validate_document, violation)

RESOLVER = "resolve-project"
RESOLVER_TIMEOUT = 60
GITHUB_TRACKER = "github"


class Project(NamedTuple):
    root: Path          # Path(project.root), as the resolver printed it
    id: str             # project.id
    tracker_kind: str   # bindings.tracker.kind
    repo_slug: str | None


def _unresolvable(message: str) -> Refusal:
    return Refusal("contract_unresolvable", [violation("", message)])


def _member(document: object, *names: str) -> object:
    """The member at `names`, or `None` when any level is absent or not an object."""
    for name in names:
        if not isinstance(document, dict):
            return None
        document = document.get(name)
    return document


def resolve(repo_root: str | None) -> Project:
    """The resolved project, from `resolve-project resolve` on `PATH` (D5).

    `--repo-root` is passed on only when given. Every failure refuses
    `contract_unresolvable`; a resolver refusal's own code is the message.
    """
    argv = [RESOLVER, "resolve"] + ([] if repo_root is None else ["--repo-root", repo_root])
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=RESOLVER_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        raise _unresolvable(f"{RESOLVER} could not run: {type(error).__name__}")
    try:
        resolved = load_strict(proc.stdout)
    except ValueError:
        resolved = None
    code = _member(resolved, "error", "code")
    if isinstance(code, str):
        raise _unresolvable(code)
    if proc.returncode != 0:
        raise _unresolvable(f"{RESOLVER} exited {proc.returncode}")
    if not isinstance(resolved, dict):
        raise _unresolvable(f"{RESOLVER} printed no ResolvedProject object")
    values = {}
    for pointer, names in (("/project/root", ("project", "root")),
                           ("/project/id", ("project", "id")),
                           ("/bindings/tracker/kind", ("bindings", "tracker", "kind"))):
        value = _member(resolved, *names)
        if not isinstance(value, str) or not value:
            raise _unresolvable(f"the ResolvedProject has no string {pointer}")
        values[pointer] = value
    slug = _member(resolved, "bindings", "tracker", "repo_slug")
    return Project(Path(values["/project/root"]), values["/project/id"],
                   values["/bindings/tracker/kind"], slug if isinstance(slug, str) else None)


def output_target(raw: str, root: Path) -> tuple[Path, str]:
    """The absolute output path and its posix path relative to `root` (D25, D30).

    A relative `raw` is taken from the working directory. The parent must be an
    existing directory (none is created) and the path must lie beneath `root`.
    """
    given = Path(raw)
    absolute = given if given.is_absolute() else Path.cwd() / given
    if absolute.name in ("", ".", "..") or not absolute.parent.is_dir():
        raise Refusal("output_outside_root",
                      [violation("", "--output must name a file in an existing directory")])
    target = absolute.parent.resolve() / absolute.name
    base = root.resolve()
    if base not in target.parents:
        raise Refusal("output_outside_root",
                      [violation("", "--output must resolve under project.root")])
    return target, target.relative_to(base).as_posix()


def write_new(target: Path, document: dict) -> None:
    """Create `target` exclusively with the rendered document (D14).

    Never creates a directory and never overwrites: an existing file, or a
    symlink at `target`, refuses `output_exists` and is left byte-identical.
    """
    data = render(document).encode("utf-8")
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        raise Refusal("output_exists", [violation("", "--output already exists")])
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def read_document(path: str) -> dict:
    """The JSON object at `path`, strictly loaded (D30); raises `Refusal`."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeError):
        raise Refusal("unreadable_input", [violation("", "the input file cannot be read")])
    try:
        document = load_strict(text)
    except ValueError:
        raise Refusal("invalid_document", [violation("", "the input is not strict JSON")])
    if not isinstance(document, dict):
        raise Refusal("invalid_document", [violation("", "must be an object")])
    return document


def render(document) -> str:
    """The canonical line: sorted, compact, ASCII-escaped, finite JSON plus a newline."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False) + "\n"


def emit(document) -> int:
    sys.stdout.write(render(document))
    return 0


def emit_refusal(refusal: Refusal) -> int:
    sys.stdout.write(render({"error": {"code": refusal.code,
                                       "candidate_id": refusal.candidate_id,
                                       "state": refusal.state,
                                       "violations": refusal.violations}}))
    return refusal.exit_code


def run_capture(args) -> int:
    project = resolve(args.repo_root)
    if project.tracker_kind != GITHUB_TRACKER or not project.repo_slug:
        raise _unresolvable("capture needs a github tracker with a repo_slug")
    target, relative = output_target(args.output, project.root)
    draft = read_document(args.input)
    violations = validate_document(draft)
    if not violations and draft["kind"] != DRAFT_KIND:
        violations = [violation("/kind", f"must be {DRAFT_KIND}")]
    if violations:
        raise Refusal("invalid_document", violations)
    candidate = mint_candidate(draft, project.repo_slug, relative)
    write_new(target, candidate)
    return emit(candidate)


def run_evaluate(args) -> int:
    project = resolve(args.repo_root)
    target, _ = output_target(args.output, project.root)
    evaluation = mint_evaluation(project.id, args.revision, args.command,
                                 args.candidate or [])
    violations = validate_document(evaluation)
    if violations:
        raise Refusal("invalid_document", violations)
    write_new(target, evaluation)
    return emit(evaluation)


def run_validate(args) -> int:
    document = read_document(args.input)
    violations = validate_document(document)
    if violations:
        raise Refusal("invalid_document", violations)
    return emit({"valid": True})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMMAND_NAME, description="Capture, evaluate and validate promotion documents.")
    subcommands = parser.add_subparsers(dest="subcommand", required=True)
    capture = subcommands.add_parser(
        "capture", help="turn a draft into a captured candidate; the tracker is not touched")
    capture.add_argument("--input", required=True, metavar="PATH",
                         help="a promotion-candidate-draft document")
    capture.add_argument("--output", required=True, metavar="PATH",
                         help="the new candidate file, beneath project.root")
    capture.add_argument("--repo-root", metavar="PATH",
                         help="passed on to resolve-project resolve")
    capture.set_defaults(handler=run_capture)
    evaluate = subcommands.add_parser(
        "evaluate", help="record a sweep's commands verbatim; runs none of them")
    evaluate.add_argument("--output", required=True, metavar="PATH",
                          help="the new evaluation file, beneath project.root")
    evaluate.add_argument("--command", required=True, action="append", metavar="TEXT",
                          help="one sweep command, recorded verbatim (repeatable)")
    evaluate.add_argument("--candidate", action="append", metavar="ID",
                          help="one candidate_id the sweep found (repeatable)")
    evaluate.add_argument("--revision", metavar="HEX",
                          help="the swept revision; null when absent")
    evaluate.add_argument("--repo-root", metavar="PATH",
                          help="passed on to resolve-project resolve")
    evaluate.set_defaults(handler=run_evaluate)
    validate = subcommands.add_parser(
        "validate", help="judge one document's shape; resolves and writes nothing")
    validate.add_argument("--input", required=True, metavar="PATH",
                          help="a draft, candidate or evaluation document")
    validate.set_defaults(handler=run_validate)
    return parser


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.handler(args)
    except SystemExit:
        raise
    except Refusal as refusal:
        return emit_refusal(refusal)
    except Exception as error:  # the one boundary (D12)
        print(f"{COMMAND_NAME}: {error!r}", file=sys.stderr)
        return emit_refusal(Refusal("internal_failure",
                                    [violation("", INTERNAL_FAILURE_MESSAGE)]))


if __name__ == "__main__":
    raise SystemExit(main())
