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


def fold(records):
    run = deliveries.RunFold()
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
                    run = deliveries.RunFold()
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
            (held, "done"),
        ]
        single = journal("single")[:30]
        for result, expected in rows:
            with self.subTest(result=result):
                self.assertEqual(shown(single + [R("a15", result)]), {858: expected})
        batch = journal("batch")[:42] + [R("b9", {})]
        self.assertEqual(shown(batch), {856: "landing", 857: "plan review", 860: "queued"})
        again = batch + [S("b9b", "close-out-856", "Land"), R("b9b", CLOSED_OUT)]
        self.assertEqual(shown(again)[856], "done")

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
