# Task 1: The shape fixture and the skill check

**Files:**
- Create: `tests/fixtures/guarded-command-shapes.json`
- Modify: `home/common/agent-skills/tests/test_shell_example_contracts.py`
- Test: `home/common/agent-skills/tests/test_shell_example_contracts.py`

No skill document changes in this task, and the source-tree sweep is Task 2's: at this
task's commit the skill text still breaks the new rules, so only fixture documents are
checked here.

**Interfaces:**
- Consumes: nothing from another task. From the suite itself: `_examples`, `_spans`,
  `_OpenFence`, `SANCTIONED_PREFIX`, `PLACEHOLDER`, `REPO_ROOT`, `SOURCE_TREES`,
  `swept_documents()`.
- Produces, for Task 2 (same file) and Task 3 (the fixture):
  - `tests/fixtures/guarded-command-shapes.json` with exactly the content in Step 1.
  - `GUARDED_SHAPES: dict` — the parsed fixture.
  - `GuardedFinding(line: int, rule: str, example: str)` — a `NamedTuple`.
  - `guarded_command_findings(document_text: str, shapes: dict, document_name: str) -> tuple[GuardedFinding, ...]`.
  - `ship_issue_documents() -> tuple[tuple[str, Path], ...]` — `(document name, path)` of every
    swept `.md` directly in the shared tree's `ship-issue/` directory.
  - `guarded_findings_report(document: str, findings) -> str` and the constants
    `GUARDED_ANCHOR`, `GUARDED_FORMS`, `GUARDED_POINTER`.

**Invariants:**
- `refused_examples`, `shell_fence_heads` and every existing test keep their results: the
  `_examples` payload only gains a third member, and existing readers index `payload[0]`
  and `payload[1]`.
- A concrete command is never stored in the fixture: a skill form holds a `template`, and a
  refused shape holds a form id plus the text before and after it (D6, D12).
- Findings come out in document order (R1 before R2 for one example), then R3 form
  findings in fixture order, then the R3 heading finding.
- No rule has an exemption (D4). A guarded verb is recognised only at the start of a living
  example, after the guard's own prefix literal.
- No new assertion pins an English phrase of a skill document.

The rules, R1 to R3, are the spec's "The skill check" section; D12 fixes what that
section left open.

- [ ] **Step 1: Create the fixture**

Write `tests/fixtures/guarded-command-shapes.json` with exactly this content (it is a
wire format two suites read; every verdict and reason fragment below was observed from
the guard source at the base commit):

```json
{
  "anchor": "`## gh hygiene`",
  "verbs": ["git push", "gh pr merge", "git branch -d"],
  "values": {
    "<branch>": "issue-351-topic",
    "<pr-num>": "351",
    "<resolved-repository>": "fagenorn/nix-config",
    "<rendered subject>": "feature (#351)"
  },
  "skill_forms": [
    {
      "id": "push.first",
      "template": "git push -u origin <branch>",
      "sites": ["SKILL.md"],
      "label": "push",
      "bare": {"exit": 0},
      "prefixed": {"exit": 0}
    },
    {
      "id": "push.later",
      "template": "git push origin <branch>",
      "sites": ["REVIEW.md", "POST-SELECTION-SYNC.md"],
      "label": "push",
      "bare": {"exit": 0},
      "prefixed": {"exit": 0}
    },
    {
      "id": "merge.subject",
      "template": "gh pr merge <pr-num> --repo <resolved-repository> --merge --subject \"<rendered subject>\" --delete-branch",
      "sites": ["SKILL.md"],
      "label": "merge",
      "bare": {"exit": 0},
      "prefixed": {"exit": 0}
    },
    {
      "id": "merge.plain",
      "template": "gh pr merge <pr-num> --repo <resolved-repository> --merge --delete-branch",
      "sites": [],
      "label": "merge",
      "bare": {"exit": 0},
      "prefixed": {"exit": 0}
    },
    {
      "id": "branch.local",
      "template": "git branch -d <branch>",
      "sites": ["SKILL.md", "HUMAN-GATE.md"],
      "label": "branch deletion",
      "bare": {"exit": 0},
      "prefixed": {"exit": 2, "reason": "forbidden raw command character"}
    },
    {
      "id": "branch.remote",
      "template": "git push origin --delete <branch>",
      "sites": ["SKILL.md", "HUMAN-GATE.md"],
      "label": "push",
      "bare": {"exit": 2, "reason": "expected exactly git push [-u] origin <branch>"},
      "prefixed": {"exit": 2, "reason": "expected exactly git push [-u] origin <branch>"}
    }
  ],
  "refused_shapes": [
    {"id": "push.redirect-pipe", "form": "push.first", "before": "", "after": " 2>&1 | tail -3",
     "label": "push", "reason": "forbidden raw command character"},
    {"id": "push.env-wrapper", "form": "push.first", "before": "env -u GITHUB_TOKEN ", "after": "",
     "label": "push", "reason": "not in a command position"},
    {"id": "merge.env-wrapper", "form": "merge.subject", "before": "env -u GITHUB_TOKEN ", "after": "",
     "label": "merge", "reason": "not in a command position"},
    {"id": "merge.after-cd", "form": "merge.subject", "before": "cd /tmp/worktree && ", "after": "",
     "label": "merge", "reason": "does not match the guarded merge grammar"},
    {"id": "merge.then-echo", "form": "merge.plain", "before": "", "after": "; echo exit=$?",
     "label": "merge", "reason": "does not match the guarded merge grammar"},
    {"id": "mention.unquoted", "form": "push.later", "before": "workflow-state finish --notes refused ", "after": "",
     "label": "push", "reason": "not in a command position"},
    {"id": "branch.after-cd", "form": "branch.local", "before": "cd /tmp/worktree && ", "after": "",
     "label": "branch deletion", "reason": "forbidden raw command character"}
  ]
}
```

Key meanings: `anchor` is the token a citing block must contain, and without its
backticks it is the heading line `SKILL.md` must hold once. `verbs` are the guarded
verbs R1 looks for. `values` turn a template into a concrete command for the guard
suite. For a skill form, `sites` are the `ship-issue` documents that must carry it,
`label` is the word the guard prints after `lifecycle guard: unsafe `, and `bare` and
`prefixed` are the verdicts of the command alone and behind `unset GITHUB_TOKEN && `.
A refused shape's command is `before` + its form's concrete command + `after`.

- [ ] **Step 2: Write the failing tests**

In `home/common/agent-skills/tests/test_shell_example_contracts.py`, insert this block
immediately before the line `ORCHESTRATE_SKILL = SOURCE_TREES["claude-only"] / "orchestrate-issues/SKILL.md"`:

```python
GUARDED_ANCHOR = GUARDED_SHAPES["anchor"]
GUARDED_FORMS = {form["id"]: form["template"] for form in GUARDED_SHAPES["skill_forms"]}
GUARDED_POINTER = "see ship-issue/SKILL.md, ## gh hygiene"


def guarded_findings_report(document, findings):
    lines = [f"{document}:{f.line}: {f.rule}: {f.example}" for f in findings]
    return "\n".join(lines + [GUARDED_POINTER])


def _conforming(name):
    """The smallest document called `name` that meets R1, R2 and R3."""
    blocks = [GUARDED_ANCHOR.strip("`")] if name == "SKILL.md" else []
    blocks += [f"Run `{form['template']}` ({GUARDED_ANCHOR})."
               for form in GUARDED_SHAPES["skill_forms"] if name in form["sites"]]
    return "\n\n".join(blocks) + "\n"


def _guarded(document, name="OTHER.md"):
    return [tuple(f) for f in guarded_command_findings(document, GUARDED_SHAPES, name)]


class GuardedCommandShapeTest(unittest.TestCase):
    """#351: every guarded command in ship-issue/ is a listed form that cites the rule."""

    def test_the_fixture_is_well_formed(self):
        verbs = [verb.split() for verb in GUARDED_SHAPES["verbs"]]
        documents = {name for name, _ in ship_issue_documents()}
        self.assertEqual(len(GUARDED_FORMS), len(GUARDED_SHAPES["skill_forms"]))
        sited = set()
        for form in GUARDED_SHAPES["skill_forms"]:
            with self.subTest(form=form["id"]):
                words = form["template"].split()
                self.assertTrue(any(words[:len(verb)] == verb for verb in verbs))
                self.assertLessEqual(set(PLACEHOLDER.findall(form["template"])),
                                     set(GUARDED_SHAPES["values"]))
                self.assertLessEqual(set(form["sites"]), documents)
                sited.update(form["sites"])
        self.assertIn("SKILL.md", sited)
        for shape in GUARDED_SHAPES["refused_shapes"]:
            with self.subTest(shape=shape["id"]):
                self.assertIn(shape["form"], GUARDED_FORMS)
                self.assertTrue(shape["before"] or shape["after"])

    def test_conforming_documents_yield_nothing(self):
        for name in ("SKILL.md", "REVIEW.md", "POST-SELECTION-SYNC.md", "HUMAN-GATE.md",
                     "OTHER.md"):
            with self.subTest(document=name):
                self.assertEqual(_guarded(_conforming(name), name), [])

    def test_each_failure_class_is_found(self):
        first, later = GUARDED_FORMS["push.first"], GUARDED_FORMS["push.later"]
        merge = GUARDED_FORMS["merge.subject"]
        cases = {
            "a push with no citation in its block":
                ("OTHER.md", f"Run `{first}`.", [(1, "R2", first)]),
            "a merge fence with no citation in its lead-in":
                ("OTHER.md", f"Merge it:\n\n```\n{merge}\n```", [(4, "R2", merge)]),
            "a remote-less push":
                ("OTHER.md", f"Run `git push` ({GUARDED_ANCHOR}).", [(1, "R1", "git push")]),
            "a push carrying a redirection":
                ("OTHER.md", f"Run `{first} 2>&1` ({GUARDED_ANCHOR}).",
                 [(1, "R1", f"{first} 2>&1")]),
            "a site with its form removed":
                ("REVIEW.md", "Nothing is pushed here.", [(0, "R3", later)]),
            # ship-issue/REVIEW.md's fix step 4, verbatim at 02d2f378.
            "REVIEW.md with only the remote-less push":
                ("REVIEW.md",
                 "4. Run `check-launch` (SKILL.md's `## Launch guard`); on anything but "
                 "`current: true`, stop without\n   pushing and take the no-write stop. "
                 "Then `git push`.",
                 [(2, "R1", "git push"), (2, "R2", "git push"), (0, "R3", later)]),
            "a bare verb named in a span":
                ("OTHER.md", "`gh pr merge` runs local post-merge steps.",
                 [(1, "R1", "gh pr merge"), (1, "R2", "gh pr merge")]),
            "a citation in another block":
                ("OTHER.md", f"See {GUARDED_ANCHOR}.\n\nRun `{later}`.", [(3, "R2", later)]),
            "a citation in another list item":
                ("OTHER.md", f"- shape: {GUARDED_ANCHOR};\n- `{later}`.", [(2, "R2", later)]),
            "a fence introduced only by an earlier fence's lead-in":
                ("OTHER.md",
                 f"Then ({GUARDED_ANCHOR}):\n\n```\ngit status\n```\n\n```\n{later}\n```",
                 [(8, "R2", later)]),
            "SKILL.md without the anchor's heading":
                ("SKILL.md", _conforming("SKILL.md").split("\n", 1)[1],
                 [(0, "R3", "## gh hygiene")]),
            "SKILL.md with the anchor's heading twice":
                ("SKILL.md", _conforming("SKILL.md") + "\n## gh hygiene\n",
                 [(0, "R3", "## gh hygiene")]),
        }
        for name, (document_name, text, expected) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(_guarded(text, document_name), expected)

    def test_accepted_spellings_yield_nothing(self):
        later = GUARDED_FORMS["push.later"]
        merge = GUARDED_FORMS["merge.subject"]
        cases = {
            "the sanctioned prefix before a form":
                f"Run `{SANCTIONED_PREFIX}{later}` ({GUARDED_ANCHOR}).",
            "a citation wrapped across lines of the block":
                f"Then `{later}` (`## gh\nhygiene`).",
            "a fence cited by its lead-in":
                f"Then ({GUARDED_ANCHOR}):\n\n```\n{merge}\n```",
            "a list-item fence cited by its item":
                f"2. Clean up ({GUARDED_ANCHOR}):\n   ```\n   git worktree prune\n"
                f"   {GUARDED_FORMS['branch.local']}\n   ```",
            "a quoted mention inside another command": "Run `rg -n 'git branch -d' docs/`.",
            "a guarded verb in prose": "The merge runs alone; so does git push.",
            "a diagram line in a bare fence": f"```\n7. Merge → {merge}\n```",
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                self.assertEqual(_guarded(text), [])

    def test_a_finding_report_names_document_line_rule_and_example(self):
        findings = guarded_command_findings("Run `git push`.", GUARDED_SHAPES, "OTHER.md")
        self.assertEqual(
            guarded_findings_report("ship-issue/OTHER.md", findings),
            "ship-issue/OTHER.md:1: R1: git push\nship-issue/OTHER.md:1: R2: git push\n"
            + GUARDED_POINTER)
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: the module fails to load with `NameError: name 'GUARDED_SHAPES' is not defined`.

- [ ] **Step 4: Write the implementation**

All in the same test file.

1. Add `import json` to the imports, between `from dataclasses import dataclass` and
   `from pathlib import Path`.
2. Give every example its block. `_OpenFence` gains a last field `lead: str`, commented
   `# the prose block that introduces the fence, "" when none does`. In `_examples`:
   - keep a local `lead = ""`, commented `# the last prose block since a fence closed`;
   - `flushed()` declares `nonlocal lead`, and when `block` is not empty sets `lead` to the
     block's stripped lines joined by a newline before it yields; each span it yields carries
     the payload `(call, False, lead)`;
   - a fence opener stores the current `lead` in its `_OpenFence`;
   - each call of a closed fence carries the payload
     the existing `_Example.joined(…)` value, then `shell`, then `closed.lead`;
   - after a fence closes and no fence is still open, `lead` is reset to `""`, so a second
     fence with no prose of its own has no block (D12).
   Rewrite the payload sentence of `_examples`' docstring to say that a `"call"` carries the
   `_Example`, whether a shell fence holds it, and the text of its block: a span's own
   prose block, or for a fence call the last prose block since the previous fence closed.
3. Insert this block immediately before `def swept_documents():`. It is given in full
   because the tests assert the order of its findings:

```python
GUARDED_SHAPES = json.loads(
    (REPO_ROOT / "tests/fixtures/guarded-command-shapes.json").read_text(encoding="utf-8"))
SHIP_ISSUE_DIRECTORY = "ship-issue"


class GuardedFinding(NamedTuple):
    line: int  # 0 for a finding about the whole document
    rule: str  # "R1", "R2" or "R3"
    example: str


def _squeezed(text):
    return " ".join(text.split())


def guarded_command_findings(document_text, shapes, document_name):
    """Every R1, R2 and R3 finding of one ship-issue document (#351).

    R1: a living example that begins with a guarded verb, after the sanctioned
    prefix, is one of `shapes`' skill-form templates. R2: its block carries the
    anchor. R3: every form listing `document_name` as a site appears there
    meeting R1 and R2, and SKILL.md holds the anchor's heading exactly once.
    """
    anchor = shapes["anchor"]
    verbs = [verb.split() for verb in shapes["verbs"]]
    templates = {form["template"] for form in shapes["skill_forms"]}
    findings, satisfied = [], set()
    for position, kind, payload in sorted(_examples(document_text), key=lambda e: e[0]):
        if kind != "call":
            continue
        command = _squeezed(payload[0].text)
        if command.startswith(SANCTIONED_PREFIX):
            command = command[len(SANCTIONED_PREFIX):]
        words = command.split()
        if not any(words[:len(verb)] == verb for verb in verbs):
            continue
        line = position[0]
        listed = command in templates
        cited = anchor in _squeezed(payload[2])
        if not listed:
            findings.append(GuardedFinding(line, "R1", command))
        if not cited:
            findings.append(GuardedFinding(line, "R2", command))
        if listed and cited:
            satisfied.add(command)
    for form in shapes["skill_forms"]:
        if document_name in form["sites"] and form["template"] not in satisfied:
            findings.append(GuardedFinding(0, "R3", form["template"]))
    if document_name == "SKILL.md":
        heading = anchor.strip("`")
        if document_text.splitlines().count(heading) != 1:
            findings.append(GuardedFinding(0, "R3", heading))
    return tuple(findings)


def ship_issue_documents():
    """(document name, path) of every swept document directly in ship-issue/."""
    return tuple(
        (Path(relative).name, SOURCE_TREES[tree] / relative)
        for tree, relative in swept_documents()
        if tree == "shared" and Path(relative).parts[:-1] == (SHIP_ISSUE_DIRECTORY,))
```

4. Replace the last paragraph of the module docstring (the one that begins
   `refused_examples(document_text)` followed by "is the one boundary") with:

```text
`refused_examples(document_text)` is the boundary for refused forms: every form
sweep and form fixture below calls it on a document's text.
`guarded_command_findings(document_text, shapes, document_name)` is the boundary
for the commands the lifecycle guard adjudicates in ship-issue (#351): a living
example that begins with one of the fixture's verbs must be a form listed in
tests/fixtures/guarded-command-shapes.json, and its block must carry the
fixture's anchor. Nothing else produces findings.
```

- [ ] **Step 5: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: `Ran 32 tests`, `OK (skipped=1)` — the 27 tests of the base file and the 5 new ones.

Then prove the new tests can fail. In the fixture, change `push.later`'s `sites` to `[]`
and run
`env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py -k GuardedCommandShapeTest`.
Expected: `test_each_failure_class_is_found` fails in the two `REVIEW.md` cases (no `R3`
finding). Undo that edit so the fixture again equals Step 1's content, and rerun the first command
to the same `Ran 32 tests`, `OK (skipped=1)`.

Scope check: `git status --short` lists exactly the two files of this task.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/guarded-command-shapes.json home/common/agent-skills/tests/test_shell_example_contracts.py
git commit -m "test(skills): check ship-issue's guarded commands against a shape fixture (#351)"
```
