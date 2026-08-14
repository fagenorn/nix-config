---
name: writing-plans
description: Turn a spec into a task-by-task implementation plan before touching code. Use when you have requirements for multi-step work and need a plan to execute.
---

# Writing Plans

Write the plan for an engineer who is skilled but has zero context for this codebase, this toolset, and this domain, and who will read exactly one task without the others. Every task names the files it touches, the code to write, how to test it, and how to verify it. DRY. YAGNI. Test-first. Frequent commits.

**Save to** `<planDir>/YYYY-MM-DD-<feature-name>.md` (`planDir` from `.claude/skills.config.json`, default `.claude/plans`), committed in the worktree you were called in.

## Scope check

If the spec covers several independent subsystems, write one plan per subsystem — each producing working, testable software on its own — and say so rather than fusing them.

## File structure first

Before defining tasks, map which files get created or modified and what each is responsible for. Decomposition decisions get locked in here.

When that map depends on one sharply bounded repository fact, keep the planning judgment in this Opus owner and delegate only the read-only lookup:

<!-- agent-dispatch: id=planning-bounded-fact-lookup role=explorer model=haiku effort=medium -->
Agent(subagent_type="Explore", model="haiku", effort="medium") performs one sharply bounded read-only repository lookup without choosing task boundaries.

If the lookup becomes open-ended, ambiguous, or judgment-bearing, stop the cheap-tier run and re-dispatch the `issue-owner` on Opus/high; record that escalation and selected role in the plan phase's existing fixed-schema report.

- One clear responsibility per file, with a well-defined interface. Files that change together live together; split by responsibility, not by technical layer.
- Prefer focused files: edits are more reliable in code that fits in one context.
- In an existing codebase, follow its established patterns. Don't unilaterally restructure — but a split of a file you're already modifying is fair game.

## Task right-sizing

A task is the smallest unit that carries its own test cycle and is worth a fresh reviewer's gate. Fold setup, configuration, scaffolding and documentation into the task whose deliverable needs them; split only where a reviewer could meaningfully reject one task while approving its neighbor. Every task ends with an independently testable deliverable.

Steps inside a task are one action each (2–5 minutes): write the failing test · run it and see it fail · write the minimal implementation · run the tests · commit.

## Plan header

Every plan starts with:

```markdown
# <Feature> Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** <one sentence>

**Architecture:** <2–3 sentences on the approach>

**Tech stack:** <key technologies and libraries>

## Global Constraints

<The spec's project-wide requirements — version floors, dependency limits, naming
and copy rules, platform requirements — one line each, exact values copied
verbatim from the spec. Every task's requirements implicitly include this section.>

## Test seams

<The seams the spec agreed on, one line each. Implementers test at these and
nowhere else; a task needing a new seam is a plan bug, not an implementer's call.>

## Auto-resolved decisions

<One entry per question you answered instead of the user — mandatory when the
caller runs autonomously, expected otherwise, since task granularity, test
framing, verification gates and commit boundaries are all your calls:

### <decision title>
- **Question:** what would have been asked
- **Choice:** what you picked
- **Grounding:** the docs / code / spec references that justify it
- **Alternative considered:** what you rejected and why

Never consolidate entries — a later phase extends this section rather than
rewriting it, so the design stays traceable in order.>

---
```

## Task structure

````markdown
### Task N: <Component>

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py`
- Test: `tests/exact/path/to/test.py`

**Interfaces:**
- Consumes: <what this task uses from earlier tasks — exact signatures>
- Produces: <what later tasks rely on — exact names, parameter and return types.
  An implementer sees only its own task; this block is how it learns the names
  neighboring tasks use.>

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL — `function` is not defined

- [ ] **Step 3: Write the minimal implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Verify**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS, 1 test, no warnings

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

**Every task carries at least one verification line that could fail.** Name the command and the observation that would show the task incomplete, and confirm that observation holds at the commit the implementer starts from. A criterion already true at the base commit is how an implementer "completes" a no-op.

**Scope every gate to the files the plan owns.** Give diffs a pathspec (`git diff --stat BASE..HEAD -- <the paths named in the plan's Files: blocks>`) or assert against file content directly; never write a raw commit-range expectation — "exactly three files changed", "every commit in the range is a `feat:`". The range is not the plan's to grade: the plan and spec files land in it, so do the caller's `docs(plans):`/`docs(specs):` artifact commits, and a ship-time sync merge pulls in everything the integration branch advanced by — the gate then reads another issue's shipped work as scope creep and demands reverting it. Where commit shape genuinely is under test, restrict to the branch's own commits (`git log --no-merges BASE..HEAD ^origin/<integration-branch>`; the sync merge is unreachable from the integration branch, so `^` alone leaves it in) and name the artifact and review-fixup subjects as exempt.

## No placeholders

These are plan failures — never write them:

- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Write tests for the above" without the test code
- "Similar to Task N" — repeat the code; tasks are read out of order and in isolation
- Steps that say what to do without showing how (code steps need code blocks)
- References to types, functions or methods no task defines

## Self-review

Read the finished plan against the spec with fresh eyes. This is your own checklist, not a dispatch.

1. **Spec coverage** — for each requirement in the spec, name the task that implements it. List gaps and add tasks for them.
2. **Placeholder scan** — search for the patterns above and fix what you find.
3. **Type consistency** — do the signatures, method names and property names used in later tasks match what earlier tasks define? `clearLayers()` in Task 3 and `clearFullLayers()` in Task 7 is a bug.
4. **Falsifiability and gate scope** — every task has a verification line that can fail, and no gate asserts over an unscoped commit range.

Fix inline and move on; no re-review pass.

## Return control

Report the plan path, any question you could not resolve, and ≤500 characters of notes. Do not offer an execution choice, invoke an execution skill, or start implementing — the caller owns standards review and execution.
