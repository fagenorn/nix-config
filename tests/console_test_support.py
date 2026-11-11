"""Shared helpers of the console service suites (#855): registries, log rows, requests, a started service."""
import http.client
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

from agent_tools.console import service as console_service
from agent_tools.console import sessions as console_sessions


def entries(n):
    return [{"project_id": f"owner/p{i:02d}", "root": f"/srv/p{i:02d}"} for i in range(n)]


def write_registry(path, items):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(handle, "w") as stream:
        json.dump({"schema_version": 1, "projects": items}, stream)
    os.replace(temporary, path)


def log_rows(store):
    connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    try:
        return connection.execute(
            "SELECT seq, at, kind, project, payload FROM events ORDER BY seq").fetchall()
    finally:
        connection.close()


def request(address, method, path, host=None):
    connection = http.client.HTTPConnection(*address, timeout=5)
    try:
        if host is None:
            connection.request(method, path)
        else:
            connection.putrequest(method, path, skip_host=True)
            connection.putheader("Host", host)
            connection.endheaders()
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def post_hook(address, body, headers=None, host=None):
    headers = {"Content-Type": "application/json"} if headers is None else dict(headers)
    if host is not None:
        headers["Host"] = host
    connection = http.client.HTTPConnection(*address, timeout=5)
    try:
        connection.request("POST", "/api/hooks", body=body, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def write_session(directory, *, pid, session_id, cwd, status, waiting_for=None, name=None,
                  updated_at=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    document = {"pid": pid, "sessionId": session_id, "cwd": cwd, "status": status,
                "updatedAt": int(time.time() * 1000) if updated_at is None else updated_at}
    stat = Path("/proc") / str(pid) / "stat"
    if stat.exists():
        document["procStart"] = stat.read_text().rsplit(")", 1)[1].split()[19]
        document["pidDomain"] = console_sessions.own_pid_domain()
    if waiting_for is not None:
        document["waitingFor"] = waiting_for
    if name is not None:
        document["name"] = name
    handle, temporary = tempfile.mkstemp(dir=directory)
    with os.fdopen(handle, "w") as stream:
        json.dump(document, stream)
    os.replace(temporary, directory / f"{pid}.json")


HOOK_FIXTURE = Path(__file__).parent / "fixtures" / "console" / "hook-payloads.json"


def hook_cases():
    document = json.loads(HOOK_FIXTURE.read_text())
    return [(case["name"], {**document["common"], **case["payload"]}, case["expect"])
            for case in document["cases"]]


def hook_body(name, **overrides):
    for case_name, payload, _ in hook_cases():
        if case_name == name:
            return json.dumps({**payload, **overrides}).encode("utf-8")
    raise KeyError(name)


def service(test, store, registry, session_dirs=(), repo_of=lambda cwd: cwd, **kwargs):
    svc = console_service.ConsoleService(
        store, registry, port=0, session_dirs=lambda: list(session_dirs),
        repo_of=repo_of, **kwargs)
    svc.start()
    test.addCleanup(svc.close)
    return svc
