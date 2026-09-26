# Task 3: State the ledger read in the living docs, then run the final gate

Decisions: D11 (the `CLAUDE.md` bullet and ship-handoff's "regenerates"
sentence; the sanctioned-exception sentences, ship-issue and the #171/#181 specs
stay untouched). Spec §5 "Documentation". Work from the worktree root. Every
shell block starts with `set -euo pipefail` and these abbreviations, which the
blocks below omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
SH=home/common/agent-skills/skills/from-issue/ship-handoff.md
```

**Files:**
- Modify: `CLAUDE.md` (one sentence in the "Delivery objects are built, never
  hand-composed" bullet)
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md` (the
  `authorization_intents` sentence)

**Interfaces:**
- Consumes (Tasks 1 and 2): the behaviour both docs now describe. The
  `build-delivery --help` text from Task 2 is the authoritative statement, and
  these docs restate it (D11).
- Produces: nothing code consumes.

**Invariants:**
- `CLAUDE.md` no longer says the builder reads no ledger, and it no longer says
  the builder refuses everything it cannot derive. It keeps the exit-2,
  empty-stdout and verbatim resolver-relay statements.
- ship-handoff keeps its command, heredoc and `{"contract": <installed contract>}`
  wording, so the skill contract and shell example suites stay green.
- No other file changes. In particular, `docs/`, the ship-issue skill, the
  sanctioned-exception sentences and every file under `.agents/artifacts/specs/`
  keep their bytes (D11).

- [ ] **Step 1: Confirm the gate fails at the start**

```bash
set -uo pipefail
SH=home/common/agent-skills/skills/from-issue/ship-handoff.md
grep -c 'no lock, ledger, clock or write' CLAUDE.md
tr -s '[:space:]' ' ' < $SH | grep -c 'the builder regenerates from that contract'
```

Expected: `1` and `1`. Step 3's prohibitions would exit on both.

- [ ] **Step 2: Edit the two documents**

1. In `CLAUDE.md`, in the "Delivery objects are built" bullet, replace exactly
   this text:
   ```
   It is read-only — no lock, ledger, clock or write — and refuses anything it cannot derive with exit 2 and empty stdout;
   ```
   with this text, whose backticks around `--repo-root` are literal Markdown:
   ```
   It is read-only — no lock, clock or write. A contract it cannot re-derive is served only when a ledger under `--repo-root` has installed it, and then against that ledger's stored initial intent; that is the only time it reads a ledger. It refuses anything else it cannot derive with exit 2 and empty stdout;
   ```
   The rest of that sentence, about the resolver's error document, is
   unchanged. The bullet stays one line.
2. In `$SH`, the sentence reads today, across two lines:
   "`authorization_intents` is the one initial intent the builder regenerates
   from that contract, printed by". Replace `regenerates from that contract`
   with `prints for that contract`, and rewrap to
   ```
   `authorization_intents` is the one initial intent the builder prints for that
   contract, printed by
   ```
   Leave the command line and the rest of the paragraph as they are.

- [ ] **Step 3: Verify the documents**

```bash
set -euo pipefail
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
SH=home/common/agent-skills/skills/from-issue/ship-handoff.md
if grep -qF 'no lock, ledger, clock or write' CLAUDE.md; then exit 1; fi
if tr -s '[:space:]' ' ' < $SH | grep -qF 'builder regenerates from'; then exit 1; fi
grep -cF "that is the only time it reads a ledger. It refuses anything else it cannot derive with exit 2 and empty stdout;" CLAUDE.md
tr -s '[:space:]' ' ' < $SH | grep -cF 'the one initial intent the builder prints for that contract, printed by'
grep -cx '@.agents/instructions/bootstrap.md' CLAUDE.md
git diff --numstat -- CLAUDE.md $SH
PYTHONPATH=python python3 -m unittest $T/test_workflow_skill_contracts.py $T/test_shell_example_contracts.py $T/test_dispatch_contracts.py 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
```

Expected: both prohibitions pass. Then `1`, `1`, `1`, then `1	1	CLAUDE.md`
and `2	2	home/common/agent-skills/skills/from-issue/ship-handoff.md`, and the
three contract suites together end `OK (skipped=3)`.

- [ ] **Step 4: Final gate**

```bash
set -euo pipefail
LOG="${TMPDIR:-/tmp}"; LOG="${LOG%/}/issue-193-build.log"
WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
if just build > "$LOG" 2>&1; then echo build-ok; else grep -E 'error:' "$LOG" | head -20; exit 1; fi
git status --short
```

Expected: `Ran 1312 tests …` and `OK (skipped=4)`. That is the base count of 1305
at `6c23e64` plus this plan's 7 tests, and it grows only if a sync merge adds
tests. The four skips are the installed-tree and pre-activation checks that this
invocation leaves out by design. `WORKFLOW_POLICY_SURFACE=source`
is the spelling CI uses. Without it,
`test_installed_policy_surface_matches_source_contract` reads this machine's
activated `~/.agents/skills`, which predates the branch. The suite takes about 9
minutes. The build prints `build-ok`, and `git status --short` shows only this
task's two files before the commit. Summarize any failure to its test ids or
`error:` lines. Never run `just switch`.

- [ ] **Step 5: Commit**

```bash
set -euo pipefail
SH=home/common/agent-skills/skills/from-issue/ship-handoff.md
git add CLAUDE.md $SH
git commit -m "docs: state when build-delivery reads a ledger" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014t9cPhYQiiTKbbAn8vTEaq"
```
