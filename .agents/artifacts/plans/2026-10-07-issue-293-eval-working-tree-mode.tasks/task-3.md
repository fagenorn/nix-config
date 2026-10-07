# Task 3: Four pipeline cases and the narrowed R8

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/evals/evals.json` (append case 5)
- Modify: `home/common/agent-skills/skills/sdd/evals/evals.json` (append case 4)
- Modify: `home/common/agent-skills/skills/ship-release/evals/evals.json` (append case 5, extend `notes`)
- Modify: `home/common/claude-code/skills/orchestrate-issues/evals/evals.json` (append case 7)
- Modify: `home/common/agent-skills/tests/test_eval_cases.py` (two methods, one constant, one helper)
- Modify: `home/common/agent-skills/tests/test_ship_release_contracts.py` (the R8 test only)

**Interfaces:**
- Consumes from Task 2:
  - setup kinds `shippable-worktree`, `planned-worktree` and `release-ready`;
  - the worktree `$WORK/worktree-issue-3-rename-flag`, also exported as `$PRE_WT`;
  - the assert env `BASE_MAIN`;
  - the plan file name `2026-10-07-issue-3-rename-flag.md` under the fixture's plans dir (`.claude/plans`);
  - `test_eval_cases.py`'s `REPO_ROOT`, `SKILL_ROOTS` and `EvalCasesTest`.
- Consumes from Task 1: `$OUT` (the result text plus stderr), and `assert-lib.sh`'s `fail`, `first_file`, `commits_touch` and `out_matches`.
- Produces: one `"mode": "pipeline"` case in each of the four files, which Task 4 runs as `ship-issue 5`, `sdd 4`, `ship-release 5` and `orchestrate-issues 7`.

**Invariants:**
- Existing cases are byte-identical. New cases are appended with the next free `id`.
- Every new prompt carries `Resolve once into a retained ResolvedProject.`, `A resolver refusal is fatal and values are never defaulted or inferred.` and an explicit bold stop.
- The ship-issue case never expects a push. It stops before `git push` and asserts that origin has no branch (D12).
- The ship-release case uses `release-ready` and runs through Phase 6. It asserts that no tag was pushed and no state file remains (D8, D15).
- The Global Constraints' forbidden eval strings and retired orchestrate anchors appear nowhere in the new text.
- R8 keeps its `notes` fragments (`plan-only`, `kind=none`, `fixture-repo`) and its single-branch `expected_output` fragments. Plan-only cases keep the non-execution guard, and a pipeline case must use `release-ready` (D8).

- [ ] **Step 1: Write the failing tests**

Add this constant and helper to `test_eval_cases.py`, below `SETUP_KINDS`:

```python
PIPELINE_SKILLS = ("from-issue", "ship-issue", "sdd", "ship-release", "orchestrate-issues")


def skill_cases(skill):
    for root in SKILL_ROOTS:
        path = root / skill / "evals/evals.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))["evals"]
    raise AssertionError(f"no evals.json for {skill}")
```

Add these two methods to `EvalCasesTest`:

```python
    def test_each_pipeline_skill_has_a_scripted_pipeline_case(self):
        for skill in PIPELINE_SKILLS:
            with self.subTest(skill=skill):
                scripted = [
                    case for case in skill_cases(skill)
                    if case.get("mode") == "pipeline"
                    and case.get("prompt", "").strip() and case.get("asserts")
                ]
                self.assertGreaterEqual(len(scripted), 1, f"{skill} has no pipeline case")

    def test_pipeline_prompts_resolve_once_and_stop_explicitly(self):
        for skill in PIPELINE_SKILLS:
            for case in skill_cases(skill):
                if case.get("mode") != "pipeline":
                    continue
                with self.subTest(skill=skill, case=case["id"]):
                    self.assertIn("ResolvedProject", case["prompt"])
                    self.assertRegex(case["prompt"].lower(), r"\bstop\b")
```

In `test_ship_release_contracts.py`, rename `test_evals_cover_the_fixture_shape_and_never_execute_a_release` to `test_evals_cover_the_fixture_shape_and_release_only_in_the_sandbox`, and replace its per-case loop with:

```python
        for case in evals:
            if case.get("mode", "plan-only") == "pipeline":
                self.assertEqual(
                    (case.get("setup") or {}).get("kind"), "release-ready",
                    f"eval {case['id']} is a pipeline case outside the release-ready sandbox",
                )
                continue
            guard = (case["prompt"]).lower()
            self.assertTrue(
                any(
                    marker in guard
                    for marker in (
                        "plan-only",
                        "dry-run",
                        "don't actually",
                        "do not create any tag",
                        "without actually",
                    )
                ),
                f"eval {case['id']} prompt lacks a non-execution guard",
            )
        self.assertTrue(
            any(case.get("mode") == "pipeline" for case in evals),
            "no ship-release pipeline case runs inside the release-ready sandbox",
        )
```

Leave the notes-fragment checks above the loop and the `single_branch` checks below it as they are.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python timeout 600 python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py home/common/agent-skills/tests/test_ship_release_contracts.py 2>&1 | grep -E '^(FAIL|ERROR):|has no pipeline case|no ship-release pipeline' | head`
Expected: `test_each_pipeline_skill_has_a_scripted_pipeline_case` fails for `ship-issue`, `sdd`, `ship-release` and `orchestrate-issues`, and the R8 test fails with `no ship-release pipeline case …`.

- [ ] **Step 3: Append the four cases**

Write each case as one JSON object with the keys `id`, `name`, `mode: "pipeline"`, `setup` (where given), `prompt`, `expected_output` and `asserts`. Each assert is a `{name, shell}` pair. The shell texts below are the exact shell. JSON-escape them when writing, and check them with `jq` afterwards.

**ship-issue, id 5, `tracker-free-ship-stops-before-push`, setup `{"kind": "shippable-worktree"}`.** The prompt:

```
/ship-issue 3

Resolve once into a retained ResolvedProject. A resolver refusal is fatal and values are never defaulted or inferred. The tracker capability is unsupported, so `issues/003-mechanical.md` is issue 3; its finished work (spec, plan and implementation) is committed on the existing linked worktree branch `worktree-issue-3-rename-flag` — find it with `git worktree list`. This is a standalone invocation on the tracker-free route: no PR, no tracker call, and no local merge into `main`.

**Stop before any `git push`.** Run every phase up to the push, then report the exact push command you would run next, and stop.
```

The `expected_output`: "Standalone ship on the tracker-free route. It syncs the worktree branch with origin/main (a no-op here), runs the declared verification and records it with `verified-tree record` in the worktree's git directory, and reaches the push step. There it stops and names `git push -u origin worktree-issue-3-rename-flag` as the next command. Nothing is pushed or merged, and `main` is unchanged locally and on origin."

Asserts:
- `local verification was recorded for the worktree`: `[ -f "$(git -C "$PRE_WT" rev-parse --absolute-git-dir)/verified-tree.json" ] || fail "no verified-tree.json in the worktree's git directory"`
- `the fixture's tests pass in the worktree`: `(cd "$PRE_WT" && python3 -m unittest discover -q 2>/dev/null) || fail "fixture tests fail in $PRE_WT"`
- `the branch still carries the implementation`: `commits_touch "$PRE_WT" tinytask`
- `nothing was pushed`: `[ -z "$(git -C "$ORIGIN" for-each-ref refs/heads/worktree-issue-3-rename-flag)" ] || fail "the branch reached origin despite the stop"`
- `local and origin main are unchanged`: `{ [ "$(git -C "$REPO" rev-parse main)" = "$BASE_MAIN" ] && [ "$(git -C "$ORIGIN" rev-parse main)" = "$BASE_MAIN" ]; } || fail "main moved"`
- `the run names the push it would run next`: `out_matches 'git push (-u )?origin worktree-issue-3-rename-flag'`

**sdd, id 4, `planned-worktree-executes-and-stops-before-final-review`, setup `{"kind": "planned-worktree"}`.** The prompt:

```
/sdd .claude/plans/2026-10-07-issue-3-rename-flag.md

Resolve once into a retained ResolvedProject. A resolver refusal is fatal and values are never defaulted or inferred. The plan and its design spec are committed on the existing linked worktree branch `worktree-issue-3-rename-flag` — find it with `git worktree list` and execute from that worktree, so the plan path is relative to it. The tracker capability is unsupported and there is no lifecycle identity.

**Stop after the last task's review passes, before the final review.** Do not run the final review, the final verification or any ship step, and do not push.
```

The `expected_output`: "sdd resolves the plan's workspace beneath the primary checkout (`.superpowers/sdd/wt-worktree-issue-3-rename-flag/<plan>/`) and dispatches one implementer for Task 1. The implementer commits the flag rename on the worktree branch, and its task review passes. The ledger then records `Task 1: complete` and the run stops before the final review. The fixture's tests pass in the worktree, `list --all` is a usage error, nothing is pushed and `main` is unchanged."

Asserts:
- `a branch commit touches tinytask/`: `commits_touch "$PRE_WT" tinytask`
- `list --include-done works and list --all is a usage error`: `cd "$PRE_WT" && python3 -m tinytask --file "$WORK/probe.json" list --include-done >/dev/null && { python3 -m tinytask --file "$WORK/probe.json" list --all >/dev/null 2>&1; [ $? -eq 2 ]; } || fail "the flag rename is not in place"`
- `the fixture's tests pass in the worktree`: `(cd "$PRE_WT" && python3 -m unittest discover -q 2>/dev/null) || fail "fixture tests fail in $PRE_WT"`
- `the sdd ledger records the task done`: `f=$(first_file "$REPO"/.superpowers/sdd/wt-worktree-issue-3-rename-flag/*/progress.md) && grep -q 'Task 1: complete' "$f" || fail "no 'Task 1: complete' in the sdd progress ledger"`
- `local and origin main are unchanged`: the ship-issue shell for this name, unchanged.
- `nothing was pushed`: the ship-issue shell for this name, unchanged.

**ship-release, id 5, `tracker-free-local-release-in-sandbox`, setup `{"kind": "release-ready"}`.** The prompt:

```
/ship-release

Resolve once into a retained ResolvedProject. A resolver refusal is fatal and values are never defaulted or inferred. This repository is single-branch (integration equals default, `main`) and the tracker capability is unsupported (kind=none), so this is the tracker-free local release: no PR, no forge step and no GitHub Release. `v0.1.0` is the previous release, and one `feat:` merge has landed on `main` since. Make the version decision yourself and do not ask for confirmation.

**Stop after the final report.** Run Phases 0 and 1, the local annotated tag of Phase 4.5, Phase 5 (no deploy adapter) and Phase 6, then stop. Push no tag.
```

The `expected_output`: "Phase 0 finds no durable state and `git describe --tags --abbrev=0 origin/main` prints `v0.1.0`, while the single-branch range `v0.1.0..origin/main` is non-empty. Phase 1 drafts the changelog from the one `feat:` merge. Phases 2–4 are skipped. Phase 4.5 resolves the merge SHA as `main`'s tip, finds no existing tag on it, bumps past `v0.1.0`, and creates exactly one annotated tag there, which it does not push. Phase 5 records `deployState` `none`, and Phase 6 reports and deletes `.superpowers/workflows/ship-release/state.json`."

Asserts (in each one, `new` is computed as shown):
- `exactly one new annotated release tag`: `new=$(git -C "$REPO" tag -l 'v*' | grep -vx v0.1.0); [ "$(printf '%s\n' "$new" | grep -c .)" -eq 1 ] && [ "$(git -C "$REPO" cat-file -t "$new")" = tag ] || fail "expected one new annotated v* tag, got: $new"`
- `the new tag is newer than v0.1.0`: `new=$(git -C "$REPO" tag -l 'v*' | grep -vx v0.1.0); python3 -c 'import sys; v = tuple(int(x) for x in sys.argv[1][1:].split(".")); sys.exit(0 if v > (0, 1, 0) else 1)' "$new" 2>/dev/null || fail "$new is not a semver tag newer than v0.1.0"`
- `the new tag points at main's tip`: `new=$(git -C "$REPO" tag -l 'v*' | grep -vx v0.1.0); [ "$(git -C "$REPO" rev-parse "$new^{commit}")" = "$(git -C "$REPO" rev-parse main)" ] || fail "$new does not point at main"`
- `origin carries no new tag`: `[ "$(git -C "$ORIGIN" tag -l)" = v0.1.0 ] || fail "origin tags: $(git -C "$ORIGIN" tag -l | tr '\n' ' ')"`
- `no durable release state remains`: `[ ! -e "$REPO/.superpowers/workflows/ship-release/state.json" ] || fail "the ship-release state file is still present"`

Extend `notes` by appending this sentence: " Eval 5 is the one pipeline case: it runs a real tracker-free release, but only inside the disposable eval sandbox built by the `release-ready` setup, and pushes no tag."

**orchestrate-issues, id 7, `tracker-free-first-control-response`, no setup.** The prompt:

```
/orchestrate-issues 1 3

Resolve once into a retained ResolvedProject. A resolver refusal is fatal and values are never defaulted or inferred. The tracker capability is unsupported, so these facts replace the tracker read: issue 1 is `issues/001-well-specified.md` and issue 3 is `issues/003-mechanical.md`, both open and unblocked. This repository is the ledger repository root.

**Stop after the first `workflow-state control` response is rendered.** Report the actions it returned for each issue, then stop: launch no agent, create no worktree and make no commit.
```

The `expected_output`: "The dispatcher asks `workflow-state host-route --route claude-code` first. It then runs `workflow-state init-run` for a fresh run under `.superpowers/workflows/`, followed by one `workflow-state control` call whose validated response holds a dispatch action for issue 1 and one for issue 3. It renders that response and stops. No agent is launched, no worktree is created and `main` carries no new commit."

Asserts:
- `a run ledger covers issues 1 and 3`: `found=0; for f in "$REPO"/.superpowers/workflows/*/state.json; do [ -f "$f" ] || continue; jq -e '.issues | has("1") and has("3")' "$f" >/dev/null && found=1; done; [ "$found" -eq 1 ] || fail "no run ledger under .superpowers/workflows covers issues 1 and 3"`
- `no worktree was created`: `[ "$WT_COUNT" -eq 0 ] || fail "found $WT_COUNT worktrees"`
- `main carries no new commit`: `[ "$(git -C "$REPO" rev-parse main)" = "$BASE_MAIN" ] || fail "main moved"`
- `the output names the dispatch for both issues`: `out_matches 'spawn|dispatch' && out_matches '(issue|#) ?1([^0-9]|$)' && out_matches '(issue|#) ?3([^0-9]|$)'`

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 600 python3 -m unittest -v home/common/agent-skills/tests/test_eval_cases.py home/common/agent-skills/tests/test_ship_release_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -n 4`
Expected: `OK`.

Run: `for f in home/common/agent-skills/skills/{ship-issue,sdd,ship-release}/evals/evals.json home/common/claude-code/skills/orchestrate-issues/evals/evals.json; do jq -e '[.evals[] | select(.mode == "pipeline")] | length == 1' "$f" >/dev/null || { echo "bad: $f"; exit 1; }; done; echo ok`
Expected: `ok`. Each of the four files has exactly one pipeline case.

Run: `for id in 5:ship-issue 4:sdd 5:ship-release; do s=${id#*:}; n=${id%%:*}; jq -r --argjson n "$n" '.evals[] | select(.id == $n) | .asserts[].shell' home/common/agent-skills/skills/$s/evals/evals.json; done | while IFS= read -r shell; do bash -n -c "$shell" || exit 1; done && jq -r '.evals[] | select(.id == 7) | .asserts[].shell' home/common/claude-code/skills/orchestrate-issues/evals/evals.json | while IFS= read -r shell; do bash -n -c "$shell" || exit 1; done && echo syntax-ok`
Expected: `syntax-ok`. Every new assert parses as bash.

- [ ] **Step 5: Commit**

Commit the six files with the message `feat(evals): pipeline cases for ship-issue, sdd, ship-release and orchestrate-issues (#293)`, using sdd's lifecycle commit rule.
