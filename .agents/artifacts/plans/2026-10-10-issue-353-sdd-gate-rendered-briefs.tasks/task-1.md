# Task 1: Prompt-body rendering and tokenized templates

**Files:**
- Create: `python/agent_tools/sdd_brief.py`
- Create: `tests/test_sdd_brief.py`
- Modify: `home/common/agent-skills/skills/sdd/implementer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`
- Modify: `justfile` (one line in the `agent-workflow-tests` recipe)
- Test: `tests/test_sdd_brief.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces, in `agent_tools.sdd_brief`:
  - `TOKEN: re.Pattern[str]` — `re.compile(r"\[[A-Z0-9_]+\]")`.
  - `IMPLEMENTER_TEMPLATE = "implementer-prompt.md"`, `REVIEWER_TEMPLATE = "task-reviewer-prompt.md"`.
  - `IMPLEMENTER_TOKENS: frozenset[str]`, `REVIEWER_TOKENS: frozenset[str]` — the two closed sets written out in the test below.
  - `OPTIONAL_TOKENS: frozenset[str]` — `{"[CONTEXT]", "[LIFECYCLE_WORKER]"}`.
  - `class BriefError(Exception)` — a template, plan header or standards layer a brief cannot be rendered from; its message is one line.
  - `prompt_body(template_text: str) -> str`
  - `render(template_text: str, tokens: frozenset[str], values: Mapping[str, str]) -> str`
- Produces, in the two shipped templates: a prompt body whose `TOKEN` matches are exactly `IMPLEMENTER_TOKENS` and `REVIEWER_TOKENS`.

**Invariants (spec "Rendering", D5, D12):**
- `prompt_body` reads the same region `_fence_region` in `home/common/agent-skills/tests/test_dispatch_contracts.py` reads: the one unlabeled fenced block, the lines after its one `prompt: |` line.
- Every byte of a rendered brief outside a token is the template's byte; nothing is prepended or appended.
- All tokens are replaced in one pass. A value is inserted byte for byte and never scanned for tokens.
- The token check is made on the template body before filling: the set of `TOKEN` matches in the body must equal `tokens` (D12).
- Only a token in `OPTIONAL_TOKENS` may have an empty value.
- The module imports nothing outside the standard library and has no `__file__` lookup.
- The dispatch markers, the `Agent(...)` lines, the four leaf-agent clauses and every other byte of both templates outside the edits below are unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sdd_brief.py`:

```python
"""Rendering contract of `agent_tools.sdd_brief` (issue 353, spec D5).

The rendering functions are imported (agent-helpers rule 5). The shipped
templates are rendered and compared with a body this file derives on its own;
no test holds a copy of their prose (rule 6).
"""
from __future__ import annotations

from pathlib import Path
import unittest

from agent_tools import sdd_brief
from agent_tools.sdd_brief import BriefError

REPO_ROOT = Path(__file__).resolve().parents[1]
SDD = REPO_ROOT / "home/common/agent-skills/skills/sdd"
TOKENS = frozenset({"[BRIEF_FILE]", "[CONTEXT]", "[REPORT_FILE]"})
VALUES = {"[BRIEF_FILE]": "/w/brief.md", "[REPORT_FILE]": "/w/report.md", "[CONTEXT]": "ctx"}
HEADER = ("Subagent:", '  description: "x"', "  prompt: |")
BODY = ("    Read [BRIEF_FILE] then [REPORT_FILE].", "", "    [CONTEXT]", "   ",
        "    Verdict: [Approved | Needs fixes]", "      indented")
RENDERED = ("Read /w/brief.md then /w/report.md.\n\nctx\n\n"
            "Verdict: [Approved | Needs fixes]\n  indented\n")


def template(*body, header=HEADER):
    return "\n".join(["# Fixture", "", "Outside [NOT_A_SLOT].", "", "```", *header, *body,
                      "```", "", "After.", ""])


def independent_body(text):
    """The fence lines after `prompt: |`, their first four characters removed (spec seam 2)."""
    lines = text.split("\n")
    opening, closing = [i for i, line in enumerate(lines) if line.startswith("```")]
    start = next(i for i in range(opening, closing) if lines[i].strip() == "prompt: |")
    return "\n".join(line[4:] for line in lines[start + 1:closing]) + "\n"


class RenderTest(unittest.TestCase):
    def test_the_body_is_dedented_and_filled(self):
        self.assertEqual(sdd_brief.render(template(*BODY), TOKENS, VALUES), RENDERED)

    def test_prompt_body_keeps_the_tokens(self):
        self.assertEqual(
            sdd_brief.prompt_body(template(*BODY)),
            "Read [BRIEF_FILE] then [REPORT_FILE].\n\n[CONTEXT]\n\n"
            "Verdict: [Approved | Needs fixes]\n  indented\n")

    def test_a_value_is_inserted_verbatim_and_never_rescanned(self):
        values = {**VALUES, "[BRIEF_FILE]": "[REPORT_FILE] \\1 $x", "[CONTEXT]": "a\n[BRIEF_FILE]"}
        self.assertEqual(
            sdd_brief.render(template(*BODY), TOKENS, values),
            "Read [REPORT_FILE] \\1 $x then /w/report.md.\n\na\n[BRIEF_FILE]\n\n"
            "Verdict: [Approved | Needs fixes]\n  indented\n")

    def test_an_empty_optional_value_removes_its_line_and_the_empty_line_after(self):
        self.assertEqual(
            sdd_brief.render(template(*BODY), TOKENS, {**VALUES, "[CONTEXT]": ""}),
            "Read /w/brief.md then /w/report.md.\n\nVerdict: [Approved | Needs fixes]\n  indented\n")

    def test_an_empty_optional_value_keeps_a_following_text_line(self):
        body = ("    [CONTEXT]", "    Read [BRIEF_FILE] then [REPORT_FILE].")
        self.assertEqual(
            sdd_brief.render(template(*body), TOKENS, {**VALUES, "[CONTEXT]": ""}),
            "Read /w/brief.md then /w/report.md.\n")

    def test_a_labeled_fence_is_not_the_prompt(self):
        text = template(*BODY) + "\n```python\nprint('[ZED]')\n```\n"
        self.assertEqual(sdd_brief.render(text, TOKENS, VALUES), RENDERED)

    def test_every_other_shape_is_refused(self):
        good = template(*BODY)
        cases = {
            "no fence": ("# T\n\nno fence\n", TOKENS, VALUES),
            "two unlabeled fences": (good + "\n```\nmore\n```\n", TOKENS, VALUES),
            "unclosed fence": (good.replace("```\n\nAfter.\n", "\nAfter.\n"), TOKENS, VALUES),
            "no prompt line": (template(*BODY, header=("Subagent:",)), TOKENS, VALUES),
            "two prompt lines": (template("    prompt: |", *BODY), TOKENS, VALUES),
            "under-indented line": (template(*BODY, "  short"), TOKENS, VALUES),
            "last body line empty": (template(*BODY, ""), TOKENS, VALUES),
            "unknown token": (template(*BODY, "    [ZED]"), TOKENS, VALUES),
            "token missing from the template": (
                good, TOKENS | {"[BASE_SHA]"}, {**VALUES, "[BASE_SHA]": "x"}),
            "value missing": (good, TOKENS, {"[BRIEF_FILE]": "b", "[CONTEXT]": "c"}),
            "extra value": (good, TOKENS, {**VALUES, "[ZED]": "z"}),
            "empty required value": (good, TOKENS, {**VALUES, "[BRIEF_FILE]": ""}),
            "optional token sharing its line": (
                template("    Read [BRIEF_FILE] then [REPORT_FILE].", "    Context: [CONTEXT]"),
                TOKENS, VALUES),
        }
        for name, (text, tokens, values) in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(BriefError):
                    sdd_brief.render(text, tokens, values)


class ShippedTemplateTest(unittest.TestCase):
    def test_the_token_sets_are_the_spec_table(self):
        plan = {"[PLAN_ROOT]", "[PLAN_ROOT_BYTES]", "[PLAN_TOTAL_BYTES]", "[PLAN_FILE_COUNT]",
                "[PLAN_LARGEST_MEMBER_BYTES]"}
        both = plan | {"[BRIEF_FILE]", "[REPORT_FILE]", "[GLOBAL_CONSTRAINTS]", "[STANDARDS]",
                       "[STACKS_DIR]"}
        self.assertEqual(sdd_brief.IMPLEMENTER_TOKENS, both | {
            "[TASK_NUMBER]", "[TASK_NAME]", "[CONTEXT]", "[TEST_SEAMS]", "[LIFECYCLE_WORKER]"})
        self.assertEqual(sdd_brief.REVIEWER_TOKENS, both | {
            "[BASE_SHA]", "[HEAD_SHA]", "[MANIFEST_ROOT]", "[ROOT_BYTES]", "[TOTAL_BYTES]",
            "[FILE_COUNT]", "[LARGEST_MEMBER_BYTES]"})
        self.assertEqual(sdd_brief.OPTIONAL_TOKENS, {"[CONTEXT]", "[LIFECYCLE_WORKER]"})

    def test_filling_each_token_with_itself_reproduces_the_prompt_body(self):
        for name, tokens in ((sdd_brief.IMPLEMENTER_TEMPLATE, sdd_brief.IMPLEMENTER_TOKENS),
                             (sdd_brief.REVIEWER_TEMPLATE, sdd_brief.REVIEWER_TOKENS)):
            with self.subTest(template=name):
                text = (SDD / name).read_text(encoding="utf-8")
                self.assertEqual(sdd_brief.render(text, tokens, {token: token for token in tokens}),
                                 independent_body(text))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_sdd_brief.py`
Expected: one ERROR — `ModuleNotFoundError: No module named 'agent_tools.sdd_brief'`.

- [ ] **Step 3: Write `python/agent_tools/sdd_brief.py`**

The constants and the two functions under **Interfaces**. Decisions the code must embody:

`prompt_body(template_text)`:
1. Walk `template_text.splitlines()`. A line starting with three backticks opens a block when none is open (its info string is the rest of the line, stripped) and closes the open one otherwise. A block is unlabeled when its info string is empty.
2. Refuse (`BriefError`) unless exactly one unlabeled block exists and it is closed. A labeled block is skipped, whatever it holds.
3. Inside that block, refuse unless exactly one line satisfies `line.strip() == "prompt: |"`. The body lines are the block's lines after it.
4. A body line with `line.strip() == ""` becomes `""`. Any other body line must start with four spaces, which are removed; otherwise refuse, naming the line's number within the block.
5. Refuse when there is no body line or the last body line is empty. Return the lines joined with `"\n"` plus one final `"\n"`.

`render(template_text, tokens, values)`:
1. `body = prompt_body(template_text)`. Refuse as template drift unless `set(TOKEN.findall(body)) == tokens`, naming the sorted tokens present in only one of the two sets.
2. Refuse unless `set(values) == tokens`.
3. For each token of `tokens & OPTIONAL_TOKENS`: refuse unless the token occurs exactly once in the body and that occurrence is a whole line (`line == token`). This holds whether or not its value is empty.
4. Refuse when a token outside `OPTIONAL_TOKENS` has the value `""`.
5. For each optional token whose value is `""`: delete its line and, when the body line after it is `""`, that line too. Work on the body's lines: the final newline is not a line and is never deleted.
6. Replace every token in one pass: `TOKEN.sub(lambda match: values[match.group(0)], text)`. A function argument is required: a string replacement would interpret backslashes in a value.

Write the module docstring and the two function docstrings from the code you implemented: each says which region of a template is the prompt body, what is refused, and that values are never rescanned. Do not restate the spec's prose.

- [ ] **Step 4: Run the test: rendering green, shipped templates red**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_sdd_brief.py`
Expected: `RenderTest` passes (7 tests) and `ShippedTemplateTest.test_the_token_sets_are_the_spec_table` passes; `test_filling_each_token_with_itself_reproduces_the_prompt_body` fails for both templates with `BriefError` naming tokens such as `[TASK_NUMBER]` and `[STANDARDS]` that the shipped templates do not hold yet.

- [ ] **Step 5: Edit the two templates**

Apply these six edits exactly. Each "replace" text is the file's current text at the base; the indentation is part of it.

**Edit 1** — in `home/common/agent-skills/skills/sdd/implementer-prompt.md`, replace this text, which occurs exactly once:

````text
    You are implementing Task N: [task name]
````

with:

````text
    You are implementing Task [TASK_NUMBER]: [TASK_NAME]
````

**Edit 2** — in `home/common/agent-skills/skills/sdd/implementer-prompt.md`, replace this text, which occurs exactly once:

````text
    [Scene-setting: where this fits, interfaces and decisions from earlier
    tasks, the plan's Global Constraints, and the plan's agreed test seams]
````

with:

````text
    [CONTEXT]

    Plan root: [PLAN_ROOT] ([PLAN_ROOT_BYTES], [PLAN_TOTAL_BYTES], [PLAN_FILE_COUNT], [PLAN_LARGEST_MEMBER_BYTES])

    Global Constraints:
    [GLOBAL_CONSTRAINTS]

    Test seams:
    [TEST_SEAMS]

    ## Standards

    Your work is held to the documents below; the most specific layer wins.

    [STANDARDS]

    Also read the stack document under [STACKS_DIR] that matches the file
    types you touch.
````

**Edit 3** — in `home/common/agent-skills/skills/sdd/implementer-prompt.md`, replace this text, which occurs exactly once:

````text
    ## Lifecycle Worker

    Only when
````

with:

````text
    ## Lifecycle Worker

    [LIFECYCLE_WORKER]

    Only when
````

**Edit 4** — in `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`, replace this text, which occurs exactly once:

````text
    Read the task brief: [BRIEF_FILE]
````

with:

````text
    Read the task brief: [BRIEF_FILE]
    Plan root: [PLAN_ROOT] ([PLAN_ROOT_BYTES], [PLAN_TOTAL_BYTES], [PLAN_FILE_COUNT], [PLAN_LARGEST_MEMBER_BYTES])
````

**Edit 5** — in `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`, replace this text, which occurs exactly once:

````text
    ## Calibration
````

with:

````text
    ## Standards

    The code under review is held to the documents below; the most specific
    layer wins.

    [STANDARDS]

    Also read the stack document under [STACKS_DIR] that matches the file
    types in the diff.

    ## Calibration
````

**Edit 6** — in `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`, replace this text, which occurs exactly once:

````text
**Placeholders:**
- `[BRIEF_FILE]` — REQUIRED: the task brief file (`scripts/task-brief PLAN N`)
- `[GLOBAL_CONSTRAINTS]` — the binding requirements copied verbatim from the
  plan's Global Constraints or the spec: exact values, formats, and stated
  relationships between components (not process rules)
- `[REPORT_FILE]` — REQUIRED: the implementer's report file
- `[BASE_SHA]` — commit before this task
- `[HEAD_SHA]` — current commit
- `[MANIFEST_ROOT]` and `[ROOT_BYTES]`, `[TOTAL_BYTES]`,
  `[FILE_COUNT]`, `[LARGEST_MEMBER_BYTES]` — REQUIRED: the manifest root path
  and all four metrics from the validated producer report
````

with:

````text
**Placeholders:** every bracketed capital token above is filled before dispatch.
````

Edit 6's sentence names no command on purpose: until Task 5 the owner still fills the tokens by hand, and Task 5 rewrites this line to name `sdd-gate review`.

- [ ] **Step 6: Add the suite to the workflow recipe**

In `justfile`, recipe `agent-workflow-tests`, add the line `    tests/test_sdd_brief.py \` directly after the line `    tests/test_lane_triage.py \`.

- [ ] **Step 7: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_sdd_brief.py`
Expected: `OK`, 9 tests, no warnings.

Run: `wc -c home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/sdd/implementer-prompt.md home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`
Expected: `21844`, `6837`, `7452`, total `36133`. A different figure means an edit was not applied exactly: fix the edit, not the expectation.

Run: `just agent-instruction-budget`
Expected: exactly `check: pass`, with no `ceiling:`, `tightness:`, `lint:` or `raise:` line. If it fails, follow the plan root's "Instruction budget" section.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py`
Expected: `OK` (skips allowed). These suites read the templates' markers, carrier clauses and machine text.

Run: `just build` (timeout 3600 s)
Expected: exit 0. The package build import-checks every module under `python/agent_tools`, the new one included.

Run: `git diff --stat cd4b1746e5a844a17f806ccf791e6840e26d4cb2 -- home/common/agent-skills/skills python/agent_tools justfile tests/test_sdd_brief.py`
Expected: exactly the five files under **Files**.

- [ ] **Step 8: Commit**

```bash
git add python/agent_tools/sdd_brief.py tests/test_sdd_brief.py justfile home/common/agent-skills/skills/sdd/implementer-prompt.md home/common/agent-skills/skills/sdd/task-reviewer-prompt.md
git commit -m "feat(issue-353): render a dispatch brief from a template's prompt body"
```
