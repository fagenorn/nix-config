# Task 2: One sealed-member table and the pure worktree policy comparison

Decisions: D4, D5, D9 (runtime-facade seam, digest check). Spec §3
"Sealed-policy comparison". Work from the worktree root. Every shell block
starts with `set -euo pipefail` (`set -uo pipefail` in a
watch-it-fail step) and these abbreviations, which the blocks below
omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
```

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow_delivery_build.py` (module
  docstring, a new table and accessor after `_policy_member`, `_build_contract`'s
  `facts` and provenance `policy`, and a new `DeliveryBuilder` method)
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py` (one forwarding
  method on `DeliveryRuntime`)
- Test: `home/common/agent-skills/tests/test_workflow_delivery.py` (one helper and
  one new class)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (one
  `DeliveryBuilderTest` method)

**Interfaces:**
- Consumes: the existing `_policy_member(policy, path, kind)`. It refuses with
  `ValueError("policy member missing: <path>")` or
  `ValueError("policy member mistyped: <path>")`. Also the existing `_refuse`.
- Produces (build module):
  - `_SEALED_POLICY: tuple[tuple[str, str, type], ...]`, the seven rows of
    (provenance key, snapshot path, type).
  - `_sealed_policy(policy: object) -> dict[str, Any]`.
  - `DeliveryBuilder.check_worktree_policy(self, repo_root_policy: object, worktree_policy: object) -> None`.
- Produces (runtime): `DeliveryRuntime.check_worktree_policy(self, repo_root_policy: dict[str, Any], worktree_policy: dict[str, Any]) -> None`.
  It returns `None` when the sealed members agree and raises `ValueError`
  otherwise. Task 3 calls it and wraps the message as
  `build-delivery refused: <message>`.

**Invariants:**
- Contract output bytes do not change for any input and snapshot. That includes
  the provenance digest's `policy` object, which keeps the same seven keys and
  values (spec §3).
- The first missing or mistyped member refuses first, in the old literal order:
  `project.id`, `bindings.tracker.kind`, `bindings.tracker.repo_slug`,
  `bindings.vcs.branch_pattern`, `bindings.vcs.worktree.prefix`,
  `bindings.vcs.integration_branch`, `bindings.vcs.merge.delete_branch`.
- Each snapshot path appears exactly once in the build module, in the table.
- `check_worktree_policy` is pure and compares only the seven members. A worktree
  member that is missing or mistyped refuses as `worktree ` plus the accessor's
  message. Differences refuse as
  `worktree policy differs from repo-root policy: <path>, <path>`, in table
  order.
- `WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION` stays `1` (D5).

- [ ] **Step 1: Write the failing tests**

In `T/test_workflow_delivery.py`, add this helper after `direct_policy`:

```python
def resolved_snapshot(root):
    """A resolver-shaped snapshot rooted at `root` with this repo's authored policy.

    The resolver makes only `paths` members and command `cwd`s absolute under
    `root`, so snapshots from two roots differ only in path-shaped members.
    """
    return {
        "schema_version": 1,
        "project": {"id": "fagenorn/nix-config", "name": "nix-config", "root": root},
        "bindings": {
            "vcs": {"kind": "git", "default_branch": "main", "integration_branch": "main",
                    "branch_pattern": "issue-<num>-<slug>",
                    "worktree": {"root": ".worktrees", "prefix": "worktree-"},
                    "commit": {"co_authored_by": True, "signed": True},
                    "merge": {"strategy": "merge", "delete_branch": True}},
            "tracker": {"kind": "github", "cli": "gh", "repo_slug": "fagenorn/nix-config",
                        "credential_env": {"unset_before_invocation": []}},
            "paths": {"artifacts": {"plans": f"{root}/.claude/plans",
                                    "specs": f"{root}/.claude/specs"},
                      "architecture": [f"{root}/CLAUDE.md"]},
            "workflow": {"orchestration": {"max_parallel": 2, "attempt_budget_minutes": 180}},
        },
        "capabilities": {},
    }
```

Add this class directly before `if __name__ == "__main__":`:

```python
class WorktreePolicyCheckTest(unittest.TestCase):
    """D4, D9: the pure sealed-policy comparison behind the worktree cross-check."""

    @classmethod
    def setUpClass(cls):
        cls.runtime = runpy.run_path(str(ENTRY))["DeliveryRuntime"](
            notes_max_characters=10_000)

    def refusal(self, worktree_policy):
        with self.assertRaises(ValueError) as caught:
            self.runtime.check_worktree_policy(resolved_snapshot("/repo"), worktree_policy)
        return str(caught.exception)

    def test_equal_sealed_members_pass_whatever_the_root_and_unsealed_policy(self):
        worktree = resolved_snapshot("/repo/.worktrees/worktree-issue-181-x")
        worktree["bindings"]["workflow"]["orchestration"]["max_parallel"] = 5
        self.assertIsNone(
            self.runtime.check_worktree_policy(resolved_snapshot("/repo"), worktree))

    def test_differing_members_are_named_in_table_order(self):
        worktree = resolved_snapshot("/wt")
        worktree["bindings"]["vcs"]["merge"]["delete_branch"] = False
        worktree["bindings"]["vcs"]["integration_branch"] = "dev"
        self.assertEqual(self.refusal(worktree),
                         "worktree policy differs from repo-root policy: "
                         "bindings.vcs.integration_branch, bindings.vcs.merge.delete_branch")

    def test_a_missing_or_mistyped_worktree_member_refuses_with_the_worktree_prefix(self):
        missing = resolved_snapshot("/wt")
        del missing["bindings"]["tracker"]["repo_slug"]
        mistyped = resolved_snapshot("/wt")
        mistyped["bindings"]["vcs"]["merge"]["delete_branch"] = "true"
        for worktree, message in (
                (missing, "worktree policy member missing: bindings.tracker.repo_slug"),
                (mistyped, "worktree policy member mistyped: bindings.vcs.merge.delete_branch")):
            with self.subTest(message=message):
                self.assertEqual(self.refusal(worktree), message)
```

In `T/test_delivery_workflow.py`, add this method to `class DeliveryBuilderTest`
directly after `test_contract_is_deterministic_policy_derived_and_valid`. It
recomputes #171's provenance digest from the seven authored members, written
out here independently of the table. It passes at the base commit, and it must
still pass after the refactor (D9):

```python
    def test_provenance_digest_seals_the_seven_authored_policy_members(self):
        self.project()
        value = self.contract_input()
        contract = self.build("contract", value)["contract"]
        authored = source_contract()
        vcs, tracker = authored["bindings"]["vcs"], authored["bindings"]["tracker"]
        self.assertEqual(contract["provenance"]["digest"], self.model.canonical_digest({
            "policy": {"project_id": authored["project"]["id"],
                       "tracker_kind": tracker["kind"],
                       "repository_slug": tracker["repo_slug"],
                       "branch_pattern": vcs["branch_pattern"],
                       "worktree_prefix": vcs["worktree"]["prefix"],
                       "integration_branch": vcs["integration_branch"],
                       "delete_branch": vcs["merge"]["delete_branch"]},
            "issue": 171, "worktree": self.worktree,
            "source": {"kind": value["source_kind"], "reference": value["source_reference"]}}))
```

- [ ] **Step 2: Run the tests and watch the facade tests fail**

```bash
PYTHONPATH=python python3 -m unittest $T/test_workflow_delivery.py -k WorktreePolicyCheckTest 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py -k test_provenance_digest_seals 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
```

Expected: the first run gives `Ran 3 tests` and `FAILED (errors=4)`, since each subtest counts, because
`DeliveryRuntime` has no `check_worktree_policy`. The second gives `Ran 1 test`
and `OK`, since it is the characterization pin.

- [ ] **Step 3: Implement the table, the accessor and the comparison**

In `S/workflow_delivery_build.py`, add the following directly after
`_policy_member`. The table is written out exactly because its provenance keys
are the digest's member names:

```python
# The policy members a contract seals, in one home: (provenance key, snapshot
# path, type). Contract derivation, the provenance digest's `policy` object and
# the worktree comparison all read this table.
_SEALED_POLICY = (
    ("project_id", "project.id", str),
    ("tracker_kind", "bindings.tracker.kind", str),
    ("repository_slug", "bindings.tracker.repo_slug", str),
    ("branch_pattern", "bindings.vcs.branch_pattern", str),
    ("worktree_prefix", "bindings.vcs.worktree.prefix", str),
    ("integration_branch", "bindings.vcs.integration_branch", str),
    ("delete_branch", "bindings.vcs.merge.delete_branch", bool),
)


def _sealed_policy(policy: object) -> dict[str, Any]:
    """The sealed members by provenance key; the first bad one in table order refuses."""
    return {key: _policy_member(policy, path, kind) for key, path, kind in _SEALED_POLICY}
```

In `_build_contract`, replace the whole `facts = { ... }` literal (seven
`_policy_member` calls) with `facts = _sealed_policy(policy)`. In the provenance
digest, replace
`"policy": {name: facts[name] for name in ("project_id", …, "delete_branch")},`
with `"policy": dict(facts),`. Every later `facts[...]` read stays as it is.

Add this method to `DeliveryBuilder` directly after `build`:

```python
    def check_worktree_policy(self, repo_root_policy: object,
                              worktree_policy: object) -> None:
        """Refuse unless a worktree snapshot's sealed members equal the repo root's.

        Both snapshots pass the same typed accessor, so equal values are equal in
        type too; paths and unsealed bindings never take part (D4).
        """
        sealed = _sealed_policy(repo_root_policy)
        try:
            candidate = _sealed_policy(worktree_policy)
        except ValueError as error:
            _refuse(f"worktree {error}")
        differing = [path for key, path, _ in _SEALED_POLICY if candidate[key] != sealed[key]]
        if differing:
            _refuse("worktree policy differs from repo-root policy: " + ", ".join(differing))
```

In the module docstring, change the sentence
`workflow-state resolves project policy and hands it in; every sealed object`
`this module returns is validated again by DeliveryRuntime before it is printed.`
to:
`workflow-state resolves project policy and hands it in, and`
`` `check_worktree_policy` compares the members a contract seals across two such ``
`snapshots; every sealed object this module returns is validated again by`
`DeliveryRuntime before it is printed.`
Keep the ~84-column wrap.

In `S/workflow_delivery.py`, add this method to `DeliveryRuntime` directly
after `build_delivery`:

```python
    def check_worktree_policy(self, repo_root_policy: dict[str, Any],
                              worktree_policy: dict[str, Any]) -> None:
        """Refuse when a contract worktree's sealed policy differs from the repo root's."""
        self._builder.check_worktree_policy(repo_root_policy, worktree_policy)
```

- [ ] **Step 4: Verify**

```bash
PYTHONPATH=python python3 -m unittest $T/test_workflow_delivery.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py -k DeliveryBuilderTest 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
if grep -n '"worktree_prefix", "integration_branch", "delete_branch")' $S/workflow_delivery_build.py; then exit 1; fi
for path in project.id bindings.tracker.kind bindings.tracker.repo_slug bindings.vcs.branch_pattern \
    bindings.vcs.worktree.prefix bindings.vcs.integration_branch bindings.vcs.merge.delete_branch; do
  grep -cF "\"$path\"" $S/workflow_delivery_build.py
done | tr '\n' ' '; echo
grep -c '^WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION = 1$' $S/workflow_delivery_build.py
```

Expected: `Ran 6 tests` and `OK`, then `Ran 6 tests` and `OK`, then `OK` for
the whole delivery-workflow file. The `if grep` finds nothing, the loop prints
`1 1 1 1 1 1 1`, and the last line prints `1`. Summarize any failure to its test
ids.

- [ ] **Step 5: Commit**

```bash
git add $S/workflow_delivery_build.py $S/workflow_delivery.py $T/test_workflow_delivery.py $T/test_delivery_workflow.py
git commit -m "feat(delivery-build): seal policy from one table and compare worktree policy" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
