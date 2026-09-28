"""Transaction core slice 3: the administrative protocol (#206).

Run: just agent-workflow-tests
"""

import copy
import fcntl
import unittest

from agent_tools import transaction_history, transaction_storage
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import (
    MAX_ATTEMPTS, RETRY_WINDOW_MS, EffectResultInvalid, InvocationRefused, StaleCustody,
    StateInvalid, TransactionError, TransactionStore, TransitionRefused, action_id)

from .test_transaction_custody import TTL, CustodyCase, T0, plain, serialize

TID = "rel_01890a5d-ac96-7abc-8def-0123456789ab"


class ActionIdTest(unittest.TestCase):
    def test_the_id_is_act_plus_the_first_32_hex_of_the_digest(self):
        parameters = {"mode": "materialize", "subject": {"digest": "sha256:abc"}}
        expected = "act_" + telemetry_digest([TID, "build", parameters])[7:39]
        self.assertEqual(action_id(TID, "build", parameters), expected)
        self.assertRegex(expected, r"\Aact_[0-9a-f]{32}\Z")

    def test_re_derivation_is_stable_under_parameter_key_order(self):
        first = action_id(TID, "build", {"a": 1, "b": [1, 2]})
        self.assertEqual(action_id(TID, "build", {"b": [1, 2], "a": 1}), first)
        self.assertEqual(action_id(TID, "build", {"a": 1, "b": [1, 2]}), first)

    def test_any_changed_input_changes_the_id(self):
        base = action_id(TID, "build", {"a": 1})
        changed = {action_id(TID[:-1] + "c", "build", {"a": 1}),
                   action_id(TID, "stage", {"a": 1}), action_id(TID, "build", {"a": 2}),
                   action_id(TID, "build", {})}
        self.assertEqual(len(changed), 4)
        self.assertNotIn(base, changed)

    def test_malformed_inputs_are_refused(self):
        for args in ((TID, "", {}), (TID, 7, {}), (TID, "\ud800", {}), (TID, "b", []),
                     (TID, "b", {"x": float("nan")}), (TID, "b", {1: "x"}),
                     ("", "b", {}), (None, "b", {})):
            with self.subTest(args=args), self.assertRaises(StateInvalid):
                action_id(*args)


class VocabularyTest(unittest.TestCase):
    def test_the_retry_budget_constants(self):
        self.assertEqual((MAX_ATTEMPTS, RETRY_WINDOW_MS), (3, 900_000))

    def test_the_new_errors_are_transaction_errors_homed_in_storage(self):
        self.assertIs(InvocationRefused, transaction_storage.InvocationRefused)
        self.assertIs(EffectResultInvalid, transaction_storage.EffectResultInvalid)
        self.assertTrue(issubclass(InvocationRefused, TransactionError))
        self.assertTrue(issubclass(EffectResultInvalid, TransactionError))
        error = InvocationRefused("rel_x: refused", reason="window_closed")
        self.assertEqual((error.reason, str(error)), ("window_closed", "rel_x: refused"))

    def test_the_codecs_have_one_home_in_storage(self):
        for name in ("format_at", "parse_at", "json_object_violation"):
            self.assertIs(getattr(transaction_history, name),
                          getattr(transaction_storage, name))


OTHER_FENCE = {key: {"epoch": 9, "instance": "lin_" + "0" * 32}
               for key in ("project:alpha", "target:alpha")}


class Crash(Exception):
    """A runner dying inside an effect."""


class FakeWorld:
    """The external side: which attempt applied each idempotency key, and invoke counts."""

    def __init__(self):
        self.applied = {}
        self.invokes = {}


class FakeEffect:
    """An effect over a FakeWorld. `inspect_outcome` forces the observation; `results`
    scripts each invoke's (result, error_class), default accepted; `crash` is "before"
    (raise before touching the world) or "after" (apply, then raise); `during` runs at
    the start of every call. References encode what the request carried."""

    def __init__(self, world, *, inspect_outcome=None, results=(), crash=None, during=None):
        self.world, self.inspect_outcome = world, inspect_outcome
        self.results, self.crash, self.during = list(results), crash, during

    def inspect(self, request):
        if self.during:
            self.during()
        outcome = self.inspect_outcome or (
            "satisfied" if request["action_id"] in self.world.applied else "absent")
        epoch = min(entry["epoch"] for entry in request["fence"].values())
        return {"outcome": outcome, "reference": f"seen:{request['attempt']}:{epoch}"}

    def invoke(self, request):
        if self.during:
            self.during()
        key = request["action_id"]
        if self.crash == "before":
            raise Crash(key)
        self.world.invokes[key] = self.world.invokes.get(key, 0) + 1
        result, error_class = self.results.pop(0) if self.results else ("accepted", None)
        if result == "accepted":
            self.world.applied[key] = request["attempt"]
        if self.crash == "after":
            raise Crash(key)
        return {"result": result, "error_class": error_class,
                "reference": f"call:{request['attempt']}"}


def renumbered(document):
    for seq, event in enumerate(document["events"], start=1):
        event["seq"] = seq
    document["revision"] = len(document["events"])
    return document


class ProtocolCase(CustodyCase):
    NAME = "build"
    PARAMETERS = {"mode": "materialize", "subject": {"digest": "sha256:abc"}}

    def setUp(self):
        super().setUp()
        self.world = FakeWorld()
        self.transaction_id = self.new()
        self.custody = self.acquire(self.transaction_id)

    def effect(self, **options):
        return FakeEffect(self.world, **options)

    def to(self, *targets, custody=None):
        for target in targets:
            after = self.store.advance(self.transaction_id, target, reason="r",
                                       external_state="known",
                                       custody=custody or self.custody)
        return after

    def publishing(self):
        return self.to("awaiting_verification", "ready", "publishing")

    def inspect(self, effect=None, *, custody=None, name=None):
        return self.store.inspect_action(
            custody or self.custody, name=name or self.NAME, parameters=self.PARAMETERS,
            effect=effect or self.effect())

    def act(self, name=None):
        return action_id(self.transaction_id, name or self.NAME, self.PARAMETERS)

    def view(self):
        [entry] = self.store.load(self.transaction_id).actions
        return dict(entry)

    def action_types(self):
        return [e["type"] for e in self.store.load(self.transaction_id).events
                if e["type"].startswith(("action_", "invocation_"))]


class SchemaTest(ProtocolCase):
    def test_new_state_is_v3_and_a_v2_document_fails_closed_naming_its_version(self):
        document = self.state_doc(self.transaction_id)
        self.assertEqual(document["schema"], "transaction-state/v3")
        self.assertRuleRefuses(self.transaction_id,
                               {**document, "schema": "transaction-state/v2"},
                               "transaction-state/v2")


class InspectActionTest(ProtocolCase):
    def test_a_first_inspection_declares_the_action_and_records_the_outcome(self):
        after = self.inspect()
        at = "2027-01-15T08:00:00.000Z"
        self.assertEqual([dict(e) for e in after.events[2:]], [
            {"seq": 3, "type": "action_declared", "at": at, "action_id": self.act(),
             "name": "build", "parameters": self.PARAMETERS},
            {"seq": 4, "type": "action_inspected", "at": at, "action_id": self.act(),
             "outcome": "absent", "reference": "seen:0:1",
             "fence": plain(self.custody.fence)}])
        self.assertEqual(self.view(), {
            "action_id": self.act(), "name": "build", "attempts": 0, "status": "absent",
            "last_error_class": None, "retry_eligible": True, "retry_deadline_at": None})
        self.assertEqual(self.world.invokes, {})
        self.assertEqual(TransactionStore(self.root).load(self.transaction_id).actions,
                         after.actions)

    def test_a_later_inspection_appends_only_its_outcome(self):
        self.inspect()
        self.world.applied[self.act()] = 0
        self.assertEqual(self.inspect().events[-1]["outcome"], "satisfied")
        self.assertEqual(self.action_types(),
                         ["action_declared", "action_inspected", "action_inspected"])
        self.assertEqual(self.view()["status"], "satisfied")

    def test_every_outcome_is_recorded_and_a_parking_may_inspect(self):
        self.to("attention_required")
        for outcome in ("in_progress", "diverged", "unknown", "absent", "satisfied"):
            self.inspect(self.effect(inspect_outcome=outcome))
            self.assertEqual(self.view()["status"], outcome)
            self.assertEqual(self.view()["retry_eligible"], outcome == "absent")

    def test_actions_are_listed_in_declaration_order(self):
        for name in ("stage", "build", "stage"):
            self.inspect(name=name)
        self.assertEqual([e["name"] for e in self.store.load(self.transaction_id).actions],
                         ["stage", "build"])

    def test_malformed_arguments_are_refused_before_any_lock(self):
        effect = self.effect(during=self.fail)
        cases = ({"name": "", "parameters": {}, "effect": effect},
                 {"name": "b", "parameters": [], "effect": effect},
                 {"name": "b", "parameters": {"x": float("nan")}, "effect": effect},
                 {"name": "b", "parameters": {}, "effect": object()})
        with open(self.root / self.transaction_id / "lock", "r+") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for kwargs in cases:
                with self.subTest(kwargs=kwargs):
                    self.assertRefusedUnchanged(StateInvalid, lambda: self.store.inspect_action(
                        self.custody, **kwargs))
            self.assertRefusedUnchanged(StateInvalid, lambda: self.store.inspect_action(
                "not custody", name="b", parameters={}, effect=effect))

    def test_a_malformed_inspect_result_is_refused_with_nothing_recorded(self):
        class Returning(FakeEffect):
            def inspect(self, request):
                return self.inspect_outcome

        for result in (None, {"outcome": "absent"}, {"outcome": "gone", "reference": "r"},
                       {"outcome": "absent", "reference": ""},
                       {"outcome": "absent", "reference": "r", "extra": 1}):
            with self.subTest(result=result):
                self.assertRefusedUnchanged(EffectResultInvalid, lambda: self.inspect(
                    Returning(self.world, inspect_outcome=result)))

    def test_stale_or_terminal_holders_are_refused_before_the_effect_runs(self):
        self.clock.advance(TTL)
        self.assertRefusedUnchanged(StaleCustody,
                                    lambda: self.inspect(self.effect(during=self.fail)))
        self.clock.advance(-TTL)
        self.to("abandoned")
        self.assertRefusedUnchanged(TransitionRefused,
                                    lambda: self.inspect(self.effect(during=self.fail)))

    def test_a_lease_lapse_during_the_call_records_nothing(self):
        self.assertRefusedUnchanged(StaleCustody, lambda: self.inspect(
            self.effect(during=lambda: self.clock.advance(TTL))))

    def test_hand_edited_action_histories_fail_the_named_rule(self):
        self.inspect()
        good = self.state_doc(self.transaction_id)
        released = {"type": "lease_released", "at": good["events"][2]["at"],
                    "fence": plain(self.custody.fence), "reason": "released"}

        def edit(change):
            document = copy.deepcopy(good)
            change(document["events"])
            return renumbered(document)

        cases = {
            "does not re-derive from its name and parameters":
                lambda ev: ev[2].update(name="stage"),
            "is declared twice": lambda ev: ev.append(copy.deepcopy(ev[2])),
            "name '' is not a non-empty string": lambda ev: ev[2].update(name=""),
            "parameters is not a JSON object": lambda ev: ev[2].update(parameters=[]),
            "fence is not a non-empty object": lambda ev: ev[3].update(fence={}),
            "has no earlier action_declared": lambda ev: ev.pop(2),
            "action_id is not a string": lambda ev: ev[3].update(action_id=["x"]),
            "outcome is not absent, in_progress, satisfied, diverged or unknown":
                lambda ev: ev[3].update(outcome="gone"),
            "reference is not a non-empty string": lambda ev: ev[3].update(reference=""),
            "fence does not equal the open span's fence":
                lambda ev: ev[3].update(fence=OTHER_FENCE),
            "sits outside an open custody span": lambda ev: ev.insert(2, dict(released)),
            "is not the closed action_inspected event": lambda ev: ev[3].update(extra=1),
        }
        for fragment, change in cases.items():
            with self.subTest(fragment=fragment):
                self.assertRuleRefuses(self.transaction_id, edit(change), fragment)


THROTTLED = ("rejected", "provider_throttled")


class InvokeCase(ProtocolCase):
    def setUp(self):
        super().setUp()
        self.publishing()

    def invoke(self, effect=None, *, custody=None, name=None):
        return self.store.invoke_action(
            custody or self.custody, name=name or self.NAME, parameters=self.PARAMETERS,
            effect=effect or self.effect())

    def refused(self, reason, call, name=None):
        error = self.assertRefusedUnchanged(InvocationRefused, call)
        self.assertEqual(error.reason, reason)
        self.assertIn(self.transaction_id, str(error))
        self.assertIn(self.act(name), str(error))
        return error

    def views(self):
        return {e["name"]: dict(e) for e in self.store.load(self.transaction_id).actions}

    def attempts(self, name=None):
        identity = self.act(name)
        return [e["attempt"] for e in self.store.load(self.transaction_id).events
                if e["type"] == "invocation_intended" and e["action_id"] == identity]

    def wait(self, ms):
        while ms:
            step = min(ms, 400_000)
            self.clock.advance(step)
            ms -= step
            self.store.renew(self.custody)


class InvokeActionTest(InvokeCase):
    def test_an_absent_action_is_invoked_once_then_inspected(self):
        self.inspect()
        after = self.invoke()
        fence, at = plain(self.custody.fence), "2027-01-15T08:00:00.000Z"
        self.assertEqual([dict(e) for e in after.events[7:]], [
            {"seq": 8, "type": "invocation_intended", "at": at, "action_id": self.act(),
             "attempt": 1, "fence": fence},
            {"seq": 9, "type": "invocation_returned", "at": at, "action_id": self.act(),
             "attempt": 1, "result": "accepted", "error_class": None,
             "reference": "call:1", "fence": fence},
            {"seq": 10, "type": "action_inspected", "at": at, "action_id": self.act(),
             "outcome": "satisfied", "reference": "seen:1:1", "fence": fence}])
        self.assertEqual((self.world.invokes, self.world.applied),
                         ({self.act(): 1}, {self.act(): 1}))
        self.assertEqual((self.view()["status"], self.view()["attempts"]), ("satisfied", 1))

    def test_a_satisfied_action_is_never_invoked_again(self):
        self.inspect()
        self.invoke()
        before = self.files()
        self.assertEqual(self.invoke(self.effect(during=self.fail)).revision, 10)
        self.assertEqual(self.files(), before)
        self.assertEqual(self.world.invokes, {self.act(): 1})

    def test_an_inspection_reading_satisfied_settles_the_action_without_a_call(self):
        self.world.applied[self.act()] = 0
        self.inspect()
        self.invoke(self.effect(during=self.fail))
        self.assertEqual(self.world.invokes, {})
        self.assertEqual(self.action_types(), ["action_declared", "action_inspected"])

    def test_a_blind_invoke_is_refused_before_any_call(self):
        self.refused("inspection_required", lambda: self.invoke(self.effect(during=self.fail)))
        self.assertEqual(self.world.invokes, {})

    def test_an_inspection_that_is_not_absent_refuses_the_call(self):
        for outcome in ("in_progress", "diverged", "unknown"):
            with self.subTest(outcome=outcome):
                self.inspect(self.effect(inspect_outcome=outcome))
                self.refused("not_absent", lambda: self.invoke(self.effect(during=self.fail)))

    def test_only_publishing_and_activating_may_invoke(self):
        self.inspect()
        self.to("attention_required")
        self.refused("state_not_effectful", lambda: self.invoke(self.effect(during=self.fail)))
        self.to("publishing", "published")
        self.refused("state_not_effectful", lambda: self.invoke(self.effect(during=self.fail)))
        self.to("activating")
        self.invoke()
        self.assertEqual(self.world.invokes, {self.act(): 1})

    def test_a_throttled_attempt_is_retried_once(self):
        self.inspect()
        self.invoke(self.effect(results=[THROTTLED]))
        self.assertEqual(self.view(), {
            "action_id": self.act(), "name": "build", "attempts": 1, "status": "absent",
            "last_error_class": "provider_throttled", "retry_eligible": True,
            "retry_deadline_at": "2027-01-15T08:15:00.000Z"})
        self.clock.advance(30_000)
        self.invoke()
        self.assertEqual(self.view(), {
            "action_id": self.act(), "name": "build", "attempts": 2, "status": "satisfied",
            "last_error_class": None, "retry_eligible": False,
            "retry_deadline_at": "2027-01-15T08:15:00.000Z"})
        self.assertEqual((self.attempts(), self.world.invokes), ([1, 2], {self.act(): 2}))

    def test_a_fourth_try_is_refused_budget_exhausted(self):
        self.inspect()
        throttled = self.effect(results=[THROTTLED] * 3)
        for _ in range(MAX_ATTEMPTS):
            self.invoke(throttled)
        self.assertFalse(self.view()["retry_eligible"])
        self.refused("budget_exhausted", lambda: self.invoke(self.effect(during=self.fail)))
        self.assertEqual(self.world.invokes, {self.act(): 3})

    def test_the_window_admits_exactly_900_000_ms_and_refuses_one_more(self):
        for name in ("late", "exact"):
            self.inspect(name=name)
            self.invoke(self.effect(results=[THROTTLED]), name=name)
            self.clock.advance(1)
        self.wait(RETRY_WINDOW_MS - 1)
        self.refused("window_closed",
                     lambda: self.invoke(self.effect(during=self.fail), name="late"),
                     name="late")
        self.invoke(name="exact")
        self.assertEqual(self.views()["exact"]["status"], "satisfied")

    def test_a_non_retry_safe_class_or_an_accepted_absent_attempt_is_not_retryable(self):
        for name, result in (("denied", ("rejected", "invalid_input")),
                             ("vanished", ("accepted", None))):
            with self.subTest(name=name):
                self.inspect(name=name)
                self.invoke(self.effect(results=[result], inspect_outcome="absent"), name=name)
                self.assertFalse(self.views()[name]["retry_eligible"])
                self.refused("not_retryable",
                             lambda: self.invoke(self.effect(during=self.fail), name=name),
                             name=name)

    def test_an_inspection_from_an_earlier_custody_span_licenses_no_call(self):
        self.inspect()
        self.invoke(self.effect(results=[THROTTLED]))
        self.store.release(self.custody)
        self.custody = self.acquire(self.transaction_id)
        self.refused("inspection_required", lambda: self.invoke(self.effect(during=self.fail)))
        self.assertEqual(self.inspect().events[-1]["reference"], "seen:1:2")
        self.invoke()
        self.assertEqual((self.attempts(), self.world.invokes), ([1, 2], {self.act(): 2}))

    def test_a_malformed_invoke_result_leaves_the_intent_open(self):
        class Returning(FakeEffect):
            def invoke(self, request):
                return self.results[0]

        for index, result in enumerate((
                None, {"result": "accepted", "error_class": None},
                {"result": "done", "error_class": None, "reference": "r"},
                {"result": "accepted", "error_class": "invalid_input", "reference": "r"},
                {"result": "rejected", "error_class": None, "reference": "r"},
                {"result": "rejected", "error_class": "flaky", "reference": "r"},
                {"result": "accepted", "error_class": None, "reference": ""})):
            with self.subTest(result=result):
                name = f"bad-{index}"
                self.inspect(name=name)
                with self.assertRaises(EffectResultInvalid):
                    self.invoke(Returning(self.world, results=[result]), name=name)
                self.assertEqual(self.views()[name]["status"], "open")
                self.assertEqual(self.store.load(self.transaction_id).events[-1]["type"],
                                 "invocation_intended")

    def test_a_lease_lapse_during_the_call_leaves_the_intent_open(self):
        self.inspect()
        with self.assertRaises(StaleCustody):
            self.invoke(self.effect(during=lambda: self.clock.advance(TTL)))
        self.assertEqual(self.action_types()[-1], "invocation_intended")
        self.assertEqual(self.world.invokes, {self.act(): 1})

    def test_hand_edited_attempt_histories_fail_the_named_rule(self):
        self.inspect()
        self.invoke(self.effect(results=[THROTTLED]))
        self.invoke()
        good = self.state_doc(self.transaction_id)
        parked = {"type": "transitioned", "at": good["events"][7]["at"],
                  "from": "publishing", "to": "attention_required", "reason": "r",
                  "external_state": None}

        def edit(change):
            document = copy.deepcopy(good)
            change(document["events"])
            return renumbered(document)

        cases = {
            "attempt 3 does not follow attempt 1": lambda ev: ev[10].update(attempt=3),
            "does not follow an absent inspection under its fence": lambda ev: ev.pop(9),
            "invocation_intended sits outside publishing and activating":
                lambda ev: ev.insert(7, dict(parked)),
            "retry follows an attempt that is not retry-safe":
                lambda ev: ev[8].update(error_class="invalid_input"),
            "invocation_returned follows no open attempt":
                lambda ev: ev.insert(10, copy.deepcopy(ev[8])),
            "attempt 1 already returned": lambda ev: ev.insert(9, copy.deepcopy(ev[8])),
            "attempt does not name the open attempt": lambda ev: ev[8].update(attempt=2),
            "result is not accepted, rejected or unknown":
                lambda ev: ev[8].update(result="done"),
            "error_class does not match the result":
                lambda ev: ev[11].update(error_class="provider_throttled"),
            "is not the closed invocation_intended event": lambda ev: ev[7].update(extra=1),
            "reference is not a non-empty string": lambda ev: ev[8].update(reference=""),
        }
        for fragment, change in cases.items():
            with self.subTest(fragment=fragment):
                self.assertRuleRefuses(self.transaction_id, edit(change), fragment)
        for attempt in (True, 1.0):
            with self.subTest(attempt=attempt):
                self.assertRuleRefuses(
                    self.transaction_id, edit(lambda ev: ev[8].update(attempt=attempt)),
                    "attempt does not name the open attempt")

    def test_a_return_under_another_fence_than_its_intent_is_refused(self):
        self.inspect()
        with self.assertRaises(Crash):
            self.invoke(self.effect(crash="before"))
        self.store.release(self.custody)
        self.custody = self.acquire(self.transaction_id)
        document = self.state_doc(self.transaction_id)
        document["events"].append({
            "type": "invocation_returned", "at": document["events"][-1]["at"],
            "action_id": self.act(), "attempt": 1, "result": "accepted", "error_class": None,
            "reference": "r", "fence": plain(self.custody.fence)})
        self.assertRuleRefuses(self.transaction_id, renumbered(document),
                               "fence does not equal its intent's")

    def test_a_fourth_attempt_in_history_is_refused(self):
        self.inspect()
        throttled = self.effect(results=[THROTTLED] * 3)
        for _ in range(MAX_ATTEMPTS):
            self.invoke(throttled)
        document = self.state_doc(self.transaction_id)
        document["events"].append({**document["events"][-3], "attempt": 4})
        self.assertRuleRefuses(self.transaction_id, renumbered(document),
                               "attempt 4 exceeds 3")


class CrashSeamTest(InvokeCase):
    def crash(self, where):
        self.inspect()
        with self.assertRaises(Crash):
            self.invoke(self.effect(crash=where))

    def reacquire(self):
        self.store.release(self.custody)
        self.custody = self.acquire(self.transaction_id)

    def test_a_crash_before_the_call_leaves_an_open_intent_and_resumes_as_attempt_2(self):
        self.crash("before")
        self.assertEqual(self.state_doc(self.transaction_id)["events"][-1]["type"],
                         "invocation_intended")
        self.assertEqual((self.world.invokes, self.world.applied), ({}, {}))
        self.assertEqual(self.view()["status"], "open")
        self.refused("inspection_required", lambda: self.invoke(self.effect(during=self.fail)))
        self.refused("attempt_in_flight", lambda: self.inspect(self.effect(during=self.fail)))
        self.reacquire()
        self.assertEqual(self.inspect().events[-1]["outcome"], "absent")
        self.assertTrue(self.view()["retry_eligible"])
        self.invoke()
        self.assertEqual((self.attempts(), self.world.invokes), ([1, 2], {self.act(): 1}))
        self.assertEqual(self.view()["status"], "satisfied")

    def test_an_effect_that_applied_then_raised_is_settled_without_a_second_call(self):
        self.crash("after")
        self.refused("attempt_in_flight", lambda: self.inspect(self.effect(during=self.fail)))
        self.reacquire()
        self.assertEqual(self.inspect().events[-1]["outcome"], "satisfied")
        self.invoke(self.effect(during=self.fail))
        self.assertEqual((self.attempts(), self.world.invokes), ([1], {self.act(): 1}))

    def test_an_observation_made_before_a_newer_attempt_is_not_recorded(self):
        self.inspect()
        with self.assertRaises(InvocationRefused) as caught:
            self.inspect(self.effect(inspect_outcome="absent", during=lambda: self.invoke()))
        self.assertEqual(caught.exception.reason, "attempt_in_flight")
        self.assertEqual(self.store.load(self.transaction_id).events[-1]["outcome"],
                         "satisfied")
        self.assertEqual((self.view()["status"], self.world.invokes),
                         ("satisfied", {self.act(): 1}))

    def test_a_return_less_attempt_closed_under_its_own_fence_is_refused(self):
        self.crash("before")
        document = self.state_doc(self.transaction_id)
        intent = document["events"][-1]
        document["events"].append({
            "type": "action_inspected", "at": intent["at"], "action_id": self.act(),
            "outcome": "absent", "reference": "r", "fence": intent["fence"]})
        self.assertRuleRefuses(self.transaction_id, renumbered(document),
                               "closes a return-less attempt under its intent's fence")

    def test_a_malformed_post_invoke_inspection_leaves_the_attempt_open(self):
        self.inspect()
        with self.assertRaises(EffectResultInvalid):
            self.invoke(self.effect(inspect_outcome="done"))
        self.assertEqual(self.action_types()[-1], "invocation_intended")
        self.assertEqual((self.view()["status"], self.world.invokes),
                         ("open", {self.act(): 1}))


if __name__ == "__main__":
    unittest.main()
