"""agent-costs --report boot (issue 448, spec test seam 1)."""
import json
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


def two_call_boot(session, agent, seconds, *, issue, launch, phase, start, end, requests=True):
    """A child owner booting from `start` to `end` in two calls, registering at the second."""
    session.child(agent, tool_use_id=dispatch(session, seconds))
    if requests:
        opening(session, agent)
    session.call(agent, seconds + 10, context=start, write=start)
    gate = session.call(agent, seconds + 20, context=end, write=end - start,
                        bash=progress(phase, action_id=f"{issue}:1:{launch}"))
    session.result(agent, seconds + 21, gate, gate_reply("continue", issue=issue, launch=launch))


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
        self.assertEqual(document["unsplit"], {HOST: 1})
        self.assertIsNone(document["observed_chars_per_token"])

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
        self.assertEqual(document["unsplit"], {HOST: 0})

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
        self.assertEqual(document["unsplit"], {"alpha": 0, "beta": 0})

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


if __name__ == "__main__":
    unittest.main()
