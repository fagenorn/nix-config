# Task 1: The guard's remote-deletion push arm

Spec § The remote-deletion form, § Test seams (guard suite); per D1, D2. After this task the guard allows `git push origin --delete refs/heads/<branch>` for a non-permanent branch in an authorized repository, bare, behind either scrub prefix and behind `git -C <dir>`, and prints it as the third push form in every push refusal. `ship-issue` and the fixture's `branch.remote` template are untouched until Task 2; only that row's refusal reason moves here.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py` (`FORM_TABLE["push"]`, `validate_push`)
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `tests/fixtures/guarded-command-shapes.json` (the `branch.remote` row's three `reason` values only)
- Modify: `home/common/claude-code/README.md` (`## Adjudicated verbs`)

**Interfaces:**
- Consumes: `match_form`, `form_problem`, `accepted_forms`, `refuse`, `branch_name_problem`, `BRANCH_VALIDATION_TIMEOUT`, `ownership_problem`, `Context.base_branch`, `Context.integration_bases`, `Context.repository` (all unchanged); test helpers `make_repo(origin, default_branch=…)`, `run_guard(command, cwd=…)`, `refusal_line(result)`, `NODO`, `self.fixture_dir`.
- Produces: push form id `delete`, template `git push origin --delete refs/heads/<branch>`, third in `FORM_TABLE["push"]["forms"]` with note `None`; `--delete` joins the compiled push operation's `flags` (derived from the templates, no separate edit); the state refusal text `refusing to delete the permanent branch <branch>`.

**Invariants:**
- Forms keep table order `tag`, `branch`, `delete`; every push text refusal ends `; accepted: git push origin refs/tags/<vX.Y.Z>; or git push [-u] origin <branch>; or git push origin --delete refs/heads/<branch>; optional prefix: unset GITHUB_TOKEN && | env -u GITHUB_TOKEN`.
- Order of judgment for the delete form (D2): standing authorization (before the match, unchanged), `branch_name_problem` on the slot value (a timeout is a state refusal, any other problem a text refusal), `cannot resolve the repository default branch`, then the permanent-branch state refusal when the value equals `context.base_branch` or `context.integration_bases.get(context.repository)`. No forge lookup and no new subprocess.
- The branch arm, tag arm, merge, release creation and branch deletion keep every verdict and message; `git push origin --delete topic` in `test_push_grammar_accepts_only_plain_nondefault_branch` stays a refusal, unedited.
- The adversarial table stays unedited and green.

- [ ] **Step 1: Write the failing tests**

1. In `tests/test_claude_permission_guard.py`, outside the adversarial table (the section from `# Adversarial table.` to `# Release arm: the declared integration branch`), insert a new section directly before the comment line `# Guarded command shapes (#351): the forms ship-issue spells and the dressed`:

```python
    # Remote branch deletion (issue 458): the push verb's third form.

    def test_remote_branch_deletion_arm(self):
        """Issue 458 D1, D2: `git push origin --delete refs/heads/<branch>` deletes a
        feature branch in an authorized repository and never a permanent branch."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        form = "git push origin --delete refs/heads/<branch>"
        delete = "git push origin --delete refs/heads/issue-458-topic"
        for command, cwd in (
            (delete, repo),
            ("unset GITHUB_TOKEN && " + delete, repo),
            ("env -u GITHUB_TOKEN " + delete, repo),
            (f"git -C {repo} push origin --delete refs/heads/issue-458-topic",
             self.fixture_dir.name),
            (delete, nodo),
        ):
            with self.subTest(command=command, cwd=cwd):
                result = self.run_guard(command, cwd=cwd)
                self.assertEqual(0, result.returncode, result.stderr)
        for command, cwd, problem in (
            ("git push origin --delete refs/heads/main", repo,
             "refusing to delete the permanent branch main"),
            ("git push origin --delete refs/heads/main", nodo,
             "refusing to delete the permanent branch main"),
            ("git push origin --delete refs/heads/dev", nodo,
             "refusing to delete the permanent branch dev"),
        ):
            with self.subTest(command=command, cwd=cwd):
                line = self.refusal_line(self.run_guard(command, cwd=cwd))
                self.assertEqual(f"lifecycle guard: unsafe push: {problem}", line)
        for command, problem in (
            ("git push origin --delete issue-458-topic", "missing refs/heads/<branch>"),
            ("git push origin --delete refs/tags/v1.2.3", "missing refs/heads/<branch>"),
            ("git push origin --delete refs/heads/a refs/heads/b",
             "unexpected refs/heads/b at the end"),
            ("git push -u origin --delete refs/heads/issue-458-topic", "missing <branch>"),
            ("git push --delete origin refs/heads/issue-458-topic", "--delete is out of place"),
            ("git push origin -d refs/heads/issue-458-topic", "unknown flag -d"),
            ("git push origin --delete refs/heads/", "branch name must not be empty"),
            ("git push origin --delete refs/heads/refs/heads/x",
             "namespaced ref refs/heads/x is not accepted; name the branch directly"),
        ):
            with self.subTest(command=command):
                line = self.refusal_line(self.run_guard(command, cwd=repo))
                self.assertTrue(line.startswith(
                    f"lifecycle guard: unsafe push: {problem}; accepted: "), line)
                self.assertIn("; or " + form + "; optional prefix: ", line)
        outsider = self.make_repo("git@github.com:someoneelse/tool.git")
        line = self.refusal_line(self.run_guard(delete, cwd=outsider))
        self.assertEqual("lifecycle guard: unsafe push: repository someoneelse/tool is "
                         "outside standing authorization", line)
        unresolved = self.make_repo("git@github.com:fagenorn/argus.git", default_branch=None)
        line = self.refusal_line(self.run_guard(delete, cwd=unresolved))
        self.assertEqual("lifecycle guard: unsafe push: cannot resolve the repository "
                         "default branch", line)
```

2. `test_every_printed_form_is_allowed_where_printed`: in `one_each`, change `"push": 2` to `"push": 3`; in the AC2 tuple whose command is `"unset GITHUB_TOKEN; git push -q origin HEAD:issue-402-topic 2>&1 | tail -2"`, change its count `2` to `3`. The test then fills the new form from `form_values` (`<branch>` = `issue-402-topic`) and runs it in the fixture, Nodo-row and no-context cases.

3. `test_text_refusals_list_the_forms_their_facts_admit`: set

```python
        push = ("git push origin refs/tags/<vX.Y.Z>; or git push [-u] origin <branch>; "
                "or git push origin --delete refs/heads/<branch>")
```

4. `test_the_retro_commands_name_their_problem_and_cure`: the expected push line ends `"refs/tags/<vX.Y.Z>; or git push [-u] origin <branch>; or git push origin "` `"--delete refs/heads/<branch>" + self.PREFIX_CLAUSE`.

5. In `tests/fixtures/guarded-command-shapes.json`, the `branch.remote` row keeps its template `git push origin --delete <branch>` and its exits (2); its `bare`, `prefixed` and `env_prefixed` `reason` values become `"missing refs/heads/<branch>"` (the guard's text for the bare spelling once `--delete` is a known flag).

- [ ] **Step 2: Run the tests and watch them fail**

Run the Guard suite with `-k test_remote_branch_deletion_arm -k test_every_printed_form_is_allowed_where_printed -k test_text_refusals_list_the_forms_their_facts_admit -k test_the_retro_commands_name_their_problem_and_cure -k test_every_guarded_command_shape_gets_its_verdict`.
Expected: FAIL in all five — the allowed deletions exit 2 `unknown flag --delete`, the printed push lists hold two forms, and the `branch.remote` shape reads `unknown flag --delete`.

- [ ] **Step 3: Write the minimal implementation**

1. `FORM_TABLE["push"]["forms"]` becomes:

```python
            ("tag", "git push origin refs/tags/<vX.Y.Z>", None),
            ("branch", "git push [-u] origin <branch>", None),
            ("delete", "git push origin --delete refs/heads/<branch>", None),
```

2. `validate_push`: the form dispatch admits `branch` and `delete` and still raises on any other id; the shared tail runs the branch name rule and the default-branch resolution for both, then splits:

```python
    if match.form.id not in ("branch", "delete"):
        raise AssertionError(f"unhandled push form {match.form.id}")
    branch = match.values["branch"]
    # … branch_name_problem and the base_branch None refusal, unchanged …
    if match.form.id == "delete":
        # Issue 458 D2: a remote deletion never names a permanent branch, the
        # default branch or the repository's declared integration branch.
        if branch in (context.base_branch, context.integration_bases.get(context.repository)):
            return refuse("push", f"refusing to delete the permanent branch {branch}")
        return 0
    if branch == context.base_branch:
        return refuse("push", f"refusing to push the default branch {branch}")
    return 0
```

3. `home/common/claude-code/README.md`, `## Adjudicated verbs`:
   - In the push clause, replace `the one exception is the tag-push arm below)` with `the two exceptions are the tag-push and remote-deletion arms below)`.
   - Insert one new paragraph directly after the paragraph that holds that clause, exactly:

     The **remote-deletion arm** (issue 458) is the push verb's third form, judged after the tag and branch arms: exactly `git push origin --delete refs/heads/<branch>`, with the push verb's whole-text character rule, credential-scrub prefixes and one `git -C <dir>`. The `refs/heads/` literal is the point: git resolves a bare `--delete <name>` against the remote's refs and deletes a tag when only a tag matches, while the qualified name can only be a branch, so the bare spelling stays refused (`missing refs/heads/<branch>`). After standing authorization the value takes the branch arm's name rule (so `refs/heads/refs/heads/x` is a namespaced ref), then needs a resolvable `origin/HEAD`, and the default branch and the repository's declared integration branch are refused as `unsafe push: refusing to delete the permanent branch <branch>`. The arm reads no forge state: GitHub itself refuses to delete a protected branch, and `ship-issue` runs the deletion only after verifying the merge and seeing `git ls-remote --heads origin <branch>` non-empty.

   - In the refusal taxonomy paragraph's state-refusal list, replace `a default-branch push, head equal to base` with `a default-branch push, a permanent-branch deletion, head equal to base`.

- [ ] **Step 4: Verify**

Run the Guard suite with no `-k`.
Expected: `OK`, the five tests above and the adversarial table among them.

Run: `bash -c 'sect() { sed -n "/# Adversarial table\./,/# Release arm: the declared integration branch/p"; }; diff <(git show HEAD:tests/test_claude_permission_guard.py | sect) <(sect < tests/test_claude_permission_guard.py)'`
Expected: no output, exit 0 (the adversarial table is unedited).

Run the Skill contracts.
Expected: `OK` — the fixture's `branch.remote` template and the two `ship-issue` sites are unchanged.

Run: `bash -c 'if git diff -U0 -- home/common/claude-code/lifecycle_guard.py | grep -E "^\+.*(import |subprocess\.)"; then exit 1; fi'`
Expected: exit 0 (no new import, no new child process).

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py tests/fixtures/guarded-command-shapes.json home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(guard): remote branch deletion arm for issue 458" -m "<trailers>"
```
