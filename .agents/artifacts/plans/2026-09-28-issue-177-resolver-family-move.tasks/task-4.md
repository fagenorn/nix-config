# Task 4: Re-point the living documents and verify the slice

Decisions: D3, D4, D5, D10, D12; parent D14, D15. Spec sections "Living
documents (D10)" and "Acceptance criteria and how each is verified". Work from
the worktree root. `PK` = `python/agent_tools`,
`T` = `home/common/agent-skills/tests`.

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Tasks 1–3 as committed. The launchers `resolve-project`,
  `conformance` and `adopt-project` are in the built `.agents/bin`, and
  `agent_tools.host_admission` exists.
- Produces: no code. It produces the one-sentence `CLAUDE.md` re-point and the
  recorded end-to-end verification.

**Invariants:**
- `CLAUDE.md` changes in exactly one place: the parenthetical
  `validated by \`host_admission.py\`` (here `\`` is a literal backtick). The
  "Agent helper package" paragraph stays as it is, because the remaining flat
  helpers still live in `scripts/` until #178 (D10).
- The generated `@.agents/instructions/bootstrap.md` import line is untouched,
  so `resolve-project check-projections` still passes.
- Skill prose, the agent-skills README, the standards shard and every record
  under `.agents/artifacts` are unchanged.

- [ ] **Step 0: Record the starting commit**

Run: `START=$(git rev-parse HEAD); BASE=$(git merge-base HEAD origin/main); B=$(mktemp -d); echo "$START $BASE $B"`.
Substitute the printed values literally wherever later steps write `${START}`,
`${BASE}` or `$B`. `BASE` is the PR base, where the family was still flat.

- [ ] **Step 1: Re-point CLAUDE.md**

In `CLAUDE.md`, replace `validated by \`host_admission.py\`` with
`validated by \`agent_tools.host_admission\``. Touch nothing else.

Run: `grep -c 'validated by `agent_tools.host_admission`' CLAUDE.md; grep -c 'host_admission\.py' CLAUDE.md`
Expected: `1`, then `0`. At `$START` the first command prints `0` and the
second prints `1`.

Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.resolve_project check-projections --repo-root "$PWD" >/dev/null; echo "exit=$?"`
Expected: `exit=0`.

- [ ] **Step 2: Final acceptance greps (AC3, D3)**

```bash
set -e
T=home/common/agent-skills/tests
if git grep -nE "importlib|SourceFileLoader|spec_from|sys\.path|__file__|loaded_from" -- python/agent_tools; then exit 1; fi
if git grep -nE "importlib|SourceFileLoader|spec_from|sys\.path|loaded_from" -- $T/test_resolve_project.py $T/test_resolve_platform.py $T/test_resolve_platform_status.py $T/conformance_test_support.py $T/test_conformance.py $T/test_conformance_checks.py $T/test_conformance_registry.py $T/test_adopt_project.py $T/test_adopt_project_boundaries.py $T/test_adopt_apply.py $T/test_adopt_verify.py; then exit 1; fi
if git grep -nE "platform\.library\.missing|adopt\.library\.missing|library_unavailable" -- ':!.agents/artifacts'; then exit 1; fi
if git grep -n "host_admission\.py" -- CLAUDE.md; then exit 1; fi
echo slice-clean
```

Expected: `slice-clean`. At `${BASE}` the second, third and fourth checks
match. The first guards the moved modules, which did not exist there yet.

- [ ] **Step 3: Build, the installed layout, and AC2/AC4**

Run: `just build 2>&1 | tail -3`
Expected: success.

```bash
H=$(nix-store --query --requisites ./result | grep -- '-home-manager-files$')
ls "$H/.agents/lib/python"
if ls "$H/.agents/bin" | grep -E '^conformance-(registry|checks)$'; then echo LEFTOVER; fi
for c in resolve-project conformance adopt-project; do sed -n 's/.*-I -m \(agent_tools\.[a-z_]*\).*/\1/p' "$H/.agents/bin/$c"; done
```

Expected: the listing is exactly `artifact_budget.py delivery_model
host_admission.py workflow_delivery.py workflow_delivery_build.py
workflow_delivery_wire.py`. No `LEFTOVER` line appears. The loop prints
`agent_tools.resolve_project`, `agent_tools.conformance` and
`agent_tools.adopt_project`.

Run: `just agent-installed-skill-tests 2>&1 | grep -E "^Ran |^OK|FAILED"`
Expected: `OK`. `test_promotion_installed` passes against the built
`conformance` launcher (AC1).

- [ ] **Step 4: The demo (shown, not committed)**

Give the built tree a writable `HOME`, so that `adopt-project verify` may
create its state root. Then run the three commands:

```bash
D=$(mktemp -d); cp -RL "$H/.agents" "$D/"
HOME="$D" "$D/.agents/bin/resolve-project" resolve --repo-root "$PWD" | head -c 200; echo
HOME="$D" "$D/.agents/bin/conformance" run --purpose doctor --offline --repo-root "$PWD" | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r["outcome"], [c["status"] for c in r["checks"] if c["id"]=="repository.contract.resolvable"])'
HOME="$D" "$D/.agents/bin/adopt-project" verify --repo-root "$PWD" | head -c 300; echo
```

Expected:
- The resolver prints the snapshot, starting `{"bindings":`.
- The conformance line shows an outcome that is not `failed`, and
  `['passed']` for `repository.contract.resolvable`.
- `adopt-project verify` prints one JSON object. That is a report, or a
  documented `adopt_failure` refusal whose `repair_id` is not
  `adopt.resolver.unavailable` or `adopt.resolver.unexpected_exit`. Either way,
  its resolver child ran through `sibling_argv`'s isolated branch: the
  launcher runs `-I`, so `sys.flags.isolated` is 1.

Record the three outputs in the task handback.

- [ ] **Step 5: Full suite, then commit**

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests > "$B/t4.log" 2>&1; tail -3 "$B/t4.log"`
Expected: `Ran NBASE-17 tests` and `OK (skipped=2)`.

```bash
git add CLAUDE.md
git commit -m "docs: re-point the host admission library to agent_tools"
```

The message ends with the plan's trailer lines. Run: `git status --porcelain`.
Expected: no output.
