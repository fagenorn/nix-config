# Task 2: Host compile evidence, final gate and acceptance record

Spec § Test seams (host evidence), per D6 and D7. This task changes no code. It builds the final head, compiles the guard policy from the live fleet registry into a scratch file with the built base policy, confirms Arcwave's row with the built row check once, runs the final gate and writes the acceptance record.

**Files:**
- Create: `.agents/artifacts/plans/2026-10-14-issue-384-arcwave-derived-row.acceptance.md`

**Interfaces:**
- Consumes (Task 1): the built base policy with `integration_bases == {}`; the guard-suite test `test_an_arcwave_shaped_project_is_judged_by_its_compiled_row`. (Build): the built `claude-guard-row-check`, a script whose lines include `export PATH="<store tool path>:$PATH"` and `exec <guard-policy launcher> derive "$@"`. (Host): the fleet registry under `~/.agents/state/`, Arcwave's registered checkout and its `origin`, the `gh` keyring credential.
- Produces: the acceptance record with rows `AC1`–`AC4`.

**Invariants:**
- Never run `just switch` or the installed `claude-guard-policy`, and write nothing under `~/.agents/state/`: the compile's `--output` lies under the scratch root (D6).
- A refusal of `fagenorn/arcwave` in step 2 is reported, not fixed: record `AC1` as `not met` with the refusal's `reason_code` and `detail`, and return the record to the controller without editing code (spec § Test seams, Host evidence).
- A refusal of another project does not decide `AC1`; record it under Conditions.

- [ ] **Step 1: Build and locate the built paths**

Run (timeout 3600 s):

```bash
set -e -o pipefail
just build 2>&1 | tail -3
REQ=$(nix-store --query --requisites ./result)
CHECK=$(printf '%s\n' "$REQ" | grep -- '-claude-guard-row-check$')
BASE=$(printf '%s\n' "$REQ" | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$')
test "$(printf '%s\n' "$CHECK" | wc -l)" -eq 1
test "$(printf '%s\n' "$BASE" | wc -l)" -eq 1
LAUNCHER=$(sed -n 's|^exec \(/nix/store/[^ ]*\) derive "\$@"$|\1|p' "$CHECK")
TOOLS=$(sed -n 's|^export PATH="\(.*\):\$PATH"$|\1|p' "$CHECK")
test -x "$LAUNCHER"
test -n "$TOOLS"
python3 -I -c 'import json, sys; assert json.load(open(sys.argv[1]))["integration_bases"] == {}' "$BASE"
printf 'CHECK=%s\nBASE=%s\nLAUNCHER=%s\nTOOLS=%s\n' "$CHECK" "$BASE" "$LAUNCHER" "$TOOLS"
```

Expected: exit 0 and four paths printed. A failing line means the build does not carry Task 1's base policy or the row check changed shape; stop.

- [ ] **Step 2: AC1 (a), the scratch compile against the live registry**

Run (timeout 600 s), with `<scratch>` the `launch-scope scratch` root:

```bash
set -o pipefail
D=<scratch>/i384-acceptance
mkdir -p "$D"
status=0
env PATH="$TOOLS:$PATH" "$LAUNCHER" compile --base "$BASE" --output "$D/policy.json" \
  > "$D/compile-report.json" 2> "$D/compile-stderr.txt" || status=$?
echo "compile exit $status"
python3 -I - "$D/compile-report.json" "$D/policy.json" <<'EOF'
import json, pathlib, sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text())
policy = pathlib.Path(sys.argv[2])
row = json.loads(policy.read_text())["derived_repositories"].get("fagenorn/arcwave") if policy.exists() else None
refusals = [r for r in report.get("refused", []) if "arcwave" in json.dumps(r)]
print(json.dumps({"derived": report.get("derived"),
                  "arcwave_row": row and [row["default_branch"], row["integration_branch"]],
                  "arcwave_refusals": refusals,
                  "other_refusals": [(r.get("project_id"), r.get("reason_code"))
                                     for r in report.get("refused", []) if r not in refusals]}))
sys.exit(0 if row and (row["default_branch"], row["integration_branch"]) == ("main", "dev")
         and "fagenorn/arcwave" in (report.get("derived") or []) and not refusals else 1)
EOF
```

Expected: the summary line shows `"fagenorn/arcwave"` in `derived`, `"arcwave_row": ["main", "dev"]`, `"arcwave_refusals": []`, and the script exits 0. `compile exit` is 0, or 1 only when `other_refusals` is non-empty.

Then confirm the row once with the built row check (timeout 120 s):

```bash
env -u GITHUB_TOKEN -u GH_TOKEN "$CHECK" --repository fagenorn/arcwave < /dev/null \
  | python3 -I -c 'import json, sys; r = json.load(sys.stdin); row = r.get("row") or {}; print(r.get("outcome"), row.get("default_branch"), row.get("integration_branch"))'
```

Expected: `derived main dev`.

- [ ] **Step 3: Final gate**

Run: `set -o pipefail; just agent-workflow-tests 2>&1 | tail -4` (timeout 3600 s). Expected: `OK`, exit 0.

Run: the guard-suite invocation (Global Constraints, timeout 1200 s). Expected: `OK`.

Run: the `tests/test_guard_policy.py` run (timeout 900 s). Expected: `OK`.

- [ ] **Step 4: The acceptance record**

Create `.agents/artifacts/plans/2026-10-14-issue-384-arcwave-derived-row.acceptance.md` with the heading `# Acceptance record — issue 384`, one sentence naming the host `mbp`, the date and the head commit, and one table with the columns `AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict`. Use the issue's four criteria verbatim (https://github.com/fagenorn/nix-config/issues/384) and the plan's Acceptance map kinds and checks. Fill the columns from this task's output:
- `AC1`: Observed holds step 2's summary line, the compile exit status and the row check's line. Conditions name the store paths of `$BASE` and `$CHECK`, that `--output` was the scratch file, any `other_refusals`, and that part (b) is the user's post-switch read of `derived_repositories["fagenorn/arcwave"]` from `~/.agents/state/guard/policy.json`. Verdict `met (pre-switch)`, or `not met`, per D7.
- `AC2`, `AC3`: the guard-suite result, naming the tests in the Acceptance map.
- `AC4`: the exit statuses and summary lines of `just build`, `just agent-workflow-tests`, the guard suite and `tests/test_guard_policy.py`.
- `Commit` is the head the evidence was taken on. Every other `Verdict` is `met` or `not met`.

- [ ] **Step 5: Commit**

```bash
git add .agents/artifacts/plans/2026-10-14-issue-384-arcwave-derived-row.acceptance.md
launch-commit … -- -m "docs(issue-384): acceptance record for Arcwave's derived row (issue 384)"
```

Verify: `grep -c '^| AC[1-4] |' .agents/artifacts/plans/2026-10-14-issue-384-arcwave-derived-row.acceptance.md` prints `4`, and `git status --short -- .agents/artifacts/plans` prints nothing.
