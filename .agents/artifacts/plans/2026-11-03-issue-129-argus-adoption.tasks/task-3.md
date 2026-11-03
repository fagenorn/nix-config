# Task 3: Argus's contract commit, pre-flight and doctor report 1

Spec § 1, § 2 and § 4 steps 3–4, per D1–D5, D9, D10, D17 and D19; it produces doctor report 1 for AC3. The contract is committed in a scratch clone only. Nothing is pushed here.

**Files:**
- Modify: `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` (`E`)

**Interfaces:**
- Consumes: Task 2's `Platform version: <V>` line in `E` (the switch is installed); `tests/fixtures/release/argus-shaped-profile.json` in this worktree; `git@github.com:fagenorn/argus.git`.
- Produces: the clone `$SCR/argus-129` on local branch `project-contract`, whose `HEAD` is the contract commit `K` on top of `origin/main` `B`, with `node_modules` installed. Task 4 consumes it.
- Produces: the section `## Task 3 — Contract commit and doctor report 1`. It holds the lines `Argus base: <B>`, `Contract commit: <K>` and `Contract sha256: <hex>`, plus one fenced `json` block with the contract as a single compact line. Task 4 uses that line to rebuild the commit if the clone is gone.

**Invariants:**
- `.agents/project.json` is the only path the contract commit changes (`git show --name-only --format= K` prints exactly that path).
- The contract is exactly the generator's output for `V`. Change it only toward a truthful value of the same member, and only when a pre-flight command fails because its argv does not match Argus's CI step. Never drop or narrow a verification step (D4). Any other reason to change the contract is a stop: a contract gap, or `BLOCKED` with the refusal.
- Doctor report 1 judges `K` with the projection not yet written. A `host` check whose status is `suppressed` is no finding (spec § 6).

- [ ] **Step 1: Confirm the red state**

Run: `grep -c '^## Task 3 — Contract commit and doctor report 1$' .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md`
Expected: `0` (exit 1). Read `V` from `E`'s `Platform version:` line.

- [ ] **Step 2: Clone**

If `$SCR/argus-129` exists, remove it with `rm -rf "$SCR/argus-129"`; it is scratch from an earlier attempt of this task in this launch. Then run (timeout 600 s):
`launch-scope exec … -- git clone --quiet git@github.com:fagenorn/argus.git "$SCR/argus-129"`
`B=$(git -C "$SCR/argus-129" rev-parse HEAD)` must equal `git -C "$SCR/argus-129" rev-parse origin/main`. Also `git -C "$SCR/argus-129" symbolic-ref refs/remotes/origin/HEAD` must print `refs/remotes/origin/main`. Then run `git -C "$SCR/argus-129" switch --quiet -c project-contract`.

- [ ] **Step 3: Write the contract**

Run from the worktree root (timeout 60 s), with `<V>` replaced by its literal value:

```bash
python3 -I - tests/fixtures/release/argus-shaped-profile.json "$SCR/argus-129/.agents/project.json" '<V>' <<'EOF'
import json, pathlib, re, sys
fixture, out, version = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version)
assert match, "platform version is not strict SemVer"
flags = ["--experimental-strip-types", "--experimental-sqlite", "--disable-warning=ExperimentalWarning"]
def cmd(*argv):
    return {"argv": list(argv), "cwd": ".", "env": []}
contract = {
  "schema_version": 1,
  "platform": {"min_inclusive": version, "max_exclusive": f"{int(match.group(1)) + 1}.0.0"},
  "project": {"id": "fagenorn/argus", "name": "argus"},
  "bindings": {
    "vcs": {"kind": "git", "default_branch": "main", "integration_branch": "main",
            "branch_pattern": "issue-<num>-<slug>",
            "worktree": {"root": ".worktrees", "prefix": "worktree-"},
            "commit": {"co_authored_by": True, "signed": True},
            "merge": {"strategy": "merge", "delete_branch": True,
                      "required_checks": ["memory foundation (unit + forced checks)"]}},
    "tracker": {"kind": "github", "cli": "gh", "repo_slug": "fagenorn/argus",
                "credential_env": {"unset_before_invocation": ["GITHUB_TOKEN", "GH_TOKEN"]}},
    "paths": {"artifacts": {"specs": ".agents/artifacts/specs", "plans": ".agents/artifacts/plans"},
              "context": ["docs/CONTEXT-MAP.md"], "standards": ["docs/standards/README.md"],
              "architecture": ["docs/guides/architecture.md"],
              "operations": [], "hints": [], "rejections": []},
    "commands": {
      "install": cmd("npm", "ci"),
      "coverage-guard": cmd("node", "--test", *flags, "tests/docs/ci-covers-every-test.test.ts"),
      "unit-tests": cmd("node", "--test", *flags, "tests/**/*.test.ts"),
      "forced-checks": cmd("node", *flags, "eval/suites/memory/checks/forced-checks.ts"),
      "recall-cap-checks": cmd("node", *flags, "eval/suites/memory/checks/recall-cap.ts"),
      "build-notifier": cmd("bash", "daemon/notifyd/build.sh")},
    "workflow": {"verification": ["install", "coverage-guard", "unit-tests", "forced-checks",
                                  "recall-cap-checks"],
                 "orchestration": {"max_parallel": 2, "attempt_budget_minutes": 240},
                 "review": {"plan": None, "code": None}},
    "deploy": {"adapter": "none", "command": None, "config": {}}},
  "capabilities": {name: {"support": support} for name, support in [
    ("tracker", "supported"), ("worktrees", "supported"), ("knowledge.context", "supported"),
    ("knowledge.standards", "supported"), ("knowledge.architecture", "supported"),
    ("knowledge.hints", "unsupported"), ("verification", "supported"),
    ("review.plan", "unsupported"), ("review.code", "unsupported"), ("deploy", "unsupported")]},
  "projections": [{"id": "claude-instructions", "agent": "claude", "kind": "managed_import",
                   "target": "CLAUDE.md", "source": "AGENTS.md"}],
  "release": {"profiles": {
    "local-host": json.loads(fixture.read_text(encoding="utf-8")),
    "forge-main": {
      "profile_version": 1,
      "target": {"environment": "github-main", "concurrency_keys": ["release/fagenorn/argus"]},
      "requirements": {"adapters": {"forge": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"}}},
      "bindings": {"adapters": {"forge": {"adapter": "github-forge"}},
                   "targets": {"repository": {"adapter": "forge", "kind": "github_repository",
                                              "repository": "fagenorn/argus", "branch": "main"}},
                   "principals": {}, "credentials": {}},
      "publication": "none", "activation": "none",
      "proof": {"convergence_window_ms": 1800000, "obligations": []},
      "recovery": {"units": {}}, "limits": {}}}}}
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
print(json.dumps(contract, separators=(",", ":")))
EOF
```

Expected: exit 0, printing the compact line. Keep that line for Step 8. Then run `shasum -a 256 "$SCR/argus-129/.agents/project.json"` and keep the hex digest.

- [ ] **Step 4: Commit in the clone**

Run `git -C "$SCR/argus-129" add .agents/project.json`, then:
`env -C "$SCR/argus-129" launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "chore: add the project contract" -m "Declares Argus's project policy for the cross-agent project system, adopted under https://github.com/fagenorn/nix-config/issues/129." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`
Then check: `K=$(git -C "$SCR/argus-129" rev-parse HEAD)`; `git -C "$SCR/argus-129" cat-file commit "$K" | grep -c '^gpgsig '` prints `1`; `git -C "$SCR/argus-129" show --name-only --format= "$K"` prints only `.agents/project.json`.

- [ ] **Step 5: Resolve at `K`**

Run (timeout 120 s): `resolve-project resolve --repo-root "$SCR/argus-129"`
Expected: the refusal `invalid_projection`, repair `projection.claude-instructions.stale`, and nothing else: `CLAUDE.md` lacks the managed line until the adoption plan's projection operation writes it. Any other refusal is a stop. If the refusal names a member whose value Argus's evidence supports but the resolver cannot express, it is a contract gap. Otherwise return `BLOCKED` with the refusal verbatim.

- [ ] **Step 6: Pre-flight the verification commands (D4)**

In CI order, run each command in the clone root and record its exit status and last 5 lines. Use `launch-scope exec … -- env -C "$SCR/argus-129" <argv>`, where `<argv>` is:

| Id | argv (single-quote the glob so no shell expands it) | Timeout |
|---|---|---|
| `install` | `npm ci` | 900 s |
| `coverage-guard` | `node --test --experimental-strip-types --experimental-sqlite --disable-warning=ExperimentalWarning tests/docs/ci-covers-every-test.test.ts` | 900 s |
| `unit-tests` | `node --test --experimental-strip-types --experimental-sqlite --disable-warning=ExperimentalWarning 'tests/**/*.test.ts'` | 1800 s |
| `forced-checks` | `node --experimental-strip-types --experimental-sqlite --disable-warning=ExperimentalWarning eval/suites/memory/checks/forced-checks.ts` | 900 s |
| `recall-cap-checks` | `node --experimental-strip-types --experimental-sqlite --disable-warning=ExperimentalWarning eval/suites/memory/checks/recall-cap.ts` | 900 s |

Expected: every exit is 0, and `git -C "$SCR/argus-129" status --porcelain` stays empty. A failure stops the task: return `BLOCKED` with that step's output tail. The only permitted edit is the Invariants' truthful-command correction, which is followed by a new commit (Step 4) and a full re-run of this step.

- [ ] **Step 7: Doctor report 1 (D10)**

Run (timeout 900 s): `launch-scope exec … -- conformance run --purpose doctor --repo-root "$SCR/argus-129" > "$SCR/doctor-1.json"`, then:

```bash
python3 -I - "$SCR/doctor-1.json" <<'EOF'
import json, sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
print("outcome", json.dumps(report["outcome"]))
for check in report["checks"]:
    if check["id"].startswith("host.") or check["status"] != "passed":
        print(check["id"], check["status"], check.get("reason_code"), check.get("repair_id"))
print("repairs", json.dumps(report.get("repairs")))
EOF
```

Expected: no `host.*` line says `failed`, and `host.policy_path.no_follow_readable` and `host.executor.helper_on_path` say `passed`. Every repository finding is listed for Task 4 to match; `repository.ignore.runtime_sentinel` and the projection drift are expected.
If a `host` check `failed`, apply only the repair the report names for it, and only when that repair is a host action you can take without editing nix-config or Argus. Then re-run this step. If the repair needs the owner (`safety_class` `user_action`), return `BLOCKED human_gate`, naming the check, the repair id and its safety class; the run resumes at this step. A repair that needs a central nix-config change is a contract gap.

- [ ] **Step 8: Write the section**

Append `## Task 3 — Contract commit and doctor report 1` to `E` with the lines `Argus base: <B>`, `Contract commit: <K>`, `Contract sha256: <hex>`, `Platform interval: <V> to <major+1>.0.0` and the Step 5 refusal. Add a fenced `json` block holding the compact line from Step 3, then a pre-flight table `| Id | Exit | Tail |`. Close with doctor report 1: outcome, every `host.*` check with its status, and every non-`passed` check with its `reason_code` and `repair_id`. Add the UTC time of each run.

- [ ] **Step 9: Verify and commit**

Run:

```bash
set -e
E=.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
test "$(wc -c < "$E")" -le 30720
test "$(grep -c '^## Task 3 — Contract commit and doctor report 1$' "$E")" -eq 1
grep -Eq '^Contract commit: [0-9a-f]{40}$' "$E"
test "$(git -C "$SCR/argus-129" rev-parse HEAD)" = "$(sed -n 's/^Contract commit: //p' "$E")"
if grep -q '^host\.[a-z_.]* failed' "$E"; then exit 1; fi
```

Expected: exit 0.

```bash
git add .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-129/T3): Argus contract commit and doctor report 1" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"97eeed52ee1d2728a7f130e26cbe224f994dba39","head":"186316a098f0d93861a79d41b6af01518c4a3dd7"}],"commit_subject_bytes":[64,64],"id":3,"records":[{"bounds":[{"added_lines":768,"boundary":"all","deleted_lines":0,"record_bytes":31744,"support":{"covers":["e1","e2","e3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"e3","last_task":8,"owner":3,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md"}]}}
```
