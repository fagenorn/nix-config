# Task 2: Document the guard's source and govern it by the helper shard

Decisions: D10, D11 (the branch where `docs/standards/` is present, since #175
landed on `main` and reached this branch through the sync merge), D14; parent
D4, D6. Spec section "Living documents (D10, D11)". Work from the worktree root.
Every shell block starts with these lines, which the blocks below omit:

```bash
set -euo pipefail
CAP="${TMPDIR:-/tmp}"; CAP="${CAP%/}/issue-176"
G=home/common/claude-code/lifecycle_guard.py
```

**Files:**
- Modify: `CLAUDE.md` (one sentence inserted into the "Claude Code is
  declaratively managed" bullet)
- Modify: `docs/standards/README.md` (one path appended to the `agent-helpers.md`
  row's `governs` cell)
- Modify: `docs/standards/agent-helpers.md` (one closing paragraph)

**Interfaces:**
- Consumes: Task 1's committed state. That is
  `home/common/claude-code/lifecycle_guard.py`, the three-line wrapper, and the
  five-key policy, which is reachable from `$CAP/new-settings.json`.
- Produces: the living documents name the new file, and the Layer-2 shard loads
  for any change that touches it.

**Invariants:**
- Each sentence this task adds describes the code as Task 1 committed it. Step 1
  checks every clause against the source and the built wrapper before any prose
  is written (plan-prose ≠ code-prose).
- `CLAUDE.md` gains exactly one sentence. The existing clause that names
  `authorizedOwners` in `default.nix` as the authoritative roster stays, and the
  `@.agents/instructions/bootstrap.md` import line is untouched.
- `docs/standards/README.md` stays at 40 lines or fewer. Only the `governs`
  cell of its one row changes, and the Gist cell stays the same.
- `agent-helpers.md` keeps rules 1–5 byte-identical. The added paragraph is
  unnumbered and sits after rule 5.

- [ ] **Step 1: Confirm the claims against the code, and watch the doc checks fail**

```bash
W="$(jq -r '.hooks.PreToolUse[0].hooks[0].command' "$CAP/new-settings.json")"
P="$(sed -n 's/.* --policy \([^ ]*\) .*/\1/p' "$W")"
grep -cx 'unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE' "$W"
grep -cE -- ' -I /nix/store/[0-9a-z]{32}-lifecycle_guard\.py --policy ' "$W"
jq -r 'keys | join(",")' "$P"
jq -r '.git_bin, .gh_bin, .jq_bin' "$P" | grep -c '^/nix/store/'
grep -E '^(import|from) ' "$G" | tr '\n' ' '; echo
if grep -nE '^\s*(import|from) .*agent_tools|sys\.path|importlib|__file__' "$G"; then exit 1; fi
python3 - "$G" <<'PY'
import ast, sys
tree = ast.parse(open(sys.argv[1], encoding="utf-8").read())
heads = sorted({ast.unparse(node.args[0].elts[0]) for node in ast.walk(tree)
                if isinstance(node, ast.Call) and ast.unparse(node.func) == "subprocess.run"})
print(heads)
PY
grep -c 'lifecycle_guard.py' CLAUDE.md docs/standards/README.md docs/standards/agent-helpers.md || true
```

The expected output is `1`, then `1`, then
`authorized_owners,gh_bin,git_bin,integration_bases,jq_bin`, then `3`, then
`import argparse import json import os import re import shlex import subprocess import sys`,
then `['context.gh_bin', 'context.jq_bin', 'git_bin']`. After that come three
lines, each ending in `:0`, one per document. If any claim differs, stop: the
prose below would then be false.

- [ ] **Step 2: Add the `CLAUDE.md` sentence (D10)**

`CLAUDE.md` contains the text
``hands four lifecycle verbs to a fail-closed `PreToolUse` hook. The hook splits``
exactly once, on one line. Insert this sentence between `hook.` and
` The hook splits`, keeping one space on each side:

```markdown
That hook's Python is `home/common/claude-code/lifecycle_guard.py`, a standard-library-only file that imports nothing from `agent_tools`: the registered command is a store wrapper that clears `NIX_PYTHON*` and runs it under `python3 -I` with `--policy` naming a store JSON file of the Nix-owned values (`authorizedOwners`, `integrationBases` and the `git`/`gh`/`jq` paths), so an owner change never touches the source, `just build` fails when the source or policy cannot load, and an unreadable or malformed policy blocks every Bash call.
```

- [ ] **Step 3: Govern the guard by the shard (D11)**

In `docs/standards/README.md`, change the row's `governs` cell ending
``, `home/common/agent-skills/skills/*/scripts/**` |`` to
``, `home/common/agent-skills/skills/*/scripts/**`, `home/common/claude-code/lifecycle_guard.py` |``.
Change nothing else.

In `docs/standards/agent-helpers.md`, append one blank line and this paragraph
after rule 5, which is the last line of the file:

```markdown
The Claude Code lifecycle guard, `home/common/claude-code/lifecycle_guard.py`, stays a standalone, standard-library-only file that imports nothing from `agent_tools`, so of these rules only rule 3's ban on import machinery and `__file__` lookups binds it, and it runs `git`, `gh` and `jq` by the absolute store paths its policy names rather than by name on `PATH`. ([design](../../.claude/specs/2026-09-24-issue-176-lifecycle-guard-extraction-design.md))
```

- [ ] **Step 4: Verify**

```bash
grep -c 'hook\. That hook'"'"'s Python is `home/common/claude-code/lifecycle_guard.py`' CLAUDE.md
grep -c 'blocks every Bash call\. The hook splits' CLAUDE.md
grep -c '(the authoritative roster)' CLAUDE.md
grep -cx '@.agents/instructions/bootstrap.md' CLAUDE.md
grep -cF '`home/common/agent-skills/skills/*/scripts/**`, `home/common/claude-code/lifecycle_guard.py` |' docs/standards/README.md
test "$(wc -l < docs/standards/README.md)" -le 40 && echo index-ok
git diff --numstat -- CLAUDE.md docs/standards/README.md docs/standards/agent-helpers.md
test -f .claude/specs/2026-09-24-issue-176-lifecycle-guard-extraction-design.md && echo link-target-ok
```

Expected: `1`, `1`, `1`, `1` and `1`, then `index-ok`. The numstat lines are
`1	1	CLAUDE.md`, `1	1	docs/standards/README.md` and
`2	0	docs/standards/agent-helpers.md`, and the last line is `link-target-ok`.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'`
Expected: `Ran 1222 tests …` and `OK (skipped=2)`. The count is the base count
at `dbbc09a`, and it grows only if a sync merge adds tests. Conformance fixtures
copy `CLAUDE.md`. `WORKFLOW_POLICY_SURFACE=source` is the spelling CI uses.
Without it, `test_installed_policy_surface_matches_source_contract` reads this
machine's activated `~/.agents/skills`, which predates the branch, and the test
fails at base too. The planning run took about 12 minutes. Summarize any failure
to its test ids.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/standards/README.md docs/standards/agent-helpers.md
git commit -m "docs: point the architecture note and helper shard at the extracted lifecycle guard"
```

The message ends with the plan's trailer lines.
