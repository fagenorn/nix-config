"""Run journals (#858): incremental reads, the label-to-stage fold."""

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import deliveries

L1 = b'{"type":"launched"}\n'
L2 = b'{"type":"started","agentId":"a1","label":"setup","phase":"Setup"}\n'
SETUP = {"type": "started", "agentId": "a1", "label": "setup", "phase": "Setup"}
LAUNCHED = {"type": "launched"}
FIXTURES = Path(__file__).parent / "fixtures/console/journals"
PROGRAMS = Path(__file__).resolve().parents[1] / "home/common/claude-code/skills/deliver-standard"


class CountingFile:
    """A binary file whose `read` adds the bytes it returns to the owner's counter."""

    def __init__(self, owner, handle):
        self._owner, self._handle = owner, handle

    def read(self, n=-1):
        data = self._handle.read(n)
        self._owner.bytes += len(data)
        return data

    def seek(self, *args):
        return self._handle.seek(*args)

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)

    def close(self):
        return self._handle.close()


class CountingOpener:
    def __init__(self, fail=None):
        self.calls, self.bytes, self.fail = 0, 0, fail

    def __call__(self, path):
        self.calls += 1
        if self.fail is not None and self.fail[0]:
            raise PermissionError("denied")
        return CountingFile(self, open(path, "rb"))


class JournalReaderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / deliveries.JOURNAL_NAME

    def write(self, data):
        self.path.write_bytes(data)

    def append(self, data):
        with open(self.path, "ab") as handle:
            handle.write(data)

    def test_an_unchanged_journal_reads_no_bytes(self):
        self.write(L1 + L2)
        opener = CountingOpener()
        reader = deliveries.JournalReader(opener)
        first = reader.read(self.path)
        self.assertEqual(first.records, (LAUNCHED, SETUP))
        self.assertIs(first.from_start, True)
        self.assertEqual(opener.bytes, len(L1 + L2))
        second = reader.read(self.path)
        self.assertEqual(second.records, ())
        self.assertIs(second.from_start, False)
        self.assertEqual(opener.calls, 1)
        self.assertEqual(opener.bytes, len(L1 + L2))

    def test_a_grown_journal_reads_only_the_new_bytes(self):
        self.write(L1)
        opener = CountingOpener()
        reader = deliveries.JournalReader(opener)
        reader.read(self.path)
        self.append(L2)
        before = opener.bytes
        grown = reader.read(self.path)
        self.assertEqual(grown.records, (SETUP,))
        self.assertIs(grown.from_start, False)
        self.assertEqual(opener.bytes - before, len(L2))
        self.append(L1)
        before = opener.bytes
        reader.read(self.path)
        self.assertEqual(opener.bytes - before, len(L1))

    def test_a_partial_line_waits_for_its_newline(self):
        self.write(L2[:20])
        opener = CountingOpener()
        reader = deliveries.JournalReader(opener)
        self.assertEqual(reader.read(self.path).records, ())
        self.append(L2[20:])
        self.assertEqual(reader.read(self.path).records, (SETUP,))
        self.assertEqual(opener.bytes, len(L2))

    def test_a_truncated_or_replaced_journal_is_read_from_the_start(self):
        self.write(L1 + L2)
        reader = deliveries.JournalReader()
        reader.read(self.path)
        self.write(L1)
        truncated = reader.read(self.path)
        self.assertEqual(truncated.records, (LAUNCHED,))
        self.assertIs(truncated.from_start, True)
        beside = self.dir / "new.jsonl"
        beside.write_bytes(L2 + L1)
        os.replace(beside, self.path)
        replaced = reader.read(self.path)
        self.assertEqual(replaced.records, (SETUP, LAUNCHED))
        self.assertIs(replaced.from_start, True)
        self.assertIs(reader.read(self.path).from_start, False)

    def test_a_missing_journal_reads_as_none(self):
        reader = deliveries.JournalReader()
        self.assertIsNone(reader.read(self.path))
        self.write(L1)
        self.assertEqual(reader.read(self.path).records, (LAUNCHED,))
        self.path.unlink()
        self.assertIsNone(reader.read(self.path))
        self.write(L1)
        again = reader.read(self.path)
        self.assertEqual(again.records, (LAUNCHED,))
        self.assertIs(again.from_start, True)

    def test_a_malformed_line_is_skipped(self):
        self.write(L1 + b"not json\n" + b"[1,2]\n" + b"\xff\n" + b"\n" + L2)
        chunk = deliveries.JournalReader().read(self.path)
        self.assertEqual(chunk.records, (LAUNCHED, SETUP))

    def test_moved_ms_is_the_journal_mtime(self):
        self.write(L1)
        os.utime(self.path, ns=(1_700_000_000_123_456_789,) * 2)
        reader = deliveries.JournalReader()
        self.assertEqual(reader.read(self.path).moved_ms, 1_700_000_000_123)
        self.assertEqual(reader.read(self.path).moved_ms, 1_700_000_000_123)

    def test_a_failed_read_is_unreadable_and_keeps_the_offset(self):
        fail = [False]
        opener = CountingOpener(fail)
        reader = deliveries.JournalReader(opener)
        self.write(L1)
        reader.read(self.path)
        self.append(L2)
        fail[0] = True
        failed = reader.read(self.path)
        self.assertIsInstance(failed, deliveries.Unreadable)
        self.assertTrue(failed.reason.startswith("PermissionError"))
        fail[0] = False
        before = opener.bytes
        recovered = reader.read(self.path)
        self.assertEqual(recovered.records, (SETUP,))
        self.assertIs(recovered.from_start, False)
        self.assertEqual(opener.bytes - before, len(L2))
        with mock.patch("agent_tools.console.deliveries.os.stat", side_effect=PermissionError("denied")):
            self.assertIsInstance(reader.read(self.path), deliveries.Unreadable)
        calls = opener.calls
        unchanged = reader.read(self.path)
        self.assertEqual(unchanged.records, ())
        self.assertIs(unchanged.from_start, False)
        self.assertEqual(opener.calls, calls)


def journal(name):
    lines = (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def S(agent, label, phase):
    return {"type": "started", "agentId": agent, "label": label, "phase": phase}


def R(agent, result):
    return {"type": "result", "agentId": agent, "result": result}


PATTERN = "issue-<num>-<slug>"


def fold(records, pattern=PATTERN):
    run = deliveries.RunFold(pattern)
    run.apply(records)
    return run


def shown(records):
    return {item.issue: deliveries.stage_text(item) for item in fold(records).issues()}


CHILD = "▸ deliver-standard"
CLOSED_OUT = {"issue_state": "CLOSED", "branch_deleted": True, "released": True, "decision_ended": True, "notes": "ok"}


class RunFoldTest(unittest.TestCase):
    def test_journal_fixtures_map_to_each_issues_stage(self):
        queued = {856: "queued", 857: "queued", 860: "queued"}
        at34 = {856: "final review", 857: "plan review", 860: "queued"}
        rows = [
            ("single", 2, {}),
            ("single", 3, {858: "planning"}),
            ("single", 5, {858: "planning"}),
            ("single", 6, {858: "plan review"}),
            ("single", 10, {858: "building task 1 of 3"}),
            ("single", 14, {858: "building task 2 of 3"}),
            ("single", 20, {858: "building task 3 of 3"}),
            ("single", 22, {858: "final review"}),
            ("single", 24, {858: "verifying"}),
            ("single", 26, {858: "landing"}),
            ("single", 30, {858: "landing"}),
            ("single", 31, {858: "done"}),
            ("batch", 3, {}),
            ("batch", 9, queued),
            ("batch", 10, {**queued, 856: "planning"}),
            ("batch", 13, {856: "planning", 857: "planning", 860: "queued"}),
            ("batch", 21, {856: "plan review", 857: "planning", 860: "queued"}),
            ("batch", 25, {856: "plan review", 857: "planning", 860: "queued"}),
            ("batch", 26, {856: "building task 1 of 5", 857: "planning", 860: "queued"}),
            ("batch", 29, {856: "building task 1 of 5", 857: "plan review", 860: "queued"}),
            ("batch", 31, {856: "building task 2 of 5", 857: "plan review", 860: "queued"}),
            ("batch", 34, at34),
            ("batch", 36, {**at34, 856: "verifying"}),
            ("batch", 38, {**at34, 856: "landing"}),
            ("batch", 42, {**at34, 856: "landing"}),
            ("batch", 43, {**at34, 856: "done"}),
            ("batch", 45, {**at34, 856: "done"}),
            ("batch", 49, {**at34, 856: "done"}),
        ]
        for name, k, expected in rows:
            with self.subTest(fixture=name, k=k):
                run = fold(journal(name)[:k])
                self.assertEqual({item.issue: deliveries.stage_text(item) for item in run.issues()}, expected)
                self.assertTrue(all(isinstance(item, deliveries.IssueStage) for item in run.issues()))
                issues = [item.issue for item in run.issues()]
                self.assertEqual(issues, sorted(issues))

    def test_an_unknown_label_reads_working(self):
        single = journal("single")[:3]
        self.assertEqual(shown(single + [S("x1", "brand-new-step", "Tasks")]), {858: "working"})
        self.assertEqual(
            shown(single + [S("x1", "brand-new-step", "Tasks"), S("x2", "impl-2", "Tasks")]),
            {858: "building task 2"},
        )
        batch = journal("batch")[:14] + [S("x3", "brand-new-step", CHILD)]
        self.assertEqual(shown(batch), {856: "working", 857: "planning", 860: "queued"})
        self.assertIsNone(deliveries.classify("brand-new-step", batch=False))
        self.assertEqual(shown(single + [S("x4", "", "Tasks")]), {858: "working"})

    def test_building_without_a_plan_result_names_no_total(self):
        single = journal("single")[:3]
        self.assertEqual(shown(single + [S("x", "impl-4", "Tasks")]), {858: "building task 4"})
        self.assertEqual(shown(single + [S("y", "direct-impl", "Tasks")]), {858: "building"})

    def test_a_childs_effects_wait_for_its_setup_result(self):
        records = journal("batch")[:11] + [
            S("d1", "setup", CHILD),
            S("d2", "plan", CHILD),
            R("d2", {"status": "planned", "tasks": [{"n": 1}, {"n": 2}]}),
            S("d3", "impl-1", CHILD),
        ]
        self.assertEqual(shown(records)[856], "planning")
        records.append(R("d1", {"ok": True, "branch": "issue-856-x"}))
        self.assertEqual(shown(records), {856: "building task 1 of 2", 857: "queued", 860: "queued"})

    def test_done_is_final(self):
        records = journal("single") + [S("z", "impl-9", "Tasks"), S("z2", "brand-new", "Ship")]
        self.assertEqual(shown(records), {858: "done"})

    def test_a_queued_label_never_moves_an_issue_back(self):
        records = journal("batch")[:10] + [S("q", "facts-856", "Intake")]
        self.assertEqual(shown(records)[856], "planning")

    def test_folding_in_chunks_equals_folding_whole(self):
        for name in ("single", "batch"):
            lines = journal(name)
            whole = fold(lines).issues()
            for k in range(len(lines) + 1):
                with self.subTest(fixture=name, k=k):
                    run = deliveries.RunFold(PATTERN)
                    run.apply(lines[:k])
                    run.apply(lines[k:])
                    self.assertEqual(run.issues(), whole)

    def test_malformed_records_are_ignored(self):
        junk = [
            None,
            [],
            {"type": "started"},
            {"type": "started", "agentId": 1, "label": "plan", "phase": "Plan"},
            {"type": "started", "agentId": 2, "label": "impl-5", "phase": "Tasks"},
            {"type": "started", "agentId": "b", "label": "impl-5"},
            {"type": "result", "agentId": "nobody", "result": {}},
        ]
        single = journal("single")[:3]
        self.assertEqual(shown(junk + single), {858: "planning"})
        for result in ({"ok": True, "branch": "feature-x"}, {"ok": False}):
            with self.subTest(result=result):
                self.assertEqual(shown([S("a1", "setup", "Setup"), R("a1", result)]), {})

    def test_a_failed_or_incomplete_close_out_is_not_done(self):
        held = {"issue_state": "OPEN", "released": True, "decision_ended": True, "notes": "held"}
        full = {"issue_state": "CLOSED", "released": True, "decision_ended": True, "notes": "x"}
        rows = [
            ({}, "landing"),
            (None, "landing"),
            ("done", "landing"),
            ({**full, "released": False}, "landing"),
            ({**full, "decision_ended": False}, "landing"),
            ({**full, "notes_posted": False}, "landing"),
            ({**full, "issue_state": "MERGED"}, "landing"),
            (held, "landing"),
            (full, "done"),
        ]
        single = journal("single")[:30]
        for result, expected in rows:
            with self.subTest(result=result):
                self.assertEqual(shown(single + [R("a15", result)]), {858: expected})
        batch = journal("batch")[:42] + [R("b9", {})]
        self.assertEqual(shown(batch), {856: "landing", 857: "plan review", 860: "queued"})
        again = batch + [S("b9b", "close-out-856", "Land"), R("b9b", CLOSED_OUT)]
        self.assertEqual(shown(again)[856], "done")

    def test_a_close_out_is_graded_against_the_plans_acceptance(self):
        def planned(kinds, owner="a2"):
            acceptance = [{"id": f"AC{i}", "kind": kind} for i, kind in enumerate(kinds)]
            return R(owner, {"status": "planned", "tasks": [{"n": 1}], "acceptance": acceptance})

        def single(kinds, result):
            records = journal("single")[:4] + [planned(kinds)] + journal("single")[5:30]
            return shown(records + [R("a15", result)])[858]

        closed, held = CLOSED_OUT, {**CLOSED_OUT, "issue_state": "OPEN"}
        with_notes = {**CLOSED_OUT, "notes_posted": True}
        self.assertEqual(single(["code"], held), "landing")
        self.assertEqual(single(["code"], closed), "done")
        self.assertEqual(single(["code", "note"], closed), "landing")
        self.assertEqual(single(["code", "note"], with_notes), "done")
        self.assertEqual(single(["code", "human"], held), "done")
        self.assertEqual(single(["code", "evidence"], {**held, "issue_state": "CLOSED"}), "done")

        base = journal("batch")[:42]
        open_result = {**CLOSED_OUT, "issue_state": "OPEN", "released": True, "decision_ended": True}
        records = base + [R("b9", open_result)]
        self.assertEqual(shown(records)[856], "landing")
        held_batch = [dict(r) for r in base]
        for record in held_batch:
            if record.get("agentId") == "c3" and record.get("type") == "result":
                record["result"] = {**record["result"], "acceptance": [{"id": "AC1", "kind": "human"}]}
        self.assertEqual(shown(held_batch + [R("b9", open_result)])[856], "done")
        self.assertEqual(shown(held_batch + [R("b9", CLOSED_OUT)])[856], "landing")

    def test_a_close_out_waits_for_the_childs_issue_and_its_acceptance(self):
        records = journal("batch")[:11] + [
            S("d1", "setup", CHILD),
            S("d2", "plan", CHILD),
            R("d2", {"status": "planned", "tasks": [{"n": 1}], "acceptance": [{"id": "A", "kind": "code"}]}),
            S("d3", "close-out", CHILD),
            R("d3", {**CLOSED_OUT, "issue_state": "OPEN"}),
            R("d1", {"ok": True, "branch": "issue-856-x"}),
        ]
        self.assertEqual(shown(records)[856], "landing")
        records[-2] = R("d3", CLOSED_OUT)
        self.assertEqual(shown(records)[856], "done")

    def test_a_branch_names_its_issue_through_the_configured_pattern(self):
        rows = [
            ("issue-<num>-<slug>", "issue-858-in-flight", 858),
            ("issue-<num>-<slug>", "issue-858", None),
            ("issue-<num>-<slug>", "console-stage-858", None),
            ("<slug>-<num>", "console-stage-858", 858),
            ("<slug>-<num>", "issue-858", 858),
            ("<slug>-<num>", "feature-x", None),
            ("feat/<num>-<slug>", "feat/12-a-b", 12),
            ("feat/<num>-<slug>", "feat-12-a-b", None),
            ("issue-<num>", "issue-7", 7),
            ("<num><slug>", "12abc", None),
            ("<slug><num>", "abc12", None),
            ("no-number", "no-number", None),
            (None, "issue-858-x", None),
        ]
        for pattern, branch, expected in rows:
            with self.subTest(pattern=pattern, branch=branch):
                self.assertEqual(deliveries.branch_issue(pattern, branch), expected)

    def test_a_valid_branch_pattern_other_than_issue_first_still_names_the_issue(self):
        records = [
            S("a1", "setup", "Setup"), R("a1", {"ok": True, "branch": "console-stage-858"}),
            S("a2", "impl-1", "Tasks"),
        ]
        self.assertEqual(shown(records), {})
        self.assertEqual({i.issue: deliveries.stage_text(i)
                          for i in fold(records, "<slug>-<num>").issues()}, {858: "building task 1"})
        child = [
            S("b1", "facts-858", "Intake"),
            S("c1", "setup", CHILD), R("c1", {"ok": True, "branch": "console-stage-858"}),
            S("c2", "impl-2", CHILD),
        ]
        self.assertEqual({i.issue: deliveries.stage_text(i)
                          for i in fold(child, "<slug>-<num>").issues()}, {858: "building task 2"})

    def test_train_counters_name_no_issue(self):
        base = journal("batch")[:9]
        counters = [
            S("t1", "train-build-1", "Land"),
            S("t2", "train-sweep-1", "Land"),
            S("t3", "train-checks-2-1", "Land"),
            S("t4", "train-flip-1-3", "Land"),
            S("t5", "train-merge-1", "Land"),
            S("t6", "train-ready-1", "Land"),
            S("u1", "brand-new-857", "Land"),
        ]
        queued = {856: "queued", 857: "queued", 860: "queued"}
        self.assertEqual(shown(base + counters), queued)
        self.assertEqual(
            shown(base + counters + [S("t7", "train-pr-857", "Land")]),
            {**queued, 857: "landing"},
        )

    def test_every_program_label_maps_to_a_known_stage(self):
        patterns = [
            r"\blabel:\s*'([^'\s]+)'",
            r"\blabel:\s*`([^`\s]+)`",
            r"\breviewLabel:\s*['`]([^'`\s]+)['`]",
            r"\b(?:const|let)\s+\w*[lL]abel\s*=\s*(?:[^?\n]*\?\s*'([^'\s]+)'\s*:\s*)?`([^`\s]+)`",
            r"`\s*,\s*`([a-z][a-z-]*(?:-\$\{[^}`]+\})*)`\s*,\s*\{",
        ]

        def templates(text):
            found = set()
            for pattern in patterns:
                for match in re.finditer(pattern, text):
                    found.update(group for group in match.groups() if group)
            return found

        standard = (PROGRAMS / "deliver-standard.js").read_text(encoding="utf-8")
        batch = (PROGRAMS / "deliver-batch.js").read_text(encoding="utf-8")
        renews = set(re.findall(r"\brenew\('([a-z-]+)'", standard))
        standard_templates, batch_templates = templates(standard), templates(batch)
        self.assertEqual(renews, {"plan", "amend", "final-review"})
        for needed in ("setup", "plan", "impl-${t.n}", "close-out", "renew-${at}", "verify", "pr", "merge"):
            self.assertIn(needed, standard_templates)
        for needed in (
            "facts-${n}",
            "land-pr-${n}",
            "close-out-${n}",
            "train-pr-${e.n}",
            "train-build-${t}",
            "train-sweep-${sweepNo}",
        ):
            self.assertIn(needed, batch_templates)

        def instantiate(template, issue_marks, renew_points):
            if template == "renew-${at}":
                return [f"renew-{at}" for at in sorted(renew_points)]
            label = template
            for mark in issue_marks:
                label = label.replace(mark, "4242")
            return [re.sub(r"\$\{[^}]+\}", "7", label)]

        for template in sorted(standard_templates):
            for label in instantiate(template, (), renews):
                with self.subTest(program="deliver-standard", label=label):
                    step = deliveries.classify(label, batch=False)
                    self.assertIsNotNone(step)
                    self.assertTrue(step.stage is None or step.stage in deliveries.STAGES)
                    self.assertIsNone(step.issue)
        for template in sorted(batch_templates):
            names_issue = "${n}" in template or "${e.n}" in template
            for label in instantiate(template, ("${n}", "${e.n}"), ()):
                with self.subTest(program="deliver-batch", label=label):
                    step = deliveries.classify(label, batch=True)
                    self.assertIsNotNone(step)
                    self.assertTrue(step.stage is None or step.stage in deliveries.STAGES)
                    self.assertEqual(step.issue, 4242 if names_issue else None)


    def test_a_rerun_review_label_reads_as_the_step_it_reruns(self):
        # Both programs append one suffix to the label of a review they run once more (an unusable first reply).
        for name in ("deliver-standard.js", "deliver-batch.js"):
            with self.subTest(program=name):
                source = (PROGRAMS / name).read_text(encoding="utf-8")
                self.assertEqual(source.count(f"const AGAIN = '{deliveries.RERUN_SUFFIX}'\n"), 1)
        for label in ("review-3", "rereview-3-1", "plan-review", "final-2", "fix-wave-review-2", "sync-review-1", "verify-fix-review-1"):
            with self.subTest(label=label):
                again = deliveries.classify(label + deliveries.RERUN_SUFFIX, batch=False)
                self.assertIsNotNone(again)
                self.assertEqual(again, deliveries.classify(label, batch=False))
        for label in ("land-sync-review-2259-1", "land-sync-rereview-2259-1", "land-fix-review-2259"):
            with self.subTest(label=label):
                again = deliveries.classify(label + deliveries.RERUN_SUFFIX, batch=True)
                self.assertEqual(again, deliveries.classify(label, batch=True))
                self.assertEqual(again.issue, 2259)
        self.assertEqual(
            shown([S("t0", "facts-857", "Intake"), S("t1", "land-sync-review-857-1-again", "Land")]),
            {857: "landing"},
        )


class ConfiguredBranchPatternTest(unittest.TestCase):
    def test_the_pattern_is_the_contracts_vcs_branch_pattern(self):
        snapshot = {"bindings": {"vcs": {"branch_pattern": "<slug>-<num>"}}}
        with mock.patch("agent_tools.console.deliveries.resolve_project.resolve",
                        return_value=snapshot) as resolve:
            self.assertEqual(deliveries.configured_branch_pattern("/srv/p"), "<slug>-<num>")
        resolve.assert_called_once_with("/srv/p")

    def test_an_unresolved_contract_gives_none(self):
        refusal = deliveries.resolve_project.ContractError("not_onboarded", "r", [])
        for outcome in ({"side_effect": refusal}, {"side_effect": OSError("gone")},
                        {"return_value": {}}, {"return_value": {"bindings": {"vcs": {"branch_pattern": 3}}}}):
            with self.subTest(outcome=outcome), mock.patch(
                    "agent_tools.console.deliveries.resolve_project.resolve", **outcome):
                self.assertIsNone(deliveries.configured_branch_pattern("/srv/p"))


class RunJournalsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        a = self.root / "a/projects"
        self.journals = {}
        for name, slug, session, run in (
            ("w2", "-srv-p00", "s1", "wf_2"), ("w1", "-srv-p00", "s1", "wf_1"),
            ("w0", "-srv-p01", "s1", "wf_0"), ("w9", "-srv-p00", "s2", "wf_9"),
        ):
            journal = a / slug / session / "subagents/workflows" / run / "journal.jsonl"
            journal.parent.mkdir(parents=True)
            journal.write_text("")
            self.journals[name] = journal
        (a / "-srv-p00/s1/subagents/workflows/wf_3").mkdir()
        (a / "-srv-p00/s1/subagents/workflows/wf_4/journal.jsonl").mkdir(parents=True)
        self.dirs = [a, self.root / "b/projects"]

    def test_run_journals_lists_only_the_sessions_journals(self):
        j = self.journals
        self.assertEqual(deliveries.run_journals(self.dirs, "s1"),
                         sorted([j["w2"], j["w1"], j["w0"]]))
        self.assertEqual(deliveries.run_journals(self.dirs, "nobody"), [])
        record = deliveries.final_record(j["w1"])
        self.assertEqual(record, self.root / "a/projects/-srv-p00/s1/workflows/wf_1.json")
        self.assertIs(deliveries.has_final_record(j["w1"]), False)
        record.parent.mkdir(parents=True)
        record.write_text("{}")
        self.assertIs(deliveries.has_final_record(j["w1"]), True)

    def test_a_session_id_with_a_nul_is_absent_not_a_failure(self):
        self.assertEqual(deliveries.run_journals(self.dirs, "a\x00b"), [])
        journal = self.root / "a/projects/-srv-p00/a\x00b/subagents/workflows/wf_1/journal.jsonl"
        self.assertIs(deliveries.has_final_record(journal), False)
        self.assertIsNone(deliveries.JournalReader().read(journal))

    def test_a_listing_failure_is_unreadable_not_empty(self):
        with mock.patch("agent_tools.console.deliveries.os.scandir",
                        side_effect=PermissionError("denied")):
            result = deliveries.run_journals(self.dirs, "s1")
        self.assertIsInstance(result, deliveries.Unreadable)
        self.assertTrue(result.reason.startswith("PermissionError"))
        with mock.patch("agent_tools.console.deliveries.os.scandir",
                        side_effect=FileNotFoundError()):
            self.assertEqual(deliveries.run_journals(self.dirs, "s1"), [])
        with mock.patch("agent_tools.console.deliveries.os.stat",
                        side_effect=PermissionError("denied")):
            self.assertIsInstance(deliveries.has_final_record(self.journals["w1"]),
                                  deliveries.Unreadable)


if __name__ == "__main__":
    unittest.main()
