"""Copies of the shipped procedures that a stubbed run edits: kept across a continue, stopped once verified, or unstructured."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

PROCEDURES = Path(__file__).resolve().parents[1] / "python/agent_tools/delivery/procedures"


def stopping_after_verify(tmp: Path) -> Path:
    """A copy of the shipped procedures whose run is kept across a continue and stops once verified."""
    copy = tmp / "procedures"
    shutil.copytree(PROCEDURES, copy)
    path = copy / "deliver.json"
    document = json.loads(path.read_text("utf-8"))
    for step in document["steps"]:
        if step["id"] == "start":
            step["holds"] = "run"
        if step["id"] == "issue":
            step["on"]["refused"] = "done"  # the check wants one reachable step that still ends the run
        if step["id"] == "verification":
            step["on"]["done"] = "verified"
            step["on"]["verify"] = "landing"  # the check wants the landing step reachable too
    document["stops"]["verified"] = {"need": "owner-decision", "reenter": "verification"}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return copy


def keeping_the_run(tmp: Path) -> Path:
    """A copy of the shipped procedures whose run is kept across a continue and otherwise unchanged."""
    copy = tmp / "kept-procedures"
    shutil.copytree(PROCEDURES, copy)
    path = copy / "deliver.json"
    document = json.loads(path.read_text("utf-8"))
    for step in document["steps"]:
        if step["id"] == "start":
            step["holds"] = "run"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return copy


def unstructured_procedures(tmp: Path) -> Path:
    """A copy of the shipped procedures as they were before findings carried a kind, a rule and declines."""
    copy = tmp / "unstructured-procedures"
    shutil.copytree(PROCEDURES, copy)
    for path in sorted(copy.glob("*.json")):
        document = json.loads(path.read_text("utf-8"))
        if path.name.endswith(".reply.json"):
            items = document["properties"].get("findings", {}).get("items")
            if items is not None:
                for member in ("kind", "rule", "restates"):
                    items["properties"].pop(member, None)
                    if member in items["required"]:
                        items["required"].remove(member)
            if path.name == "direct-fix.reply.json":
                document["properties"].pop("declines")
                document["required"].remove("declines")
            path.write_text(json.dumps(document) + "\n", encoding="utf-8")
        else:
            for step in document["steps"]:
                if "in" in step:
                    step["in"] = [name for name in step["in"] if not name.endswith(".declines")]
            path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    for path in sorted(copy.glob("*.md")):
        lines = path.read_text("utf-8").splitlines(keepends=True)
        path.write_text("".join(line for line in lines if ".declines}}" not in line), encoding="utf-8")
    return copy
