# Task 1: The boot report over one root — attribution, cohorts, groups, JSON and text

Spec § The boot report (Module and seam, Cohorts, Attribution, Buckets, Document); per D1–D4, D14, D17. This task reads one transcript root, either `--projects-dir PATH` or the default `~/.claude/projects`, labelled with the local short hostname. Task 2 makes the root repeatable and labelled. Every function below already takes a list of hosts, so Task 2 changes only the argument parsing.

**Files:**
- Create: `python/agent_tools/agent_boot_report.py`
- Modify: `python/agent_tools/agent_costs.py`: add `--report boot`, its flag gating, `_boot_report`, and `_window_label`, which is factored out of `_owners_report`'s non-eval window branch and the cache report's identical branch.
- Modify: `tests/owner_transcripts.py`: request records, Skill meta messages, any tool use.
- Create: `tests/test_agent_boot_report.py`
- Modify: `justfile`: `agent-workflow-tests` lists `tests/test_agent_boot_report.py` on the line after `tests/test_agent_owner_replay.py`.
- Modify: `python/README.md`: in the agent-costs section, a `**Boot report (issue 448).**` paragraph after the owner report's last paragraph, which begins "The keep rule (D8)".

**Interfaces:**
- Consumes (unchanged):
  - from `agent_owner_report`: `collect(root, *, cutoff, since, before, eval_rows, executor_factory) -> (lineages, footer)`, `boot_facts(launch) -> (group, facts) | None`, `boot_slice(launch) -> tuple`, `_SAVED_TO` (`saved to: (\S+)`) and `_TASK_FILE` (`\.tasks/task-(\d+)\.md$`);
  - `Lineage.run_id/.issue/.launches` (in lineage order) and `Launch.transcript` (path string) and `.launch` (ordinal or `None`);
  - `transcript_calls.read_transcript(handle)`: its `.calls` list `Call` objects (`first_line`, `context`, `usage["output_tokens"]`, `tool_names`, `tool_inputs`), and its `.results` map a tool-use ID to `ToolResult(line, text, size, ends_turn)`;
  - `context_meter_commands.lex(command) -> list[Token] | None` and `SEPARATORS`;
  - from `agent_costs`: `scan_paths(jobs, executor_factory, scanner=…)`, `print_table`, `human`, `DISCLAIMER` and `format_rfc3339_utc`.
- Produces (Task 2 and Task 3 rely on these exact names):
  - `agent_boot_report.SCHEMA_VERSION = 1`, `REPORT_KIND = "agent-boot-report"`, `CHARS_PER_TOKEN = 2.44`, `RATIO_MIN_CHARS = 2_000`, `ALL = "all"`.
  - `BUCKETS = ("tool_schemas", "harness", "prompt", "skill_bodies", "skill_files", "plan_reads", "resume_reads", "rereads", "other_reads", "commands", "assistant", "unexplained")`, `READERS = ("cat", "sed", "head", "tail", "nl", "awk", "jq", "less")`, `COHORTS = ("fresh", "spawned")` and `PHASE_GROUPS = ("0-5", "6-7", "all")`.
  - `short_hostname() -> str`: `socket.gethostname().split(".", 1)[0]`.
  - `attribute(job: tuple[str, int]) -> dict | None`: a module-level function, so the process pool can pickle it. Called with `(transcript path, boot call count)`, it returns `{"start", "b", "buckets", "skills", "skill_files", "ratio_chars", "ratio_tokens"}`, or `None` (unsplit) when no `api-request-shape` record and no `api-request` record precede call 0, or the file cannot be opened.
  - `collect_host(label: str, root: Path, *, cutoff, since, before, executor_factory) -> dict`: `{"label", "root" (str), "boots": [row, ...], "unsplit": int, "ratio_chars": int, "ratio_tokens": int}`.
  - `build_document(hosts: list[dict], *, window: str) -> dict`; `print_document(doc: dict, *, top: int) -> None`.
  - `agent_costs._boot_report(ap, args, cutoff, event_start, event_end, executor_factory)`; `agent_costs._window_label(args, cutoff, event_start, event_end) -> str`, which returns `events <since> → <before>`, `last <n>d by file mtime` or `all time`, exactly as the two branches it replaces did.
  - `tests/owner_transcripts.Session.shape(agent, *, system, tools)`, `.blob(agent, role, blocks) -> str`, `.request(agent, tail)`, `.skill_body(agent, seconds, tool_id, text)`, and `call(..., tool=None)`.

**Invariants:**
- Every boot row's twelve buckets are integers that sum exactly to its `b`. `skills` sums to `buckets["skill_bodies"]`, and `skill_files` to `buckets["skill_files"]`.
- A row's `b` and `start` equal `boot_facts(launch)[1]["b"]` and `["start"]`, and `calls` equals `len(boot_slice(launch))`.
- `--report owners`, `cache` and `issues` print exactly what they printed before (the existing report tests pass unchanged).
- The JSON document's keys are exactly `kind, schema_version, window, hosts, chars_per_token, observed_chars_per_token, unsplit, boots, groups`. A boot row's keys are exactly `host, transcript, run_id, issue, cohort, phase_group, calls, start, b, buckets, skills, skill_files`. A group row's keys are exactly `host, cohort, phase_group, count, b_mean, b_without_schemas_mean, buckets`.
- Every refused flag exits 2 with nothing on stdout.

- [ ] **Step 1: Extend the fixture builder and write the failing tests**

In `tests/owner_transcripts.py`, add one keyword to `Session.call`: `tool=None`, a `(name, input)` pair for any tool the other options do not name. Add it to the condition that creates a tool use, and use it as `(name, tool_input)` before the existing `bash`/`agent_tool`/`read_file` choice. Then add these methods to `Session`:

```python
    def shape(self, agent, *, system, tools):
        """An `api-request-shape` record: the system blocks' texts and the tool definitions."""
        self.lines[agent].append(_line({
            "type": "api-request-shape", "agentId": agent, "shapeHash": self._id("shape-"),
            "shape": {"system": [{"type": "text", "text": text} for text in system],
                      "tools": list(tools)}}))

    def blob(self, agent, role, blocks):
        """An `api-request-blob` record holding one message; returns its hash."""
        digest = self._id("blob-")
        self.lines[agent].append(_line({
            "type": "api-request-blob", "agentId": agent, "hash": digest,
            "message": {"role": role, "content": list(blocks)}}))
        return digest

    def request(self, agent, tail):
        """An `api-request` record whose tail names blob hashes."""
        self.lines[agent].append(_line({
            "type": "api-request", "agentId": agent, "id": self._id("req-"), "tail": list(tail)}))

    def skill_body(self, agent, seconds, tool_id, text):
        """The meta user message that carries the body a Skill call loaded."""
        self.lines[agent].append(_line({
            "type": "user", "isSidechain": agent is not None, "isMeta": True,
            "sourceToolUseID": tool_id, "timestamp": at(seconds),
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}))
```

Create `tests/test_agent_boot_report.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

The arithmetic each test pins. In the first test, call 0's text is (244 + 2,440) ÷ 2.44 = 1,100 harness tokens plus 488 ÷ 2.44 = 200 prompt tokens, so `tool_schemas` is 30,000 − 1,300. Each later call's growth is 40 output tokens plus the added characters (one character per token, apart from call 2's 6,100 characters for 2,500 tokens, the observed ratio 2.44). The skill body logged again as a request blob is counted once.

- [ ] **Step 2: Run the tests and watch them fail**

Run: **Boot tests**.
Expected: FAIL. Every test errors or fails with `argument --report: invalid choice: 'boot'` (exit 2), and the flag test's subtests already pass.

- [ ] **Step 3: Write the minimal implementation**

`agent_costs.main`:
- Add `boot` to `--report`'s choices and help. Set `boot_report = args.report == "boot"`.
- With `boot_report`, `ap.error` on `--project`, `--artifacts` and `--strata` other than `claude`, as `owners` does, with the message naming `--report boot`. The existing checks already refuse `--policy`/`--sweep`, `--eval-results`/`--eval` and `--context-threshold` outside their reports.
- Extend the `--events-since/--events-before` availability check to cover `boot_report`.
- Dispatch `if boot_report: return _boot_report(...)` right after the owners dispatch.
- `_boot_report` imports `agent_boot_report` inside the function, as `_owners_report` imports its module. It takes `root = Path(args.projects_dir)` and exits through `sys.exit(f"no transcript root at {root}")` when that is not a directory.
- It then makes one host: `collect_host(short_hostname(), root, cutoff=event_start.timestamp() if event_start else cutoff, since=event_start, before=event_end, executor_factory=executor_factory)`.
- It builds `build_document([host], window=_window_label(...))` and prints compact JSON with `--format json` (`separators=(",", ":")`), else `print_document(doc, top=args.top)`.

`agent_boot_report` (module docstring: what it reports, the seam to `agent_owner_report`, and that python/README.md (agent-costs) holds the contract):

- **`collect_host`.** Call `agent_owner_report.collect(root, ..., eval_rows=None, ...)`. Then, for each lineage in order and each launch in `lineage.launches` with `boot_facts(launch)` not `None`, record the job `(launch.transcript, len(boot_slice(launch)))`, together with `run_id`, `issue`, the boot's `phase_group` and its cohort. The cohort is `"fresh"` when the launch is not `lineage.launches[0]` or `isinstance(launch.launch, int) and launch.launch >= 2`, else `"spawned"` (D4). Attribute every job through `scan_paths(jobs, executor_factory, scanner=attribute)`. A `None` result adds 1 to `unsplit`; every other result becomes a row, with its `ratio_chars`/`ratio_tokens` summed into the host's.
- **`attribute`, call 0** (D3). Read the file once with `read_transcript`, keeping `calls = transcript.calls[:n]`. Read it a second time line by line, `json.loads`-ing only the lines that contain `"type":"api-request` or `"isMeta":true`. Keep each record's line number, a hash-to-blob map (first occurrence wins), and a tool map merged from every call's `tool_names`/`tool_inputs`.
  - The shape is the last `api-request-shape` record before `calls[0].first_line`, and the request is the last `api-request` record before it. If either is missing, return `None`.
  - Harness characters are the shape's system texts, plus every text block of the request's tail blobs that is in a `system`-role message or starts with `<system-reminder>`. Prompt characters are every other text block of those blobs. `tool_addition` and `tool_result` blocks add nothing.
  - `harness = round(h ÷ 2.44)` and `prompt = round(p ÷ 2.44)`. `tool_schemas = start − harness − prompt`, unclamped.
  - Remember the shape's tool characters, `sum(len(json.dumps(tool, separators=(",", ":"))))`, and mark the tail's hashes as counted.
- **`attribute`, call i ≥ 1.**
  - `growth = calls[i].context − calls[i−1].context`. When `growth ≤ 0`, add it to `unexplained` and continue.
  - Otherwise `assistant += min(growth, calls[i−1].usage["output_tokens"])`, and the residual is the rest.
  - The segment is the lines strictly between `calls[i−1].first_line` and `calls[i].first_line`. Its chunks `(bucket, sub_key, chars)` come in line order:
    1. each tool result whose `line` is in the segment, at `chars = result.size`, classified below;
    2. each meta user record whose `sourceToolUseID` is a `Skill` call, at its joined text length, as `skill_bodies` keyed by the Skill input's `skill`;
    3. each `api-request` record's tail hashes not yet counted. Each one is marked counted. Its text blocks become `harness` chunks, except a text equal to a meta record's text in this segment, which is skipped. `tool_addition` blocks become `tool_schemas` chunks at their compact JSON length, and `tool_result` blocks are skipped;
    4. each `api-request-shape` record, which becomes a `tool_schemas` chunk of `max(0, new tool characters − previous)`, after which the previous tool characters become the new ones.
  - With residual > 0 and total chunk characters > 0, each chunk gets `floor(residual × chars ÷ total)`. The leftover goes to the chunk with the most characters, the first one on a tie. With residual > 0 and no characters, the residual goes to `unexplained`.
  - When total > `RATIO_MIN_CHARS` and residual > 0, add the total to `ratio_chars` and the residual to `ratio_tokens`.
- **Classifying a tool result** (D2, D17), with per-boot state `seen` (read keys) and `saved` (path → `(bucket, sub_key)`). Every result first records each `_SAVED_TO` match in its text into `saved` with the bucket decided below. The bucket is the first rule that holds:
  1. A `Read` whose `file_path` is in `saved` takes that entry.
  2. A call with at least one read key, every key already in `seen`, is `rereads`. Its keys join `seen` in every case.
  3. Text matching `"kind"\s*:\s*"resume_pack"`, or both `"kind"\s*:\s*"owner"` and `"interface_version"\s*:\s*2\b`, is `resume_reads`.
  4. Path classes: the first read path, in read order, that is a skill file gives `skill_files` with its key, else any plan path gives `plan_reads`, else any read gives `other_reads`.
  5. A `Skill` call is `skill_bodies`, keyed by its `skill`.
  6. Anything else, including a tool-use ID missing from the tool map, is `commands`.
- **Read keys.**
  - A `Read` gives `(file_path, offset, limit)`.
  - A `Bash` command is processed line by line, with `cwd` and `env` starting empty for each call.
    - Outside a heredoc, every operator `(?<!<)<<-?(?!<)\s*(['"]?)([A-Za-z_]\w*)\1` is cut from its line, and the lines after it are skipped through the one whose stripped text is the delimiter.
    - The joined remainder goes to `lex`. When `lex` returns `None`, the call reads nothing.
    - The tokens are split into simple commands at `op` tokens in `SEPARATORS`. Within each simple command, every other `op` token and the word after it (a redirection and its target) are dropped.
    - Expanding a word replaces each `$NAME`/`${NAME}` with `env[NAME]`, leaving unknown names as written.
    - Leading `NAME=value` words set `env[NAME]` to the expanded value. `cd DIR` expands `DIR`, then sets `cwd` to it when it is absolute or starts with `~`, else to `posixpath.normpath(cwd + "/" + DIR)` (just `DIR` while `cwd` is empty).
    - The program word is the first other word. When its basename is in `READERS`, the remaining words are scanned. A word starting with `-` is an option, and for `head`/`tail`, `-n` and `-c` also consume the next word. For `sed`, `awk` and `jq`, the first non-option word is the program text.
    - Every other word, once expanded, is an operand when it contains `/` or ends in `\.[A-Za-z0-9]+`. A relative operand joins `cwd` as `cd` does.
    - Each operand's key is `(path, tuple(words from the program word on, redirections excluded))`.
  - Other tools read nothing.
- **Path classes** (on `PurePosixPath(path).parts`):
  - A skill file has a component equal to `skills` with two or more components after the last such one, keyed `"/".join(parts after it)`.
  - A plan path matches `_TASK_FILE`, or is a `.md` whose parent directory is `plans` and whose name does not end in `.acceptance.md`, or is a `progress.md` with `.superpowers` and `sdd` among its components.
- **`build_document`.**
  - It returns the nine keys in invariant order, with `schema_version` 1, `kind` `REPORT_KIND`, `chars_per_token` 2.44, `hosts = [{"label", "root"}]`, `unsplit = {label: n}` and `boots` (each host's rows in collect order).
  - `observed_chars_per_token` is `round(Σ ratio_chars ÷ Σ ratio_tokens, 2)`, or `null` when no tokens.
  - `groups` holds, for each host label and then `"all"` (every host's boots), each cohort in `COHORTS` order and each phase group in `PHASE_GROUPS` order (`"all"` pooling `0-5` and `6-7`), one row when `count > 0`. The row's `b_mean`, `b_without_schemas_mean` (the mean of `b − buckets["tool_schemas"]`) and per-bucket means are `statistics.fmean` values.
- **`print_document`** prints, in order:
  - `Boot composition (<window>; hosts: <label> <root>, …; <n> boots: <f> fresh, <s> spawned; call 0 at 2.44 characters per token)`;
  - for each host and then for all hosts, `Mean boot buckets, host <label> (tokens per boot):` or `Mean boot buckets, all hosts (tokens per boot):`, then a `print_table` whose rows are `boots`, each bucket, `B` and `B without tool schemas`, and whose columns are that host's groups (`fresh 6-7`, …);
  - `Top skill bodies and skill files (mean tokens per fresh boot, all hosts):`, a table of `skill`/`file`, key and mean over the pooled fresh boots, a missing key counting 0, sorted descending and capped at `top`;
  - `Boots by B (host, issue, cohort, phase, calls, start, B, then each bucket):`, a table sorted by `-b` then `transcript`, capped at `top` with the owner report's `... N more rows not shown` line.

  Then the footer lines `Observed characters per token (boot calls adding more than 2,000 characters): <x or none>`, `Unsplit boots (no request records, left out): <label> <n>, …` and `NOTE: {DISCLAIMER}`. Use `human()` for token figures.

README paragraph. Write it from the code as built. It states:
- the report's purpose (a fresh owner's boot split into buckets) and the flags it takes and refuses (D14);
- the boot and cohort definitions, the attribution rule with the fixed 2.44 and the observed ratio, the bucket list and the classification order (D17's path classes included), and `unsplit`;
- the document's exact key sets.

- [ ] **Step 4: Verify**

Run: **Boot tests**. Expected: PASS, 6 tests.
Run: **Report tests**. Expected: PASS, every pre-existing test unchanged.
Run: **Build** (the new module joins the package's import check). Expected: exit 0.
Run: `bash -c 'grep -q "tests/test_agent_boot_report.py" justfile'`. Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_boot_report.py python/agent_tools/agent_costs.py \
  tests/owner_transcripts.py tests/test_agent_boot_report.py justfile python/README.md
git commit -m "feat(agent-costs): --report boot splits each owner boot into buckets (issue 448)"
```
