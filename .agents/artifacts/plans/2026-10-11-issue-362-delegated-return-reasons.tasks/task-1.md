# Task 1: State the two reasons in the `delegate` action, paid for by two cuts

Issue: https://github.com/fagenorn/nix-config/issues/362. Spec: `.agents/artifacts/specs/2026-10-11-issue-362-delegated-return-reasons-design.md` (`## Decisions`: "The two reasons, and where each attaches", "Paying for the bytes"; ledger rows D1, D2, D10).

Background for a reader with no context. `home/common/agent-skills/skills/from-issue/SKILL.md` is the instruction text an issue-owning agent follows. Its `delegate` action (item 4 under `**Executable phase gate.**`) says what a delegating owner does when the fresh owner it launched comes back. The first return case tells it to relay three kinds of return and do nothing else, but not why that is safe. This task adds the two reasons as two parentheses in that case, and deletes two clauses elsewhere in the same file that only restate their own sentence, so the file's byte count does not move. The byte count matters: the Instruction Budget gate (`just agent-instruction-budget`) measures the UTF-8 bytes of the documents each agent profile loads, this file is loaded by three profiles, and the tightest has 71 bytes free. Raising a ceiling needs a label only the user may apply.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Test: none added. Existing: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: nothing from another task.
- Produces: the committed text of `SKILL.md` that Task 2 grades. Task 2 relies on these two strings each occurring exactly once in it: ` line (the delegated owner already reaped before its own exit), or bytes valid at ` and `` `terminal_failed` (these alone mean it already ended the launch itself): relay it, ``.

**Invariants:**
- `SKILL.md` has the same number of bytes after the edit as before (30409 at `96174d0e`).
- `git diff --numstat` for the file shows exactly `3	3`: three lines changed, none added or removed.
- In the `delegate` action nothing changes except the two added parentheses: the order of the three return cases, the labels `(a)`, `(b)`, `(c)`, the boundary names `--boundary workflow-response` and `--boundary ship-handoff`, the `workflow-state progress` call and the instruction "relay it, write nothing and stop, with no reap" stay byte for byte.
- The two deletions remove only these: the tail `` , whether the rejection meant a suspension or the `stopped(stalled)` bound `` of the paragraph on a rejected `workflow-state progress` call, and the sentence ` Suspension is NOT a terminal return.` that ends the suspension procedure's last paragraph.
- No other file changes. No ceiling in `home/common/agent-skills/instruction-load.json` changes.

The script below is the whole edit. `check` reports whether the edit is in place; `apply` makes it, and writes nothing unless each old string occurs exactly once and the byte count is unchanged.

```python
# begin edit
"""Issue 362: state the two reasons in the delegate action, paid for by two cuts.

usage: edit.py check | apply   (run from the worktree root)
"""
import pathlib
import sys

PATH = pathlib.Path("home/common/agent-skills/skills/from-issue/SKILL.md")

# (old, new): each old occurs exactly once before the edit.
EDITS = (
    (
        " line, or bytes valid at `--boundary workflow-response` as `terminal` or"
        " `terminal_failed`: relay it, write nothing and stop, with no reap;",
        " line (the delegated owner already reaped before its own exit), or bytes"
        " valid at `--boundary workflow-response` as `terminal` or `terminal_failed`"
        " (these alone mean it already ended the launch itself): relay it, write"
        " nothing and stop, with no reap;",
    ),
    (
        " and stop, writing no `finish`, whether the rejection meant a suspension"
        " or the `stopped(stalled)` bound.",
        " and stop, writing no `finish`.",
    ),
    (
        "emit no result JSON. Suspension is NOT a terminal return.",
        "emit no result JSON.",
    ),
)
PRESENT = (
    " line (the delegated owner already reaped before its own exit), or bytes valid at ",
    "`terminal_failed` (these alone mean it already ended the launch itself): relay it,",
    " and stop, writing no `finish`.",
    "make no `finish` call and emit no result JSON.",
)
ABSENT = (
    "whether the rejection meant a suspension",
    "Suspension is NOT a terminal return",
)


def main(mode: str) -> int:
    text = PATH.read_bytes().decode("utf-8")
    if mode == "apply":
        before = len(text.encode("utf-8"))
        for old, new in EDITS:
            if text.count(old) != 1:
                print(f"apply: expected one match, found {text.count(old)}: {old[:50]!r}")
                return 1
            text = text.replace(old, new)
        after = len(text.encode("utf-8"))
        if after != before:
            print(f"apply: not byte-neutral: {before} -> {after}; nothing written")
            return 1
        PATH.write_bytes(text.encode("utf-8"))
        print(f"apply: {before} -> {after} bytes")
    elif mode != "check":
        print(__doc__)
        return 2
    problems = [f"missing or repeated: {s!r}" for s in PRESENT if text.count(s) != 1]
    problems += [f"still present: {s!r}" for s in ABSENT if s in text]
    for line in problems:
        print(line)
    print("check: fail" if problems else "check: pass")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) == 2 else ""))
# end edit
```

In every command below, `SCRATCH` is your scratch directory (Global Constraints) and `TASK` is `.agents/artifacts/plans/2026-10-11-issue-362-delegated-return-reasons.tasks/task-1.md`.

- [ ] **Step 1: Extract the script and watch the check fail**

Run:

```bash
block() { sed -n "/^# begin $1\$/,/^# end $1\$/p" "$2" | sed '1d;$d'; }
block edit "$TASK" > "$SCRATCH/edit.py"
python3 "$SCRATCH/edit.py" check
```

Expected: exit 1. Three `missing or repeated:` lines, two `still present:` lines, then `check: fail`. (The fourth `PRESENT` string is already in the file and stays.)

- [ ] **Step 2: Apply the edit**

Run: `python3 "$SCRATCH/edit.py" apply`
Expected: `apply: 30409 -> 30409 bytes`, then `check: pass`, exit 0. Both numbers are equal whatever they are; `30409` is the count at `96174d0e`.

If it prints `apply: expected one match, found …`, the file is not the text this plan was written against (a sync with `main` changed one of the three sentences). Nothing was written. Stop and report BLOCKED with that line; do not edit the file by hand.

- [ ] **Step 3: Verify the edit and its shape**

Run:

```bash
python3 "$SCRATCH/edit.py" check
git diff --numstat -- home/common/agent-skills/skills/from-issue/SKILL.md
git status --porcelain
```

Expected: `check: pass`; one numstat line beginning `3	3	`; `git status --porcelain` lists only ` M home/common/agent-skills/skills/from-issue/SKILL.md`.

Read the three changed lines with `git diff -U0 -- home/common/agent-skills/skills/from-issue/SKILL.md` and confirm the first return case of the `delegate` action now reads, with nothing else on that line changed:

> (a) only the re-entry line or a `Suspended (…)` line (the delegated owner already reaped before its own exit), or bytes valid at `--boundary workflow-response` as `terminal` or `terminal_failed` (these alone mean it already ended the launch itself): relay it, write nothing and stop, with no reap;

- [ ] **Step 4: Run the gate and the skill-text tests**

Run: `just agent-instruction-budget 2>&1 | tail -1` (timeout 600 s)
Expected: `check: pass`.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_delegated_return_line -k test_generic_delegated_owner_returns -k test_delegate_action_checks -k test_from_issue_evals_cover 2>&1 | tail -3` (timeout 600 s)
Expected: `Ran 4 tests`, `OK`.

Run: `T=home/common/agent-skills/tests; PYTHONPATH="$PWD/python" python3 -m unittest $T/test_workflow_skill_contracts.py $T/test_dispatch_contracts.py $T/test_instruction_load.py $T/test_skill_lint.py $T/test_eval_cases.py 2>&1 | tail -3` (timeout 600 s)
Expected: `Ran 284 tests` (the count at `96174d0e`; a sync with `main` may change it), `OK (skipped=2)`. These are the suites that read skill text. No failure and no error is the requirement.

The project build is not run here: it copies this file into the installed skills directory without reading it, and sdd's final gate runs `just build` once.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md
git commit -m "docs(from-issue): say why a delegated return is relayed untouched (#362)"
```

Then run `git diff --stat HEAD~1 HEAD -- home/common/agent-skills/skills/from-issue/SKILL.md | tail -1`.
Expected: `1 file changed, 3 insertions(+), 3 deletions(-)`.

A review fix to this task goes through the same rule: the file's byte count must not move, and Step 4 is run again on the fixed text. A fix that needs different wording changes the script's strings, not the file by hand.
