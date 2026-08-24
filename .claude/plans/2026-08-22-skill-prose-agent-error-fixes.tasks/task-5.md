# Task 5: Chain-operator check and every chain rewrite

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/bindings.md`
- Modify: `home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SYNC.md`
- Modify: `home/common/agent-skills/skills/ship-release/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes from Task 2: `skill_documents()`. From Task 4: `shell_commands()`, `without_placeholders()`, `command_head()`.
- Produces: `CHAIN: re.Pattern` — `re.compile(r"&&|\|\||;")`, module-level. Task 6 does not import it; its pipe check removes `||` from a command itself so a chain operator is reported only by this task's check.

**Invariants:**
- No shell command shown in a discovered skill document contains `&&`, `||`, or `;` after placeholder stripping (per D4).
- The `unset GITHUB_TOKEN &&` prefix becomes `env -u GITHUB_TOKEN` — a single invocation carrying the same per-call environment change. It does **not** become two calls, which would lose the effect, and it does **not** become `GITHUB_TOKEN= gh …`, which sets an empty token that `gh` reads as a credential (per D20).
- Two sites are rewritten for **meaning**, not stripped mechanically (per D10):
  - the release pre-flight's `|| true` exists so a no-tags repository survives `set -e`; the replacement prose must still tell the reader what to do with a non-zero exit;
  - the tag-existence pre-check's `git remote get-url origin >/dev/null 2>&1 &&` guard exists so a fetch is skipped when there is no remote; the replacement must still say the fetch is conditional.
- `writing-plans/SKILL.md`'s `if grep -q <forbidden> <file>; then exit 1; fi` sentence is **not** edited: it is not extracted, because `if` is not in `SHELL_COMMANDS` (per D18). Removing it would destroy the gate-writing instruction it exists to teach.
- Pipes and redirects on the same lines are Task 6's, except where a rewrite here removes them as a side effect — `ship-release/SKILL.md`'s tag-existence fence loses both its chain and its `>/dev/null 2>&1` in one edit, and that is correct.
- No behavioural claim about the checker is added anywhere; the rules already live in the `worktrees` skill from Task 3, and these sites just stop demonstrating the refused forms.

## The rewrites

Read each file before editing it.

**`env -u GITHUB_TOKEN` in four documents.** Each currently instructs prefixing a tracker call
with `unset GITHUB_TOKEN &&`. Replace the prefix text with `env -u GITHUB_TOKEN`, keeping the
surrounding sentence's meaning and its statement that the default is off:

| File | Sentence |
|---|---|
| `from-issue/bindings.md` | "prefix *every* `<tracker-cli>` call … with `unset GITHUB_TOKEN &&`" |
| `from-issue/REVIEW-CONTRACT.md` | "prefix with `unset GITHUB_TOKEN &&` only if `unsetGithubToken` is true" |
| `ship-issue/SKILL.md` | "prefix every `gh` call with `unset GITHUB_TOKEN &&`" |
| `ship-release/SKILL.md` | "`GH_PREFIX` below means `unset GITHUB_TOKEN && ` when `unsetGithubToken` is true, else nothing" |

For `ship-release/SKILL.md` the replacement is `` `env -u GITHUB_TOKEN ` `` — keep the trailing
space inside the span, because `GH_PREFIX` is concatenated directly onto the command that
follows it throughout that document.

**`ship-issue/SYNC.md`** — the `.claude/settings.json` row of the generated-file table. Replace
`` `git restore --staged .claude/settings.json && git checkout HEAD -- .claude/settings.json` ``
with two spans and a connector: `` `git restore --staged .claude/settings.json`, then
`git checkout HEAD -- .claude/settings.json` ``.

**`ship-release/SKILL.md`** — four chained `git` examples:

- The `issueTracker.kind == "none"` paragraph: `git checkout <default> && git merge --no-ff <integration>` becomes "check out `<default>`, then `git merge --no-ff <integration>`".
- Pre-flight step 3, the single-branch parenthesis: drop `2>/dev/null || true` from `PREV=$(git describe --tags --abbrev=0 origin/<default>)` and replace the `|| true` explanation with prose that keeps the `set -e` reasoning — the command exits non-zero in a no-tags repository (the first release), so capture its status and treat the failure as an empty `PREV` instead of letting it abort. Keep the existing sentence about why the explicit ref matters and the following `git log ${PREV:+$PREV..}origin/<default> --oneline` check unchanged.
- Pre-flight step 6, local-behind: `git checkout <integration> && git merge --ff-only origin/<integration>` becomes "`git checkout <integration>` followed by `git merge --ff-only origin/<integration>`".
- Phase 4 verification: "Don't `git push origin <default>` or `git checkout <default> && git merge`" becomes "Don't `git push origin <default>`, and don't check out `<default>` to merge it locally".
- The 4.5b tag-existence `bash` fence becomes:

```bash
# a remote? fetch tags first, so a tag pushed by a crashed session is visible
git remote get-url origin
git fetch --tags --quiet origin
EXISTING=$(git tag --points-at "$MERGE_SHA" 'v[0-9]*')
```

  and the sentence below the fence gains: skip the fetch when the first command reports no
  remote.

- [ ] **Step 1: Write the failing test**

Add `CHAIN` at module level beside the Task 4 patterns, then the test as a method of
`WorkflowSkillContractsTest`.

```python
CHAIN = re.compile(r"&&|\|\||;")
```

```python
    def test_skill_shell_examples_use_no_chain_operator(self):
        for path, text in skill_documents():
            relative = path.relative_to(REPO_ROOT)
            for line_number, command in shell_commands(text):
                with self.subTest(path=f"{relative}:{line_number}"):
                    self.assertIsNone(
                        CHAIN.search(without_placeholders(command)),
                        f"chain operator in shell example: {command} — run one "
                        "command per call and make a dependent step a second call",
                    )
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `just agent-workflow-tests`

Expected: FAIL, with one `subTest` failure per site listed above — the four
`unset GITHUB_TOKEN &&` prefixes, the `SYNC.md` table row, and the five `ship-release/SKILL.md`
sites (four chained `git` examples plus `|| true`). Each failure message quotes the offending
command.

`writing-plans/SKILL.md` must **not** appear among the failures. If it does, `command_head`
or `SHELL_COMMANDS` from Task 4 is treating `if` as a command; fix the extraction rule, never
the sentence, and never add an exception list (per D4, D18).

Any failure at a site not listed above is a genuine find or an extraction imprecision — judge
which by reading it. A real shell example gets rewritten by the same rule; a false positive
means `SHELL_COMMANDS`, `command_head` or `PLACEHOLDER` needs tightening.

- [ ] **Step 3: Apply the rewrites**

Make exactly the changes above. Do not touch the pipes at `ship-release/SKILL.md`'s
pre-flight steps 3 and 6 or its adapter fence — those are Task 6's, and the chain check does
not fail on them.

- [ ] **Step 4: Verify**

Run: `just agent-workflow-tests`

Expected: PASS — the new test green and every pre-existing test still green.

Then confirm no chained prefix survived anywhere in either skill tree:

Run: `grep -rn "unset GITHUB_TOKEN" home/common/agent-skills/skills home/common/claude-code/skills --include=*.md`

Expected: no output. Any line printed is this task incomplete.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/bindings.md home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/SYNC.md home/common/agent-skills/skills/ship-release/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
```

```bash
git commit -m "fix(agent-skills): drop chain operators from every shell example"
```
