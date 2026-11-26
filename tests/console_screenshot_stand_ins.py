"""Stand-ins for the console screenshots (tests/console_screenshots.py): an issue tracker that answers the
titles of the `live-several` issues, and the HTTP client of a guest door.

This module imports nothing from `agent_tools`, so the screenshots can run it beside the base commit's
`python/` and draw the before picture: `title_kwargs` and `poll_titles` do nothing when the console they are
given has no titles read, and the stand-in tracker lives here rather than in the console.
"""
import http.client
import inspect
import socket
from pathlib import Path

TITLES = {21: "Keep the theme after a reload", 22: "Save the settings in one click",
          23: "Show which settings changed", 24: "Undo a settings change",
          31: "Import a large file in parts", 32: "Skip rows already imported",
          41: "Resume an upload after a drop", 42: "Show the upload's progress"}


def title_reader(slug: str, numbers, *, cancelled) -> dict[int, str]:
    """The titles of `numbers` this stand-in tracker knows, whatever the repository."""
    return {number: TITLES[number] for number in numbers if number in TITLES}


def title_kwargs(constructor) -> dict:
    """The constructor argument that gives a console its titles read, only when `constructor` takes one."""
    if "title_reader" in inspect.signature(constructor).parameters:
        return {"title_reader": title_reader}
    return {}


def poll_titles(service) -> None:
    """One titles read of `service`, only when it has one."""
    if hasattr(service, "poll_titles"):
        service.poll_titles()


class UnixHTTPConnection(http.client.HTTPConnection):
    """An HTTP client of a guest door that is a Unix socket at `path`."""

    def __init__(self, path: str | Path, timeout: float = 5):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def door_connection(door: str | tuple[str, int], timeout: float) -> http.client.HTTPConnection:
    """A client of `door`: a socket path (the branch's guest door) or an address (the base commit's)."""
    if isinstance(door, str):
        return UnixHTTPConnection(door, timeout)
    return http.client.HTTPConnection(*door, timeout=timeout)
