# Task 4: Guard prose and the acceptance evidence

Spec section 7 and `## Acceptance and hold` (per D4, D6, D12). `home/common/claude-code/README.md` describes the two producers, the compile outcomes and the repair command as the code behaves after Task 3, and the evidence rows of the acceptance map are measured on the final head.

**Files:**
- Modify: `home/common/claude-code/README.md`

**Interfaces:**
- Consumes (Tasks 1–3, all committed before this task): `python/agent_tools/guard_policy.py` and its `python/README.md` section `## guard-policy`; in `home/common/claude-code/default.nix` the base policy `lifecycleGuardBasePolicy`, the compiled path, `claudeGuardPolicy` and `home.activation.claudeGuardPolicy`; in `lifecycle_guard.py` `load_policy`, `Context` and `ownership_problem`.
- Produces: documentation, and the measured values for acceptance-record rows `AC1`, `AC4`–`AC7` and `AC10`, handed to the caller in the task report. This task writes no acceptance file and runs no part of `AC9`.

**Invariants:**
- Every sentence added or changed is true of the code at this task's commit: read each named function, Nix binding and the built `claude-guard-policy` script before writing about it.
- The README uses exactly three terms for the policy, each introduced once (D12): the **base policy** (Nix-built), the **compiled policy** (the file the hook reads) and a **derived row**.
- The README restates no project's row: it does not contain `elevenyellow`, and it names the compiled policy, not `default.nix`, as the authoritative roster.
- `CLAUDE.md`, `AGENTS.md` and `.agents/instructions/` are not edited: no sentence of them becomes false (the one guard bullet of `CLAUDE.md` names the hook, its verbs and this README, not the policy's source), so the instruction budget is untouched and no raise label is involved.
- No file outside `home/common/claude-code/README.md` is changed by this task.
- Nothing here runs `claude-guard-policy`, `just switch`, or any command in or against the Nodo checkout or repository.

- [ ] **Step 1: Confirm the gate fails first**

Run:

```bash
f=home/common/claude-code/README.md
if ! grep -q 'claude-guard-policy' "$f"; then echo MISSING-REPAIR; fi
if ! grep -q 'compiled policy' "$f"; then echo MISSING-TERM; fi
if grep -q 'elevenyellow' "$f"; then echo STALE-ROW; fi
```

Expected at this task's starting commit: `MISSING-REPAIR`, `MISSING-TERM` and `STALE-ROW` are all printed.

- [ ] **Step 2: Write the documentation**

In `home/common/claude-code/README.md`, in the file's existing style (dense prose paragraphs, decisions cited as `issue 126 D<n>` where the file cites `#<n>`), each sentence written from the implemented code:

1. `## Allow surface and lifecycle guard`: the registered wrapper's `--policy` names the compiled policy at `~/.agents/state/guard/policy.json`, a path fixed at evaluation time from the configured home directory; `just build` fails when the guard source or the base policy cannot load, because the wrapper's build check runs the guard against the base policy; an unreadable, missing or malformed compiled policy blocks every Bash call. Remove the claim that `--policy` names a store JSON file of the Nix-owned values.
2. The same paragraph's closing pointer to `tests/test_claude_permission_guard.py`: the suite takes the built settings through `CLAUDE_SETTINGS_PATH` and the built base policy through `CLAUDE_GUARD_BASE_POLICY_PATH`, runs under `python3 -m unittest` with `python/` on `PYTHONPATH`, and passes a fixture policy on every invocation, so it never reads this host's compiled policy.
3. `## Adjudicated verbs`: the four repository-bound verbs require the repository to be inside standing authorization, which means its owner is in the policy's `authorized_owners` or the repository itself has a derived row; a declared integration branch comes from a literal `integration_bases` row or from a derived row whose two branches differ. Remove the `authorizedOwners`-in-`default.nix` roster claim and the Nodo example. In the forge-adapter paragraph, both occurrences of "an authorized owner" (the tag-push arm's and release creation's) become the same standing-authorization wording.
4. A new section `## Guard policy`, placed after `## The raise label` and before `## Guard/core decision`, stating:
   - the three terms, and the closed seven-member schema both policies share;
   - what the base policy holds (the literal `authorizedOwners` and `integrationBases` rows, which are only for repositories that are not registered projects, plus the three tool paths) and that it is a valid policy with no derived row;
   - who writes the compiled policy: `guard-policy compile` (contract in `python/README.md` § guard-policy), run with fixed arguments by the installed, argument-free `claude-guard-policy`, which the activation step `claudeGuardPolicy` runs on every switch after `linkGeneration` and before the settings copy, without ever aborting the switch;
   - what a derived row is and does in the guard: one per registered project whose proof held at that compile, keyed by the exact repository, authorizing that repository and no other of its owner; `origin/HEAD` must name the row's `default_branch` or every repository-bound verb is refused; the row's `integration_branch` is the integration base when it differs from the default; `evidence` and `derivation` are recorded and not interpreted by the guard;
   - that a repository cannot be both a derived row and a literal integration row: the compiler withholds both and the guard refuses a policy carrying both (issue 126 D5);
   - the three compile outcomes as the activation step treats them: status 0; status 1, a policy without the refused projects' rows, so each of those repositories is judged by the literal rows alone; any other status, no policy file, so the hook blocks every Bash call;
   - the repair: `claude-guard-policy` from a shell that can fetch each project's `origin` and whose `gh` keyring reaches the provider; it can only re-derive from the registry and `origin`;
   - that registry and contract changes take effect at the next compile and the guard does not recheck them per invocation (issue 126 D6), and that the compiled policy's `authorized_owners` and `derived_repositories` keys are the authoritative roster.

- [ ] **Step 3: Verify the documentation gate**

Run, as one script:

```bash
set -e
f=home/common/claude-code/README.md
for needle in 'claude-guard-policy' 'compiled policy' 'base policy' 'derived row' '^## Guard policy' 'CLAUDE_GUARD_BASE_POLICY_PATH' 'guard-policy compile'; do
  if ! grep -q -- "$needle" "$f"; then echo "missing: $needle"; exit 1; fi
done
if grep -q 'elevenyellow' "$f"; then exit 1; fi
if grep -q 'naming a store JSON file of the Nix-owned values' "$f"; then exit 1; fi
git diff --quiet 450f1de3627b -- CLAUDE.md AGENTS.md .agents/instructions
git diff --stat 450f1de3627b -- home/common/claude-code/README.md | tail -1
just agent-instruction-budget 2>&1 | tail -1
```

Expected: exit 0, `1 file changed` in the stat, and a last line `check: pass`.

- [ ] **Step 4: Commit**

```bash
git add home/common/claude-code/README.md
```

Commit through `launch-commit` with the message `docs(claude-code): the base policy, the compiled policy and the repair command (issue 126)`.

- [ ] **Step 5: Run the branch gates on the committed head**

Run the half-wired gate of Global Constraints. Expected: exit 0, no `half-wired` line.

- [ ] **Step 6: Measure the evidence rows**

With a clean tree (`git status --porcelain` empty), read-only:

```bash
for n in 210 367 368; do
  gh issue view "$n" --repo fagenorn/nix-config --json number,state,stateReason \
    -q '[.number, .state, .stateReason] | @tsv'
done
git grep -c elevenyellow HEAD -- home/common/claude-code/default.nix || echo "no literal Nodo row"
git rev-parse HEAD
```

Expected: three lines ending `CLOSED	COMPLETED`, then `no literal Nodo row`, then the head commit. Any other state for issue 210 leaves `AC1` and `AC4`–`AC7` unmet; any other state for 367 or 368, or a count from `git grep`, leaves `AC10` unmet.

Report for the acceptance record: for `AC1` and `AC4`–`AC7` the issue 210 line (the 2026-09-27 scope split moved those criteria there); for `AC10` the 367 and 368 lines and the `git grep` line; each with the head commit, the date and the clean-tree condition. Report `AC9` as `human_pending`, naming who makes the judgment and when: the orchestrating session, after this pull request merges, by one `just switch` and one Nodo pull request into `dev` with its merge through the derived guard (owner decision 5 of 2026-10-11). If that switch's compile cannot fetch or reach the provider, the proof reports that outcome and whether `claude-guard-policy` repaired it (spec `## Acceptance and hold`).

`AC2`, `AC3` and `AC8` are code rows: sdd's final gate runs their tests on the final head.
