"""Contract tests for `holding` (`agent_tools.delivery.holding`): the pure close-out hold gate and hold texts."""

from __future__ import annotations

import json
import unittest

from agent_tools.delivery import holding
from agent_tools.verification import verify_block

TIER = "fast"

MERGE = "a" * 40
VERIFICATION = ["lint", "test"]
NOT_BEFORE = {"not_before": "2099-01-01T00:00:00Z"}
EVIDENCE = {"ac": "AC2", "kind": "evidence", "host": "any", "when": NOT_BEFORE, "run": {"command": "test"}}
ASK = {"ac": "AC3", "kind": "human", "host": "any", "when": NOT_BEFORE,
       "run": {"ask": "Does the greeting read well?"}, "reason": "taste"}

BODY = """## Acceptance criteria

- [ ] [code] The greeting is printed.
- [ ] [evidence] The greeting reads well in production.
- [ ] Something untagged.
"""


def criterion(number: int, kind: str | None, text: str = "text") -> dict:
    return {"id": f"AC{number}", "kind": kind, "text": text}


CRITERIA = [criterion(1, "code"), criterion(2, "evidence", "proof")]
HUMAN_CRITERIA = [criterion(1, "code"), criterion(2, "evidence", "proof"), criterion(3, "human", "taste")]


def written(*checks: dict) -> list[dict]:
    return [{"ac": check["ac"], "check": json.dumps(check)} for check in checks]


def gate(criteria=None, **given) -> dict:
    arguments = {"criteria": CRITERIA if criteria is None else criteria, "posted": [], "blocks": [],
                 "answered": [], "written": written(EVIDENCE), "merge": MERGE, "issue": 41,
                 "verification": VERIFICATION}
    arguments.update(given)
    return holding.gate(**arguments)


def fence(issue: int, *checks: dict, merge: str = MERGE, results: bool = False, comment_id: int = 9) -> dict:
    return {"issue": issue, "merge": merge, "checks": list(checks), "comment_id": comment_id,
            "results": results}


class CriteriaTest(unittest.TestCase):
    def test_criteria_reads_ids_kinds_and_texts_in_body_order(self):
        self.assertEqual(holding.criteria(BODY), [
            {"id": "AC1", "kind": "code", "text": "The greeting is printed."},
            {"id": "AC2", "kind": "evidence", "text": "The greeting reads well in production."},
            {"id": "AC3", "kind": None, "text": "Something untagged."},
        ])


class GateTest(unittest.TestCase):
    def test_gate_is_ready_with_the_parent_block_of_the_open_criteria_and_no_split_when_nothing_is_blocked(self):
        self.assertEqual(gate(), {"verdict": "ready", "block": {"v": 1, "merge": MERGE, "checks": [EVIDENCE]},
                                  "split": [], "held": [{"id": "AC2", "kind": "evidence", "text": "proof"}]})

    def test_a_criterion_without_a_check_is_missing_checks(self):
        verdict = gate(written=[])
        self.assertEqual((verdict["verdict"], verdict["acs"]), ("missing-checks", ["AC2"]))

    def test_a_human_criterion_with_a_machine_check_is_missing_checks(self):
        machine = {**EVIDENCE, "ac": "AC3"}
        verdict = gate(HUMAN_CRITERIA, written=written(EVIDENCE, machine))
        self.assertEqual((verdict["verdict"], verdict["acs"]), ("missing-checks", ["AC3"]))

    def test_an_owner_check_for_an_evidence_criterion_is_human_checks(self):
        owner = {**ASK, "ac": "AC2"}
        verdict = gate(written=written(owner))
        self.assertEqual((verdict["verdict"], verdict["acs"]), ("human-checks", ["AC2"]))

    def test_an_owner_check_for_an_evidence_criterion_in_a_posted_fence_is_human_checks_naming_that_issue(self):
        verdict = gate(posted=[fence(77, {**ASK, "ac": "ac2"})])
        self.assertEqual((verdict["verdict"], verdict["acs"], verdict["posted_holds"]),
                         ("human-checks", ["AC2"], [77]))

    def test_a_command_outside_the_verification_ids_is_unattended(self):
        for run in ({"command": "deploy"}, {"command": "test", "then": {"command": "deploy"}}):
            check = {**EVIDENCE, "run": run} if "then" not in run else {**EVIDENCE, "run": {"then": run["then"]}}
            with self.subTest(run=run):
                verdict = gate(written=written(check))
                self.assertEqual((verdict["verdict"], verdict["acs"]), ("unattended", ["AC2"]))

    def test_a_posted_own_check_whose_ac_is_no_string_is_left_to_the_lint_not_a_crash(self):
        for ac in ([], 7, None, {"x": 1}):
            nameless = {**EVIDENCE, "ac": ac, "run": {"command": "curl"}}
            with self.subTest(ac=ac):
                self.assertEqual(gate(posted=[fence(41, EVIDENCE, nameless)])["verdict"], "ready")
        keyless = {key: value for key, value in EVIDENCE.items() if key != "ac"}
        self.assertEqual(gate(posted=[fence(41, EVIDENCE, {**keyless, "run": {"command": "curl"}})])["verdict"],
                         "ready")

    def test_a_posted_machine_check_for_a_human_criterion_is_owner_checks(self):
        machine = {**EVIDENCE, "ac": "AC3"}
        verdict = gate(HUMAN_CRITERIA, written=written(EVIDENCE, ASK), posted=[fence(50, machine)])
        self.assertEqual((verdict["verdict"], verdict["acs"], verdict["posted_holds"]),
                         ("owner-checks", ["AC3"], [50]))

    def test_an_own_fence_without_the_owner_check_of_an_unsplit_human_criterion_is_owner_checks(self):
        verdict = gate(HUMAN_CRITERIA, written=written(EVIDENCE, ASK), posted=[fence(41, EVIDENCE)])
        self.assertEqual((verdict["verdict"], verdict["acs"], verdict["posted_holds"]),
                         ("owner-checks", ["AC3"], [41]))

    def test_a_posted_check_running_another_script_invocation_is_script_checks(self):
        script = {**EVIDENCE, "run": {"script": "scripts/check.sh", "args": ["a"]}}
        other = {**script, "run": {"script": "scripts/check.sh", "args": ["b"]}}
        verdict = gate(written=written(script), posted=[fence(41, other)])
        self.assertEqual((verdict["verdict"], verdict["acs"], verdict["posted_holds"]),
                         ("script-checks", ["AC2"], [41]))

    def test_a_posted_own_fence_checking_a_note_is_note_checks(self):
        note = {**EVIDENCE, "ac": "AC3"}
        verdict = gate([*CRITERIA, criterion(3, "note")], posted=[fence(41, EVIDENCE, note)])
        self.assertEqual((verdict["verdict"], verdict["acs"]), ("note-checks", ["AC3"]))

    def test_a_posted_own_fence_missing_an_open_criterion_is_missing_checks_unless_a_child_fence_of_the_merge_holds_the_human_one(self):
        arguments = {"criteria": HUMAN_CRITERIA, "written": written(EVIDENCE, ASK), "blocks": [50]}
        own = fence(41, EVIDENCE)
        verdict = gate(**arguments, posted=[own])
        self.assertEqual((verdict["verdict"], verdict["acs"]), ("missing-checks", ["AC3"]))
        child = fence(50, ASK)
        self.assertEqual(gate(**arguments, posted=[own, child])["verdict"], "ready")
        elsewhere = fence(50, ASK, merge="b" * 40)
        self.assertEqual(gate(**arguments, posted=[own, elsewhere])["verdict"], "missing-checks")

    def test_gate_refusals_come_in_the_programs_order(self):
        criteria = [criterion(1, "code"), criterion(2, "evidence"), criterion(3, "evidence"),
                    criterion(4, "evidence")]
        owner = {**ASK, "ac": "AC2"}
        outside = {**EVIDENCE, "ac": "AC3", "run": {"command": "deploy"}}
        fine = {**EVIDENCE, "ac": "AC4"}
        verdict = gate(criteria, written=written(owner, outside))
        self.assertEqual((verdict["verdict"], verdict["acs"]), ("missing-checks", ["AC4"]))
        verdict = gate(criteria, written=written(owner, outside, fine))
        self.assertEqual((verdict["verdict"], verdict["acs"]), ("human-checks", ["AC2"]))
        verdict = gate(criteria, written=written(EVIDENCE, outside, fine))
        self.assertEqual((verdict["verdict"], verdict["acs"]), ("unattended", ["AC3"]))

    def test_gate_drops_the_criteria_the_look_approval_answers(self):
        self.assertEqual(gate(answered=["ac2"], written=[]),
                         {"verdict": "ready", "block": None, "split": [], "held": []})

    def test_gate_splits_human_criteria_only_when_the_issue_blocks_another(self):
        arguments = {"criteria": HUMAN_CRITERIA, "written": written(EVIDENCE, ASK)}
        split = gate(**arguments, blocks=[50])
        self.assertEqual(split["split"], [{"ac": "AC3", "block": {"v": 1, "merge": MERGE, "checks": [ASK]}}])
        self.assertEqual(split["block"], {"v": 1, "merge": MERGE, "checks": [EVIDENCE]})
        whole = gate(**arguments, blocks=[])
        self.assertEqual(whole["split"], [])
        self.assertEqual(whole["block"], {"v": 1, "merge": MERGE, "checks": [EVIDENCE, ASK]})

    def test_gate_block_is_none_when_every_open_criterion_is_split(self):
        verdict = gate([criterion(1, "code"), criterion(3, "human", "taste")], written=written(ASK), blocks=[50])
        self.assertEqual((verdict["verdict"], verdict["block"], verdict["held"]), ("ready", None, []))
        self.assertEqual([entry["ac"] for entry in verdict["split"]], ["AC3"])


class WrittenTest(unittest.TestCase):
    def test_parse_written_drops_an_entry_that_is_not_a_json_object(self):
        entries = [{"ac": "AC2", "check": json.dumps(EVIDENCE)}, {"ac": "AC3", "check": "not json"},
                   {"ac": "AC4", "check": "[1]"}]
        self.assertEqual(holding.parse_written(entries), [EVIDENCE])

    def test_parse_written_drops_a_check_that_is_not_strict_json(self):
        nonfinite = json.dumps(EVIDENCE)[:-1] + ', "expect": NaN}'
        repeated = json.dumps(EVIDENCE)[:-1] + ', "run": {"command": "lint"}}'
        entries = [{"ac": "AC2", "check": nonfinite}, {"ac": "AC2", "check": repeated}]
        self.assertEqual(holding.parse_written(entries), [])
        self.assertEqual(gate(written=entries)["verdict"], "missing-checks")


class StaleTest(unittest.TestCase):
    def test_stale_names_a_child_fence_or_an_own_fence_with_results(self):
        arguments = {"answered": ["AC2"], "issue": 41, "criteria": HUMAN_CRITERIA}
        child = fence(50, EVIDENCE)
        own = fence(41, EVIDENCE)
        self.assertEqual(holding.stale([child], **arguments), [{**child, "acs": ["AC2"]}])
        self.assertEqual(holding.stale([own], **arguments), [])
        recorded = fence(41, EVIDENCE, results=True)
        self.assertEqual(holding.stale([recorded], **arguments), [{**recorded, "acs": ["AC2"]}])

    def test_stale_names_an_own_fence_without_results_when_nothing_is_left_to_hold(self):
        entry = fence(41, EVIDENCE)
        self.assertEqual(holding.stale([entry], ["AC2"], 41, CRITERIA), [{**entry, "acs": ["AC2"]}])


    def test_a_posted_check_whose_ac_is_not_a_string_names_no_criterion(self):
        for check in ({"ac": []}, {"ac": None}, {"ac": 3}, {"kind": "evidence"}):
            with self.subTest(check=check):
                entry = fence(50, check, EVIDENCE)
                self.assertEqual(holding.stale([entry], ["AC2"], 41, HUMAN_CRITERIA),
                                 [{**entry, "acs": ["AC2"]}])
                self.assertEqual(holding.stale([fence(50, check)], ["AC2"], 41, HUMAN_CRITERIA), [])


class TextTest(unittest.TestCase):
    def test_hold_body_holds_one_fence_that_parses_back_to_the_block(self):
        block = holding.block_of([EVIDENCE], MERGE)
        body = holding.hold_body(7, MERGE, [{"id": "AC2", "kind": "evidence", "text": "proof"}], block)
        self.assertEqual(body.count("```verify"), 1)
        self.assertEqual(verify_block.parse_block(body), (block, []))

    def test_split_body_starts_with_the_identity_line(self):
        block = holding.block_of([ASK], MERGE)
        title, body = holding.split_body(41, 7, MERGE, criterion(3, "human", "taste"), block)
        self.assertEqual(body.split("\n")[0], holding.split_line(41, "AC3", MERGE))
        self.assertEqual(holding.split_line(41, "AC3", MERGE), f"Split from #41: AC3 after the merge {MERGE}.")
        self.assertIn("taste", title)
        self.assertEqual(verify_block.parse_block(body), (block, []))


if __name__ == "__main__":
    unittest.main()
