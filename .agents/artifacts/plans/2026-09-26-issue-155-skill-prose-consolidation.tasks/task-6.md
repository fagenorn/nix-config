# Task 6: The `report` command and the `agent-instruction-load` recipe

**Files:**
- Modify: `IL`, `justfile`
- Test: `T/test_instruction_load.py`

**Interfaces:**
- Consumes (Task 5, in `IL`): `MODEL_PATH`, `FRAME_MEMBER`, `HOSTS`, `Reader`,
  `load_model(data)`, `validate(model, read)`, `measure(model, read)` and the
  host-counting rule. The measurement shape is `{"frame", "documents":
  {member: {"path", "tree", "bytes", "words", "absent"}}, "profiles": {id:
  {host: {"hot"|"conditional": {"members", "bytes", "words"}}}}}`. From the test
  module: `BASE_FILES`, `HEAD_FILES` and `fixture_model()`.
- Produces in `IL`:
  - `REGENERATE = "just agent-instruction-load report --base {base} --head {head} --output <path>"`.
  - `revision_reader(root: Path, revision: str) -> tuple[str, Reader]`: the full
    commit SHA plus a reader over that commit.
  - `compare(model, base_measurement, head_measurement, base: str, head: str) -> dict`,
    the report data.
  - `render_markdown(report) -> str` and `render_json(report) -> str`.
  - `main(argv: Optional[list[str]] = None) -> int`, with `if __name__ ==
    "__main__": raise SystemExit(main())`.
  - The CLI is `agent-instruction-load report --base REV --head REV
    [--output PATH] [--format markdown|json] [--root DIR]`. The default format
    is `markdown` and the default root is the current directory.
- Produces in `justfile`: the recipe `agent-instruction-load *args`.

**Invariants:**
- The output is a function of the two SHAs alone (D17). The model and the matrix
  are read at `--head`, every member at each revision, all through
  `revision_reader`. Nothing reads the working tree, the clock, the environment
  or the `--output` path. The regeneration line prints the literal `<path>`.
- `revision_reader` runs these commands:
  - `git -C <root> rev-parse --verify --quiet --end-of-options <rev>^{commit}`.
    A non-zero exit raises `ValueError(f"unknown revision {rev!r}")`.
  - `git -C <root> ls-tree -r -z --name-only <sha>` once, for the path set. A
    path outside the set reads as `None`.
  - `git -C <root> show <sha>:<path>` per present path, cached.
  Any other git failure raises
  `ValueError(f"git <subcommand> failed: <last stderr line>")`.
- `main` exits 2 for an unknown revision, a model absent at head, an invalid
  model at head or a git failure. The absent-model message is
  `no home/common/agent-skills/instruction-load.json at <head sha>`. An invalid
  model gives `invalid model at <head sha>: ` followed by the violations joined
  by `; `. On exit 2, stderr is exactly one line,
  `agent-instruction-load: <message>`, with its whitespace runs collapsed.
  Stdout is empty and no output file is written. On success it writes the text
  to `--output` (UTF-8, stdout empty), or to stdout, and returns 0.
- `compare` returns
  `{"base", "head", "frame", "documents", "profiles"}`.
  - `frame` is `{"member", "base", "head", "delta"}`, where `base` and `head` are
    `{"bytes", "words", "absent"}` and `delta` is `{"bytes", "words"}`.
  - `documents` is sorted by member. Each entry is
    `{"member", "hosts", "base", "head", "delta"}`, with `hosts` from the head
    tree.
  - `profiles` is in model order. Each entry is
    `{"id", "entry", "launch", "prompt", "note", "unread", "hosts"}`, where the
    absent one of `entry` and `launch` is `null`. `hosts[host]` is
    `{"hot": T, "conditional": T, "ceiling_bytes": int}`, and each `T` is
    `{"members", "base", "head", "delta", "affected"}`.
  - `members` is the head measurement's list. `base` sums the base bytes and
    words of those same members. `affected` is true when any listed member's
    `(bytes, words, absent)` differs between the revisions (D26).
- `render_json` is `json.dumps(report, indent=2, ensure_ascii=False) + "\n"`.
- `render_markdown` emits, in order, joined by `\n` with a trailing newline:
  1. `# Instruction load: <base[:7]> → <head[:7]>`, a blank line, then
     `` - Base: `<base>` ``, `` - Head: `<head>` `` and
     `` - Regenerate: `<REGENERATE filled>` ``.
  2. The two preface paragraphs below, verbatim.
  3. `## Frame` with the columns
     `| Member | Base bytes | Head bytes | Δ bytes | Base words | Head words | Δ words |`.
  4. `## Hot totals`, then `## Conditional totals`, each with the columns
     `| Profile | Host | Base bytes | Head bytes | Δ bytes | Base words | Head words | Δ words | Affected | Note |`.
     There is one row per profile and host in model order, `Affected` is `yes`
     or `no`, and `|` in a note is escaped as `\|`.
  5. `## Documents` with the columns
     `| Member | Hosts | Base bytes | Head bytes | Δ bytes | Base words | Head words | Δ words |`.
     An absent side shows `absent` in its bytes cell.
  6. `## Members by profile`, one `### <id>` per profile with these bullets:
     - `` - Launched by: entry `<skill>` `` or
       `` - Launched by: sites `<a>`, `<b>` ``
     - `` - Prompt: `<doc>` (not measured) `` or `- Prompt: none (an entry)`
     - one `` - <host> — hot: `<m>`, …; conditional: `<m>`, … `` per host,
       with `none` for an empty list
     - one `` - Unread: `<m>` — <reason> `` per unread entry

  Every delta is signed (`+13`, `-70`, `0`). The tables use GitHub pipe syntax,
  with a `---:` alignment for numeric columns. A row is `| ` + the cells joined
  by ` | ` + ` |`. A Member cell is a code span (`` `demo/NEW.md` ``), and every
  other cell is plain text. The Hosts cell joins the head-tree hosts with `, `.
  An absent side shows `absent` in its bytes cell and `0` in its words cell.
  The Step 1 row literals pin this (D33). The preface paragraphs:

  > Bytes are UTF-8 lengths and words are whitespace-separated tokens; neither is a token count. A hot member loads on every run of its profile's standard route and a conditional member only on a named branch. A shared-tree member counts on both hosts; a Claude-only-tree member or an agent definition counts on Claude only.
  >
  > Not measured: received prompts (each profile names its prompt's source document), the harness system prompt and skill listing, project instructions, and plugin or generated skills. The frame, the global guidance file installed for both hosts, is reported once and kept out of every profile total.

- The module docstring becomes `"""Measure the instruction documents each agent
  profile loads, per host, and compare two revisions."""`.

- [ ] **Step 1: Write the failing test**

Add `import os`, `import subprocess` and `import sys` to the imports of
`T/test_instruction_load.py`. Then append, before the `if __name__ ==
"__main__":` block:

```python
GIT_LOCATION_VARS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
)


def git_env():
    """Hermetic git, as test_sdd_workspace.py: no user or system config, so no signing."""
    env = dict(os.environ)
    for name in GIT_LOCATION_VARS:
        env.pop(name, None)
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.test",
        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.test",
    })
    return env


class ReportCommandTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.env = git_env()
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")
        self.base = self.commit(BASE_FILES, "base")
        self.head = self.commit({**HEAD_FILES, instruction_load.MODEL_PATH:
                                 json.dumps(fixture_model(), indent=2).encode()}, "head")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, files, message):
        for relative, data in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def report(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.instruction_load", "report",
             "--root", str(self.repo), *args],
            env=self.env, capture_output=True, text=True, check=False)

    def json_report(self):
        completed = self.report("--base", self.base, "--head", self.head, "--format", "json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_json_reports_hand_computed_deltas(self):
        data = self.json_report()
        self.assertEqual((data["base"], data["head"]), (self.base, self.head))
        demo = next(p for p in data["profiles"] if p["id"] == "demo")
        self.assertEqual(demo["hosts"]["claude"]["hot"]["base"], {"bytes": 38, "words": 7})
        self.assertEqual(demo["hosts"]["claude"]["hot"]["head"], {"bytes": 51, "words": 9})
        self.assertEqual(demo["hosts"]["claude"]["hot"]["delta"], {"bytes": 13, "words": 2})
        self.assertTrue(demo["hosts"]["claude"]["hot"]["affected"])
        self.assertEqual(demo["hosts"]["codex"]["conditional"]["delta"], {"bytes": 9, "words": 2})
        self.assertEqual(demo["hosts"]["claude"]["conditional"]["delta"], {"bytes": 9, "words": 2})
        self.assertEqual(demo["hosts"]["claude"]["ceiling_bytes"], 51)
        reviewer = next(p for p in data["profiles"] if p["id"] == "demo-reviewer")
        self.assertEqual(reviewer["hosts"]["claude"]["hot"]["delta"], {"bytes": 0, "words": 0})
        self.assertFalse(reviewer["hosts"]["claude"]["hot"]["affected"])
        self.assertEqual(reviewer["hosts"]["codex"]["hot"]["members"], [])
        new = next(d for d in data["documents"] if d["member"] == "demo/NEW.md")
        self.assertEqual(new["base"], {"bytes": 0, "words": 0, "absent": True})
        self.assertEqual(new["head"], {"bytes": 9, "words": 2, "absent": False})
        self.assertEqual(data["frame"]["delta"], {"bytes": 0, "words": 0})

    def test_markdown_file_carries_both_shas_and_the_regeneration_command(self):
        output = Path(self.temporary.name) / "report.md"
        completed = self.report("--base", self.base, "--head", self.head, "--output", str(output))
        self.assertEqual((completed.returncode, completed.stdout), (0, ""), completed.stderr)
        text = output.read_text(encoding="utf-8")
        self.assertIn(f"`{self.base}`", text)
        self.assertIn(f"`{self.head}`", text)
        self.assertIn(f"just agent-instruction-load report --base {self.base} "
                      f"--head {self.head} --output <path>", text)
        self.assertIn("neither is a token count", text)
        for heading in ("## Frame", "## Hot totals", "## Conditional totals", "## Documents",
                        "## Members by profile", "### demo-reviewer"):
            self.assertIn(heading, text)
        lines = text.splitlines()
        self.assertIn("| demo | claude | 38 | 51 | +13 | 7 | 9 | +2 | yes | fixture entry |", lines)
        self.assertIn("| `demo/NEW.md` | claude, codex | absent | 9 | +9 | 0 | 2 | +2 |", lines)

    def test_the_output_is_a_function_of_the_two_shas(self):
        first = self.report("--base", self.base, "--head", self.head)
        (self.repo / "home/common/agent-skills/skills/demo/SKILL.md").write_bytes(b"dirty\n")
        second = self.report("--base", self.base, "--head", self.head)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(first.stdout.startswith("# Instruction load: "), first.stdout[:80])
        self.assertEqual(first.stdout, second.stdout)

    def test_the_model_is_read_at_head_not_from_the_working_tree(self):
        (self.repo / instruction_load.MODEL_PATH).write_text("{", encoding="utf-8")
        self.assertEqual(self.json_report()["head"], self.head)
        completed = self.report("--base", self.base, "--head", self.base)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(len(completed.stderr.splitlines()), 1, completed.stderr)
        self.assertIn(instruction_load.MODEL_PATH, completed.stderr)

    def test_an_unknown_revision_exits_2_and_writes_no_file(self):
        output = Path(self.temporary.name) / "never.md"
        completed = self.report("--base", "no-such-revision", "--head", self.head,
                                "--output", str(output))
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr.count("\n"), 1, completed.stderr)
        self.assertTrue(completed.stderr.startswith("agent-instruction-load: "))
        self.assertFalse(output.exists())

    def test_an_invalid_model_at_head_exits_2(self):
        model = fixture_model()
        del model["excluded_sites"]["demo-plugin"]
        broken = self.commit({instruction_load.MODEL_PATH: json.dumps(model).encode()}, "broken")
        completed = self.report("--base", self.base, "--head", broken)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("matrix site demo-plugin is in no profile", completed.stderr)
```

The fixture numbers come from `BASE_FILES` and `HEAD_FILES`. `demo/SKILL.md` goes
from 38 bytes and 7 words to 51 bytes and 9 words. `demo/NEW.md`, 9 bytes and 2
words, is absent at base. `solo/SKILL.md` is Claude-only.

- [ ] **Step 2: Run the test and watch it fail**

Run: `env PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py -k ReportCommandTest`
Expected: FAILED (failures=3, errors=3). The module has no `main` yet, so
every subprocess exits 0 with empty stdout and writes no file. The three
failures are the two exit-2 tests and
`test_the_output_is_a_function_of_the_two_shas`, at its `startswith` check.
The three errors are the two tests that end in `json.loads("")` and
`test_markdown_file_carries_both_shas_and_the_regeneration_command`, whose
`read_text` finds no file.

- [ ] **Step 3: Implement**

Add `REGENERATE`, `revision_reader`, `compare`, `render_markdown`,
`render_json`, a `_parser()` (`prog="agent-instruction-load"`, one required
`report` subcommand) and `main` to `IL`, following the Invariants. `main` is the
only function that catches: `ValueError` and `OSError` become the one-line exit 2.

In `justfile`, directly after the two `agent-model-matrix` recipe lines, add:

```make
# Compare the instruction documents each agent profile loads at two revisions (#155 D9).
agent-instruction-load *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.instruction_load {{args}}
```

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py`
Expected: OK, with 25 tests: 19 in `ModelCoreTest` and 6 in `ReportCommandTest`.

Run: `just --list`
Expected: one line for `agent-instruction-load *args`, with the comment above.

Run: `just agent-instruction-load report --base HEAD --head HEAD`
Expected: exit 2 and one stderr line starting
`agent-instruction-load: no home/common/agent-skills/instruction-load.json at `.
The live model arrives in Task 7.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/instruction_load.py home/common/agent-skills/tests/test_instruction_load.py justfile
git commit -m "feat(agent-tools): report instruction load across two revisions (#155)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Decision IDs: D8, D9, D14, D17, D26, D33.
