# Task 4: Guard prose — trust split, row check, residual

Spec section 7 and section 6 (per D1–D7, D9). The guard README and the agent-helpers standard describe the code as it behaves after Task 3. `python/README.md` was brought up to date by Tasks 1 and 2.

**Files:**
- Modify: `home/common/claude-code/README.md`
- Modify: `docs/standards/agent-helpers.md`

**Interfaces:**
- Consumes (Tasks 1–3, all committed): in `lifecycle_guard.py` `load_base_policy`, `load_compiled_policy`, `Context`, `row_check_problem`, `ownership_problem`, `INVOCATION_DEADLINE_SECONDS`, the argv; in `default.nix` `lifecycleGuardBasePolicy`, `lifecycleGuardPolicyPath`, `lifecycleGuardRowCheck`, `lifecycleGuard`, `claudeGuardPolicy`, `home.activation.claudeGuardPolicy`; `python/README.md` § guard-policy.
- Produces: documentation only, and the acceptance-record row `AC6` value handed to the caller from sdd's final gate (this task runs no part of the final gate itself).

**Invariants:**
- Every sentence added or changed is true of the code at this task's commit: read each named function, binding and the built wrapper and row-check scripts before writing about them.
- Four terms, each introduced once in `## Guard policy` (D9): **base policy**, **compiled policy**, **derived row**, **row check**.
- `CLAUDE.md`, `AGENTS.md`, `.agents/instructions/` and `python/README.md` are not edited (no sentence of `CLAUDE.md` names the policy's files or schema).
- No file outside the two above is changed by this task.

- [ ] **Step 1: Confirm the gate fails first**

Run:

```bash
f=home/common/claude-code/README.md
grep -q 'D17 records it as an open residual' "$f" && echo STALE-D17
grep -q 'does not recheck them per invocation' "$f" && echo STALE-D6
grep -q 'row check' "$f" || echo MISSING-ROW-CHECK
grep -q 'base policy' docs/standards/agent-helpers.md || echo MISSING-STANDARD
```

Expected at this task's starting commit: `STALE-D17`, `STALE-D6`, `MISSING-ROW-CHECK` and `MISSING-STANDARD`.

- [ ] **Step 2: Write the documentation**

In `home/common/claude-code/README.md`, in the file's existing style (dense prose paragraphs, decisions cited as `issue 377 D<n>` / `issue 126 D<n>`), each sentence written from the implemented code:

1. `## Allow surface and lifecycle guard`, the wrapper sentence: the store wrapper runs the guard with `--base-policy` naming the store base policy, `--policy` naming the compiled policy at `~/.agents/state/guard/policy.json` and `--derive-bin` naming the store row check; `just build` fails when the guard source or the base policy cannot load, because the wrapper's build check runs the guard as registered on a harmless payload; a bad base policy blocks every Bash call, while a bad compiled policy contributes no row (pointer to `## Guard policy`). The closing pointer to `tests/test_claude_permission_guard.py` says the suite passes a fixture compiled policy and a stub row check on every invocation, so it never reads this host's compiled policy or registry.
2. `## Guard policy`, rewritten. It states:
   - the two files and their closed schemas: the base policy (`claude-bash-lifecycle-guard-base-policy.json`, from `lifecycleGuardBasePolicy`) holds exactly `authorized_owners`, `integration_bases`, `git_bin`, `gh_bin`, `jq_bin`; the compiled policy holds exactly `derived_repositories` and `derivation`; a trust table (member, file, rule) as in spec section 1;
   - that the guard loads the base policy on every call and the compiled policy only when it judges a repository-bound verb, and never executes a program the compiled policy names;
   - who writes the compiled policy (`guard-policy compile` via `claude-guard-policy` and the activation step, unchanged facts kept) and that it is a user-writable state file;
   - the row check: what `--derive-bin` runs (the store script that pins store `git`, `gh`, `ssh` and execs `guard-policy derive --repository <slug>`, contract in `python/README.md` § guard-policy), the four-step order for a repository with a row (literal conflict, `origin/HEAD`, row check, branch comparison), that `evidence` is not compared, that it runs once per invocation and only for a repository with a row, in its own process group, bounded by `--derive-timeout-seconds` (15 s) and the 27-second invocation deadline that every child shares (issue 377 D6), and the refusal naming `claude-guard-policy`;
   - cost and offline behaviour: one remote listing, one fetch per branch read and one provider read on every repository-bound verb in a repository with a row, nix-config included (about 5–7 s measured on the host on 2026-10-12, per spec section 3); unreachable `origin` or provider refuses with no fallback; a concurrent fetch that loses a ref lock refuses and a rerun clears it (issue 377 D3);
   - the bad-file rule (issue 377 D4): a missing, unreadable, malformed or out-of-schema compiled policy contributes no row and blocks nothing the base policy allows, and a refusal for standing authorization then adds the reason and `claude-guard-policy`; a bad base policy blocks every Bash call;
   - literal and derived rows (issue 377 D5): the compiler refuses a `literal_conflict` project its row, the literal row stays, and the guard refuses a repository that has both;
   - the roster sentence: what the guard authorizes is the base `authorized_owners` and `integration_bases` plus the derived rows the row check confirms;
   - the activation step's outcomes as `default.nix` now reports them (a removed or failed compile leaves registered projects without a row, not every call blocked);
   - the issue 126 D6 sentence becomes: rows are rechecked at use, and a row whose branches no longer match `origin` refuses until the next compile;
   - the residual (spec section 6): rewriting the compiled policy alone gains nothing; the registry, transport and tool configuration and `~/.claude/settings.json` remain user-writable, with what each still allows; the check-to-use window; the guard catches a cooperating session's mistakes and is not a sandbox.
   - Remove the sentence recording issue 126 D17 as an open residual and the claim that the guard checks the compiled file's schema and not its origin as the whole story.
3. `docs/standards/agent-helpers.md`, the closing guard paragraph: the guard runs `git`, `gh` and `jq` by the absolute store paths its **base policy** names and the row check by the store path its wrapper passes as `--derive-bin`; it never runs a program named by the user-writable compiled policy. Keep the paragraph's design link.

- [ ] **Step 3: Verify**

Run:

```bash
set -e
f=home/common/claude-code/README.md
for needle in '^## Guard policy' 'base policy' 'compiled policy' 'derived row' 'row check' \
  '--derive-bin' 'claude-guard-policy' 'guard-policy derive' 'residual' 'issue 377 D4'; do
  if ! grep -q -- "$needle" "$f"; then echo "missing: $needle"; exit 1; fi
done
if grep -q 'D17 records it as an open residual' "$f"; then exit 1; fi
if grep -q 'does not recheck them per invocation' "$f"; then exit 1; fi
if grep -q 'closed schema of seven members' "$f"; then exit 1; fi
if grep -q 'elevenyellow' "$f"; then exit 1; fi
grep -q 'base policy' docs/standards/agent-helpers.md
grep -q -- '--derive-bin' docs/standards/agent-helpers.md
git diff --quiet 69a1047920707528fc97729b57b705332a360d27 -- CLAUDE.md AGENTS.md .agents/instructions
echo PROSE
```

Expected: `PROSE`.

Then reread `## Guard policy` against spec sections 1–7 and the code; this reading is the AC5 judgment the reviewer repeats.

- [ ] **Step 4: Commit**

```bash
git add home/common/claude-code/README.md docs/standards/agent-helpers.md
launch-commit … -- -m "docs(guard): document the policy trust split and the row check (#377)"
```
