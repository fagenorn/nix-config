"""The facts a verify-pending run reads: `when` conditions and the built-in probes (issue 630).

A `when` condition is read from the running system (`darwin-version`/`nixos-version`, git) and
the forge, never from a host clock: every time comparison uses `forge_markers.server_now()`
through `Context.now()` (P7). Every `gh` call goes through `forge_markers`, so no token reaches
it; the version tool, every `git` child and the in-process deploy adapter also run with
`GITHUB_TOKEN` and `GH_TOKEN` removed (P16). This module only reads: the `window-open` marker a
`days_after` condition waits for is posted by the caller.
"""
import contextlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from agent_tools import forge_markers, release_adapter, verify_block, verify_issues
from agent_tools.forge_markers import ForgeError, Marker
from agent_tools.resolve_project import registered_deploy_adapter

TOKENS = ("GITHUB_TOKEN", "GH_TOKEN")
VERSION_TOOLS = ("darwin-version", "nixos-version")
TOOL_TIMEOUT = 60
REVISION = re.compile(r"[0-9a-f]{40}")
NOT_YET = 75
INCLUDED = ("ahead", "identical")
EXCLUDED = ("behind", "diverged")


@dataclass
class Context:
    slug: str
    root: Path
    default_branch: str
    deploy: Mapping[str, Any]
    tracker: Mapping[str, Any]
    markers: Sequence[Marker] = ()
    _now: datetime | None = field(default=None, init=False, repr=False)
    _revision: tuple[str | None] | None = field(default=None, init=False, repr=False)

    def now(self) -> datetime:
        """The forge's time, read once."""
        if self._now is None:
            self._now = forge_markers.server_now()
        return self._now

    def revision(self) -> str | None:
        """The deployed revision of this host, read once."""
        if self._revision is None:
            self._revision = (deployed_revision(),)
        return self._revision[0]


@dataclass(frozen=True)
class Reading:
    reason: str
    facts: dict[str, str]

    @property
    def ok(self) -> bool:
        return self.reason == "due"


@dataclass(frozen=True)
class Due:
    due: bool
    reason: str
    facts: dict[str, str]
    open_window: str | None = None


@dataclass(frozen=True)
class Probe:
    exit: int
    output: str
    facts: dict[str, str]


def _clean_environ() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in TOKENS}


def deployed_revision() -> str | None:
    """The commit this host's system was built from, or None when it cannot be read."""
    tool = next((name for name in VERSION_TOOLS if shutil.which(name)), None)
    if tool is None:
        return None
    try:
        done = subprocess.run([tool, "--json"], capture_output=True, text=True, timeout=TOOL_TIMEOUT,
                              stdin=subprocess.DEVNULL, env=_clean_environ())
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if done.returncode != 0:
        return None
    try:
        payload = json.loads(done.stdout)
    except (ValueError, RecursionError):
        return None
    value = payload.get("configurationRevision") if isinstance(payload, dict) else None
    if not isinstance(value, str):
        return None
    value = value.removesuffix("-dirty")
    return value if REVISION.fullmatch(value) else None


def _compare(slug: str, base: str, head: str) -> str | None:
    """The status of the forge's compare of `base...head`, or None when the forge cannot say."""
    payload = forge_markers.api_get(f"repos/{slug}/compare/{quote(base)}...{quote(head)}", allow=(404,))
    status = payload.get("status") if isinstance(payload, dict) else None
    return status if isinstance(status, str) else None


def includes(ctx: Context, sha: str, rev: str) -> bool | None:
    """Whether `rev` contains `sha`: local ancestry first, the forge's compare when git cannot say."""
    try:
        done = subprocess.run(["git", "-C", str(ctx.root), "merge-base", "--is-ancestor", sha, rev],
                              capture_output=True, text=True, timeout=TOOL_TIMEOUT,
                              stdin=subprocess.DEVNULL, env=_clean_environ())
    except (subprocess.TimeoutExpired, OSError, ValueError):
        done = None
    if done is not None and done.returncode in (0, 1):
        return done.returncode == 0
    status = _compare(ctx.slug, sha, rev)
    if status in INCLUDED:
        return True
    if status in EXCLUDED:
        return False
    return None


def on_forge(ctx: Context, rev: str) -> bool | None:
    """True when the forge holds commit `rev`, False when it answers 404 or 422."""
    payload = forge_markers.api_get(f"repos/{ctx.slug}/commits/{rev}", allow=(404, 422))
    if payload is None:
        return False
    if isinstance(payload, dict) and payload.get("sha") == rev:
        return True
    raise ForgeError("payload_invalid", "commit payload does not name the commit")


def deployed_includes(ctx: Context, sha: str) -> Reading:
    rev = ctx.revision()
    if rev is None:
        return Reading("revision_unknown", {})
    facts = {"rev": rev}
    if not on_forge(ctx, rev):
        return Reading("revision_unpushed", facts)
    found = includes(ctx, sha, rev)
    if found is None:
        return Reading("compare_unknown", facts)
    return Reading("due" if found else "not_deployed", facts)


@contextlib.contextmanager
def scrubbed_environ(names: Iterable[str]) -> Iterator[None]:
    """Remove `names` from `os.environ` for the block and restore each previous value after it."""
    previous = {name: os.environ.pop(name) for name in set(names) if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(previous)


def deploy_observation(ctx: Context, sha: str) -> dict | None:
    """The registered deploy adapter's observation for `sha`, or None when none is registered."""
    name = registered_deploy_adapter(ctx.deploy)
    if name is None:
        return None
    operation = release_adapter.watch_operation(release_adapter.DESCRIPTORS[name])
    request = {"kind": "effect", "operation": operation, "parameters": {
        "target": {"kind": "github_repository", "repository": ctx.slug, "branch": ctx.default_branch},
        "candidate": {"commit": sha}, "config": ctx.deploy["config"]}}
    unset = ctx.tracker.get("credential_env", {}).get("unset_before_invocation", [])
    with scrubbed_environ((*TOKENS, *unset)):
        return release_adapter.REGISTRY[name].inspect(request)


def released_includes(ctx: Context, sha: str) -> Reading:
    if registered_deploy_adapter(ctx.deploy) is not None:
        observation = deploy_observation(ctx, sha)
        satisfied = isinstance(observation, dict) and observation.get("outcome") == "satisfied"
        return Reading("due" if satisfied else "not_released", {})
    if ctx.deploy.get("command") is not None:
        return Reading("deploy_watch_unread", {})
    latest = forge_markers.api_get(f"repos/{ctx.slug}/releases/latest", allow=(404,))
    tag = latest.get("tag_name") if isinstance(latest, dict) else None
    if not isinstance(tag, str) or not tag:
        return Reading("not_released", {})
    facts = {"tag": tag}
    contains = _compare(ctx.slug, sha, tag)
    if contains is None:
        return Reading("compare_unknown", facts)
    if contains not in INCLUDED:
        return Reading("not_released", facts)
    on_default = _compare(ctx.slug, tag, ctx.default_branch)
    return Reading("due" if on_default in INCLUDED else "not_released", facts)


def _workflow_runs(ctx: Context, query: str) -> list[dict]:
    payload = forge_markers.api_get(f"repos/{ctx.slug}/actions/runs?{query}")
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        raise ForgeError("payload_invalid", "no workflow_runs list")
    return [run for run in runs if isinstance(run, dict)]


def _runs_of(runs: Iterable[dict], workflow: str) -> list[dict]:
    """The runs of `workflow`, matched by name or by the last segment of the workflow path."""
    return [run for run in runs
            if run.get("name") == workflow
            or (isinstance(run.get("path"), str) and run["path"].rsplit("/", 1)[-1] == workflow)]


def ci_run(ctx: Context, workflow: str, branch: str, sha: str) -> str:
    """`success`, `failure` or `none` for the workflow's completed runs at `sha` on `branch`."""
    runs = _runs_of(_workflow_runs(ctx, f"branch={branch}&head_sha={sha}&per_page=100"), workflow)
    done = [run for run in runs if run.get("status") == "completed"]
    if any(run.get("conclusion") == "success" for run in done):
        return "success"
    return "failure" if done else "none"


def _event_reading(ctx: Context, event: str, merge: str) -> Reading:
    return deployed_includes(ctx, merge) if event == "deployed" else released_includes(ctx, merge)


def _days_after(spec: Mapping, merge: str, ctx: Context, facts: dict[str, str]) -> Due:
    event, days = spec["event"], spec["days"]
    opened = verify_issues.live_one(list(ctx.markers), verify_issues.WINDOW, {"event": event, "merge": merge})
    if opened is not None:
        if ctx.now() >= opened.updated_at + timedelta(days=days):
            return Due(True, "due", facts)
        return Due(False, "window_not_open", facts)
    reading = _event_reading(ctx, event, merge)
    facts = {**facts, **reading.facts}
    if reading.ok:
        return Due(False, "window_opening", facts, open_window=event)
    return Due(False, "window_not_open", facts)


def evaluate_when(when: Mapping, merge: str, ctx: Context) -> Due:
    """Whether every member of `when` holds; stops at the first one that does not."""
    facts: dict[str, str] = {}
    if "not_before" in when and not ctx.now() >= verify_block.parse_time(when["not_before"]):
        return Due(False, "not_before", facts)
    for name, reader in (("deployed_includes", deployed_includes), ("released_includes", released_includes)):
        if name in when:
            reading = reader(ctx, when[name])
            facts.update(reading.facts)
            if not reading.ok:
                return Due(False, reading.reason, facts)
    if "ci_run_includes" in when:
        spec = when["ci_run_includes"]
        if ci_run(ctx, spec["workflow"], spec["branch"], spec["sha"]) != "success":
            return Due(False, "ci_not_passed", facts)
    if "days_after" in when:
        return _days_after(when["days_after"], merge, ctx, facts)
    return Due(True, "due", facts)


def _stamps(ctx: Context, run: Mapping) -> list[str]:
    if run["source"] == "releases":
        payload = forge_markers.api_get(f"repos/{ctx.slug}/releases?per_page=100")
        if not isinstance(payload, list):
            raise ForgeError("payload_invalid", "releases is not a list")
        return [item["published_at"] for item in payload
                if isinstance(item, dict) and not item.get("draft")
                and isinstance(item.get("published_at"), str)]
    query = "per_page=100" + (f"&branch={run['branch']}" if run.get("branch") else "")
    return [item["created_at"] for item in _runs_of(_workflow_runs(ctx, query), run["workflow"])
            if isinstance(item.get("created_at"), str)]


def _probe(exit_code: int, output: dict, facts: dict[str, str]) -> Probe:
    return Probe(exit_code, json.dumps(output, sort_keys=True), facts)


def run_probe(run: Mapping, ctx: Context) -> Probe:
    """Run a built-in probe: exit 0 met, 1 not met, 75 not yet."""
    name = run["probe"]
    if name in ("deployed_includes", "released_includes"):
        reader = deployed_includes if name == "deployed_includes" else released_includes
        reading = reader(ctx, run["sha"])
        return _probe(0 if reading.ok else NOT_YET, {"reason": reading.reason}, reading.facts)
    if name == "ci_run_includes":
        state = ci_run(ctx, run["workflow"], run["branch"], run["sha"])
        return _probe({"success": 0, "failure": 1}.get(state, NOT_YET), {"ci_run": state}, {})
    if name == "count_since":
        stamps = _stamps(ctx, run)
        try:
            count = verify_block.count_after(stamps, run["since"])
            code = verify_block.count_since(stamps, run["since"], run["n"])
        except ValueError as error:
            raise ForgeError("payload_invalid", str(error)) from None
        return _probe(code, {"count": count}, {})
    raise ValueError(f"unknown probe {name!r}")
