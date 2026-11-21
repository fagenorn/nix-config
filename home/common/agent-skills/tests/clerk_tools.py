"""Support for tests that hold a clerk prompt to the tools the clerk agent is granted (#1425).

Support only: no TestCase, not a suite member. `outside_clerk_tools(text)` is the set of tools the instructions in `text` name that the
clerk's agent definition (`home/common/claude-code/agents/clerk.md`, its `tools:` line) does not grant. A tool is named by its bare
name as a whole word ("Use Edit to update the file") or by a capitalised word before "tool" ("the Write tool"), so a sentence that
asks for a tool the clerk lacks is found whether or not it says "tool".
"""
import re
from pathlib import Path

CLERK = Path(__file__).parents[4] / "home/common/claude-code/agents/clerk.md"
# The harness's tool names; the "X tool" form below catches any other.
TOOL_NAMES = ("Agent", "Bash", "BashOutput", "Edit", "ExitPlanMode", "Glob", "Grep", "KillShell", "MultiEdit", "NotebookEdit",
              "Read", "Skill", "Task", "TodoWrite", "WebFetch", "WebSearch", "Write")
BARE_NAME = re.compile(r"\b(" + "|".join(TOOL_NAMES) + r")\b")
NAMED_TOOL = re.compile(r"\b([A-Z][A-Za-z]+) tool\b")


def granted_tools() -> set[str]:
    return set(re.search(r"^tools: (.*)$", CLERK.read_text(encoding="utf-8"), re.M).group(1).split(", "))


def tools_named(text: str) -> set[str]:
    return set(BARE_NAME.findall(text)) | set(NAMED_TOOL.findall(text))


def outside_clerk_tools(text: str) -> set[str]:
    return tools_named(text) - granted_tools()
