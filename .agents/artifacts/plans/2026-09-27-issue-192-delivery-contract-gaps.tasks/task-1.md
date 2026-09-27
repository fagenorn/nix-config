# Task 1: The builder takes a live branch for a worktree name that is not an issue branch

Spec §1–§2, per D2, D3, D4, D19, D23. The builder stays pure: it never reads git.
It is handed the live branch through a keyword, and Task 2 wires the probe.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow_delivery_build.py`
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py`
- Test: `home/common/agent-skills/tests/test_workflow_delivery.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (Tasks 2 and 5 rely on these exact names):
  - `DeliveryBuilder.build(kind, value, *, policy, installed_intent=None, worktree_branch=None)`.
    Only kind `contract` reads `worktree_branch`.
  - `DeliveryBuilder.requires_worktree_branch(value: object, policy: object) -> bool`
  - `DeliveryBuilder.worktree_pattern_refusal(worktree: str, clause: str | None = None) -> str`
    (a `@staticmethod`)
  - `DeliveryRuntime.build_delivery(kind, value, *, policy, installed_intent=None, worktree_branch=None)`
  - `DeliveryRuntime.requires_worktree_branch(value, policy) -> bool` and
    `DeliveryRuntime.worktree_pattern_refusal(worktree, clause=None) -> str`, both
    plain forwards to the builder, like `requires_installed_intent`.

**Invariants:**
- Rule 1: when the regex accepts the worktree path's final component, the
  contract is byte-identical to base, and `worktree_branch` is ignored.
- Rule 2: only otherwise, and only when `worktree_branch` is a string the same
  regex accepts, the contract's branch is `worktree_branch`. The provenance
  digest input then gains `"branch": worktree_branch`. The slot's
  `constraints.branch`, `delete_remote_branch` and `delete_local_branch` take
  that branch, and `remove_worktree` keeps the input path.
- The regex is built in exactly one place. It is the binding's pattern, with
  `<num>` the decimal issue and `<slug>` `[a-z0-9][a-z0-9-]*`, and the worktree
  prefix optional.
- `requires_worktree_branch` is true only for an input the contract build would
  accept up to the pattern check (closed keys, types, source kind, an absolute
  normalized worktree, well-typed sealed policy, a `github` tracker) whose final
  component the regex rejects. Every other input answers false, whatever it
  raises.
- `worktree_pattern_refusal(w)` is exactly
  `worktree name '<final component of w>' does not match the issue branch pattern`,
  and with a clause it is that text plus `, and <clause>`.

- [ ] **Step 1: Write the failing tests**

Append this class to `home/common/agent-skills/tests/test_workflow_delivery.py`,
before the `if __name__ == "__main__":` block. It reuses the module's `ENTRY`,
`NOW`, `resolved_snapshot`, `copy` and `runpy`.

```python
LEGACY = "/repo/.worktrees/worktree-issue-154"
LIVE = "worktree-issue-154-shell-checker-examples"


def sealed_members(snapshot):
    """The seven policy members a contract seals, keyed as its provenance digest keys them."""
    vcs, tracker = snapshot["bindings"]["vcs"], snapshot["bindings"]["tracker"]
    return {"project_id": snapshot["project"]["id"], "tracker_kind": tracker["kind"],
            "repository_slug": tracker["repo_slug"], "branch_pattern": vcs["branch_pattern"],
            "worktree_prefix": vcs["worktree"]["prefix"],
            "integration_branch": vcs["integration_branch"],
            "delete_branch": vcs["merge"]["delete_branch"]}


class WorktreeBranchTest(unittest.TestCase):
    """#192 D2-D4, D19: a live branch names the contract only where the path cannot."""

    SOURCE = {"kind": "explicit_user", "reference": "invocation:/from-issue 154 --auto"}

    @classmethod
    def setUpClass(cls):
        cls.runtime = runpy.run_path(str(ENTRY))["DeliveryRuntime"](
            notes_max_characters=10_000)
        cls.policy = resolved_snapshot("/repo")

    def value(self, worktree=LEGACY, **changes):
        return {"issue": 154, "worktree": worktree, "source_kind": self.SOURCE["kind"],
                "source_reference": self.SOURCE["reference"], "now": NOW, **changes}

    def build(self, value, worktree_branch=None):
        return self.runtime.build_delivery("contract", value, policy=self.policy,
                                           worktree_branch=worktree_branch)

    def refusal(self, value, worktree_branch=None):
        with self.assertRaises(ValueError) as caught:
            self.build(value, worktree_branch)
        return str(caught.exception)

    def digest(self, worktree, **branch):
        return self.runtime.model.canonical_digest({
            "policy": sealed_members(self.policy), "issue": 154, "worktree": worktree,
            "source": self.SOURCE, **branch})

    def test_only_a_well_formed_unpatterned_input_requires_a_worktree_branch(self):
        gitlab = copy.deepcopy(self.policy)
        gitlab["bindings"]["tracker"]["kind"] = "gitlab"
        unslugged = copy.deepcopy(self.policy)
        del unslugged["bindings"]["tracker"]["repo_slug"]
        for label, value, policy, expected in (
                ("slugless", self.value(), self.policy, True),
                ("another issue's branch",
                 self.value("/repo/.worktrees/worktree-issue-155-other"), self.policy, True),
                ("patterned", self.value(f"/repo/.worktrees/{LIVE}"), self.policy, False),
                ("patterned without the prefix",
                 self.value("/repo/.worktrees/issue-154-shell"), self.policy, False),
                ("relative", self.value(".worktrees/worktree-issue-154"), self.policy, False),
                ("unnormalized", self.value("/repo/.worktrees/../worktree-issue-154"),
                 self.policy, False),
                ("unknown key", self.value(extra=True), self.policy, False),
                ("unsourced kind", self.value(source_kind="parent_handoff"), self.policy,
                 False),
                ("bad clock", self.value(now="today"), self.policy, False),
                ("not an object", "contract", self.policy, False),
                ("no policy", self.value(), None, False),
                ("non-github tracker", self.value(), gitlab, False),
                ("missing sealed member", self.value(), unslugged, False)):
            with self.subTest(label=label):
                self.assertIs(self.runtime.requires_worktree_branch(value, policy), expected)

    def test_a_live_branch_names_the_contract_and_enters_its_provenance(self):
        built = self.build(self.value(), LIVE)
        contract = built["contract"]
        literals = {stage["id"]: stage["target_ref"].get("value")
                    for stage in contract["stages"]}
        self.assertEqual({stage["target_ref"]["constraints"]["branch"]
                          for stage in contract["stages"]
                          if stage["target_ref"]["kind"] == "slot"}, {LIVE})
        self.assertEqual((literals["delete_remote_branch"], literals["delete_local_branch"],
                          literals["remove_worktree"]), (LIVE, LIVE, LEGACY))
        self.assertEqual(contract["provenance"]["digest"], self.digest(LEGACY, branch=LIVE))
        # Re-derivation reads the branch from the contract, never from the path.
        self.assertEqual(self.runtime.build_delivery(
            "initial-intent", {"contract": contract}, policy=None), built["initial_intent"])

    def test_a_patterned_name_wins_and_ignores_the_worktree_branch(self):
        patterned = self.value(f"/repo/.worktrees/{LIVE}")
        plain = self.build(patterned)
        self.assertEqual(
            self.runtime.model.canonical_bytes(
                self.build(patterned, "worktree-issue-154-elsewhere")),
            self.runtime.model.canonical_bytes(plain))
        self.assertEqual(plain["contract"]["provenance"]["digest"],
                         self.digest(f"/repo/.worktrees/{LIVE}"))

    def test_refusals_keep_the_pattern_prefix_and_name_their_reason(self):
        prefix = "worktree name 'worktree-issue-154' does not match the issue branch pattern"
        self.assertEqual(self.refusal(self.value()), prefix)
        for branch in ("feature-x", "worktree-issue-155-other"):
            with self.subTest(branch=branch):
                self.assertEqual(
                    self.refusal(self.value(), branch),
                    f"{prefix}, and its checked-out branch {branch!r} does not match either")
        self.assertEqual(self.runtime.worktree_pattern_refusal(LEGACY), prefix)
        self.assertEqual(
            self.runtime.worktree_pattern_refusal(LEGACY, "the worktree is absent"),
            prefix + ", and the worktree is absent")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_delivery.py -k WorktreeBranchTest`
Expected: `FAILED (errors=4)`. The errors are `AttributeError` (no
`requires_worktree_branch` or `worktree_pattern_refusal`) and `TypeError`
(an unexpected keyword argument `worktree_branch`).

- [ ] **Step 3: Implement rule 2 in the builder**

In `workflow_delivery_build.py`:

1. Extract the contract build's input checks into one module-level function.
   Its refusals, and their order, are the current `_build_contract`'s own. It is
   the one home of the regex (§1):

   ```python
   def _contract_input(value: object, policy: object
                       ) -> tuple[int, str, dict[str, Any], re.Pattern[str]]:
       """Check one contract input and derive its issue branch regex (#192 §1).

       The regex is the binding's pattern with `<num>` the decimal issue and
       `<slug>` `[a-z0-9][a-z0-9-]*`, and the worktree prefix optional. The
       refusals, in order, are the contract build's own.
       """
   ```

   It returns `(issue, worktree, facts, branch_regex)`, where `facts` is
   `_sealed_policy(policy)`. The body is the current checks, moved unchanged:
   `_closed(value, _CONTRACT_INPUT)`, the mistyped-input check, the source-kind
   check, the absolute-and-normalized check, `_sealed_policy`, and the `github`
   check. Then it returns
   `re.compile(f"(?:{re.escape(facts['worktree_prefix'])})?{pattern}")`, where
   `pattern` is today's join.

2. Add the refusal composer:

   ```python
   @staticmethod
   def worktree_pattern_refusal(worktree: str, clause: str | None = None) -> str:
       """The kept pattern refusal for ``worktree``, plus ``, and <clause>`` (#192 D19)."""
   ```

   It returns
   `f"worktree name {PurePosixPath(worktree).name!r} does not match the issue branch pattern"`,
   plus `f", and {clause}"` when `clause` is not None.

3. Add the predicate:

   ```python
   def requires_worktree_branch(self, value: object, policy: object) -> bool:
       """Whether a contract input needs the branch its live checkout has (#192 D3).

       True only for an input the build would accept up to the pattern check
       whose worktree name the issue branch regex rejects. Anything else answers
       False whatever it raises, and then meets its own refusal in ``build``.
       """
   ```

   Its body is `try: _, worktree, _, branch_regex = _contract_input(value, policy)`,
   then `except Exception: return False`, which follows `requires_installed_intent`
   (#193 D14). Then it returns
   `branch_regex.fullmatch(PurePosixPath(worktree).name) is None`.

4. `build` gains the keyword `worktree_branch: str | None = None` and passes it
   only to `self._build_contract(value, policy, worktree_branch)`.

5. `_build_contract(value, policy, worktree_branch)` starts with
   `issue, worktree, facts, branch_regex = _contract_input(value, policy)`, and
   then chooses the branch:

   ```python
   name = PurePosixPath(worktree).name
   live = None
   if branch_regex.fullmatch(name) is None:
       if worktree_branch is None:
           _refuse(self.worktree_pattern_refusal(worktree))
       if (not isinstance(worktree_branch, str)
               or branch_regex.fullmatch(worktree_branch) is None):
           _refuse(self.worktree_pattern_refusal(
               worktree,
               f"its checked-out branch {worktree_branch!r} does not match either"))
       live = worktree_branch
   branch = name if live is None else live
   ```

   Everything after is unchanged. It keeps reading `source_kind`,
   `source_reference` and `now` from `value`. The one other change is that the
   provenance digest input becomes
   `{"policy": dict(facts), "issue": issue, "worktree": worktree, "source": source}`,
   plus `"branch": live` only when `live` is not None.

6. In the module docstring, directly after the sentence that ends
   `validated again by DeliveryRuntime before it is printed.`, add this sentence:
   `The one observed input a contract takes is ``worktree_branch``: the branch a
   worktree whose name is not an issue branch has checked out, which
   workflow-state reads only when ``requires_worktree_branch`` says so.`

In `workflow_delivery.py`, `DeliveryRuntime.build_delivery` gains
`worktree_branch=None` and passes it to `self._builder.build`. Add the two
forwarding methods beside `requires_installed_intent`. Their docstrings are
`"""Whether a contract input needs the branch its live checkout has (#192 D3)."""`
and `"""The kept pattern refusal for ``worktree``, with ``clause`` appended (#192 D19)."""`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_delivery.py`
Expected: `OK`, 4 tests more than at base, no `FAIL:`/`ERROR:`.

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k DeliveryBuilderTest -k WorktreePolicyTest -k DeliveryLoopTest`
Expected: `OK`. These are unchanged tests, and they pin rule 1's byte identity
and the kept refusal texts (T3).

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow_delivery_build.py home/common/agent-skills/scripts/workflow_delivery.py home/common/agent-skills/tests/test_workflow_delivery.py
git commit -m "feat(workflow-delivery): take a legacy worktree's contract branch from its checkout (#192)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
