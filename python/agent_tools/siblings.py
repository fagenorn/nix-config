"""Running one agent_tools module from another as a child process (parent D16).

A packaged module that runs a packaged sibling builds that child's argv here
and nowhere else. The child runs under this process's own interpreter, so an
installed launcher's child uses the same store environment, and therefore the
same package, as its parent.
"""

import sys


def sibling_argv(module: str) -> list[str]:
    """argv that runs agent_tools.<module> under this interpreter, isolated iff we are."""
    return [sys.executable, *(["-I"] if sys.flags.isolated else []), "-m", f"agent_tools.{module}"]
