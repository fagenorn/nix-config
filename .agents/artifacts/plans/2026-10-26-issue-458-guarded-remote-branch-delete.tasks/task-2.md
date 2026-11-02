# Task 2: One remote-deletion spelling in the fixture and `ship-issue`

Spec § One spelling, § Acceptance evidence, § Test seams (shape table, shell-example suite, git-level test); per D1, D5, D6, D7. After this task the shape fixture's `branch.remote` row is the qualified form, allowed bare and behind both scrub prefixes; `ship-issue` Phase 7 and the HUMAN-GATE Gate 2 chain spell exactly that form; the old bare spelling is a refused guard-only invocation shape; and a git-level test shows the filled form deletes only the named branch. The two skill edits pay for their growth inside the touched lines (D7).

**Files:**
- Modify: `tests/fixtures/guarded-command-shapes.json` (`skill_forms` row `branch.remote`; one new `invocation_shapes` row)
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (Phase 7, one line)
- Modify: `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md` (Gate 2 chain, one item)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`SHIP_ISSUE_MACHINE_TEXT[SHIP_ISSUE_HUMAN_GATE]`)
- Modify: `tests/test_claude_permission_guard.py` (the issue-458 section Task 1 opened)
- Modify: `home/common/claude-code/README.md` (the shape-fixture sentence)

**Interfaces:**
- Consumes: Task 1's push form `delete` (`git push origin --delete refs/heads/<branch>`) and its refusal `missing refs/heads/<branch>` for the bare spelling; the guard suite's `SHAPES`, `shape_command(template)`, `fixture_dir`, `test_every_guarded_command_shape_gets_its_verdict`, `test_every_invocation_shape_gets_its_verdict`; the shell-example suite's `guarded_command_findings` (R1: a living example holding a guarded verb is one `skill_forms` template space for space; R2: its block cites `` `## gh hygiene` ``; R3: every form listing a document as a site appears there).
- Produces: fixture `branch.remote` = `{"id": "branch.remote", "template": "git push origin --delete refs/heads/<branch>", "sites": ["SKILL.md", "HUMAN-GATE.md"], "label": "push", "bare": {"exit": 0}, "prefixed": {"exit": 0}, "env_prefixed": {"exit": 0}}`; `invocation_shapes` row `branch.remote-bare`; the two `ship-issue` spellings below.

**Invariants:**
- `ship-issue` changes exactly two lines, each still citing `` (`## gh hygiene`) ``; no line is added or removed in either document.
- Net growth: `SKILL.md` +11 bytes (hot set, 1,619 B headroom); `HUMAN-GATE.md` +4 bytes (`ship-owner` conditional set, 6 B headroom on claude and codex). `just agent-instruction-budget` passes with no `--raise-label` (D7); `instruction-load.json` is untouched.
- The fixture's `values`, `refused_shapes`, `form_values` and every other row are unchanged.

- [ ] **Step 1: Write the failing tests**

1. `tests/fixtures/guarded-command-shapes.json`, row `branch.remote`: template `"git push origin --delete refs/heads/<branch>"`; `"bare": {"exit": 0}`, `"prefixed": {"exit": 0}`, `"env_prefixed": {"exit": 0}`. Id, sites and label stay.

2. Same file, append to `invocation_shapes` after `merge.flag-between-path`:

```json
    {"id": "branch.remote-bare", "template": "git push origin --delete <branch>",
     "label": "push", "verdict": {"exit": 2, "reason": "missing refs/heads/<branch>"}}
```

3. `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `SHIP_ISSUE_MACHINE_TEXT[SHIP_ISSUE_HUMAN_GATE]`: replace the item `"git push origin --delete <branch>"` with `"git push origin --delete refs/heads/<branch>"`.

4. `tests/test_claude_permission_guard.py`, directly after Task 1's `test_remote_branch_deletion_arm`:

```python
    def test_the_remote_deletion_form_deletes_only_the_named_branch(self):
        """Issue 458 D1, D5: run by git against a local bare remote that holds a branch
        and a tag of one name, ship-issue's filled spelling deletes the branch alone."""
        form = next(form for form in self.SHAPES["skill_forms"]
                    if form["id"] == "branch.remote")
        command = self.shape_command(form["template"])
        name = self.SHAPES["values"]["<branch>"]
        base = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        remote, work = base / "remote.git", base / "work"
        identity = ["-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]

        def git(*argv, cwd=work):
            return subprocess.run(["git", *identity, *argv], cwd=cwd, check=True,
                                  capture_output=True, text=True).stdout

        subprocess.run(["git", "init", "--quiet", "--bare", str(remote)], check=True,
                       capture_output=True)
        work.mkdir()
        git("init", "--quiet")
        git("remote", "add", "origin", str(remote))
        git("commit", "--quiet", "--allow-empty", "-m", "init")
        git("tag", name)
        git("push", "--quiet", "origin", f"HEAD:refs/heads/{name}", f"refs/tags/{name}")
        subprocess.run(shlex.split(command), cwd=work, check=True, capture_output=True)
        self.assertEqual("", git("ls-remote", "--heads", "origin", name))
        self.assertIn(f"refs/tags/{name}", git("ls-remote", "--tags", "origin", name))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Skill contracts.
Expected: FAIL — `ShipIssueGuardedCommandSweepTest.test_every_guarded_command_is_a_cited_form` reports R1 for the old spelling at `SKILL.md` and `HUMAN-GATE.md` and R3 for the new template at both sites, and `WorkflowSkillContractsTest.test_ship_issue_documents_carry_their_machine_text` misses the new `HUMAN-GATE.md` pin.

(The guard-suite rows of Step 1 pass at once: Task 1 already allows the form, and the git-level test exercises git itself. Step 4 runs them.)

- [ ] **Step 3: Write the minimal implementation**

1. `home/common/agent-skills/skills/ship-issue/SKILL.md`, Phase 7, the sentence ending the merge verify: replace `` Non-empty output → `git push origin --delete <branch>` (`## gh hygiene`). `` with exactly `` Non-empty output → `git push origin --delete refs/heads/<branch>` (`## gh hygiene`). ``

2. `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`, Gate 2 chain: replace the two-line item

```
- `git push origin --delete <branch>` (`## gh hygiene`), only when
  `git ls-remote --heads origin <branch>` is non-empty;
```

with exactly

```
- `git push origin --delete refs/heads/<branch>` (`## gh hygiene`), if
  `git ls-remote --heads origin <branch>` is non-empty;
```

3. `home/common/claude-code/README.md`, the shape-fixture sentence (it starts ``The shape fixture `tests/fixtures/guarded-command-shapes.json` (#351) lists``): replace the words `lists the push, merge and branch-delete forms` with `lists the push (remote deletion included), merge and branch-delete forms`.

- [ ] **Step 4: Verify**

Run the Skill contracts.
Expected: `OK`.

Run the Budget.
Expected: last line `check: pass`.

Run the Guard suite with `-k test_every_guarded_command_shape_gets_its_verdict -k test_every_invocation_shape_gets_its_verdict -k test_the_remote_deletion_form_deletes_only_the_named_branch -k test_remote_branch_deletion_arm`.
Expected: `OK`, 4 tests.

Run: `bash -c 'cd home/common/agent-skills/skills/ship-issue && test "$(git diff --numstat -- SKILL.md HUMAN-GATE.md | awk "{a+=\$1; d+=\$2} END {print a, d}")" = "2 2" && test "$(grep -c -F "origin --delete <branch>" SKILL.md HUMAN-GATE.md | grep -vc ":0$")" = 0'`
Expected: exit 0 — two lines changed in each direction and no old spelling left. (Keep the word `push` out of any `bash -c` text that also runs `git`: the lifecycle guard reads evaluator source as raw text and refuses it as a push.)

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/guarded-command-shapes.json home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md home/common/agent-skills/tests/test_workflow_skill_contracts.py tests/test_claude_permission_guard.py home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(ship-issue): one guarded remote-deletion spelling for issue 458" -m "<trailers>"
```
