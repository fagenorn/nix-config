"""The console's capacity fold (#860): parsing the proxy's report, the reset-aware reading, the view."""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import capacity
from agent_tools.console.capacity import (
    READING,
    STOP,
    CapacityState,
    Reading,
    capacity_state,
    capacity_view,
    parse_report,
    profile_capacity,
    report_entries,
)
from agent_tools.console.event_log import Event
from agent_tools.console.signin import SignIn
from agent_tools.console.view import (
    ALL_OUT_HEADLINE,
    ALL_OUT_SENTENCE,
    InboxRecord,
    ProjectState,
    ReadState,
    derive_view,
    encode_view,
)
from agent_tools.hosts import rate_limits

T = 1794400000
FIXTURES = Path(__file__).parent / "fixtures" / "cache_proxy"


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def fixture_headers(name):
    return [tuple(pair) for pair in json.loads((FIXTURES / f"{name}.json").read_text())["headers"]]


def window(status="allowed", utilization=0.0, reset=None):
    return {"status": status, "utilization": utilization, "reset": reset}


def report(**members):
    document = {"http_status": 200, "status": "allowed", "reset": None, "binding": None,
                "claim": None, "account": None, "session_id": None, "windows": {}}
    document.update(members)
    return document


def reading_of(document, profile="work", seq=1, at="t1"):
    parsed = parse_report(document)
    return Reading(profile, parsed["account"], parsed["session_id"], parsed["http_status"],
                   parsed["status"], parsed["reset"], parsed["binding"], parsed["claim"],
                   parsed["windows"], seq, at)


def refused_report():
    headers = fixture_headers("limits-refused")
    return rate_limits.report_document(429, headers, b"{}")


def open_reading_of(profile):
    return reading_of(report(
        status="allowed", reset=T + 3600, binding="7d", claim="seven_day",
        windows={"7d": window("allowed", 0.4, T + 3600)}), profile)


def open_reading():
    return reading_of(report(
        status="allowed", reset=T + 3600, binding="7d", claim="seven_day",
        windows={"7d": window("allowed", 0.4, T + 3600), "5h": window("allowed", 0.9, T + 600)}))


def event(seq, kind, payload, project=None):
    return Event(seq, f"t{seq}", kind, project, payload)


class ProfileCapacityTest(unittest.TestCase):
    def test_reset_aware_reading_table(self):
        table = [
            (T, "ok", 60, 10, iso(T + 600)),
            (T + 601, "ok", 60, 100, iso(T + 3600)),
            (T + 3601, "reset", 100, 100, None),
        ]
        for now, state, week, five, next_reset in table:
            with self.subTest(now=now):
                result = profile_capacity("work", open_reading(), now)
                self.assertEqual(
                    (result["state"], result["week_left"], result["five_hour_left"],
                     result["next_reset"], result["out_until"]),
                    (state, week, five, next_reset, None))
                self.assertEqual(result["profile"], "work")
                self.assertEqual(result["read_at"], "t1")

    def test_a_refusal_is_out_until_its_window_reset(self):
        refused = reading_of(refused_report())
        result = profile_capacity("work", refused, T)
        self.assertEqual(result["state"], "out")
        self.assertEqual(result["out_until"], iso(1794816000))
        self.assertEqual((result["week_left"], result["five_hour_left"]), (0, 100))
        after = profile_capacity("work", refused, 1794816000)
        self.assertEqual(after["state"], "reset")
        self.assertIsNone(after["out_until"])

    def test_the_latest_reset_among_out_windows_is_when_it_is_back(self):
        both = reading_of(report(
            http_status=429, status="rejected", reset=T + 50, binding="5h",
            windows={"5h": window("rejected", 1.0, T + 50), "7d": window("rejected", 1.0, T + 200)}))
        self.assertEqual(profile_capacity("work", both, T)["out_until"], iso(T + 200))

    def test_a_window_without_its_own_reset_uses_the_top_level_reset(self):
        refused = reading_of(report(
            http_status=429, status="rejected", binding="7d", claim="seven_day", reset=T + 100,
            windows={"7d": window("rejected", 1.0, None)}))
        out = profile_capacity("work", refused, T)
        self.assertEqual(out["state"], "out")
        self.assertEqual(out["out_until"], iso(T + 100))
        self.assertEqual(out["week_left"], 0)
        self.assertEqual(out["next_reset"], iso(T + 100))
        back = profile_capacity("work", refused, T + 100)
        self.assertEqual(back["state"], "reset")
        self.assertEqual(back["week_left"], 100)
        self.assertIsNone(back["out_until"])

    def test_a_refusal_without_a_top_level_reset_clears_at_the_binding_windows_reset(self):
        refused = reading_of(report(
            http_status=429, status="rejected", reset=None, binding="7d", claim="seven_day",
            windows={"7d": window("rejected", 1.0, T + 100), "5h": window("allowed", 0.2, T + 50)}))
        out = profile_capacity("work", refused, T)
        self.assertEqual((out["state"], out["out_until"]), ("out", iso(T + 100)))
        back = profile_capacity("work", refused, T + 100)
        self.assertEqual((back["state"], back["out_until"]), ("reset", None))
        self.assertEqual((back["week_left"], back["five_hour_left"]), (100, 100))

    def test_a_refusal_without_a_binding_uses_the_rejected_windows_reset(self):
        refused = reading_of(report(
            http_status=429, status="rejected", reset=None,
            windows={"5h": window("allowed", 0.2, T + 500), "7d": window("rejected", 1.0, T + 100)}))
        self.assertEqual(profile_capacity("work", refused, T)["out_until"], iso(T + 100))
        self.assertEqual(profile_capacity("work", refused, T + 100)["state"], "ok")

    def test_no_reading_is_unknown(self):
        self.assertEqual(profile_capacity("idle", None, T), {
            "profile": "idle", "state": "unknown", "week_left": None, "five_hour_left": None,
            "next_reset": None, "out_until": None, "read_at": None})


class ReportTest(unittest.TestCase):
    def test_only_whitelisted_members_are_kept(self):
        document = report(
            reset=T, windows={"7d": {**window("allowed", 0.5, T), "extra": 1}, "1m": {}})
        document["authorization"] = "Bearer t"
        parsed = parse_report(document)
        self.assertEqual(parsed, report(reset=T, windows={"7d": window("allowed", 0.5, T)}))
        self.assertNotIn("authorization", parsed)
        self.assertNotIn("extra", parsed["windows"]["7d"])
        self.assertNotIn("1m", parsed["windows"])

    def test_a_malformed_report_is_refused(self):
        def with_window(**members):
            return report(windows={"7d": {**window(), **members}})

        table = [
            ("not an object", ["status"]),
            ("status", report(status="Allowed!")),
            ("http_status", report(http_status="429")),
            ("utilization true", with_window(utilization=True)),
            ("utilization 10.5", with_window(utilization=10.5)),
            ("utilization inf", with_window(utilization=float("inf"))),
            ("reset -1", report(reset=-1)),
            ("reset 0", report(reset=0)),
            ("reset 10**11", report(reset=10**11)),
            ("session_id 65", report(session_id="a" * 65)),
        ]
        for name, document in table:
            with self.subTest(row=name):
                with self.assertRaises(ValueError):
                    parse_report(document)

    def test_every_document_the_proxy_produces_is_a_report(self):
        body = json.dumps({"metadata": {"user_id": json.dumps(
            {"account_uuid": "a" * 64, "session_id": "b" * 64})}}).encode()
        rows = [("-7d-reset", "0"), ("-7d-reset", "1"), ("-7d-reset", "99999999999"),
                ("-7d-reset", "100000000000"), ("-reset", "0"),
                ("-7d-utilization", "0"), ("-7d-utilization", "10"),
                ("-7d-utilization", "10.000001"), ("-7d-utilization", "9" * 400)]
        for suffix, value in rows:
            with self.subTest(header=suffix, value=value[:12]):
                name = f"anthropic-ratelimit-unified{suffix}"
                headers = [(k, v) for k, v in fixture_headers("limits-allowed") if k != name]
                headers.append((name, value))
                document = rate_limits.report_document(200, headers, body)
                self.assertEqual(parse_report(document), document)

    def test_a_refusal_gives_a_limit_stop_with_its_window_and_reset(self):
        refused = parse_report(refused_report())
        self.assertEqual(report_entries(refused, "work"), [
            (READING, None, {**refused, "profile": "work"}),
            (STOP, None, {"profile": "work", "window": "7d", "reset": 1794816000})])
        allowed = parse_report(report())
        self.assertEqual(report_entries(allowed, "work"),
                         [(READING, None, {**allowed, "profile": "work"})])
        five = parse_report(report(
            http_status=429, status="rejected", reset=T + 5, binding=None,
            windows={"5h": window("rejected", 1.0, T + 9), "7d": window("allowed", 0.1, T + 99)}))
        self.assertEqual(report_entries(five, "work")[1],
                         (STOP, None, {"profile": "work", "window": "5h", "reset": T + 9}))
        both = parse_report(report(
            http_status=429, status="rejected", reset=T + 5, binding=None,
            windows={"5h": window("rejected", 1.0, T + 9), "7d": window("rejected", 1.0, T + 99)}))
        self.assertEqual(report_entries(both, "work")[1],
                         (STOP, None, {"profile": "work", "window": "7d", "reset": T + 99}))


class CapacityStateTest(unittest.TestCase):
    def test_last_reading_per_profile_and_account_pairs_fold_incrementally(self):
        first = report(account="acct-1", reset=T + 1, windows={"7d": window("allowed", 0.1, T + 1)})
        second = report(account="acct-1", reset=T + 2)
        third = report(account="acct-2", reset=T + 3)
        events = [
            event(1, READING, {**first, "profile": "work"}),
            event(2, READING, {**second, "profile": "work"}),
            event(3, "session.seen", {"profile": "other"}),
            event(4, READING, {"profile": "bad", "status": "Nope"}),
            event(5, READING, {**third, "profile": "play"}),
            event(6, READING, {**report(), "profile": "bare"}),
        ]
        whole = capacity_state(events)
        self.assertEqual(sorted(whole.readings), ["bare", "play", "work"])
        self.assertEqual(whole.readings["work"].reset, T + 2)
        self.assertEqual((whole.readings["work"].seq, whole.readings["work"].at), (2, "t2"))
        self.assertEqual(whole.accounts, {"acct-1": "work", "acct-2": "play"})
        step = capacity_state(events[:2])
        self.assertEqual(capacity_state(events[2:], step), whole)
        self.assertEqual(step.readings["work"].reset, T + 2)


class CapacityViewTest(unittest.TestCase):
    def state_of(self, kinds, now=T):
        readings = {}
        for index, kind in enumerate(kinds):
            name = f"p{index}"
            if kind == "ok":
                readings[name] = reading_of(report(
                    reset=T + 1000, windows={"7d": window("allowed", 0.1, T + 1000)}), name)
            elif kind == "out":
                readings[name] = reading_of(report(
                    http_status=429, status="rejected", reset=T + 1000, binding="7d",
                    windows={"7d": window("rejected", 1.0, T + 1000)}), name)
            elif kind == "reset":
                readings[name] = reading_of(report(
                    reset=T - 10, windows={"7d": window("allowed", 0.1, T - 10)}), name)
        names = [f"p{index}" for index in range(len(kinds))]
        return capacity_view(names, CapacityState(readings, {}), now)

    def test_a_profile_without_a_configured_directory_is_not_current_capacity(self):
        refused = reading_of(report(
            http_status=429, status="rejected", reset=T + 100, binding="7d",
            windows={"7d": window("rejected", 1.0, T + 100)}))
        gone = reading_of(report(reset=T + 1000, windows={"7d": window("allowed", 0.1, T + 1000)}),
                          "gone")
        state = CapacityState({"work": refused, "gone": gone}, {})
        current = capacity_view(["work"], state, T)
        self.assertEqual([e["profile"] for e in current["profiles"]], ["work"])
        self.assertIs(current["all_out"], True)
        self.assertEqual(current["resumes_at"], iso(T + 100))
        self.assertIs(current["tight"], False)

    def test_tight_needs_every_other_profile_out(self):
        table = [(["ok"], False), (["ok", "out"], True), (["reset", "out", "out"], True),
                 (["ok", "unknown"], False), (["ok", "out", "unknown"], False),
                 (["ok", "ok"], False), (["out", "out"], False), (["unknown", "unknown"], False)]
        for kinds, tight in table:
            with self.subTest(kinds=kinds):
                self.assertIs(self.state_of(kinds)["tight"], tight)

    def test_profiles_with_no_reading_fold_into_one_note(self):
        three = self.state_of(["ok", "unknown", "unknown", "unknown"])
        self.assertEqual(three["no_reading"], "3 with no reading yet")
        self.assertEqual(len(three["profiles"]), 4)
        self.assertEqual(self.state_of(["ok", "out", "unknown"])["no_reading"],
                         "1 with no reading yet")
        self.assertIsNone(self.state_of(["ok", "out"])["no_reading"])
        self.assertIsNone(capacity.EMPTY["no_reading"])

    def test_every_profile_out_promotes_capacity_and_states_the_earliest_reset(self):
        def refused(until):
            return reading_of(report(
                http_status=429, status="rejected", reset=until, binding="7d",
                windows={"7d": window("rejected", 1.0, until)}))

        state = CapacityState({"a": refused(T + 100), "b": refused(T + 50)}, {})
        view_of = capacity_view(["a", "b"], state, T)
        project = ProjectState("p", "/srv/p", 1, "t1")
        item = {"key": "k", "project_id": "p", "answered": False, "held_work": 1}
        records = {("p", "k"): InboxRecord(item, "t1", "t1")}
        view = derive_view([project], records, {}, capacity=view_of)
        self.assertIs(view["capacity"]["all_out"], True)
        self.assertEqual(view["capacity"]["resumes_at"], iso(T + 50))
        self.assertEqual(view["statement"]["sentence"], ALL_OUT_SENTENCE)
        self.assertEqual(view["statement"]["inbox_items"], 1)
        self.assertEqual(view["statement"]["headline"], "1 thing needs you")
        stale = derive_view([project], {}, {"p": ReadState(False, None)}, capacity=view_of)
        self.assertEqual(stale["statement"]["headline"], ALL_OUT_HEADLINE)
        self.assertEqual(stale["statement"]["sentence"], ALL_OUT_SENTENCE)
        self.assertTrue(stale["statement"]["stale"])
        quiet = derive_view([project], capacity=view_of)
        self.assertEqual(quiet["statement"]["headline"], ALL_OUT_HEADLINE)
        self.assertEqual(quiet["statement"]["inbox_items"], 0)
        partial = capacity_view(["a", "idle"], CapacityState({"a": state.readings["a"]}, {}), T)
        self.assertIs(partial["all_out"], False)
        ordinary = derive_view([project], capacity=partial)["statement"]
        self.assertEqual(ordinary["headline"], "Nothing needs you")
        self.assertEqual(ordinary["sentence"], "1 registered project, and nothing is waiting on you.")

    def test_no_capacity_argument_equals_the_empty_capacity(self):
        states = [ProjectState("p", "/srv/p", 1, "t1", 2)]
        self.assertEqual(
            encode_view(derive_view(states)),
            encode_view(derive_view(states, capacity=capacity_view((), CapacityState({}, {}), 5.0))))
        self.assertEqual(derive_view(states)["capacity"], capacity.EMPTY)


def refused_reading(until, profile="work"):
    return reading_of(report(
        http_status=429, status="rejected", reset=until, binding="7d",
        windows={"7d": window("rejected", 1.0, until)}), profile)


class SigninCapacityTest(unittest.TestCase):
    def test_each_profile_entry_carries_its_sign_in(self):
        state = CapacityState({"work": open_reading()}, {})
        signins = {"work": SignIn("signed_in", iso(T + 10 * 86400), "t1")}
        shown = capacity_view(["spare", "work"], state, T, signins)
        by_name = {e["profile"]: e for e in shown["profiles"]}
        self.assertEqual(by_name["work"]["signin"], {
            "state": "signed_in", "ends_at": iso(T + 864000), "days_left": 10, "ask": False,
            "since": None})
        self.assertEqual(by_name["spare"]["signin"], {
            "state": "unknown", "ends_at": None, "days_left": None, "ask": False, "since": None})
        self.assertEqual(list(shown), ["tight", "all_out", "resumes_at", "no_reading", "profiles"])

    def test_a_signed_out_profile_is_not_a_profile_with_no_reading(self):
        signins = {"default": SignIn("signed_out", None, "t1")}
        shown = capacity_view(["default", "work"], CapacityState({}, {}), T, signins)
        self.assertEqual(shown["no_reading"], "1 with no reading yet")
        by_name = {e["profile"]: e for e in shown["profiles"]}
        self.assertEqual(by_name["default"]["state"], "unknown")
        self.assertEqual(by_name["default"]["signin"]["state"], "signed_out")
        covered = capacity_view(["default", "work"], CapacityState({"work": open_reading()}, {}),
                                T, signins)
        self.assertIsNone(covered["no_reading"])

    def test_a_signed_out_profile_never_blocks_all_out_or_tight(self):
        signed_out = {"default": SignIn("signed_out", None, "t1")}
        out = CapacityState({"work": refused_reading(T + 100)}, {})
        shown = capacity_view(["default", "work"], out, T, signed_out)
        self.assertIs(shown["all_out"], True)
        self.assertEqual(shown["resumes_at"], iso(T + 100))
        tight = CapacityState({"work": open_reading(), "spare": refused_reading(T + 100, "spare")},
                              {})
        self.assertIs(capacity_view(["default", "spare", "work"], tight, T, signed_out)["tight"],
                      True)
        alone = capacity_view(["default"], CapacityState({}, {}), T, signed_out)
        self.assertIs(alone["all_out"], False)
        self.assertIs(alone["tight"], False)
        self.assertIsNone(alone["no_reading"])
        old = CapacityState({"work": refused_reading(T + 100), "default": open_reading_of("default")},
                            {})
        kept = capacity_view(["default", "work"], old, T, signed_out)
        self.assertIs(kept["all_out"], True)
        self.assertEqual(kept["resumes_at"], iso(T + 100))
        self.assertEqual({e["profile"]: e["state"] for e in kept["profiles"]},
                         {"default": "ok", "work": "out"})
        today = capacity_view(["default", "work"], old, T)
        self.assertIs(today["all_out"], False)

    def test_an_ask_is_open_exactly_within_three_days_or_signed_out(self):
        empty = CapacityState({}, {})

        def ask(signin, now):
            return capacity_view(["work"], empty, now, {"work": signin})["profiles"][0]["signin"]

        ending = SignIn("signed_in", iso(T + 259200), "t1")
        self.assertIs(ask(ending, T - 1)["ask"], False)
        at = ask(ending, T)
        self.assertIs(at["ask"], True)
        self.assertEqual(at["since"], iso(T))
        self.assertIs(ask(SignIn("signed_in", iso(T + 30 * 86400), "t2"), T + 10)["ask"], False)
        out = ask(SignIn("signed_out", None, "t3"), T + 10)
        self.assertIs(out["ask"], True)
        self.assertEqual(out["since"], "t3")
        self.assertIs(ask(SignIn("unknown", None, "t4"), T + 10)["ask"], False)


if __name__ == "__main__":
    unittest.main()
