# Task 4: Shell-text extraction helper, heredoc checks, and the two heredoc rewrites

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-release/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes from Task 2: `skill_documents()` and `SKILL_TREES`.
- Produces, for Tasks 5 and 6, these module-level names in `test_workflow_skill_contracts.py`:
  - `SHELL_FENCE_INFO: frozenset[str]` — `{"bash", "sh", "shell", "console"}`.
  - `SHELL_COMMANDS: frozenset[str]` — the known command first-words listed in Step 1.
  - `PLACEHOLDER: re.Pattern` — `re.compile(r"<[^<>\n]+>")`.
  - `HEREDOC: re.Pattern` — `re.compile(r"<<-?['\"]?[A-Za-z_][A-Za-z0-9_]*")`.
  - `def command_head(command: str) -> str` — the command's first whitespace-separated token with a leading `${VAR}` expansion and a leading `VAR=` / `VAR=$(` assignment removed.
  - `def shell_commands(text: str) -> Iterator[tuple[int, str]]` — `(line_number, command)` for every shell command a skill document shows: each non-blank, non-`#` line inside a fence whose info string is in `SHELL_FENCE_INFO`, plus each inline code span outside any fence whose `command_head` is in `SHELL_COMMANDS`.
  - `def without_placeholders(command: str) -> str` — `PLACEHOLDER.sub("", command)`.

**Invariants:**
- The extraction rule is the contract; there is no per-site exception list. If a check fires on something that is not a shell example, the fix is a more precise extraction or placeholder rule — never an allowlist (per D4).
- `command_head` normalizes the first token before the known-command lookup, because `${GH_PREFIX}gh pr list …` and `PREV=$(git describe … )` are real offenders whose raw first token is not a command name (per D16).
- All four forbidden-form checks run over placeholder-stripped text, and the heredoc pattern requires `<<` immediately followed by an optional `-`, an optional quote, and an identifier — so `<pr-num>`-style placeholders and the `<<<<` conflict markers in `ship-issue/SYNC.md` do not fire (per D17).
- The heredoc check runs over **whole documents** as well as extracted commands, because extraction alone does not reach every site: `ship-issue/SKILL.md`'s heredoc lives in a fence with no info string, which extraction deliberately does not read, while `ship-release/SKILL.md`'s lives in a ```` ```bash ```` fence and is reached by both checks (per test seam 3, D24).
- The `if grep -q <forbidden> <file>; then exit 1; fi` sentence in `writing-plans/SKILL.md` needs no change: `if` is not in `SHELL_COMMANDS`, so extraction never reaches it (per D18). Do not edit that sentence.
- Command substitution `$(…)` is out of scope and no check may forbid it (per D8).
- Both PR-body rewrites keep the body text itself intact — the same headings, the same `Closes #<num>` trailer. Only the delivery mechanism changes.

## The two heredoc rewrites

**`ship-issue/SKILL.md` — Phase 5 PR creation.** The fence currently reads
`gh pr create --base <integrationBranch> --title "<title>" --body "$(cat <<'EOF'` followed by
the body and `EOF )"`. Replace the whole fenced block, and label the new command fence `bash`
so the sweep covers it:

````markdown
Write the body to a file with the file-writing tool first, then pass it by path — a heredoc
into `gh` is one of the forms the worktree isolation checker refuses (see the `worktrees`
skill). Body template:

```markdown
## Summary
<2-4 bullets of what shipped>

## Spec
<spec-path>

## Plan
<plan-path>

Closes #<num>
```

```bash
git push -u origin <branch>
gh pr create --base <integrationBranch> --title "<title>" --body-file <pr-body-path>
```
````

**`ship-release/SKILL.md` — Phase 2 PR creation.** Replace the `--body "$(cat <<'EOF'` line
and its heredoc terminator so the existing `bash` fence becomes:

```bash
${GH_PREFIX}gh pr create \
  --base <default> \
  --head <integration> \
  --title "<merge subject seed from Phase 1>" \
  --body-file <release-body-path>
```

Add one sentence above the fence: the Phase 1 body is written to `<release-body-path>` with
the file-writing tool and passed by path, because a heredoc into `gh` is refused by the
worktree isolation checker.

- [ ] **Step 1: Write the failing test**

Add the module-level machinery beside `skill_documents()`, then the test as a method of
`WorkflowSkillContractsTest`.

```python
SHELL_FENCE_INFO = frozenset({"bash", "sh", "shell", "console"})
# First words that mark an inline code span as a shell command rather than prose.
SHELL_COMMANDS = frozenset({
    "artifact-budget", "cat", "cd", "cp", "env", "gh", "git", "glab", "grep",
    "just", "ls", "mkdir", "mv", "node", "npm", "python3", "railway", "rm",
    "sed", "unset",
})
PLACEHOLDER = re.compile(r"<[^<>\n]+>")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
HEREDOC = re.compile(r"<<-?['\"]?[A-Za-z_][A-Za-z0-9_]*")


def command_head(command):
    tokens = command.split()
    if not tokens:
        return ""
    head = re.sub(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}", "", tokens[0])
    return re.sub(r"^[A-Za-z_][A-Za-z0-9_]*=\$?\(?", "", head)


def shell_commands(text):
    info = None
    for line_number, line in enumerate(text.splitlines(), 1):
        if line.startswith("```"):
            info = None if info is not None else line[3:].strip()
            continue
        if info is not None:
            if info in SHELL_FENCE_INFO:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    yield line_number, stripped
            continue
        for span in INLINE_CODE.findall(line):
            candidate = span.strip()
            if candidate and command_head(candidate) in SHELL_COMMANDS:
                yield line_number, candidate


def without_placeholders(command):
    return PLACEHOLDER.sub("", command)
```

```python
    def test_skill_documents_show_no_heredoc(self):
        for path, text in skill_documents():
            relative = path.relative_to(REPO_ROOT)
            for line_number, line in enumerate(text.splitlines(), 1):
                match = HEREDOC.search(without_placeholders(line))
                if match is None:
                    continue
                with self.subTest(path=f"{relative}:{line_number}"):
                    self.fail(
                        f"heredoc {match.group(0)!r} shown in a skill document; "
                        "write the body with the file-writing tool and pass it "
                        "by path instead"
                    )

    def test_skill_shell_examples_use_no_heredoc(self):
        for path, text in skill_documents():
            relative = path.relative_to(REPO_ROOT)
            for line_number, command in shell_commands(text):
                with self.subTest(path=f"{relative}:{line_number}"):
                    self.assertIsNone(
                        HEREDOC.search(without_placeholders(command)),
                        f"heredoc in shell example: {command}",
                    )
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `just agent-workflow-tests`

Expected: FAIL. `test_skill_documents_show_no_heredoc` reports exactly two `subTest`
failures, one at `home/common/agent-skills/skills/ship-issue/SKILL.md:119` and one at
`home/common/agent-skills/skills/ship-release/SKILL.md:117` (line numbers shift if earlier
tasks changed those files above those points — the paths are the contract, not the
numbers). `test_skill_shell_examples_use_no_heredoc` reports exactly **one** `subTest`
failure, at `home/common/agent-skills/skills/ship-release/SKILL.md:117`. The two heredoc
sites are asymmetric, and the plan's earlier claim that both escape extraction was wrong:
`ship-release/SKILL.md`'s heredoc sits inside a fence opened ```` ```bash ```` (line 112),
which **is** in `SHELL_FENCE_INFO`, so extraction reads it and the shell-example check
fires too; `ship-issue/SKILL.md`'s heredoc sits inside a bare fence (opened line 117),
which extraction deliberately does not read, so only the whole-document check catches it.
That single site is why the whole-document check exists — it is the only check covering
the `ship-issue` heredoc — and both checks go green together in Step 3, which rewrites
both sites (per D24).

If `test_skill_documents_show_no_heredoc` reports a third failure, read that site before
touching it: `ship-issue/SYNC.md` mentions `<<<<` conflict markers in prose and must **not**
fire. A failure there means the `HEREDOC` pattern is too loose and the pattern — not the
prose — is what to fix (per D17).

- [ ] **Step 3: Apply the two rewrites**

Read each file before editing it, then apply the two rewrites above verbatim.

- [ ] **Step 4: Verify**

Run: `just agent-workflow-tests`

Expected: PASS — both new tests green and every pre-existing test still green.

Then confirm the extraction helper actually reaches the newly labelled fence, so Tasks 5
and 6 inherit working machinery rather than a helper that silently yields nothing:

Run: `python3 -c "import pathlib,sys; sys.path.insert(0,'home/common/agent-skills/tests'); import test_workflow_skill_contracts as t; print(sum(1 for _ in t.shell_commands(pathlib.Path('home/common/agent-skills/skills/ship-issue/SKILL.md').read_text())))"`

Expected: a non-zero count. Zero means the fence label or the fence-tracking logic is wrong
and the helper is inert.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-release/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
```

```bash
git commit -m "fix(agent-skills): pass PR bodies by path and forbid heredocs in skill documents"
```
