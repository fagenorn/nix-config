"""The engine judges a procedure by running the check as its own process.

`verdict` starts `python -m agent_tools.delivery.procedure_check` through
`sibling_argv`, under the engine's interpreter, with no stdin and the engine's
own environment and working directory, so a relative `--procedures` resolves as
the engine resolved it. Every option is passed in the `--name=value` form, so a
value that begins with a dash is read as a value and never as an option.
`caps` false adds `--without-caps`: the check then leaves the size caps unmeasured.

The check's wire format is the contract. Exit 0 prints one JSON object whose
`verdict` is `ok` and whose `procedures` lists the names; exit 1 prints one whose
`verdict` is `refused`, with `breaches` and `refusals` lists holding at least one
entry between them; exit 2 prints one stderr line, `procedure-check: <reason>`.
`verdict` returns `(exit, document)` for exit 0 and 1. Anything else, a usage
exit, a timeout, a child that does not start, an unknown exit code or a document
that breaks these shapes, raises `CheckError` carrying the reason.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from agent_tools.system.siblings import sibling_argv

CHECK_SECONDS = 120
_PREFIX = "procedure-check: "
_NO_REASON = "the procedure check refused with no reason"


class CheckError(Exception):
    """The check did not give a verdict; `str` is the reason."""


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _refusal_ok(item: object) -> bool:
    return (isinstance(item, dict)
            and all(isinstance(item.get(key), str) for key in ("procedure", "defect", "detail"))
            and (item.get("step") is None or isinstance(item.get("step"), str)))


def _breach_ok(item: object) -> bool:
    return (isinstance(item, dict)
            and all(isinstance(item.get(key), str) for key in ("thing", "unit"))
            and _is_int(item.get("size")) and _is_int(item.get("cap")))


def _shaped(code: int, document: object) -> bool:
    if not isinstance(document, dict):
        return False
    if code == 0:
        return document.get("verdict") == "ok" and _is_strings(document.get("procedures"))
    breaches, refusals = document.get("breaches"), document.get("refusals")
    return (document.get("verdict") == "refused"
            and isinstance(breaches, list) and isinstance(refusals, list)
            and bool(breaches or refusals)
            and all(map(_breach_ok, breaches)) and all(map(_refusal_ok, refusals)))


def verdict(directory: Path, project_commands: Sequence[str], *, caps: bool) -> tuple[int, dict]:
    """The check process's exit (0 or 1) and its document, or `CheckError`."""
    argv = [*sibling_argv("delivery.procedure_check"), f"--procedures={directory}",
            *(f"--project-command={name}" for name in project_commands),
            *(() if caps else ("--without-caps",))]
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=CHECK_SECONDS)
    except subprocess.TimeoutExpired:
        raise CheckError(f"the procedure check did not finish within {CHECK_SECONDS} seconds") from None
    except (OSError, subprocess.SubprocessError) as error:
        raise CheckError(f"the procedure check did not start: {error}") from error
    last = _last_line(done.stderr)
    if done.returncode == 2:
        raise CheckError(last.removeprefix(_PREFIX) or _NO_REASON)
    if done.returncode in (0, 1):
        try:
            document = json.loads(done.stdout)
        except ValueError:
            document = None
        if _shaped(done.returncode, document):
            return done.returncode, document
    raise CheckError(f"the procedure check exited {done.returncode} without a verdict: {last}")
