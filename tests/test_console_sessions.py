"""The console's session model (#857): hooks, registry, liveness, worktrees, fold."""

import functools
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console.event_log import Event
from agent_tools.console.sessions import (
    ENDED,
    GONE,
    HOOK,
    HOOK_EVENTS,
    IDLE,
    SEEN,
    Observation,
    SessionState,
    hook_entry,
    main_checkout,
    own_pid_domain,
    poll_changes,
    process_matches,
    read_session_registry,
    registry_state,
    session_states,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "console" / "hook-payloads.json").read_text()
)
COMMON = FIXTURE["common"]
SID = COMMON["session_id"]


def repo_of(cwd):
    return cwd


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="microseconds")


def project_of(repo):
    return "owner/p00" if repo == "/srv/p00" else None


def case(name):
    return next(c for c in FIXTURE["cases"] if c["name"] == name)


def sstate(sid, state, hook_ms=None):
    return SessionState(sid, "/srv/p00", "/srv/p00", state, "n", 1, "t1", hook_ms)


def observation(sid, status, updated_ms=5000):
    return Observation(sid, "/srv/p00", 10, status, None, "n", updated_ms)


def seen(sid, state, project="owner/p00"):
    return (SEEN, project, {"session_id": sid, "cwd": "/srv/p00", "repo": "/srv/p00",
                            "state": state, "name": "n"})


class SessionModelTest(unittest.TestCase):
    def test_each_registered_hook_event_moves_the_session_to_its_state(self):
        cases = FIXTURE["cases"]
        self.assertEqual({c["payload"]["hook_event_name"] for c in cases}, set(HOOK_EVENTS))
        for c in cases:
            with self.subTest(c["name"]):
                events = []
                if c["previous"] is not None:
                    events.append(Event(1, "t1", SEEN, None, {
                        "session_id": SID, "cwd": "/srv/p00", "repo": "/srv/p00",
                        "state": c["previous"]}))
                kind, payload = hook_entry({**COMMON, **c["payload"]}, repo_of)
                events.append(Event(2, "t2", kind, None, payload))
                result = session_states(events)
                expect = ENDED if c["expect"] == "ended" else c["expect"]
                self.assertEqual(result[SID].state, expect)
                self.assertEqual(result[SID].last_seq, 2)

    def test_a_hook_entry_keeps_only_the_known_fields(self):
        doc = {**COMMON, **case("permission prompt")["payload"], "future_field": {"x": 1}}
        self.assertEqual(
            hook_entry(doc, lambda cwd: "/repo"),
            (HOOK, {"event": "PermissionRequest", "session_id": SID, "cwd": "/srv/p00",
                    "repo": "/repo", "tool_name": "Bash"}))
        self.assertEqual(
            hook_entry({**COMMON, **case("session start")["payload"]}, lambda cwd: "/repo"),
            (HOOK, {"event": "SessionStart", "session_id": SID, "cwd": "/srv/p00",
                    "repo": "/repo", "source": "startup"}))
        failure = {**COMMON, "hook_event_name": "StopFailure", "error": None}
        self.assertEqual(
            hook_entry(failure, repo_of),
            (HOOK, {"event": "StopFailure", "session_id": SID, "cwd": "/srv/p00",
                    "repo": "/srv/p00"}))
        stop = {**COMMON, **case("finished turn")["payload"]}
        self.assertEqual(
            hook_entry(stop, lambda cwd: None)[1],
            {"event": "Stop", "session_id": SID, "cwd": "/srv/p00", "repo": None})

    def test_an_unknown_event_kind_or_shape_is_ignored(self):
        for doc in (
            {**COMMON, "hook_event_name": "PreCompact"},
            {**COMMON, "hook_event_name": "FutureEvent"},
            {"hook_event_name": "Stop", "cwd": "/srv/p00"},
            {**COMMON, "hook_event_name": "Stop", "session_id": 7},
            {**COMMON, "hook_event_name": "Stop", "cwd": ""},
            [],
            None,
            "Stop",
        ):
            with self.subTest(doc=doc):
                self.assertIsNone(hook_entry(doc, repo_of))
        self.assertEqual(session_states([
            Event(1, "t1", "session.future", None, {"session_id": "s"}),
            Event(2, "t2", HOOK, None, {"event": "Stop", "session_id": "s", "cwd": "/x"}),
            Event(3, "t3", SEEN, None, {"session_id": "s", "cwd": "/x", "repo": "/x",
                                        "state": "dancing"}),
            Event(4, "t4", SEEN, None, {"session_id": "s", "cwd": "/x", "repo": "/x",
                                        "state": "ended"}),
        ]), {})

    def test_folding_onto_states_equals_folding_everything(self):
        def at(seq):
            return iso(1000 * seq)

        hook = {"session_id": "s1", "cwd": "/srv/p00", "repo": "/srv/p00"}
        events = [
            Event(1, at(1), SEEN, None, {**hook, "state": "working", "name": "n1"}),
            Event(2, at(2), HOOK, None, {**hook, "event": "PermissionRequest",
                                         "tool_name": "Bash"}),
            Event(3, at(3), SEEN, None, {"session_id": "s2", "cwd": "/srv/p01",
                                         "repo": "/srv/p01", "state": "idle"}),
            Event(4, at(4), HOOK, None, {**hook, "event": "Stop"}),
            Event(5, at(5), GONE, None, {"session_id": "s2"}),
        ]
        result = session_states(events)
        self.assertEqual(result, session_states(events[3:], session_states(events[:3])))
        self.assertEqual(result, {"s1": SessionState(
            "s1", "/srv/p00", "/srv/p00", "idle", "n1", 4, iso(4000), 4000)})

    def test_an_ended_session_is_a_tombstone_a_new_start_revives(self):
        hook = {"session_id": "s1", "cwd": "/srv/p00", "repo": "/srv/p00"}
        events = [
            Event(1, iso(1000), SEEN, None, {**hook, "state": "working"}),
            Event(2, iso(2000), HOOK, None, {**hook, "event": "SessionEnd"}),
        ]
        result = session_states(events)
        self.assertEqual(result["s1"].state, ENDED)
        self.assertEqual(result["s1"].hook_ms, 2000)
        events.append(Event(3, iso(3000), HOOK, None, {**hook, "event": "SessionStart"}))
        result = session_states(events)
        self.assertEqual(result["s1"].state, IDLE)
        self.assertEqual(result["s1"].hook_ms, 3000)

    def test_a_hook_is_stamped_with_the_time_it_was_received_not_the_time_it_was_logged(self):
        kind, payload = hook_entry({**COMMON, **case("finished turn")["payload"]}, repo_of,
                                   received_ms=1500)
        self.assertEqual(payload["received_ms"], 1500)
        result = session_states([Event(1, iso(4000), kind, None, payload)])
        self.assertEqual(result[SID].hook_ms, 1500)
        self.assertEqual(result[SID].last_at, iso(4000))

    def test_an_unrelated_notification_keeps_the_time_of_the_state_it_keeps(self):
        hook = {"session_id": "s1", "cwd": "/srv/p00", "repo": "/srv/p00"}
        events = [
            Event(1, iso(1000), HOOK, None, {**hook, "event": "Stop"}),
            Event(2, iso(2000), HOOK, None, {**hook, "event": "Notification",
                                             "notification_type": "auth_success"}),
        ]
        result = session_states(events)["s1"]
        self.assertEqual((result.state, result.hook_ms, result.last_seq), ("idle", 1000, 2))
        events.append(Event(3, iso(3000), HOOK, None, {**hook, "event": "Notification",
                                                       "notification_type": "idle_prompt"}))
        self.assertEqual(session_states(events)["s1"].hook_ms, 3000)
        unseen = Event(1, iso(5000), HOOK, None, {**hook, "event": "Notification",
                                                  "notification_type": "auth_success"})
        self.assertEqual(session_states([unseen])["s1"].hook_ms, 5000)


def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


class WorktreeTest(unittest.TestCase):
    def test_a_worktree_session_belongs_to_its_main_checkout(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            git("-c", "init.defaultBranch=main", "init", "-q", str(tmp / "main"))
            git("-C", str(tmp / "main"), "-c", "user.name=t", "-c", "user.email=t@t",
                "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "x")
            git("-C", str(tmp / "main"), "worktree", "add", "-q", str(tmp / "wt"), "-b", "wt")
            (tmp / "wt" / "sub").mkdir()
            (tmp / "main" / "sub").mkdir()
            (tmp / "plain").mkdir()
            main = os.path.realpath(tmp / "main")
            self.assertEqual(main_checkout(str(tmp / "wt" / "sub")), main)
            self.assertEqual(main_checkout(str(tmp / "wt")), main)
            self.assertEqual(main_checkout(str(tmp / "main" / "sub")), main)
            self.assertIsNone(main_checkout(str(tmp / "plain")))
            (tmp / "wt" / ".git").write_text("garbage")
            self.assertEqual(main_checkout(str(tmp / "wt" / "sub")),
                             os.path.realpath(tmp / "wt"))


class RegistryTest(unittest.TestCase):
    def test_the_registry_reading_skips_what_it_cannot_use(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            (tmp / "a").mkdir()
            (tmp / "b").mkdir()
            files = {
                "a/10.json": {"pid": 10, "sessionId": "s-busy", "cwd": "/srv/p00",
                              "status": "busy", "name": "p00-aa",
                              "updatedAt": 1794418246662, "future": [1]},
                "a/11.json": {"pid": 11, "sessionId": "s-shell", "cwd": "/srv/p00",
                              "status": "shell", "updatedAt": True},
                "a/12.json": {"pid": 12, "sessionId": "s-wait", "cwd": "/srv/p01",
                              "status": "waiting", "waitingFor": "permission prompt",
                              "procStart": "37198", "pidDomain": "linux:m:pid:[1]"},
                "a/14.json": [1],
                "a/20.json": {"pid": 20, "sessionId": "s-nul", "cwd": "/tmp/a\u0000b",
                              "status": "busy"},
                "a/15.json": {"pid": 15, "cwd": "/x"},
                "a/16.json": {"pid": "16", "sessionId": "s-strpid", "cwd": "/x"},
                "a/17.json": {"pid": 17, "sessionId": "s-dead", "cwd": "/x",
                              "status": "busy"},
                "a/18.json": {"pid": True, "sessionId": "s-bool", "cwd": "/x"},
                "b/19.json": {"pid": 19, "sessionId": "s-busy", "cwd": "/other",
                              "status": "idle"},
            }
            for name, document in files.items():
                (tmp / name).write_text(json.dumps(document))
            (tmp / "a" / "13.json").write_text("{not json")
            calls = []

            def record(pid, start, domain):
                calls.append((pid, start, domain))
                return pid != 17

            result = read_session_registry([tmp / "a", tmp / "missing", tmp / "b"], alive=record)
        self.assertEqual(set(result), {"s-busy", "s-shell", "s-wait"})
        self.assertEqual(result["s-busy"], Observation(
            "s-busy", "/srv/p00", 10, "busy", None, "p00-aa", 1794418246662))
        self.assertIsNone(result["s-shell"].updated_ms)
        self.assertNotIn("s-nul", result)
        self.assertIn((12, "37198", "linux:m:pid:[1]"), calls)
        self.assertIn((10, None, None), calls)
        table = [
            (observation("s", "busy"), "working"),
            (observation("s", "idle"), "idle"),
            (Observation("s", "/x", 1, "waiting", "input needed", None, None), "waiting_answer"),
            (Observation("s", "/x", 1, "waiting", "permission prompt", None, None),
             "waiting_permission"),
            (Observation("s", "/x", 1, "waiting", None, None, None), "waiting_answer"),
            (observation("s", "shell"), None),
            (observation("s", None), None),
        ]
        for obs, expect in table:
            with self.subTest(status=obs.status, waiting_for=obs.waiting_for):
                self.assertEqual(registry_state(obs), expect)

    def test_a_reused_pid_is_not_the_session(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            (tmp / "proc" / "self" / "ns").mkdir(parents=True)
            (tmp / "proc" / "self" / "stat").write_text("1 (x) S")
            os.symlink("pid:[4026532224]", tmp / "proc" / "self" / "ns" / "pid")
            (tmp / "proc" / "2164").mkdir()
            (tmp / "proc" / "2164" / "stat").write_text(
                "2164 (a) b) S " + " ".join(["0"] * 18) + " 976 0 0\n")
            (tmp / "machine-id").write_text("21b1c3eb3a554a8792391e610443b8b8\n")
            kw = dict(proc=tmp / "proc", machine_id=tmp / "machine-id")
            here = "linux:21b1c3eb3a554a8792391e610443b8b8:pid:[4026532224]"
            other = "linux:21b1c3eb3a554a8792391e610443b8b8:pid:[4026532223]"
            self.assertEqual(own_pid_domain(**kw), here)
            self.assertIs(process_matches(2164, "37198", here, **kw), False)
            self.assertIs(process_matches(2164, "976", here, **kw), True)
            self.assertIs(process_matches(2164, "976", other, **kw), False)
            for start, domain in ((None, None), (None, here), ("976", None),
                                  (976, here), ("976", 4026532224), ("", here)):
                with self.subTest(start=start, domain=domain):
                    self.assertIs(process_matches(2164, start, domain, **kw), False)
            (tmp / "noid").write_text("\n")
            self.assertIs(process_matches(
                2164, "976", here, proc=tmp / "proc", machine_id=tmp / "noid"), False)
            self.assertIs(process_matches(2165, None, None, **kw), False)
            self.assertIs(process_matches(0, None, None, **kw), False)
            self.assertIs(process_matches(-1, None, None, **kw), False)
            (tmp / "reg").mkdir()
            (tmp / "reg" / "2164.json").write_text(json.dumps({
                "pid": 2164, "sessionId": "s-ghost", "cwd": "/home/u/Projects/comfyUI",
                "status": "idle", "procStart": "37198", "pidDomain": other}))
            self.assertEqual(read_session_registry(
                [tmp / "reg"], alive=functools.partial(process_matches, **kw)), {})

    def test_the_process_table_decides_without_procfs_details(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        with tempfile.TemporaryDirectory() as raw:
            noproc = Path(raw) / "noproc"
            self.assertIs(process_matches(os.getpid(), "anything", "x", proc=noproc), True)
            self.assertIs(process_matches(child.pid, None, None, proc=noproc), False)
        if not Path("/proc/self/stat").exists():
            self.skipTest("no procfs")
        own = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]
        domain = own_pid_domain()
        if domain is None:
            self.skipTest("no machine id")
        self.assertIs(process_matches(os.getpid(), own, domain), True)
        self.assertIs(process_matches(os.getpid(), own, None), False)
        self.assertIs(process_matches(os.getpid(), None, domain), False)
        self.assertIs(process_matches(os.getpid(), own + "1", domain), False)
        self.assertIs(process_matches(child.pid, None, None), False)


class PollTest(unittest.TestCase):
    def poll(self, states, observations, absent=frozenset(), repo=repo_of):
        return poll_changes(states, observations, absent, repo, project_of)

    def test_a_busy_to_idle_change_with_no_hook_is_one_seen_event(self):
        states = {"s1": sstate("s1", "working")}
        self.assertEqual(
            self.poll(states, {"s1": observation("s1", "idle")}),
            ([seen("s1", "idle")], frozenset()))
        self.assertEqual(self.poll(states, {"s1": observation("s1", "busy")}),
                         ([], frozenset()))

    def test_a_changed_directory_or_name_is_seen_and_the_repository_resolved_again(self):
        states = {"s1": sstate("s1", "idle")}

        def moved(status, **fields):
            return Observation("s1", fields.get("cwd", "/srv/p00"), 10, status, None,
                               fields.get("name", "n"), 5000)

        def payload(state, cwd, repo, name):
            return {"session_id": "s1", "cwd": cwd, "repo": repo, "state": state, "name": name}

        def elsewhere(cwd):
            return "/srv/p00" if cwd.startswith("/srv/p00") else "/srv/p01"

        self.assertEqual(
            self.poll(states, {"s1": moved("idle", cwd="/srv/p01")}, repo=elsewhere),
            ([(SEEN, None, payload("idle", "/srv/p01", "/srv/p01", "n"))], frozenset()))
        self.assertEqual(
            self.poll(states, {"s1": moved("busy", cwd="/srv/p01")}, repo=elsewhere),
            ([(SEEN, None, payload("working", "/srv/p01", "/srv/p01", "n"))], frozenset()))
        self.assertEqual(
            self.poll(states, {"s1": moved("idle", cwd="/srv/p00/sub")}, repo=elsewhere),
            ([(SEEN, "owner/p00", payload("idle", "/srv/p00/sub", "/srv/p00", "n"))],
             frozenset()))
        self.assertEqual(
            self.poll(states, {"s1": moved("idle", name="renamed")}),
            ([(SEEN, "owner/p00", payload("idle", "/srv/p00", "/srv/p00", "renamed"))],
             frozenset()))
        self.assertEqual(
            self.poll(states, {"s1": moved("shell", cwd="/srv/p01")}, repo=elsewhere),
            ([(SEEN, None, payload("idle", "/srv/p01", "/srv/p01", "n"))], frozenset()))
        self.assertEqual(self.poll(states, {"s1": moved("idle")}), ([], frozenset()))
        limit = {"s1": sstate("s1", "limit")}
        self.assertEqual(
            self.poll(limit, {"s1": moved("idle", name="renamed")}),
            ([(SEEN, "owner/p00", payload("limit", "/srv/p00", "/srv/p00", "renamed"))],
             frozenset()))

    def test_a_usage_limit_is_not_cleared_by_an_idle_registry(self):
        states = {"s1": sstate("s1", "limit")}
        self.assertEqual(self.poll(states, {"s1": observation("s1", "idle")}),
                         ([], frozenset()))
        self.assertEqual(self.poll(states, {"s1": observation("s1", "busy")}),
                         ([seen("s1", "working")], frozenset()))

    def test_a_session_is_gone_after_two_polls_without_it(self):
        states = {"s1": sstate("s1", "idle")}
        self.assertEqual(self.poll(states, {}), ([], frozenset({"s1"})))
        self.assertEqual(self.poll(states, {}, frozenset({"s1"})),
                         ([(GONE, "owner/p00", {"session_id": "s1"})], frozenset()))
        self.assertEqual(
            self.poll(states, {"s1": observation("s1", "idle")}, frozenset({"s1"})),
            ([], frozenset()))

    def test_a_new_session_in_the_registry_is_seen(self):
        obs = Observation("s2", "/srv/p00/sub", 20, "shell", None, None, 5000)
        payload = {"session_id": "s2", "cwd": "/srv/p00/sub", "repo": "/srv/p00",
                   "state": "idle"}
        self.assertEqual(self.poll({}, {"s2": obs}, repo=lambda cwd: "/srv/p00"),
                         ([(SEEN, "owner/p00", payload)], frozenset()))
        self.assertEqual(
            self.poll({}, {"s2": obs}, repo=lambda cwd: None),
            ([(SEEN, None, {**payload, "repo": None})], frozenset()))

    def test_a_registry_reading_older_than_the_last_hook_changes_nothing(self):
        states = {"s1": sstate("s1", "waiting_permission", 2000)}
        for updated in (1500, 2000, None):
            with self.subTest(updated=updated):
                self.assertEqual(
                    self.poll(states, {"s1": observation("s1", "busy", updated)}),
                    ([], frozenset()))
        self.assertEqual(
            self.poll(states, {"s1": observation("s1", "busy", 2500)}),
            ([seen("s1", "working")], frozenset()))

    def test_an_ended_session_is_not_brought_back_by_an_older_reading(self):
        states = {"s1": sstate("s1", ENDED, 2000)}
        self.assertEqual(self.poll(states, {"s1": observation("s1", "idle", 1999)}),
                         ([], frozenset()))
        self.assertEqual(self.poll(states, {"s1": observation("s1", "idle", 2001)}),
                         ([seen("s1", "idle")], frozenset()))
        _, absent = self.poll(states, {})
        self.assertEqual(self.poll(states, {}, absent),
                         ([(GONE, "owner/p00", {"session_id": "s1"})], frozenset()))


if __name__ == "__main__":
    unittest.main()
