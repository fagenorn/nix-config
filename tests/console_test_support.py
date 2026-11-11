"""Shared helpers of the console service suites (#855): registries, log rows, requests, a started service."""
import http.client
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from agent_tools.console import service as console_service


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


def service(test, store, registry):
    svc = console_service.ConsoleService(store, registry, port=0)
    svc.start()
    test.addCleanup(svc.close)
    return svc
