"""agent-costs --report boot (issue 448, spec test seam 1)."""
import json
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .owner_transcripts import RUN, Session, gate_reply, progress

HOST = socket.gethostname().split(".", 1)[0]
PLANS = "/r/.agents/artifacts/plans"
TOOLS = [{"name": "Read", "description": "Read a file.", "input_schema": {"type": "object"}}]
BUCKETS = ("tool_schemas", "harness", "prompt", "skill_bodies", "skill_files", "plan_reads",
           "resume_reads", "rereads", "other_reads", "commands", "assistant", "unexplained")
BASELINE = "2026-10-25T09:00:00Z..2026-10-25T10:00:00Z"
BASELINE_EVENTS = ("--events-since", "2026-10-25T09:00:00Z",
                   "--events-before", "2026-10-25T10:00:00Z")
EVENTS = ("--events-since", "2026-10-25T10:00:00Z", "--events-before", "2026-10-25T11:00:00Z")
WINDOW_BOOTS = (  # (seconds after T0, issue, project, phase, start, end): four boots in the
                  # baseline window, four in the event window and one after both
    (100, 11, "alpha", 6, 24_000, 40_000), (200, 12, "beta", 6, 28_000, 52_000),
    (300, 13, "beta", 6, 28_000, 54_000), (400, 14, "beta", 6, 28_000, 56_000),
    (3_700, 21, "alpha", 6, 20_000, 30_000), (3_800, 22, "alpha", 6, 21_000, 32_000),
    (3_900, 23, "alpha", 6, 22_000, 34_000), (4_000, 24, "beta", 6, 26_000, 50_000),
    (7_300, 31, "alpha", 6, 20_000, 99_000))
COVERAGE_BOOTS = (  # baseline: alpha and delta in 6-7; event window: alpha and gamma in 6-7, alpha in 0-5
    (100, 11, "alpha", 6, 24_000, 40_000), (200, 12, "delta", 6, 28_000, 60_000),
    (3_700, 21, "alpha", 6, 20_000, 30_000), (3_800, 22, "gamma", 6, 22_000, 44_000),
    (3_900, 23, "alpha", 3, 21_000, 35_000))
SIDE_KEYS = ["count", "b_mean", "b_median", "b_without_schemas_mean", "b_without_schemas_median"]
TOP_KEYS = ["kind", "schema_version", "window", "hosts", "chars_per_token",
            "observed_chars_per_token", "unsplit", "boots", "groups", "reweighted"]
BOOT_KEYS = ["arm", "host", "transcript", "run_id", "issue", "project", "cohort", "phase_group",
             "calls", "start", "b", "boot_reading", "first_unit_work", "buckets", "skills",
             "skill_files"]
GROUP_KEYS = ["arm", "host", "cohort", "phase_group", "count", "b_mean", "b_median",
              "b_without_schemas_mean", "b_without_schemas_median", "boot_reading_mean",
              "boot_reading_median", "first_unit_work_mean", "first_unit_work_median", "buckets",
              "bucket_medians"]


def costs(*args):
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.agent_costs", "--report", "boot", *args],
        capture_output=True, text=True, check=False)


def report(*roots, extra=()):
    dirs = [arg for root in roots for arg in ("--projects-dir", str(root))]
    completed = costs("--format", "json", "--days", "0", *dirs, *extra)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def buckets(**values):
    return {name: values.get(name, 0) for name in BUCKETS}


def opening(session, agent, *, system=244, reminder=0, prompt=244):
    """The shape, the first request's tail blob and the request, before an owner's call 0."""
    session.shape(agent, system=["s" * system], tools=TOOLS)
    blocks = ([{"type": "text", "text": "<system-reminder>\n" + "r" * (reminder - 18)}]
              if reminder else [])
    blocks.append({"type": "text", "text": "p" * prompt})
    session.request(agent, [session.blob(agent, "user", blocks)])


def dispatch(session, seconds):
    """A root call that dispatches one child; returns its tool-use id."""
    return session.call(None, seconds, context=10_000, write=10_000, ttl="1h", agent_tool=True)


def two_call_boot(session, agent, seconds, *, issue, launch, phase, start, end, requests=True,
                  repo_root="/Users/me/repo"):
    """A child owner booting from `start` to `end` in two calls, registering at the second."""
    session.child(agent, tool_use_id=dispatch(session, seconds))
    if requests:
        opening(session, agent)
    session.call(agent, seconds + 10, context=start, write=start)
    gate = session.call(agent, seconds + 20, context=end, write=end - start,
                        bash=progress(phase, action_id=f"{issue}:1:{launch}",
                                          repo_root=repo_root))
    session.result(agent, seconds + 21, gate, gate_reply("continue", issue=issue, launch=launch))


def bash(command):
    return ("Bash", {"command": command})


def read(path, **extent):
    return ("Read", {"file_path": path, **extent})


def stepped_boot(session, agent, seconds, steps, *, issue=7):
    """A fresh owner (launch 2, phase 6) booting from 20,000 in one call per `(tool, size)` step.
    The step's result holds `size` characters, so the next call grows by `size` plus the 40
    output tokens of the step's call. The last call registers."""
    session.child(agent, tool_use_id=dispatch(session, seconds))
    opening(session, agent)
    context, previous = 20_000, 0
    for index, (tool, size) in enumerate(steps):
        tool_id = session.call(agent, seconds + 10 * index + 10, context=context,
                               write=context - previous, tool=tool)
        session.result(agent, seconds + 10 * index + 11, tool_id, "x" * size)
        previous, context = context, context + size + 40
    gate = session.call(agent, seconds + 10 * len(steps) + 10, context=context,
                        write=context - previous, bash=progress(6, action_id=f"{issue}:1:2"))
    session.result(agent, seconds + 10 * len(steps) + 11, gate,
                   gate_reply("continue", issue=issue, launch=2))


class BootReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_call_0_splits_at_2_44_and_later_growth_by_character_share(self):
        session = Session(self.root)
        session.child("o1", tool_use_id=dispatch(session, 0))
        opening(session, "o1", system=244, reminder=2_440, prompt=488)
        c0 = session.call("o1", 100, context=30_000, write=30_000,
                          tool=("Read", {"file_path": f"{PLANS}/2026-10-26-x.md"}))
        session.result("o1", 101, c0, "R" * 1_000)
        c1 = session.call("o1", 110, context=31_040, write=1_040,
                          bash=f"cat {PLANS}/2026-10-26-x.tasks/task-1.md "
                               f"{PLANS}/2026-10-26-x.tasks/task-2.md")
        session.result("o1", 111, c1, "T" * 6_100)
        c2 = session.call("o1", 120, context=33_580, write=2_540, tool=("Skill", {"skill": "sdd"}))
        session.result("o1", 121, c2, "Launching skill: sdd")
        body = "Base directory for this skill: /h/.claude/skills/sdd\n"
        body += "b" * (1_980 - len(body))
        session.skill_body("o1", 122, c2, body)
        session.request("o1", [session.blob("o1", "user", [{"type": "text", "text": body}])])
        c3 = session.call("o1", 130, context=35_620, write=2_040,
                          tool=("Read", {"file_path": "/h/.claude/skills/from-issue/AUTO.md"}))
        session.result("o1", 131, c3, "A" * 500)
        session.request("o1", [session.blob("o1", "system", [
            {"type": "text", "text": "<system-reminder>\n" + "h" * 482}])])
        c4 = session.call("o1", 140, context=36_660, write=1_040,
                          bash=progress(6, action_id="7:1:2"))
        session.result("o1", 141, c4, gate_reply("continue", launch=2))
        session.write()
        document = report(self.root)
        [row] = document["boots"]
        self.assertEqual(row["buckets"], buckets(
            tool_schemas=28_700, harness=1_600, prompt=200, skill_bodies=2_000,
            skill_files=500, plan_reads=3_500, assistant=160))
        self.assertEqual(sum(row["buckets"].values()), row["b"])
        self.assertEqual(
            (row["host"], row["run_id"], row["issue"], row["cohort"], row["phase_group"],
             row["calls"], row["start"], row["b"]),
            (HOST, RUN, 7, "fresh", "6-7", 5, 30_000, 36_660))
        self.assertEqual(row["skills"], {"sdd": 2_000})
        self.assertEqual(row["skill_files"], {"from-issue/AUTO.md": 500})
        self.assertEqual((document["chars_per_token"], document["observed_chars_per_token"]),
                         (2.44, 2.44))

    def test_a_skill_call_without_a_name_is_keyed_unnamed(self):
        session = Session(self.root)
        session.child("o1", tool_use_id=dispatch(session, 0))
        opening(session, "o1")
        c0 = session.call("o1", 100, context=20_000, write=20_000, tool=("Skill", {}))
        session.result("o1", 101, c0, "E" * 1_000)
        c1 = session.call("o1", 110, context=21_040, write=1_040,
                          bash=progress(6, action_id="7:1:2"))
        session.result("o1", 111, c1, gate_reply("continue", launch=2))
        session.write()
        [row] = report(self.root)["boots"]
        self.assertEqual(row["skills"], {"(unnamed)": 1_000})
        text = costs("--days", "0", "--projects-dir", str(self.root))
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertIn("(unnamed)", text.stdout)

    def test_read_backs_rereads_and_resume_content_take_their_buckets(self):
        session = Session(self.root)
        session.child("o1", tool_use_id=dispatch(session, 0))
        opening(session, "o1")
        saved = "/h/.claude/projects/p/s1/tool-results/b1.txt"
        preview = f"Output too large (61.0KB). Full output saved to: {saved}\n"
        pack = json.dumps({"kind": "resume_pack", "version": 1,
                           "next_action": {"kind": "resume_task", "task": 3}})
        owner = json.dumps({"interface_version": 2, "kind": "owner", "run_id": RUN, "issue": 7})
        steps = [  # (context, tool, result); each result is the next call's growth less 40
            (20_000, ("Bash", {"command": f'P={PLANS}; cd "$P" && cat 2026-10-26-x.md'}),
             preview + "t" * (2_000 - len(preview))),
            (22_040, ("Read", {"file_path": saved}), "P" * 5_000),
            (27_080, ("Read", {"file_path": "/r/src/app.py", "offset": 1, "limit": 50}), "S" * 1_000),
            (28_120, ("Read", {"file_path": "/r/src/app.py", "offset": 1, "limit": 50}), "S" * 1_000),
            (29_160, ("Read", {"file_path": "/r/src/app.py", "offset": 51, "limit": 50}), "S" * 1_000),
            (30_200, ("Bash", {"command": 'P=/tmp/scratch; cat "$P/notes-7.json"'}),
             pack + " " * (1_000 - len(pack))),
            (31_240, ("Bash", {"command": "artifact-budget validate-report --boundary "
                                          "workflow-response --input - <<'EOF'\n{}\nEOF"}),
             owner + " " * (1_000 - len(owner))),
            (32_280, ("Bash", {"command": "cat <<'EOF' > /tmp/notes.md\nsee the plan\nEOF\n"
                                          "cat /r/src/app.py"}), "S" * 1_000),
            (33_320, ("Bash", {"command": "ls /r"}), "L" * 1_000),
        ]
        previous = 0
        for index, (context, tool, text) in enumerate(steps):
            tool_id = session.call("o1", 100 + 10 * index, context=context,
                                   write=context - previous, tool=tool)
            session.result("o1", 101 + 10 * index, tool_id, text)
            previous = context
        gate = session.call("o1", 200, context=34_360, write=1_040,
                            bash=progress(6, action_id="7:1:2"))
        session.result("o1", 201, gate, gate_reply("continue", launch=2))
        session.write()
        [row] = report(self.root)["boots"]
        self.assertEqual(row["buckets"], buckets(
            tool_schemas=19_800, harness=100, prompt=100, plan_reads=7_000, other_reads=3_000,
            rereads=1_000, resume_reads=2_000, commands=1_000, assistant=360))
        self.assertEqual(sum(row["buckets"].values()), row["b"])

    def test_negative_or_unexplained_growth_and_a_boot_without_request_records(self):
        session = Session(self.root)
        session.child("o1", tool_use_id=dispatch(session, 0))
        opening(session, "o1")
        session.call("o1", 100, context=30_000, write=30_000)
        session.call("o1", 110, context=29_000, write=1_000)
        gate = session.call("o1", 120, context=31_000, write=2_000,
                            bash=progress(6, action_id="7:1:2"))
        session.result("o1", 121, gate, gate_reply("continue", launch=2))
        two_call_boot(session, "o8", 300, issue=8, launch=2, phase=6, start=20_000,
                      end=21_000, requests=False)
        session.write()
        document = report(self.root)
        [row] = document["boots"]
        self.assertEqual(row["issue"], 7)
        self.assertEqual(row["buckets"], buckets(tool_schemas=29_800, harness=100, prompt=100,
                                                 assistant=40, unexplained=960))
        self.assertEqual(document["unsplit"], {"live": {HOST: 1}})
        self.assertIsNone(document["observed_chars_per_token"])

    def gated_boot(self, session, seconds, context):
        gate = session.call("o1", seconds, context=context, write=1_000,
                            bash=progress(6, action_id="7:1:2"))
        session.result("o1", seconds + 1, gate, gate_reply("continue", launch=2))
        session.write()
        [row] = report(self.root)["boots"]
        self.assertEqual(sum(row["buckets"].values()), row["b"])
        return row

    def test_assistant_text_in_a_request_blob_is_not_charged_again(self):
        session = Session(self.root)
        session.child("o1", tool_use_id=dispatch(session, 0))
        opening(session, "o1")
        c0 = session.call("o1", 100, context=30_000, write=30_000,
                          tool=("Read", {"file_path": f"{PLANS}/2026-10-26-x.md"}))
        session.result("o1", 101, c0, "R" * 1_000)
        session.request("o1", [session.blob("o1", "assistant", [
            {"type": "text", "text": "W" * 1_000}])])
        row = self.gated_boot(session, 110, 31_040)
        self.assertEqual(row["buckets"], buckets(
            tool_schemas=29_800, harness=100, prompt=100, plan_reads=1_000, assistant=40))

    def test_meta_text_not_from_a_skill_call_counts_where_its_blob_lands(self):
        session = Session(self.root)
        session.child("o1", tool_use_id=dispatch(session, 0))
        opening(session, "o1")
        c0 = session.call("o1", 100, context=30_000, write=30_000, bash="ls /r")
        session.result("o1", 101, c0, "L" * 1_000)
        session.skill_body("o1", 102, c0, "m" * 1_000)
        session.request("o1", [session.blob("o1", "user", [
            {"type": "text", "text": "m" * 1_000}])])
        row = self.gated_boot(session, 110, 32_040)
        self.assertEqual(row["buckets"], buckets(
            tool_schemas=29_800, harness=1_100, prompt=100, commands=1_000, assistant=40))

    def test_a_shrinking_segment_still_records_its_reads(self):
        session = Session(self.root)
        session.child("o1", tool_use_id=dispatch(session, 0))
        opening(session, "o1")
        plan = ("Read", {"file_path": f"{PLANS}/2026-10-26-x.md"})
        c0 = session.call("o1", 100, context=30_000, write=30_000, tool=plan)
        session.result("o1", 101, c0, "R" * 1_000)
        c1 = session.call("o1", 110, context=29_000, write=1_000, tool=plan)
        session.result("o1", 111, c1, "R" * 1_000)
        row = self.gated_boot(session, 120, 30_040)
        self.assertEqual(row["buckets"], buckets(
            tool_schemas=29_800, harness=100, prompt=100, rereads=1_000, assistant=40,
            unexplained=-1_000))

    def test_a_whole_read_covers_every_later_read_of_its_file(self):
        src = "/r/src/a.py"
        cases = (  # (first read, second read, whether the second is a reread)
            (bash(f"cat {src}"), read(src), True),
            (read(src), bash(f"cat {src}"), True),
            (read(src), read(src, offset=10, limit=20), True),
            (bash("cd /r/src && cat a.py 2>/dev/null"), read(src), True),
            (read(src, offset=1, limit=50), read(src), False),
            (read(src, offset=1, limit=50), read(src, offset=51, limit=50), False),
            (read("/r/docs/a.pdf", pages="1-2"), read("/r/docs/a.pdf", pages="3-4"), False),
            (bash(f"cat {src} | head -n 5"), read(src), False),
            (bash(f'V=$(cat {src}); echo "$V"'), read(src), False),
            (bash(f"echo `cat {src}`"), read(src), False),
            (bash(f"cat {src} > /tmp/a.txt"), read(src), False),
            (bash(f"cat {src} 1>>/tmp/a.txt"), read(src), False),
            (bash(f"cat {src} $(true) | head -n 5"), read(src), False),
            (bash(f"echo $(cat /dev/null) cat {src}"), read(src), False),
            (bash(f"echo `cat /dev/null` cat {src}"), read(src), False),
            (bash(f"cat {src} >&/dev/null"), read(src), False),
            (bash(f"cat {src} >& /tmp/a.txt"), read(src), False),
            (bash(f"cat {src} 1>&/dev/null"), read(src), False),
            (bash(f"cat {src} >&2"), read(src), True),
            (bash(f"cat {src} 2>&1"), read(src), True),
        )
        for index, (first, second, reread) in enumerate(cases):
            with self.subTest(first=first, second=second):
                root = self.root / f"case-{index}"
                session = Session(root)
                stepped_boot(session, "o1", 0, [(first, 1_000), (second, 2_000)])
                session.write()
                [row] = report(root)["boots"]
                self.assertEqual((row["buckets"]["other_reads"], row["buckets"]["rereads"]),
                                 (1_000, 2_000) if reread else (3_000, 0))

    def test_cohorts_follow_lineage_position_and_launch_ordinal_and_groups_pool_them(self):
        session = Session(self.root)
        g1 = session.call(None, 0, context=40_000, write=40_000, ttl="1h", bash=progress(1))
        session.result(None, 5, g1, gate_reply("continue"))
        two_call_boot(session, "a7", 100, issue=7, launch=1, phase=6, start=30_000, end=32_000)
        two_call_boot(session, "o8", 200, issue=8, launch=2, phase=7, start=40_000, end=41_000)
        two_call_boot(session, "o9", 300, issue=9, launch=1, phase=5, start=50_000, end=56_000)
        session.write()
        document = report(self.root)
        self.assertEqual(
            {row["issue"]: (row["cohort"], row["phase_group"]) for row in document["boots"]},
            {7: ("fresh", "6-7"), 8: ("fresh", "6-7"), 9: ("spawned", "0-5")})
        self.assertEqual(
            [(g["host"], g["cohort"], g["phase_group"], g["count"]) for g in document["groups"]],
            [(host, cohort, group, count) for host in (HOST, "all")
             for cohort, group, count in (("fresh", "6-7", 2), ("fresh", "all", 2),
                                          ("spawned", "0-5", 1), ("spawned", "all", 1))])
        pooled = next(g for g in document["groups"]
                      if (g["host"], g["cohort"], g["phase_group"]) == ("all", "fresh", "all"))
        self.assertEqual((pooled["b_mean"], pooled["b_without_schemas_mean"],
                          pooled["buckets"]["tool_schemas"]), (36_500, 1_700, 34_800))
        self.assertEqual([host["label"] for host in document["hosts"]], [HOST])
        self.assertEqual(document["unsplit"], {"live": {HOST: 0}})

    def test_foreign_flags_are_usage_errors(self):
        for extra in (["--project", "x"], ["--artifacts", "docs"], ["--strata", "codex"],
                      ["--policy", "a=threshold=150000"], ["--sweep"],
                      ["--eval-results", "r.jsonl", "--eval", "from-issue:8"],
                      ["--context-threshold", "5"]):
            with self.subTest(extra=extra):
                completed = costs("--format", "json", "--projects-dir", str(self.root), *extra)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""))

    def test_text_output_prints_its_four_sections_and_footer(self):
        session = Session(self.root)
        two_call_boot(session, "o8", 0, issue=8, launch=2, phase=6, start=20_000, end=21_000)
        session.write()
        completed = costs("--days", "0", "--projects-dir", str(self.root))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        positions = [completed.stdout.find(heading) for heading in (
            "Boot composition (", f"Mean boot buckets, host {HOST}", "Mean boot buckets, all hosts",
            "Top skill bodies and skill files", "Boots by B", "Observed characters per token",
            "Unsplit boots", "NOTE: ")]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))


    def test_group_rows_carry_medians_and_both_sub_totals(self):
        session = Session(self.root)
        sizes = ((1_000, 1_000, 1_000), (2_000, 3_000, 1_000), (4_000, 1_000, 2_000),
                 (9_000, 2_000, 6_000))  # result characters of (plan read, other read, command)
        for issue, (plan, other, command) in enumerate(sizes, start=7):
            stepped_boot(session, f"o{issue}", 100 * issue, [
                (read(f"{PLANS}/2026-10-26-x.md"), plan), (read("/r/src/app.py"), other),
                (bash("ls /r"), command)], issue=issue)
        session.write()
        document = report(self.root)
        for row in document["boots"]:
            self.assertEqual(row["boot_reading"], sum(row["buckets"][name] for name in (
                "skill_bodies", "skill_files", "plan_reads", "resume_reads", "rereads")))
            self.assertEqual(row["first_unit_work"], sum(row["buckets"][name] for name in (
                "commands", "assistant", "other_reads")))
        self.assertEqual(
            sorted((row["b"], row["boot_reading"], row["first_unit_work"])
                   for row in document["boots"]),
            [(23_120, 1_000, 2_120), (26_120, 2_000, 4_120), (27_120, 4_000, 3_120),
             (37_120, 9_000, 8_120)])
        pooled = next(g for g in document["groups"]
                      if (g["host"], g["cohort"], g["phase_group"]) == ("all", "fresh", "all"))
        # Four boots, so each median is the mean of the middle two (B: 23,120 26,120 27,120
        # 37,120; without schemas, B less 19,800).
        self.assertEqual(
            {name: pooled[name] for name in (
                "count", "b_mean", "b_median", "b_without_schemas_mean",
                "b_without_schemas_median", "boot_reading_mean", "boot_reading_median",
                "first_unit_work_mean", "first_unit_work_median")},
            {"count": 4, "b_mean": 28_370, "b_median": 26_620, "b_without_schemas_mean": 8_570,
             "b_without_schemas_median": 6_820, "boot_reading_mean": 4_000,
             "boot_reading_median": 3_000, "first_unit_work_mean": 4_370,
             "first_unit_work_median": 3_620})
        self.assertEqual(pooled["buckets"], buckets(
            tool_schemas=19_800, harness=100, prompt=100, plan_reads=4_000, other_reads=1_750,
            commands=2_500, assistant=120))
        self.assertEqual(pooled["bucket_medians"], buckets(
            tool_schemas=19_800, harness=100, prompt=100, plan_reads=3_000, other_reads=1_500,
            commands=1_500, assistant=120))
        self.assertEqual(document["schema_version"], 2)

    def test_text_output_prints_medians_beside_means_and_the_sub_total_rows(self):
        session = Session(self.root)
        stepped_boot(session, "o7", 0, [(read(f"{PLANS}/2026-10-26-x.md"), 1_000),
                                        (bash("ls /r"), 1_000)])
        session.write()
        completed = costs("--days", "0", "--projects-dir", str(self.root))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        out = completed.stdout
        self.assertRegex(out, r"(?m)fresh 6-7 +median +fresh all +median$")
        self.assertRegex(out, r"(?m)^kind +key +mean +median$")
        self.assertRegex(out, r"\bB +boot reading +first-unit work +tool_schemas\b")
        positions = [re.search(pattern, out, re.M).start() for pattern in (
            r"^unexplained ", r"^boot reading ", r"^first-unit work ", r"^B ",
            r"^B without tool schemas ")]
        self.assertEqual(positions, sorted(positions))


class HostsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.alpha = Path(self.tmp.name) / "alpha"
        self.beta = Path(self.tmp.name) / "beta"
        self.alpha.mkdir()
        self.beta.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_hosts(self):
        """alpha: issue 7's root owner and its second launch, and a launch 2 of issue 9; beta: the same run's issue 7
        as a lone first launch, and a launch 2 of issue 8."""
        alpha = Session(self.alpha)
        g1 = alpha.call(None, 0, context=40_000, write=40_000, ttl="1h", bash=progress(1))
        alpha.result(None, 5, g1, gate_reply("continue"))
        two_call_boot(alpha, "a7", 100, issue=7, launch=1, phase=6, start=30_000, end=32_000)
        two_call_boot(alpha, "a9", 300, issue=9, launch=2, phase=6, start=28_000, end=30_000)
        alpha.write()
        beta = Session(self.beta)
        two_call_boot(beta, "b7", 100, issue=7, launch=1, phase=6, start=25_000, end=27_000)
        two_call_boot(beta, "b8", 200, issue=8, launch=2, phase=6, start=40_000, end=42_000)
        beta.write()

    def test_each_root_is_its_own_host_and_all_pools_every_boot(self):
        self.write_hosts()
        document = report(f"alpha={self.alpha}", f"beta={self.beta}")
        self.assertEqual(document["hosts"], [{"label": "alpha", "root": str(self.alpha)},
                                             {"label": "beta", "root": str(self.beta)}])
        self.assertEqual(
            sorted((row["host"], row["issue"], row["cohort"]) for row in document["boots"]),
            [("alpha", 7, "fresh"), ("alpha", 9, "fresh"), ("beta", 7, "spawned"),
             ("beta", 8, "fresh")])
        means = {(g["host"], g["cohort"], g["phase_group"]): (g["count"], g["b_mean"])
                 for g in document["groups"]}
        self.assertEqual(means[("alpha", "fresh", "all")], (2, 31_000))
        self.assertEqual(means[("beta", "fresh", "all")], (1, 42_000))
        self.assertEqual(means[("all", "fresh", "all")], (3, 104_000 / 3))
        self.assertEqual(means[("all", "spawned", "6-7")], (1, 27_000))
        self.assertEqual([g["host"] for g in document["groups"]],
                         ["alpha"] * 2 + ["beta"] * 4 + ["all"] * 4)
        pooled = next(g for g in document["groups"]
                      if (g["host"], g["cohort"], g["phase_group"]) == ("all", "fresh", "all"))
        # Call 0 of the three fresh boots starts at 30,000, 28,000 and 40,000 with 200 of
        # harness and prompt each, so the schemas are (29,800 + 27,800 + 39,800) / 3 and each
        # boot's B without schemas is 2,200; each grows 2,000 over its second call, 40 of it
        # the first call's output and the rest unexplained.
        self.assertEqual(pooled["b_without_schemas_mean"], 2_200)
        self.assertEqual(pooled["buckets"], buckets(
            tool_schemas=97_400 / 3, harness=100, prompt=100, assistant=40, unexplained=1_960))
        self.assertEqual(document["unsplit"], {"live": {"alpha": 0, "beta": 0}})

    def test_an_unlabelled_root_takes_the_short_hostname(self):
        self.write_hosts()
        document = report(f"alpha={self.alpha}", self.beta)
        self.assertEqual([host["label"] for host in document["hosts"]], ["alpha", HOST])

    def test_bad_roots_are_usage_errors(self):
        for args in (("--projects-dir", f"a={self.alpha}", "--projects-dir", f"a={self.beta}"),
                     ("--projects-dir", f"all={self.alpha}"),
                     ("--projects-dir", str(self.alpha), "--projects-dir", str(self.beta))):
            with self.subTest(boot=args):
                completed = costs("--format", "json", *args)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""))
        for args in (("--projects-dir", f"a={self.alpha}"),
                     ("--projects-dir", str(self.alpha), "--projects-dir", str(self.beta))):
            with self.subTest(owners=args):
                completed = subprocess.run(
                    [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners",
                     "--format", "json", *args], capture_output=True, text=True, check=False)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""))

    def test_text_output_prints_one_table_per_host_and_one_for_all(self):
        self.write_hosts()
        completed = costs("--days", "0", "--projects-dir", f"alpha={self.alpha}",
                          "--projects-dir", f"beta={self.beta}")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for heading in ("Mean boot buckets, host alpha", "Mean boot buckets, host beta",
                        "Mean boot buckets, all hosts"):
            self.assertIn(heading, completed.stdout)


class WindowsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_boots(self, boots, root=None):
        """One session under `root` (default `self.root`) holding an owner per `(seconds, issue,
        project, phase, start, end[, launch])`, launch 2 by default, registering with
        `--repo-root /Users/me/<project>`."""
        session = Session(root or self.root)
        for seconds, issue, project, phase, start, end, *launch in boots:
            two_call_boot(session, f"o{issue}", seconds, issue=issue, launch=(launch or [2])[0],
                          phase=phase, start=start, end=end, repo_root=f"/Users/me/{project}")
        session.write()

    def test_without_a_baseline_every_row_is_live_and_reweighted_is_null(self):
        self.write_boots(WINDOW_BOOTS)
        document = report(self.root, extra=EVENTS)
        self.assertEqual(list(document), TOP_KEYS)
        self.assertEqual(document["window"], "events 2026-10-25T10:00:00Z → 2026-10-25T11:00:00Z")
        self.assertEqual(
            [(row["arm"], row["issue"], row["project"]) for row in document["boots"]],
            [("live", 21, "alpha"), ("live", 22, "alpha"), ("live", 23, "alpha"),
             ("live", 24, "beta")])
        for row in document["boots"]:
            self.assertEqual(list(row), BOOT_KEYS)
        for row in document["groups"]:
            self.assertEqual((list(row), row["arm"]), (GROUP_KEYS, "live"))
        self.assertEqual((document["unsplit"], document["reweighted"]), ({"live": {HOST: 0}}, None))

    def test_a_baseline_collects_each_window_as_its_lone_run_does(self):
        self.write_boots(WINDOW_BOOTS)
        document = report(self.root, extra=(*EVENTS, "--baseline", BASELINE))
        self.assertEqual(list(document), TOP_KEYS)
        self.assertEqual(document["window"],
                         "baseline 2026-10-25T09:00:00Z → 2026-10-25T10:00:00Z; "
                         "candidate 2026-10-25T10:00:00Z → 2026-10-25T11:00:00Z")
        self.assertEqual(
            [(row["arm"], row["issue"], row["project"]) for row in document["boots"]],
            [("baseline", 11, "alpha"), ("baseline", 12, "beta"), ("baseline", 13, "beta"),
             ("baseline", 14, "beta"), ("candidate", 21, "alpha"), ("candidate", 22, "alpha"),
             ("candidate", 23, "alpha"), ("candidate", 24, "beta")])
        self.assertEqual([row["arm"] for row in document["groups"]],
                         ["baseline"] * 4 + ["candidate"] * 4)
        self.assertEqual(document["unsplit"], {"baseline": {HOST: 0}, "candidate": {HOST: 0}})

        def without_arm(rows, arm):
            return [{key: value for key, value in row.items() if key != "arm"}
                    for row in rows if row["arm"] == arm]

        for arm, window in (("baseline", BASELINE_EVENTS), ("candidate", EVENTS)):
            with self.subTest(arm=arm):
                alone = report(self.root, extra=window)
                self.assertEqual(without_arm(document["boots"], arm),
                                 without_arm(alone["boots"], "live"))
                self.assertEqual(without_arm(document["groups"], arm),
                                 without_arm(alone["groups"], "live"))

    def test_baseline_usage_errors_come_before_any_root_is_read(self):
        missing = str(self.root / "missing")
        for extra in (["--baseline", BASELINE],
                      [*EVENTS, "--baseline", "2026-10-25T09:00:00Z"],
                      [*EVENTS, "--baseline", "2026-10-25T10:00:00Z..2026-10-25T09:00:00Z"],
                      [*EVENTS, "--baseline", "2026-10-25T09:30:00Z..2026-10-25T10:30:00Z"]):
            with self.subTest(extra=extra):
                completed = costs("--format", "json", "--projects-dir", missing, *extra)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""))
        for name in ("issues", "cache"):
            with self.subTest(report=name):
                completed = subprocess.run(
                    [sys.executable, "-m", "agent_tools.agent_costs", "--report", name,
                     "--projects-dir", missing, "--baseline", BASELINE],
                    capture_output=True, text=True, check=False)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""))
        touching = costs("--format", "json", "--projects-dir", missing, *EVENTS,
                         "--baseline", "2026-10-25..2026-10-25T10:00:00Z")
        self.assertEqual(touching.returncode, 1, touching.stderr)   # parsed; the root is missing

    def test_text_output_with_a_baseline_prints_each_arm_in_turn(self):
        self.write_boots(WINDOW_BOOTS)
        completed = costs("--projects-dir", str(self.root), *EVENTS, "--baseline", BASELINE)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        out = completed.stdout
        self.assertIn("; baseline 4 boots: 4 fresh, 0 spawned; "
                      "candidate 4 boots: 4 fresh, 0 spawned;", out)
        self.assertRegex(out, r"\bissue +project +cohort\b")
        positions = [out.find(heading) for heading in (
            "Boot composition (", f"Mean boot buckets, baseline, host {HOST} ",
            "Mean boot buckets, baseline, all hosts", "Top skill bodies and skill files, baseline",
            "Boots by B, baseline", f"Mean boot buckets, candidate, host {HOST} ",
            "Mean boot buckets, candidate, all hosts",
            "Top skill bodies and skill files, candidate", "Boots by B, candidate",
            "Observed characters per token",
            f"Unsplit boots (no request records, left out): baseline {HOST} 0; candidate {HOST} 0\n",
            "NOTE: ")]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))

    def test_the_candidate_is_reweighted_to_the_baseline_project_mix(self):
        """AC: baseline alpha x1 and beta x3, candidate alpha x3 and beta x1; one host, fresh, 6-7."""
        self.write_boots(WINDOW_BOOTS)
        document = report(self.root, extra=(*EVENTS, "--baseline", BASELINE))
        rows = document["reweighted"]
        self.assertEqual([(row["host"], row["cohort"], row["phase_group"]) for row in rows],
                         [(HOST, "fresh", "6-7"), (HOST, "fresh", "all"), ("all", "fresh", "6-7"),
                          ("all", "fresh", "all")])
        # Candidate weights n0/n1: 1/3 for each alpha boot, 3 for the beta boot (total 4).
        # B: alpha 30,000 32,000 34,000, beta 50,000. The mean is 1/4 x 32,000 + 3/4 x 50,000 =
        # 45,500. The weighted median is 50,000: cumulative 1/3, 2/3, 1, 4 first reaches 2 there,
        # while the plain median is 33,000. Without schemas (end - start + 200): alpha 10,200
        # 11,200 12,200, beta 24,200, so 1/4 x 11,200 + 3/4 x 24,200 = 20,950, median 24,200.
        candidate = {"count": 4, "b_mean": 45_500, "b_median": 50_000,
                     "b_without_schemas_mean": 20_950, "b_without_schemas_median": 24_200}
        # Every baseline stratum is common, so the baseline side is the baseline group row:
        # B 40,000 52,000 54,000 56,000; without schemas 16,200 24,200 26,200 28,200.
        baseline = {"count": 4, "b_mean": 50_500, "b_median": 53_000,
                    "b_without_schemas_mean": 23_700, "b_without_schemas_median": 25_200}
        for row in rows:
            with self.subTest(host=row["host"], phase_group=row["phase_group"]):
                self.assertEqual(list(row), ["host", "cohort", "phase_group", "common_strata",
                                             "baseline", "candidate"])
                self.assertEqual((list(row["baseline"]), list(row["candidate"])),
                                 (SIDE_KEYS, SIDE_KEYS))
                self.assertEqual((row["common_strata"], row["baseline"], row["candidate"]),
                                 (2, baseline, candidate))
                group = {g["arm"]: g for g in document["groups"] if (g["host"], g["cohort"],
                         g["phase_group"]) == (row["host"], row["cohort"], row["phase_group"])}
                self.assertEqual({key: group["baseline"][key] for key in SIDE_KEYS}, baseline)
                self.assertEqual((group["candidate"]["b_mean"], group["candidate"]["b_median"]),
                                 (36_500, 33_000))

    def test_strata_in_one_window_drop_out_and_a_scope_with_none_in_common_is_null(self):
        self.write_boots(COVERAGE_BOOTS)
        document = report(self.root, extra=(*EVENTS, "--baseline", BASELINE))
        empty = dict.fromkeys(SIDE_KEYS, None) | {"count": 0}
        alpha_baseline = {"count": 1, "b_mean": 40_000, "b_median": 40_000,
                          "b_without_schemas_mean": 16_200, "b_without_schemas_median": 16_200}
        alpha_candidate = {"count": 1, "b_mean": 30_000, "b_median": 30_000,
                           "b_without_schemas_mean": 10_200, "b_without_schemas_median": 10_200}
        self.assertEqual(
            [(row["host"], row["cohort"], row["phase_group"], row["common_strata"],
              row["baseline"], row["candidate"]) for row in document["reweighted"]],
            [(host, "fresh", group, *sides) for host in (HOST, "all") for group, sides in (
                ("0-5", (0, empty, empty)), ("6-7", (1, alpha_baseline, alpha_candidate)),
                ("all", (1, alpha_baseline, alpha_candidate)))])

    def test_reweighted_strata_keep_hosts_and_cohorts_apart(self):
        """WINDOW_BOOTS with beta's boots on host b, every boot project alpha, plus a spawned
        candidate boot on a: pooling hosts (common 1, mean 36,500) or cohorts fails
        (issue 504 D13)."""
        roots = {label: self.root / label for label in ("a", "b")}
        for label, project in (("a", "alpha"), ("b", "beta")):
            spawned = [(4_100, 25, "alpha", 6, 20_000, 90_000, 1)] if label == "a" else []
            self.write_boots([(*boot[:2], "alpha", *boot[3:]) for boot in WINDOW_BOOTS
                              if boot[2] == project] + spawned, root=roots[label])
        document = report(*(f"{label}={root}" for label, root in roots.items()),
                          extra=(*EVENTS, "--baseline", BASELINE))
        rows = {(r["host"], r["cohort"], r["phase_group"]): (r["common_strata"], *(
            r["candidate"][key] for key in ("count", "b_mean", "b_median")))
            for r in document["reweighted"]}
        self.assertEqual((rows[("all", "fresh", "all")], rows[("a", "fresh", "6-7")],
                          rows[("all", "spawned", "all")]),
                         ((2, 4, 45_500, 50_000), (1, 3, 32_000, 32_000), (0, 0, None, None)))

    def test_text_output_prints_the_reweighted_table_after_both_arms(self):
        self.write_boots(COVERAGE_BOOTS)
        completed = costs("--projects-dir", str(self.root), *EVENTS, "--baseline", BASELINE)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        out = completed.stdout
        positions = [out.find(heading) for heading in (
            "Boots by B, candidate",
            "Reweighted to the baseline's host × phase group × project mix",
            "Observed characters per token")]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))
        self.assertRegex(out, rf"(?m)^{re.escape(HOST)} +fresh +0-5 +0 +0 +0( +-){{8}}$")
        live = costs("--projects-dir", str(self.root), *EVENTS)
        self.assertNotIn("Reweighted to", live.stdout)


if __name__ == "__main__":
    unittest.main()
