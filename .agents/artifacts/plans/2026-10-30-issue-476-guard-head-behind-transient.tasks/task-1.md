# Task 1: Merge mergeability check — BEHIND and head commit

Spec § Merge validator: two PR facts, § Guard documentation, § Test seams. Rests on D1–D5, D8 and D9. After this task, both merge arms read `headRefOid` and `mergeStateStatus` from the one PR lookup. Each arm refuses a `BEHIND` PR and then a `--match-head-commit` that is not the PR's head commit, after its own shape judgment and before its first gate. Row-check refusals are untouched until Task 2.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py` (the `HEAD_COMMIT` comment, `validate_merge`, new `mergeability_problem`, `validate_release_merge`)
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `home/common/claude-code/README.md` (`## Adjudicated verbs`)

**Interfaces:**
- Consumes (all unchanged): `refuse`, `HEAD_COMMIT`, `validate_merge`'s locals `head_commit` (the `sha` slot value, or None), `pr_facts` (the parsed lookup object) and `base` (the read-back base); and the test helpers `make_repo`, `run_guard`, `refusal_line`, `release_env`, `NODO`, the module sentinel `ABSENT`, the class attribute `RELEASE_PR` and the fake `gh`'s `FAKE_PR_JSON` and `FAKE_PROTECTION_MODE`.
- Produces: `mergeability_problem(pr_facts, base, head_commit) -> str | None`, and `validate_release_merge(pr_facts, base, integration_base, head_commit, context, compiled)`, which gains `head_commit` as its fourth parameter. It also produces the PR lookup field list `state,baseRefName,headRefName,headRefOid,mergeStateStatus,url,statusCheckRollup`. In the tests: `HEAD_SHA` moves above `RELEASE_PR`, and the class gains `OTHER_SHA`, `BEHIND` and the helper `mergeability_paths()`.

**Invariants:**
- The check runs in this order (D1). Feature arm: head read, permanent-head refusal, mergeability check, integration-base exemption, protection lookup. Release arm: integration-into-default shape check, mergeability check, rollup predicate.
- Inside the check (D2, D4), the merge state comes first. A `mergeStateStatus` that is missing, not a `str` or empty is refused as `cannot read the PR merge state`. The exact value `BEHIND` is refused. Any other string passes. Only after that, and only when `head_commit` is not None, the guard reads `headRefOid`. A value that is not a `str` or fails `HEAD_COMMIT.fullmatch` is refused as `cannot read the PR head commit`. A value that differs from `head_commit` is refused.
- Both new refusals and both `cannot read` refusals go through `refuse("merge", problem)` with no forms, so they print no `accepted:` clause and no prefix clause (D5).
- The PR lookup still scrubs the credential variables through `gh_lookup_env()`. The jq predicate and the base read-back are unchanged.
- The adversarial table changes only as D9 allows, and every test outside this task's edits keeps its verdict.

- [ ] **Step 1: Write the failing tests**

All edits are in `tests/test_claude_permission_guard.py`. Per D9, leave the fake `gh`'s field-list line (`and argv[6] == "state,baseRefName,headRefName,url,statusCheckRollup"`) unchanged until Step 3.

1. In `FAKE_GH_SCRIPT`'s `pr` default payload, insert two lines directly after `'"headRefName":"issue-' + number + '-topic",'`:

```python
        '"headRefOid":"d4d9acc0505c73305b3e0ced029db43100bc0e8a",'
        '"mergeStateStatus":"CLEAN",'
```

2. In the adversarial table, make exactly three edits. In the `FAKE_PR_JSON` literals of `test_prefixed_merge_reaches_acceptance_on_the_integration_base` (one) and `test_merge_protection_demand_follows_the_base_branch` (two), insert `"mergeStateStatus":"CLEAN",` directly after `"state":"OPEN",`. Change nothing else in the table.

3. Delete the two lines directly above `def test_merge_takes_an_optional_head_commit_flag`: the comment `# The PR head commit a merge may pin (issue 402 D10): the guard checks only its spelling.` and `HEAD_SHA = "d4d9acc0505c73305b3e0ced029db43100bc0e8a"`, along with the blank line after them. Then replace the opening of `RELEASE_PR` with:

```python
    # The PR head commit a merge may pin (issue 402 D10), which must be the PR's
    # headRefOid (issue 476 D3): the fake gh's default head and RELEASE_PR's.
    HEAD_SHA = "d4d9acc0505c73305b3e0ced029db43100bc0e8a"
    # A well-spelled commit that is no fixture PR's head.
    OTHER_SHA = "0123456789abcdef0123456789abcdef01234567"

    RELEASE_PR = {
        "state": "OPEN",
        "baseRefName": "main",
        "headRefName": "dev",
        "headRefOid": HEAD_SHA,
        "mergeStateStatus": "CLEAN",
```

   The rest of `RELEASE_PR` (`url`, `statusCheckRollup`) is unchanged.

4. Payloads outside the table that reach the check gain the fields it reads:
   - `test_merge_takes_an_optional_head_commit_flag`: in `feature_into_dev`'s dict, add `"headRefOid": sha, "mergeStateStatus": "CLEAN",` after `"headRefName": "issue-2342-topic",`.
   - `test_the_retro_commands_name_their_problem_and_cure`: in `feature_into_dev`'s dict, add `"headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN",` after `"headRefName": "issue-2342-topic",`.
   - `test_an_arcwave_shaped_project_is_judged_by_its_compiled_row`: in `feature_pr`, add `"mergeStateStatus": "CLEAN",` after `"headRefName": "issue-7-topic",`.
   - Every other override is refused before the check and stays unedited: the predicate failures, `pr(head, base)` in `test_text_refusals_list_the_forms_their_facts_admit`, the AC2 `feature_into_dev` in `test_every_printed_form_is_allowed_where_printed`, and the permanent-head and unreadable-head tests.

5. In `test_state_refusals_print_no_accepted_forms`, append two rows after the rollup row (`merge` is that test's `--delete-branch` command):

```python
            (merge.replace(" --delete-branch", f" --match-head-commit {self.OTHER_SHA} "
                           "--delete-branch"), repo, None,
             f"unsafe merge: --match-head-commit {self.OTHER_SHA} is not the PR head commit "
             f"{self.HEAD_SHA}; merge only a head you reviewed"),
            (merge, repo, {"FAKE_PR_JSON": json.dumps({
                "state": "OPEN", "baseRefName": "main", "headRefName": "issue-2342-topic",
                "headRefOid": self.HEAD_SHA, "mergeStateStatus": "BEHIND",
                "url": "https://github.com/fagenorn/nix-config/pull/2342"})},
             "unsafe merge: the PR is behind its base main; repair: sync the branch with main, "
             "push it and wait for its required checks before merging"),
```

6. Insert this section directly before the section header whose second line is `# Forge adapter arms (#124): the tag push and the release creation the` (after `test_unexpected_dependency_exception_blocks`):

```python
    # ------------------------------------------------------------------
    # Mergeability (issue 476): each merge arm, after its own shape judgment
    # and before its first gate, refuses a PR behind its base and then a
    # --match-head-commit that is not the PR's head commit.
    # ------------------------------------------------------------------

    BEHIND = ("the PR is behind its base {base}; repair: sync the branch with {base}, "
              "push it and wait for its required checks before merging")

    def mergeability_paths(self):
        """The three paths the check binds (issue 476 D1), each (name, cwd, command, facts,
        env): `command` takes the optional `--match-head-commit` group through `{pin}`,
        and `facts` is a PR payload every check passes."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        clean = {"headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN"}
        return (
            ("feature into main", repo,
             "gh pr merge 1 --repo fagenorn/nix-config --merge{pin} --delete-branch",
             {"state": "OPEN", "baseRefName": "main", "headRefName": "issue-1-topic",
              "url": "https://github.com/fagenorn/nix-config/pull/1", **clean}, {}),
            ("feature into dev", nodo,
             f"gh pr merge 7 --repo {NODO} --merge{{pin}} --delete-branch",
             {"state": "OPEN", "baseRefName": "dev", "headRefName": "issue-7-topic",
              "url": f"https://github.com/{NODO}/pull/7", **clean},
             {"FAKE_PROTECTION_MODE": "nonzero"}),
            ("release", nodo, f"gh pr merge 1484 --repo {NODO} --merge{{pin}}",
             dict(self.RELEASE_PR), {"FAKE_PROTECTION_MODE": "nonzero"}),
        )

    def test_a_wrong_head_commit_is_refused_naming_the_pr_head(self):
        """Issue 476 AC1, D3, D5: on every path the check binds, a --match-head-commit
        that is not the PR's headRefOid is refused with the actual head; the PR's own head
        passes."""
        for name, cwd, command, facts, env in self.mergeability_paths():
            env = {**env, "FAKE_PR_JSON": json.dumps(facts)}
            with self.subTest(path=name, pin="the PR head"):
                result = self.run_guard(
                    command.format(pin=f" --match-head-commit {self.HEAD_SHA}"), cwd=cwd, env=env)
                self.assertEqual(0, result.returncode, result.stderr)
            with self.subTest(path=name, pin="another commit"):
                line = self.refusal_line(self.run_guard(
                    command.format(pin=f" --match-head-commit {self.OTHER_SHA}"), cwd=cwd,
                    env=env))
                self.assertEqual(
                    f"lifecycle guard: unsafe merge: --match-head-commit {self.OTHER_SHA} is not "
                    f"the PR head commit {self.HEAD_SHA}; merge only a head you reviewed", line)

    def test_a_pr_behind_its_base_is_refused_naming_the_sync(self):
        """Issue 476 AC2, D1, D2, D5: on every path the check binds, a BEHIND PR is refused
        with the sync recovery, ahead of the head comparison; other merge states pass."""
        for name, cwd, command, facts, env in self.mergeability_paths():
            behind = {**env, "FAKE_PR_JSON": json.dumps({**facts, "mergeStateStatus": "BEHIND"})}
            for pin in ("", f" --match-head-commit {self.HEAD_SHA}",
                        f" --match-head-commit {self.OTHER_SHA}"):
                with self.subTest(path=name, pin=pin):
                    line = self.refusal_line(self.run_guard(
                        command.format(pin=pin), cwd=cwd, env=behind))
                    self.assertEqual("lifecycle guard: unsafe merge: "
                                     + self.BEHIND.format(base=facts["baseRefName"]), line)
            for state in ("UNKNOWN", "BLOCKED", "DIRTY", "UNSTABLE"):
                with self.subTest(path=name, state=state):
                    result = self.run_guard(
                        command.format(pin=f" --match-head-commit {self.HEAD_SHA}"), cwd=cwd,
                        env={**env, "FAKE_PR_JSON": json.dumps(
                            {**facts, "mergeStateStatus": state})})
                    self.assertEqual(0, result.returncode, result.stderr)

    def test_an_arm_refusal_comes_before_the_mergeability_check(self):
        """Issue 476 D1: a PR whose head no arm admits keeps its arm refusal, whatever its
        merge state and head commit."""
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        env = {"FAKE_PROTECTION_MODE": "nonzero", "FAKE_PR_JSON": json.dumps({
            "state": "OPEN", "baseRefName": "dev", "headRefName": "main",
            "headRefOid": self.HEAD_SHA, "mergeStateStatus": "BEHIND",
            "url": f"https://github.com/{NODO}/pull/7", "statusCheckRollup": []})}
        merge = f"gh pr merge 7 --repo {NODO} --merge --match-head-commit {self.OTHER_SHA}"
        for command, problem in (
            (merge + " --delete-branch", "--delete-branch would delete the permanent branch main"),
            (merge, "--delete-branch may be omitted only when merging dev into main; this PR "
                    "merges main into dev"),
        ):
            with self.subTest(command=command):
                line = self.refusal_line(self.run_guard(command, cwd=nodo, env=env))
                self.assertEqual(f"lifecycle guard: unsafe merge: {problem}", line)

    def test_an_unreadable_merge_state_or_head_commit_is_refused(self):
        """Issue 476 D4: a fact the check needs and cannot read fails closed; without
        --match-head-commit the head commit is neither read nor demanded."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        merge = "gh pr merge 1 --repo fagenorn/nix-config --merge"
        bare = f"{merge} --delete-branch"
        pinned = f"{merge} --match-head-commit {self.HEAD_SHA} --delete-branch"
        facts = {"state": "OPEN", "baseRefName": "main", "headRefName": "issue-1-topic",
                 "headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN",
                 "url": "https://github.com/fagenorn/nix-config/pull/1"}

        def env(**change):
            payload = {key: value for key, value in {**facts, **change}.items()
                       if value is not ABSENT}
            return {"FAKE_PR_JSON": json.dumps(payload)}

        state, head = "cannot read the PR merge state", "cannot read the PR head commit"
        for label, command, change, problem in (
            ("state missing", pinned, {"mergeStateStatus": ABSENT}, state),
            ("state null", bare, {"mergeStateStatus": None}, state),
            ("state number", bare, {"mergeStateStatus": 7}, state),
            ("state empty", bare, {"mergeStateStatus": ""}, state),
            ("head missing", pinned, {"headRefOid": ABSENT}, head),
            ("head null", pinned, {"headRefOid": None}, head),
            ("head short", pinned, {"headRefOid": self.HEAD_SHA[:7]}, head),
            ("head uppercase", pinned, {"headRefOid": self.HEAD_SHA.upper()}, head),
        ):
            with self.subTest(fact=label):
                line = self.refusal_line(self.run_guard(command, cwd=repo, env=env(**change)))
                self.assertEqual(f"lifecycle guard: unsafe merge: {problem}", line)
        for label, change in (("missing", {"headRefOid": ABSENT}),
                              ("short", {"headRefOid": self.HEAD_SHA[:7]})):
            with self.subTest(head=label, pin="none"):
                result = self.run_guard(bare, cwd=repo, env=env(**change))
                self.assertEqual(0, result.returncode, result.stderr)

```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Guard suite with `-k wrong_head_commit -k behind_its_base -k arm_refusal_comes -k unreadable_merge_state -k test_state_refusals_print_no_accepted_forms`.
Expected: `Ran 5 tests` and `FAILED (failures=22)`, and every failure is `AssertionError: 2 != 0`. Each wrong-head, `BEHIND`, unreadable-fact and new state-class merge exits 0 on the base guard, so it is allowed through to GitHub. `test_an_arm_refusal_comes_before_the_mergeability_check` passes, because base already refuses there; it pins the order.

- [ ] **Step 3: Write the minimal implementation**

1. `lifecycle_guard.py`, the comment above `HEAD_COMMIT` becomes:

```python
# The value `--match-head-commit` takes: a full commit SHA (issue 402 D10), which
# must also be the PR's head commit (issue 476 D3).
```

2. In `validate_merge`'s PR lookup argv, replace `"--json", "state,baseRefName,headRefName,url,statusCheckRollup",` with:

```python
                "--json",
                "state,baseRefName,headRefName,headRefOid,mergeStateStatus,url,statusCheckRollup",
```

3. Add this function directly above `validate_release_merge`. The full code is given because its messages are an exact wire format:

```python
def mergeability_problem(pr_facts, base, head_commit):
    """Why the PR's forge state refuses this merge, or None (issue 476 D1-D5).

    `pr_facts` is the PR lookup's object, `base` its read-back base branch and
    `head_commit` the command's `--match-head-commit` value, None without the
    flag. A merge state of exactly `BEHIND` is judged first; the head commit is
    read and compared only when the flag is present. Every other merge state
    passes: GitHub keeps its own up-to-date rule and its atomic head match.
    """
    state = pr_facts.get("mergeStateStatus")
    if not isinstance(state, str) or not state:
        return "cannot read the PR merge state"
    if state == "BEHIND":
        return (f"the PR is behind its base {base}; repair: sync the branch with {base}, "
                "push it and wait for its required checks before merging")
    if head_commit is None:
        return None
    head = pr_facts.get("headRefOid")
    if not isinstance(head, str) or HEAD_COMMIT.fullmatch(head) is None:
        return "cannot read the PR head commit"
    if head != head_commit:
        return (f"--match-head-commit {head_commit} is not the PR head commit {head}; "
                "merge only a head you reviewed")
    return None
```

4. Feature arm: directly after the permanent-head block's last line (`return refuse("merge", permanent)`) and before the comment `# A declared integration branch is deliberately exempt from the`, insert:

```python
    problem = mergeability_problem(pr_facts, base, head_commit)
    if problem is not None:
        return refuse("merge", problem)
```

5. Release arm: the call becomes `validate_release_merge(pr_facts, base, integration_base, head_commit, context, compiled)`, and the signature gains `head_commit` in the same position. Insert the same three lines as item 4 directly after `return refuse("merge", f"--delete-branch {omitted}")` and before the rollup predicate's `try:`.

6. `tests/test_claude_permission_guard.py`: the fake `gh`'s field-list line becomes `    and argv[6] == "state,baseRefName,headRefName,headRefOid,mergeStateStatus,url,statusCheckRollup"` (D9: it changes in the same step as the guard's).

7. `home/common/claude-code/README.md`, `## Adjudicated verbs`:
   - In the merge clause, replace `whose spelling alone the guard checks (gh hands it to GitHub, which refuses the merge atomically if the PR head differs; issue 402)` with `(issue 402) that must also be the PR's head commit (the mergeability check below, issue 476)`.
   - Insert one new paragraph between the paragraph ending `from which the guard suite fills and runs every form a refusal prints.` and the paragraph beginning `A refusal that lies in the command's text`. Its text is exactly:

     The **mergeability check** (issue 476) reads two more facts from the same PR lookup, whose `--json` field list is `state,baseRefName,headRefName,headRefOid,mergeStateStatus,url,statusCheckRollup`. Each merge arm runs it after its own shape judgment (the feature arm's permanent-head refusal, the release arm's integration-into-default check) and before its first gate (the feature arm's integration-base exemption and protection lookup, the release arm's rollup predicate), so a PR merged onto a declared integration base meets it before the exemption. A `mergeStateStatus` of exactly `BEHIND` is refused first, as `unsafe merge: the PR is behind its base <base>; repair: sync the branch with <base>, push it and wait for its required checks before merging`; then, only when the command carries `--match-head-commit`, a value other than the PR's `headRefOid` is refused as `unsafe merge: --match-head-commit <given> is not the PR head commit <headRefOid>; merge only a head you reviewed`. Any other non-empty merge state passes, `UNKNOWN`, `BLOCKED`, `DIRTY` and `UNSTABLE` included, and the check reads no protection setting. A `mergeStateStatus` that is missing, not a string or empty is refused as `cannot read the PR merge state`, and, with the flag, a `headRefOid` that is not 40 lowercase hex characters as `cannot read the PR head commit`; without the flag `headRefOid` is neither read nor demanded. GitHub stays the authority: it still compares `--match-head-commit` atomically with the merge and enforces its own up-to-date rule, which closes the window between this check and the merge.

   - In the refusal-class paragraph's state list, replace `every PR, protection and rollup lookup or predicate failure, timeouts,` with `every PR, protection and rollup lookup or predicate failure, a PR behind its base, a `--match-head-commit` that is not the PR head, an unreadable PR merge state or head commit, timeouts,`.

- [ ] **Step 4: Verify**

Run the Guard suite with no `-k`.
Expected: `Ran 93 tests` and `OK`. That covers the 89 base tests, the adversarial table and the four new tests.

Run: `bash -c 'sect() { sed -n "/# Adversarial table\./,/# Release arm: the declared integration branch/p"; }; diff <(git show HEAD:tests/test_claude_permission_guard.py | sect) <(sect < tests/test_claude_permission_guard.py | sed "s/\"mergeStateStatus\":\"CLEAN\",//")'`
Expected: no output and exit 0. The table differs from the start commit only by D9's field.

Run: `bash -c 'set -e; if git diff -U0 -- home/common/claude-code/lifecycle_guard.py | grep -E "^\+.*(import |subprocess\.)"; then exit 1; fi; if grep -q "whose spelling alone the guard checks" home/common/claude-code/README.md; then exit 1; fi; test "$(grep -c "state,baseRefName,headRefName,headRefOid,mergeStateStatus,url,statusCheckRollup" home/common/claude-code/lifecycle_guard.py)" = 1; grep -qF "The **mergeability check** (issue 476)" home/common/claude-code/README.md'`
Expected: exit 0. That means no new import or child process, the old sentence is gone, the guard carries the new field list once, and the new paragraph is present.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(guard): refuse BEHIND merges and a wrong head commit (issue 476)" -m "<trailers>"
```
