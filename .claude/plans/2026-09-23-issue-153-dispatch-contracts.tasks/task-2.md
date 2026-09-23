# Task 2: Blockquote and composition-rule carriers

Decisions: D1, D2, D4, D6, D10, D12, D15. Work from the worktree root; paths are
repo-relative. `SK` = `home/common/agent-skills/skills`. This is new work: the
retained commit's only `orchestrate-issues` hunk is the excluded #100 guard, so
nothing here is recovered and the commit carries no `Recovered-From` trailer.

**Files:**
- Modify: `home/common/agent-skills/tests/test_dispatch_contracts.py`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `SK/from-issue/SKILL.md`, `SK/from-issue/AUTO.md`, `SK/sdd/SKILL.md`
- Test: `home/common/agent-skills/tests/test_dispatch_contracts.py`

**Interfaces:**
- Consumes (Task 1, in `test_dispatch_contracts.py`): `Carrier(relative, tree,
  kind, anchor="")`, `CARRIERS`, `RegionError`, `_fence_region`,
  `_RENDERERS`, `REGION_BREAKERS`, `missing_contracts`; the six fence carriers
  already hold both clauses.
- Produces: carrier kinds `"blockquote"` and `"section"` in `_RENDERERS` and
  `REGION_BREAKERS`; `CARRIERS` at nine entries — Task 3 iterates them all and
  filters by `carrier.tree`.

**Invariants:**
- Blockquote region: the contiguous `>` lines after the one line containing
  `carrier.anchor` (blank lines between are skipped), each with `^> ?` removed;
  zero or several anchor lines, or no quote after it, raise `RegionError`.
- Section region: the lines after the one line equal to `carrier.anchor`, up to
  the next line matching `#{1,2} `; zero or several headings raise `RegionError`.
- The orchestrate blockquote stays one contiguous quote (`>` separator lines,
  never a blank line), so `test_dispatcher_passes_immutable_ledger_root_separately_from_worktree`
  still slices it at `\n\nNever inline`.
- `AUTO.md` gains a pointer bullet only and never restates the sentences.
- No existing line in the four prose files changes.

- [ ] **Step 1: Extend the test module (failing)**

In `test_dispatch_contracts.py`:

1. Append to `CARRIERS`, after the `from-issue/ship-handoff.md` entry:

```python
    Carrier(
        "orchestrate-issues/SKILL.md", "claude-only", "blockquote",
        "launches the issue owner in a fresh context with this entire prompt:",
    ),
    Carrier(
        "from-issue/SKILL.md", "shared", "section",
        "## Dispatch, phase-budget and attempt-budget rules",
    ),
    Carrier("sdd/SKILL.md", "shared", "section", "## Agent tiers"),
```

2. Replace `_RENDERERS = {"fence": _fence_region}` with:

```python
def _blockquote_region(carrier, text):
    lines = text.splitlines()
    anchors = [index for index, line in enumerate(lines) if carrier.anchor in line]
    if len(anchors) != 1:
        raise RegionError(
            f"{carrier.relative}: expected one anchor line, found {len(anchors)}"
        )
    index = anchors[0] + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    quoted = []
    while index < len(lines) and lines[index].startswith(">"):
        quoted.append(re.sub(r"^> ?", "", lines[index]))
        index += 1
    if not quoted:
        raise RegionError(
            f"{carrier.relative}: the anchor line is not followed by a quote block"
        )
    return "\n".join(quoted)


def _section_region(carrier, text):
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line == carrier.anchor]
    if len(starts) != 1:
        raise RegionError(
            f"{carrier.relative}: expected heading {carrier.anchor!r} once, "
            f"found {len(starts)}"
        )
    body = []
    for line in lines[starts[0] + 1:]:
        if re.match(r"#{1,2} ", line):
            break
        body.append(line)
    return "\n".join(body)


_RENDERERS = {
    "fence": _fence_region,
    "blockquote": _blockquote_region,
    "section": _section_region,
}
```

3. Add to `REGION_BREAKERS`, after the `"fence"` entry:

```python
    "blockquote": (
        ("the anchor line removed", lambda carrier, text: text.replace(carrier.anchor, "")),
        ("the anchor line repeated", lambda carrier, text: text + "\n" + carrier.anchor + "\n"),
        ("the quote markers stripped", lambda carrier, text: re.sub(r"(?m)^> ?", "", text)),
    ),
    "section": (
        ("the heading removed", lambda carrier, text: text.replace(carrier.anchor + "\n", "", 1)),
        ("the heading repeated", lambda carrier, text: text + "\n" + carrier.anchor + "\n"),
    ),
```

- [ ] **Step 2: Run and watch it fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -1`
Expected: `FAILED (failures=27)`, all in the three new carriers:
`python3 -m unittest -v home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | grep 'FAIL$' | grep -c -v -e orchestrate-issues/SKILL.md -e from-issue/SKILL.md -e sdd/SKILL.md`
prints `0`; `test_a_missing_or_ambiguous_region_fails_loud` and
`EnrolmentGuardTest` pass.

- [ ] **Step 3: Add the clauses**

`home/common/claude-code/skills/orchestrate-issues/SKILL.md` — insert these six
lines immediately before `> Persist the compact result with …` (l160):

```
>
> Launch any subagent by type only, never by name: a subagent cannot spawn a
> named teammate, and a named launch returns an error instead of work. Read an
> existing file before writing to it: overwriting content you have not read
> destroys work you cannot see.
>
```

`SK/from-issue/SKILL.md` — in `## Dispatch, phase-budget and attempt-budget
rules`, insert after the `**Structured report-backs.**` paragraph (l189) and its
blank line, before `**Artifact report boundary (D5, D6, D11, D14).**` (l191),
these lines followed by one blank line (each paragraph is one unwrapped line,
like its sibling):

```
**Leaf-agent clauses.** Every prompt this skill or a file beside it composes for an `Agent` dispatch carries these two sentences verbatim, as a paragraph of their own; a prompt built from `ship-handoff.md` already carries them:

> Launch any subagent by type only, never by name: a subagent cannot spawn a named teammate, and a named launch returns an error instead of work. Read an existing file before writing to it: overwriting content you have not read destroys work you cannot see.
```

`SK/sdd/SKILL.md` — at the end of `## Agent tiers`, after the `Turn count beats
token price …` paragraph and its blank line, before `## The task loop` (l78),
these lines followed by one blank line:

```
**Leaf-agent clauses.** Every prompt this skill composes for an `Agent` dispatch — here, in [fix-loop.md](fix-loop.md) or in [final-review.md](final-review.md) — carries these two sentences verbatim, as a paragraph of their own; a prompt built from one of the `*-prompt.md` templates already carries them:

> Launch any subagent by type only, never by name: a subagent cannot spawn a named teammate, and a named launch returns an error instead of work. Read an existing file before writing to it: overwriting content you have not read destroys work you cannot see.
```

`SK/from-issue/AUTO.md` — in the `Both prompts must carry, inline` list, insert
before `- the fixed return schema, with …` (l116):

```
- the two sentences of `SKILL.md`'s **Leaf-agent clauses** rule, verbatim, as a paragraph of their own,
```

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -3`
Expected: `Ran 9 tests`, `OK`.
Run: `python3 -m unittest -k test_dispatcher_passes_immutable_ledger_root_separately_from_worktree home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -1` — `OK`.
Run: `just agent-workflow-tests 2>&1 | tail -3` — `OK`.
Run: `just agent-model-matrix 2>&1 | head -1` — `agent model matrix: valid`.
Run: `if grep -q 'Launch any subagent' home/common/agent-skills/skills/from-issue/AUTO.md; then echo "AUTO.md restates the clause"; exit 1; fi`
Run: `git diff --numstat -- home/common/claude-code/skills home/common/agent-skills/skills`
Expected rows: orchestrate-issues `6 0`, from-issue/SKILL.md `4 0`,
sdd/SKILL.md `4 0`, from-issue/AUTO.md `1 0`.

- [ ] **Step 5: Commit**

Stage exactly the five Files above and commit (signed; harness attribution
trailers only, no `Recovered-From`):

```
fix(agent-skills): carry leaf-agent clauses in composed dispatch prompts

Add both leaf-agent clauses to the orchestrate-issues issue-owner
prompt and a Leaf-agent clauses rule to from-issue's and sdd's dispatch
rules, with a pointer bullet in from-issue/AUTO.md, and extend
test_dispatch_contracts.py with the blockquote and section carrier
kinds that hold them.
```

- [ ] **Step 6: Post-commit gates**

Run: `git log -1 --format='%(trailers:key=Recovered-From,valueonly)'` — expected
an empty line (this commit recovers nothing).
Run the root's **AC4 exclusion gate** — expected `AC4 exclusion gate: pass`.
Run: `git status --porcelain` — expected empty.
