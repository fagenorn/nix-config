"""Size caps on the engine, measured from the files it is given (#1513).

Caps: core 600 lines; engine package 2500 lines (the core and every module
that `engine.py`, `engine_*.py` or what they import reach, tests excluded);
25 graders of at most 40 source lines each; 40 steps per procedure (group
members included); 8192 bytes per prompt file. Lines are physical lines, blank
and comment lines included. Raising a cap is a reviewed change of its number.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agent_tools.delivery import procedure_check
from agent_tools.delivery.engine_graders import Grader

CORE_LINES = 600
PACKAGE_LINES = 2500
PROCEDURE_STEPS = 40
GRADER_COUNT = 25
GRADER_LINES = 40
PROMPT_BYTES = 8192

_PACKAGE = ("agent_tools", "delivery")


@dataclass(frozen=True)
class Breach:
    thing: str
    size: int
    cap: int
    unit: str

    def as_json(self) -> dict:
        return {"cap": self.cap, "size": self.size, "thing": self.thing, "unit": self.unit}


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValueError(f"cannot read {path.name}: {error}") from error


def physical_lines(path: Path) -> int:
    # Python reads LF, CR and CRLF each as one line break; bytes.splitlines splits on exactly those.
    return len(_read(path).splitlines())


def _imports(path: Path, package_dir: Path) -> set[str]:
    try:
        tree = ast.parse(_read(path))
    except SyntaxError as error:
        raise ValueError(f"cannot parse {path.name}: {error}") from error
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if tuple(parts[:2]) == _PACKAGE and len(parts) > 2:
                    names.add(parts[2])
        elif isinstance(node, ast.ImportFrom):
            parts = (node.module or "").split(".") if node.module else []
            if node.level == 0 and tuple(parts[:2]) == _PACKAGE:
                if len(parts) > 2:
                    names.add(parts[2])
                else:
                    names.update(alias.name for alias in node.names)
            elif node.level == 1:
                if parts:
                    names.add(parts[0])
                else:
                    names.update(alias.name for alias in node.names)
    return {name for name in names if (package_dir / f"{name}.py").is_file()}


def engine_modules(package_dir: Path) -> tuple[Path, ...]:
    found = {
        path.name
        for path in package_dir.iterdir()
        if path.is_file() and (path.name == "engine.py" or (path.name.startswith("engine_") and path.suffix == ".py"))
    }
    pending = sorted(found)
    while pending:
        for name in _imports(package_dir / pending.pop(), package_dir):
            if f"{name}.py" != "__init__.py" and f"{name}.py" not in found:
                found.add(f"{name}.py")
                pending.append(f"{name}.py")
    return tuple(package_dir / name for name in sorted(found))


def _grader_breaches(graders: Mapping[str, Grader]) -> list[Breach]:
    out = []
    if len(graders) > GRADER_COUNT:
        out.append(Breach("graders", len(graders), GRADER_COUNT, "graders"))
    for name in sorted(graders):
        try:
            size = len(inspect.getsourcelines(graders[name].grade)[0])
        except (TypeError, OSError) as error:
            raise ValueError(f"cannot read the source of grader {name!r}") from error
        if size > GRADER_LINES:
            out.append(Breach(f"grader {name}", size, GRADER_LINES, "lines"))
    return out


def _step_count(path: Path) -> int | None:
    try:
        doc = procedure_check._strict_load(path)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("steps"), list):
        return None
    return len(doc["steps"])


def breaches(package_dir: Path, procedures_dir: Path, graders: Mapping[str, Grader]) -> tuple[Breach, ...]:
    try:
        return _breaches(package_dir, procedures_dir, graders)
    except OSError as error:
        raise ValueError(f"cannot measure the engine: {' '.join(str(error).split())}") from error


def _breaches(package_dir: Path, procedures_dir: Path, graders: Mapping[str, Grader]) -> tuple[Breach, ...]:
    out = []
    core = physical_lines(package_dir / "engine_core.py")
    if core > CORE_LINES:
        out.append(Breach("core", core, CORE_LINES, "lines"))
    total = sum(physical_lines(path) for path in engine_modules(package_dir))
    if total > PACKAGE_LINES:
        out.append(Breach("engine package", total, PACKAGE_LINES, "lines"))
    out.extend(_grader_breaches(graders))
    documents = sorted(
        (
            p
            for p in procedures_dir.glob("*.json")
            if not p.name.endswith(".reply.json") and procedure_check._inside(procedures_dir, p.name)
        ),
        key=lambda p: p.stem,
    )
    for path in documents:
        steps = _step_count(path)
        if steps is not None and steps > PROCEDURE_STEPS:
            out.append(Breach(f"procedure {path.stem}", steps, PROCEDURE_STEPS, "steps"))
    for path in sorted((p for p in procedures_dir.glob("*.md") if procedure_check._inside(procedures_dir, p.name)), key=lambda p: p.name):
        size = path.stat().st_size
        if size > PROMPT_BYTES:
            out.append(Breach(f"prompt {path.name}", size, PROMPT_BYTES, "bytes"))
    return tuple(out)
