# Task 1: The contract member `bindings.vcs.merge.required_checks`

Spec § The contract member. Rests on D1. After this task the resolver accepts the optional member, refuses each malformed value with its pointer and repair id, and passes a valid value through the snapshot unchanged. Nothing reads the member yet (Task 2 copies it into the derived row).

**Files:**
- Modify: `python/agent_tools/resolve_project.py` (the vcs constants beside `VCS_MEMBERS`, `validate_vcs`, a new `validate_required_checks`)
- Test: `home/common/agent-skills/tests/test_resolve_project.py` (a new `RequiredChecksTest` class)
- Modify: `python/README.md` (§ guard-policy, one new paragraph)

**Interfaces:**
- Consumes (unchanged): `check_exact_members(value, pointer, expected, section, violations, *, optional=())`, `check_list`, `check_string`, `violation(pointer, message, repair_id)`; in the tests `ResolverTestCase.resolve`, `assert_refusal`, `make_root`, `source_contract()`.
- Produces: `MERGE_MEMBERS = ("strategy", "delete_branch")`, `MERGE_OPTIONAL_MEMBERS = ("required_checks",)` and `validate_required_checks(merge: dict, violations: list[dict]) -> None` in `resolve_project`. Task 2 reads the member from the resolved snapshot as `bindings.vcs.merge.get("required_checks")`.

**Invariants:**
- An absent member and `null` both resolve, and the resolver never inserts the member: absent stays absent and `null` stays `null` in the snapshot. The project schema version stays 1.
- A present, non-null value is a non-empty list of distinct non-empty strings. No character is restricted and the list is neither sorted nor rewritten (`normalize_bindings` is untouched).
- Violations, all in section `vcs`: not a list is `contract.vcs.not_list` at `/bindings/vcs/merge/required_checks`; `[]` is `contract.vcs.empty_required_checks` at the same pointer; an entry that is not a non-empty string is `contract.vcs.not_string` at `/bindings/vcs/merge/required_checks/<i>`; a repeated string is `contract.vcs.duplicate_required_check` at the second occurrence's pointer. Duplicates are judged among the non-empty string entries only, so a non-string entry is reported once, as `not_string`.
- Any other member of `bindings.vcs.merge` is still `contract.vcs.member_unexpected`.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_resolve_project.py`, insert this class directly before `class PublicResolveTest(InProcessTestCase):`:

```python
class RequiredChecksTest(ResolverTestCase):
    """Issue 552 D1: the optional `bindings.vcs.merge.required_checks` member."""

    POINTER = "/bindings/vcs/merge/required_checks"
    ABSENT = object()
    MERGE = {"strategy": "merge", "delete_branch": True}

    def contract_with(self, checks):
        contract = source_contract()
        merge = contract["bindings"]["vcs"]["merge"]
        merge.pop("required_checks", None)
        if checks is not self.ABSENT:
            merge["required_checks"] = checks
        return contract

    def resolved_merge(self, checks):
        code, snap, err = self.resolve(self.make_root(self.contract_with(checks)))
        self.assertEqual(code, 0, err)
        return snap["bindings"]["vcs"]["merge"]

    def test_a_valid_list_round_trips_unchanged(self):
        for checks in (["memory foundation (unit + forced checks)"],
                       ["lint", "CI / build", "Nix Eval"], ["café ✓", "a\tb"]):
            with self.subTest(checks=checks):
                # Passed through as authored: neither sorted nor restricted (D1).
                self.assertEqual(self.resolved_merge(checks),
                                 {**self.MERGE, "required_checks": checks})

    def test_an_absent_member_stays_absent(self):
        self.assertEqual(self.resolved_merge(self.ABSENT), self.MERGE)

    def test_null_stays_null(self):
        self.assertEqual(self.resolved_merge(None), {**self.MERGE, "required_checks": None})

    REFUSALS = (
        # (member, pointer suffixes in order, the error's repair id); suffixes are
        # rooted at POINTER, and the error carries the first violation's repair id.
        ("CI", [""], "contract.vcs.not_list"),
        ({"CI": True}, [""], "contract.vcs.not_list"),
        ([], [""], "contract.vcs.empty_required_checks"),
        (["CI", ""], ["/1"], "contract.vcs.not_string"),
        (["CI", 7], ["/1"], "contract.vcs.not_string"),
        ([None], ["/0"], "contract.vcs.not_string"),
        (["CI", "lint", "CI"], ["/2"], "contract.vcs.duplicate_required_check"),
        (["CI", 7, 7, "CI"], ["/1", "/2", "/3"], "contract.vcs.not_string"),
    )

    def test_each_malformed_member_is_refused_with_its_pointer(self):
        for checks, suffixes, repair_id in self.REFUSALS:
            with self.subTest(checks=checks):
                code, payload, _ = self.resolve(self.make_root(self.contract_with(checks)))
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertEqual(error["repair_id"], repair_id)
                self.assertEqual([v["pointer"] for v in error["violations"]],
                                 [self.POINTER + suffix for suffix in suffixes])
                self.assertTrue(all(v["message"] for v in error["violations"]))

    def test_any_other_merge_member_is_still_unexpected(self):
        contract = self.contract_with(self.ABSENT)
        contract["bindings"]["vcs"]["merge"]["required_check"] = ["CI"]
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual(error["repair_id"], "contract.vcs.member_unexpected")
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/bindings/vcs/merge/required_check"])
```

The `["CI", 7, 7, "CI"]` row pins that non-strings are never duplicates: `/1` and `/2` are `not_string`, `/3` repeats `"CI"`.

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py -k RequiredChecks 2>&1 | tail -4'`
Expected: FAIL. The valid-list and null cases exit 2 with `contract.vcs.member_unexpected`, and the refusal rows report `member_unexpected` instead of their repair ids. `test_an_absent_member_stays_absent` and `test_any_other_merge_member_is_still_unexpected` already pass.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/resolve_project.py`:

1. Directly after the `VCS_MEMBERS` tuple, add the two constants with this comment:

```python
MERGE_MEMBERS = ("strategy", "delete_branch")
# Issue 552 D1: the one `vcs.merge` member an author may leave out. `null` and
# absent both mean the project declares no required checks, and the resolver
# never inserts it.
MERGE_OPTIONAL_MEMBERS = ("required_checks",)
```

2. In `validate_vcs`, the `merge` block calls `check_exact_members(merge, "/bindings/vcs/merge", MERGE_MEMBERS, "vcs", violations, optional=MERGE_OPTIONAL_MEMBERS)` in place of the literal pair, keeps its `strategy` and `delete_branch` checks, and ends with `validate_required_checks(merge, violations)`.

3. Add `validate_required_checks(merge, violations)` directly after `validate_vcs`, with the docstring `"""Issue 552 D1: the optional `bindings.vcs.merge.required_checks` member."""`. It reads `merge.get("required_checks")` and returns at once for `None`. Otherwise it runs `check_list` at the pointer and returns when that fails. For an empty list it appends `violation(pointer, "must be a non-empty list", "contract.vcs.empty_required_checks")`. Then it walks the entries in order. Each runs `check_string` at `<pointer>/<i>`, and a failing entry is skipped. A string already seen appends `violation(<pointer>/<i>, "required check is declared more than once", "contract.vcs.duplicate_required_check")`.

In `python/README.md`, insert this paragraph as the last paragraph of § guard-policy, directly before `## Ship delivery recipes` and separated by blank lines:

```markdown
`bindings.vcs.merge.required_checks` (issue 552) is an optional `resolve-project` member beside `strategy` and `delete_branch`; absent or `null` means the project declares no required checks, and the resolver never inserts it, so the project schema version stays 1. A present value is a non-empty list of distinct non-empty strings, each the exact name GitHub shows for a check (a check run's `name` or a commit status's `context`), with no character restricted. A value that is not a list is `contract.vcs.not_list`, an empty list `contract.vcs.empty_required_checks`, an entry that is not a non-empty string `contract.vcs.not_string` at that entry's pointer, and a repeated entry `contract.vcs.duplicate_required_check` at its second occurrence's pointer. The snapshot passes the member through unchanged.
```

- [ ] **Step 4: Verify**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py 2>&1 | tail -4'`
Expected: PASS, `OK`. The whole resolver suite stays green, because the committed contract declares no required checks.

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -4'`
Expected: PASS, `OK`. The derivation still ignores the member.

Run: `if grep -q '"required_checks"' .agents/project.json; then exit 1; fi`
Expected: exit 0. Out of scope: nix-config's own contract declares no checks.

After `git add` of the three files, run the Build (root § Global Constraints, timeout 3600 s). Expected: it ends without an error line, which shows that `resolve_project` still imports in the built `agent_tools` environment.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/resolve_project.py home/common/agent-skills/tests/test_resolve_project.py python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(issue-552/T1): declare required checks in the project contract" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":1,"records":[{"bounds":[{"added_lines":40,"boundary":"all","deleted_lines":4,"record_bytes":8192,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1a","last_task":1,"owner":1,"path":"python/agent_tools/resolve_project.py"},{"bounds":[{"added_lines":90,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1b","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_resolve_project.py"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":0,"record_bytes":11264,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":2,"owner":1,"path":"python/README.md"}]}}
```
