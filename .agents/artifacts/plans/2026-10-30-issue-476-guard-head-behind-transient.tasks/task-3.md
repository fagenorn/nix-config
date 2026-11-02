# Task 3: Global guidance states the accepted lifecycle-verb form

Spec § Global guidance: the accepted form. Rests on D7. After this task, the single global guidance source has one more paragraph, placed just before the `instruction-budget-raise` line. It says that each guarded lifecycle verb runs alone in its own Bash call, and it gives that call's accepted shape. The text reaches Claude as `~/.claude/CLAUDE.md` and Codex as `~/.codex/AGENTS.md` after a switch, which this task never runs.

**Files:**
- Modify: `home/common/agent-guidance/AGENTS.md`

**Interfaces:**
- Consumes: the Instruction Budget gate (`python -m agent_tools.instruction_load check --base origin/main`, through `just agent-instruction-budget`). It counts the frame `agent-guidance/AGENTS.md` toward the corpus ceiling and toward no profile total. Also consumed: `home/common/agent-skills/tests/test_dispatch_contracts.py`, which scans this file for stray contract clauses.
- Produces: one paragraph of 5 lines, 302 bytes including its separating blank line. No code reads it.

**Invariants:**
- The paragraph's words are exactly D7's line, and the wrapping below is fixed. No other line of the file changes: the diff is 6 added lines and 0 removed.
- It sits after the skills paragraph and before `Only the user applies the `instruction-budget-raise` label.`, separated by single blank lines.
- The Budget run passes with no ceiling raised. Never add the `instruction-budget-raise` label, and never edit `home/common/agent-skills/instruction-load.json`.

- [ ] **Step 1: Write the failing check**

The check is the gate in Step 4. It names no lifecycle verb and not the raise label, so the live guard leaves it alone. A gate that names the label is refused, because a command substitution sits inside a quoted word:

`bash -c 'set -e; F=home/common/agent-guidance/AGENTS.md; a=$(grep -n "each alone in its own Bash call" "$F" | cut -d: -f1); b=$(grep -n "Only the user applies the" "$F" | cut -d: -f1); test -n "$a"; test "$a" -lt "$b"; test "$(git diff --numstat -- "$F" | cut -f1,2)" = "$(printf "6\t0")"'`

- [ ] **Step 2: Run the check and watch it fail**

Run the gate above.
Expected: exit 1, because the paragraph is absent and `test -n "$a"` fails.

- [ ] **Step 3: Write the paragraph**

In `home/common/agent-guidance/AGENTS.md`, insert these five lines, followed by one blank line, between the blank line after `current version rather than working from memory.` and the line `Only the user applies the `instruction-budget-raise` label.`:

```markdown
Run `git push`, `git branch -d`, `gh pr create`, `gh pr merge` and
`gh release create` each alone in its own Bash call: no chain, pipe or
redirection beyond an `unset GITHUB_TOKEN && ` prefix, an explicit `--repo`
on each `gh` verb, and no `"`, `$`, backtick or backslash in a title,
subject or body.
```

The code span `` `unset GITHUB_TOKEN && ` `` keeps its trailing space inside the backticks. No line breaks inside a code span.

- [ ] **Step 4: Verify**

Run the Step 1 gate.
Expected: exit 0.

Run the Budget run.
Expected: the output ends `check: pass`.

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -3'`
Expected: `OK (skipped=1)`, the same as at base.

Run the Build.
Expected: the build ends without an error line. The guidance file is read into the home configuration.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-guidance/AGENTS.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(guidance): state the accepted lifecycle-verb form (issue 476)" -m "<trailers>"
```
