"""The instruction surface enforcer: no instruction surface grows past its budget (rule standard:B25).

A surface is a set of committed instruction bytes an agent loads, measured at a committed
revision by the functions of `agent_tools.instruction_load`: `always-loaded` and `conditional`
per profile and host of the model (`instruction-surface/<kind>/<profile id>/<host>`), `corpus`
(`instruction-surface/corpus`) and `descriptions` (`instruction-surface/descriptions`). The
paths are synthetic, so a violation's path names the surface. Its line is the measured bytes,
so a surface that grows reports a larger line.

The budgets are `BUDGETS`, platform constants. No project file sets them: the ceilings of the
model file (`corpus_ceiling_bytes`, `description_ceiling_bytes`, each profile's `ceiling_bytes`
and `conditional_ceiling_bytes`) are never read, and `structure` neutralises them before the
model is validated, so a project ceiling, low, high, absent or malformed, changes no verdict.

A surface that cannot be measured is a violation of its own, one per part, so a part held
unmeasurable on both sides never hides a new one: a model that cannot be loaded or does not
validate is `instruction-surface/unmeasurable/profiles`, a skill tree that cannot be read is
`instruction-surface/unmeasurable/corpus`. Each is a violation at line 1. A repository with no
model measures no profile, and one with no skill tree measures no corpus.

`ENFORCER` is a per-file rule for the never-rise check, matched by path alone
(`follows_renames` is false, so a file git pairs as moved onto a synthetic path changes no
verdict): a surface over its budget may not grow and one under it may grow up to it. The check
keeps the committed bytes of every path `reads` accepts, and a path measured but not kept
fails loud (`EnforcerFailed`). That check, not this command's exit, is the gate.

The command `instruction-surface-lint --repo-root <absolute directory> [--revision <rev>]`
prints every surface over its budget at the revision (default `HEAD`) and every unmeasurable
part that no reasoned suppression marker of the rule covers, and one line for each bare marker
of the rule (`agent_tools.delivery.never_rise.counted`), one line each on stdout,
`<rule> <path>:<line>` with the path escaped as `agent_tools.delivery.never_rise.Violation.text`
defines. It exits 1 when it printed any and 0 when none. It exits 2 with
`instruction-surface-lint: <reason>` on stderr for a relative or missing root, a root below the
repository's top level, an unresolvable revision, a failed git read or a measured path the
snapshot did not keep.
"""

import argparse
import copy
import sys
from types import MappingProxyType
from typing import Mapping, NamedTuple

from agent_tools import instruction_load, skill_lint
from agent_tools.agent_model_matrix import MATRIX_PATH
from agent_tools.delivery import never_rise
from agent_tools.delivery.never_rise import Enforcer, EnforcerFailed, Snapshot, Violation

COMMAND = "instruction-surface-lint"
RULE_ID = "B25"
BUDGETS: Mapping[str, int] = MappingProxyType({
    "always-loaded": 20480, "conditional": 32768, "corpus": 163840, "descriptions": 3072})
UNMEASURABLE_PROFILES = "instruction-surface/unmeasurable/profiles"
UNMEASURABLE_CORPUS = "instruction-surface/unmeasurable/corpus"
TREES = (skill_lint.SHARED_TREE, skill_lint.CLAUDE_TREE, skill_lint.AGENTS_DIR)


class Surface(NamedTuple):
    path: str
    kind: str
    measured: int


def reads(path: str) -> bool:
    """Whether the enforcer measures `path`, so the snapshot must keep its bytes."""
    return (path in (instruction_load.MODEL_PATH, instruction_load.FRAME_PATH, MATRIX_PATH.as_posix())
            or any(path.startswith(tree + "/") for tree in TREES))


def structure(model: dict) -> dict:
    """A copy of the model with every ceiling neutralised, so only its structure is validated."""
    result = copy.deepcopy(model)
    for key in instruction_load.GATE_TOP_LEVEL_KEYS:
        result.pop(key, None)
    profiles = result.get("profiles")
    for profile in profiles if isinstance(profiles, list) else []:
        if not isinstance(profile, dict):
            continue
        for key in instruction_load.GATE_PROFILE_KEYS:
            profile.pop(key, None)
        hosts = profile.get("hosts")
        named = isinstance(hosts, list) and all(isinstance(host, str) for host in hosts)
        profile["ceiling_bytes"] = {host: 0 for host in hosts} if named else {}
    return result


def _reader(snapshot: Snapshot) -> skill_lint.Snapshot:
    def read(path: str) -> bytes | None:
        if path not in snapshot.paths:
            return None
        if path not in snapshot.blobs:
            raise EnforcerFailed(RULE_ID, f"{path} is measured but not kept")
        return snapshot.blobs[path]

    def list_files(prefix: str) -> list[str]:
        return sorted(path for path in snapshot.paths if path.startswith(prefix + "/"))

    return skill_lint.Snapshot(read=read, list_files=list_files)


def _profile_surfaces(reader: skill_lint.Snapshot) -> list[Surface]:
    model = structure(instruction_load.load_model(reader.read(instruction_load.MODEL_PATH)))
    if instruction_load.validate(model, reader.read, gate_fields=False):
        raise ValueError("the model does not validate")
    measure = instruction_load.measure(model, reader.read)["profiles"]
    return [Surface(f"instruction-surface/{kind}/{profile['id']}/{host}", kind,
                    measure[profile["id"]][host]["hot" if kind == "always-loaded" else kind]["bytes"])
            for profile in model["profiles"] for host in profile["hosts"]
            for kind in ("always-loaded", "conditional")]


def surfaces(snapshot: Snapshot) -> tuple[tuple[Surface, ...], tuple[str, ...]]:
    """The measured surfaces, and the sorted paths of the parts that cannot be measured."""
    reader = _reader(snapshot)
    found: list[Surface] = []
    unmeasurable: list[str] = []
    if instruction_load.MODEL_PATH in snapshot.paths:
        try:
            found += _profile_surfaces(reader)
        except ValueError:
            unmeasurable.append(UNMEASURABLE_PROFILES)
    if any(path.startswith(tree + "/") for path in snapshot.paths
           for tree in (skill_lint.SHARED_TREE, skill_lint.CLAUDE_TREE)):
        try:
            corpus = instruction_load.measure_corpus(reader)
        except ValueError:
            unmeasurable.append(UNMEASURABLE_CORPUS)
        else:
            found += [Surface("instruction-surface/corpus", "corpus", corpus["corpus"]),
                      Surface("instruction-surface/descriptions", "descriptions",
                              corpus["descriptions"])]
    return tuple(found), tuple(sorted(unmeasurable))


def find(snapshot: Snapshot) -> list[Violation]:
    measured, unmeasurable = surfaces(snapshot)
    found = [Violation(RULE_ID, s.path, s.measured) for s in measured if s.measured > BUDGETS[s.kind]]
    found += [Violation(RULE_ID, path, 1) for path in unmeasurable]
    return sorted(found, key=lambda v: (v.path, v.line))


ENFORCER = Enforcer(RULE_ID, find, per_file=True, follows_renames=False, reads=reads)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=COMMAND)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args(argv)
    snapshot = never_rise.command_snapshot(COMMAND, args.repo_root, args.revision)
    if snapshot is None:
        return 2
    try:
        kept, marked = never_rise.counted(ENFORCER, snapshot)
    except EnforcerFailed as failure:
        print(f"{COMMAND}: {failure.reason}", file=sys.stderr)
        return 2
    found = sorted(kept + marked, key=lambda v: (v.path, v.line))
    for violation in found:
        print(violation.text())
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
