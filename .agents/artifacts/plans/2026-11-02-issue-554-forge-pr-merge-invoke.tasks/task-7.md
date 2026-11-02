# Task 7: Native certification against the sandbox

Per D10, D11 and D19; spec §8 and §9. Read the plan root's Global Constraints first. This is the only task with real GitHub effects.

**Stop rule (human gate).** Launch the harness openly, through the Bash tool and `launch-scope exec`, in the foreground. Stop and report `blocked_on: human_gate`, naming the refused step and its message, when any of these happens:
- a permission guard, hook, prompt or sandbox policy refuses that launch;
- one of these is refused or denied: the sandbox repository's creation, its protection or `delete_branch_on_merge` setup, a push, a status, a PR, a merge or a close on it.

Never route around a refusal: no other command spelling, no direct `gh` or `git` call in place of the harness, no changed permission setting, no disabled signing, no other repository. Then commit only Step 1's harness and recipe (Step 6a), and leave the evidence test, the evidence file and the README sentence out. Never mutate `fagenorn/nix-config` or `elevenyellow/jarbird`, and never touch any repository's protection except the sandbox's.

**Files:**
- Create: `tests/release_merge_certification.py`
- Modify: `justfile` (new recipe `release-merge-certification`)
- Create: `.agents/artifacts/evidence/release-554-native-certification.json` (written by the harness run, committed only when `result` is `passed`)
- Modify: `tests/test_release_evidence.py` (new `MergeCertificationEvidenceTest`)
- Modify: `home/common/claude-code/README.md` (the guard/core paragraph's last sentence, only with passing evidence)

**Interfaces:**
- Consumes:
  - `forge_adapter.invoke`, `forge_adapter.inspect` and `forge_adapter.describe` (Tasks 2–3).
  - `agent_tools.canonical.telemetry_digest`.
  - `agent_tools.github_remote.github_slug`.
  - The spelling fixture's `pr_merge.merge` row.
- Produces:
  - `tests/release_merge_certification.py`, with no `test_` prefix, so no suite collects it. Its module constants are:
    - `SANDBOX = "fagenorn/release-merge-sandbox"`, which no argument or environment variable overrides;
    - `MARKER = "nix-config issue 554 release-merge certification sandbox"`;
    - `CONTEXT = "release-merge-certification"`;
    - `SCHEMA = "release-merge-certification/v1"`.

    Its entry point is `main(argv: list[str] | None = None) -> int`, with the required options `--scratch DIR` (an existing absolute directory) and `--output FILE`. It exits 0 when `result` is `passed`, 1 when the evidence was written but failed, and 2 on a refusal before any mutation (a bad argument, a sandbox without the marker).
  - The `justfile` recipe, placed beside `agent-gate-bundle`, with the summary comment directly above it:

    ```
    # Certify issue 554's forge pr_merge against the live sandbox repository (real GitHub calls)
    release-merge-certification *args:
      PYTHONPATH="{{agent_tools_path}}" python3 -m tests.release_merge_certification {{args}}
    ```
  - The evidence object, written with `json.dumps(…, indent=2, sort_keys=True) + "\n"`: `{schema, issue: 554, repository: SANDBOX, actor, implementation: {commit, pr_merge_descriptor_digest}, protection: {strict, required_contexts, enforce_admins}, spelling, guard: "recording-shim", rows: [{id, pr, bound: {head, base_tip}, attempts: [{via, outcome, detail}], after: {state, base_tip, merge_commit, parents}, passed}], result, started_at, finished_at}`.
    - `via` is `adapter`, `argv` or `graphql`, and `outcome` is `accepted` or `refused`.
    - `detail` is the first line of stderr, at most 240 characters, or the GraphQL error's `type: message`.
    - `implementation.commit` is `git rev-parse HEAD` of the checkout that runs the harness.
    - `pr_merge_descriptor_digest` is `telemetry_digest(forge_adapter.describe()["operations"]["pr_merge"])` (D19).
    - `after.merge_commit` and `after.parents` are null while the PR is not merged.
    - Times are UTC ISO 8601 with `Z`.

**Invariants:**
- Every child the harness starts runs with `GITHUB_TOKEN` and `GH_TOKEN` removed. Every `gh` mutation names `SANDBOX` through `--repo SANDBOX`, `repos/SANDBOX/…` or `gh repo create SANDBOX`, and one helper asserts that before it runs a mutation. Every `git` mutation runs in the scratch clone, whose `origin` the harness checks once with `github_slug(...) == SANDBOX` before its first push.
- Before any mutation, `gh api repos/SANDBOX --jq .description`:
  - on 404, it creates the repository with `gh repo create SANDBOX --public --add-readme --description MARKER`;
  - with any other description, it refuses (exit 2) and mutates nothing.
- Setup, on every run:
  1. `gh api --method PATCH repos/SANDBOX -F delete_branch_on_merge=false`.
  2. `gh api --method PUT repos/SANDBOX/branches/main/protection --input <file>` with `{"required_status_checks": {"strict": true, "checks": [{"context": CONTEXT, "app_id": -1}]}, "enforce_admins": true, "required_pull_request_reviews": null, "restrictions": null}`.
  3. `gh repo clone SANDBOX <scratch>/sandbox-<run>`, where `<run>` is a UTC `YYYYMMDDTHHMMSSZ` stamp.
- Each row's PR comes from a fresh `cert-<run>-<row>` branch made from `main`'s current tip. The branch carries one commit adding `cert/<run>-<row>.txt`; commits inherit the host's git config, and signing is never disabled. The harness pushes the branch, posts `gh api --method POST repos/SANDBOX/statuses/<sha> -f state=success -f context=CONTEXT`, and opens `gh pr create --repo SANDBOX --base main --head cert-<run>-<row> --title "cert <run> <row>" --body "issue 554 certification"`. Before any merge attempt it polls `gh pr view <n> --repo SANDBOX --json mergeStateStatus` every 2 s, for at most 90 s, until the state is not `UNKNOWN`.
- The floor gate: before row a's first invoke, `forge_adapter.inspect` on row a's PR must report `facts.protection == {"status": "protected", "strict": True, "required_contexts": [CONTEXT], "enforce_admins": True}`. Otherwise the run records `result: failed` and stops before any merge. `protection` in the evidence is those three members.
- Row a (base unchanged) runs with the working directory set to the clone and a recording `claude-bash-lifecycle-guard` shim first on `PATH`. The shim appends its stdin's `tool_input.command` to a file in the scratch directory and exits 0. Its parameters are `{action: "merge", operation: "pr_merge", config: {}, target: {kind: "github_repository", repository: SANDBOX, branch: "main"}, candidate: {version: "v0.0.1", commit: H, merge: {pr, base_tip: B0}}}`. It runs `invoke`, `inspect`, `invoke`, `inspect`. It passes when:
  - the first invoke is `accepted`;
  - the inspect is `satisfied`, and the merge commit's parents read back as `[B0, H]`;
  - the second invoke is `rejected` with reference `pr_not_open: MERGED`, and `main` still points at that merge commit;
  - the second inspect is `satisfied`;
  - the shim recorded exactly one command, equal to `gh pr merge <pr> --repo SANDBOX --merge --match-head-commit <H>`, which is the evidence `spelling`.
- Row b (base moved to a commit the head lacks) binds H and B0. It then opens, statuses and merges a side PR with `gh pr merge <side> --repo SANDBOX --merge --match-head-commit <side head>`, so `main` moves to B1, waits for row b's `mergeStateStatus`, and attempts:
  - (b1) the rendered argv `gh pr merge <pr> --repo SANDBOX --merge --match-head-commit H`;
  - (b2) `gh api graphql -f query='mutation($id:ID!,$head:GitObjectID!){mergePullRequest(input:{pullRequestId:$id,expectedHeadOid:$head,mergeMethod:MERGE}){pullRequest{state}}}' -f id=<PR node id> -f head=H`.

  It passes when both are refused (non-zero exit, or GraphQL `errors`), the PR is still `OPEN` and `main` is still B1.
- Row c (head mismatch) binds H, then pushes a second commit H′ to the head branch and posts a success status on it. After the wait, it attempts the rendered argv with `--match-head-commit H`. It passes when that is refused, the PR is still `OPEN` and `main` is unchanged.
- Cleanup closes row b's and row c's PRs (`gh pr close <n> --repo SANDBOX`), deletes no branch and never deletes the repository. `result` is `passed` only when all three rows pass. The evidence never holds a token, a header or a raw transcript.

- [ ] **Step 1: Write the harness and the recipe**

Write `tests/release_merge_certification.py` and the recipe per Interfaces and Invariants. The module docstring states that it makes live GitHub calls against `SANDBOX` only, that nothing in the repository runs it, and that it cites issue 554 D10, D11, D19. Check the plumbing hermetically first:

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -c "import tests.release_merge_certification as h; assert h.SANDBOX == \"fagenorn/release-merge-sandbox\"; print(\"ok\")"'`
Expected: `ok`, with no network call.

Run: `bash -c 'just release-merge-certification --scratch /nonexistent --output /tmp/x.json; test $? -eq 2'`
Expected: exit 0 (the harness refused, exit 2, before any call).

- [ ] **Step 2: Write the failing evidence test**

Add to `tests/test_release_evidence.py`:

```python
CERTIFICATION = REPO_ROOT / ".agents/artifacts/evidence/release-554-native-certification.json"
SPELLINGS = REPO_ROOT / "tests/fixtures/forge-adapter-spellings.json"


class MergeCertificationEvidenceTest(unittest.TestCase):
    """Issue 554 AC4, D10, D11, D19: the native certification is real, passing and current."""

    def setUp(self):
        self.text = CERTIFICATION.read_text(encoding="utf-8")
        self.evidence = json.loads(self.text)
        self.rows = {row["id"]: row for row in self.evidence["rows"]}

    def test_the_sandbox_run_passed_under_the_floor(self):
        from . import release_merge_certification as harness
        evidence = self.evidence
        self.assertEqual((evidence["schema"], evidence["issue"], evidence["repository"],
                          evidence["guard"], evidence["result"]),
                         ("release-merge-certification/v1", 554, harness.SANDBOX, "recording-shim", "passed"))
        self.assertEqual(sorted(self.rows), ["a", "b", "c"])
        self.assertTrue(all(row["passed"] for row in evidence["rows"]))
        self.assertEqual(evidence["protection"], {"strict": True, "required_contexts": [harness.CONTEXT],
                                                  "enforce_admins": True})
        for marker in ("gho_", "ghp_", "github_pat_", "Authorization", "Bearer "):
            self.assertNotIn(marker, self.text)

    def test_each_row_shows_what_github_did(self):
        a, b, c = self.rows["a"], self.rows["b"], self.rows["c"]
        self.assertEqual([(t["via"], t["outcome"]) for t in a["attempts"]],
                         [("adapter", "accepted"), ("adapter", "refused")])
        self.assertEqual((a["after"]["state"], a["after"]["parents"]),
                         ("MERGED", [a["bound"]["base_tip"], a["bound"]["head"]]))
        self.assertEqual([(t["via"], t["outcome"]) for t in b["attempts"]],
                         [("argv", "refused"), ("graphql", "refused")])
        self.assertNotEqual(b["after"]["base_tip"], b["bound"]["base_tip"])
        self.assertEqual([(t["via"], t["outcome"]) for t in c["attempts"]], [("argv", "refused")])
        self.assertEqual(c["after"]["base_tip"], c["bound"]["base_tip"])
        for row in (b, c):
            self.assertEqual((row["after"]["state"], row["after"]["merge_commit"]), ("OPEN", None))

    def test_the_spelling_and_descriptor_are_the_current_ones(self):
        """D11: a spelling or descriptor change demands a new certification."""
        fixture = json.loads(SPELLINGS.read_text(encoding="utf-8"))
        row = next(r for r in fixture["rows"] if r["id"] == "pr_merge.merge")
        canonical, a = fixture["canonical"], self.rows["a"]
        expected = (row["raw"].replace(canonical["slug"], self.evidence["repository"])
                    .replace(f" {canonical['pr']} ", f" {a['pr']} ")
                    .replace(canonical["commit"], a["bound"]["head"]))
        self.assertEqual(self.evidence["spelling"], expected)
        implementation = self.evidence["implementation"]
        self.assertEqual(implementation["pr_merge_descriptor_digest"],
                         telemetry_digest(forge_adapter.describe()["operations"]["pr_merge"]))
        self.assertRegex(implementation["commit"], r"^[0-9a-f]{40}$")
```

Add the imports `from agent_tools import forge_adapter` and `from agent_tools.canonical import telemetry_digest`. `tests/test_release_evidence.py` is already in the `agent-workflow-tests` list.

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_evidence.py -k MergeCertification 2>&1 | tail -4'`
Expected: FAIL, with `FileNotFoundError` for the evidence file.

- [ ] **Step 3: Run the certification (real GitHub effects; stop rule applies)**

Run (timeout 1800 s), from the worktree root: `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- just release-merge-certification --scratch <launch-scope scratch dir> --output .agents/artifacts/evidence/release-554-native-certification.json`
Expected: exit 0 and `"result": "passed"`. On exit 1, read the failing row's `detail`. Fix only the harness's own defect and re-run, at most twice. A failure that shows the adapter or the spec's premise wrong (for example, GitHub merges row b) is a finding: commit nothing from this step and report it with the evidence path. Any permission refusal falls under the stop rule.

- [ ] **Step 4: Document the admission**

Only with passing evidence: in `home/common/claude-code/README.md`'s guard/core paragraph, replace "future core admission waits for the named enforcement and conformance work." with a sentence that names this delivery. The release core's forge `pr_merge` invoke is admitted under issue 554: the adapter refuses it unless protection holds strict required checks with admin enforcement, and `.agents/artifacts/evidence/release-554-native-certification.json` is its native certification. Any other core admission still waits for the named enforcement and conformance work.

- [ ] **Step 5: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_release_evidence.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `if git grep -nE 'jarbird|elevenyellow|fagenorn/nix-config' -- tests/release_merge_certification.py; then exit 1; fi`
Expected: exit 0 (the harness names no repository but the sandbox).

- [ ] **Step 6: Commit**

(6a, always) The harness and the recipe:

```bash
git add tests/release_merge_certification.py justfile
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-554/T7): add the sandbox merge certification harness" -m "<trailer>"
```

(6b, only with passing evidence) The evidence, its test and the README sentence:

```bash
git add .agents/artifacts/evidence/release-554-native-certification.json tests/test_release_evidence.py home/common/claude-code/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-554/T7): record the native pr_merge certification" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":7,"records":[{"bounds":[{"added_lines":420,"boundary":"all","deleted_lines":0,"record_bytes":30720,"support":{"covers":["r7a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r7a","last_task":7,"owner":7,"path":"tests/release_merge_certification.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r7b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7b","last_task":7,"owner":7,"path":"justfile"},{"bounds":[{"added_lines":130,"boundary":"all","deleted_lines":0,"record_bytes":6144,"support":{"covers":["r7c"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r7c","last_task":7,"owner":7,"path":".agents/artifacts/evidence/release-554-native-certification.json"},{"bounds":[{"added_lines":70,"boundary":"all","deleted_lines":0,"record_bytes":6144,"support":{"covers":["r7d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7d","last_task":7,"owner":7,"path":"tests/test_release_evidence.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":7168,"support":{"covers":["r7e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7e","last_task":7,"owner":7,"path":"home/common/claude-code/README.md"}]}}
```
